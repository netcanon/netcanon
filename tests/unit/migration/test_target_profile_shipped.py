"""
Target-profile shipped-YAML regression tests.

Per-profile assertions for every YAML under
``definitions/target_profiles/``.  A test method per profile
(with parametrized batching for SKUs that share port-layout
invariants) asserts exact port-name strings, counts, and
common-mistake regression guards (e.g. VP6600 uses ``ixl`` not
``ix``; Cat 9300 -24P sticks to gig-speed chassis ports, not
10gig mGig).  These tests catch two classes of authoring drift:

  1. Copy-paste mistakes between sibling SKUs (VP2410 vs VP2420,
     C9300-24P vs C9300-24U).
  2. Module-variant allowlist drift — the
     ``MODULE_VARIANT_PROFILES`` set here mirrors the API-side
     allowlist in
     ``tests/integration/test_migration_target_profiles_api.py``
     and is kept in sync manually.

Schema / accessor tests live in ``test_target_profile_schema.py``;
loader behaviour tests live in ``test_target_profile_loader.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.target_profiles import (
    ProfileLoadError,
    TargetLAGCaps,
    TargetModule,
    TargetPort,
    TargetProfile,
    load_profile_file,
    load_profiles_dir,
)

pytestmark = pytest.mark.unit


class TestRealProfilesShipped:
    """The YAML files under ``definitions/target_profiles/`` load
    cleanly and expose the documented port inventories.  Any breakage
    here means a published profile file was malformed."""

    REPO_PROFILES_DIR = (
        Path(__file__).resolve().parents[3]
        / "definitions" / "target_profiles"
    )

    def test_all_profiles_load(self):
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        # At least two ship with this commit.
        assert len(profiles) >= 2

    def test_aruba_2930f_48g_poep(self):
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["aruba_aoss/2930F-48G-PoEP"]
        assert p.port_count == 50  # 48 RJ45 + 2 SFP+ uplinks
        assert len(p.port_ids(kind="physical")) == 48
        assert len(p.port_ids(kind="uplink")) == 2
        assert p.lags.max == 24
        assert p.lags.prefix == "Trk"
        # Every physical port has PoE.
        for port in p.ports:
            if port.kind == "physical":
                assert port.poe is True

    def test_cisco_c9300_24ux(self):
        """C9300-24UX is a module-variant profile (NM-8X + NM-2Q).
        Chassis is 25 ports (24 mGig + 1 mgmt); each module adds
        its own uplink inventory on top."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["cisco_iosxe/C9300-24UX"]
        assert p.has_modules
        assert set(p.module_skus()) == {"NM-8X", "NM-2Q"}
        # Chassis only (modules excluded): 24 mGig access + 1 mgmt.
        assert p.port_count == 25
        # NM-8X variant adds 8x 10G uplinks → 33 total.
        assert p.effective_port_count("NM-8X") == 33
        assert len(p.port_ids(kind="uplink", module_sku="NM-8X")) == 8
        # NM-2Q variant adds 2x 40G uplinks → 27 total.  This is the
        # path that unblocks the user-reported 40G case — source
        # FortyGigabitEthernet1/1/1-2 now has matching targets.
        assert p.effective_port_count("NM-2Q") == 27
        nm2q_uplinks = p.port_ids(kind="uplink", module_sku="NM-2Q")
        assert nm2q_uplinks == [
            "FortyGigabitEthernet1/1/1",
            "FortyGigabitEthernet1/1/2",
        ]
        # Chassis ports identical between modules (uplinks are the
        # only moving piece).
        assert (
            p.port_ids(kind="physical", module_sku="NM-8X")
            == p.port_ids(kind="physical", module_sku="NM-2Q")
        )
        assert len(p.port_ids(kind="physical", module_sku="NM-8X")) == 24
        assert len(p.port_ids(kind="mgmt", module_sku="NM-8X")) == 1
        assert p.lags.max == 48
        assert p.lags.prefix == "Port-channel"
        # First port is a mGig multigig interface.
        first = p.lookup_port("GigabitEthernet1/0/1")
        assert first is not None
        assert first.speed == "10gig"  # max negotiated speed
        assert first.poe is True

    #: Profiles in the shipped set that have opted in to the
    #: module-variant schema.  Everything else must still be
    #: legacy-shaped (empty modules).  Add to this set when
    #: migrating more profiles.
    MODULE_VARIANT_PROFILES = {
        "cisco_iosxe/C9300-24P",
        "cisco_iosxe/C9300-24U",
        "cisco_iosxe/C9300-24UX",
        "cisco_iosxe/C9300-48P",
        "cisco_iosxe/C9300-48U",
        "cisco_iosxe/C9300-48UXM",
        "aruba_aoss/3810M-24G-PoEP",
        "aruba_aoss/3810M-48G-PoEP",
    }

    def test_non_module_variant_profiles_stay_legacy(self):
        """Profiles not in :attr:`MODULE_VARIANT_PROFILES` must
        keep their legacy shape (``modules == {}``) so existing
        UI/API consumers don't see modules they don't expect.  A
        regression here means a profile was accidentally migrated
        without updating the allowlist."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        for key, p in profiles.items():
            if key in self.MODULE_VARIANT_PROFILES:
                continue
            assert p.modules == {}, (
                f"{key}: modules should be empty for legacy profile, "
                f"got {list(p.modules)}"
            )
            assert p.has_modules is False
            assert p.default_module_sku() is None
            # effective_ports() with no arg should match ports exactly.
            assert p.effective_ports() == list(p.ports)
            # Kind-filtered port_ids should be identical to pre-module
            # behaviour.
            assert p.port_ids() == [pp.id for pp in p.ports]

    def test_all_module_variant_profiles_declare_modules(self):
        """Every entry in the allowlist must actually declare
        modules in its YAML — catches accidental mis-adds."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        for key in self.MODULE_VARIANT_PROFILES:
            assert key in profiles, (
                f"{key}: declared as module-variant but YAML missing"
            )
            p = profiles[key]
            assert p.has_modules, (
                f"{key}: allowlisted as module-variant but modules is "
                f"empty; update YAML or remove from allowlist"
            )

    @pytest.mark.parametrize(
        "model,chassis_access,chassis_total,upoe",
        [
            ("C9300-24P", 24, 25, False),
            ("C9300-24U", 24, 25, True),
            ("C9300-48P", 48, 49, False),
            ("C9300-48U", 48, 49, True),
        ],
    )
    def test_cisco_c9300_plain_variants_module_shape(
        self, model, chassis_access, chassis_total, upoe
    ):
        """The 4 C9300 plain -P/-U variants share the Cat 9300 NM
        slot architecture with the already-migrated -UX / -UXM
        siblings.  After migration they must present the same
        module-variant shape: 25- or 49-port chassis + NM-8X /
        NM-2Q modules, with NM-8X adding 8x 10G uplinks and NM-2Q
        adding 2x 40G uplinks.

        This is the regression guard against accidentally
        reverting any of these four profiles to the old legacy
        shape that baked 8 uplinks into the chassis list — doing
        so would silently re-break the 40G target-port flow for
        operators on non-multigig Cat 9300 boxes."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles[f"cisco_iosxe/{model}"]
        assert p.has_modules, (
            f"{model}: expected module-variant shape, got legacy"
        )
        assert set(p.module_skus()) == {"NM-8X", "NM-2Q"}
        assert p.port_count == chassis_total  # access + mgmt
        # NM-8X adds 8x 10G → chassis_total + 8
        assert p.effective_port_count("NM-8X") == chassis_total + 8
        nm8x_uplinks = p.port_ids(kind="uplink", module_sku="NM-8X")
        assert nm8x_uplinks == [
            f"TenGigabitEthernet1/1/{n}" for n in range(1, 9)
        ]
        # NM-2Q adds 2x 40G → chassis_total + 2
        assert p.effective_port_count("NM-2Q") == chassis_total + 2
        nm2q_uplinks = p.port_ids(kind="uplink", module_sku="NM-2Q")
        assert nm2q_uplinks == [
            "FortyGigabitEthernet1/1/1",
            "FortyGigabitEthernet1/1/2",
        ]
        # Chassis access-port kind should be physical and speed=gig
        # (NOT 10gig — that'd indicate the mGig -UX/-UXM siblings).
        first_access = p.lookup_port("GigabitEthernet1/0/1")
        assert first_access is not None
        assert first_access.kind == "physical"
        assert first_access.speed == "gig"
        assert first_access.poe is True
        if upoe:
            # UPOE variants carry the note; PoE+ variants don't.
            assert "UPOE" in first_access.notes
        # Chassis ports identical between the two module choices
        # (modules only add uplinks — this is the core invariant
        # of the module-variant schema).
        assert (
            p.port_ids(kind="physical", module_sku="NM-8X")
            == p.port_ids(kind="physical", module_sku="NM-2Q")
        )
        assert len(p.port_ids(kind="physical", module_sku="NM-8X")) == chassis_access

    def test_aruba_3810m_48g_poep_module_variants(self):
        """Aruba 3810M chassis with JL083A/JL084A/JL085A expansion
        modules.  Exercises the real-world shape where multiple
        modules reuse the same port-name space (``1/A1-1/A4``) at
        different speeds — picking JL084A gives 4x 40G on the same
        port ids JL083A used for 4x 10G.  The rename modal filters
        target dropdowns by the selected module, so this parallels
        Cat 9300 NM-8X vs NM-2Q at different port-name spaces."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["aruba_aoss/3810M-48G-PoEP"]
        assert set(p.module_skus()) == {"JL083A", "JL084A", "JL085A"}
        # Chassis: 48 RJ45 (no mgmt — AOS-S stackable has no OOB port).
        assert p.port_count == 48
        # JL083A: +4 × 10G SFP+ → 52 total.
        assert p.effective_port_count("JL083A") == 52
        jl083a_uplinks = [
            pt for pt in p.modules["JL083A"].ports if pt.kind == "uplink"
        ]
        assert all(pt.speed == "10gig" for pt in jl083a_uplinks)
        # JL084A: +4 × 40G QSFP+ on the SAME port id range.
        assert p.effective_port_count("JL084A") == 52
        jl084a_uplinks = [
            pt for pt in p.modules["JL084A"].ports if pt.kind == "uplink"
        ]
        assert all(pt.speed == "40gig" for pt in jl084a_uplinks)
        # Same ids, different speeds — this is the key property the
        # rename modal relies on when swapping modules.
        assert (
            [pt.id for pt in jl083a_uplinks]
            == [pt.id for pt in jl084a_uplinks]
        )
        # JL085A: 1 × 40G QSFP+ only (single port).
        assert p.effective_port_count("JL085A") == 49
        jl085a_uplinks = [
            pt for pt in p.modules["JL085A"].ports if pt.kind == "uplink"
        ]
        assert len(jl085a_uplinks) == 1
        assert jl085a_uplinks[0].id == "1/A1"
        assert jl085a_uplinks[0].speed == "40gig"

    # ------------------------------------------------------------------
    # MikroTik / FortiGate / OPNsense target profiles
    #
    # Each assertion anchors the YAML to its authorship-time
    # rationale so that a careless edit (wrong port count, wrong
    # CLI name) gets caught by CI instead of shipping.  Port-name
    # strings are the critical invariant — they become literal target
    # dropdown options in the rename modal, and a typo silently
    # offers the operator non-existent ports.
    # ------------------------------------------------------------------

    def test_mikrotik_crs310(self):
        """CRS310-8G+2S+: grounded in real user-contributed capture
        (user_contrib_crs310_ros7.rsc).  ether1-8 are 2.5G PoE+ RJ45,
        sfp-sfpplus1-2 are 10G SFP+."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["mikrotik_routeros/CRS310-8G+2S+"]
        assert p.vendor == "mikrotik_routeros"
        assert p.device_class == "switch"
        assert p.port_count == 10
        # ether1..8 — every one PoE+ capable
        ether_ids = [pt.id for pt in p.ports if pt.id.startswith("ether")]
        assert ether_ids == [f"ether{n}" for n in range(1, 9)]
        for pt in p.ports:
            if pt.id.startswith("ether"):
                assert pt.poe is True
                assert pt.speed == "2.5gig"
        # sfp-sfpplus1..2 — uplinks, 10gig
        sfp_ids = [pt.id for pt in p.ports if pt.kind == "uplink"]
        assert sfp_ids == ["sfp-sfpplus1", "sfp-sfpplus2"]
        assert p.lags.prefix == "bond"

    def test_mikrotik_ccr2004(self):
        """CCR2004-1G-12S+2XS: 1x GbE mgmt + 12x 10G SFP+ + 2x 25G SFP28."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["mikrotik_routeros/CCR2004-1G-12S+2XS"]
        assert p.device_class == "router"
        assert p.port_count == 15
        # ether1 is the GbE mgmt port.
        ether1 = p.lookup_port("ether1")
        assert ether1 is not None and ether1.kind == "mgmt"
        # 12x SFP+ 10G with exact RouterOS default-name form.
        sfp_plus_ids = [
            pt.id for pt in p.ports if pt.id.startswith("sfp-sfpplus")
        ]
        assert sfp_plus_ids == [f"sfp-sfpplus{n}" for n in range(1, 13)]
        # 2x SFP28 25G — different default-name prefix (no `sfp-`).
        sfp28_ids = [pt.id for pt in p.ports if pt.id.startswith("sfp28")]
        assert sfp28_ids == ["sfp28-1", "sfp28-2"]
        for pt in p.ports:
            if pt.id.startswith("sfp28"):
                assert pt.speed == "25gig"
                assert pt.kind == "uplink"
        assert p.lags.prefix == "bond"

    def test_fortigate_40f(self):
        """FG-40F: 5 GE RJ45 with the peculiar default naming
        `wan`/`a`/`lan1`-`lan3`.  NOT `internal1-4`, NOT `port1-5`,
        NOT `lan4` — the factory config doesn't expose any of those."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["fortigate/40F"]
        assert p.device_class == "firewall"
        assert p.port_count == 5
        ids = set(p.port_ids())
        assert ids == {"wan", "a", "lan1", "lan2", "lan3"}
        # `wan` is an uplink; `a` and lan1-3 are physical.
        assert p.lookup_port("wan").kind == "uplink"
        assert p.lookup_port("a").kind == "physical"
        for n in (1, 2, 3):
            assert p.lookup_port(f"lan{n}").kind == "physical"
        # Common mistakes that should NOT be valid targets on a 40F.
        for wrong in ("wan1", "wan2", "internal1", "port1", "lan4"):
            assert p.lookup_port(wrong) is None, (
                f"{wrong} must not be a valid 40F port — fix the YAML"
            )
        assert p.lags.prefix == ""  # FortiGate LAGs are user-named

    def test_fortigate_60f(self):
        """FG-60F: 10 GE RJ45.  Distinct from sibling 60E/80F/100E
        (which have internal1-7); the 60F has internal1-5 + FortiLink
        ports `a`, `b`."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["fortigate/60F"]
        assert p.port_count == 10
        ids = set(p.port_ids())
        assert ids == {
            "wan1", "wan2", "dmz",
            "internal1", "internal2", "internal3", "internal4", "internal5",
            "a", "b",
        }
        # internal1-5 only — not 6/7 (those are sibling-model names).
        for wrong in ("internal6", "internal7", "lan1"):
            assert p.lookup_port(wrong) is None, (
                f"{wrong} must not be a 60F port — that's a 60E/80F/100E name"
            )
        # `a`/`b` are the FortiLink defaults (physical, not uplink/mgmt).
        assert p.lookup_port("a").kind == "physical"
        assert p.lookup_port("b").kind == "physical"

    def test_fortigate_100e(self):
        """FG-100E: grounded in real user-contributed capture
        (user_contrib_fg100e_fos7213.conf).  22 ports total: wan1/wan2,
        dmz, mgmt, ha1/ha2, port1-14 RJ45, port15-16 GE SFP."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["fortigate/100E"]
        assert p.port_count == 22
        ids = set(p.port_ids())
        # All 6 special-named ports present.
        assert {"wan1", "wan2", "dmz", "mgmt", "ha1", "ha2"} <= ids
        # port1..16 present.
        for n in range(1, 17):
            assert f"port{n}" in ids, f"missing port{n}"
        # port15 and port16 are the SFP cages (sfp=True).
        for n in (15, 16):
            pt = p.lookup_port(f"port{n}")
            assert pt is not None and pt.sfp is True
        # mgmt has its own kind.
        assert p.lookup_port("mgmt").kind == "mgmt"

    # ------------------------------------------------------------------
    # OPNsense Deciso Netboard A-series — three generation-specific
    # profiles, each grounded in a dmesg capture at bsd-hardware.info.
    # Deciso reuses the "A10" and "A20" labels across multiple
    # hardware generations with different chipsets, so we name the
    # profiles by chipset-variant (not by A10/A20 alone) to
    # disambiguate in the rename-modal dropdown.
    # ------------------------------------------------------------------

    def test_opnsense_deciso_a10_i210_gen2(self):
        """Deciso A10 Gen2 (DEC670/DEC690 family): 4x Intel I210
        GbE.  Grounded in bsd-hardware.info probe e0b8ceecae."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Netboard-A10-I210"]
        assert p.device_class == "firewall"
        assert p.port_count == 4
        assert p.port_ids() == ["igb0", "igb1", "igb2", "igb3"]
        for pt in p.ports:
            assert pt.speed == "gig"
            assert pt.kind == "physical"
        assert p.lags.prefix == "lagg"

    def test_opnsense_deciso_a10_i210_sfpplus_gen3(self):
        """Deciso A10 Gen3 (DEC750): 3x I210/I211 + 2x 10G SFP+
        (AMD XGMAC, NOT Intel ix).  Grounded in probe 272dd56725.

        Regression guard against the most likely authoring mistake:
        using ``ix0``/``ix1`` for the 10G cages.  Those are Intel
        ixgbe names — no Deciso platform uses them."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Netboard-A10-I210-SFPPlus"]
        assert p.port_count == 5
        ids = p.port_ids()
        assert ids == ["igb0", "igb1", "igb2", "ax0", "ax1"]
        # The 10G SFP+ cages MUST be ax* not ix* or cxgbe*.
        for wrong in ("ix0", "ix1", "cxgbe0", "cxgbe1"):
            assert p.lookup_port(wrong) is None, (
                f"{wrong} must not appear — Deciso uses AMD XGMAC (ax*) "
                f"for all 10G cages"
            )
        # Verify speed + kind on the AMD ports.
        for letter in ("0", "1"):
            pt = p.lookup_port(f"ax{letter}")
            assert pt is not None and pt.speed == "10gig"
            assert pt.kind == "uplink"
            assert pt.sfp is True

    def test_opnsense_deciso_a20_i225_sfpplus(self):
        """Deciso A20 current generation (DEC850 era): 4x I225-V
        2.5GbE + 2x 10G SFP+ (AMD).  Grounded in probe 06e5f53429
        (OPNsense 23.7.9 / FreeBSD 13.2)."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Netboard-A20-I225-SFPPlus"]
        assert p.port_count == 6
        ids = p.port_ids()
        assert ids == ["igc0", "igc1", "igc2", "igc3", "ax0", "ax1"]
        # igc* are the 2.5GbE copper ports; I225 and I226 share the
        # same igc(4) driver name — don't over-specialise the YAML.
        for n in range(4):
            pt = p.lookup_port(f"igc{n}")
            assert pt is not None
            assert pt.speed == "2.5gig"
            assert pt.kind == "physical"
        # Common mistakes that should NOT be valid ports on the A20.
        for wrong in ("ix0", "ix1", "igb0", "em0", "cxgbe0"):
            assert p.lookup_port(wrong) is None

    def test_opnsense_deciso_a10_82574l_gen1(self):
        """Deciso Netboard A10 Gen1 (original ~2014-2016): 4x
        82574L GbE via em(4) driver.  Grounded in 7+ independent
        bsd-hardware.info probes (primary b64efa8617).  SOC: AMD
        GX-416RA Jaguar pins the generation."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Netboard-A10-82574L"]
        assert p.port_count == 4
        assert p.port_ids() == ["em0", "em1", "em2", "em3"]
        for pt in p.ports:
            assert pt.speed == "gig"
            assert pt.kind == "physical"
        # Pure-em profile has NO SFP+ or 10G ports.
        for wrong in ("ax0", "ix0", "igb0", "igc0"):
            assert p.lookup_port(wrong) is None

    def test_opnsense_deciso_a20_i210_sfpplus_dec3840(self):
        """Deciso A20 pre-R2.0 / DEC3840 rack: 4x I210 GbE + 2x 10G
        SFP+ (AMD).  Grounded in probes 8ded6d9af6 and bab94f86da.
        Distinct from the current R2.0/DEC850 variant which swaps
        I210 copper for I225 2.5GbE."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Netboard-A20-I210-SFPPlus"]
        assert p.port_count == 6
        ids = p.port_ids()
        assert ids == ["igb0", "igb1", "igb2", "igb3", "ax0", "ax1"]
        # igb copper at 1G (not 2.5G — that'd be the igc variant).
        for n in range(4):
            pt = p.lookup_port(f"igb{n}")
            assert pt is not None
            assert pt.speed == "gig"
            assert pt.kind == "physical"
        # AMD 10G uplink — never ix or cxgbe.
        for wrong in ("ix0", "ix1", "cxgbe0", "cxgbe1"):
            assert p.lookup_port(wrong) is None

    def test_opnsense_deciso_a8_i225_current(self):
        """Deciso Netboard A8 current 2.5GbE revision (DEC600
        series): 4x I225-V via igc(4).  Grounded in probe
        ad01c76099, OPNsense DEC600 2.5G desktop.  NO SFP+ cage —
        distinct from A20 which has the same igc chipset but adds
        2x AMD 10G."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Netboard-A8-I225"]
        assert p.port_count == 4
        assert p.port_ids() == ["igc0", "igc1", "igc2", "igc3"]
        for pt in p.ports:
            assert pt.speed == "2.5gig"
            assert pt.kind == "physical"
        # A8 is 2.5G copper only — no SFP+.
        for wrong in ("ax0", "ix0"):
            assert p.lookup_port(wrong) is None

    # ------------------------------------------------------------------
    # Generic OPNsense + virtualization-class profiles
    #
    # The codec is hardware-agnostic — FreeBSD's driver->iface-name
    # mapping is a kernel guarantee.  These profiles let the UI
    # cover common non-appliance cases (bring-your-own-hardware,
    # hypervisor guests) without enumerating every possible SKU.
    # ------------------------------------------------------------------

    def test_opnsense_generic_is_empty_ports_fallback(self):
        """The Generic profile intentionally has ``ports: []`` —
        signals to the rename-modal UI that no dropdown validation
        is available, and the UI falls back to free-form entry.
        Verified behaviour: rename-table.js's check ``if (opts &&
        opts.length)`` treats the empty list as falsy and creates
        a free-form <input> per row."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Generic"]
        assert p.device_class == "firewall"
        assert p.port_count == 0
        assert p.ports == []
        assert p.port_ids() == []
        # LAGs still declared — lagg(4) works regardless of hardware.
        assert p.lags.prefix == "lagg"

    def test_opnsense_vmware_vmxnet3(self):
        """VMware guest: 4x vmx(4) VMXNET3.  FreeBSD driver naming
        is deterministic across hypervisor versions; the VMXNET3
        protocol is what's being modelled, not a specific chipset."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/VMware-VMXNET3"]
        assert p.port_count == 4
        assert p.port_ids() == ["vmx0", "vmx1", "vmx2", "vmx3"]
        for pt in p.ports:
            assert pt.speed == "10gig"
            assert pt.kind == "physical"

    def test_opnsense_virtio_4port(self):
        """KVM/QEMU/Proxmox 4-port VirtIO guest: vtnet0..vtnet3."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/VirtIO-4port"]
        assert p.port_count == 4
        assert p.port_ids() == [f"vtnet{n}" for n in range(4)]

    def test_opnsense_virtio_6port(self):
        """KVM 6-port VirtIO guest — distinct from 4-port solely by
        vtnet count; same driver, same speed."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/VirtIO-6port"]
        assert p.port_count == 6
        assert p.port_ids() == [f"vtnet{n}" for n in range(6)]
        # Regression guard: if this accidentally regresses to 4
        # ports, the fit-check banner will silently undercount for
        # a 6-port VM operator.
        assert p.port_count == 6, "6-port profile must stay 6"

    def test_opnsense_hyperv(self):
        """Microsoft Hyper-V guest: 4x hn(4) synthetic NICs.
        SR-IOV deployments see the underlying physical driver
        instead; those operators should use Generic OPNsense or an
        appliance-specific profile."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/HyperV"]
        assert p.port_count == 4
        assert p.port_ids() == ["hn0", "hn1", "hn2", "hn3"]

    # ------------------------------------------------------------------
    # OPNsense appliance profiles (Protectli, Qotom, Netgate)
    # Grounded in research-agent findings (KB docs + dmesg probes).
    # Each profile uses the chipset-in-name convention established by
    # the Deciso batch so "VP2410" and "VP2420" can't silently collide
    # despite sharing the "Vault" product line.
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("model,ids", [
        # Protectli FW/VP series
        ("Protectli-VP2410-IGB", [f"igb{n}" for n in range(4)]),
        ("Protectli-VP2420-IGC", [f"igc{n}" for n in range(4)]),
        ("Protectli-FW4B-IGB",   [f"igb{n}" for n in range(4)]),
        ("Protectli-FW4C-IGC",   [f"igc{n}" for n in range(4)]),
        ("Protectli-FW6B-IGB",   [f"igb{n}" for n in range(6)]),
        ("Protectli-VP4600-IGC", [f"igc{n}" for n in range(6)]),
        ("Protectli-VP6600-IGC-IXL",
            [f"igc{n}" for n in range(4)] + ["ixl0", "ixl1"]),
        # Qotom mini-PC series
        ("Qotom-Q355G4-IGB",  [f"igb{n}" for n in range(4)]),
        ("Qotom-Q555G6-IGB",  [f"igb{n}" for n in range(6)]),
        ("Qotom-Q750G5-IGC",  [f"igc{n}" for n in range(5)]),
        ("Qotom-Q20331G9-IGC-IX",
            [f"igc{n}" for n in range(5)] + [f"ix{n}" for n in range(4)]),
        # Netgate SG
        ("Netgate-SG5100", ["igb0", "igb1", "ix0", "ix1", "ix2", "ix3"]),
    ])
    def test_opnsense_appliance_port_ids_exact(self, model, ids):
        """Each appliance profile declares the exact driver-level
        port-name sequence the research agents confirmed.  Regression
        guard against copy-paste drift between sibling SKUs — e.g.
        VP2410-IGB and VP2420-IGC share a chassis name prefix but
        use different drivers, and mixing them up would offer
        operators invalid dropdown options."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles[f"opnsense/{model}"]
        assert p.device_class == "firewall"
        assert p.port_ids() == ids
        assert p.port_count == len(ids)

    def test_opnsense_vp6600_has_ixl_not_ix(self):
        """Protectli VP6600's SFP+ cages use the X710-BM2 chip,
        which binds to `ixl(4)` — NOT `ix(4)` (ixgbe family).  This
        distinguishes VP6600 from the Qotom Q20331G9 which uses
        X553 via `ix(4)`.  Missing this distinction would silently
        offer the wrong port names in the rename modal."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Protectli-VP6600-IGC-IXL"]
        uplinks = [pt for pt in p.ports if pt.kind == "uplink"]
        assert [pt.id for pt in uplinks] == ["ixl0", "ixl1"]
        # Regression guard: the ix* names belong to a sibling SKU.
        for wrong in ("ix0", "ix1"):
            assert p.lookup_port(wrong) is None, (
                f"VP6600 must not expose {wrong} — that's Q20331G9's "
                f"naming (X553 via ixgbe); VP6600 uses X710-BM2 via ixl"
            )

    def test_opnsense_sg5100_has_mixed_drivers(self):
        """Netgate SG-5100 exposes 6 ports across TWO drivers —
        2x igb (discrete I210) + 4x ix (X553 fused to 1G).  Common
        authoring mistake would be declaring all 6 as igb since
        they're all 1G copper; the X553 binds to `ix(4)` (ixgbe
        family) despite its fused-down speed."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Netgate-SG5100"]
        assert p.port_count == 6
        igb_ids = [pt.id for pt in p.ports if pt.id.startswith("igb")]
        ix_ids = [pt.id for pt in p.ports if pt.id.startswith("ix")]
        assert igb_ids == ["igb0", "igb1"]
        assert ix_ids == ["ix0", "ix1", "ix2", "ix3"]
        # All 6 report speed=gig (X553 fused-down — NOT 10gig).
        for pt in p.ports:
            assert pt.speed == "gig", (
                f"SG-5100 port {pt.id} should be gig (X553 fused-down), "
                f"got {pt.speed!r}"
            )

    def test_opnsense_deciso_a8_i211_older(self):
        """Deciso Netboard A8 older 1GbE revision: 4x I211 via
        igb(4).  The "A8" name was reused across two electrical
        revisions — this profile targets the older 1GbE variant
        (distinct from the current 2.5GbE igc-based variant)."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["opnsense/Netboard-A8-I211"]
        assert p.port_count == 4
        assert p.port_ids() == ["igb0", "igb1", "igb2", "igb3"]
        for pt in p.ports:
            assert pt.speed == "gig"  # 1G, not 2.5G
            assert pt.kind == "physical"
        # A8-I211 must NOT expose the 2.5G ports that belong to the
        # I225 sibling — else authoring collision between the two
        # revisions.
        for wrong in ("igc0", "igc1", "ax0"):
            assert p.lookup_port(wrong) is None

# ---------------------------------------------------------------------------
# Module-variant support (schema-first Option B, milestone-1)
# ---------------------------------------------------------------------------


