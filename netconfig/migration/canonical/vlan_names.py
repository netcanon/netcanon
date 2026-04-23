"""
Canonical VLAN-ID rewrite orchestrator.

Cross-vendor VLAN mapping for the Tier-3 migration override modal.
Parallel to :mod:`netconfig.migration.canonical.port_names`, but the
underlying domain is simpler: VLAN IDs are integers 1-4094 with
universal semantics across every switching vendor — there is no
vendor-specific encoding to bridge.  A mapping is just
``dict[int, int | None]``:

    {10: 20, 100: None}

means "rename VLAN 10 → 20; drop VLAN 100 entirely".

Compared with port_names.py the orchestrator is lighter-weight — no
``classify_port_name`` / ``format_port_identity`` bridge is needed
because integers don't require translation between vendors — but
the canonical-tree walker still has to touch every VLAN-referring
field:

    CanonicalVlan.id
    CanonicalInterface.access_vlan
    CanonicalInterface.trunk_allowed_vlans (list)
    CanonicalInterface.trunk_native_vlan
    CanonicalInterface.voice_vlan

Drop semantics (map value is None):

    * The :class:`CanonicalVlan` itself is removed from
      ``intent.vlans``.
    * Every interface whose ``access_vlan`` matches is detached
      (``access_vlan = None``) — operator gets a warning and the
      interface becomes unassigned.
    * Dropped IDs are removed from ``trunk_allowed_vlans`` lists.
    * ``trunk_native_vlan`` / ``voice_vlan`` pointing at a dropped
      VLAN are cleared; target device will fall back to vendor
      default (typically VLAN 1).

Collision detection:

    * Two source VLANs mapped to the same target ID → reported as a
      warning; the later-processed VLAN wins in the output, earlier
      entries' data is merged (tagged/untagged ports unioned,
      SVI addresses concatenated).  Same-ID merge is load-bearing
      because it's the only sane thing to do when an operator
      squashes 10 and 20 both onto target ID 30.
    * Mapping a VLAN to an ID that already EXISTS in the tree (a
      non-collision rename conflict) → same merge semantics: the
      renamed VLAN's membership is unioned into the existing one.

The orchestrator does NOT rename SVI interfaces (``Vlan10`` →
``Vlan20``).  Those live in the port-rename pipeline's domain —
their naming convention is vendor-specific (``Vlan10`` on Cisco,
``vlan0.10`` on OPNsense, etc.), so it's the port-rename
orchestrator's job to rewrite them.  If the operator wants SVI
renames to follow their VLAN renames, the UI composes the two maps
on the client side before posting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .intent import CanonicalIntent


class VlanRenameResult(BaseModel):
    """Outcome of :func:`translate_vlan_ids`.

    Mirrors :class:`PortRenameResult` — exposed so the UI can show
    exactly which VLANs changed, which were dropped, and which
    overrides produced warnings.
    """

    applied: dict[int, int] = Field(default_factory=dict)
    """Map of source_vlan_id → target_vlan_id for every rewrite that
    happened.  VLANs whose ID didn't change are NOT in this map."""

    dropped: list[int] = Field(default_factory=list)
    """VLAN IDs the operator explicitly marked "don't render" via a
    ``None`` value in the rename map.  Every reference to these IDs
    was stripped from the canonical tree before render."""

    warnings: list[str] = Field(default_factory=list)
    """Per-VLAN advisories — collision hits, interface-detachment
    side effects of drops, out-of-range rejections."""


