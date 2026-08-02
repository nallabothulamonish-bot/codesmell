"""Size and complexity metrics.

Every metric is exposed twice: as a pure function over an AST node, and as a
:class:`~codesmell.core.ports.MetricCalculator` plugin. The maintainability
index needs Halstead volume, cyclomatic complexity and SLOC, and reaching those
through other *calculators* would create an ordering dependency between
plugins. Reaching them through pure *functions* does not, so the functions are
the real implementation and the calculators are thin wrappers.
"""

from __future__ import annotations

import ast

from codesmell.core.enums import EntityType, Language
from codesmell.core.models import CodeEntity
from codesmell.core.ports import AnalysisContext, MetricCalculator

_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Statements that open a nesting level. Handlers are excluded because they
#: are reached through their parent ``Try``, which has already incremented.
_NESTING_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While)


# --------------------------------------------------------------------- #
# Size
# --------------------------------------------------------------------- #


def line_metrics(source: str) -> dict[str, float]:
    """Physical, source, comment and blank line counts for a text block.

    A docstring is a string expression, not a comment, so it counts toward
    SLOC. That is the conventional treatment and, more importantly, it is
    applied identically at training and inference time.
    """
    lines = source.splitlines()
    blank = 0
    comment = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank += 1
        elif stripped.startswith("#"):
            comment += 1

    loc = len(lines)
    sloc = loc - blank - comment
    return {
        "loc": float(loc),
        "sloc": float(max(sloc, 0)),
        "comment_lines": float(comment),
        "blank_lines": float(blank),
        "comment_density": float(comment / loc) if loc else 0.0,
    }


def has_docstring(node: ast.AST) -> bool:
    if isinstance(node, (ast.Module, ast.ClassDef, *_FUNCTION_NODES)):
        return ast.get_docstring(node) is not None
    return False


# --------------------------------------------------------------------- #
# Cyclomatic complexity
# --------------------------------------------------------------------- #


def cyclomatic_complexity(node: ast.AST) -> int:
    """McCabe complexity: one plus the number of independent branch points.

    Counted: ``if``/``elif`` (each ``elif`` is a nested ``If`` in Python's
    AST), ternaries, loops, ``except`` handlers, ``assert``, ``match`` cases,
    each comprehension clause and its filters, and each additional operand of a
    boolean operator (``a and b and c`` contributes 2).

    Not counted: ``else``, ``finally``, ``with`` -- none of them introduces a
    new independent path.

    Nested function definitions are included, matching radon's behaviour.
    """
    complexity = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (ast.If, ast.IfExp, ast.ExceptHandler, ast.Assert, *_LOOP_NODES),
        ):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, ast.comprehension):
            complexity += 1 + len(child.ifs)
        elif isinstance(child, ast.match_case):
            complexity += 1
    return complexity


# --------------------------------------------------------------------- #
# Cognitive complexity
# --------------------------------------------------------------------- #


def cognitive_complexity(node: ast.AST) -> int:
    """Cognitive complexity, following Campbell's specification.

    Differs from McCabe in three ways that matter for smell detection:
    nesting is penalised, ``else``/``elif`` cost one point without deepening
    nesting, and a whole sequence of like boolean operators costs one point
    rather than one per operand. It tracks how hard code is to *read*, which
    correlates better with human smell judgements than path count does.
    """
    body = getattr(node, "body", None)
    if body is None:
        return 0

    function_name = getattr(node, "name", None)
    score = _cognitive_block(body, nesting=0)

    if function_name and _calls_itself(node, function_name):
        score += 1  # recursion is one point, regardless of call sites
    return score


def _cognitive_block(body: list[ast.stmt], *, nesting: int) -> int:
    return sum(_cognitive_statement(statement, nesting) for statement in body)


def _cognitive_statement(node: ast.stmt, nesting: int) -> int:
    if isinstance(node, ast.If):
        return _cognitive_if(node, nesting)

    if isinstance(node, _LOOP_NODES):
        score = 1 + nesting + _cognitive_block(node.body, nesting=nesting + 1)
        # Only the loop header, never the whole node: the body is already
        # counted by the recursive call above, and walking it again here
        # double-counts every boolean operator and ternary inside the loop.
        header = node.test if isinstance(node, ast.While) else node.iter
        score += _cognitive_expressions(header, nesting)
        if node.orelse:
            score += 1 + _cognitive_block(node.orelse, nesting=nesting + 1)
        return score

    if isinstance(node, ast.Try | ast.TryStar):
        score = _cognitive_block(node.body, nesting=nesting)
        for handler in node.handlers:
            score += 1 + nesting + _cognitive_block(
                handler.body, nesting=nesting + 1
            )
        score += _cognitive_block(node.orelse, nesting=nesting)
        score += _cognitive_block(node.finalbody, nesting=nesting)
        return score

    if isinstance(node, ast.Match):
        # One point for the dispatch, as with a switch; arms are not each a
        # separate mental branch.
        return (
            1
            + nesting
            + sum(
                _cognitive_block(case.body, nesting=nesting + 1)
                for case in node.cases
            )
        )

    if isinstance(node, (*_FUNCTION_NODES, ast.ClassDef)):
        # A nested definition deepens nesting but is not itself a branch.
        return _cognitive_block(node.body, nesting=nesting + 1)

    if isinstance(node, ast.With | ast.AsyncWith):
        return _cognitive_block(node.body, nesting=nesting)

    return _cognitive_expressions(node, nesting)


