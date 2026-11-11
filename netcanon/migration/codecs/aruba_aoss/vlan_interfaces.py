"""What an interface of the tree that stands for a VLAN is on AOS-S:
a VLAN, by the tree's own id, or a review line.

AOS-S routes on a VLAN: an address is a line of a ``vlan <id>`` stanza,
and a port is a member of a VLAN, tagged or untagged.  The renderer has
no form for an interface that is one unit of a port, nor for an
interface whose name is free text, and it read a VLAN's id from an
interface's NAME (``Vlan<id>``, ``vlan<id>``, ``irb.<id>``).  Two kinds
of interface in the tree were written wrongly so:

* **A routed sub-interface**: an 802.1Q tag on one port
  (``dot1q_vlan``), from IOS-XE, Junos, VyOS, FortiOS, OPNsense and
  RouterOS.  It came out as ``interface <port>.<unit>``, a line AOS-S
  has no form for, or -- where its name happened to end in its tag --
  inside a VLAN stanza that did not tag its port.  It is written as
  VLAN <tag>, tagged on its port, with its addresses: on AOS-S, the
  frames with that tag on that port, routed with that address.  One
  thing differs, and the job says it: an AOS-S VLAN is the switch's, so
  a port tagged with the same VLAN later is in the same network, where
  a sub-interface is its port's alone.
* **A VLAN interface its parser links to its VLAN record by name**
  (RouterOS, OPNsense, and FortiOS on a FortiLink): ``vlan_parent``
  set, no tag, ``ianaift:l3ipvlan``, and one VLAN record named after
  it.  Its VLAN is that record's id, never digits in its name: on
  RouterOS a name is free text, and ``vlan10`` may carry VLAN 20.  Read
  by its name, its address went to VLAN 10, or nowhere.  A VLAN that
  has a label is called by it on AOS-S, and the label is its name in
  the tree the renderer is given (``_vlan_labels``), so the record is
  no longer named after the interface: where the platform has one label
  for a VLAN and its interface (:data:`_ONE_LABEL`), the record is
  found by the label the interface carries; and one that no record
  names, nor its label, is refused.  Read by its name, an address of a
  RouterOS, FortiOS or OPNsense VLAN interface whose VLAN has a label
  went to the VLAN its digits name, which may be another VLAN's.  One
  named ``Vlan<id>`` with no record is the VLAN of that id: an entry of
  the port map gave it the name AOS-S has for that VLAN's interface.
  From those three platforms (``NAMES_A_VLAN_AFTER_ITS_INTERFACE``)
  one whose parent the port translator dropped -- a bridge AOS-S has no
  name for, such as RouterOS's default ``bridge`` -- is found the same
  way, and is never read as a VLAN interface of a grammar: read so, a
  RouterOS ``vlan10`` that carries VLAN 20 had its address written into
  VLAN 10.
* **A VLAN interface of a grammar that has one** (:func:`_svi_id`): no
  tag, no parent, typed a VLAN interface by its parser, from none of
  those three platforms, and named
  ``Vlan<id>`` in any letter case, as IOS-XE, NX-OS, EOS and AOS-S
  write it, or ``vlan <id>`` (AOS-CX) or ``vlan<id>`` (OS10).  The
  renderer looked for ``Vlan<id>`` only, so an AOS-CX or OS10 VLAN
  interface lost its IPv6 addresses, and an OS10 one its VRRP groups
  (the AOS-CX parser reads none; the IPv4 addresses are on the VLAN's
  record, where those parsers put them),
  and one that is shut down was written as an address that is up.  Its
  VLAN is its id, as its grammar has it.  It is refused where it is
  disabled and holds an address or a VRRP group, and its addresses are
  then taken off its VLAN's record, which still writes the VLAN's
  ports; and where another interface stands for its VLAN.  One that
  has no VLAN record and holds something is given one.

Each is renamed ``Vlan<id>`` throughout the tree, through the one sweep
of port names (:func:`~netcanon.migration.canonical.port_names.rewrite_port_names`),
so that the VLAN's stanza takes its addresses, its VRRP groups and its
DHCP pools, and a route out of it is ``vlan <id>``, by the rule that
reads a Cisco ``Vlan<id>``.  A sub-interface is given the record its
VLAN did not have.

What cannot be written so is refused: a ``; review:`` line where its
stanza would be, a warning of the job, and its name kept out of every
reading of a VLAN id from a name (:attr:`Prepared.not_a_vlan`), so that
no VLAN takes its addresses and no route goes out of a VLAN it does not
stand for.  A sub-interface is refused where it has two tags, takes its
port's untagged frames, is disabled, carries VLAN 1 (the switch's
default VLAN, which every port is in), carries a VLAN the config also
has as a network of its own (a VLAN record with a port or an address)
or as another sub-interface, rides on no port AOS-S can tag (a VLAN,
a loopback, another unit, or a name an unquoted port list cannot
hold), or where another interface already stands for its VLAN.  A VLAN record of its
tag that holds nothing (the IOS XR parser makes one for each tag a
sub-interface states) is the VLAN it is written as; where every
sub-interface that carries its VLAN is refused, such a record is not
written at all (:data:`_VLANS_ARE_ITS_TAGS`), for it states nothing the
config said: written, it was a ``vlan <id>`` stanza of nothing, a VLAN
the switch would make and no port is in.  A VLAN interface
is refused where it is disabled, is named by more than one VLAN record,
has the label of more than one, is named by none and has the label of
none, or where another interface stands for its VLAN.

An interface whose name begins ``vlan`` and that no VLAN stanza takes
(a FortiOS loopback called ``vlan-guest``, a RouterOS bridge called
``vlanbr``) is not one of these: the renderer writes it as it writes
every other name of no AOS-S form, with what it holds.

A unit of a port or a LAG of AOS-S that has no 802.1Q tag (``2.100``,
``Trk1.100``: the name the port translator gives a unit it sends after
its port, or an entry of the port map) is not written either: AOS-S
has no form for a unit of a port, and writes one only as the VLAN of
its tag.  Where it holds an address, a VRRP group, a description or an
MTU, a ``; review:`` line and a warning say so; one that holds none of
them loses nothing, and nothing is said.  Written, it was ``interface
2.100``, a name AOS-S has no form for, with its address.  The AOS-CX
and OS10 parsers read no tag for a sub-interface, so each of theirs is
such a unit.  A unit of a name of no AOS-S form (``ge-0/0/2.100``, left
as the source has it) is written as every such name is, for a reviewer.

An interface in a VRF is written without it, as the renderer writes
every other interface of a VRF (a ``Vlan<id>`` of IOS-XE among them):
AOS-S has no VRF, and ``/interfaces/interface/config/vrf`` is declared
lossy, so the job lists the VRF as dropped.

The renderer and the job's warnings read the same function
(:func:`prepare`), on the tree as it is given to the codec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..._vlan_labels import NAMES_A_VLAN_AFTER_ITS_INTERFACE
from ...canonical.intent import CanonicalIntent, CanonicalInterface, CanonicalVlan
from ...canonical.port_names import rewrite_port_names, split_unit
from ...limits import ticked
from .port_names import classify_port_name

#: A name that encodes a VLAN's id, and the id: ``Vlan10`` /
#: ``vlan10`` (Cisco and generic), and a unit of a VLAN device or of a
#: Junos ``irb`` (OPNsense ``vlan0.10``, Junos ``irb.10``).  A routed
#: sub-interface of a port (``Ethernet1.10``, ``port1.10``) is not one:
#: its VLAN is its tag (``dot1q_vlan``), and on FortiOS its name is free
#: text.
_VLAN_ID_BARE_RE = re.compile(r"^[Vv]lan(\d+)$")
_VLAN_ID_DOTTED_RE = re.compile(r"^(?:[Vv]lan\d*|irb)\.(\d+)$")

#: The name of a grammar's VLAN interface, and its id: ``Vlan30``
#: (IOS-XE, NX-OS, EOS, AOS-S), ``vlan 30`` (AOS-CX), ``vlan30`` (OS10),
#: in any letter case.  Read only of an interface its parser types a
#: VLAN interface (:data:`_SVI_TYPES`) and gives no tag and no parent:
#: on FortiOS and RouterOS a name is free text, and a loopback or a
#: bridge may be called ``vlan30``.  Nor is it read of a VLAN interface
#: from FortiOS, RouterOS or OPNsense, which has no parent where the
#: port translator dropped it: its parser links it to its VLAN record.
_SVI_NAME_RE = re.compile(r"[Vv][Ll][Aa][Nn] ?(\d+)")

#: The types a parser gives a VLAN interface of its grammar: the
#: CLI parsers ``l3ipvlan``, the IOS-XE NETCONF parser ``l2vlan``.
_SVI_TYPES = frozenset({"ianaift:l3ipvlan", "ianaift:l2vlan"})

#: The platforms (``CanonicalIntent.source_vendor``) that have ONE
#: label for a VLAN and its VLAN interface, which their parser reads as
#: the description of both: RouterOS ``comment=`` on ``/interface
#: vlan``, FortiOS ``set alias``.  The label pass gives a VLAN its label
#: as its name (``_vlan_labels``), and the interface still carries it.
#: OPNsense is not one: a VLAN device's ``<descr>`` is the VLAN's, and
#: the interface is described by its zone's.  Measured, not assumed:
#: ``test_an_interface_that_stands_for_a_vlan.py`` parses each.
_ONE_LABEL = frozenset({"fortigate", "mikrotik_routeros"})

#: The platforms (``CanonicalIntent.source_vendor``) whose parser makes
#: a VLAN record of each 802.1Q tag a sub-interface states, and of
#: nothing else: IOS XR has no VLAN stanza, and its parser gives each
#: tag a record with no name and no port, so that a target of VLANs is
#: given the ids.  Such a record, as the parser made it, states nothing
#: of its own (:func:`_records_of_refused_tags`).  Measured, not
#: assumed: ``test_an_interface_that_stands_for_a_vlan.py`` parses each.
_VLANS_ARE_ITS_TAGS = frozenset({"cisco_iosxr"})

#: The name AOS-S has for a VLAN's interface, and the id.  Read of a
#: VLAN interface on a parent that no record links to its VLAN: only an
#: entry of the port map gives it that name.
_AOSS_VLAN_NAME_RE = re.compile(r"Vlan([1-9]\d{0,3})")

#: Names AOS-S has for an interface that is no port: a VLAN, a
#: loopback, the out-of-band management port.  Such a name cannot be
#: tagged in a VLAN.
_NOT_A_PORT_RE = re.compile(r"^(?:vlan|irb|loopback|oobm)", re.IGNORECASE)

#: A name that can stand in an AOS-S port list as one port: the list is
#: written unquoted, its entries cut at commas, and the device ends the
#: list at white space.  (This parser keeps a name with a space in it
#: whole, so asking it would pass a name no switch reads.)
_ONE_ENTRY_RE = re.compile(r"[^\s,\"']+")


def vlan_id_of_name(name: str, not_a_vlan: frozenset[str] = frozenset()) -> int | None:
    """The VLAN id *name* encodes (:data:`_VLAN_ID_BARE_RE`,
    :data:`_VLAN_ID_DOTTED_RE`), or ``None``: for a name of no such
    form, and for one :func:`prepare` found to stand for no VLAN, or for
    another (*not_a_vlan*, lower case)."""
    if name.lower() in not_a_vlan:
        return None
    m = _VLAN_ID_BARE_RE.match(name) or _VLAN_ID_DOTTED_RE.match(name)
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class Prepared:
    """The tree the renderer writes, and what :func:`prepare` said.

    Attributes:
        tree: The tree given, or a copy of it in which each interface
            that stands for a VLAN is named ``Vlan<id>`` and each
            sub-interface that is written as a VLAN has the VLAN's
            record.
        review: For each interface that is refused, by its name in
            :attr:`tree`: the ``; review:`` line written where its
            stanza would be.
        not_a_vlan: The refused names, in lower case, and those of the
            units of a port with no tag that are written nowhere and
            said nowhere (they hold nothing): no reading of a VLAN id
            from a name may take one of them, and the renderer writes
            no stanza of theirs.
        warnings: One warning of the job for each sub-interface written
            as a VLAN and for each interface refused.
        as_vlans: The names in :attr:`tree`, in lower case, of the
            interfaces written as a VLAN (``vlan<id>``): the renderer
            writes no stanza of their own, a VLAN's stanza being all
            there is of them on AOS-S.
    """

    tree: CanonicalIntent
    review: dict[str, str] = field(default_factory=dict)
    not_a_vlan: frozenset[str] = frozenset()
    warnings: tuple[str, ...] = ()
    as_vlans: frozenset[str] = frozenset()


def _svi_id(iface: CanonicalInterface) -> int | None:
    """The VLAN id of *iface*, where it is a VLAN interface of its
    grammar (:data:`_SVI_NAME_RE`, :data:`_SVI_TYPES`), or ``None``."""
    if iface.dot1q_vlan is not None or iface.vlan_parent:
        return None
    if iface.interface_type not in _SVI_TYPES:
        return None
    m = _SVI_NAME_RE.fullmatch(iface.name)
    if m is None:
        return None
    vid = int(m.group(1))
    return vid if 1 <= vid <= 4094 else None


def _by_its_label(
    iface: CanonicalInterface, labelled: dict[str, list[CanonicalVlan]],
) -> tuple[int | None, str] | None:
    """The VLAN a VLAN interface on a parent carries, found by the label
    it carries (*labelled*: the records called by their label, by it),
    and why it is not written as that VLAN, or ``""``; ``None`` where no
    record has its label."""
    named = labelled.get(iface.description, []) if iface.description else []
    if not named:
        return None
    ids = sorted({vlan.id for vlan in named})
    if len(ids) > 1:
        return None, (
            "has the label of VLANs " + ", ".join(str(v) for v in ids)
            + ", and which of them it carries is not known here"
        )
    return _why_not_a_vlan_interface(iface, named)


def _holds_something(iface: CanonicalInterface) -> bool:
    """Whether *iface* holds what a VLAN's stanza writes of it: an
    address or a VRRP group."""
    return bool(iface.ipv4_addresses or iface.ipv6_addresses or iface.vrrp_groups)


def _port_of(iface: CanonicalInterface) -> str:
    """The port a sub-interface is a unit of: the parent its config
    states, or else the name in front of its unit (``ge-0/0/1`` of
    ``ge-0/0/1.54``); ``""`` where there is none."""
    if iface.vlan_parent:
        return iface.vlan_parent
    unit = split_unit(iface.name)
    return unit[0] if unit else ""


def _taggable(port: str) -> bool:
    """Whether a VLAN's ``tagged`` line can name *port*: a name that is
    no VLAN, loopback or management interface of AOS-S, is no unit of
    another port, and can stand in a port list (:data:`_ONE_ENTRY_RE`:
    no white space, comma or quote)."""
    return (
        _ONE_ENTRY_RE.fullmatch(port) is not None
        and not _NOT_A_PORT_RE.match(port)
        and split_unit(port) is None
    )


def _holds_a_network(vlan: CanonicalVlan) -> bool:
    """Whether VLAN record *vlan* is a network of its own: it has a
    port, tagged or untagged, or an address."""
    return bool(vlan.tagged_ports or vlan.untagged_ports or vlan.ipv4_addresses)


def _why_not_a_sub_interface(
    iface: CanonicalInterface, records: dict[int, CanonicalVlan],
    tags: dict[int, list[str]],
) -> str:
    """Why sub-interface *iface* is not written as its VLAN, or ``""``.
    *records* are the tree's VLAN records by id (the first of each);
    *tags*, the sub-interfaces by their tag."""
    tag = iface.dot1q_vlan
    port = _port_of(iface)
    if iface.dot1q_inner_vlan is not None:
        return (
            f"matches two 802.1Q tags ({tag}, then {iface.dot1q_inner_vlan}), "
            f"and AOS-S has no form for that"
        )
    if iface.dot1q_native:
        return (
            f"also takes the untagged frames of {port or 'its port'}, and an "
            f"AOS-S VLAN has no form for that"
        )
    if not iface.enabled:
        return "is disabled, and an AOS-S VLAN cannot be"
    if tag == 1:
        return (
            "carries VLAN 1, the switch's default VLAN, which every port "
            "of the switch is in"
        )
    if tag in records and _holds_a_network(records[tag]):
        return (
            f"carries VLAN {tag}, which the config also has as a VLAN; on "
            f"AOS-S the two would be one network"
        )
    others = [name for name in tags.get(tag, ()) if name != iface.name]
    if others:
        return (
            f"carries VLAN {tag}, as {others[0]} does; on AOS-S the two "
            f"would be one network"
        )
    if not _taggable(port):
        return (
            f"is a unit of {port}, which is no port AOS-S can tag"
            if port else "names no port it is a unit of"
        )
    return ""


#: What one interface stands for: its index in the tree, its VLAN id
#: (``None`` where it is the interface of several), why it is refused
#: (``""`` where it is not), and whether it is a sub-interface.
_Decision = tuple[int, "int | None", str, bool]


def _why_not_a_vlan_interface(
    iface: CanonicalInterface, named: list[CanonicalVlan],
) -> tuple[int | None, str]:
    """The VLAN a VLAN interface its records *named* name stands for,
    and why it is not written as that VLAN, or ``""``."""
    ids = sorted({vlan.id for vlan in named})
    if len(ids) > 1:
        return None, (
            "is the interface of VLANs " + ", ".join(str(v) for v in ids)
            + ", and an AOS-S VLAN stanza is one VLAN's"
        )
    if not iface.enabled:
        return ids[0], "is disabled, and an AOS-S VLAN cannot be"
    return ids[0], ""


def _decide(
    tree: CanonicalIntent,
) -> tuple[list[_Decision], dict[int, list[str]], list[tuple[int, int]]]:
    """What each sub-interface and each VLAN interface its record names
    stands for; for every other interface whose name encodes a VLAN id
    (:func:`vlan_id_of_name`) or that is a VLAN interface of its grammar
    (:func:`_svi_id`), its name, by that id; and the latter, as (index,
    VLAN id)."""
    records_by_name: dict[str, list[CanonicalVlan]] = {}
    records: dict[int, CanonicalVlan] = {}
    for vlan in ticked(tree.vlans):
        records_by_name.setdefault(vlan.name, []).append(vlan)
        records.setdefault(vlan.id, vlan)
    # The records called by their label: named, described no more, and
    # named after no interface -- on a platform of one label.
    labelled: dict[str, list[CanonicalVlan]] = {}
    if tree.source_vendor in _ONE_LABEL:
        names = {iface.name for iface in ticked(tree.interfaces)}
        for vlan in ticked(tree.vlans):
            if vlan.name and not vlan.description and vlan.name not in names:
                labelled.setdefault(vlan.name, []).append(vlan)
    tags: dict[int, list[str]] = {}
    for iface in ticked(tree.interfaces):
        if iface.dot1q_vlan is not None:
            tags.setdefault(iface.dot1q_vlan, []).append(iface.name)
    # A platform whose parser links a VLAN interface to the record named
    # after it, where a name says nothing of a VLAN's id.
    linked_by_its_parser = tree.source_vendor in NAMES_A_VLAN_AFTER_ITS_INTERFACE
    decided: list[_Decision] = []
    by_its_name: dict[int, list[str]] = {}
    svis: list[tuple[int, int]] = []
    for index, iface in enumerate(ticked(tree.interfaces)):
        if iface.dot1q_vlan is not None:
            why = _why_not_a_sub_interface(iface, records, tags)
            decided.append((index, iface.dot1q_vlan, why, True))
            continue
        named = records_by_name.get(iface.name, []) if iface.name else []
        # On a parent, or with none where the port translator dropped it.
        linkable = iface.interface_type == "ianaift:l3ipvlan" and (
            bool(iface.vlan_parent) or linked_by_its_parser
        )
        if linkable and named:
            vid, why = _why_not_a_vlan_interface(iface, named)
            decided.append((index, vid, why, False))
            continue
        if linkable:
            linked = _by_its_label(iface, labelled)
            if linked is not None:
                decided.append((index, *linked, False))
                continue
            m = _AOSS_VLAN_NAME_RE.fullmatch(iface.name)
            vid = int(m.group(1)) if m else 0
            if not 1 <= vid <= 4094:
                decided.append((index, None, (
                    f"rides on {iface.vlan_parent or 'no port of the output'}, "
                    "and which VLAN it carries is not known here: no VLAN is "
                    "named after it, nor has its label"
                ), False))
                continue
            by_its_name.setdefault(vid, []).append(iface.name)
            continue
        svi = _svi_id(iface)
        if svi is not None:
            svis.append((index, svi))
        encoded = svi if svi is not None else vlan_id_of_name(iface.name)
        if encoded is not None:
            by_its_name.setdefault(encoded, []).append(iface.name)
    return decided, by_its_name, svis


def _one_interface_each(
    tree: CanonicalIntent, decided: list[_Decision],
    by_its_name: dict[int, list[str]],
) -> list[_Decision]:
    """*decided*, with each interface refused that stands for a VLAN
    another interface stands for as well: a VLAN's stanza takes one
    interface's addresses.  An interface whose name encodes the VLAN
    (*by_its_name*) keeps the reading it had."""
    claims: dict[int, list[str]] = {}
    for index, vid, why, _sub in decided:
        if vid is not None and not why:
            claims.setdefault(vid, []).append(tree.interfaces[index].name)
    final: list[_Decision] = []
    for index, vid, why, sub in decided:
        name = tree.interfaces[index].name
        if vid is not None and not why:
            others = [n for n in (*claims[vid], *by_its_name.get(vid, ())) if n != name]
            if others:
                why = (
                    f"stands for VLAN {vid}, as {others[0]} does, and an AOS-S "
                    f"VLAN stanza is one interface's"
                )
        final.append((index, vid, why, sub))
    return final


#: The kinds of name (:func:`.port_names.classify_port_name`) whose
#: unit is a unit of a port: a port or a LAG of AOS-S.
_PORT_KINDS = frozenset({"physical", "lag"})


def _units_with_no_tag(
    tree: CanonicalIntent, taken: set[int],
) -> tuple[list[_Decision], set[str]]:
    """Each interface of *tree* that is a unit of a port or a LAG of
    AOS-S and has no 802.1Q tag, of those :func:`_decide` did not decide
    (*taken*, by index): those that hold an address, a VRRP group, a
    description or an MTU, refused, as decisions; and the names of all
    of them, in lower case.  AOS-S has no form for a unit of a port."""
    refused: list[_Decision] = []
    names: set[str] = set()
    for index, iface in enumerate(ticked(tree.interfaces)):
        if index in taken or iface.dot1q_vlan is not None:
            continue
        unit = split_unit(iface.name)
        if unit is None or classify_port_name(unit[0]).kind not in _PORT_KINDS:
            continue
        names.add(iface.name.lower())
        if _holds_something(iface) or iface.description or iface.mtu is not None:
            refused.append((index, None, (
                f"is a unit of {unit[0]} with no 802.1Q tag read for it, and "
                f"AOS-S writes a unit of a port only as the VLAN of its tag"
            ), False))
    return refused, names


def _the_svis(
    tree: CanonicalIntent, svis: list[tuple[int, int]],
) -> tuple[list[_Decision], list[tuple[int, int]], list[tuple[int, int]]]:
    """Each VLAN interface of its grammar of *svis* (index, VLAN id):
    the refused, as decisions; those written, as (index, VLAN id); and
    those refused for being disabled, whose addresses come off their
    VLAN's record.  Of the interfaces of one id, one already named
    ``Vlan<id>`` (in any letter case) is decided first, and then the
    others in the order of the tree.  The first is written, unless it is
    disabled and holds something (:func:`_holds_something`); another of
    the same id, or one whose ``Vlan<id>`` another interface of the tree
    is named, is refused."""
    names = {iface.name.lower(): iface.name for iface in ticked(tree.interfaces)}
    refused: list[_Decision] = []
    written: list[tuple[int, int]] = []
    stripped: list[tuple[int, int]] = []
    first: dict[int, str] = {}
    named_so = sorted(
        svis, key=lambda svi: tree.interfaces[svi[0]].name.lower() != f"vlan{svi[1]}",
    )
    for index, vid in ticked(named_so):
        iface = tree.interfaces[index]
        taken = first.get(vid) or (
            names.get(f"vlan{vid}") if iface.name.lower() != f"vlan{vid}" else None
        )
        if taken is not None and taken != iface.name:
            refused.append((index, vid, (
                f"stands for VLAN {vid}, as {taken} does, and an AOS-S VLAN "
                f"stanza is one interface's"
            ), False))
            continue
        first.setdefault(vid, iface.name)
        if not iface.enabled and _holds_something(iface):
            refused.append((index, vid, "is disabled, and an AOS-S VLAN cannot be", False))
            stripped.append((index, vid))
            continue
        written.append((index, vid))
    return refused, written, stripped


def _records_of_refused_tags(
    tree: CanonicalIntent, every: list[_Decision],
    by_its_name: dict[int, list[str]], svis_written: list[tuple[int, int]],
) -> frozenset[int]:
    """The VLANs of *tree* whose record its parser made of a
    sub-interface's tag (:data:`_VLANS_ARE_ITS_TAGS`), is as the parser
    made it (no name and nothing else), and that nothing else stands
    for: every sub-interface that carries the VLAN is refused (*every*),
    no other interface is written as it (*every*, *svis_written*) or
    named after it (*by_its_name*), and no port of the tree names it.
    Written, each was a ``vlan <id>`` stanza of nothing."""
    if tree.source_vendor not in _VLANS_ARE_ITS_TAGS:
        return frozenset()
    refused = {vid for _index, vid, why, sub in every if sub and why and vid is not None}
    held = {vid for _index, vid, why, sub in every if vid is not None and not (sub and why)}
    held.update(vid for _index, vid in svis_written)
    held.update(by_its_name)
    candidates = refused - held
    if not candidates:
        return frozenset()
    for iface in ticked(tree.interfaces):
        named = {iface.access_vlan, iface.trunk_native_vlan, iface.voice_vlan}
        if candidates & named or not candidates.isdisjoint(iface.trunk_allowed_vlans):
            candidates -= named | set(iface.trunk_allowed_vlans)
    return frozenset(
        vlan.id for vlan in ticked(tree.vlans)
        if vlan.id in candidates and vlan == CanonicalVlan(id=vlan.id, name="")
    )


def _written(
    tree: CanonicalIntent, renames: dict[str, str],
    written: list[tuple[int, int, str]],
    svis: tuple[list[int], list[tuple[int, int]]] = ([], []),
    unwritten: frozenset[int] = frozenset(),
) -> CanonicalIntent:
    """A copy of *tree* with each name of *renames* renamed everywhere,
    and each sub-interface of *written* (index, VLAN id, port) untagged
    and its port tagged in its VLAN's record, made where it has none.
    *svis* are the VLANs whose interface of its grammar is written and
    has no record, each given one; and the VLAN interfaces of their
    grammar refused for being disabled (index, VLAN id), each of whose
    addresses comes off every record of its VLAN.  The records of the
    VLANs of *unwritten* (:func:`_records_of_refused_tags`) are taken
    out."""
    out = tree.model_copy(deep=True)
    if unwritten:
        out.vlans = [vlan for vlan in out.vlans if vlan.id not in unwritten]
    if renames:
        rewrite_port_names(out, lambda name: renames.get(name, name), units=False)
    of_id: dict[int, CanonicalVlan] = {}
    for vlan in out.vlans:
        of_id.setdefault(vlan.id, vlan)
    records_made, svis_stripped = svis
    for vid in records_made:
        of_id[vid] = CanonicalVlan(id=vid)
        out.vlans.append(of_id[vid])
    for index, vid in svis_stripped:
        held = {(a.ip, a.prefix_length) for a in out.interfaces[index].ipv4_addresses}
        for vlan in out.vlans:
            if vlan.id == vid:
                vlan.ipv4_addresses = [
                    a for a in vlan.ipv4_addresses if (a.ip, a.prefix_length) not in held
                ]
    for index, vid, port in written:
        sub_iface = out.interfaces[index]
        sub_iface.dot1q_vlan = None
        sub_iface.vlan_parent = None
        record = of_id.get(vid)
        if record is None:
            record = of_id[vid] = CanonicalVlan(id=vid)
            out.vlans.append(record)
        record.tagged_ports.append(port)
    return out


def prepare(tree: CanonicalIntent) -> Prepared:
    """Each interface of *tree* that stands for a VLAN, written as that
    VLAN or refused (the module docstring has the rules).

    The tree given is not changed: where anything is renamed or added,
    :attr:`Prepared.tree` is a copy.
    """
    decided, by_its_name, svis = _decide(tree)
    units_refused, units = _units_with_no_tag(
        tree, {d[0] for d in decided} | {index for index, _vid in svis},
    )
    if not decided and not svis and not units:
        return Prepared(tree)
    svis_refused, svis_written, svis_stripped = _the_svis(tree, svis)
    review: dict[str, str] = {}
    # A unit of a port with no tag is written nowhere, and said where it
    # holds something (``units_refused``).
    refused: set[str] = set(units)
    warnings: list[str] = []
    renames: dict[str, str] = {
        tree.interfaces[index].name: f"Vlan{vid}"
        for index, vid in svis_written
        if tree.interfaces[index].name != f"Vlan{vid}"
    }
    written: list[tuple[int, int, str]] = []
    as_vlans: set[str] = set()
    every = [
        *_one_interface_each(tree, decided, by_its_name), *svis_refused, *units_refused,
    ]
    for index, vid, why, sub in every:
        iface = tree.interfaces[index]
        if why or vid is None:      # (a VLAN interface of no one VLAN has a reason)
            review.setdefault(iface.name, f"; review: interface {iface.name} {why}; not written")
            refused.add(iface.name.lower())
            warnings.append(f"interface {iface.name} {why}; not written")
            continue
        as_vlans.add(f"vlan{vid}")
        if iface.name != f"Vlan{vid}":
            renames[iface.name] = f"Vlan{vid}"
        if sub:
            port = _port_of(iface)
            written.append((index, vid, port))
            warnings.append(
                f"interface {iface.name} (802.1Q tag {vid} on {port}) is written "
                f"as VLAN {vid}, tagged on {port}: an AOS-S VLAN is the "
                f"switch's, so a port tagged {vid} later is in the same network"
            )
    # A copy only where something changes: the AOS-S parser's own
    # ``Vlan<id>`` is written as it is.
    ids = {vlan.id for vlan in tree.vlans}
    records_made = sorted({
        vid for index, vid in svis_written
        if vid not in ids and _holds_something(tree.interfaces[index])
    })
    unwritten = _records_of_refused_tags(tree, every, by_its_name, svis_written)
    if renames or written or records_made or svis_stripped or unwritten:
        tree = _written(tree, renames, written, (records_made, svis_stripped), unwritten)
    as_vlans.update(f"vlan{vid}" for _index, vid in svis_written)
    return Prepared(
        tree, review, frozenset(refused), tuple(warnings), frozenset(as_vlans),
    )
