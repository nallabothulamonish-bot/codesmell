import { useMemo, useState } from 'react'
import { Card, EmptyState, SeverityBadge } from '../../components/UI'
import type { Finding } from '../../types/api'
import { formatPercent, titleCase } from '../../utils/format'

export function FindingsPanel({ findings }: { findings: Finding[] }) {
  const [severity, setSeverity] = useState('')
  const [smell, setSmell] = useState('')
  const [path, setPath] = useState('')
  const smells = useMemo(() => [...new Set(findings.map((item) => item.smell_type))].sort(), [findings])
  const filtered = findings.filter((item) => (!severity || item.severity === severity) && (!smell || item.smell_type === smell) && (!path || item.relative_path.toLowerCase().includes(path.toLowerCase())))

  return <Card>
    <div className="filter-bar">
      <select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select>
      <select value={smell} onChange={(event) => setSmell(event.target.value)}><option value="">All smell types</option>{smells.map((item) => <option value={item} key={item}>{titleCase(item)}</option>)}</select>
      <input value={path} onChange={(event) => setPath(event.target.value)} placeholder="Filter source path…" />
      <span>{filtered.length} findings</span>
    </div>
    {filtered.length ? <div className="finding-list">{filtered.map((item) => <article className="finding-card" key={item.id}>
      <div className="finding-top"><div><h3>{titleCase(item.smell_type)}</h3><p>{item.qualified_name}</p></div><div><SeverityBadge severity={item.severity} /><strong>{formatPercent(item.confidence)}</strong></div></div>
      <div className="source-location">{item.relative_path}:{item.start_line}–{item.end_line} · {titleCase(item.entity_type)}</div>
      <p className="rationale">{item.rationale}</p>
      {item.evidence.length > 0 && <div className="evidence-chips">{item.evidence.slice(0, 6).map((entry, index) => <span key={index}>{String(entry.metric ?? entry.feature ?? 'evidence')}: <strong>{entry.value !== undefined ? Number(entry.value).toFixed(2) : 'triggered'}</strong></span>)}</div>}
    </article>)}</div> : <EmptyState title="No matching findings" message="Adjust the filters or inspect a different analysis." />}
  </Card>
}
