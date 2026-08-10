'use strict'

/**
 * Gửi email (Brevo SMTP) — chỉ dùng để gửi mã kích hoạt sau khi thanh toán.
 *
 * Không cấu hình SMTP thì mọi lời gọi ở đây thành no-op: mã vẫn hiện trên
 * trang thanh toán, email chỉ là bản sao lưu tiện lợi. Không được để việc
 * gửi mail hỏng làm hỏng luồng cấp key.
 */
const nodemailer = require('nodemailer')

let transporter = null
let configured = null

function getTransport() {
  if (configured !== null) return transporter
  const host = (process.env.BREVO_SMTP_HOST || '').trim()
  const user = (process.env.BREVO_SMTP_USER || '').trim()
  const pass = (process.env.BREVO_SMTP_PASS || '').trim()
  configured = Boolean(host && user && pass)
  if (configured) {
    transporter = nodemailer.createTransport({
      host,
      port: Number(process.env.BREVO_SMTP_PORT) || 587,
      secure: false,
      auth: { user, pass },
    })
  }
  return transporter
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ))
}

async function sendActivationKey({ to, keyCode, vox, orderCode, amountVnd }) {
  const tx = getTransport()
  if (!tx || !to) return false

  const web = (process.env.PUBLIC_URL || 'http://localhost:3001').replace(/\/+$/, '')
  const html = `
<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
  <h2 style="margin:0 0 8px">Thanh toán thành công</h2>
  <p style="margin:0 0 20px;color:#555">Cảm ơn bạn đã mua credit VoxDub Studio.</p>
  <div style="border:1px solid #e0e0e0;border-radius:12px;padding:20px;margin-bottom:20px">
    <p style="margin:0 0 6px;color:#666;font-size:13px">MÃ KÍCH HOẠT</p>
    <p style="margin:0 0 16px;font-size:24px;font-weight:700;letter-spacing:2px;font-family:ui-monospace,Consolas,monospace">${escapeHtml(keyCode)}</p>
    <p style="margin:0;color:#444;font-size:14px">
      Số Vox: <b>${Number(vox).toLocaleString('vi-VN')}</b><br>
      Đơn hàng: ${escapeHtml(orderCode)} · ${Number(amountVnd).toLocaleString('vi-VN')} đ
    </p>
  </div>
  <p style="margin:0 0 8px"><b>Cách kích hoạt:</b></p>
  <ol style="margin:0 0 20px;padding-left:20px;color:#444;line-height:1.7">
    <li>Mở VoxDub Studio trên máy tính</li>
    <li>Vào mục <b>Tài khoản</b> ở thanh bên</li>
    <li>Dán mã trên vào ô "Mã kích hoạt" rồi bấm <b>Kích hoạt</b></li>
  </ol>
  <p style="margin:0 0 20px;padding:12px;background:#fff8e6;border-radius:8px;color:#7a5b00;font-size:13px">
    Mã này chỉ kích hoạt được <b>một lần trên một máy</b>. Giữ mã cho riêng bạn.
  </p>
  <p style="margin:0;color:#888;font-size:13px">
    Cần hỗ trợ? Trả lời email này hoặc truy cập <a href="${web}" style="color:#4a6cf7">${web}</a>
  </p>
</div>`

  try {
    await tx.sendMail({
      from: process.env.MAIL_FROM || 'VoxDub Studio <noreply@example.com>',
      to,
      subject: `Mã kích hoạt VoxDub — ${keyCode}`,
      text: `Mã kích hoạt: ${keyCode}\nSố Vox: ${vox}\nĐơn hàng: ${orderCode}\n\n`
        + 'Mở VoxDub Studio > Tài khoản > dán mã > Kích hoạt.\n'
        + 'Mã chỉ dùng được một lần trên một máy.',
      html,
    })
    return true
  } catch {
    return false
  }
}

module.exports = { sendActivationKey, isConfigured: () => Boolean(getTransport()) }
