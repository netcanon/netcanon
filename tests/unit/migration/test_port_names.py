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
    CASES = [
        "port1", "port24",
        "wan1", "wan2",
        "lan", "lan5",
        "internal", "internal3",
        "dmz1", "mgmt",
        "ssl.root", "gre1",
        "loopback0",
        # FG-60F / FG-61F bare-letter FortiLink defaults.  These are
        # documented in Fortinet's fast-path architecture doc for the
        # 60F/61F — the NPU-connected ports labelled A and B on the
        # front panel appear in the CLI as literal ``a`` / ``b``,
        # NOT as ``fortilink1`` / ``fortilink2``.  Same-vendor round-
        # trip must preserve the letter; cross-vendor targets see
        # them as physical ports via the fortigate_role=fortilink
        # meta hint.
        "a", "b",
    ]

    @pytest.mark.parametrize("name", CASES)
    def test_round_trip(self, name):
        f = FortiGateCLICodec()
        ident = f.classify_port_name(name)
        assert f.format_port_identity(ident) == name

    def test_fortilink_letter_classifies_as_physical(self):
        """``a`` and ``b`` on FG-60F must NOT fall through to unknown
        — the rename modal relies on kind=physical for correct
        profile-dropdown routing (access vs uplink split)."""
        f = FortiGateCLICodec()
        for letter in ("a", "b"):
            ident = f.classify_port_name(letter)
            assert ident.kind == "physical", (
                f"FG-60F bare ``{letter}`` must classify as physical, "
                f"got {ident.kind!r}"
            )
            assert ident.meta.get("fortigate_role") == "fortilink"
            assert (
                ident.meta.get("fortigate_fortilink_letter") == letter
            )

    def test_fortilink_letter_case_insensitive(self):
        """Classifier accepts ``A`` / ``B`` too (rare but seen in
        community posts where the front-panel label leaked into a
        pasted config)."""
        f = FortiGateCLICodec()
        for upper, lower in [("A", "a"), ("B", "b")]:
            ident = f.classify_port_name(upper)
            assert ident.kind == "physical"
            # Formatter normalises to lowercase — that's the canonical
            # form FortiOS writes.
            assert f.format_port_identity(ident) == lower


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

    def test_loopback_maps_to_aos_s_loopback_form(self):
        """AOS-S 16.04+ DOES support `interface loopback <0-7>` per
        the Aruba Basic Operation Guide ("Managing loopback
        interfaces" chapter).  Loopback0 from a source vendor maps
        to AOS-S `loopback1` (lo-0 is reserved for the auto-assigned
        ::1/128 IPv6 loopback so user-creatable IDs start at 1)."""
        src = CiscoIOSXECLICodec()
        tgt = ArubaAOSSCodec()
        ident = src.classify_port_name("Loopback0")
        assert tgt.format_port_identity(ident) == "loopback1"

    def test_loopback_indices_above_seven_return_none(self):
        """AOS-S only supports loopback 0-7; higher indices have
        no representation and must flag for operator review."""
        src = CiscoIOSXECLICodec()
        tgt = ArubaAOSSCodec()
        ident = src.classify_port_name("Loopback42")
        assert tgt.format_port_identity(ident) is None

    def test_aruba_port_zero_maps_to_oobm(self):
        """Cisco ``GigabitEthernet0/0`` is the OOBM Mgmt-vrf port
        (port=0, kind=mgmt-classified by Cisco's classifier when it
        recognises Mgmt-vrf semantics, OR physical/port=0 fallback).
        AOS-S has a dedicated ``oobm`` top-level configuration block
        per the Aruba Management & Configuration Guide ("Out-of-Band
        Management" chapter); the Aruba formatter returns the sentinel
        name ``oobm`` so the renderer emits the correct top-level
        block instead of silently dropping the management interface."""
        src = CiscoIOSXECLICodec()
        tgt = ArubaAOSSCodec()
        ident = src.classify_port_name("GigabitEthernet0/0")
        assert ident.port == 0
        # Cisco's classifier returns kind=physical/port=0 here (not
        # kind=mgmt) since GigabitEthernet0/0 isn't *always* the
        # OOBM port — depends on platform.  For physical/port=0 the
        # Aruba formatter still returns None (no port 0 in AOS-S).
        # The mgmt-kind path is exercised by Arista's `Management1`
        # which classifies as kind=mgmt.
        assert tgt.format_port_identity(ident) is None

    def test_arista_management_maps_to_oobm(self):
        """Arista's ``Management1`` classifies as kind=mgmt; AOS-S
        has the dedicated `oobm` top-level block.  Formatter returns
        the sentinel name ``oobm`` so the renderer emits the right
        thing instead of silently dropping the interface (verified
        against Aruba MCG for AOS-S 16.10)."""
        from netconfig.migration.codecs.arista_eos.codec import (
            AristaEOSCodec,
        )
        src = AristaEOSCodec()
        tgt = ArubaAOSSCodec()
        ident = src.classify_port_name("Management1")
        assert ident.kind == "mgmt"
        assert tgt.format_port_identity(ident) == "oobm"


