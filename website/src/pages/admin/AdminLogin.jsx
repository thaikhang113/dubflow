import { useState } from 'react'

import { Spinner } from '../../components/ui'
import { useAdminAuth } from '../../store/admin'

export default function AdminLogin() {
  const login = useAdminAuth((s) => s.login)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    if (!token.trim()) return
    setBusy(true)
    setError('')
    const result = await login(token.trim())
    if (!result.ok) setError(result.message)
    setBusy(false)
  }

  return (
    <div className="min-h-screen grid place-items-center px-4">
      <form onSubmit={submit} className="card p-7 w-full max-w-sm">
        <h1 className="font-bold text-lg">
          VoxDub <span className="text-primary">Admin</span>
        </h1>
        <p className="text-ink-soft text-sm mt-1.5">
          Nhập token quản trị để tiếp tục.
        </p>

        <label className="label mt-6" htmlFor="admin-token">Token quản trị</label>
        <input
          id="admin-token"
          type="password"
          className="input font-mono"
          placeholder="••••••••••••••••"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          autoFocus
          autoComplete="off"
        />

        {error && <p className="text-danger text-xs mt-2.5">{error}</p>}

        <button type="submit" disabled={busy || !token.trim()} className="btn-primary w-full mt-5">
          {busy ? <><Spinner className="w-4 h-4" /> Đang kiểm tra…</> : 'Đăng nhập'}
        </button>

        <p className="text-xs text-ink-muted mt-4 leading-relaxed">
          Token là biến <code className="font-mono">ADMIN_TOKEN</code> trong tệp
          cấu hình của máy chủ. Phiên đăng nhập kết thúc khi bạn đóng tab.
        </p>
      </form>
    </div>
  )
}
