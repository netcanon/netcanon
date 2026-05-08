"""
In-memory adapter registry.

Adapters register themselves at import time via the ``@register`` class
decorator — each codec module imports this module and decorates its
``CodecBase`` subclass on definition.  The set of in-tree adapters
loaded at startup is driven by which codec packages
``netcanon.migration.codecs.__init__`` imports; third-party packages
that ship their own codec module can call ``register`` from anywhere
to extend the set without forking the in-tree code.  Future entry-
point-based discovery (a ``pyproject.toml``-declared ``entry_points``
group) would slot in alongside this mechanism rather than replace it.

Thread-safety: registration happens at import time, before any request
handling, so the dict is effectively read-only at runtime.  If that
assumption changes, wrap ``_REGISTRY`` in a lock.
"""

from __future__ import annotations

from typing import TypeVar

from .base import CodecBase

#: Module-level registry keyed on ``CodecBase.name``.  Never mutate
#: directly; always go through :func:`register`.
_REGISTRY: dict[str, type[CodecBase]] = {}

_T = TypeVar("_T", bound="type[CodecBase]")


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


def get_codec(name: str) -> CodecBase:
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


def list_codecs() -> list[str]:
    """Return registered adapter names, sorted alphabetically."""
    return sorted(_REGISTRY)
