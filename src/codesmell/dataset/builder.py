"""Build reproducible, blinded human-labelling bundles from M2/M3 outputs."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from codesmell import __version__
from codesmell.core.enums import Severity
from codesmell.core.models import CodeEntity, SourceFile
from codesmell.detectors.engine import DetectionReport, Finding
from codesmell.detectors.rules import SmellRule
from codesmell.metrics.engine import AnalysisResult

from .models import (
    CandidateEvidence,
    CandidateSource,
    ProjectLabelBundle,
    ReviewTask,
)


@dataclass(frozen=True, slots=True)
class SamplingConfig:
    """Control-sampling and snippet limits for one build."""

    negative_ratio: float = 1.0
    min_controls_per_smell: int = 3
    seed: int = 42
    max_snippet_lines: int = 200

    def __post_init__(self) -> None:
        if self.negative_ratio < 0:
            raise ValueError("negative_ratio must be non-negative")
        if self.min_controls_per_smell < 0:
            raise ValueError("min_controls_per_smell must be non-negative")
        if self.max_snippet_lines < 1:
            raise ValueError("max_snippet_lines must be at least 1")


class LabelDatasetBuilder:
    """Turn one analysed project into blinded tasks plus separate evidence."""

    def __init__(self, config: SamplingConfig | None = None) -> None:
        self._config = config or SamplingConfig()

    @property
    def config(self) -> SamplingConfig:
        return self._config

    def build_project(
        self,
        analysis: AnalysisResult,
        report: DetectionReport,
        rules: Sequence[SmellRule],
    ) -> ProjectLabelBundle:
        findings = {
            (finding.smell_type.value, finding.entity.entity_id): finding
            for finding in report.findings
        }
        entities_by_type: dict[str, list[CodeEntity]] = defaultdict(list)
        for entity in analysis.context.entities():
            entities_by_type[entity.entity_type.value].append(entity)
        for entities in entities_by_type.values():
            entities.sort(key=_entity_sort_key)

        source_files = {
            source.relative_path: source
            for source in analysis.inventory.source_files
        }
        rng = random.Random(
            _project_seed(self._config.seed, analysis.inventory.fingerprint)
        )

        tasks: list[ReviewTask] = []
        evidence_rows: list[CandidateEvidence] = []
        snippets: dict[str, str] = {}

        for rule in sorted(rules, key=lambda item: item.smell_type.value):
            if rule.smell_type.value in report.skipped_rules:
                continue
            candidates = entities_by_type.get(rule.entity_type.value, [])
            positive = [
                entity
                for entity in candidates
                if (rule.smell_type.value, entity.entity_id) in findings
            ]
            negative = [
                entity
                for entity in candidates
                if (rule.smell_type.value, entity.entity_id) not in findings
            ]
            controls = self._sample_controls(negative, len(positive), rng)

            for entity in positive:
                finding = findings[(rule.smell_type.value, entity.entity_id)]
                task, evidence = self._make_rows(
                    analysis,
                    entity,
                    source_files.get(entity.relative_path),
                    rule,
                    finding,
                    CandidateSource.RULE,
                    report.threshold_mode.value,
                    snippets,
                )
                tasks.append(task)
                evidence_rows.append(evidence)

            for entity in controls:
                task, evidence = self._make_rows(
                    analysis,
                    entity,
                    source_files.get(entity.relative_path),
                    rule,
                    None,
                    CandidateSource.CONTROL,
                    report.threshold_mode.value,
                    snippets,
                )
                tasks.append(task)
                evidence_rows.append(evidence)

        ordered = sorted(
            zip(tasks, evidence_rows, strict=True),
            key=lambda pair: (
                pair[0].project_name,
                pair[0].smell_type,
                pair[0].relative_path,
                pair[0].start_line,
                pair[0].task_id,
            ),
        )
        tasks = [pair[0] for pair in ordered]
        evidence_rows = [pair[1] for pair in ordered]

        project = {
            **analysis.inventory.summary(),
            "origin": analysis.inventory.origin,
            "tool_version": __version__,
            "threshold_mode": report.threshold_mode.value,
            "rules_applied": report.rules_applied,
            "entities_examined": report.entities_examined,
            "review_tasks": len(tasks),
            "rule_candidates": sum(
                row.candidate_source is CandidateSource.RULE
                for row in evidence_rows
            ),
            "sampled_controls": sum(
                row.candidate_source is CandidateSource.CONTROL
                for row in evidence_rows
            ),
            "tasks_by_smell": dict(Counter(task.smell_type for task in tasks)),
        }
        return ProjectLabelBundle(
            project=project,
            tasks=tuple(tasks),
            evidence=tuple(evidence_rows),
            snippets=snippets,
            parse_failures=analysis.parse_failures,
        )

    def _sample_controls(
        self,
        negative: Sequence[CodeEntity],
        positive_count: int,
        rng: random.Random,
    ) -> list[CodeEntity]:
        if not negative or (
            self._config.negative_ratio == 0
            and self._config.min_controls_per_smell == 0
        ):
            return []
        requested = max(
            self._config.min_controls_per_smell,
            math.ceil(positive_count * self._config.negative_ratio),
        )
        requested = min(requested, len(negative))
        # Sampling from a path-sorted population plus a project-derived seed
        # makes reruns byte-for-byte reproducible.
        return sorted(rng.sample(list(negative), requested), key=_entity_sort_key)

    def _make_rows(
        self,
        analysis: AnalysisResult,
        entity: CodeEntity,
        source_file: SourceFile | None,
        rule: SmellRule,
        finding: Finding | None,
        candidate_source: CandidateSource,
        threshold_mode: str,
        snippets: dict[str, str],
    ) -> tuple[ReviewTask, CandidateEvidence]:
        task_id = _stable_id(
            analysis.inventory.fingerprint,
            entity.entity_id,
            rule.smell_type.value,
        )
        snippet_name = _snippet_name(
            analysis.inventory.fingerprint, entity.entity_id, entity.relative_path
        )
        snippets.setdefault(
            snippet_name,
            _truncate_source(
                analysis.context.source_of(entity),
                self._config.max_snippet_lines,
            ),
        )
        task = ReviewTask(
            task_id=task_id,
            project_name=analysis.inventory.name,
            project_fingerprint=analysis.inventory.fingerprint,
            source_kind=analysis.inventory.source_kind.value,
            origin=analysis.inventory.origin,
            entity_id=entity.entity_id,
            entity_type=entity.entity_type.value,
            qualified_name=entity.qualified_name,
            relative_path=entity.relative_path,
            start_line=entity.start_line,
            end_line=entity.end_line,
            source_sha256=source_file.sha256 if source_file else "",
            smell_type=rule.smell_type.value,
            snippet_path=f"snippets/{snippet_name}",
        )

        conditions = []
        severity = Severity.NONE
        if finding is not None:
            severity = finding.severity
            conditions = [
                {
                    "metric": outcome.metric,
                    "operator": outcome.operator,
                    "observed": outcome.observed,
                    "threshold": outcome.threshold,
                    "satisfied": outcome.satisfied,
                    "threshold_source": outcome.source.value,
                }
                for outcome in finding.outcomes
            ]

        evidence = CandidateEvidence(
            task_id=task_id,
            candidate_source=candidate_source,
            rule_fired=finding is not None,
            rule_severity=severity,
            threshold_mode=threshold_mode,
            conditions_json=json.dumps(
                conditions, separators=(",", ":"), sort_keys=True
            ),
            rationale=rule.rationale,
            references_json=json.dumps(
                list(rule.references), separators=(",", ":")
            ),
        )
        return task, evidence


def _entity_sort_key(entity: CodeEntity) -> tuple[str, int, str]:
    return (entity.relative_path, entity.start_line, entity.qualified_name)


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:24]


def _project_seed(seed: int, fingerprint: str) -> int:
    digest = hashlib.sha256(f"{seed}:{fingerprint}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _snippet_name(fingerprint: str, entity_id: str, path: str) -> str:
    suffix = PurePosixPath(path).suffix or ".txt"
    return f"{_stable_id(fingerprint, entity_id)}{suffix}"


def _truncate_source(source: str, max_lines: int) -> str:
    lines = source.splitlines()
    if len(lines) <= max_lines:
        return source.rstrip() + ("\n" if source else "")
    kept = lines[:max_lines]
    kept.append(f"# ... snippet truncated after {max_lines} lines ...")
    return "\n".join(kept) + "\n"
