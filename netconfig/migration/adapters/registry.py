"""
In-memory adapter registry.

Phase 0 uses a trivial module-level dict populated by the ``@register``
decorator at adapter-module import time.  Phase 3 will switch to
entry-point discovery so third-party adapters can plug in via
``pyproject.toml`` without editing the registry.

Thread-safety: registration happens at import time, before any request
handling, so the dict is effectively read-only at runtime.  If that
assumption changes, wrap ``_REGISTRY`` in a lock.
"""

from __future__ import annotations

from typing import TypeVar

from .base import AdapterBase

#: Module-level registry keyed on ``AdapterBase.name``.  Never mutate
#: directly; always go through :func:`register`.
_REGISTRY: dict[str, type[AdapterBase]] = {}

_T = TypeVar("_T", bound="type[AdapterBase]")


def register(cls: _T) -> _T:
    """Class decorator: register *cls* under its ``name`` attribute.

    Raises:
        ValueError: If ``cls.name`` is missing/empty, or another adapter
            is already registered under the same name.  Re-registering
            the same class is allowed (idempotent — useful during test
            re-imports via ``importlib.reload``).
    """
    name = getattr(cls, "name", None)
    if not name:
        raise ValueError(
            f"{cls.__qualname__} is missing a non-empty `name` class attribute"
        )
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"Adapter name collision: {name!r} is already registered to "
            f"{existing.__qualname__}; cannot also register {cls.__qualname__}"
        )
    _REGISTRY[name] = cls
    return cls


def get_adapter(name: str) -> AdapterBase:
    """Instantiate and return the adapter registered under *name*.

    Raises:
        LookupError: If no adapter is registered under *name*.
    """
    if name not in _REGISTRY:
        raise LookupError(
            f"No adapter registered: {name!r}. "
            f"Known adapters: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]()


def list_adapters() -> list[str]:
    """Return registered adapter names, sorted alphabetically."""
    return sorted(_REGISTRY)
