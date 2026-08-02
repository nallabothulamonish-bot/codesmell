const API_ROOT = (import.meta.env.VITE_API_ROOT as string | undefined)?.replace(/\/$/, '') ?? ''
const TOKEN_KEY = 'codesmell.access_token'

export function getAccessToken(): string | null { return localStorage.getItem(TOKEN_KEY) }
export function setAccessToken(token: string): void { localStorage.setItem(TOKEN_KEY, token) }
export function clearAccessToken(): void { localStorage.removeItem(TOKEN_KEY) }

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message)
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: unknown
  const raw = await response.text()
  try {
    payload = raw ? JSON.parse(raw) : null
  } catch {
    payload = raw
  }
  const message =
    typeof payload === 'object' && payload !== null && 'detail' in payload
      ? typeof payload.detail === 'string'
        ? payload.detail
        : JSON.stringify(payload.detail)
      : `Request failed with status ${response.status}`
  return new ApiError(message, response.status, payload)
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken()
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...init?.headers,
    },
  })
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function queryString(values: Record<string, string | number | boolean | null | undefined>): string {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  })
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

export async function download(path: string): Promise<{ blob: Blob; filename: string }> {
  const token = getAccessToken()
  const response = await fetch(`${API_ROOT}${path}`, { headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) } })
  if (!response.ok) throw await parseError(response)
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = disposition.match(/filename="?([^";]+)"?/i)
  return { blob: await response.blob(), filename: match?.[1] ?? 'codesmell-report' }
}

