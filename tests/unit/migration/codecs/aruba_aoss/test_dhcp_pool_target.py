"""Aruba AOS-S as a DHCP target: the switch's own server is written,
and its parser reads it back.

The renderer used to write a comment for each pool of the tree, and the
capability matrix declared pools unsupported.  An AOS-S switch has a
DHCPv4 server of its own (HPE, ArubaOS-Switch Management and
Configuration Guide, "DHCPv4 server"; HPE's DHCP white paper), so a
pool is now written as the switch prints one (a committed capture of a
2930F), in ``codecs/aruba_aoss/dhcp_pools.py``:

* ``dhcp-server pool "<name>"``, then ``default-router``,
  ``dns-server``, ``domain-name``, ``lease [DD:HH:MM | infinite]``,
  ``network <address> <mask>`` and ``range`` lines, and ``exit``; the
  default lease of one day is not written, as the switch prints none;
* the pools after every VLAN, and ``dhcp-server enable`` after the
  last (the server "Defaults to disabled", and the switch refuses to
  change a pool while it is enabled);
* ``dhcp-server`` in the stanza of the VLAN the pool is served on,
  where that stanza holds an address of the pool's network -- which is
  what the parser reads a pool's interface from.

What AOS-S cannot be given as the tree has it is a ``; review:`` line,
and the job has a warning for each.  Every test here reads the output
back with the AOS-S parser, and counts the warnings against the review
lines.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalVlan,
)
from netcanon.migration.codecs._dhcp_pools import INFINITE_LEASE
from netcanon.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

CODEC = ArubaAOSSCodec()

CAPTURE = (
    Path(__file__).resolve().parents[4]
    / "fixtures" / "real" / "aruba_aoss" / "hpe_community_2930f_wc1610_dhcp_server.cfg"
)


def _a4(ip: str, plen: int = 24) -> CanonicalIPv4Address:
    return CanonicalIPv4Address(ip=ip, prefix_length=plen)


def _vlans() -> list[CanonicalVlan]:
    """VLAN 10 holds 10.1.10.1/24; VLAN 20 holds no address."""
    return [
        CanonicalVlan(id=10, name="USERS", ipv4_addresses=[_a4("10.1.10.1")]),
        CanonicalVlan(id=20, name="VOICE"),
    ]


def _pool(**fields: object) -> CanonicalDHCPPool:
    stated: dict[str, object] = {
        "interface": "Vlan10", "network": "10.1.10.0/24",
        "start_ip": "10.1.10.100", "end_ip": "10.1.10.200",
    }
    stated.update(fields)
    return CanonicalDHCPPool(**stated)


def _tree(
    *pools: CanonicalDHCPPool,
    vlans: list[CanonicalVlan] | None = None,
    interfaces: list[CanonicalInterface] | None = None,
) -> CanonicalIntent:
    return CanonicalIntent(
        source_vendor="test", source_format="test", hostname="sw1",
        vlans=_vlans() if vlans is None else vlans,
        interfaces=interfaces or [], dhcp_servers=list(pools),
    )


class _Out:
    """The AOS-S output for a tree: its lines, the job's DHCP warnings,
    and the pools the AOS-S parser reads back."""

    def __init__(self, tree: CanonicalIntent) -> None:
        self.text = CODEC.render(tree)
        self.lines = self.text.splitlines()
        self.warnings = [w for w in CODEC.render_warnings(tree) if "DHCP pool" in w]
        self.pools = CODEC.parse(self.text).dhcp_servers

    @property
    def reviews(self) -> list[str]:
        return [line for line in self.lines if "review:" in line and "pool" in line]

    def stanza(self, header: str) -> list[str]:
        """The lines of the stanza that opens with *header*, its
        ``exit`` included."""
        start = self.lines.index(header)
        end = self.lines.index("   exit", start)
        return self.lines[start:end + 1]

    def told(self) -> None:
        """Each review line has its warning, and each warning its line."""
        assert len(self.warnings) == len(self.reviews), (self.warnings, self.reviews)


def _fields(pool: CanonicalDHCPPool) -> tuple:
    return (
        pool.interface, pool.network, pool.start_ip, pool.end_ip, pool.gateway,
        list(pool.dns_servers), pool.lease_time, pool.domain_name,
    )


# ---------------------------------------------------------------------------
# (a) A pool on a VLAN, written and read back
# ---------------------------------------------------------------------------


_WHOLE = _pool(
    gateway="10.1.10.1", dns_servers=["10.0.0.53", "10.0.0.54"],
    lease_time=43200, domain_name="example.test",
)


def test_a_pool_on_a_vlan_reads_back_whole() -> None:
    out = _Out(_tree(_WHOLE))
    assert [_fields(p) for p in out.pools] == [_fields(_WHOLE)]
    assert out.reviews == [] and out.warnings == []


def test_the_vlan_that_serves_it_states_dhcp_server() -> None:
    out = _Out(_tree(_WHOLE))
    assert "   dhcp-server" in out.stanza("vlan 10")
    assert "   dhcp-server" not in out.stanza("vlan 20")


def test_the_pool_is_written_as_the_switch_prints_one() -> None:
    out = _Out(_tree(_WHOLE))
    assert out.stanza('dhcp-server pool "pool-1"') == [
        'dhcp-server pool "pool-1"',
        '   default-router "10.1.10.1"',
        '   dns-server "10.0.0.53,10.0.0.54"',
        '   domain-name "example.test"',
        "   lease 00:12:00",
        "   network 10.1.10.0 255.255.255.0",
        "   range 10.1.10.100 10.1.10.200",
        "   exit",
    ]


def test_the_server_is_enabled_after_the_last_pool_and_every_vlan() -> None:
    out = _Out(_tree(_WHOLE, _pool(network="10.1.20.0/24", interface="", start_ip="10.1.20.5",
                                   end_ip="10.1.20.9")))
    pools = [i for i, line in enumerate(out.lines) if line.startswith("dhcp-server pool ")]
    vlans = [i for i, line in enumerate(out.lines) if line.startswith("vlan ")]
    assert len(pools) == 2 and min(pools) > max(vlans)
    assert out.lines[-1] == "dhcp-server enable"
    assert out.lines.count("dhcp-server enable") == 1


def test_pools_are_named_by_their_place_in_the_tree() -> None:
    out = _Out(_tree(_WHOLE, _pool(start_ip="10.1.10.210", end_ip="10.1.10.220")))
    assert [line for line in out.lines if line.startswith("dhcp-server pool ")] == [
        'dhcp-server pool "pool-1"', 'dhcp-server pool "pool-2"',
    ]
    assert len(out.pools) == 2


def test_no_pool_no_server() -> None:
    assert "dhcp-server" not in _Out(_tree()).text


def test_the_committed_capture_comes_back_through_its_own_output() -> None:
    tree = CODEC.parse(CAPTURE.read_text(encoding="utf-8"))
    assert len(tree.dhcp_servers) == 3
    out = _Out(tree)
    assert [_fields(p) for p in out.pools] == [_fields(p) for p in tree.dhcp_servers]
    assert out.reviews == [] and out.warnings == []


# ---------------------------------------------------------------------------
# (b) The lease
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lease_time", "line", "reviewed", "read_back"),
    [
        (86400, None, False, 86400),
        (43200, "   lease 00:12:00", False, 43200),
        (7 * 86400 + 5 * 3600 + 7 * 60, "   lease 07:05:07", False, 7 * 86400 + 5 * 3600 + 7 * 60),
        (99 * 86400, "   lease 99:00:00", False, 99 * 86400),
        (INFINITE_LEASE, "   lease infinite", False, INFINITE_LEASE),
        # In minutes, and never 00:00:00.
        (90, "   lease 00:00:01", True, 60),
        (30, "   lease 00:00:01", True, 60),
        (3600 + 59, "   lease 00:01:00", True, 3600),
        # Not a lease HPE's DD:HH:MM states: the default of one day.
        (100 * 86400, None, True, 86400),
        (-5, None, True, 86400),
    ],
)
def test_the_lease(lease_time: int, line: str | None, reviewed: bool, read_back: int) -> None:
    out = _Out(_tree(_pool(lease_time=lease_time)))
    leases = [x for x in out.stanza('dhcp-server pool "pool-1"') if x.startswith("   lease")]
    assert leases == ([line] if line else [])
    assert bool(out.reviews) is reviewed
    out.told()
    assert [p.lease_time for p in out.pools] == [read_back]


# ---------------------------------------------------------------------------
# (c) A pool the switch would discard is not written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pool", "why"),
    [
        (_pool(network=""), "it states no IPv4 network"),
        (_pool(network="2001:db8::/64"), "it states no IPv4 network"),
        (_pool(start_ip="10.2.10.100", end_ip="10.2.10.200"), "its range is not a run of addresses"),
        (_pool(start_ip="10.1.10.200", end_ip="10.1.10.100"), "its range is not a run of addresses"),
    ],
    ids=["no network", "an IPv6 network", "a range outside", "a range turned round"],
)
def test_a_pool_the_switch_discards_is_said_and_not_written(pool: CanonicalDHCPPool, why: str) -> None:
    out = _Out(_tree(pool))
    assert not [line for line in out.lines if line.startswith("dhcp-server")]
    assert "   dhcp-server" not in out.stanza("vlan 10")
    assert len(out.reviews) == 1 and out.reviews[0].startswith("; review: ") and why in out.reviews[0]
    out.told()
    assert out.pools == []


# ---------------------------------------------------------------------------
# (d) A pool that states no whole range is written what it hands out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stated", "own", "ranges"),
    [
        ({"start_ip": "", "end_ip": ""}, [], ["   range 10.1.10.2 10.1.10.254"]),
        ({"end_ip": ""}, [], ["   range 10.1.10.100 10.1.10.254"]),
        ({"start_ip": "", "end_ip": ""}, ["10.1.10.50"],
         ["   range 10.1.10.2 10.1.10.49", "   range 10.1.10.51 10.1.10.254"]),
    ],
    ids=["no range", "one end", "around an address of the output"],
)
def test_a_pool_with_no_whole_range(stated: dict, own: list[str], ranges: list[str]) -> None:
    interfaces = [CanonicalInterface(name="Loopback0", ipv4_addresses=[_a4(ip, 32)]) for ip in own]
    out = _Out(_tree(_pool(**stated), interfaces=interfaces))
    stanza = out.stanza('dhcp-server pool "pool-1"')
    assert [line for line in stanza if line.startswith("   range ")] == ranges
    assert len(out.reviews) == 1 and out.reviews[0] in stanza
    out.told()
    (pool,) = out.pools
    assert (pool.start_ip, pool.end_ip) == tuple(ranges[0].split()[1:])
    assert pool.interface == "Vlan10"


# ---------------------------------------------------------------------------
# (e) The VLAN that serves a pool
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pool", "why"),
    [
        (_pool(interface="port2"), "this output has no VLAN stanza for port2"),
        (_pool(interface="Vlan20", network="10.1.20.0/24", start_ip="10.1.20.5", end_ip="10.1.20.9"),
         "VLAN 20 holds no address whose subnet is 10.1.20.0/24"),
        (_pool(network="10.1.99.0/24", start_ip="10.1.99.5", end_ip="10.1.99.9"),
         "VLAN 10 holds no address whose subnet is 10.1.99.0/24"),
    ],
    ids=["not a VLAN", "a VLAN with no address", "a VLAN of another subnet"],
)
def test_a_pool_no_vlan_of_the_output_serves(pool: CanonicalDHCPPool, why: str) -> None:
    out = _Out(_tree(pool))
    assert not [line for line in out.lines if line == "   dhcp-server"]
    stanza = out.stanza('dhcp-server pool "pool-1"')
    assert len(out.reviews) == 1 and out.reviews[0] in stanza and why in out.reviews[0]
    assert "relay" in out.reviews[0]
    out.told()
    assert [p.interface for p in out.pools] == [""]
    assert [p.network for p in out.pools] == [pool.network]


def test_a_pool_the_source_serves_on_no_interface_is_not_reviewed() -> None:
    out = _Out(_tree(_pool(interface="")))
    assert out.reviews == [] and out.warnings == []
    assert not [line for line in out.lines if line == "   dhcp-server"]
    assert [p.interface for p in out.pools] == [""]


@pytest.mark.parametrize("name", ["Vlan30", "vlan30"])
def test_a_vlan_whose_address_is_its_interfaces_serves(name: str) -> None:
    vlans = [CanonicalVlan(id=30, name="GUEST")]
    svi = CanonicalInterface(name=name, ipv4_addresses=[_a4("10.1.30.1")])
    out = _Out(_tree(
        _pool(interface=name, network="10.1.30.0/24", start_ip="10.1.30.5", end_ip="10.1.30.9"),
        vlans=vlans, interfaces=[svi],
    ))
    assert "   dhcp-server" in out.stanza("vlan 30")
    assert out.reviews == [] and out.warnings == []
    assert [p.interface for p in out.pools] == ["Vlan30"]


@pytest.mark.parametrize("name", ["irb.10", "vlan.10"])
def test_a_pool_on_a_name_that_encodes_the_vlan_is_the_vlans(name: str) -> None:
    """The Junos parser puts the address of ``irb.10`` on VLAN 10 itself,
    and keeps ``irb.10`` as the pool's interface: the VLAN's stanza
    serves it, as it writes that interface's address."""
    out = _Out(_tree(_pool(interface=name)))
    assert "   dhcp-server" in out.stanza("vlan 10")
    assert out.reviews == [] and out.warnings == []
    assert [p.interface for p in out.pools] == ["Vlan10"]


