import { Activity, Boxes, BrainCircuit, FolderKanban, LogOut, Menu, Moon, Sun, UserCog, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth'

const navigation = [
  { to: '/', label: 'Dashboard', icon: Activity },
  { to: '/projects', label: 'Projects', icon: FolderKanban },
  { to: '/analyses', label: 'Analyses', icon: Boxes },
  { to: '/models', label: 'Model Registry', icon: BrainCircuit },
  { to: '/users', label: 'Users & Roles', icon: UserCog },
]

export function AppLayout() {
  const { user, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const [dark, setDark] = useState(() => localStorage.getItem('theme') === 'dark')

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  const initial = user?.display_name ? user.display_name.charAt(0).toUpperCase() : 'U'

  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <img className="sidebar-brand-logo" src="/codesmell-icon.jpeg" alt="CodeSmell" />
          <div><strong>CodeSmell AI</strong><span>Enterprise Quality Platform</span></div>
          <button className="mobile-close" onClick={() => setOpen(false)} aria-label="Close navigation"><X /></button>
        </div>
        <nav>
          {navigation.filter((item) => !['/models', '/users'].includes(item.to) || user?.role === 'admin' || user?.role === 'analyst').map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} onClick={() => setOpen(false)}>
              <Icon size={19} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="version-pill">Final Year Capstone Edition · v3.0</div>
          <p>Explainable multi-language static analysis & AI refactoring engine.</p>
        </div>
      </aside>
      {open && <button className="scrim" onClick={() => setOpen(false)} aria-label="Close navigation" />}
      <div className="main-shell">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu /></button>
          <div className="topbar-title">
            <span>Software Quality Intelligence</span>
            <div className="status-pulse-pill">
              <span className="pulse-dot" />
              <span>AI Worker Active</span>
            </div>
          </div>
          <div className="topbar-user" style={{ cursor: 'pointer' }} onClick={() => setShowProfile(true)}>
            <div className="user-avatar-circle">{initial}</div>
            <span>
              <strong>{user?.display_name}</strong>
              <span className={`role-pill ${user?.role || 'viewer'}`}>{user?.role}</span>
            </span>
            <button className="icon-button" onClick={(e) => { e.stopPropagation(); setDark((value) => !value) }} aria-label="Toggle theme">{dark ? <Sun /> : <Moon />}</button>
            <button className="icon-button" onClick={(e) => { e.stopPropagation(); logout() }} aria-label="Sign out"><LogOut /></button>
          </div>
        </header>
        <main><Outlet /></main>
      </div>

      {/* User Profile & Session Modal */}
      {showProfile && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setShowProfile(false) }}>
          <div className="modal-card glass-card" style={{ maxWidth: '420px', width: '100%', padding: '24px', borderRadius: 'var(--radius-xl)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div className="user-avatar-circle" style={{ width: '44px', height: '44px', fontSize: '1.2rem' }}>{initial}</div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 800 }}>{user?.display_name}</h3>
                  <small style={{ color: 'var(--text-secondary)' }}>{user?.email}</small>
                </div>
              </div>
              <button className="icon-button" onClick={() => setShowProfile(false)}>×</button>
            </div>

            <div style={{ background: 'var(--bg-subtle)', padding: '12px 16px', borderRadius: 'var(--radius-md)', marginBottom: '16px' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>Active Role & Permissions</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className={`role-pill ${user?.role || 'viewer'}`}>{user?.role}</span>
                <span style={{ fontSize: '0.82rem', fontWeight: 600 }}>
                  {user?.role === 'admin' ? 'Full System Governance Access' : user?.role === 'analyst' ? 'Analysis & Model Access' : 'Read-Only Console Access'}
                </span>
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Account ID:</span>
                <code style={{ fontSize: '0.76rem' }}>{user?.id.slice(0, 18)}...</code>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Authentication Mode:</span>
                <strong style={{ color: 'var(--emerald)' }}>JWT Bearer Token</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Account Status:</span>
                <strong style={{ color: 'var(--emerald)' }}>Active & Enabled</strong>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '12px' }}>
              <button className="button button-secondary" style={{ flex: 1 }} onClick={() => setShowProfile(false)}>Close Inspector</button>
              <button className="button button-danger" onClick={logout}><LogOut size={16} /> Sign Out</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}





