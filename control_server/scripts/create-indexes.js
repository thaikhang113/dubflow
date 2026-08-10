'use strict'

/**
 * Tạo toàn bộ index MongoDB. Chạy một lần khi deploy:
 *     node scripts/create-indexes.js
 *
 * Mongoose tự tạo index lúc chạy (`autoIndex`), nhưng làm thế trên production
 * nghĩa là index được dựng lúc request đầu tiên tới — chậm và khó đoán. Chạy
 * tường minh ở đây rồi tắt autoIndex là cách đúng.
 */
require('dotenv').config({ path: `${__dirname}/../.env` })

const mongoose = require('mongoose')

const MODELS = [
  '../src/models/Device',
  '../src/models/ActivationKey',
  '../src/models/CreditLedger',
  '../src/models/Order',
  '../src/models/AiProvider',
  '../src/models/AppConfig',
  '../src/models/UsageLog',
  '../src/models/AuditLog',
  '../src/models/JobResult',
]

async function main() {
  await mongoose.connect(process.env.MONGODB_URI)
  for (const path of MODELS) {
    const Model = require(path)
    await Model.syncIndexes()
    const indexes = await Model.collection.indexes()
    console.log(`  ${Model.modelName}: ${indexes.length} index`)
  }
  await mongoose.connection.close()
  console.log('Xong.')
}

main().catch((err) => { console.error(err); process.exit(1) })
