"""Object-oriented (CK suite) and method-level metrics.

Several CK metrics have more than one operationalization in the literature.
Every choice made here is stated explicitly, because the choice itself becomes
part of the feature definition: a model trained on one reading of CBO and
served another is the feature-parity failure from the roadmap, section 1.3.
Since training and inference both run this exact code, the definitions only
need to be *consistent* and *documented* -- not universal.
"""

from __future__ import annotations

import ast
from collections.abc import Container
from itertools import combinations

from codesmell.core.enums import EntityType
from codesmell.core.models import CodeEntity
from codesmell.core.ports import AnalysisContext
from codesmell.metrics.complexity import (
    _PythonCalculator,
    cyclomatic_complexity,
    max_nesting_depth,
)

_RECEIVER_NAMES = frozenset({"self", "cls", "mcs", "metacls"})


# --------------------------------------------------------------------- #
# Cohesion
# --------------------------------------------------------------------- #


def lcom1(method_fields: list[set[str]]) -> int:
    """Chidamber & Kemerer LCOM1.

    Pairs of methods sharing no instance field, minus pairs that do share one,
    floored at zero. Higher means less cohesive.
    """
    if len(method_fields) < 2:
        return 0

    sharing = 0
    disjoint = 0
    for left, right in combinations(method_fields, 2):
        if left & right:
            sharing += 1
        else:
            disjoint += 1
    return max(0, disjoint - sharing)


def lcom_hs(method_fields: list[set[str]], declared_fields: set[str]) -> float:
    """Henderson-Sellers LCOM*, normalised to roughly 0-1.

    ``(mean_over_fields(methods touching that field) - m) / (1 - m)`` where
    ``m`` is the method count. Preferred over LCOM1 as a model feature because
    it does not grow quadratically with class size, so it separates cohesion
    from mere bigness -- which matters when the label being predicted (God
    Class) is itself correlated with size.
    """
    method_count = len(method_fields)
    if method_count <= 1 or not declared_fields:
        return 0.0

    accesses = [
        sum(1 for fields in method_fields if field in fields)
        for field in declared_fields
    ]
    if not accesses:
        return 0.0

    mean_access = sum(accesses) / len(accesses)
    denominator = 1 - method_count
    if denominator == 0:
        return 0.0
    return max(0.0, min(1.0, (mean_access - method_count) / denominator))


# --------------------------------------------------------------------- #
# Method-level helpers
# --------------------------------------------------------------------- #


def max_message_chain(node: ast.AST) -> int:
    """Longest attribute chain, e.g. ``a.b.c.d()`` is 3.

    The direct input to the Message Chains smell and a component of Law of
    Demeter violations.
    """
    best = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            depth = 0
            current: ast.expr = child
            while isinstance(current, ast.Attribute):
                depth += 1
                current = current.value
            best = max(best, depth)
    return best


def local_variable_names(node: ast.AST) -> set[str]:
    """Names bound inside a function body, parameters excluded."""
    parameters = set()
    arguments = getattr(node, "args", None)
    if arguments is not None:
        for argument in [
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
            *([arguments.vararg] if arguments.vararg else []),
            *([arguments.kwarg] if arguments.kwarg else []),
        ]:
            parameters.add(argument.arg)

    locals_found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            locals_found.add(child.id)
        elif isinstance(child, ast.withitem) and isinstance(
            child.optional_vars, ast.Name
        ):
            locals_found.add(child.optional_vars.id)
    return locals_found - parameters


def count_returns(node: ast.AST) -> int:
    return sum(1 for child in ast.walk(node) if isinstance(child, ast.Return))


def count_magic_numbers(node: ast.AST) -> int:
    """Numeric literals other than the conventionally meaningful ones.

    0, 1, -1 and 2 are excluded: they appear in indexing and arithmetic
    idioms constantly and flagging them produces noise, not signal.
    """
    benign = {0, 1, -1, 2}
    total = 0
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, int | float)
            and not isinstance(child.value, bool)
            and child.value not in benign
        ):
            total += 1
    return total


