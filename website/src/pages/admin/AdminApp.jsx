/**
 * Trang quản trị — bộ khung.
 *
 * Toàn bộ mã admin nằm dưới nhánh này và được `App.jsx` nạp lười, nên khách
 * vào trang mua hàng không phải tải nó về.
 *
 * Không có route nào ở đây tự bảo vệ được: an ninh thật nằm ở máy chủ (mọi
 * `/v1/admin/*` đòi header `X-Admin-Token`). Lớp đăng nhập dưới đây chỉ để
 * người dùng không phải nhìn một loạt lỗi 401.
 */
import { useEffect } from 'react'
import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'

import { Loading } from '../../components/ui'
import { useAdminAuth } from '../../store/admin'
import AdminLogin from './AdminLogin'
import Dashboard from './Dashboard'
import Devices from './Devices'
import DeviceDetail from './DeviceDetail'
import Keys from './Keys'
import Orders from './Orders'
import Providers from './Providers'
import Config from './Config'
import AuditLog from './AuditLog'

const NAV = [
  { to: '/admin', label: 'Tổng quan', end: true },
  { to: '/admin/thiet-bi', label: 'Thiết bị' },
  { to: '/admin/don-hang', label: 'Đơn hàng' },
  { to: '/admin/ma-kich-hoat', label: 'Mã kích hoạt' },
  { to: '/admin/mo-hinh', label: 'Nơi gọi mô hình' },
  { to: '/admin/cau-hinh', label: 'Cấu hình' },
  { to: '/admin/nhat-ky', label: 'Nhật ký' },
]

function Shell({ children }) {
  const logout = useAdminAuth((s) => s.logout)
  const navigate = useNavigate()

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-0 z-40 bg-sidebar border-b border-border-subtle">
        <div className="px-4 h-14 flex items-center gap-4">
          <span className="font-bold text-sm shrink-0">
            VoxDub <span className="text-primary">Admin</span>
          </span>
          <nav className="flex items-center gap-0.5 overflow-x-auto flex-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg text-xs whitespace-nowrap transition-colors ${
                    isActive ? 'bg-panel text-ink' : 'text-ink-soft hover:text-ink'
                  }`}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <button
            onClick={() => { logout(); navigate('/admin') }}
            className="btn-ghost text-xs py-1.5 px-3 shrink-0"
          >
            Đăng xuất
          </button>
        </div>
      </header>
      <main className="flex-1 p-4 sm:p-6">{children}</main>
    </div>
  )
}

export default function AdminApp() {
  const { authed, checking, restore } = useAdminAuth()

  // Mở lại tab admin: token còn trong sessionStorage nhưng có thể đã bị đổi
  // phía máy chủ — hỏi lại một lần thay vì tin tưởng mù.
  useEffect(() => { restore() }, [restore])

  if (checking) return <Loading label="Đang kiểm tra quyền truy cập…" />
  if (!authed) return <AdminLogin />

  return (
    <Shell>
      <Routes>
        <Route index element={<Dashboard />} />
        <Route path="thiet-bi" element={<Devices />} />
        <Route path="thiet-bi/:fingerprint" element={<DeviceDetail />} />
        <Route path="don-hang" element={<Orders />} />
        <Route path="ma-kich-hoat" element={<Keys />} />
        <Route path="mo-hinh" element={<Providers />} />
        <Route path="cau-hinh" element={<Config />} />
        <Route path="nhat-ky" element={<AuditLog />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </Shell>
  )
}
