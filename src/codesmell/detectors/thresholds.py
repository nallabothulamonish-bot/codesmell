"""Project-relative thresholds.

Computes, for each ``(entity_type, metric)`` pair, the distribution of values
across the project being analysed, so a rule can ask for "the 90th percentile
of WMC *in this project*" instead of a fixed number from a paper about Java
codebases from 2006.

This is the cheap precursor to the ``ProjectRelativeScaler`` planned for M5. If
percentile-mode detection agrees with absolute-mode detection on large mature
projects but diverges sharply on small ones, that is early evidence for the
project-relative framing being worth pursuing -- available now, before any
model is trained.

.. warning::
   **A percentile threshold flags a fixed share of entities by construction.**
   The 90th percentile always marks 10% of a project, whether the code is
   pristine or appalling, because the threshold moves with the distribution it
   is measuring. Measured on ``psf/requests``, percentile mode produced 468
   findings against absolute mode's 253, and the excess was concentrated in
   single-condition rules -- ``message_chain`` went from 0 to 177 because the
   95th percentile of chain length in that codebase is 2.

   So percentile mode is **not** a drop-in better detector. It is useful for
   ranking within one project ("which of my classes are the worst?") and as
   evidence about how much project-relative framing changes the picture. It is
   not useful for asking "is this project healthy?", and multi-condition rules
   like God Class resist the effect precisely because a conjunction cannot be
   satisfied by distribution position alone -- God Class returns 6 findings in
   both modes.

   The lesson carries into M5: project-relative framing belongs in *feature
   scaling*, where the model learns what a given percentile position implies,
   not in *thresholding*, where it fixes the positive rate in advance.

A small project cannot support percentiles: the 90th percentile of six values
is the second-largest value, which flags something no matter how healthy the
code is. Below :data:`MIN_ENTITIES_FOR_PERCENTILES` the table refuses to answer
and the caller falls back to absolute thresholds.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from codesmell.core.enums import EntityType
from codesmell.core.models import FeatureVector

#: Below this many entities of a given type, percentiles are not meaningful.
MIN_ENTITIES_FOR_PERCENTILES = 20


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile, matching numpy's default method.

    Implemented here rather than pulled from numpy because the metrics layer
    has no numeric dependencies yet and this keeps the detector usable in a
    minimal install. The ML layer at M5 brings numpy in properly.
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (q / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


class ThresholdTable:
    """Per-project metric distributions, built once per analysis."""

    def __init__(
        self,
        distributions: Mapping[EntityType, Mapping[str, Sequence[float]]],
    ) -> None:
        self._distributions = {
            entity_type: {
                metric: tuple(sorted(values)) for metric, values in metrics.items()
            }
            for entity_type, metrics in distributions.items()
        }

    @classmethod
    def from_vectors(cls, vectors: Iterable[FeatureVector]) -> ThresholdTable:
        collected: dict[EntityType, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for vector in vectors:
            for metric, value in vector.values.items():
                collected[vector.entity_type][metric].append(value)
        return cls(collected)

    def sample_size(self, entity_type: EntityType, metric: str) -> int:
        return len(self._distributions.get(entity_type, {}).get(metric, ()))

    def supports_percentiles(self, entity_type: EntityType, metric: str) -> bool:
        return (
            self.sample_size(entity_type, metric) >= MIN_ENTITIES_FOR_PERCENTILES
        )

    def percentile(
        self, entity_type: EntityType, metric: str, q: float
    ) -> float | None:
        """The ``q``-th percentile, or ``None`` if the sample is too small."""
        if not self.supports_percentiles(entity_type, metric):
            return None
        values = self._distributions[entity_type][metric]
        return percentile(values, q)

    def summary(self) -> dict[str, int]:
        return {
            entity_type.value: len(metrics)
            for entity_type, metrics in self._distributions.items()
        }
