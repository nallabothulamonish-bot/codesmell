"""Complexity, size and Halstead metric tests.

Every expected value here is hand-computed from the definition and the reason
is written into the test. That is the point of this file: a metric that is
merely self-consistent still produces a publishable-looking number while being
wrong, and nothing downstream would ever raise.
"""

from __future__ import annotations

import ast

import pytest

from codesmell.metrics.complexity import (
    cognitive_complexity,
    cyclomatic_complexity,
    line_metrics,
    max_nesting_depth,
)
from codesmell.metrics.halstead import (
    halstead_counts,
    halstead_metrics,
    maintainability_index,
)


def _function(source: str) -> ast.AST:
    """Parse a snippet and return its single top-level function node."""
    return ast.parse(source).body[0]


# --------------------------------------------------------------------- #
# Cyclomatic complexity
# --------------------------------------------------------------------- #


def test_straight_line_function_has_complexity_one():
    """No branches means exactly one path."""
    node = _function("def f():\n    x = 1\n    return x\n")
    assert cyclomatic_complexity(node) == 1


def test_single_if_adds_one():
    node = _function("def f(a):\n    if a:\n        return 1\n    return 0\n")
    assert cyclomatic_complexity(node) == 2


def test_else_branch_adds_nothing():
    """`else` is not an independent decision -- the `if` already counted it."""
    node = _function(
        "def f(a):\n    if a:\n        return 1\n    else:\n        return 0\n"
    )
    assert cyclomatic_complexity(node) == 2


def test_elif_chain_counts_each_test():
    """Three tests: if + elif + elif. 1 + 3 = 4."""
    node = _function(
        "def f(a):\n"
        "    if a == 1:\n        return 1\n"
        "    elif a == 2:\n        return 2\n"
        "    elif a == 3:\n        return 3\n"
        "    return 0\n"
    )
    assert cyclomatic_complexity(node) == 4


def test_boolean_operators_count_per_extra_operand():
    """`a and b and c` is two decisions, not one. 1 + 1(if) + 2 = 4."""
    node = _function("def f(a, b, c):\n    if a and b and c:\n        return 1\n")
    assert cyclomatic_complexity(node) == 4


def test_loop_and_except_each_add_one():
    """1 + for + except = 3."""
    node = _function(
        "def f(items):\n"
        "    for i in items:\n"
        "        try:\n            g(i)\n"
        "        except ValueError:\n            pass\n"
    )
    assert cyclomatic_complexity(node) == 3


def test_multiple_except_handlers_each_add_one():
    """1 + try-body(0) + 3 handlers = 4."""
    node = _function(
        "def f():\n"
        "    try:\n        g()\n"
        "    except ValueError:\n        pass\n"
        "    except KeyError:\n        pass\n"
        "    except TypeError:\n        pass\n"
    )
    assert cyclomatic_complexity(node) == 4


def test_finally_adds_nothing():
    """`finally` always runs -- it is not a branch. 1 + 1 handler = 2."""
    node = _function(
        "def f():\n"
        "    try:\n        g()\n"
        "    except ValueError:\n        pass\n"
        "    finally:\n        h()\n"
    )
    assert cyclomatic_complexity(node) == 2


def test_comprehension_counts_clause_and_filters():
    """1 + for-clause + 2 filters = 4."""
    node = _function("def f(xs):\n    return [x for x in xs if x if x > 2]\n")
    assert cyclomatic_complexity(node) == 4


def test_ternary_adds_one():
    node = _function("def f(a):\n    return 1 if a else 0\n")
    assert cyclomatic_complexity(node) == 2


def test_match_statement_counts_each_case():
    """1 + 3 cases = 4."""
    node = _function(
        "def f(a):\n"
        "    match a:\n"
        "        case 1:\n            return 'one'\n"
        "        case 2:\n            return 'two'\n"
        "        case _:\n            return 'other'\n"
    )
    assert cyclomatic_complexity(node) == 4


def test_with_statement_adds_nothing():
    node = _function("def f(p):\n    with open(p) as fh:\n        return fh.read()\n")
    assert cyclomatic_complexity(node) == 1


