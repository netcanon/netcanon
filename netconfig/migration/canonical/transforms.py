"""
Shared post-parse transforms on :class:`CanonicalIntent`.

Individual codecs populate the canonical tree from vendor-native config
in whichever shape is natural for that vendor.  Some vendors (Cisco
IOS-XE) describe VLAN membership per-port via ``switchport`` lines on
the interface stanza.  Others (Aruba AOS-S, OPNsense, MikroTik) describe
it VLAN-centrically via a membership list on the VLAN record.  The
canonical model carries **both** representations so that renderers can
emit whichever shape their target expects, but the parser only fills in
one side natively.

This module provides the bridging transforms.  Codecs call them at the
end of ``parse()`` to mirror the native representation across so the
other side is populated too.

Naming convention: a transform named ``project_X_to_Y`` reads from ``X``
and writes into ``Y``.  All transforms are:

* idempotent — safe to call twice
* in-place — they mutate the intent and return None
* additive — they never delete data already present

The mirror functions are deliberately kept simple and free of codec-
specific heuristics.  Anything more subtle belongs in the codec itself.
"""

from __future__ import annotations

import re

from .intent import CanonicalIntent, CanonicalVlan


# Splits a port name into a tuple of (str, int, str, int, ...) for
# natural sort.  Used by :func:`project_vlan_to_switchport` so
# synthesis order is deterministic + operator-natural across vendors.
#
#   "1/1"     -> ("", 1, "/", 1)
#   "1/2"     -> ("", 1, "/", 2)
#   "1/10"    -> ("", 1, "/", 10)            <- comes after "1/2", not before
#   "1/47"    -> ("", 1, "/", 47)
#   "1/A1"    -> ("", 1, "/A", 1)            <- "/A" sorts after "/"
#   "1/A4"    -> ("", 1, "/A", 4)
#   "ether1"  -> ("ether", 1)
#   "ge-0/0/0"-> ("ge-", 0, "/", 0, "/", 0)
#
# The result is a tuple suitable for ``sorted(key=...)``.  Mixed tuples
# of (str, int, ...) compare element-wise, so all-string segments sort
# alphabetically and all-int segments sort numerically — the standard
# "natural sort" semantic.  Identical-length tuples compare consistently;
# different-length tuples prefer shorter on ties (which is the
# operator-natural behaviour: "1/1" before "1/A1" because "/" < "/A").
_NATURAL_SORT_RE = re.compile(r"(\d+)")


def _natural_port_sort_key(name: str) -> tuple:
    parts = _NATURAL_SORT_RE.split(name)
    out: list = []
    for i, p in enumerate(parts):
        if i % 2 == 0:
            out.append(p)              # non-digit chunk
        else:
            out.append(int(p))         # digit chunk → int for numeric ordering
    return tuple(out)


