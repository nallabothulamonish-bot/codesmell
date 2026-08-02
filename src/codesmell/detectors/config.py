"""Rule configuration loading.

Rules are validated against the live :class:`FeatureSchema` at load time, not
at detection time. A rule referring to ``lcom`` when the metric is called
``lcom_hs`` would otherwise silently never fire: the detector would run, find
nothing, and report a clean project. Failing at startup is the only safe
behaviour.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from codesmell.config.logging import get_logger
from codesmell.core.enums import EntityType, Severity, SmellType
from codesmell.detectors.rules import (
    DEFAULT_SEVERITY_MULTIPLIERS,
    Combinator,
    Condition,
    Exemption,
    Operator,
    RuleConfigError,
    SmellRule,
)
from codesmell.metrics.engine import FeatureSchema

logger = get_logger(__name__)

SUPPORTED_VERSION = 1
DEFAULT_RULES_RESOURCE = "default_rules.yaml"


def default_rules_path() -> Path:
    """Filesystem path of the bundled rule set."""
    return Path(
        str(resources.files("codesmell.detectors").joinpath(DEFAULT_RULES_RESOURCE))
    )


def load_rules(
    source: Path | str | None = None, *, schema: FeatureSchema | None = None
) -> tuple[SmellRule, ...]:
    """Load and validate rules from YAML.

    Args:
        source: Path to a rule file. Defaults to the bundled rule set.
        schema: If given, every metric named by a rule must exist in it for the
            declared entity type.

    Raises:
        RuleConfigError: on a malformed file, an unknown smell or operator, or
            a metric the schema does not define.
    """
    path = Path(source) if source is not None else default_rules_path()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuleConfigError(
            f"rule file could not be read: {exc}", path=str(path)
        ) from exc
    except yaml.YAMLError as exc:
        raise RuleConfigError(
            f"rule file is not valid YAML: {exc}", path=str(path)
        ) from exc

    if not isinstance(raw, dict):
        raise RuleConfigError("rule file must be a mapping", path=str(path))

    version = raw.get("version")
    if version != SUPPORTED_VERSION:
        raise RuleConfigError(
            "unsupported rule file version",
            found=version,
            supported=SUPPORTED_VERSION,
        )

    smells = raw.get("smells")
    if not isinstance(smells, dict) or not smells:
        raise RuleConfigError("rule file declares no smells", path=str(path))

    shared = _shared_exemptions(raw.get("exemption_sets"))
    rules = tuple(
        _build_rule(name, body, schema, shared)
        for name, body in sorted(smells.items())
    )
    logger.debug(
        "rules loaded", extra={"path": path.name, "rules": len(rules)}
    )
    return rules


def _build_rule(
    name: str,
    body: Any,
    schema: FeatureSchema | None,
    shared: Mapping[str, Exemption],
) -> SmellRule:
    if not isinstance(body, dict):
        raise RuleConfigError("rule body must be a mapping", smell=name)

    try:
        smell_type = SmellType(name)
    except ValueError:
        raise RuleConfigError(
            "unknown smell name",
            smell=name,
            known=[s.value for s in SmellType],
        ) from None

    entity_type = _entity_type(body.get("entity_type"), name)
    combinator = _combinator(body.get("combinator", "all"), name)
    conditions = _conditions(body.get("conditions"), name, entity_type, schema)

    return SmellRule(
        exemption=_exemption(body.get("exempt_if"), name, shared),
        smell_type=smell_type,
        entity_type=entity_type,
        conditions=conditions,
        combinator=combinator,
        severity_multipliers=_severity_multipliers(body.get("severity"), name),
        rationale=str(body.get("rationale", "")).strip(),
        references=tuple(str(r) for r in body.get("references", []) or []),
    )


def _shared_exemptions(value: Any) -> dict[str, Exemption]:
    """Named exemption blocks rules can reuse by name."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuleConfigError("exemption_sets must be a mapping")
    return {
        str(key): _exemption_from_mapping(body, f"exemption_sets.{key}")
        for key, body in value.items()
    }