# --------------------------------------------------------------------- #
# Cognitive complexity
# --------------------------------------------------------------------- #


def test_cognitive_complexity_of_flat_code_is_zero():
    node = _function("def f():\n    x = 1\n    return x\n")
    assert cognitive_complexity(node) == 0


def test_cognitive_complexity_penalises_nesting():
    """Flat: 1+1+1 = 3. Nested: 1 + (1+1) + (1+2) = 6.

    Identical cyclomatic complexity, very different readability -- which is
    exactly the distinction this metric exists to capture.
    """
    flat = _function(
        "def f(a, b, c):\n"
        "    if a:\n        return 1\n"
        "    if b:\n        return 2\n"
        "    if c:\n        return 3\n"
    )
    nested = _function(
        "def f(a, b, c):\n"
        "    if a:\n"
        "        if b:\n"
        "            if c:\n"
        "                return 3\n"
    )
    assert cyclomatic_complexity(flat) == cyclomatic_complexity(nested) == 4
    assert cognitive_complexity(flat) == 3
    assert cognitive_complexity(nested) == 6


def test_cognitive_complexity_elif_costs_one_without_nesting():
    """if(1) + elif(1) + else(1) = 3, with no nesting surcharge."""
    node = _function(
        "def f(a):\n"
        "    if a == 1:\n        return 1\n"
        "    elif a == 2:\n        return 2\n"
        "    else:\n        return 3\n"
    )
    assert cognitive_complexity(node) == 3


def test_cognitive_complexity_charges_once_per_boolean_sequence():
    """Unlike McCabe: the whole `a and b and c` sequence is one point.

    if(1) + sequence(1) = 2, where cyclomatic complexity would say 4.
    """
    node = _function("def f(a, b, c):\n    if a and b and c:\n        return 1\n")
    assert cognitive_complexity(node) == 2
    assert cyclomatic_complexity(node) == 4


def test_cognitive_complexity_counts_recursion_once():
    """if(1) + recursion(1) = 2, regardless of how many recursive calls."""
    node = _function(
        "def fib(n):\n"
        "    if n < 2:\n        return n\n"
        "    return fib(n - 1) + fib(n - 2)\n"
    )
    assert cognitive_complexity(node) == 2


def test_cognitive_complexity_charges_nested_loop_with_surcharge():
    """for(1) + nested for(1+1) + if inside(1+2) = 6."""
    node = _function(
        "def f(rows):\n"
        "    for row in rows:\n"
        "        for cell in row:\n"
        "            if cell:\n"
        "                g(cell)\n"
    )
    assert cognitive_complexity(node) == 6


# --------------------------------------------------------------------- #
# Nesting
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def f():\n    return 1\n", 0),
        ("def f(a):\n    if a:\n        return 1\n", 1),
        ("def f(a, b):\n    if a:\n        if b:\n            return 1\n", 2),
        (
            "def f(xs):\n"
            "    for x in xs:\n"
            "        if x:\n"
            "            while x:\n"
            "                x -= 1\n",
            3,
        ),
    ],
)
def test_max_nesting_depth(source: str, expected: int):
    assert max_nesting_depth(_function(source)) == expected


def test_nesting_depth_takes_the_deepest_branch_not_the_last():
    node = _function(
        "def f(a, b):\n"
        "    if a:\n"
        "        if b:\n"
        "            if a and b:\n"
        "                return 1\n"
        "    if a:\n"
        "        return 2\n"
    )
    assert max_nesting_depth(node) == 3


# --------------------------------------------------------------------- #
# Line metrics
# --------------------------------------------------------------------- #


def test_line_metrics_classify_each_line():
    source = "# a comment\n\ndef f():\n    return 1\n"
    metrics = line_metrics(source)

    assert metrics["loc"] == 4
    assert metrics["comment_lines"] == 1
    assert metrics["blank_lines"] == 1
    assert metrics["sloc"] == 2
    assert metrics["comment_density"] == pytest.approx(0.25)


