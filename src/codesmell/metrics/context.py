"""The cross-file analysis context.

CBO, RFC, fan-in, DIT and NOC cannot be computed from a single file, which is
why the metrics engine runs in two passes: parse everything, build this index,
then compute. A single-file metrics pass silently produces wrong coupling
numbers -- nothing crashes, the values are just quietly meaningless, which is
the worst failure mode in a research pipeline.

Name resolution is deliberately explicit about being approximate. Python is
dynamically typed, so ``Base`` in ``class Order(Base)`` cannot always be
resolved to a definition. The strategy is: same module first, then imports,
then a unique project-wide match by simple name, then give up. Giving up is
recorded rather than guessed at, because a wrong DIT is worse than a missing
one -- it becomes a feature the model learns from.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from codesmell.core.enums import EntityType
from codesmell.core.models import (
    CodeEntity,
    EntityFacts,
    ParsedModule,
    ProjectInventory,
)

_EMPTY_FACTS = EntityFacts()

#: Guard against inheritance cycles, which are illegal in Python but reachable
#: through unresolvable names, and against pathological deep hierarchies.
_MAX_INHERITANCE_DEPTH = 32


class ProjectAnalysisContext:
    """Indexed, read-only view of every parsed module in one project."""

    def __init__(
        self,
        inventory: ProjectInventory,
        modules: Sequence[ParsedModule],
        sources: Mapping[str, str],
    ) -> None:
        self._inventory = inventory
        self._modules = tuple(modules)
        self._sources = dict(sources)

        self._by_id: dict[str, CodeEntity] = {}
        self._by_qualified_name: dict[str, CodeEntity] = {}
        self._facts: dict[str, EntityFacts] = {}
        self._nodes: dict[str, Any] = {}
        self._imports_by_path: dict[str, Mapping[str, str]] = {}
        self._module_by_path: dict[str, str] = {}

        self._children: dict[str, list[CodeEntity]] = defaultdict(list)
        self._classes_by_simple_name: dict[str, list[CodeEntity]] = defaultdict(list)
        self._classes_by_module: dict[str, list[CodeEntity]] = defaultdict(list)

        self._index_entities()

        self._subclasses: dict[str, list[CodeEntity]] = defaultdict(list)
        self._referencing: dict[str, list[CodeEntity]] = defaultdict(list)
        self._depth_cache: dict[str, int] = {}
        self._unresolved_bases: set[str] = set()

        self._build_hierarchy()
        self._build_reference_graph()

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def _index_entities(self) -> None:
        for module in self._modules:
            path = module.source_file.relative_path
            self._imports_by_path[path] = module.imports
            self._module_by_path[path] = module.source_file.package_path
            for entity in module.entities:
                self._by_id[entity.entity_id] = entity
                # First declaration wins: shadowed redefinitions in the same
                # project are rare and ambiguous, and picking the later one
                # would make results depend on file ordering.
                self._by_qualified_name.setdefault(entity.qualified_name, entity)
                self._facts[entity.entity_id] = module.facts_for(entity)
                self._nodes[entity.entity_id] = module.native_nodes.get(
                    entity.entity_id
                )

                if entity.parent_qualified_name:
                    self._children[entity.parent_qualified_name].append(entity)

                if entity.entity_type is EntityType.CLASS:
                    self._classes_by_simple_name[entity.name].append(entity)
                    self._classes_by_module[
                        module.source_file.package_path
                    ].append(entity)

    def _build_hierarchy(self) -> None:
        for entity in self._by_id.values():
            if entity.entity_type is not EntityType.CLASS:
                continue
            for base_name in self._facts[entity.entity_id].base_names:
                base = self.resolve_class(base_name, entity)
                if base is None:
                    self._unresolved_bases.add(f"{entity.qualified_name}->{base_name}")
                    continue
                self._subclasses[base.entity_id].append(entity)

    def _build_reference_graph(self) -> None:
        """Invert the reference relation once, so fan-in is O(1) per class."""
        for entity in self._by_id.values():
            if entity.entity_type is not EntityType.CLASS:
                continue
            for name in set(self._facts[entity.entity_id].references):
                for target in self._classes_by_simple_name.get(name, ()):
                    if target.entity_id != entity.entity_id:
                        self._referencing[target.entity_id].append(entity)

    # ------------------------------------------------------------------ #
    # AnalysisContext protocol
    # ------------------------------------------------------------------ #

    @property
    def inventory(self) -> ProjectInventory:
        return self._inventory

    @property
    def modules(self) -> tuple[ParsedModule, ...]:
        return self._modules

    @property
    def unresolved_base_count(self) -> int:
        """How many superclass names could not be resolved.

        Surfaced in the analysis report: a high count means DIT and NOC are
        weakly grounded for this project and should be read with caution.
        """
        return len(self._unresolved_bases)

    def entities(self) -> Iterable[CodeEntity]:
        return self._by_id.values()

    def entity_by_id(self, entity_id: str) -> CodeEntity | None:
        return self._by_id.get(entity_id)

    def entity_by_qualified_name(self, qualified_name: str) -> CodeEntity | None:
        return self._by_qualified_name.get(qualified_name)

    def facts(self, entity: CodeEntity) -> EntityFacts:
        return self._facts.get(entity.entity_id, _EMPTY_FACTS)

    def native_node(self, entity: CodeEntity) -> Any:
        return self._nodes.get(entity.entity_id)

    def source_of(self, entity: CodeEntity) -> str:
        source = self._sources.get(entity.relative_path, "")
        if not source:
            return ""
        lines = source.splitlines()
        return "\n".join(lines[entity.start_line - 1 : entity.end_line])

    def children_of(self, entity: CodeEntity) -> Sequence[CodeEntity]:
        return tuple(self._children.get(entity.qualified_name, ()))

    def methods_of(self, entity: CodeEntity) -> tuple[CodeEntity, ...]:
        """Direct methods of a class, excluding nested classes."""
        return tuple(
            child
            for child in self.children_of(entity)
            if child.entity_type is EntityType.METHOD
        )

    def resolve_class(self, name: str, origin: CodeEntity) -> CodeEntity | None:
        """Resolve a class name from ``origin``'s point of view.

        Order: same module, then an import binding, then a project-wide unique
        simple-name match. An ambiguous simple name resolves to nothing rather
        than to an arbitrary candidate.
        """
        if not name:
            return None

        module_name = self._module_by_path.get(origin.relative_path, "")
        for candidate in self._classes_by_module.get(module_name, ()):
            if candidate.name == name:
                return candidate

        imports = self._imports_by_path.get(origin.relative_path, {})
        origin_path = imports.get(name)
        if origin_path:
            direct = self._by_qualified_name.get(origin_path)
            if direct is not None and direct.entity_type is EntityType.CLASS:
                return direct
            simple = origin_path.rsplit(".", 1)[-1]
            candidates = self._classes_by_simple_name.get(simple, [])
            if len(candidates) == 1:
                return candidates[0]

        candidates = self._classes_by_simple_name.get(name, [])
        return candidates[0] if len(candidates) == 1 else None

    def subclasses_of(self, entity: CodeEntity) -> Sequence[CodeEntity]:
        return tuple(self._subclasses.get(entity.entity_id, ()))

    def inheritance_depth(self, entity: CodeEntity) -> int:
        """Longest resolvable path from ``entity`` up to a project root class.

        A class with no bases, or whose bases all live outside the project, has
        depth 0. Depth counts only edges this project can actually see, which
        is the honest answer -- inventing a depth for an unresolvable external
        base would fabricate a feature value.
        """
        return self._depth(entity, set())

    def _depth(self, entity: CodeEntity, seen: set[str]) -> int:
        cached = self._depth_cache.get(entity.entity_id)
        if cached is not None:
            return cached
        if entity.entity_id in seen or len(seen) > _MAX_INHERITANCE_DEPTH:
            return 0

        seen = seen | {entity.entity_id}
        best = 0
        for base_name in self.facts(entity).base_names:
            base = self.resolve_class(base_name, entity)
            if base is None:
                continue
            best = max(best, 1 + self._depth(base, seen))

        self._depth_cache[entity.entity_id] = best
        return best

    def referencing_classes(self, entity: CodeEntity) -> Sequence[CodeEntity]:
        return tuple(self._referencing.get(entity.entity_id, ()))

    def imports_for(self, entity: CodeEntity) -> Mapping[str, str]:
        """Import bindings visible in the entity's module."""
        return self._imports_by_path.get(entity.relative_path, {})

    def classes_named(self, name: str) -> tuple[CodeEntity, ...]:
        """Project classes with this simple name, straight from the index.

        Coupling metrics call this once per referenced name per class. Without
        the index it is a full entity scan each time, which turns CBO into an
        O(n^2) pass over the project.
        """
        return tuple(self._classes_by_simple_name.get(name, ()))

    def project_classes(self) -> tuple[CodeEntity, ...]:
        return tuple(
            entity
            for entity in self._by_id.values()
            if entity.entity_type is EntityType.CLASS
        )

    def __repr__(self) -> str:
        return (
            f"ProjectAnalysisContext(entities={len(self._by_id)}, "
            f"modules={len(self._modules)})"
        )
