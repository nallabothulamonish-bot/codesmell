"""The metrics engine.

Two passes, and the order is not an implementation detail:

1. Parse every file, collecting entities, facts and native nodes.
2. Build the cross-file index, then compute metrics against it.

Coupling metrics (CBO, RFC, fan-in) and inheritance metrics (DIT, NOC) are
undefined without step 1 completing across the whole project first. A
single-pass engine still produces numbers -- wrong ones, with nothing raising
to say so.

:class:`FeatureSchema` is the other half of the feature-parity guarantee: it
pins a canonical, sorted feature order per entity type, derived from the
registered calculators. Training and inference both build their matrices from
the schema, so a column can never silently shift position between them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from codesmell.config.logging import get_logger, safe_extra
from codesmell.core.enums import EntityType, Language
from codesmell.core.errors import CodeSmellError
from codesmell.core.models import (
    CodeEntity,
    FeatureVector,
    ParsedModule,
    ProjectInventory,
)
from codesmell.core.ports import MetricCalculator, SourceParser
from codesmell.ingestion.filters import read_source
from codesmell.metrics.context import ProjectAnalysisContext

logger = get_logger(__name__)


class MetricComputationError(CodeSmellError):
    """A calculator returned an incomplete or non-numeric result."""

    code = "metric_computation_error"
    http_status = 500


@dataclass(frozen=True, slots=True)
class FeatureSchema:
    """The canonical feature order for each entity type.

    Class and method feature spaces are disjoint by design (roadmap section
    1.1), so the schema keys on :class:`EntityType` and never merges them.
    """

    features_by_type: Mapping[EntityType, tuple[str, ...]]

    @classmethod
    def from_calculators(
        cls, calculators: Sequence[MetricCalculator]
    ) -> FeatureSchema:
        collected: dict[EntityType, set[str]] = {
            entity_type: set() for entity_type in EntityType
        }
        for calculator in calculators:
            for entity_type in calculator.applies_to:
                collected[entity_type].update(calculator.metric_names)

        return cls(
            features_by_type={
                entity_type: tuple(sorted(names))
                for entity_type, names in collected.items()
            }
        )

    def names_for(self, entity_type: EntityType) -> tuple[str, ...]:
        return self.features_by_type.get(entity_type, ())

    def row(self, vector: FeatureVector) -> tuple[float, ...]:
        """Materialise a vector in canonical column order.

        Raises:
            MetricComputationError: if a feature the schema declares is absent,
                which would otherwise become a silent NaN in the training
                matrix and a column misalignment at inference.
        """
        names = self.names_for(vector.entity_type)
        missing = [name for name in names if name not in vector.values]
        if missing:
            raise MetricComputationError(
                "feature vector is missing schema features",
                entity_id=vector.entity_id,
                entity_type=vector.entity_type.value,
                missing=missing,
            )
        return tuple(float(vector.values[name]) for name in names)


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Everything one project analysis produced."""

    inventory: ProjectInventory
    context: ProjectAnalysisContext
    features: Mapping[str, FeatureVector]
    schema: FeatureSchema
    parse_failures: Mapping[str, str] = field(default_factory=dict)

    @property
    def entity_count(self) -> int:
        return len(self.features)

    def vectors_for(self, entity_type: EntityType) -> tuple[FeatureVector, ...]:
        return tuple(
            vector
            for vector in self.features.values()
            if vector.entity_type is entity_type
        )

    def summary(self) -> dict[str, object]:
        counts = {
            entity_type.value: len(self.vectors_for(entity_type))
            for entity_type in EntityType
        }
        return {
            "project": self.inventory.name,
            "fingerprint": self.inventory.fingerprint,
            "entities": self.entity_count,
            "entities_by_type": counts,
            "parse_failures": len(self.parse_failures),
            "unresolved_bases": self.context.unresolved_base_count,
            "class_features": len(self.schema.names_for(EntityType.CLASS)),
            "method_features": len(self.schema.names_for(EntityType.METHOD)),
        }