def test_a_name_that_encodes_another_vlan_is_that_vlans() -> None:
    """The name finds the VLAN; its subnets still decide."""
    out = _Out(_tree(_pool(interface="irb.20")))
    assert not [line for line in out.lines if line == "   dhcp-server"]
    assert len(out.reviews) == 1
    assert "VLAN 20 holds no address whose subnet is 10.1.10.0/24" in out.reviews[0]
    out.told()


_JUNOS_IRB = """set system host-name r1
set vlans USERS vlan-id 10
set vlans USERS l3-interface irb.10
set interfaces irb unit 10 family inet address 10.1.10.1/24
set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members USERS
set access address-assignment pool P family inet network 10.1.10.0/24
set access address-assignment pool P family inet range r1 low 10.1.10.100
set access address-assignment pool P family inet range r1 high 10.1.10.200
set access address-assignment pool P family inet dhcp-attributes router 10.1.10.1
set system services dhcp-local-server group P interface irb.10
"""


def test_a_junos_pool_on_an_irb_is_served_on_its_vlan() -> None:
    job = run_plan_with_checked_names(get_codec("juniper_junos"), CODEC, _JUNOS_IRB)
    assert job.rendered is not None
    lines = job.rendered.splitlines()
    vlan = lines[lines.index("vlan 10"):lines.index("   exit", lines.index("vlan 10"))]
    assert "   dhcp-server" in vlan
    assert not [line for line in lines if "review:" in line and "pool" in line]
    (pool,) = CODEC.parse(job.rendered).dhcp_servers
    assert (pool.interface, pool.network, pool.start_ip, pool.end_ip, pool.gateway) == (
        "Vlan10", "10.1.10.0/24", "10.1.10.100", "10.1.10.200", "10.1.10.1",
    )


