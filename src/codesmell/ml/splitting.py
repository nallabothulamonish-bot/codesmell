"""Deterministic project-level train/test splitting."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .models import SplitConfig


@dataclass(frozen=True, slots=True)
class ProjectSplit:
    train_projects: tuple[str, ...]
    test_projects: tuple[str, ...]
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    train_positive: int
    test_positive: int
    test_has_both_classes: bool


def project_holdout_split(
    rows: Sequence[Mapping[str, str]],
    config: SplitConfig,
) -> ProjectSplit:
    """Split entire projects, searching for a train set with both classes.

    Preference is given to a test set containing both classes, but that cannot
    always be achieved when individual projects are single-class. The returned
    flag makes this limitation explicit so ROC-AUC/PR-AUC can be reported as
    unavailable rather than fabricated.
    """
    projects = sorted({row["project_fingerprint"] for row in rows})
    if len(projects) < 2:
        raise ValueError("project-level splitting requires at least 2 projects")
    test_count = max(1, min(len(projects) - 1, round(len(projects) * config.test_size)))

    fallback: ProjectSplit | None = None
    for attempt in range(config.max_attempts):
        shuffled = list(projects)
        random.Random(config.seed + attempt).shuffle(shuffled)
        test_projects = tuple(sorted(shuffled[:test_count]))
        train_projects = tuple(sorted(shuffled[test_count:]))
        split = _materialize(rows, train_projects, test_projects)
        train_labels = {int(rows[index]["label"]) for index in split.train_indices}
        if len(train_labels) < 2:
            continue
        if fallback is None:
            fallback = split
        if split.test_has_both_classes:
            return split
    if fallback is not None:
        return fallback
    raise ValueError(
        "no project-level split leaves both classes in the training partition"
    )


def _materialize(
    rows: Sequence[Mapping[str, str]],
    train_projects: tuple[str, ...],
    test_projects: tuple[str, ...],
) -> ProjectSplit:
    train_set = set(train_projects)
    test_set = set(test_projects)
    train_indices = tuple(
        index
        for index, row in enumerate(rows)
        if row["project_fingerprint"] in train_set
    )
    test_indices = tuple(
        index
        for index, row in enumerate(rows)
        if row["project_fingerprint"] in test_set
    )
    train_positive = sum(int(rows[index]["label"]) for index in train_indices)
    test_positive = sum(int(rows[index]["label"]) for index in test_indices)
    test_labels = {int(rows[index]["label"]) for index in test_indices}
    return ProjectSplit(
        train_projects=train_projects,
        test_projects=test_projects,
        train_indices=train_indices,
        test_indices=test_indices,
        train_positive=train_positive,
        test_positive=test_positive,
        test_has_both_classes=len(test_labels) == 2,
    )
