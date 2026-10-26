// The cell grid (C6 K11): a virtualised, keyboard-operable data grid over rows that arrive in pages.
//
// Why virtual: a dataset can have hundreds of thousands of rows, and a DOM row per row would
// freeze the page. The scroll container holds a body as tall as the whole table, and only the
// rows under the viewport (plus a few either side) are rendered, positioned absolutely. The
// parent owns the data: it is told which rows are visible (`onRangeChange`) and supplies them
// through `rowAt`, so paging, caching and sorting stay out of this component.
//
// Why aria-activedescendant and not a roving tabindex: the focused cell can scroll out of the
// rendered window, and a focused element that is removed from the DOM drops keyboard focus. The
// grid itself keeps focus (one Tab stop) and names the active cell; the active row is always
// rendered. Row -1 is the header row: Enter or Space there sorts by that column.
//
// A column's type colour (the C6 "region") sits under its header and tints the selected
// column's cells; the same fact is in words in the inspector, never colour alone.
import { useEffect, useId, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent, MouseEvent, UIEvent } from 'react'
import { ChevronDownIcon } from '../workbench/icons.tsx'
import { dtypeKind, dtypeRegion } from './dtype.ts'
import './grid.css'

export interface GridColumn {
  name: string
  dtype: string
}

export interface GridCell {
  row: number // -1 is the header row
  col: number
}

export interface GridSort {
  column: string
  descending: boolean
}

interface DataGridProps {
  label: string
  columns: GridColumn[]
  totalRows: number
  rowAt: (index: number) => readonly string[] | undefined
  sort: GridSort | null
  onSort: (column: string) => void
  active: GridCell
  onActiveChange: (cell: GridCell) => void
  // Reported from scroll and resize events, never from an effect: the first and last row in view.
  onRangeChange: (first: number, last: number) => void
  busy?: boolean
}

const OVERSCAN = 8
const FALLBACK_ROW_PX = 16

// Width in characters: the header must fit with room for padding and the sort arrow.
function columnWidth(column: GridColumn): number {
  const kind = dtypeKind(column.dtype)
  const base = kind === 'text' ? 18 : kind === 'boolean' ? 9 : 12
  return Math.min(40, Math.max(base, column.name.length + 5))
}

// The sticky header covers the first row-height of the viewport, so the last visible data row is
// one row-height above the viewport's bottom edge.
function visibleRange(top: number, rowPx: number, view: number, totalRows: number) {
  const first = Math.max(0, Math.floor(top / rowPx))
  const last = Math.ceil((top + view - rowPx) / rowPx) - 1
  return { first, last: Math.max(first, Math.min(totalRows - 1, last)) }
}

