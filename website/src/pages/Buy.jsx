import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { api } from '../api/client'
import { formatVnd, formatVox } from '../api/format'
import { useFetch } from '../api/useFetch'
import { ErrorBox, Loading, Spinner } from '../components/ui'
import { Reveal } from '../components/motion'
import { rememberOrder } from '../store/orders'

/** Email hợp lệ ở mức đủ dùng — không cố bắt hết RFC 5322. */
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

/** Stepper 3 bước — cho người mua biết mình đang ở đâu. */
function Stepper({ current = 1 }) {
  const steps = ['Chọn gói', 'Thanh toán', 'Nhận mã']
  return (
    <ol className="flex items-center gap-2 text-xs">
      {steps.map((label, i) => {
        const n = i + 1
        const active = n === current
        const done = n < current
        return (
          <li key={label} className="flex items-center gap-2">
            {i > 0 && <span className="w-6 h-px bg-border" />}
            <span
              className={`w-5 h-5 rounded-full grid place-items-center font-semibold ${
                active
                  ? 'bg-primary text-white'
                  : done
                    ? 'bg-ok/20 text-ok'
                    : 'bg-panel text-ink-muted border border-border-subtle'
              }`}
            >
              {n}
            </span>
            <span className={active ? 'text-ink font-medium' : 'text-ink-muted'}>
              {label}
            </span>
          </li>
        )
      })}
    </ol>
  )
}

