'use strict'

/**
 * Đăng ký URL webhook với PayOS. Chạy MỘT LẦN sau khi deploy (và chạy lại
 * nếu PUBLIC_URL đổi):
 *     npm run payos:confirm-webhook
 *
 * Điều kiện: server phải ĐANG CHẠY và PUBLIC_URL phải là HTTPS công khai —
 * PayOS sẽ bắn một request test vào URL để xác nhận trước khi chấp nhận.
 */
require('dotenv').config({ path: `${__dirname}/../.env` })

const payos = require('../src/services/payos.service')

async function main() {
  if (!payos.isConfigured()) {
    console.error('Thiếu PAYOS_CLIENT_ID / PAYOS_API_KEY / PAYOS_CHECKSUM_KEY trong .env')
    process.exit(1)
  }
  const publicUrl = String(process.env.PUBLIC_URL || '').replace(/\/$/, '')
  if (!publicUrl) {
    console.error('Thiếu PUBLIC_URL trong .env')
    process.exit(1)
  }
  const webhookUrl = `${publicUrl}/v1/billing/webhook/payos`
  console.log(`Đăng ký webhook: ${webhookUrl}`)
  try {
    const result = await payos.confirmWebhook(webhookUrl)
    console.log('Thành công:', JSON.stringify(result))
  } catch (err) {
    console.error('Thất bại:', err.message)
    if (err.detail) console.error(JSON.stringify(err.detail, null, 2))
    console.error('\nKiểm tra: server đang chạy? PUBLIC_URL là HTTPS công khai?')
    process.exit(1)
  }
}

main()
