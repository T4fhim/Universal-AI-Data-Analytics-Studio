// The ECharts chunk: the modular import set the 14 registered chart types need, registered once, with the
// Instrument theme (CI.8a).
//
// Why a module of its own and not `import * as echarts from 'echarts'`: the full package is 1.1 MB
// (360 KB gzipped); `echarts/core` plus the ten chart types, thirteen components and the canvas renderer the
// catalogue needs is about 295 KB gzipped (plans/phase-4-ci0-findings.md section 6.5). Why one module that
// `echarts.ts` imports dynamically: Vite then gives all of it one lazy chunk, fetched the first time a chart
// is drawn and never part of the initial bundle (scripts/check-bundle.mjs enforces both). Adding a chart
// type, component or feature is a deliberate edit to this list, with the budget check as the reviewer.
//
// The renderer is canvas only. SVG would give the chart per-element DOM, but the CI.0 measurements and the
// golden screenshots are canvas, and the text alternative is a data table built from the option
// (optionData.ts), not from the SVG.
import * as echarts from 'echarts/core'
import {
  BarChart,
  BoxplotChart,
  CandlestickChart,
  FunnelChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  TreemapChart,
} from 'echarts/charts'
import {
  AriaComponent,
  AxisPointerComponent,
  DataZoomComponent,
  DatasetComponent,
  GraphicComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { LabelLayout, UniversalTransition } from 'echarts/features'
import { CanvasRenderer } from 'echarts/renderers'
import theme from '../../../../assets/design-tokens/echarts-theme.json'

echarts.use([
  BarChart,
  BoxplotChart,
  CandlestickChart,
  FunnelChart,
  HeatmapChart,
  LineChart,
  PieChart,
  RadarChart,
  ScatterChart,
  TreemapChart,
  AriaComponent,
  AxisPointerComponent,
  DataZoomComponent,
  DatasetComponent,
  GraphicComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  LabelLayout,
  UniversalTransition,
  CanvasRenderer,
])

// Generated from the same design tokens as the Plotly template (scripts/build_design_tokens.py).
export const THEME = 'instrument'
echarts.registerTheme(THEME, theme)

export { echarts }
