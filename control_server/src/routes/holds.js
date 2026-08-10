'use strict'

/**
 * `/v1/holds` — giữ chỗ Vox cho luồng wizard (hold sau ASR, commit lúc xuất).
 *
 * Tất cả yêu cầu token thiết bị. `holdId` do app sinh (= run_id, hash nội
 * dung transcript) nên POST lại cùng holdId là idempotent — nhận về đúng
 * hold cũ kèm khóa giải mã, phục vụ resume sau crash.
 */
const holds = require('../services/hold.service')
const credit = require('../services/credit.service')

module.exports = async function holdRoutes(fastify) {
  const { requireDevice } = require('../middleware/auth.middleware')

  fastify.addHook('preHandler', requireDevice)

  // --- Tạo hold (hoặc nhận lại hold active cùng holdId) -------------------
  fastify.post('/', {
    config: { rateLimit: { max: 20, timeWindow: '1 minute' } },
    schema: {
      body: {
        type: 'object',
        required: ['holdId', 'sentences'],
        properties: {
          holdId: { type: 'string', minLength: 8, maxLength: 100 },
          sentences: { type: 'integer', minimum: 1, maximum: 20000 },
          videoDurationS: { type: 'number', minimum: 0, default: 0 },
          autoTranslate: { type: 'boolean', default: true },
          metadata: { type: 'boolean', default: true },
        },
      },
    },
  }, async (request, reply) => {
    const { device } = request
    try {
      const result = await holds.createHold({
        fingerprint: device.fingerprint,
        deviceId: device._id,
        holdId: request.body.holdId,
        sentences: request.body.sentences,
        videoDurationS: request.body.videoDurationS || 0,
        autoTranslate: request.body.autoTranslate,
        metadata: request.body.metadata,
        ip: request.ip,
      })
      return result
    } catch (err) {
      if (err instanceof credit.InsufficientCreditError) {
        return reply.code(402).send({
          code: 'INSUFFICIENT_CREDIT',
          message: `Không đủ Vox. Cần ${err.required}, bạn có ${err.balance}.`,
          balance: err.balance,
          required: err.required,
        })
      }
      if (err.statusCode) {
        return reply.code(err.statusCode).send({ code: err.code, message: err.message })
      }
      throw err
    }
  })

  // --- Trạng thái hold + khóa giải mã -------------------------------------
  // Khóa trả về khi hold còn active HOẶC đã committed: sau khi đã trả tiền,
  // dự án phải giải mã được mãi (resume, mở lại máy...).
  fastify.get('/:holdId', async (request, reply) => {
    const hold = await holds.getHold(request.device.fingerprint, request.params.holdId)
    if (!hold) {
      return reply.code(404).send({ code: 'HOLD_NOT_FOUND', message: 'Không tìm thấy hold.' })
    }
    const withKey = hold.status === 'active' || hold.status === 'committed'
    return {
      hold: holds.publicView(hold, { withKey }),
      balance: await credit.getBalance(request.device.fingerprint),
    }
  })

  // --- Commit: chốt lượt và mở khóa (giá đã cố định lúc tạo hold) ----------
  fastify.post('/:holdId/commit', {
    config: { rateLimit: { max: 20, timeWindow: '1 minute' } },
  }, async (request, reply) => {
    try {
      return await holds.commitHold({
        fingerprint: request.device.fingerprint,
        holdId: request.params.holdId,
      })
    } catch (err) {
      if (err.statusCode) {
        return reply.code(err.statusCode).send({ code: err.code, message: err.message })
      }
      throw err
    }
  })
}
