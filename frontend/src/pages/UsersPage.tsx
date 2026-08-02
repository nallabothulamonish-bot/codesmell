import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Shield, UserPlus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '../api/endpoints'
import { Button, Card, ErrorState, Loading, Notice, PageHeader, StatusBadge } from '../components/UI'
import { formatDate, titleCase } from '../utils/format'

export function UsersPage() {
  const client = useQueryClient()
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })
  const audit = useQuery({ queryKey: ['audit'], queryFn: api.auditEvents })
  const [form, setForm] = useState({ email: '', display_name: '', password: '', role: 'viewer', enabled: true })
  const create = useMutation({ mutationFn: () => api.createUser(form), onSuccess: () => { setForm({ email: '', display_name: '', password: '', role: 'viewer', enabled: true }); void client.invalidateQueries({ queryKey: ['users'] }) } })
  const update = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.updateUser(id, { enabled }), onSuccess: () => void client.invalidateQueries({ queryKey: ['users'] }) })
  function submit(event: FormEvent) { event.preventDefault(); create.mutate() }
  if (users.isLoading) return <Loading />
  if (users.error) return <ErrorState error={users.error} />
  return <div className="page">
    <PageHeader title="Users & Roles" description="Manage administrator, analyst, and viewer access." />
    <div className="admin-grid">
      <Card><h2><UserPlus size={20} /> Create user</h2><form className="form-grid" onSubmit={submit}>
        <label>Name<input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} required /></label>
        <label>Email<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></label>
        <label>Password<input type="password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></label>
        <label>Role<select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option value="viewer">Viewer</option><option value="analyst">Analyst</option><option value="admin">Administrator</option></select></label>
        <Button type="submit" disabled={create.isPending}><UserPlus size={16} /> Create</Button>
      </form>{create.error && <Notice tone="danger">{create.error.message}</Notice>}</Card>
      <Card><h2><Shield size={20} /> Role permissions</h2><ul className="compact-list"><li><strong>Admin:</strong> users, models, projects, analyses, reports.</li><li><strong>Analyst:</strong> projects, analyses, and reports.</li><li><strong>Viewer:</strong> read-only access.</li></ul></Card>
    </div>
    <div className="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last login</th><th></th></tr></thead><tbody>{users.data?.items.map((user) => <tr key={user.id}><td><strong>{user.display_name}</strong><br/><small>{user.email}</small></td><td>{titleCase(user.role)}</td><td><StatusBadge status={user.enabled ? 'enabled' : 'disabled'} /></td><td>{user.last_login_at ? formatDate(user.last_login_at) : 'Never'}</td><td><Button variant="secondary" onClick={() => update.mutate({ id: user.id, enabled: !user.enabled })}>{user.enabled ? 'Disable' : 'Enable'}</Button></td></tr>)}</tbody></table></div>
    <Card><h2>Recent audit events</h2>{audit.data?.items.length ? <div className="audit-list">{audit.data.items.map((event) => <div key={event.id}><code>{event.action}</code><span>{event.resource_type}{event.resource_id ? ` Â· ${event.resource_id}` : ''}</span><time>{formatDate(event.created_at)}</time></div>)}</div> : <p>No audit events recorded yet.</p>}</Card>
  </div>
}

