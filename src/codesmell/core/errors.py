"""Exception hierarchy.

Every failure the platform can produce is a subclass of :class:`CodeSmellError`
and carries a stable ``code``. The API layer maps ``code`` to an HTTP status and
an error envelope, so no handler ever needs to string-match on a message.
"""

from __future__ import annotations

from typing import Any


class CodeSmellError(Exception):
    """Base class for every error raised by this package."""

    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


class ConfigurationError(CodeSmellError):
    """The application is misconfigured and cannot start or serve safely."""

    code = "configuration_error"
    http_status = 500


class RegistryError(CodeSmellError):
    """A plugin registry was used incorrectly."""

    code = "registry_error"
    http_status = 500


class DuplicateRegistrationError(RegistryError):
    code = "duplicate_registration"


class UnknownPluginError(RegistryError):
    code = "unknown_plugin"
    http_status = 400


class IngestionError(CodeSmellError):
    """Base class for all intake failures."""

    code = "ingestion_error"
    http_status = 400


class UnsupportedSourceError(IngestionError):
    code = "unsupported_source"


class ArchiveError(IngestionError):
    code = "archive_error"


class CorruptArchiveError(ArchiveError):
    code = "corrupt_archive"


class ArchiveTooLargeError(ArchiveError):
    code = "archive_too_large"
    http_status = 413


class UnsafeArchiveMemberError(ArchiveError):
    """An archive member tried to escape the extraction root or was hostile."""

    code = "unsafe_archive_member"


class RepositoryError(IngestionError):
    code = "repository_error"


class InvalidRepositoryUrlError(RepositoryError):
    code = "invalid_repository_url"


class RepositoryFetchError(RepositoryError):
    code = "repository_fetch_failed"
    http_status = 502


class RepositoryTimeoutError(RepositoryFetchError):
    code = "repository_fetch_timeout"
    http_status = 504


class EmptyProjectError(IngestionError):
    """Nothing analysable survived filtering."""

    code = "empty_project"


class WorkspaceError(CodeSmellError):
    code = "workspace_error"
    http_status = 500


class PathEscapeError(WorkspaceError):
    """A resolved path fell outside its containing workspace."""

    code = "path_escape"
