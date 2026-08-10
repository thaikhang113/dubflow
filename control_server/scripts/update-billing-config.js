'use strict'

/**
 * Cập nhật GIÁ BÁN trên DB đang chạy. Seed dùng $setOnInsert nên KHÔNG đè
 * giá trị cũ — script này force-$set đúng 2 khóa liên quan bảng giá:
 *     credit.packages   (danh sách gói bán sẵn)
 *     order.min.vnd     (số tiền tối thiểu khi mua tùy chỉnh)
 * lấy từ DEFAULTS trong src/services/config.service.js — nguồn sự thật duy nhất.
 *
 * Chạy khi đổi bảng giá:  npm run billing:update
 * Có hiệu lực trong vòng 60 giây (TTL cache config), không cần restart.
 */
require('dotenv').config({ path: `${__dirname}/../.env` })

const mongoose = require('mongoose')

const AppConfig = require('../src/models/AppConfig')
const { DEFAULTS } = require('../src/services/config.service')

const KEYS = ['credit.packages', 'order.min.vnd']

async function main() {
  await mongoose.connect(process.env.MONGODB_URI)

  for (const key of KEYS) {
    await AppConfig.updateOne(
      { key },
      { $set: { key, value: DEFAULTS[key] } },
      { upsert: true },
    )
    console.log(`  = ${key} → ${JSON.stringify(DEFAULTS[key])}`)
  }

  await mongoose.connection.close()
  console.log('Xong. Server áp dụng trong tối đa 60 giây (không cần restart).')
}

main().catch((err) => { console.error(err); process.exit(1) })
