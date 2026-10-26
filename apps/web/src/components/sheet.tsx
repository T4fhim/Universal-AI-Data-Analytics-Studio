// The B4 sheet idioms inside the C6 grammar (plans/phase-4-design-reference.md T5 K15-K18):
// numbered section bars, key/value rows, a two-row quote strip and the one editable value.
//
// Why dl/dt/dd: a sheet is a list of name-value pairs, which is exactly what a description list
// means, so assistive technology announces each pair without extra ARIA. A <dl> may hold only
// <div> groups of dt/dd (no nesting), so the quote strip is one <dl> per row.
import { useId } from 'react'
import type { ReactNode } from 'react'
import { ChevronDownIcon } from '../workbench/icons.tsx'
import './components.css'

// Three columns in the 30 : 33 : 33 ratio measured on the B4 reference.
export function SheetColumns({ children }: { children: ReactNode }) {
  return <div className="sheet-columns">{children}</div>
}

interface SheetSectionProps {
  title: string
  // B4 numbers its sections ("3) Notes"); the number is part of the heading text.
  number?: number
  children: ReactNode
}

export function SheetSection({ title, number, children }: SheetSectionProps) {
  const id = useId()
  return (
    <section className="sheet-section" aria-labelledby={id}>
      <h3 id={id} className="sheet-bar">
        {number !== undefined && <span className="sheet-number">{number})</span>}
        {title}
      </h3>
      {children}
    </section>
  )
}

export interface KeyValue {
  label: string
  value: ReactNode
}

export function KeyValueList({ rows }: { rows: KeyValue[] }) {
  return (
    <dl className="kv">
      {rows.map((row) => (
        <div key={row.label} className="kv-row">
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </div>
      ))}
    </dl>
  )
}

export interface QuoteItem {
  label: string
  value: string
  // The sign must already be in `value` ("+3.09"); the tone only adds colour and an arrow.
  tone?: 'up' | 'down'
}

export function QuoteStrip({ rows }: { rows: QuoteItem[][] }) {
  return (
    <div className="quote">
      {rows.map((row, index) => (
        <dl key={index} className="quote-row">
          {row.map((item) => (
            <div key={item.label} className={`quote-item${item.tone ? ` quote-${item.tone}` : ''}`}>
              <dt>{item.label}</dt>
              <dd>
                {item.tone && (
                  <span className={`quote-arrow quote-arrow-${item.tone}`}>
                    <ChevronDownIcon />
                  </span>
                )}
                {item.value}
              </dd>
            </div>
          ))}
        </dl>
      ))}
    </div>
  )
}

interface EditableValueProps {
  // Names the input; the visible name is the row's label next to it.
  label: string
  defaultValue: string
  unit?: string
}

// The solid fill marks the one value in a sheet that can be changed (decision 2: amber only here).
export function EditableValue({ label, defaultValue, unit }: EditableValueProps) {
  return (
    <span className="editable-wrap">
      <input className="editable" aria-label={label} defaultValue={defaultValue} />
      {unit && <span className="dim">{unit}</span>}
    </span>
  )
}
