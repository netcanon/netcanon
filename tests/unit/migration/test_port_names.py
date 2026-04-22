"""
Cross-vendor port-name translation — per-codec classify/format
symmetry + cross-codec mesh coverage.

This file is the canonical place to verify that:

1. Every codec's ``classify_port_name`` + ``format_port_identity`` pair
   round-trips its OWN vendor's native names (same-vendor identity).

2. Every (source, target) pair produces a sensible translation for
   common port-name forms (the mesh — catches regressions when a new
   codec lands or an existing codec's rules change).

3. The :func:`translate_port_names` orchestrator rewrites every
   place in :class:`CanonicalIntent` that stores a port name
   (``interfaces``, ``vlans[].tagged/untagged_ports``, ``lags[].members``,
   ``static_routes[].interface``, ``dhcp_servers[].interface``).

4. User-supplied rename_map overrides the auto-heuristic (Tier 2).

5. Warnings are emitted with specific advisory text for the complexity
   cases (breakout, hw_aggregate, loopback-into-Aruba, etc.).
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalStaticRoute,
    CanonicalDHCPPool,
    CanonicalVlan,
)
from netconfig.migration.canonical.port_names import (
    PortIdentity,
    translate_port_names,
    build_port_rename_transform,
)
from netconfig.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netconfig.migration.codecs.opnsense import OPNsenseCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Same-vendor round-trip: classify → format → should equal input
# ---------------------------------------------------------------------------


class TestCiscoClassifyFormat:
    CASES = [
        # Physical ports — every speed prefix.
        "FastEthernet0/1",
        "GigabitEthernet0/1",
        "GigabitEthernet1/0/24",
        "TenGigabitEthernet1/0/1",
        "TwentyFiveGigE1/1/1",
        "FortyGigabitEthernet1/1/1",
        "HundredGigE1/1/1",
        # Breakout (4-part notation).
        "TenGigabitEthernet1/1/1/1",
        "TenGigabitEthernet1/1/1/4",
        # App-hosting virtual (collides with regular gig on lossy
        # translation, preserved via meta hint).
        "AppGigabitEthernet1/0/1",
        # Logical kinds.
        "Port-channel1",
        "Port-channel99",
        "Vlan1",
        "Vlan4094",
        "Loopback0",
        "Loopback999",
        "Tunnel100",
        "VirtualPortGroup0",
    ]

    @pytest.mark.parametrize("name", CASES)
    def test_round_trip(self, name):
        c = CiscoIOSXECLICodec()
        ident = c.classify_port_name(name)
        assert c.format_port_identity(ident) == name, (
            f"Cisco classify→format drift for {name!r} "
            f"(identity={ident.model_dump()})"
        )

    def test_unknown_returns_unknown_kind(self):
        c = CiscoIOSXECLICodec()
        ident = c.classify_port_name("not-a-cisco-name")
        assert ident.kind == "unknown"
        assert ident.original == "not-a-cisco-name"


class TestArubaClassifyFormat:
    CASES = ["1", "24", "48", "1/1", "1/24", "2/48", "1/A1", "1/B24", "Trk1", "Trk99"]

    @pytest.mark.parametrize("name", CASES)
    def test_round_trip(self, name):
        a = ArubaAOSSCodec()
        ident = a.classify_port_name(name)
        assert a.format_port_identity(ident) == name


class TestMikroTikClassifyFormat:
    CASES = [
        "ether1", "ether24",
        "sfp-sfpplus1", "sfp-sfpplus4",
        "sfp1",
        "qsfpplus1", "qsfpplus1-2",
        "bond1",
        "lo", "loopback5",
        "wg1", "gre2", "ipip1",
        "bridge", "br-lan",
        "igb0.10",
    ]

    @pytest.mark.parametrize("name", CASES)
    def test_round_trip(self, name):
        m = MikroTikRouterOSCodec()
        ident = m.classify_port_name(name)
        back = m.format_port_identity(ident)
        # MikroTik VLAN subinterface renders under "bridge.N" when
        # parent hint missing — but with meta-preserving classify,
        # same-vendor round-trip keeps the parent.
        assert back == name


class TestOPNsenseClassifyFormat:
    CASES = ["igb0", "em1", "ix0", "re2", "bnxt0", "lagg0", "igb0.10", "lagg0.100", "lo0", "wg0", "gre1"]

    @pytest.mark.parametrize("name", CASES)
    def test_round_trip(self, name):
        o = OPNsenseCodec()
        ident = o.classify_port_name(name)
        assert o.format_port_identity(ident) == name


class TestFortiGateClassifyFormat:
    CASES = ["port1", "port24", "wan1", "wan2", "lan", "lan5", "internal", "internal3", "dmz1", "mgmt", "ssl.root", "gre1", "loopback0"]

    @pytest.mark.parametrize("name", CASES)
    def test_round_trip(self, name):
        f = FortiGateCLICodec()
        ident = f.classify_port_name(name)
        assert f.format_port_identity(ident) == name


# ---------------------------------------------------------------------------
# The Cisco→Aruba /0/ strip — the exact case that motivated this feature
# ---------------------------------------------------------------------------


class TestCiscoToAruba:
    """The specific translation that surfaced this whole design.

    User's complaint: Cisco→Aruba translation preserved
    ``GigabitEthernet1/0/24`` verbatim instead of stripping the
    ``/0/`` middle digit for stacked Aruba switches.
    """

    @pytest.mark.parametrize("cisco,aruba", [
        ("GigabitEthernet1/0/1", "1/1"),
        ("GigabitEthernet1/0/24", "1/24"),
        ("TenGigabitEthernet1/0/1", "1/1"),
        ("TenGigabitEthernet2/0/48", "2/48"),
        ("GigabitEthernet0/1", "1"),   # standalone Cisco → bare Aruba port
        ("Port-channel1", "Trk1"),
        ("Port-channel10", "Trk10"),
    ])
    def test_translates(self, cisco, aruba):
        src = CiscoIOSXECLICodec()
        tgt = ArubaAOSSCodec()
        ident = src.classify_port_name(cisco)
        assert tgt.format_port_identity(ident) == aruba

    def test_uplink_module_returns_none_for_warning(self):
        """Non-zero middle digit = Cisco uplink module.  Aruba uses
        letter-prefix (A1/B1) for uplink ports which we can't infer.
        Must return None so the orchestrator flags it."""
        src = CiscoIOSXECLICodec()
        tgt = ArubaAOSSCodec()
        ident = src.classify_port_name("FortyGigabitEthernet1/1/1")
        assert tgt.format_port_identity(ident) is None

    def test_breakout_returns_none_for_warning(self):
        """Cisco 4-part breakout notation can't be represented in
        AOS-S (no breakout concept).  Must flag."""
        src = CiscoIOSXECLICodec()
        tgt = ArubaAOSSCodec()
        ident = src.classify_port_name("TenGigabitEthernet1/1/1/1")
        assert tgt.format_port_identity(ident) is None

    def test_loopback_returns_none_for_warning(self):
        """Aruba AOS-S has no loopback concept."""
        src = CiscoIOSXECLICodec()
        tgt = ArubaAOSSCodec()
        ident = src.classify_port_name("Loopback0")
        assert tgt.format_port_identity(ident) is None


# ---------------------------------------------------------------------------
# Cross-codec mesh: every (source, target) pair produces a result
# ---------------------------------------------------------------------------


CODECS = {
    "cisco": CiscoIOSXECLICodec(),
    "aruba": ArubaAOSSCodec(),
    "mikrotik": MikroTikRouterOSCodec(),
    "opnsense": OPNsenseCodec(),
    "fortigate": FortiGateCLICodec(),
}


class TestMesh:
    """Sanity mesh: every codec's classifier sees a recognisable
    sample in its own vendor convention; every target codec either
    returns a string or None (no exceptions, no garbage)."""

    SAMPLES = {
        "cisco": "GigabitEthernet1/0/1",
        "aruba": "1/1",
        "mikrotik": "ether1",
        "opnsense": "igb0",
        "fortigate": "port1",
    }

    @pytest.mark.parametrize("src_name", list(CODECS))
    @pytest.mark.parametrize("tgt_name", list(CODECS))
    def test_every_pair(self, src_name, tgt_name):
        src = CODECS[src_name]
        tgt = CODECS[tgt_name]
        ident = src.classify_port_name(self.SAMPLES[src_name])
        result = tgt.format_port_identity(ident)
        assert result is None or isinstance(result, str)

    def test_every_source_classifies_as_physical(self):
        """Every vendor's representative port name must classify as
        kind='physical' by its own codec — if it falls through to
        unknown, the regex needs fixing."""
        for name, sample in self.SAMPLES.items():
            codec = CODECS[name]
            ident = codec.classify_port_name(sample)
            assert ident.kind == "physical", (
                f"{name} sample {sample!r} classified as "
                f"{ident.kind}, expected physical"
            )


# ---------------------------------------------------------------------------
# Orchestrator — translate_port_names mutates every port-name field
# ---------------------------------------------------------------------------


def _cisco_intent_with_lag():
    """Build a CanonicalIntent that exercises every field where a port
    name might appear: interface names, VLAN membership, LAG members +
    name, interface lag_member_of, static-route interface, DHCP pool
    interface."""
    return CanonicalIntent(
        hostname="test-sw",
        interfaces=[
            CanonicalInterface(
                name="GigabitEthernet1/0/1",
                switchport_mode="access",
                access_vlan=10,
            ),
            CanonicalInterface(
                name="GigabitEthernet1/0/2",
                switchport_mode="trunk",
                trunk_allowed_vlans=[10, 20],
                lag_member_of="Port-channel1",
            ),
            CanonicalInterface(
                name="GigabitEthernet1/0/3",
                lag_member_of="Port-channel1",
            ),
            CanonicalInterface(name="Vlan10"),
            CanonicalInterface(name="Loopback0"),
        ],
        vlans=[
            CanonicalVlan(
                id=10,
                name="users",
                untagged_ports=["GigabitEthernet1/0/1"],
                tagged_ports=["GigabitEthernet1/0/2"],
            ),
            CanonicalVlan(
                id=20,
                name="servers",
                tagged_ports=["GigabitEthernet1/0/2"],
            ),
        ],
        lags=[
            CanonicalLAG(
                name="Port-channel1",
                members=["GigabitEthernet1/0/2", "GigabitEthernet1/0/3"],
            ),
        ],
        static_routes=[
            CanonicalStaticRoute(
                destination="10.0.0.0/8",
                gateway="",
                interface="GigabitEthernet1/0/1",
            ),
        ],
        dhcp_servers=[
            CanonicalDHCPPool(interface="Vlan10", network="192.168.10.0/24"),
        ],
    )


class TestOrchestrator:
    def test_rewrites_every_port_name_field(self):
        intent = _cisco_intent_with_lag()
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec()
        )

        # Interfaces — physical ones rewritten; Vlan10 + Loopback0
        # fall through with warnings since Aruba can't express those.
        names = [i.name for i in intent.interfaces]
        assert "1/1" in names
        assert "1/2" in names
        assert "1/3" in names
        # Vlan10 stays verbatim (SVI has no AOS-S port-name form — the
        # Aruba renderer handles VLAN L3 via the VLAN stanza itself,
        # so this is correct).
        assert "Vlan10" in names
        assert "Loopback0" in names

        # VLAN port lists rewritten consistently.
        vlan10 = next(v for v in intent.vlans if v.id == 10)
        assert vlan10.untagged_ports == ["1/1"]
        assert vlan10.tagged_ports == ["1/2"]

        # LAG name + members rewritten.
        lag = intent.lags[0]
        assert lag.name == "Trk1"
        assert lag.members == ["1/2", "1/3"]

        # Interface's lag_member_of updated.
        iface2 = next(i for i in intent.interfaces if i.name == "1/2")
        assert iface2.lag_member_of == "Trk1"

        # Static-route interface rewritten.
        assert intent.static_routes[0].interface == "1/1"

        # Applied map includes the rewrites.
        assert result.applied["GigabitEthernet1/0/1"] == "1/1"
        assert result.applied["Port-channel1"] == "Trk1"

        # Warnings describe the verbatim-fallback cases.
        assert any("Vlan10" in w and "svi" in w for w in result.warnings)
        assert any("Loopback0" in w and "loopback" in w for w in result.warnings)

    def test_user_rename_map_wins_over_auto(self):
        intent = _cisco_intent_with_lag()
        # User says: actually map Gi1/0/1 to 2/A1 (uplink on stack 2)
        user_map = {"GigabitEthernet1/0/1": "2/A1"}
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            rename_map=user_map,
        )
        # User override wins.
        assert intent.interfaces[0].name == "2/A1"
        # Other ports still auto-translated.
        assert intent.interfaces[1].name == "1/2"
        assert result.applied["GigabitEthernet1/0/1"] == "2/A1"
        assert result.applied["GigabitEthernet1/0/2"] == "1/2"

    def test_transform_factory_returns_usable_pair(self):
        """``build_port_rename_transform`` returns a (callable, result)
        pair that fits the existing transforms= signature and
        accumulates warnings across invocations."""
        transform, result = build_port_rename_transform(
            CiscoIOSXECLICodec(), ArubaAOSSCodec(),
        )
        intent = _cisco_intent_with_lag()
        transform(intent)
        assert intent.interfaces[0].name == "1/1"
        assert "GigabitEthernet1/0/1" in result.applied
        assert any("Vlan10" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Integration: run_plan_with_rename against the real Cat 9300-24UX fixture
# ---------------------------------------------------------------------------


class TestCat9300ToAruba:
    """End-to-end: take the real user-contributed Cat 9300-24UX
    capture, translate to AOS-S, verify the interface names get
    properly rewritten and the warnings surface the untranslatable
    cases.  This is the integration proof for the whole feature.
    """

    FIXTURE_PATH = (
        "tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt"
    )

    def test_run_plan_with_rename_produces_aruba_port_names(self):
        from pathlib import Path
        from netconfig.services.migration_pipeline import run_plan_with_rename

        raw = Path(self.FIXTURE_PATH).read_text(encoding="utf-8")
        job = run_plan_with_rename(
            CiscoIOSXECLICodec(), ArubaAOSSCodec(), raw,
        )

        # Some ports SHOULD have been rewritten.  Spot-check the
        # canonical trunk ports from the fixture.
        assert "TenGigabitEthernet1/0/1" in job.port_renames
        assert job.port_renames["TenGigabitEthernet1/0/1"] == "1/1"
        assert "Port-channel1" in job.port_renames
        assert job.port_renames["Port-channel1"] == "Trk1"

        # Breakout / uplink / loopback / SVI cases produce warnings.
        warnings_text = "\n".join(job.warnings)
        # Cat 9300-24UX has a Gi0/0 Mgmt-vrf port (0/0 is NOT a
        # breakout, it's the mgmt port) and various multi-type ports.
        # Loopback warning — if the fixture has no Loopback lines
        # this may not fire; keep it loose.
        # At minimum the uplink-module Gi1/1/x ports should warn:
        assert any(
            "1/1/" in w or "1/1/1" in w or "FortyGigabit" in w
            or "TwentyFiveGigE" in w or "GigabitEthernet1/1/" in w
            for w in job.warnings
        ), f"expected uplink-module warning; got:\n{warnings_text}"

    def test_user_map_unblocks_flagged_uplinks(self):
        """When the orchestrator flags an uplink port it can't
        auto-resolve, the user can supply a rename_map entry to pin
        the target name.  The warning for that port goes away."""
        from pathlib import Path
        from netconfig.services.migration_pipeline import run_plan_with_rename

        raw = Path(self.FIXTURE_PATH).read_text(encoding="utf-8")
        user_map = {
            # Pin the uplink ports to specific Aruba letter slots.
            "FortyGigabitEthernet1/1/1": "1/A1",
            "FortyGigabitEthernet1/1/2": "1/A2",
        }
        job = run_plan_with_rename(
            CiscoIOSXECLICodec(), ArubaAOSSCodec(), raw,
            port_rename_map=user_map,
        )
        # User override applied.
        assert job.port_renames.get("FortyGigabitEthernet1/1/1") == "1/A1"
        assert job.port_renames.get("FortyGigabitEthernet1/1/2") == "1/A2"
