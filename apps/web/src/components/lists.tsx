// A ranked leaderboard and a log pane (plans/phase-4-design-reference.md T9: "ranked list" with a
// thin coloured underline as its bar, "log = a K8 table with level colours"; phase-4 step 7).
//
// Why these two are components and not Plotly figures: both are lists of rows read for their text,
// which a chart canvas would make unreadable to a screen reader and unselectable. Each row keeps
// its meaning in text: the rank is a number, the value is written out, the log level is a word.
// The colour (the bar, the level swatch) is decoration only, so colour is never the only channel.
import { DataTable } from './tables.tsx'
import type { Column, DataRow } from './tables.tsx'
import './components.css'

export interface RankedRow {
  id: string
  label: string
  value: number
  // The value as it should be read; defaults to the number with thousands separators.
  display?: string
}

interface RankedListProps {
  label: string
  rows: RankedRow[]
  // Written after each value ("tokens", "%"); part of the text, not a decoration.
  unit?: string
}

// Rows are ranked here, highest value first (a stable sort, so a tie keeps its given order), so a
// caller cannot show a "ranking" that is not one. The underline under each row is its value as a
// share of the top value; a negative value draws none.
export function RankedList({ label, rows, unit }: RankedListProps) {
  // A row with no usable value (NaN) cannot be ranked, and would break the sort's order.
  const ranked = rows.filter((row) => Number.isFinite(row.value)).sort((a, b) => b.value - a.value)
  if (ranked.length === 0) return <p className="dim">Nothing to rank.</p>
  const top = Math.max(ranked[0].value, 0)
  return (
    // role="list": list-style: none drops the list semantics in Safari with VoiceOver otherwise.
    <ol className="ranked" role="list" aria-label={label}>
      {ranked.map((row, index) => {
        const share = top > 0 ? (Math.max(row.value, 0) / top) * 100 : 0
        return (
          <li key={row.id} className="ranked-row">
            <span className="ranked-rank">{index + 1}</span>
            <span className="ranked-label">{row.label}</span>
            <span className="ranked-value">
              {row.display ?? row.value.toLocaleString('en')}
              {unit ? ` ${unit}` : ''}
            </span>
            <span className="ranked-bar" aria-hidden style={{ width: `${share}%` }} />
          </li>
        )
      })}
    </ol>
  )
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogEntry {
  id: string
  time: string
  level: LogLevel
  message: string
}

// The level colours are region keys; the level is also its own column, in words.
const LEVEL_SWATCH: Record<LogLevel, string> = {
  debug: 'var(--region-grey)',
  info: 'var(--region-blue)',
  warn: 'var(--region-yellow)',
  error: 'var(--region-red)',
}

const LEVEL_WORD: Record<LogLevel, string> = { debug: 'DEBUG', info: 'INFO', warn: 'WARN', error: 'ERROR' }

const LOG_COLUMNS: Column[] = [
  { key: 'time', label: 'Time' },
  { key: 'level', label: 'Level' },
  { key: 'message', label: 'Message' },
]

interface LogPaneProps {
  label: string
  entries: LogEntry[]
}

// A K8 table of entries, newest last as a log reads. The pane scrolls when it is long, so the
// scroll area is a focusable region: a keyboard user can scroll it without a pointer (WCAG 2.1.1).
export function LogPane({ label, entries }: LogPaneProps) {
  if (entries.length === 0) return <p className="dim">No log entries.</p>
  const rows: DataRow[] = entries.map((entry) => ({
    id: entry.id,
    swatch: LEVEL_SWATCH[entry.level],
    cells: { time: entry.time, level: LEVEL_WORD[entry.level], message: entry.message },
  }))
  return (
    <div className="log-pane" role="region" aria-label={label} tabIndex={0}>
      <DataTable label={`${label}, entries`} columns={LOG_COLUMNS} rows={rows} swatchLabel="Level colour" />
    </div>
  )
}
