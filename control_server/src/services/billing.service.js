'use strict'

/**
 * Mua credit — đơn hàng, link thanh toán PayOS, webhook xác nhận.
 *
 * Luồng: web tạo đơn → server sinh `orderCode` + gọi PayOS tạo link thanh
 * toán → web hiện QR (render từ chuỗi `qrCode`) + nút mở trang PayOS →
 * người dùng trả tiền (QR/thẻ/ví) → PayOS bắn webhook có chữ ký HMAC →
 * server verify → sinh key → gửi mail + hiện trên web (web đang poll).
 *
 * Không có tài khoản người dùng: `orderCode` ("VOX123456") là mã đơn hiển
 * thị, còn `payosOrderCode` (phần 6 chữ số) là mã số gửi sang PayOS — PayOS
 * tự khớp giao dịch với đơn, không còn cảnh người mua ghi sai nội dung.
 */
const crypto = require('node:crypto')

const Order = require('../models/Order')
const config = require('./config.service')
const audit = require('./audit.service')
const email = require('./email.service')
const activation = require('./activation.service')
const payos = require('./payos.service')
const { generateOrderCode } = require('../utils/keycode')

class BillingError extends Error {
  constructor(code, message, statusCode = 400) {
    super(message)
    this.name = 'BillingError'
    this.code = code
    this.statusCode = statusCode
  }
}

/** Danh sách gói + quy tắc cho số tiền tùy chỉnh (hiện trên trang mua). */
async function getPackages() {
  const cfg = await config.getMany([
    'credit.packages', 'credit.vox.to.vnd', 'order.min.vnd', 'order.max.vnd',
    'credit.enabled',
  ])
  const packages = (cfg['credit.packages'] || []).map((p) => ({
    id: p.id,
    label: p.label,
    vnd: p.vnd,
    vox: p.vox,
    bonus: p.bonus || 0,
    totalVox: (p.vox || 0) + (p.bonus || 0),
    popular: Boolean(p.popular),
  }))
  return {
    packages,
    custom: {
      enabled: true,
      voxPerVnd: 1 / cfg['credit.vox.to.vnd'],
      vndPerVox: cfg['credit.vox.to.vnd'],
      minVnd: cfg['order.min.vnd'],
      maxVnd: cfg['order.max.vnd'],
      // Số tiền tùy chỉnh làm tròn xuống bội số này để số Vox nhận được
      // luôn là con số chẵn, dễ đối chiếu.
      stepVnd: 1000,
    },
    creditEnabled: cfg['credit.enabled'],
  }
}

/**
 * Quy đổi một yêu cầu mua thành { amountVnd, vox, packageId, packageLabel }.
 *
 * Gói có sẵn: lấy đúng số tiền và số Vox đã cấu hình (kèm bonus).
 * Số tùy chỉnh: quy đổi theo tỷ giá, làm tròn XUỐNG bội số 1.000đ — không
 * bonus, vì bonus là thứ dành riêng cho việc mua trọn gói.
 */
async function resolvePurchase({ packageId, amountVnd }) {
  const cfg = await config.getMany([
    'credit.packages', 'credit.vox.to.vnd', 'order.min.vnd', 'order.max.vnd',
  ])

  if (packageId && packageId !== 'custom') {
    const pkg = (cfg['credit.packages'] || []).find((p) => p.id === packageId)
    if (!pkg) throw new BillingError('PACKAGE_NOT_FOUND', 'Gói không tồn tại.', 404)
    return {
      amountVnd: pkg.vnd,
      vox: (pkg.vox || 0) + (pkg.bonus || 0),
      packageId: pkg.id,
      packageLabel: pkg.label,
    }
  }

  const raw = Math.floor(Number(amountVnd) || 0)
  const amount = Math.floor(raw / 1000) * 1000
  const min = cfg['order.min.vnd']
  const max = cfg['order.max.vnd']
  if (amount < min) {
    throw new BillingError('AMOUNT_TOO_LOW',
      `Số tiền tối thiểu là ${min.toLocaleString('vi-VN')} đ.`)
  }
  if (amount > max) {
    throw new BillingError('AMOUNT_TOO_HIGH',
      `Số tiền tối đa là ${max.toLocaleString('vi-VN')} đ.`)
  }
  const rate = cfg['credit.vox.to.vnd'] || 10
  return {
    amountVnd: amount,
    vox: Math.floor(amount / rate),
    packageId: 'custom',
    packageLabel: 'Tùy chọn',
  }
}

