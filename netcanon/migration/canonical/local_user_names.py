"""
Canonical local-user rename orchestrator.

Third per-pane override category after port_names.py (physical + logical
interface-name translation) and vlan_names.py (VLAN-ID rewrite).
Local-user renaming is the simplest of the three domains — a
:class:`CanonicalLocalUser` has a vendor-opaque string name, a
privilege level, an opaque password hash, and a role string.  The
rename operation touches only the ``name`` field; the rest passes
through untouched.

Use cases:

  * Username standardisation during a migration (``admin`` on Cisco
    → ``manager`` on Aruba AOS-S to match target platform convention).
  * Dropping stale / unused local accounts that shouldn't follow the
    config to the target device (``svc-backup-2019``, etc.).
  * Merging duplicate accounts: two source users collapse into one
    target name — union of privilege levels (higher wins), union of
    roles, first non-empty hashed_password wins.

Rename-map shape (``dict[str, str | None]``):

  * ``{src: tgt}`` where ``tgt`` is a str → rewrite the user's ``name``
    from ``src`` to ``tgt``.
  * ``{src: None}`` → drop the user entirely; the
    :class:`CanonicalLocalUser` entry is removed from
    ``intent.local_users``.
  * key NOT in map → user passes through unchanged.

Collision semantics:

  * Two source names mapped to the same target name → merge into a
    single user with the higher ``privilege_level``, the non-empty
    ``role`` (first non-empty wins if both set), and the first
    ``hashed_password`` (hashes are opaque — we can't combine them).
  * Mapping a name to one that already exists in the tree as an
    unmapped source → same merge semantics.

Intentionally NOT in scope:

  * Renaming usernames inside vendor-specific ACL / AAA rule text
    that lives in ``intent.raw_sections``.  Tier-3 informational
    data is passed through verbatim; the UI's username-rename map
    is a Tier-2 concept and doesn't reach Tier-3 raw blobs.
  * Changing privilege levels or roles — the rename map is
    strictly about names.  Operators who want to restructure
    privilege mappings should edit the rendered output directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .intent import CanonicalIntent, CanonicalLocalUser

logger = logging.getLogger(__name__)


class LocalUserRenameResult(BaseModel):
    """Outcome of :func:`translate_local_user_names`.

    Mirrors :class:`VlanRenameResult` / :class:`PortRenameResult` —
    exposed so the UI can show exactly which users were renamed,
    which were dropped, and which overrides produced warnings.
    """

    applied: dict[str, str] = Field(default_factory=dict)
    """Map of source_name → target_name for every rewrite that
    happened.  Users whose name didn't change are NOT in this map."""

    dropped: list[str] = Field(default_factory=list)
    """User names the operator explicitly marked "don't render" via
    a ``None`` value in the rename map.  Every reference to these
    names was stripped from the canonical tree before render."""

    warnings: list[str] = Field(default_factory=list)
    """Per-user advisories — collision merges, mapping to non-
    existent source names, empty target names."""


