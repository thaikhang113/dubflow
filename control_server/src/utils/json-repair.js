'use strict'

/**
 * Đọc JSON do mô hình sinh ra — bản chuyển từ `autodub/text/translate_common.py`.
 *
 * Mô hình hay bọc câu trả lời trong ```json, chèn một câu dẫn, hoặc bị cắt
 * giữa chừng khi chạm trần token. Ba lớp xử lý (bóc fence → cắt lấy phần
 * giữa cặp ngoặc ngoài cùng → vá dấu đóng còn thiếu) cứu được gần hết các
 * trường hợp đó, thay vì vứt cả lô đã tốn tiền gọi.
 */

const CJK_RE = /[㐀-䶿一-鿿]/
const FENCE_RE = /^\s*```(?:json)?\s*|\s*```\s*$/gi

function containsCjk(text) {
  return CJK_RE.test(String(text || ''))
}

function stripFences(text) {
  return String(text || '').trim().replace(FENCE_RE, '').trim()
}

/** Cắt lấy phần từ dấu mở ngoặc đầu tiên tới dấu đóng cuối cùng. */
function sliceToPayload(text) {
  const starts = [text.indexOf('{'), text.indexOf('[')].filter((i) => i >= 0)
  if (!starts.length) return text
  const start = Math.min(...starts)
  const end = Math.max(text.lastIndexOf('}'), text.lastIndexOf(']'))
  return end > start ? text.slice(start, end + 1) : text.slice(start)
}

/**
 * Vá một khối JSON bị cắt giữa chừng để còn đọc được phần đã có.
 *
 * Câu trả lời chạm trần token đứt ngang: có thể đứt giữa một chuỗi, và chắc
 * chắn thiếu các dấu đóng ngoặc. Hàm này đóng nốt chúng theo đúng thứ tự đã
 * mở. Phần tử cuối bị đứt sẽ hỏng, nhưng những phần tử trước đó vẫn cứu được.
 */
function repairJson(input) {
  let text = sliceToPayload(stripFences(input)).replace(/\s+$/, '')
  if (!text) return text

  const stack = []
  let inString = false
  let escaped = false
  for (const ch of text) {
    if (inString) {
      if (escaped) escaped = false
      else if (ch === '\\') escaped = true
      else if (ch === '"') inString = false
      continue
    }
    if (ch === '"') inString = true
    else if (ch === '{' || ch === '[') stack.push(ch === '{' ? '}' : ']')
    else if ((ch === '}' || ch === ']') && stack.length) stack.pop()
  }

  if (inString) text += '"'
  // Bỏ phần đuôi dở dang: dấu phẩy treo, một khóa chưa có giá trị, hoặc một
  // khóa bị đứt trước cả dấu hai chấm.
  text = text.replace(/,\s*$/, '')
  text = text.replace(/,\s*"[^"]*"\s*:?\s*$/, '')
  text = text.replace(/\{\s*"[^"]*"\s*:?\s*$/, '{')
  return text + stack.reverse().join('')
}

/** Đọc câu trả lời thành mảng câu; ném lỗi khi hỏng hoàn toàn. */
function parseResponseSegments(content) {
  const raw = stripFences(content)
  for (const candidate of [raw, sliceToPayload(raw), repairJson(raw)]) {
    if (!candidate) continue
    let data
    try {
      data = JSON.parse(candidate)
    } catch {
      continue
    }
    if (data && typeof data === 'object' && !Array.isArray(data)) {
      data = data.segments !== undefined ? data.segments : data.data
    }
    if (Array.isArray(data)) {
      return data.filter((s) => s && typeof s === 'object')
    }
  }
  const err = new Error('Không đọc được kết quả dịch (JSON hỏng): '
    + raw.slice(0, 200).replace(/\n/g, ' '))
  err.code = 'BAD_AI_RESPONSE'
  throw err
}

/** Đọc một khối JSON object bất kỳ (phân tích ngữ cảnh, nội dung đăng bài). */
function parseJsonObject(content) {
  const raw = stripFences(content)
  for (const candidate of [raw, sliceToPayload(raw), repairJson(raw)]) {
    if (!candidate) continue
    try {
      const data = JSON.parse(candidate)
      if (data && typeof data === 'object' && !Array.isArray(data)) return data
    } catch {
      // thử ứng viên tiếp theo
    }
  }
  return null
}

const TERMINAL = ['.', '!', '?', '…', ':']

/** Chuẩn hóa một dòng dịch cho TTS: một khoảng trắng + dấu kết câu. */
function ensureTerminalPunct(text) {
  let s = String(text || '').split(/\s+/).filter(Boolean).join(' ')
  s = s.replace(/[,;\-–— ]+$/, '')
  if (s && !TERMINAL.some((t) => s.endsWith(t))) s += '.'
  return s
}

/**
 * Ghép bản dịch trả về vào đúng câu gốc theo `id`.
 *
 * Trả về `{ merged, missing }` thay vì ném lỗi: lớp gọi cần biết THIẾU câu
 * nào để chia đôi lô rồi thử lại phần thiếu, chứ không phải vứt cả lô.
 */
function mergeTranslations(batch, returned, targetField) {
  const byId = new Map()
  for (const item of returned) {
    const text = String(item[targetField] || '').trim()
    if (item.id === undefined || item.id === null || !text) continue
    const n = Number(item.id)
    byId.set(Number.isFinite(n) ? n : String(item.id), text)
  }

  // Mô hình bỏ mất id nhưng trả đúng số câu, đúng thứ tự — chấp nhận và ghép
  // theo vị trí, còn hơn ném đi cả một lô đã dịch xong.
  if (!byId.size && returned.length === batch.length) {
    batch.forEach((seg, i) => {
      const text = String(returned[i][targetField] || '').trim()
      if (text) byId.set(Number(seg.id), text)
    })
  }

  const merged = []
  const missing = []
  for (const seg of batch) {
    const text = byId.get(Number(seg.id)) ?? byId.get(String(seg.id))
    if (!text) { missing.push(seg.id); continue }
    merged.push({ id: seg.id, [targetField]: ensureTerminalPunct(text) })
  }
  return { merged, missing }
}

module.exports = {
  containsCjk,
  stripFences,
  sliceToPayload,
  repairJson,
  parseResponseSegments,
  parseJsonObject,
  ensureTerminalPunct,
  mergeTranslations,
}