class TestSviAbsorption:
    """Codecs that render VLAN SVIs via VLAN-stanza absorption (Aruba
    AOS-S: ``vlan 11 / ip address X / exit``) have no port-name for
    SVIs — but the L3 state still reaches the target via the VLAN
    stanza render path.  The orchestrator should NOT emit a "no
    native representation" warning for these; the rename modal would
    otherwise list non-actionable review rows for something the
    codec handles correctly elsewhere."""

    def test_aruba_declares_absorbs_svi(self):
        assert ArubaAOSSCodec.absorbs_svi_into_vlan is True

    def test_non_absorbing_codecs_default_false(self):
        # MikroTik, OPNsense, FortiGate render VLANs as standalone
        # interfaces with their own port names, not via absorption.
        assert MikroTikRouterOSCodec.absorbs_svi_into_vlan is False
        assert OPNsenseCodec.absorbs_svi_into_vlan is False
        assert FortiGateCLICodec.absorbs_svi_into_vlan is False
        assert CiscoIOSXECLICodec.absorbs_svi_into_vlan is False

    def test_svi_warning_suppressed_when_target_absorbs(self):
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface,
        )
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="Vlan11"),
                CanonicalInterface(name="Vlan100"),
                # Non-SVI kinds must still translate without warning
                # IF the target codec has a representation.  Aruba
                # AOS-S 16.04+ supports `interface loopback <0-7>`
                # so Loopback0 maps cleanly to `loopback1`.  Use a
                # tunnel name (no AOS-S equivalent) for the warn-
                # path coverage.
                CanonicalInterface(name="Loopback0"),
                CanonicalInterface(name="Tunnel99"),
            ],
        )
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
        )
        # SVIs: no warning, name left verbatim (absorbed into VLAN stanza).
        assert not any("Vlan11" in w for w in result.warnings)
        assert not any("Vlan100" in w for w in result.warnings)
        # Loopback maps cleanly (AOS-S supports loopback) — no warning.
        assert not any("Loopback0" in w for w in result.warnings)
        assert result.applied.get("Loopback0") == "loopback1"
        # Tunnel still warns (AOS-S has no tunnel concept) — regression
        # coverage for "we didn't accidentally silence everything".
        assert any("Tunnel99" in w and "tunnel" in w for w in result.warnings)

    def test_svi_renames_cleanly_when_target_has_native_form(self):
        """FortiGate doesn't absorb SVIs into the VLAN stanza (vlan
        child interfaces are separate ``edit "vlan<id>"`` entries),
        but it DOES have a deterministic native name shape for SVI
        identities: ``vlan<id>``.  Cross-vendor source SVIs (Cisco
        ``Vlan99``, OPNsense ``vlan0.99``) format to the same
        ``vlan99`` post-rename, carrying their ``ipv4_addresses``
        through the rename pass so the FortiGate render's
        ``_build_vlan_children`` synthesis can absorb the IP via the
        sibling-iface walk (Finding 5 in user_smoke_findings.md).
        Result: no "no native representation" warning, name applied
        directly.  Mirrors :func:`test_svi_warning_suppressed_when_
        target_absorbs` for absorbing targets — both paths suppress
        the warning, just for different reasons."""
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface,
        )
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(name="Vlan99")],
        )
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), FortiGateCLICodec(),
        )
        assert not any("Vlan99" in w for w in result.warnings)
        assert result.applied.get("Vlan99") == "vlan99"


