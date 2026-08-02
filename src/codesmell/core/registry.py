"""Generic plugin registry.

One registry class serves parsers, metric calculators, smell detectors,
explainers and report writers. Registration is explicit -- no import-time magic,
no entry-point scanning -- so the set of active plugins is always inspectable
and testable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Generic, TypeVar

from codesmell.core.errors import DuplicateRegistrationError, UnknownPluginError

K = TypeVar("K")
V = TypeVar("V")


class Registry(Generic[K, V]):
    """An append-only mapping from key to plugin instance.

    Example::

        parsers: Registry[Language, SourceParser] = Registry("parser")
        parsers.register(Language.PYTHON, PythonParser())
        parsers.get(Language.PYTHON).parse(src, file)
    """

    __slots__ = ("_items", "_name")

    def __init__(self, name: str) -> None:
        self._name = name
        self._items: dict[K, V] = {}

    @property
    def name(self) -> str:
        return self._name

    def register(self, key: K, value: V, *, replace: bool = False) -> V:
        """Register ``value`` under ``key``.

        Raises :class:`DuplicateRegistrationError` unless ``replace`` is set, so
        a typo in a plugin key fails loudly at startup instead of silently
        shadowing a working plugin.
        """
        if key in self._items and not replace:
            raise DuplicateRegistrationError(
                f"{self._name!r} already has an entry for {key!r}",
                registry=self._name,
                key=str(key),
            )
        self._items[key] = value
        return value

    def decorator(self, key: K, *, replace: bool = False) -> Callable[[V], V]:
        """Register via decorator, returning the decorated object unchanged."""

        def _wrap(value: V) -> V:
            self.register(key, value, replace=replace)
            return value

        return _wrap

    def get(self, key: K) -> V:
        try:
            return self._items[key]
        except KeyError:
            raise UnknownPluginError(
                f"no {self._name} registered for {key!r}",
                registry=self._name,
                key=str(key),
                available=[str(k) for k in self._items],
            ) from None

    def find(self, key: K) -> V | None:
        """Like :meth:`get` but returns ``None`` instead of raising."""
        return self._items.get(key)

    def unregister(self, key: K) -> None:
        self._items.pop(key, None)

    def clear(self) -> None:
        """Reset the registry. Intended for test isolation."""
        self._items.clear()

    def keys(self) -> tuple[K, ...]:
        return tuple(self._items)

    def values(self) -> tuple[V, ...]:
        return tuple(self._items.values())

    def as_mapping(self) -> Mapping[K, V]:
        return dict(self._items)

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[K]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"Registry({self._name!r}, entries={len(self._items)})"
