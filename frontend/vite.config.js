import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser talks to /api on the Vite origin, and Vite forwards it to FastAPI.
// This avoids CORS entirely during development and when previewing a production build.
const proxy = {
  '/api': {
    target: process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, '')
  }
}

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy }
})
