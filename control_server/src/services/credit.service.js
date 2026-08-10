'use strict'

/**
 * Ví Vox — cộng, trừ, và sổ cái.
 *
 * MongoDB đứng một mình (không replica set) nên KHÔNG có transaction nhiều
 * tài liệu. Thay vào đó dùng đúng thứ MongoDB bảo đảm sẵn: một lệnh
 * findOneAndUpdate trên MỘT tài liệu là nguyên tử. Trừ credit vì thế được
 * viết thành một lệnh có điều kiện `balance >= amount` — hai request đồng
 * thời thì đúng một cái thắng, cái kia thấy điều kiện không còn đúng và
 * nhận về null. Không bao giờ có số dư âm, không cần khóa.
 *
 * Sổ cái ghi ngay sau đó. Nếu ghi sổ thất bại (trùng idempotencyKey — tức
 * request này đã được xử lý rồi) thì hoàn lại phần vừa trừ, nên trạng thái
 * luôn khớp giữa ví và sổ.
 */
const CreditLedger = require('../models/CreditLedger')
const Device = require('../models/Device')
const config = require('./config.service')

class InsufficientCreditError extends Error {
  constructor(balance, required) {
    super(`Không đủ Vox: cần ${required}, hiện có ${balance}`)
    this.name = 'InsufficientCreditError'
    this.code = 'INSUFFICIENT_CREDIT'
    this.balance = balance
    this.required = required
  }
}

/** Giao dịch đã ghi trước đó với cùng idempotencyKey, hoặc null. */
async function findByIdempotencyKey(idempotencyKey) {
  if (!idempotencyKey) return null
  return CreditLedger.findOne({ idempotencyKey }).lean()
}

async function getBalance(fingerprint) {
  const device = await Device.findOne({ fingerprint }, { balance: 1 }).lean()
  return device ? device.balance : 0
}

/**
 * Trừ Vox. Trả về { charged, balanceAfter, replayed }.
 *
 * `replayed=true` nghĩa là idempotencyKey này đã được tính phí trước đó —
 * không trừ thêm lần nữa, chỉ trả lại số dư hiện tại.
 */
async function deduct(fingerprint, amount, { type = 'usage', idempotencyKey,
  description = '', metadata = {} } = {}) {
  const required = Math.max(0, Math.round(amount))
  if (!idempotencyKey) throw new Error('deduct: thiếu idempotencyKey')

  if (!(await config.get('credit.enabled'))) {
    return { charged: 0, balanceAfter: await getBalance(fingerprint), replayed: false, skipped: true }
  }
  if (required === 0) {
    return { charged: 0, balanceAfter: await getBalance(fingerprint), replayed: false }
  }

  const prior = await findByIdempotencyKey(idempotencyKey)
  if (prior) {
    return { charged: Math.abs(prior.delta), balanceAfter: await getBalance(fingerprint), replayed: true }
  }

  const device = await Device.findOneAndUpdate(
    { fingerprint, status: 'active', balance: { $gte: required } },
    { $inc: { balance: -required } },
    { new: true },
  )
  if (!device) {
    throw new InsufficientCreditError(await getBalance(fingerprint), required)
  }

  try {
    await CreditLedger.create({
      fingerprint,
      deviceId: device._id,
      delta: -required,
      balanceAfter: device.balance,
      type,
      idempotencyKey,
      description,
      metadata,
    })
  } catch (err) {
    // Trùng idempotencyKey: một request song song đã tính phí xong ngay
    // giữa lúc ta kiểm tra và lúc ta trừ. Hoàn lại phần vừa trừ.
    await Device.updateOne({ _id: device._id }, { $inc: { balance: required } })
    if (err.code === 11000) {
      return { charged: required, balanceAfter: device.balance + required, replayed: true }
    }
    throw err
  }
  return { charged: required, balanceAfter: device.balance, replayed: false }
}

/**
 * Cộng Vox. Trả về { granted, balanceAfter, replayed }.
 *
 * Cộng an toàn hơn trừ (không có điều kiện nào để thua) nên ghi sổ TRƯỚC:
 * unique index trên idempotencyKey là thứ chặn cộng hai lần, và nếu server
 * chết ngay sau đó thì có bản ghi sổ để đối chiếu, còn hơn cộng xong mà
 * không ai biết vì sao.
 */
