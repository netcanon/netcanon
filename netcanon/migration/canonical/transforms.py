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

Public surface:

* :func:`project_switchport_to_vlan` — read per-interface
  ``switchport_mode`` / ``access_vlan`` / ``trunk_allowed_vlans``
  fields and back-fill the corresponding VLAN-centric port-membership
  lists on each :class:`CanonicalVlan`.  Called by Cisco-style codecs
  whose native config is per-port.  Told which VLAN ids its caller
  keeps (``keep``), it makes nothing the caller would then drop.
* :func:`project_vlan_to_switchport` — the inverse: read VLAN-centric
  ``tagged_ports`` / ``untagged_ports`` lists and synthesise
  ``switchport_mode`` + ``access_vlan`` + ``trunk_allowed_vlans`` on each
  :class:`CanonicalInterface`.
  Called by VLAN-centric codecs (Aruba AOS-S, OPNsense, MikroTik)
  before handing the tree to a per-port-shape target renderer.
* :func:`project_svi_to_vlan` — synthesise a :class:`CanonicalVlan`
  record for every ``Vlan<N>`` SVI interface that lacks one,
  bridging the gap between OpenConfig's "SVI is just an interface"
  model and the canonical's explicit VLAN list.
* :func:`access_and_native_vlan_ids` — the set of VIDs an operator
  unambiguously declared by binding a port to them as an ``access``
  or trunk ``native`` VLAN.  Port-centric codecs union this into the
  "legitimate" set their phantom-VLAN prune keeps, so a switchport-
  only VLAN (no ``vlan <N>`` stanza / SVI) survives while a wide
  ``trunk_allowed`` phantom range is still dropped.
* :func:`switchport_declared_vlan_ids` — the full "legitimate" set the
  phantom prune keeps: the above, PLUS the members of every
  ``trunk_allowed_vlans`` list narrow enough to be a specific operator
  declaration rather than the "allow everything" idiom.  This is what
  the six port-centric codecs call; :func:`access_and_native_vlan_ids`
  remains the narrower primitive it is built from.

Internal helper:

* ``_natural_port_sort_key`` — natural-sort key function used by
  :func:`project_vlan_to_switchport` to keep synthesised port-name
  ordering deterministic and operator-natural across vendors.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from .intent import CanonicalIntent, CanonicalInterface, CanonicalVlan

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


class _SortKeys(dict):
    """A port name's natural-sort key, worked out the first time it is
    asked for.  A port on a thousand VLANs is in a thousand lists that
    are each sorted; its key is the same in every one."""

    def __missing__(self, name: str) -> tuple:
        key = self[name] = _natural_port_sort_key(name)
        return key


class _PortList:
    """A port list while ports are being stamped onto it.

    Says whether a name is in the list, appends one that is not, and
    takes the first entry of a name out -- what ``name in lst``,
    ``lst.append`` and ``lst.remove`` do -- without reading the list
    for any of them.  An entry taken out is struck and leaves the list
    when :meth:`settle` is called; until then the list still holds it.
    The order of what remains is the order ``remove`` would have left,
    which matters to the stable sort that follows: two names can sort
    alike (``Gi1`` and ``Gi01``) and keep the order they were in.

    Two small counts are kept for a name, and nothing for an entry.
    The entries struck for a name are always its FIRST ones in the
    list -- each strike takes the oldest that is left, and a new entry
    goes on the end -- so how many of its first entries are struck
    says which they are.  (A queue of positions for every name was 760
    bytes for each stamp: nine tenths of what a membership cost while
    it was being made.)
    """

    __slots__ = ("_live", "_ports", "_struck")

    def __init__(self, ports: list[str]) -> None:
        self._ports = ports
        # name -> how many of its entries have not been struck.
        self._live: dict[str, int] = {}
        # name -> how many of its first entries have been.
        self._struck: dict[str, int] = {}
        live = self._live
        for name in ports:
            live[name] = live.get(name, 0) + 1

    def add(self, name: str) -> None:
        """Append *name* unless an entry for it is in the list."""
        if not self._live.get(name):
            self._live[name] = 1
            self._ports.append(name)

    def remove_first(self, name: str) -> None:
        """Strike the first entry of *name*, if there is one."""
        if self._live.get(name):
            self._live[name] -= 1
            self._struck[name] = self._struck.get(name, 0) + 1

    def settle(self) -> None:
        """Take the struck entries out of the list, in place."""
        if self._struck:
            left = self._struck
            kept: list[str] = []
            for name in self._ports:
                if left.get(name):
                    left[name] -= 1
                else:
                    kept.append(name)
            self._ports[:] = kept
            self._struck = {}


