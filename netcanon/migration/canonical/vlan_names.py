"""
Canonical VLAN-ID rewrite orchestrator.

Cross-vendor VLAN mapping for the Tier-3 migration override modal.
Parallel to :mod:`netcanon.migration.canonical.port_names`, but the
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
    CanonicalInterface.dot1q_vlan (routed L3 sub-interface tag)
    CanonicalVxlan.vlan_id (VLAN-to-VNI mapping)

Drop semantics (map value is None):

    * The :class:`CanonicalVlan` itself is removed from
      ``intent.vlans``.
    * Every interface whose ``access_vlan`` matches is detached
      (``access_vlan = None``) — operator gets a warning and the
      interface becomes unassigned.
    * Dropped IDs are removed from ``trunk_allowed_vlans`` lists.
      A trunk left with an empty list allows NO VLAN, and the
      operator gets a warning that says so.  A list of every id
      (1-4094) is the statement "every VLAN" and is left as it is by
      a drop and by a rename alike.
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
    * A map can bring a port's native VLAN INTO its allowed list.
      The port stated native VLAN 10 outside a list of 20 and 30 --
      stated and not carried -- and the map sends 10 to 20.  Left
      alone the port would carry VLAN 20 UNTAGGED, which it carried
      tagged.  What is done turns on the ids of the list that the map
      puts on the native VLAN's id.  Where the list names one of
      them as a VLAN -- it has a record in ``intent.vlans`` before
      the map, or the list is a short one, whose every id is a
      VLAN -- two VLANs have been made one, and the native VLAN is
      cleared.  Where it names none so -- ``native vlan 1000`` beside
      ``allowed vlan 2-999,1001-4094``, and 1000 renumbered to 900,
      a number the range covers and no VLAN had -- nothing was
      merged: the new id is taken out of the list, and the port
      still states its native VLAN and still does not carry it.
      Each has a warning of its own.  A native VLAN the list held
      already is renumbered with it as before.

SVI interfaces named with the canonical ``Vlan<N>`` spelling (Cisco /
Arista / NX-OS — the exact form render-side
``synthesize_svis_from_vlan_l3`` keys off) DO track the VLAN rename
(#18): renaming VLAN 10→20 also renames ``interface Vlan10`` → ``Vlan20``
(merging into an existing ``Vlan20`` SVI rather than rendering two
same-named stanzas), and dropping VLAN 10 removes the ``Vlan10`` SVI.
Without this, the renamed VLAN's L3 rendered a fresh ``interface Vlan20``
while the stale ``Vlan10`` still rendered — two overlapping-subnet SVIs
the device rejects.  Vendor-specific SVI spellings that are NOT
``Vlan<N>`` (OPNsense ``vlan0.10``, Junos ``irb.10``) are left to the
port-rename orchestrator's domain.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from .transforms import (
    TRUNK_ALLOWED_SPECIFICITY_BOUND,
    is_every_vlan,
    trunk_untagged_vlan,
)

logger = logging.getLogger(__name__)

# Canonical SVI interface spelling (Cisco / Arista / NX-OS) — the exact form
# render-side ``synthesize_svis_from_vlan_l3`` synthesises and keys off.  Used
# by Pass 2b (#18) to keep an SVI interface's name tracking its VLAN rename.
_SVI_NAME_RE = re.compile(r"^Vlan(\d+)$")

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


def translate_vlan_ids(  # noqa: C901
    intent: CanonicalIntent,
    rename_map: dict[int, int | None] | None = None,
) -> VlanRenameResult:
    """Apply *rename_map* to *intent* in-place and return a summary.

    For each entry ``{src: tgt}``:
      * ``tgt`` is an int → rename the VLAN + update every
        referring field (access_vlan, trunk lists, native, voice,
        routed-sub-interface dot1q tag, and VXLAN VNI vlan_id).
      * ``tgt`` is None → drop the VLAN entirely (interfaces detached,
        matching VXLAN VNI mappings removed).

    Collisions (two source VLANs → same target ID, or target ID
    already exists in the tree) merge tagged/untagged port lists
    and SVI addresses by union, de-duplicating while preserving
    order of first occurrence.

    A port's native VLAN that its allowed list did NOT hold before
    the map and WOULD hold after it is not left to become a VLAN the
    port carries untagged.  The list is what a trunk carries
    (:func:`.transforms.trunk_untagged_vlan`), so that native VLAN
    was stated and not carried, and it is asked which ids of the list
    as it stood the map puts on the native VLAN's id:

    * The list names one of them as a VLAN.  The port carried that
      VLAN tagged, and the map has made the two VLANs one: left
      alone, every target that writes a native line would carry
      untagged a VLAN the source carried tagged, while a target
      written from the VLANs' member lists kept it tagged.  The
      native VLAN is CLEARED, with a warning that names the
      interface, both ids and that VLAN.  The port then states no
      native VLAN, and both halves of the tree say tagged.
    * It names none of them so.  It covered that number only as part of a
      range, no VLAN had it, and nothing was merged: ``native vlan
      1000`` beside ``allowed vlan 2-999,1001-4094`` with 1000
      renumbered to 900, or ``allowed vlan except 10`` with 10
      renumbered to 4000.  The new id is TAKEN OUT of the list and
      the native VLAN is kept, with a warning of its own: the port
      did not carry that VLAN before the map and does not carry it
      after.

    A list names an id as a VLAN where the id is a VLAN of the
    config -- it has a record in ``intent.vlans`` before the map --
    or where the list as it stood is no longer than
    ``TRUNK_ALLOWED_SPECIFICITY_BOUND``.  The second is the parsers'
    own reading of a list
    (:func:`.transforms.switchport_declared_vlan_ids`): every id of
    a list that short is a VLAN, declared or not, and a longer list
    or a range covers numbers.  A parser makes a record for every
    VLAN the config declares, for an access port's access VLAN, and
    for a trunk's native VLAN and the ids of its short list; in
    such a tree an id of a trunk's list has a record exactly where
    the trunk is that VLAN's tagged member, so after either branch
    the trunk's own fields and the VLANs' member lists say one
    thing.

    This is asked of every port that has the two fields, whatever
    its mode: a port's trunk lines say what it carries when it is a
    trunk, and a port in a dynamic mode or with no mode line can
    become one.  Such a port is no VLAN's tagged member, and no
    record is made from its trunk lines; its short list is read as
    a trunk's is all the same.  Asked for a record alone,
    ``native vlan 10`` beside ``allowed vlan 500`` with 10 given the
    id 500 would be a merge under ``switchport mode trunk`` and,
    in a dynamic mode, a list emptied of its only id -- for which
    such a port has no line, so that it would be written its native
    line alone.  A list longer than the bound is not emptied by one
    id taken out.  A native VLAN the list held before is renumbered
    with the list, and a list of every VLAN holds every native VLAN
    before and after.

    Input validation:
      * Source or target IDs outside 1-4094 → warning; entry
        skipped (invalid IDs can't survive AOS-S validation
        downstream anyway).
      * Mapping a VLAN ID that is present nowhere in the tree — neither
        as a ``vlan`` stanza nor as an interface reference (access /
        native / voice / trunk-allowed) → warning + no-op.  The UI should
        avoid sending these but the orchestrator doesn't crash on them.
        (An ID present only as an interface reference is still rewritten
        by Pass 2, so it is NOT flagged as a no-op.  A trunk-allowed
        list of every id, 1-4094, is no reference to any one VLAN: it
        says "every VLAN" and Pass 2 leaves it alone.)

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

    # Entry log fires on EVERY call — including no-op paths — so
    # "did the orchestrator run at all?" is answerable from logs
    # even when the operator's map is empty or the tree is a mock.
    # Outcome (applied/dropped/warnings counts) is logged by
    # run_plan_with_overrides's post-run summary; this line
    # answers the orthogonal "was I even invoked?" question.
    logger.debug(
        "translate_vlan_ids: entry with rename_map=%s "
        "source_vlans=%d",
        "None" if rename_map is None
        else f"{len(rename_map)}-entry dict",
        len(getattr(intent, "vlans", []) or []),
    )

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

    # (#49a) Warn on map entries whose source VLAN is present nowhere — not as
    # a stanza (source_ids) and not as an interface reference (rewritten by
    # Pass 2 below).  The docstring promises this; without it a typo'd entry
    # silently no-ops.  Computed from ORIGINAL interface fields (Pass 2 hasn't
    # run yet).
    referenced_ids: set[int] = set(source_ids)
    for iface in intent.interfaces:
        for vid in (
            iface.access_vlan,
            iface.trunk_native_vlan,
            iface.voice_vlan,
            iface.dot1q_vlan,
        ):
            if vid is not None:
                referenced_ids.add(vid)
        # A list of every id is the statement "every VLAN" and names
        # no VLAN in particular (Pass 2 leaves it as it is for the
        # same reason).  Counted id by id, one trunk that states no
        # allowed list -- every VLAN, on four platforms -- made every
        # id there is "referenced", and a map entry for a VLAN the
        # config does not have was no longer reported.
        if iface.trunk_allowed_vlans and not is_every_vlan(
            iface.trunk_allowed_vlans
        ):
            referenced_ids.update(iface.trunk_allowed_vlans)
    # (#5) VXLAN VNI records carry a vlan_id that this orchestrator now
    # rewrites (Pass 3) — count it as a reference so a rename touching ONLY a
    # vni mapping isn't wrongly flagged "present nowhere".
    for vx in intent.vxlan_vnis:
        referenced_ids.add(vx.vlan_id)
    for missing in sorted((set(renames) | drops) - referenced_ids):
        result.warnings.append(
            f"vlan_rename: VLAN {missing} is present nowhere in the parsed "
            f"config (no stanza or interface reference); entry ignored"
        )

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
        #
        # Whether the trunk carried it is asked first, of the fields
        # as the source stated them: the native VLAN is rewritten
        # here and the list further down, and the answer is wanted
        # again when both are done.
        native_before = iface.trunk_native_vlan
        carried_before = trunk_untagged_vlan(
            iface.trunk_allowed_vlans, native_before,
        )
        if iface.trunk_native_vlan is not None:
            if iface.trunk_native_vlan in drops:
                # A list of every id is left as it stands (below),
                # so the port still allows the id that was dropped.
                # "Cleared" alone reads as "no longer carried".  The
                # pass does not know the target, so the words say
                # what holds for any output that writes the port as
                # a trunk of every VLAN, and no more.
                still_held = (
                    f"; the port allows every VLAN, and an output that "
                    f"writes it as a trunk of every VLAN still allows "
                    f"VLAN {iface.trunk_native_vlan}"
                    if is_every_vlan(iface.trunk_allowed_vlans) else ""
                )
                result.warnings.append(
                    f"vlan_rename: interface {iface.name!r} had native VLAN "
                    f"{iface.trunk_native_vlan} which was dropped — "
                    f"native VLAN cleared{still_held}"
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

        # (#5) 802.1Q tag on a routed (L3) sub-interface.  A stale tag
        # renders ``encapsulation dot1Q <old>`` on the renumbered VLAN —
        # L3 dead on deploy.  Rewrite like access_vlan.  The inner tag
        # of a Q-in-Q sub-interface is a customer's tag inside this
        # VLAN, not a VLAN of the device: a map does not move it, and
        # it goes with the outer tag it is inside of.
        if iface.dot1q_vlan is not None:
            if iface.dot1q_vlan in drops:
                inner = (
                    f" and its inner tag {iface.dot1q_inner_vlan}"
                    if iface.dot1q_inner_vlan is not None else ""
                )
                result.warnings.append(
                    f"vlan_rename: interface {iface.name!r} had 802.1Q "
                    f"sub-interface VLAN {iface.dot1q_vlan} which was dropped "
                    f"— tag{inner} cleared"
                )
                iface.dot1q_vlan = None
                iface.dot1q_inner_vlan = None
            elif iface.dot1q_vlan in renames:
                iface.dot1q_vlan = renames[iface.dot1q_vlan]

        # Trunk allowed list — remove drops, rename renames, dedupe.
        #
        # A list of every id is the statement "every VLAN", not 4,094
        # VLANs: it is the same statement after one of them is
        # renumbered or dropped, and it is left as it stands.
        # Rewritten id by id it loses the id that moved or went: a
        # trunk that said ``all`` came out as ``1-99,101-4094``, and
        # so would every trunk of a config that states no list --
        # every VLAN, on four platforms -- for one edit in the VLAN
        # pane.
        if iface.trunk_allowed_vlans and not is_every_vlan(
            iface.trunk_allowed_vlans
        ):
            new_list: list[int] = []
            seen: set[int] = set()
            gone: list[int] = []
            allowed_before = iface.trunk_allowed_vlans
            for vid in iface.trunk_allowed_vlans:
                if vid in drops:
                    gone.append(vid)
                    continue
                new_vid = renames.get(vid, vid)
                if new_vid not in seen:
                    seen.add(new_vid)
                    new_list.append(new_vid)
            iface.trunk_allowed_vlans = new_list
            if not new_list and iface.switchport_mode == "trunk":
                # Every VLAN the trunk allowed was dropped.  An empty
                # list is a trunk that allows NO VLAN, and that is
                # what every target is now told -- so the operator is
                # told as well.
                result.warnings.append(_emptied_trunk_warning(iface.name, gone))
            # A native VLAN the port stated and did not carry, which
            # the map has brought into the port's list.  The list is
            # what a trunk carries, so the port would now carry that
            # VLAN untagged.  (Only a list that was rewritten can
            # come to hold it: a list of every VLAN held the native
            # VLAN before.  Whatever the port's mode: its trunk lines
            # say what it carries when it is a trunk.)
            native_after = iface.trunk_native_vlan
            if (
                native_before is not None
                and carried_before is None
                and trunk_untagged_vlan(new_list, native_after) is not None
            ):
                # The ids of the list as it stood that the map puts
                # on the native VLAN's id: there is one, or the new
                # list would not hold it.
                landed = [
                    vid for vid in allowed_before
                    if vid not in drops
                    and renames.get(vid, vid) == native_after
                ]
                merged = next(
                    (vid for vid in landed if vid in source_ids), None,
                )
                if merged is None and (
                    len(allowed_before) <= TRUNK_ALLOWED_SPECIFICITY_BOUND
                ):
                    # A list this short names VLANs, with or without
                    # a record: it is how a parser reads a trunk's,
                    # and a port in another mode gets no record from
                    # its trunk lines.
                    merged = landed[0]
                if merged is not None:
                    # A VLAN the list names, which the port carried
                    # tagged: the map has made the two one.  Cleared,
                    # the port states no native VLAN and the merged
                    # VLAN stays tagged.
                    result.warnings.append(_merged_native_warning(
                        iface.name, native_before, native_after, merged,
                    ))
                    iface.trunk_native_vlan = None
                else:
                    # A number a longer list covered and no VLAN had:
                    # nothing was merged.  The native VLAN's id comes
                    # out of the NEW list, so the port states it and
                    # does not carry it, as before the map.
                    iface.trunk_allowed_vlans = [
                        vid for vid in new_list if vid != native_after
                    ]
                    result.warnings.append(_number_only_warning(
                        iface.name, native_before, native_after, landed[0],
                    ))

    # ------------------------------------------------------------------
    # Pass 2b — track the rename/drop on canonical ``Vlan<N>`` SVIs (#18).
    # ------------------------------------------------------------------
    # A Cisco/Arista/NX-OS SVI is a CanonicalInterface named ``Vlan<N>``.  The
    # passes above renamed the CanonicalVlan record + its folded L3 but left
    # the SVI interface NAME untouched, so render-side synthesis emitted a new
    # ``interface Vlan<M>`` (from the renamed VLAN's L3) while the stale
    # ``Vlan<N>`` also rendered — two overlapping-subnet SVIs the device
    # rejects, with no warning.  Rename the SVI alongside its VLAN (merging
    # into a pre-existing ``Vlan<M>`` SVI) / drop it when the VLAN is dropped.
    if renames or drops:
        svi_kept: list = []
        iface_by_name: dict[str, object] = {
            i.name: i for i in intent.interfaces
        }
        for iface in intent.interfaces:
            m = _SVI_NAME_RE.match(iface.name)
            if m is None:
                svi_kept.append(iface)
                continue
            svi_vid = int(m.group(1))
            if svi_vid in drops:
                result.warnings.append(
                    f"vlan_rename: SVI interface {iface.name!r} removed "
                    f"because VLAN {svi_vid} was dropped"
                )
                continue  # SVI disappears with its VLAN
            if svi_vid in renames:
                new_name = f"Vlan{renames[svi_vid]}"
                existing = iface_by_name.get(new_name)
                if existing is not None and existing is not iface:
                    # A Vlan<M> SVI already exists — merge this SVI's L3
                    # into it rather than render two same-named stanzas.
                    _merge_svi_addresses(existing, iface)
                    result.warnings.append(
                        f"vlan_rename: SVI {iface.name!r} merged into existing "
                        f"{new_name!r} (VLAN {svi_vid}->{renames[svi_vid]} "
                        f"rename)"
                    )
                    continue
                result.warnings.append(
                    f"vlan_rename: SVI interface renamed {iface.name!r}->"
                    f"{new_name!r} to track the VLAN "
                    f"{svi_vid}->{renames[svi_vid]} rename"
                )
                iface.name = new_name
                iface_by_name[new_name] = iface
            svi_kept.append(iface)
        intent.interfaces = svi_kept

    # ------------------------------------------------------------------
    # Pass 3 — VXLAN VNI records carry a vlan_id that must track the rename.
    # ------------------------------------------------------------------
    # intent.py documents that CanonicalVxlan.vlan_id stays in sync with
    # CanonicalVlan.id.  cisco_nxos render unions vni vlan_ids into the
    # emitted VLAN list, so a stale vlan_id resurrects the OLD VLAN with the
    # vn-segment bound to it — a rename/drop that skips this leaves a broken
    # overlay.  Rename in place; drop the whole VNI record with a warning.
    if intent.vxlan_vnis:
        kept_vnis: list = []
        for vx in intent.vxlan_vnis:
            if vx.vlan_id in drops:
                result.warnings.append(
                    f"vlan_rename: VXLAN VNI {vx.vni} mapped to VLAN "
                    f"{vx.vlan_id} which was dropped — VNI mapping removed"
                )
                continue
            if vx.vlan_id in renames:
                vx.vlan_id = renames[vx.vlan_id]
            kept_vnis.append(vx)
        intent.vxlan_vnis = kept_vnis

    # (#4) A rename/drop invalidates verbatim vendor-provenance group bodies
    # (Junos apply-groups): re-emitting them resurrects the PRE-renumber VLAN
    # definitions alongside the renumbered ones.  The flattened canonical tree
    # already carries the semantics, so clear the bodies + apply-group refs
    # once IDs have moved — mirrors the port-rename orchestrator + sanitizer.
    if (result.applied or result.dropped) and (
        intent.group_content or intent.apply_groups
    ):
        intent.group_content = {}
        intent.apply_groups = []
        result.warnings.append(
            "vlan_rename: cleared verbatim apply-group bodies because a "
            "rename/drop was applied — group content was flattened into the "
            "canonical tree to avoid resurrecting pre-rename VLAN ids"
        )

    logger.debug(
        "translate_vlan_ids: exit applied=%d dropped=%d warnings=%d",
        len(result.applied),
        len(result.dropped),
        len(result.warnings),
    )
    return result


def _emptied_trunk_warning(name: str, gone: list[int]) -> str:
    """The warning for a trunk whose every allowed VLAN was dropped.

    Names the first few ids and counts the rest: a trunk can list
    thousands.
    """
    shown = ", ".join(str(vid) for vid in gone[:8])
    if len(gone) == 1:
        what = f"VLAN {shown} which was dropped"
    elif len(gone) <= 8:
        what = f"VLANs {shown} which were dropped"
    else:
        what = f"VLANs {shown} and {len(gone) - 8} more which were dropped"
    return (
        f"vlan_rename: interface {name!r} is a trunk that allowed only "
        f"{what} — the trunk now allows no VLAN"
    )


def _merged_native_warning(
    name: str, before: int, after: int, tagged: int,
) -> str:
    """The warning for a port whose native VLAN was outside its
    allowed list and is merged by the map with a VLAN of the list.

    *before* and *after* are the native VLAN's id on either side of
    the map, and *tagged* is a VLAN that the list names (a VLAN of
    the config, or an id of a short list), by its id before the
    map, which the map puts on the same
    id.  *before* and *after* are one id where the map moved that
    VLAN onto the native VLAN and not the other way.
    """
    if before == after:
        how = (
            f"the map merges VLAN {tagged}, which the trunk carries "
            f"tagged, into it"
        )
    else:
        how = (
            f"the map merges it into VLAN {after}, which the trunk "
            f"carries tagged"
        )
    return (
        f"vlan_rename: interface {name!r} had native VLAN {before} "
        f"outside its allowed list, and {how} — native VLAN cleared"
    )


def _number_only_warning(
    name: str, before: int, after: int, number: int,
) -> str:
    """The warning for a port whose native VLAN was outside its
    allowed list and is given, by the map, an id the list named only
    as a number: no VLAN of the config had it.

    *before* and *after* are the native VLAN's id on either side of
    the map, and *number* is the id of the list, before the map, that
    the map puts on *after*.  It is *after* itself where the list
    named the new id, and another id where the map moved a number of
    the list onto the native VLAN's.

    Nothing was merged and no VLAN was carried tagged under that
    number: the warning says neither.
    """
    nothing_had = (
        "which the list named only as a number no VLAN of the "
        "config had"
    )
    if number == after:
        how = f"the map gives it the id {after}, {nothing_had}"
    elif before == after:
        how = f"the map gives its id to {number}, {nothing_had}"
    else:
        how = (
            f"the map gives it the id {after} and gives the same id "
            f"to {number}, {nothing_had}"
        )
    return (
        f"vlan_rename: interface {name!r} had native VLAN {before} "
        f"outside its allowed list, and {how} — {after} is taken out "
        f"of the list, and the trunk does not carry native VLAN {after}"
    )


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


def _merge_svi_addresses(dest, src) -> None:
    """Merge SVI *src* interface's L3 addresses into *dest* in-place (#18).

    Used when a VLAN rename lands a ``Vlan<N>`` SVI onto an already-present
    ``Vlan<M>`` interface — union the v4/v6 address lists (dedupe on
    ``(ip, prefix_length)``) so the target renders one SVI, not two.
    """
    seen4 = {(a.ip, a.prefix_length) for a in dest.ipv4_addresses}
    for a in src.ipv4_addresses:
        if (a.ip, a.prefix_length) not in seen4:
            seen4.add((a.ip, a.prefix_length))
            dest.ipv4_addresses.append(a)
    seen6 = {(a.ip, a.prefix_length) for a in dest.ipv6_addresses}
    for a in src.ipv6_addresses:
        if (a.ip, a.prefix_length) not in seen6:
            seen6.add((a.ip, a.prefix_length))
            dest.ipv6_addresses.append(a)


def build_vlan_rename_transform(
    rename_map: dict[int, int | None] | None = None,
) -> tuple[Callable[[CanonicalIntent], CanonicalIntent], VlanRenameResult]:
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

    def _transform(intent: CanonicalIntent) -> CanonicalIntent:
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
