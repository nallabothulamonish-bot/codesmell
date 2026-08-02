export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Project {
  id: string
  name: string
  source_type: 'upload' | 'github' | string
  source_url: string | null
  original_filename: string | null
  content_sha256: string | null
  fingerprint: string | null
  status: string
  inventory_summary: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export type AnalysisKind = 'rule' | 'ml' | 'hybrid'
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | string

export interface Analysis {
  id: string
  project_id: string
  status: JobStatus
  analysis_kind: AnalysisKind
  threshold_mode: 'absolute' | 'percentile'
  min_severity: Severity
  progress: number
  progress_message: string
  attempts: number
  max_attempts: number
  cancel_requested: boolean
  locked_by: string | null
  queued_at: string
  started_at: string | null
  completed_at: string | null
  error_code: string | null
  error_message: string | null
  summary: Record<string, unknown> | null
  model_ids: string[] | null
  explain_predictions: boolean
  created_at: string
  updated_at: string
}

export type Severity = 'low' | 'medium' | 'high' | 'critical'

export interface Evidence {
  metric?: string
  feature?: string
  value?: number
  threshold?: number
  contribution?: number
  direction?: string
  [key: string]: unknown
}

export interface Finding {
  id: number
  job_id: string
  entity_id: string
  smell_type: string
  severity: Severity
  confidence: number
  detector: string
  qualified_name: string
  entity_type: string
  relative_path: string
  start_line: number
  end_line: number
  threshold_mode: string
  rationale: string
  evidence: Evidence[]
  references: string[]
}

export interface MetricRecord {
  id: number
  job_id: string
  entity_id: string
  entity_type: string
  qualified_name: string
  relative_path: string
  start_line: number
  end_line: number
  language: string
  metrics: Record<string, number>
}

export interface ModelArtifact {
  id: string
  name: string
  smell_type: string
  entity_type: string
  model_kind: string
  model_sha256: string
  threshold: number
  feature_names: string[]
  model_card: Record<string, unknown>
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface Prediction {
  id: number
  job_id: string
  model_id: string
  entity_id: string
  smell_type: string
  prediction: boolean
  probability: number
  threshold: number
  confidence: number
  uncertainty: number
  qualified_name: string
  entity_type: string
  relative_path: string
  start_line: number
  end_line: number
  created_at: string
}

export interface ExplanationFeature {
  feature: string
  value: number
  contribution: number
  direction?: string
  importance?: number
  rank?: number
  [key: string]: unknown
}

export interface Explanation {
  id: number
  prediction_id: number
  method: string
  base_value: number | null
  output_value: number | null
  top_features: ExplanationFeature[]
  warning: string | null
  created_at: string
}

export interface Recommendation {
  id: number
  job_id: string
  prediction_id: number
  entity_id: string
  smell_type: string
  priority: Severity | string
  title: string
  summary: string
  actions: string[]
  evidence: Evidence[]
  validation_steps: string[]
  created_at: string
}

export interface JobEvent {
  id: number
  job_id: string
  event_type: string
  message: string
  details: Record<string, unknown> | null
  created_at: string
}

export interface AnalysisCreate {
  analysis_kind: AnalysisKind
  threshold_mode: 'absolute' | 'percentile'
  min_severity: Severity
  model_ids?: string[]
  explain_predictions: boolean
}

export interface User {
  id: string
  email: string
  display_name: string
  role: 'admin' | 'analyst' | 'viewer' | string
  enabled: boolean
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_at: string
  user: User
}

export type ReportFormat = 'json' | 'csv' | 'html' | 'pdf'

export interface GeneratedReport {
  id: string
  job_id: string
  requested_by: string | null
  format: ReportFormat
  status: 'generating' | 'ready' | 'failed' | string
  title: string
  filename: string | null
  media_type: string | null
  size_bytes: number | null
  content_sha256: string | null
  error_message: string | null
  created_at: string
  completed_at: string | null
}

export interface AuditEvent {
  id: number
  actor_user_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  request_id: string | null
  details: Record<string, unknown> | null
  created_at: string
}
