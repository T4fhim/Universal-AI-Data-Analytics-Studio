// The Data pane: sign-in, the first-run pane, or the dataset grid, plus the upload drop target.
//
// Why paging lives here: the grid is purely presentational, so this component turns "which
// rows are in view" into "which preview pages to fetch" (TanStack Query caches each page by
// dataset and sort), and hands the grid a `rowAt` lookup. Columns come from the summary, which
// is cached per dataset, so sorting (which changes every page's key) never blanks the headers.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { MAX_PREVIEW_ROWS, PAGE_SIZE, usePreviewPages } from '../../api/queries.ts'
import type { DatasetOut } from '../../api/client.ts'
import { AlertBar, Button } from '../../components/controls.tsx'
import { DataGrid } from '../../components/grid.tsx'
import { useWorkbenchData } from '../dataContext.ts'
import { FirstRun } from './FirstRun.tsx'
import { SignIn } from './SignIn.tsx'

// A few rows beyond the viewport are fetched too (the grid renders that margin), so a short
// scroll never shows blank rows.
const PREFETCH_ROWS = 16

// Pages are requested only once the scroll has settled: dragging the scrollbar sweeps across
// hundreds of pages, and each unsettled one would spend the preview rate budget (120 a minute).
const RANGE_SETTLE_MS = 150

function pagesFor(first: number, last: number, total: number): number[] {
  const start = Math.max(0, first - PREFETCH_ROWS)
  const end = Math.max(0, Math.min(last + PREFETCH_ROWS, total - 1))
  const pages = new Set([0])
  for (let page = Math.floor(start / PAGE_SIZE); page <= Math.floor(end / PAGE_SIZE); page++) pages.add(page)
  return [...pages].sort((a, b) => a - b)
}

function DatasetGrid({ dataset }: { dataset: DatasetOut }) {
  const { scope, summary, cell, setCell, sort, toggleSort } = useWorkbenchData()
  const [range, setRange] = useState({ first: 0, last: 40 })
  const settle = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(settle.current), [])
  // Only rows the API can page to are scrollable (see MAX_PREVIEW_ROWS).
  const total = Math.min(dataset.row_count, MAX_PREVIEW_ROWS)
  const pages = useMemo(() => pagesFor(range.first, range.last, total), [range, total])
  const results = usePreviewPages(scope, dataset.id, sort, pages)

  const columns = summary?.columns ?? results[0]?.data?.columns ?? []
  const rowAt = (index: number) => results[pages.indexOf(Math.floor(index / PAGE_SIZE))]?.data?.rows[index % PAGE_SIZE]
  const failed = results.some((result) => result.isError)
  const selected = columns[cell.col]

  const onRange = (first: number, last: number) => {
    window.clearTimeout(settle.current)
    settle.current = window.setTimeout(
      () => setRange((prev) => (prev.first === first && prev.last === last ? prev : { first, last })),
      RANGE_SETTLE_MS,
    )
  }

  return (
    <div className="dataset-view">
      {failed && (
        <AlertBar action={<Button onClick={() => results.forEach((result) => result.isError && void result.refetch())}>Retry</Button>}>
          Some rows could not be loaded.
        </AlertBar>
      )}
      <DataGrid
        label={`Rows of ${dataset.name}`}
        columns={columns}
        totalRows={total}
        rowAt={rowAt}
        sort={sort}
        onSort={toggleSort}
        active={cell}
        onActiveChange={setCell}
        onRangeChange={onRange}
        busy={results.some((result) => result.isFetching)}
      />
      <div className="readout">
        <span>
          <span className="dim">Rows</span> {total === 0 ? 0 : range.first + 1}-{Math.min(range.last + 1, total)} of {dataset.row_count.toLocaleString('en')}
        </span>
        {dataset.row_count > total && (
          <span>
            <span className="dim">Scrollable</span> first {total.toLocaleString('en')}
          </span>
        )}
        {selected && (
          <span>
            <span className="dim">Column</span> {selected.name}
          </span>
        )}
        {sort && (
          <span>
            <span className="dim">Sorted</span> {sort.column} {sort.descending ? 'descending' : 'ascending'}
          </span>
        )}
      </div>
    </div>
  )
}

export function DataView() {
  const { phase, retry, active, upload, openPicker, uploadFile, gridFocusTick } = useWorkbenchData()
  const [dragging, setDragging] = useState(false)
  const depth = useRef(0)

  // When an upload finishes the first-run pane (and its button) is replaced by the grid: if focus
  // was on either, or was lost, it goes to the grid instead of the page. A user who has moved on
  // to something else keeps focus where it is.
  useEffect(() => {
    if (gridFocusTick === 0) return
    const focused = document.activeElement
    if (!focused || focused === document.body || focused.id === 'open-file') {
      document.querySelector<HTMLElement>('#pane-data [role=grid]')?.focus()
    }
  }, [gridFocusTick])

  if (phase === 'loading' || phase === 'loading-account') return <p className="empty">Loading...</p>
  if (phase === 'unreachable') {
    return (
      <AlertBar action={<Button onClick={retry}>Retry</Button>}>The server is not answering.</AlertBar>
    )
  }
  if (phase === 'signed-out') return <SignIn />

  const hasFiles = (event: DragEvent) => event.dataTransfer.types.includes('Files')
  const onDragEnter = (event: DragEvent) => {
    if (!hasFiles(event)) return
    depth.current += 1
    setDragging(true)
  }
  const onDragLeave = (event: DragEvent) => {
    if (!hasFiles(event)) return
    depth.current = Math.max(0, depth.current - 1)
    if (depth.current === 0) setDragging(false)
  }
  const onDrop = (event: DragEvent) => {
    if (!hasFiles(event)) return
    event.preventDefault()
    depth.current = 0
    setDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) uploadFile(file)
  }

  return (
    <div
      className="dropzone"
      data-dragging={dragging || undefined}
      onDragEnter={onDragEnter}
      onDragOver={(event) => hasFiles(event) && event.preventDefault()}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {upload.status === 'failed' && (
        <AlertBar action={<Button onClick={openPicker}>Choose another file</Button>}>
          {upload.name} could not be added: {upload.message}
        </AlertBar>
      )}
      {upload.status === 'busy' && active && (
        <p className="banner">
          {upload.step === 'uploading' ? 'Sending' : 'Reading'} {upload.name}
          {upload.step === 'processing' ? ` ${upload.progress} %` : ''}...
        </p>
      )}
      {active ? <DatasetGrid key={active.id} dataset={active} /> : <FirstRun />}
      {dragging && (
        <div className="drop-hint" aria-hidden>
          Drop to add this file
        </div>
      )}
    </div>
  )
}
