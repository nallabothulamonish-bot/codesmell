"""Structured logging.

Analyses run in background workers, so every log line must carry the job it
belongs to or the logs are unusable. ``job_id`` is stored in a
:class:`contextvars.ContextVar`, which is coroutine- and thread-safe, and
injected by a filter rather than passed by every call site.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from codesmell.config.settings import LoggingSettings

_job_id: ContextVar[str | None] = ContextVar("codesmell_job_id", default=None)

#: Attributes present on every LogRecord; anything else is treated as an extra.
_RESERVED = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName", "job_id"}


@contextmanager
def job_context(job_id: str) -> Iterator[None]:
    """Bind ``job_id`` to every log record emitted inside the block."""
    token = _job_id.set(job_id)
    try:
        yield
    finally:
        _job_id.reset(token)


def current_job_id() -> str | None:
    return _job_id.get()


class JobIdFilter(logging.Filter):
    """Attaches the ambient job id to each record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.job_id = _job_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """Emits one JSON object per line, suitable for log aggregation."""

    def __init__(self, *, include_timestamp: bool = True) -> None:
        super().__init__()
        self.include_timestamp = include_timestamp

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if self.include_timestamp:
            payload["timestamp"] = datetime.fromtimestamp(
                record.created, tz=UTC
            ).isoformat()

        job_id = getattr(record, "job_id", None)
        if job_id:
            payload["job_id"] = job_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = _coerce(value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable format for local development."""

    def __init__(self, *, include_timestamp: bool = True) -> None:
        fmt = "%(levelname)-8s %(name)s: %(message)s"
        if include_timestamp:
            fmt = "%(asctime)s " + fmt
        super().__init__(fmt=fmt, datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        job_id = getattr(record, "job_id", None)
        return f"{base}  [job={job_id}]" if job_id else base


def safe_extra(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Make a domain dict safe to pass as ``extra=``.

    ``logging`` raises ``KeyError`` if an extra collides with a built-in
    ``LogRecord`` attribute, and domain summaries legitimately contain keys
    like ``name`` and ``module``. Colliding keys are prefixed rather than
    dropped, so no information is lost from the log line.
    """
    return {
        (f"ctx_{key}" if key in _RESERVED else key): value
        for key, value in fields.items()
    }


def _coerce(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


def configure_logging(settings: LoggingSettings | None = None) -> None:
    """Install handlers on the root logger. Idempotent."""
    cfg = settings or LoggingSettings()

    # Logs go to stderr so that stdout carries only the command's data.
    # Anything else makes `codesmell detect --json | jq` fail.
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.addFilter(JobIdFilter())
    handler.setFormatter(
        JsonFormatter(include_timestamp=cfg.include_timestamp)
        if cfg.json_output
        else ConsoleFormatter(include_timestamp=cfg.include_timestamp)
    )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
        existing.close()
    root.addHandler(handler)
    root.setLevel(cfg.level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
