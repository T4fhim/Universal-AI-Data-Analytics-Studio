// The Profile tab (C6 K13, "plot well"): how complete each column is, from the file's own summary.
//
// Why completeness and not a histogram: the summary endpoint reports types, missing counts and
// ranges from the file footer without reading the data, so this plot costs no extra job. A real
// distribution needs the profile stage (a job), which arrives with the stage views. Each bar
// shows the share of rows that are not missing; the figure beside it says the same in words, so
// the bar is never the only channel.
import { AlertBar, Button } from '../../components/controls.tsx'
import { dtypeRegion, regionColour } from '../../components/dtype.ts'
import { useWorkbenchData } from '../dataContext.ts'

export function ProfileView() {
  const { active, summary, summaryFailed, retrySummary, cell } = useWorkbenchData()
  if (active && summaryFailed) return <AlertBar action={<Button onClick={retrySummary}>Retry</Button>}>The column summary could not be loaded.</AlertBar>
  if (!active || !summary) return <p className="empty">Upload a file to see how complete each column is.</p>

  const total = summary.row_count
  const selected = summary.columns[cell.col]

  return (
    <div className="view">
      <div className="plot-frame">
        <div className="plot-well">
          <h2 className="plot-title">Complete values per column (share of {total.toLocaleString('en')} rows)</h2>
          <ul className="bars" aria-label="Complete values per column">
            {summary.columns.map((column, index) => {
              const known = column.null_count !== null && column.null_count !== undefined
              const share = known && total > 0 ? 1 - (column.null_count as number) / total : 0
              const percent = Math.round(share * 1000) / 10
              return (
                <li key={column.name} className="bar-row" data-selected={index === cell.col || undefined}>
                  <span className="bar-name">{column.name}</span>
                  <span className="bar-track" aria-hidden>
                    <span className="bar-fill" style={{ width: `${share * 100}%`, background: regionColour(dtypeRegion(column.dtype)) }} />
                  </span>
                  <span className="bar-value">{known ? `${percent} %` : 'unknown'}</span>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
      {selected && (
        <p className="readout-line">
          <span className="dim">Selected</span> {selected.name}, {selected.dtype}, range {selected.min ?? '-'} to {selected.max ?? '-'}
        </p>
      )}
    </div>
  )
}
