import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { adminApi } from '../../api/client'
import { formatDate, formatRelative, formatVox } from '../../api/format'
import { useFetch } from '../../api/useFetch'
import {
  Badge, CopyButton, Empty, ErrorBox, Loading, Modal, Spinner,
} from '../../components/ui'

const LEDGER_LABELS = {
  activation: 'Kích hoạt mã',
  trial: 'Tặng dùng thử',
  usage: 'Sử dụng',
  admin_grant: 'Quản trị cộng',
  admin_deduct: 'Quản trị trừ',
  refund: 'Hoàn lại',
  transfer_in: 'Nhận chuyển sang',
  transfer_out: 'Chuyển đi',
}

const ACTION_LABELS = {
  translate: 'Dịch',
  analyze: 'Phân tích ngữ cảnh',
  review: 'Rà soát',
  generate_post: 'Nội dung đăng bài',
}

/** Hộp thoại cộng/trừ Vox. Bắt buộc có lý do — sổ cái là vĩnh viễn. */
function CreditModal({ open, onClose, fingerprint, balance, onDone }) {
  const [delta, setDelta] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const value = Number(delta) || 0
  const after = balance + value
  const valid = value !== 0 && reason.trim().length >= 3 && after >= 0

  async function submit() {
    setBusy(true)
    setError('')
    try {
      await adminApi.adjustCredit(fingerprint, value, reason.trim())
      onDone()
      onClose()
      setDelta(''); setReason('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Cộng hoặc trừ Vox"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">Hủy</button>
          <button onClick={submit} disabled={!valid || busy} className="btn-primary">
            {busy ? <Spinner className="w-4 h-4" /> : 'Xác nhận'}
          </button>
        </>
      }
    >
      <label className="label">Số Vox (âm để trừ)</label>
      <input
        className="input"
        inputMode="numeric"
        placeholder="500 hoặc -500"
        value={delta}
        onChange={(e) => setDelta(e.target.value.replace(/[^\d-]/g, ''))}
      />
      {value !== 0 && (
        <p className={`text-xs mt-1.5 ${after < 0 ? 'text-danger' : 'text-ink-soft'}`}>
          {formatVox(balance)} → {formatVox(after)} Vox
          {after < 0 && ' — không thể trừ quá số dư'}
        </p>
      )}

      <label className="label mt-4">Lý do</label>
      <input
        className="input"
        placeholder="Bồi thường sự cố ngày 07/08"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <p className="text-xs text-ink-muted mt-1.5">
        Lý do được ghi vĩnh viễn vào sổ cái và nhật ký quản trị.
      </p>

      {error && <p className="text-danger text-xs mt-3">{error}</p>}
    </Modal>
  )
}

/** Hộp thoại chuyển toàn bộ Vox sang máy mới. */
function TransferModal({ open, onClose, fingerprint, balance, onDone }) {
  const [target, setTarget] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const valid = /^[a-f0-9]{64}$/i.test(target.trim())
    && reason.trim().length >= 3 && balance > 0

  async function submit() {
    setBusy(true)
    setError('')
    try {
      await adminApi.transferCredit(fingerprint, target.trim().toLowerCase(), reason.trim())
      onDone()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Chuyển Vox sang máy mới"
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">Hủy</button>
          <button onClick={submit} disabled={!valid || busy} className="btn-primary">
            {busy ? <Spinner className="w-4 h-4" /> : `Chuyển ${formatVox(balance)} Vox`}
          </button>
        </>
      }
    >
      <div className="bg-warn/10 border border-warn/25 rounded-xl px-4 py-3 mb-4">
        <p className="text-xs text-warn leading-relaxed">
          Toàn bộ {formatVox(balance)} Vox sẽ chuyển sang máy mới, và{' '}
          <strong>máy hiện tại bị khóa lại</strong>. Không có nút hoàn tác —
          muốn đảo ngược thì phải chuyển ngược thủ công.
        </p>
      </div>

      <label className="label">Mã máy mới (64 ký tự)</label>
      <input
        className="input font-mono text-xs"
        placeholder="a1b2c3…"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
      />
      <p className="text-xs text-ink-muted mt-1.5">
        Máy mới phải mở ứng dụng ít nhất một lần trước khi chuyển. Người dùng
        đọc mã này ở trang Tài khoản trong ứng dụng.
      </p>

      <label className="label mt-4">Lý do</label>
      <input
        className="input"
        placeholder="Hỏng ổ cứng, đã xác minh hóa đơn"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />

      {error && <p className="text-danger text-xs mt-3">{error}</p>}
    </Modal>
  )
}

/** Hộp thoại khóa/mở máy. */
function StatusModal({ open, onClose, device, onDone }) {
  const blocking = device.status === 'active'
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    setBusy(true)
    setError('')
    try {
      await adminApi.setDeviceStatus(
        device.fingerprint, blocking ? 'blocked' : 'active', reason.trim())
      onDone()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={blocking ? 'Khóa thiết bị' : 'Mở khóa thiết bị'}
      footer={
        <>
          <button onClick={onClose} className="btn-ghost">Hủy</button>
          <button
            onClick={submit}
            disabled={busy || (blocking && reason.trim().length < 3)}
            className={blocking ? 'btn-danger' : 'btn-primary'}
          >
            {busy ? <Spinner className="w-4 h-4" /> : (blocking ? 'Khóa máy' : 'Mở khóa')}
          </button>
        </>
      }
    >
      {blocking ? (
        <>
          <p className="text-sm text-ink-soft leading-relaxed">
            Máy này sẽ không dùng được tính năng dịch nữa, và mọi phiên đang mở
            bị thu hồi ngay lập tức. Số Vox trong ví giữ nguyên.
          </p>
          <label className="label mt-4">Lý do khóa</label>
          <input
            className="input"
            placeholder="Chia sẻ mã kích hoạt cho nhiều máy"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <p className="text-xs text-ink-muted mt-1.5">
            Lý do này hiện trực tiếp cho người dùng trong ứng dụng.
          </p>
        </>
      ) : (
        <p className="text-sm text-ink-soft leading-relaxed">
          Máy này sẽ dùng lại được bình thường.
          {device.blockedReason && (
            <> Lý do khóa trước đó: "{device.blockedReason}".</>
          )}
        </p>
      )}
      {error && <p className="text-danger text-xs mt-3">{error}</p>}
    </Modal>
  )
}

export default function DeviceDetail() {
  const { fingerprint } = useParams()
  const { data, error, loading, reload } = useFetch(
    () => adminApi.device(fingerprint), [fingerprint])

  const [modal, setModal] = useState('')

  if (loading) return <Loading />
  if (error) return <ErrorBox error={error} onRetry={reload} />

  const { device, ledger, usage, keys } = data

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <Link to="/admin/thiet-bi" className="text-xs text-ink-soft hover:text-ink">
        ← Danh sách thiết bị
      </Link>

      {/* Đầu trang */}
      <div className="card p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-lg font-bold">{device.name || 'Máy không tên'}</h1>
              {device.status === 'active'
                ? <Badge tone="ok">Hoạt động</Badge>
                : <Badge tone="danger">Đã khóa</Badge>}
            </div>
            <div className="flex items-center gap-2 mt-2">
              <code className="text-xs text-ink-muted font-mono break-all">
                {device.fingerprint}
              </code>
              <CopyButton value={device.fingerprint} label="Chép mã máy" />
            </div>
            {device.blockedReason && (
              <p className="text-xs text-danger mt-2">Lý do khóa: {device.blockedReason}</p>
            )}
          </div>
          <div className="text-right shrink-0">
            <p className="text-xs text-ink-muted">Số dư</p>
            <p className="text-2xl font-bold text-primary">{formatVox(device.balance)}</p>
            <p className="text-xs text-ink-muted">Vox</p>
          </div>
        </div>

        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6 pt-5 border-t border-border-subtle text-sm">
          {[
            ['Phiên bản app', device.appVersion || '—'],
            ['Lần đầu thấy', formatDate(device.firstSeenAt)],
            ['Lần cuối thấy', formatRelative(device.lastSeenAt)],
            ['IP gần nhất', device.lastSeenIp || '—'],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-ink-muted">{k}</dt>
              <dd className="mt-0.5">{v}</dd>
            </div>
          ))}
        </dl>

        <div className="flex flex-wrap gap-2 mt-5">
          <button onClick={() => setModal('credit')} className="btn-ghost text-xs py-2">
            Cộng / trừ Vox
          </button>
          <button
            onClick={() => setModal('transfer')}
            className="btn-ghost text-xs py-2"
            disabled={device.balance <= 0}
            title={device.balance <= 0 ? 'Ví trống, không có gì để chuyển' : ''}
          >
            Chuyển sang máy mới
          </button>
          <button
            onClick={() => setModal('status')}
            className={`text-xs py-2 ${device.status === 'active' ? 'btn-danger' : 'btn-ghost'}`}
          >
            {device.status === 'active' ? 'Khóa máy' : 'Mở khóa'}
          </button>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Sổ cái */}
        <div className="card overflow-hidden">
          <h2 className="font-semibold text-sm px-5 py-4 border-b border-border-subtle">
            Sổ cái Vox
          </h2>
          {!ledger.length ? (
            <Empty title="Chưa có giao dịch." />
          ) : (
            <div className="max-h-[420px] overflow-y-auto">
              {ledger.map((l) => (
                <div
                  key={l._id}
                  className="px-5 py-3 border-b border-border-subtle last:border-0 flex items-start justify-between gap-3"
                >
                  <div className="min-w-0">
                    <p className="text-sm truncate">
                      {l.description || LEDGER_LABELS[l.type] || l.type}
                    </p>
                    <p className="text-xs text-ink-muted mt-0.5">
                      {LEDGER_LABELS[l.type] || l.type} · {formatDate(l.createdAt)}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className={`text-sm font-semibold ${l.delta > 0 ? 'text-ok' : 'text-ink-soft'}`}>
                      {l.delta > 0 ? '+' : ''}{formatVox(l.delta)}
                    </p>
                    <p className="text-xs text-ink-muted">còn {formatVox(l.balanceAfter)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Lượt gọi mô hình */}
        <div className="card overflow-hidden">
          <h2 className="font-semibold text-sm px-5 py-4 border-b border-border-subtle">
            Lượt gọi gần đây
          </h2>
          {!usage.length ? (
            <Empty title="Chưa có lượt gọi nào." />
          ) : (
            <div className="max-h-[420px] overflow-y-auto">
              {usage.map((u) => (
                <div
                  key={u._id}
                  className="px-5 py-3 border-b border-border-subtle last:border-0 flex items-start justify-between gap-3"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm">{ACTION_LABELS[u.action] || u.action}</span>
                      {u.status === 'error' && <Badge tone="danger">Lỗi</Badge>}
                      {u.status === 'pending' && <Badge tone="warn">Dở dang</Badge>}
                    </div>
                    <p className="text-xs text-ink-muted mt-0.5">
                      {u.inputSize} câu · {u.aiModel || '—'} · {formatDate(u.createdAt)}
                    </p>
                    {u.errorMessage && (
                      <p className="text-xs text-danger mt-1 truncate max-w-[280px]">
                        {u.errorMessage}
                      </p>
                    )}
                  </div>
                  <p className="text-sm text-ink-soft shrink-0">
                    {u.creditCharged ? `−${formatVox(u.creditCharged)}` : '—'}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Mã đã dùng */}
      <div className="card overflow-hidden">
        <h2 className="font-semibold text-sm px-5 py-4 border-b border-border-subtle">
          Mã kích hoạt đã dùng trên máy này
        </h2>
        {!keys.length ? (
          <Empty title="Máy này chưa kích hoạt mã nào." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Mã</th>
                  <th className="th">Vox</th>
                  <th className="th">Nguồn</th>
                  <th className="th">Kích hoạt lúc</th>
                </tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.code}>
                    <td className="td font-mono text-xs">{k.code}</td>
                    <td className="td">{formatVox(k.vox)}</td>
                    <td className="td text-ink-soft text-xs">{k.source}</td>
                    <td className="td text-ink-soft text-xs">{formatDate(k.usedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <CreditModal
        open={modal === 'credit'}
        onClose={() => setModal('')}
        fingerprint={device.fingerprint}
        balance={device.balance}
        onDone={reload}
      />
      <TransferModal
        open={modal === 'transfer'}
        onClose={() => setModal('')}
        fingerprint={device.fingerprint}
        balance={device.balance}
        onDone={reload}
      />
      <StatusModal
        open={modal === 'status'}
        onClose={() => setModal('')}
        device={device}
        onDone={reload}
      />
    </div>
  )
}
