'use strict'

/**
 * `/v1/ai` — cổng duy nhất app gọi để dùng mô hình.
 *
 * Trật tự bất biến của mọi route ở đây:
 *   1. Idempotency: `jobId` đã xử lý rồi → trả kết quả cũ, KHÔNG tính phí lại
 *   2. Kiểm tra trần cứng (số câu, độ dài câu) — app không đổi được
 *   3. Kiểm tra số dư
 *   4. Gọi mô hình
 *   5. Trừ credit (chỉ khi mô hình trả về thành công)
 *   6. Lưu kết quả theo jobId + ghi UsageLog
 *
 * Trừ credit SAU khi gọi mô hình: mô hình lỗi thì người dùng không mất gì.
 * Rủi ro ngược lại (gọi xong, chưa kịp trừ thì server chết) được UsageLog ghi
 * lại để đối chiếu, và nó hiếm hơn nhiều so với việc mô hình lỗi.
 *
 * `holdId` (tùy chọn, luồng wizard): thay vì trừ ví từng lượt, usage tích lũy
 * vào CreditHold — ví đã bị trừ trước bằng số ước tính lúc tạo hold, chốt
 * sổ lúc người dùng bấm Xuất video. Không có holdId thì mọi thứ như cũ.
 *
 * Response KHÔNG BAO GIỜ chứa tên provider, model, token hay chi phí.
 */
const JobResult = require('../models/JobResult')
const UsageLog = require('../models/UsageLog')
const credit = require('../services/credit.service')
const holds = require('../services/hold.service')
const config = require('../services/config.service')
const gateway = require('../services/ai-gateway.service')
const prompts = require('../prompts/translate')
const { containsCjk } = require('../utils/json-repair')

const TARGET_FIELD = 'text_vi'

/** Kết quả đã lưu của jobId này, hoặc null. */
async function replay(jobId, fingerprint) {
  if (!jobId) return null
  const doc = await JobResult.findOne({ jobId, fingerprint }).lean()
  return doc ? doc.result : null
}

async function remember(jobId, fingerprint, action, result, creditCharged) {
  if (!jobId) return
  try {
    await JobResult.create({ jobId, fingerprint, action, result, creditCharged })
  } catch (err) {
    if (err.code !== 11000) throw err   // trùng jobId = đã lưu rồi, không sao
  }
}

/**
 * Kiểm tra khả năng chi trả TRƯỚC khi gọi mô hình.
 *
 * Hold hấp thụ được lượt này (active, hoặc committed + gói đăng bài cho
 * generate_post — xem `holds.canAbsorb`): đã trả tiền trọn lượt lúc tạo hold,
 * không kiểm tra gì nữa. Không có hold: so với số dư ví (đường dự phòng,
 * xem `walletCost`).
 * Trả về null nếu đủ, ngược lại {balance, required} để route trả 402.
 */
async function precheck(fingerprint, holdId, cost, { action = '', jobId = '' } = {}) {
  if (holdId) {
    const hold = await holds.getHold(fingerprint, holdId)
    if (holds.canAbsorb(hold, action, jobId)) return null
  }
  if (cost <= 0) return null
  const balance = await credit.getBalance(fingerprint)
  if (balance >= cost) return null
  return { balance, required: cost }
}

/**
 * Kết thúc một lượt AI thành công.
 *
 * Hold hấp thụ được (active — hoặc committed + gói đăng bài cho đúng một
 * lượt generate_post): KHÔNG trừ ví. Tiền của cả lượt đã thu lúc tạo hold
 * theo số segment, nên ở đây chỉ ghi `internalVox` vào `hold.usage` để đối
 * soát biên lợi nhuận. `charged: 0` là đúng — app hiện tổng một lần ở bước
 * xuất video, không hiện từng lượt.
 *
 * Hold không hấp thụ được (đã tự chốt sau TTL, hoặc lượt vượt phạm vi):
 * rơi về trừ ví thẳng theo `walletCost` — đường dự phòng cho các lượt lẻ
 * ngoài luồng wizard.
 * Trả về { charged, balanceAfter }.
 */
