'use strict'

/** Kết nối MongoDB một lần cho cả tiến trình, và đóng êm khi Fastify tắt. */
const fp = require('fastify-plugin')
const mongoose = require('mongoose')

module.exports = fp(async function mongoPlugin(fastify) {
  const uri = process.env.MONGODB_URI
  if (!uri) throw new Error('Thiếu MONGODB_URI trong .env')

  mongoose.set('strictQuery', true)
  await mongoose.connect(uri, {
    serverSelectionTimeoutMS: 10000,
    maxPoolSize: 20,
  })
  fastify.log.info('MongoDB đã kết nối')

  fastify.decorate('mongoose', mongoose)
  fastify.addHook('onClose', async () => { await mongoose.connection.close() })
})
