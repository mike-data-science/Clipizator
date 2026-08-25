import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Web app: dev server on :5173, proxying /api and /media to the FastAPI backend.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_URL || 'http://127.0.0.1:8000'
  const wsTarget = target.replace(/^http/, 'ws')

  return {
    plugins: [react()],
    clearScreen: false,
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: target,
          changeOrigin: true,
        },
        '/media': {
          target: target,
          changeOrigin: true,
        },
        '/ws': {
          target: wsTarget,
          ws: true,
          changeOrigin: true,
        },
      },
    },
  build: {
    target: 'es2022',
  },
  }
})
