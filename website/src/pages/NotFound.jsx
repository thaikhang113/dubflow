import { motion } from 'framer-motion'
import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="max-w-lg mx-auto px-4 py-24 text-center">
      <motion.p
        className="text-7xl font-extrabold text-gradient inline-block"
        initial={{ opacity: 0, scale: 0.7 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ type: 'spring', stiffness: 200, damping: 16 }}
      >
        404
      </motion.p>
      {/* Sóng âm "mất tín hiệu" — đúng chất app lồng tiếng. */}
      <div className="flex items-end justify-center gap-1 h-8 mt-3" aria-hidden>
        {[10, 22, 14, 28, 8, 18, 12].map((h, i) => (
          <motion.span
            key={i}
            className="w-1.5 rounded-full bg-primary/40"
            animate={{ height: [h, 4, h] }}
            transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.12, ease: 'easeInOut' }}
          />
        ))}
      </div>
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15, duration: 0.35 }}
      >
        <h1 className="text-2xl font-bold mt-4">Trang này chưa được lồng tiếng</h1>
        <p className="text-ink-soft mt-2.5">
          Đường dẫn không tồn tại hoặc đã được đổi.
        </p>
        <div className="mt-7 flex gap-3 justify-center">
          <Link to="/" className="btn-primary">Về trang chủ</Link>
          <Link to="/lien-he" className="btn-ghost">Liên hệ</Link>
        </div>
      </motion.div>
    </div>
  )
}