# ---------------------------------------------------------------------------
# (f) What a pool hands its clients
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "why", "read_back"),
    [
        ({"gateway": "2001:db8::1"}, "the gateway of this pool is not written", ("", [], "")),
        ({"dns_servers": ["10.0.0.53", "2001:db8::53"]}, "not an IPv4 address is not written",
         ("", ["10.0.0.53"], "")),
        ({"dns_servers": [f"10.0.0.{n}" for n in range(1, 11)]}, "after the first 8",
         ("", [f"10.0.0.{n}" for n in range(1, 9)], "")),
        ({"domain_name": 'a"b.test'}, "the domain of this pool is not written", ("", [], "")),
        ({"domain_name": "a\tb.test"}, "the domain of this pool is not written", ("", [], "")),
    ],
    ids=["an IPv6 gateway", "an IPv6 DNS server", "ten DNS servers", "a quote", "a tab"],
)
def test_what_a_pool_cannot_be_given(fields: dict, why: str, read_back: tuple) -> None:
    out = _Out(_tree(_pool(**fields)))
    assert len(out.reviews) == 1 and why in out.reviews[0]
    out.told()
    (pool,) = out.pools
    assert (pool.gateway, list(pool.dns_servers), pool.domain_name) == read_back


# ---------------------------------------------------------------------------
# (g) Every source that writes a pool, onto AOS-S
# ---------------------------------------------------------------------------


