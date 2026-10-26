import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The API is same-origin in production (one host behind a proxy); in development the Vite server
  // forwards /api to Django so the session and CSRF cookies work without CORS. The Host header must
  // stay the browser's (changeOrigin: false; the string shorthand would set it to true): Django's
  // CSRF check compares the request's Origin with its Host, and a rewritten Host fails it.
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } } },
})
