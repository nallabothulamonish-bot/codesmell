import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { AuthProvider } from './auth'

afterEach(() => vi.restoreAllMocks())

describe('application routing', () => {
  it('renders the dashboard shell', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/auth/me')) return new Response(JSON.stringify({ id: 'local', email: 'local@example.test', display_name: 'Local Admin', role: 'admin', enabled: true, last_login_at: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }), { status: 200 })
      if (url.includes('/projects')) return new Response(JSON.stringify({ items: [], total: 0, limit: 200, offset: 0 }), { status: 200 })
      if (url.includes('/analyses')) return new Response(JSON.stringify({ items: [], total: 0, limit: 200, offset: 0 }), { status: 200 })
      if (url.includes('/models')) return new Response(JSON.stringify({ items: [], total: 0, limit: 500, offset: 0 }), { status: 200 })
      return new Response('{}', { status: 200 })
    }))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><AuthProvider><MemoryRouter initialEntries={['/']}><App /></MemoryRouter></AuthProvider></QueryClientProvider>)
    expect(await screen.findByText('Research Dashboard')).toBeInTheDocument()
    expect(screen.getByText('CodeSmell')).toBeInTheDocument()
  })
})
