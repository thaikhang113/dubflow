'use strict'

/**
 * Nạp cấu hình mặc định + provider đầu tiên. Chạy một lần sau khi deploy:
 *     node scripts/seed-config.js
 *
 * Chạy lại an toàn: không ghi đè giá trị đã có trong DB, chỉ thêm khóa còn
 * thiếu. Provider cũng vậy — sửa key qua Admin API, không sửa qua script này.
 */
require('dotenv').config({ path: `${__dirname}/../.env` })

const mongoose = require('mongoose')

const AppConfig = require('../src/models/AppConfig')
const AiProvider = require('../src/models/AiProvider')
const { DEFAULTS } = require('../src/services/config.service')
const { encrypt } = require('../src/utils/crypto')

const DESCRIPTIONS = {
  'credit.enabled': 'Bật/tắt toàn bộ hệ thống credit (false = mọi thứ miễn phí)',
  'credit.vox.to.vnd': 'Tỷ giá: 1 Vox = ? VND (dùng cho số tiền tùy chỉnh)',
  'trial.vox': 'Số Vox tặng lần đầu mỗi thiết bị (0 = tắt)',
  'credit.cost.segment.base': 'GIÁ CÔNG KHAI: Vox mỗi segment, luôn thu',
  'credit.cost.segment.autotranslate':
    'GIÁ CÔNG KHAI: Vox cộng thêm mỗi segment khi bật dịch tự động',
  'credit.cost.metadata': 'GIÁ CÔNG KHAI: Vox trọn gói tiêu đề + mô tả mỗi video',
  'internal.cost.translate.per_sentence':
    'Giá nội bộ (đối soát biên lợi nhuận) — không trừ ví khi có hold',
  'internal.cost.analyze': 'Giá nội bộ mỗi lượt phân tích ngữ cảnh',
  'internal.cost.review.per_sentence': 'Giá nội bộ mỗi câu được rà soát và sửa',
  'internal.cost.generate_post': 'Giá nội bộ mỗi lượt viết tiêu đề + mô tả',
  'maintenance.mode': 'Bật để chặn mọi request AI',
  'maintenance.message': 'Thông báo hiện trong app khi bảo trì',
  'min.app.version': 'Phiên bản app tối thiểu được phép chạy',
  'force.update.version': 'Buộc cập nhật lên phiên bản này ("" = tắt)',
  'ai.max.segments.per.request': 'Trần cứng số câu mỗi request dịch',
  'ai.max.chars.per.segment': 'Trần cứng độ dài một câu',
  'ai.max.retries': 'Số lần thử lại mỗi provider',
  'order.min.vnd': 'Số tiền tối thiểu khi mua tùy chỉnh',
  'order.max.vnd': 'Số tiền tối đa khi mua tùy chỉnh',
  'order.expire.minutes': 'Đơn hàng hết hạn sau bao nhiêu phút',
  'credit.packages': 'Danh sách gói bán sẵn trên website',
}

async function main() {
  await mongoose.connect(process.env.MONGODB_URI)

  let added = 0
  for (const [key, value] of Object.entries(DEFAULTS)) {
    const result = await AppConfig.updateOne(
      { key },
      { $setOnInsert: { key, value, description: DESCRIPTIONS[key] || '' } },
      { upsert: true },
    )
    if (result.upsertedCount) { added += 1; console.log(`  + ${key}`) }
  }
  console.log(`AppConfig: thêm ${added} khóa mới, giữ nguyên ${Object.keys(DEFAULTS).length - added} khóa đã có.`)

  const seedKey = (process.env.SEED_OPENROUTER_API_KEY || '').trim()
  if (seedKey) {
    const exists = await AiProvider.findOne({ name: 'openrouter' })
    if (exists) {
      console.log('AiProvider "openrouter" đã tồn tại — bỏ qua (sửa qua Admin API).')
    } else {
      await AiProvider.create({
        name: 'openrouter',
        label: 'OpenRouter',
        role: 'translate',
        type: 'openai_compat',
        baseUrl: 'https://openrouter.ai/api/v1',
        apiKeyEnc: encrypt(seedKey),
        model: process.env.SEED_OPENROUTER_MODEL || 'google/gemini-2.5-flash',
        temperature: 0.3,
        maxTokens: 16384,
        priority: 1,
        enabled: true,
      })
      console.log('AiProvider: đã thêm "openrouter".')
    }
  } else {
    console.log('Không có SEED_OPENROUTER_API_KEY — thêm provider qua POST /v1/admin/providers.')
  }

  await mongoose.connection.close()
  console.log('Xong.')
}

main().catch((err) => { console.error(err); process.exit(1) })
