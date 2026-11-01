// ECharts, loaded on demand behind a small typed surface (CI.8a).
//
// The same idea as plotly.ts: `import()` gives the library a chunk of its own, fetched the first time a chart
// mounts, so the initial bundle does not grow. A failed load is **final for the page**: a browser remembers a
// module whose fetch failed and rejects the next `import()` of it without asking the network again (measured:
// three attempts, one request), so caching the promise or forgetting it makes no difference and a retry loop
// would only spin. The caller (ChartView) turns the failure into the fallback ladder; a reload is the recovery.

export type EChartsModule = typeof import('./echarts-bundle.ts')

let loading: Promise<EChartsModule> | undefined

export function loadECharts(): Promise<EChartsModule> {
  loading ??= import('./echarts-bundle.ts')
  return loading
}
