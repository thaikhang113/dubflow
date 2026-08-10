import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Website build ra tĩnh, nginx serve thẳng từ dist/. Không có server-side
// rendering: mọi thứ động đều đi qua REST API của backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev: gọi thẳng backend local, khỏi phải cấu hình CORS cho localhost.
    proxy: {
      '/v1': { target: 'http://127.0.0.1:3001', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:3001', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    // Admin panel chỉ vài người dùng nhưng kéo theo khá nhiều mã. Tách
    // riêng để khách vào trang mua hàng không phải tải phần đó.
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          motion: ['framer-motion'],
        },
      },
    },
  },
})
