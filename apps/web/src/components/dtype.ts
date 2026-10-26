// Column data types as the UI shows them: a region colour and a plain-word kind.
//
// Why both: the colour is the C6 "region" idea (a type owns a fill, plans/phase-4-design-reference.md
// K11), and the kind is the same fact in words, because colour must never be the only channel.
// The API reports Arrow-style names ("int64", "double", "string", "bool", "date32[day]",
// "timestamp[us]", ...); anything not recognised is "other" and grey rather than guessed.
export type Region = 'blue' | 'green' | 'purple' | 'orange' | 'grey'
export type Kind = 'number' | 'text' | 'boolean' | 'date or time' | 'other'

export function dtypeKind(dtype: string): Kind {
  const t = dtype.toLowerCase()
  if (/^(u?int\d*|float\d*|double|decimal.*|halffloat)$/.test(t)) return 'number'
  if (/^(large_)?(string|utf8)$/.test(t)) return 'text'
  if (t === 'bool' || t === 'boolean') return 'boolean'
  if (/^(date|time|timestamp|duration)/.test(t)) return 'date or time'
  return 'other'
}

const REGION_OF_KIND: Record<Kind, Region> = {
  number: 'blue',
  text: 'green',
  boolean: 'purple',
  'date or time': 'orange',
  other: 'grey',
}

export function dtypeRegion(dtype: string): Region {
  return REGION_OF_KIND[dtypeKind(dtype)]
}

// A CSS colour for swatches: the region's key colour from the generated tokens.
export function regionColour(region: Region): string {
  return `var(--region-${region})`
}
