/** @type {import('tailwindcss').Config} */
// Bảng màu khớp với `autodub_gui/tokens.py` của app desktop — người dùng đi
// từ web sang app không thấy hai sản phẩm khác nhau.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        app: '#0e0e14',
        panel: '#1a1a24',
        'panel-hover': '#22222e',
        input: '#1e1e2a',
        sidebar: '#16161e',
        border: {
          subtle: '#252534',
          DEFAULT: '#32324a',
          active: '#6366f1',
        },
        primary: {
          DEFAULT: '#6366f1',
          hover: '#7577f3',
          dark: '#4f46e5',
        },
        accent: '#8b5cf6',
        ink: {
          DEFAULT: '#e8e8f0',
          soft: '#9090a8',
          muted: '#606078',
        },
        ok: '#22c55e',
        warn: '#f59e0b',
        danger: '#f87171',
      },
      fontFamily: {
        sans: ['"Be Vietnam Pro"', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'Consolas', 'monospace'],
      },
      borderRadius: { xl: '12px', '2xl': '16px' },
      keyframes: {
        // Blob gradient trôi chậm phía sau hero — nền "aurora".
        aurora: {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)' },
          '33%': { transform: 'translate(60px, -40px) scale(1.15)' },
          '66%': { transform: 'translate(-40px, 30px) scale(0.95)' },
        },
        // Vệt sáng quét ngang nút bấm khi hover.
        shine: {
          from: { transform: 'translateX(-100%) skewX(-15deg)' },
          to: { transform: 'translateX(250%) skewX(-15deg)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        'pulse-glow': {
          '0%, 100%': { boxShadow: '0 0 24px 0 rgba(99, 102, 241, 0.25)' },
          '50%': { boxShadow: '0 0 48px 8px rgba(139, 92, 246, 0.35)' },
        },
        marquee: {
          from: { transform: 'translateX(0)' },
          to: { transform: 'translateX(-50%)' },
        },
        // Vạch sáng chạy dọc khung QR — gợi ý "đưa máy lên quét".
        'scan-line': {
          '0%, 100%': { top: '4%' },
          '50%': { top: '92%' },
        },
      },
      animation: {
        aurora: 'aurora 14s ease-in-out infinite',
        shine: 'shine 0.9s ease',
        float: 'float 5s ease-in-out infinite',
        'pulse-glow': 'pulse-glow 3s ease-in-out infinite',
        marquee: 'marquee 30s linear infinite',
        'scan-line': 'scan-line 2.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
