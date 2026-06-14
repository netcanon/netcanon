"""
Focused unit tests for the Aruba AOS-CX codec (``aruba_aoscx``).

The generic harnesses already cover the broad guarantees — synthetic
round-trip (``test_synthetic_kitchen_sink_round_trips.py`` auto-discovers
``tests/fixtures/synthetic/aruba_aoscx/kitchen_sink.cfg``), capability-
matrix honesty, bidirectionality invariants, and the cross-mesh smoke
matrix.  This module pins the AOS-CX-SPECIFIC behaviours that those
generic tests don't isolate:

* the ``!Version ArubaOS-CX`` probe + its non-collision with the legacy
  ``aruba_aoss`` codec and with Arista EOS,
* multi-token interface-name parsing (``interface vlan 11`` /
  ``interface 1/1/1`` / the ``interface lag N`` interception),
* the type-aware default admin-state (loopbacks up, everything else
  down),
* the ``vrf <name>`` declaration + ``vrf attach`` interface bind,
* the port-name bridge round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.aruba_aoscx import port_names
from netcanon.migration.codecs.aruba_aoscx.codec import ArubaAOSCXCodec
from netcanon.migration.codecs.registry import get_codec

_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "synthetic" / "aruba_aoscx" / "kitchen_sink.cfg"
)

_SAMPLE = """\
!
!Version ArubaOS-CX FL.10.13.1000
!export-password: default
hostname Leaf1
!
vrf RED
vlan 1
vlan 10
    name USERS
    description User access VLAN
interface 1/1/1
    no shutdown
    mtu 9198
    ip address 198.51.100.1/31
interface 1/1/2
    no shutdown
    no routing
    vlan access 10
interface lag 1 multi-chassis
    no shutdown
    no routing
    vlan trunk allowed all
interface vlan 10
    no shutdown
    vrf attach RED
    ip address 10.10.10.1/24
interface loopback 0
    ip address 10.255.0.1/32
ip route 0.0.0.0/0 198.51.100.2
"""

# A legacy AOS-S config + an Arista config — used to prove the AOS-CX
# probe does NOT steal captures that belong to sibling codecs.
_AOSS_SAMPLE = """\
; J9850A Configuration Editor; Created on release #WC.16.11
hostname "sw-edge-01"
vlan 10
   name "USERS"
   untagged 1-24
   exit
interface 1
   name "Desk 1"
   exit
"""

_ARISTA_SAMPLE = """\
! device: spine1 (DCS-7050, EOS-4.28.0F)
!
hostname spine1
!
interface Ethernet1
   no switchport
   ip address 10.0.0.1/31
