import { useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { formatVnd, formatVox } from '../api/format'
import { useFetch } from '../api/useFetch'
import { ErrorBox, Loading } from '../components/ui'
import { HoverLift, Reveal, Stagger, StaggerItem } from '../components/motion'
import { estimateCapacity, packageDetails } from '../data/packages'

const FAQ = [
  ['Vox có hết hạn không?',
   'Không. Vox nằm trong ví của máy bạn cho tới khi dùng hết.'],
  ['Một video tốn bao nhiêu Vox?',
   'Tính theo số câu thoại: 10 Vox mỗi câu, 12 nếu bật dịch tự động qua máy '
   + 'chủ, cộng 20 nếu tạo tiêu đề + mô tả đăng bài. Video 10 phút thường có '
   + '150–300 câu. Ứng dụng báo đúng tổng số trước khi trừ ví.'],
  ['Có phải trả tiền hàng tháng không?',
   'Không. Không có thuê bao, không tự động gia hạn. Mua một lần dùng dần.'],
  ['Thanh toán bằng cách nào?',
   'Qua PayOS: quét QR bằng app ngân hàng bất kỳ, thẻ ATM, Visa/Mastercard '
   + 'hoặc ví điện tử. Hệ thống tự khớp đơn, mã kích hoạt hiện ra ngay khi '
   + 'thanh toán xong.'],
  ['Mua rồi mà đổi máy thì sao?',
   'Liên hệ hỗ trợ kèm mã máy (xem ở trang Tài khoản trong ứng dụng), chúng '
   + 'tôi chuyển số Vox còn lại sang máy mới.'],
  ['Thanh toán xong mà chưa thấy mã?',
   'Hiếm khi xảy ra — thường mã hiện ra trong vài giây. Nếu sau 5 phút vẫn '
   + 'chưa thấy, liên hệ hỗ trợ kèm mã đơn hàng (VOXxxxxxx), chúng tôi cấp mã '
   + 'thủ công ngay.'],
]

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" className="w-4 h-4 text-ok shrink-0 mt-0.5" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  )
}

function PackageCard({ pkg, rate }) {
  const details = packageDetails(pkg.id)
  const cap = estimateCapacity(pkg.totalVox)
  const perVox = pkg.vnd / pkg.totalVox
  const saving = Math.round((1 - perVox / rate) * 100)
  return (
    <HoverLift className="h-full">
      <div
        className={`card p-6 relative flex flex-col h-full ${
          pkg.popular
            ? 'border-primary shadow-lg shadow-primary/20 animate-pulse-glow lg:scale-[1.03]'
            : ''
        }`}
      >
        {pkg.popular && (
          <span className="absolute -top-2.5 left-6 badge bg-gradient-to-r from-primary to-accent text-white">
            Phổ biến nhất
          </span>
        )}
        {!pkg.popular && saving > 0 && (
          <span className="absolute -top-2.5 right-4 badge bg-ok/15 text-ok border border-ok/30">
            Tiết kiệm {saving}%
          </span>
        )}
        <p className="text-sm text-ink-soft">{pkg.label}</p>
        <p className="text-3xl font-bold mt-2">{formatVnd(pkg.vnd)}</p>
        <p className="text-xs text-ink-muted mt-1">{details.tagline}</p>

        <div className="mt-4 pb-4 border-b border-border-subtle">
          <p className="text-primary font-semibold text-lg">
            {formatVox(pkg.totalVox)} Vox
          </p>
          {pkg.bonus > 0 && (
            <p className="text-xs text-ok mt-1">
              Gồm {formatVox(pkg.bonus)} Vox tặng thêm
              {saving > 0 && ` · rẻ hơn ${saving}%`}
            </p>
          )}
        </div>

        <ul className="mt-4 space-y-2 text-sm text-ink-soft flex-1">
          <li className="flex gap-2">
            <CheckIcon />
            <span>
              ≈ <strong className="text-ink">{formatVox(cap.segments)}</strong> câu
              thoại dịch tự động
            </span>
          </li>
          <li className="flex gap-2">
            <CheckIcon />
            <span>
              ≈ <strong className="text-ink">{formatVox(cap.minutes)}</strong> phút
              video lồng tiếng (~{cap.videos} video 10 phút)
            </span>
          </li>
          {details.perks.map((perk) => (
            <li key={perk} className="flex gap-2">
              <CheckIcon />
              <span>{perk}</span>
            </li>
          ))}
        </ul>

        <Link
          to={`/mua?goi=${pkg.id}`}
          className={`mt-6 ${pkg.popular ? 'btn-primary' : 'btn-ghost'} w-full`}
        >
          Chọn gói này
        </Link>
      </div>
    </HoverLift>
  )
}

