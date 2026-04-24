"""
Canonical SNMPv3 USM user-name rename orchestrator.

Fifth per-pane override category after port_names.py (physical +
logical interface naming), vlan_names.py (VLAN-ID rewrite),
local_user_names.py (local-admin user-name rewrite), and
snmp_names.py (v1/v2c community rename).  Where the previous four
operate on list-like surfaces (``interfaces``, ``vlans``,
``local_users``) or a scalar (``snmp.community``), this
orchestrator operates on :attr:`CanonicalSNMP.v3_users` — a list
of :class:`CanonicalSNMPv3User` records keyed by USM
``securityName`` (the user's login-like identity).

Why it exists as a separate pane:

  * **SNMPv3 users and v1/v2c communities are orthogonal identity
    surfaces.**  Many real migrations keep v2c community
    (``public`` → ``monitoring-ro``) on the wire for legacy
    observability platforms AND rename v3 users (``netadmin`` →
    ``platform-snmpro``) for the modern monitoring stack.
    Bundling both into one pane forces the operator to make both
    decisions at once — mixing two mental models.
  * **User rename is the dominant migration use case.**  Auth /
    priv keys are typically re-generated on the target device
    regardless of rename (cross-vendor hash incompatibility) so
    the rename surface is purely the ``name`` + ``group``
    identity.  Keys stay verbatim on canonical, lossy on render
    for cross-vendor hops.
  * **Groups are metadata, not identity.**  VACM group names
    differ across vendors (``v3ReadOnlyGroup`` vs ``RO`` vs
    ``monitoring``) but rename is driven by the user identity;
    ops teams rebuild groups on the target when they rebuild
    the monitoring platform anyway.  ``group`` carries through
    unchanged by design — same policy as SNMP location / contact.

Rename-map shape (``dict[str, str | None]``):

  * ``{src: tgt}`` where ``tgt`` is a non-empty str → rewrite
    every ``CanonicalSNMPv3User.name == src`` to ``tgt``.
  * ``{src: None}`` → drop the user (remove from
    ``intent.snmp.v3_users``).
  * key NOT in map → user passes through unchanged.
  * map is empty / None → no-op.

Collisions: two source names mapped to the same target name (or a
target name that already exists in the tree) merge on
FIRST-WINS.  Auth protocol + passphrase + priv protocol +
passphrase + group from the first matched record are kept; later
records silently drop.  Merging by-union would risk preserving
stale crypto on the target (rare but hard to debug); first-wins
matches the local-user rename convention and keeps the semantic
predictable.

Identity is by ``name`` alone.  ``group`` + ``auth_*`` + ``priv_*``
are attributes, not identity — renaming a user preserves their
crypto configuration, dropping a user erases it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .intent import CanonicalIntent

logger = logging.getLogger(__name__)


class SnmpV3UserRenameResult(BaseModel):
    """Outcome of :func:`translate_snmpv3_users`.

    Mirrors :class:`LocalUserRenameResult` structure — exposed so
    the UI can show exactly which users were renamed, which were
    dropped, and which override entries produced warnings.
    """

    applied: dict[str, str] = Field(default_factory=dict)
    """Map of source_name → target_name rewrites that landed on
    the canonical tree.  Source names that didn't exist in the
    tree don't appear here (they produce warnings instead)."""

    dropped: list[str] = Field(default_factory=list)
    """Source user names the operator explicitly removed (map
    value was ``None``).  The corresponding
    :class:`CanonicalSNMPv3User` records were removed from
    ``intent.snmp.v3_users``."""

    warnings: list[str] = Field(default_factory=list)
    """Per-entry advisories — typically "source user name X does
    not exist in the canonical tree" when an operator's override
    map references a user the parse didn't find, or "rename
    target X collides with existing user Y; first-wins merge
    applied"."""


