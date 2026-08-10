'use strict'

/**
 * `/v1/billing` — mua credit trên website (không cần tài khoản).
 *
 * Người mua chỉ để lại email (không bắt buộc) để nhận key. Thanh toán đi qua
 * PayOS: server tạo link, PayOS bắn webhook có chữ ký khi tiền về.
 */
const billing = require('../services/billing.service')
const email = require('../services/email.service')
const payos = require('../services/payos.service')

module.exports = async function billingRoutes(fastify) {
  // --- Bảng giá (công khai) ---------------------------------------------
  fastify.get('/packages', async () => billing.getPackages())

  // --- Tạo đơn -----------------------------------------------------------
  fastify.post('/orders', {
    config: { rateLimit: { max: 10, timeWindow: '1 minute' } },
    schema: {
      body: {
        type: 'object',
        properties: {
          packageId: { type: 'string', maxLength: 40 },
          amountVnd: { type: 'integer', minimum: 0 },
          email: { type: 'string', maxLength: 200 },
        },
      },
    },
  }, async (request, reply) => {
    try {
      const { order, payment } = await billing.createOrder({
        ...request.body, ip: request.ip,
      })
      // `accessToken` chỉ trả về ĐÚNG MỘT LẦN, ngay lúc tạo đơn. Trình
      // duyệt cất nó lại để theo dõi đơn và nhận key; ai không tạo đơn thì
      // không có token, và mã đơn ngắn không thay thế được nó.
      return {
        ...billing.orderView(order, { authorized: true }),
        accessToken: order.accessToken,
        payment,
      }
    } catch (err) {
      if (err.statusCode) {
        return reply.code(err.statusCode).send({ code: err.code, message: err.message })
      }
      throw err
    }
  })

  // --- Trạng thái đơn (web poll trong lúc chờ thanh toán) ----------------
  // Không có token vẫn xem được trạng thái (để người dùng mở lại link cũ
  // trên máy khác còn biết đơn đã thanh toán chưa), nhưng `keyCode` thì
  // tuyệt đối không — xem `orderView`.
  fastify.get('/orders/:orderCode', {
    config: { rateLimit: { max: 120, timeWindow: '1 minute' } },
    schema: {
      querystring: {
        type: 'object',
        properties: { token: { type: 'string', maxLength: 100 } },
      },
    },
  }, async (request, reply) => {
    const order = await billing.getOrder(request.params.orderCode)
    if (!order) {
      return reply.code(404).send({ code: 'ORDER_NOT_FOUND', message: 'Không tìm thấy đơn hàng.' })
    }
    return billing.orderView(order, {
      includePayment: true,
      authorized: billing.tokenMatches(order, request.query.token),
    })
  })

  // --- Gửi lại mã vào email --------------------------------------------
  // Người mua đóng tab trước khi kịp chép mã. Có token thì gửi lại được —
  // không có token thì đây lại thành cách moi key của đơn người khác.
  fastify.post('/orders/:orderCode/resend', {
    config: { rateLimit: { max: 5, timeWindow: '10 minutes' } },
    schema: {
      body: {
        type: 'object',
        required: ['token'],
        properties: {
          token: { type: 'string', maxLength: 100 },
          email: { type: 'string', maxLength: 200 },
        },
      },
    },
  }, async (request, reply) => {
    const order = await billing.getOrder(request.params.orderCode)
    if (!order || !billing.tokenMatches(order, request.body.token)) {
      return reply.code(404).send({ code: 'ORDER_NOT_FOUND', message: 'Không tìm thấy đơn hàng.' })
    }
    if (order.status !== 'paid' || !order.keyCode) {
      return reply.code(409).send({
        code: 'NOT_PAID',
        message: 'Đơn này chưa thanh toán xong nên chưa có mã.',
      })
    }
    const to = String(request.body.email || order.email || '').trim().toLowerCase()
    if (!to) {
      return reply.code(400).send({ code: 'NO_EMAIL', message: 'Chưa có địa chỉ email.' })
    }
    // Nhớ lại email mới để lần sau khỏi phải nhập.
    if (to !== order.email) { order.email = to; await order.save() }

    const sent = await email.sendActivationKey({
      to,
      keyCode: order.keyCode,
      vox: order.vox,
      orderCode: order.orderCode,
      amountVnd: order.amountVnd,
    })
    if (!sent) {
      return reply.code(503).send({
        code: 'MAIL_FAILED',
        message: 'Chưa gửi được email. Mã của bạn vẫn hiện trên màn hình — hãy chép lại.',
      })
    }
    return { ok: true, email: to }
  })

  // --- Webhook PayOS -----------------------------------------------------
  // PayOS gửi { code, desc, success, data, signature } — verify chữ ký
  // HMAC-SHA256 bằng checksum key. Sai chữ ký → 401. Đúng chữ ký nhưng
  // không khớp đơn → vẫn 2xx (lúc đăng ký webhook PayOS bắn payload test
  // không có đơn thật; trả lỗi là đăng ký thất bại).
  fastify.post('/webhook/payos', {
    config: { rateLimit: { max: 120, timeWindow: '1 minute' } },
  }, async (request, reply) => {
    if (!payos.isConfigured()) {
      return reply.code(503).send({ success: false, message: 'Webhook chưa cấu hình' })
    }
    const body = request.body || {}
    if (!payos.verifyWebhookSignature(body.data, body.signature)) {
      request.log.warn({ ip: request.ip }, 'payos webhook: sai chữ ký')
      return reply.code(401).send({ success: false, message: 'Unauthorized' })
    }
    // Giao dịch không thành công thì bỏ qua (PayOS chỉ webhook khi thành
    // công, nhưng vẫn chặn phòng hờ theo tài liệu).
    if (body.success === false || (body.code && body.code !== '00')) {
      return { success: true }
    }
    try {
      const result = await billing.handlePayosPayment(body.data, request.ip)
      if (!result.matched) {
        request.log.warn({ orderCode: body.data && body.data.orderCode },
          'payos webhook: không khớp đơn nào (có thể là payload test)')
      }
      return { success: true }
    } catch (err) {
      request.log.error({ err }, 'payos webhook lỗi')
      // Vẫn 200: giao dịch đã ghi ở PayOS, admin đối chiếu tay được.
      return { success: true }
    }
  })
}
