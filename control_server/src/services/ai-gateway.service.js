'use strict'

/**
 * AI Gateway — lớp DUY NHẤT trong hệ thống được biết provider/model/key.
 *
 * App gửi câu thoại thô; ở đây chọn provider theo `priority`, dựng prompt nội
 * bộ, gọi mô hình, đọc kết quả, và trả về đúng phần bản dịch. Không một
 * trường nào về provider, model, token hay chi phí được đưa vào response.
 *
 * Provider lỗi thì tự rơi xuống provider kế tiếp cùng `role` — đổi nhà cung
 * cấp hay hết hạn mức không làm gián đoạn người dùng.
 */
const axios = require('axios')

const AiProvider = require('../models/AiProvider')
const { decrypt } = require('../utils/crypto')
const {
  parseResponseSegments, parseJsonObject, mergeTranslations, containsCjk,
} = require('../utils/json-repair')
const prompts = require('../prompts/translate')

class AiError extends Error {
  constructor(code, message, statusCode = 503) {
    super(message)
    this.name = 'AiError'
    this.code = code
    this.statusCode = statusCode
  }
}

const PROVIDER_CACHE_TTL_MS = 60_000
const providerCache = new Map()   // role -> { list, expiresAt }

/** Provider đang bật của một vai trò, đã sắp theo ưu tiên. */
async function providersFor(role) {
  const hit = providerCache.get(role)
  if (hit && hit.expiresAt > Date.now()) return hit.list
  const list = await AiProvider.find({ role, enabled: true })
    .sort({ priority: 1 }).lean()
  providerCache.set(role, { list, expiresAt: Date.now() + PROVIDER_CACHE_TTL_MS })
  return list
}

function invalidateProviders() { providerCache.clear() }

// ------------------------------------------------------------ gọi mô hình ---

function openAiHeaders(provider, apiKey) {
  const headers = {
    Authorization: `Bearer ${apiKey}`,
    'Content-Type': 'application/json',
  }
  const host = String(provider.baseUrl || '')
  if (host.includes('anthropic.com')) {
    headers['x-api-key'] = apiKey
    headers['anthropic-version'] = '2023-06-01'
  } else if (host.includes('openrouter.ai')) {
    headers['HTTP-Referer'] = 'https://example.com'
    headers['X-Title'] = 'VoxDub Studio'
  }
  return headers
}

/**
 * Một lượt gọi `/chat/completions`. Trả về { content, usage }.
 *
 * 429 → chờ tăng dần rồi thử lại; 5xx → chờ ngắn hơn; 401/403/404 → hỏng cấu
 * hình, báo ngay để rơi xuống provider dự phòng thay vì thử lại vô ích.
 */
async function callOpenAiCompat(provider, { system, user, schema, maxRetries = 2 }) {
  const apiKey = decrypt(provider.apiKeyEnc)
  if (!apiKey) throw new AiError('PROVIDER_MISCONFIGURED', `Provider ${provider.name} chưa có API key`)
  if (!provider.baseUrl || !provider.model) {
    throw new AiError('PROVIDER_MISCONFIGURED', `Provider ${provider.name} thiếu baseUrl/model`)
  }

  const url = provider.baseUrl.replace(/\/+$/, '').endsWith('/chat/completions')
    ? provider.baseUrl
    : `${provider.baseUrl.replace(/\/+$/, '')}/chat/completions`

  const payload = {
    model: provider.model,
    temperature: provider.temperature,
    max_tokens: provider.maxTokens,
    response_format: schema
      ? { type: 'json_schema', json_schema: { name: 'result', strict: true, schema } }
      : { type: 'json_object' },
    messages: [
      { role: 'system', content: system },
      { role: 'user', content: user },
    ],
  }
  if (provider.disableReasoning && url.includes('openrouter.ai')) {
    payload.reasoning = { enabled: false }
  }

  let lastError = ''
  let attempt = 0
  while (attempt < Math.max(1, maxRetries)) {
    let resp
    try {
      resp = await axios.post(url, payload, {
        headers: openAiHeaders(provider, apiKey),
        timeout: provider.timeoutMs || 180_000,
        validateStatus: () => true,
      })
    } catch (err) {
      lastError = `${err.code || 'NETWORK'}: ${err.message}`
      attempt += 1
      if (attempt >= maxRetries) break
      await sleep(Math.min(2 ** attempt * 1000, 8000))
      continue
    }

    if (resp.status === 200) return readOpenAiReply(resp.data, provider)

    if (resp.status === 429) {
      attempt += 1
      if (attempt >= maxRetries) {
        throw new AiError('RATE_LIMITED', `${provider.name} hết hạn mức (429)`)
      }
      await sleep(Math.min(2 ** attempt * 3000, 20_000))
      continue
    }
    if ([400, 401, 403, 404, 402].includes(resp.status)) {
      // Cấu hình sai hoặc hết tiền — thử lại cũng vậy, rơi xuống provider sau.
      const detail = typeof resp.data === 'string'
        ? resp.data.slice(0, 200) : JSON.stringify(resp.data || {}).slice(0, 200)
      throw new AiError('PROVIDER_REJECTED',
        `${provider.name} từ chối request (HTTP ${resp.status}): ${detail}`)
    }
    lastError = `HTTP ${resp.status}`
    attempt += 1
    if (attempt >= maxRetries) break
    await sleep(Math.min(2 ** attempt * 2000, 15_000))
  }
  throw new AiError('PROVIDER_UNAVAILABLE',
    `Không gọi được ${provider.name} sau ${maxRetries} lần — ${lastError}`)
}