def translate_snmpv3_users(
    intent: "CanonicalIntent",
    rename_map: dict[str, str | None] | None = None,
) -> SnmpV3UserRenameResult:
    """Apply *rename_map* to ``intent.snmp.v3_users`` in-place and
    return a summary.

    Edge cases:

    * ``intent.snmp is None`` — source config had no SNMP block at
      all.  No-op; empty result returned.  Over-eager operator
      rename maps produce warnings.
    * ``intent.snmp.v3_users`` empty — source had v1/v2c only.
      Same behaviour as no-SNMP-block case.
    * Target name collision — two sources mapped to the same
      target, or target name already exists.  First-match wins;
      subsequent records drop silently with a warning.
    * Drop of a name that was previously renamed — later entries
      in the map window out earlier ones (processed in insertion
      order).

    Args:
        intent: Canonical tree to mutate in-place.
        rename_map: ``{src: tgt | None}`` override map.  None /
            empty = no-op.

    Returns:
        :class:`SnmpV3UserRenameResult` summarising the change.
    """
    from .intent import CanonicalIntent  # isinstance guard

    v3_count_pre = 0
    if isinstance(intent, CanonicalIntent) and intent.snmp is not None:
        v3_count_pre = len(intent.snmp.v3_users)
    logger.debug(
        "translate_snmpv3_users: entry rename_map=%s v3_users_pre=%d",
        "None" if rename_map is None
        else f"{len(rename_map)}-entry dict",
        v3_count_pre,
    )

    result = SnmpV3UserRenameResult()

    # Defensive no-op against mock adapters that produce plain dicts.
    if not isinstance(intent, CanonicalIntent):
        return result

    if not rename_map:
        return result

    # Normalise + validate the map.
    valid_map: dict[str, str | None] = {}
    for src, tgt in rename_map.items():
        if not isinstance(src, str) or not src.strip():
            result.warnings.append(
                f"snmpv3_user_rename: source name {src!r} is "
                f"empty or not a string"
            )
            continue
        if tgt is None:
            valid_map[src] = None
            continue
        if not isinstance(tgt, str) or not tgt.strip():
            result.warnings.append(
                f"snmpv3_user_rename: target name {tgt!r} for "
                f"source {src!r} is empty or not a string"
            )
            continue
        valid_map[src] = tgt

    if not valid_map:
        return result

    if intent.snmp is None or not intent.snmp.v3_users:
        result.warnings.append(
            "snmpv3_user_rename: source config has no SNMPv3 users; "
            "overrides are no-ops"
        )
        return result

    # Index users by name for fast collision + existence checks.
    # ``intent.snmp.v3_users`` is a list; we rebuild it at the end
    # with the rewritten + de-duplicated records.
    existing_names = {u.name for u in intent.snmp.v3_users}

    # First pass: apply rewrites + drops.  Iterate the original list
    # to preserve order for non-matched records; collect intended
    # changes in a parallel map.
    decisions: dict[str, str | None] = {}
    for src, tgt in valid_map.items():
        if src not in existing_names:
            result.warnings.append(
                f"snmpv3_user_rename: source user {src!r} does not "
                f"exist in the parsed config"
            )
            continue
        decisions[src] = tgt

    # Build the new list.  Walk the original order; apply decisions;
    # skip drops; detect target collisions.
    new_users: list = []
    seen_targets: dict[str, str] = {}   # target_name -> source_name who won
    for u in intent.snmp.v3_users:
        decision = decisions.get(u.name, "__pass__")
        if decision is None:
            # Drop.
            result.dropped.append(u.name)
            continue
        if decision == "__pass__":
            new_name = u.name
        else:
            new_name = decision
            result.applied[u.name] = decision
        if new_name in seen_targets and seen_targets[new_name] != u.name:
            # Collision: a previous user (renamed or not) already
            # occupies this target name.  First-wins — drop this one
            # with a warning.
            result.warnings.append(
                f"snmpv3_user_rename: target name {new_name!r} "
                f"collides with previously-seen user "
                f"{seen_targets[new_name]!r}; dropping {u.name!r} "
                f"(first-wins)"
            )
            continue
        seen_targets[new_name] = u.name
        # Mutate in-place to preserve all other attributes (group,
        # auth, priv, engine_id).
        u.name = new_name
        new_users.append(u)

    intent.snmp.v3_users = new_users

    logger.debug(
        "translate_snmpv3_users: exit applied=%d dropped=%d "
        "warnings=%d v3_users_post=%d",
        len(result.applied),
        len(result.dropped),
        len(result.warnings),
        len(intent.snmp.v3_users),
    )
    return result


def build_snmpv3_user_rename_transform(
    rename_map: dict[str, str | None] | None = None,
) -> tuple[
    Callable[["CanonicalIntent"], "CanonicalIntent"],
    SnmpV3UserRenameResult,
]:
    """Return a pipeline-compatible transform + a result accumulator.

    Pattern mirrors :func:`build_port_rename_transform` /
    :func:`build_vlan_rename_transform` /
    :func:`build_local_user_rename_transform` /
    :func:`build_snmp_community_rename_transform`.  The pipeline
    applies the transform to the parsed canonical tree; the
    returned :class:`SnmpV3UserRenameResult` is populated as a
    side-effect and attached to the :class:`MigrationJob` after
    the pipeline run.

    Args:
        rename_map: As accepted by :func:`translate_snmpv3_users`.

    Returns:
        Tuple of ``(transform_fn, result)``.  The transform returns
        the same ``intent`` it was given (mutation is in-place).
    """
    result = SnmpV3UserRenameResult()

    def _transform(intent: "CanonicalIntent") -> "CanonicalIntent":
        outcome = translate_snmpv3_users(
            intent, rename_map=rename_map,
        )
        result.applied.update(outcome.applied)
        result.dropped.extend(outcome.dropped)
        result.warnings.extend(outcome.warnings)
        return intent

    return _transform, result
