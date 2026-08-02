import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BrainCircuit, Power, Trash2 } from 'lucide-react'
import { api } from '../api/endpoints'
import { Button, Card, EmptyState, ErrorState, Loading, Notice, PageHeader, StatusBadge } from '../components/UI'
import { formatDate, formatPercent, titleCase } from '../utils/format'

export function ModelsPage() {
  const client = useQueryClient()
  const models = useQuery({ queryKey: ['models'], queryFn: () => api.models() })
  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.setModelEnabled(id, enabled),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['models'] }),
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteModel(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['models'] }),
  })

  if (models.isLoading) return <Loading />
  if (models.error) return <ErrorState error={models.error} />

  return <div className="page">
    <PageHeader title="Model Registry" description="Trusted, server-side M5 artifacts available for ML and hybrid analyses." />
    <Notice tone="info">Models are registered through the administrator CLI. The web application intentionally does not accept arbitrary joblib or pickle uploads.</Notice>
    {models.data?.items.length ? <div className="model-grid">{models.data.items.map((model) => <Card className="model-card" key={model.id}>
      <div className="model-card-top"><div className="model-icon"><BrainCircuit /></div><StatusBadge status={model.enabled ? 'enabled' : 'disabled'} /></div>
      <h2>{model.name}</h2>
      <p>{titleCase(model.smell_type)} detector for {titleCase(model.entity_type)} entities.</p>
      <dl className="detail-grid">
        <div><dt>Estimator</dt><dd>{titleCase(model.model_kind)}</dd></div>
        <div><dt>Threshold</dt><dd>{formatPercent(model.threshold)}</dd></div>
        <div><dt>Features</dt><dd>{model.feature_names.length}</dd></div>
        <div><dt>Registered</dt><dd>{formatDate(model.created_at)}</dd></div>
      </dl>
      <details><summary>Feature schema</summary><div className="feature-list">{model.feature_names.map((feature) => <span key={feature}>{titleCase(feature)}</span>)}</div></details>
      <div className="hash-row"><span>SHA-256</span><code>{model.model_sha256}</code></div>
      <div className="model-actions"><Button variant="secondary" onClick={() => toggle.mutate({ id: model.id, enabled: !model.enabled })} disabled={toggle.isPending}><Power size={16} /> {model.enabled ? 'Disable' : 'Enable'}</Button><Button variant="ghost" onClick={() => { if (confirm(`Delete ${model.name}? Models with persisted predictions cannot be deleted.`)) remove.mutate(model.id) }}><Trash2 size={17} /></Button></div>
    </Card>)}</div> : <EmptyState title="No registered models" message="Use codesmell model register to add a verified M5 model artifact." />}
    {(toggle.error || remove.error) && <Notice tone="danger">{(toggle.error ?? remove.error)?.message}</Notice>}
  </div>
}