def _cognitive_if(node: ast.If, nesting: int) -> int:
    score = 1 + nesting
    score += _cognitive_expressions(node.test, nesting)
    score += _cognitive_block(node.body, nesting=nesting + 1)

    if not node.orelse:
        return score

    # `elif` is a lone `If` inside `orelse`: one point, no extra nesting.
    if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        return score + _cognitive_if_chain(node.orelse[0], nesting)

    return score + 1 + _cognitive_block(node.orelse, nesting=nesting + 1)


def _cognitive_if_chain(node: ast.If, nesting: int) -> int:
    score = 1
    score += _cognitive_expressions(node.test, nesting)
    score += _cognitive_block(node.body, nesting=nesting + 1)
    if not node.orelse:
        return score
    if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
        return score + _cognitive_if_chain(node.orelse[0], nesting)
    return score + 1 + _cognitive_block(node.orelse, nesting=nesting + 1)


def _cognitive_expressions(node: ast.AST, nesting: int) -> int:
    """Boolean-operator sequences and ternaries inside an expression."""
    score = 0
    for child in ast.walk(node):
        if isinstance(child, ast.BoolOp):
            score += 1  # the whole sequence, not one per operand
        elif isinstance(child, ast.IfExp):
            score += 1 + nesting
    return score


def _calls_itself(node: ast.AST, name: str) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id == name:
                return True
            if isinstance(func, ast.Attribute) and func.attr == name:
                return True
    return False


# --------------------------------------------------------------------- #
# Nesting
# --------------------------------------------------------------------- #


def max_nesting_depth(node: ast.AST) -> int:
    """Deepest run of nested control structures inside ``node``."""
    body = getattr(node, "body", None)
    if body is None:
        return 0
    return max((_nesting(statement, 0) for statement in body), default=0)


def _nesting(node: ast.stmt, depth: int) -> int:
    if isinstance(node, (*_NESTING_NODES, ast.Try, ast.TryStar, ast.Match)):
        depth += 1

    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.stmt):
            best = max(best, _nesting(child, depth))
        elif isinstance(child, ast.ExceptHandler):
            # `try` already incremented depth; an `except` block sits at the
            # same indentation as the `try` body, not one level deeper.
            for statement in child.body:
                best = max(best, _nesting(statement, depth))
    return best


# --------------------------------------------------------------------- #
# Calculators
# --------------------------------------------------------------------- #


class _PythonCalculator(MetricCalculator):
    """Shared base: every calculator here reads Python AST nodes."""

    @property
    def language(self) -> Language:
        return Language.PYTHON


class SizeCalculator(_PythonCalculator):
    """Line counts, defined for every entity type."""

    @property
    def metric_names(self) -> tuple[str, ...]:
        return (
            "loc",
            "sloc",
            "comment_lines",
            "blank_lines",
            "comment_density",
            "has_docstring",
        )

    @property
    def applies_to(self) -> frozenset[EntityType]:
        return frozenset(EntityType)

    def compute(
        self, entity: CodeEntity, context: AnalysisContext
    ) -> dict[str, float]:
        metrics = line_metrics(context.source_of(entity))
        node = context.native_node(entity)
        metrics["has_docstring"] = float(
            has_docstring(node) if node is not None else False
        )
        return metrics


class ComplexityCalculator(_PythonCalculator):
    """Complexity metrics, defined for callables only.

    A class has no independent execution paths of its own; its equivalent is
    WMC, which lives in the object-oriented calculator.
    """

    @property
    def metric_names(self) -> tuple[str, ...]:
        return (
            "cyclomatic_complexity",
            "cognitive_complexity",
            "max_nesting_depth",
        )

    @property
    def applies_to(self) -> frozenset[EntityType]:
        return frozenset({EntityType.METHOD, EntityType.FUNCTION})

    def compute(
        self, entity: CodeEntity, context: AnalysisContext
    ) -> dict[str, float]:
        node = context.native_node(entity)
        if node is None:
            return dict.fromkeys(self.metric_names, 0.0)
        return {
            "cyclomatic_complexity": float(cyclomatic_complexity(node)),
            "cognitive_complexity": float(cognitive_complexity(node)),
            "max_nesting_depth": float(max_nesting_depth(node)),
        }
