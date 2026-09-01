import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, EmptyState, StatusBadge } from '../../components/UI'
import type { Explanation, Prediction } from '../../types/api'
import { formatPercent, titleCase } from '../../utils/format'

export function PredictionsPanel({ predictions, explanations }: { predictions: Prediction[]; explanations: Explanation[] }) {
  const [selected, setSelected] = useState<Prediction | null>(predictions.find((item) => item.prediction) ?? predictions[0] ?? null)
  const [positiveOnly, setPositiveOnly] = useState(false)
  const [smell, setSmell] = useState('')
  const smells = useMemo(() => [...new Set(predictions.map((item) => item.smell_type))].sort(), [predictions])
  const filtered = predictions.filter((item) => (!positiveOnly || item.prediction) && (!smell || item.smell_type === smell))
  const explanation = selected ? explanations.find((item) => item.prediction_id === selected.id) : undefined
  const chart = (explanation?.top_features ?? []).map((item) => ({ feature: titleCase(item.feature), contribution: item.contribution, value: item.value }))

  return <div className="split-detail">
    <Card>
      <div className="filter-bar">
        <select value={smell} onChange={(event) => setSmell(event.target.value)}><option value="">All smells</option>{smells.map((item) => <option key={item} value={item}>{titleCase(item)}</option>)}</select>
        <label className="checkbox-label"><input type="checkbox" checked={positiveOnly} onChange={(event) => setPositiveOnly(event.target.checked)} /> Positive only</label>
        <span>{filtered.length} predictions</span>
      </div>
      {filtered.length ? <div className="prediction-list">{filtered.map((item) => <button className={`prediction-row ${selected?.id === item.id ? 'selected' : ''}`} key={item.id} onClick={() => setSelected(item)}><div><strong>{titleCase(item.smell_type)}</strong><span>{item.qualified_name}</span><small>{item.relative_path}:{item.start_line}</small></div><div><StatusBadge status={item.prediction ? 'positive' : 'negative'} /><b>{formatPercent(item.probability)}</b></div></button>)}</div> : <EmptyState title="No predictions" message="No model predictions match these filters." />}
    </Card>
    <Card className="sticky-detail">
      {selected ? <>
        <div className="card-heading"><div><h2>{titleCase(selected.smell_type)}</h2><p>{selected.qualified_name}</p></div><StatusBadge status={selected.prediction ? 'positive' : 'negative'} /></div>
        <div className="probability-meter"><span style={{ width: `${selected.probability * 100}%` }} /><i style={{ left: `${selected.threshold * 100}%` }} /></div>
        <div className="metric-summary"><div><span>Probability</span><strong>{formatPercent(selected.probability)}</strong></div><div><span>Confidence</span><strong>{formatPercent(selected.confidence)}</strong></div><div><span>Uncertainty</span><strong>{formatPercent(selected.uncertainty)}</strong></div></div>
        <div className="source-location">{selected.relative_path}:{selected.start_line}–{selected.end_line}</div>
        {explanation ? <>
          <div className="section-title"><h3>Local explanation</h3><span>{titleCase(explanation.method)}</span></div>
          {explanation.warning && <p className="warning-text">{explanation.warning}</p>}
          {chart.length ? <ResponsiveContainer width="100%" height={Math.max(240, chart.length * 42)}><BarChart data={chart} layout="vertical" margin={{ left: 20, right: 20 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" /><YAxis dataKey="feature" type="category" width={125} tick={{ fontSize: 11 }} /><Tooltip formatter={(value: any) => Number(value).toFixed(4)} /><Bar dataKey="contribution" radius={[0, 5, 5, 0]}>{chart.map((entry, index) => <Cell key={index} fill={entry.contribution > 0 ? 'var(--color-danger)' : 'var(--color-success)'} />)}</Bar></BarChart></ResponsiveContainer> : <p>No feature attributions stored.</p>}
        </> : <p className="state-message">No local explanation stored for this prediction.</p>}
      </> : <EmptyState title="Select a prediction" message="Choose a model result to inspect probability and feature contributions." />}
    </Card>
  </div>
}
