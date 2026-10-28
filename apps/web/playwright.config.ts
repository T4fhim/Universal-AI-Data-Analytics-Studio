// Golden-screenshot tests for the Instrument chart skin (phase-4 step 7).
//
// Why a pinned Linux container and not "whatever browser is installed": a golden image is only
// comparable to one rendered by the same browser build, fonts and rasteriser, so baselines are
// rendered in `mcr.microsoft.com/playwright:v<version>-noble` (e2e/docker.mjs locally, the `web` job
// in CI) and only the `-linux` baselines are committed. A run on Windows or macOS finds no
// baseline of its own and fails rather than diffing against the wrong renderer.
//
// The figures come from `src/charts/gallery-figures.json`, built by scripts/build_chart_gallery.py
// with the real core chart classes, so a change in a core chart shows up here as a pixel diff.
import { defineConfig, devices } from '@playwright/test'

const PORT = 5199

export default defineConfig({
  testDir: 'e2e',
  // Where the baselines live, one folder per spec; the platform stays in the name (see above).
  snapshotPathTemplate: '{testDir}/__golden__/{testFilePath}/{arg}-{projectName}-{platform}{ext}',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  // The first requests to a cold Vite dev server pull and transform Plotly (3 MB, loaded lazily)
  // while every worker is starting at once; 5 s was not enough for that in the container.
  timeout: 60_000,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  expect: {
    timeout: 30_000,
    toHaveScreenshot: {
      animations: 'disabled',
      caret: 'hide',
      // Anti-aliasing noise only; a recoloured series or a moved axis is far above this.
      maxDiffPixelRatio: 0.002,
    },
  },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: 'dark',
    reducedMotion: 'reduce',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } } }],
  webServer: {
    command: `pnpm exec vite --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}/charts.html`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
