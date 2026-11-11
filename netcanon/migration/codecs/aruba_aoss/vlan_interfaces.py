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
  (RouterOS, OPNsense, and FortiOS on a switch): ``vlan_parent`` set,
  no tag, ``ianaift:l3ipvlan``, and one VLAN record named after it.  Its
  VLAN is that record's id, never digits in its name: on RouterOS a
  name is free text, and ``vlan10`` may carry VLAN 20.  Read by its
  name, its address went to VLAN 10, or nowhere.

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
sub-interface states) is the VLAN it is written as.  A VLAN interface
is refused where it is disabled, is named by more than one VLAN record,
or where another interface stands for its VLAN.

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

from ...canonical.intent import CanonicalIntent, CanonicalInterface, CanonicalVlan
from ...canonical.port_names import rewrite_port_names, split_unit
from ...limits import ticked

#: A name that encodes a VLAN's id, and the id: ``Vlan10`` /
#: ``vlan10`` (Cisco and generic), and a unit of a VLAN device or of a
#: Junos ``irb`` (OPNsense ``vlan0.10``, Junos ``irb.10``).  A routed
#: sub-interface of a port (``Ethernet1.10``, ``port1.10``) is not one:
#: its VLAN is its tag (``dot1q_vlan``), and on FortiOS its name is free
#: text.
_VLAN_ID_BARE_RE = re.compile(r"^[Vv]lan(\d+)$")
_VLAN_ID_DOTTED_RE = re.compile(r"^(?:[Vv]lan\d*|irb)\.(\d+)$")

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
        not_a_vlan: The refused names, in lower case: no reading of a
            VLAN id from a name may take one of them.
        warnings: One warning of the job for each sub-interface written
            as a VLAN and for each interface refused.
    """

    tree: CanonicalIntent
    review: dict[str, str] = field(default_factory=dict)
    not_a_vlan: frozenset[str] = frozenset()
    warnings: tuple[str, ...] = ()


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


def _decide(tree: CanonicalIntent) -> tuple[list[_Decision], dict[int, list[str]]]:
    """What each sub-interface and each VLAN interface its record names
    stands for; and, for every other interface whose name encodes a
    VLAN id (:func:`vlan_id_of_name`), its name, by that id."""
    records_by_name: dict[str, list[CanonicalVlan]] = {}
    records: dict[int, CanonicalVlan] = {}
    for vlan in ticked(tree.vlans):
        records_by_name.setdefault(vlan.name, []).append(vlan)
        records.setdefault(vlan.id, vlan)
    tags: dict[int, list[str]] = {}
    for iface in ticked(tree.interfaces):
        if iface.dot1q_vlan is not None:
            tags.setdefault(iface.dot1q_vlan, []).append(iface.name)
    decided: list[_Decision] = []
    by_its_name: dict[int, list[str]] = {}
    for index, iface in enumerate(ticked(tree.interfaces)):
        if iface.dot1q_vlan is not None:
            why = _why_not_a_sub_interface(iface, records, tags)
            decided.append((index, iface.dot1q_vlan, why, True))
            continue
        named = records_by_name.get(iface.name, []) if iface.name else []
        if iface.vlan_parent and iface.interface_type == "ianaift:l3ipvlan" and named:
            vid, why = _why_not_a_vlan_interface(iface, named)
            decided.append((index, vid, why, False))
            continue
        encoded = vlan_id_of_name(iface.name)
        if encoded is not None:
            by_its_name.setdefault(encoded, []).append(iface.name)
    return decided, by_its_name


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


def _written(
    tree: CanonicalIntent, renames: dict[str, str],
    written: list[tuple[int, int, str]],
) -> CanonicalIntent:
    """A copy of *tree* with each name of *renames* renamed everywhere,
    and each sub-interface of *written* (index, VLAN id, port) untagged
    and its port tagged in its VLAN's record, made where it has none."""
    out = tree.model_copy(deep=True)
    if renames:
        rewrite_port_names(out, lambda name: renames.get(name, name), units=False)
    of_id: dict[int, CanonicalVlan] = {}
    for vlan in out.vlans:
        of_id.setdefault(vlan.id, vlan)
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
    decided, by_its_name = _decide(tree)
    if not decided:
        return Prepared(tree)
    review: dict[str, str] = {}
    refused: set[str] = set()
    warnings: list[str] = []
    renames: dict[str, str] = {}
    written: list[tuple[int, int, str]] = []
    for index, vid, why, sub in _one_interface_each(tree, decided, by_its_name):
        iface = tree.interfaces[index]
        if why or vid is None:      # (a VLAN interface of no one VLAN has a reason)
            review.setdefault(iface.name, f"; review: interface {iface.name} {why}; not written")
            refused.add(iface.name.lower())
            warnings.append(f"interface {iface.name} {why}; not written")
            continue
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
    if renames or written:
        tree = _written(tree, renames, written)
    return Prepared(tree, review, frozenset(refused), tuple(warnings))
