import { useState } from 'react'
import { Link } from 'react-router-dom'

import { adminApi } from '../../api/client'
import { formatVnd, formatVox } from '../../api/format'
import { useFetch } from '../../api/useFetch'
import { ErrorBox, Loading } from '../../components/ui'

const RANGES = [
  { days: 1, label: 'Hôm nay' },
  { days: 7, label: '7 ngày' },
  { days: 30, label: '30 ngày' },
  { days: 90, label: '90 ngày' },
]

function Stat({ label, value, sub, tone = '' }) {
  return (
    <div className="card p-5">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className={`text-2xl font-bold mt-1.5 ${tone}`}>{value}</p>
      {sub && <p className="text-xs text-ink-muted mt-1">{sub}</p>}
    </div>
  )
}

/** Biểu đồ cột thuần CSS — không đáng kéo thêm thư viện vẽ cho một bảng. */
function UsageChart({ rows }) {
  const byDate = new Map()
  for (const r of rows) {
    const date = r._id.date
    const entry = byDate.get(date) || { date, requests: 0, sentences: 0, credit: 0 }
    entry.requests += r.requests
    entry.sentences += r.sentences
    entry.credit += r.credit
    byDate.set(date, entry)
  }
  const days = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date))
  if (!days.length) {
    return <p className="text-sm text-ink-muted py-8 text-center">Chưa có dữ liệu.</p>
  }
  const max = Math.max(...days.map((d) => d.credit), 1)

  return (
    <div className="flex items-end gap-1 h-40 mt-4">
      {days.map((d) => (
        <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group relative">
          <div
            className="w-full bg-primary/70 hover:bg-primary rounded-t transition-colors min-h-[2px]"
            style={{ height: `${(d.credit / max) * 100}%` }}
          />
          <span className="text-[9px] text-ink-muted rotate-45 origin-left whitespace-nowrap h-4">
            {d.date.slice(5)}
          </span>
          <div className="absolute bottom-full mb-1 hidden group-hover:block bg-panel border border-border rounded-lg px-2.5 py-1.5 text-xs whitespace-nowrap z-10 shadow-lg">
            <p className="font-medium">{d.date}</p>
            <p className="text-ink-soft">{formatVox(d.credit)} Vox · {d.sentences} câu</p>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [days, setDays] = useState(7)
  const overview = useFetch(() => adminApi.overview(days), [days])
  const usage = useFetch(() => adminApi.usage(days), [days])

  if (overview.loading) return <Loading />
  if (overview.error) return <ErrorBox error={overview.error} onRetry={overview.reload} />

  const d = overview.data
  const ai = d.ai || {}
  const success = ai.success || {}
  const failed = ai.error || {}
  const orders = d.orders || {}
  const keys = d.keys || {}

  return (
    <div className="max-w-7xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold">Tổng quan</h1>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.days}
              onClick={() => setDays(r.days)}
              className={`px-3 py-1.5 rounded-lg text-xs transition-colors ${
                days === r.days ? 'bg-primary text-white' : 'btn-ghost'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Doanh thu"
          value={formatVnd(d.revenue.vnd)}
          sub={`${d.revenue.paidOrders} đơn đã thanh toán`}
          tone="text-ok"
        />
        <Stat
          label="Thiết bị hoạt động"
          value={d.devices.active.toLocaleString('vi-VN')}
          sub={`${d.devices.new} máy mới · ${d.devices.total} tổng cộng`}
        />
        <Stat
          label="Vox đã tiêu"
          value={formatVox(d.credit.consumed)}
          sub={`Đã phát ra ${formatVox(d.credit.issued)}`}
        />
        <Stat
          label="Vox đang lưu hành"
          value={formatVox(d.credit.outstanding)}
          sub="Tổng số dư trong mọi ví"
          tone="text-warn"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="card p-5">
          <h2 className="font-semibold text-sm">Vox tiêu thụ theo ngày</h2>
          {usage.loading && <Loading />}
          {usage.error && <ErrorBox error={usage.error} onRetry={usage.reload} />}
          {usage.data && <UsageChart rows={usage.data.data} />}
        </div>

        <div className="space-y-4">
          <div className="card p-5">
            <h2 className="font-semibold text-sm">Lượt gọi mô hình</h2>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-soft">Thành công</dt>
                <dd className="font-medium text-ok">
                  {(success.requests || 0).toLocaleString('vi-VN')}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-soft">Thất bại</dt>
                <dd className={`font-medium ${failed.requests ? 'text-danger' : ''}`}>
                  {(failed.requests || 0).toLocaleString('vi-VN')}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-soft">Câu đã dịch</dt>
                <dd className="font-medium">
                  {(success.sentences || 0).toLocaleString('vi-VN')}
                </dd>
              </div>
              <div className="flex justify-between pt-2 border-t border-border-subtle">
                <dt className="text-ink-soft">Token đã dùng</dt>
                <dd className="font-medium">
                  {(((success.promptTokens || 0) + (success.completionTokens || 0)) / 1000)
                    .toFixed(1)}K
                </dd>
              </div>
            </dl>
          </div>

          <div className="card p-5">
            <h2 className="font-semibold text-sm">Đơn hàng</h2>
            <dl className="mt-3 space-y-2 text-sm">
              {[
                ['Đã thanh toán', orders.paid || 0, 'text-ok'],
                ['Đang chờ', orders.pending || 0, 'text-warn'],
                ['Hết hạn', orders.expired || 0, ''],
              ].map(([label, value, tone]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-ink-soft">{label}</dt>
                  <dd className={`font-medium ${tone}`}>{value}</dd>
                </div>
              ))}
            </dl>
            {(orders.pending || 0) > 0 && (
              <Link
                to="/admin/don-hang?status=pending"
                className="btn-ghost w-full mt-4 text-xs py-2"
              >
                Xem đơn đang chờ
              </Link>
            )}
          </div>

          <div className="card p-5">
            <h2 className="font-semibold text-sm">Mã kích hoạt</h2>
            <dl className="mt-3 space-y-2 text-sm">
              {[
                ['Đã dùng', keys.used],
                ['Chưa dùng', keys.issued],
                ['Đã thu hồi', keys.revoked],
              ].map(([label, entry]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-ink-soft">{label}</dt>
                  <dd className="font-medium">
                    {entry ? `${entry.count} · ${formatVox(entry.vox)} Vox` : '0'}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </div>
    </div>
  )
}
