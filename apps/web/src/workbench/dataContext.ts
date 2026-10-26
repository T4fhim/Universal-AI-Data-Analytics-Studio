// The workbench data context: its shape, and the hook the views read it through.
//
// Why a file of its own: the provider (`data.tsx`) is a component, and a file that exports both a
// component and a hook breaks fast refresh. Views import only this file, so they never depend
// on how the data is fetched.
import { createContext, useContext } from 'react'
import type { AuthUser } from '../api/auth.ts'
import type { DatasetOut, SummaryOut } from '../api/client.ts'
import type { Scope, Sort } from '../api/queries.ts'
import type { GridCell } from '../components/grid.tsx'

// 'loading' while the session is read; 'unreachable' when the API did not answer; 'signed-out'
// shows the sign-in form; 'loading-account' while the organization, project and datasets load.
export type Phase = 'loading' | 'unreachable' | 'signed-out' | 'loading-account' | 'ready'

export type UploadState =
  | { status: 'idle' }
  | { status: 'busy'; name: string; step: 'uploading' | 'processing'; progress: number }
  | { status: 'failed'; name: string; message: string }

export const HEADER_CELL: GridCell = { row: -1, col: 0 }

export interface WorkbenchData {
  phase: Phase
  user: AuthUser | null
  signIn: (email: string, password: string) => Promise<string | null>
  signOut: () => Promise<void>
  retry: () => void
  scope: Scope | null
  datasets: DatasetOut[]
  active: DatasetOut | null
  setActiveId: (id: string) => void
  summary: SummaryOut | undefined
  summaryFailed: boolean
  retrySummary: () => void
  // The selected cell of the active dataset (row -1 is the header) and its sort order; both
  // reset when another dataset becomes active.
  cell: GridCell
  setCell: (cell: GridCell) => void
  sort: Sort | null
  toggleSort: (column: string) => void
  upload: UploadState
  // Bumped when an upload finishes: the Data pane then moves focus to the grid if it was lost.
  gridFocusTick: number
  uploadFile: (file: File) => void
  openPicker: () => void
}

export const DataContext = createContext<WorkbenchData | null>(null)

export function useWorkbenchData(): WorkbenchData {
  const value = useContext(DataContext)
  if (!value) throw new Error('useWorkbenchData must be used inside <DataProvider>')
  return value
}
