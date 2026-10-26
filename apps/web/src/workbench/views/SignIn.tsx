// The sign-in form, shown inside the Data pane while there is no session.
//
// Why inside the pane and not a separate screen: the workbench frame (menu, panes, status) stays
// the same before and after sign-in, so nothing jumps; every other pane just keeps its hint
// until there is data. Signup, email verification and password reset are separate screens.
import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { AlertBar, Button } from '../../components/controls.tsx'
import { useWorkbenchData } from '../dataContext.ts'

export function SignIn() {
  const { signIn } = useWorkbenchData()
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const emailId = useId()
  const passwordId = useId()

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setPending(true)
    setError(null)
    try {
      const message = await signIn(String(form.get('email') ?? ''), String(form.get('password') ?? ''))
      if (message) setError(message)
    } catch {
      setError('The server could not be reached.')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="view view-center">
      <form className="sign-in" onSubmit={submit} aria-labelledby={`${emailId}-title`}>
        <h2 id={`${emailId}-title`} className="view-title">
          Sign in
        </h2>
        {error && <AlertBar>{error}</AlertBar>}
        <div className="form-row">
          <label htmlFor={emailId} className="field-label">
            Email
          </label>
          <input id={emailId} className="field" name="email" type="email" autoComplete="username" required />
        </div>
        <div className="form-row">
          <label htmlFor={passwordId} className="field-label">
            Password
          </label>
          <input id={passwordId} className="field" name="password" type="password" autoComplete="current-password" required />
        </div>
        <div className="form-actions">
          <Button type="submit" disabled={pending}>
            {pending ? 'Signing in...' : 'Sign in'}
          </Button>
        </div>
      </form>
    </div>
  )
}