async function charge(device, { holdId, jobId, action, walletCost, internalVox,
  sentences, description, ip }) {
  if (holdId) {
    const res = await holds.accrue({
      holdId,
      fingerprint: device.fingerprint,
      jobId,
      action,
      vox: internalVox,
      sentences,
    })
    if (res) {
      return { charged: 0, balanceAfter: await credit.getBalance(device.fingerprint) }
    }
    // Hold không hấp thụ được lượt này — rơi về đường cũ.
  }
  const amount = walletCost
  if (amount <= 0) {
    return { charged: 0, balanceAfter: await credit.getBalance(device.fingerprint) }
  }
  const prefix = { translate: 'translate', analyze: 'analyze', review: 'review',
    generate_post: 'post' }[action] || action
  try {
    const deducted = await credit.deduct(device.fingerprint, amount, {
      type: 'usage',
      idempotencyKey: `${prefix}-${jobId}`,
      description,
      metadata: { jobId, action, sentences, ip },
    })
    return { charged: amount, balanceAfter: deducted.balanceAfter }
  } catch (err) {
    if (!(err instanceof credit.InsufficientCreditError)) throw err
    // Precheck đã qua nhưng một request song song rút cạn ví trước khi trừ.
    // Mô hình ĐÃ chạy — phí AI phía server đã tiêu. Ném lỗi ở đây nghĩa là
    // route trả 5xx, jobId chưa được remember, app retry → server trả phí AI
    // lần thứ hai cho cùng một việc. Thay vào đó thu trần số dư còn lại và
    // trả kết quả — server không bao giờ chịu lỗ, ví không bao giờ âm.
    const clamp = Math.max(0, err.balance)
    if (clamp === 0) {
      return { charged: 0, balanceAfter: 0 }
    }
    try {
      const deducted = await credit.deduct(device.fingerprint, clamp, {
        type: 'usage',
        idempotencyKey: `${prefix}-${jobId}`,
        description: `${description} (thu được ${clamp}/${amount} Vox)`,
        metadata: { jobId, action, sentences, ip, clamped: true, intended: amount },
      })
      return { charged: clamp, balanceAfter: deducted.balanceAfter }
    } catch (err2) {
      // Ví lại bị rút tiếp giữa hai nhịp — thôi, coi như thu được 0. Kết quả
      // vẫn phải trả về: phí AI đã tiêu, giữ kết quả lại không cứu được gì.
      if (err2 instanceof credit.InsufficientCreditError) {
        return { charged: 0, balanceAfter: Math.max(0, err2.balance) }
      }
      throw err2
    }
  }
}

