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
  const [dark, setDark] = useState(() => localStorage.getItem('theme') !== 'light')

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <div className="app-shell">
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <img className="sidebar-brand-logo" src="/codesmell-icon.jpeg" alt="CodeSmell" />
          <div><strong>CodeSmell</strong><span>Research Console</span></div>
          <button className="mobile-close" onClick={() => setOpen(false)} aria-label="Close navigation"><X /></button>
        </div>
        <nav>
          {navigation.filter((item) => !['/models', '/users'].includes(item.to) || user?.role === 'admin').map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === '/'} onClick={() => setOpen(false)}>
              <Icon size={19} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="version-pill">M9 Â· v0.7.0</div>
          <p>Explainable cross-project static analysis.</p>
        </div>
      </aside>
      {open && <button className="scrim" onClick={() => setOpen(false)} aria-label="Close navigation" />}
      <div className="main-shell">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setOpen(true)} aria-label="Open navigation"><Menu /></button>
          <div className="topbar-title">Software Quality Intelligence</div>
          <div className="topbar-user"><span><strong>{user?.display_name}</strong><small>{user?.role}</small></span><button className="icon-button" onClick={() => setDark((value) => !value)} aria-label="Toggle theme">{dark ? <Sun /> : <Moon />}</button><button className="icon-button" onClick={logout} aria-label="Sign out"><LogOut /></button></div>
        </header>
        <main><Outlet /></main>
      </div>
    </div>
  )
}




