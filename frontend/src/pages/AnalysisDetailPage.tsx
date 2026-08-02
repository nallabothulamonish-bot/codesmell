import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { RotateCcw, Square } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/endpoints'
import { useAuth } from '../auth'
import { Button, ErrorState, Loading, Notice, PageHeader, ProgressBar, StatusBadge, Tabs } from '../components/UI'
import { EventsPanel } from '../features/analysis/EventsPanel'
import { FindingsPanel } from '../features/analysis/FindingsPanel'
import { MetricsPanel } from '../features/analysis/MetricsPanel'
import { OverviewPanel } from '../features/analysis/OverviewPanel'
import { PredictionsPanel } from '../features/analysis/PredictionsPanel'
import { RecommendationsPanel } from '../features/analysis/RecommendationsPanel'
import { ReportsPanel } from '../features/analysis/ReportsPanel'
import { compactId, titleCase } from '../utils/format'

export function AnalysisDetailPage() {
  const { user } = useAuth()
  const canMutate = user?.role === 'admin' || user?.role === 'analyst'
  const { id = '' } = useParams()
  const client = useQueryClient()
  const [tab, setTab] = useState('overview')
  const analysis = useQuery({
    queryKey: ['analysis', id],
    queryFn: () => api.analysis(id),
    enabled: Boolean(id),
    refetchInterval: (query) => ['queued', 'running'].includes(query.state.data?.status ?? '') ? 2000 : false,
  })
  const project = useQuery({ queryKey: ['project', analysis.data?.project_id], queryFn: () => api.project(analysis.data!.project_id), enabled: Boolean(analysis.data?.project_id) })
  const isFinished = ['succeeded', 'completed'].includes(analysis.data?.status ?? '')
  const resultQueries = useQueries({
    queries: [
      { queryKey: ['findings', id], queryFn: () => api.findings(id), enabled: isFinished },
      { queryKey: ['metrics', id], queryFn: () => api.metrics(id), enabled: isFinished },
      { queryKey: ['predictions', id], queryFn: () => api.predictions(id), enabled: isFinished },
      { queryKey: ['explanations', id], queryFn: () => api.explanations(id), enabled: isFinished },
      { queryKey: ['recommendations', id], queryFn: () => api.recommendations(id), enabled: isFinished },
      { queryKey: ['events', id], queryFn: () => api.events(id), refetchInterval: ['queued', 'running'].includes(analysis.data?.status ?? '') ? 2500 : false },
    ],
  })
  const cancel = useMutation({ mutationFn: () => api.cancelAnalysis(id), onSuccess: () => void client.invalidateQueries({ queryKey: ['analysis', id] }) })
  const retry = useMutation({ mutationFn: () => api.retryAnalysis(id), onSuccess: () => void client.invalidateQueries({ queryKey: ['analysis', id] }) })

  if (analysis.isLoading) return <Loading />
  if (analysis.error || !analysis.data) return <ErrorState error={analysis.error ?? new Error('Analysis not found')} />

  const job = analysis.data
  const findings = resultQueries[0].data?.items ?? []
  const metrics = resultQueries[1].data?.items ?? []
  const predictions = resultQueries[2].data?.items ?? []
  const explanations = resultQueries[3].data?.items ?? []
  const recommendations = resultQueries[4].data?.items ?? []
  const events = resultQueries[5].data?.items ?? []
  const actionError = cancel.error ?? retry.error
  const isActive = ['queued', 'running'].includes(job.status)

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'findings', label: 'Findings', count: findings.length },
    { id: 'metrics', label: 'Metrics', count: metrics.length },
    { id: 'predictions', label: 'ML & XAI', count: predictions.length },
    { id: 'recommendations', label: 'Recommendations', count: recommendations.length },
    { id: 'reports', label: 'Reports' },
    { id: 'events', label: 'Events', count: events.length },
  ]

  return <div className="page">
    <PageHeader title={project.data?.name ?? `Analysis ${compactId(job.id)}`} description={`${titleCase(job.analysis_kind)} analysis · ${job.progress_message}`} actions={<div className="inline-actions"><StatusBadge status={job.status} />{canMutate && isActive && <Button variant="danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}><Square size={15} /> Cancel</Button>}{canMutate && ['failed', 'cancelled'].includes(job.status) && <Button onClick={() => retry.mutate()} disabled={retry.isPending}><RotateCcw size={16} /> Retry</Button>}<Link className="button button-secondary" to="/analyses">All jobs</Link></div>} />
    {actionError && <Notice tone="danger">{actionError.message}</Notice>}
    {job.error_message && <Notice tone="danger"><strong>{job.error_code ?? 'Analysis failed'}:</strong> {job.error_message}</Notice>}
    {isActive && <div className="job-progress-card"><div><strong>{job.progress}%</strong><span>{job.progress_message || 'Waiting for worker'}</span></div><ProgressBar value={job.progress} /></div>}
    <Tabs items={tabs} active={tab} onChange={setTab} />
    {tab === 'overview' && <OverviewPanel analysis={job} findings={findings} predictions={predictions} recommendations={recommendations} />}
    {tab === 'findings' && <FindingsPanel findings={findings} />}
    {tab === 'metrics' && <MetricsPanel metrics={metrics} />}
    {tab === 'predictions' && <PredictionsPanel predictions={predictions} explanations={explanations} />}
    {tab === 'recommendations' && <RecommendationsPanel recommendations={recommendations} />}
    {tab === 'reports' && <ReportsPanel jobId={id} />}
    {tab === 'events' && <EventsPanel events={events} />}
  </div>
}