export default function Buy() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { data, error, loading, reload } = useFetch(() => api.packages())

  const [picked, setPicked] = useState(params.get('goi') || '')
  const [customVnd, setCustomVnd] = useState('')
  const [useCustom, setUseCustom] = useState(params.get('tuy-chon') === '1')
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  // Chọn sẵn gói phổ biến khi vào trang mà chưa chỉ định gói nào — không để
  // người dùng đối diện một danh sách chưa chọn gì.
  useEffect(() => {
    if (!data || picked || useCustom) return
    const popular = data.packages.find((p) => p.popular) || data.packages[0]
    if (popular) setPicked(popular.id)
  }, [data, picked, useCustom])

  const custom = data ? data.custom : null

  /** Quy đổi số tiền tùy chọn — phải khớp ĐÚNG công thức phía máy chủ. */
  const customPreview = useMemo(() => {
    if (!custom) return null
    const raw = Math.floor(Number(String(customVnd).replace(/\D/g, '')) || 0)
    if (!raw) return null
    // Máy chủ làm tròn xuống bội 1.000đ rồi mới chia tỷ giá. Tính khác đi ở
    // đây thì người dùng thấy một con số, nhận được một con số khác.
    const amount = Math.floor(raw / custom.stepVnd) * custom.stepVnd
    return {
      raw,
      amount,
      vox: Math.floor(amount / custom.vndPerVox),
      tooLow: amount < custom.minVnd,
      tooHigh: amount > custom.maxVnd,
      rounded: amount !== raw,
    }
  }, [customVnd, custom])

  const selectedPkg = data && !useCustom
    ? data.packages.find((p) => p.id === picked)
    : null

  const canSubmit = !submitting && (
    useCustom
      ? Boolean(customPreview && !customPreview.tooLow && !customPreview.tooHigh)
      : Boolean(selectedPkg)
  ) && (!email || EMAIL_RE.test(email))

  async function submit(e) {
    e.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const order = await api.createOrder({
        packageId: useCustom ? 'custom' : picked,
        amountVnd: useCustom ? customPreview.amount : undefined,
        email: email.trim() || undefined,
      })
      // Cất token TRƯỚC khi chuyển trang: đây là thứ duy nhất mở được mã
      // kích hoạt sau này, và máy chủ không bao giờ trả lại nó lần thứ hai.
      rememberOrder({
        orderCode: order.orderCode,
        accessToken: order.accessToken,
        amountVnd: order.amountVnd,
        vox: order.vox,
        email: email.trim(),
      })
      navigate(`/thanh-toan/${order.orderCode}`)
    } catch (err) {
      setSubmitError(err)
      setSubmitting(false)
    }
  }

  if (loading) return <Loading label="Đang tải bảng giá…" />
  if (error) {
    return (
      <div className="max-w-lg mx-auto px-4 py-14">
        <ErrorBox error={error} onRetry={reload} />
      </div>
    )
  }

  if (!data.creditEnabled) {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center">
        <h1 className="text-2xl font-bold">Đang miễn phí</h1>
        <p className="text-ink-soft mt-3">
          Hệ thống Vox đang tạm tắt — bạn dùng ứng dụng thoải mái mà không cần
          mua gì. Quay lại sau nhé.
        </p>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-14">
      <Reveal>
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold">Mua Vox</h1>
            <p className="text-ink-soft mt-2.5">
              Chọn gói rồi thanh toán qua PayOS (QR, thẻ, ví). Nhận mã kích hoạt
              ngay khi xong — không cần đăng ký tài khoản.
            </p>
          </div>
          <Stepper current={1} />
        </div>
      </Reveal>

      <form onSubmit={submit} className="mt-8 grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="space-y-5">
          {/* Gói có sẵn */}
          <div className="grid gap-3 sm:grid-cols-2">
            {data.packages.map((pkg) => {
              const active = !useCustom && picked === pkg.id
              return (
                <motion.button
                  key={pkg.id}
                  type="button"
                  onClick={() => { setUseCustom(false); setPicked(pkg.id) }}
                  whileTap={{ scale: 0.98 }}
                  animate={active ? { scale: 1.01 } : { scale: 1 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 26 }}
                  className={`card p-4 text-left transition-colors relative ${
                    active
                      ? 'border-primary bg-primary/5'
                      : 'hover:border-border hover:bg-panel-hover'
                  }`}
                >
                  {active && (
                    <motion.span
                      layoutId="pkg-check"
                      className="absolute top-3 right-3 w-5 h-5 rounded-full bg-primary text-white grid place-items-center"
                      transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                    >
                      <svg viewBox="0 0 24 24" className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M20 6 9 17l-5-5" />
                      </svg>
                    </motion.span>
                  )}
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm text-ink-soft">{pkg.label}</span>
                    {pkg.popular && !active && (
                      <span className="badge bg-primary/15 text-primary">Phổ biến</span>
                    )}
                  </div>
                  <p className="text-xl font-bold mt-1.5">{formatVnd(pkg.vnd)}</p>
                  <p className="text-sm text-primary font-medium mt-1">
                    {formatVox(pkg.totalVox)} Vox
                  </p>
                  {pkg.bonus > 0 && (
                    <p className="text-xs text-ok mt-0.5">
                      +{formatVox(pkg.bonus)} Vox tặng
                    </p>
                  )}
                </motion.button>
              )
            })}
          </div>

          {/* Số tiền tùy chọn */}
          <div
            className={`card p-5 transition-colors ${
              useCustom ? 'border-primary bg-primary/5' : ''
            }`}
          >
            <label className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="radio"
                checked={useCustom}
                onChange={() => setUseCustom(true)}
                className="accent-primary"
              />
              <span className="font-medium text-sm">Nhập số tiền khác</span>
            </label>

            {useCustom && (
              <div className="mt-4">
                <label className="label" htmlFor="custom-amount">Số tiền (VNĐ)</label>
                <input
                  id="custom-amount"
                  className="input"
                  inputMode="numeric"
                  placeholder={String(custom.minVnd)}
                  value={customVnd}
                  onChange={(e) => setCustomVnd(e.target.value)}
                />
                <p className="text-xs text-ink-muted mt-2">
                  Từ {formatVnd(custom.minVnd)} tới {formatVnd(custom.maxVnd)} ·
                  tỷ giá {formatVnd(custom.vndPerVox)} một Vox
                </p>

                {customPreview && (
                  <div className="mt-3 text-sm">
                    {customPreview.tooLow && (
                      <p className="text-warn">
                        Tối thiểu {formatVnd(custom.minVnd)}.
                      </p>
                    )}
                    {customPreview.tooHigh && (
                      <p className="text-warn">
                        Tối đa {formatVnd(custom.maxVnd)}. Cần nhiều hơn thì
                        mua thành vài đơn.
                      </p>
                    )}
                    {!customPreview.tooLow && !customPreview.tooHigh && (
                      <p className="text-ink-soft">
                        {formatVnd(customPreview.amount)} →{' '}
                        <strong className="text-primary">
                          {formatVox(customPreview.vox)} Vox
                        </strong>
                        {customPreview.rounded && (
                          <span className="text-ink-muted">
                            {' '}(làm tròn xuống bội {formatVnd(custom.stepVnd)})
                          </span>
                        )}
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Email nhận mã */}
          <div className="card p-5">
            <label className="label" htmlFor="email">
              Email nhận mã <span className="text-ink-muted">(không bắt buộc)</span>
            </label>
            <input
              id="email"
              type="email"
              className="input"
              placeholder="ban@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <p className="text-xs text-ink-muted mt-2 leading-relaxed">
              Mã luôn hiện trên màn hình sau khi thanh toán. Điền email thì có
              thêm một bản sao gửi vào hộp thư, phòng khi bạn lỡ đóng tab.
            </p>
            {email && !EMAIL_RE.test(email) && (
              <p className="text-xs text-warn mt-1.5">Địa chỉ email chưa đúng.</p>
            )}
          </div>

          {submitError && <ErrorBox error={submitError} />}
        </div>

        {/* Tóm tắt đơn */}
        <aside className="lg:sticky lg:top-24 h-fit">
          <div className="card p-5">
            <h2 className="font-semibold">Đơn hàng</h2>
            <div className="mt-4 space-y-2.5 text-sm">
              <div className="flex justify-between">
                <span className="text-ink-soft">Gói</span>
                <span className="font-medium">
                  {useCustom ? 'Tùy chọn' : (selectedPkg ? selectedPkg.label : '—')}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-ink-soft">Số Vox</span>
                <span className="font-medium text-primary">
                  {useCustom
                    ? (customPreview && !customPreview.tooLow && !customPreview.tooHigh
                      ? formatVox(customPreview.vox) : '—')
                    : (selectedPkg ? formatVox(selectedPkg.totalVox) : '—')}
                </span>
              </div>
              <div className="pt-3 border-t border-border-subtle flex justify-between items-baseline">
                <span className="text-ink-soft">Thành tiền</span>
                <motion.span
                  key={useCustom
                    ? (customPreview ? customPreview.amount : 0)
                    : (selectedPkg ? selectedPkg.vnd : 0)}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25 }}
                  className="text-xl font-bold"
                >
                  {useCustom
                    ? (customPreview ? formatVnd(customPreview.amount) : '—')
                    : (selectedPkg ? formatVnd(selectedPkg.vnd) : '—')}
                </motion.span>
              </div>
            </div>

            <button type="submit" disabled={!canSubmit} className="btn-primary w-full mt-5">
              {submitting ? <><Spinner className="w-4 h-4" /> Đang tạo đơn…</> : 'Tiếp tục thanh toán'}
            </button>

            <p className="text-xs text-ink-muted mt-3 leading-relaxed">
              Bước sau thanh toán qua PayOS: quét QR bằng app ngân hàng, hoặc
              trả bằng thẻ/ví. Xong là mã kích hoạt hiện ra ngay trên màn hình.
            </p>
          </div>
        </aside>
      </form>
    </div>
  )
}
