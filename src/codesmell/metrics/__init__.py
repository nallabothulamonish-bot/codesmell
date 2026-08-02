"""M2: the software metric extraction engine."""

from codesmell.metrics.complexity import (
    ComplexityCalculator,
    SizeCalculator,
    cognitive_complexity,
    cyclomatic_complexity,
    line_metrics,
    max_nesting_depth,
)
from codesmell.metrics.context import ProjectAnalysisContext
from codesmell.metrics.engine import (
    AnalysisResult,
    FeatureSchema,
    MetricComputationError,
    MetricsEngine,
)
from codesmell.metrics.halstead import (
    HalsteadCalculator,
    MaintainabilityCalculator,
    halstead_metrics,
    maintainability_index,
)
from codesmell.metrics.oo import (
    MethodCalculator,
    ObjectOrientedCalculator,
    lcom1,
    lcom_hs,
)

#: The default calculator set, in no particular order -- the engine merges
#: their outputs and FeatureSchema imposes the canonical column order.
DEFAULT_CALCULATORS = (
    SizeCalculator(),
    ComplexityCalculator(),
    HalsteadCalculator(),
    MaintainabilityCalculator(),
    ObjectOrientedCalculator(),
    MethodCalculator(),
)

__all__ = [
    "DEFAULT_CALCULATORS",
    "AnalysisResult",
    "ComplexityCalculator",
    "FeatureSchema",
    "HalsteadCalculator",
    "MaintainabilityCalculator",
    "MethodCalculator",
    "MetricComputationError",
    "MetricsEngine",
    "ObjectOrientedCalculator",
    "ProjectAnalysisContext",
    "SizeCalculator",
    "cognitive_complexity",
    "cyclomatic_complexity",
    "halstead_metrics",
    "lcom1",
    "lcom_hs",
    "line_metrics",
    "maintainability_index",
    "max_nesting_depth",
]
