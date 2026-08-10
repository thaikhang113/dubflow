/** Khung trang công khai: thanh điều hướng trên, chân trang dưới. */
import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'Trang chủ', end: true },
  { to: '/bang-gia', label: 'Bảng giá' },
  { to: '/mua', label: 'Mua Vox' },
  { to: '/tai-ve', label: 'Tải ứng dụng' },
  { to: '/huong-dan', label: 'Hướng dẫn' },
]

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 shrink-0">
      <svg viewBox="0 0 32 32" className="w-8 h-8">
        <rect width="32" height="32" rx="7" fill="#6366f1" />
        <g fill="#fff">
          <rect x="8" y="13" width="2.5" height="6" rx="1.25" />
          <rect x="12.5" y="9" width="2.5" height="14" rx="1.25" />
          <rect x="17" y="11" width="2.5" height="10" rx="1.25" />
          <rect x="21.5" y="14" width="2.5" height="4" rx="1.25" />
        </g>
      </svg>
      <span className="font-bold text-[15px] tracking-tight">VoxDub Studio</span>
    </Link>
  )
}

/** Nav desktop: gạch chân trượt theo mục đang mở (layoutId). */
function DesktopNav({ pathname }) {
  return (
    <nav className="hidden md:flex items-center gap-1 flex-1">
      {NAV.map((item) => {
        const active = item.end ? pathname === item.to : pathname.startsWith(item.to)
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={`relative px-3 py-2 rounded-lg text-sm transition-colors ${
              active ? 'text-ink' : 'text-ink-soft hover:text-ink'
            }`}
          >
            {item.label}
            {active && (
              <motion.span
                layoutId="nav-underline"
                className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-gradient-to-r from-primary to-accent"
                transition={{ type: 'spring', stiffness: 400, damping: 32 }}
              />
            )}
          </NavLink>
        )
      })}
    </nav>
  )
}

/** Menu hamburger cho mobile — trượt xuống dưới header. */
function MobileMenu({ open, onClose }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.nav
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
          className="md:hidden overflow-hidden border-t border-border-subtle bg-app/95 backdrop-blur"
        >
          <div className="px-4 py-3 flex flex-col gap-1">
            {NAV.map((item, i) => (
              <motion.div
                key={item.to}
                initial={{ opacity: 0, x: -12 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.04 * i, duration: 0.25 }}
              >
                <NavLink
                  to={item.to}
                  end={item.end}
                  onClick={onClose}
                  className={({ isActive }) =>
                    `block px-3 py-2.5 rounded-lg text-sm ${
                      isActive ? 'text-ink bg-panel' : 'text-ink-soft'
                    }`}
                >
                  {item.label}
                </NavLink>
              </motion.div>
            ))}
          </div>
        </motion.nav>
      )}
    </AnimatePresence>
  )
}

export default function PublicLayout() {
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)

  // Đóng menu khi đổi trang (bấm link trong menu).
  useEffect(() => { setMenuOpen(false) }, [location.pathname])

  // Header đổ bóng nhẹ khi đã cuộn — tách khỏi nội dung phía dưới.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div className="min-h-screen flex flex-col">
      <header
        className={`sticky top-0 z-40 bg-app/85 backdrop-blur border-b border-border-subtle transition-shadow ${
          scrolled ? 'shadow-lg shadow-black/30' : ''
        }`}
      >
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center gap-6">
          <Logo />
          <DesktopNav pathname={location.pathname} />
          <div className="flex-1 md:hidden" />
          <Link to="/mua" className="btn-primary text-xs py-2 px-3.5">Mua Vox</Link>
          <button
            type="button"
            aria-label={menuOpen ? 'Đóng menu' : 'Mở menu'}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            className="md:hidden -mr-1 p-2 text-ink-soft hover:text-ink"
          >
            <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              {menuOpen
                ? <path d="M6 6l12 12M18 6L6 18" />
                : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
        <MobileMenu open={menuOpen} onClose={() => setMenuOpen(false)} />
      </header>

      <main className="flex-1">
        {/* Fade nhẹ mỗi lần chuyển trang — key theo pathname. */}
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>

      <footer className="relative border-t border-border-subtle mt-16 overflow-hidden">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-24 h-48 bg-gradient-to-b from-primary/5 to-transparent" />
        <div className="max-w-6xl mx-auto px-4 py-10 grid gap-8 sm:grid-cols-4 text-sm">
          <div className="sm:col-span-2">
            <Logo />
            <p className="text-ink-muted text-xs mt-3 leading-relaxed max-w-xs">
              Lồng tiếng video sang tiếng Việt tự động. Nghe chép, giọng đọc và
              dựng video chạy ngay trên máy bạn.
            </p>
            <p className="text-ink-muted text-xs mt-3">
              1 Vox = 10đ · 1.000 Vox = 10.000đ · Thanh toán an toàn qua PayOS
            </p>
          </div>
          <div>
            <p className="font-medium mb-2.5">Sản phẩm</p>
            <ul className="space-y-1.5 text-ink-soft text-xs">
              <li><Link to="/bang-gia" className="hover:text-ink transition-colors">Bảng giá</Link></li>
              <li><Link to="/mua" className="hover:text-ink transition-colors">Mua Vox</Link></li>
              <li><Link to="/don-hang" className="hover:text-ink transition-colors">Đơn hàng của tôi</Link></li>
              <li><Link to="/tai-ve" className="hover:text-ink transition-colors">Tải ứng dụng</Link></li>
            </ul>
          </div>
          <div>
            <p className="font-medium mb-2.5">Hỗ trợ</p>
            <ul className="space-y-1.5 text-ink-soft text-xs">
              <li><Link to="/huong-dan" className="hover:text-ink transition-colors">Hướng dẫn cài đặt</Link></li>
              <li><Link to="/cau-hoi" className="hover:text-ink transition-colors">Câu hỏi thường gặp</Link></li>
              <li><Link to="/lien-he" className="hover:text-ink transition-colors">Liên hệ</Link></li>
            </ul>
          </div>
        </div>
        <div className="border-t border-border-subtle">
          <p className="max-w-6xl mx-auto px-4 py-4 text-xs text-ink-muted">
            © {new Date().getFullYear()} VoxDub Studio
          </p>
        </div>
      </footer>
    </div>
  )
}
