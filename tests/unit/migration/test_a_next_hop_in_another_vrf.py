"""A route whose next hop is in another VRF is not a route of its own.

A canonical route has one VRF.  Four Cisco-shaped grammars name a
second one, the VRF the next hop is looked up in:

* IOS-XE ``global`` after a VRF route's next hop -- "the next hop
  address is global" (Cisco, IOS IP Routing command reference,
  ``ip route vrf``); the IPv6 command reference writes it on an
  ``ipv6 route`` in its own example -- and the IPv6 route's
  ``nexthop-vrf [<name> | default]``;
* NX-OS ``vrf <name>`` after the next hop, "the VRF for the next hop,
  if it is different from the present VRF" (Nexus 9000 "Configuring
  Static Routing");
* EOS ``egress-vrf <name>`` after the destination (Arista, "Static
  Inter-VRF Route");
* IOS XR ``<prefix> vrf <name> <next hop>`` in ``router static``
  (``test_a_word_is_not_a_name.py``).

Read past, or the keyword read as an interface, each was a route of
its own VRF on every target, its next hop looked up where it is not,
in a job that said nothing.  It is left out, and one section row a
parser says how many (``next_hop_elsewhere_rows``).  A next hop's
VRF that is the route's own is read past, and the route is read.

Each is read here from the parse, and from the OUTPUT of the plan
path the API uses onto every public codec.
"""

from __future__ import annotations

import functools

import pytest

from netcanon.migration._tier3_detection import is_left_out_row
from netcanon.migration.codecs._helpers import next_hop_elsewhere_rows
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

_XE_FORM = "ip route vrf <name> ... <next hop> global, ipv6 route ... nexthop-vrf <name>"
_NX_FORM = "ip route <prefix> <next hop> vrf <name>"
_EOS_FORM = "ip route [vrf <name>] <prefix> egress-vrf <name> <next hop>"

_XE_HEAD = (
    "hostname r1\nvrf definition A\n!\n"
    "interface GigabitEthernet1\n ip address 192.0.2.1 255.255.255.0\n!\n"
)
_NX_HEAD = (
    "hostname n1\nvrf context A\n"
    "interface Ethernet1/1\n  no switchport\n  ip address 192.0.2.1/24\n"
)
_EOS_HEAD = (
    "hostname a1\nvrf instance A\n!\n"
    "interface Ethernet1\n   no switchport\n   ip address 192.0.2.1/24\n!\n"
)


def _xe(*lines: str) -> str:
    return _XE_HEAD + "\n".join(lines) + "\n!\nend\n"


def _nx(*lines: str) -> str:
    return _NX_HEAD + "\n".join(lines) + "\n"


def _eos(*lines: str) -> str:
    return _EOS_HEAD + "\n".join(lines) + "\n!\nend\n"


_BUILD = {"cisco_iosxe_cli": _xe, "cisco_nxos": _nx, "arista_eos": _eos}
_FORM = {"cisco_iosxe_cli": _XE_FORM, "cisco_nxos": _NX_FORM, "arista_eos": _EOS_FORM}


def _read(codec: str, *lines: str):
    """(vrf, destination, gateway, interface, distance) of each route
    the parser keeps, and its rows."""
    tree = get_codec(codec).parse(_BUILD[codec](*lines))
    routes = sorted(
        (r.vrf, r.destination, r.gateway, r.interface, r.metric) for r in tree.static_routes
    )
    return routes, tree.dropped_tier3_sections


def _row(codec: str, count: int) -> str:
    return next_hop_elsewhere_rows("ip route", count, _FORM[codec])[0]


#: Lines whose next hop is in another VRF: (codec, line).
_ELSEWHERE = [
    ("cisco_iosxe_cli", "ip route vrf A 10.9.0.0 255.255.0.0 192.0.2.254 global"),
    ("cisco_iosxe_cli", "ip route vrf A 10.9.0.0 255.255.0.0 GigabitEthernet1 192.0.2.254 global 20"),
    ("cisco_iosxe_cli", "ip route vrf A 0.0.0.0 0.0.0.0 192.0.2.254 global name INTERNET"),
    ("cisco_iosxe_cli", "ipv6 route vrf A ::/0 2001:db8::1 global"),
    ("cisco_iosxe_cli", "ipv6 route vrf A 2001:db8:9::/48 2001:db8::1 nexthop-vrf default"),
    ("cisco_iosxe_cli", "ipv6 route vrf A 2001:db8:9::/48 2001:db8::1 nexthop-vrf B 20"),
    ("cisco_iosxe_cli", "ipv6 route 2001:db8:9::/48 2001:db8::1 nexthop-vrf A"),
    # ``nexthop-vrf`` with no name says a VRF and not which.
    ("cisco_iosxe_cli", "ipv6 route vrf A 2001:db8:9::/48 2001:db8::1 nexthop-vrf"),
    ("cisco_nxos", "ip route 10.9.0.0/16 192.0.2.254 vrf A"),
    ("cisco_nxos", "ip route 10.9.0.0/16 Ethernet1/1 192.0.2.254 vrf A 20"),
    ("cisco_nxos", "ip route 10.9.0.0/16 192.0.2.254 name WAN tag 7 vrf A"),
    ("cisco_nxos", "ipv6 route 2001:db8:9::/48 2001:db8::1 vrf A"),
    ("cisco_nxos", "vrf context A\n  ip route 10.9.0.0/16 192.0.2.254 vrf default"),
    ("cisco_nxos", "vrf context A\n  ipv6 route 2001:db8:9::/48 2001:db8::1 vrf B 20"),
    ("arista_eos", "ip route vrf A 10.9.0.0/16 egress-vrf default 192.0.2.254"),
    ("arista_eos", "ip route 10.9.0.0/16 egress-vrf A 192.0.2.254 20"),
    ("arista_eos", "ip route 10.9.0.0/16 egress-vrf A Ethernet1 192.0.2.254"),
    ("arista_eos", "ipv6 route vrf A 2001:db8:9::/48 egress-vrf default 2001:db8::1"),
]

