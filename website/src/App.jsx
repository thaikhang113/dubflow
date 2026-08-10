/**
 * Bộ định tuyến của toàn site.
 *
 * Đường dẫn công khai dùng tiếng Việt không dấu (/mua, /bang-gia) — dễ đọc,
 * dễ đọc qua điện thoại cho người khác. Admin nằm dưới /admin và tải theo
 * kiểu lười: khách mua hàng không phải tải mã của trang quản trị.
 */
import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { MotionConfig } from 'framer-motion'

import PublicLayout from './components/PublicLayout'
import { Loading } from './components/ui'
import Landing from './pages/Landing'
import Pricing from './pages/Pricing'
import Buy from './pages/Buy'
import Checkout from './pages/Checkout'
import MyOrders from './pages/MyOrders'
import Download from './pages/Download'
import Docs from './pages/Docs'
import Faq from './pages/Faq'
import Contact from './pages/Contact'
import NotFound from './pages/NotFound'

const AdminApp = lazy(() => import('./pages/admin/AdminApp'))

export default function App() {
  return (
    // reducedMotion="user": tôn trọng cài đặt "giảm chuyển động" của hệ điều hành.
    <MotionConfig reducedMotion="user">
      <BrowserRouter>
      <Routes>
        <Route element={<PublicLayout />}>
          <Route index element={<Landing />} />
          <Route path="bang-gia" element={<Pricing />} />
          <Route path="mua" element={<Buy />} />
          <Route path="thanh-toan/:orderCode" element={<Checkout />} />
          <Route path="don-hang" element={<MyOrders />} />
          <Route path="tai-ve" element={<Download />} />
          <Route path="huong-dan" element={<Docs />} />
          <Route path="cau-hoi" element={<Faq />} />
          <Route path="lien-he" element={<Contact />} />
          {/* Đường dẫn cũ/tiếng Anh — giữ để link đã chia sẻ không chết. */}
          <Route path="buy" element={<Navigate to="/mua" replace />} />
          <Route path="pricing" element={<Navigate to="/bang-gia" replace />} />
          <Route path="download" element={<Navigate to="/tai-ve" replace />} />
          <Route path="*" element={<NotFound />} />
        </Route>

        <Route
          path="/admin/*"
          element={
            <Suspense fallback={<Loading label="Đang mở trang quản trị…" />}>
              <AdminApp />
            </Suspense>
          }
        />
      </Routes>
      </BrowserRouter>
    </MotionConfig>
  )
}
