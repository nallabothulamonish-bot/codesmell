import { CheckCircle2 } from 'lucide-react'
import { Card, EmptyState, SeverityBadge } from '../../components/UI'
import type { Recommendation } from '../../types/api'
import { titleCase } from '../../utils/format'

export function RecommendationsPanel({ recommendations }: { recommendations: Recommendation[] }) {
  return recommendations.length ? <div className="recommendation-grid">{recommendations.map((item) => <Card key={item.id} className="recommendation-card">
    <div className="card-heading"><div><h2>{item.title}</h2><p>{titleCase(item.smell_type)}</p></div><SeverityBadge severity={item.priority} /></div>
    <p>{item.summary}</p>
    <h3>Recommended actions</h3>
    <ol>{item.actions.map((action, index) => <li key={index}>{action}</li>)}</ol>
    {item.evidence.length > 0 && <><h3>Metric evidence</h3><div className="evidence-chips">{item.evidence.map((entry, index) => <span key={index}>{String(entry.metric ?? entry.feature ?? 'feature')}: <strong>{entry.value !== undefined ? Number(entry.value).toFixed(2) : 'flagged'}</strong></span>)}</div></>}
    <h3>Validation checklist</h3>
    <ul className="check-list">{item.validation_steps.map((step, index) => <li key={index}><CheckCircle2 size={16} />{step}</li>)}</ul>
  </Card>)}</div> : <EmptyState title="No recommendations" message="Recommendations are generated for eligible positive ML predictions." />
}
