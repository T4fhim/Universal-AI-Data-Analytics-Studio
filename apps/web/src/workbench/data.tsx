// The data provider: session, account scope, datasets, selection and upload, in one place.
//
// What it decides (plans/phase-4-design-reference.md step 5): the signed-in user works in their
// first organization and its first project. There is no organization or project picker yet; the
// first upload creates "Untitled project" when the account has none, so a new user never meets a
// "create a project" form before they have any data.
//
// Why selection and sort are stored *with the dataset id* and not reset by an effect: when
// another dataset becomes active the stored id no longer matches and the defaults apply, with no
// setState-in-effect and no stale row index from the previous dataset.
//
// Upload is a small state machine (idle, busy, failed). While one runs, a second is ignored: the
// API throttles uploads, and two at once would race on creating the first project.
import { useCallback, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import filters from '../../../../assets/ui-contract/file-picker-filters.json'
import { signIn as signInRequest, signOut as signOutRequest } from '../api/auth.ts'
import { ApiError, messageOf } from '../api/client.ts'
import { createProject, datasetsQuery, dropTenantData, expireSession, keys, meQuery, projectsQuery, sessionQuery, uploadFile as uploadRequest, useSummary, waitForJob } from '../api/queries.ts'
import type { Scope, Sort } from '../api/queries.ts'
import type { GridCell } from '../components/grid.tsx'
import { DataContext, HEADER_CELL } from './dataContext.ts'
import type { Phase, UploadState, WorkbenchData } from './dataContext.ts'

// The same extension list the old desktop file dialog used (assets/ui-contract), so the picker
// offers what the server's admission table accepts.
const ACCEPT = filters.dataset_open.groups[0].patterns.map((pattern) => pattern.replace('*', '')).join(',')

interface Keyed<T> {
  datasetId: string
  value: T
}

function nextSort(current: Sort | null, column: string): Sort | null {
  if (!current || current.column !== column) return { column, descending: false }
  return current.descending ? null : { column, descending: true }
}

export function DataProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const uploading = useRef(false)
  // Bumped by sign-out and session expiry: an upload that started before then must not touch state.
  const epoch = useRef(0)
  const [upload, setUpload] = useState<UploadState>({ status: 'idle' })
  const [notice, setNotice] = useState({ text: '', n: 0 })
  const [gridFocusTick, setGridFocusTick] = useState(0)
  // One polite message per event; the counter makes a repeated sentence announce again.
  const notify = useCallback((text: string) => setNotice((prev) => ({ text, n: prev.n + 1 })), [])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [cellState, setCellState] = useState<Keyed<GridCell> | null>(null)
  const [sortState, setSortState] = useState<Keyed<Sort | null> | null>(null)

  const session = useQuery(sessionQuery)
  const authed = session.data?.authenticated === true
  const me = useQuery({ ...meQuery, enabled: authed })
  const orgId = authed ? (me.data?.memberships[0]?.organization.id ?? null) : null
  const projects = useQuery(projectsQuery(orgId))
  const projectId = projects.data?.items[0]?.id ?? null
  const scope = useMemo<Scope | null>(() => (orgId && projectId ? { orgId, projectId } : null), [orgId, projectId])
  const datasetList = useQuery(datasetsQuery(scope))
  const datasets = useMemo(() => datasetList.data?.items ?? [], [datasetList.data])
  const active = datasets.find((d) => d.id === activeId) ?? datasets[0] ?? null
  const summary = useSummary(scope, active?.id ?? null)

  const cell = cellState && cellState.datasetId === active?.id ? cellState.value : HEADER_CELL
  const sort = sortState && sortState.datasetId === active?.id ? sortState.value : null

  let phase: Phase
  if (session.isPending) phase = 'loading'
  else if (session.isError || me.isError || projects.isError || datasetList.isError) phase = 'unreachable'
  else if (!authed) phase = 'signed-out'
  else if (me.isPending || (orgId !== null && projects.isPending) || (scope !== null && datasetList.isPending)) phase = 'loading-account'
  else phase = 'ready'

  const startUpload = useCallback(
    async (file: File) => {
      if (uploading.current) return
      uploading.current = true
      const mine = epoch.current
      const ended = () => mine !== epoch.current
      const name = file.name
      setUpload({ status: 'busy', name, step: 'uploading', progress: 0 })
      notify(`Uploading ${name}`)
      try {
        if (!orgId) throw new Error('no organization')
        let target = scope
        if (!target) {
          const created = await createProject(orgId, 'Untitled project')
          await queryClient.invalidateQueries({ queryKey: keys.projects(orgId) })
          target = { orgId, projectId: created.id }
        }
        const accepted = await uploadRequest(target, file)
        if (ended()) return
        setUpload({ status: 'busy', name, step: 'processing', progress: 0 })
        await waitForJob(target, accepted.job_id, (job) => setUpload({ status: 'busy', name, step: 'processing', progress: job.progress }))
        await queryClient.invalidateQueries({ queryKey: keys.datasets(target) })
        if (ended()) return
        setActiveId(accepted.dataset_id)
        setUpload({ status: 'idle' })
        notify(`${name} is ready`)
        setGridFocusTick((tick) => tick + 1)
      } catch (error) {
        if (ended()) return
        if (error instanceof ApiError && error.status === 401) {
          epoch.current += 1
          expireSession(queryClient)
          setUpload({ status: 'idle' })
          return
        }
        const message = orgId ? messageOf(error) : 'Your account has no organization to upload into.'
        setUpload({ status: 'failed', name, message })
      } finally {
        uploading.current = false
      }
    },
    [orgId, scope, queryClient, notify],
  )

  const value: WorkbenchData = {
    phase,
    user: session.data?.authenticated ? session.data.user : null,
    signIn: async (email, password) => {
      const error = await signInRequest(email, password)
      if (!error) {
        dropTenantData(queryClient) // nothing fetched for a previous account may be shown to this one
        await queryClient.invalidateQueries({ queryKey: keys.session })
        notify('Signed in')
        // The form is about to go away: keep focus in the Data pane rather than let it fall to the page.
        document.getElementById('pane-data')?.focus()
      }
      return error
    },
    signOut: async () => {
      if (!(await signOutRequest())) {
        notify('Sign-out was not confirmed by the server. You are still signed in.')
        return
      }
      document.getElementById('pane-data')?.focus() // the Sign out button is about to unmount
      epoch.current += 1
      expireSession(queryClient)
      setActiveId(null)
      setUpload({ status: 'idle' })
      notify('Signed out')
    },
    retry: () => void queryClient.invalidateQueries(),
    scope,
    datasets,
    active,
    setActiveId,
    summary: summary.data,
    summaryFailed: summary.isError,
    retrySummary: () => void summary.refetch(),
    cell,
    setCell: (next) => active && setCellState({ datasetId: active.id, value: next }),
    sort,
    toggleSort: (column) => {
      if (!active) return
      const next = nextSort(sort, column)
      setSortState({ datasetId: active.id, value: next })
      notify(next ? `Sorted by ${column}, ${next.descending ? 'descending' : 'ascending'}` : 'Sort cleared')
    },
    upload,
    gridFocusTick,
    uploadFile: (file) => void startUpload(file),
    openPicker: () => inputRef.current?.click(),
  }

  const onPicked = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = '' // so choosing the same file again fires change again
    if (file) void startUpload(file)
  }

  return (
    <DataContext value={value}>
      {children}
      <input ref={inputRef} type="file" accept={ACCEPT} hidden tabIndex={-1} onChange={onPicked} />
      <div className="visually-hidden" role="status">
        <span key={notice.n}>{notice.text}</span>
      </div>
    </DataContext>
  )
}
