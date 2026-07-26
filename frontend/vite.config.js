import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// During development the frontend runs on :5173 and proxies /api to the
// FastAPI backend on :8000. This keeps requests same-origin (no CORS issues)
// and lets SSE streaming pass straight through.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
