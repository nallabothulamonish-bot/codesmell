import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ShieldCheck, UserPlus, Users, X, Search, Lock, Activity, Sliders } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '../api/endpoints'
import { Button, Card, ErrorState, Loading, Notice, PageHeader, StatusBadge } from '../components/UI'
import { formatDate, titleCase } from '../utils/format'

export function UsersPage() {
  const client = useQueryClient()
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const audit = useQuery({ queryKey: ['audit'], queryFn: api.auditEvents })
  
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [form, setForm] = useState({ email: '', display_name: '', password: '', role: 'viewer', enabled: true })
  
  const [resetModalUser, setResetModalUser] = useState<{ id: string; name: string } | null>(null)
  const [resetPasswordText, setResetPasswordText] = useState('')

  const create = useMutation({
    mutationFn: () => api.createUser(form),
    onSuccess: () => {
      setForm({ email: '', display_name: '', password: '', role: 'viewer', enabled: true })
      void client.invalidateQueries({ queryKey: ['users'] })
      void client.invalidateQueries({ queryKey: ['audit'] })
    }
  })

  const update = useMutation({
    mutationFn: ({ id, enabled, role }: { id: string; enabled?: boolean; role?: string }) =>
      api.updateUser(id, { ...(enabled !== undefined && { enabled }), ...(role !== undefined && { role }) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['users'] })
      void client.invalidateQueries({ queryKey: ['audit'] })
    }
  })

  const resetPassword = useMutation({
    mutationFn: () => {
      if (!resetModalUser) throw new Error('No user selected')
      return api.resetPassword(resetModalUser.id, resetPasswordText)
    },
    onSuccess: () => {
      setResetModalUser(null)
      setResetPasswordText('')
      alert('Password reset successfully!')
      void client.invalidateQueries({ queryKey: ['audit'] })
    }
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    create.mutate()
  }

  if (users.isLoading) return <Loading />
  if (users.error) return <ErrorState error={users.error} />

  const userItems = users.data?.items || []
  const totalUsers = userItems.length
  const adminCount = userItems.filter(u => u.role === 'admin').length
  const analystCount = userItems.filter(u => u.role === 'analyst' || u.role === 'developer').length
  const activeCount = userItems.filter(u => u.enabled).length

  const filteredUsers = userItems.filter(u => {
    const matchesSearch = u.display_name.toLowerCase().includes(search.toLowerCase()) || u.email.toLowerCase().includes(search.toLowerCase())
    const matchesRole = roleFilter === 'all' || u.role === roleFilter
    return matchesSearch && matchesRole
  })

  return (
    <div className="page">
      <PageHeader
        title="Team & Access Control (RBAC)"
        description="Manage organization team members, assign role permissions, and review security audit logs."
      />

      {/* Hero Summary Cards */}
      <div className="stats-hero-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '24px' }}>
        <div className="glass-card" style={{ padding: '20px', borderRadius: 'var(--radius-lg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Total Members</span>
            <Users size={20} color="var(--accent)" />
          </div>
          <div style={{ fontSize: '1.8rem', fontWeight: 900 }}>{totalUsers}</div>
          <small style={{ color: 'var(--emerald)', fontWeight: 600 }}>{activeCount} active user accounts</small>
        </div>

        <div className="glass-card" style={{ padding: '20px', borderRadius: 'var(--radius-lg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Administrators</span>
            <ShieldCheck size={20} color="var(--violet)" />
          </div>
          <div style={{ fontSize: '1.8rem', fontWeight: 900 }}>{adminCount}</div>
          <small style={{ color: 'var(--text-muted)' }}>Full system governance</small>
        </div>

        <div className="glass-card" style={{ padding: '20px', borderRadius: 'var(--radius-lg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Analysts & Devs</span>
            <Sliders size={20} color="var(--sky)" />
          </div>
          <div style={{ fontSize: '1.8rem', fontWeight: 900 }}>{analystCount}</div>
          <small style={{ color: 'var(--sky)', fontWeight: 600 }}>Code ingestion & ML access</small>
        </div>

        <div className="glass-card" style={{ padding: '20px', borderRadius: 'var(--radius-lg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Security Policy</span>
            <Lock size={20} color="var(--emerald)" />
          </div>
          <div style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--emerald)' }}>RBAC Enforced</div>
          <small style={{ color: 'var(--text-muted)' }}>Token JWT Auth active</small>
        </div>
      </div>

      <div className="admin-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: '24px', marginBottom: '24px' }}>
        {/* User Registration Form Card */}
        <Card>
          <h2><UserPlus size={20} /> Add New Team Member</h2>
          <form className="form-grid" onSubmit={submit} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <strong>Full Name</strong>
              <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="e.g. Alex Rivera" required />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <strong>Corporate Email</strong>
              <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="alex@company.com" required />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <strong>Initial Password</strong>
              <input type="password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="••••••••" required />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <strong>Assigned Role</strong>
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="viewer">Viewer (Read-Only Dashboards)</option>
                <option value="analyst">Analyst (Run Rule & ML Analyses)</option>
                <option value="admin">Administrator (Full Control)</option>
              </select>
            </label>
            <div style={{ gridColumn: 'span 2', marginTop: '8px' }}>
              <Button type="submit" disabled={create.isPending}><UserPlus size={16} /> Create User Account</Button>
            </div>
          </form>
          {create.error && <div style={{ marginTop: '12px' }}><Notice tone="danger">{create.error.message}</Notice></div>}
        </Card>

        {/* Role Privileges Permission Matrix */}
        <Card>
          <h2><ShieldCheck size={20} /> Role Privileges Matrix</h2>
          <div style={{ overflowX: 'auto' }}>
            <table className="rbac-table">
              <thead>
                <tr>
                  <th>Permission</th>
                  <th>Admin</th>
                  <th>Analyst</th>
                  <th>Viewer</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>View Dashboards & Reports</td>
                  <td className="rbac-check"><Check size={16} /></td>
                  <td className="rbac-check"><Check size={16} /></td>
                  <td className="rbac-check"><Check size={16} /></td>
                </tr>
                <tr>
                  <td>Upload & Ingest Projects</td>
                  <td className="rbac-check"><Check size={16} /></td>
                  <td className="rbac-check"><Check size={16} /></td>
                  <td className="rbac-cross"><X size={16} /></td>
                </tr>
                <tr>
                  <td>Run Hybrid ML Detections</td>
                  <td className="rbac-check"><Check size={16} /></td>
                  <td className="rbac-check"><Check size={16} /></td>
                  <td className="rbac-cross"><X size={16} /></td>
                </tr>
                <tr>
                  <td>Manage ML Models</td>
                  <td className="rbac-check"><Check size={16} /></td>
                  <td className="rbac-cross"><X size={16} /></td>
                  <td className="rbac-cross"><X size={16} /></td>
                </tr>
                <tr>
                  <td>Manage Users & Roles</td>
                  <td className="rbac-check"><Check size={16} /></td>
                  <td className="rbac-cross"><X size={16} /></td>
                  <td className="rbac-cross"><X size={16} /></td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* Search & Team Directory Table */}
      <div style={{ marginBottom: '24px' }}>
        <Card>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px', marginBottom: '16px' }}>
          <h2 style={{ margin: 0 }}><Users size={20} /> Team Member Directory</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ position: 'relative', width: '240px' }}>
              <Search size={16} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                type="text"
                placeholder="Search team members..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ paddingLeft: '32px', width: '100%' }}
              />
            </div>
            <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
              <option value="all">All Roles</option>
              <option value="admin">Administrators</option>
              <option value="analyst">Analysts</option>
              <option value="viewer">Viewers</option>
            </select>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User Profile</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last Login</th>
                <th>Account Controls</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.length ? filteredUsers.map((user) => (
                <tr key={user.id}>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <div className="user-avatar-circle">
                        {user.display_name ? user.display_name.charAt(0).toUpperCase() : 'U'}
                      </div>
                      <div>
                        <strong>{user.display_name}</strong>
                        <br />
                        <small style={{ color: 'var(--text-secondary)' }}>{user.email}</small>
                      </div>
                    </div>
                  </td>
                  <td>
                    <select
                      value={user.role}
                      onChange={(e) => update.mutate({ id: user.id, role: e.target.value })}
                      style={{ padding: '4px 8px', fontSize: '0.82rem' }}
                    >
                      <option value="admin">Admin</option>
                      <option value="analyst">Analyst</option>
                      <option value="viewer">Viewer</option>
                    </select>
                  </td>
                  <td>
                    <StatusBadge status={user.enabled ? 'enabled' : 'disabled'} />
                  </td>
                  <td>
                    <span style={{ fontSize: '0.82rem' }}>
                      {user.last_login_at ? formatDate(user.last_login_at) : 'Never logged in'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <Button
                        variant={user.enabled ? 'secondary' : 'primary'}
                        onClick={() => update.mutate({ id: user.id, enabled: !user.enabled })}
                      >
                        {user.enabled ? 'Disable Account' : 'Enable Account'}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => setResetModalUser({ id: user.id, name: user.display_name })}
                        title="Reset Password"
                      >
                        <Lock size={15} /> Reset Password
                      </Button>
                    </div>
                  </td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '24px', color: 'var(--text-muted)' }}>
                    No team members found matching search query.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
      </div>

      {/* Security Audit Log Feed */}
      <Card>
        <h2><Activity size={20} /> Security & System Audit Event Timeline</h2>
        {audit.data?.items.length ? (
          <div className="audit-timeline">
            {audit.data.items.slice(0, 10).map((event) => (
              <div className="audit-item" key={event.id}>
                <div className="audit-icon-wrap">
                  <Activity size={16} />
                </div>
                <div className="audit-content">
                  <div className="audit-action">{titleCase(event.action.replace('_', ' '))}</div>
                  <div className="audit-meta">
                    Target Resource: <strong>{event.resource_type}</strong> {event.resource_id ? `· ${event.resource_id}` : ''}
                  </div>
                </div>
                <div className="audit-time">{formatDate(event.created_at)}</div>
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: 'var(--text-muted)' }}>No audit events recorded yet.</p>
        )}
      </Card>

      {/* Password Reset Modal Dialog */}
      {resetModalUser && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(e) => { if (e.target === e.currentTarget) setResetModalUser(null) }}
        >
          <Card className="modal-card">
            <div className="card-heading">
              <div>
                <h2>Reset User Password</h2>
                <p>Account: <strong>{resetModalUser.name}</strong></p>
              </div>
              <button className="icon-button" onClick={() => setResetModalUser(null)}>×</button>
            </div>
            <div className="form-grid" style={{ marginTop: '16px' }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <strong>New Secure Password</strong>
                <input
                  type="password"
                  minLength={8}
                  value={resetPasswordText}
                  onChange={(e) => setResetPasswordText(e.target.value)}
                  placeholder="Enter new password (min 8 chars)..."
                  required
                />
              </label>
            </div>
            {resetPassword.error && (
              <div style={{ marginTop: '12px' }}>
                <Notice tone="danger">{resetPassword.error.message}</Notice>
              </div>
            )}
            <div className="modal-actions" style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '20px' }}>
              <Button variant="secondary" onClick={() => setResetModalUser(null)}>Cancel</Button>
              <Button
                onClick={() => resetPassword.mutate()}
                disabled={resetPassword.isPending || resetPasswordText.length < 8}
              >
                <Lock size={16} /> {resetPassword.isPending ? 'Resetting...' : 'Confirm Reset Password'}
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}