def access_and_native_vlan_ids(intent: CanonicalIntent) -> set[int]:
    """VIDs a per-port switchport config *unambiguously* declares as real.

    Returns every ``access_vlan`` and ``trunk_native_vlan`` referenced by
    any interface.  Both are single VIDs an operator explicitly bound a
    port to, so — unlike a wide ``trunk_allowed_vlans`` range that can span
    thousands of VIDs — they are never phantom-range inflation.

    A VLAN that exists only because a port is an access or native member
    of it — with no ``vlan <N>`` stanza and no SVI (the exact shape of a
    Cisco ``show running-config`` whose VLAN database lives in
    ``vlan.dat``) — is a real VLAN and must survive the phantom-VLAN
    prune.

    This is the narrow primitive, NOT what the codecs call.  The
    port-centric prune sites use :func:`switchport_declared_vlan_ids`,
    which unions this with the members of any sufficiently narrow
    ``trunk_allowed_vlans`` list.  Keep them separate: "a port is bound to
    exactly this VID" and "a port's trunk filter names this VID" are
    different claims, and only the first is unconditional.
    """
    vids: set[int] = set()
    for iface in intent.interfaces:
        if iface.access_vlan is not None:
            vids.add(iface.access_vlan)
        if iface.trunk_native_vlan is not None:
            vids.add(iface.trunk_native_vlan)
    return vids


#: Largest ``trunk_allowed_vlans`` list still read as a SPECIFIC operator
#: declaration rather than the "allow everything" idiom.
#:
#: A trunk-allowed list is a filter, not a VLAN database — but a *narrow*
#: one enumerates exactly the VLANs the operator put on that link, which
#: makes each member as real as an ``access_vlan``.  A *wide* one
#: (``1-4094``, ``2-4094``, ``100-3000``) says "don't filter" and names no
#: VLAN at all; expanding it would synthesise thousands of records the
#: operator never wrote.  Breadth is the signal that separates them — not
#: the literal form, because real narrow declarations are written as
#: ranges too (``switchport trunk allowed vlan 701-710``).
#:
#: The exact value is deliberately NOT load-bearing.  Measured over the
#: committed corpus the recovered-VID count is identical for every bound
#: from 12 to 2901 — the two populations are separated by a ~240x gap:
#:
#:     real, undeclared           <= 12 VIDs per list
#:     real, fully declared          85 VIDs per list  (a Junos ae trunk)
#:     "allow everything" idiom    4093 / 4094 VIDs per list
#:
#: 128 sits above every genuine list observed and ~4x below the narrowest
#: phantom case the regression guards pin (``500-999``).  That gap is
#: re-measured on every CI run by
#: ``tests/unit/migration/test_trunk_allowed_specificity_bound.py`` — if a
#: future capture lands a legitimate list wider than this, the guard fails
#: loudly instead of the VLANs being dropped silently.
TRUNK_ALLOWED_SPECIFICITY_BOUND = 128


def switchport_declared_vlan_ids(intent: CanonicalIntent) -> set[int]:
    """VIDs a per-port switchport config declares as real.

    :func:`access_and_native_vlan_ids` plus every member of a
    ``trunk_allowed_vlans`` list no wider than
    :data:`TRUNK_ALLOWED_SPECIFICITY_BOUND`.

    This is the set the six port-centric codecs (Cisco IOS-XE CLI, Arista
    EOS, NX-OS, Junos, Aruba AOS-CX, Dell OS10) keep through their
    phantom-VLAN prune.

    Why trunk-allowed members count
    -------------------------------
    They did not used to.  The prune kept only access and native VIDs, so
    a VLAN carried *solely* on a trunk was dropped at PARSE time — before
    any renderer or audit could see it.  Measured on the committed corpus
    that silently discarded 45 real VLANs across 6 captures, including the
    ten-VLAN block ``701-710`` on four Dell Azure-Local ToR configs.  The
    loss was invisible to the cross-mesh audit precisely because it
    happened before the comparison: source and target were both already
    missing the VIDs, so the cell scored ALIGNED.

    The anti-inflation rationale the old rule rested on is still honoured
    — it just applies to *wide* lists, which is the case it was written
    for.  A ``switchport trunk allowed vlan 1-4094`` still synthesises
    nothing.

    Note this reads the EXPANDED ``trunk_allowed_vlans`` list, so it needs
    no provenance about how the operator wrote it; ``701-710`` and
    ``701,702,...,710`` are treated identically, which is correct — they
    mean the same thing on the wire.
    """
    vids = access_and_native_vlan_ids(intent)
    for iface in intent.interfaces:
        allowed = iface.trunk_allowed_vlans
        if allowed and len(allowed) <= TRUNK_ALLOWED_SPECIFICITY_BOUND:
            vids.update(allowed)
    return vids


