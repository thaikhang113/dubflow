import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { adminApi } from '../../api/client'
import { formatDate, formatVox, shortFingerprint } from '../../api/format'
import { useFetch } from '../../api/useFetch'
import {
  Badge, CopyButton, Empty, ErrorBox, Loading, Modal, Pager, Spinner,
} from '../../components/ui'

const LIMIT = 20

const STATUS = {
  issued: { tone: 'info', label: 'Chưa dùng' },
  used: { tone: 'ok', label: 'Đã dùng' },
  revoked: { tone: 'danger', label: 'Đã thu hồi' },
}

/** Phát mã tay — bồi thường sự cố, tặng KOL, bán ngoài luồng. */
function IssueModal({ open, onClose, onDone }) {
  const [vox, setVox] = useState('1000')
  const [count, setCount] = useState('1')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [issued, setIssued] = useState(null)

  const voxNum = Number(vox) || 0
  const countNum = Number(count) || 0
  const valid = voxNum >= 1 && countNum >= 1 && countNum <= 100 && note.trim().length >= 3

  async function submit() {
    setBusy(true)
    setError('')
    try {
      const res = await adminApi.issueKeys(voxNum, countNum, note.trim())
      setIssued(res.keys)
      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function close() {
    setIssued(null); setNote(''); setError('')
    onClose()
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title={issued ? `Đã phát ${issued.length} mã` : 'Phát mã kích hoạt'}
      footer={issued
        ? <button onClick={close} className="btn-primary">Xong</button>
        : (
          <>
            <button onClick={close} className="btn-ghost">Hủy</button>
            <button onClick={submit} disabled={!valid || busy} className="btn-primary">
              {busy ? <Spinner className="w-4 h-4" /> : `Phát ${countNum} mã`}
            </button>
          </>
        )}
    >
      {issued ? (
        <div>
          <p className="text-sm text-ink-soft mb-3">
            Chép lại các mã dưới đây — chúng cũng nằm trong danh sách mã.
          </p>
          <div className="bg-input rounded-xl p-3 max-h-64 overflow-y-auto space-y-1.5">
            {issued.map((k) => (
              <div key={k.code} className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm">{k.code}</span>
                <span className="text-xs text-ink-muted">{formatVox(k.vox)} Vox</span>
              </div>
            ))}
          </div>
          <div className="mt-3">
            <CopyButton
              value={issued.map((k) => k.code).join('\n')}
              label="Chép tất cả"
            />
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Vox mỗi mã</label>
              <input
                className="input"
                inputMode="numeric"
                value={vox}
                onChange={(e) => setVox(e.target.value.replace(/\D/g, ''))}
              />
            </div>
            <div>
              <label className="label">Số lượng mã</label>
              <input
                className="input"
                inputMode="numeric"
                value={count}
                onChange={(e) => setCount(e.target.value.replace(/\D/g, ''))}
              />
              {countNum > 100 && (
                <p className="text-xs text-warn mt-1">Tối đa 100 mã mỗi lần.</p>
              )}
            </div>
          </div>

          <label className="label mt-4">Ghi chú (bắt buộc)</label>
          <input
            className="input"
            placeholder="Bồi thường sự cố 07/08 — 12 người dùng bị ảnh hưởng"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <p className="text-xs text-ink-muted mt-1.5">
            Tổng phát ra: {formatVox(voxNum * countNum)} Vox. Ghi chú lưu vĩnh
            viễn trong nhật ký quản trị.
          </p>

          {error && <p className="text-danger text-xs mt-3">{error}</p>}
        </>
      )}
    </Modal>
  )
}

export default function Keys() {
  const [params, setParams] = useSearchParams()
  const [codeSearch, setCodeSearch] = useState(params.get('code') || '')
  const [issuing, setIssuing] = useState(false)
  const [revoking, setRevoking] = useState(null)
  const [revokeError, setRevokeError] = useState('')

  const page = Number(params.get('page')) || 1
  const status = params.get('status') || ''
  const code = params.get('code') || ''

  const { data, error, loading, reload } = useFetch(
    () => adminApi.keys({ page, limit: LIMIT, status, code }),
    [page, status, code])

  function setFilter(next) {
    setParams(Object.fromEntries(Object.entries({
      status, code, ...next, page: '1',
    }).filter(([, v]) => v)))
  }

  async function revoke() {
    setRevokeError('')
    try {
      await adminApi.revokeKey(revoking.code)
      setRevoking(null)
      reload()
    } catch (err) {
      setRevokeError(err.message)
    }
  }

  return (
    <div className="max-w-7xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold">Mã kích hoạt</h1>
        <div className="flex gap-2">
          <button onClick={reload} className="btn-ghost text-xs py-1.5 px-3">Tải lại</button>
          <button onClick={() => setIssuing(true)} className="btn-primary text-xs py-1.5 px-3">
            Phát mã
          </button>
        </div>
      </div>

      <div className="card p-4 flex flex-wrap gap-3">
        <form
          className="flex gap-2 flex-1 min-w-[220px]"
          onSubmit={(e) => { e.preventDefault(); setFilter({ code: codeSearch }) }}
        >
          <input
            className="input flex-1 font-mono"
            placeholder="VOX-XXXX-XXXX-XXXX"
            value={codeSearch}
            onChange={(e) => setCodeSearch(e.target.value.toUpperCase())}
          />
          <button type="submit" className="btn-ghost text-xs px-3">Tìm</button>
        </form>
        <div className="flex gap-1 flex-wrap">
          {[['', 'Tất cả'], ['issued', 'Chưa dùng'], ['used', 'Đã dùng'], ['revoked', 'Thu hồi']]
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
            <Empty title="Không có mã nào khớp." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="th">Mã</th>
                    <th className="th">Vox</th>
                    <th className="th">Trạng thái</th>
                    <th className="th">Nguồn</th>
                    <th className="th">Máy đã dùng</th>
                    <th className="th">Tạo lúc</th>
                    <th className="th" />
                  </tr>
                </thead>
                <tbody>
                  {data.data.map((k) => {
                    const meta = STATUS[k.status] || STATUS.issued
                    return (
                      <tr key={k.code} className="hover:bg-panel-hover">
                        <td className="td font-mono text-xs">
                          <span className="flex items-center gap-1.5">
                            {k.code}
                            <CopyButton value={k.code} label="" className="!px-1.5" />
                          </span>
                        </td>
                        <td className="td">{formatVox(k.vox)}</td>
                        <td className="td"><Badge tone={meta.tone}>{meta.label}</Badge></td>
                        <td className="td text-ink-soft text-xs">
                          {k.source}
                          {k.note && (
                            <span className="block text-ink-muted truncate max-w-[160px]">
                              {k.note}
                            </span>
                          )}
                        </td>
                        <td className="td text-xs">
                          {k.usedByFingerprint ? (
                            <Link
                              to={`/admin/thiet-bi/${k.usedByFingerprint}`}
                              className="font-mono text-primary hover:underline"
                            >
                              {shortFingerprint(k.usedByFingerprint)}
                            </Link>
                          ) : <span className="text-ink-muted">—</span>}
                        </td>
                        <td className="td text-ink-soft text-xs whitespace-nowrap">
                          {formatDate(k.createdAt)}
                        </td>
                        <td className="td text-right">
                          {k.status === 'issued' && (
                            <button
                              onClick={() => { setRevoking(k); setRevokeError('') }}
                              className="btn-ghost text-xs py-1 px-2.5"
                            >
                              Thu hồi
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
            onPage={(p) => setParams({ page: String(p), status, code })}
          />
        </div>
      )}

      <IssueModal open={issuing} onClose={() => setIssuing(false)} onDone={reload} />

      <Modal
        open={Boolean(revoking)}
        onClose={() => setRevoking(null)}
        title="Thu hồi mã"
        footer={
          <>
            <button onClick={() => setRevoking(null)} className="btn-ghost">Hủy</button>
            <button onClick={revoke} className="btn-danger">Thu hồi</button>
          </>
        }
      >
        <p className="text-sm text-ink-soft leading-relaxed">
          Mã <strong className="font-mono text-ink">{revoking?.code}</strong> sẽ
          không kích hoạt được nữa. Chỉ thu hồi được mã CHƯA dùng — mã đã kích
          hoạt thì phải trừ Vox trực tiếp trên thiết bị.
        </p>
        {revokeError && <p className="text-danger text-xs mt-3">{revokeError}</p>}
      </Modal>
    </div>
  )
}