def attribute_chain_root(node: ast.Attribute) -> str | None:
    """The base identifier of an attribute chain, if it has one.

    ``a.b.c`` -> ``a``. A chain rooted in a call or subscript
    (``f().x``, ``d["k"].y``) has no identifier root and returns ``None``.
    """
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def foreign_access_ratio(
    node: ast.AST, ignored_roots: Container[str] = frozenset()
) -> float:
    """Share of attribute accesses reaching into another object's data.

    The Feature Envy signal: a method more interested in some other object's
    data than its own probably belongs on that object.

    Two corrections over a naive "is the base ``self``" check, both of which
    materially change the result on real code:

    * **Classification is by chain root, not by immediate parent.**
      ``self.repo.find`` is reaching through the method's *own* field, so it
      counts as own access. Judging the outer ``.find`` on its immediate
      parent would call it foreign and mark almost every delegating method
      envious.
    * **Module and namespace accesses are excluded** via ``ignored_roots``.
      ``ast.walk(...)`` and ``os.path.join(...)`` are qualified names, not
      another object's data. Counting them made the ratio a proxy for "uses
      the standard library", which is not a smell -- it was the single
      largest source of false positives when this rule was first run.
    """
    own = 0
    foreign = 0

    for child in ast.walk(node):
        if not isinstance(child, ast.Attribute):
            continue
        root = attribute_chain_root(child)
        if root is None:
            continue
        if root in _RECEIVER_NAMES:
            own += 1
        elif root in ignored_roots:
            continue
        else:
            foreign += 1

    total = own + foreign
    return foreign / total if total else 0.0


# --------------------------------------------------------------------- #
# Calculators
# --------------------------------------------------------------------- #


class ObjectOrientedCalculator(_PythonCalculator):
    """The CK suite plus coupling counts, for classes.

    Operationalizations used here:

    * **WMC** -- sum of the cyclomatic complexity of the class's direct
      methods, not a plain method count.
    * **DIT** -- longest inheritance path resolvable *within this project*. A
      class whose only base is external has depth 0; inventing a depth for an
      unresolvable base would fabricate a feature value.
    * **NOC** -- immediate subclasses declared in this project.
    * **CBO** -- efferent coupling: distinct other project classes referenced
      anywhere in this class's body. Afferent coupling is reported separately
      as ``fan_in`` rather than folded in, so a model can weight the two
      directions differently.
    * **RFC** -- own methods plus the distinct method names they invoke.
    * **LCOM** -- both LCOM1 and the normalised Henderson-Sellers LCOM*.
    """

    @property
    def metric_names(self) -> tuple[str, ...]:
        return (
            "wmc",
            "number_of_methods",
            "number_of_public_methods",
            "number_of_fields",
            "dit",
            "noc",
            "cbo",
            "fan_in",
            "fan_out",
            "rfc",
            "lcom1",
            "lcom_hs",
            "average_method_complexity",
            "number_of_base_classes",
        )

    @property
    def applies_to(self) -> frozenset[EntityType]:
        return frozenset({EntityType.CLASS})

    def compute(
        self, entity: CodeEntity, context: AnalysisContext
    ) -> dict[str, float]:
        facts = context.facts(entity)
        methods = [
            child
            for child in context.children_of(entity)
            if child.entity_type is EntityType.METHOD
        ]

        complexities: list[int] = []
        method_fields: list[set[str]] = []
        called: set[str] = set()

        for method in methods:
            node = context.native_node(method)
            complexities.append(cyclomatic_complexity(node) if node else 1)
            method_facts = context.facts(method)
            method_fields.append(set(method_facts.accessed_fields))
            called.update(method_facts.called_names)

        declared_fields = set(facts.declared_fields)
        method_count = len(methods)

        referenced_classes = {
            candidate.entity_id
            for name in set(facts.references)
            for candidate in _classes_named(context, name)
            if candidate.entity_id != entity.entity_id
        }
        fan_in = len({
            referrer.entity_id for referrer in context.referencing_classes(entity)
        })

        return {
            "wmc": float(sum(complexities)),
            "number_of_methods": float(method_count),
            "number_of_public_methods": float(
                sum(1 for m in methods if not m.name.startswith("_"))
            ),
            "number_of_fields": float(len(declared_fields)),
            "dit": float(context.inheritance_depth(entity)),
            "noc": float(len(context.subclasses_of(entity))),
            "cbo": float(len(referenced_classes)),
            "fan_in": float(fan_in),
            "fan_out": float(len(referenced_classes)),
            "rfc": float(method_count + len(called)),
            "lcom1": float(lcom1(method_fields)),
            "lcom_hs": lcom_hs(method_fields, declared_fields),
            "average_method_complexity": (
                float(sum(complexities) / method_count) if method_count else 0.0
            ),
            "number_of_base_classes": float(len(facts.base_names)),
        }


