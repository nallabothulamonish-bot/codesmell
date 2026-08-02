import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileArchive, FileCode2, FileJson, FileText } from 'lucide-react'
import { api } from '../../api/endpoints'
import { Button, ErrorState, Loading, Notice } from '../../components/UI'
import type { ReportFormat } from '../../types/api'
import { useAuth } from '../../auth'

const formats: { id: ReportFormat; label: string; icon: typeof FileText }[] = [
  { id: 'pdf', label: 'PDF', icon: FileText },
  { id: 'html', label: 'HTML', icon: FileCode2 },
  { id: 'json', label: 'JSON', icon: FileJson },
  { id: 'csv', label: 'CSV bundle', icon: FileArchive },
]

export function ReportsPanel({ jobId }: { jobId: string }) {
  const { user } = useAuth()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['reports', jobId], queryFn: () => api.reports(jobId) })
  const create = useMutation({ mutationFn: (format: ReportFormat) => api.createReport(jobId, format), onSuccess: () => void client.invalidateQueries({ queryKey: ['reports', jobId] }) })
  const download = useMutation({ mutationFn: async (id: string) => { const file = await api.downloadReport(id); const url = URL.createObjectURL(file.blob); const link = document.createElement('a'); link.href = url; link.download = file.filename; link.click(); URL.revokeObjectURL(url) } })
  if (query.isLoading) return <Loading />
  if (query.error) return <ErrorState error={query.error} />
  const canCreate = user?.role === 'admin' || user?.role === 'analyst'
  return <div className="stack">
    {canCreate && <div className="report-actions">{formats.map(({ id, label, icon: Icon }) => <Button key={id} onClick={() => create.mutate(id)} disabled={create.isPending}><Icon size={16} /> Generate {label}</Button>)}</div>}
    {create.error && <Notice tone="danger">{create.error.message}</Notice>}
    <div className="report-list">{query.data?.items.length ? query.data.items.map((report) => <article className="report-card" key={report.id}><div><strong>{report.title}</strong><span>{report.format.toUpperCase()} · {report.status} · {report.size_bytes ? `${Math.ceil(report.size_bytes / 1024)} KB` : 'pending'}</span>{report.content_sha256 && <code>{report.content_sha256.slice(0, 20)}...</code>}</div>{report.status === 'ready' && <Button variant="secondary" onClick={() => download.mutate(report.id)} disabled={download.isPending}><Download size={16} /> Download</Button>}</article>) : <Notice>No reports generated yet.</Notice>}</div>
  </div>
}
