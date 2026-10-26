// Dev-only gallery of the Instrument components, served at /components.html.
//
// Why: the plan's phase-4 exit criterion is "a component gallery you can look at". Every
// component appears in its states (sorted, collapsed, disabled) on
// synthetic sample data, so reviewers and the browser checks exercise the real components. It
// is not part of the production bundle (index.html does not link it).
import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import '../index.css'
import './components.css'
import { AlertBar, Button, RadioGroup, Select } from './controls.tsx'
import { EditableValue, KeyValueList, QuoteStrip, SheetColumns, SheetSection } from './sheet.tsx'
import { DataTable, TreeTable } from './tables.tsx'
import type { Column, DataRow, SortState, TreeRow } from './tables.tsx'

const columns: Column[] = [
  { key: 'name', label: 'Name', sortable: true },
  { key: 'type', label: 'Type', sortable: true },
  { key: 'nulls', label: 'Nulls', align: 'end', sortable: true },
  { key: 'distinct', label: 'Distinct', align: 'end', sortable: true },
]

const sampleRows: (DataRow & { sortValues: Record<string, string | number> })[] = [
  { id: 'c1', swatch: 'var(--region-grey)', cells: { name: 'order_id', type: 'id', nulls: '0', distinct: '18,410' }, sortValues: { name: 'order_id', type: 'id', nulls: 0, distinct: 18410 } },
  { id: 'c2', swatch: 'var(--region-orange)', cells: { name: 'ordered_at', type: 'date', nulls: '12', distinct: '364' }, sortValues: { name: 'ordered_at', type: 'date', nulls: 12, distinct: 364 } },
  { id: 'c3', swatch: 'var(--region-green)', cells: { name: 'region', type: 'text', nulls: '0', distinct: '6' }, sortValues: { name: 'region', type: 'text', nulls: 0, distinct: 6 } },
  { id: 'c4', swatch: 'var(--region-blue)', cells: { name: 'ad_spend', type: 'number', nulls: '231', distinct: '9,802' }, sortValues: { name: 'ad_spend', type: 'number', nulls: 231, distinct: 9802 } },
  { id: 'c5', swatch: 'var(--region-blue)', cells: { name: 'revenue', type: 'number', nulls: '0', distinct: '17,955' }, sortValues: { name: 'revenue', type: 'number', nulls: 0, distinct: 17955 } },
  { id: 'c6', swatch: 'var(--region-purple)', cells: { name: 'is_returned', type: 'boolean', nulls: '0', distinct: '2' }, sortValues: { name: 'is_returned', type: 'boolean', nulls: 0, distinct: 2 } },
]

const lineage: TreeRow[] = [
  {
    id: 'ds1',
    swatch: 'var(--region-grey)',
    cells: { name: 'sales.csv', step: 'upload', rows: '18,410' },
    children: [
      {
        id: 'ds2',
        swatch: 'var(--region-teal)',
        cells: { name: 'sales_clean', step: 'drop_duplicates', rows: '18,102' },
        children: [
          { id: 'ds3', swatch: 'var(--region-blue)', cells: { name: 'sales_monthly', step: 'aggregate by month', rows: '12' } },
          { id: 'ds4', swatch: 'var(--region-blue)', cells: { name: 'sales_by_region', step: 'aggregate by region', rows: '6' } },
        ],
      },
    ],
  },
  { id: 'ds5', swatch: 'var(--region-grey)', cells: { name: 'returns.csv', step: 'upload', rows: '1,204' } },
]

const lineageColumns: Column[] = [
  { key: 'name', label: 'Name', width: '1.4fr' },
  { key: 'step', label: 'Step', width: '1.4fr' },
  { key: 'rows', label: 'Rows', align: 'end', width: '0.8fr' },
]

function Box({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="g-box" aria-label={title}>
      <h2 className="g-title">{title}</h2>
      <div className="g-body">{children}</div>
    </section>
  )
}

