"""Python source parser.

Uses the standard library :mod:`ast`, which is the correct choice here: it is
the same parser CPython uses, so it agrees with the language definition by
construction, and it needs no build step or grammar file.

The collector runs one pass per module and emits both entities and
:class:`~codesmell.core.models.EntityFacts`. Facts are gathered here rather
than in the metric calculators because a class's reference set includes names
appearing inside its methods, which is a single-traversal problem and an
O(n^2) one if each calculator re-walks the tree.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from codesmell.config.logging import get_logger
from codesmell.core.enums import EntityType, Language
from codesmell.core.models import CodeEntity, EntityFacts, ParsedModule, SourceFile
from codesmell.core.ports import SourceParser

logger = get_logger(__name__)

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Parameters that name the receiver rather than real input.
_RECEIVER_NAMES = frozenset({"self", "cls", "mcs", "metacls"})


class PythonParser(SourceParser):
    """Parses Python source into entities, facts and native AST nodes."""

    @property
    def language(self) -> Language:
        return Language.PYTHON

    def parse(self, source: str, source_file: SourceFile) -> ParsedModule:
        try:
            tree = ast.parse(source, filename=source_file.relative_path)
        except (SyntaxError, ValueError) as exc:
            # Python 2 files, templated sources and truncated uploads all land
            # here. One bad file must never abort a whole-project analysis.
            logger.debug(
                "unparseable module",
                extra={"path": source_file.relative_path, "error": str(exc)},
            )
            return ParsedModule(
                source_file=source_file, parse_error=f"{type(exc).__name__}: {exc}"
            )
        except RecursionError:
            return ParsedModule(
                source_file=source_file,
                parse_error="RecursionError: expression nesting too deep",
            )

        collector = _EntityCollector(source_file)
        collector.run(tree)

        return ParsedModule(
            source_file=source_file,
            entities=tuple(collector.entities),
            facts=dict(collector.facts),
            native_nodes=dict(collector.nodes),
            imports=dict(collector.imports),
        )


class _EntityCollector:
    """Single-pass entity and fact extraction for one module."""

    def __init__(self, source_file: SourceFile) -> None:
        self._source_file = source_file
        self._module_name = source_file.package_path or source_file.name
        self.entities: list[CodeEntity] = []
        self.facts: dict[str, EntityFacts] = {}
        self.nodes: dict[str, ast.AST] = {}
        self.imports: dict[str, str] = {}

    # ------------------------------------------------------------------ #

    def run(self, tree: ast.Module) -> None:
        self._collect_imports(tree)
        self._add_module_entity(tree)
        self._walk_body(tree.body, scope=self._module_name, inside_class=False)

    def _collect_imports(self, tree: ast.Module) -> None:
        """Map local binding -> dotted origin, for later name resolution."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    origin = f"{module}.{alias.name}" if module else alias.name
                    self.imports[alias.asname or alias.name] = origin

    def _add_module_entity(self, tree: ast.Module) -> None:
        end_line = max(
            (getattr(n, "end_lineno", 0) or 0 for n in ast.walk(tree)), default=1
        )
        entity = self._make_entity(
            entity_type=EntityType.MODULE,
            name=self._source_file.name,
            qualified_name=self._module_name,
            start_line=1,
            end_line=max(end_line, 1),
            parent=None,
        )
        self._record(entity, tree, self._module_facts(tree))

    # ------------------------------------------------------------------ #

    def _walk_body(
        self, body: list[ast.stmt], *, scope: str, inside_class: bool
    ) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                self._handle_class(node, scope)
            elif isinstance(node, _FUNCTION_NODES):
                self._handle_function(node, scope, inside_class=inside_class)

    def _handle_class(self, node: ast.ClassDef, scope: str) -> None:
        qualified = f"{scope}.{node.name}"
        entity = self._make_entity(
            entity_type=EntityType.CLASS,
            name=node.name,
            qualified_name=qualified,
            start_line=node.lineno,
            end_line=_end_line(node),
            parent=scope,
        )
        self._record(entity, node, self._class_facts(node))
        self._walk_body(node.body, scope=qualified, inside_class=True)

    def _handle_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, scope: str, *,
        inside_class: bool,
    ) -> None:
        qualified = f"{scope}.{node.name}"
        entity = self._make_entity(
            entity_type=EntityType.METHOD if inside_class else EntityType.FUNCTION,
            name=node.name,
            qualified_name=qualified,
            start_line=node.lineno,
            end_line=_end_line(node),
            parent=scope,
        )
        self._record(entity, node, self._function_facts(node))
        # Nested definitions are entities in their own right; a closure can be
        # a Long Method just as a top-level function can.
        self._walk_body(node.body, scope=qualified, inside_class=False)

    # ------------------------------------------------------------------ #

    def _make_entity(
        self,
        *,
        entity_type: EntityType,
        name: str,
        qualified_name: str,
        start_line: int,
        end_line: int,
        parent: str | None,
    ) -> CodeEntity:
        return CodeEntity(
            entity_id=f"{self._source_file.relative_path}::{qualified_name}",
            entity_type=entity_type,
            name=name,
            qualified_name=qualified_name,
            relative_path=self._source_file.relative_path,
            start_line=start_line,
            end_line=max(end_line, start_line),
            language=Language.PYTHON,
            parent_qualified_name=parent,
        )

    def _record(self, entity: CodeEntity, node: ast.AST, facts: EntityFacts) -> None:
        self.entities.append(entity)
        self.nodes[entity.entity_id] = node
        self.facts[entity.entity_id] = facts

    # ------------------------------------------------------------------ #
    # Fact extraction
    # ------------------------------------------------------------------ #

    def _module_facts(self, node: ast.Module) -> EntityFacts:
        return EntityFacts(
            references=tuple(sorted(_referenced_names(node))),
            called_names=tuple(_called_names(node)),
        )

    def _class_facts(self, node: ast.ClassDef) -> EntityFacts:
        return EntityFacts(
            references=tuple(sorted(_referenced_names(node))),
            called_names=tuple(_called_names(node)),
            base_names=tuple(_base_names(node)),
            declared_fields=tuple(sorted(_class_fields(node))),
            decorators=tuple(_decorator_names(node)),
        )

    def _function_facts(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> EntityFacts:
        arguments = node.args
        positional = [*arguments.posonlyargs, *arguments.args]
        parameters = [
            *positional,
            *arguments.kwonlyargs,
            *([arguments.vararg] if arguments.vararg else []),
            *([arguments.kwarg] if arguments.kwarg else []),
        ]
        has_self = bool(positional) and positional[0].arg in _RECEIVER_NAMES

        return EntityFacts(
            references=tuple(sorted(_referenced_names(node))),
            called_names=tuple(_called_names(node)),
            accessed_fields=tuple(sorted(_self_attributes(node))),
            decorators=tuple(_decorator_names(node)),
            parameter_count=len(parameters),
            has_self_parameter=has_self,
        )


# --------------------------------------------------------------------- #
# AST helpers
# --------------------------------------------------------------------- #


def _end_line(node: ast.AST) -> int:
    """Last physical line of a node, decorators excluded."""
    end = getattr(node, "end_lineno", None)
    if end is not None:
        return int(end)
    return max(
        (getattr(child, "lineno", 0) for child in ast.walk(node)),
        default=int(getattr(node, "lineno", 1)),
    )


def _referenced_names(node: ast.AST) -> set[str]:
    """Every simple and dotted-root name referenced inside ``node``.

    ``models.Order`` contributes both ``models`` and ``Order`` so that a class
    can be matched whether it is imported directly or reached via its module.
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
            root = _attribute_root(child)
            if root:
                names.add(root)
    return names


def _attribute_root(node: ast.Attribute) -> str | None:
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _called_names(node: ast.AST) -> list[str]:
    """Names invoked as calls, duplicates kept -- RFC counts distinct later."""
    called: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            called.append(func.id)
        elif isinstance(func, ast.Attribute):
            called.append(func.attr)
    return called


def _self_attributes(node: ast.AST) -> set[str]:
    """``self.x`` accesses, which are the instance fields LCOM is defined over."""
    fields: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id in _RECEIVER_NAMES
        ):
            fields.add(child.attr)
    return fields


def _base_names(node: ast.ClassDef) -> list[str]:
    """Superclass names as written, ignoring keyword bases like ``metaclass=``."""
    names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
        elif isinstance(base, ast.Subscript):
            # Generic[T] / Protocol[T]: the origin is what matters.
            origin = base.value
            if isinstance(origin, ast.Name):
                names.append(origin.id)
            elif isinstance(origin, ast.Attribute):
                names.append(origin.attr)
    return names


def _class_fields(node: ast.ClassDef) -> set[str]:
    """Fields declared by a class: class-level assignments plus ``self.x``."""
    fields: set[str] = set()

    for statement in node.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    fields.add(target.id)
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target, ast.Name
        ):
            fields.add(statement.target.id)

    for statement in node.body:
        if isinstance(statement, _FUNCTION_NODES):
            fields |= _assigned_self_attributes(statement)

    return fields


def _assigned_self_attributes(node: ast.AST) -> set[str]:
    """``self.x = ...`` only -- a read does not declare a field."""
    fields: set[str] = set()
    for child in ast.walk(node):
        targets: Iterator[ast.expr]
        if isinstance(child, ast.Assign):
            targets = iter(child.targets)
        elif isinstance(child, ast.AnnAssign | ast.AugAssign):
            targets = iter([child.target])
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id in _RECEIVER_NAMES
            ):
                fields.add(target.attr)
    return fields


def _decorator_names(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> (
    list[str]
):
    names: list[str] = []
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return names
