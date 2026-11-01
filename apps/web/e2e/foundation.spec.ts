// The ECharts foundation (CI.8a): the lazy chunk, the theme, the text alternative and the fallback ladder.
//
// The fixture is the gallery's "ECharts foundation" box (src/charts/foundation.ts): a fixed option through
// the same ChartView any ported chart will use, so these tests need no API, sign-in or data. The golden is the
// themed chart; the rest are assertions. Run in the pinned Playwright container like the other goldens
// (playwright.config.ts says why), so the canvas text is rendered by the same fonts as the baseline. The
// module-level tests import the app's own modules into the page (Vite serves them), which is the only way to
// exercise formatters.ts and optionData.ts without a unit-test runner.
import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

const TITLE = 'ECharts foundation (fixture, not a registered chart)'
// The lazy module, or the optimised library when Vite pre-bundles it: not `echarts.ts`, the small loader that
// every page imports statically.
const ECHARTS_CODE = /echarts-bundle|\.vite\/deps\/echarts/

async function open(page: Page, variant = 'ok'): Promise<Locator> {
  await page.goto(`/charts.html?only=foundation&variant=${variant}`)
  return page.getByRole('region', { name: TITLE, exact: true })
}

// Evaluates an expression in the page, where `import()` of the app's own modules works under Vite.
const inPage = <T>(page: Page, expression: string): Promise<T> => page.evaluate<T>(expression)

test.describe('ECharts foundation', () => {
  test('draws the fixed option on one canvas in the Instrument theme', async ({ page }) => {
    const box = await open(page)
    const chart = box.locator('figure.chart-echarts')
    // One canvas, not two: React's StrictMode mounts, unmounts and mounts again, and an instance left over from
    // the first mount would draw a second canvas or merge into the first.
    await expect(chart.locator('canvas')).toHaveCount(1)
    await page.evaluate(() => document.fonts.ready)
    // Park the pointer off the page so no tooltip or axis pointer is showing.
    await page.mouse.move(0, 0)
    await expect(chart.locator('.chart-host')).toHaveScreenshot('foundation.png')
  })

  test('has a text alternative: one named image and a data table of the plotted numbers', async ({ page }) => {
    const box = await open(page)
    // The host is the image, named with the label and the summary (ECharts writes the same text onto it).
    const image = box.getByRole('img', { name: /^Visits and sign-ups by day\. bar, line chart with 2 series, 5 categories$/ })
    await expect(image).toHaveCount(1)

    await box.locator('summary').click()
    const table = box.getByRole('table')
    await expect(table.getByRole('columnheader')).toHaveText(['Day', 'Visits', 'Sign-ups'])
    await expect(table.getByRole('row', { name: /Wed/ }).getByRole('cell')).toHaveText(['2400', '260'])
    // Not N identical "Data table" controls on a page of charts: the control names its chart.
    await expect(box.locator('summary')).toContainText('Data table for Visits and sign-ups by day')
  })

  test('loads ECharts only when a chart is drawn', async ({ page }) => {
    const requested: string[] = []
    page.on('request', (request) => requested.push(request.url()))
    await page.goto('/charts.html?only=reference')
    await expect(page.locator('.main-svg').first()).toBeVisible()
    expect(requested.filter((url) => ECHARTS_CODE.test(url))).toEqual([])

    requested.length = 0
    const box = await open(page)
    await expect(box.locator('canvas')).toHaveCount(1)
    expect(requested.some((url) => ECHARTS_CODE.test(url))).toBe(true)
  })

  test('re-draws a chart with fewer series without merging into the old one, and unmounts cleanly', async ({ page }) => {
    const box = await open(page)
    const host = box.locator('.chart-host')
    await expect(box.locator('canvas')).toHaveCount(1)
    const seriesOf = () =>
      inPage<number>(
        page,
        `import('/src/charts/echarts-bundle.ts').then((m) => m.echarts.getInstanceByDom(document.querySelector('.chart-host')).getOption().series.length)`,
      )
    expect(await seriesOf()).toBe(2)

    await box.getByRole('button', { name: 'Show one series' }).click()
    // The option has one series now: an instance that merged the new option into the old one would still hold two.
    await expect.poll(seriesOf).toBe(1)
    await expect(box.locator('canvas')).toHaveCount(1)
    await expect(host).toHaveAttribute('aria-label', /bar chart with 1 series/)

    await box.getByRole('button', { name: 'Remove chart' }).click()
    await expect(box.locator('canvas')).toHaveCount(0)
  })

  test('keeps one polite status region in every state and announces a fallback through it', async ({ page }) => {
    const ok = await open(page)
    // Present and empty while the chart is fine, never inserted with its text already in it.
    await expect(ok.getByRole('status')).toHaveCount(1)
    await expect(ok.getByRole('status')).toHaveText('')

    const broken = await open(page, 'broken')
    await expect(broken.getByRole('status')).toHaveCount(1)
    await expect(broken.getByRole('status')).toHaveText(/fallback/i)
    // Never assertive: a failed chunk fails every chart on a page at once.
    await expect(broken.getByRole('alert')).toHaveCount(0)
  })

  test('falls back to Plotly when the ECharts chunk cannot be loaded, and still offers the table', async ({ page }) => {
    await page.route(ECHARTS_CODE, (route) => route.abort())
    const box = await open(page)
    await expect(box.locator('.chart-note')).toHaveText(/fallback/i)
    await expect(box.locator('.main-svg').first()).toBeVisible()
    await expect(box.locator('canvas')).toHaveCount(0)
    await expect(box.locator('summary')).toBeVisible()
  })

  test('falls back to Plotly when the client refuses the option, and still offers the table', async ({ page }) => {
    const box = await open(page, 'broken')
    await expect(box.locator('.chart-note')).toHaveText(/fallback/i)
    await expect(box.locator('.main-svg').first()).toBeVisible()
    await expect(box.locator('canvas')).toHaveCount(0)
    await expect(box.locator('summary')).toBeVisible()
  })

  test('says so plainly when there is nothing to fall back to, with the data still reachable', async ({ page }) => {
    const box = await open(page, 'broken-no-fallback')
    await expect(box.locator('.chart-note')).toHaveText('The chart could not be drawn.')
    await expect(box.getByRole('status')).toHaveText('The chart could not be drawn.')
    await expect(box.locator('canvas')).toHaveCount(0)
    await expect(box.locator('.main-svg')).toHaveCount(0)
    await box.locator('summary').click()
    await expect(box.getByRole('table')).toBeVisible()
  })
})

