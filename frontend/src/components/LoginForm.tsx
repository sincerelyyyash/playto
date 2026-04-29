import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { getApiErrorMessage } from '../utils/errors'

export function LoginForm() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setPending(true)
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(getApiErrorMessage(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="app-shell mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <div className="surface p-8">
        <h1 className="text-2xl font-semibold text-slate-100">Playto Payout Engine</h1>
        <p className="mt-2 text-sm text-slate-400">
          Sign in with seeded merchant creds, for example user{' '}
          <code className="rounded bg-slate-800 px-1 text-slate-200">alice</code> and pass{' '}
          <code className="rounded bg-slate-800 px-1 text-slate-200">alice</code> after seeding.
        </p>
        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-slate-300">
              Username
            </label>
            <input
              id="username"
              name="username"
              autoComplete="username"
              className="mono-input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-slate-300">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              className="mono-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error ? (
            <p className="rounded-md border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-300" role="alert">
              {error}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={pending}
            className="mono-button w-full py-2.5"
          >
            {pending ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  )
}
