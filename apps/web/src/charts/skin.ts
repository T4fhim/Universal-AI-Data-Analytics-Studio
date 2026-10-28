// The Instrument skin for a Plotly figure: what is added to a figure the API returned.
//
// Why the skin is applied here and not in the Python chart classes: the core builds plain,
// unstyled figures (the same JSON the API's `charts_render` returns), so every consumer gets the
// same data and the look stays in one place, generated from the design tokens
// (assets/design-tokens/plotly-template.json). The template carries the colours, mono type,
// dotted quarter grid, flat marks and per-chart-type defaults; the five things done here are
// the ones a template cannot express:
//  * hover labels are hidden (`hoverinfo: 'none'` still fires hover events) because the point
//    under the cursor is read out on one line under the chart instead of in a floating box;
//  * a trace named "Incomplete" is drawn hatched, the OpenRouter idiom for a bucket that is not
//    finished yet (a bar that looks complete would mislead);
//  * a filled area (a line drawn to the baseline) is filled with its series colour at a low alpha,
//    flat and with no gradient, so the 1 px line above it still reads;
//  * a bar trace named "Volume" (under a candlestick) is drawn in the neutral axis grey: the
//    colours of the candles mean direction, so the volume must not take the next series colour;
//  * the Absolute|Percentage and Linear|Log chips: `barnorm` and the y axis type.
import template from '../../../../assets/design-tokens/plotly-template.json'

export interface Figure {
  data: Record<string, unknown>[]
  layout?: Record<string, unknown>
}

export interface View {
  percent: boolean
  log: boolean
}

export const DEFAULT_VIEW: View = { percent: false, log: false }

// Mirrors the old desktop theme's config: no logo, the mode bar always visible (zoom and pan stay
// reachable), the two selection tools that need a pointing device removed.
const CONFIG = {
  displaylogo: false,
  displayModeBar: true,
  responsive: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d'],
  toImageButtonOptions: { format: 'png', scale: 2 },
}

const CARTESIAN = new Set(['bar', 'scatter', 'box', 'histogram', 'candlestick'])
const INCOMPLETE = /incomplete/i
const VOLUME = /^volume$/i
// The axis line colour (a neutral grey) is the hatch colour.
const HATCH = (template.layout.xaxis as { linecolor: string }).linecolor
// Plotly's own fill is the line colour at 50 %, which swallows a 1 px line of the same hue.
const AREA_ALPHA = 0.22

// The fill of a filled scatter trace: its line colour (set on the trace, else the colorway entry
// Plotly gives a trace at that position) at AREA_ALPHA. Nothing when the colour is not a #rrggbb.
function areaFill(trace: Record<string, unknown>, index: number): string | undefined {
  const own = (trace.line as { color?: unknown } | undefined)?.color
  const colorway = template.layout.colorway as string[]
  const colour = typeof own === 'string' ? own : colorway[index % colorway.length]
  const hex = /^#([0-9a-f]{6})$/i.exec(colour)
  if (!hex) return undefined
  const rgb = parseInt(hex[1], 16)
  return `rgba(${rgb >> 16}, ${(rgb >> 8) & 255}, ${rgb & 255}, ${AREA_ALPHA})`
}

export interface FigureFacts {
  // Two or more bar traces are stacked, so can be shown as a percentage of the stack (bars side by
  // side, `barmode: group`, have no stack to be a share of).
  stacked: boolean
  // Every trace has a numeric y axis, so a log axis makes sense.
  cartesian: boolean
  summary: string
}

export function figureFacts(figure: Figure): FigureFacts {
  const types = figure.data.map((trace) => String(trace.type ?? 'scatter'))
  const bars = types.filter((type) => type === 'bar').length
  const kinds = [...new Set(types)].join(', ')
  return {
    stacked: bars >= 2 && figure.layout?.barmode !== 'group',
    cartesian: types.length > 0 && types.every((type) => CARTESIAN.has(type)),
    summary: `${kinds} chart with ${types.length} ${types.length === 1 ? 'trace' : 'traces'}`,
  }
}