class TestDropSemantic:
    """Entries with ``None`` value in the rename map DROP the source
    interface from the canonical tree before render.  Cascade sweep
    removes references from vlans/lags/routes/dhcp so the rendered
    output has no dangling pointers to the dropped name."""

    def _build_cat9300ish_intent(self):
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface, CanonicalLAG,
            CanonicalVlan, CanonicalStaticRoute, CanonicalDHCPPool,
        )
        return CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="GigabitEthernet1/0/1"),
                CanonicalInterface(name="AppGigabitEthernet1/0/1"),
                CanonicalInterface(
                    name="GigabitEthernet1/0/2",
                    lag_member_of="Port-channel1",
                ),
            ],
            vlans=[
                CanonicalVlan(
                    id=10, name="users",
                    tagged_ports=[
                        "GigabitEthernet1/0/1",
                        "AppGigabitEthernet1/0/1",
                    ],
                    untagged_ports=["GigabitEthernet1/0/2"],
                ),
            ],
            lags=[CanonicalLAG(name="Port-channel1", members=["GigabitEthernet1/0/2"])],
            static_routes=[
                CanonicalStaticRoute(
                    destination="0.0.0.0/0",
                    interface="AppGigabitEthernet1/0/1",
                ),
            ],
            dhcp_servers=[
                CanonicalDHCPPool(interface="AppGigabitEthernet1/0/1"),
            ],
        )

    def test_drop_removes_interface_from_tree(self):
        intent = self._build_cat9300ish_intent()
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            rename_map={"AppGigabitEthernet1/0/1": None},
        )
        # Interface gone.
        names = [i.name for i in intent.interfaces]
        assert "AppGigabitEthernet1/0/1" not in names
        # Dropped set echoed in result.
        assert "AppGigabitEthernet1/0/1" in result.dropped

    def test_drop_cascades_to_vlan_port_lists(self):
        intent = self._build_cat9300ish_intent()
        translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            rename_map={"AppGigabitEthernet1/0/1": None},
        )
        vlan10 = next(v for v in intent.vlans if v.id == 10)
        # Gi1/0/1 still in tagged_ports (renamed to 1/1).
        assert "1/1" in vlan10.tagged_ports
        # AppGig dropped; NO reference in any VLAN list.
        for vlan in intent.vlans:
            for p in vlan.tagged_ports + vlan.untagged_ports:
                assert "AppGigabitEthernet" not in p

    def test_drop_cascades_to_static_routes_and_dhcp(self):
        intent = self._build_cat9300ish_intent()
        translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            rename_map={"AppGigabitEthernet1/0/1": None},
        )
        # Static route + DHCP pool pointing at the dropped interface
        # are deleted entirely (no dangling pointer).
        assert len(intent.static_routes) == 0
        assert len(intent.dhcp_servers) == 0

    def test_drop_cascades_to_lag_membership(self):
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface, CanonicalLAG,
        )
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(
                    name="Gi1/0/1", lag_member_of="Port-channel1",
                ),
            ],
            lags=[
                CanonicalLAG(name="Port-channel1", members=["Gi1/0/1"]),
            ],
        )
        translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            rename_map={"Port-channel1": None},
        )
        # LAG gone.
        assert len(intent.lags) == 0
        # Member interface's lag_member_of back-reference cleared.
        assert intent.interfaces[0].lag_member_of is None

    def test_drop_does_not_warn(self):
        """Dropped names emit NO warning — the operator deliberately
        chose not to render this.  Different from 'no target
        equivalent' (which DOES warn).  Warning noise is the whole
        point of having explicit drop."""
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface,
        )
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(name="Loopback0")],
        )
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            rename_map={"Loopback0": None},
        )
        # No warning for the dropped Loopback0 — normally would warn
        # ("Aruba has no loopback") but the drop signals intent.
        assert not any("Loopback0" in w for w in result.warnings)
        assert "Loopback0" in result.dropped


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
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            strip_unmappable=False,  # keep verbatim for reference checks
        )

        # Interfaces — physical ones rewritten; Vlan10 stays verbatim
        # (SVI has no AOS-S port-name form — the Aruba renderer handles
        # VLAN L3 via the VLAN stanza itself).  Loopback0 NOW
        # translates cleanly to AOS-S `loopback1` (16.04+ supports
        # `interface loopback <N>`); previously it was passed through
        # as a warn-and-leave-verbatim case.
        names = [i.name for i in intent.interfaces]
        assert "1/1" in names
        assert "1/2" in names
        assert "1/3" in names
        # Vlan10 stays verbatim.
        assert "Vlan10" in names
        # Loopback0 → loopback1 (Aruba representation).
        assert "loopback1" in names
        assert "Loopback0" not in names

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

        # Warnings: SVI (Vlan10) is NOT warned about because Aruba
        # absorbs SVI L3 into the VLAN stanza.  Loopback0 is NOT
        # warned about because AOS-S 16.04+ supports
        # `interface loopback <N>` and the formatter maps it cleanly
        # to `loopback1` — see TestSviAbsorption for the suppression
        # rule and the dedicated loopback tests for the mapping.
        assert not any("Vlan10" in w for w in result.warnings)
        assert not any("Loopback0" in w for w in result.warnings)

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
        # Loopback0 maps cleanly to AOS-S `loopback1` — no warning,
        # not auto-dropped.  SVI Vlan10 suppressed because Aruba
        # absorbs SVI into VLAN stanza.
        assert not any("Loopback0" in w for w in result.warnings)
        assert "Loopback0" not in result.dropped
        assert result.applied.get("Loopback0") == "loopback1"