module.exports = async function aiRoutes(fastify) {
  const { requireDevice } = require('../middleware/auth.middleware')

  fastify.addHook('preHandler', requireDevice)

  // Chặn mọi request AI khi đang bảo trì — chạy dở nửa chừng lúc bảo trì tệ
  // hơn là báo rõ ngay từ đầu.
  fastify.addHook('preHandler', async (request, reply) => {
    if (await config.get('maintenance.mode')) {
      return reply.code(503).send({
        code: 'MAINTENANCE',
        message: (await config.get('maintenance.message'))
          || 'Hệ thống đang bảo trì. Vui lòng thử lại sau ít phút.',
      })
    }
  })

  // ------------------------------------------------------------ dịch lô ---
  fastify.post('/translate', {
    config: { rateLimit: { max: 40, timeWindow: '1 minute' } },
    schema: {
      body: {
        type: 'object',
        required: ['jobId', 'segments'],
        properties: {
          jobId: { type: 'string', minLength: 8, maxLength: 100 },
          holdId: { type: 'string', minLength: 8, maxLength: 100 },
          sourceLang: { type: 'string', maxLength: 16, default: 'zh-CN' },
          cpsBudget: { type: 'number', minimum: 4, maximum: 40, default: 12.5 },
          segments: {
            type: 'array',
            minItems: 1,
            items: {
              type: 'object',
              required: ['id', 'text'],
              properties: {
                id: { type: 'integer' },
                text: { type: 'string' },
                duration: { type: 'number' },
                max_chars: { type: 'integer' },
              },
            },
          },
          prevContext: {
            type: 'array',
            maxItems: 5,
            items: { type: 'object', additionalProperties: true },
          },
          context: {
            type: 'object',
            properties: {
              videoTitle: { type: 'string' },
              domain: { type: 'string' },
              context: { type: 'string' },
              pronouns: { type: 'string' },
              glossary: { type: 'string' },
              styleNotes: { type: 'string' },
            },
          },
        },
      },
    },
  }, async (request, reply) => {
    const { device } = request
    const { jobId, holdId, segments, sourceLang = 'zh-CN', cpsBudget = 12.5 } = request.body

    const cached = await replay(jobId, device.fingerprint)
    if (cached) return cached

    const cfg = await config.getMany([
      'ai.max.segments.per.request', 'ai.max.chars.per.segment',
      'ai.max.retries', 'credit.enabled',
      'credit.cost.segment.base', 'credit.cost.segment.autotranslate',
      'internal.cost.translate.per_sentence',
    ])
    if (segments.length > cfg['ai.max.segments.per.request']) {
      return reply.code(400).send({
        code: 'BATCH_TOO_LARGE',
        message: `Tối đa ${cfg['ai.max.segments.per.request']} câu mỗi lượt.`,
        maxSegments: cfg['ai.max.segments.per.request'],
      })
    }
    const maxChars = cfg['ai.max.chars.per.segment']
    const tooLong = segments.find((s) => String(s.text || '').length > maxChars)
    if (tooLong) {
      return reply.code(400).send({
        code: 'SEGMENT_TOO_LONG',
        message: `Câu ${tooLong.id} dài quá ${maxChars} ký tự.`,
      })
    }

    // Không có hold thì thu thẳng đơn giá segment của lượt dịch tự động —
    // gọi được /translate nghĩa là đang dùng server để dịch, giá phải bằng
    // đúng giá trong hold, không có đường tắt nào rẻ hơn.
    const perSegment = cfg['credit.cost.segment.base']
      + cfg['credit.cost.segment.autotranslate']
    const cost = cfg['credit.enabled'] ? segments.length * perSegment : 0
    if (cfg['credit.enabled']) {
      const short = await precheck(device.fingerprint, holdId, cost,
        { action: 'translate', jobId })
      if (short) {
        return reply.code(402).send({
          code: 'INSUFFICIENT_CREDIT',
          message: `Không đủ Vox. Cần ${short.required}, bạn có ${short.balance}.`,
          balance: short.balance,
          required: short.required,
        })
      }
    }

    const log = await UsageLog.create({
      fingerprint: device.fingerprint,
      jobId,
      action: 'translate',
      inputSize: segments.length,
      ip: request.ip,
      appVersion: device.appVersion,
    })
    const started = Date.now()

    let result
    try {
      const context = prompts.sanitizeContext(request.body.context || {})
      result = await gateway.translateBatch({
        segments,
        sourceLang,
        targetField: TARGET_FIELD,
        context,
        cpsBudget,
        prevContext: request.body.prevContext || [],
        maxRetries: cfg['ai.max.retries'],
      })
      // Lưới cuối: câu nào còn chữ Hán thì dịch lại ngay, app không phải
      // biết chuyện này tồn tại.
      const fix = await gateway.fixCjkLeftovers({
        merged: result.segments, sourceLang, targetField: TARGET_FIELD,
        context, cpsBudget,
      })
      result.segments = fix.segments
      result.usage.promptTokens += fix.usage.promptTokens
      result.usage.completionTokens += fix.usage.completionTokens
    } catch (err) {
      await UsageLog.updateOne({ _id: log._id }, {
        $set: {
          status: 'error',
          errorCode: err.code || 'AI_ERROR',
          errorMessage: String(err.message).slice(0, 500),
          durationMs: Date.now() - started,
        },
      })
      request.log.error({ err, jobId }, 'translate failed')
      return reply.code(err.statusCode || 503).send({
        code: err.code || 'AI_UNAVAILABLE',
        message: 'Dịch vụ dịch tạm thời không phản hồi. Thử lại sau ít phút.',
        retryAfter: 30,
      })
    }

    // Chỉ tính phí những câu thực sự dịch được.
    const done = result.segments.length
    const paid = await charge(device, {
      holdId,
      jobId,
      action: 'translate',
      walletCost: cfg['credit.enabled'] ? done * perSegment : 0,
      internalVox: done * cfg['internal.cost.translate.per_sentence'],
      sentences: done,
      description: `Dịch ${done} segment`,
      ip: request.ip,
    })

    const response = {
      jobId,
      segments: result.segments,
      creditCharged: paid.charged,
      balanceAfter: paid.balanceAfter,
    }
    await Promise.all([
      remember(jobId, device.fingerprint, 'translate', response, paid.charged),
      UsageLog.updateOne({ _id: log._id }, {
        $set: {
          status: 'success',
          creditCharged: paid.charged,
          aiProvider: result.provider,
          aiModel: result.model,
          promptTokens: result.usage.promptTokens,
          completionTokens: result.usage.completionTokens,
          durationMs: Date.now() - started,
        },
      }),
    ])
    return response
  })

  // ----------------------------------------------- phân tích ngữ cảnh ----
  fastify.post('/analyze', {
    config: { rateLimit: { max: 20, timeWindow: '1 minute' } },
    schema: {
      body: {
        type: 'object',
        required: ['jobId', 'lines'],
        properties: {
          jobId: { type: 'string', minLength: 8, maxLength: 100 },
          holdId: { type: 'string', minLength: 8, maxLength: 100 },
          sourceLang: { type: 'string', maxLength: 16, default: 'zh-CN' },
          videoTitle: { type: 'string', maxLength: 300 },
          // App đã lấy mẫu đầu–giữa–cuối trước khi gửi; đây là trần cứng.
          lines: { type: 'array', maxItems: 400, items: { type: 'string', maxLength: 800 } },
        },
      },
    },
  }, async (request, reply) => {
    const { device } = request
    const { jobId, lines, sourceLang = 'zh-CN', videoTitle = '', holdId } = request.body

    const cached = await replay(jobId, device.fingerprint)
    if (cached) return cached

    const cfg = await config.getMany(['credit.enabled', 'internal.cost.analyze'])
    const cost = cfg['credit.enabled'] ? cfg['internal.cost.analyze'] : 0
    const lacking = await precheck(device.fingerprint, holdId, cost,
      { action: 'analyze', jobId })
    if (lacking) {
      return reply.code(402).send({
        code: 'INSUFFICIENT_CREDIT',
        message: `Không đủ Vox. Cần ${lacking.required}, bạn có ${lacking.balance}.`,
        balance: lacking.balance,
        required: lacking.required,
      })
    }

    const started = Date.now()
    let result
    try {
      result = await gateway.analyze({
        lines: lines.join('\n'),
        sourceLang,
        videoTitle: String(videoTitle).slice(0, 300),
      })
    } catch (err) {
      // Phân tích là bước phụ trợ — hỏng thì app dịch như thường, không tính
      // phí, không dựng cờ đỏ trước mặt người dùng.
      request.log.warn({ err, jobId }, 'analyze failed')
      return { jobId, analysis: null, creditCharged: 0, balanceAfter: await credit.getBalance(device.fingerprint) }
    }
    if (!result.analysis) {
      return { jobId, analysis: null, creditCharged: 0, balanceAfter: await credit.getBalance(device.fingerprint) }
    }

    const paid = await charge(device, {
      holdId,
      jobId,
      action: 'analyze',
      walletCost: cost,
      internalVox: cfg['internal.cost.analyze'],
      description: 'Phân tích ngữ cảnh video',
      ip: request.ip,
    })

    const response = {
      jobId,
      analysis: result.analysis,
      creditCharged: paid.charged,
      balanceAfter: paid.balanceAfter,
    }
    await Promise.all([
      remember(jobId, device.fingerprint, 'analyze', response, paid.charged),
      UsageLog.create({
        fingerprint: device.fingerprint,
        jobId,
        action: 'analyze',
        inputSize: lines.length,
        creditCharged: paid.charged,
        aiProvider: result.provider,
        aiModel: result.model,
        promptTokens: result.usage.promptTokens,
        completionTokens: result.usage.completionTokens,
        durationMs: Date.now() - started,
        status: 'success',
        ip: request.ip,
        appVersion: device.appVersion,
      }),
    ])
    return response
  })

  // ------------------------------------------------------------ rà soát ---
  fastify.post('/review', {
    config: { rateLimit: { max: 20, timeWindow: '1 minute' } },
    schema: {
      body: {
        type: 'object',
        required: ['jobId', 'items'],
        properties: {
          jobId: { type: 'string', minLength: 8, maxLength: 100 },
          holdId: { type: 'string', minLength: 8, maxLength: 100 },
          sourceLang: { type: 'string', maxLength: 16, default: 'zh-CN' },
          cpsBudget: { type: 'number', minimum: 4, maximum: 40, default: 12.5 },
          context: { type: 'object', additionalProperties: true },
          items: {
            type: 'array',
            minItems: 1,
            maxItems: 60,
            items: {
              type: 'object',
              required: ['id', 'reason', 'text', 'current'],
              properties: {
                id: { type: 'integer' },
                reason: { type: 'string', enum: ['cjk', 'over_budget', 'too_short'] },
                text: { type: 'string', maxLength: 800 },
                current: { type: 'string', maxLength: 1200 },
                duration: { type: 'number' },
                max_chars: { type: 'integer' },
                neighbors: { type: 'string', maxLength: 1200 },
              },
            },
          },
        },
      },
    },
  }, async (request, reply) => {
    const { device } = request
    const { jobId, items, sourceLang = 'zh-CN', cpsBudget = 12.5, holdId } = request.body

    const cached = await replay(jobId, device.fingerprint)
    if (cached) return cached

    const cfg = await config.getMany(['credit.enabled', 'internal.cost.review.per_sentence'])
    const unitCost = cfg['credit.enabled'] ? cfg['internal.cost.review.per_sentence'] : 0
    const lacking = await precheck(device.fingerprint, holdId, items.length * unitCost,
      { action: 'review', jobId })
    if (lacking) {
      return reply.code(402).send({
        code: 'INSUFFICIENT_CREDIT',
        message: `Không đủ Vox. Cần ${lacking.required}, bạn có ${lacking.balance}.`,
        balance: lacking.balance,
        required: lacking.required,
      })
    }

    const context = prompts.sanitizeContext(request.body.context || {})
    const started = Date.now()
    let promptTokens = 0
    let completionTokens = 0

    const results = await Promise.all(items.map(async (item) => {
      try {
        const { text, usage } = await gateway.reviewOne({
          segment: {
            id: item.id, text: item.text, duration: item.duration,
            max_chars: item.max_chars, [TARGET_FIELD]: item.current,
          },
          reason: item.reason,
          neighbors: item.neighbors || '',
          sourceLang,
          targetField: TARGET_FIELD,
          context,
          cpsBudget,
        })
        promptTokens += usage.promptTokens
        completionTokens += usage.completionTokens
        if (!accept(item, text)) return null
        return { id: item.id, [TARGET_FIELD]: text }
      } catch {
        // Một câu rà soát hỏng không được phép làm hỏng cả lượt — giữ bản cũ.
        return null
      }
    }))

    const fixed = results.filter(Boolean)
    const paid = await charge(device, {
      holdId,
      jobId,
      action: 'review',
      walletCost: unitCost > 0 ? fixed.length * unitCost : 0,
      internalVox: fixed.length * cfg['internal.cost.review.per_sentence'],
      sentences: fixed.length,
      description: `Rà soát ${fixed.length} câu`,
      ip: request.ip,
    })

    const response = {
      jobId,
      segments: fixed,
      creditCharged: paid.charged,
      balanceAfter: paid.balanceAfter,
    }
    await Promise.all([
      remember(jobId, device.fingerprint, 'review', response, paid.charged),
      UsageLog.create({
        fingerprint: device.fingerprint,
        jobId,
        action: 'review',
        inputSize: items.length,
        creditCharged: paid.charged,
        promptTokens,
        completionTokens,
        durationMs: Date.now() - started,
        status: 'success',
        ip: request.ip,
        appVersion: device.appVersion,
      }),
    ])
    return response
  })

  // ------------------------------------------------- nội dung đăng bài ----
  fastify.post('/generate-post', {
    config: { rateLimit: { max: 10, timeWindow: '1 minute' } },
    schema: {
      body: {
        type: 'object',
        required: ['jobId', 'scriptOriginal', 'scriptVi'],
        properties: {
          jobId: { type: 'string', minLength: 8, maxLength: 100 },
          holdId: { type: 'string', minLength: 8, maxLength: 100 },
          scriptOriginal: { type: 'string', maxLength: 20000 },
          scriptVi: { type: 'string', maxLength: 20000 },
          videoTitle: { type: 'string', maxLength: 300 },
        },
      },
    },
  }, async (request, reply) => {
    const { device } = request
    const { jobId, scriptOriginal, scriptVi, videoTitle = '', holdId } = request.body

    const cached = await replay(jobId, device.fingerprint)
    if (cached) return cached

    // Không kèm hold thì thu đúng giá công khai của gói tiêu đề + mô tả.
    const cfg = await config.getMany([
      'credit.enabled', 'credit.cost.metadata', 'internal.cost.generate_post',
    ])
    const cost = cfg['credit.enabled'] ? cfg['credit.cost.metadata'] : 0
    // Luồng wizard gọi bước này SAU khi hold đã chốt (bấm Xuất video) —
    // canAbsorb vẫn nhận vì gói tiêu đề + mô tả đã nằm trong giá hold.
    const lacking = await precheck(device.fingerprint, holdId, cost,
      { action: 'generate_post', jobId })
    if (lacking) {
      return reply.code(402).send({
        code: 'INSUFFICIENT_CREDIT',
        message: `Không đủ Vox. Cần ${lacking.required}, bạn có ${lacking.balance}.`,
        balance: lacking.balance,
        required: lacking.required,
      })
    }

    const started = Date.now()
    let result
    try {
      result = await gateway.generatePost({ scriptOriginal, scriptVi, videoTitle })
    } catch (err) {
      request.log.warn({ err, jobId }, 'generate-post failed')
      return reply.code(503).send({
        code: 'AI_UNAVAILABLE',
        message: 'Chưa viết được nội dung đăng bài. Video của bạn không bị ảnh hưởng.',
        retryAfter: 30,
      })
    }

    const paid = await charge(device, {
      holdId,
      jobId,
      action: 'generate_post',
      walletCost: cost,
      internalVox: cfg['internal.cost.generate_post'],
      description: 'Tạo tiêu đề + mô tả',
      ip: request.ip,
    })

    const response = {
      jobId,
      metadata: result.metadata,
      creditCharged: paid.charged,
      balanceAfter: paid.balanceAfter,
    }
    await Promise.all([
      remember(jobId, device.fingerprint, 'generate_post', response, paid.charged),
      UsageLog.create({
        fingerprint: device.fingerprint,
        jobId,
        action: 'generate_post',
        inputSize: 1,
        creditCharged: paid.charged,
        aiProvider: result.provider,
        aiModel: result.model,
        promptTokens: result.usage.promptTokens,
        completionTokens: result.usage.completionTokens,
        durationMs: Date.now() - started,
        status: 'success',
        ip: request.ip,
        appVersion: device.appVersion,
      }),
    ])
    return response
  })
}

/** Bản dịch lại chỉ được nhận khi thật sự sửa được lý do bị cờ. */
function accept(item, text) {
  const next = String(text || '').trim()
  if (!next) return false
  if (containsCjk(next)) return false
  if (item.reason === 'over_budget') {
    if (item.max_chars && next.length > item.max_chars * 1.25) return false
    return next.length < String(item.current || '').length
  }
  return true
}
