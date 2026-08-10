'use strict'

/**
 * Kiểm thử phần thuần của tích hợp PayOS (không cần MongoDB, không gọi mạng):
 * chữ ký request, verify chữ ký webhook, ánh xạ orderCode ↔ payosOrderCode.
 *
 * Chạy:  node --test tests/
 */
const test = require('node:test')
const assert = require('node:assert')
const crypto = require('node:crypto')

// Khóa giả cố định để test — không phải khóa thật.
const CHECKSUM_KEY = 'test-checksum-key-0123456789abcdef'
process.env.PAYOS_CLIENT_ID = 'test-client'
process.env.PAYOS_API_KEY = 'test-api-key'
process.env.PAYOS_CHECKSUM_KEY = CHECKSUM_KEY

const payos = require('../src/services/payos.service')

function hmac(raw) {
  return crypto.createHmac('sha256', CHECKSUM_KEY).update(raw).digest('hex')
}

// ------------------------------------------------------ chữ ký tạo link ---

test('signCreateRequest ký đúng 5 trường theo thứ tự alphabet', () => {
  const params = {
    amount: 10000,
    cancelUrl: 'https://example.com/thanh-toan/VOX123456?huy=1',
    description: 'VOX123456',
    orderCode: 123456,
    returnUrl: 'https://example.com/thanh-toan/VOX123456',
  }
  const expected = hmac(
    `amount=${params.amount}&cancelUrl=${params.cancelUrl}`
    + `&description=${params.description}&orderCode=${params.orderCode}`
    + `&returnUrl=${params.returnUrl}`,
  )
  assert.equal(payos.signCreateRequest(params), expected)
})

// ------------------------------------------------------ verify webhook ----

test('verifyWebhookSignature: chữ ký đúng thì nhận', () => {
  const data = {
    orderCode: 123456,
    amount: 10000,
    description: 'VOX123456',
    reference: 'FT123',
    transactionDateTime: '2026-08-07 10:00:00',
  }
  const raw = Object.keys(data).sort().map((k) => `${k}=${data[k]}`).join('&')
  assert.ok(payos.verifyWebhookSignature(data, hmac(raw)))
})

test('verifyWebhookSignature: sort key alphabet bất kể thứ tự trong payload', () => {
  // Cùng nội dung, thứ tự key khác nhau → cùng một chữ ký.
  const raw = 'amount=5000&orderCode=999999'
  const sig = hmac(raw)
  assert.ok(payos.verifyWebhookSignature({ orderCode: 999999, amount: 5000 }, sig))
  assert.ok(payos.verifyWebhookSignature({ amount: 5000, orderCode: 999999 }, sig))
})

test('verifyWebhookSignature: null/undefined thành chuỗi rỗng', () => {
  const data = { amount: 5000, note: null, orderCode: 999999 }
  const raw = 'amount=5000&note=&orderCode=999999'
  assert.ok(payos.verifyWebhookSignature(data, hmac(raw)))
})

test('verifyWebhookSignature: chữ ký sai hoặc thiếu thì từ chối', () => {
  const data = { amount: 5000, orderCode: 999999 }
  assert.ok(!payos.verifyWebhookSignature(data, 'deadbeef'))
  assert.ok(!payos.verifyWebhookSignature(data, ''))
  assert.ok(!payos.verifyWebhookSignature(null, 'abc'))
})

test('verifyWebhookSignature: đổi một trường là chữ ký cũ vô hiệu', () => {
  const data = { amount: 5000, orderCode: 999999 }
  const sig = hmac('amount=5000&orderCode=999999')
  assert.ok(!payos.verifyWebhookSignature({ ...data, amount: 6000 }, sig))
})

// -------------------------------------------- orderCode ↔ payosOrderCode --

test('orderCode VOX\\d{6} ánh xạ 1-1 sang số cho PayOS', () => {
  const { generateOrderCode } = require('../src/utils/keycode')
  for (let i = 0; i < 500; i += 1) {
    const code = generateOrderCode()
    assert.match(code, /^VOX\d{6}$/)
    assert.equal(code.length, 9, 'description PayOS giới hạn 9 ký tự')
    const numeric = Number(code.slice(3))
    assert.ok(Number.isInteger(numeric) && numeric >= 0 && numeric <= 999999)
    // Khôi phục lại được chuỗi gốc → ánh xạ không mất thông tin.
    assert.equal(`VOX${String(numeric).padStart(6, '0')}`, code)
  }
})

test('isConfigured đúng khi đủ 3 khóa', () => {
  assert.ok(payos.isConfigured())
})