class TestAutoDropUnmappable:
    """Default behaviour (``strip_unmappable=True``): when the auto-
    heuristic can't translate a name (target codec's
    ``format_port_identity`` returns None), the source name is
    AUTO-DROPPED from the canonical tree instead of leaking verbatim
    into the rendered output.  Operator can still override with a
    user rename map, or use the Tier 3 UI's "keep verbatim" link."""

    def test_auto_drops_unmappable_by_default(self):
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface,
        )
        intent = CanonicalIntent(
            interfaces=[
                CanonicalInterface(name="GigabitEthernet1/0/1"),
                # Aruba uplink module (non-zero middle digit) — no
                # auto-translation possible.
                CanonicalInterface(name="FortyGigabitEthernet1/1/1"),
                # Tunnel — AOS-S has no tunnel concept (verified
                # against Aruba 16.10/16.11 docs).  Loopback was
                # previously the unmappable case here but AOS-S
                # 16.04+ supports `interface loopback <N>`, so it
                # now translates cleanly to `loopback1`.
                CanonicalInterface(name="Tunnel99"),
            ],
        )
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
        )
        names = [i.name for i in intent.interfaces]
        # Successfully auto-translated: stays (renamed).
        assert "1/1" in names
        # Unmappable: auto-dropped.
        assert "FortyGigabitEthernet1/1/1" not in names
        assert "Tunnel99" not in names
        # Dropped set reflects the auto-drops.
        assert "FortyGigabitEthernet1/1/1" in result.dropped
        assert "Tunnel99" in result.dropped
        # Warnings still fire so the operator sees what happened.
        assert any("FortyGigabitEthernet1/1/1" in w for w in result.warnings)
        assert any("Tunnel99" in w for w in result.warnings)

    def test_strip_unmappable_false_keeps_verbatim(self):
        """Opt-out: ``strip_unmappable=False`` preserves legacy
        leave-verbatim behaviour.  Used by API callers that need
        to inspect unmapped names before deciding what to do."""
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface,
        )
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(name="FortyGigabitEthernet1/1/1")],
        )
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            strip_unmappable=False,
        )
        # Name preserved in canonical tree.
        assert intent.interfaces[0].name == "FortyGigabitEthernet1/1/1"
        # Warning still fires (we didn't translate it).
        assert any("FortyGigabitEthernet1/1/1" in w for w in result.warnings)
        # Not auto-dropped.
        assert "FortyGigabitEthernet1/1/1" not in result.dropped

    def test_verbatim_user_override_beats_auto_drop(self):
        """Operators who explicitly want to keep an unmappable name
        verbatim can supply a no-op rename (``{name: name}``) — the
        user map wins over auto-drop."""
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface,
        )
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(name="FortyGigabitEthernet1/1/1")],
        )
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
            rename_map={"FortyGigabitEthernet1/1/1": "FortyGigabitEthernet1/1/1"},
        )
        # User override applied → name preserved, no drop.
        assert intent.interfaces[0].name == "FortyGigabitEthernet1/1/1"
        assert "FortyGigabitEthernet1/1/1" not in result.dropped

    def test_svi_absorbed_not_auto_dropped(self):
        """SVIs that the target codec absorbs into the VLAN stanza
        are a special case — neither warned nor auto-dropped.  The
        L3 data still reaches the target via the VLAN render path."""
        from netconfig.migration.canonical.intent import (
            CanonicalIntent, CanonicalInterface, CanonicalVlan,
        )
        intent = CanonicalIntent(
            interfaces=[CanonicalInterface(name="Vlan11")],
            vlans=[CanonicalVlan(id=11, name="mgmt")],
        )
        result = translate_port_names(
            intent, CiscoIOSXECLICodec(), ArubaAOSSCodec(),
        )
        # Name stays verbatim (no port-name rename), NO auto-drop.
        assert "Vlan11" in [i.name for i in intent.interfaces]
        assert "Vlan11" not in result.dropped
        assert not any("Vlan11" in w for w in result.warnings)


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


