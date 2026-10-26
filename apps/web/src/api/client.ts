// The typed API client: one openapi-fetch instance over the generated `schema.d.ts`.
//
// Why a thin wrapper and not a hand-written fetch layer: every path, parameter and response
// body is checked against `apps/api/openapi.json` (regenerate with `pnpm gen:api` after the
// contract changes), so a renamed field fails the build instead of the browser.
//
// Auth is the allauth browser client: an HttpOnly session cookie plus a CSRF token the SPA must
// echo on every state-changing request. The token cookie is read fresh on each request because
// login rotates it.
import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schemas = components['schemas']
export type DatasetOut = Schemas['DatasetOut']
export type SummaryOut = Schemas['SummaryOut']
export type ColumnSummary = Schemas['ColumnSummaryOut']
export type PreviewOut = Schemas['PreviewOut']
export type JobOut = Schemas['JobOut']

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : ''
}

// A failed request as the UI needs it: the HTTP status, the API's closed error code and its
// message. The API never puts exception text, paths or row data in an error, so `message` is
// safe to show.
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export const api = createClient<paths>({ baseUrl: window.location.origin })

api.use({
  onRequest({ request }) {
    if (!SAFE_METHODS.has(request.method)) request.headers.set('X-CSRFToken', csrfToken())
    return request
  },
})

function toApiError(status: number, body: unknown): ApiError {
  const error = (body as { error?: { code?: string; message?: string } } | undefined)?.error
  return new ApiError(status, error?.code ?? 'unavailable', error?.message ?? 'The server did not answer as expected.')
}

// Unwraps an openapi-fetch result: the data on success, an ApiError otherwise.
export async function unwrap<T>(result: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await result
  if (error !== undefined || data === undefined) throw toApiError(response.status, error)
  return data
}

// What to tell the user about a failure: the API's own closed message, or a plain network line.
export function messageOf(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'The server could not be reached.'
}
