'use strict'

/**
 * Giữ chỗ Vox (hold) — luồng wizard: hold sau ASR, commit lúc xuất video.
 *
 * Nguyên tắc tiền bạc, cùng kỷ luật với credit.service:
 *   - Tạo hold = TRỪ balance ngay đúng GIÁ CỦA CẢ LƯỢT (số segment × đơn
 *     giá, một findOneAndUpdate có điều kiện `balance >= est` — nguyên tử,
 *     không âm ví). Nhờ vậy mọi chỗ đọc balance (/me, /balance, pre-check
 *     ai.js, admin) tự nhiên đúng mà không cần biết hold tồn tại.
 *   - Giá cố định từ đó: các lượt AI bên trong `accrue()` chi phí NỘI BỘ vào
 *     hold để đối soát biên lợi nhuận — replay theo jobId là no-op nhờ điều
 *     kiện `usage.jobId $ne` — nhưng không đổi số tiền người dùng trả.
 *   - Commit = mở khóa, trung tính về tiền: không hoàn, không truy thu.
 *     Idempotent: gọi lại trả kết quả cũ kèm khóa giải mã. Sau commit, hold
 *     vẫn hấp thụ đúng MỘT lượt generate_post nếu có mua gói đăng bài —
 *     luồng wizard chạy bước đó sau khi bấm Xuất video (xem `canAbsorb`).
 *   - Không có hủy hoàn tiền. Bỏ ngang thì sweeper tự commit sau TTL — phí
 *     AI đã tiêu là đã tiêu, server không bao giờ chịu lỗ.
 *
 * Sổ cái chỉ còn MỘT dòng mỗi lượt (`hold`, âm, lúc tạo) nên tổng delta của
 * sổ luôn khớp ví; chi tiết từng lượt AI nằm trong CreditHold.usage.
 */
const crypto = require('node:crypto')

const CreditHold = require('../models/CreditHold')
const CreditLedger = require('../models/CreditLedger')
const Device = require('../models/Device')
const config = require('./config.service')
const credit = require('./credit.service')

class HoldError extends Error {
  constructor(statusCode, code, message) {
    super(message)
    this.name = 'HoldError'
    this.statusCode = statusCode
    this.code = code
  }
}

/**
 * Giá của một video `sentences` segment — nguồn sự thật duy nhất, dùng chung
 * cho `/v1/device/estimate`, lúc tạo hold và lúc chốt hold.
 *
 * Đây là công thức đóng, không phải dự đoán: số segment biết chắc ngay sau
 * ASR nên giá chốt luôn từ đó và không đổi nữa. `breakdown` chỉ để đối soát
 * nội bộ — API public trả về đúng một con số tổng.
 */
async function estimateVox(sentences, { autoTranslate = true, metadata = true } = {}) {
  const cfg = await config.getMany([
    'credit.enabled',
    'credit.cost.segment.base',
    'credit.cost.segment.autotranslate',
    'credit.cost.metadata',
  ])
  if (!cfg['credit.enabled']) return { estimated: 0, breakdown: {} }
  const n = Math.max(0, Math.round(sentences))
  const perSegment = cfg['credit.cost.segment.base']
    + (autoTranslate ? cfg['credit.cost.segment.autotranslate'] : 0)
  const breakdown = {
    segments: n,
    perSegment,
    segmentTotal: n * perSegment,
    metadata: metadata ? cfg['credit.cost.metadata'] : 0,
  }
  return { estimated: breakdown.segmentTotal + breakdown.metadata, breakdown }
}

function publicView(hold, { withKey = false } = {}) {
  return {
    holdId: hold.holdId,
    status: hold.status,
    estimatedVox: hold.estimatedVox,
    usedVox: hold.usedVox,
    usage: hold.usage || [],
    expiresAt: hold.expiresAt,
    autoCommitted: hold.autoCommitted || false,
    meta: hold.meta || {},
    ...(withKey ? { encKeyHex: hold.encKeyHex } : {}),
  }
}

/**
 * Tạo hold (hoặc trả lại hold đang active cùng holdId — resume sau crash).
 * Trả về { hold (kèm key), balance, created }.
 */
