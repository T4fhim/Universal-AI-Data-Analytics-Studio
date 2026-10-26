// Sign-in against allauth's headless browser client (`/api/auth/browser/v1/...`).
//
// Why hand-written and not generated: these routes belong to allauth, not to the Ninja API, so
// they are not in `openapi.json`. Only what the workbench needs is here: read the session,
// sign in, sign out. Signup, email verification and password reset are separate screens.
//
// `GET /config` is what sets the `csrftoken` cookie, so it runs before anything that writes.
import { ApiError, csrfToken } from './client'

const BASE = '/api/auth/browser/v1'

export interface AuthUser {
  id: string
  email: string
  display: string
}

export type AuthState = { authenticated: true; user: AuthUser } | { authenticated: false }

interface AllauthError {
  message?: string
}

export async function loadSession(): Promise<AuthState> {
  await fetch(`${BASE}/config`, { credentials: 'same-origin' })
  const response = await fetch(`${BASE}/auth/session`, { credentials: 'same-origin' })
  if (response.status === 200) {
    const body = (await response.json()) as { data: { user: AuthUser } }
    return { authenticated: true, user: body.data.user }
  }
  if (response.status === 401) return { authenticated: false }
  throw new ApiError(response.status, 'unavailable', 'The server did not answer as expected.')
}

// Returns null on success, otherwise the sentence to show under the form.
export async function signIn(email: string, password: string): Promise<string | null> {
  const response = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
    body: JSON.stringify({ email, password }),
  })
  if (response.status === 200) return null
  if (response.status === 429) return 'Too many attempts. Wait a few minutes and try again.'
  if (response.status === 400) {
    const body = (await response.json().catch(() => ({}))) as { errors?: AllauthError[] }
    return body.errors?.[0]?.message ?? 'The email address or password is not correct.'
  }
  return 'Sign-in is not available right now.'
}

// True when the server confirmed the session is gone. allauth answers a successful logout with
// 401 (there is no session any more); anything else (a CSRF 403, a network error) means the
// session may still be valid and the caller must not pretend otherwise.
export async function signOut(): Promise<boolean> {
  try {
    const response = await fetch(`${BASE}/auth/session`, {
      method: 'DELETE',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfToken() },
    })
    return response.ok || response.status === 401
  } catch {
    return false
  }
}
