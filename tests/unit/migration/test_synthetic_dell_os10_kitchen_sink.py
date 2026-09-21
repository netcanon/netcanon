"""
Synthetic kitchen-sink coverage test for the dell_os10 codec.

``dell_os10`` is the one codec with NO committed real-capture corpus —
its 14 validation captures carry live password hashes and are held
out-of-tree — so this fixture is the only in-tree config that exercises
the codec's grammar end to end.  That makes these assertions load-
bearing in a way the other vendors' kitchen sinks are not: if the
fixture silently loses a surface, nothing else in the repository
notices.

Three tests, mirroring the arista_eos / juniper_junos modules:

1. :func:`test_parses_without_exceptions` — sanity.
2. :func:`test_populates_every_expected_canonical_field` — one
   assertion per canonical surface the matrix declares ``supported``
   or ``lossy``.
3. :func:`test_round_trip_stable` — parse → render → parse is
   canonical-stable.

Plus four guards for the OS10-specific traps that would otherwise be
silent defects, each measured against the real capture corpus during
Phase 1-3 and documented in ``docs/vendor-research/dell_os10/``:

* ``interface breakout … map`` is NOT a port declaration.
* ``switchport access vlan`` on a TRUNK port is the NATIVE vlan.
* ``management route`` is NOT a global-RIB static route.
* an SNMPv3 key with no ``localized`` marker is a PASSPHRASE (the
  OPPOSITE of the NX-OS default), and one WITH it is pre-localised.

When extending the fixture, add the matching assertion here so the
coverage stays explicit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.dell_os10 import DellOS10Codec

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "dell_os10" / "kitchen_sink.cfg"
)


@pytest.fixture(scope="module")
def raw_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codec() -> DellOS10Codec:
    return DellOS10Codec()


# ---------------------------------------------------------------------------
# Test 1 — sanity parse
# ---------------------------------------------------------------------------


def test_parses_without_exceptions(codec, raw_text):
    assert FIXTURE_PATH.is_file(), f"{FIXTURE_PATH} is missing"
    intent = codec.parse(raw_text)
    assert intent is not None


# ---------------------------------------------------------------------------
# Test 2 — every supported/lossy canonical surface is populated
# ---------------------------------------------------------------------------


def test_populates_every_expected_canonical_field(codec, raw_text):
    """Mirrors the ``supported`` + ``lossy`` lists in
    :class:`DellOS10Codec._CAPS`.  Surfaces the matrix declares
    ``unsupported`` (VXLAN/EVPN, BGP/OSPF, ACLs, QoS, NAT, DHCP pools,
    radius, the management-plane scalars) are intentionally not
    asserted — the codec parses none of them by design."""
    intent = codec.parse(raw_text)

    # /system/hostname
    assert intent.hostname == "dellos10-kitchensink"

    # /interfaces/interface — 14 records across every shape OS10 emits.
    assert len(intent.interfaces) == 14
    by_name = {i.name: i for i in intent.interfaces}

    # Routed physical port: description + MTU + IPv4 + IPv6.
    eth1 = by_name["ethernet1/1/1"]
    assert eth1.description == "Routed-uplink"
    assert eth1.enabled is True
    assert eth1.mtu == 9216
    assert any(
        a.ip == "192.0.2.1" and a.prefix_length == 31
        for a in eth1.ipv4_addresses
    )
    assert any(
        a.ip == "2001:db8:a::1" and a.prefix_length == 64
        for a in eth1.ipv6_addresses
    )

    # Per-interface VRF binding (`ip vrf forwarding`).
    eth2 = by_name["ethernet1/1/2"]
    assert eth2.vrf == "TENANT-A"
    assert any(a.ip == "172.16.0.1" for a in eth2.ipv4_addresses)

    # L2 access port.
    eth3 = by_name["ethernet1/1/3"]
    assert eth3.switchport_mode == "access"
    assert eth3.access_vlan == 32

    # L2 trunk port — see the native-VLAN guard below for the trap.
    eth4 = by_name["ethernet1/1/4"]
    assert eth4.switchport_mode == "trunk"
    assert eth4.trunk_allowed_vlans == [461, 700]

    # Admin-down port (`shutdown`, no `no shutdown`).
    assert by_name["ethernet1/1/5"].enabled is False

    # Management port keeps its address.
    assert any(
        a.ip == "192.168.33.44" for a in by_name["mgmt1/1/1"].ipv4_addresses
    )

    # SVIs: three spellings normalise to one canonical `vlanN` name.
    svi = by_name["vlan461"]
    assert svi.description == "TENANT-A-GATEWAY"
    assert svi.vrf == "TENANT-A"
    assert any(a.ip == "192.168.46.3" and a.prefix_length == 26
               for a in svi.ipv4_addresses)
    assert any(a.ip == "2001:db8:32::2" for a in by_name["vlan32"].ipv6_addresses)

    # /interfaces/interface/vrrp-groups — REAL VRRP, not HSRP-normalised.
    g = svi.vrrp_groups[0]
    assert g.group_id == 46
    assert g.priority == 110
    assert g.preempt is True
    assert g.virtual_ips == ["192.168.46.1"]
    assert by_name["vlan700"].vrrp_groups[0].group_id == 70

    # /interfaces/interface/lag-member-of + /lags
    assert by_name["ethernet1/1/30"].lag_member_of == "port-channel100"
    assert by_name["ethernet1/1/31"].lag_member_of == "port-channel100"
    lags = {lag.name: lag for lag in intent.lags}
    assert set(lags) == {"port-channel100", "port-channel200"}
    assert lags["port-channel100"].members == [
        "ethernet1/1/30", "ethernet1/1/31",
    ]
    # `mode active` -> LACP active; `mode on` -> static.
    assert lags["port-channel100"].mode == "active"
    assert lags["port-channel200"].mode == "static"

    # /vlans — derived from SVIs (OS10 has no top-level `vlan <id>`).
    by_vlan = {v.id: v for v in intent.vlans}
    assert {461, 700, 32}.issubset(set(by_vlan))
    assert by_vlan[461].name == "TENANT-A-GATEWAY"
    assert "port-channel100" in by_vlan[461].tagged_ports
    assert "ethernet1/1/3" in by_vlan[32].untagged_ports

    # /routing-instances — `ip vrf <name>`; `default` is not an instance.
    names = {ri.name for ri in intent.routing_instances}
    assert names == {"TENANT-A", "management"}

    # /routing/static-route incl. the per-VRF discriminator.
    routes = {r.destination: r for r in intent.static_routes}
    assert routes["10.100.0.0/16"].gateway == "192.0.2.254"
    assert routes["10.100.0.0/16"].vrf == ""
    assert routes["10.50.0.0/16"].vrf == "TENANT-A"

    # /local-users — OS10 carries a REAL numeric priv-lvl.
    users = {u.name: u for u in intent.local_users}
    assert set(users) == {"admin", "netops"}
    assert users["admin"].role == "sysadmin"
    assert users["admin"].privilege_level == 15
    assert users["netops"].privilege_level == 2
    assert users["admin"].hashed_password

    # /snmp — v2c scalars + trap host.
    assert intent.snmp.community == "publicro"
    assert intent.snmp.location == "DataCenter-1-RackB"
    assert intent.snmp.contact == "netops@example.net"
    assert "192.0.2.50" in intent.snmp.trap_hosts

    # /snmp/v3-user — both key provenances present (see the guard below).
    v3 = {u.name: u for u in intent.snmp.v3_users}
    assert set(v3) == {"monitor", "localkey"}
    assert v3["monitor"].auth_protocol == "sha"
    assert v3["monitor"].priv_protocol == "aes"
    assert v3["localkey"].auth_protocol == "md5"
    assert v3["localkey"].priv_protocol == "des"

    # Tier-3 surfacing — the banner names the section, never its payload.
    assert "interface breakout" in intent.dropped_tier3_sections


# ---------------------------------------------------------------------------
# Test 3 — canonical round-trip stability
# ---------------------------------------------------------------------------


def _comparable(intent) -> dict:
    """Strip provenance metadata + sort cosmetic-order list fields.

    Mirrors ``test_synthetic_kitchen_sink_round_trips`` / the real-capture
    comparator: the codec promises CANONICAL stability, not byte-identical
    text, and interface order follows device order on render.
    """
    d = intent.model_dump()
    for k in ("source_vendor", "source_format", "source_version",
              "dropped_tier3_sections"):
        d.pop(k, None)
    for key in ("interfaces", "vlans", "lags", "static_routes",
                "local_users", "routing_instances"):
        if isinstance(d.get(key), list):
            d[key] = sorted(d[key], key=lambda x: str(sorted(x.items())))
    return d


def test_round_trip_stable(codec, raw_text):
    first = codec.parse(raw_text)
    second = codec.parse(codec.render(first))
    assert _comparable(first) == _comparable(second)


# ---------------------------------------------------------------------------
# The four OS10 grammar traps — each a silent defect if it regresses
# ---------------------------------------------------------------------------


def test_interface_breakout_does_not_invent_a_port(codec, raw_text):
    """``interface breakout 1/1/1 map 100g-1x`` sits at column 0 and starts
    with the word ``interface`` without declaring one.  A naive
    ``^interface\\s+(\\S+)`` anchor invents ports named ``breakout`` and
    absorbs the config that follows."""
    intent = codec.parse(raw_text)
    names = {i.name for i in intent.interfaces}
    assert not any(n.startswith("breakout") for n in names), names
    assert "breakout" not in names
    # It IS surfaced as a dropped Tier-3 section rather than swallowed.
    assert "interface breakout" in intent.dropped_tier3_sections


def test_switchport_access_vlan_on_a_trunk_is_the_native_vlan(codec, raw_text):
    """OS10 emits NO ``switchport trunk native vlan`` line at all — the
    native VLAN is spelled ``switchport access vlan`` on a trunk port.
    Mapping it to ``access_vlan`` inverts the port's L2 semantics (the
    #239 shape).  Resolved at stanza CLOSE, so line order cannot matter."""
    intent = codec.parse(raw_text)
    by_name = {i.name: i for i in intent.interfaces}

    trunk = by_name["ethernet1/1/4"]
    assert trunk.switchport_mode == "trunk"
    assert trunk.trunk_native_vlan == 1, "native VLAN lost on a trunk port"
    assert trunk.access_vlan is None, (
        "`switchport access vlan` on a TRUNK was read as the access VLAN — "
        "that inverts the port's L2 semantics"
    )

    # The same line on a genuine ACCESS port still means the access VLAN.
    access = by_name["ethernet1/1/3"]
    assert access.access_vlan == 32
    assert access.trunk_native_vlan is None


