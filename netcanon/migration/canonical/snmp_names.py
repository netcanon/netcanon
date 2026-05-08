"""
Canonical SNMP community-name rename orchestrator.

Fourth per-pane override category after port_names.py (physical +
logical interface naming), vlan_names.py (VLAN-ID rewrite), and
local_user_names.py (user-name rewrite).  Where the first three
operate on LIST-like canonical surfaces (``interfaces``, ``vlans``,
``local_users``), the SNMP canonical surface is narrower —
:class:`CanonicalIntent.snmp` is a single :class:`CanonicalSNMP`
object, not a list.  The rename operation therefore touches ONLY
the ``community`` scalar field.

Why community-only:

  * **Community rename is the dominant operator use case.**  Every
    migration ticket I've seen touches the community string
    (``public`` on old device → ``monitoring-ro`` on new device
    matching monitoring-platform convention).
  * **Location / contact are metadata, not identities.**  Operators
    edit sysLocation and sysContact per-device in their CMDB; the
    migration tool keeping them unchanged is correct.
  * **Trap-host rename is a list-surface problem** (one community
    but N trap hosts).  Deferred to a follow-up commit — the
    orchestrator API + pane UI can grow a parallel
    ``trap_host_rename_map`` field in the same shape as the
    local-user rename map.

Rename-map shape (``dict[str, str | None]``):

  * ``{src: tgt}`` where ``tgt`` is a non-empty str → rewrite
    ``intent.snmp.community`` from ``src`` to ``tgt``.
  * ``{src: None}`` → clear ``intent.snmp.community`` entirely (empty
    string, which every codec's render path treats as
    "don't emit the SNMP block").
  * key NOT in map → community passes through unchanged.
  * map is empty / None → no-op.

Because there's at most ONE community string in the canonical tree,
the map is effectively single-entry.  Using the dict shape (rather
than a scalar ``snmp_community: str | None``) keeps symmetry with
the other three orchestrators: the pipeline param is always
``dict[T, T | None] | None``, the None-vs-empty-dict sentinel
semantics are universal, and the UI sends a ``dict[str, str]``
over the wire identically per pane.

Intentionally NOT in scope for this orchestrator:

  * **SNMPv3 users.**  CanonicalSNMP does not model v3's
    user-based security (securityName / auth protocol / priv
    protocol / engineId).  Adding v3 support is a canonical-schema
    change; see ``docs/adding-a-canonical-field.md`` for the
    worked-example procedure.  Today's community rename only
    affects SNMPv1/v2c sysNAME (the community string).
  * **Trap hosts.**  See above.
  * **Location / contact.**  See above.

Rename semantics quirk (single-value field):

  * The "collision" concept from the list-oriented panes doesn't
    apply — there's only one slot for the community string, so
    two-sources-map-to-same-target is impossible.  The map may
    contain at most one meaningful entry; additional entries whose
    source doesn't match the current community produce warnings
    (same policy as local-user rename when the source name
    doesn't exist in the tree).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .intent import CanonicalIntent

logger = logging.getLogger(__name__)


class SnmpRenameResult(BaseModel):
    """Outcome of :func:`translate_snmp_community`.

    Mirrors :class:`PortRenameResult` / :class:`VlanRenameResult` /
    :class:`LocalUserRenameResult` — exposed so the UI can show
    exactly what changed, what was cleared, and which override
    entries produced warnings.

    ``applied`` is effectively single-entry because there's only one
    community slot, but the dict shape is preserved for symmetry
    with the other three per-pane results.
    """

    applied: dict[str, str] = Field(default_factory=dict)
    """Map of source_community → target_community for the rewrite
    that happened.  Empty when no rename engaged or when the rename
    was a clear (no-op plus drop, not rename)."""

    dropped: list[str] = Field(default_factory=list)
    """Source community names the operator explicitly cleared (map
    value was ``None``).  At most a single-entry list because the
    community is a scalar field."""

    warnings: list[str] = Field(default_factory=list)
    """Per-entry advisories — typically "source community name X
    does not match the parsed config (current is Y)" when an
    operator's override map doesn't agree with the tree they
    intended to override."""


def translate_snmp_community(
    intent: "CanonicalIntent",
    rename_map: dict[str, str | None] | None = None,
) -> SnmpRenameResult:
    """Apply *rename_map* to ``intent.snmp.community`` in-place and
    return a summary.

    Edge cases:

    * ``intent.snmp is None`` — source config had no SNMP block.
      No-op; empty result returned.  An over-eager operator rename
      map produces a warning so the UI can surface "your rename
      applied to a field the source didn't define".
    * ``intent.snmp.community`` is empty string — the source had a
      bare SNMP block (sysLocation only, say) without a community
      configured.  Rename is a no-op; any non-empty target in the
      map is advisory only.  Warning emitted.
    * Multiple entries in the map — only one can match (the scalar
      can't hold multiple values).  Entries whose source doesn't
      match the current community produce warnings; the matching
      entry (if any) takes effect.

    Args:
        intent: Canonical tree to mutate in-place.
        rename_map: ``{source_community: target_community | None}``.
            Empty dict / None → no-op.  Value of None clears the
            community string.

    Returns:
        :class:`SnmpRenameResult` summarising the change.
    """
    from .intent import CanonicalIntent  # isinstance guard

    # Entry log — uniform across all four per-pane orchestrators.
    current_community = ""
    if isinstance(intent, CanonicalIntent) and intent.snmp is not None:
        current_community = intent.snmp.community or ""
    logger.debug(
        "translate_snmp_community: entry rename_map=%s current=%r",
        "None" if rename_map is None
        else f"{len(rename_map)}-entry dict",
        current_community,
    )

    result = SnmpRenameResult()

    # Defensive no-op when called against a non-canonical tree
    # (mock adapters produce plain dicts for testing) — mirrors
    # the guard pattern used by the three sibling orchestrators.
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
                f"snmp_community_rename: source name {src!r} is "
                f"empty or not a string"
            )
            continue
        if tgt is None:
            valid_map[src] = None
            continue
        if not isinstance(tgt, str) or not tgt.strip():
            result.warnings.append(
                f"snmp_community_rename: target name {tgt!r} for "
                f"source {src!r} is empty or not a string"
            )
            continue
        valid_map[src] = tgt

    if not valid_map:
        return result

    # Source tree has no SNMP block at all — nothing to rename.
    if intent.snmp is None:
        result.warnings.append(
            "snmp_community_rename: source config has no SNMP block; "
            "override is a no-op"
        )
        return result

    current = intent.snmp.community or ""

    # Iterate the map in insertion order.  The first entry whose
    # source matches the current community wins; others are
    # advisory-only warnings.
    matched = False
    for src, tgt in valid_map.items():
        if src != current:
            result.warnings.append(
                f"snmp_community_rename: source name {src!r} does not "
                f"match parsed community {current!r} — rewrite skipped"
            )
            continue
        if matched:
            # Defensive — shouldn't happen because src is compared
            # literally and the current community is a single string.
            result.warnings.append(
                f"snmp_community_rename: multiple entries matched "
                f"community {current!r}; using first"
            )
            continue
        if tgt is None:
            # Drop / clear — render paths treat empty-string
            # community as "don't emit the SNMP block".
            result.dropped.append(current)
            intent.snmp.community = ""
        else:
            result.applied[current] = tgt
            intent.snmp.community = tgt
        matched = True

    logger.debug(
        "translate_snmp_community: exit applied=%d dropped=%d "
        "warnings=%d matched=%s",
        len(result.applied),
        len(result.dropped),
        len(result.warnings),
        "yes" if matched else "no",
    )
    return result


def build_snmp_community_rename_transform(
    rename_map: dict[str, str | None] | None = None,
) -> tuple[
    Callable[["CanonicalIntent"], "CanonicalIntent"],
    SnmpRenameResult,
]:
    """Return a pipeline-compatible transform + a result accumulator.

    Pattern mirrors :func:`build_port_rename_transform` /
    :func:`build_vlan_rename_transform` /
    :func:`build_local_user_rename_transform`.  The pipeline applies
    the transform to the parsed canonical tree; the returned
    :class:`SnmpRenameResult` is populated as a side-effect and
    attached to the :class:`MigrationJob` after the pipeline run.

    Args:
        rename_map: As accepted by :func:`translate_snmp_community`.

    Returns:
        Tuple of ``(transform_fn, result)``.  The transform returns
        the same ``intent`` it was given (mutation is in-place).
    """
    result = SnmpRenameResult()

    def _transform(intent: "CanonicalIntent") -> "CanonicalIntent":
        outcome = translate_snmp_community(
            intent, rename_map=rename_map,
        )
        result.applied.update(outcome.applied)
        result.dropped.extend(outcome.dropped)
        result.warnings.extend(outcome.warnings)
        return intent

    return _transform, result
