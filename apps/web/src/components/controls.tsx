// Form controls and the alert bar (C6/B4: plans/phase-4-design-reference.md T5 K5, K6, K19).
//
// Why native elements: <select>, <input type="radio"> and <button> already give keyboard,
// screen-reader and form behaviour for free; this file only gives them the Instrument look (flat,
// blue-grey fills, 16 px high) and a visible name. Nothing here stores state: the owner passes
// the value in and gets changes back.
import { useId } from 'react'
import type { ButtonHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { ChevronDownIcon } from '../workbench/icons.tsx'
import './components.css'

export function Button({ className = '', ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" className={`button ${className}`.trim()} {...rest} />
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string
  // The label stays in the accessibility tree; hide it only where the surrounding UI already shows it.
  hideLabel?: boolean
}

export function Select({ label, hideLabel = false, children, ...rest }: SelectProps) {
  const id = useId()
  return (
    <div className="field-row">
      <label htmlFor={id} className={hideLabel ? 'visually-hidden' : 'field-label'}>
        {label}
      </label>
      <span className="select">
        <select {...rest} id={id}>
          {children}
        </select>
        <span className="select-arrow">
          <ChevronDownIcon />
        </span>
      </span>
    </div>
  )
}

export interface RadioOption {
  value: string
  label: string
}

interface RadioGroupProps {
  // Names the group for assistive technology; C6 shows no visible legend.
  legend: string
  name: string
  value: string
  options: RadioOption[]
  onChange: (value: string) => void
}

export function RadioGroup({ legend, name, value, options, onChange }: RadioGroupProps) {
  return (
    <fieldset className="radio-group">
      <legend className="visually-hidden">{legend}</legend>
      {options.map((option) => (
        <label key={option.value} className="radio">
          <input
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
          />
          <span>{option.label}</span>
        </label>
      ))}
    </fieldset>
  )
}

// One full-width solid bar for a system-level problem; use at most one per window.
export function AlertBar({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="alert-bar" role="alert">
      <span>{children}</span>
      {action}
    </div>
  )
}
