import { useState, type FormEvent } from 'react'
import { LogIn } from 'lucide-react'
import { useAuth } from '../auth'
import { Button, Notice } from '../components/UI'

export function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null)
    try { await login(email, password) } catch (reason) { setError(reason as Error) } finally { setBusy(false) }
  }

  return <div className="login-page">
    <form className="login-card" onSubmit={submit}>
      <img className="login-brand-logo" src="/codesmell-icon.jpeg" alt="CodeSmell" />
      <h1>CodeSmell Research Console</h1>
      <p>Sign in with your administrator, analyst, or viewer account.</p>
      {error && <Notice tone="danger">{error.message}</Notice>}
      <label>Email<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
      <label>Password<input type="password" autoComplete="current-password" minLength={8} title="Use at least 8 characters. Uppercase is optional." value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
      <Button type="submit" disabled={busy}><LogIn size={16} /> {busy ? 'Signing in...' : 'Sign in'}</Button>
    </form>
  </div>
}

