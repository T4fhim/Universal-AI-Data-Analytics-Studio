// Tables (C6: plans/phase-4-design-reference.md T5 K8, K9, K10): a sortable zebra table, and a
// tree-table with a keyboard model. The inspector (Name / Value) is a two-column DataTable.
//
// Why two implementations: DataTable is a real <table> (best semantics for flat data, sortable
// headers via aria-sort). A hierarchy needs the ARIA treegrid pattern, which a <table> cannot
// express, so TreeTable lays out ARIA rows on a CSS grid and implements the arrow-key model
// itself: Up/Down move between visible rows, Right expands (or enters the first child), Left
// collapses (or goes to the parent), Home/End jump, Enter/Space toggle. Focus is on the row;
// only one row is in the Tab order (roving tabindex).
//
// A swatch is decoration only (aria-hidden): the meaning it carries must also be in a text
// column, so colour is never the only channel.
import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent, ReactNode } from 'react'
import { ChevronDownIcon, ChevronRightIcon } from '../workbench/icons.tsx'
import './components.css'

export interface Column {
  key: string
  label: string
  align?: 'start' | 'end'
  // A CSS grid track for TreeTable ("1fr", "6rem"); ignored by DataTable.
  width?: string
  sortable?: boolean
}

export interface DataRow {
  id: string
  // Any CSS colour, normally a region token such as "var(--region-blue)".
  swatch?: string
  cells: Record<string, ReactNode>
}

export type SortState = { key: string; direction: 'ascending' | 'descending' } | null

interface DataTableProps {
  label: string
  columns: Column[]
  rows: DataRow[]
  // Adds a leading colour column with this header text.
  swatchLabel?: string
  // Makes the first column a row header (th scope=row), so a name/value table reads as pairs.
  rowHeader?: boolean
  sort?: SortState
  // The owner sorts the rows; the table only reports the click and shows the state.
  onSort?: (key: string) => void
}

