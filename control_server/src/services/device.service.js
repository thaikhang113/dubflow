'use strict'

/**
 * Thiết bị và device token.
 *
 * Đăng ký (`/v1/device/register`) là lần bắt tay duy nhất: app gửi
 * fingerprint, server tạo bản ghi (hoặc nhận ra máy cũ) và cấp một JWT dài
 * hạn có `fp` trong payload. Mọi request sau đó mang token đó; middleware
 * kiểm tra `fp` khớp với thiết bị còn `active` — token bị chép sang máy khác
 * vẫn dùng được, nhưng nó chỉ tiêu credit của chính ví máy gốc, nên chép
 * token không cho ai thêm gì cả.
 *
 * `tokenVersion` là công tắc thu hồi: tăng nó lên là mọi token đã cấp cho
 * máy đó hết hiệu lực ngay.
 */
const jwt = require('jsonwebtoken')

const Device = require('../models/Device')
const config = require('./config.service')
const credit = require('./credit.service')

const FINGERPRINT_RE = /^[a-f0-9]{64}$/i

function jwtSecret() {
  const s = (process.env.JWT_SECRET || '').trim()
  if (s.length < 32) throw new Error('JWT_SECRET quá ngắn (cần >= 32 ký tự)')
  return s
}

function isValidFingerprint(fp) {
  return FINGERPRINT_RE.test(String(fp || '').trim())
}

function signToken(device) {
  return jwt.sign(
    { fp: device.fingerprint, v: device.tokenVersion },
    jwtSecret(),
    { expiresIn: process.env.JWT_EXPIRES_IN || '30d', subject: String(device._id) },
  )
}

function verifyToken(token) {
  return jwt.verify(token, jwtSecret())
}

/**
 * Đăng ký hoặc nhận diện lại một thiết bị. Trả về { device, token, isNew }.
 *
 * Máy mới được tặng trial một lần — chia hai nhịp để farm trial mất mồi:
 * `trial.upfront.vox` cộng ngay, phần còn lại "chờ chín" cấp nốt khi thiết
 * bị sống đủ `trial.defer.hours` (xem maybeGrantDeferredTrial). Vì mốc là
 * fingerprint nên cài lại app không reset.
 *
 * Chống farm theo IP: quá `register.max.new.per.ip.day` thiết bị MỚI từ cùng
 * một IP trong 24h thì máy vẫn đăng ký được (người thật sau NAT không bị
 * chặn) nhưng không được tặng trial.
 */
async function registerDevice({ fingerprint, name = '', appVersion = '', ip = '' }) {
  const fp = String(fingerprint || '').trim().toLowerCase()
  if (!isValidFingerprint(fp)) {
    const err = new Error('Mã thiết bị không hợp lệ')
    err.statusCode = 400
    err.code = 'BAD_FINGERPRINT'
    throw err
  }

  const existing = await Device.findOne({ fingerprint: fp })
  const isNew = !existing
  const device = existing || new Device({
    fingerprint: fp, firstSeenAt: new Date(), createdIp: ip,
  })

  if (name) device.name = String(name).slice(0, 120)
  if (appVersion) device.appVersion = String(appVersion).slice(0, 32)
  device.lastSeenAt = new Date()
  device.lastSeenIp = ip
  await device.save()

  if (device.status === 'blocked') {
    const err = new Error(device.blockedReason
      || 'Thiết bị này đã bị khóa. Liên hệ hỗ trợ để biết thêm chi tiết.')
    err.statusCode = 403
    err.code = 'DEVICE_BLOCKED'
    throw err
  }

  if (!device.trialGranted) {
    const trial = Number(await config.get('trial.vox')) || 0
    const allowed = trial > 0 && await trialAllowedForIp(fp, ip)
    if (allowed) {
      const upfrontCfg = Number(await config.get('trial.upfront.vox'))
      const upfront = Number.isFinite(upfrontCfg)
        ? Math.max(0, Math.min(trial, Math.round(upfrontCfg))) : trial
      if (upfront > 0) {
        await credit.grant(fp, upfront, {
          type: 'trial',
          idempotencyKey: `trial-${fp}`,
          description: `Tặng ${upfront} Vox dùng thử`,
        })
      }
      device.trialDeferredVox = trial - upfront
    }
    // Đánh dấu kể cả khi trial=0 hoặc IP vượt trần: bật lại trial sau này
    // không được phép tặng ngược cho những máy đã đăng ký từ trước.
    device.trialGranted = true
    await device.save()
  }

  const fresh = await Device.findOne({ fingerprint: fp })
  return { device: fresh, token: signToken(fresh), isNew }
}

/** IP này còn suất tặng trial cho thiết bị mới không (trần 24h)? */
async function trialAllowedForIp(fp, ip) {
  const cap = Number(await config.get('register.max.new.per.ip.day')) || 0
  if (cap <= 0 || !ip) return true
  const since = new Date(Date.now() - 24 * 3600 * 1000)
  const recent = await Device.countDocuments({
    createdIp: ip,
    firstSeenAt: { $gte: since },
    fingerprint: { $ne: fp },   // không tự đếm mình
  })
  return recent < cap
}

/**
 * Cấp nốt phần trial "chờ chín" nếu tới hạn. Gọi từ các route đã xác thực
 * (/me, /balance) — thiết bị nào còn sống sau `trial.defer.hours` sẽ nhận
 * nốt phần còn lại một cách tự nhiên, không cần cron.
 *
 * An toàn gọi chồng: điều kiện `trialDeferredVox: {$gt: 0}` trong chính lệnh
 * update là khóa — hai request song song thì đúng một cái thắng, và grant
 * có idempotencyKey riêng làm lưới thứ hai.
 */
async function maybeGrantDeferredTrial(device) {
  if (!device || !device.trialDeferredVox || device.status !== 'active') return
  const deferHours = Number(await config.get('trial.defer.hours')) || 0
  const readyAt = new Date(device.firstSeenAt).getTime() + deferHours * 3600 * 1000
  if (Date.now() < readyAt) return

  const claimed = await Device.findOneAndUpdate(
    { fingerprint: device.fingerprint, trialDeferredVox: { $gt: 0 } },
    { $set: { trialDeferredVox: 0 } },
    { new: false },   // giá trị TRƯỚC update = số Vox cần cấp
  )
  if (!claimed || !claimed.trialDeferredVox) return
  try {
    await credit.grant(device.fingerprint, claimed.trialDeferredVox, {
      type: 'trial',
      idempotencyKey: `trial2-${device.fingerprint}`,
      description: `Tặng nốt ${claimed.trialDeferredVox} Vox dùng thử`,
    })
  } catch (err) {
    // Cấp hỏng thì trả nợ lại để lần đọc sau thử tiếp — không ai mất gì.
    await Device.updateOne(
      { fingerprint: device.fingerprint },
      { $set: { trialDeferredVox: claimed.trialDeferredVox } },
    )
    throw err
  }
}

/** Bản tóm tắt gửi xuống app — không có gì nhạy cảm. */
function publicView(device) {
  return {
    fingerprint: device.fingerprint,
    name: device.name,
    balance: device.balance,
    status: device.status,
    firstSeenAt: device.firstSeenAt,
  }
}

module.exports = {
  registerDevice,
  maybeGrantDeferredTrial,
  signToken,
  verifyToken,
  isValidFingerprint,
  publicView,
}
