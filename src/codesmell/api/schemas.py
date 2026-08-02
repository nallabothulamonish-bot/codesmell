"""Pydantic request and response contracts for the M6 API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class GitProjectCreate(BaseModel):
    url: HttpUrl
    name: str | None = Field(default=None, max_length=160)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ProjectOut(ApiModel):
    id: str
    name: str
    source_type: str
    source_url: str | None
    original_filename: str | None
    content_sha256: str | None
    fingerprint: str | None
    status: str
    inventory_summary: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class AnalysisCreate(BaseModel):
    analysis_kind: Literal["rule", "ml", "hybrid"] = "rule"
    threshold_mode: Literal["absolute", "percentile"] = "absolute"
    min_severity: Literal["low", "medium", "high", "critical"] = "low"
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    model_ids: list[str] | None = Field(default=None, max_length=50)
    explain_predictions: bool = True

    @field_validator("model_ids")
    @classmethod
    def _unique_models(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("model_ids must not contain duplicates")
        return cleaned or None


class AnalysisOut(ApiModel):
    id: str
    project_id: str
    status: str
    analysis_kind: str
    threshold_mode: str
    min_severity: str
    progress: int
    progress_message: str
    attempts: int
    max_attempts: int
    cancel_requested: bool
    locked_by: str | None
    queued_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    summary: dict[str, Any] | None
    model_ids: list[str] | None
    explain_predictions: bool
    created_at: datetime
    updated_at: datetime


class ModelArtifactOut(ApiModel):
    id: str
    name: str
    smell_type: str
    entity_type: str
    model_kind: str
    model_sha256: str
    threshold: float
    feature_names: list[str]
    model_card: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ModelStateUpdate(BaseModel):
    enabled: bool


class PredictionOut(ApiModel):
    id: int
    job_id: str
    model_id: str
    entity_id: str
    smell_type: str
    prediction: bool
    probability: float
    threshold: float
    confidence: float
    uncertainty: float
    qualified_name: str
    entity_type: str
    relative_path: str
    start_line: int
    end_line: int
    created_at: datetime


class ExplanationOut(ApiModel):
    id: int
    prediction_id: int
    method: str
    base_value: float | None
    output_value: float | None
    top_features: list[dict[str, Any]]
    warning: str | None
    created_at: datetime


class RecommendationOut(ApiModel):
    id: int
    job_id: str
    prediction_id: int
    entity_id: str
    smell_type: str
    priority: str
    title: str
    summary: str
    actions: list[str]
    evidence: list[dict[str, Any]]
    validation_steps: list[str]
    created_at: datetime


class FindingOut(ApiModel):
    id: int
    job_id: str
    entity_id: str
    smell_type: str
    severity: str
    confidence: float
    detector: str
    qualified_name: str
    entity_type: str
    relative_path: str
    start_line: int
    end_line: int
    threshold_mode: str
    rationale: str
    evidence: list[dict[str, Any]]
    references: list[str]


class MetricOut(ApiModel):
    id: int
    job_id: str
    entity_id: str
    entity_type: str
    qualified_name: str
    relative_path: str
    start_line: int
    end_line: int
    language: str
    metrics: dict[str, float]


class JobEventOut(ApiModel):
    id: int
    job_id: str
    event_type: str
    message: str
    details: dict[str, Any] | None
    created_at: datetime


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Message(BaseModel):
    message: str


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: "UserOut"


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=8, max_length=512)
    role: Literal["admin", "analyst", "viewer"] = "viewer"
    enabled: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    role: Literal["admin", "analyst", "viewer"] | None = None
    enabled: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=512)


class UserOut(ApiModel):
    id: str
    email: str
    display_name: str
    role: str
    enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReportCreate(BaseModel):
    format: Literal["json", "csv", "html", "pdf"]
    title: str | None = Field(default=None, max_length=255)


class ReportOut(ApiModel):
    id: str
    job_id: str
    requested_by: str | None
    format: str
    status: str
    title: str
    filename: str | None
    media_type: str | None
    size_bytes: int | None
    content_sha256: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class AuditEventOut(ApiModel):
    id: int
    actor_user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    request_id: str | None
    details: dict[str, Any] | None
    created_at: datetime

