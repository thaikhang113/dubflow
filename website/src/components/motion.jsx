/**
 * Bộ dựng chuyển động dùng chung cho trang public.
 *
 * Mọi animation vào trang đều đi qua đây để đồng nhất timing/easing.
 * MotionConfig reducedMotion="user" ở App root sẽ tự tắt chuyển động cho
 * người bật "giảm chuyển động" trong hệ điều hành.
 */
import { motion, useInView, useMotionValue, useSpring } from 'framer-motion'
import { useEffect, useRef } from 'react'

const EASE = [0.22, 1, 0.36, 1]

/** Fade + trồi lên khi cuộn tới. `delay` tính bằng giây để stagger tay. */
export function Reveal({ children, delay = 0, y = 24, className, once = true }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once, margin: '-60px' }}
      transition={{ duration: 0.6, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  )
}

/** Container stagger: các con là <StaggerItem> sẽ vào lần lượt. */
export function Stagger({ children, className, gap = 0.08 }) {
  return (
    <motion.div
      className={className}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-60px' }}
      variants={{ show: { transition: { staggerChildren: gap } } }}
    >
      {children}
    </motion.div>
  )
}

export function StaggerItem({ children, className, y = 24 }) {
  return (
    <motion.div
      className={className}
      variants={{
        hidden: { opacity: 0, y },
        show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE } },
      }}
    >
      {children}
    </motion.div>
  )
}

/** Đếm số chạy lên khi vào khung nhìn — cho hàng thống kê. */
export function AnimatedNumber({ value, format = (n) => n.toLocaleString('vi-VN'), className }) {
  const ref = useRef(null)
  const inView = useInView(ref, { once: true, margin: '-40px' })
  const mv = useMotionValue(0)
  const spring = useSpring(mv, { duration: 1.6, bounce: 0 })

  useEffect(() => {
    if (inView) mv.set(value)
  }, [inView, value, mv])

  useEffect(() => {
    const unsub = spring.on('change', (v) => {
      if (ref.current) ref.current.textContent = format(Math.round(v))
    })
    return unsub
  }, [spring, format])

  return <span ref={ref} className={className}>{format(0)}</span>
}

/** Bọc nội dung mỗi trang — fade nhẹ khi chuyển route. */
export function PageTransition({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: EASE }}
    >
      {children}
    </motion.div>
  )
}

/** Card nhấc lên khi hover — dùng cho grid tính năng / gói giá. */
export function HoverLift({ children, className }) {
  return (
    <motion.div
      className={className}
      whileHover={{ y: -6, transition: { duration: 0.25, ease: EASE } }}
    >
      {children}
    </motion.div>
  )
}

/**
 * Nền aurora: các blob gradient blur trôi chậm, thuần CSS (không canvas).
 * Đặt trong container `relative overflow-hidden`; blob tự nằm dưới nội dung.
 */
export function AuroraBackground({ className = '' }) {
  return (
    <div aria-hidden className={`pointer-events-none absolute inset-0 -z-10 overflow-hidden ${className}`}>
      <div className="absolute -top-32 left-1/4 h-96 w-96 rounded-full bg-primary/25 blur-[120px] animate-aurora" />
      <div className="absolute top-24 right-1/5 h-80 w-80 rounded-full bg-accent/20 blur-[110px] animate-aurora [animation-delay:-5s]" />
      <div className="absolute -bottom-24 left-1/3 h-72 w-72 rounded-full bg-primary/15 blur-[100px] animate-aurora [animation-delay:-9s]" />
    </div>
  )
}