!
"""


@pytest.fixture()
def codec() -> ArubaAOSCXCodec:
    return ArubaAOSCXCodec()


# ---------------------------------------------------------------------------
# Registration + metadata
# ---------------------------------------------------------------------------

def test_registered() -> None:
    c = get_codec("aruba_aoscx")
    assert isinstance(c, ArubaAOSCXCodec)
    assert c.input_format == "cli-aoscx"
    assert c.direction == "bidirectional"
    assert c.certainty == "experimental"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def test_probe_detects_version_banner() -> None:
    result = ArubaAOSCXCodec.probe(_SAMPLE)
    assert result is not None
    score, _reason = result
    assert score >= 95


def test_probe_structural_fallback_without_banner() -> None:
    no_banner = "\n".join(
        line for line in _SAMPLE.splitlines()
        if "ArubaOS-CX" not in line
    )
    result = ArubaAOSCXCodec.probe(no_banner)
    assert result is not None
    score, _reason = result
    # `interface 1/1/1` + `interface lag N` + `vlan access/trunk` +
    # `vrf attach` + `no routing` -> several structural markers.
    assert score >= 90


def test_probe_does_not_steal_aoss() -> None:
    """The AOS-CX probe must reject a legacy AOS-S config (`;` banner +
    bare-numeric `interface N` + `untagged`)."""
    assert ArubaAOSCXCodec.probe(_AOSS_SAMPLE) is None


def test_probe_does_not_steal_arista() -> None:
    """The AOS-CX probe must reject an Arista EOS config."""
    assert ArubaAOSCXCodec.probe(_ARISTA_SAMPLE) is None


# ---------------------------------------------------------------------------
# Parse — core surfaces
# ---------------------------------------------------------------------------

def test_parse_hostname_and_vrf(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    assert intent.hostname == "Leaf1"
    assert intent.source_version == "FL.10.13.1000"
    assert [ri.name for ri in intent.routing_instances] == ["RED"]


def test_parse_vlans_with_name_and_description(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    by_id = {v.id: v for v in intent.vlans}
    assert set(by_id) >= {1, 10}
    assert by_id[10].name == "USERS"
    assert by_id[10].description == "User access VLAN"


def test_parse_static_route(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    assert len(intent.static_routes) == 1
    route = intent.static_routes[0]
    assert route.destination == "0.0.0.0/0"
    assert route.gateway == "198.51.100.2"


# ---------------------------------------------------------------------------
# Multi-token interface names
# ---------------------------------------------------------------------------

def test_multitoken_interface_names(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    names = {i.name for i in intent.interfaces}
    # Physical triple, SVI, loopback, and the access port are materialised
    # with their space-separated canonical names.
    assert "1/1/1" in names
    assert "1/1/2" in names
    assert "vlan 10" in names
    assert "loopback 0" in names


def test_interface_lag_is_skipped(codec: ArubaAOSCXCodec) -> None:
    """`interface lag N [multi-chassis]` is intercepted (LAGs are a later
    phase) and never materialised as an interface — and the `multi-chassis`
    modifier never leaks into a name."""
    intent = codec.parse(_SAMPLE)
    names = {i.name for i in intent.interfaces}
    assert not any(n.lower().startswith("lag") for n in names)
    assert "lag 1 multi-chassis" not in names


def test_interface_l3_addressing(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    by_name = {i.name: i for i in intent.interfaces}
    eth = by_name["1/1/1"]
    assert eth.mtu == 9198
    assert eth.ipv4_addresses[0].ip == "198.51.100.1"
    assert eth.ipv4_addresses[0].prefix_length == 31


def test_vrf_attach_binds_interface(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    svi = next(i for i in intent.interfaces if i.name == "vlan 10")
    assert svi.vrf == "RED"


# ---------------------------------------------------------------------------
# Type-aware default admin-state
# ---------------------------------------------------------------------------

def test_default_admin_state_type_aware(codec: ArubaAOSCXCodec) -> None:
    intent = codec.parse(_SAMPLE)
    by_name = {i.name: i for i in intent.interfaces}
    # loopback 0 has no `no shutdown` line — loopbacks are up by default.
    assert by_name["loopback 0"].enabled is True
    # Explicit `no shutdown` enables a physical port.
    assert by_name["1/1/1"].enabled is True


def test_bare_physical_defaults_down(codec: ArubaAOSCXCodec) -> None:
    raw = (
        "!Version ArubaOS-CX FL.10.13.1000\n"
        "hostname x\n"
        "interface 1/1/9\n"
        "    description bare\n"
    )
    intent = codec.parse(raw)
    iface = next(i for i in intent.interfaces if i.name == "1/1/9")
    # No explicit admin-state line + a physical port -> AOS-CX default down.
    assert iface.enabled is False


# ---------------------------------------------------------------------------
# Round-trip (sorted compare, mirroring the harness normalisation)
# ---------------------------------------------------------------------------

def _normalise(intent):
    """Return comparable views of the canonical lists the codec populates,
    sorted so render-order vs file-order doesn't register as drift."""
    return {
        "hostname": intent.hostname,
        "vrfs": [ri.name for ri in intent.routing_instances],
        "vlans": sorted(
            (v.id, v.name, v.description) for v in intent.vlans
        ),
        "interfaces": sorted(
            (
                i.name,
                i.enabled,
                i.mtu,
                i.vrf,
                tuple((a.ip, a.prefix_length) for a in i.ipv4_addresses),
                tuple((a.ip, a.prefix_length) for a in i.ipv6_addresses),
            )
            for i in intent.interfaces
        ),
        "routes": sorted(
            (r.destination, r.gateway, r.interface, r.metric)
            for r in intent.static_routes
        ),
    }


def test_round_trip_sample(codec: ArubaAOSCXCodec) -> None:
    once = codec.parse(_SAMPLE)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_round_trip_kitchen_sink(codec: ArubaAOSCXCodec) -> None:
    raw = _FIXTURE.read_text(encoding="utf-8")
    once = codec.parse(raw)
    twice = codec.parse(codec.render(once))
    assert _normalise(twice) == _normalise(once)


def test_render_emits_version_banner(codec: ArubaAOSCXCodec) -> None:
    out = codec.render(codec.parse(_SAMPLE))
    assert "!Version ArubaOS-CX" in out
    # Rendered output re-probes as AOS-CX (self-consistent).
    assert ArubaAOSCXCodec.probe(out) is not None


# ---------------------------------------------------------------------------
# Capability matrix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/system/hostname",
    "/interfaces/interface/ipv4/address/ip",
    "/vlans/vlan/name",
    "/routing/static-route",
    "/routing-instances/instance/name",
])
def test_matrix_supported(codec: ArubaAOSCXCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "supported"


def test_matrix_type_is_lossy(codec: ArubaAOSCXCodec) -> None:
    assert codec.capabilities.classify(
        "/interfaces/interface/config/type"
    ) == "lossy"


@pytest.mark.parametrize("path", [
    "/interfaces/interface/switchport-mode",
    "/lags/lag/name",
    "/vxlan-vnis/vni",
    "/routing-protocols/bgp",
    "/anycast-gateway-mac",
])
def test_matrix_unsupported(codec: ArubaAOSCXCodec, path: str) -> None:
    assert codec.capabilities.classify(path) == "unsupported"


# ---------------------------------------------------------------------------
# Port-name bridge
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,kind", [
    ("1/1/1", "physical"),
    ("vlan 10", "svi"),
    ("lag 1", "lag"),
    ("loopback 0", "loopback"),
    ("vxlan 1", "vtep"),
    ("mgmt", "mgmt"),
])
def test_port_name_classify(name: str, kind: str) -> None:
    assert port_names.classify_port_name(name).kind == kind


@pytest.mark.parametrize("name", [
    "1/1/1", "vlan 10", "lag 1", "loopback 0", "vxlan 1", "mgmt",
])
def test_port_name_round_trip(name: str) -> None:
    ident = port_names.classify_port_name(name)
    assert port_names.format_port_identity(ident) == name