def translate_vlan_ids(
    intent: "CanonicalIntent",
    rename_map: dict[int, int | None] | None = None,
) -> VlanRenameResult:
    """Apply *rename_map* to *intent* in-place and return a summary.

    For each entry ``{src: tgt}``:
      * ``tgt`` is an int → rename the VLAN + update every
        referring field (access_vlan, trunk lists, native, voice).
      * ``tgt`` is None → drop the VLAN entirely.

    Collisions (two source VLANs → same target ID, or target ID
    already exists in the tree) merge tagged/untagged port lists
    and SVI addresses by union, de-duplicating while preserving
    order of first occurrence.

    Input validation:
      * Source or target IDs outside 1-4094 → warning; entry
        skipped (invalid IDs can't survive AOS-S validation
        downstream anyway).
      * Mapping a VLAN ID that doesn't exist in ``intent.vlans`` →
        warning + no-op.  The UI should avoid sending these but the
        orchestrator doesn't crash on them.

    Args:
        intent: Canonical tree to mutate.  Passed through the
            pipeline as a transform, so side-effect on ``intent``
            is expected.
        rename_map: ``{source_id: target_id | None}``.  None or
            empty dict → no-op (returns an empty result).

    Returns:
        :class:`VlanRenameResult` summarising the changes.
    """
    from .intent import CanonicalIntent  # for isinstance guard

    result = VlanRenameResult()

    # Defensive no-op when called against a non-canonical tree
    # (mock adapters produce plain dicts for testing) — mirrors the
    # guard in translate_port_names so run_plan_with_overrides is
    # safe to wire into the mock adapter's smoke path.
    if not isinstance(intent, CanonicalIntent):
        return result

    if not rename_map:
        return result

    # Normalise + validate the map.  Invalid entries produce warnings
    # and are discarded before any tree mutation — better to run the
    # operator's VALID intent than crash on a stray bad entry.
    valid_map: dict[int, int | None] = {}
    for src, tgt in rename_map.items():
        try:
            src_int = int(src)
        except (TypeError, ValueError):
            result.warnings.append(
                f"vlan_rename: source id {src!r} is not a valid VLAN id"
            )
            continue
        if not (1 <= src_int <= 4094):
            result.warnings.append(
                f"vlan_rename: source id {src_int} out of range 1-4094"
            )
            continue
        if tgt is None:
            valid_map[src_int] = None
            continue
        try:
            tgt_int = int(tgt)
        except (TypeError, ValueError):
            result.warnings.append(
                f"vlan_rename: target id {tgt!r} for source {src_int} "
                f"is not a valid VLAN id"
            )
            continue
        if not (1 <= tgt_int <= 4094):
            result.warnings.append(
                f"vlan_rename: target id {tgt_int} for source "
                f"{src_int} out of range 1-4094"
            )
            continue
        valid_map[src_int] = tgt_int

    if not valid_map:
        return result

    # Split renames from drops for clearer downstream logic.
    renames: dict[int, int] = {
        s: t for s, t in valid_map.items() if t is not None
    }
    drops: set[int] = {s for s, t in valid_map.items() if t is None}

    # ------------------------------------------------------------------
    # Pass 1 — rewrite / drop within intent.vlans themselves.
    # ------------------------------------------------------------------
    # Collect which IDs exist in the source tree so "rename to
    # already-existing ID" is detectable.
    source_ids = {v.id for v in intent.vlans}

    # Build the post-rewrite vlans list.  We defer actually assigning
    # back onto intent.vlans until we've resolved all collisions,
    # because a single source VLAN might need to be merged INTO
    # another whose rewrite targets the same ID.
    kept: list = []
    by_target_id: dict[int, object] = {}  # target_id -> CanonicalVlan

    for v in intent.vlans:
        if v.id in drops:
            result.dropped.append(v.id)
            # Don't append — VLAN disappears.
            continue
        new_id = renames.get(v.id, v.id)
        if new_id != v.id:
            result.applied[v.id] = new_id
            # Collision check against existing IDs in the tree that
            # weren't themselves renamed out of the way.
            if new_id in source_ids and new_id not in renames:
                result.warnings.append(
                    f"vlan_rename: target id {new_id} already exists in "
                    f"source config — merging source VLAN {v.id} into {new_id}"
                )
        v.id = new_id
        if new_id in by_target_id:
            # Collision: merge this VLAN's data into the existing entry.
            existing = by_target_id[new_id]
            _merge_vlan(existing, v)
            result.warnings.append(
                f"vlan_rename: multiple source VLANs mapped to {new_id} — "
                f"tagged/untagged port lists merged"
            )
        else:
            kept.append(v)
            by_target_id[new_id] = v
    intent.vlans = kept

    # ------------------------------------------------------------------
    # Pass 2 — update every VLAN-referring field on interfaces.
    # ------------------------------------------------------------------
    for iface in intent.interfaces:
        # Access VLAN
        if iface.access_vlan is not None:
            if iface.access_vlan in drops:
                result.warnings.append(
                    f"vlan_rename: interface {iface.name!r} was access VLAN "
                    f"{iface.access_vlan} which was dropped — interface "
                    f"detached from VLAN"
                )
                iface.access_vlan = None
            elif iface.access_vlan in renames:
                iface.access_vlan = renames[iface.access_vlan]

        # Native VLAN
        if iface.trunk_native_vlan is not None:
            if iface.trunk_native_vlan in drops:
                result.warnings.append(
                    f"vlan_rename: interface {iface.name!r} had native VLAN "
                    f"{iface.trunk_native_vlan} which was dropped — "
                    f"native VLAN cleared"
                )
                iface.trunk_native_vlan = None
            elif iface.trunk_native_vlan in renames:
                iface.trunk_native_vlan = renames[iface.trunk_native_vlan]

        # Voice VLAN
        if iface.voice_vlan is not None:
            if iface.voice_vlan in drops:
                result.warnings.append(
                    f"vlan_rename: interface {iface.name!r} had voice VLAN "
                    f"{iface.voice_vlan} which was dropped — voice VLAN cleared"
                )
                iface.voice_vlan = None
            elif iface.voice_vlan in renames:
                iface.voice_vlan = renames[iface.voice_vlan]

        # Trunk allowed list — remove drops, rename renames, dedupe.
        if iface.trunk_allowed_vlans:
            new_list: list[int] = []
            seen: set[int] = set()
            for vid in iface.trunk_allowed_vlans:
                if vid in drops:
                    continue
                new_vid = renames.get(vid, vid)
                if new_vid not in seen:
                    seen.add(new_vid)
                    new_list.append(new_vid)
            iface.trunk_allowed_vlans = new_list

    return result