#: Lines whose next hop's VRF is the route's own, or that name no
#: other: (codec, line, the route read).
_OWN = [
    ("cisco_iosxe_cli", "ip route 10.9.0.0 255.255.0.0 192.0.2.254 global 30",
     ("", "10.9.0.0/16", "192.0.2.254", "", 30)),
    ("cisco_iosxe_cli", "ip route vrf A 10.9.0.0 255.255.0.0 192.0.2.254 name global",
     ("A", "10.9.0.0/16", "192.0.2.254", "", 0)),
    ("cisco_iosxe_cli", "ipv6 route vrf A 2001:db8:9::/48 2001:db8::1 nexthop-vrf A 40",
     ("A", "2001:db8:9::/48", "2001:db8::1", "", 40)),
    ("cisco_iosxe_cli", "ipv6 route 2001:db8:9::/48 2001:db8::1 nexthop-vrf default 50",
     ("", "2001:db8:9::/48", "2001:db8::1", "", 50)),
    # A distance after the next hop's VRF is the route's.
    ("cisco_nxos", "ip route 10.9.0.0/16 192.0.2.254 vrf default 30",
     ("", "10.9.0.0/16", "192.0.2.254", "", 30)),
    ("cisco_nxos", "ip route 10.9.0.0/16 Ethernet1/1 192.0.2.254 vrf default 35",
     ("", "10.9.0.0/16", "192.0.2.254", "Ethernet1/1", 35)),
    ("cisco_nxos", "vrf context A\n  ip route 10.9.0.0/16 192.0.2.254 vrf A 20",
     ("A", "10.9.0.0/16", "192.0.2.254", "", 20)),
    ("arista_eos", "ip route vrf A 10.9.0.0/16 egress-vrf A 192.0.2.254 30",
     ("A", "10.9.0.0/16", "192.0.2.254", "", 30)),
    ("arista_eos", "ip route 10.9.0.0/16 egress-vrf default Ethernet1 192.0.2.254 40",
     ("", "10.9.0.0/16", "192.0.2.254", "Ethernet1", 40)),
    ("arista_eos", "ip route 10.9.0.0/16 192.0.2.254 50",
     ("", "10.9.0.0/16", "192.0.2.254", "", 50)),
]


class TestTheParse:
    @pytest.mark.parametrize(("codec", "line"), _ELSEWHERE)
    def test_it_is_left_out_and_counted(self, codec: str, line: str) -> None:
        routes, rows = _read(codec, line)
        assert routes == []
        assert rows == [_row(codec, 1)]

    @pytest.mark.parametrize(("codec", "line", "read"), _OWN)
    def test_its_own_vrf_is_read(self, codec: str, line: str, read: tuple) -> None:
        routes, rows = _read(codec, line)
        assert routes == [read]
        assert rows == []

    @pytest.mark.parametrize("codec", sorted(_BUILD))
    def test_one_row_counts_them_all(self, codec: str) -> None:
        lines = [line for c, line in _ELSEWHERE if c == codec]
        kept = [line for c, line, _ in _OWN if c == codec]
        routes, rows = _read(codec, *lines, *kept)
        assert len(routes) == len(kept)
        assert rows == [_row(codec, len(lines))]

    def test_the_row_is_a_section(self) -> None:
        """The route is in force on the source: its row is not one of
        a statement left out."""
        assert not is_left_out_row(_row("cisco_nxos", 2))

    def test_no_row_for_none(self) -> None:
        assert next_hop_elsewhere_rows("ip route", 0, _NX_FORM) == []


@functools.cache
def _job(source: str, text: str, target: str) -> MigrationJob:
    """*text* onto *target*, as the plan endpoints run it."""
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )
    assert job.rendered, f"{source} -> {target}: {job.error}"
    return job


#: For each source, a route of another VRF's next hop to
#: 198.51.100.0/24 and a route of its own to 203.0.113.0/24.
_PAIRS = {
    "cisco_iosxe_cli": _xe(
        "ip route vrf A 198.51.100.0 255.255.255.0 192.0.2.254 global",
        "ip route vrf A 203.0.113.0 255.255.255.0 192.0.2.254",
    ),
    "cisco_nxos": _nx(
        "ip route 198.51.100.0/24 192.0.2.254 vrf A",
        "ip route 203.0.113.0/24 192.0.2.254",
    ),
    "arista_eos": _eos(
        "ip route vrf A 198.51.100.0/24 egress-vrf default 192.0.2.254",
        "ip route vrf A 203.0.113.0/24 192.0.2.254",
    ),
}


class TestTheOutput:
    @pytest.mark.parametrize("target", PUBLIC)
    @pytest.mark.parametrize("source", sorted(_PAIRS))
    def test_no_output_has_it(self, source: str, target: str) -> None:
        job = _job(source, _PAIRS[source], target)
        assert "198.51.100.0" not in job.rendered, target
        assert _row(source, 1) in job.dropped_tier3_sections, target

    @pytest.mark.parametrize("source", sorted(_PAIRS))
    def test_the_route_of_its_own_is_written(self, source: str) -> None:
        """Onto its own codec, the other route is in the output."""
        assert "203.0.113.0" in _job(source, _PAIRS[source], source).rendered