# Two lists of a trunk are not expanded into a VLAN record per id:
# every id (1-4094: Junos ``vlan members all``, Arista ``switchport
# trunk allowed vlan all``) and every id but 1 (2-4094, common on an
# MLAG peer link).  Projecting either into VLAN-centric tagged_ports
# would synthesise some 4,094 phantom VLAN records, each of which
# renders out and reparses with a generated name (``VLAN-N``),
# breaking round-trip stability and producing 4000-line VLAN dumps on
# cross-vendor renders.  The trunk goes onto the VLANs already
# declared that its list holds instead.  (The two are not the same
# list: 2-4094 leaves VLAN 1 out, and a renderer writes its word for
# "all" for the first only.)
_TRUNK_ALL_RANGE_FULL = frozenset(range(1, 4095))
_TRUNK_ALL_RANGE_OPERATIONAL = frozenset(range(2, 4095))
_EVERY_ID_IN_ORDER = list(range(1, 4095))


def _every_id(allowed: list[int]) -> frozenset[int] | None:
    """Which of the two lists that are not expanded *allowed* is --
    every id, or every id but 1 -- or ``None`` for any other list.

    The order of a list and an id written twice do not matter, as they
    did not when the list was compared as a set; a list too short to
    be either is not made into one to find that out.
    """
    if len(allowed) < len(_TRUNK_ALL_RANGE_OPERATIONAL):
        return None
    ids = set(allowed)
    if ids == _TRUNK_ALL_RANGE_FULL:
        return _TRUNK_ALL_RANGE_FULL
    if ids == _TRUNK_ALL_RANGE_OPERATIONAL:
        return _TRUNK_ALL_RANGE_OPERATIONAL
    return None


def is_every_vlan(allowed: Sequence[int]) -> bool:
    """Whether a trunk's allowed list says EVERY VLAN: it holds every
    id there is, 1-4094.

    On a trunk the list means what it says.  An empty list is no
    VLAN.  A list of every id is every VLAN -- the ones the device has
    and any it is given later, which is what the platforms that have a
    word for it mean by the word.  Any other list is the list.  There
    is no value for "not stated": the parser knows its platform and
    puts what the platform does with a trunk that states no list
    (``TRUNK_THAT_STATES_NO_LIST`` in ``codecs/_helpers.py``).

    The order of the list and an id written twice do not matter.  A
    list too short to hold every id is not made into a set to find
    that out, and neither is the list as every parser writes it, the
    ids in their order: this is asked of every trunk a renderer
    writes, and a config can have such a trunk on every port.
    """
    if len(allowed) < len(_TRUNK_ALL_RANGE_FULL):
        return False
    if allowed == _EVERY_ID_IN_ORDER:
        return True
    return _TRUNK_ALL_RANGE_FULL.issubset(allowed)


def _listed(allowed: list[int], keep: AbstractSet[int] | None) -> list[int]:
    """The ids of a trunk's list that are handed to a VLAN record.

    All of them for a caller that keeps every VLAN (``keep`` is
    ``None``): the list itself.  Otherwise the ids the caller keeps --
    and any id that is not a VLAN id at all, because the record
    refuses that one, and the parse has to fail as it did when every
    id was handed over.
    """
    if keep is None:
        return allowed
    return [
        vid for vid in allowed
        if vid in keep or vid not in _TRUNK_ALL_RANGE_FULL
    ]