def _merge_vlan(dest, src) -> None:
    """Merge *src* into *dest* in-place (union port lists, concat
    SVI addresses, preserve dest's name/description if set)."""
    existing_tagged = set(dest.tagged_ports)
    for p in src.tagged_ports:
        if p not in existing_tagged:
            existing_tagged.add(p)
            dest.tagged_ports.append(p)

    existing_untagged = set(dest.untagged_ports)
    for p in src.untagged_ports:
        if p not in existing_untagged:
            existing_untagged.add(p)
            dest.untagged_ports.append(p)

    # SVI addresses — concat without dedup (canonical form doesn't
    # require unique IPs at this level; downstream validate/render
    # may flag duplicates if present).
    dest.ipv4_addresses.extend(src.ipv4_addresses)

    # Preserve dest's name if it has one; otherwise take src's.
    if not dest.name and src.name:
        dest.name = src.name
    if not dest.description and src.description:
        dest.description = src.description


def build_vlan_rename_transform(
    rename_map: dict[int, int | None] | None = None,
) -> tuple[Callable[["CanonicalIntent"], "CanonicalIntent"], VlanRenameResult]:
    """Return a pipeline-compatible transform + a result accumulator.

    Pattern mirrors :func:`build_port_rename_transform`.  The pipeline
    applies the transform to the parsed canonical tree; the returned
    ``VlanRenameResult`` is populated as a side-effect and can be
    attached to the :class:`MigrationJob` after the pipeline run.

    Args:
        rename_map: As accepted by :func:`translate_vlan_ids`.

    Returns:
        Tuple of ``(transform_fn, result)``.  The transform returns
        the same ``intent`` it was given (mutation is in-place); the
        result fills with per-VLAN outcomes as the transform runs.
    """
    result = VlanRenameResult()

    def _transform(intent: "CanonicalIntent") -> "CanonicalIntent":
        outcome = translate_vlan_ids(intent, rename_map=rename_map)
        # Copy outcome fields into the shared result so the caller can
        # inspect them after the pipeline completes.  Transforms are
        # supposed to return the (possibly mutated) tree; the result
        # is side-channel state.
        result.applied.update(outcome.applied)
        result.dropped.extend(outcome.dropped)
        result.warnings.extend(outcome.warnings)
        return intent

    return _transform, result