function readOpenAiReply(data, provider) {
  const choice = data && data.choices && data.choices[0]
  const content = choice && choice.message && choice.message.content
  if (!content || !String(content).trim()) {
    throw new AiError('EMPTY_RESPONSE', `${provider.name} trả về nội dung rỗng`)
  }
  if (choice.finish_reason === 'length') {
    // Bị cắt vì chạm trần token đầu ra ⇒ JSON chắc chắn hỏng. Báo lỗi để lớp
    // trên chia đôi lô (đầu vào nhỏ hơn thì đầu ra lọt dưới trần).
    throw new AiError('TRUNCATED', `${provider.name} cắt phản hồi giữa chừng`)
  }
  const usage = data.usage || {}
  return {
    content: String(content),
    usage: {
      promptTokens: usage.prompt_tokens || 0,
      completionTokens: usage.completion_tokens || 0,
    },
  }
}

/** Google Gemini — API riêng, không tương thích OpenAI. */
async function callGemini(provider, { system, user, schema, maxRetries = 2 }) {
  const apiKey = decrypt(provider.apiKeyEnc)
  if (!apiKey) throw new AiError('PROVIDER_MISCONFIGURED', `Provider ${provider.name} chưa có API key`)

  const base = provider.baseUrl || 'https://generativelanguage.googleapis.com/v1beta'
  const url = `${base.replace(/\/+$/, '')}/models/${provider.model}:generateContent`
  const generationConfig = {
    temperature: provider.temperature,
    maxOutputTokens: provider.maxTokens,
    responseMimeType: 'application/json',
  }
  if (schema) generationConfig.responseSchema = toGeminiSchema(schema)

  const payload = {
    systemInstruction: { parts: [{ text: system }] },
    contents: [{ role: 'user', parts: [{ text: user }] }],
    generationConfig,
  }

  let lastError = ''
  for (let attempt = 0; attempt < Math.max(1, maxRetries); attempt += 1) {
    let resp
    try {
      resp = await axios.post(url, payload, {
        headers: { 'Content-Type': 'application/json', 'x-goog-api-key': apiKey },
        timeout: provider.timeoutMs || 180_000,
        validateStatus: () => true,
      })
    } catch (err) {
      lastError = `${err.code || 'NETWORK'}: ${err.message}`
      await sleep(Math.min(2 ** (attempt + 1) * 1000, 8000))
      continue
    }
    if (resp.status === 200) {
      const cand = resp.data && resp.data.candidates && resp.data.candidates[0]
      const text = cand && cand.content && cand.content.parts
        && cand.content.parts.map((p) => p.text || '').join('')
      if (!text || !text.trim()) {
        throw new AiError('EMPTY_RESPONSE', `${provider.name} trả về nội dung rỗng`)
      }
      if (cand.finishReason === 'MAX_TOKENS') {
        throw new AiError('TRUNCATED', `${provider.name} cắt phản hồi giữa chừng`)
      }
      const um = resp.data.usageMetadata || {}
      return {
        content: text,
        usage: {
          promptTokens: um.promptTokenCount || 0,
          completionTokens: um.candidatesTokenCount || 0,
        },
      }
    }
    if ([400, 401, 403, 404].includes(resp.status)) {
      throw new AiError('PROVIDER_REJECTED',
        `${provider.name} từ chối request (HTTP ${resp.status})`)
    }
    lastError = `HTTP ${resp.status}`
    await sleep(Math.min(2 ** (attempt + 1) * 2000, 15_000))
  }
  throw new AiError('PROVIDER_UNAVAILABLE', `Không gọi được ${provider.name} — ${lastError}`)
}