/** Accordion FAQ — mở/đóng mượt bằng animate height. */
function FaqItem({ q, a }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-5 py-4 text-left"
        aria-expanded={open}
      >
        <span className="font-medium text-sm">{q}</span>
        <motion.svg
          viewBox="0 0 24 24"
          className="w-4 h-4 text-ink-muted shrink-0"
          fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.25 }}
        >
          <path d="m6 9 6 6 6-6" />
        </motion.svg>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            <p className="text-ink-soft text-sm px-5 pb-4 leading-relaxed">{a}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export default function Pricing() {
  const { data, error, loading, reload } = useFetch(() => api.packages())
  // Đơn giá lấy từ máy chủ để website không bao giờ lệch với app;
  // chưa tải xong thì dùng giá niêm yết hiện hành làm khung.
  const { data: cfg } = useFetch(() => api.appConfig())
  const pricing = (cfg && cfg.pricing) || {}
  const base = pricing.segmentBase || 10
  const auto = base + (pricing.segmentAutoTranslate || 2)
  const meta = pricing.metadata || 20

  return (
    <div className="max-w-6xl mx-auto px-4 py-14">
      <Reveal>
        <div className="text-center">
          <p className="inline-flex badge bg-primary/10 text-primary border border-primary/20 mb-4">
            1 Vox = 10đ · 1.000 Vox = 10.000đ
          </p>
          <h1 className="text-3xl font-bold">Bảng giá</h1>
          <p className="text-ink-soft mt-3 max-w-2xl mx-auto">
            Giá tính theo số câu thoại của video: {base} Vox mỗi câu, {auto} nếu
            bật dịch tự động qua máy chủ, cộng {meta} Vox trọn gói nếu tạo tiêu
            đề + mô tả đăng bài. Ứng dụng báo tổng Vox trước khi trừ ví và con
            số đó không đổi nữa.
          </p>
        </div>
      </Reveal>

      {loading && <Loading label="Đang tải bảng giá…" />}
      {error && (
        <div className="mt-8 max-w-lg mx-auto">
          <ErrorBox error={error} onRetry={reload} />
        </div>
      )}

      {data && (
        <>
          {!data.creditEnabled && (
            <div className="card border-ok/30 bg-ok/5 p-4 mt-8 text-center">
              <p className="text-sm text-ok font-medium">
                Hiện đang miễn phí toàn bộ
              </p>
              <p className="text-xs text-ink-soft mt-1">
                Hệ thống Vox đang tạm tắt — bạn dùng thoải mái, không cần mua gì.
              </p>
            </div>
          )}

          <Stagger className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {data.packages.map((pkg) => (
              <StaggerItem key={pkg.id} className="h-full">
                <PackageCard pkg={pkg} rate={data.custom.vndPerVox} />
              </StaggerItem>
            ))}
          </Stagger>

          <Reveal>
            <div className="card p-6 mt-5 flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="flex-1">
                <h3 className="font-semibold">Muốn số tiền khác?</h3>
                <p className="text-ink-soft text-sm mt-1">
                  Nhập bất kỳ số tiền nào từ {formatVnd(data.custom.minVnd)} trở
                  lên, quy đổi theo tỷ giá {formatVnd(data.custom.vndPerVox)} một Vox.
                </p>
              </div>
              <Link to="/mua?tuy-chon=1" className="btn-ghost shrink-0">
                Nhập số tiền
              </Link>
            </div>
          </Reveal>

          <Reveal>
            <div className="mt-14 max-w-3xl mx-auto">
              <h2 className="text-xl font-bold text-center">Câu hỏi về giá</h2>
              <div className="mt-6 space-y-3">
                {FAQ.map(([q, a]) => (
                  <FaqItem key={q} q={q} a={a} />
                ))}
              </div>
            </div>
          </Reveal>
        </>
      )}
    </div>
  )
}
