// Plotly.js, loaded on demand behind a small typed surface.
//
// Why a dynamic import: the bundle is 4.7 MB (about 1.4 MB gzipped) and most sessions never open a
// chart. `import()` makes Vite give it a chunk of its own, fetched the first time a chart mounts
// and cached after that. Why the pinned version: the Python `plotly` package that builds the
// figures (6.8.0, resources/web/PLOTLY_VERSION.txt) is paired with plotly.js 3.6.0, and a figure's
// JSON is only guaranteed for its own renderer.

export type PlotlyPoint = Record<string, unknown>

// Plotly decorates the element it draws into with an event emitter.
export interface PlotlyHost extends HTMLElement {
  on?: (event: string, handler: (event: { points?: PlotlyPoint[] }) => void) => void
  removeAllListeners?: (event: string) => void
}

export interface PlotlyApi {
  react(host: HTMLElement, data: unknown[], layout: Record<string, unknown>, config: Record<string, unknown>): Promise<unknown>
  purge(host: HTMLElement): void
  Plots: { resize(host: HTMLElement): void }
}

let loading: Promise<PlotlyApi> | undefined

export function loadPlotly(): Promise<PlotlyApi> {
  loading ??= import('plotly.js-dist-min').then((module) => (module.default ?? module) as PlotlyApi)
  return loading
}
