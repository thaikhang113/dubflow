import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { adminApi } from '../../api/client'
import { formatDate, formatVnd, formatVox } from '../../api/format'
import { useFetch } from '../../api/useFetch'
import {
  Badge, CopyButton, Empty, ErrorBox, Loading, Modal, Pager, Spinner,
} from '../../components/ui'

const LIMIT = 20

const STATUS = {
  paid: { tone: 'ok', label: 'Đã thanh toán' },
  pending: { tone: 'warn', label: 'Chờ thanh toán' },
  expired: { tone: 'muted', label: 'Hết hạn' },
  cancelled: { tone: 'muted', label: 'Đã hủy' },
}

/**
 * Duyệt tay một đơn.
 *
 * Dùng khi webhook PayOS lỗi hoặc gián đoạn mà tiền đã vào thật. Cấp key khi
 * CHƯA đối chiếu giao dịch trên dashboard PayOS là mất tiền thật, nên hộp
 * thoại này bắt buộc ghi lý do.
 */
function ApproveModal({ open, onClose, order, onDone }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  async function submit() {
    setBusy(true)
    setError('')
    try {
      const res = await adminApi.approveOrder(order.orderCode, note.trim())
      setResult(res)
      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function close() {
    setResult(null); setNote(''); setError('')
    onClose()
  }

  if (!order) return null

  return (
    <Modal
      open={open}
      onClose={close}
      title={result ? 'Đã cấp mã' : `Duyệt đơn ${order.orderCode}`}
      footer={result
        ? <button onClick={close} className="btn-primary">Xong</button>
        : (
          <>
            <button onClick={close} className="btn-ghost">Hủy</button>
            <button
              onClick={submit}
              disabled={busy || note.trim().length < 5}
              className="btn-primary"
            >
              {busy ? <Spinner className="w-4 h-4" /> : 'Duyệt và cấp mã'}
            </button>
          </>
        )}
    >
      {result ? (
        <div>
          <p className="text-sm text-ink-soft">
            {result.alreadyPaid
              ? 'Đơn này đã được thanh toán từ trước — mã đã cấp:'
              : 'Mã kích hoạt đã được tạo và gửi vào email (nếu người mua có điền):'}
          </p>
          <div className="bg-input rounded-xl px-4 py-3 mt-3 flex items-center justify-between gap-3">
            <p className="font-mono font-semibold tracking-wider">{result.keyCode}</p>
            <CopyButton value={result.keyCode} />
          </div>
        </div>
      ) : (
        <>
          <div className="bg-warn/10 border border-warn/25 rounded-xl px-4 py-3 mb-4">
            <p className="text-xs text-warn leading-relaxed">
              Chỉ duyệt sau khi đã <strong>đối chiếu sao kê ngân hàng</strong> và
              xác nhận tiền thật sự vào. Thao tác này tạo mã kích hoạt ngay và
              không có nút hoàn tác.
            </p>
          </div>

          <dl className="text-sm space-y-2">
            {[
              ['Số tiền', formatVnd(order.amountVnd)],
              ['Số Vox', formatVox(order.vox)],
              ['Tạo lúc', formatDate(order.createdAt)],
              ['Email', order.email || '— (không có)'],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <dt className="text-ink-soft">{k}</dt>
                <dd className="font-medium">{v}</dd>
              </div>
            ))}
          </dl>

          <label className="label mt-4">Ghi chú (bắt buộc)</label>
          <input
            className="input"
            placeholder="Đã đối chiếu sao kê 14:32 ngày 07/08, CK thiếu nội dung"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          {error && <p className="text-danger text-xs mt-3">{error}</p>}
        </>
      )}
    </Modal>
  )
}

export default function Orders() {
  const [params, setParams] = useSearchParams()
  const [codeSearch, setCodeSearch] = useState(params.get('orderCode') || '')
  const [approving, setApproving] = useState(null)

  const page = Number(params.get('page')) || 1
  const status = params.get('status') || ''
  const orderCode = params.get('orderCode') || ''

  const { data, error, loading, reload } = useFetch(
    () => adminApi.orders({ page, limit: LIMIT, status, orderCode }),
    [page, status, orderCode])

  function setFilter(next) {
    setParams(Object.fromEntries(Object.entries({
      status, orderCode, ...next, page: '1',
    }).filter(([, v]) => v)))
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold">Đơn hàng</h1>
        <button onClick={reload} className="btn-ghost text-xs py-1.5 px-3">Tải lại</button>
      </div>

      <div className="card p-4 flex flex-wrap gap-3">
        <form
          className="flex gap-2 flex-1 min-w-[220px]"
          onSubmit={(e) => { e.preventDefault(); setFilter({ orderCode: codeSearch }) }}
        >
          <input
            className="input flex-1 font-mono"
            placeholder="VOX123456"
            value={codeSearch}
            onChange={(e) => setCodeSearch(e.target.value.toUpperCase())}
          />
          <button type="submit" className="btn-ghost text-xs px-3">Tìm</button>
        </form>
        <div className="flex gap-1 flex-wrap">
          {[['', 'Tất cả'], ['pending', 'Đang chờ'], ['paid', 'Đã trả'], ['expired', 'Hết hạn']]
            .map(([value, label]) => (
              <button
                key={value}
                onClick={() => setFilter({ status: value })}
                className={`px-3 py-1.5 rounded-lg text-xs whitespace-nowrap ${
                  status === value ? 'bg-primary text-white' : 'btn-ghost'
                }`}
              >
                {label}
              </button>
            ))}
        </div>
      </div>

      {loading && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}

      {data && (
        <div className="card overflow-hidden">
          {!data.data.length ? (
            <Empty title="Không có đơn hàng nào khớp." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="th">Mã đơn</th>
                    <th className="th">Số tiền</th>
                    <th className="th">Vox</th>
                    <th className="th">Trạng thái</th>
                    <th className="th">Mã kích hoạt</th>
                    <th className="th">Email</th>
                    <th className="th">Tạo lúc</th>
                    <th className="th" />
                  </tr>
                </thead>
                <tbody>
                  {data.data.map((o) => {
                    const meta = STATUS[o.status] || STATUS.pending
                    return (
                      <tr key={o.orderCode} className="hover:bg-panel-hover">
                        <td className="td font-mono text-xs font-medium">{o.orderCode}</td>
                        <td className="td whitespace-nowrap">{formatVnd(o.amountVnd)}</td>
                        <td className="td">{formatVox(o.vox)}</td>
                        <td className="td"><Badge tone={meta.tone}>{meta.label}</Badge></td>
                        <td className="td font-mono text-xs">
                          {o.keyCode ? (
                            <span className="flex items-center gap-1.5">
                              {o.keyCode}
                              <CopyButton value={o.keyCode} label="" className="!px-1.5" />
                            </span>
                          ) : '—'}
                        </td>
                        <td className="td text-ink-soft text-xs truncate max-w-[160px]">
                          {o.email || '—'}
                        </td>
                        <td className="td text-ink-soft text-xs whitespace-nowrap">
                          {formatDate(o.createdAt)}
                        </td>
                        <td className="td text-right">
                          {o.status !== 'paid' && (
                            <button
                              onClick={() => setApproving(o)}
                              className="btn-ghost text-xs py-1 px-2.5"
                            >
                              Duyệt tay
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <Pager
            page={page}
            total={data.total}
            limit={LIMIT}
            onPage={(p) => setParams({ page: String(p), status, orderCode })}
          />
        </div>
      )}

      <ApproveModal
        open={Boolean(approving)}
        order={approving}
        onClose={() => setApproving(null)}
        onDone={reload}
      />
    </div>
  )
}
