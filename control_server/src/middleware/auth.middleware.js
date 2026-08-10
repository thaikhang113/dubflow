'use strict'

/**
 * Xác thực device token trên mọi route cần danh tính.
 *
 * Ba lớp kiểm tra: chữ ký JWT hợp lệ → thiết bị tồn tại và còn `active` →
 * `tokenVersion` khớp (công tắc thu hồi của admin). Thiếu bất kỳ lớp nào thì
 * 401/403 kèm mã lỗi để app biết nên đăng ký lại hay hiện thông báo khóa máy.
 *
 * `request.device` được gắn sẵn cho các handler phía sau.
 */
const Device = require('../models/Device')
const deviceService = require('../services/device.service')

async function requireDevice(request, reply) {
  const header = request.headers.authorization || ''
  const token = header.startsWith('Bearer ') ? header.slice(7).trim() : ''
  if (!token) {
    return reply.code(401).send({ code: 'NO_TOKEN', message: 'Thiếu token thiết bị.' })
  }

  let payload
  try {
    payload = deviceService.verifyToken(token)
  } catch (err) {
    const expired = err.name === 'TokenExpiredError'
    return reply.code(401).send({
      code: expired ? 'TOKEN_EXPIRED' : 'BAD_TOKEN',
      message: expired
        ? 'Phiên làm việc đã hết hạn. Ứng dụng sẽ tự kết nối lại.'
        : 'Token không hợp lệ.',
    })
  }

  const device = await Device.findOne({ fingerprint: payload.fp })
  if (!device) {
    return reply.code(401).send({
      code: 'DEVICE_NOT_FOUND',
      message: 'Thiết bị chưa đăng ký. Ứng dụng sẽ tự đăng ký lại.',
    })
  }
  if (device.status === 'blocked') {
    return reply.code(403).send({
      code: 'DEVICE_BLOCKED',
      message: device.blockedReason || 'Thiết bị này đã bị khóa.',
    })
  }
  if (Number(payload.v) !== device.tokenVersion) {
    return reply.code(401).send({
      code: 'TOKEN_REVOKED',
      message: 'Phiên làm việc đã bị thu hồi. Ứng dụng sẽ tự kết nối lại.',
    })
  }

  request.device = device
  // Cập nhật dấu vết hoạt động — best-effort, không chặn request.
  Device.updateOne({ _id: device._id }, {
    $set: { lastSeenAt: new Date(), lastSeenIp: request.ip },
  }).catch(() => {})
}

module.exports = { requireDevice }