def project_switchport_to_vlan(
    intent: CanonicalIntent,
    keep: AbstractSet[int] | None = None,
) -> None:
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
              A list of every id (``1-4094``), or of every id but
              1 (``2-4094``), is not made into 4,094 VLANs: the
              iface goes onto the VLANs already declared that the
              list holds.
            - if ``trunk_native_vlan`` is set:
              append iface to ``vlans[native].untagged_ports`` AND
              remove it from ``tagged_ports`` on that same VLAN.
              (Native VLAN traffic rides the trunk untagged; Cisco
              permits listing the native vlan in ``allowed`` but it
              never actually gets tagged.)

    Idempotent: an interface already present in a list is not added twice.

    This is Bug 3 from translator-plans.txt (KNOWN DATA-LOSS BUGS).

    Args:
        intent: The tree; changed in place.
        keep: The VLAN ids the caller keeps afterwards, or ``None``
            for a caller that keeps every one.  The six port-centric
            codecs drop, on the line after this call, every VLAN that
            is not in a set they worked out on the line before it
            (the VLANs already declared and
            :func:`switchport_declared_vlan_ids`).  Given that set, no
            record is made and no port stamped for an id of a trunk's
            list that is outside it.  The tree the caller is left with
            is the same either way; what differs is what is made on
            the way: a trunk that states ``1-4093`` was 4,093 VLAN
            records and as many stamps, so that a handful could be
            kept -- on a 48-port switch, some 400 times what was kept
            and nearly all the memory the parse took.  Access and
            native VLANs are always made (they are in every caller's
            set).  So is an id that is not a VLAN id at all, so that
            the record still refuses it: ``1-200,5000`` fails with
            *keep* as it does without.

    Raises:
        pydantic.ValidationError: An access, native or listed id is
            not a VLAN id (1-4094), with *keep* or without.
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

    # One reader per port list that is stamped, so that asking whether
    # a port is already in a list, and taking one out of it, do not
    # read the list: with a scan for each, a config of many trunks cost
    # the square of its ports.
    readers: dict[int, _PortList] = {}

    def _ports(lst: list[str]) -> _PortList:
        reader = readers.get(id(lst))
        if reader is None:
            reader = readers[id(lst)] = _PortList(lst)
        return reader

    def _add_unique(lst: list[str], name: str) -> None:
        _ports(lst).add(name)

    # (#20) PASS 1 — materialise every VLAN record a switchport references
    # BEFORE any membership stamping.  The trunk-all branch below stamps the
    # iface onto every VLAN in ``intent.vlans``; if a trunk-all uplink is
    # declared BEFORE an access port whose VLAN has no top-level stanza, that
    # VLAN is synthesised only later and the trunk-all stamp misses it — an
    # interface-order dependence that also made a second call add the entry
    # (violating the documented idempotency).  Pre-materialising decouples the
    # VLAN set from interface order.  This never stamps, so it can't change
    # what an already-order-correct config produced.
    #
    # What a trunk's list comes to is worked out here, once a trunk, and
    # used again in PASS 2, by the id() of the trunk: which of the two
    # lists that are not expanded it is (``whole``), or else the ids of
    # it that get a record (``listed``).
    whole: dict[int, frozenset[int]] = {}
    listed: dict[int, list[int]] = {}
    for iface in intent.interfaces:
        mode = iface.switchport_mode
        if mode == "access":
            if iface.access_vlan is not None:
                _vlan(iface.access_vlan)
        elif mode == "trunk":
            every = _every_id(iface.trunk_allowed_vlans)
            if every is not None:
                whole[id(iface)] = every
            else:
                ids = listed[id(iface)] = _listed(iface.trunk_allowed_vlans, keep)
                for vid in ids:
                    _vlan(vid)
            if iface.trunk_native_vlan is not None:
                _vlan(iface.trunk_native_vlan)

    # PASS 2 — stamp membership; the trunk-all branch now sees the full set.
    #
    # PASS 1 made every record there will be, so the tagged lists a
    # trunk of either whole list goes onto are found once for that
    # list (by its id()), and not once for every such trunk.
    onto: dict[int, list[_PortList]] = {
        id(every): [
            _ports(vlan.tagged_ports) for vlan in intent.vlans if vlan.id in every
        ]
        for every in set(whole.values())
    }
    for iface in intent.interfaces:
        mode = iface.switchport_mode
        if mode is None:
            continue
        if mode == "access":
            if iface.access_vlan is not None:
                _add_unique(_vlan(iface.access_vlan).untagged_ports, iface.name)
        elif mode == "trunk":
            every = whole.get(id(iface))
            if every is not None:
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
                #
                # Only the VLANs the list holds: `2-4094` leaves
                # VLAN 1 out, and a trunk written that way was
                # stamped onto a declared VLAN 1 all the same.
                name = iface.name
                for reader in onto[id(every)]:
                    reader.add(name)
            else:
                for vid in listed[id(iface)]:
                    _add_unique(_vlan(vid).tagged_ports, iface.name)
            native = iface.trunk_native_vlan
            if native is not None:
                vlan = _vlan(native)
                _add_unique(vlan.untagged_ports, iface.name)
                # Native VLAN rides the trunk untagged; purge any duplicate
                # in tagged_ports that came from trunk_allowed_vlans.
                _ports(vlan.tagged_ports).remove_first(iface.name)
        # Any other mode ("dynamic", etc.) is left alone — we don't have
        # enough signal to decide membership.

    # Operator-natural sort of the resulting membership lists.  The
    # projection above appends in ``intent.interfaces`` iteration
    # order; for cross-vendor renders that synthesise missing
    # interfaces (Aruba 1-48 untagged where only 1,2,42-47 had
    # iface stanzas) the synthesised ports land at the END of
    # ``intent.interfaces``, producing VLAN port lists like
    # ``[1, 2, 42, 43, 44, 45, 46, 47, 3, 4, ..., 41, 48]`` on
    # round-trip.  Sorting here gives every consumer a stable
    # operator-natural ordering regardless of which order the
    # source codec materialised its interface records.  Idempotent —
    # sorting twice is the same as once.
    for reader in readers.values():
        reader.settle()
    # A name's key is worked out once, not once for every VLAN the
    # name is in: N trunks on M VLANs are N keys, where they were N x M.
    # Only where a port was stamped, though.  The lists of a tree this
    # projection added nothing to (a VLAN-centric config) are sorted as
    # they always were: remembering a key for each name costs more than
    # working it out, when no name is asked for twice.
    key_of = _SortKeys().__getitem__ if readers else _natural_port_sort_key
    for vlan in intent.vlans:
        vlan.tagged_ports.sort(key=key_of)
        vlan.untagged_ports.sort(key=key_of)


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
            # Looked for in a set, kept in the list: a port tagged in
            # 4,000 VLANs looked through its own list for each one.
            allowed = set(iface.trunk_allowed_vlans)
            for vid in t_vids:
                if vid not in allowed:
                    allowed.add(vid)
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