interface Frame {
  data: Record<string, unknown>[]
  layout: Record<string, unknown>
  config: typeof CONFIG
}

// A copy: Plotly writes bookkeeping properties onto the objects it is given.
function cloned(figure: Figure): Figure {
  return structuredClone({ data: figure.data, layout: figure.layout ?? {} })
}

// The figure exactly as the API returned it (for the before / after comparison).
export function plain(figure: Figure): Frame {
  const { data, layout = {} } = cloned(figure)
  delete layout.width
  delete layout.height
  return { data, layout: { ...layout, autosize: true }, config: CONFIG }
}

export function skinned(figure: Figure, view: View = DEFAULT_VIEW): Frame {
  const { data, layout = {} } = cloned(figure)
  delete layout.width
  delete layout.height
  // A bar named "Volume" is a candlestick's volume pane only when candles are drawn with it: a bar
  // chart whose series happens to be called "Volume" keeps its series colour.
  const hasCandles = data.some((trace) => trace.type === 'candlestick')
  const traces = data.map((trace, index) => {
    const next: Record<string, unknown> = { ...trace, hoverinfo: 'none' }
    if ((trace.type ?? 'scatter') === 'scatter' && trace.fill && trace.fill !== 'none' && trace.fillcolor === undefined) {
      next.fillcolor = areaFill(trace, index)
    }
    // The heatmap builder names a Plotly colour scale itself, which a template cannot override:
    // a scale centred on a value (a correlation, centred on 0) is diverging, any other sequential.
    if (trace.type === 'heatmap') {
      const scales = template.layout.colorscale
      next.colorscale = trace.zmid === undefined ? scales.sequential : scales.diverging
    }
    if (trace.type === 'bar' && INCOMPLETE.test(String(trace.name ?? ''))) {
      const marker = (trace.marker ?? {}) as Record<string, unknown>
      next.marker = { ...marker, pattern: { shape: '/', size: 6, solidity: 0.35, fgcolor: HATCH, bgcolor: 'rgba(0,0,0,0)' } }
    }
    if (hasCandles && trace.type === 'bar' && VOLUME.test(String(trace.name ?? ''))) {
      next.marker = { ...((trace.marker ?? {}) as Record<string, unknown>), color: HATCH }
    }
    return next
  })
  const skin: Record<string, unknown> = { ...layout, template, autosize: true }
  if (view.percent) {
    skin.barmode = layout.barmode ?? 'stack'
    skin.barnorm = 'percent'
    skin.yaxis = { ...(layout.yaxis as object), ticksuffix: ' %' }
  }
  // The first y axis only: under a candlestick that is the price (a log price axis is meaningful),
  // while the volume pane's axis stays linear; on a dual-axis line it is the left-hand series.
  if (view.log) skin.yaxis = { ...(skin.yaxis as object), type: 'log' }
  return { data: traces, layout: skin, config: CONFIG }
}

function format(value: unknown): string {
  return typeof value === 'number' ? value.toLocaleString('en', { maximumFractionDigits: 3 }) : String(value)
}

// One line for the point under the cursor: the series name, then whichever coordinates the
// trace type has. Pie and treemap points have a label and value, a radar point a theta and r.
export function describePoint(point: Record<string, unknown> | undefined): string {
  if (!point) return ''
  const parts: string[] = []
  const name = (point.data as { name?: unknown } | undefined)?.name
  if (name) parts.push(String(name))
  const has = (key: string) => point[key] !== undefined && point[key] !== null
  // A bar point repeats its x as `label` and its y as `value`: name each fact once.
  const keys = [
    ...(has('label') && !has('x') ? ['label'] : []),
    'x',
    'y',
    'open',
    'high',
    'low',
    'close',
    'z',
    'theta',
    'r',
    ...(has('value') && !has('y') && !has('r') ? ['value'] : []),
  ]
  for (const key of keys) {
    if (!has(key)) continue
    parts.push(key === 'label' ? format(point[key]) : `${key}: ${format(point[key])}`)
  }
  if (typeof point.percent === 'number') parts.push(`${(point.percent * 100).toFixed(1)} %`)
  return parts.join('  ·  ')
}
