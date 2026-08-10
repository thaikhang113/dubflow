'use strict'

/** Ghi AuditLog — best-effort, không bao giờ làm hỏng request chính. */
const AuditLog = require('../models/AuditLog')

async function log(entry) {
  try {
    await AuditLog.create(entry)
  } catch {
    // Mất một dòng nhật ký không đáng để đánh đổi một lượt kích hoạt hỏng.
  }
}

module.exports = { log }
