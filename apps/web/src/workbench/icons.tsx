// Small drawn icons for pane controls (one stroke weight, currentColor).
//
// Why SVG and not Unicode glyphs: the design rules this theme follows refuse glyphs standing in
// for an icon system. All icons are decorative (aria-hidden); the buttons that use them carry
// their own accessible names.
const common = {
  width: 10,
  height: 10,
  viewBox: '0 0 10 10',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.25,
  'aria-hidden': true,
  focusable: false,
} as const

export function ChevronDownIcon() {
  return (
    <svg {...common}>
      <path d="M2 3.5 5 6.5 8 3.5" />
    </svg>
  )
}

export function ChevronRightIcon() {
  return (
    <svg {...common}>
      <path d="M3.5 2 6.5 5 3.5 8" />
    </svg>
  )
}

export function MaximiseIcon() {
  return (
    <svg {...common}>
      <rect x="1.75" y="1.75" width="6.5" height="6.5" />
    </svg>
  )
}

export function RestoreIcon() {
  return (
    <svg {...common}>
      <rect x="1.75" y="3.25" width="5" height="5" />
      <path d="M3.5 3.25V1.75H8.25V6.5H6.75" />
    </svg>
  )
}

export function DotIcon() {
  return (
    <svg {...common} width={8} height={8} viewBox="0 0 8 8">
      <circle cx="4" cy="4" r="1.75" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function CheckIcon() {
  return (
    <svg {...common} width={8} height={8} viewBox="0 0 8 8">
      <path d="M1.25 4.25 3.25 6.25 6.75 1.75" />
    </svg>
  )
}
