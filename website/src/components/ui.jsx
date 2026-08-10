/** Các mảnh giao diện dùng lại ở nhiều trang. */
import { useEffect, useState } from 'react'

export function Spinner({ className = 'w-5 h-5' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-20" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export function Loading({ label = 'Đang tải…' }) {
  return (
    <div className="flex items-center gap-3 text-ink-soft py-10 justify-center">
      <Spinner />
      <span className="text-sm">{label}</span>
    </div>
  )
}

/**
 * Báo lỗi kèm nút thử lại.
 *
 * Mất mạng và lỗi máy chủ là hai chuyện khác nhau với người dùng: một cái họ
 * sửa được, một cái thì không. `code === 'OFFLINE'` nói rõ điều đó.
 */
export function ErrorBox({ error, onRetry }) {
  if (!error) return null
  const offline = error.code === 'OFFLINE'
  return (
    <div className="card border-danger/30 bg-danger/5 p-4">
      <p className="text-sm text-danger font-medium">
        {offline ? 'Không kết nối được máy chủ' : 'Có lỗi xảy ra'}
      </p>
      <p className="text-sm text-ink-soft mt-1">{error.message}</p>
      {onRetry && (
        <button className="btn-ghost mt-3 text-xs py-1.5" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  )
}

export function Empty({ title, hint }) {
  return (
    <div className="text-center py-12">
      <p className="text-ink-soft text-sm">{title}</p>
      {hint && <p className="text-ink-muted text-xs mt-1">{hint}</p>}
    </div>
  )
}

const BADGE_TONES = {
  ok: 'bg-ok/15 text-ok',
  warn: 'bg-warn/15 text-warn',
  danger: 'bg-danger/15 text-danger',
  info: 'bg-primary/15 text-primary',
  muted: 'bg-white/5 text-ink-muted',
}

export function Badge({ tone = 'muted', children }) {
  return <span className={`badge ${BADGE_TONES[tone] || BADGE_TONES.muted}`}>{children}</span>
}

/**
 * Nút chép vào clipboard, có phản hồi thị giác.
 *
 * Chép mã kích hoạt là thao tác quan trọng nhất trên trang thanh toán —
 * người dùng cần biết chắc là đã chép được, không phải đoán.
 */
export function CopyButton({ value, label = 'Chép', className = '' }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return undefined
    const t = setTimeout(() => setCopied(false), 1800)
    return () => clearTimeout(t)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(String(value))
      setCopied(true)
    } catch {
      // Trình duyệt cũ hoặc trang không chạy HTTPS — bôi đen tay vẫn được.
      const el = document.createElement('textarea')
      el.value = String(value)
      document.body.appendChild(el)
      el.select()
      try { document.execCommand('copy'); setCopied(true) } catch { /* thôi vậy */ }
      document.body.removeChild(el)
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      className={`btn-ghost text-xs py-1.5 px-3 ${copied ? 'text-ok border-ok/40' : ''} ${className}`}
    >
      {copied ? 'Đã chép' : label}
    </button>
  )
}

/** Hộp thoại xác nhận cho các thao tác không lùi lại được. */
export function Modal({ open, title, children, onClose, footer, width = 'max-w-lg' }) {
  useEffect(() => {
    if (!open) return undefined
    function onKey(e) { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('keydown', onKey)
    // Khóa cuộn nền: cuộn trang phía sau trong khi hộp thoại mở là lỗi
    // giao diện kinh điển, và ở đây nó che mất nút xác nhận.
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}
    >
      <div className={`card w-full ${width} shadow-2xl`}>
        <div className="px-5 py-4 border-b border-border-subtle">
          <h3 className="font-semibold">{title}</h3>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && (
          <div className="px-5 py-4 border-t border-border-subtle flex justify-end gap-2">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}

/** Thanh phân trang tối giản — chỉ lùi/tiến và vị trí hiện tại. */
export function Pager({ page, total, limit, onPage }) {
  const pages = Math.max(1, Math.ceil(total / limit))
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-between px-3 py-3 text-xs text-ink-soft">
      <span>{total.toLocaleString('vi-VN')} mục · trang {page}/{pages}</span>
      <div className="flex gap-2">
        <button
          className="btn-ghost py-1 px-2.5 text-xs"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          Trước
        </button>
        <button
          className="btn-ghost py-1 px-2.5 text-xs"
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          Sau
        </button>
      </div>
    </div>
  )
}
