"""
Focused unit tests for the VyOS codec (``vyos``) — Phase 1 (Tier-1).

Covers the curly-brace ``config.boot`` grammar: probe (config-version
trailer + structural fallback + the Junos non-collision the codec is
careful about), the brace-stack parser (hostname / ethernet+loopback+dummy
interfaces / addresses (IPv4+IPv6 / dhcp) / description / disable / mtu /
``vif`` VLAN sub-interfaces / static routes), port-name classification,
the canonical round-trip, and the capability-matrix declarations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.juniper_junos import JunosCodec
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.codecs.vyos import port_names
from netcanon.migration.codecs.vyos.codec import VyOSCodec

pytestmark = pytest.mark.unit


_SAMPLE = """\
interfaces {
    ethernet eth0 {
        address "192.0.2.1/30"
        description "uplink"
        mtu 1500
    }
    ethernet eth1 {
        address dhcp
        vif 100 {
            address "10.0.100.1/24"
        }
    }
    loopback lo {
        address "192.0.2.255/32"
        address "2001:db8::1/128"
    }
    dummy dum0 {
        disable
    }
}
protocols {
    static {
        route 0.0.0.0/0 {
            next-hop 192.0.2.2 {
                distance 1
            }
        }
        route6 ::/0 {
            next-hop 2001:db8::2 {
            }
        }
    }
}
system {
    host-name vyos-sample
}
// vyos-config-version: "system@27:interfaces@29"
"""

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "vyos" / "kitchen_sink.conf"
)


@pytest.fixture
def codec() -> VyOSCodec:
    return VyOSCodec()


def test_registered() -> None:
    c = get_codec("vyos")
    assert isinstance(c, VyOSCodec)
    assert c.input_format == "cli-vyos"
    assert c.direction == "bidirectional"
    assert c.certainty == "experimental"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def test_probe_detects_config_version() -> None:
    score = VyOSCodec.probe(_SAMPLE)
    assert score is not None and score[0] == 99


def test_probe_structural_fallback_without_trailer() -> None:
    raw = (
        "interfaces {\n"
        "    ethernet eth0 {\n"
        "        address 10.0.0.1/24\n"
        "        disable\n"
        "    }\n"
        "}\n"
        "system {\n"
        "    host-name r1\n"
        "}\n"
    )
    score = VyOSCodec.probe(raw)
    assert score is not None and score[0] == 90


def test_probe_rejects_junos_set_form() -> None:
    raw = (
        "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n"
        "set system host-name r1\n"
    )
    assert VyOSCodec.probe(raw) is None


def test_probe_rejects_junos_curly_form() -> None:
    """A Junos `show configuration` capture is curly-brace too, but its
    leaves end in `;` — the veto must reject it (VyOS has no `;`)."""
    raw = (
        "interfaces {\n"
        "    ge-0/0/0 {\n"
        "        unit 0 {\n"
        "            family inet {\n"
        "                address 10.0.0.1/24;\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    assert VyOSCodec.probe(raw) is None


def test_junos_probe_does_not_steal_vyos() -> None:
    assert JunosCodec.probe(_SAMPLE) is None


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def test_parse_hostname(codec: VyOSCodec) -> None:
    assert codec.parse(_SAMPLE).hostname == "vyos-sample"


def test_parse_ethernet_l3(codec: VyOSCodec) -> None:
    intent = codec.parse(_SAMPLE)
    eth0 = next(i for i in intent.interfaces if i.name == "eth0")
    assert eth0.ipv4_addresses[0].ip == "192.0.2.1"
    assert eth0.ipv4_addresses[0].prefix_length == 30
    assert eth0.description == "uplink"
    assert eth0.mtu == 1500
    assert eth0.enabled is True  # VyOS interfaces default UP


def test_parse_dhcp_address(codec: VyOSCodec) -> None:
    eth1 = next(i for i in codec.parse(_SAMPLE).interfaces if i.name == "eth1")
    assert eth1.dhcp_client is True


def test_parse_vif_subinterface(codec: VyOSCodec) -> None:
    """`ethernet eth1 { vif 100 { ... } }` → an `eth1.100` interface."""
    intent = codec.parse(_SAMPLE)
    vif = next((i for i in intent.interfaces if i.name == "eth1.100"), None)
    assert vif is not None
    assert vif.ipv4_addresses[0].ip == "10.0.100.1"


def test_parse_loopback_dual_stack(codec: VyOSCodec) -> None:
    lo = next(i for i in codec.parse(_SAMPLE).interfaces if i.name == "lo")
    assert lo.ipv4_addresses[0].ip == "192.0.2.255"
    assert lo.ipv6_addresses[0].ip == "2001:db8::1"


def test_parse_disable_sets_admin_down(codec: VyOSCodec) -> None:
    dum0 = next(i for i in codec.parse(_SAMPLE).interfaces if i.name == "dum0")
    assert dum0.enabled is False


def test_parse_static_routes(codec: VyOSCodec) -> None:
    routes = {r.destination: r for r in codec.parse(_SAMPLE).static_routes}
    assert routes["0.0.0.0/0"].gateway == "192.0.2.2"
    assert routes["0.0.0.0/0"].metric == 1
    assert routes["::/0"].gateway == "2001:db8::2"


def test_unquoted_values_tolerated(codec: VyOSCodec) -> None:
    """Older VyOS (1.3 / 1.4-rolling) leaves values bare — the parser
    must accept both quoted and unquoted forms."""
    raw = (
        "interfaces {\n"
        "    ethernet eth0 {\n"
        "        address 10.0.0.1/24\n"
        "        description bare-desc\n"
        "    }\n"
        "}\n"
        "// vyos-config-version: \"x@1\"\n"
    )
    eth0 = next(i for i in codec.parse(raw).interfaces if i.name == "eth0")
    assert eth0.ipv4_addresses[0].ip == "10.0.0.1"
    assert eth0.description == "bare-desc"


# ---------------------------------------------------------------------------
# Port names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,kind", [
    ("eth0", "physical"),
    ("eth0.100", "physical"),
    ("bond0", "lag"),
    ("dum0", "loopback"),
    ("lo", "loopback"),
])
def test_port_name_classify(name: str, kind: str) -> None:
    assert port_names.classify_port_name(name).kind == kind


@pytest.mark.parametrize("name", ["eth0", "bond0", "lo"])
def test_port_name_round_trip(name: str) -> None:
    ident = port_names.classify_port_name(name)
    assert port_names.format_port_identity(ident) == name


# ---------------------------------------------------------------------------
# Round-trip (sorted compare, mirroring the harness normalisation)
# ---------------------------------------------------------------------------

def _normalise(intent):
    return {
        "hostname": intent.hostname,
        "interfaces": sorted(
            (
                i.name, i.enabled, i.mtu, i.description,
                i.dhcp_client, i.dhcp_client_v6,
                tuple((a.ip, a.prefix_length) for a in i.ipv4_addresses),
                tuple((a.ip, a.prefix_length) for a in i.ipv6_addresses),
            )
            for i in intent.interfaces
        ),
        "routes": sorted(
            (r.destination, r.gateway, r.metric)
            for r in intent.static_routes
        ),
    }


def test_round_trip_sample(codec: VyOSCodec) -> None:
    once = codec.parse(_SAMPLE)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_round_trip_kitchen_sink(codec: VyOSCodec) -> None:
    raw = _FIXTURE.read_text(encoding="utf-8")
    once = codec.parse(raw)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_render_emits_config_version_trailer(codec: VyOSCodec) -> None:
    out = codec.render(codec.parse(_SAMPLE))
    assert "vyos-config-version" in out
    assert VyOSCodec.probe(out) is not None


def test_render_vif_nested_under_parent(codec: VyOSCodec) -> None:
    """A vif renders nested inside its parent ethernet block."""
    out = codec.render(codec.parse(_SAMPLE))
    assert "    ethernet eth1 {" in out
    assert "        vif 100 {" in out


# ---------------------------------------------------------------------------
# Capability matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/system/hostname",
    "/interfaces/interface/ipv4/address/ip",
    "/interfaces/interface/ipv6/address/ip",
    "/interfaces/interface/config/mtu",
    "/interfaces/interface/dhcp-client-v6",
    "/routing/static-route",
])
def test_matrix_supported(codec: VyOSCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "supported"


@pytest.mark.parametrize("path", [
    "/interfaces/interface/config/type",
    "/system/raw-sections/version-banner",
])
def test_matrix_lossy(codec: VyOSCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "lossy"


@pytest.mark.parametrize("path", [
    "/vlans/vlan/id",
    "/lags/lag/name",
    "/local-users/user/name",
    "/snmp/community",
    "/routing-instances/instance/name",
    "/vxlan-vnis/vni",
    "/routing-protocols/bgp",
    "/nat",
    "/firewall",
])
def test_matrix_unsupported(codec: VyOSCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "unsupported"
