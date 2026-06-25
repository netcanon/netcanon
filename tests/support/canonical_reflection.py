"""Reflection over the canonical model — the shared spine of the
fail-surfaced-defaults completeness guards.

Two recurring blind-spot classes (see
``docs/reviews/2026-06-24-fail-surfaced-defaults/``) both stem from a
hand-maintained *subset* of the canonical model's leaves with a permissive
default:

* the migration walker (`_walk_canonical`) yields a subset of leaves and
  ``classify()`` defaults any *unwalked* leaf to ``supported`` — so a silently
  dropped field reports ``severity: ok`` (the silent capability-loss class), and
* the sanitizer (`sanitize_intent`) redacts a subset of fields — so a new
  IP/secret-bearing field leaks verbatim (the sanitizer-bypass class).

The durable fix in both cases is a CI **completeness guard** that enumerates the
*full* leaf universe by reflection and FAILS when a leaf is neither handled nor
in a self-justifying exemption set. Both guards enumerate the SAME universe, so
the enumerators live here, in one place, rather than being re-derived per guard.

These helpers were first proven in the secret-coverage guard
(``tests/unit/tools/test_sanitize.py``) against pydantic v2 +
``from __future__ import annotations``: pydantic resolves
``model_fields[name].annotation`` to the *live type object* at class-build time,
so we introspect that — NOT ``typing.get_type_hints`` on the raw class, which can
choke on forward refs and needs the defining module's globals.
"""

from __future__ import annotations

import typing

from pydantic import BaseModel

#: Scalar leaf types. A field whose flattened annotation contains one of these
#: is data-bearing (a scalar or a list/optional of a scalar), as opposed to a
#: pure nested-model container (whose *children* are the leaves).
SCALAR_TYPES: tuple[type, ...] = (str, int, bool, float)


def flatten_annotation(ann) -> typing.Iterator:
    """Yield *ann* and every nested type argument.

    Unwraps ``list[...]`` / ``Optional[...]`` / ``dict[...]`` / unions by
    recursing through ``typing.get_args``. A leaf annotation (no args) yields
    itself. NB: ``Literal["a", "b"]`` yields the *values* ``"a"``, ``"b"`` (string
    instances, not the ``str`` type) — callers that care must detect ``Literal``
    via :func:`typing.get_origin`; the current canonical model has no ``Literal``
    field (pinned by ``test_canonical_reflection``).
    """
    args = typing.get_args(ann)
    if not args:
        yield ann
        return
    for a in args:
        yield from flatten_annotation(a)


def reachable_models(root_cls: type[BaseModel], acc: set | None = None) -> set:
    """Return every ``BaseModel`` subclass reachable from *root_cls* via its
    (possibly nested / list-wrapped / optional) field annotations, including
    *root_cls* itself."""
    if acc is None:
        acc = set()
    if root_cls in acc:
        return acc
    acc.add(root_cls)
    for fld in root_cls.model_fields.values():
        for t in flatten_annotation(fld.annotation):
            if isinstance(t, type) and issubclass(t, BaseModel):
                reachable_models(t, acc)
    return acc


def _is_scalar(t) -> bool:
    return isinstance(t, type) and issubclass(t, SCALAR_TYPES)


def _is_model(t) -> bool:
    return isinstance(t, type) and issubclass(t, BaseModel)


def scalar_leaves(root_cls: type[BaseModel]) -> set[tuple[str, str]]:
    """``(ModelName, field)`` for every data-bearing *scalar / list-of-scalar*
    leaf reachable from *root_cls*.

    A pure nested-model container (``interfaces: list[CanonicalInterface]``) is
    NOT a leaf — its child fields are (recursion via :func:`reachable_models`
    covers them). A field whose flattened annotation has neither a scalar nor a
    ``BaseModel`` (e.g. a bare ``dict``) IS yielded, so the caller's exemption set
    must consciously account for it (fail-surfaced: an unclassifiable field is
    surfaced, not silently skipped).
    """
    out: set[tuple[str, str]] = set()
    for model in reachable_models(root_cls):
        for fname, fld in model.model_fields.items():
            flat = set(flatten_annotation(fld.annotation))
            has_scalar = any(_is_scalar(t) for t in flat)
            has_model = any(_is_model(t) for t in flat)
            if has_model and not has_scalar:
                continue  # pure nested-model container — children are the leaves
            out.add((model.__name__, fname))
    return out


def str_leaves(root_cls: type[BaseModel]) -> set[tuple[str, str]]:
    """``(ModelName, field)`` for every leaf whose flattened annotation contains
    ``str`` (a ``str`` scalar, ``list[str]``, ``Optional[str]``, or a
    ``dict[..., str]``) reachable from *root_cls*.

    This is the universe the sanitizer partition guard classifies: only ``str``
    leaves can carry a free-form IP / host / secret. Pure nested-model containers
    and non-``str`` scalars (``int`` ports, ``bool`` flags) are excluded — they
    cannot hold an operator-supplied IP/secret literal.
    """
    out: set[tuple[str, str]] = set()
    for model in reachable_models(root_cls):
        for fname, fld in model.model_fields.items():
            if str in set(flatten_annotation(fld.annotation)):
                out.add((model.__name__, fname))
    return out
