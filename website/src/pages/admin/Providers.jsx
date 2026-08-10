import { useState } from 'react'

import { adminApi } from '../../api/client'
import { formatRelative } from '../../api/format'
import { useFetch } from '../../api/useFetch'
import { Badge, Empty, ErrorBox, Loading, Modal, Spinner } from '../../components/ui'

const EMPTY_FORM = {
  name: '', label: '', role: 'translate', type: 'openai_compat',
  baseUrl: 'https://openrouter.ai/api/v1', apiKey: '',
  model: '', temperature: 0.3, maxTokens: 16384, priority: 100,
  enabled: true, timeoutMs: 180000,
}

/**
 * Thêm/sửa một nơi gọi mô hình.
 *
 * Khi sửa: ô API key ĐỂ TRỐNG nghĩa là giữ key cũ — backend quy ước vậy để
 * đổi model không vô tình xóa mất key. Nhãn ô nói rõ điều đó.
 */
function ProviderModal({ open, onClose, editing, onDone }) {
  const [form, setForm] = useState(EMPTY_FORM)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Nạp dữ liệu khi mở để sửa (React state không tự theo props).
  const [loadedId, setLoadedId] = useState(null)
  if (open && editing && loadedId !== editing._id) {
    setLoadedId(editing._id)
    setForm({ ...EMPTY_FORM, ...editing, apiKey: '' })
  }
  if (open && !editing && loadedId !== 'new') {
    setLoadedId('new')
    setForm(EMPTY_FORM)
  }

  function set(key, value) { setForm((f) => ({ ...f, [key]: value })) }

  const valid = form.name.trim() && form.model.trim()
    && (editing || form.apiKey.trim())

  async function submit() {
    setBusy(true)
    setError('')
    const payload = {
      name: form.name.trim(),
      label: form.label.trim(),
      role: form.role,
      type: form.type,
      baseUrl: form.baseUrl.trim(),
      model: form.model.trim(),
      temperature: Number(form.temperature),
      maxTokens: Number(form.maxTokens),
      priority: Number(form.priority),
      enabled: form.enabled,
      timeoutMs: Number(form.timeoutMs),
    }
    if (form.apiKey.trim()) payload.apiKey = form.apiKey.trim()
    try {
      if (editing) await adminApi.updateProvider(editing._id, payload)
      else await adminApi.createProvider(payload)
      onDone()
      onClose()
      setLoadedId(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={() => { onClose(); setLoadedId(null) }}
      title={editing ? `Sửa "${editing.name}"` : 'Thêm nơi gọi mô hình'}
      width="max-w-2xl"
      footer={
        <>
          <button onClick={() => { onClose(); setLoadedId(null) }} className="btn-ghost">
            Hủy
          </button>
          <button onClick={submit} disabled={!valid || busy} className="btn-primary">
            {busy ? <Spinner className="w-4 h-4" /> : 'Lưu'}
          </button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="label">Tên định danh</label>
          <input
            className="input font-mono"
            placeholder="openrouter"
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            disabled={Boolean(editing)}
          />
        </div>
        <div>
          <label className="label">Nhãn hiển thị</label>
          <input
            className="input"
            placeholder="OpenRouter"
            value={form.label}
            onChange={(e) => set('label', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Vai trò</label>
          <select className="input" value={form.role} onChange={(e) => set('role', e.target.value)}>
            <option value="translate">Dịch (translate)</option>
            <option value="content">Nội dung đăng bài (content)</option>
          </select>
        </div>
        <div>
          <label className="label">Giao thức</label>
          <select className="input" value={form.type} onChange={(e) => set('type', e.target.value)}>
            <option value="openai_compat">Chuẩn OpenAI (OpenRouter, DeepSeek…)</option>
            <option value="google">Google Gemini</option>
          </select>
        </div>
        <div className="sm:col-span-2">
          <label className="label">Địa chỉ máy chủ</label>
          <input
            className="input font-mono text-xs"
            placeholder="https://openrouter.ai/api/v1"
            value={form.baseUrl}
            onChange={(e) => set('baseUrl', e.target.value)}
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label">
            API key {editing && <span className="text-ink-muted">(để trống = giữ key cũ)</span>}
          </label>
          <input
            className="input font-mono text-xs"
            type="password"
            placeholder={editing ? '••••••••  (không đổi)' : 'sk-or-v1-…'}
            value={form.apiKey}
            onChange={(e) => set('apiKey', e.target.value)}
            autoComplete="off"
          />
        </div>
        <div>
          <label className="label">Mô hình</label>
          <input
            className="input font-mono text-xs"
            placeholder="google/gemini-2.5-flash"
            value={form.model}
            onChange={(e) => set('model', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Ưu tiên (nhỏ = trước)</label>
          <input
            className="input"
            inputMode="numeric"
            value={form.priority}
            onChange={(e) => set('priority', e.target.value.replace(/\D/g, ''))}
          />
        </div>
        <div>
          <label className="label">Temperature</label>
          <input
            className="input"
            value={form.temperature}
            onChange={(e) => set('temperature', e.target.value)}
          />
        </div>
        <div>
          <label className="label">Trần token đầu ra</label>
          <input
            className="input"
            inputMode="numeric"
            value={form.maxTokens}
            onChange={(e) => set('maxTokens', e.target.value.replace(/\D/g, ''))}
          />
        </div>
        <label className="flex items-center gap-2.5 sm:col-span-2 cursor-pointer">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set('enabled', e.target.checked)}
            className="accent-primary"
          />
          <span className="text-sm">Đang bật</span>
        </label>
      </div>

      {error && <p className="text-danger text-xs mt-4">{error}</p>}
    </Modal>
  )
}

export default function Providers() {
  const { data, error, loading, reload } = useFetch(() => adminApi.providers())
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [deleteError, setDeleteError] = useState('')

  async function remove() {
    setDeleteError('')
    try {
      await adminApi.deleteProvider(deleting._id)
      setDeleting(null)
      reload()
    } catch (err) {
      setDeleteError(err.message)
    }
  }

  async function toggle(provider) {
    try {
      await adminApi.updateProvider(provider._id, { enabled: !provider.enabled })
      reload()
    } catch {
      // Bảng sẽ tự phản ánh trạng thái thật khi tải lại.
    }
  }

  return (
    <div className="max-w-6xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Nơi gọi mô hình</h1>
          <p className="text-xs text-ink-muted mt-1">
            Sắp theo ưu tiên. Nơi đầu lỗi thì tự rơi xuống nơi sau — người dùng
            không thấy gián đoạn.
          </p>
        </div>
        <button
          onClick={() => { setEditing(null); setModal(true) }}
          className="btn-primary text-xs py-1.5 px-3"
        >
          Thêm nơi gọi
        </button>
      </div>

      {loading && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}

      {data && (
        !data.data.length ? (
          <div className="card">
            <Empty
              title="Chưa cấu hình nơi gọi mô hình nào."
              hint="Bước dịch sẽ báo lỗi cho tới khi bạn thêm ít nhất một nơi."
            />
          </div>
        ) : (
          <div className="space-y-3">
            {data.data.map((p) => (
              <div key={p._id} className="card p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <h2 className="font-semibold">{p.label || p.name}</h2>
                      <Badge tone={p.enabled ? 'ok' : 'muted'}>
                        {p.enabled ? 'Đang bật' : 'Đang tắt'}
                      </Badge>
                      <Badge tone="info">
                        {p.role === 'translate' ? 'Dịch' : 'Nội dung'}
                      </Badge>
                      <Badge tone="muted">ưu tiên {p.priority}</Badge>
                    </div>
                    <p className="font-mono text-xs text-ink-soft mt-1.5 truncate">
                      {p.model} · {p.baseUrl || '(mặc định)'}
                    </p>
                    <div className="flex flex-wrap gap-4 mt-2 text-xs text-ink-muted">
                      <span>API key: {p.hasApiKey ? 'đã đặt' : 'CHƯA CÓ'}</span>
                      {p.lastOkAt && <span>lần cuối OK: {formatRelative(p.lastOkAt)}</span>}
                      {p.lastError && (
                        <span className="text-danger truncate max-w-[320px]">
                          lỗi gần nhất: {p.lastError}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button onClick={() => toggle(p)} className="btn-ghost text-xs py-1.5 px-3">
                      {p.enabled ? 'Tắt' : 'Bật'}
                    </button>
                    <button
                      onClick={() => { setEditing(p); setModal(true) }}
                      className="btn-ghost text-xs py-1.5 px-3"
                    >
                      Sửa
                    </button>
                    <button
                      onClick={() => { setDeleting(p); setDeleteError('') }}
                      className="btn-danger text-xs py-1.5 px-3"
                    >
                      Xóa
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )
      )}

      <ProviderModal
        open={modal}
        editing={editing}
        onClose={() => setModal(false)}
        onDone={reload}
      />

      <Modal
        open={Boolean(deleting)}
        onClose={() => setDeleting(null)}
        title="Xóa nơi gọi mô hình"
        footer={
          <>
            <button onClick={() => setDeleting(null)} className="btn-ghost">Hủy</button>
            <button onClick={remove} className="btn-danger">Xóa</button>
          </>
        }
      >
        <p className="text-sm text-ink-soft leading-relaxed">
          Xóa <strong className="text-ink">{deleting?.name}</strong>? Nếu đây là
          nơi duy nhất của vai trò này, bước dịch sẽ báo lỗi cho tới khi bạn
          thêm nơi khác. Cân nhắc <strong className="text-ink">Tắt</strong> thay
          vì xóa.
        </p>
        {deleteError && <p className="text-danger text-xs mt-3">{deleteError}</p>}
      </Modal>
    </div>
  )
}
