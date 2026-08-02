import { useMemo, useState } from 'react'
import { Card, EmptyState } from '../../components/UI'
import type { MetricRecord } from '../../types/api'
import { titleCase } from '../../utils/format'

export function MetricsPanel({ metrics }: { metrics: MetricRecord[] }) {
  const [entityType, setEntityType] = useState('')
  const [path, setPath] = useState('')
  const metricNames = useMemo(() => [...new Set(metrics.flatMap((item) => Object.keys(item.metrics)))].sort(), [metrics])
  const [sortMetric, setSortMetric] = useState('')
  const filtered = metrics.filter((item) => (!entityType || item.entity_type === entityType) && (!path || item.relative_path.toLowerCase().includes(path.toLowerCase()))).sort((a, b) => sortMetric ? (b.metrics[sortMetric] ?? -Infinity) - (a.metrics[sortMetric] ?? -Infinity) : a.relative_path.localeCompare(b.relative_path))
  return <Card>
    <div className="filter-bar">
      <select value={entityType} onChange={(event) => setEntityType(event.target.value)}><option value="">All entities</option>{[...new Set(metrics.map((item) => item.entity_type))].sort().map((item) => <option key={item} value={item}>{titleCase(item)}</option>)}</select>
      <select value={sortMetric} onChange={(event) => setSortMetric(event.target.value)}><option value="">Sort by path</option>{metricNames.map((item) => <option value={item} key={item}>{titleCase(item)}</option>)}</select>
      <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="Filter source path…" />
      <span>{filtered.length} entities</span>
    </div>
    {filtered.length ? <div className="table-wrap"><table><thead><tr><th>Entity</th><th>Type</th><th>Location</th><th>Selected metric</th><th>Metric count</th></tr></thead><tbody>{filtered.map((item) => <tr key={item.id}><td><strong>{item.qualified_name}</strong></td><td>{titleCase(item.entity_type)}</td><td>{item.relative_path}:{item.start_line}</td><td>{sortMetric ? (item.metrics[sortMetric]?.toFixed(2) ?? '—') : '—'}</td><td><details><summary>{Object.keys(item.metrics).length} values</summary><pre className="metric-json">{JSON.stringify(item.metrics, null, 2)}</pre></details></td></tr>)}</tbody></table></div> : <EmptyState title="No metrics available" message="This analysis did not persist metric entities matching the filters." />}
  </Card>
}
