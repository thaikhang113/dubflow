'use strict'

/**
 * Cổng admin — một secret duy nhất trong `.env`, tách hẳn khỏi token thiết bị.
 *
 * Đây là tầng bảo mật độc lập: kể cả khi toàn bộ device token bị lộ, không
 * ai chạm được vào `/v1/admin/*`. So sánh bằng hash timing-safe để không rò
 * rỉ độ dài hay tiền tố của secret qua thời gian phản hồi.
 */
const { safeEqual } = require('../utils/crypto')

async function requireAdmin(request, reply) {
  const expected = (process.env.ADMIN_TOKEN || '').trim()
  if (!expected) {
    return reply.code(503).send({
      code: 'ADMIN_DISABLED',
      message: 'Server chưa đặt ADMIN_TOKEN.',
    })
  }
  const given = String(request.headers['x-admin-token'] || '')
  if (!safeEqual(given, expected)) {
    request.log.warn({ ip: request.ip, url: request.url }, 'admin auth fail')
    return reply.code(401).send({ code: 'BAD_ADMIN_TOKEN', message: 'Sai token admin.' })
  }
}

module.exports = { requireAdmin }