export function Gallery() {
  const [sort, setSort] = useState<SortState>(null)
  const [representation, setRepresentation] = useState('decimal')
  const [locale, setLocale] = useState('en')

  const onSort = (key: string) =>
    setSort((prev) => ({ key, direction: prev?.key === key && prev.direction === 'ascending' ? 'descending' : 'ascending' }))
  const rows = [...sampleRows]
  if (sort) {
    const factor = sort.direction === 'ascending' ? 1 : -1
    rows.sort((a, b) => (a.sortValues[sort.key] < b.sortValues[sort.key] ? -1 : a.sortValues[sort.key] > b.sortValues[sort.key] ? 1 : 0) * factor)
  }

  return (
    <main className="g-page">
      <h1 className="g-h1">Instrument components</h1>
      <AlertBar action={<Button>Retry</Button>}>Upload failed: the file is not a valid CSV (PARSE_ERROR).</AlertBar>

      <Box title="Buttons, select, radio">
        <div className="g-row">
          <Button>Run rule</Button>
          <Button disabled>Run rule</Button>
          <Select label="Dataset" defaultValue="sales">
            <option value="sales">sales.csv</option>
            <option value="returns">returns.csv</option>
          </Select>
          <Select label="Dataset" disabled>
            <option>No dataset loaded</option>
          </Select>
        </div>
        <div className="g-row">
          <RadioGroup
            legend="Number representation"
            name="rep"
            value={representation}
            onChange={setRepresentation}
            options={[
              { value: 'decimal', label: 'Decimal' },
              { value: 'scientific', label: 'Scientific' },
            ]}
          />
          <RadioGroup
            legend="Locale"
            name="locale"
            value={locale}
            onChange={setLocale}
            options={[
              { value: 'en', label: 'English' },
              { value: 'de', label: 'German' },
              { value: 'fr', label: 'French' },
            ]}
          />
        </div>
      </Box>

      <Box title="Table with sortable headers (K8) and inspector (K10)">
        <DataTable label="Columns of sales.csv" columns={columns} rows={rows} swatchLabel="Colour" sort={sort} onSort={onSort} />
        <DataTable
          label="Selected column"
          columns={[
            { key: 'name', label: 'Name' },
            { key: 'value', label: 'Value', align: 'end' },
          ]}
          rows={[
            { id: 'i1', cells: { name: 'Type', value: 'float64' } },
            { id: 'i2', cells: { name: 'Nulls', value: '0' } },
            { id: 'i3', cells: { name: 'Minimum', value: '12.50' } },
            { id: 'i4', cells: { name: 'Maximum', value: '98,415.20' } },
            { id: 'i5', cells: { name: 'Mean', value: '4,210.73' } },
          ]}
        />
      </Box>

      <Box title="Tree-table with colour swatches (K9): lineage">
        <TreeTable label="Dataset lineage" columns={lineageColumns} rows={lineage} defaultExpanded={['ds1', 'ds2']} swatchLabel="Colour" />
      </Box>

      <Box title="Sheet, quote strip, editable value (K15-K18)">
        <QuoteStrip
          rows={[
            [
              { label: 'Dataset', value: 'sales_clean' },
              { label: 'Rows', value: '18,102' },
              { label: 'Change', value: '-308', tone: 'down' },
            ],
            [
              { label: 'Columns', value: '9' },
              { label: 'Nulls', value: '243' },
              { label: 'Last run', value: '+12 rows', tone: 'up' },
            ],
          ]}
        />
        <SheetColumns>
          <SheetSection number={1} title="Dataset card">
            <KeyValueList
              rows={[
                { label: 'Rows', value: '18,102' },
                { label: 'Columns', value: '9' },
                { label: 'Source', value: 'sales.csv' },
                { label: 'Sample size', value: <EditableValue label="Sample size" defaultValue="5000" unit="rows" /> },
              ]}
            />
          </SheetSection>
          <SheetSection number={2} title="Cleaning">
            <KeyValueList
              rows={[
                { label: 'drop_duplicates', value: '308 rows' },
                { label: 'fill_nulls', value: '231 cells' },
                { label: 'parse_dates', value: '12 cells' },
              ]}
            />
          </SheetSection>
          <SheetSection number={3} title="Notes">
            <KeyValueList rows={[{ label: 'Owner', value: 'analytics' }, { label: 'Reviewed', value: '2026-10-26' }]} />
          </SheetSection>
        </SheetColumns>
      </Box>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Gallery />
  </StrictMode>,
)