_SVI_NAME_RE = re.compile(r"^Vlan(\d+)$", re.IGNORECASE)


def project_svi_to_vlan(intent: CanonicalIntent) -> None:
    """Fold ``interface Vlan<N>`` SVI L3 state onto the matching VLAN.

    Arista EOS / Cisco IOS-XE / EOS-derivative grammars carry the
    Layer-3 surface for a VLAN on a sibling ``interface Vlan<N>``
    stanza.  VLAN-centric downstream codecs (Aruba AOS-S, OPNsense)
    expect the IPv4 to live on :attr:`CanonicalVlan.ipv4_addresses`
    instead.  Without this projection the SVI IP is invisible to
    every VLAN-centric renderer - it stays attached to the
    ``Vlan<N>`` interface but the VLAN record is L3-empty.
    Originally implemented as ``_synthesize_vlans_from_svis`` in the
    cisco_iosxe_cli parser; lifted here so every codec that emits
    SVIs (arista_eos, cisco_iosxe_cli, future cisco_iosxe NETCONF)
    can call the same logic.
    See translator-plans.txt "KNOWN DATA-LOSS BUGS / BUG 1".

    Behaviour:
        * SVI with no matching VLAN record - synthesise a bare
          :class:`CanonicalVlan` with the SVI's IPs attached and
          its description as the fallback ``name``.
        * SVI with an existing VLAN record - merge the SVI's IPs
          onto :attr:`CanonicalVlan.ipv4_addresses`, de-duped on
          ``(ip, prefix_length)``.  The existing ``name`` wins.
        * SVI with no IPs - touched the same way; the bare VLAN
          still gets created so "this VLAN exists" round-trips.

    Idempotent + additive: walking the same intent twice does not
    duplicate IPs or VLAN records.
    """
    from .intent import CanonicalIPv4Address

    by_id: dict[int, CanonicalVlan] = {v.id: v for v in intent.vlans}
    for iface in intent.interfaces:
        m = _SVI_NAME_RE.match(iface.name)
        if not m:
            continue
        vid = int(m.group(1))
        existing = by_id.get(vid)
        if existing is None:
            # Dedupe the copied addresses by (ip, prefix_length) — the
            # same key the merge branch below uses.  Without this, an SVI
            # carrying multiple addresses that reduce to the same
            # (ip, prefix) pair (e.g. several VARP ``ip address virtual``
            # entries that fold to empty-ip /N records) synthesises
            # duplicate VLAN addresses on the first parse, while the merge
            # branch dedupes them on the rendered-output re-parse — an
            # asymmetry that breaks round-trip stability (observed on
            # VLAN 83 of the Arista AVD kitchen-sink capture).
            seen_synth: set[tuple[str, int]] = set()
            synth_addrs: list[CanonicalIPv4Address] = []
            for a in iface.ipv4_addresses:
                pair = (a.ip, a.prefix_length)
                if pair in seen_synth:
                    continue
                seen_synth.add(pair)
                synth_addrs.append(
                    CanonicalIPv4Address(
                        ip=a.ip, prefix_length=a.prefix_length,
                    )
                )
            synthesised = CanonicalVlan(
                id=vid,
                name=iface.description,
                ipv4_addresses=synth_addrs,
            )
            intent.vlans.append(synthesised)
            by_id[vid] = synthesised
            continue
        existing_pairs = {
            (a.ip, a.prefix_length) for a in existing.ipv4_addresses
        }
        for addr in iface.ipv4_addresses:
            pair = (addr.ip, addr.prefix_length)
            if pair not in existing_pairs:
                existing.ipv4_addresses.append(
                    CanonicalIPv4Address(
                        ip=addr.ip, prefix_length=addr.prefix_length,
                    )
                )
                existing_pairs.add(pair)


