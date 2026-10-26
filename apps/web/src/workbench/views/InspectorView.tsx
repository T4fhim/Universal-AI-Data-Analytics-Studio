// The Inspector pane (C6 K10): a Name / Value table for the selected column and, when a cell is
// selected, its row number and value.
//
// Why the cell value is repeated in full under the table: grid and table cells clip long text
// with an ellipsis, and the inspector is the one place the whole value can be read. The value
// comes from the preview page the grid already fetched (same query key, so no extra request).
import { PAGE_SIZE, usePreviewPages } from '../../api/queries.ts'
import { AlertBar, Button } from '../../components/controls.tsx'
import { DataTable } from '../../components/tables.tsx'
import type { DataRow } from '../../components/tables.tsx'
import { dtypeKind } from '../../components/dtype.ts'
import { useWorkbenchData } from '../dataContext.ts'

const COLUMNS = [
  { key: 'name', label: 'Name' },
  { key: 'value', label: 'Value', align: 'end' as const },
]

const row = (name: string, value: string): DataRow => ({ id: name, cells: { name, value } })

// A value longer than this is also shown in full under the table, where it can wrap.
const LONG_VALUE = 24

export function InspectorView() {
  const { active, scope, summary, summaryFailed, retrySummary, cell, sort } = useWorkbenchData()
  const column = summary?.columns[cell.col]
  const page = cell.row >= 0 ? Math.floor(cell.row / PAGE_SIZE) : -1
  const pages = usePreviewPages(scope, active?.id ?? null, sort, page >= 0 ? [page] : [])
  const value = page >= 0 ? pages[0]?.data?.rows[cell.row % PAGE_SIZE]?.[cell.col] : undefined

  if (active && summaryFailed) return <AlertBar action={<Button onClick={retrySummary}>Retry</Button>}>The column summary could not be loaded.</AlertBar>
  if (!active || !summary || !column) {
    return <p className="empty">Select a cell or a column to see its type, missing values, minimum and maximum.</p>
  }

  const nulls = column.null_count
  const missing = nulls === null || nulls === undefined ? 'unknown' : `${nulls.toLocaleString('en')} (${summary.row_count ? ((nulls / summary.row_count) * 100).toFixed(1) : '0.0'} %)`

  return (
    <div className="view">
      <DataTable
        label={`Column ${column.name}`}
        columns={COLUMNS}
        rowHeader
        rows={[
          row('Column', column.name),
          row('Position', `${cell.col + 1} of ${summary.column_count}`),
          row('Type', column.dtype),
          row('Kind', dtypeKind(column.dtype)),
          row('Missing', missing),
          row('Minimum', column.min ?? '-'),
          row('Maximum', column.max ?? '-'),
          ...(cell.row >= 0 ? [row('Row', (cell.row + 1).toLocaleString('en')), row('Value', value ?? (pages[0]?.isError ? '-' : 'Loading...'))] : []),
        ]}
      />
      {cell.row >= 0 && value !== undefined && value.length > LONG_VALUE && <p className="cell-value">{value}</p>}
    </div>
  )
}
