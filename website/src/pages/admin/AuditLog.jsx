import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { adminApi } from '../../api/client'
import { formatDate } from '../../api/format'
import { useFetch } from '../../api/useFetch'
import { Empty, ErrorBox, Loading, Pager } from '../../components/ui'

const LIMIT = 50

/** Nhãn tiếng Việt cho các hành động hay gặp; lạ thì hiện mã gốc. */
const ACTION_LABELS = {
  'key.activate': 'Kích hoạt mã',
  'order.paid': 'Đơn thanh toán',
  'order.underpaid': 'Chuyển thiếu tiền',
  'admin.order.approve': 'Duyệt đơn tay',
  'admin.key.issue': 'Phát mã tay',
  'admin.key.revoke': 'Thu hồi mã',
  'admin.credit.grant': 'Cộng Vox tay',
  'admin.credit.deduct': 'Trừ Vox tay',
  'admin.credit.transfer': 'Chuyển Vox',
  'admin.device.status': 'Đổi trạng thái máy',
  'admin.config.update': 'Sửa cấu hình',
  'admin.provider.create': 'Thêm nơi gọi mô hình',
  'admin.provider.update': 'Sửa nơi gọi mô hình',
  'admin.provider.delete': 'Xóa nơi gọi mô hình',
}

function Details({ entry }) {
  const parts = []
  if (entry.before) parts.push(`trước: ${JSON.stringify(entry.before)}`)
  if (entry.after) parts.push(`sau: ${JSON.stringify(entry.after)}`)
  if (!parts.length) return null
  return (
    <p className="font-mono text-[11px] text-ink-muted mt-1 break-all">
      {parts.join(' · ')}
    </p>
  )
}

export default function AuditLog() {
  const [params, setParams] = useSearchParams()
  const [actionSearch, setActionSearch] = useState(params.get('action') || '')
  const [targetSearch, setTargetSearch] = useState(params.get('target') || '')

  const page = Number(params.get('page')) || 1
  const action = params.get('action') || ''
  const target = params.get('target') || ''

  const { data, error, loading, reload } = useFetch(
    () => adminApi.auditLog({ page, limit: LIMIT, action, target }),
    [page, action, target])

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Nhật ký quản trị</h1>
          <p className="text-xs text-ink-muted mt-1">
            Mọi thao tác đụng tới tiền và quyền đều nằm ở đây, lưu vĩnh viễn.
          </p>
        </div>
        <button onClick={reload} className="btn-ghost text-xs py-1.5 px-3">Tải lại</button>
      </div>

      <form
        className="card p-4 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          setParams(Object.fromEntries(Object.entries({
            action: actionSearch, target: targetSearch, page: '1',
          }).filter(([, v]) => v)))
        }}
      >
        <input
          className="input flex-1 min-w-[180px]"
          placeholder="Lọc theo hành động (vd: credit)"
          value={actionSearch}
          onChange={(e) => setActionSearch(e.target.value)}
        />
        <input
          className="input flex-1 min-w-[180px] font-mono"
          placeholder="Lọc theo đối tượng (mã máy, mã đơn…)"
          value={targetSearch}
          onChange={(e) => setTargetSearch(e.target.value)}
        />
        <button type="submit" className="btn-ghost text-xs px-4">Lọc</button>
      </form>

      {loading && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}

      {data && (
        <div className="card overflow-hidden">
          {!data.data.length ? (
            <Empty title="Không có bản ghi nào khớp." />
          ) : (
            data.data.map((entry) => (
              <div
                key={entry._id}
                className="px-5 py-3 border-b border-border-subtle last:border-0"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-sm font-medium">
                    {ACTION_LABELS[entry.action] || entry.action}
                  </span>
                  {entry.target && (
                    <code className="font-mono text-xs text-primary">
                      {entry.target.length > 24
                        ? `${entry.target.slice(0, 12)}…${entry.target.slice(-6)}`
                        : entry.target}
                    </code>
                  )}
                  <span className="text-xs text-ink-muted ml-auto whitespace-nowrap">
                    {entry.actor} · {entry.ip || '—'} · {formatDate(entry.createdAt)}
                  </span>
                </div>
                {entry.note && (
                  <p className="text-xs text-ink-soft mt-1">{entry.note}</p>
                )}
                <Details entry={entry} />
              </div>
            ))
          )}
          <Pager
            page={page}
            total={data.total}
            limit={LIMIT}
            onPage={(p) => setParams(Object.fromEntries(Object.entries({
              page: String(p), action, target,
            }).filter(([, v]) => v)))}
          />
        </div>
      )}
    </div>
  )
}
