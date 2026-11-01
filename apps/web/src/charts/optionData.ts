// The text alternative of an ECharts option: a one-line summary and a data table, built from the option
// itself (CI.8a).
//
// Why: an ECharts canvas gives a screen reader one container label and nothing per mark (plans/
// phase-4-ci0-findings.md section 4), so the values must also exist as text. Both come from the same option
// the chart is drawn from, so the table cannot say something the chart does not. The extraction understands
// the shapes the catalogue produces (category-aligned numbers for bar and line, `{name, value}` items for pie,
// funnel and treemap, coordinate or OHLC arrays for scatter, candlestick, heatmap and box plot), returns no
// table for anything else, and never throws (a chart with no table is still a chart).
//
// It works on the option as the server sent it, before the formatters are revived, so it needs no ECharts and
// is also what the fallback paths show when ECharts could not be loaded. It is bounded: only the first
// MAX_TABLE_ROWS rows are ever mapped (a 1M-point scatter costs the same as a 100-point one) and a cell is
// cut at MAX_CELL characters. Cell text comes out as plain strings that React renders as text nodes, so a
// tenant's labels are escaped. A missing value is the empty string; the table shows it as "missing", never
// as a blank that could mean an empty label.

export interface OptionTable {
  headers: string[]
  rows: string[][]
  // The number of rows before the cap, so the page can say "first 100 of 5,000".
  total: number
}

export interface OptionFacts {
  summary: string
  table: OptionTable | undefined
}

export const MAX_TABLE_ROWS = 100
const MAX_CELL = 200

type Dict = Record<string, unknown>

const isDict = (value: unknown): value is Dict => value !== null && typeof value === 'object' && !Array.isArray(value)
const asList = (value: unknown): unknown[] => (Array.isArray(value) ? value : isDict(value) ? [value] : [])
const isNamed = (item: unknown): boolean => isDict(item) && 'name' in item

function text(value: unknown): string {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return ''
    // 12 significant digits removes binary noise (0.30000000000000004) and keeps every digit of an integer.
    return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(12)))
  }
  if (typeof value === 'string') return value.length > MAX_CELL ? `${value.slice(0, MAX_CELL)}…` : value
  if (typeof value === 'boolean') return String(value)
  if (isDict(value) && 'value' in value) return text(value.value)
  return ''
}

// The category labels of the first axis that has any, with that axis's name.
// `count` is the true number of categories; `labels` is capped like the table.
function categoriesOf(root: Dict): { labels: string[]; axisName: string; count: number } {
  for (const axis of [...asList(root.xAxis), ...asList(root.yAxis)]) {
    if (isDict(axis) && Array.isArray(axis.data) && axis.data.length > 0) {
      return { labels: axis.data.slice(0, MAX_TABLE_ROWS).map(text), axisName: text(axis.name), count: axis.data.length }
    }
  }
  return { labels: [], axisName: '', count: 0 }
}

const seriesName = (series: Dict, index: number): string => text(series.name) || `Series ${index + 1}`

// ECharts' candlestick data order is [open, close, low, high].
const OHLC = ['Open', 'Close', 'Low', 'High']

// Column names for the numbers of an array item: the series' own `dimensions`, the candlestick order, else x, y, ...
function valueHeaders(series: Dict, width: number, hasCategories: boolean): string[] {
  const own = asList(series.dimensions).map(text).filter((name) => name !== '')
  const base = own.length >= width ? own : series.type === 'candlestick' ? OHLC : []
  return Array.from({ length: width }, (_, i) => base[i] ?? (hasCategories || i > 1 ? `Value ${i + 1}` : i === 0 ? 'x' : 'y'))
}

function capped(headers: string[], rows: string[][], total: number): OptionTable {
  return { headers, rows: rows.slice(0, MAX_TABLE_ROWS), total }
}

function tableOf(root: Dict, series: Dict[], categories: string[], axisName: string): OptionTable | undefined {
  const first = series[0]
  if (!first) return undefined
  const items = asList(first.data)
  if (items.length === 0) return undefined
  const head = items.slice(0, MAX_TABLE_ROWS)
  const names = series.map(seriesName)

  // Pie, funnel, treemap: one row per named item, one value column per series (matched by position).
  if (head.every(isNamed)) {
    const rows = head.map((item, row) => [text((item as Dict).name), ...series.map((s) => text(asList(s.data)[row]))])
    return capped(['Name', ...names], rows, items.length)
  }

  // Heatmap: `[xIndex, yIndex, value]`, the indices into the two category axes (not row positions).
  if (first.type === 'heatmap' && head.every((item) => Array.isArray(item) && item.length >= 3)) {
    const [xAxis, yAxis] = [asList(root.xAxis)[0], asList(root.yAxis)[0]]
    const labelsOf = (axis: unknown): unknown[] => (isDict(axis) && Array.isArray(axis.data) ? axis.data : [])
    const [xs, ys] = [labelsOf(xAxis), labelsOf(yAxis)]
    const rows = head.map((item) => {
      const [x, y, value] = item as unknown[]
      return [text(xs[Number(x)] ?? x), text(ys[Number(y)] ?? y), text(value)]
    })
    return capped([text(isDict(xAxis) ? xAxis.name : '') || 'x', text(isDict(yAxis) ? yAxis.name : '') || 'y', 'Value'], rows, items.length)
  }

  // Scatter, candlestick, box plot: each item is an array of numbers.
  if (head.every((item) => Array.isArray(item))) {
    let width = 0
    for (const item of head) width = Math.max(width, (item as unknown[]).length)
    const headers = valueHeaders(first, width, categories.length > 0)
    if (categories.length > 0) {
      const rows = head.map((item, row) => [categories[row] ?? String(row + 1), ...(item as unknown[]).map(text)])
      return capped([axisName || 'Category', ...headers], rows, items.length)
    }
    // No category axis: coordinates. With several series each row says which one it belongs to.
    const several = series.length > 1
    const rows: string[][] = []
    let total = 0
    series.forEach((s, index) => {
      const data = asList(s.data)
      total += data.length
      for (const item of data.slice(0, Math.max(0, MAX_TABLE_ROWS - rows.length))) {
        const cells = Array.isArray(item) ? item.map(text) : [text(item)]
        rows.push(several ? [seriesName(s, index), ...cells] : cells)
      }
    })
    return capped(several ? ['Series', ...headers] : headers, rows, total)
  }

  // Bar, line: one row per category, one column per series.
  const labels = categories.length > 0 ? categories : head.map((_, row) => String(row + 1))
  const rows = labels.map((label, row) => [label, ...series.map((s) => text(asList(s.data)[row]))])
  return capped([axisName || 'Category', ...names], rows, Math.max(items.length, categories.length))
  // (`categories` is capped like the rows, so for a very long axis the total is the series length.)
}

function describe(option: unknown): OptionFacts {
  const root = isDict(option) ? option : {}
  const series = asList(root.series).filter(isDict)
  const kinds = [...new Set(series.map((s) => text(s.type) || 'line'))].join(', ')
  const { labels, axisName, count } = categoriesOf(root)
  const parts = [`${kinds || 'Empty'} chart with ${series.length} series`]
  if (count > 0) parts.push(`${count} categories`)
  return { summary: parts.join(', '), table: tableOf(root, series, labels, axisName) }
}

export function describeOption(option: unknown): OptionFacts {
  try {
    return describe(option)
  } catch {
    return { summary: 'A chart.', table: undefined }
  }
}
