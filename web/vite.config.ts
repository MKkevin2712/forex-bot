import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En développement, les appels /api sont redirigés vers l'API FastAPI (forex-bot api).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
