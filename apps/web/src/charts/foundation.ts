// A fixed chart for the ECharts foundation (CI.8a), shown in the dev gallery at /charts.html?only=foundation.
//
// Why a fixture and not a ported chart: the foundation (renderer registry, lazy chunk, theme, fallback
// ladder, text alternative) lands before any chart is ported (CI.8b onwards), so it needs a chart of its own to
// be exercised, golden-tested and fault-injected. The option is hand-written here the way a core option builder
// will emit it (plain JSON, a named `$fmt` formatter where ECharts wants a function); the fallback is the same
// data as a Plotly figure, which is what the API will send beside every ECharts option. Not part of the
// production bundle: only the gallery imports this file.
import type { ChartPayload } from './ChartView.tsx'
import type { Figure } from './skin.ts'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const VISITS = [1200, 1850, 2400, 3100, 2750]
const SIGNUPS = [120, 210, 260, 340, 300]

const OPTION = {
  legend: { data: ['Visits', 'Sign-ups'] },
  tooltip: { trigger: 'axis', valueFormatter: { $fmt: 'thousands' } },
  xAxis: { type: 'category', data: DAYS, name: 'Day' },
  yAxis: { type: 'value', axisLabel: { formatter: { $fmt: 'compact' } } },
  series: [
    { name: 'Visits', type: 'bar', data: VISITS },
    { name: 'Sign-ups', type: 'line', data: SIGNUPS },
  ],
}

const FALLBACK: Figure = {
  data: [
    { type: 'bar', name: 'Visits', x: DAYS, y: VISITS },
    { type: 'scatter', mode: 'lines', name: 'Sign-ups', x: DAYS, y: SIGNUPS },
  ],
  layout: {},
}

// `single` is the same chart with one series: swapping to it re-draws an existing chart with *fewer* series, which
// is what exposes ECharts' merge-into-the-old-instance trap (a merged chart would still have both).
export type FoundationVariant = 'ok' | 'single' | 'broken' | 'broken-no-fallback'

// `broken` holds a formatter name the SPA does not implement, so the reviver refuses it: the render-failure
// half of the fallback ladder (the other half, the chunk not loading, is injected by the test at the network).
export function foundationPayload(variant: FoundationVariant = 'ok'): ChartPayload {
  const option =
    variant === 'ok'
      ? OPTION
      : variant === 'single'
        ? { ...OPTION, legend: { data: ['Visits'] }, series: OPTION.series.slice(0, 1) }
        : { ...OPTION, yAxis: { type: 'value', axisLabel: { formatter: { $fmt: 'no_such_formatter' } } } }
  return variant === 'broken-no-fallback'
    ? { renderer: 'echarts', option }
    : { renderer: 'echarts', option, fallback: FALLBACK }
}