def project_switchport_to_vlan(intent: CanonicalIntent) -> None:
    """Port-centric -> VLAN-centric membership mirror.

    For every :class:`CanonicalInterface` with switchport state populated,
    add the interface's name to the matching :class:`CanonicalVlan`'s
    ``tagged_ports`` / ``untagged_ports`` list.  Synthesize bare VLAN
    records for any VIDs referenced by a switchport but not declared as
    a top-level VLAN stanza (otherwise the membership info is lost when
    a VLAN-centric target renders).

    Semantics:
        * ``switchport_mode == "access"`` + ``access_vlan == N``:
          append iface to ``vlans[N].untagged_ports``.
        * ``switchport_mode == "trunk"``:
            - for each vid in ``trunk_allowed_vlans``:
              append iface to ``vlans[vid].tagged_ports``.
            - if ``trunk_native_vlan`` is set:
              append iface to ``vlans[native].untagged_ports`` AND
              remove it from ``tagged_ports`` on that same VLAN.
              (Native VLAN traffic rides the trunk untagged; Cisco
              permits listing the native vlan in ``allowed`` but it
              never actually gets tagged.)

    Idempotent: an interface already present in a list is not added twice.

    This is Bug 3 from translator-plans.txt (KNOWN DATA-LOSS BUGS).
    """
    # Index existing VLANs for O(1) lookup and for synthesizing missing ones.
    by_id: dict[int, CanonicalVlan] = {v.id: v for v in intent.vlans}

    def _vlan(vid: int) -> CanonicalVlan:
        v = by_id.get(vid)
        if v is None:
            v = CanonicalVlan(id=vid)
            intent.vlans.append(v)
            by_id[vid] = v
        return v

    def _add_unique(lst: list[str], name: str) -> None:
        if name not in lst:
            lst.append(name)

    # "Trunk all" sentinel detection: when an interface's
    # ``trunk_allowed_vlans`` is the full 1-4094 (or 2-4094) range,
    # this is the operator-form of "all VLANs allowed" — equivalent
    # to Junos ``vlan members all`` / Arista ``switchport trunk
    # allowed vlan all``.  Projecting that into VLAN-centric
    # tagged_ports would synthesise 4094 phantom VLAN records, each
    # of which renders out and reparses with a generated name (e.g.
    # ``VLAN-N``), breaking round-trip stability and producing
    # nonsensical 4000-line VLAN dumps on cross-vendor renders.  Skip
    # projection on the trunk-all form; the renderer side detects
    # this same shape and emits the appropriate "all" sentinel.
    _TRUNK_ALL_RANGE_FULL = set(range(1, 4095))
    _TRUNK_ALL_RANGE_OPERATIONAL = set(range(2, 4095))

    for iface in intent.interfaces:
        mode = iface.switchport_mode
        if mode is None:
            continue
        if mode == "access":
            if iface.access_vlan is not None:
                _add_unique(_vlan(iface.access_vlan).untagged_ports, iface.name)
        elif mode == "trunk":
            allowed_set = set(iface.trunk_allowed_vlans)
            is_trunk_all = (
                allowed_set == _TRUNK_ALL_RANGE_FULL
                or allowed_set == _TRUNK_ALL_RANGE_OPERATIONAL
            )
            if is_trunk_all:
                # Trunk-all sentinel: do NOT synthesise 4094 phantom
                # VLANs (would render to nonsensical output) but DO
                # stamp the iface onto every operator-DECLARED VLAN's
                # tagged_ports.  VLAN-centric targets (Aruba AOS-S)
                # consume tagged_ports as their substrate; without
                # this stamp Junos's ``vlan members all`` shape lost
                # its trunk-mode classification on round-trip — the
                # source iface had ``trunk_allowed_vlans=[1..4094]``
                # but no vlan listed it as tagged, so the target
                # codec's ``project_vlan_to_switchport`` had nothing
                # to derive trunk-mode from.  Verified against the
                # Junos OS Routing Devices Configuration Guide
                # ("Configuring VLANs" §VLAN tagging — ``all``
                # keyword) and the Aruba 2930M Management &
                # Configuration Guide ("VLAN-port binding").
                # Bucket-A fix from
                # ``phase4_findings_juniper_junos.md``.
                for vlan in intent.vlans:
                    _add_unique(vlan.tagged_ports, iface.name)
            else:
                for vid in iface.trunk_allowed_vlans:
                    _add_unique(_vlan(vid).tagged_ports, iface.name)
            native = iface.trunk_native_vlan
            if native is not None:
                vlan = _vlan(native)
                _add_unique(vlan.untagged_ports, iface.name)
                # Native VLAN rides the trunk untagged; purge any duplicate
                # in tagged_ports that came from trunk_allowed_vlans.
                if iface.name in vlan.tagged_ports:
                    vlan.tagged_ports.remove(iface.name)
        # Any other mode ("dynamic", etc.) is left alone — we don't have
        # enough signal to decide membership.


