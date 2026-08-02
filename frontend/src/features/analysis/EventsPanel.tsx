import { Card, EmptyState } from '../../components/UI'
import type { JobEvent } from '../../types/api'
import { formatDate, titleCase } from '../../utils/format'

export function EventsPanel({ events }: { events: JobEvent[] }) {
  return <Card>{events.length ? <div className="timeline">{events.map((event) => <div className="timeline-item" key={event.id}><span /><div><div><strong>{titleCase(event.event_type)}</strong><time>{formatDate(event.created_at)}</time></div><p>{event.message}</p>{event.details && <details><summary>Details</summary><pre className="json-preview">{JSON.stringify(event.details, null, 2)}</pre></details>}</div></div>)}</div> : <EmptyState title="No job events" message="Worker lifecycle events will appear here." />}</Card>
}
