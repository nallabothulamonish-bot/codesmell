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
          <div className="version-pill">Enterprise v3.0 · AI Engine</div>
          <p>Explainable cross-project static analysis & ML prediction.</p>
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
          <div className="topbar-user">
            <div className="user-avatar-circle">{initial}</div>
            <span>
              <strong>{user?.display_name}</strong>
              <span className={`role-pill ${user?.role || 'viewer'}`}>{user?.role}</span>
            </span>
            <button className="icon-button" onClick={() => setDark((value) => !value)} aria-label="Toggle theme">{dark ? <Sun /> : <Moon />}</button>
            <button className="icon-button" onClick={logout} aria-label="Sign out"><LogOut /></button>
          </div>
        </header>
        <main><Outlet /></main>
      </div>
    </div>
  )
}





