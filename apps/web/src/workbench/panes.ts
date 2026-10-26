// Pane and area definitions for the Instrument workbench.
//
// Why a data file: the layout (C6's dock, plans/phase-4-design-reference.md T2) and the five
// areas (decision 3: views opened from the View menu and keys 1-5, not a separate nav control)
// are *configuration*. Keeping them here lets Workbench.tsx stay a thin wiring layer and keeps
// the proportions measured on the reference in one reviewable place.
export type PaneId = 'data' | 'inspector' | 'rules' | 'profile' | 'schema'
export type AreaId = 'data' | 'clean' | 'analyze' | 'visualize' | 'report'

interface TabDef {
  id: string
  label: string
  hint: string
}

export interface PaneDef {
  id: PaneId
  title: string
  // Collapsing shrinks a pane to a strip: in a stacked (vertical) group that is its height,
  // in a side-by-side (horizontal) group it is its width.
  collapses: 'height' | 'width'
  tabs: TabDef[]
}

export const PANES: Record<PaneId, PaneDef> = {
  data: {
    id: 'data',
    title: 'Data',
    collapses: 'width',
    tabs: [
      {
        id: 'grid',
        label: 'Data grid',
        hint: 'No dataset loaded. Upload a CSV to preview its rows here.',
      },
    ],
  },
  inspector: {
    id: 'inspector',
    title: 'Inspector',
    collapses: 'width',
    tabs: [
      {
        id: 'inspector',
        label: 'Inspector',
        hint: 'Select a cell or a column to see its type, missing values, minimum and maximum.',
      },
    ],
  },
  rules: {
    id: 'rules',
    title: 'Rules and report',
    collapses: 'height',
    tabs: [
      {
        id: 'rule-editor',
        label: 'Rule editor',
        hint: 'Cleaning rules and stage parameters appear here, one numbered line per rule.',
      },
      {
        id: 'report',
        label: 'Report',
        hint: 'Result details and export options appear here.',
      },
    ],
  },
  profile: {
    id: 'profile',
    title: 'Profile and chart',
    collapses: 'height',
    tabs: [
      {
        id: 'profile',
        label: 'Profile',
        hint: 'Upload a file to see how complete each column is.',
      },
      {
        id: 'chart',
        label: 'Chart',
        hint: 'Charts you build appear here. This pane fills the window when you open the Visualize area.',
      },
    ],
  },
  schema: {
    id: 'schema',
    title: 'Schema and lineage',
    collapses: 'height',
    tabs: [
      {
        id: 'schema',
        label: 'Schema',
        hint: 'Column names, types and positions appear here once a dataset is loaded.',
      },
      {
        id: 'lineage',
        label: 'Lineage',
        hint: 'Every dataset derived from another is listed here, with the step that produced it.',
      },
    ],
  },
}

// Order used by F6 / Shift+F6 to move focus between panes. It matches the DOM (and so Tab)
// order of the dock: data, inspector and schema are the left group, rules and profile the right.
export const PANE_ORDER: PaneId[] = ['data', 'inspector', 'schema', 'rules', 'profile']

export interface AreaDef {
  id: AreaId
  label: string
  key: string
  // Panes that must be visible (expanded, not maximised) when the area opens.
  reveal: PaneId[]
  focus: PaneId
  tab?: { pane: PaneId; tab: string }
  maximise?: PaneId
}

export const AREAS: AreaDef[] = [
  { id: 'data', label: 'Data', key: '1', reveal: ['data', 'schema'], focus: 'data', tab: { pane: 'schema', tab: 'schema' } },
  { id: 'clean', label: 'Clean', key: '2', reveal: ['rules', 'inspector'], focus: 'rules', tab: { pane: 'rules', tab: 'rule-editor' } },
  { id: 'analyze', label: 'Analyze', key: '3', reveal: ['inspector', 'profile'], focus: 'profile', tab: { pane: 'profile', tab: 'profile' } },
  { id: 'visualize', label: 'Visualize', key: '4', reveal: ['profile'], focus: 'profile', tab: { pane: 'profile', tab: 'chart' }, maximise: 'profile' },
  { id: 'report', label: 'Report', key: '5', reveal: ['rules'], focus: 'rules', tab: { pane: 'rules', tab: 'report' } },
]

// Default proportions from the C6 reference (T2, measured 43.6 / 24.7 / 31.1 % columns, the two
// left columns 69 / 31 % over the bottom pane, the right column 50 / 50). The left group takes
// 68.9 % of the width and the data / inspector columns split it 63.9 / 36.1 %, which renders as
// about 44.0 / 24.9 / 31.1 %: within half a point of the measurement.
export const DEFAULT_SIZES = {
  main: { left: '68.9%', right: '31.1%' },
  left: { top: '69%', bottom: '31%' },
  top: { data: '63.9%', inspector: '36.1%' },
  right: { rules: '50%', profile: '50%' },
} as const

export const GROUP_IDS = {
  main: 'uadas-dock-main',
  left: 'uadas-dock-left',
  top: 'uadas-dock-top',
  right: 'uadas-dock-right',
} as const

export const STORAGE_PREFIX = 'uadas-dock-'