test.describe('ECharts client boundary', () => {
  test('formatters format numbers, keep a point whole, and never reinterpret text', async ({ page }) => {
    await page.goto('/charts.html?only=reference')
    const out = await inPage<unknown[]>(
      page,
      `import('/src/charts/formatters.ts').then((m) => [
        m.FORMATTERS.compact(1234),
        m.FORMATTERS.pct1({ value: 42.123 }),
        m.FORMATTERS.thousands(1234567.891),
        m.FORMATTERS.fixed2([1.234, 5]),
        m.FORMATTERS.thousands('2024'),
        m.FORMATTERS.compact('007'),
        m.FORMATTERS.thousands(null),
      ])`,
    )
    // A multi-dimensional point formats each element (valueFormatter takes a string per element); a string is a
    // label, shown as it is ("2024", not "2,024"). Nothing is HTML-escaped here: see the header of formatters.ts.
    expect(out).toEqual(['1.2K', '42.1%', '1,234,567.89', ['1.23', '5.00'], '2024', '007', ''])
  })

  test('the reviver refuses what the core refuses, for the right reason, and allows what is safe', async ({ page }) => {
    await page.goto('/charts.html?only=reference')
    const verdicts = await inPage<string[]>(
      page,
      `import('/src/charts/formatters.ts').then((m) => [
        { title: { link: 'javascript:alert(1)' } },
        { series: [{ symbol: 'image://http://t.example/p.png' }] },
        { markLine: { symbol: ['none', 'image://http://t.example/p.png'] } },
        { graphic: [{ style: { image: 'http://t.example/p.png' } }] },
        { tooltip: { extraCssText: 'background:url(http://t.example/p.png)' } },
        { tooltip: { formatter: '<b>x</b>' } },
        { tooltip: { formatter: { $fmt: 'compact' } } },
        { series: [{ tooltip: { formatter: { $fmt: 'pct1' } } }] },
        { a: { $fmt: 'no_such_formatter' } },
        JSON.parse('{"__proto__": {"polluted": true}}'),
        { axisPointer: { link: [{ xAxisIndex: 'all' }] } },
        { tooltip: { valueFormatter: { $fmt: 'thousands' } } },
      ].map((option) => { try { m.reviveOption(option); return 'accepted' } catch (e) { return e.message } }))`,
    )
    const url = 'chart option would navigate to or fetch a URL'
    const html = 'a formatter function cannot be the tooltip template (its result is HTML)'
    expect(verdicts).toEqual([
      url,
      url,
      url,
      url,
      url,
      'chart option formatter template holds markup',
      html,
      html,
      'unknown chart formatter',
      'forbidden key in chart option',
      'accepted',
      'accepted',
    ])
  })

  test('the text alternative of a 300,000-point scatter is capped, not lost, and a gap reads as missing', async ({ page }) => {
    await page.goto('/charts.html?only=reference')
    const facts = await inPage<{ rows: number; total: number; headers: string[]; summary: string; gap: string[] }>(
      page,
      `import('/src/charts/optionData.ts').then((m) => {
        const data = Array.from({ length: 300000 }, (_, i) => [i, i * 2])
        const big = m.describeOption({ series: [{ type: 'scatter', large: true, data }] })
        const gap = m.describeOption({ xAxis: { data: ['a', 'b'] }, series: [{ type: 'line', data: [0.1 + 0.2, null] }] })
        return { rows: big.table.rows.length, total: big.table.total, headers: big.table.headers, summary: big.summary, gap: gap.table.rows.map((r) => r[1]) }
      })`,
    )
    expect(facts).toEqual({
      rows: 100,
      total: 300000,
      headers: ['x', 'y'],
      summary: 'scatter chart with 1 series',
      // 0.1 + 0.2 reads as 0.3, and a null is the empty string the table renders as "missing".
      gap: ['0.3', ''],
    })
  })
})
