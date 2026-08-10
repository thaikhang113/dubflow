'use strict'

/**
 * Mã hóa API key của AI provider trước khi lưu DB (AES-256-GCM).
 *
 * Định dạng chuỗi lưu: `iv:tag:ciphertext`, tất cả hex. GCM có thẻ xác thực
 * nên sửa một byte trong DB là giải mã thất bại chứ không ra rác âm thầm.
 */
const crypto = require('node:crypto')

const ALGORITHM = 'aes-256-gcm'

function key() {
  const hex = (process.env.APP_ENCRYPTION_KEY || '').trim()
  if (hex.length !== 64) {
    throw new Error(
      'APP_ENCRYPTION_KEY phải là 32 byte dạng hex (64 ký tự). ' +
      'Sinh bằng: openssl rand -hex 32')
  }
  return Buffer.from(hex, 'hex')
}

function encrypt(plain) {
  if (!plain) return ''
  const iv = crypto.randomBytes(12)   // 96-bit — kích thước chuẩn của GCM
  const cipher = crypto.createCipheriv(ALGORITHM, key(), iv)
  const enc = Buffer.concat([cipher.update(String(plain), 'utf8'), cipher.final()])
  return [iv.toString('hex'), cipher.getAuthTag().toString('hex'), enc.toString('hex')].join(':')
}

function decrypt(payload) {
  if (!payload) return ''
  const [ivHex, tagHex, dataHex] = String(payload).split(':')
  if (!ivHex || !tagHex || !dataHex) throw new Error('Chuỗi mã hóa sai định dạng')
  const decipher = crypto.createDecipheriv(ALGORITHM, key(), Buffer.from(ivHex, 'hex'))
  decipher.setAuthTag(Buffer.from(tagHex, 'hex'))
  return Buffer.concat([
    decipher.update(Buffer.from(dataHex, 'hex')),
    decipher.final(),
  ]).toString('utf8')
}

/** So sánh hai chuỗi bí mật không rò rỉ thời gian (chấp nhận khác độ dài). */
function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || !b) return false
  const ha = crypto.createHash('sha256').update(a).digest()
  const hb = crypto.createHash('sha256').update(b).digest()
  return crypto.timingSafeEqual(ha, hb)
}

module.exports = { encrypt, decrypt, safeEqual }