def test_inline_comment_is_not_a_comment_line():
    """Only whole-line comments count; `x = 1  # note` is a source line."""
    metrics = line_metrics("x = 1  # note\n")
    assert metrics["comment_lines"] == 0
    assert metrics["sloc"] == 1


def test_docstring_counts_as_source_not_comment():
    """A docstring is a string expression. Documented, and applied identically
    at training and inference time, which is what actually matters."""
    metrics = line_metrics('def f():\n    """Doc."""\n    return 1\n')
    assert metrics["comment_lines"] == 0
    assert metrics["sloc"] == 3


def test_empty_source_has_no_lines_and_no_division_error():
    metrics = line_metrics("")
    assert metrics["loc"] == 0
    assert metrics["comment_density"] == 0.0


# --------------------------------------------------------------------- #
# Halstead
# --------------------------------------------------------------------- #


def test_halstead_counts_operands_with_multiplicity():
    """`x` appears three times: one store, two loads."""
    node = ast.parse("x = 1\ny = x + x\n")
    _operators, operands = halstead_counts(node)
    assert operands["x"] == 3


def test_halstead_volume_follows_the_definition():
    """V = N * log2(n), computed from this implementation's own counts.

    The counts are an operationalization choice; the formula is not. This
    checks the formula, and the parity guarantee covers the choice.
    """
    import math

    node = ast.parse("def f(a, b):\n    return a + b\n")
    metrics = halstead_metrics(node)

    expected = metrics["halstead_length"] * math.log2(metrics["halstead_vocabulary"])
    assert metrics["halstead_volume"] == pytest.approx(expected)


def test_halstead_difficulty_follows_the_definition():
    """D = (n1 / 2) * (N2 / n2)."""
    node = ast.parse("def f(a, b):\n    return a * b + a\n")
    metrics = halstead_metrics(node)

    expected = (metrics["halstead_distinct_operators"] / 2) * (
        metrics["halstead_total_operands"] / metrics["halstead_distinct_operands"]
    )
    assert metrics["halstead_difficulty"] == pytest.approx(expected)


def test_halstead_on_empty_module_does_not_divide_by_zero():
    metrics = halstead_metrics(ast.parse(""))
    assert metrics["halstead_volume"] == 0.0
    assert metrics["halstead_difficulty"] == 0.0
    assert metrics["halstead_bugs"] == 0.0


def test_halstead_effort_is_difficulty_times_volume():
    node = ast.parse("def f(a):\n    if a > 0:\n        return a\n    return -a\n")
    metrics = halstead_metrics(node)
    assert metrics["halstead_effort"] == pytest.approx(
        metrics["halstead_difficulty"] * metrics["halstead_volume"]
    )


# --------------------------------------------------------------------- #
# Maintainability index
# --------------------------------------------------------------------- #


def test_maintainability_index_matches_the_sei_formula():
    import math

    volume, complexity, sloc = 100.0, 5.0, 20.0
    raw = 171 - 5.2 * math.log(volume) - 0.23 * complexity - 16.2 * math.log(sloc)

    assert maintainability_index(
        volume=volume, complexity=complexity, sloc=sloc
    ) == pytest.approx(raw * 100 / 171)


def test_maintainability_index_is_clamped_to_zero_hundred():
    assert (
        maintainability_index(volume=1e9, complexity=500.0, sloc=1e6) == 0.0
    )
    assert maintainability_index(volume=1.0, complexity=0.0, sloc=1.0) == 100.0


def test_maintainability_index_handles_empty_entity():
    """ln(0) is undefined; nothing to maintain reads as perfectly maintainable."""
    assert maintainability_index(volume=0.0, complexity=0.0, sloc=0.0) == 100.0


def test_maintainability_index_falls_as_code_worsens():
    simple = maintainability_index(volume=50.0, complexity=1.0, sloc=5.0)
    awful = maintainability_index(volume=5000.0, complexity=40.0, sloc=400.0)
    assert simple > awful


# --------------------------------------------------------------------- #
# Cognitive complexity: remaining statement forms
# --------------------------------------------------------------------- #


