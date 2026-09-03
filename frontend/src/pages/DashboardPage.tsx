import { useQueries, useQuery } from '@tanstack/react-query'
import { AlertTriangle, BrainCircuit, CheckCircle2, FolderKanban, Gauge, Code2, Sparkles, ArrowRight } from 'lucide-react'
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
  const analyses = useQuery({ queryKey: ['analyses'], queryFn: () => api.analyses(), refetchInterval: 5000 })
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

  // Calculate Code Health Score (0 - 100) & Grade
  const totalFindingsCount = findings.length
  let healthScore = 100
  if (totalFindingsCount > 0) {
    const highSeverity = findings.filter(f => f.severity === 'high' || f.severity === 'critical').length
    const medSeverity = findings.filter(f => f.severity === 'medium').length
    const penalty = (highSeverity * 3) + (medSeverity * 1.5) + (totalFindingsCount * 0.2)
    healthScore = Math.max(35, Math.round(100 - Math.min(65, penalty)))
  }

  let grade = 'A+'
  let gradeClass = 'grade-aplus'
  if (healthScore >= 95) { grade = 'A+'; gradeClass = 'grade-aplus'; }
  else if (healthScore >= 88) { grade = 'A'; gradeClass = 'grade-a'; }
  else if (healthScore >= 78) { grade = 'B'; gradeClass = 'grade-b'; }
  else if (healthScore >= 65) { grade = 'C'; gradeClass = 'grade-c'; }
  else { grade = 'D'; gradeClass = 'grade-d'; }

  // Technical Debt Estimate in Hours (approx 1.5h per finding)
  const techDebtHours = Math.round(totalFindingsCount * 1.5)

  // Calculate circumference offset for SVG gauge
  const radius = 68
  const circumference = 2 * Math.PI * radius
  const strokeDashoffset = circumference - (healthScore / 100) * circumference

  return (
    <div className="page">
      <PageHeader
        title="Software Quality Intelligence Dashboard"
        description="Monitor code maintainability, technical debt, rule findings, and machine learning smell predictions across repositories."
        actions={
          <div className="inline-actions">
            <Link className="button button-primary" to="/projects">
              <Sparkles size={16} /> New Analysis
            </Link>
          </div>
        }
      />

      {/* Code Health & Technical Debt Hero Gauge */}
      <div className="health-dashboard-card" style={{ marginBottom: '24px' }}>
        <div className="gauge-wrapper">
          <svg className="gauge-svg" viewBox="0 0 160 160">
            <circle className="gauge-bg" cx="80" cy="80" r={radius} />
            <circle
              className="gauge-fill"
              cx="80"
              cy="80"
              r={radius}
              stroke={healthScore >= 80 ? 'var(--emerald)' : healthScore >= 65 ? 'var(--amber)' : 'var(--rose)'}
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
            />
          </svg>
          <div className="gauge-text">
            <span className="gauge-score" style={{ color: healthScore >= 80 ? 'var(--emerald)' : healthScore >= 65 ? 'var(--amber)' : 'var(--rose)' }}>
              {healthScore}
            </span>
            <span className="gauge-label">Quality Score</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <span className={`grade-pill ${gradeClass}`}>Grade {grade}</span>
            <span className="status-pulse-pill" style={{ background: 'var(--surface)' }}>
              <span className="pulse-dot" /> Enterprise ML Engine Active
            </span>
          </div>
          <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 800 }}>
            {healthScore >= 85 ? 'Strong Code Health Maintainability' : healthScore >= 70 ? 'Moderate Technical Debt Detected' : 'Refactoring Priority Required'}
          </h2>
          <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Extracted software metrics across {projects.data?.total ?? 0} registered packages. Current estimated technical debt: <strong style={{ color: 'var(--text)' }}>{techDebtHours} hours</strong>.
          </p>

          <div style={{ display: 'flex', gap: '20px', marginTop: '4px', flexWrap: 'wrap' }}>
            <div>
              <small style={{ color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', fontSize: '0.7rem' }}>Tech Debt</small>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--amber)' }}>~{techDebtHours} hrs</div>
            </div>
            <div>
              <small style={{ color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', fontSize: '0.7rem' }}>Total Detections</small>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--rose)' }}>{totalFindingsCount}</div>
            </div>
            <div>
              <small style={{ color: 'var(--text-muted)', fontWeight: 700, textTransform: 'uppercase', fontSize: '0.7rem' }}>Multi-Language</small>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--sky)' }}>Java, C++, TS, Py</div>
            </div>
          </div>
        </div>
      </div>

      {/* Metric Cards Grid */}
      <div className="stats-grid" style={{ marginBottom: '24px' }}>
        <StatCard label="Registered Projects" value={projects.data?.total ?? 0} hint="Multi-language source repositories" icon={<FolderKanban />} />
        <StatCard label="Completed Analyses" value={completed.length} hint={`${active} jobs active in worker queue`} icon={<CheckCircle2 />} />
        <StatCard label="Active Findings" value={findings.length} hint="Across latest completed jobs" icon={<AlertTriangle />} />
        <StatCard label="Enabled ML Models" value={(models.data?.items ?? []).filter((item) => item.enabled).length} hint={`${models.data?.total ?? 0} registered artifacts`} icon={<BrainCircuit />} />
      </div>

      {/* Analytics Charts Grid */}
      <div className="dashboard-grid" style={{ marginBottom: '24px' }}>
        <Card className="glass-card">
          <div className="card-heading">
            <div>
              <h2>Severity Distribution</h2>
              <p>Rule & Machine Learning smell findings by severity level.</p>
            </div>
          </div>
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
              <div className="chart-legend">
                {severityData.map((item, index) => {
                  const SEVERITY_FILL: Record<string, string> = { Low: '#0ea5e9', Medium: '#f59e0b', High: '#f97316', Critical: '#f43f5e' }
                  const FALLBACK = ['#10b981', '#f59e0b', '#f43f5e', '#6366f1', '#0ea5e9', '#8b5cf6']
                  const color = SEVERITY_FILL[item.name] ?? FALLBACK[index % FALLBACK.length]
                  return (
                    <div key={item.name}>
                      <span className="legend-dot" style={{ background: color }} />
                      {item.name}
                      <strong>{item.value}</strong>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : <EmptyState title="No findings yet" message="Complete an analysis to populate the severity breakdown." />}
        </Card>

        <Card className="glass-card">
          <div className="card-heading">
            <div>
              <h2>Top Smell Types Detected</h2>
              <p>Most frequent code smell patterns in recent analyses.</p>
            </div>
            <Gauge />
          </div>
          {smellData.length ? (
            <div className="rank-list">
              {smellData.map((item, index) => {
                const max = smellData[0]?.value || 1
                const COLORS = ['#6366f1', '#8b5cf6', '#0ea5e9', '#10b981', '#f59e0b', '#f97316']
                return (
                  <div className="rank-row" key={item.name}>
                    <div>
                      <span>{index + 1}</span>
                      <strong>{item.name}</strong>
                      <em>{item.value}</em>
                    </div>
                    <div className="mini-bar">
                      <i style={{ width: `${(item.value / max) * 100}%`, background: COLORS[index % COLORS.length] }} />
                    </div>
                  </div>
                )
              })}
            </div>
          ) : <EmptyState title="No smell ranking" message="The ranking appears after a completed rule or hybrid analysis." />}
        </Card>
      </div>

      {/* Recent Analyses Queue */}
      <Card className="glass-card">
        <div className="card-heading">
          <div>
            <h2>Recent Worker Analyses Queue</h2>
            <p>Latest analysis jobs processed by the persistent execution queue.</p>
          </div>
          <Link to="/analyses" style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--accent)', fontWeight: 700 }}>
            View all jobs <ArrowRight size={16} />
          </Link>
        </div>
        {jobs.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Target Project</th>
                  <th>Analysis Kind</th>
                  <th>Job Status</th>
                  <th>Progress</th>
                  <th>Submitted At</th>
                </tr>
              </thead>
              <tbody>
                {jobs.slice(0, 8).map((job: Analysis) => {
                  const project = projects.data?.items.find((item) => item.id === job.project_id)
                  return (
                    <tr key={job.id}>
                      <td>
                        <Link to={`/analyses/${job.id}`} className="table-link">
                          <strong>{project?.name ?? job.project_id}</strong>
                        </Link>
                      </td>
                      <td>
                        <span className="lang-pill">
                          <Code2 size={12} /> {titleCase(job.analysis_kind)}
                        </span>
                      </td>
                      <td><StatusBadge status={job.status} /></td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <strong style={{ fontSize: '0.85rem' }}>{job.progress}%</strong>
                          <div style={{ flex: 1, height: '6px', background: 'var(--bg-subtle)', borderRadius: '4px', overflow: 'hidden' }}>
                            <div style={{ height: '100%', width: `${job.progress}%`, background: job.status === 'succeeded' ? 'var(--emerald)' : 'var(--accent)', transition: 'width 0.3s' }} />
                          </div>
                        </div>
                      </td>
                      <td><span style={{ fontSize: '0.82rem' }}>{formatDate(job.created_at)}</span></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="No analyses submitted" message="Register a project and start a rule, ML, or hybrid analysis." />}
      </Card>
    </div>
  )
}
