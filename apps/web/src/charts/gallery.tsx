// Dev-only gallery of the Instrument chart skin, served at /charts.html.
//
// Why: the phase-4 plan's step 6 output was "the 12 charts before/after" (13 with the candlestick of step 7.4). Every chart type the core
// registers is drawn twice from the same figure JSON, which scripts/build_chart_gallery.py
// builds with the real chart classes: untouched on the left (what the API returns), in the skin
// on the right. A multi-series stacked column (the OpenRouter-style reference the skin is tuned
// against) comes first, with its Absolute|Percentage and Linear|Log chips. Not part of the
// production bundle (index.html does not link it).
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '../index.css'
import '../components/components.css'
import './charts.css'
import figures from './gallery-figures.json'
import { PlotlyChart } from './PlotlyChart.tsx'
import type { Figure } from './skin.ts'

const charts = figures.charts as unknown as Record<string, Figure>
const reference = figures.references.stacked as unknown as Figure

function Box({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="g-box" aria-label={title}>
      <h2 className="g-title">{title}</h2>
      <div className="g-body">{children}</div>
    </section>
  )
}

function Pair({ name, figure }: { name: string; figure: Figure }) {
  return (
    <Box title={name}>
      <div className="chart-pair">
        <div className="chart-side">
          <p className="chart-caption">Before: as the API returns it</p>
          <PlotlyChart figure={figure} skin={false} label={`${name}, before`} />
        </div>
        <div className="chart-side">
          <p className="chart-caption">After: Instrument skin</p>
          <PlotlyChart figure={figure} skin label={`${name}, after`} controls />
        </div>
      </div>
    </Box>
  )
}

export const REFERENCE_TITLE = 'Reference: stacked column (not a registered chart)'

// `?only=<chart name>` (or `?only=reference`) draws that one box. The golden-screenshot tests use it:
// drawing all 26 figures per test made the later charts miss the test timeout.
export function Gallery() {
  const only = new URLSearchParams(window.location.search).get('only')
  return (
    <main className="g-page">
      <h1 className="g-h1">Instrument charts</h1>
      {(only === null || only === 'reference') && <Pair name={REFERENCE_TITLE} figure={reference} />}
      {Object.keys(charts)
        .sort()
        .filter((name) => only === null || only === name)
        .map((name) => (
          <Pair key={name} name={name} figure={charts[name]} />
        ))}
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Gallery />
  </StrictMode>,
)
