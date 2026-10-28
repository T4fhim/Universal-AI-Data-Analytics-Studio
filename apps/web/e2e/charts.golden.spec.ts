// One golden screenshot per chart in the dev gallery (/charts.html), skinned side only.
//
// Why the gallery and not the workbench: the gallery draws every figure from the same generated
// JSON the core chart classes produce, with no API, sign-in or data upload in the way, so a pixel
// diff here is a change to a chart or to the skin and nothing else. The set of tests is read from
// that JSON, so a chart added to the registry (the gallery builder fails without a spec for it)
// gets a golden test without anyone remembering to write one.
import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

interface GalleryFigures {
  charts: Record<string, unknown>
  references: Record<string, unknown>
}

const figures = JSON.parse(
  readFileSync(new URL('../src/charts/gallery-figures.json', import.meta.url), 'utf8'),
) as GalleryFigures

const REFERENCE_TITLE = 'Reference: stacked column (not a registered chart)'

// The skinned half of a gallery box: chips, plot well and readout line.
function skinned(page: Page, title: string): Locator {
  return page.getByRole('region', { name: title, exact: true }).locator('.chart-side').nth(1).locator('figure.chart')
}

async function settle(page: Page, chart: Locator) {
  // Plotly draws after a lazy chunk loads: wait for its SVG, then for web fonts. The screenshot
  // assertion itself retries until two frames in a row are identical.
  await expect(chart.locator('.main-svg').first()).toBeVisible()
  await page.evaluate(() => document.fonts.ready)
  // Park the pointer off the page so no mode bar or hover readout is showing.
  await page.mouse.move(0, 0)
}

// The gallery draws only the box named by ?only=, so a test never waits on the other 25 figures.
async function open(page: Page, only: string) {
  await page.goto(`/charts.html?only=${encodeURIComponent(only)}`)
}

test.describe('registered charts', () => {
  for (const name of Object.keys(figures.charts).sort()) {
    test(name, async ({ page }) => {
      await open(page, name)
      const chart = skinned(page, name)
      await settle(page, chart)
      await expect(chart).toHaveScreenshot(`${name}.png`)
    })
  }
})

test.describe('reference stacked column', () => {
  test('absolute, linear', async ({ page }) => {
    await open(page, 'reference')
    const chart = skinned(page, REFERENCE_TITLE)
    await settle(page, chart)
    await expect(chart).toHaveScreenshot('stacked-absolute-linear.png')
  })

  test('percentage chip', async ({ page }) => {
    await open(page, 'reference')
    const chart = skinned(page, REFERENCE_TITLE)
    await chart.getByRole('radio', { name: 'Percentage' }).check()
    await settle(page, chart)
    await expect(chart).toHaveScreenshot('stacked-percentage.png')
  })

  test('log chip', async ({ page }) => {
    await open(page, 'reference')
    const chart = skinned(page, REFERENCE_TITLE)
    await chart.getByRole('radio', { name: 'Log' }).check()
    await settle(page, chart)
    await expect(chart).toHaveScreenshot('stacked-log.png')
  })
})