/** Khối `payment` gửi cho trình duyệt khi đơn còn chờ thanh toán. */
function paymentInfo(order) {
  return {
    checkoutUrl: order.checkoutUrl,
    qrCode: order.qrCode,
    amount: order.amountVnd,
    description: order.orderCode,
  }
}

async function createOrder({ packageId, amountVnd, email: buyerEmail = '', ip = '' }) {
  if (!(await config.get('credit.enabled'))) {
    throw new BillingError('CREDIT_DISABLED',
      'Hệ thống credit đang tạm tắt — bạn dùng miễn phí, không cần mua.', 409)
  }
  if (!payos.isConfigured()) {
    throw new BillingError('PAYMENT_GATEWAY_ERROR',
      'Cổng thanh toán chưa được cấu hình — vui lòng thử lại sau.', 503)
  }
  const purchase = await resolvePurchase({ packageId, amountVnd })
  const minutes = Number(await config.get('order.expire.minutes')) || 60

  let order = null
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const orderCode = generateOrderCode()
    try {
      order = await Order.create({
        orderCode,
        // PayOS bắt buộc mã đơn dạng SỐ — dùng đúng phần 6 chữ số, ánh xạ 1-1
        // với orderCode nên unique index trên cả hai cùng chặn trùng lặp.
        payosOrderCode: Number(orderCode.slice(3)),
        amountVnd: purchase.amountVnd,
        vox: purchase.vox,
        packageId: purchase.packageId,
        packageLabel: purchase.packageLabel,
        email: String(buyerEmail || '').trim().toLowerCase().slice(0, 200),
        accessToken: crypto.randomBytes(24).toString('base64url'),
        expiresAt: new Date(Date.now() + minutes * 60_000),
        createdIp: ip,
      })
      break
    } catch (err) {
      if (err.code !== 11000) throw err
    }
  }
  if (!order) throw new Error('Không sinh được mã đơn hàng duy nhất')

  // Tạo link thanh toán NGAY khi tạo đơn. PayOS lỗi thì hủy đơn luôn —
  // không để lại đơn pending mà người mua không có cách nào trả tiền.
  const publicUrl = String(process.env.PUBLIC_URL || '').replace(/\/$/, '')
  try {
    const link = await payos.createPaymentLink({
      orderCode: order.payosOrderCode,
      amount: order.amountVnd,
      // description giới hạn 9 ký tự — "VOX123456" vừa khít.
      description: order.orderCode,
      returnUrl: `${publicUrl}/thanh-toan/${order.orderCode}`,
      cancelUrl: `${publicUrl}/thanh-toan/${order.orderCode}?huy=1`,
      expiredAt: Math.floor(order.expiresAt.getTime() / 1000),
    })
    order.payosPaymentLinkId = String(link.paymentLinkId || '')
    order.checkoutUrl = String(link.checkoutUrl || '')
    order.qrCode = String(link.qrCode || '')
    await order.save()
  } catch (err) {
    order.status = 'cancelled'
    await order.save()
    throw new BillingError('PAYMENT_GATEWAY_ERROR',
      'Chưa tạo được link thanh toán — vui lòng thử lại sau ít phút.', 502)
  }

  return { order, payment: paymentInfo(order) }
}

/**
 * Bản đơn hàng gửi cho trình duyệt.
 *
 * `keyCode` CHỈ đi kèm khi phía gọi xuất trình đúng `accessToken` của đơn.
 * Mã đơn ngắn (dò được) nên nó chỉ đủ để hỏi "đơn này trả tiền chưa", không
 * bao giờ đủ để lấy hàng.
 */
function orderView(order, { includePayment = false, authorized = false } = {}) {
  const view = {
    orderCode: order.orderCode,
    amountVnd: order.amountVnd,
    vox: order.vox,
    packageId: order.packageId,
    packageLabel: order.packageLabel,
    status: order.status,
    keyCode: (authorized && order.status === 'paid') ? order.keyCode : '',
    createdAt: order.createdAt,
    expiresAt: order.expiresAt,
    paidAt: order.paidAt,
  }
  if (includePayment && order.status === 'pending') {
    view.payment = paymentInfo(order)
  }
  return view
}

