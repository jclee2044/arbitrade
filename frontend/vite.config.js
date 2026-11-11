import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: Number(process.env.ARBITRADE_FRONTEND_PORT || 5173),
    strictPort: true,
    proxy: {
      '/api': { target: `http://127.0.0.1:${process.env.ARBITRADE_BACKEND_PORT || 8000}`, ws: true },
    },
  },
})
