"""The rule model for threshold-based smell detection.

A rule is a boolean combination of metric conditions. Two things make this more
than a pile of ``if`` statements:

**Threshold mode.** Every condition carries both an absolute threshold from the
literature and a project-relative percentile. Absolute thresholds do not
transfer -- a 200-line class is unremarkable in one codebase and an outlier in
another -- which is the same effect that drives the cross-project accuracy drop
in the ML pipeline. Supporting both modes here gives the paper two rule-based
baselines and an early, cheap read on how much project-relative framing is
worth before the ML work starts.

**Severity by excess.** Severity is derived from how far past the threshold an
entity sits, as a multiple. That keeps the Low/Medium/High/Critical badge
grounded in something measurable instead of invented.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from codesmell.core.enums import EntityType, Severity, SmellType
from codesmell.core.errors import CodeSmellError
from codesmell.core.models import CodeEntity, EntityFacts


class RuleConfigError(CodeSmellError):
    """A rule definition is malformed or refers to an unknown metric."""

    code = "rule_config_error"
    http_status = 400


class Operator(StrEnum):
    """Comparison direction of a condition."""

    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="

    @property
    def is_upper_bound(self) -> bool:
        """Whether crossing the threshold means going *below* it.

        Determines how excess is measured: for ``wmc > 47`` excess grows as the
        value rises, for ``cohesion < 0.3`` it grows as the value falls.
        """
        return self in (Operator.LT, Operator.LTE)

    def holds(self, value: float, threshold: float) -> bool:
        if self is Operator.GT:
            return value > threshold
        if self is Operator.GTE:
            return value >= threshold
        if self is Operator.LT:
            return value < threshold
        return value <= threshold


class ThresholdMode(StrEnum):
    """Where a condition's threshold comes from."""

    ABSOLUTE = "absolute"
    """Fixed values from the software engineering literature."""

    PERCENTILE = "percentile"
    """Per-project distribution, recomputed for every analysed project."""


class Combinator(StrEnum):
    ALL = "all"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class Condition:
    """One metric comparison within a rule."""

    metric: str
    operator: Operator
    absolute: float
    percentile: float | None = None

    def __post_init__(self) -> None:
        if self.percentile is not None and not 0.0 < self.percentile < 100.0:
            raise RuleConfigError(
                "percentile must lie strictly between 0 and 100",
                metric=self.metric,
                percentile=self.percentile,
            )

    def supports(self, mode: ThresholdMode) -> bool:
        return mode is ThresholdMode.ABSOLUTE or self.percentile is not None

    def excess(self, value: float, threshold: float) -> float:
        """How far past the threshold ``value`` sits, as a multiple.

        1.0 means exactly at the threshold; 2.0 means twice as far into the
        smelly direction. For upper-bound conditions the ratio is inverted, so
        "further past the threshold" always means a larger number regardless of
        which way the comparison points.

        Guarded against a zero threshold, which is legitimate for metrics like
        ``lcom_hs`` and would otherwise divide by zero.
        """
        if self.operator.is_upper_bound:
            if value <= 0.0:
                return float("inf") if threshold > 0.0 else 1.0
            return max(threshold / value, 0.0)
        if threshold <= 0.0:
            return 1.0 + value
        return value / threshold


@dataclass(frozen=True, slots=True)
class Exemption:
    """Structural reasons an entity should never be flagged by a rule.

    Threshold detectors have poor precision without these, and the reason is
    not a tuning problem -- it is that some classes are *supposed* to look the
    way the rule punishes. An exception subclass is meant to be three lines
    with no methods; an enum is meant to be nothing but data; a
    ``@staticmethod`` has no ``self`` to be envious with. Flagging them is not
    a borderline call, it is a false positive by construction.

    Patterns are full-match regular expressions over the entity's declared base
    class names, its decorators, and its own name.
    """

    base_class_patterns: tuple[str, ...] = ()
    decorator_patterns: tuple[str, ...] = ()
    name_patterns: tuple[str, ...] = ()

    def reason(self, entity: CodeEntity, facts: EntityFacts) -> str | None:
        """Why this entity is exempt, or ``None`` if it is not."""
        for pattern in self.base_class_patterns:
            for base in facts.base_names:
                if _matches(pattern, base):
                    return f"inherits from {base}"

        for pattern in self.decorator_patterns:
            for decorator in facts.decorators:
                if _matches(pattern, decorator):
                    return f"decorated with @{decorator}"

        for pattern in self.name_patterns:
            if _matches(pattern, entity.name):
                return f"name matches {pattern}"

        return None

    @property
    def is_empty(self) -> bool:
        return not (
            self.base_class_patterns
            or self.decorator_patterns
            or self.name_patterns
        )


def _matches(pattern: str, value: str) -> bool:
    try:
        return re.fullmatch(pattern, value) is not None
    except re.error as exc:
        raise RuleConfigError(
            f"invalid exemption pattern: {exc}", pattern=pattern
        ) from exc


#: Bands used when a rule does not override them. A finding exactly at the
#: threshold is Low; four times past it is Critical.
DEFAULT_SEVERITY_MULTIPLIERS: Mapping[Severity, float] = {
    Severity.LOW: 1.0,
    Severity.MEDIUM: 1.5,
    Severity.HIGH: 2.5,
    Severity.CRITICAL: 4.0,
}


@dataclass(frozen=True, slots=True)
class SmellRule:
    """A named, documented rule for one smell.

    ``rationale`` and ``references`` are not decoration: a rule-based detector
    that cannot say why it fired is useless as a paper baseline and useless in
    the UI, where the whole product promise is explanation.
    """

    smell_type: SmellType
    entity_type: EntityType
    conditions: tuple[Condition, ...]
    combinator: Combinator = Combinator.ALL
    severity_multipliers: Mapping[Severity, float] = field(
        default_factory=lambda: DEFAULT_SEVERITY_MULTIPLIERS
    )
    exemption: Exemption = field(default_factory=Exemption)
    rationale: str = ""
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.conditions:
            raise RuleConfigError(
                "rule has no conditions", smell=self.smell_type.value
            )
        if self.smell_type.entity_type is not self.entity_type:
            raise RuleConfigError(
                "rule entity type contradicts the smell's declared unit of "
                "analysis",
                smell=self.smell_type.value,
                declared=self.entity_type.value,
                expected=self.smell_type.entity_type.value,
            )
    def supports(self, mode: ThresholdMode) -> bool:
        """Whether every condition can be evaluated in this threshold mode."""
        return all(condition.supports(mode) for condition in self.conditions)

    def exempts(self, entity: CodeEntity, facts: EntityFacts) -> str | None:
        return self.exemption.reason(entity, facts)

    def severity_for(self, excess: float) -> Severity:
        """Map an excess multiple onto an ordinal severity band."""
        ranked = sorted(
            self.severity_multipliers.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        for severity, multiplier in ranked:
            if excess >= multiplier:
                return severity
        return Severity.LOW