def _exemption(
    value: Any, name: str, shared: Mapping[str, Exemption]
) -> Exemption:
    """Build a rule's exemption, merging any referenced shared sets."""
    if value is None:
        return Exemption()
    if isinstance(value, str):
        value = {"use": [value]}
    if not isinstance(value, dict):
        raise RuleConfigError("exempt_if must be a mapping", smell=name)

    merged = _exemption_from_mapping(value, name)

    for reference in value.get("use", []) or []:
        inherited = shared.get(str(reference))
        if inherited is None:
            raise RuleConfigError(
                "exempt_if references an undefined exemption set",
                smell=name,
                reference=reference,
                known=sorted(shared),
            )
        merged = Exemption(
            base_class_patterns=merged.base_class_patterns
            + inherited.base_class_patterns,
            decorator_patterns=merged.decorator_patterns
            + inherited.decorator_patterns,
            name_patterns=merged.name_patterns + inherited.name_patterns,
        )

    return merged


def _exemption_from_mapping(value: Any, name: str) -> Exemption:
    if not isinstance(value, dict):
        raise RuleConfigError("exemption must be a mapping", context=name)
    return Exemption(
        base_class_patterns=_patterns(value.get("base_class_matches"), name),
        decorator_patterns=_patterns(value.get("decorated_with"), name),
        name_patterns=_patterns(value.get("name_matches"), name),
    )


def _patterns(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RuleConfigError("exemption patterns must be a list", context=name)
    return tuple(str(item) for item in value)


def _entity_type(value: Any, name: str) -> EntityType:
    try:
        return EntityType(str(value))
    except ValueError:
        raise RuleConfigError(
            "unknown entity_type",
            smell=name,
            found=value,
            known=[e.value for e in EntityType],
        ) from None


def _combinator(value: Any, name: str) -> Combinator:
    try:
        return Combinator(str(value))
    except ValueError:
        raise RuleConfigError(
            "combinator must be 'all' or 'any'", smell=name, found=value
        ) from None


def _conditions(
    value: Any, name: str, entity_type: EntityType, schema: FeatureSchema | None
) -> tuple[Condition, ...]:
    if not isinstance(value, list) or not value:
        raise RuleConfigError("rule declares no conditions", smell=name)

    known = set(schema.names_for(entity_type)) if schema is not None else None
    conditions: list[Condition] = []

    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise RuleConfigError(
                "condition must be a mapping", smell=name, index=index
            )

        metric = str(entry.get("metric", "")).strip()
        if not metric:
            raise RuleConfigError(
                "condition is missing a metric", smell=name, index=index
            )
        if known is not None and metric not in known:
            # A typo here would make the detector silently never fire and
            # report a clean project. It has to fail at load time.
            raise RuleConfigError(
                "condition names a metric the feature schema does not define",
                smell=name,
                metric=metric,
                entity_type=entity_type.value,
                available=sorted(known),
            )

        try:
            operator = Operator(str(entry.get("op", "")))
        except ValueError:
            raise RuleConfigError(
                "unknown operator",
                smell=name,
                metric=metric,
                found=entry.get("op"),
                known=[o.value for o in Operator],
            ) from None

        if "absolute" not in entry:
            raise RuleConfigError(
                "condition is missing an absolute threshold",
                smell=name,
                metric=metric,
            )

        conditions.append(
            Condition(
                metric=metric,
                operator=operator,
                absolute=float(entry["absolute"]),
                percentile=(
                    float(entry["percentile"])
                    if entry.get("percentile") is not None
                    else None
                ),
            )
        )

    return tuple(conditions)


def _severity_multipliers(value: Any, name: str) -> Mapping[Severity, float]:
    if value is None:
        return DEFAULT_SEVERITY_MULTIPLIERS
    if not isinstance(value, dict):
        raise RuleConfigError("severity must be a mapping", smell=name)

    multipliers: dict[Severity, float] = {}
    for key, raw in value.items():
        try:
            severity = Severity(str(key))
        except ValueError:
            raise RuleConfigError(
                "unknown severity band",
                smell=name,
                found=key,
                known=[s.value for s in Severity],
            ) from None
        if severity is Severity.NONE:
            raise RuleConfigError(
                "severity band 'none' cannot have a multiplier", smell=name
            )
        multipliers[severity] = float(raw)

    return multipliers if multipliers else DEFAULT_SEVERITY_MULTIPLIERS