class MethodCalculator(_PythonCalculator):
    """Structural metrics for callables, and the Feature Envy inputs."""

    @property
    def metric_names(self) -> tuple[str, ...]:
        return (
            "parameter_count",
            "parameter_count_excluding_self",
            "local_variable_count",
            "return_count",
            "call_count",
            "distinct_call_count",
            "max_message_chain",
            "magic_number_count",
            "foreign_access_ratio",
            "accessed_field_count",
            "decorator_count",
            "nesting_depth",
        )

    @property
    def applies_to(self) -> frozenset[EntityType]:
        return frozenset({EntityType.METHOD, EntityType.FUNCTION})

    def compute(
        self, entity: CodeEntity, context: AnalysisContext
    ) -> dict[str, float]:
        facts = context.facts(entity)
        node = context.native_node(entity)

        if node is None:
            return dict.fromkeys(self.metric_names, 0.0)

        return {
            "parameter_count": float(facts.parameter_count),
            "parameter_count_excluding_self": float(
                max(facts.parameter_count - (1 if facts.has_self_parameter else 0), 0)
            ),
            "local_variable_count": float(len(local_variable_names(node))),
            "return_count": float(count_returns(node)),
            "call_count": float(len(facts.called_names)),
            "distinct_call_count": float(len(set(facts.called_names))),
            "max_message_chain": float(max_message_chain(node)),
            "magic_number_count": float(count_magic_numbers(node)),
            "foreign_access_ratio": foreign_access_ratio(
                node, _module_roots(context, entity)
            ),
            "accessed_field_count": float(len(facts.accessed_fields)),
            "decorator_count": float(len(facts.decorators)),
            "nesting_depth": float(max_nesting_depth(node)),
        }


def _module_roots(context: AnalysisContext, entity: CodeEntity) -> frozenset[str]:
    """Names bound by imports in the entity's module.

    Attribute access through one of these is a qualified name, not data
    belonging to another object.
    """
    lookup = getattr(context, "imports_for", None)
    if lookup is None:
        return frozenset()
    return frozenset(lookup(entity))


def _classes_named(context: AnalysisContext, name: str) -> tuple[CodeEntity, ...]:
    """Project classes whose simple name matches, via the context's index."""
    finder = getattr(context, "classes_named", None)
    if finder is not None:
        return tuple(finder(name))
    return tuple(
        entity
        for entity in context.entities()
        if entity.entity_type is EntityType.CLASS and entity.name == name
    )


__all__ = [
    "MethodCalculator",
    "ObjectOrientedCalculator",
    "attribute_chain_root",
    "count_magic_numbers",
    "count_returns",
    "foreign_access_ratio",
    "lcom1",
    "lcom_hs",
    "local_variable_names",
    "max_message_chain",
]
