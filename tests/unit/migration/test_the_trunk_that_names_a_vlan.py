"""Where one port is chosen to carry a VLAN, a trunk that names it comes first.

Three targets have no trunk of their own and hang a VLAN on ONE parent:
OPNsense (the ``<if>`` of a ``<vlan>``), RouterOS (the ``interface=`` of
a VLAN interface) and FortiOS (the ``set interface`` of a VLAN
sub-interface).  Each looks through the source's ports for one that
carries the VLAN, and each read "has an allowed list" as "is a trunk
that carries something".

A trunk that states no allowed list is a trunk of every VLAN on four
platforms, and its list now says so.  Such a trunk is in the list of
every VLAN there is: found first, a vPC peer link is the parent of
each VLAN its switch has, ahead of the port-channel that lists them.
So a trunk that NAMES the VLAN is looked for before a trunk of EVERY
VLAN, on all three.

One IOS-XE config with a trunk of each kind, written in both orders,
onto each target; the OUTPUT is read as text for the parent it gives.

A trunk of every VLAN here states no native VLAN, which on IOS-XE is
native VLAN 1: the port carries VLAN 1 untagged, VLAN 1 has a record
though the config declares none, and each of the three targets
writes a VLAN device for it as for any VLAN -- a TAGGED one, which is
how these targets write every untagged VLAN (a known limitation: the
source sends VLAN 1 without a tag).  Where it is put is read below
like the others'.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree

import pytest

from netcanon.migration.canonical.intent import CanonicalInterface, CanonicalIPv4Address
from netcanon.migration.codecs.fortigate_cli.render import _parent_for_vlan_iface, _scored_parent
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.unit

TARGETS = ("fortigate_cli", "mikrotik_routeros", "opnsense")

NAMES_100 = ("switchport mode trunk", "switchport trunk allowed vlan 100")
EVERY_VLAN = ("switchport mode trunk",)                  # no allowed line: every VLAN on IOS-XE
NO_VLAN = ("switchport mode trunk", "switchport trunk allowed vlan none")


def _iosxe(*ports: tuple[str, tuple[str, ...]]) -> str:
    """VLANs 100 and 999, and the ports given as ``(name, lines)``."""
    out = ["hostname sw1", "!", "vlan 100", " name secure", "!", "vlan 999", " name mgmt", "!"]
    for name, lines in ports:
        out += [f"interface {name}", *(f" {line}" for line in lines), "!"]
    return "\n".join([*out, "end", ""])


def _port(number: int) -> str:
    return f"GigabitEthernet1/0/{number}"


def _member(group: int) -> tuple[str, ...]:
    return (f"channel-group {group} mode active",)


# ---------------------------------------------------------------------------
# The output, read as text: the parent each target gives a VLAN
# ---------------------------------------------------------------------------


def _opnsense_parents(rendered: str) -> dict[int, str]:
    root = ElementTree.fromstring(rendered)
    return {int(vlan.findtext("tag")): vlan.findtext("if") for vlan in root.iter("vlan")}


def _routeros_parents(rendered: str) -> dict[int, str]:
    parents: dict[int, str] = {}
    section = ""
    for line in rendered.splitlines():
        if line.startswith("/"):
            section = line.strip()
        elif section == "/interface vlan" and line.startswith("add "):
            parents[int(re.search(r"\bvlan-id=(\d+)", line).group(1))] = re.search(r"\binterface=(\S+)", line).group(1)
    return parents


def _fortios_parents(rendered: str) -> dict[int, str]:
    parents: dict[int, str] = {}
    for block in re.split(r"^\s*edit ", rendered, flags=re.M)[1:]:
        body = block.split("\n    next", 1)[0]
        vid = re.search(r"^\s*set vlanid (\d+)$", body, re.M)
        parent = re.search(r'^\s*set interface "([^"]+)"$', body, re.M)
        if vid and parent:
            parents[int(vid.group(1))] = parent.group(1)
    return parents


_READ = {"opnsense": _opnsense_parents, "mikrotik_routeros": _routeros_parents, "fortigate_cli": _fortios_parents}


def _has_a_default_trunk(text: str) -> bool:
    """Whether a port of *text* says it is a trunk and states neither
    an allowed list nor a native VLAN: every VLAN, VLAN 1 untagged."""
    for stanza in re.split(r"(?m)^interface ", text)[1:]:
        lines = [line.strip() for line in stanza.splitlines()[1:]]
        if "switchport mode trunk" in lines and not any(line.startswith("switchport trunk ") for line in lines):
            return True
    return False


def _parents(target: str, text: str) -> tuple[dict[int, str], dict[str, str]]:
    """``(VLAN id -> the parent the output gives it, source port name ->
    its name in the output)``.  The VLANs are the two the config
    declares, and VLAN 1 where a trunk of every VLAN carries it
    untagged."""
    job = run_plan_with_overrides(
        get_codec("cisco_iosxe_cli"), get_codec(target), text, port_rename_map={}, force=True,
    )
    assert job.rendered, f"{target}: nothing rendered ({job.status})"
    parents = _READ[target](job.rendered)
    assert set(parents) == ({1, 100, 999} if _has_a_default_trunk(text) else {100, 999}), (target, parents)
    return parents, dict(job.port_renames)


# ---------------------------------------------------------------------------
# A trunk that names the VLAN and a trunk of every VLAN, in both orders
# ---------------------------------------------------------------------------

BOTH_ORDERS = {
    "the trunk that names it, then the trunk of every VLAN": (NAMES_100, EVERY_VLAN),
    "the trunk of every VLAN, then the trunk that names it": (EVERY_VLAN, NAMES_100),
}


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("order", sorted(BOTH_ORDERS))
def test_the_trunk_that_names_it_is_parent(order: str, target: str) -> None:
    first, second = BOTH_ORDERS[order]
    parents, renamed = _parents(target, _iosxe((_port(1), first), (_port(2), second)))
    names_it = renamed[_port(1) if first is NAMES_100 else _port(2)]
    assert parents[100] == names_it, (
        f"{target}, {order}: VLAN 100 is on {parents[100]}; the trunk that names it is {names_it}"
    )


@pytest.mark.parametrize("order", sorted(BOTH_ORDERS))
def test_opnsense_the_rest_ride_every_vlan(order: str) -> None:
    """OPNsense gives each VLAN a parent of its own.  VLAN 999 is named
    by no trunk: the trunk of every VLAN carries it, and is its parent
    -- not the port a default would pick without looking."""
    first, second = BOTH_ORDERS[order]
    parents, renamed = _parents("opnsense", _iosxe((_port(1), first), (_port(2), second)))
    assert parents[999] == renamed[_port(1) if first is EVERY_VLAN else _port(2)], (order, parents)


@pytest.mark.parametrize("order", sorted(BOTH_ORDERS))
def test_opnsense_vlan_one_rides_its_trunk(order: str) -> None:
    """VLAN 1 is carried by the trunk of every VLAN alone, untagged by
    its default, and that trunk is its parent on OPNsense -- not the
    trunk that names VLAN 100, which does not carry it."""
    first, second = BOTH_ORDERS[order]
    parents, renamed = _parents("opnsense", _iosxe((_port(1), first), (_port(2), second)))
    assert parents[1] == renamed[_port(1) if first is EVERY_VLAN else _port(2)], (order, parents)


def test_no_default_trunk_no_vlan_one() -> None:
    """...and it is that trunk which brings VLAN 1: with a native VLAN
    stated, or a list that leaves VLAN 1 out, no target writes it."""
    stated = ("switchport mode trunk", "switchport trunk native vlan 100")
    left_out = ("switchport mode trunk", "switchport trunk allowed vlan 2-4094")
    assert _has_a_default_trunk(_iosxe((_port(1), EVERY_VLAN)))
    for lines in (stated, left_out, NAMES_100, NO_VLAN):
        text = _iosxe((_port(1), lines))
        assert not _has_a_default_trunk(text), lines
        for target in TARGETS:
            parents, _renamed = _parents(target, text)
            assert 1 not in parents, (target, lines)


@pytest.mark.parametrize("order", sorted(BOTH_ORDERS))
def test_the_other_two_have_one_parent(order: str) -> None:
    """RouterOS and FortiOS choose one port for every VLAN they write:
    the trunk that names one."""
    first, second = BOTH_ORDERS[order]
    for target in ("mikrotik_routeros", "fortigate_cli"):
        parents, renamed = _parents(target, _iosxe((_port(1), first), (_port(2), second)))
        names_it = renamed[_port(1) if first is NAMES_100 else _port(2)]
        assert set(parents.values()) == {names_it}, (target, order, parents)


# ---------------------------------------------------------------------------
# OPNsense: a LAG is looked for before a plain port, within each kind
# ---------------------------------------------------------------------------


def test_opnsense_port_names_it_lag_has_all() -> None:
    """A LAG of every VLAN (an uplink that states no list) and a plain
    port that names VLAN 100: the port that names it is the parent of
    100, and the LAG of the VLAN nobody names."""
    parents, renamed = _parents("opnsense", _iosxe(
        ("Port-channel1", EVERY_VLAN), (_port(3), _member(1)), (_port(4), _member(1)), (_port(1), NAMES_100),
    ))
    assert parents[100] == renamed[_port(1)], parents
    assert parents[999] == renamed["Port-channel1"], parents


@pytest.mark.parametrize("names_it", [1, 2])
def test_opnsense_two_lags_and_one_names_it(names_it: int) -> None:
    every = 3 - names_it
    lags = {names_it: NAMES_100, every: EVERY_VLAN}
    parents, renamed = _parents("opnsense", _iosxe(
        ("Port-channel1", lags[1]), ("Port-channel2", lags[2]),
        (_port(1), _member(1)), (_port(2), _member(2)),
    ))
    assert parents[100] == renamed[f"Port-channel{names_it}"], parents
    assert parents[999] == renamed[f"Port-channel{every}"], parents


def test_opnsense_both_name_it_the_lag_wins() -> None:
    """As before the rule: of two trunks that both name the VLAN, the
    LAG is the parent, wherever it stands."""
    parents, renamed = _parents("opnsense", _iosxe(
        (_port(1), NAMES_100), ("Port-channel1", NAMES_100), (_port(3), _member(1)),
    ))
    assert parents[100] == renamed["Port-channel1"], parents


def test_opnsense_no_vlan_is_no_parent() -> None:
    """A trunk that allows no VLAN is the parent of nothing: with one
    beside a trunk that names VLAN 100, VLAN 999 falls to the default
    (the first port), which here is the trunk of no VLAN itself."""
    parents, renamed = _parents("opnsense", _iosxe((_port(1), NO_VLAN), (_port(2), NAMES_100)))
    assert parents[100] == renamed[_port(2)], parents
    assert parents[999] == renamed[_port(1)], parents      # the default: nothing carries 999


# ---------------------------------------------------------------------------
# RouterOS: the single anchor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ports,anchor", [
    # One trunk, of every VLAN, and nothing else: it is the anchor.
    (((1, EVERY_VLAN),), 1),
    # Two of every VLAN: no single anchor.
    (((1, EVERY_VLAN), (2, EVERY_VLAN)), None),
    # One that names a VLAN among trunks of every VLAN: that one.
    (((1, EVERY_VLAN), (2, NAMES_100), (3, EVERY_VLAN)), 2),
    # Two that name a VLAN: no single anchor, with a trunk of every VLAN or without.
    (((1, NAMES_100), (2, NAMES_100), (3, EVERY_VLAN)), None),
    (((1, NAMES_100), (2, NAMES_100)), None),
    # A trunk of no VLAN is no candidate.
    (((1, NO_VLAN), (2, EVERY_VLAN)), 2),
])
def test_routeros_the_single_anchor(ports: tuple[tuple[int, tuple[str, ...]], ...], anchor: int | None) -> None:
    parents, renamed = _parents("mikrotik_routeros", _iosxe(*((_port(number), lines) for number, lines in ports)))
    expected = "bridge1" if anchor is None else renamed[_port(anchor)]
    assert set(parents.values()) == {expected}, (ports, parents)


def test_routeros_a_routed_port_still_counts() -> None:
    """A port with an address counts beside the trunks, as it did: one
    of those and a trunk of every VLAN are two candidates, and with a
    trunk that names a VLAN there are two as well."""
    routed = ("no switchport", "ip address 192.0.2.1 255.255.255.0")
    for trunk in (EVERY_VLAN, NAMES_100):
        parents, _renamed = _parents("mikrotik_routeros", _iosxe((_port(1), routed), (_port(2), trunk)))
        assert set(parents.values()) == {"bridge1"}, (trunk, parents)


def test_routeros_a_port_that_is_both_counts() -> None:
    """A port can have an address AND be a trunk of every VLAN.  Its
    address makes it a candidate, as a routed port always was: it is
    not set aside with the trunks of every VLAN that have none."""
    both = ("switchport mode trunk", "ip address 192.0.2.1 255.255.255.0")
    # By itself it is the anchor.
    parents, renamed = _parents("mikrotik_routeros", _iosxe((_port(1), both)))
    assert set(parents.values()) == {renamed[_port(1)]}, parents
    # Beside a trunk that names a VLAN there are two candidates: no
    # single anchor.  (Set aside, it would leave the other trunk as
    # the one candidate.)
    for order in (((_port(1), both), (_port(2), NAMES_100)), ((_port(1), NAMES_100), (_port(2), both))):
        parents, _renamed = _parents("mikrotik_routeros", _iosxe(*order))
        assert set(parents.values()) == {"bridge1"}, (order, parents)


# ---------------------------------------------------------------------------
# FortiOS: the scorer
# ---------------------------------------------------------------------------


def test_fortios_port_index_within_a_kind() -> None:
    """Two trunks of every VLAN tie, and the higher port index is the
    parent, as it was for any two trunks."""
    parents, renamed = _parents("fortigate_cli", _iosxe((_port(1), EVERY_VLAN), (_port(2), EVERY_VLAN)))
    assert set(parents.values()) == {renamed[_port(2)]}, parents
    parents, renamed = _parents("fortigate_cli", _iosxe((_port(1), NAMES_100), (_port(2), NAMES_100)))
    assert set(parents.values()) == {renamed[_port(2)]}, parents


def test_fortios_a_private_address_is_first() -> None:
    """The signal comes first: a port with a private address is the
    parent ahead of a trunk of either kind."""
    lan = ("no switchport", "ip address 192.168.1.1 255.255.255.0")
    for trunk in (EVERY_VLAN, NAMES_100):
        parents, renamed = _parents("fortigate_cli", _iosxe((_port(1), lan), (_port(2), trunk)))
        assert set(parents.values()) == {renamed[_port(1)]}, (trunk, parents)


def test_fortios_every_vlan_is_still_a_trunk() -> None:
    """The kind of trunk only breaks a tie.  Beside a port that has no
    signal at all -- a routed port with a public address -- a trunk
    of every VLAN is the parent, as a trunk that names one is."""
    routed = ("no switchport", "ip address 198.51.100.1 255.255.255.0")
    for trunk in (EVERY_VLAN, NAMES_100):
        parents, renamed = _parents("fortigate_cli", _iosxe((_port(1), routed), (_port(2), trunk)))
        assert set(parents.values()) == {renamed[_port(2)]}, (trunk, parents)


def _fortios_port(name: str, *, address: str = "", allowed: list[int] | None = None) -> CanonicalInterface:
    return CanonicalInterface(
        name=name, interface_type="ianaift:ethernetCsmacd",
        ipv4_addresses=[CanonicalIPv4Address(ip=address, prefix_length=24)] if address else [],
        switchport_mode="trunk" if allowed else None, trunk_allowed_vlans=allowed or [],
    )


_EVERY = list(range(1, 4095))


@pytest.mark.parametrize("flip", [False, True])
def test_fortios_scorer_puts_signal_first(flip: bool) -> None:
    """The scorer by itself, on ports built by hand.  A port with a
    private address that is ALSO a trunk of every VLAN has the most
    signal there is, and is the parent ahead of a trunk that names
    its VLANs: the kind of trunk only breaks a tie."""
    lan = _fortios_port("port1", address="192.168.1.1", allowed=list(_EVERY))
    names = _fortios_port("port2", allowed=[100])
    ports = [names, lan] if flip else [lan, names]
    assert _scored_parent(ports) == "port1"
    # And at a tie on signal the trunk that names its VLANs is first,
    # whichever has the higher port index.
    every = _fortios_port("port9", allowed=list(_EVERY))
    ports = [names, every] if flip else [every, names]
    assert _scored_parent(ports) == "port2"


def test_fortios_scored_once_is_the_same() -> None:
    """A render asks the scorer once and hands its answer to every
    VLAN sub-interface.  Handed over or asked for there, the parent
    is the same -- and with no port that has any signal, it is the
    first port that is no VLAN, as it was."""
    wan = _fortios_port("port1", address="198.51.100.1")
    trunk = _fortios_port("port2", allowed=[100])
    bare = _fortios_port("port3")
    for ports in ([wan, trunk], [trunk, wan], [wan, bare], [bare, wan], []):
        scored = _scored_parent(ports)
        for name in ("vlan100", "VL_USERS", "port2.100", "port7.100"):
            assert _parent_for_vlan_iface(name, ports, scored) == _parent_for_vlan_iface(name, ports), (name, ports)
    assert _scored_parent([wan, trunk]) == "port2"
    assert _scored_parent([wan, bare]) is None
    assert _parent_for_vlan_iface("vlan100", [wan, bare], None) == "port1"
    assert _parent_for_vlan_iface("vlan100", [wan, trunk], "port2") == "port2"
    # A dotted name is its own parent's, whatever the scorer says.
    assert _parent_for_vlan_iface("port1.100", [wan, trunk], "port2") == "port1"


# ---------------------------------------------------------------------------
# The readers, handed an output each
# ---------------------------------------------------------------------------


def test_the_readers_find_the_parent() -> None:
    assert _opnsense_parents(
        "<opnsense><vlans><vlan><if>lagg0</if><tag>100</tag></vlan>"
        "<vlan><if>igb1</if><tag>999</tag></vlan></vlans></opnsense>"
    ) == {100: "lagg0", 999: "igb1"}
    assert _routeros_parents(
        "/interface bridge\nadd name=bridge1\n/interface vlan\n"
        'add comment="a b" interface=bridge1 name=vlan100 vlan-id=100\n'
        "add interface=ether2 name=vlan999 vlan-id=999\n/ip address\nadd interface=vlan100 address=192.0.2.1/24\n"
    ) == {100: "bridge1", 999: "ether2"}
    assert _fortios_parents(
        'config system interface\n    edit "port1"\n        set vdom "root"\n    next\n'
        '    edit "vlan100"\n        set type vlan\n        set vlanid 100\n        set interface "port2"\n    next\n'
        "end\n"
    ) == {100: "port2"}
