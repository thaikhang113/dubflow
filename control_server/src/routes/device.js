'use strict'

/**
 * `/v1/device` — đăng ký thiết bị, cấp token, xem ví, kích hoạt key.
 *
 * Không có đăng nhập: `POST /register` vừa là "tạo tài khoản" vừa là "đăng
 * nhập". App gọi nó lần đầu và mỗi khi token hết hạn.
 */
const deviceService = require('../services/device.service')
const activation = require('../services/activation.service')
const credit = require('../services/credit.service')
const config = require('../services/config.service')
const holds = require('../services/hold.service')

module.exports = async function deviceRoutes(fastify) {
  const { requireDevice } = require('../middleware/auth.middleware')

  // --- Đăng ký / nhận diện lại thiết bị ---------------------------------
  fastify.post('/register', {
    config: { rateLimit: { max: 20, timeWindow: '1 minute' } },
    schema: {
      body: {
        type: 'object',
        required: ['fingerprint'],
        properties: {
          fingerprint: { type: 'string', minLength: 64, maxLength: 64 },
          name: { type: 'string', maxLength: 120 },
          appVersion: { type: 'string', maxLength: 32 },
        },
      },
    },
  }, async (request, reply) => {
    try {
      const { device, token, isNew } = await deviceService.registerDevice({
        ...request.body, ip: request.ip,
      })
      const creditEnabled = await config.get('credit.enabled')
      return {
        token,
        isNew,
        device: deviceService.publicView(device),
        creditEnabled,
      }
    } catch (err) {
      if (err.statusCode) {
        return reply.code(err.statusCode).send({ code: err.code, message: err.message })
      }
      throw err
    }
  })

  // --- Thông tin thiết bị + số dư ---------------------------------------
  fastify.get('/me', { preHandler: requireDevice }, async (request) => {
    // Thiết bị sống đủ lâu thì cấp nốt phần trial chờ chín — lỗi ở đây không
    // được làm hỏng việc đọc thông tin.
    await deviceService.maybeGrantDeferredTrial(request.device).catch(() => {})
    const creditEnabled = await config.get('credit.enabled')
    return {
      device: {
        ...deviceService.publicView(request.device),
        balance: await credit.getBalance(request.device.fingerprint),
      },
      creditEnabled,
    }
  })

  // Token sắp hết hạn thì app đổi lấy token mới mà không cần đăng ký lại.
  fastify.post('/refresh', { preHandler: requireDevice }, async (request) => ({
    token: deviceService.signToken(request.device),
    device: deviceService.publicView(request.device),
  }))

  // --- Kích hoạt mã ------------------------------------------------------
  fastify.post('/activate', {
    preHandler: requireDevice,
    config: { rateLimit: { max: 10, timeWindow: '1 minute' } },
    schema: {
      body: {
        type: 'object',
        required: ['code'],
        properties: { code: { type: 'string', minLength: 8, maxLength: 40 } },
      },
    },
  }, async (request, reply) => {
    try {
      const result = await activation.activate(
        request.device.fingerprint, request.body.code, { ip: request.ip })
      return result
    } catch (err) {
      if (err.statusCode) {
        return reply.code(err.statusCode).send({ code: err.code, message: err.message })
      }
      throw err
    }
  })

  // --- Ví ---------------------------------------------------------------
  fastify.get('/balance', { preHandler: requireDevice }, async (request) => {
    await deviceService.maybeGrantDeferredTrial(request.device).catch(() => {})
    return {
      balance: await credit.getBalance(request.device.fingerprint),
      creditEnabled: await config.get('credit.enabled'),
    }
  })

  fastify.get('/history', {
    preHandler: requireDevice,
    schema: {
      querystring: {
        type: 'object',
        properties: {
          page: { type: 'integer', minimum: 1, default: 1 },
          limit: { type: 'integer', minimum: 1, maximum: 100, default: 20 },
        },
      },
    },
  }, async (request) => {
    const { page, limit } = request.query
    return credit.history(request.device.fingerprint, { page, limit })
  })

  // --- Ước tính chi phí trước khi chạy ----------------------------------
  // Dùng chung `holds.estimateVox` với lúc tạo hold: con số app hiện ra trước
  // khi chạy phải bằng đúng số tiền bị trừ, không được lệch một Vox nào.
  fastify.post('/estimate', {
    preHandler: requireDevice,
    schema: {
      body: {
        type: 'object',
        properties: {
          sentences: { type: 'integer', minimum: 0, default: 0 },
          autoTranslate: { type: 'boolean', default: false },
          metadata: { type: 'boolean', default: false },
        },
      },
    },
  }, async (request) => {
    const { sentences, autoTranslate, metadata } = request.body
    if (!(await config.get('credit.enabled'))) {
      return { estimated: 0, balance: request.device.balance, sufficient: true, creditEnabled: false }
    }
    const { estimated } = await holds.estimateVox(sentences, { autoTranslate, metadata })
    const balance = await credit.getBalance(request.device.fingerprint)
    return { estimated, balance, sufficient: balance >= estimated, creditEnabled: true }
  })
}
