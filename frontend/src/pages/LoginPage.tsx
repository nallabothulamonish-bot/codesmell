import { useState, type FormEvent } from 'react'
import { LogIn, UserPlus, Eye, EyeOff, ShieldCheck, UserCheck, Eye as EyeIcon } from 'lucide-react'
import { useAuth } from '../auth'
import { Button, Notice } from '../components/UI'

type Mode = 'login' | 'register'
type Role = 'admin' | 'analyst' | 'viewer'

export function LoginPage() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  
  // Login fields
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  
  // Register fields
  const [displayName, setDisplayName] = useState('')
  const [regEmail, setRegEmail] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [role, setRole] = useState<Role>('admin')

  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') {
        await login(email, password)
      } else {
        await register({
          display_name: displayName,
          email: regEmail,
          password: regPassword,
          role,
        })
      }
    } catch (reason) {
      setError(reason as Error)
    } finally {
      setBusy(false)
    }
  }

  function handlePresetRole(presetEmail: string) {
    setEmail(presetEmail)
    setPassword('SecurePassword123!')
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <img className="login-brand-logo" src="/codesmell-icon.jpeg" alt="CodeSmell" />
        <h1>CodeSmell</h1>
        <p>Software Quality Intelligence Platform</p>

        {/* Mode Tabs: Sign In / Create Account */}
        <div className="auth-mode-tabs">
          <button
            type="button"
            className={`auth-tab ${mode === 'login' ? 'active' : ''}`}
            onClick={() => { setMode('login'); setError(null); }}
          >
            <LogIn size={15} /> Sign In
          </button>
          <button
            type="button"
            className={`auth-tab ${mode === 'register' ? 'active' : ''}`}
            onClick={() => { setMode('register'); setError(null); }}
          >
            <UserPlus size={15} /> Create Account
          </button>
        </div>

        {error && <Notice tone="danger">{error.message}</Notice>}

        {mode === 'login' ? (
          <>
            <label>
              Email
              <input
                type="email"
                autoComplete="username"
                placeholder="admin@codesmell.invalid"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </label>
            <label>
              Password
              <div className="password-toggle">
                <input
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label="Toggle password visibility"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>

            <Button type="submit" disabled={busy}>
              <LogIn size={16} /> {busy ? 'Signing in...' : 'Sign in'}
            </Button>

            {/* Role presets */}
            <div className="role-presets-section">
              <span>Quick Login Options:</span>
              <div className="role-preset-buttons">
                <button
                  type="button"
                  className="role-preset-btn admin"
                  onClick={() => handlePresetRole('admin@codesmell.invalid')}
                >
                  <ShieldCheck size={14} /> Admin
                </button>
                <button
                  type="button"
                  className="role-preset-btn analyst"
                  onClick={() => handlePresetRole('analyst@codesmell.invalid')}
                >
                  <UserCheck size={14} /> Analyst
                </button>
                <button
                  type="button"
                  className="role-preset-btn viewer"
                  onClick={() => handlePresetRole('viewer@codesmell.invalid')}
                >
                  <EyeIcon size={14} /> Viewer
                </button>
              </div>
            </div>
          </>
        ) : (
          <>
            <label>
              Full Name / Display Name
              <input
                type="text"
                placeholder="John Doe"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
            </label>
            <label>
              Email Address
              <input
                type="email"
                autoComplete="username"
                placeholder="user@example.com"
                value={regEmail}
                onChange={(e) => setRegEmail(e.target.value)}
                required
              />
            </label>
            <label>
              Password
              <div className="password-toggle">
                <input
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  minLength={8}
                  placeholder="At least 8 characters"
                  value={regPassword}
                  onChange={(e) => setRegPassword(e.target.value)}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label="Toggle password visibility"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </label>

            {/* Role Selection Options */}
            <div className="role-select-section">
              <label>Select User Role:</label>
              <div className="role-cards-grid">
                <label className={`role-card ${role === 'admin' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="userRole"
                    value="admin"
                    checked={role === 'admin'}
                    onChange={() => setRole('admin')}
                  />
                  <div className="role-card-content">
                    <div className="role-card-header">
                      <ShieldCheck size={16} className="role-icon admin" />
                      <strong>Administrator</strong>
                    </div>
                    <small>Full control: manage projects, models, users & run analyses</small>
                  </div>
                </label>

                <label className={`role-card ${role === 'analyst' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="userRole"
                    value="analyst"
                    checked={role === 'analyst'}
                    onChange={() => setRole('analyst')}
                  />
                  <div className="role-card-content">
                    <div className="role-card-header">
                      <UserCheck size={16} className="role-icon analyst" />
                      <strong>Analyst</strong>
                    </div>
                    <small>Run analyses, trigger jobs & download research reports</small>
                  </div>
                </label>

                <label className={`role-card ${role === 'viewer' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="userRole"
                    value="viewer"
                    checked={role === 'viewer'}
                    onChange={() => setRole('viewer')}
                  />
                  <div className="role-card-content">
                    <div className="role-card-header">
                      <EyeIcon size={16} className="role-icon viewer" />
                      <strong>Viewer</strong>
                    </div>
                    <small>Read-only access to view findings, dashboards & metrics</small>
                  </div>
                </label>
              </div>
            </div>

            <Button type="submit" disabled={busy}>
              <UserPlus size={16} /> {busy ? 'Creating account...' : 'Create Account & Sign In'}
            </Button>
          </>
        )}
      </form>
    </div>
  )
}
