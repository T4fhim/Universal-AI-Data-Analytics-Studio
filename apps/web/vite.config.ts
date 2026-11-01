import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// `scripts/check-bundle.mjs` builds with UADAS_BUDGET=1: the gallery too (today the only page that imports a
// chart, and a production build of index.html alone would not contain ECharts at all), with a manifest, into a
// folder of its own, so it can read which chunks are loaded up front and which only on demand.
const budget = process.env.UADAS_BUDGET === '1'

export default defineConfig({
  plugins: [react()],
  // ECharts is imported dynamically (src/charts/echarts.ts), so Vite's scanner would only find it when the first
  // chart mounts and then reload the page to re-optimise it. Listing it keeps that out of the dev server and
  // therefore out of the Playwright runs.
  optimizeDeps: {
    include: ['echarts/core', 'echarts/charts', 'echarts/components', 'echarts/features', 'echarts/renderers'],
  },
  build: budget
    ? {
        outDir: 'dist-budget',
        manifest: true,
        // The source maps say what each chunk is made of, which is how the budget check proves ECharts is in none
        // of the chunks a page loads up front.
        sourcemap: true,
        rollupOptions: { input: { main: 'index.html', charts: 'charts.html' } },
      }
    : {},
  // The API is same-origin in production (one host behind a proxy); in development the Vite server
  // forwards /api to Django so the session and CSRF cookies work without CORS. The Host header must
  // stay the browser's (changeOrigin: false; the string shorthand would set it to true): Django's
  // CSRF check compares the request's Origin with its Host, and a rewritten Host fails it.
  server: { proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } } },
})
