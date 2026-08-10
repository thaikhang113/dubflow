import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { adminApi } from '../../api/client'
import { formatRelative, formatVox, shortFingerprint } from '../../api/format'
import { useFetch } from '../../api/useFetch'
import { Badge, Empty, ErrorBox, Loading, Pager } from '../../components/ui'

const LIMIT = 20

export default function Devices() {
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('search') || '')

  const page = Number(params.get('page')) || 1
  const status = params.get('status') || ''
  const query = params.get('search') || ''

  const { data, error, loading, reload } = useFetch(
    () => adminApi.devices({ page, limit: LIMIT, status, search: query }),
    [page, status, query])

  function update(next) {
    const merged = { page: '1', status, search: query, ...next }
    setParams(Object.fromEntries(
      Object.entries(merged).filter(([, v]) => v && v !== '1' || v > 1)))
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold">Thiết bị</h1>
        <button onClick={reload} className="btn-ghost text-xs py-1.5 px-3">Tải lại</button>
      </div>

      <div className="card p-4 flex flex-wrap gap-3">
        <form
          className="flex gap-2 flex-1 min-w-[240px]"
          onSubmit={(e) => { e.preventDefault(); update({ search }) }}
        >
          <input
            className="input flex-1"
            placeholder="Tìm theo mã máy, tên máy hoặc email…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="submit" className="btn-ghost text-xs px-3">Tìm</button>
        </form>
        <div className="flex gap-1">
          {[['', 'Tất cả'], ['active', 'Đang hoạt động'], ['blocked', 'Đã khóa']].map(
            ([value, label]) => (
              <button
                key={value}
                onClick={() => update({ status: value })}
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
            <Empty title="Không có thiết bị nào khớp." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="th">Máy</th>
                    <th className="th">Số dư</th>
                    <th className="th">Trạng thái</th>
                    <th className="th">Phiên bản</th>
                    <th className="th">Lần cuối</th>
                    <th className="th" />
                  </tr>
                </thead>
                <tbody>
                  {data.data.map((d) => (
                    <tr key={d.fingerprint} className="hover:bg-panel-hover">
                      <td className="td">
                        <p className="font-medium truncate max-w-[220px]">
                          {d.name || 'Máy không tên'}
                        </p>
                        <p className="font-mono text-xs text-ink-muted mt-0.5">
                          {shortFingerprint(d.fingerprint)}
                        </p>
                      </td>
                      <td className="td font-medium whitespace-nowrap">
                        {formatVox(d.balance)} Vox
                      </td>
                      <td className="td">
                        {d.status === 'active'
                          ? <Badge tone="ok">Hoạt động</Badge>
                          : <Badge tone="danger">Đã khóa</Badge>}
                      </td>
                      <td className="td text-ink-soft text-xs">{d.appVersion || '—'}</td>
                      <td className="td text-ink-soft text-xs whitespace-nowrap">
                        {formatRelative(d.lastSeenAt)}
                      </td>
                      <td className="td text-right">
                        <Link
                          to={`/admin/thiet-bi/${d.fingerprint}`}
                          className="btn-ghost text-xs py-1 px-2.5"
                        >
                          Chi tiết
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pager
            page={page}
            total={data.total}
            limit={LIMIT}
            onPage={(p) => setParams({ page: String(p), status, search: query })}
          />
        </div>
      )}
    </div>
  )
}
