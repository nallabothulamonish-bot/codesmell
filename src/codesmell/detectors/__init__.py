"""M3: rule-based smell detection.

A non-ML baseline driven entirely by YAML thresholds. See
:mod:`codesmell.detectors.engine` for the warning about what these detectors
may and may not legitimately be used for -- in short, they are a baseline and a
labelling aid, never training labels.
"""

from codesmell.detectors.config import default_rules_path, load_rules
from codesmell.detectors.engine import (
    ConditionOutcome,
    DetectionEngine,
    DetectionReport,
    Finding,
    RuleBasedDetector,
)
from codesmell.detectors.rules import (
    Combinator,
    Condition,
    Operator,
    RuleConfigError,
    SmellRule,
    ThresholdMode,
)
from codesmell.detectors.thresholds import ThresholdTable, percentile

__all__ = [
    "Combinator",
    "Condition",
    "ConditionOutcome",
    "DetectionEngine",
    "DetectionReport",
    "Finding",
    "Operator",
    "RuleBasedDetector",
    "RuleConfigError",
    "SmellRule",
    "ThresholdMode",
    "ThresholdTable",
    "default_rules_path",
    "load_rules",
    "percentile",
]
