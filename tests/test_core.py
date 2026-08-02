"""Domain layer tests: registry, models, enums, logging."""

from __future__ import annotations

import json
import logging

import pytest

from codesmell.config.logging import (
    JsonFormatter,
    configure_logging,
    current_job_id,
    job_context,
)
from codesmell.config.settings import LoggingSettings
from codesmell.core.enums import EntityType, Language, Severity, SmellType
from codesmell.core.errors import (
    DuplicateRegistrationError,
    UnknownPluginError,
)
from codesmell.core.models import (
    CodeEntity,
    FeatureVector,
    SmellPrediction,
    SourceFile,
)
from codesmell.core.registry import Registry

# --------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------- #


def test_registry_round_trip():
    registry: Registry[str, int] = Registry("thing")
    registry.register("a", 1)
    assert registry.get("a") == 1
    assert "a" in registry
    assert len(registry) == 1


def test_duplicate_registration_fails_loudly():
    """A typo'd plugin key must not silently shadow a working plugin."""
    registry: Registry[str, int] = Registry("thing")
    registry.register("a", 1)
    with pytest.raises(DuplicateRegistrationError):
        registry.register("a", 2)


def test_duplicate_registration_allowed_when_replacing():
    registry: Registry[str, int] = Registry("thing")
    registry.register("a", 1)
    registry.register("a", 2, replace=True)
    assert registry.get("a") == 2


def test_unknown_key_lists_what_is_available():
    registry: Registry[str, int] = Registry("thing")
    registry.register("a", 1)
    with pytest.raises(UnknownPluginError) as exc_info:
        registry.get("b")
    assert exc_info.value.details["available"] == ["a"]


def test_find_returns_none_instead_of_raising():
    registry: Registry[str, int] = Registry("thing")
    assert registry.find("missing") is None


def test_decorator_registration_returns_the_object():
    registry: Registry[str, type] = Registry("thing")

    @registry.decorator("widget")
    class Widget:
        pass

    assert registry.get("widget") is Widget


# --------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------- #


def test_severity_is_ordered():
    assert Severity.LOW < Severity.CRITICAL
    assert sorted([Severity.HIGH, Severity.NONE, Severity.MEDIUM]) == [
        Severity.NONE,
        Severity.MEDIUM,
        Severity.HIGH,
    ]


def test_every_smell_declares_its_unit_of_analysis():
    """Class and method smells have disjoint feature spaces; the mapping
    must be total or a smell would silently land in the wrong model."""
    for smell in SmellType:
        assert smell.entity_type in (EntityType.CLASS, EntityType.METHOD)


def test_only_python_is_supported_at_this_milestone():
    assert Language.PYTHON.is_supported
    assert not Language.JAVA.is_supported


# --------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------- #


def test_source_file_rejects_absolute_path():
    with pytest.raises(ValueError, match="must be relative"):
        SourceFile(
            relative_path="/etc/passwd",
            language=Language.PYTHON,
            size_bytes=1,
            line_count=1,
            sha256="0" * 64,
        )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("pkg/sub/mod.py", "pkg.sub.mod"),
        ("pkg/__init__.py", "pkg"),
        ("mod.py", "mod"),
    ],
)
def test_source_file_package_path(path: str, expected: str):
    source = SourceFile(
        relative_path=path,
        language=Language.PYTHON,
        size_bytes=1,
        line_count=1,
        sha256="0" * 64,
    )
    assert source.package_path == expected


def test_code_entity_rejects_inverted_line_span():
    with pytest.raises(ValueError, match="precedes"):
        CodeEntity(
            entity_id="e1",
            entity_type=EntityType.METHOD,
            name="f",
            qualified_name="m.f",
            relative_path="m.py",
            start_line=20,
            end_line=10,
            language=Language.PYTHON,
        )


def test_code_entity_line_span_is_inclusive():
    entity = CodeEntity(
        entity_id="e1",
        entity_type=EntityType.METHOD,
        name="f",
        qualified_name="m.f",
        relative_path="m.py",
        start_line=10,
        end_line=12,
        language=Language.PYTHON,
    )
    assert entity.line_span == 3


def test_feature_vector_names_are_sorted():
    vector = FeatureVector(
        entity_id="e1",
        entity_type=EntityType.CLASS,
        values={"wmc": 3.0, "cbo": 1.0, "lcom": 0.5},
    )
    assert vector.feature_names == ("cbo", "lcom", "wmc")
    assert vector.get("missing", -1.0) == -1.0


def test_prediction_rejects_confidence_outside_zero_one():
    with pytest.raises(ValueError, match="confidence"):
        SmellPrediction(
            entity_id="e1",
            smell_type=SmellType.GOD_CLASS,
            is_present=True,
            confidence=1.4,
        )


def test_absent_smell_cannot_carry_a_severity():
    """Guards the UI contract: no severity badge on a negative prediction."""
    with pytest.raises(ValueError, match="absent smell"):
        SmellPrediction(
            entity_id="e1",
            smell_type=SmellType.GOD_CLASS,
            is_present=False,
            confidence=0.2,
            severity=Severity.HIGH,
        )


# --------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------- #


def test_job_context_binds_and_unbinds():
    assert current_job_id() is None
    with job_context("job-42"):
        assert current_job_id() == "job-42"
    assert current_job_id() is None


def test_json_formatter_emits_extras_and_job_id():
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="analysis finished", args=(), exc_info=None,
    )
    record.job_id = "job-7"
    record.file_count = 42

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "analysis finished"
    assert payload["job_id"] == "job-7"
    assert payload["file_count"] == 42
    assert payload["level"] == "INFO"


def test_configure_logging_is_idempotent():
    configure_logging(LoggingSettings(level="INFO"))
    configure_logging(LoggingSettings(level="DEBUG"))
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


def test_safe_extra_renames_logrecord_collisions():
    """Regression: ProjectInventory.summary() has a 'name' key, which
    logging refuses as an extra and which crashed every inventory build."""
    from codesmell.config.logging import safe_extra

    result = safe_extra({"name": "sample", "module": "x", "file_count": 4})

    assert result == {"ctx_name": "sample", "ctx_module": "x", "file_count": 4}


def test_domain_summary_is_loggable(caplog):
    from codesmell.config.logging import safe_extra

    logger = logging.getLogger("codesmell.test")
    with caplog.at_level(logging.INFO):
        logger.info("built", extra=safe_extra({"name": "sample", "files": 3}))

    assert caplog.records[-1].ctx_name == "sample"


def test_logs_go_to_stderr_not_stdout():
    """stdout carries a command's data; anything else breaks
    `codesmell detect --json | jq`."""
    import sys

    configure_logging(LoggingSettings())
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is sys.stderr
