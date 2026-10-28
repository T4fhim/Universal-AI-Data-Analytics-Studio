// One Plotly figure, in the Instrument skin or (for the before / after gallery) as the API
// returned it, with the chart idioms around it: the Absolute|Percentage and Linear|Log chips and a
// one-line readout of the point under the cursor.
//
// Why the plot is drawn in an effect and not as React output: Plotly owns its DOM. The effect
// hands it the figure (`Plotly.react`, which diffs against what is drawn) and never reads state
// back out, apart from the hover readout, which is set from Plotly's event callback and not
// from the effect body. Why a ResizeObserver: Plotly only follows the *window* size, and a pane
// in the workbench changes size when a gutter is dragged.
//
// Known gap (documented in plans/phase-4-design-reference.md, step 6): Plotly's marks cannot be
// reached by keyboard, so the readout is a pointer aid only and the figure has a short text
// summary, not a data table. A table alternative belongs with the chart builder.
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { RadioGroup } from '../components/controls.tsx'
import { loadPlotly } from './plotly.ts'
import type { PlotlyHost } from './plotly.ts'
import { DEFAULT_VIEW, describePoint, figureFacts, plain, skinned } from './skin.ts'
import type { Figure } from './skin.ts'
import './charts.css'

interface PlotlyChartProps {
  figure: Figure
  // False draws the figure untouched, for the "before" side of the gallery.
  skin: boolean
  label: string
  // Shows the chips that apply to this figure (none for a pie, say).
  controls?: boolean
  height?: number
}

const IDLE = 'Hover a mark to read its values.'

export function PlotlyChart({ figure, skin, label, controls = false, height = 280 }: PlotlyChartProps) {
  const id = useId()
  const host = useRef<HTMLDivElement>(null)
  const [view, setView] = useState(DEFAULT_VIEW)
  const [readout, setReadout] = useState('')
  const [failed, setFailed] = useState(false)
  const facts = useMemo(() => figureFacts(figure), [figure])

  useEffect(() => {
    const node = host.current as PlotlyHost | null
    if (!node) return
    let cancelled = false
    const frame = skin ? skinned(figure, view) : plain(figure)
    loadPlotly()
      .then(async (Plotly) => {
        if (cancelled) return
        await Plotly.react(node, frame.data, frame.layout, frame.config)
        if (cancelled) return
        // react() keeps old listeners: replace, never stack.
        node.removeAllListeners?.('plotly_hover')
        node.removeAllListeners?.('plotly_unhover')
        node.on?.('plotly_hover', (event) => setReadout(describePoint(event.points?.[0])))
        node.on?.('plotly_unhover', () => setReadout(''))
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [figure, skin, view])

  useEffect(() => {
    const node = host.current
    if (!node) return
    let live = true
    const observer = new ResizeObserver(() => {
      void loadPlotly().then((Plotly) => {
        try {
          if (live) Plotly.Plots.resize(node)
        } catch {
          // Not drawn yet: the first react() sizes it.
        }
      })
    })
    observer.observe(node)
    return () => {
      live = false
      observer.disconnect()
      void loadPlotly().then((Plotly) => Plotly.purge(node))
    }
  }, [])

  const showChips = controls && skin && (facts.stacked || facts.cartesian)

  return (
    <figure className="chart">
      {showChips && (
        <div className="chart-controls">
          {facts.stacked && (
            <RadioGroup
              legend="Scale"
              name={`${id}-scale`}
              value={view.percent ? 'percent' : 'absolute'}
              options={[
                { value: 'absolute', label: 'Absolute' },
                { value: 'percent', label: 'Percentage' },
              ]}
              onChange={(value) => setView((prev) => ({ ...prev, percent: value === 'percent' }))}
            />
          )}
          {facts.cartesian && (
            <RadioGroup
              legend="Axis"
              name={`${id}-axis`}
              value={view.log ? 'log' : 'linear'}
              options={[
                { value: 'linear', label: 'Linear' },
                { value: 'log', label: 'Log' },
              ]}
              onChange={(value) => setView((prev) => ({ ...prev, log: value === 'log' }))}
            />
          )}
        </div>
      )}
      {/* A group, not an img: Plotly's mode bar is focusable, and an img may not contain focusable
          descendants (axe: nested-interactive). The summary is its description. */}
      <div ref={host} className="chart-host" role="group" aria-label={label} aria-describedby={`${id}-summary`} style={{ height }} />
      <span id={`${id}-summary`} className="visually-hidden">
        {facts.summary}
      </span>
      {skin && (
        <p className="chart-readout" data-idle={readout === '' || undefined}>
          {failed ? 'The chart library could not be loaded.' : readout || IDLE}
        </p>
      )}
    </figure>
  )
}
