import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, LoaderCircle, XCircle } from 'lucide-react'
import { titleCase } from '../utils/format'

export function Card({ children, className = '' }: PropsWithChildren<{ className?: string }>) {
  return <section className={`card ${className}`}>{children}</section>
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

export function Button({ children, className = '', variant = 'primary', ...props }: PropsWithChildren<ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost' }>) {
  return <button className={`button button-${variant} ${className}`} {...props}>{children}</button>
}

export function Badge({ children, tone = 'neutral' }: PropsWithChildren<{ tone?: string }>) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === 'succeeded' || status === 'completed' || status === 'enabled' ? 'success' : status === 'failed' || status === 'critical' ? 'danger' : status === 'running' || status === 'high' ? 'warning' : status === 'queued' || status === 'medium' ? 'info' : 'neutral'
  return <Badge tone={tone}>{titleCase(status)}</Badge>
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={severity}>{titleCase(severity)}</Badge>
}

export function EmptyState({ title, message, action }: { title: string; message: string; action?: ReactNode }) {
  return (
    <Card className="empty-state">
      <div className="empty-icon">◇</div>
      <h3>{title}</h3>
      <p>{message}</p>
      {action}
    </Card>
  )
}

export function Loading({ label = 'Loading data…' }: { label?: string }) {
  return <div className="state-message"><LoaderCircle className="spin" size={20} /> {label}</div>
}

export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : 'An unexpected error occurred.'
  return <div className="alert alert-danger"><XCircle size={18} /> <span>{message}</span></div>
}

export function Notice({ tone = 'info', children }: PropsWithChildren<{ tone?: 'info' | 'success' | 'warning' | 'danger' }>) {
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'warning' ? AlertTriangle : tone === 'danger' ? XCircle : AlertTriangle
  return <div className={`alert alert-${tone}`}><Icon size={18} /><span>{children}</span></div>
}

export function StatCard({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: string; icon?: ReactNode }) {
  return (
    <Card className="stat-card">
      <div className="stat-icon">{icon}</div>
      <div>
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value}</div>
        {hint && <div className="stat-hint">{hint}</div>}
      </div>
    </Card>
  )
}

export function ProgressBar({ value }: { value: number }) {
  const safe = Math.max(0, Math.min(100, value))
  return <div className="progress-track" aria-label={`${safe}% complete`}><span style={{ width: `${safe}%` }} /></div>
}

export function Tabs({ items, active, onChange }: { items: Array<{ id: string; label: string; count?: number }>; active: string; onChange: (id: string) => void }) {
  return <div className="tabs" role="tablist">{items.map((item) => <button key={item.id} className={active === item.id ? 'active' : ''} onClick={() => onChange(item.id)}>{item.label}{item.count !== undefined && <span>{item.count}</span>}</button>)}</div>
}