def test_management_route_does_not_enter_the_global_rib(codec, raw_text):
    """``management route`` installs into the management VRF only.  In the
    real corpus it outnumbers ``ip route`` 8:2, so parsing it as a normal
    static route puts a management-only default into the global RIB."""
    intent = codec.parse(raw_text)
    default = [r for r in intent.static_routes if r.destination == "0.0.0.0/0"]
    assert len(default) == 1
    assert default[0].vrf == "management", (
        "`management route` landed in the global RIB — it is management-VRF "
        "only"
    )
    assert not [
        r for r in intent.static_routes if r.vrf == "" and r.destination == "0.0.0.0/0"
    ]


def test_snmpv3_key_provenance_is_per_line(codec, raw_text):
    """OS10 marks the key's kind ON THE LINE with a trailing ``localized``.

    Its per-codec default is ``plaintext`` — the OPPOSITE of NX-OS — so an
    UNMARKED value is a passphrase.  Labelling it pre-localised would make
    the switch derive a key from a key (the #471 same-vendor corruption),
    which a round-trip guard cannot see because parse→render→parse stays
    stable while the rendered text is wrong."""
    intent = codec.parse(raw_text)
    v3 = {u.name: u for u in intent.snmp.v3_users}

    # Unmarked -> passphrase.
    assert v3["monitor"].auth_kind == "plaintext"
    assert v3["monitor"].priv_kind == "plaintext"

    # Trailing `localized` -> already localised against THIS agent.
    assert v3["localkey"].auth_kind == "localised"
    assert v3["localkey"].priv_kind == "localised"

    # And the marker survives the render rather than being invented or lost.
    rendered = codec.render(intent)
    lines = [ln for ln in rendered.splitlines() if "snmp-server user" in ln]
    monitor = next(ln for ln in lines if " monitor " in ln)
    localkey = next(ln for ln in lines if " localkey " in ln)
    assert "localized" not in monitor, (
        "a source PASSPHRASE was re-emitted as if already localised"
    )
    assert localkey.rstrip().endswith("localized"), (
        "a pre-localised key lost its marker on render"
    )
