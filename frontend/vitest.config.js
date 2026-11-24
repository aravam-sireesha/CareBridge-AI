import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// End-to-end UI test: renders the real app in jsdom and talks to a RUNNING backend.
//   1) start the backend   2) CAREBRIDGE_E2E_API=http://127.0.0.1:8000 npm test
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.js'],
    include: ['tests/**/*.test.jsx'],
    testTimeout: 30000,
    hookTimeout: 30000,
    env: { VITE_API_URL: process.env.CAREBRIDGE_E2E_API || 'http://127.0.0.1:8000' }
  }
})
