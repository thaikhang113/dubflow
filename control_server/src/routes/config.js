'use strict'

/**
 * `/v1/config` — app gọi lúc khởi động.
 *
 * Trả về đúng những gì app cần biết để quyết định có chạy được không: bảo
 * trì, phiên bản tối thiểu, credit đang bật hay tắt, và đơn giá theo segment
 * (để app hiện tổng "video này tốn ~2.400 Vox" trước khi bấm chạy).
 *
 * Chỉ có ba con số giá, và đó là chủ ý: giá theo segment cộng gói tiêu đề+mô
 * tả là toàn bộ những gì người dùng cần biết. Chi phí từng lượt AI bên trong
 * là chuyện nội bộ của server, không lộ ra API public.
 *
 * KHÔNG cần token: app phải đọc được thông báo bảo trì kể cả khi chưa đăng
 * ký thiết bị.
 */
const config = require('../services/config.service')

module.exports = async function configRoutes(fastify) {
  fastify.get('/app', {
    config: { rateLimit: { max: 60, timeWindow: '1 minute' } },
  }, async () => {
    const cfg = await config.getMany([
      'credit.enabled', 'maintenance.mode', 'maintenance.message',
      'min.app.version', 'force.update.version',
      'credit.cost.segment.base', 'credit.cost.segment.autotranslate',
      'credit.cost.metadata',
      'ai.max.segments.per.request',
    ])
    return {
      creditEnabled: cfg['credit.enabled'],
      maintenanceMode: cfg['maintenance.mode'],
      maintenanceMessage: cfg['maintenance.message'],
      minAppVersion: cfg['min.app.version'],
      forceUpdateVersion: cfg['force.update.version'],
      maxSegmentsPerRequest: cfg['ai.max.segments.per.request'],
      pricing: {
        segmentBase: cfg['credit.cost.segment.base'],
        segmentAutoTranslate: cfg['credit.cost.segment.autotranslate'],
        metadata: cfg['credit.cost.metadata'],
      },
      webUrl: (process.env.PUBLIC_URL || 'http://localhost:3001').replace(/\/+$/, ''),
      serverVersion: '3.0.0',
    }
  })
}