#: The public codecs whose own output, parsed again, holds a pool: each
#: is a source a pool reaches AOS-S from here.  Compared for equality
#: with what is measured, so a codec that starts writing pools fails
#: until it is added.
WRITES_A_POOL = {
    "arista_eos", "aruba_aoss", "cisco_iosxe_cli", "fortigate_cli", "juniper_junos",
    "mikrotik_routeros", "opnsense",
}


def _source_tree() -> CanonicalIntent:
    return _tree(
        _WHOLE,
        vlans=[CanonicalVlan(id=10, name="USERS")],
        interfaces=[CanonicalInterface(name="Vlan10", ipv4_addresses=[_a4("10.1.10.1")])],
    )


def test_every_source_that_writes_a_pool_reaches_aoss_whole() -> None:
    reached: set[str] = set()
    aoss = get_codec("aruba_aoss")
    for name in sorted(list_public_codecs()):
        source = get_codec(name)
        text = source.render(_source_tree())
        if not source.parse(text).dhcp_servers:
            continue
        reached.add(name)
        job = run_plan_with_checked_names(source, aoss, text)
        assert job.rendered is not None, name
        pools = aoss.parse(job.rendered).dhcp_servers
        assert [_fields(p) for p in pools] == [_fields(_WHOLE)], name
        assert "   dhcp-server" in job.rendered.splitlines(), name
    assert reached == WRITES_A_POOL
