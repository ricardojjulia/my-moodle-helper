import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4101,
    proxy: {
      '/api': 'http://localhost:4100',
    },
  },
  preview: {
    port: 4102,
  },
})
