"""Application settings.

Every value is overridable by environment variable with the ``CODESMELL_``
prefix, and nested groups use ``__`` as the delimiter, e.g.::

    CODESMELL_INGESTION__MAX_ARCHIVE_BYTES=52428800
    CODESMELL_LOGGING__LEVEL=DEBUG

Settings are cached; call :func:`get_settings.cache_clear` in tests.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MB = 1024 * 1024


class IngestionSettings(BaseSettings):
    """Hard limits applied to every uploaded archive and cloned repository.

    These are the controls that stop a zip bomb, a zip-slip archive or a
    runaway monorepo from taking down a public deployment. They are settings
    rather than constants because a research deployment analysing Apache-scale
    projects needs different ceilings than a shared demo instance.
    """

    max_archive_bytes: int = Field(default=200 * _MB, gt=0)
    max_uncompressed_bytes: int = Field(default=1024 * _MB, gt=0)
    max_member_bytes: int = Field(default=16 * _MB, gt=0)
    max_members: int = Field(default=50_000, gt=0)
    max_compression_ratio: float = Field(default=120.0, gt=1.0)

    max_source_file_bytes: int = Field(default=4 * _MB, gt=0)
    max_source_files: int = Field(default=25_000, gt=0)

    allowed_archive_suffixes: tuple[str, ...] = (".zip",)

    git_clone_timeout_seconds: float = Field(default=180.0, gt=0)
    git_allowed_hosts: tuple[str, ...] = (
        "github.com",
        "gitlab.com",
        "bitbucket.org",
    )
    git_allow_any_host: bool = False

    @model_validator(mode="after")
    def _check_limit_coherence(self) -> IngestionSettings:
        if self.max_member_bytes > self.max_uncompressed_bytes:
            raise ValueError(
                "max_member_bytes cannot exceed max_uncompressed_bytes"
            )
        if self.max_archive_bytes > self.max_uncompressed_bytes:
            raise ValueError(
                "max_archive_bytes cannot exceed max_uncompressed_bytes"
            )
        return self


class LoggingSettings(BaseSettings):
    level: str = "INFO"
    json_output: bool = True
    include_timestamp: bool = True

    @field_validator("level")
    @classmethod
    def _upper(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log level must be one of {sorted(allowed)}")
        return upper


class DatabaseSettings(BaseSettings):
    """SQLAlchemy connection and schema-management settings."""

    url: str = "sqlite:///./codesmell.db"
    echo: bool = False
    pool_size: int = Field(default=10, gt=0)
    auto_migrate: bool = True


class ApiSettings(BaseSettings):
    """HTTP API and persistent upload-storage settings."""

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    root_path: str = ""
    storage_root: Path = Field(default=Path(".codesmell-data"))
    max_upload_bytes: int = Field(default=200 * _MB, gt=0)
    allowed_upload_suffixes: tuple[str, ...] = (".zip", ".py")
    cors_origins: tuple[str, ...] = ()


class WorkerSettings(BaseSettings):
    """Database-backed analysis-worker behaviour."""

    poll_interval_seconds: float = Field(default=2.0, ge=0.1)
    stale_after_seconds: int = Field(default=900, ge=30)
    heartbeat_interval_seconds: int = Field(default=15, ge=1)
    default_max_attempts: int = Field(default=3, ge=1, le=20)


class ExplainabilitySettings(BaseSettings):
    """M7 local-attribution and recommendation controls."""

    top_features: int = Field(default=8, ge=1, le=50)
    prefer_shap: bool = True
    recommendations_for_positive_only: bool = True


class SecuritySettings(BaseSettings):
    """Authentication, authorization and HTTP hardening controls."""

    auth_enabled: bool = False
    jwt_secret: SecretStr = SecretStr("development-only-change-me-please")
    jwt_issuer: str = "codesmell"
    jwt_audience: str = "codesmell-api"
    access_token_minutes: int = Field(default=60, ge=5, le=1440)
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None
    bootstrap_admin_name: str = "CodeSmell Administrator"
    docs_enabled: bool = True
    trusted_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver")
    force_https: bool = False
    content_security_policy: str = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    )


class ReportSettings(BaseSettings):
    """Stored analysis-report controls."""

    max_rows_per_section: int = Field(default=5000, ge=100, le=100000)
    pdf_max_findings: int = Field(default=300, ge=10, le=5000)
    pdf_max_predictions: int = Field(default=300, ge=10, le=5000)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CODESMELL_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "codesmell"
    environment: str = "development"
    debug: bool = False

    rules_path: Path | None = Field(
        default=None,
        description="Custom rule YAML. Defaults to the bundled rule set.",
    )

    workspace_root: Path = Field(default=Path(".codesmell-workspaces"))
    keep_workspaces: bool = Field(
        default=False,
        description="Skip workspace teardown. Debugging only -- leaks disk.",
    )

    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    explainability: ExplainabilitySettings = Field(default_factory=ExplainabilitySettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    reports: ReportSettings = Field(default_factory=ReportSettings)

    @field_validator("environment")
    @classmethod
    def _known_environment(cls, value: str) -> str:
        allowed = {"development", "test", "staging", "production"}
        if value not in allowed:
            raise ValueError(f"environment must be one of {sorted(allowed)}")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment == "production":
            if self.debug:
                raise ValueError("debug must be off in production")
            if self.keep_workspaces:
                raise ValueError("keep_workspaces must be off in production")
            if self.ingestion.git_allow_any_host:
                raise ValueError(
                    "git_allow_any_host must be off in production; "
                    "set ingestion.git_allowed_hosts instead"
                )
            if self.database.auto_migrate:
                raise ValueError(
                    "database.auto_migrate must be off in production; "
                    "run `codesmell db upgrade` during deployment"
                )
            if not self.security.auth_enabled:
                raise ValueError("security.auth_enabled must be on in production")
            if len(self.security.jwt_secret.get_secret_value()) < 32:
                raise ValueError("security.jwt_secret must contain at least 32 characters")
            if self.security.jwt_secret.get_secret_value().startswith("development-only"):
                raise ValueError("replace the development JWT secret in production")
            if "*" in self.api.cors_origins:
                raise ValueError("wildcard CORS origins are forbidden in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
