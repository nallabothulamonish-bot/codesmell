import { download, queryString, request } from './client'
import type {
  Analysis,
  AnalysisCreate,
  Explanation,
  Finding,
  JobEvent,
  MetricRecord,
  ModelArtifact,
  Page,
  Prediction,
  Project,
  Recommendation,
  GeneratedReport,
  ReportFormat,
  TokenResponse,
  User,
  AuditEvent,
} from '../types/api'

export const api = {
  login: (email: string, password: string) => request<TokenResponse>('/api/v1/auth/token', { method: 'POST', body: JSON.stringify({ email, password }) }),
  register: (payload: { email: string; display_name: string; password: string; role: string }) => request<TokenResponse>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify(payload) }),
  me: () => request<User>('/api/v1/auth/me'),
  users: () => request<Page<User>>('/api/v1/users?limit=500'),
  createUser: (payload: { email: string; display_name: string; password: string; role: string; enabled: boolean }) => request<User>('/api/v1/users', { method: 'POST', body: JSON.stringify(payload) }),
  updateUser: (id: string, payload: { role?: string; enabled?: boolean; display_name?: string }) => request<User>(`/api/v1/users/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  resetPassword: (userId: string, password: string) => request<User>(`/api/v1/users/${userId}/password`, { method: 'POST', body: JSON.stringify({ password }) }),
  auditEvents: () => request<Page<AuditEvent>>('/api/v1/users/audit/events?limit=100'),
  health: () => request<{ status: string }>('/health/ready'),

  projects: (limit = 200) => request<Page<Project>>(`/api/v1/projects${queryString({ limit })}`),
  project: (id: string) => request<Project>(`/api/v1/projects/${id}`),
  uploadProject: async (file: File, name?: string) => {
    const body = new FormData()
    body.append('file', file)
    if (name?.trim()) body.append('name', name.trim())
    return request<Project>('/api/v1/projects/upload', { method: 'POST', body })
  },
  registerGithub: (url: string, name?: string) =>
    request<Project>('/api/v1/projects/github', {
      method: 'POST',
      body: JSON.stringify({ url, name: name?.trim() || null }),
    }),
  deleteProject: (id: string) => request<void>(`/api/v1/projects/${id}`, { method: 'DELETE' }),

  analyses: (filters: { project_id?: string; status?: string; limit?: number } = {}) =>
    request<Page<Analysis>>(`/api/v1/analyses${queryString({ limit: 200, ...filters })}`),
  analysis: (id: string) => request<Analysis>(`/api/v1/analyses/${id}`),
  createAnalysis: (projectId: string, payload: AnalysisCreate) =>
    request<Analysis>(`/api/v1/projects/${projectId}/analyses`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  cancelAnalysis: (id: string) => request<Analysis>(`/api/v1/analyses/${id}/cancel`, { method: 'POST' }),
  retryAnalysis: (id: string) => request<Analysis>(`/api/v1/analyses/${id}/retry`, { method: 'POST' }),

  findings: (jobId: string, filters: Record<string, string | number | undefined> = {}) =>
    request<Page<Finding>>(`/api/v1/analyses/${jobId}/findings${queryString({ limit: 500, ...filters })}`),
  metrics: (jobId: string, filters: Record<string, string | number | undefined> = {}) =>
    request<Page<MetricRecord>>(`/api/v1/analyses/${jobId}/metrics${queryString({ limit: 500, ...filters })}`),
  predictions: (jobId: string, filters: Record<string, string | number | boolean | undefined> = {}) =>
    request<Page<Prediction>>(`/api/v1/analyses/${jobId}/predictions${queryString({ limit: 500, ...filters })}`),
  explanations: (jobId: string) => request<Page<Explanation>>(`/api/v1/analyses/${jobId}/explanations?limit=500`),
  recommendations: (jobId: string, filters: Record<string, string | number | undefined> = {}) =>
    request<Page<Recommendation>>(`/api/v1/analyses/${jobId}/recommendations${queryString({ limit: 500, ...filters })}`),
  events: (jobId: string) => request<Page<JobEvent>>(`/api/v1/analyses/${jobId}/events?limit=500`),
  reports: (jobId: string) => request<Page<GeneratedReport>>(`/api/v1/analyses/${jobId}/reports?limit=100`),
  createReport: (jobId: string, format: ReportFormat) => request<GeneratedReport>(`/api/v1/analyses/${jobId}/reports`, { method: 'POST', body: JSON.stringify({ format }) }),
  downloadReport: (id: string) => download(`/api/v1/reports/${id}/download`),

  models: (filters: { smell?: string; enabled?: boolean } = {}) =>
    request<Page<ModelArtifact>>(`/api/v1/models${queryString({ limit: 500, ...filters })}`),
  setModelEnabled: (id: string, enabled: boolean) =>
    request<ModelArtifact>(`/api/v1/models/${id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }),
  deleteModel: (id: string) => request<void>(`/api/v1/models/${id}`, { method: 'DELETE' }),
}