/** JSON Schema → lược đồ Gemini (không nhận `additionalProperties`). */
function toGeminiSchema(schema) {
  if (!schema || typeof schema !== 'object') return schema
  if (Array.isArray(schema)) return schema.map(toGeminiSchema)
  const out = {}
  for (const [k, v] of Object.entries(schema)) {
    if (k === 'additionalProperties') continue
    out[k] = (v && typeof v === 'object') ? toGeminiSchema(v) : v
  }
  return out
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

/**
 * Gọi mô hình qua provider ưu tiên nhất còn dùng được.
 *
 * Trả về { content, usage, provider }. Provider nào lỗi thì ghi lại lý do
 * (để admin nhìn thấy trong dashboard) rồi thử provider kế tiếp; hết provider
 * mới ném lỗi lên trên.
 */
async function callWithFallback(role, args) {
  const list = await providersFor(role)
  if (!list.length) {
    throw new AiError('NO_PROVIDER',
      `Chưa cấu hình nơi gọi mô hình cho "${role}". Thêm qua /v1/admin/providers.`, 503)
  }

  let lastError = null
  for (const provider of list) {
    try {
      const result = provider.type === 'google'
        ? await callGemini(provider, args)
        : await callOpenAiCompat(provider, args)
      AiProvider.updateOne({ _id: provider._id },
        { $set: { lastOkAt: new Date(), lastError: '' } }).catch(() => {})
      return { ...result, provider }
    } catch (err) {
      lastError = err
      AiProvider.updateOne({ _id: provider._id }, {
        $set: { lastErrorAt: new Date(), lastError: String(err.message).slice(0, 300) },
      }).catch(() => {})
    }
  }
  throw lastError || new AiError('AI_UNAVAILABLE', 'Không nơi nào phản hồi')
}

// ---------------------------------------------------------------- dịch lô ---

/**
 * Dịch một lô câu. Trả về { segments, usage, provider, model }.
 *
 * Thiếu câu thì chia đôi lô rồi thử lại đúng phần thiếu — mô hình yếu hay
 * nghẹn ở lô lớn, và một lô 60 câu thiếu 2 câu không đáng phải dịch lại cả 60.
 * Hết hạn mức (RATE_LIMITED) thì KHÔNG chia đôi: chia đôi làm số request tăng
 * gấp đôi, đúng thứ đang bị chặn.
 */
async function translateBatch({ segments, sourceLang, targetField, context,
  cpsBudget, prevContext = [], maxRetries = 2, depth = 0 }) {
  const system = prompts.buildTranslateSystemPrompt({
    sourceLang, targetField, context, cpsBudget,
  })
  const user = prompts.buildTranslateUserPrompt({ segments, targetField, prevContext })
  const schema = prompts.translateSchema(targetField)

  const { content, usage, provider } = await callWithFallback('translate',
    { system, user, schema, maxRetries })
  const returned = parseResponseSegments(content)
  const { merged, missing } = mergeTranslations(segments, returned, targetField)

  if (!missing.length) {
    return { segments: merged, usage, provider: provider.name, model: provider.model }
  }
  if (segments.length === 1 || depth >= 3) {
    // Không chia nhỏ hơn được nữa — trả về phần dịch được, lớp trên quyết
    // định (câu thiếu sẽ được app giữ nguyên bản gốc).
    return { segments: merged, usage, provider: provider.name, model: provider.model, missing }
  }

  const missingSet = new Set(missing.map(String))
  const rest = segments.filter((s) => missingSet.has(String(s.id)))
  const mid = Math.floor(rest.length / 2) || 1
  const halves = [rest.slice(0, mid), rest.slice(mid)].filter((h) => h.length)

  const results = await Promise.all(halves.map((half) => translateBatch({
    segments: half, sourceLang, targetField, context, cpsBudget,
    prevContext, maxRetries, depth: depth + 1,
  }).catch(() => null)))

  const extra = []
  let extraPrompt = 0
  let extraCompletion = 0
  for (const r of results) {
    if (!r) continue
    extra.push(...r.segments)
    extraPrompt += r.usage.promptTokens
    extraCompletion += r.usage.completionTokens
  }

  const byId = new Map([...merged, ...extra].map((s) => [String(s.id), s]))
  const ordered = segments.map((s) => byId.get(String(s.id))).filter(Boolean)
  return {
    segments: ordered,
    usage: {
      promptTokens: usage.promptTokens + extraPrompt,
      completionTokens: usage.completionTokens + extraCompletion,
    },
    provider: provider.name,
    model: provider.model,
  }
}

/** Dịch lại các câu còn sót chữ Hán (lưới cuối trước khi trả về app). */
async function fixCjkLeftovers({ merged, sourceLang, targetField, context, cpsBudget }) {
  const bad = merged.filter((s) => containsCjk(s[targetField]))
  if (!bad.length) return { segments: merged, usage: { promptTokens: 0, completionTokens: 0 } }

  const system = prompts.buildTranslateSystemPrompt({ sourceLang, targetField, context, cpsBudget })
  const schema = prompts.translateSchema(targetField)
  let promptTokens = 0
  let completionTokens = 0

  const fixes = await Promise.all(bad.map(async (seg) => {
    const user = 'Your previous translation still contained Chinese characters: '
      + `${JSON.stringify(seg[targetField])}\n`
      + `Translate this ONE segment again. "${targetField}" must be pure Vietnamese `
      + '(Latin script only). Return ONLY JSON: '
      + `{"segments": [{"id": ..., "${targetField}": "..."}]}\n\n`
      + JSON.stringify({ id: seg.id })
    try {
      const { content, usage } = await callWithFallback('translate',
        { system, user, schema, maxRetries: 2 })
      promptTokens += usage.promptTokens
      completionTokens += usage.completionTokens
      const returned = parseResponseSegments(content)
      const text = returned[0] && String(returned[0][targetField] || '').trim()
      if (text && !containsCjk(text)) return [seg.id, text]
    } catch {
      // Giữ bản cũ — giọng đọc sẽ bỏ qua ký tự lạ, còn hơn mất cả câu.
    }
    return null
  }))

  const fixed = new Map(fixes.filter(Boolean))
  const segments = merged.map((s) => (
    fixed.has(s.id) ? { ...s, [targetField]: fixed.get(s.id) } : s
  ))
  return { segments, usage: { promptTokens, completionTokens } }
}

/** Phân tích ngữ cảnh video (lượt 0). Trả về dict hoặc null. */
async function analyze({ lines, sourceLang, videoTitle }) {
  const user = prompts.buildAnalysisPrompt({ lines, sourceLang, videoTitle })
  const { content, usage, provider } = await callWithFallback('translate', {
    system: prompts.ANALYSIS_SYSTEM,
    user,
    schema: prompts.ANALYSIS_SCHEMA,
    maxRetries: 2,
  })
  const data = parseJsonObject(content)
  return { analysis: data, usage, provider: provider.name, model: provider.model }
}

/** Rà soát và dịch lại một câu nghi vấn. */
async function reviewOne({ segment, reason, neighbors, sourceLang, targetField,
  context, cpsBudget }) {
  const system = prompts.buildTranslateSystemPrompt({ sourceLang, targetField, context, cpsBudget })
  const user = prompts.buildReviewUserPrompt({ segment, reason, targetField, neighbors })
  const { content, usage } = await callWithFallback('translate', {
    system, user, schema: prompts.translateSchema(targetField), maxRetries: 2,
  })
  const returned = parseResponseSegments(content)
  const text = returned[0] && String(returned[0][targetField] || '').trim()
  return { text: text || '', usage }
}

// ------------------------------------------------------ nội dung đăng bài ---

// Emoji và ký hiệu trang trí — người dùng cấm tuyệt đối, prompt đã dặn nhưng
// mô hình vẫn hay lỡ tay, nên đây là lớp bảo đảm cuối.
const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2700}-\u{27BF}\u{2600}-\u{26FF}\u{1F1E6}-\u{1F1FF}\u{FE00}-\u{FE0F}\u{1F3FB}-\u{1F3FF}\u{200D}\u{20E3}\u{2B00}-\u{2BFF}\u{2190}-\u{21FF}\u{2500}-\u{25FF}]+/gu