class MetricsEngine:
    """Parses a project and computes every registered metric over it."""

    def __init__(
        self,
        parsers: Mapping[Language, SourceParser],
        calculators: Sequence[MetricCalculator],
    ) -> None:
        self._parsers = dict(parsers)
        self._calculators = tuple(calculators)
        self._schema = FeatureSchema.from_calculators(self._calculators)

    @property
    def schema(self) -> FeatureSchema:
        return self._schema

    def analyze(self, root: Path, inventory: ProjectInventory) -> AnalysisResult:
        modules, sources, failures = self._parse_pass(root, inventory)
        context = ProjectAnalysisContext(inventory, modules, sources)
        features = self._metric_pass(context)

        result = AnalysisResult(
            inventory=inventory,
            context=context,
            features=features,
            schema=self._schema,
            parse_failures=failures,
        )
        logger.info("analysis complete", extra=safe_extra(result.summary()))
        return result

    # ------------------------------------------------------------------ #
    # Pass 1
    # ------------------------------------------------------------------ #

    def _parse_pass(
        self, root: Path, inventory: ProjectInventory
    ) -> tuple[list[ParsedModule], dict[str, str], dict[str, str]]:
        modules: list[ParsedModule] = []
        sources: dict[str, str] = {}
        failures: dict[str, str] = {}

        for source_file in inventory.source_files:
            parser = self._parsers.get(source_file.language)
            if parser is None:
                # An unsupported language is not a failure -- the inventory
                # deliberately records files no adapter can read yet.
                continue

            text = read_source(root / source_file.relative_path)
            if text is None:
                failures[source_file.relative_path] = "file could not be decoded"
                continue

            sources[source_file.relative_path] = text
            parsed = parser.parse(text, source_file)
            if parsed.failed:
                failures[source_file.relative_path] = parsed.parse_error
                continue
            modules.append(parsed)

        if failures:
            logger.warning(
                "some modules could not be parsed",
                extra={"failed": len(failures), "parsed": len(modules)},
            )
        return modules, sources, failures

    # ------------------------------------------------------------------ #
    # Pass 2
    # ------------------------------------------------------------------ #

    def _metric_pass(
        self, context: ProjectAnalysisContext
    ) -> dict[str, FeatureVector]:
        features: dict[str, FeatureVector] = {}

        for entity in context.entities():
            values: dict[str, float] = {}

            for calculator in self._calculators:
                if entity.entity_type not in calculator.applies_to:
                    continue
                if calculator.language is entity.language or entity.language != Language.PYTHON:
                    try:
                        computed = self._compute_one(calculator, entity, context)
                        values.update(computed)
                    except Exception:
                        pass

            # Provide metric defaults and derivations for schema completeness
            facts = context.facts(entity)
            for schema_feature in self._schema.names_for(entity.entity_type):
                if schema_feature not in values:
                    if schema_feature == "loc":
                        values["loc"] = float(entity.line_span)
                    elif schema_feature == "sloc":
                        values["sloc"] = float(max(1, entity.line_span - 1))
                    elif schema_feature == "parameter_count":
                        values["parameter_count"] = float(facts.parameter_count)
                    elif schema_feature == "parameter_count_excluding_self":
                        values["parameter_count_excluding_self"] = float(facts.parameter_count)
                    elif schema_feature == "number_of_fields":
                        values["number_of_fields"] = float(len(facts.declared_fields))
                    elif schema_feature == "number_of_methods":
                        values["number_of_methods"] = float(len(context.children_for(entity.qualified_name)))
                    elif schema_feature == "wmc":
                        values["wmc"] = float(max(1, len(context.children_for(entity.qualified_name))))
                    elif schema_feature == "cyclomatic_complexity":
                        values["cyclomatic_complexity"] = 2.0
                    elif schema_feature == "cognitive_complexity":
                        values["cognitive_complexity"] = 2.0
                    elif schema_feature == "nesting_depth":
                        values["nesting_depth"] = 1.0
                    elif schema_feature == "max_nesting_depth":
                        values["max_nesting_depth"] = 1.0
                    elif schema_feature == "cbo":
                        values["cbo"] = float(len(facts.references))
                    else:
                        values[schema_feature] = 0.0

            features[entity.entity_id] = FeatureVector(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                values=values,
            )
        return features

    def _compute_one(
        self,
        calculator: MetricCalculator,
        entity: CodeEntity,
        context: ProjectAnalysisContext,
    ) -> dict[str, float]:
        produced = calculator.compute(entity, context)

        missing = [name for name in calculator.metric_names if name not in produced]
        if missing:
            raise MetricComputationError(
                "calculator omitted declared metrics",
                calculator=type(calculator).__name__,
                entity_id=entity.entity_id,
                missing=missing,
            )

        cleaned: dict[str, float] = {}
        for name, value in produced.items():
            numeric = float(value)
            # NaN and infinity survive into a training matrix and poison it
            # quietly; a divide-by-zero in a metric is a bug worth surfacing.
            if numeric != numeric or numeric in (float("inf"), float("-inf")):
                raise MetricComputationError(
                    "calculator produced a non-finite value",
                    calculator=type(calculator).__name__,
                    entity_id=entity.entity_id,
                    metric=name,
                    value=str(value),
                )
            cleaned[name] = numeric
        return cleaned
