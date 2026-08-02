import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/endpoints'
import { Card, EmptyState, ErrorState, Loading, PageHeader, ProgressBar, StatusBadge } from '../components/UI'
import { formatDate, titleCase } from '../utils/format'

export function AnalysesPage() {
  const analyses = useQuery({
    queryKey: ['analyses'],
    queryFn: () => api.analyses(),
    refetchInterval: (query) => query.state.data?.items.some((item) => ['queued', 'running'].includes(item.status)) ? 2500 : false,
  })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api.projects() })

  if (analyses.isLoading || projects.isLoading) return <Loading />
  if (analyses.error || projects.error) return <ErrorState error={analyses.error ?? projects.error} />

  const items = analyses.data?.items ?? []
  return (
    <div className="page">
      <PageHeader title="Analysis Jobs" description="Persistent queue status, progress, retries, failures, and completed research runs." />
      <Card>
        {items.length ? <div className="analysis-list">{items.map((job) => {
          const project = projects.data?.items.find((item) => item.id === job.project_id)
          return <Link className="analysis-row" to={`/analyses/${job.id}`} key={job.id}>
            <div className="analysis-row-top"><div><h3>{project?.name ?? job.project_id}</h3><p>{titleCase(job.analysis_kind)} analysis · {titleCase(job.threshold_mode)} thresholds</p></div><StatusBadge status={job.status} /></div>
            <div className="analysis-progress"><ProgressBar value={job.progress} /><strong>{job.progress}%</strong></div>
            <div className="meta-row"><span>{job.progress_message || 'Waiting for worker'}</span><span>Attempt {job.attempts}/{job.max_attempts}</span><span>{formatDate(job.created_at)}</span></div>
          </Link>
        })}</div> : <EmptyState title="No analysis jobs" message="Start an analysis from the Projects page." />}
      </Card>
    </div>
  )
}
