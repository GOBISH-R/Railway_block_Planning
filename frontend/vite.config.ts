import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev proxy: the frontend calls /api/*, Vite forwards to the FastAPI
    // backend on 8000. This is what removes CORS as a concern during
    // development, per the project's "no unnecessary infrastructure" stance --
    // Phase 8 packaging serves both from one origin in production.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