function stripEmoji(value) {
  if (typeof value === 'string') {
    const cleaned = value.replace(EMOJI_RE, '')
    return cleaned === value ? value : cleaned.split(/\s+/).filter(Boolean).join(' ')
  }
  if (Array.isArray(value)) return value.map(stripEmoji)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, stripEmoji(v)]))
  }
  return value
}

async function generatePost({ scriptOriginal, scriptVi, videoTitle }) {
  const user = prompts.buildContentPrompt({ scriptOriginal, scriptVi, videoTitle })
  // Vai trò "content" có provider riêng thì dùng; chưa cấu hình thì dùng
  // chung với dịch (một provider chạy được cả hai việc).
  const contentProviders = await providersFor('content')
  const role = contentProviders.length ? 'content' : 'translate'
  const { content, usage, provider } = await callWithFallback(role, {
    system: prompts.CONTENT_SYSTEM,
    user,
    schema: prompts.CONTENT_SCHEMA,
    maxRetries: 3,
  })
  const data = parseJsonObject(content)
  if (!data) throw new AiError('BAD_AI_RESPONSE', 'Không đọc được nội dung đăng bài', 502)
  return { metadata: stripEmoji(data), usage, provider: provider.name, model: provider.model }
}

module.exports = {
  AiError,
  translateBatch,
  fixCjkLeftovers,
  analyze,
  reviewOne,
  generatePost,
  invalidateProviders,
  providersFor,
}
