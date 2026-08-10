import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { formatDate, formatVnd, formatVox } from '../api/format'
import { Badge, CopyButton, Empty } from '../components/ui'
import { forgetOrder, listOrders, markOrderPaid } from '../store/orders'

const STATUS = {
  paid: { tone: 'ok', label: 'Đã thanh toán' },
  pending: { tone: 'warn', label: 'Chờ thanh toán' },
  expired: { tone: 'muted', label: 'Hết hạn' },
  cancelled: { tone: 'muted', label: 'Đã hủy' },
}

export default function MyOrders() {
  const [orders, setOrders] = useState(() => listOrders())
  const [live, setLive] = useState({})

  // Đơn nào chưa chốt thì hỏi lại máy chủ một lần khi mở trang — người dùng
  // hay quay lại đây sau khi đã thanh toán ở tab khác.
  useEffect(() => {
    let alive = true
    const pending = orders.filter((o) => !o.keyCode)
    Promise.all(pending.map(async (o) => {
      try {
        const fresh = await api.getOrder(o.orderCode, o.accessToken)
        if (fresh.status === 'paid' && fresh.keyCode) {
          markOrderPaid(o.orderCode, fresh.keyCode)
        }
        return [o.orderCode, fresh]
      } catch {
        return null
      }
    })).then((pairs) => {
      if (!alive) return
      setLive(Object.fromEntries(pairs.filter(Boolean)))
      setOrders(listOrders())
    })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function remove(orderCode) {
    forgetOrder(orderCode)
    setOrders(listOrders())
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-14">
      <h1 className="text-3xl font-bold">Đơn hàng của tôi</h1>
      <p className="text-ink-soft mt-2.5 text-sm leading-relaxed">
        Danh sách này lưu trong chính trình duyệt này, không nằm trên máy chủ.
        Xóa lịch sử trình duyệt hoặc mở ở máy khác thì sẽ không thấy — vì vậy
        hãy chép mã kích hoạt ra chỗ an toàn ngay khi nhận được.
      </p>

      {!orders.length ? (
        <div className="card mt-8">
          <Empty
            title="Chưa có đơn hàng nào trên trình duyệt này."
            hint="Đơn bạn tạo sẽ xuất hiện ở đây."
          />
          <div className="text-center pb-8">
            <Link to="/mua" className="btn-primary">Mua Vox</Link>
          </div>
        </div>
      ) : (
        <div className="space-y-3 mt-8">
          {orders.map((o) => {
            const fresh = live[o.orderCode]
            const status = fresh ? fresh.status : (o.keyCode ? 'paid' : 'pending')
            const meta = STATUS[status] || STATUS.pending
            const keyCode = o.keyCode || (fresh && fresh.keyCode) || ''
            return (
              <div key={o.orderCode} className="card p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2.5">
                      <span className="font-mono font-semibold">{o.orderCode}</span>
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                    </div>
                    <p className="text-xs text-ink-muted mt-1.5">
                      {formatDate(o.createdAt)} · {formatVnd(o.amountVnd)} ·{' '}
                      {formatVox(o.vox)} Vox
                    </p>
                  </div>
                  <div className="flex gap-2">
                    {status === 'pending' && (
                      <Link
                        to={`/thanh-toan/${o.orderCode}`}
                        className="btn-primary text-xs py-1.5 px-3"
                      >
                        Tiếp tục
                      </Link>
                    )}
                    <button
                      onClick={() => remove(o.orderCode)}
                      className="btn-ghost text-xs py-1.5 px-3"
                      title="Chỉ xóa khỏi danh sách trên máy này"
                    >
                      Ẩn
                    </button>
                  </div>
                </div>

                {keyCode && (
                  <div className="mt-4 bg-input rounded-xl px-4 py-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-xs text-ink-muted">Mã kích hoạt</p>
                      <p className="font-mono font-semibold tracking-wider mt-0.5 truncate">
                        {keyCode}
                      </p>
                    </div>
                    <CopyButton value={keyCode} className="shrink-0" />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