async function grant(fingerprint, amount, { type = 'activation', idempotencyKey,
  description = '', metadata = {} } = {}) {
  const value = Math.max(0, Math.round(amount))
  if (!idempotencyKey) throw new Error('grant: thiếu idempotencyKey')
  if (value === 0) {
    return { granted: 0, balanceAfter: await getBalance(fingerprint), replayed: false }
  }

  const prior = await findByIdempotencyKey(idempotencyKey)
  if (prior) {
    return { granted: prior.delta, balanceAfter: await getBalance(fingerprint), replayed: true }
  }

  const device = await Device.findOneAndUpdate(
    { fingerprint },
    { $inc: { balance: value } },
    { new: true },
  )
  if (!device) throw new Error(`Không tìm thấy thiết bị ${fingerprint}`)

  try {
    await CreditLedger.create({
      fingerprint,
      deviceId: device._id,
      delta: value,
      balanceAfter: device.balance,
      type,
      idempotencyKey,
      description,
      metadata,
    })
  } catch (err) {
    await Device.updateOne({ _id: device._id }, { $inc: { balance: -value } })
    if (err.code === 11000) {
      return { granted: value, balanceAfter: device.balance - value, replayed: true }
    }
    throw err
  }
  return { granted: value, balanceAfter: device.balance, replayed: false }
}

/** Hoàn lại phần đã trừ khi việc gọi AI thất bại sau lúc tính phí. */
async function refund(fingerprint, amount, { idempotencyKey, description = '',
  metadata = {} } = {}) {
  return grant(fingerprint, amount, {
    type: 'refund', idempotencyKey, description, metadata,
  })
}

async function history(fingerprint, { page = 1, limit = 20 } = {}) {
  const skip = (Math.max(1, page) - 1) * limit
  const [items, total] = await Promise.all([
    CreditLedger.find({ fingerprint })
      .sort({ createdAt: -1 }).skip(skip).limit(limit)
      .select('delta balanceAfter type description createdAt metadata.action metadata.sentences')
      .lean(),
    CreditLedger.countDocuments({ fingerprint }),
  ])
  return { items, total, page, limit }
}

/**
 * Đối soát ví ↔ sổ cái: sum(delta) theo fingerprint phải bằng đúng
 * device.balance. Lệch chỉ xảy ra ở kịch bản hiếm (crash giữa $inc và ghi
 * sổ) — nhưng hệ thống tiền không có đối soát thì lỗi hiếm sẽ được phát
 * hiện bởi khách khiếu nại thay vì bởi mình.
 *
 * Chỉ ĐỌC và BÁO (ghi audit log), không tự sửa: chênh lệch tiền phải có
 * con người nhìn vào trước khi đụng tới ví.
 * Trả về { checked, mismatches: [{fingerprint, balance, ledgerSum, diff}] }.
 */
async function reconcile({ limit = 50 } = {}) {
  const sums = await CreditLedger.aggregate([
    { $group: { _id: '$fingerprint', ledgerSum: { $sum: '$delta' } } },
  ])
  const byFp = new Map(sums.map((s) => [s._id, s.ledgerSum]))

  const mismatches = []
  let checked = 0
  // Duyệt theo Device (nguồn sự thật về số dư): thiết bị chưa có dòng sổ nào
  // thì ledgerSum = 0, và balance phải bằng 0 theo đúng lẽ.
  const cursor = Device.find({}, { fingerprint: 1, balance: 1 }).lean().cursor()
  for await (const device of cursor) {
    checked += 1
    const ledgerSum = byFp.get(device.fingerprint) || 0
    if (ledgerSum !== device.balance) {
      mismatches.push(device.fingerprint)
      if (mismatches.length >= limit) break
    }
  }

  // Xác minh lại từng ca lệch: một request đang bay (đã $inc ví, chưa kịp ghi
  // sổ) tạo ra lệch giả trong vài mili giây — đọc lại cả hai phía cho từng
  // fingerprint loại gần hết nhiễu đó.
  const confirmed = []
  for (const fp of mismatches) {
    const [device, agg] = await Promise.all([
      Device.findOne({ fingerprint: fp }, { balance: 1 }).lean(),
      CreditLedger.aggregate([
        { $match: { fingerprint: fp } },
        { $group: { _id: null, ledgerSum: { $sum: '$delta' } } },
      ]),
    ])
    if (!device) continue
    const ledgerSum = (agg[0] && agg[0].ledgerSum) || 0
    if (ledgerSum !== device.balance) {
      confirmed.push({
        fingerprint: fp,
        balance: device.balance,
        ledgerSum,
        diff: device.balance - ledgerSum,
      })
    }
  }

  if (confirmed.length) {
    const audit = require('./audit.service')
    await audit.log({
      action: 'credit.reconcile.mismatch',
      actor: 'system',
      target: `${confirmed.length} thiết bị lệch ví`,
      after: { mismatches: confirmed.slice(0, 20) },
    }).catch(() => {})
  }
  return { checked, mismatches: confirmed }
}

module.exports = {
  InsufficientCreditError,
  getBalance,
  deduct,
  grant,
  refund,
  history,
  reconcile,
  findByIdempotencyKey,
}