export function DataGrid({ label, columns, totalRows, rowAt, sort, onSort, active, onActiveChange, onRangeChange, busy }: DataGridProps) {
  const gridId = useId()
  const scrollRef = useRef<HTMLDivElement>(null)
  const headRef = useRef<HTMLDivElement>(null)
  const [metrics, setMetrics] = useState({ row: FALLBACK_ROW_PX, view: 0, top: 0 })

  // The latest callback and row count, for the resize observer (which outlives a render).
  const report = useRef(onRangeChange)
  const totalRowsRef = useRef(totalRows)
  useEffect(() => {
    report.current = onRangeChange
    totalRowsRef.current = totalRows
  })

  // Row height is measured from the header row (which is `--size-row` tall), so browser zoom and a
  // changed token keep the arithmetic right; the viewport height follows the pane being resized.
  useEffect(() => {
    const scroller = scrollRef.current
    const head = headRef.current
    if (!scroller || !head) return
    const observer = new ResizeObserver(() => {
      const row = head.getBoundingClientRect().height || FALLBACK_ROW_PX
      const view = scroller.clientHeight
      setMetrics((m) => (m.row === row && m.view === view ? m : { ...m, row, view }))
      const range = visibleRange(scroller.scrollTop, row, view, totalRowsRef.current)
      report.current(range.first, range.last)
    })
    observer.observe(scroller)
    observer.observe(head)
    return () => observer.disconnect()
  }, [])

  const cellId = (row: number, col: number) => `${gridId}-${row}-${col}`

  // Keeps the active cell on screen after a keyboard move or a selection made elsewhere (the
  // schema list). The sticky header and gutter are accounted for by scroll-padding in the CSS.
  useEffect(() => {
    document.getElementById(`${gridId}-${active.row}-${active.col}`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [gridId, active.row, active.col])

  const widths = columns.map(columnWidth)
  const gutter = Math.max(5, String(totalRows).length + 2)
  const style = {
    '--grid-cols': [`${gutter}ch`, ...widths.map((w) => `${w}ch`)].join(' '),
    '--grid-width': `${gutter + widths.reduce((sum, w) => sum + w, 0)}ch`,
    '--grid-gutter': `${gutter}ch`,
  } as CSSProperties

  const firstRow = Math.max(0, Math.floor(metrics.top / metrics.row) - OVERSCAN)
  const lastRow = Math.min(totalRows - 1, Math.ceil((metrics.top + metrics.view) / metrics.row) + OVERSCAN)
  const rows: number[] = []
  for (let i = firstRow; i <= lastRow; i++) rows.push(i)
  // The active row stays rendered wherever it is, so aria-activedescendant never points at nothing.
  if (active.row >= 0 && active.row < totalRows && (active.row < firstRow || active.row > lastRow)) rows.push(active.row)

  const move = (row: number, col: number) => {
    const next = { row: Math.max(-1, Math.min(totalRows - 1, row)), col: Math.max(0, Math.min(columns.length - 1, col)) }
    if (next.row !== active.row || next.col !== active.col) onActiveChange(next)
  }

  const sortBy = (col: number) => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0
    onSort(columns[col].name)
  }

  const onScroll = (event: UIEvent<HTMLDivElement>) => {
    const top = event.currentTarget.scrollTop
    setMetrics((m) => (m.top === top ? m : { ...m, top }))
    const range = visibleRange(top, metrics.row, metrics.view, totalRows)
    onRangeChange(range.first, range.last)
  }

  const onClick = (event: MouseEvent<HTMLDivElement>) => {
    const target = (event.target as HTMLElement).closest<HTMLElement>('[data-row]')
    if (!target || columns.length === 0) return
    const row = Number(target.dataset.row)
    const col = target.dataset.col === undefined ? active.col : Number(target.dataset.col)
    move(row, col)
    if (row === -1) sortBy(col)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Browser and OS shortcuts are not ours; Ctrl+Home and Ctrl+End are the grid's own.
    if (event.altKey || event.metaKey || (event.ctrlKey && event.key !== 'Home' && event.key !== 'End')) return
    if (columns.length === 0) return
    const page = Math.max(1, Math.floor(metrics.view / metrics.row) - 2)
    switch (event.key) {
      case 'ArrowDown':
        move(active.row + 1, active.col)
        break
      case 'ArrowUp':
        move(active.row - 1, active.col)
        break
      case 'ArrowRight':
        move(active.row, active.col + 1)
        break
      case 'ArrowLeft':
        move(active.row, active.col - 1)
        break
      case 'PageDown':
        move(active.row + page, active.col)
        break
      case 'PageUp':
        move(active.row - page, active.col)
        break
      case 'Home':
        move(event.ctrlKey ? 0 : active.row, 0)
        break
      case 'End':
        move(event.ctrlKey ? totalRows - 1 : active.row, columns.length - 1)
        break
      case 'Enter':
      case ' ':
        // Space must never scroll the grid (the active cell would leave the view), even where it does nothing.
        if (active.row !== -1) {
          if (event.key === ' ') event.preventDefault()
          return
        }
        sortBy(active.col)
        break
      default:
        return
    }
    event.preventDefault()
  }

  const direction = (name: string) => (sort?.column === name ? (sort.descending ? 'descending' : 'ascending') : undefined)

  return (
    <div
      ref={scrollRef}
      className="grid"
      role="grid"
      aria-label={label}
      aria-rowcount={totalRows + 1}
      aria-colcount={columns.length + 1}
      aria-busy={busy || undefined}
      aria-activedescendant={columns.length > 0 ? cellId(active.row, active.col) : undefined}
      tabIndex={0}
      style={style}
      onScroll={onScroll}
      onClick={onClick}
      onKeyDown={onKeyDown}
    >
      <div className="grid-head" role="rowgroup">
        <div ref={headRef} className="grid-row" role="row" aria-rowindex={1}>
          <div className="grid-corner" role="columnheader" id={cellId(-1, -1)}>
            <span className="visually-hidden">Row number</span>
            <span aria-hidden>#</span>
          </div>
          {columns.map((column, col) => {
            const sorted = direction(column.name)
            return (
              <div
                key={column.name}
                id={cellId(-1, col)}
                className="grid-cell grid-head-cell"
                role="columnheader"
                aria-sort={sorted ?? 'none'}
                data-row={-1}
                data-col={col}
                data-region={dtypeRegion(column.dtype)}
                data-align={dtypeKind(column.dtype) === 'number' ? 'end' : undefined}
                data-selcol={active.col === col || undefined}
                data-active={(active.row === -1 && active.col === col) || undefined}
              >
                <span className="grid-name">{column.name}</span>
                <span className="grid-sort" data-direction={sorted}>
                  <ChevronDownIcon />
                </span>
              </div>
            )
          })}
        </div>
      </div>
      <div className="grid-body" role="rowgroup" style={{ height: totalRows * metrics.row }}>
        {rows.map((index) => {
          const cells = rowAt(index)
          return (
            <div
              key={index}
              className="grid-row"
              role="row"
              aria-rowindex={index + 2}
              data-odd={index % 2 === 1 || undefined}
              data-pending={cells ? undefined : true}
              style={{ top: index * metrics.row }}
            >
              <div className="grid-corner" role="rowheader" data-row={index}>
                {index + 1}
              </div>
              {columns.map((column, col) => (
                <div
                  key={column.name}
                  id={cellId(index, col)}
                  className="grid-cell"
                  role="gridcell"
                  data-row={index}
                  data-col={col}
                  data-region={dtypeRegion(column.dtype)}
                  data-align={dtypeKind(column.dtype) === 'number' ? 'end' : undefined}
                  data-selcol={active.col === col || undefined}
                  data-active={(active.row === index && active.col === col) || undefined}
                >
                  {cells?.[col]}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
