// Named chart formatters and the reviver that puts them into an ECharts option (CI.8a).
//
// Why named formatters: the server builds an ECharts option as plain JSON (uadas_core/visualization/
// base_option_builder.py), and JSON cannot carry a function, so wherever ECharts wants one the option
// holds `{ "$fmt": "<name>" }` and this module owns what that name means. The set of names is closed
// on both sides: the core refuses a name outside it, `reviveOption` throws on one, and a test
// (tests/visualization/test_base_option_builder.py) reads FORMATTER_NAMES below and fails when it differs
// from the core's list. Why a throw and not a fallback: an unknown name means the two sides disagree, and
// drawing a chart with the wrong number format would be worse than the fallback renderer taking over.
//
// Where a function may stand. ECharts treats what a formatter returns as canvas text (an axis label, a label)
// or encodes it itself (`tooltip.valueFormatter`), except in ONE place: the string `tooltip.formatter` returns is
// set as HTML. A tenant's text must never become markup, so a `$fmt` is refused there (here and in the core) and
// nothing in this module escapes: escaping in the formatter would double-encode in `valueFormatter` and show
// entities on the canvas.
//
// The locale is fixed (en-US) so a number reads the same on every machine, which also keeps the golden
// screenshots independent of the host.

export const FORMATTER_NAMES = ['pct1', 'compact', 'thousands', 'fixed2'] as const

export type FormatterName = (typeof FORMATTER_NAMES)[number]
// `valueFormatter` receives the whole `[x, y]` of a multi-dimensional point and accepts one string per element.
export type Formatter = (value: unknown) => string | string[]

const PCT1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const COMPACT = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })
const THOUSANDS = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })
const FIXED2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const isObject = (value: unknown): value is object => value !== null && typeof value === 'object'

// ECharts hands a formatter a bare number (an axis label), a params object (a label or a tooltip), an array of
// params objects (an axis tooltip) or, to a `valueFormatter`, the array of numbers of one point. A params
// object yields its `value` (the last element when that is itself `[x, y]`); an array of params objects, the
// first one's.
function unwrap(raw: unknown): unknown {
  if (Array.isArray(raw)) return unwrap(raw[0])
  if (isObject(raw) && 'value' in raw) {
    const value = (raw as { value: unknown }).value
    return Array.isArray(value) ? value[value.length - 1] : value
  }
  return raw
}

// Only a number is formatted. A string is shown as it is ("2024" stays "2024", not "2,024"): a formatter never
// reinterprets a label, and never hides a value by turning it into "NaN".
function one(format: (n: number) => string, value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) return format(value)
  return value === null || value === undefined ? '' : String(value)
}

function numeric(format: (n: number) => string): Formatter {
  return (raw) => {
    // The numbers of one point: one string for each.
    if (Array.isArray(raw) && raw.every((item) => !isObject(item))) return raw.map((item) => one(format, item))
    return one(format, unwrap(raw))
  }
}

export const FORMATTERS: Record<FormatterName, Formatter> = {
  // A share already in percent (42.123 is "42.1%"): the core normalises a 100 % stack to 0-100.
  pct1: numeric((n) => `${PCT1.format(n)}%`),
  compact: numeric((n) => COMPACT.format(n)),
  thousands: numeric((n) => THOUSANDS.format(n)),
  fixed2: numeric((n) => FIXED2.format(n)),
}

export function isFormatterName(name: string): name is FormatterName {
  return (FORMATTER_NAMES as readonly string[]).includes(name)
}

// The client repeats the checks of the core's `validate_option` that guard the browser (defence in depth: the
// server is the gate, this is what is left if a payload ever skips it). Keys that mean something to a JavaScript
// object merge; keys whose *string* value ECharts opens with `window.open` (a `javascript:` URL would run in the
// app's origin); keys that name a URL to fetch or CSS to apply. `axisPointer.link` is a list, not a URL, and passes.
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype'])
const NAVIGATION_KEYS = new Set(['link', 'sublink', 'target', 'subtarget'])
const FETCH_KEYS = new Set(['image', 'icon', 'src', 'url', 'extraCssText'])
// The same depth as the core (base_option_builder.py MAX_DEPTH).
const MAX_DEPTH = 16

const isImageSymbol = (item: unknown): boolean => typeof item === 'string' && item.toLowerCase().startsWith('image://')

function refuse(key: string, item: unknown): void {
  const navigates = NAVIGATION_KEYS.has(key) && typeof item === 'string'
  const markup = key === 'formatter' && typeof item === 'string' && item.includes('<')
  // `symbol` is a string, or a list of them (markLine, markPoint, visualMap).
  const imageSymbol = key === 'symbol' && (isImageSymbol(item) || (Array.isArray(item) && item.some(isImageSymbol)))
  if (FORBIDDEN_KEYS.has(key)) throw new Error('forbidden key in chart option')
  if (FETCH_KEYS.has(key) || navigates || imageSymbol) throw new Error('chart option would navigate to or fetch a URL')
  if (markup) throw new Error('chart option formatter template holds markup')
}

// A copy of `option` with every `{ "$fmt": name }` replaced by its function. Never mutates its input, and
// builds objects with `Object.fromEntries` (own properties), never by assigning to a key that could be
// `__proto__`. `trail` is the keys on the way down (array positions are not keys), used to refuse a function
// where ECharts would render its result as HTML.
export function reviveOption(value: unknown, depth = 0, trail: readonly string[] = []): unknown {
  if (depth > MAX_DEPTH) throw new Error('chart option is nested too deeply')
  if (Array.isArray(value)) return value.map((item) => reviveOption(item, depth + 1, trail))
  if (value === null || typeof value !== 'object') return value
  const record = value as Record<string, unknown>
  if ('$fmt' in record) {
    const name = record.$fmt
    if (Object.keys(record).length !== 1 || typeof name !== 'string' || !isFormatterName(name)) {
      throw new Error('unknown chart formatter')
    }
    if (trail.at(-1) === 'formatter' && trail.at(-2) === 'tooltip') {
      throw new Error('a formatter function cannot be the tooltip template (its result is HTML)')
    }
    return FORMATTERS[name]
  }
  return Object.fromEntries(
    Object.entries(record).map(([key, item]) => {
      refuse(key, item)
      return [key, reviveOption(item, depth + 1, [...trail, key])]
    }),
  )
}
