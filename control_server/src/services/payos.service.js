'use strict'

/**
 * PayOS (payos.vn) — cổng thanh toán chính thức thay cho SePay.
 *
 * Ba khóa trong .env: PAYOS_CLIENT_ID, PAYOS_API_KEY (header khi gọi API),
 * PAYOS_CHECKSUM_KEY (ký HMAC-SHA256 cho cả request lẫn webhook).
 *
 * Luồng: tạo đơn → gọi createPaymentLink → PayOS trả checkoutUrl + chuỗi
 * qrCode (payload VietQR, web tự render thành ảnh QR) → người dùng trả tiền
 * (QR/thẻ/ví) → PayOS bắn webhook kèm chữ ký → server verify + phát key.
 *
 * Lưu ý từ tài liệu PayOS:
 * - `orderCode` phải là SỐ nguyên duy nhất → dùng phần 6 chữ số của mã đơn
 *   ("VOX123456" → 123456), ánh xạ 1-1 vì orderCode string đã unique.
 * - `description` tối đa 9 ký tự với tài khoản ngân hàng thường → dùng luôn
 *   chuỗi "VOX123456" (đúng 9 ký tự).
 * - `expiredAt` là Unix timestamp tính bằng GIÂY.
 */
const crypto = require('node:crypto')
const axios = require('axios')

const { safeEqual } = require('../utils/crypto')

const BASE_URL = 'https://api-merchant.payos.vn'

function env() {
  return {
    clientId: (process.env.PAYOS_CLIENT_ID || '').trim(),
    apiKey: (process.env.PAYOS_API_KEY || '').trim(),
    checksumKey: (process.env.PAYOS_CHECKSUM_KEY || '').trim(),
  }
}

/** Đủ 3 khóa chưa — thiếu thì tạo đơn phải báo lỗi rõ ràng thay vì treo. */
function isConfigured() {
  const { clientId, apiKey, checksumKey } = env()
  return Boolean(clientId && apiKey && checksumKey)
}

function headers() {
  const { clientId, apiKey } = env()
  return { 'x-client-id': clientId, 'x-api-key': apiKey }
}

/**
 * Chữ ký cho request tạo link thanh toán.
 * PayOS quy định đúng 5 trường, đúng thứ tự alphabet, giá trị thô không
 * URL-encode: amount, cancelUrl, description, orderCode, returnUrl.
 */
function signCreateRequest({ amount, cancelUrl, description, orderCode, returnUrl }) {
  const raw = `amount=${amount}&cancelUrl=${cancelUrl}&description=${description}`
    + `&orderCode=${orderCode}&returnUrl=${returnUrl}`
  return crypto.createHmac('sha256', env().checksumKey).update(raw).digest('hex')
}

/**
 * Verify chữ ký webhook: sort key của `data` theo alphabet, nối thành
 * `key=value&...` (null/undefined → chuỗi rỗng, object/array → JSON đã sort
 * key con — khớp cách SDK chính thức serialize), rồi HMAC-SHA256.
 */
function verifyWebhookSignature(data, signature) {
  if (!data || typeof data !== 'object' || !signature) return false
  const raw = Object.keys(data).sort().map((k) => {
    let v = data[k]
    if (v === null || v === undefined || v === 'null' || v === 'undefined') v = ''
    else if (Array.isArray(v)) v = JSON.stringify(v.map(sortObjKeys))
    else if (typeof v === 'object') v = JSON.stringify(sortObjKeys(v))
    return `${k}=${v}`
  }).join('&')
  const expected = crypto.createHmac('sha256', env().checksumKey).update(raw).digest('hex')
  return safeEqual(expected, String(signature))
}

function sortObjKeys(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return obj
  const out = {}
  for (const k of Object.keys(obj).sort()) out[k] = obj[k]
  return out
}

class PayosError extends Error {
  constructor(message, detail = null) {
    super(message)
    this.name = 'PayosError'
    this.detail = detail
  }
}

/** Gọi API PayOS, bóc `data` khi code='00', ném PayosError khi thất bại. */
async function call(method, path, body = null) {
  let res
  try {
    res = await axios({
      method,
      url: `${BASE_URL}${path}`,
      headers: headers(),
      data: body || undefined,
      timeout: 20_000,
    })
  } catch (err) {
    const detail = err.response ? err.response.data : { message: err.message }
    throw new PayosError('Không gọi được PayOS', detail)
  }
  const payload = res.data || {}
  if (payload.code !== '00') {
    throw new PayosError(`PayOS từ chối: ${payload.desc || payload.code}`, payload)
  }
  return payload.data
}

/**
 * Tạo link thanh toán. Trả về data của PayOS:
 * { checkoutUrl, qrCode, paymentLinkId, accountNumber, accountName, bin,
 *   amount, description, orderCode, status, ... }
 */
async function createPaymentLink({ orderCode, amount, description, returnUrl, cancelUrl, expiredAt }) {
  const body = {
    orderCode,
    amount,
    description,
    returnUrl,
    cancelUrl,
    signature: signCreateRequest({ amount, cancelUrl, description, orderCode, returnUrl }),
  }
  if (expiredAt) body.expiredAt = expiredAt
  return call('post', '/v2/payment-requests', body)
}

/** Tra cứu link theo paymentLinkId hoặc orderCode số. */
async function getPaymentLink(id) {
  return call('get', `/v2/payment-requests/${id}`)
}

/** Hủy link thanh toán (đơn hết hạn / người dùng hủy). */
async function cancelPaymentLink(id, reason = '') {
  return call('post', `/v2/payment-requests/${id}/cancel`,
    reason ? { cancellationReason: reason } : {})
}

/** Đăng ký URL webhook với PayOS (chạy 1 lần sau deploy). */
async function confirmWebhook(webhookUrl) {
  return call('post', '/confirm-webhook', { webhookUrl })
}

module.exports = {
  PayosError,
  isConfigured,
  signCreateRequest,
  verifyWebhookSignature,
  createPaymentLink,
  getPaymentLink,
  cancelPaymentLink,
  confirmWebhook,
}
