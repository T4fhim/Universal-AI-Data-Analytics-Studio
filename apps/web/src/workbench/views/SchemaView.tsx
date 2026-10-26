// The Schema and Lineage tabs (C6 K9): the active dataset's columns, and every dataset in the
// project arranged by what it was derived from.
//
// Why two TreeTables and not one: a column is a part of a dataset, while a derived dataset is a
// step after it; mixing the two in one tree would make "expand" mean two different things.
// Selecting a column row selects that column in the grid (the same cell state); selecting a
// dataset row makes it the active dataset. Orphans (a parent that was deleted) are roots: the
// workspace model keeps them on purpose.
import { AlertBar, Button } from '../../components/controls.tsx'
import { dtypeRegion, regionColour } from '../../components/dtype.ts'
import { TreeTable } from '../../components/tables.tsx'
import type { Column, TreeRow } from '../../components/tables.tsx'
import type { DatasetOut } from '../../api/client.ts'
import { useWorkbenchData } from '../dataContext.ts'

const SCHEMA_COLUMNS: Column[] = [
  { key: 'name', label: 'Name', width: '1.4fr' },
  { key: 'type', label: 'Type', width: '1fr' },
  { key: 'nulls', label: 'Missing', align: 'end', width: '0.7fr' },
]

const LINEAGE_COLUMNS: Column[] = [
  { key: 'name', label: 'Name', width: '1.3fr' },
  { key: 'step', label: 'Step', width: '1.4fr' },
  { key: 'rows', label: 'Rows', align: 'end', width: '0.7fr' },
]

export function SchemaView() {
  const { active, summary, summaryFailed, retrySummary, cell, setCell } = useWorkbenchData()
  if (active && summaryFailed) return <AlertBar action={<Button onClick={retrySummary}>Retry</Button>}>The column summary could not be loaded.</AlertBar>
  if (!active || !summary) return <p className="empty">Column names, types and positions appear here once a dataset is loaded.</p>

  const columns: TreeRow[] = summary.columns.map((column, index) => ({
    id: `col-${index}`,
    swatch: regionColour(dtypeRegion(column.dtype)),
    cells: { name: column.name, type: column.dtype, nulls: column.null_count === null || column.null_count === undefined ? '-' : column.null_count.toLocaleString('en') },
  }))
  const totalMissing = summary.columns.reduce((sum, column) => sum + (column.null_count ?? 0), 0)
  const rows: TreeRow[] = [
    {
      id: 'dataset',
      cells: { name: active.name, type: `${summary.column_count} columns`, nulls: totalMissing.toLocaleString('en') },
      children: columns,
    },
  ]

  return (
    <div className="view">
      <TreeTable
        key={active.id}
        label={`Columns of ${active.name}`}
        columns={SCHEMA_COLUMNS}
        rows={rows}
        defaultExpanded={['dataset']}
        swatchLabel="Kind"
        selectedId={`col-${cell.col}`}
        onSelect={(id) => id.startsWith('col-') && setCell({ row: cell.row, col: Number(id.slice(4)) })}
      />
    </div>
  )
}

function lineageTree(datasets: DatasetOut[]): TreeRow[] {
  const known = new Set(datasets.map((d) => d.id))
  const build = (dataset: DatasetOut): TreeRow => {
    const children = datasets.filter((d) => d.parent_dataset_id === dataset.id).map(build)
    return {
      id: dataset.id,
      cells: {
        name: dataset.name,
        step: dataset.derivation_description || `upload (${dataset.source_format})`,
        rows: dataset.row_count.toLocaleString('en'),
      },
      children: children.length > 0 ? children : undefined,
    }
  }
  return datasets.filter((d) => !d.parent_dataset_id || !known.has(d.parent_dataset_id)).map(build)
}

export function LineageView() {
  const { datasets, active, setActiveId } = useWorkbenchData()
  if (datasets.length === 0) return <p className="empty">Every dataset derived from another is listed here, with the step that produced it.</p>

  const rows = lineageTree(datasets)
  const parents = datasets.filter((d) => datasets.some((other) => other.parent_dataset_id === d.id)).map((d) => d.id)
  return (
    <div className="view">
      <TreeTable
        key={datasets.map((d) => d.id).join()}
        label="Dataset lineage"
        columns={LINEAGE_COLUMNS}
        rows={rows}
        defaultExpanded={parents}
        selectedId={active?.id}
        onSelect={setActiveId}
      />
    </div>
  )
}
