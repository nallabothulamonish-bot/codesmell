import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileArchive, Github, Play, Trash2, UploadCloud } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { api } from '../api/endpoints'
import { useAuth } from '../auth'
import { Button, Card, EmptyState, ErrorState, Loading, Notice, PageHeader, StatusBadge } from '../components/UI'
import type { AnalysisKind, Project, Severity } from '../types/api'
import { formatDate, titleCase } from '../utils/format'

const githubSchema = z.object({
  url: z.string().url().refine((value) => value.startsWith('https://'), 'Use a public HTTPS repository URL.'),
  name: z.string().max(160).optional(),
})
type GithubForm = z.infer<typeof githubSchema>

function AnalysisLauncher({ project, onClose }: { project: Project; onClose: () => void }) {
  const navigate = useNavigate()
  const models = useQuery({ queryKey: ['models'], queryFn: () => api.models({ enabled: true }) })
  const [kind, setKind] = useState<AnalysisKind>('hybrid')
  const [thresholdMode, setThresholdMode] = useState<'absolute' | 'percentile'>('absolute')
  const [severity, setSeverity] = useState<Severity>('low')
  const [selectedModels, setSelectedModels] = useState<string[]>([])
  const [explain, setExplain] = useState(true)
  const create = useMutation({
    mutationFn: () => api.createAnalysis(project.id, {
      analysis_kind: kind,
      threshold_mode: thresholdMode,
      min_severity: severity,
      model_ids: kind === 'rule' ? undefined : selectedModels.length ? selectedModels : undefined,
      explain_predictions: explain,
    }),
    onSuccess: (analysis) => navigate(`/analyses/${analysis.id}`),
  })

  const enabledModels = models.data?.items ?? []
  const needsModels = kind !== 'rule'

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <Card className="modal-card">
        <div className="card-heading"><div><h2>Configure analysis</h2><p>{project.name}</p></div><button className="icon-button" onClick={onClose}>×</button></div>
        <div className="form-grid">
          <label>Analysis mode<select value={kind} onChange={(event) => setKind(event.target.value as AnalysisKind)}><option value="rule">Rule based</option><option value="ml">Machine learning</option><option value="hybrid">Hybrid</option></select></label>
          <label>Threshold mode<select value={thresholdMode} onChange={(event) => setThresholdMode(event.target.value as 'absolute' | 'percentile')}><option value="absolute">Absolute</option><option value="percentile">Project percentile</option></select></label>
          <label>Minimum severity<select value={severity} onChange={(event) => setSeverity(event.target.value as Severity)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label>
          <label className="checkbox-label"><input type="checkbox" checked={explain} onChange={(event) => setExplain(event.target.checked)} disabled={!needsModels} /> Generate local explanations</label>
        </div>
        {needsModels && <div className="model-picker"><h3>ML models</h3>{models.isLoading ? <Loading label="Loading enabled models…" /> : enabledModels.length ? enabledModels.map((model) => <label className="model-choice" key={model.id}><input type="checkbox" checked={selectedModels.includes(model.id)} onChange={(event) => setSelectedModels((current) => event.target.checked ? [...current, model.id] : current.filter((id) => id !== model.id))} /><span><strong>{model.name}</strong><small>{titleCase(model.smell_type)} · {titleCase(model.model_kind)}</small></span></label>) : <Notice tone="warning">No enabled models are registered. Register an M5 model from the CLI or choose rule analysis.</Notice>}</div>}
        {create.error && <Notice tone="danger">{create.error.message}</Notice>}
        <div className="modal-actions"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={() => create.mutate()} disabled={create.isPending || (needsModels && !enabledModels.length)}><Play size={17} /> {create.isPending ? 'Submitting…' : 'Start analysis'}</Button></div>
      </Card>
    </div>
  )
}

