import { Activity, AlertTriangle, BrainCircuit, CheckCircle2 } from 'lucide-react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Card, StatCard } from '../../components/UI'
import type { Analysis, Finding, Prediction, Recommendation } from '../../types/api'
import { formatDate, titleCase } from '../../utils/format'

export function OverviewPanel({ analysis, findings, predictions, recommendations }: { analysis: Analysis; findings: Finding[]; predictions: Prediction[]; recommendations: Recommendation[] }) {
  const severity = Object.entries(findings.reduce<Record<string, number>>((acc, item) => { acc[item.severity] = (acc[item.severity] ?? 0) + 1; return acc }, {})).map(([name, value]) => ({ name: titleCase(name), value }))
  const positives = predictions.filter((item) => item.prediction).length
  const predictionChart = [
    { name: 'Predicted Positive', value: positives },
    { name: 'Predicted Negative', value: predictions.length - positives },
  ].filter((item) => item.value > 0)
  const isMlOnly = analysis.analysis_kind === 'ml'
  const chartData = isMlOnly ? predictionChart : severity
  return <>
    <div className="stats-grid compact">
      <StatCard label="Rule findings" value={findings.length} hint={`${findings.filter((item) => ['high', 'critical'].includes(item.severity)).length} high priority`} icon={<AlertTriangle />} />
      <StatCard label="ML predictions" value={predictions.length} hint={`${positives} predicted positive`} icon={<BrainCircuit />} />
      <StatCard label="Recommendations" value={recommendations.length} hint="Behaviour-preserving guidance" icon={<CheckCircle2 />} />
      <StatCard label="Attempts" value={`${analysis.attempts}/${analysis.max_attempts}`} hint={`Completed ${formatDate(analysis.completed_at)}`} icon={<Activity />} />
    </div>
    <div className="dashboard-grid">
      <Card>
        <div className="card-heading"><div><h2>Analysis summary</h2><p>Worker output and run configuration.</p></div></div>
        <dl className="detail-grid">
          <div><dt>Mode</dt><dd>{titleCase(analysis.analysis_kind)}</dd></div>
          <div><dt>Thresholds</dt><dd>{titleCase(analysis.threshold_mode)}</dd></div>
          <div><dt>Minimum severity</dt><dd>{titleCase(analysis.min_severity)}</dd></div>
          <div><dt>Explanations</dt><dd>{analysis.explain_predictions ? 'Enabled' : 'Disabled'}</dd></div>
          <div><dt>Started</dt><dd>{formatDate(analysis.started_at)}</dd></div>
          <div><dt>Completed</dt><dd>{formatDate(analysis.completed_at)}</dd></div>
        </dl>
        {analysis.summary && <pre className="json-preview">{JSON.stringify(analysis.summary, null, 2)}</pre>}
      </Card>
      <Card>
        <div className="card-heading"><div><h2>{isMlOnly ? 'ML prediction distribution' : 'Finding severity'}</h2><p>{isMlOnly ? 'Positive and negative model predictions.' : 'Rule-based risk distribution.'}</p></div></div>
        {chartData.length ? <ResponsiveContainer width="100%" height={280}><PieChart><Pie data={chartData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} label={({ name, value }) => `${name}: ${value}`}>{chartData.map((_, index) => <Cell key={index} className={`chart-slice slice-${index}`} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer> : <div className="state-message">{isMlOnly ? 'No ML predictions were stored for this job.' : 'No rule findings were stored for this job.'}</div>}
      </Card>
    </div>
  </>
}




