import { Link } from 'react-router-dom'
import { EmptyState } from '../components/UI'

export function NotFoundPage() {
  return <div className="page"><EmptyState title="Page not found" message="The requested dashboard route does not exist." action={<Link className="button button-primary" to="/">Return to dashboard</Link>} /></div>
}
