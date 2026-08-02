"""Halstead metrics and the maintainability index.

Halstead's measures were defined for languages with an explicit operator/
operand lexis. Applying them to a Python AST requires a decision about what
counts as which, and different tools decide differently -- which is exactly why
training on another tool's Halstead columns and inferring with this one would
be a feature-parity failure. The classification below is fixed, documented, and
used identically for training and inference.

Operators: arithmetic, comparison, boolean and unary operators; assignment and
augmented assignment; call, subscript and attribute access; and the control
keywords that structure execution.

Operands: identifiers, literals, parameter names, and declared function and
class names.
"""

from __future__ import annotations

import ast
import math
from collections import Counter

from codesmell.core.enums import EntityType
from codesmell.core.models import CodeEntity
from codesmell.core.ports import AnalysisContext
from codesmell.metrics.complexity import (
    _PythonCalculator,
    cyclomatic_complexity,
    line_metrics,
)

#: Statement and expression nodes that contribute one operator token.
_KEYWORD_OPERATORS: dict[type[ast.AST], str] = {
    ast.If: "if",
    ast.IfExp: "if-exp",
    ast.For: "for",
    ast.AsyncFor: "async-for",
    ast.While: "while",
    ast.Try: "try",
    ast.TryStar: "try",
    ast.ExceptHandler: "except",
    ast.With: "with",
    ast.AsyncWith: "async-with",
    ast.Return: "return",
    ast.Yield: "yield",
    ast.YieldFrom: "yield-from",
    ast.Await: "await",
    ast.Raise: "raise",
    ast.Assert: "assert",
    ast.Lambda: "lambda",
    ast.Delete: "del",
    ast.Global: "global",
    ast.Nonlocal: "nonlocal",
    ast.Import: "import",
    ast.ImportFrom: "import-from",
    ast.Break: "break",
    ast.Continue: "continue",
    ast.Pass: "pass",
    ast.Match: "match",
    ast.Starred: "*",
    ast.Slice: "slice",
    ast.Call: "()",
    ast.Subscript: "[]",
    ast.Attribute: ".",
    ast.Assign: "=",
    ast.AnnAssign: ":=",
    ast.NamedExpr: ":=",
    ast.List: "[]-literal",
    ast.Tuple: "()-literal",
    ast.Dict: "{}-literal",
    ast.Set: "{}-set",
}