def synthesize_svis_from_vlan_l3(
    intent: CanonicalIntent,
) -> list[CanonicalInterface]:
    """Inverse of :func:`project_svi_to_vlan`: materialise a synthetic
    ``interface Vlan<N>`` SVI for every VLAN carrying Layer-3
    (``ipv4_addresses``) that has NO matching ``Vlan<N>`` interface in
    ``intent.interfaces``.

    SVI-model renderers (arista_eos, cisco_iosxe_cli) emit a VLAN's L3
    from a sibling ``interface Vlan<N>`` stanza, NOT from
    :attr:`CanonicalVlan.ipv4_addresses`.  A same-vendor parse keeps
    that interface in ``intent.interfaces`` (the
    :func:`project_svi_to_vlan` fold is additive — it copies the IPs
    onto the VLAN but leaves the interface), so the SVI is already
    present and this returns nothing for it.  But a cross-vendor source
    that lands the VLAN's L3 on ``vlans[].ipv4_addresses`` WITHOUT a
    ``Vlan<N>`` interface — Junos ``set interfaces irb unit N family
    inet address X/N`` + ``set vlans <name> l3-interface irb.N`` is the
    canonical example — would otherwise lose the SVI address entirely on
    render, even though the capability matrix and the cross-vendor
    expectation YAMLs both declare ``vlans[].ipv4_addresses`` *good* for
    these targets.

    NON-MUTATING by contract: returns a fresh list of synthetic
    interfaces for the caller to render ALONGSIDE
    ``intent.interfaces`` — it must NOT append to ``intent.interfaces``,
    because the cross-mesh runner parses a source ONCE and reuses that
    one intent across every target render; a mutation would leak the
    synthetic SVIs into sibling renders.

    The synthetic SVI carries only ``ip`` / ``prefix_length`` — the same
    subset :func:`project_svi_to_vlan` denormalises onto the VLAN — so
    the rendered SVI re-parses back to an identical
    ``vlans[].ipv4_addresses`` record (the round-trip the cross-mesh
    audit compares), and dedupes on ``(ip, prefix_length)`` for the same
    reason the fold does.
    """
    from .intent import CanonicalInterface, CanonicalIPv4Address

    existing_svi_ids: set[int] = set()
    for iface in intent.interfaces:
        m = _SVI_NAME_RE.match(iface.name)
        if m:
            existing_svi_ids.add(int(m.group(1)))

    synth: list[CanonicalInterface] = []
    for vlan in intent.vlans:
        if vlan.id in existing_svi_ids or not vlan.ipv4_addresses:
            continue
        seen: set[tuple[str, int]] = set()
        addrs: list[CanonicalIPv4Address] = []
        for a in vlan.ipv4_addresses:
            pair = (a.ip, a.prefix_length)
            if pair in seen:
                continue
            seen.add(pair)
            addrs.append(
                CanonicalIPv4Address(
                    ip=a.ip, prefix_length=a.prefix_length,
                )
            )
        synth.append(
            CanonicalInterface(name=f"Vlan{vlan.id}", ipv4_addresses=addrs)
        )
    return synth
