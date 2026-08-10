/**
 * Sổ đơn hàng của trình duyệt này.
 *
 * `accessToken` chỉ được máy chủ trả về ĐÚNG MỘT LẦN, lúc tạo đơn — mất nó
 * là mất đường lấy mã kích hoạt (mã đơn 6 chữ số không thay thế được, xem
 * `orderView` phía máy chủ). Vì vậy nó phải xuống đĩa NGAY, trước cả khi
 * người dùng kịp thanh toán: đóng tab, tắt máy, mở lại vẫn còn.
 *
 * localStorage (không phải sessionStorage): người dùng thường thanh toán
 * bằng app ngân hàng trên điện thoại rồi mới quay lại tab — có khi hàng giờ
 * sau, có khi sau khi đã đóng trình duyệt.
 */
const KEY = 'voxdub_orders'
const MAX_ORDERS = 20

function readAll() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(raw) ? raw : []
  } catch {
    return []
  }
}

function writeAll(orders) {
  try {
    localStorage.setItem(KEY, JSON.stringify(orders.slice(0, MAX_ORDERS)))
  } catch {
    // Hết dung lượng hoặc trình duyệt chặn — đơn vẫn dùng được trong phiên
    // này, chỉ là mở lại tab thì mất. Không đáng để làm hỏng luồng mua.
  }
}

export function rememberOrder({ orderCode, accessToken, amountVnd, vox, email }) {
  const orders = readAll().filter((o) => o.orderCode !== orderCode)
  orders.unshift({
    orderCode,
    accessToken,
    amountVnd,
    vox,
    email: email || '',
    createdAt: new Date().toISOString(),
  })
  writeAll(orders)
}

export function listOrders() {
  return readAll()
}

export function getOrderToken(orderCode) {
  const found = readAll().find((o) => o.orderCode === orderCode)
  return found ? found.accessToken : ''
}

/** Ghi lại mã đã nhận để trang "Đơn của tôi" hiện luôn, khỏi gọi lại API. */
export function markOrderPaid(orderCode, keyCode) {
  const orders = readAll()
  const found = orders.find((o) => o.orderCode === orderCode)
  if (!found) return
  found.keyCode = keyCode
  found.paidAt = new Date().toISOString()
  writeAll(orders)
}

export function forgetOrder(orderCode) {
  writeAll(readAll().filter((o) => o.orderCode !== orderCode))
}
