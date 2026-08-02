"""Rule-based smell detection.

.. warning::
   **These detectors are a baseline, not ground truth.**

   It is tempting -- especially with no labelled Python dataset available -- to
   run these rules over a corpus, treat the output as labels, and train a model
   on it. Do not. A model trained on rule output learns to reproduce the rules,
   nothing more. It will score near-perfectly on held-out data, transfer
   flawlessly across projects, and mean absolutely nothing, because the target
   it predicts is a deterministic function of the same features it is given.
   The resulting paper would be circular.

   What these detectors are legitimately for:

   * a **non-ML baseline** the trained model must beat to be worth anything;
   * a **sanity check** on the metrics engine -- if the rules flag classes that
     humans would not, a metric is probably wrong;
   * a **first pass for human labelling**, where the rules propose candidates
     and people adjudicate them. The human judgement is the label; the rule
     only decides what gets looked at.
   * **coverage** for languages and entity types with no training data at all.

Confidence is reported as 1.0 for every rule finding. That is not a probability
estimate -- it is the statement that the rule definitely fired. Calibrated
probabilities arrive with the ML detector at M5, and conflating the two would
put a fabricated number in front of a user.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from codesmell.config.logging import get_logger, safe_extra
from codesmell.core.enums import EntityType, Severity, SmellType
from codesmell.core.models import (
    CodeEntity,
    EntityFacts,
    FeatureVector,
    SmellPrediction,
)
from codesmell.core.ports import SmellDetector
from codesmell.detectors.rules import (
    Combinator,
    Condition,
    SmellRule,
    ThresholdMode,
)
from codesmell.detectors.thresholds import ThresholdTable
from codesmell.metrics.engine import AnalysisResult

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ConditionOutcome:
    """Why one condition passed or failed, for the explanation trail."""

    metric: str
    operator: str
    observed: float
    threshold: float
    satisfied: bool
    excess: float
    source: ThresholdMode

    def describe(self) -> str:
        verdict = "met" if self.satisfied else "not met"
        basis = (
            "project percentile"
            if self.source is ThresholdMode.PERCENTILE
            else "literature threshold"
        )
        return (
            f"{self.metric} = {self.observed:g} {self.operator} "
            f"{self.threshold:g} ({basis}): {verdict}"
        )


@dataclass(frozen=True, slots=True)
class Finding:
    """One detected smell, with everything needed to justify it."""

    entity: CodeEntity
    prediction: SmellPrediction
    outcomes: tuple[ConditionOutcome, ...]
    rationale: str
    references: tuple[str, ...]
    threshold_mode: ThresholdMode

    @property
    def smell_type(self) -> SmellType:
        return self.prediction.smell_type

    @property
    def severity(self) -> Severity:
        return self.prediction.severity

    def to_dict(self) -> dict[str, object]:
        """Serialisable form, for export and for the labelling workflow.

        Carries the full condition trail, not just the verdict: a human
        adjudicating this candidate needs to see what the rule actually
        measured, and a label produced without that context is not much better
        than the rule's own guess.
        """
        return {
            "smell": self.smell_type.value,
            "severity": self.severity.value,
            "entity": {
                "id": self.entity.entity_id,
                "qualified_name": self.entity.qualified_name,
                "type": self.entity.entity_type.value,
                "path": self.entity.relative_path,
                "start_line": self.entity.start_line,
                "end_line": self.entity.end_line,
            },
            "detector": self.prediction.model_name,
            "threshold_mode": self.threshold_mode.value,
            "conditions": [
                {
                    "metric": outcome.metric,
                    "operator": outcome.operator,
                    "observed": outcome.observed,
                    "threshold": outcome.threshold,
                    "satisfied": outcome.satisfied,
                    "threshold_source": outcome.source.value,
                }
                for outcome in self.outcomes
            ],
            "rationale": self.rationale,
            "references": list(self.references),
        }

    def explain(self) -> str:
        """A human-readable justification, built only from what was measured."""
        header = (
            f"{self.smell_type.value} in {self.entity.qualified_name} "
            f"({self.entity.relative_path}:{self.entity.start_line}) "
            f"-- severity {self.severity.value}"
        )
        conditions = "\n".join(f"  - {o.describe()}" for o in self.outcomes)
        parts = [header, conditions]
        if self.rationale:
            parts.append(f"  why this matters: {self.rationale}")
        return "\n".join(parts)


class RuleBasedDetector(SmellDetector):
    """Evaluates one :class:`SmellRule` against an entity's feature vector."""

    def __init__(
        self,
        rule: SmellRule,
        table: ThresholdTable,
        mode: ThresholdMode = ThresholdMode.ABSOLUTE,
    ) -> None:
        self._rule = rule
        self._table = table
        self._mode = mode

    @property
    def rule(self) -> SmellRule:
        return self._rule

    @property
    def smell_type(self) -> SmellType:
        return self._rule.smell_type

    @property
    def name(self) -> str:
        return f"rule:{self._rule.smell_type.value}:{self._mode.value}"

    def detect(
        self, entity: CodeEntity, features: FeatureVector
    ) -> SmellPrediction | None:
        finding = self.evaluate(entity, features)
        return finding.prediction if finding else None

    def evaluate(
        self,
        entity: CodeEntity,
        features: FeatureVector,
        facts: EntityFacts | None = None,
    ) -> Finding | None:
        """Evaluate the rule, returning a full :class:`Finding` when it fires."""
        if entity.entity_type is not self._rule.entity_type:
            return None

        # Structural exemptions run before thresholds: an exception subclass
        # is meant to be three lines, so flagging it is a false positive by
        # construction rather than a threshold that needs tuning.
        if facts is not None and self._rule.exempts(entity, facts):
            return None

        outcomes = tuple(
            self._evaluate_condition(condition, entity, features)
            for condition in self._rule.conditions
        )

        satisfied = [o for o in outcomes if o.satisfied]
        if self._rule.combinator is Combinator.ALL:
            fired = len(satisfied) == len(outcomes)
        else:
            fired = bool(satisfied)

        if not fired:
            return None

        # Severity comes from the weakest satisfied condition. Taking the
        # strongest would let one extreme metric mask an otherwise borderline
        # finding and inflate every severity to Critical.
        excesses = [o.excess for o in satisfied if o.excess != float("inf")]
        excess = min(excesses) if excesses else 1.0
        severity = self._rule.severity_for(excess)

        return Finding(
            entity=entity,
            prediction=SmellPrediction(
                entity_id=entity.entity_id,
                smell_type=self._rule.smell_type,
                is_present=True,
                confidence=1.0,  # rule satisfaction, not a calibrated probability
                severity=severity,
                model_name=self.name,
            ),
            outcomes=outcomes,
            rationale=self._rule.rationale,
            references=self._rule.references,
            threshold_mode=self._mode,
        )

    def _evaluate_condition(
        self, condition: Condition, entity: CodeEntity, features: FeatureVector
    ) -> ConditionOutcome:
        observed = features.get(condition.metric)
        threshold, source = self._threshold_for(condition, entity.entity_type)

        return ConditionOutcome(
            metric=condition.metric,
            operator=condition.operator.value,
            observed=observed,
            threshold=threshold,
            satisfied=condition.operator.holds(observed, threshold),
            excess=condition.excess(observed, threshold),
            source=source,
        )

    def _threshold_for(
        self, condition: Condition, entity_type: EntityType
    ) -> tuple[float, ThresholdMode]:
        if self._mode is ThresholdMode.PERCENTILE and condition.percentile:
            value = self._table.percentile(
                entity_type, condition.metric, condition.percentile
            )
            if value is not None:
                return value, ThresholdMode.PERCENTILE
            # Too few entities for a meaningful percentile: fall back rather
            # than flag the second-largest of six values as an outlier.
        return condition.absolute, ThresholdMode.ABSOLUTE