def test_cognitive_try_body_is_not_nested_but_handlers_are():
    """try body: 0. except: 1. `if` inside the handler: 1 + 1 nesting = 2.

    Total 3. The `try` itself is not a branch -- only the handler is.
    """
    node = _function(
        "def f(a):\n"
        "    try:\n        g()\n"
        "    except ValueError:\n"
        "        if a:\n            return 1\n"
    )
    assert cognitive_complexity(node) == 3


def test_cognitive_finally_and_else_bodies_stay_at_the_same_level():
    """except(1) + if in else(1) + if in finally(1) = 3, none nested."""
    node = _function(
        "def f(a):\n"
        "    try:\n        g()\n"
        "    except ValueError:\n        pass\n"
        "    else:\n"
        "        if a:\n            g()\n"
        "    finally:\n"
        "        if a:\n            h()\n"
    )
    assert cognitive_complexity(node) == 3


def test_cognitive_match_charges_the_dispatch_once():
    """One point for the dispatch, not one per arm -- arms are parallel, not
    cumulative mental load. match(1) + if inside an arm(1+1) = 3."""
    node = _function(
        "def f(a, b):\n"
        "    match a:\n"
        "        case 1:\n            return 1\n"
        "        case 2:\n"
        "            if b:\n                return 2\n"
        "        case _:\n            return 0\n"
    )
    assert cognitive_complexity(node) == 3


def test_cognitive_nested_function_deepens_nesting_without_a_branch():
    """A def is not a decision, but code inside one is harder to follow.
    inner `if`: 1 + 1 nesting = 2."""
    node = _function(
        "def outer(a):\n"
        "    def inner():\n"
        "        if a:\n            return 1\n"
        "    return inner\n"
    )
    assert cognitive_complexity(node) == 2


def test_cognitive_with_statement_is_transparent():
    """`with` is not a branch and does not deepen nesting: only the `if`
    counts, at nesting 0."""
    node = _function(
        "def f(a, p):\n"
        "    with open(p) as fh:\n"
        "        if a:\n            return fh.read()\n"
    )
    assert cognitive_complexity(node) == 1


def test_cognitive_loop_else_clause_costs_a_point():
    """for(1) + else(1) = 2."""
    node = _function(
        "def f(xs):\n"
        "    for x in xs:\n        g(x)\n"
        "    else:\n        h()\n"
    )
    assert cognitive_complexity(node) == 2


def test_cognitive_ternary_inside_a_loop_takes_the_nesting_surcharge():
    """for(1) + ternary(1 + 1 nesting) = 3."""
    node = _function(
        "def f(xs):\n    for x in xs:\n        y = 1 if x else 0\n    return y\n"
    )
    assert cognitive_complexity(node) == 3


def test_cognitive_complexity_of_a_non_function_node_is_zero():
    assert cognitive_complexity(ast.parse("x = 1").body[0]) == 0


def test_nesting_depth_counts_except_handler_bodies():
    node = _function(
        "def f(a):\n"
        "    try:\n        g()\n"
        "    except ValueError:\n"
        "        if a:\n            return 1\n"
    )
    assert max_nesting_depth(node) == 2


def test_cognitive_does_not_double_count_boolean_ops_inside_a_loop():
    """Regression: the loop branch scanned the whole loop node for boolean
    operators while the recursive call already scanned the body, so every
    ternary and `and`/`or` inside any loop was charged twice.

    for(1) + if(1+1) + its boolean sequence(1) = 4.
    """
    node = _function(
        "def f(xs, a, b):\n"
        "    for x in xs:\n"
        "        if a and b:\n"
        "            g(x)\n"
    )
    assert cognitive_complexity(node) == 4


def test_cognitive_counts_a_boolean_operator_in_a_while_header():
    """while(1) + header sequence(1) = 2."""
    node = _function("def f(a, b):\n    while a and b:\n        g()\n")
    assert cognitive_complexity(node) == 2


def test_nesting_treats_try_and_except_as_one_level():
    """Regression: `try` incremented depth and the handler incremented again,
    so try/except read as two levels when they share an indentation level."""
    shallow = _function(
        "def f():\n    try:\n        g()\n    except ValueError:\n        h()\n"
    )
    assert max_nesting_depth(shallow) == 1