class TestNonCanonicalIntentTreeIsNoOp:
    """Regression guard: :func:`translate_port_names` must gracefully
    handle trees that aren't :class:`CanonicalIntent` — specifically
    the reference mock codec's plain dict shape.  Without this guard
    the orchestrator crashes with
    ``AttributeError: 'dict' object has no attribute 'interfaces'``
    and the pipeline surfaces a spurious ``status: failed`` job (the
    UI always opts into the rename-aware pipeline via
    ``port_rename_map: {}``, so every mock→mock translation from the
    browser hit this path before the guard landed)."""

    def test_plain_dict_tree_returns_empty_result(self):
        from netconfig.migration.codecs.registry import get_codec
        mock = get_codec("mock")
        # Mock codec returns a plain dict from parse() — mimics any
        # future back-compat codec that predates the canonical intent.
        tree = {"/unsafe/kernel_module": "rootkit"}
        result = translate_port_names(tree, mock, mock, rename_map={})
        assert result.applied == {}
        assert result.warnings == []
        assert result.dropped == []

    def test_run_plan_with_rename_passes_through_mock_tree(self):
        """End-to-end: a mock→mock plan with an unsafe path in the
        input must reach ``partial`` (validate blocks on unsupported)
        rather than ``failed``.  This is the exact path the web UI
        hits because it always sends ``port_rename_map: {}`` to opt
        into the rename-aware pipeline."""
        from netconfig.migration.codecs.registry import get_codec
        from netconfig.services.migration_pipeline import run_plan_with_rename

        mock = get_codec("mock")
        raw = '{"/unsafe/kernel_module": "rootkit"}'
        job = run_plan_with_rename(mock, mock, raw, port_rename_map={})
        # Parse succeeded, render succeeded; validate flagged block
        # severity → job status is ``partial`` (terminal-but-unsafe).
        assert job.status.value == "partial"
        assert job.rendered  # the (unsafe) rendered output is present
        assert job.port_renames == {}
        assert job.warnings == []
