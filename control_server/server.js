'use strict'

/**
 * Điểm khởi động server VoxDub.
 *
 * Kiểm tra biến môi trường bắt buộc NGAY khi khởi động chứ không đợi request
 * đầu tiên: thiếu APP_ENCRYPTION_KEY mà chạy được thì mọi lượt gọi AI sẽ hỏng
 * lúc 3 giờ sáng thay vì hỏng ngay lúc deploy.
 */
require('dotenv').config()

const { build } = require('./src/app')

const REQUIRED = ['MONGODB_URI', 'JWT_SECRET', 'APP_ENCRYPTION_KEY']

function checkEnv() {
  const missing = REQUIRED.filter((k) => !(process.env[k] || '').trim())
  if (missing.length) {
    console.error(`[voxdub] Thiếu biến môi trường bắt buộc: ${missing.join(', ')}`)
    console.error('[voxdub] Xem control_server/.env.example')
    process.exit(1)
  }
  if ((process.env.APP_ENCRYPTION_KEY || '').trim().length !== 64) {
    console.error('[voxdub] APP_ENCRYPTION_KEY phải là 64 ký tự hex (openssl rand -hex 32)')
    process.exit(1)
  }
  if (!(process.env.ADMIN_TOKEN || '').trim()) {
    console.warn('[voxdub] CẢNH BÁO: chưa đặt ADMIN_TOKEN — /v1/admin/* sẽ trả 503.')
  }
}

async function main() {
  checkEnv()
  const app = await build()

  const port = Number(process.env.PORT) || 3001
  const host = process.env.HOST || '127.0.0.1'
  await app.listen({ port, host })

  // Sweeper hold quá hạn: bỏ ngang không xuất video thì sau TTL server tự
  // chốt (Vox đã tiêu là đã tiêu). Lỗi một vòng quét không được làm sập app.
  const holds = require('./src/services/hold.service')
  const config = require('./src/services/config.service')
  const sweepMinutes = Number(await config.get('hold.sweep.interval.minutes')) || 30
  const sweepTimer = setInterval(async () => {
    try {
      const done = await holds.expireSweep(app.log)
      if (done > 0) app.log.info({ done }, 'đã tự chốt hold quá hạn')
    } catch (err) {
      app.log.warn({ err }, 'vòng quét hold thất bại')
    }
  }, sweepMinutes * 60 * 1000)
  sweepTimer.unref()

  // Đối soát ví ↔ sổ cái mỗi ngày: chỉ đọc và báo (audit log + log server),
  // không tự sửa. Lệch tiền phải có người nhìn vào trước khi đụng ví.
  const credit = require('./src/services/credit.service')
  const reconcileTimer = setInterval(async () => {
    try {
      const { checked, mismatches } = await credit.reconcile()
      if (mismatches.length) {
        app.log.error({ mismatches }, `ĐỐI SOÁT: ${mismatches.length}/${checked} thiết bị lệch ví — xem audit log`)
      } else {
        app.log.info({ checked }, 'đối soát ví–sổ cái: khớp toàn bộ')
      }
    } catch (err) {
      app.log.warn({ err }, 'vòng đối soát thất bại')
    }
  }, 24 * 60 * 60 * 1000)
  reconcileTimer.unref()

  // Tắt êm: ngừng nhận request mới, cho request đang chạy kịp xong.
  for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, async () => {
      app.log.info(`Nhận ${sig} — đang tắt...`)
      await app.close()
      process.exit(0)
    })
  }
}

main().catch((err) => {
  console.error('[voxdub] Không khởi động được:', err)
  process.exit(1)
})
