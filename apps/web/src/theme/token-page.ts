// Dev-only gallery of the Instrument design tokens, served at /tokens.html.
//
// Why: the plan's phase-2 exit criterion is "a token page you can look at" (swatches, region
// fills with contrast, type ramp). It reads the *generated* tokens.resolved.json, so what you
// see is exactly what scripts/build_design_tokens.py produced and tested; nothing here is
// hand-typed. It is not part of the production bundle (index.html does not link it).
import './token-page.css'
import resolved from './tokens.resolved.json'

type Check = { pair: string; ratio: number; min: number; pass: boolean }
type Region = { key: string; fill: string }

const tokens: Record<string, string> = resolved.tokens
const sources: Record<string, string> = resolved.sources
const region: Record<string, Region> = resolved.region
const checks: Check[] = resolved.checks

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className = '',
  text = '',
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text) node.textContent = text
  return node
}

function section(title: string, note: string): HTMLElement {
  const s = el('section', 'tp-section')
  s.append(el('h2', 'tp-title', title), el('p', 'tp-note', note))
  return s
}

function swatches(group: string): HTMLElement {
  const grid = el('div', 'tp-swatches')
  for (const [name, value] of Object.entries(tokens)) {
    if (!name.startsWith(`${group}.`) || !value.startsWith('#')) continue
    const item = el('div', 'tp-swatch')
    const chip = el('span', 'tp-chip')
    chip.style.background = value
    item.append(chip, el('code', '', name), el('span', 'tp-dim', `${value}  ${sources[name]}`))
    grid.append(item)
  }
  return grid
}

function regionRows(): HTMLElement {
  const table = el('div', 'tp-region')
  for (const [name, { key, fill }] of Object.entries(region)) {
    const ratio = checks.find((c) => c.pair === `text.primary on region.${name} fill`)?.ratio
    const row = el('div', 'tp-region-row')
    const swatch = el('span', 'tp-chip')
    swatch.style.background = key
    const cell = el('span', 'tp-cells', '4D 5A 90 00 03 00 00 00')
    cell.style.background = fill
    row.append(swatch, el('code', '', name), el('span', 'tp-dim', `${key} -> ${fill}`), cell)
    row.append(el('span', 'tp-dim', `${ratio?.toFixed(2)} : 1`))
    table.append(row)
  }
  return table
}

function demoPane(): HTMLElement {
  const pane = el('div', 'tp-pane')
  const tabs = el('div', 'tp-tabs')
  tabs.append(
    el('span', 'tp-tab tp-tab-focused', 'Hex editor'),
    el('span', 'tp-tab tp-tab-unfocused', 'Data Inspector'),
    el('span', 'tp-tab tp-tab-inactive', 'Bookmarks'),
  )
  const rows = el('div', 'tp-rows')
  const data: [string, string][] = [
    ['Binary (8 bit)', '01001101'],
    ['uint8_t', '77'],
    ['int8_t', '77'],
    ['uint16_t', '23117'],
    ['ASCII Character', "'M'"],
    ['String', '"MZ"'],
  ]
  for (const [name, value] of data) {
    const row = el('div', 'tp-row')
    row.append(el('span', '', name), el('span', '', value))
    rows.append(row)
  }
  pane.append(tabs, rows)
  return pane
}

function contrastTable(): HTMLElement {
  const table = el('div', 'tp-contrast')
  const bad = checks.filter((c) => !c.pass).length
  table.append(el('p', 'tp-note', `${checks.length - bad} of ${checks.length} pairs pass.`))
  for (const c of checks) {
    const row = el('div', c.pass ? 'tp-crow' : 'tp-crow tp-fail')
    row.append(el('span', '', c.pair), el('span', '', `${c.ratio.toFixed(2)}`), el('span', '', `min ${c.min}`))
    table.append(row)
  }
  return table
}

const root = document.getElementById('token-page')!
const series = el('div', 'tp-series')
resolved.series_order.forEach((name: string) => {
  const bar = el('span', 'tp-bar')
  bar.style.background = region[name].key
  bar.title = name
  series.append(bar)
})

const surfaces = section('Surfaces', 'C6 greys: canvas behind panes, chrome band, pane, wells, table header, zebra.')
surfaces.append(swatches('surface'))
const blues = section('Blue family', 'The single chrome accent: tab states, fields, buttons, radio.')
blues.append(swatches('blue'))
const semantic = section('Semantic', 'Amber = the one editable value; crimson = one alert bar; the rest are text colours.')
semantic.append(swatches('semantic'))
const regions = section('Region palette (50 % rule)', 'Key colour for swatches and lines; the same colour at 50 % over the pane behind text.')
regions.append(regionRows())
const chart = section('Series order', 'Colours used by the Plotly template, in order.')
chart.append(series)
const demo = section('Pane proportions', 'Tab strip (focused / unfocused / inactive) and a zebra table at the single row height.')
demo.append(demoPane())
const audit = section('Contrast audit', 'Generated; the build fails if any pair drops below its minimum.')
audit.append(contrastTable())

root.append(
  el('h1', 'tp-h1', 'Instrument tokens'),
  surfaces, blues, semantic, regions, chart, demo, audit,
)