@dataclass(frozen=True, slots=True)
class DetectionReport:
    """Every finding from one detection run."""

    findings: tuple[Finding, ...]
    threshold_mode: ThresholdMode
    rules_applied: int
    entities_examined: int
    skipped_rules: Mapping[str, str] = field(default_factory=dict)

    def by_severity(self, severity: Severity) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is severity)

    def by_smell(self, smell_type: SmellType) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.smell_type is smell_type)

    def counts_by_smell(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.smell_type.value] = (
                counts.get(finding.smell_type.value, 0) + 1
            )
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def counts_by_severity(self) -> dict[str, int]:
        return {
            severity.value: len(self.by_severity(severity))
            for severity in Severity
            if severity is not Severity.NONE
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": self.summary(),
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def summary(self) -> dict[str, object]:
        return {
            "findings": len(self.findings),
            "threshold_mode": self.threshold_mode.value,
            "rules_applied": self.rules_applied,
            "entities_examined": self.entities_examined,
            "by_smell": self.counts_by_smell(),
            "by_severity": self.counts_by_severity(),
            "skipped_rules": len(self.skipped_rules),
        }


class DetectionEngine:
    """Runs a rule set over an analysis result."""

    def __init__(
        self,
        rules: Sequence[SmellRule],
        mode: ThresholdMode = ThresholdMode.ABSOLUTE,
    ) -> None:
        self._rules = tuple(rules)
        self._mode = mode

    @property
    def mode(self) -> ThresholdMode:
        return self._mode

    def detect(self, analysis: AnalysisResult) -> DetectionReport:
        table = ThresholdTable.from_vectors(analysis.features.values())

        applicable: list[SmellRule] = []
        skipped: dict[str, str] = {}
        for rule in self._rules:
            if rule.supports(self._mode):
                applicable.append(rule)
            else:
                skipped[rule.smell_type.value] = (
                    "no percentile declared for one or more conditions"
                )

        detectors = [
            RuleBasedDetector(rule, table, self._mode) for rule in applicable
        ]

        findings: list[Finding] = []
        examined = 0
        for entity_id, vector in analysis.features.items():
            entity = analysis.context.entity_by_id(entity_id)
            if entity is None:
                continue
            examined += 1
            facts = analysis.context.facts(entity)
            for detector in detectors:
                finding = detector.evaluate(entity, vector, facts)
                if finding is not None:
                    findings.append(finding)

        report = DetectionReport(
            findings=tuple(_ordered(findings)),
            threshold_mode=self._mode,
            rules_applied=len(applicable),
            entities_examined=examined,
            skipped_rules=skipped,
        )
        logger.info("detection complete", extra=safe_extra(report.summary()))
        return report


def _ordered(findings: Iterable[Finding]) -> list[Finding]:
    """Most severe first, then stable by location so output is reproducible."""
    return sorted(
        findings,
        key=lambda f: (
            -f.severity.rank,
            f.entity.relative_path,
            f.entity.start_line,
            f.smell_type.value,
        ),
    )
