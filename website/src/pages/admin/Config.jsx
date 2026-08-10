import { useState } from 'react'

import { adminApi } from '../../api/client'
import { useFetch } from '../../api/useFetch'
import { Badge, ErrorBox, Loading, Modal, Spinner } from '../../components/ui'

/**
 * Nhóm các khóa cấu hình để trang đọc được như một bảng điều khiển, không
 * phải một bãi key-value. Khóa không thuộc nhóm nào rơi xuống "Khác".
 */
const GROUPS = [
  {
    title: 'Hệ thống credit',
    keys: [
      'credit.enabled', 'credit.vox.to.vnd',
      'trial.vox', 'trial.upfront.vox', 'trial.defer.hours',
      'register.max.new.per.ip.day',
    ],
  },
  {
    title: 'Giá công khai (theo segment)',
    keys: [
      'credit.cost.segment.base', 'credit.cost.segment.autotranslate',
      'credit.cost.metadata',
    ],
  },
  {
    title: 'Giá nội bộ (đối soát, không trừ ví khi có hold)',
    keys: [
      'internal.cost.translate.per_sentence', 'internal.cost.analyze',
      'internal.cost.review.per_sentence', 'internal.cost.generate_post',
    ],
  },
  {
    title: 'Giữ chỗ Vox (hold)',
    keys: [
      'hold.enabled', 'hold.ttl.hours', 'hold.sweep.interval.minutes',
      'hold.review.ratio',
    ],
  },
  {
    title: 'Gói bán và đơn hàng',
    keys: ['credit.packages', 'order.min.vnd', 'order.max.vnd', 'order.expire.minutes'],
  },
  {
    title: 'Bảo trì và phiên bản',
    keys: ['maintenance.mode', 'maintenance.message', 'min.app.version', 'force.update.version'],
  },
  {
    title: 'Trần chống lạm dụng',
    keys: ['ai.max.segments.per.request', 'ai.max.chars.per.segment', 'ai.max.retries'],
  },
]

/** Các khóa nguy hiểm — sửa sai là toàn bộ người dùng bị ảnh hưởng ngay. */
const DANGEROUS = new Set(['credit.enabled', 'maintenance.mode', 'min.app.version'])

