'use strict'

/**
 * Kích hoạt key → cộng Vox vào ví thiết bị.
 *
 * Quy tắc bất di bất dịch: MỘT key dùng đúng MỘT lần trên đúng MỘT thiết bị.
 * Nó được ép ở tầng dữ liệu chứ không phải bằng lệnh if — lệnh
 * findOneAndUpdate dưới đây chỉ khớp khi key còn `status: 'issued'`, và nó
 * đặt luôn `status: 'used'` trong cùng một thao tác nguyên tử. Hai máy nhập
 * cùng lúc thì đúng một máy khớp, máy kia nhận null và bị từ chối.
 */
const ActivationKey = require('../models/ActivationKey')
const Device = require('../models/Device')
const credit = require('./credit.service')
const audit = require('./audit.service')
const { normalizeKeyCode } = require('../utils/keycode')

class ActivationError extends Error {
  constructor(code, message, statusCode = 400) {
    super(message)
    this.name = 'ActivationError'
    this.code = code
    this.statusCode = statusCode
  }
}

/**
 * Dùng key cho một thiết bị. Trả về { vox, balanceAfter, keyCode }.
 *
 * Idempotency: cùng một key nhập lại trên CHÍNH máy đó trả về kết quả cũ
 * (không cộng thêm) thay vì báo lỗi — app bấm nhầm hai lần không đáng bị coi
 * là gian lận. Nhập trên máy khác thì bị từ chối thẳng.
 */
async function activate(fingerprint, rawCode, { ip = '' } = {}) {
  const code = normalizeKeyCode(rawCode)
  if (!code) {
    throw new ActivationError('BAD_KEY_FORMAT',
      'Mã kích hoạt sai định dạng. Mã có dạng VOX-XXXX-XXXX-XXXX.')
  }

  const device = await Device.findOne({ fingerprint })
  if (!device) {
    throw new ActivationError('DEVICE_NOT_FOUND', 'Thiết bị chưa đăng ký.', 404)
  }
  if (device.status === 'blocked') {
    throw new ActivationError('DEVICE_BLOCKED',
      'Thiết bị này đã bị khóa.', 403)
  }

  const existing = await ActivationKey.findOne({ code })
  if (!existing) {
    throw new ActivationError('KEY_NOT_FOUND',
      'Mã kích hoạt không tồn tại. Kiểm tra lại mã trong email đơn hàng.', 404)
  }
  if (existing.status === 'revoked') {
    throw new ActivationError('KEY_REVOKED',
      'Mã này đã bị thu hồi. Liên hệ hỗ trợ nếu bạn cho là nhầm.', 409)
  }
  if (existing.status === 'used') {
    if (existing.usedByFingerprint === fingerprint) {
      // Đã kích hoạt trên chính máy này — trả về kết quả cũ, không cộng lại.
      return {
        vox: existing.vox,
        balanceAfter: device.balance,
        keyCode: code,
        alreadyActivated: true,
      }
    }
    throw new ActivationError('KEY_ALREADY_USED',
      'Mã này đã được kích hoạt trên một thiết bị khác. '
      + 'Mỗi mã chỉ dùng được cho một máy.', 409)
  }

  // Chốt key về thiết bị này. Điều kiện status='issued' trong chính lệnh
  // update là thứ chặn hai máy cùng thắng.
  const claimed = await ActivationKey.findOneAndUpdate(
    { code, status: 'issued' },
    {
      $set: {
        status: 'used',
        usedByFingerprint: fingerprint,
        usedByDeviceId: device._id,
        usedAt: new Date(),
        usedIp: ip,
      },
    },
    { new: true },
  )
  if (!claimed) {
    throw new ActivationError('KEY_ALREADY_USED',
      'Mã này vừa được kích hoạt trên một thiết bị khác.', 409)
  }

  let result
  try {
    result = await credit.grant(fingerprint, claimed.vox, {
      type: 'activation',
      idempotencyKey: `key-${code}`,
      description: `Kích hoạt mã ${code} (+${claimed.vox} Vox)`,
      metadata: { keyCode: code, orderCode: claimed.orderId ? String(claimed.orderId) : '', ip },
    })
  } catch (err) {
    // Cộng credit hỏng thì trả key về trạng thái chưa dùng — người mua không
    // được phép mất cả key lẫn credit vì một lỗi phía chúng ta.
    await ActivationKey.updateOne({ _id: claimed._id, status: 'used' }, {
      $set: { status: 'issued', usedByFingerprint: null, usedByDeviceId: null, usedAt: null },
    })
    throw err
  }

  await audit.log({
    action: 'key.activate',
    actor: `device:${fingerprint.slice(0, 8)}`,
    target: code,
    after: { vox: claimed.vox, balanceAfter: result.balanceAfter },
    ip,
  })

  return {
    vox: claimed.vox,
    balanceAfter: result.balanceAfter,
    keyCode: code,
    alreadyActivated: false,
  }
}

/** Tạo một key mới (dùng bởi webhook thanh toán và admin). */
async function issueKey({ vox, source = 'order', orderId = null, packageId = '',
  amountVnd = 0, note = '' }) {
  const { generateKeyCode } = require('../utils/keycode')
  // UNIQUE index là trọng tài cuối cùng; vài lần thử là quá đủ cho không
  // gian mã 5e17 tổ hợp.
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const code = generateKeyCode()
    try {
      return await ActivationKey.create({
        code, vox, source, orderId, packageId, amountVnd, note,
      })
    } catch (err) {
      if (err.code !== 11000) throw err
    }
  }
  throw new Error('Không sinh được mã kích hoạt duy nhất sau 5 lần thử')
}

module.exports = { activate, issueKey, ActivationError }
