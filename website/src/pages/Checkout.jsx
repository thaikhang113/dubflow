import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { QRCodeSVG } from 'qrcode.react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import { formatCountdown, formatVnd, formatVox } from '../api/format'
import { CopyButton, ErrorBox, Loading, Spinner } from '../components/ui'
import { getOrderToken, markOrderPaid } from '../store/orders'

// Người dùng đang ngồi chờ trước màn hình — 4 giây đủ nhanh để thấy "tức
// thì" mà không dội request lên máy chủ. Backend cho 120 req/phút/IP.
const POLL_MS = 4000

/** Màn hình thành công: mã kích hoạt + hướng dẫn dùng. */
function PaidView({ order, token }) {
  const [emailInput, setEmailInput] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState('')
  const [sendError, setSendError] = useState(null)

  // Pháo giấy một lần khi mã hiện ra — dynamic import để không nặng bundle chính.
  useEffect(() => {
    let cancelled = false
    import('canvas-confetti').then(({ default: confetti }) => {
      if (cancelled) return
      confetti({ particleCount: 90, spread: 75, origin: { y: 0.3 }, disableForReducedMotion: true })
    }).catch(() => { /* trang vẫn chạy bình thường nếu thiếu hiệu ứng */ })
    return () => { cancelled = true }
  }, [])

  async function resend(e) {
    e.preventDefault()
    setSending(true)
    setSendError(null)
    try {
      const result = await api.resendKey(order.orderCode, token, emailInput.trim())
      setSent(result.email)
    } catch (err) {
      setSendError(err)
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-14">
      <div className="text-center">
        <motion.div
          initial={{ scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 260, damping: 18 }}
          className="w-16 h-16 rounded-full bg-ok/15 text-ok grid place-items-center mx-auto"
        >
          <svg viewBox="0 0 24 24" className="w-8 h-8" fill="none" stroke="currentColor" strokeWidth="2.5">
            {/* Checkmark vẽ đường — thấy rõ "vừa xong". */}
            <motion.path
              d="M20 6 9 17l-5-5"
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.5, delay: 0.15, ease: 'easeOut' }}
            />
          </svg>
        </motion.div>
        <h1 className="text-2xl font-bold mt-4">Thanh toán thành công</h1>
        <p className="text-ink-soft mt-2">
          Đã cộng {formatVox(order.vox)} Vox vào mã kích hoạt dưới đây.
        </p>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25, duration: 0.45 }}
        className="card p-6 mt-8 border-primary/40 glow"
      >
        <p className="text-xs text-ink-muted">MÃ KÍCH HOẠT</p>
        <p className="font-mono text-2xl sm:text-3xl font-bold tracking-[0.15em] mt-2 break-all">
          {order.keyCode}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <CopyButton value={order.keyCode} label="Chép mã" />
          <Link to="/tai-ve" className="btn-ghost text-xs py-1.5 px-3">
            Chưa có ứng dụng?
          </Link>
        </div>
      </motion.div>

      <div className="card p-6 mt-4">
        <h2 className="font-semibold">Cách kích hoạt</h2>
        <ol className="mt-3 space-y-2 text-sm text-ink-soft list-decimal list-inside leading-relaxed">
          <li>Mở <strong className="text-ink">VoxDub Studio</strong> trên máy tính</li>
          <li>Vào mục <strong className="text-ink">Tài khoản</strong> ở thanh bên trái</li>
          <li>Dán mã trên vào ô "Mã kích hoạt", bấm <strong className="text-ink">Kích hoạt</strong></li>
        </ol>
        <div className="mt-4 bg-warn/10 border border-warn/25 rounded-xl px-4 py-3">
          <p className="text-xs text-warn leading-relaxed">
            Mã này chỉ kích hoạt được <strong>một lần trên một máy</strong>.
            Giữ mã cho riêng bạn — ai có mã trước thì người đó nhận Vox.
          </p>
        </div>
      </div>

      {/* Gửi lại vào email — cứu người đóng tab trước khi kịp chép mã. */}
      <div className="card p-6 mt-4">
        <h2 className="font-semibold text-sm">Gửi mã vào email</h2>
        {sent ? (
          <p className="text-sm text-ok mt-2">Đã gửi tới {sent}.</p>
        ) : (
          <form onSubmit={resend} className="mt-3 flex flex-col sm:flex-row gap-2">
            <input
              type="email"
              className="input flex-1"
              placeholder={order.email || 'ban@example.com'}
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
            />
            <button
              type="submit"
              className="btn-ghost shrink-0"
              disabled={sending || (!emailInput.trim() && !order.email)}
            >
              {sending ? <Spinner className="w-4 h-4" /> : 'Gửi mã'}
            </button>
          </form>
        )}
        {sendError && <p className="text-xs text-warn mt-2">{sendError.message}</p>}
      </div>

      <p className="text-center text-xs text-ink-muted mt-6">
        Đơn {order.orderCode} · {formatVnd(order.amountVnd)} ·{' '}
        <Link to="/don-hang" className="hover:text-ink underline">
          Xem tất cả đơn của tôi
        </Link>
      </p>
    </div>
  )
}