def halstead_counts(node: ast.AST) -> tuple[Counter[str], Counter[str]]:
    """Return ``(operators, operands)`` multisets for a subtree."""
    operators: Counter[str] = Counter()
    operands: Counter[str] = Counter()

    for child in ast.walk(node):
        keyword = _KEYWORD_OPERATORS.get(type(child))
        if keyword:
            operators[keyword] += 1

        if isinstance(child, ast.BinOp | ast.UnaryOp):
            operators[type(child.op).__name__] += 1
        elif isinstance(child, ast.BoolOp):
            # `a and b and c` is two applications of one operator.
            operators[type(child.op).__name__] += max(len(child.values) - 1, 1)
        elif isinstance(child, ast.AugAssign):
            operators[f"{type(child.op).__name__}="] += 1
        elif isinstance(child, ast.Compare):
            for operator in child.ops:
                operators[type(operator).__name__] += 1

        if isinstance(child, ast.Name):
            operands[child.id] += 1
        elif isinstance(child, ast.Attribute):
            operands[child.attr] += 1
        elif isinstance(child, ast.Constant):
            operands[f"const:{child.value!r}"] += 1
        elif isinstance(child, ast.arg):
            operands[child.arg] += 1
        elif isinstance(
            child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            operands[child.name] += 1

    return operators, operands


def halstead_metrics(node: ast.AST) -> dict[str, float]:
    """The full Halstead suite derived from the operator/operand counts."""
    operators, operands = halstead_counts(node)

    distinct_operators = len(operators)          # n1
    distinct_operands = len(operands)            # n2
    total_operators = sum(operators.values())    # N1
    total_operands = sum(operands.values())      # N2

    vocabulary = distinct_operators + distinct_operands
    length = total_operators + total_operands

    volume = length * math.log2(vocabulary) if vocabulary > 0 else 0.0
    difficulty = (
        (distinct_operators / 2) * (total_operands / distinct_operands)
        if distinct_operands > 0
        else 0.0
    )
    effort = difficulty * volume

    return {
        "halstead_distinct_operators": float(distinct_operators),
        "halstead_distinct_operands": float(distinct_operands),
        "halstead_total_operators": float(total_operators),
        "halstead_total_operands": float(total_operands),
        "halstead_vocabulary": float(vocabulary),
        "halstead_length": float(length),
        "halstead_volume": volume,
        "halstead_difficulty": difficulty,
        "halstead_effort": effort,
        "halstead_time": effort / 18.0,       # Stroud number
        "halstead_bugs": volume / 3000.0,
    }


def maintainability_index(
    *, volume: float, complexity: float, sloc: float
) -> float:
    """The SEI-normalised maintainability index, on a 0-100 scale.

    ``MI = 171 - 5.2*ln(V) - 0.23*CC - 16.2*ln(SLOC)``, rescaled to 0-100 and
    clamped. The logarithms are guarded: an empty or trivial entity has volume
    or SLOC of zero, where ``ln`` is undefined, and returning 100 (perfectly
    maintainable) is the correct reading of "there is nothing here to maintain".
    """
    safe_volume = max(volume, 1.0)
    safe_sloc = max(sloc, 1.0)

    raw = (
        171.0
        - 5.2 * math.log(safe_volume)
        - 0.23 * complexity
        - 16.2 * math.log(safe_sloc)
    )
    return max(0.0, min(100.0, raw * 100.0 / 171.0))


# --------------------------------------------------------------------- #
# Calculators
# --------------------------------------------------------------------- #


class HalsteadCalculator(_PythonCalculator):
    """Halstead measures, defined for every entity type."""

    @property
    def metric_names(self) -> tuple[str, ...]:
        return (
            "halstead_distinct_operators",
            "halstead_distinct_operands",
            "halstead_total_operators",
            "halstead_total_operands",
            "halstead_vocabulary",
            "halstead_length",
            "halstead_volume",
            "halstead_difficulty",
            "halstead_effort",
            "halstead_time",
            "halstead_bugs",
        )

    @property
    def applies_to(self) -> frozenset[EntityType]:
        return frozenset(EntityType)

    def compute(
        self, entity: CodeEntity, context: AnalysisContext
    ) -> dict[str, float]:
        node = context.native_node(entity)
        if node is None:
            return dict.fromkeys(self.metric_names, 0.0)
        return halstead_metrics(node)


class MaintainabilityCalculator(_PythonCalculator):
    """Maintainability index.

    Recomputes volume, complexity and SLOC from pure functions rather than
    reading another calculator's output, so plugin execution order stays
    irrelevant.
    """

    @property
    def metric_names(self) -> tuple[str, ...]:
        return ("maintainability_index",)

    @property
    def applies_to(self) -> frozenset[EntityType]:
        return frozenset(EntityType)

    def compute(
        self, entity: CodeEntity, context: AnalysisContext
    ) -> dict[str, float]:
        node = context.native_node(entity)
        if node is None:
            return {"maintainability_index": 100.0}

        volume = halstead_metrics(node)["halstead_volume"]
        sloc = line_metrics(context.source_of(entity))["sloc"]
        complexity = float(cyclomatic_complexity(node))

        return {
            "maintainability_index": maintainability_index(
                volume=volume, complexity=complexity, sloc=sloc
            )
        }


__all__ = [
    "HalsteadCalculator",
    "MaintainabilityCalculator",
    "halstead_counts",
    "halstead_metrics",
    "maintainability_index",
]
