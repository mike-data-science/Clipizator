import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Web app: dev server on :5173, proxying /api and /media to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'https://clipizator-asducfe0f2adexcq.polandcentral-01.azurewebsites.net',
        changeOrigin: true,
      },
      '/media': {
        target: 'https://clipizator-asducfe0f2adexcq.polandcentral-01.azurewebsites.net',
        changeOrigin: true,
      },
      '/ws': {
        target: 'wss://clipizator-asducfe0f2adexcq.polandcentral-01.azurewebsites.net',
        ws: true,
      },
    },
  },
  build: {
    target: 'es2022',
  },
})