export function DataTable({ label, columns, rows, swatchLabel, rowHeader, sort = null, onSort }: DataTableProps) {
  return (
    <table className="table" aria-label={label}>
      <thead>
        <tr>
          {swatchLabel && (
            <th scope="col" className="swatch-col" aria-hidden>
              {swatchLabel}
            </th>
          )}
          {columns.map((column) => {
            const direction = sort?.key === column.key ? sort.direction : undefined
            return (
              <th
                key={column.key}
                scope="col"
                data-align={column.align}
                aria-sort={column.sortable && onSort ? (direction ?? 'none') : undefined}
              >
                {column.sortable && onSort ? (
                  <button type="button" className="sort-button" onClick={() => onSort(column.key)}>
                    {column.label}
                    <span className="sort-icon" data-direction={direction}>
                      <ChevronDownIcon />
                    </span>
                  </button>
                ) : (
                  column.label
                )}
              </th>
            )
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            {swatchLabel && (
              <td className="swatch-col" aria-hidden>
                {row.swatch && <span className="swatch" style={{ background: row.swatch }} />}
              </td>
            )}
            {columns.map((column, index) =>
              rowHeader && index === 0 ? (
                <th key={column.key} scope="row" data-align={column.align}>
                  {row.cells[column.key]}
                </th>
              ) : (
                <td key={column.key} data-align={column.align}>
                  {row.cells[column.key]}
                </td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export interface TreeRow extends DataRow {
  children?: TreeRow[]
}

interface FlatRow {
  row: TreeRow
  level: number
  parent: string | null
  posInSet: number
  setSize: number
}

function flatten(rows: TreeRow[], expanded: Set<string>, level = 1, parent: string | null = null): FlatRow[] {
  return rows.flatMap((row, index) => [
    { row, level, parent, posInSet: index + 1, setSize: rows.length },
    ...(row.children && expanded.has(row.id) ? flatten(row.children, expanded, level + 1, row.id) : []),
  ])
}

interface TreeTableProps {
  label: string
  columns: Column[]
  rows: TreeRow[]
  defaultExpanded?: string[]
  swatchLabel?: string
  // Marks one row as selected (aria-selected) and reports a row chosen by click, or by Enter or
  // Space on a row with no children. On a row that has children Enter and Space still expand.
  selectedId?: string
  onSelect?: (id: string) => void
}

export function TreeTable({ label, columns, rows, defaultExpanded = [], swatchLabel, selectedId, onSelect }: TreeTableProps) {
  const [expanded, setExpanded] = useState(() => new Set(defaultExpanded))
  const [focusId, setFocusId] = useState(rows[0]?.id ?? '')
  const rowElements = useRef(new Map<string, HTMLDivElement>())
  const moveFocus = useRef(false)

  const flat = flatten(rows, expanded)
  // The focused row can vanish when the `rows` prop changes: fall back to the first visible row.
  const activeId = flat.some((f) => f.row.id === focusId) ? focusId : (flat[0]?.row.id ?? '')

  // Focuses after the render that made the target row current; sets no state.
  useEffect(() => {
    if (!moveFocus.current) return
    moveFocus.current = false
    rowElements.current.get(activeId)?.focus()
  }, [activeId])

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const goTo = (index: number) => {
    const target = flat[Math.max(0, Math.min(flat.length - 1, index))]
    if (target.row.id === activeId) return // already there: do not arm a focus move that nothing will consume
    moveFocus.current = true
    setFocusId(target.row.id)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>, index: number) => {
    // Browser and OS shortcuts (Alt+Left is Back) and keys meant for a control inside a cell are not ours.
    if (event.altKey || event.ctrlKey || event.metaKey || event.target !== event.currentTarget) return
    const current = flat[index]
    const hasChildren = Boolean(current.row.children?.length)
    const isOpen = expanded.has(current.row.id)
    switch (event.key) {
      case 'ArrowDown':
        goTo(index + 1)
        break
      case 'ArrowUp':
        goTo(index - 1)
        break
      case 'Home':
        goTo(0)
        break
      case 'End':
        goTo(flat.length - 1)
        break
      case 'ArrowRight':
        if (!hasChildren) return
        if (isOpen) goTo(index + 1)
        else toggle(current.row.id)
        break
      case 'ArrowLeft':
        if (hasChildren && isOpen) toggle(current.row.id)
        else if (current.parent) goTo(flat.findIndex((f) => f.row.id === current.parent))
        else return
        break
      case 'Enter':
      case ' ':
        if (hasChildren) toggle(current.row.id)
        else if (onSelect) onSelect(current.row.id)
        else return
        break
      default:
        return
    }
    event.preventDefault()
  }

  const template = [swatchLabel ? 'var(--swatch-col)' : null, ...columns.map((c) => c.width ?? '1fr')].filter(Boolean).join(' ')

  return (
    <div className="treegrid" role="treegrid" aria-label={label} style={{ '--cols': template } as CSSProperties}>
      <div className="tree-row tree-head" role="row">
        {swatchLabel && (
          <div className="tree-cell" role="columnheader" aria-hidden>
            {swatchLabel}
          </div>
        )}
        {columns.map((column) => (
          <div key={column.key} className="tree-cell" role="columnheader" data-align={column.align}>
            {column.label}
          </div>
        ))}
      </div>
      {flat.map(({ row, level, posInSet, setSize }, index) => {
        const hasChildren = Boolean(row.children?.length)
        const isOpen = expanded.has(row.id)
        return (
          <div
            key={row.id}
            ref={(element) => {
              if (element) rowElements.current.set(row.id, element)
              else rowElements.current.delete(row.id)
            }}
            className="tree-row"
            role="row"
            aria-level={level}
            aria-posinset={posInSet}
            aria-setsize={setSize}
            aria-expanded={hasChildren ? isOpen : undefined}
            aria-selected={selectedId === undefined ? undefined : row.id === selectedId}
            tabIndex={row.id === activeId ? 0 : -1}
            onFocus={(event) => {
              if (event.target === event.currentTarget) setFocusId(row.id)
            }}
            onKeyDown={(event) => onKeyDown(event, index)}
            onClick={() => onSelect?.(row.id)}
          >
            {swatchLabel && (
              <div className="tree-cell" role="gridcell" aria-hidden>
                {row.swatch && <span className="swatch" style={{ background: row.swatch }} />}
              </div>
            )}
            {columns.map((column, columnIndex) => (
              <div key={column.key} className="tree-cell" role="gridcell" data-align={column.align}>
                {columnIndex === 0 && (
                  <span className="tree-indent" style={{ paddingInlineStart: `${(level - 1) * 2}ch` }}>
                    <span className="tree-toggle" aria-hidden onClick={(event) => {
                      if (!hasChildren) return
                      event.stopPropagation() // expanding must not also select the row
                      toggle(row.id)
                    }}>
                      {hasChildren && (isOpen ? <ChevronDownIcon /> : <ChevronRightIcon />)}
                    </span>
                  </span>
                )}
                {row.cells[column.key]}
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
