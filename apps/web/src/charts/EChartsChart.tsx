// One ECharts chart, in the Instrument theme, with a text alternative (CI.8a).
//
// Why the chart is drawn in an effect and never as React output: ECharts owns its canvas. The effect hands it
// the option (the server's JSON with its `$fmt` references swapped for functions, formatters.ts) and reads
// nothing back. Three rules come from measurements in plans/phase-4-ci0-findings.md section 6:
//  * `echarts.init` on an element that already holds an instance returns that instance and MERGES the new
//    option into it, so the effect disposes any instance on the element first and again on cleanup (React's
//    StrictMode mounts, unmounts and mounts again, which is exactly that case);
//  * `aria.decal.show` must never be on (it gives every series without a decal a default one); the core
//    refuses it in an option, and this component never sets it;
//  * the Plotly SVG and the ECharts canvas are never pixel-equal, so the goldens of a ported chart are
//    re-baselined with a sign-off, not diffed against the Plotly ones.
//
// Failure is reported, not handled here: any error, from the chunk not loading to an option the reviver
// refuses, calls `onError` once and draws nothing. What happens next is ChartView's fallback ladder.
//
// Text alternative: the host *is* the image (`role="img"`, named with the label and the summary, which ECharts'
// aria component is told to write verbatim), and the same values are offered as a data table in a native
// <details> (keyboard operable, closed by default). `ChartDataTable` is exported because ChartView shows it on
// every path, including the ones where ECharts never drew: the table needs the option, not the library.
import { useEffect, useEffectEvent, useMemo, useRef } from 'react'
import type { ReactElement } from 'react'
import { loadECharts } from './echarts.ts'
import { reviveOption } from './formatters.ts'
import { describeOption } from './optionData.ts'
import type { OptionTable } from './optionData.ts'
import './charts.css'

interface EChartsChartProps {
  // The option as the server sent it: plain JSON, possibly holding `{ "$fmt": name }` references.
  option: unknown
  label: string
  height?: number
  // Called once per failed option, with that option: a late failure of an old option must not be blamed on a newer one.
  onError: (option: unknown, error: unknown) => void
}

const isDict = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

// A missing value is announced, not left blank: a blank cell reads the same as an empty label.
function Cell({ value }: { value: string }): ReactElement {
  if (value !== '') return <>{value}</>
  return (
    <>
      <span aria-hidden="true">—</span>
      <span className="visually-hidden">missing</span>
    </>
  )
}

export function ChartDataTable({ table, label }: { table: OptionTable; label: string }): ReactElement {
  const capped = table.total > table.rows.length
  const note = `First ${table.rows.length} of ${table.total.toLocaleString('en-US')} rows.`
  return (
    <details className="chart-table">
      <summary>
        Data table<span className="visually-hidden">{` for ${label}`}</span>
      </summary>
      <div className="chart-table-scroll" role="region" aria-label={`Data for ${label}`} tabIndex={0}>
        <table>
          <caption className="visually-hidden">{capped ? `Values of ${label}. ${note}` : `Values of ${label}`}</caption>
          <thead>
            <tr>
              {table.headers.map((header, column) => (
                <th key={column} scope="col">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, index) => (
              <tr key={index}>
                {row.map((cell, column) =>
                  column === 0 ? (
                    <th key={column} scope="row">
                      <Cell value={cell} />
                    </th>
                  ) : (
                    <td key={column}>
                      <Cell value={cell} />
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {capped && <p className="chart-note">{note}</p>}
    </details>
  )
}

export function EChartsChart({ option, label, height = 280, onError }: EChartsChartProps): ReactElement {
  const host = useRef<HTMLDivElement>(null)
  const facts = useMemo(() => describeOption(option), [option])
  const description = `${label}. ${facts.summary}`
  const fail = useEffectEvent(onError)

  useEffect(() => {
    const node = host.current
    if (!node) return
    let cancelled = false
    let chart: { dispose(): void } | undefined
    let observer: ResizeObserver | undefined
    loadECharts()
      .then(({ echarts, THEME }) => {
        if (cancelled) return
        // Refuse a bad option before anything is created: a refused option draws nothing, not even an empty canvas.
        const revived = reviveOption(option)
        echarts.getInstanceByDom(node)?.dispose()
        const instance = echarts.init(node, THEME, { renderer: 'canvas' })
        chart = instance
        observer = new ResizeObserver(() => instance.resize())
        observer.observe(node)
        const base = isDict(revived) ? revived : {}
        const aria = isDict(base.aria) ? base.aria : {}
        const still = prefersReducedMotion()
        instance.setOption(
          {
            ...base,
            // Motion is the renderer's to decide: an option can ask for none, never force it on.
            animation: base.animation !== false && !still,
            ...(still ? { animationDuration: 0, animationDurationUpdate: 0 } : {}),
            aria: { ...aria, enabled: true, label: { enabled: true, description } },
          },
          { notMerge: true },
        )
      })
      .catch((error: unknown) => {
        if (cancelled) return
        // Setup can throw after `init`: leave nothing alive behind a chart that is reported as not drawn.
        observer?.disconnect()
        chart?.dispose()
        fail(option, error)
      })
    return () => {
      cancelled = true
      observer?.disconnect()
      chart?.dispose()
    }
  }, [option, description])

  return (
    <figure className="chart chart-echarts">
      <div ref={host} className="chart-host" role="img" aria-label={description} style={{ height }} />
      {facts.table && <ChartDataTable table={facts.table} label={label} />}
    </figure>
  )
}
