/** Tiện ích định dạng dùng chung — tiếng Việt, đơn vị Việt Nam. */

export function formatVnd(value) {
  return `${Number(value || 0).toLocaleString('vi-VN')} đ`
}

export function formatVox(value) {
  return Number(value || 0).toLocaleString('vi-VN')
}

export function formatDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('vi-VN', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/** "3 phút trước", "2 giờ trước" — dễ đọc hơn mốc tuyệt đối trong bảng. */
export function formatRelative(value) {
  if (!value) return '—'
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Math.round((Date.now() - then) / 1000)
  if (diff < 60) return 'vừa xong'
  if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`
  if (diff < 2592000) return `${Math.floor(diff / 86400)} ngày trước`
  return formatDate(value)
}

/** Đếm ngược mm:ss cho đơn hàng sắp hết hạn. */
export function formatCountdown(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

/** Mã máy 64 ký tự không đọc nổi trong bảng — cắt còn đầu-cuối. */
export function shortFingerprint(fp) {
  const s = String(fp || '')
  return s.length > 16 ? `${s.slice(0, 8)}…${s.slice(-4)}` : s
}
