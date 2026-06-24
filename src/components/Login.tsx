import { useState, type FormEvent } from 'react'

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      })
      if (response.ok) {
        onSuccess()
        return
      }
      setError('Wrong password.')
    } catch {
      setError('Could not reach the server.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="app-shell login-shell">
      <form className="login-card" onSubmit={submit}>
        <h1>Meta Ad Agent</h1>
        <p>Sign in to view your dashboard.</p>
        <input
          type="password"
          value={password}
          placeholder="Password"
          autoFocus
          onChange={(event) => setPassword(event.target.value)}
        />
        {error && <small className="login-error">{error}</small>}
        <button type="submit" disabled={busy || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