def translate_local_user_names(
    intent: "CanonicalIntent",
    rename_map: dict[str, str | None] | None = None,
) -> LocalUserRenameResult:
    """Apply *rename_map* to *intent* in-place and return a summary.

    For each entry ``{src: tgt}``:
      * ``tgt`` is a non-empty str → rename the user.
      * ``tgt`` is None → drop the user entirely.

    Collisions (two source users → same target name, or target name
    already exists in the tree) merge on a best-effort basis:
    highest ``privilege_level`` wins, first non-empty ``role`` wins,
    first ``hashed_password`` wins (hashes aren't composable).

    Input validation:
      * Empty-string source → warning; entry skipped.
      * Empty-string target (not None) → warning; entry skipped.
      * Mapping a name that doesn't exist in ``intent.local_users``
        → warning + no-op.

    Args:
        intent: Canonical tree to mutate in-place.
        rename_map: ``{source_name: target_name | None}``.  None or
            empty dict → no-op (returns an empty result).

    Returns:
        :class:`LocalUserRenameResult` summarising the changes.
    """
    from .intent import CanonicalIntent  # for isinstance guard

    # Entry log fires on EVERY call — mirrors the pattern used by
    # the other three orchestrators so the pane-engaged trace is
    # uniform across categories.
    logger.debug(
        "translate_local_user_names: entry rename_map=%s "
        "source_users=%d",
        "None" if rename_map is None
        else f"{len(rename_map)}-entry dict",
        len(getattr(intent, "local_users", []) or []),
    )

    result = LocalUserRenameResult()

    # Defensive no-op when called against a non-canonical tree
    # (mock adapters produce plain dicts for testing) — mirrors the
    # guard pattern used by translate_port_names + translate_vlan_ids.
    if not isinstance(intent, CanonicalIntent):
        return result

    if not rename_map:
        return result

    # Normalise + validate the map.  Invalid entries produce
    # warnings and are discarded before any tree mutation.
    valid_map: dict[str, str | None] = {}
    for src, tgt in rename_map.items():
        if not isinstance(src, str) or not src.strip():
            result.warnings.append(
                f"local_user_rename: source name {src!r} is empty or "
                f"not a string"
            )
            continue
        if tgt is None:
            valid_map[src] = None
            continue
        if not isinstance(tgt, str) or not tgt.strip():
            result.warnings.append(
                f"local_user_rename: target name {tgt!r} for source "
                f"{src!r} is empty or not a string"
            )
            continue
        valid_map[src] = tgt

    if not valid_map:
        return result

    # Split renames from drops for clearer downstream logic.
    renames: dict[str, str] = {
        s: t for s, t in valid_map.items() if t is not None
    }
    drops: set[str] = {s for s, t in valid_map.items() if t is None}

    # Collect which names exist in the source tree so "rename to
    # already-existing name" is detectable.
    source_names = {u.name for u in intent.local_users}

    # Warn about rename-map entries whose source doesn't exist in
    # the tree — operator probably made a typo.  Don't skip the
    # pipeline; just flag it.
    for s in list(renames.keys()) + list(drops):
        if s not in source_names:
            result.warnings.append(
                f"local_user_rename: source name {s!r} not found in "
                f"local_users — rename/drop is a no-op"
            )

    # Build the post-rewrite users list.  Defer assignment until
    # collisions are resolved, so a single source might need to be
    # merged INTO another whose rewrite targets the same name.
    kept: list = []
    by_target_name: dict[str, object] = {}

    for u in intent.local_users:
        if u.name in drops:
            result.dropped.append(u.name)
            continue
        new_name = renames.get(u.name, u.name)
        if new_name != u.name:
            result.applied[u.name] = new_name
            # Collision check against existing names in the tree that
            # weren't themselves renamed out of the way.
            if new_name in source_names and new_name not in renames:
                result.warnings.append(
                    f"local_user_rename: target name {new_name!r} already "
                    f"exists in source config — merging source user "
                    f"{u.name!r} into {new_name!r}"
                )
        u.name = new_name
        if new_name in by_target_name:
            existing = by_target_name[new_name]
            _merge_user(existing, u)
            result.warnings.append(
                f"local_user_rename: multiple source users mapped to "
                f"{new_name!r} — merged on privilege level + role"
            )
        else:
            kept.append(u)
            by_target_name[new_name] = u
    intent.local_users = kept

    logger.debug(
        "translate_local_user_names: exit applied=%d dropped=%d "
        "warnings=%d",
        len(result.applied),
        len(result.dropped),
        len(result.warnings),
    )
    return result


def _merge_user(dest: "CanonicalLocalUser", src: "CanonicalLocalUser") -> None:
    """Merge *src* into *dest* in-place.

    Rules:
      * Highest ``privilege_level`` wins (max of the two).
      * First non-empty ``role`` wins (dest preserved if set).
      * First non-empty ``hashed_password`` wins (hashes aren't
        composable; dest preserved if set).
    """
    if src.privilege_level > dest.privilege_level:
        dest.privilege_level = src.privilege_level
    if not dest.role and src.role:
        dest.role = src.role
    if not dest.hashed_password and src.hashed_password:
        dest.hashed_password = src.hashed_password


def build_local_user_rename_transform(
    rename_map: dict[str, str | None] | None = None,
) -> tuple[
    Callable[["CanonicalIntent"], "CanonicalIntent"],
    LocalUserRenameResult,
]:
    """Return a pipeline-compatible transform + a result accumulator.

    Pattern mirrors :func:`build_vlan_rename_transform` and
    :func:`build_port_rename_transform`.  The pipeline applies the
    transform to the parsed canonical tree; the returned
    :class:`LocalUserRenameResult` is populated as a side-effect
    and attached to the :class:`MigrationJob` after the pipeline
    run.

    Args:
        rename_map: As accepted by :func:`translate_local_user_names`.

    Returns:
        Tuple of ``(transform_fn, result)``.  The transform returns
        the same ``intent`` it was given (mutation is in-place).
    """
    result = LocalUserRenameResult()

    def _transform(intent: "CanonicalIntent") -> "CanonicalIntent":
        outcome = translate_local_user_names(intent, rename_map=rename_map)
        result.applied.update(outcome.applied)
        result.dropped.extend(outcome.dropped)
        result.warnings.extend(outcome.warnings)
        return intent

    return _transform, result
