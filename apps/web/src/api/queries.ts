// Server state for the workbench: fetchers, query keys and hooks (TanStack Query).
//
// Why these keys carry the whole scope (organization, project, dataset, sort, page): the cache
// must never answer for another tenant or another sort order. Datasets are immutable once
// ingested (a cleaning step creates a *new* dataset), so summaries and preview pages never go
// stale and are kept for good (`staleTime: Infinity`); only the dataset list is refetched.
import { queryOptions, skipToken, useQueries, useQuery } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { api, ApiError, unwrap } from './client'
import type { DatasetOut, JobOut } from './client'
import { loadSession } from './auth'
import type { AuthState } from './auth'

// The API caps a preview page at 200 rows: use all of it, so scrolling costs as few requests as
// possible (preview and summary share a 120/min budget).
export const PAGE_SIZE = 200

// The API rejects a preview offset above 1,000,000 (apps/api web/config.py max_offset), so the
// last page a client can ask for starts there: rows past this count cannot be paged to.
export const MAX_PREVIEW_ROWS = 1_000_000 + PAGE_SIZE

export interface Scope {
  orgId: string
  projectId: string
}

export interface Sort {
  column: string
  descending: boolean
}

const path = (scope: Scope) => ({ org_id: scope.orgId, project_id: scope.projectId })

export const keys = {
  session: ['session'] as const,
  me: ['me'] as const,
  projects: (orgId: string | null) => ['projects', orgId] as const,
  datasets: (scope: Scope) => ['datasets', scope.orgId, scope.projectId] as const,
  summary: (scope: Scope, datasetId: string) => ['summary', scope.orgId, scope.projectId, datasetId] as const,
  preview: (scope: Scope, datasetId: string, sort: Sort | null, page: number) =>
    ['preview', scope.orgId, scope.projectId, datasetId, sort?.column ?? null, sort?.descending ?? false, page] as const,
}

// Tenant data must not outlive the session it was fetched under: everything but the session
// itself is dropped on sign-in, sign-out and when the server says the session has ended.
export function dropTenantData(client: QueryClient) {
  client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'session' })
}

export function expireSession(client: QueryClient) {
  dropTenantData(client)
  client.setQueryData<AuthState>(keys.session, { authenticated: false })
}

export const sessionQuery = queryOptions({ queryKey: keys.session, queryFn: loadSession, staleTime: Infinity, retry: false })

export const meQuery = queryOptions({
  queryKey: keys.me,
  queryFn: () => unwrap(api.GET('/api/me')),
  staleTime: 5 * 60_000,
})

export const projectsQuery = (orgId: string | null) =>
  queryOptions({
    queryKey: keys.projects(orgId),
    queryFn: orgId ? () => unwrap(api.GET('/api/organizations/{org_id}/projects', { params: { path: { org_id: orgId } } })) : skipToken,
  })

export function createProject(orgId: string, name: string) {
  return unwrap(api.POST('/api/organizations/{org_id}/projects', { params: { path: { org_id: orgId } }, body: { name } }))
}

export const datasetsQuery = (scope: Scope | null) =>
  queryOptions({
    queryKey: scope ? keys.datasets(scope) : ['datasets', null],
    queryFn: scope
      ? () => unwrap(api.GET('/api/organizations/{org_id}/projects/{project_id}/datasets', { params: { path: path(scope), query: { limit: 200 } } }))
      : skipToken,
  })

export function useSummary(scope: Scope | null, datasetId: string | null) {
  return useQuery({
    queryKey: scope && datasetId ? keys.summary(scope, datasetId) : ['summary', null],
    queryFn:
      scope && datasetId
        ? () =>
            unwrap(
              api.GET('/api/organizations/{org_id}/projects/{project_id}/datasets/{dataset_id}/summary', {
                params: { path: { ...path(scope), dataset_id: datasetId } },
              }),
            )
        : skipToken,
    staleTime: Infinity,
  })
}

function fetchPreview(scope: Scope, datasetId: string, sort: Sort | null, page: number) {
  return unwrap(
    api.GET('/api/organizations/{org_id}/projects/{project_id}/datasets/{dataset_id}/preview', {
      params: {
        path: { ...path(scope), dataset_id: datasetId },
        query: { offset: page * PAGE_SIZE, limit: PAGE_SIZE, sort: sort?.column, descending: sort?.descending ?? false },
      },
    }),
  )
}

// One query per requested page. The grid asks for the pages under its viewport; the inspector
// asks for the page holding the selected row, which is usually already cached by the grid.
export function usePreviewPages(scope: Scope | null, datasetId: string | null, sort: Sort | null, pages: number[]) {
  return useQueries({
    queries: pages.map((page) => ({
      queryKey: scope && datasetId ? keys.preview(scope, datasetId, sort, page) : ['preview', null, page],
      queryFn: scope && datasetId ? () => fetchPreview(scope, datasetId, sort, page) : skipToken,
      staleTime: Infinity,
    })),
  })
}

// crypto.randomUUID exists only in secure contexts (https or localhost); getRandomValues works
// everywhere. The API accepts 1-56 characters of A-Za-z0-9._:- .
function idempotencyKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export function uploadFile(scope: Scope, file: File) {
  return unwrap(
    api.POST('/api/organizations/{org_id}/projects/{project_id}/datasets/upload', {
      params: { path: path(scope), header: { 'Idempotency-Key': idempotencyKey() } },
      // The generated type calls the binary part a string; the serializer sends the real File.
      body: { file: file as unknown as string },
      bodySerializer: () => {
        const form = new FormData()
        form.append('file', file)
        return form
      },
    }),
  )
}

function fetchJob(scope: Scope, jobId: string) {
  return unwrap(
    api.GET('/api/organizations/{org_id}/projects/{project_id}/jobs/{job_id}', { params: { path: { ...path(scope), job_id: jobId } } }),
  )
}

const POLL_FIRST_MS = 500
const POLL_MAX_MS = 2000
const POLL_BUDGET_MS = 10 * 60_000

// Polls an ingest job until it ends. A failed or cancelled job becomes an ApiError carrying the
// job's own error message (a closed sentence, never exception text).
export async function waitForJob(scope: Scope, jobId: string, onProgress: (job: JobOut) => void): Promise<JobOut> {
  const started = Date.now()
  let delay = POLL_FIRST_MS
  for (;;) {
    const job = await fetchJob(scope, jobId)
    onProgress(job)
    if (job.status === 'succeeded') return job
    if (job.status === 'failed' || job.status === 'cancelled' || job.status === 'canceled') {
      throw new ApiError(409, 'conflict', job.error_message || 'The file could not be read.')
    }
    if (Date.now() - started > POLL_BUDGET_MS) throw new ApiError(503, 'unavailable', 'Processing is taking too long.')
    await new Promise((resolve) => setTimeout(resolve, delay))
    delay = Math.min(POLL_MAX_MS, Math.round(delay * 1.5))
  }
}

export type { DatasetOut }