const METHODS = ['QR ngân hàng', 'Thẻ ATM', 'Visa / Mastercard', 'Ví điện tử']

/** Màn hình chờ: QR PayOS + nút mở trang thanh toán, đếm ngược. */
function PendingView({ order, secondsLeft, onRefresh, cancelled }) {
  const payment = order.payment || {}
  return (
    <div className="max-w-4xl mx-auto px-4 py-14">
      <h1 className="text-2xl font-bold">Thanh toán để nhận mã</h1>
      <p className="text-ink-soft mt-2 text-sm">
        Quét mã QR bằng app ngân hàng, hoặc mở trang thanh toán PayOS để trả
        bằng thẻ/ví. Mã kích hoạt hiện ra ngay khi thanh toán xong — hệ thống
        tự khớp đơn, không cần ghi nội dung gì.
      </p>

      {cancelled && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-5 bg-warn/10 border border-warn/30 rounded-xl px-4 py-3"
        >
          <p className="text-sm text-warn font-medium">Bạn đã hủy thanh toán</p>
          <p className="text-xs text-ink-soft mt-1">
            Đơn vẫn còn hiệu lực{secondsLeft > 0 && ` trong ${formatCountdown(secondsLeft)}`} —
            quét QR hoặc bấm nút bên dưới để thanh toán lại.
          </p>
        </motion.div>
      )}

      <div className="grid gap-5 lg:grid-cols-2 mt-8">
        {/* QR PayOS */}
        <div className="card p-6 flex flex-col items-center">
          {payment.qrCode ? (
            <div className="relative w-full max-w-[280px] rounded-xl bg-white p-4 overflow-hidden">
              <QRCodeSVG
                value={payment.qrCode}
                size={248}
                level="M"
                className="w-full h-auto"
              />
              {/* Vạch sáng chạy dọc — gợi ý "đưa máy lên quét". */}
              <div
                aria-hidden
                className="absolute inset-x-3 h-0.5 rounded-full bg-primary/60 animate-scan-line"
              />
            </div>
          ) : (
            <div className="w-full max-w-[280px] aspect-square rounded-xl bg-input grid place-items-center text-center px-6">
              <p className="text-xs text-ink-muted">
                Không tải được mã QR. Dùng nút "Mở trang thanh toán" bên cạnh.
              </p>
            </div>
          )}
          <p className="text-2xl font-bold mt-5">{formatVnd(order.amountVnd)}</p>
          <p className="text-sm text-primary font-medium mt-0.5">
            {formatVox(order.vox)} Vox
          </p>
          <p className="text-xs text-ink-muted mt-2">
            Quét bằng app ngân hàng bất kỳ (VietQR)
          </p>
        </div>

        {/* Mở trang PayOS + phương thức */}
        <div className="space-y-3">
          {payment.checkoutUrl && (
            <a
              href={payment.checkoutUrl}
              target="_blank"
              rel="noreferrer"
              className="btn-primary w-full py-3.5 text-base animate-pulse-glow"
            >
              Mở trang thanh toán PayOS
              <svg viewBox="0 0 24 24" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M7 17 17 7M9 7h8v8" />
              </svg>
            </a>
          )}

          <div className="card p-4">
            <p className="text-xs text-ink-muted font-medium">PHƯƠNG THỨC HỖ TRỢ</p>
            <div className="flex flex-wrap gap-2 mt-2.5">
              {METHODS.map((m) => (
                <span key={m} className="badge bg-white/5 text-ink-soft border border-border-subtle py-1">
                  {m}
                </span>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 bg-input rounded-xl px-4 py-3">
            <div className="min-w-0">
              <p className="text-xs text-ink-muted">Mã đơn hàng</p>
              <p className="font-mono text-sm mt-0.5">{order.orderCode}</p>
            </div>
            <CopyButton value={order.orderCode} className="shrink-0" />
          </div>

          <div className="bg-primary/10 border border-primary/30 rounded-xl px-4 py-3">
            <p className="text-xs text-ink-soft leading-relaxed">
              Thanh toán xử lý bởi <strong className="text-primary">PayOS</strong> —
              cổng thanh toán được cấp phép. Đơn tự khớp theo mã, mã kích hoạt
              hiện ra trên trang này ngay khi tiền vào.
            </p>
          </div>
        </div>
      </div>

      {/* Trạng thái chờ */}
      <div className="card p-5 mt-5 flex flex-col sm:flex-row sm:items-center gap-4">
        <div className="flex items-center gap-3 flex-1">
          <Spinner className="w-5 h-5 text-primary" />
          <div>
            <p className="text-sm font-medium">Đang chờ thanh toán…</p>
            <p className="text-xs text-ink-muted mt-0.5">
              Trang này tự cập nhật, bạn không cần tải lại.
              {secondsLeft > 0 && ` Đơn hết hạn sau ${formatCountdown(secondsLeft)}.`}
            </p>
          </div>
        </div>
        <button onClick={onRefresh} className="btn-ghost text-xs py-2 shrink-0">
          Kiểm tra ngay
        </button>
      </div>

      <p className="text-xs text-ink-muted mt-6 leading-relaxed">
        Đã thanh toán mà sau 5 phút vẫn chưa thấy mã? Mã đơn của bạn là{' '}
        <strong className="text-ink font-mono">{order.orderCode}</strong> — giữ
        lại để liên hệ hỗ trợ nếu cần.
      </p>
    </div>
  )
}

function ExpiredView({ order }) {
  return (
    <div className="max-w-lg mx-auto px-4 py-20 text-center">
      <h1 className="text-2xl font-bold">Đơn đã hết hạn</h1>
      <p className="text-ink-soft mt-3 leading-relaxed">
        Đơn {order.orderCode} quá thời gian chờ thanh toán nên đã đóng lại.
        Chưa có khoản tiền nào bị trừ.
      </p>
      <p className="text-ink-soft mt-3 text-sm leading-relaxed">
        Nếu bạn <strong className="text-ink">vừa thanh toán</strong> cho đơn
        này, đừng lo — liên hệ hỗ trợ kèm mã đơn, chúng tôi cấp mã kích hoạt
        thủ công.
      </p>
      <div className="mt-6 flex gap-3 justify-center">
        <Link to="/mua" className="btn-primary">Tạo đơn mới</Link>
        <Link to="/lien-he" className="btn-ghost">Liên hệ hỗ trợ</Link>
      </div>
    </div>
  )
}

export default function Checkout() {
  const { orderCode } = useParams()
  const [searchParams] = useSearchParams()
  // PayOS đưa người dùng về đây với ?huy=1 khi họ bấm hủy trên trang thanh toán.
  const cancelled = searchParams.get('huy') === '1'
  const token = getOrderToken(orderCode)

  const [order, setOrder] = useState(null)
  const [error, setError] = useState(null)
  const [secondsLeft, setSecondsLeft] = useState(0)
  const abortRef = useRef(null)

  const load = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const result = await api.getOrder(orderCode, token, controller.signal)
      setOrder(result)
      setError(null)
      if (result.status === 'paid' && result.keyCode) {
        markOrderPaid(orderCode, result.keyCode)
      }
      return result
    } catch (err) {
      if (err.name !== 'AbortError') setError(err)
      return null
    }
  }, [orderCode, token])

  useEffect(() => {
    load()
    return () => abortRef.current?.abort()
  }, [load])

  // Poll trong lúc chờ. Dừng ngay khi đơn chốt (paid/expired) — poll tiếp là
  // đốt request vô ích và giữ tab bận vô thời hạn.
  useEffect(() => {
    if (!order || order.status !== 'pending') return undefined
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [order, load])

  // Đếm ngược tới hạn đơn.
  useEffect(() => {
    if (!order || order.status !== 'pending' || !order.expiresAt) return undefined
    function tick() {
      const left = (new Date(order.expiresAt).getTime() - Date.now()) / 1000
      setSecondsLeft(Math.max(0, left))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [order])

  if (error && !order) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20">
        <ErrorBox error={error} onRetry={load} />
        <p className="text-center text-sm text-ink-muted mt-5">
          <Link to="/mua" className="underline hover:text-ink">Quay lại trang mua</Link>
        </p>
      </div>
    )
  }
  if (!order) return <Loading label="Đang tải đơn hàng…" />

  if (order.status === 'paid') {
    // Có đơn đã trả tiền nhưng trình duyệt này không giữ token (mở link ở
    // máy khác): nói rõ vì sao không thấy mã thay vì hiện ô trống.
    if (!order.keyCode) {
      return (
        <div className="max-w-lg mx-auto px-4 py-20 text-center">
          <h1 className="text-2xl font-bold">Đơn này đã thanh toán</h1>
          <p className="text-ink-soft mt-3 leading-relaxed">
            Mã kích hoạt chỉ hiện trên đúng trình duyệt đã tạo đơn. Hãy mở lại
            tab bạn dùng lúc đặt mua, hoặc kiểm tra email nếu bạn có điền.
          </p>
          <Link to="/lien-he" className="btn-ghost mt-6 inline-flex">
            Liên hệ hỗ trợ
          </Link>
        </div>
      )
    }
    return <PaidView order={order} token={token} />
  }
  if (order.status === 'expired' || order.status === 'cancelled') {
    return <ExpiredView order={order} />
  }
  return (
    <PendingView
      order={order}
      secondsLeft={secondsLeft}
      onRefresh={load}
      cancelled={cancelled}
    />
  )
}