export function ProjectsPage() {
  const { user } = useAuth()
  const canMutate = user?.role === 'admin' || user?.role === 'analyst'
  const client = useQueryClient()
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api.projects() })
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadName, setUploadName] = useState('')
  const [launchProject, setLaunchProject] = useState<Project | null>(null)
  const upload = useMutation({
    mutationFn: () => {
      if (!uploadFile) throw new Error('Select a .zip or .py file first.')
      return api.uploadProject(uploadFile, uploadName)
    },
    onSuccess: () => {
      setUploadFile(null)
      setUploadName('')
      void client.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  const github = useMutation({
    mutationFn: (values: GithubForm) => api.registerGithub(values.url, values.name),
    onSuccess: () => {
      reset()
      void client.invalidateQueries({ queryKey: ['projects'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['projects'] }),
  })
  const { register, handleSubmit, reset, formState: { errors } } = useForm<GithubForm>({ resolver: zodResolver(githubSchema) })

  if (projects.isLoading) return <Loading />
  if (projects.error) return <ErrorState error={projects.error} />

  return (
    <div className="page">
      <PageHeader title="Projects" description="Register source code through a safe file upload or an allowed public Git repository." />
      {canMutate ? <div className="two-column">
        <Card>
          <div className="card-heading"><div><h2>Upload source</h2><p>Accepted formats: a Python file or ZIP archive.</p></div><UploadCloud /></div>
          <div className="upload-drop">
            <FileArchive size={34} />
            <strong>{uploadFile?.name ?? 'Choose a project archive'}</strong>
            <span>Source code is parsed statically and never executed.</span>
            <input aria-label="Project file" type="file" accept=".zip,.py" onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)} />
          </div>
          <label>Display name (optional)<input value={uploadName} onChange={(event) => setUploadName(event.target.value)} placeholder="My research project" maxLength={160} /></label>
          {upload.error && <Notice tone="danger">{upload.error.message}</Notice>}
          <Button className="full-width" onClick={() => upload.mutate()} disabled={!uploadFile || upload.isPending}>{upload.isPending ? 'Uploading…' : 'Register uploaded project'}</Button>
        </Card>

        <Card>
          <div className="card-heading"><div><h2>Public repository</h2><p>GitHub, GitLab, or Bitbucket HTTPS URL.</p></div><Github /></div>
          <form className="stack-form" onSubmit={handleSubmit((values) => github.mutate(values))}>
            <label>Repository URL<input {...register('url')} placeholder="https://github.com/owner/repository" />{errors.url && <small className="field-error">{errors.url.message}</small>}</label>
            <label>Display name (optional)<input {...register('name')} placeholder="Repository name" /></label>
            {github.error && <Notice tone="danger">{github.error.message}</Notice>}
            <Button type="submit" disabled={github.isPending}>{github.isPending ? 'Registering…' : 'Register repository'}</Button>
          </form>
        </Card>
      </div> : <Notice tone="info">Your viewer role provides read-only access. An analyst or administrator can register projects and start analyses.</Notice>}

      <Card>
        <div className="card-heading"><div><h2>Registered projects</h2><p>{projects.data?.total ?? 0} projects available for analysis.</p></div></div>
        {projects.data?.items.length ? <div className="project-list">{projects.data.items.map((project) => <article className="project-card" key={project.id}><div className="project-icon">{project.source_type === 'github' ? <Github /> : <FileArchive />}</div><div className="project-main"><div className="project-title"><h3>{project.name}</h3><StatusBadge status={project.status} /></div><p>{project.source_url ?? project.original_filename ?? 'Uploaded source'}</p><div className="meta-row"><span>{titleCase(project.source_type)}</span><span>{formatDate(project.created_at)}</span>{project.fingerprint && <span>Fingerprint ready</span>}</div></div>{canMutate && <div className="project-actions"><Button variant="secondary" onClick={() => setLaunchProject(project)}><Play size={16} /> Analyze</Button><Button variant="ghost" onClick={() => { if (confirm(`Delete ${project.name}?`)) remove.mutate(project.id) }} aria-label={`Delete ${project.name}`}><Trash2 size={17} /></Button></div>}</article>)}</div> : <EmptyState title="No projects registered" message="Upload a Python project or add a public repository to begin." />}
      </Card>
      {canMutate && launchProject && <AnalysisLauncher project={launchProject} onClose={() => setLaunchProject(null)} />}
    </div>
  )
}