/** Token của đơn có khớp không (so sánh không rò rỉ thời gian). */
function tokenMatches(order, given) {
  const { safeEqual } = require('../utils/crypto')
  return safeEqual(String(given || ''), order.accessToken)
}

/** Đơn quá hạn mà chưa trả tiền thì tự chuyển sang `expired` khi được đọc. */
async function getOrder(orderCode) {
  const order = await Order.findOne({ orderCode: String(orderCode || '').toUpperCase() })
  if (!order) return null
  if (order.status === 'pending' && order.expiresAt < new Date()) {
    order.status = 'expired'
    await order.save()
  }
  return order
}

/**
 * Xử lý webhook thanh toán thành công từ PayOS (chữ ký đã verify ở route).
 *
 * `data` là khối data của webhook: { orderCode (số), amount, reference,
 * transactionDateTime, ... }. Trả về { matched, orderCode, keyCode } —
 * `matched=false` nghĩa là không tìm thấy đơn (thường là payload test lúc
 * confirm-webhook). Không ném lỗi ra ngoài: webhook phải luôn nhận 2xx.
 *
 * Chống lặp: PayOS bắn lại cùng giao dịch thì thấy đơn đã `paid` và dừng
 * ngay, không sinh key thứ hai (điều kiện status nằm trong chính lệnh update).
 */
async function handlePayosPayment(data, ip = '') {
  const payosOrderCode = Number(data && data.orderCode)
  if (!Number.isFinite(payosOrderCode)) return { matched: false, reason: 'no_order_code' }

  const order = await Order.findOne({ payosOrderCode })
  if (!order) return { matched: false, reason: 'order_not_found' }

  const orderCode = order.orderCode
  if (order.status === 'paid') {
    return { matched: true, orderCode, keyCode: order.keyCode, replayed: true }
  }

  // PayOS thu đúng số tiền của link nên lệch tiền gần như không thể xảy ra —
  // nếu xảy ra thì là bất thường, ghi audit và để admin xử lý tay.
  const amount = Math.floor(Number(data.amount) || 0)
  if (amount !== order.amountVnd) {
    await audit.log({
      action: 'order.amount_mismatch',
      actor: 'system',
      target: orderCode,
      after: { expected: order.amountVnd, received: amount, reference: data.reference },
      ip,
    })
    return { matched: true, orderCode, mismatch: true, expected: order.amountVnd, received: amount }
  }

  // Chốt đơn trước khi sinh key: điều kiện status trong chính lệnh update
  // chặn hai webhook song song cùng sinh key.
  const claimed = await Order.findOneAndUpdate(
    { orderCode, status: { $in: ['pending', 'expired'] } },
    {
      $set: {
        status: 'paid',
        paidAmountVnd: amount,
        bankRefId: String(data.reference || ''),
        bankGateway: 'payos',
        paidAt: new Date(),
      },
    },
    { new: true },
  )
  if (!claimed) {
    const fresh = await Order.findOne({ orderCode })
    return { matched: true, orderCode, keyCode: fresh ? fresh.keyCode : '', replayed: true }
  }

  const key = await activation.issueKey({
    vox: claimed.vox,
    source: 'order',
    orderId: claimed._id,
    packageId: claimed.packageId,
    amountVnd: claimed.amountVnd,
  })
  claimed.keyCode = key.code
  await claimed.save()

  await audit.log({
    action: 'order.paid',
    actor: 'system',
    target: orderCode,
    after: { amount, vox: claimed.vox, keyCode: key.code, reference: data.reference },
    ip,
  })

  if (claimed.email) {
    email.sendActivationKey({
      to: claimed.email,
      keyCode: key.code,
      vox: claimed.vox,
      orderCode,
      amountVnd: claimed.amountVnd,
    }).catch(() => {})
  }

  return { matched: true, orderCode, keyCode: key.code, vox: claimed.vox }
}

module.exports = {
  BillingError,
  getPackages,
  resolvePurchase,
  createOrder,
  getOrder,
  orderView,
  tokenMatches,
  paymentInfo,
  handlePayosPayment,
}
