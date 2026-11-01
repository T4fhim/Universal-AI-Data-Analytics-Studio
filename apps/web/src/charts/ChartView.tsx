// The renderer registry and the fallback ladder (CI.8a).
//
// A chart arrives as a payload that already says which renderer draws it. The renderer is chosen by the
// server's render plan (plans/phase-4-chart-intelligence.md section 3.6), never from anything a user typed,
// and the set is closed: the `renderer` of `ChartPayload`, matched exhaustively below, so a payload with any
// other name does not compile and, from untyped JSON, is refused by the API's schema before it reaches here.
// `payload.option` must keep its identity between renders (a query result does): the view remembers *which*
// option failed, so a new option gets a fresh attempt and the same one does not retry forever. `d3` joins when
// the first chart neither library draws is scheduled (CI.10); the HTML `component` renderer joins with the KPI
// port (CI.8e). Nothing is built for either before then.
//
// The ladder: ECharts is the core renderer and Plotly the second. If ECharts cannot draw (its chunk did not
// load, or the option is one the reviver refuses) and the payload carries the Plotly figure of the *same*
// reduced data, that figure is drawn with a one-line note; with no figure there is a plain message. Either way
// the data table of the option is still offered, because it needs the option and not the library. The note and
// the message are fixed text: an error's own message can quote a value from the data.
//
// Announcing a failure: a live region is only reliably announced when it exists *before* its text changes, and
// the chart that failed is swapped out for another element. So one polite, visually hidden status element
// stays mounted in the same place in every branch and only its text changes; the visible note has no role of
// its own, and nothing is `role="alert"` (a chunk that fails to load fails every chart on the page at once, and
// that many assertive interruptions would be worse than the failure).
import { useState } from 'react'
import type { ReactElement } from 'react'
import { ChartDataTable, EChartsChart } from './EChartsChart.tsx'
import { describeOption } from './optionData.ts'
import { PlotlyChart } from './PlotlyChart.tsx'
import type { Figure } from './skin.ts'
import './charts.css'

export type ChartPayload =
  | { renderer: 'echarts'; option: unknown; fallback?: Figure }
  | { renderer: 'plotly'; figure: Figure }

// The closed set of renderers, derived from the payload so the two cannot differ.
export type RendererName = ChartPayload['renderer']

interface ChartViewProps {
  payload: ChartPayload
  label: string
  height?: number
  // The Plotly skin chips (Absolute|Percentage, Linear|Log); ECharts charts carry their own controls later.
  controls?: boolean
}

const FALLBACK_NOTE = 'Drawn with the fallback chart renderer.'
const FAILURE_NOTE = 'The chart could not be drawn.'

export function ChartView({ payload, label, height, controls = false }: ChartViewProps): ReactElement {
  // The option that failed, boxed so that an option that is itself `undefined` (data still loading) is not mistaken
  // for "nothing failed yet", and not a boolean so a new option gets a fresh attempt with no effect to reset it.
  const [failedFor, setFailedFor] = useState<{ option: unknown } | null>(null)

  if (payload.renderer === 'plotly') {
    return <PlotlyChart figure={payload.figure} skin label={label} controls={controls} height={height} />
  }

  const failed = failedFor !== null && failedFor.option === payload.option
  const note = !failed ? '' : payload.fallback ? FALLBACK_NOTE : FAILURE_NOTE
  const table = failed ? describeOption(payload.option).table : undefined

  return (
    <>
      {!failed && (
        <EChartsChart
          option={payload.option}
          label={label}
          height={height}
          onError={(failedOption, error) => {
            // The error's name only: its message may quote a value from the data.
            console.warn('chart renderer failed:', error instanceof Error ? error.name : typeof error)
            setFailedFor({ option: failedOption })
          }}
        />
      )}
      {failed && payload.fallback && (
        <PlotlyChart figure={payload.fallback} skin label={label} controls={controls} height={height} />
      )}
      {failed && note !== '' && <p className="chart-note">{note}</p>}
      {table && <ChartDataTable table={table} label={label} />}
      <p role="status" className="visually-hidden">
        {note}
      </p>
    </>
  )
}
