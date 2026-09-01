import { useQueries, useQuery } from '@tanstack/react-query'
import { AlertTriangle, BrainCircuit, CheckCircle2, FolderKanban, Gauge } from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Link } from 'react-router-dom'
import { api } from '../api/endpoints'
import { Card, EmptyState, ErrorState, Loading, PageHeader, StatCard, StatusBadge } from '../components/UI'
import type { Analysis, Finding } from '../types/api'
import { formatDate, titleCase } from '../utils/format'

function countBy<T>(items: T[], key: (item: T) => string) {
  return Object.entries(items.reduce<Record<string, number>>((acc, item) => {
    const value = key(item)
    acc[value] = (acc[value] ?? 0) + 1
    return acc
  }, {})).map(([name, value]) => ({ name: titleCase(name), value }))
}

export function DashboardPage() {
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api.projects() })
  const analyses = useQuery({ queryKey: ['analyses'], queryFn: () => api.analyses() , refetchInterval: 5000})
  const models = useQuery({ queryKey: ['models'], queryFn: () => api.models() })

  const completed = (analyses.data?.items ?? []).filter((item) => ['succeeded', 'completed'].includes(item.status))
  const recentCompleted = completed.slice(0, 5)
  const findingQueries = useQueries({
    queries: recentCompleted.map((job) => ({
      queryKey: ['findings', job.id, 'dashboard'],
      queryFn: () => api.findings(job.id),
      staleTime: 30_000,
    })),
  })
  const findings = findingQueries.flatMap((query) => query.data?.items ?? [])

  if (projects.isLoading || analyses.isLoading || models.isLoading) return <Loading />
  if (projects.error || analyses.error || models.error) return <ErrorState error={projects.error ?? analyses.error ?? models.error} />

  const jobs = analyses.data?.items ?? []
  const active = jobs.filter((item) => ['queued', 'running'].includes(item.status)).length
  const severityData = countBy(findings, (finding: Finding) => finding.severity)
  const smellData = countBy(findings, (finding: Finding) => finding.smell_type).sort((a, b) => b.value - a.value).slice(0, 6)

  return (
    <div className="page">
      <PageHeader title="Research Dashboard" description="Monitor projects, analysis jobs, rule findings, and registered ML models from one console." actions={<Link className="button button-primary" to="/projects">New analysis</Link>} />

      <div className="stats-grid">
        <StatCard label="Projects" value={projects.data?.total ?? 0} hint="Registered source packages" icon={<FolderKanban />} />
        <StatCard label="Completed analyses" value={completed.length} hint={`${active} currently active`} icon={<CheckCircle2 />} />
        <StatCard label="Recent findings" value={findings.length} hint="Across the latest completed jobs" icon={<AlertTriangle />} />
        <StatCard label="Enabled models" value={(models.data?.items ?? []).filter((item) => item.enabled).length} hint={`${models.data?.total ?? 0} registered artifacts`} icon={<BrainCircuit />} />
      </div>

      <div className="dashboard-grid">
        <Card>
          <div className="card-heading"><div><h2>Severity distribution</h2><p>Rule-based findings from recent completed analyses.</p></div></div>
          {severityData.length ? (
            <div className="chart-wrap">
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie data={severityData} dataKey="value" nameKey="name" innerRadius={58} outerRadius={92} paddingAngle={3}>
                    {severityData.map((entry, index) => {
                      const SEVERITY_FILL: Record<string, string> = { Low: '#0ea5e9', Medium: '#f59e0b', High: '#f97316', Critical: '#f43f5e' }
                      const FALLBACK = ['#10b981', '#f59e0b', '#f43f5e', '#6366f1', '#0ea5e9', '#8b5cf6']
                      return <Cell key={index} fill={SEVERITY_FILL[entry.name] ?? FALLBACK[index % FALLBACK.length]} />
                    })}
                  </Pie>
                  <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, color: 'var(--text)' }} />
                </PieChart>
              </ResponsiveContainer>
              <div className="chart-legend">{severityData.map((item, index) => {
                const SEVERITY_FILL: Record<string, string> = { Low: '#0ea5e9', Medium: '#f59e0b', High: '#f97316', Critical: '#f43f5e' }
                const FALLBACK = ['#10b981', '#f59e0b', '#f43f5e', '#6366f1', '#0ea5e9', '#8b5cf6']
                const color = SEVERITY_FILL[item.name] ?? FALLBACK[index % FALLBACK.length]
                return <div key={item.name}><span className="legend-dot" style={{ background: color }} />{item.name}<strong>{item.value}</strong></div>
              })}</div>
            </div>
          ) : <EmptyState title="No findings yet" message="Complete an analysis to populate the severity chart." />}
        </Card>

        <Card>
          <div className="card-heading"><div><h2>Top smell types</h2><p>Most frequent detections in the recent sample.</p></div><Gauge /></div>
          {smellData.length ? <div className="rank-list">{smellData.map((item, index) => {
            const max = smellData[0]?.value || 1
            const COLORS = ['#6366f1', '#8b5cf6', '#0ea5e9', '#10b981', '#f59e0b', '#f97316']
            return <div className="rank-row" key={item.name}><div><span>{index + 1}</span><strong>{item.name}</strong><em>{item.value}</em></div><div className="mini-bar"><i style={{ width: `${(item.value / max) * 100}%`, background: COLORS[index % COLORS.length] }} /></div></div>
          })}</div> : <EmptyState title="No smell ranking" message="The ranking appears after a completed rule or hybrid analysis." />}
        </Card>
      </div>

      <Card>
        <div className="card-heading"><div><h2>Recent analyses</h2><p>Latest jobs submitted to the persistent worker queue.</p></div><Link to="/analyses">View all</Link></div>
        {jobs.length ? <div className="table-wrap"><table><thead><tr><th>Project</th><th>Mode</th><th>Status</th><th>Progress</th><th>Submitted</th></tr></thead><tbody>{jobs.slice(0, 8).map((job: Analysis) => {
          const project = projects.data?.items.find((item) => item.id === job.project_id)
          return <tr key={job.id}><td><Link to={`/analyses/${job.id}`} className="table-link">{project?.name ?? job.project_id}</Link></td><td>{titleCase(job.analysis_kind)}</td><td><StatusBadge status={job.status} /></td><td>{job.progress}%</td><td>{formatDate(job.created_at)}</td></tr>
        })}</tbody></table></div> : <EmptyState title="No analyses submitted" message="Register a project and start a rule, ML, or hybrid analysis." />}
      </Card>
    </div>
  )
}