function EditModal({ open, item, onClose, onDone }) {
  const [raw, setRaw] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const [loadedKey, setLoadedKey] = useState(null)
  if (open && item && loadedKey !== item.key) {
    setLoadedKey(item.key)
    setRaw(typeof item.value === 'object'
      ? JSON.stringify(item.value, null, 2)
      : String(item.value))
    setError('')
  }

  /**
   * Giá trị gõ vào là chuỗi; cấu hình cần đúng kiểu. Đoán theo kiểu HIỆN
   * TẠI của khóa — "true" thành boolean chỉ khi khóa đang là boolean, nên
   * một chuỗi tình cờ tên "true" không bị đổi kiểu ngầm.
   */
  function parseValue() {
    const current = item.value
    const text = raw.trim()
    if (typeof current === 'boolean') {
      if (text !== 'true' && text !== 'false') {
        throw new Error('Khóa này chỉ nhận true hoặc false.')
      }
      return text === 'true'
    }
    if (typeof current === 'number') {
      const n = Number(text)
      if (!Number.isFinite(n)) throw new Error('Khóa này cần một con số.')
      return n
    }
    if (typeof current === 'object' && current !== null) {
      try {
        return JSON.parse(text)
      } catch {
        throw new Error('JSON không hợp lệ.')
      }
    }
    return text
  }

  async function submit() {
    let value
    try {
      value = parseValue()
    } catch (err) {
      setError(err.message)
      return
    }
    setBusy(true)
    setError('')
    try {
      await adminApi.setConfig(item.key, value)
      onDone()
      onClose()
      setLoadedKey(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!item) return null
  const isJson = typeof item.value === 'object' && item.value !== null

  return (
    <Modal
      open={open}
      onClose={() => { onClose(); setLoadedKey(null) }}
      title={item.key}
      width={isJson ? 'max-w-2xl' : 'max-w-lg'}
      footer={
        <>
          <button onClick={() => { onClose(); setLoadedKey(null) }} className="btn-ghost">
            Hủy
          </button>
          <button onClick={submit} disabled={busy} className="btn-primary">
            {busy ? <Spinner className="w-4 h-4" /> : 'Lưu'}
          </button>
        </>
      }
    >
      {item.description && (
        <p className="text-sm text-ink-soft mb-3">{item.description}</p>
      )}
      {DANGEROUS.has(item.key) && (
        <div className="bg-warn/10 border border-warn/25 rounded-xl px-4 py-3 mb-3">
          <p className="text-xs text-warn">
            Khóa này ảnh hưởng TOÀN BỘ người dùng trong vòng một phút sau khi lưu.
          </p>
        </div>
      )}

      {isJson ? (
        <textarea
          className="input font-mono text-xs min-h-[260px]"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          spellCheck={false}
        />
      ) : (
        <input
          className="input font-mono"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
        />
      )}
      <p className="text-xs text-ink-muted mt-2">
        Mặc định: <code className="font-mono">{JSON.stringify(item.default)}</code>
      </p>

      {error && <p className="text-danger text-xs mt-3">{error}</p>}
    </Modal>
  )
}

function Row({ item, onEdit }) {
  const display = typeof item.value === 'object' && item.value !== null
    ? `${JSON.stringify(item.value).slice(0, 60)}…`
    : String(item.value)
  return (
    <div className="px-5 py-3 border-b border-border-subtle last:border-0 flex items-center justify-between gap-4 hover:bg-panel-hover">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <code className="text-xs font-mono font-medium">{item.key}</code>
          {!item.isDefault && <Badge tone="info">đã sửa</Badge>}
        </div>
        {item.description && (
          <p className="text-xs text-ink-muted mt-0.5 truncate">{item.description}</p>
        )}
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <code
          className={`text-xs font-mono max-w-[200px] truncate ${
            typeof item.value === 'boolean'
              ? (item.value ? 'text-ok' : 'text-danger')
              : 'text-ink-soft'
          }`}
        >
          {display}
        </code>
        <button onClick={() => onEdit(item)} className="btn-ghost text-xs py-1 px-2.5">
          Sửa
        </button>
      </div>
    </div>
  )
}

export default function Config() {
  const { data, error, loading, reload } = useFetch(() => adminApi.config())
  const [editing, setEditing] = useState(null)

  if (loading) return <Loading />
  if (error) return <ErrorBox error={error} onRetry={reload} />

  const items = data.items
  const byKey = new Map(items.map((i) => [i.key, i]))
  const grouped = GROUPS.map((g) => ({
    ...g,
    items: g.keys.map((k) => byKey.get(k)).filter(Boolean),
  }))
  const known = new Set(GROUPS.flatMap((g) => g.keys))
  const other = items.filter((i) => !known.has(i.key))

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div>
        <h1 className="text-xl font-bold">Cấu hình</h1>
        <p className="text-xs text-ink-muted mt-1">
          Thay đổi có hiệu lực trong vòng một phút, không cần khởi động lại máy chủ.
        </p>
      </div>

      {grouped.map((g) => (
        <div key={g.title} className="card overflow-hidden">
          <h2 className="font-semibold text-sm px-5 py-3.5 border-b border-border-subtle">
            {g.title}
          </h2>
          {g.items.map((item) => (
            <Row key={item.key} item={item} onEdit={setEditing} />
          ))}
        </div>
      ))}

      {other.length > 0 && (
        <div className="card overflow-hidden">
          <h2 className="font-semibold text-sm px-5 py-3.5 border-b border-border-subtle">
            Khác
          </h2>
          {other.map((item) => (
            <Row key={item.key} item={item} onEdit={setEditing} />
          ))}
        </div>
      )}

      <EditModal
        open={Boolean(editing)}
        item={editing}
        onClose={() => setEditing(null)}
        onDone={reload}
      />
    </div>
  )
}