async function createHold({ fingerprint, deviceId, holdId, sentences,
  videoDurationS = 0, autoTranslate = true, metadata = true, ip = '' }) {
  if (!(await config.get('hold.enabled')) || !(await config.get('credit.enabled'))) {
    throw new HoldError(409, 'HOLD_DISABLED', 'Chế độ giữ chỗ Vox đang tắt.')
  }

  const existing = await CreditHold.findOne({ holdId }).lean()
  if (existing) {
    if (existing.fingerprint !== fingerprint) {
      throw new HoldError(403, 'HOLD_FORBIDDEN', 'Hold thuộc thiết bị khác.')
    }
    if (existing.status !== 'active') {
      throw new HoldError(409, 'HOLD_FINISHED', 'Lượt này đã chốt trước đó.')
    }
    return {
      hold: publicView(existing, { withKey: true }),
      balance: await credit.getBalance(fingerprint),
      created: false,
    }
  }

  const { estimated, breakdown } = await estimateVox(sentences, { autoTranslate, metadata })
  const ttlHours = Number(await config.get('hold.ttl.hours')) || 48
  const expiresAt = new Date(Date.now() + ttlHours * 3600 * 1000)

  // Trừ ví ngay bằng số ước tính — nguyên tử, không âm.
  const device = await Device.findOneAndUpdate(
    { fingerprint, status: 'active', balance: { $gte: estimated } },
    { $inc: { balance: -estimated } },
    { new: true },
  )
  if (!device) {
    throw Object.assign(
      new credit.InsufficientCreditError(await credit.getBalance(fingerprint), estimated),
      { statusCode: 402 },
    )
  }

  try {
    await CreditLedger.create({
      fingerprint,
      deviceId: device._id,
      delta: -estimated,
      balanceAfter: device.balance,
      type: 'hold',
      idempotencyKey: `hold-${holdId}`,
      description: `Giữ chỗ ${estimated} Vox cho lượt lồng tiếng (${sentences} segment)`,
      metadata: { holdId, sentences, ip },
    })
  } catch (err) {
    // Trùng key: một request song song vừa tạo xong hold này — hoàn phần
    // vừa trừ rồi trả về hold của người thắng.
    await Device.updateOne({ _id: device._id }, { $inc: { balance: estimated } })
    if (err.code === 11000) {
      const winner = await CreditHold.findOne({ holdId }).lean()
      if (winner && winner.fingerprint === fingerprint && winner.status === 'active') {
        return {
          hold: publicView(winner, { withKey: true }),
          balance: await credit.getBalance(fingerprint),
          created: false,
        }
      }
      throw new HoldError(409, 'HOLD_CONFLICT', 'Hold đang được xử lý, thử lại.')
    }
    throw err
  }

  const hold = await CreditHold.create({
    holdId,
    fingerprint,
    deviceId: device._id,
    estimatedVox: estimated,
    usedVox: 0,
    usage: [],
    encKeyHex: crypto.randomBytes(32).toString('hex'),
    status: 'active',
    expiresAt,
    meta: { videoDurationS, sentences, autoTranslate, metadata, breakdown },
  })

  return {
    hold: publicView(hold, { withKey: true }),
    balance: device.balance,
    created: true,
  }
}

/**
 * Hold này còn hấp thụ được lượt `action` không? (bản JS thuần cho precheck —
 * accrue() dùng đúng các điều kiện này trong query nguyên tử.)
 *
 * - Hold ACTIVE hấp thụ các lượt AI của lượt chạy: giá trọn gói đã thu.
 *   NGOẠI LỆ: hold tạo với autoTranslate=false chỉ trả 10 Vox/segment —
 *   giá đó KHÔNG bao gồm dịch máy, nên translate/analyze/review không được
 *   hấp thụ (client sửa đổi gọi /translate với holdId rẻ sẽ rơi về trừ ví
 *   đúng đơn giá 12). Luồng app bình thường không bao giờ chạm nhánh này:
 *   tắt dịch tự động là đi đường dịch tay.
 * - Riêng generate_post còn được hấp thụ SAU commit: luồng wizard chỉ chạy
 *   bước này sau khi bấm Xuất video (hold đã chốt), nhưng +20 Vox của gói
 *   tiêu đề + mô tả đã nằm trong giá hold. Điều kiện: hold có mua gói
 *   (meta.metadata) và chưa hấp thụ lượt generate_post nào khác — một hold
 *   chỉ trả cho đúng MỘT gói đăng bài.
 */
const TRANSLATE_ACTIONS = ['translate', 'analyze', 'review']

function canAbsorb(hold, action, jobId) {
  if (!hold) return false
  if (hold.status === 'active') {
    // `=== false` chứ không phải falsy: hold cũ thiếu meta.autoTranslate
    // vẫn hấp thụ như trước (đã thu giá 12 từ thời đó).
    if (TRANSLATE_ACTIONS.includes(action)
      && (hold.meta || {}).autoTranslate === false) return false
    return true
  }
  if (action !== 'generate_post') return false
  if (hold.status !== 'committed' || !(hold.meta || {}).metadata) return false
  return !(hold.usage || []).some(
    (u) => u.action === 'generate_post' && u.jobId !== jobId,
  )
}

/**
 * Tích lũy usage của một lượt AI thành công vào hold.
 * Replay-safe: jobId đã có trong usage → no-op, trả trạng thái hiện tại.
 * Trả về { accrued, usedVox, remaining } hoặc null nếu hold không hấp thụ
 * được lượt này (caller rơi về trừ ví thẳng).
 */