def project_vlan_to_switchport(
    intent: CanonicalIntent,
    synthesise_missing: bool = True,
) -> None:
    """VLAN-centric -> port-centric membership mirror.

    The inverse of :func:`project_switchport_to_vlan`.  For every
    :class:`CanonicalVlan`, read its membership lists and populate the
    corresponding :class:`CanonicalInterface`'s switchport fields.

    Semantics:
        * iface in ``untagged_ports`` only:
          set ``switchport_mode="access"`` and ``access_vlan=vid``.
        * iface in ``tagged_ports`` (possibly plus untagged on another
          VLAN that becomes the native): set ``switchport_mode="trunk"``
          and append the vid to ``trunk_allowed_vlans``; if the iface
          also appears in ``untagged_ports`` on some VLAN, set that as
          ``trunk_native_vlan``.

    When *synthesise_missing* is True (the default), port names
    referenced in VLAN membership lists but absent from
    ``intent.interfaces`` get a fresh :class:`CanonicalInterface`
    appended.  Required for cross-vendor renders into a
    port-centric target codec (Cisco IOS-XE CLI, Arista EOS) when
    the source codec is VLAN-centric and emits no explicit
    interface stanzas in its source config (Aruba AOS-S, OPNsense
    `<vlans>`-only).  Without synthesis, those targets render
    zero interfaces despite the canonical tree carrying full
    port-VLAN bindings — the bug shape that surfaced when an
    Aruba 2930M stack rendered to IOS-XE with only VLAN
    declarations and no interfaces.

    Interfaces with pre-existing switchport state are left alone —
    this transform only fills in missing information.

    Idempotent and additive like :func:`project_switchport_to_vlan`.
    Calling it twice in a row produces the same tree as one call.
    """
    iface_by_name = {i.name: i for i in intent.interfaces}

    # Build per-interface aggregated view: which vids as tagged, which as untagged.
    tagged: dict[str, list[int]] = {}
    untagged: dict[str, list[int]] = {}
    for vlan in intent.vlans:
        for name in vlan.tagged_ports:
            tagged.setdefault(name, []).append(vlan.id)
        for name in vlan.untagged_ports:
            untagged.setdefault(name, []).append(vlan.id)

    # Iterate sorted by natural port-name order so synthesis is
    # deterministic and operator-natural ("1/1", "1/2", ..., "1/47",
    # "1/A1", "1/A2") rather than set-iteration random order.  The
    # downstream renderer's per-kind sort can re-order, but starting
    # from a stable base means same-input → same-output regardless
    # of run.  See _natural_port_sort_key for how the key splits
    # numeric chunks.
    names = sorted(set(tagged) | set(untagged), key=_natural_port_sort_key)
    for name in names:
        iface = iface_by_name.get(name)
        if iface is None:
            if not synthesise_missing:
                continue
            # Synthesise a minimal CanonicalInterface so the
            # port-centric renderer has something to emit.  Leave
            # description / mtu / ipv4 empty — only the switchport
            # state is derivable from VLAN membership.  The fresh
            # iface lands at the END of intent.interfaces; ordering
            # doesn't matter for any consumer.
            from .intent import CanonicalInterface
            iface = CanonicalInterface(name=name)
            intent.interfaces.append(iface)
            iface_by_name[name] = iface
        # Don't clobber switchport state the codec already set.
        if iface.switchport_mode is not None:
            continue
        t_vids = tagged.get(name, [])
        u_vids = untagged.get(name, [])
        if t_vids:
            # Trunk: tagged list -> trunk_allowed_vlans, first untagged vid
            # becomes the native.
            iface.switchport_mode = "trunk"
            for vid in t_vids:
                if vid not in iface.trunk_allowed_vlans:
                    iface.trunk_allowed_vlans.append(vid)
            if u_vids and iface.trunk_native_vlan is None:
                iface.trunk_native_vlan = u_vids[0]
        elif u_vids:
            # Pure access: single untagged VLAN.  If multiple untagged
            # vlans appear (unusual), first wins and the rest are ignored
            # at this layer — they remain in vlan.untagged_ports so a
            # VLAN-centric renderer can still emit them faithfully.
            iface.switchport_mode = "access"
            if iface.access_vlan is None:
                iface.access_vlan = u_vids[0]