async function accrue({ holdId, fingerprint, jobId, action, vox, sentences = 0 }) {
  const amount = Math.max(0, Math.round(vox))
  const match = {
    holdId,
    fingerprint,
    'usage.jobId': { $ne: jobId },
  }
  if (action === 'generate_post') {
    // Cùng điều kiện với canAbsorb(), nhưng nguyên tử trong query.
    match.$or = [
      { status: 'active' },
      { status: 'committed', 'meta.metadata': true },
    ]
    match.usage = {
      $not: { $elemMatch: { action: 'generate_post', jobId: { $ne: jobId } } },
    }
  } else {
    match.status = 'active'
    if (TRANSLATE_ACTIONS.includes(action)) {
      // Hold giá 10 (autoTranslate=false) không bao dịch máy — xem canAbsorb.
      match['meta.autoTranslate'] = { $ne: false }
    }
  }
  const updated = await CreditHold.findOneAndUpdate(
    match,
    {
      $inc: { usedVox: amount },
      $push: { usage: { action, jobId, vox: amount, sentences, at: new Date() } },
    },
    { new: true },
  ).lean()
  if (updated) {
    return {
      accrued: amount,
      usedVox: updated.usedVox,
      remaining: Math.max(0, updated.estimatedVox - updated.usedVox),
    }
  }
  // Không update được: hoặc replay (jobId đã ghi), hoặc hold hết active.
  const hold = await CreditHold.findOne({ holdId, fingerprint }).lean()
  if (!hold) return null
  if ((hold.usage || []).some((u) => u.jobId === jobId)) {
    return {
      accrued: 0,
      usedVox: hold.usedVox,
      remaining: Math.max(0, hold.estimatedVox - hold.usedVox),
      replayed: true,
    }
  }
  return null   // committed/released — caller quyết định (fallback trừ ví thẳng)
}

/** Hold của thiết bị, tự chốt nếu quá hạn (lazy expiry). */
async function getHold(fingerprint, holdId) {
  let hold = await CreditHold.findOne({ holdId, fingerprint }).lean()
  if (!hold) return null
  if (hold.status === 'active' && hold.expiresAt < new Date()) {
    await commitHold({ fingerprint, holdId, auto: true })
    hold = await CreditHold.findOne({ holdId, fingerprint }).lean()
  }
  return hold
}

/**
 * Chốt hold. Giá đã cố định từ lúc tạo (số segment × đơn giá) và ví đã bị trừ
 * đủ ngay lúc đó, nên commit KHÔNG động vào tiền nữa: không hoàn phần "chưa
 * dùng", không truy thu phần "vượt". `usedVox`/`usage` chỉ là chi phí AI nội
 * bộ để đối soát biên lợi nhuận — người dùng không trả theo con số đó.
 * Idempotent — hold đã committed thì trả lại kết quả cũ kèm khóa.
 */
async function commitHold({ fingerprint, holdId, auto = false }) {
  const hold = await CreditHold.findOneAndUpdate(
    { holdId, fingerprint, status: 'active' },
    { $set: { status: 'committed', committedAt: new Date(), autoCommitted: auto } },
    { new: true },
  ).lean()

  if (!hold) {
    const prior = await CreditHold.findOne({ holdId, fingerprint }).lean()
    if (!prior) throw new HoldError(404, 'HOLD_NOT_FOUND', 'Không tìm thấy hold.')
    if (prior.status === 'committed') {
      // Replay — trả kết quả cũ. Sau khi đã trả tiền, dự án phải giải mã
      // được mãi mãi nên key vẫn đi kèm.
      return {
        committed: true,
        replayed: true,
        usedVox: prior.usedVox,
        chargedVox: prior.estimatedVox,
        balance: await credit.getBalance(fingerprint),
        encKeyHex: prior.encKeyHex,
        autoCommitted: prior.autoCommitted || false,
      }
    }
    throw new HoldError(409, 'HOLD_FINISHED', 'Hold đã đóng trước đó.')
  }

  return {
    committed: true,
    replayed: false,
    usedVox: hold.usedVox,
    chargedVox: hold.estimatedVox,
    balance: await credit.getBalance(fingerprint),
    encKeyHex: hold.encKeyHex,
    autoCommitted: auto,
  }
}

/** Sweeper: tự chốt mọi hold active đã quá hạn. Trả về số hold đã chốt. */
async function expireSweep(log = null) {
  if (!(await config.get('hold.enabled'))) return 0
  const expired = await CreditHold.find(
    { status: 'active', expiresAt: { $lt: new Date() } },
    { holdId: 1, fingerprint: 1 },
  ).limit(200).lean()
  let done = 0
  for (const h of expired) {
    try {
      await commitHold({ fingerprint: h.fingerprint, holdId: h.holdId, auto: true })
      done += 1
    } catch (err) {
      // Một hold kẹt không được chặn các hold còn lại.
      if (log) log.warn({ err, holdId: h.holdId }, 'auto-commit hold thất bại')
    }
  }
  return done
}

async function listHolds({ status, page = 1, limit = 50 } = {}) {
  const q = status ? { status } : {}
  const skip = (Math.max(1, page) - 1) * limit
  const [items, total] = await Promise.all([
    CreditHold.find(q).sort({ createdAt: -1 }).skip(skip).limit(limit)
      .select('-encKeyHex').lean(),
    CreditHold.countDocuments(q),
  ])
  return { items, total, page, limit }
}

module.exports = {
  HoldError,
  estimateVox,
  createHold,
  canAbsorb,
  accrue,
  getHold,
  commitHold,
  expireSweep,
  listHolds,
  publicView,
}
