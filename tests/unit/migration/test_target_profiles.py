"""
Target-profile loader + model tests.

Covers:
  * YAML schema validation (required/optional fields)
  * Loader behaviour on malformed / duplicate / missing directories
  * Helper accessors (port_count, port_ids, lookup_port, key, display)
  * Real-profile integration: the two profiles shipped under
    ``definitions/target_profiles/`` load cleanly and expose the
    expected port inventories.
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


class TestTargetProfileModel:
    def test_minimal_profile(self):
        p = TargetProfile(vendor="aruba_aoss", model="test")
        assert p.vendor == "aruba_aoss"
        assert p.model == "test"
        assert p.device_class.value == "switch"
        assert p.ports == []
        assert p.lags is None
        assert p.key == "aruba_aoss/test"
        assert p.display() == "aruba_aoss test"

    def test_full_profile(self):
        p = TargetProfile(
            vendor="aruba_aoss",
            model="2930F-48G",
            display_name="Aruba 2930F",
            stacking="vsf-capable",
            ports=[
                TargetPort(id="1", speed="gig", poe=True),
                TargetPort(id="2", speed="gig", poe=True),
                TargetPort(id="A1", kind="uplink", speed="10gig", sfp=True),
            ],
            lags=TargetLAGCaps(max=24, prefix="Trk"),
        )
        assert p.port_count == 3
        assert p.port_ids() == ["1", "2", "A1"]
        assert p.port_ids(kind="physical") == ["1", "2"]
        assert p.port_ids(kind="uplink") == ["A1"]
        assert p.lookup_port("1").poe is True
        assert p.lookup_port("A1").sfp is True
        assert p.lookup_port("missing") is None
        assert p.display() == "Aruba 2930F"

    def test_port_kind_enum(self):
        # Invalid kind rejected
        with pytest.raises(Exception):  # pydantic ValidationError
            TargetPort(id="1", kind="invalid-kind")

    def test_lag_capacity(self):
        caps = TargetLAGCaps(max=0, prefix="")
        assert caps.max == 0
        assert caps.prefix == ""
        with pytest.raises(Exception):  # negative max rejected
            TargetLAGCaps(max=-1)


class TestLoader:
    def test_load_missing_dir_returns_empty(self, tmp_path):
        profiles = load_profiles_dir(tmp_path / "does-not-exist")
        assert profiles == {}

    def test_load_empty_dir_returns_empty(self, tmp_path):
        profiles = load_profiles_dir(tmp_path)
        assert profiles == {}

    def test_load_single_file(self, tmp_path):
        (tmp_path / "test.yaml").write_text(
            "vendor: aruba_aoss\n"
            "model: test-24G\n"
            "ports:\n"
            "  - {id: '1', kind: physical, speed: gig}\n",
            encoding="utf-8",
        )
        profiles = load_profiles_dir(tmp_path)
        assert set(profiles) == {"aruba_aoss/test-24G"}
        assert profiles["aruba_aoss/test-24G"].port_count == 1

    def test_malformed_yaml_skipped_not_fatal(self, tmp_path, caplog):
        (tmp_path / "broken.yaml").write_text(
            "vendor: aruba_aoss\n"
            "ports:\n"
            "  - this is not valid YAML mapping:\n"
            "      -- bad\n",
            encoding="utf-8",
        )
        (tmp_path / "ok.yaml").write_text(
            "vendor: aruba_aoss\nmodel: ok\n",
            encoding="utf-8",
        )
        profiles = load_profiles_dir(tmp_path)
        # The one good file loaded.
        assert set(profiles) == {"aruba_aoss/ok"}

    def test_missing_required_field_rejected(self, tmp_path):
        # Missing ``model`` — required.
        (tmp_path / "no-model.yaml").write_text(
            "vendor: aruba_aoss\n", encoding="utf-8"
        )
        with pytest.raises(ProfileLoadError, match="schema validation"):
            load_profile_file(tmp_path / "no-model.yaml")

    def test_duplicate_key_logs_warning(self, tmp_path, caplog):
        (tmp_path / "a.yaml").write_text(
            "vendor: aruba_aoss\nmodel: test\n", encoding="utf-8"
        )
        (tmp_path / "b.yaml").write_text(
            "vendor: aruba_aoss\nmodel: test\n", encoding="utf-8"
        )
        import logging
        with caplog.at_level(logging.WARNING):
            profiles = load_profiles_dir(tmp_path)
        assert "duplicate" in caplog.text
        # Only one key, the second one wins.
        assert set(profiles) == {"aruba_aoss/test"}


class TestRangeSyntax:
    """Range shorthand in port entries.  Keeps profile YAMLs compact
    — the 48-port 2930F goes from 48 near-identical lines to one
    `{range: "1-48", ...}` entry."""

    def _write(self, tmp_path, body):
        fp = tmp_path / "p.yaml"
        fp.write_text(body, encoding="utf-8")
        return load_profile_file(fp)

    def test_bare_numeric_range(self, tmp_path):
        p = self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "1-48", kind: physical, speed: gig, poe: true}
""")
        assert p.port_count == 48
        assert p.ports[0].id == "1"
        assert p.ports[-1].id == "48"
        assert all(x.poe for x in p.ports)

    def test_prefixed_range_cisco_style(self, tmp_path):
        p = self._write(tmp_path, """
vendor: cisco_iosxe
model: t
ports:
  - {range: "GigabitEthernet1/0/1-24", kind: physical, speed: gig}
""")
        assert p.port_count == 24
        assert p.ports[0].id == "GigabitEthernet1/0/1"
        assert p.ports[-1].id == "GigabitEthernet1/0/24"

    def test_letter_prefix_range_aruba_uplink_style(self, tmp_path):
        p = self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "A1-A4", kind: uplink, speed: 10gig, sfp: true}
""")
        assert [x.id for x in p.ports] == ["A1", "A2", "A3", "A4"]
        assert all(x.kind == "uplink" for x in p.ports)

    def test_mixed_range_and_literal(self, tmp_path):
        p = self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "1-4", kind: physical, speed: gig}
  - {id: "A1", kind: uplink, speed: 10gig, sfp: true}
""")
        assert [x.id for x in p.ports] == ["1", "2", "3", "4", "A1"]
        assert p.ports[-1].kind == "uplink"

    def test_inconsistent_prefix_rejected(self, tmp_path):
        with pytest.raises(ProfileLoadError, match="inconsistent prefix"):
            self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "A1-B4", kind: uplink, speed: 10gig}
""")

    def test_start_greater_than_end_rejected(self, tmp_path):
        with pytest.raises(ProfileLoadError, match="start.* > end"):
            self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "10-1", kind: physical}
""")


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
        "cisco_iosxe/C9300-24UX",
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

    # NOTE: OPNsense target profiles for the Deciso A-series were
    # considered for this commit but deferred.  A background
    # research agent surfaced significant ambiguity — the "A10" and
    # "A20" names have each been reused across multiple hardware
    # generations (em/igb/igc + ax driver families), and the 10G
    # SFP+ cages use AMD XGMAC (`ax0`/`ax1`) not Intel `ix`.
    # Shipping a confidently-wrong dropdown would misdirect
    # operators; flagged for dedicated follow-up with dmesg-grade
    # per-generation verification.

# ---------------------------------------------------------------------------
# Module-variant support (schema-first Option B, milestone-1)
# ---------------------------------------------------------------------------


class TestTargetModuleModel:
    """The :class:`TargetModule` shape on its own."""

    def test_minimal_module(self):
        m = TargetModule()
        assert m.sku == ""
        assert m.description == ""
        assert m.ports == []

    def test_full_module(self):
        m = TargetModule(
            sku="NM-8X",
            description="8x 10G SFP+ uplinks",
            ports=[
                TargetPort(
                    id="TenGigabitEthernet1/1/1",
                    kind="uplink",
                    speed="10gig",
                    sfp=True,
                )
            ],
        )
        assert m.sku == "NM-8X"
        assert m.description.startswith("8x 10G")
        assert len(m.ports) == 1
        assert m.ports[0].kind == "uplink"


class TestProfileWithModules:
    """Semantics of :class:`TargetProfile` when ``modules:`` is set."""

    def _build_dual_module_profile(self) -> TargetProfile:
        """Minimal chassis + two module variants.  Used by several
        tests to avoid repeating the fixture."""
        return TargetProfile(
            vendor="cisco_iosxe",
            model="C9300-24UX",
            ports=[
                TargetPort(id="GigabitEthernet1/0/1", kind="physical"),
                TargetPort(id="GigabitEthernet1/0/2", kind="physical"),
                TargetPort(id="GigabitEthernet0/0", kind="mgmt"),
            ],
            modules={
                "NM-8X": TargetModule(
                    sku="NM-8X",
                    description="8x 10G SFP+",
                    ports=[
                        TargetPort(
                            id=f"TenGigabitEthernet1/1/{n}",
                            kind="uplink",
                            speed="10gig",
                            sfp=True,
                        )
                        for n in range(1, 9)
                    ],
                ),
                "NM-2Q": TargetModule(
                    sku="NM-2Q",
                    description="2x 40G QSFP+",
                    ports=[
                        TargetPort(
                            id="FortyGigabitEthernet1/1/1",
                            kind="uplink",
                            speed="40gig",
                            sfp=True,
                        ),
                        TargetPort(
                            id="FortyGigabitEthernet1/1/2",
                            kind="uplink",
                            speed="40gig",
                            sfp=True,
                        ),
                    ],
                ),
            },
        )

    def test_has_modules(self):
        p = self._build_dual_module_profile()
        assert p.has_modules is True
        assert set(p.module_skus()) == {"NM-8X", "NM-2Q"}

    def test_default_module_sku_prefers_literal_default(self):
        p = TargetProfile(
            vendor="v", model="m",
            modules={
                "OTHER": TargetModule(sku="OTHER"),
                "default": TargetModule(sku="default"),
            },
        )
        # "default" wins even though inserted second.
        assert p.default_module_sku() == "default"

    def test_default_module_sku_falls_back_to_first_inserted(self):
        p = self._build_dual_module_profile()
        # NM-8X was inserted first.
        assert p.default_module_sku() == "NM-8X"

    def test_default_module_sku_none_when_no_modules(self):
        p = TargetProfile(vendor="v", model="m")
        assert p.default_module_sku() is None

    def test_effective_ports_merges_base_and_module(self):
        p = self._build_dual_module_profile()
        # Base has 3 (2 physical + 1 mgmt); NM-8X adds 8.
        eff = p.effective_ports("NM-8X")
        assert len(eff) == 11
        # NM-2Q adds 2 instead — chassis ports are identical.
        eff_q = p.effective_ports("NM-2Q")
        assert len(eff_q) == 5
        # First 3 of eff_q are the same chassis ports as eff.
        assert eff_q[:3] == eff[:3]

    def test_effective_ports_defaults_to_default_sku(self):
        p = self._build_dual_module_profile()
        # No arg → uses default_module_sku() ("NM-8X" here).
        assert p.effective_ports() == p.effective_ports("NM-8X")

    def test_effective_ports_unknown_sku_falls_back_to_base(self):
        p = self._build_dual_module_profile()
        eff = p.effective_ports("NM-DOES-NOT-EXIST")
        # Unknown SKU → base ports only (no crash, no module contrib).
        assert eff == list(p.ports)

    def test_effective_ports_legacy_profile_ignores_module_arg(self):
        p = TargetProfile(
            vendor="v", model="m",
            ports=[TargetPort(id="1"), TargetPort(id="2")],
        )
        # Legacy profile — any module arg just returns base ports.
        assert p.effective_ports("anything") == list(p.ports)

    def test_port_ids_accepts_module_sku(self):
        p = self._build_dual_module_profile()
        uplinks_8x = p.port_ids(kind="uplink", module_sku="NM-8X")
        uplinks_2q = p.port_ids(kind="uplink", module_sku="NM-2Q")
        assert len(uplinks_8x) == 8
        assert len(uplinks_2q) == 2
        assert uplinks_8x[0].startswith("TenGigabitEthernet")
        assert uplinks_2q[0].startswith("FortyGigabitEthernet")
        # Physical filter is module-independent — chassis-fixed.
        phys_8x = p.port_ids(kind="physical", module_sku="NM-8X")
        phys_2q = p.port_ids(kind="physical", module_sku="NM-2Q")
        assert phys_8x == phys_2q

    def test_lookup_port_crosses_base_and_module(self):
        p = self._build_dual_module_profile()
        # Chassis port resolvable regardless of module.
        assert p.lookup_port("GigabitEthernet1/0/1") is not None
        assert (
            p.lookup_port("GigabitEthernet1/0/1", module_sku="NM-2Q")
            is not None
        )
        # Module uplink resolvable only with that module selected.
        assert (
            p.lookup_port("FortyGigabitEthernet1/1/1", module_sku="NM-2Q")
            is not None
        )
        assert (
            p.lookup_port("FortyGigabitEthernet1/1/1", module_sku="NM-8X")
            is None
        )

    def test_port_count_excludes_modules(self):
        """``port_count`` is the base (chassis-fixed) count — use
        ``effective_port_count(sku)`` to include module uplinks.
        Kept separate so UI code that only wants chassis info
        (e.g. "this is a 48-port switch") doesn't accidentally
        double-count."""
        p = self._build_dual_module_profile()
        assert p.port_count == 3
        assert p.effective_port_count("NM-8X") == 11
        assert p.effective_port_count("NM-2Q") == 5

    def test_legacy_accessors_stay_backcompat(self):
        """Existing callers that pass only ``kind`` (no
        ``module_sku``) MUST keep getting the pre-modules
        behaviour.  This guards all pre-B call sites."""
        p = TargetProfile(
            vendor="v", model="m",
            ports=[
                TargetPort(id="1", kind="physical"),
                TargetPort(id="A1", kind="uplink"),
            ],
        )
        assert p.port_ids() == ["1", "A1"]
        assert p.port_ids(kind="physical") == ["1"]
        assert p.port_ids(kind="uplink") == ["A1"]
        assert p.lookup_port("1").kind == "physical"


class TestProfileWithModulesLoader:
    """YAML loader support for the ``modules:`` key."""

    def _write(self, tmp_path: Path, body: str) -> TargetProfile:
        fp = tmp_path / "p.yaml"
        fp.write_text(body, encoding="utf-8")
        return load_profile_file(fp)

    def test_module_ports_with_range_shorthand(self, tmp_path):
        p = self._write(tmp_path, """
vendor: cisco_iosxe
model: C9300-24UX
ports:
  - {range: "GigabitEthernet1/0/1-24", kind: physical, speed: 10gig}
modules:
  NM-8X:
    description: "8x 10G SFP+"
    ports:
      - {range: "TenGigabitEthernet1/1/1-8", kind: uplink, speed: 10gig, sfp: true}
  NM-2Q:
    description: "2x 40G QSFP+"
    ports:
      - {range: "FortyGigabitEthernet1/1/1-2", kind: uplink, speed: 40gig, sfp: true}
""")
        assert p.port_count == 24
        assert p.has_modules
        assert set(p.module_skus()) == {"NM-8X", "NM-2Q"}
        nm8x = p.modules["NM-8X"]
        assert len(nm8x.ports) == 8
        assert nm8x.ports[0].id == "TenGigabitEthernet1/1/1"
        assert nm8x.ports[-1].id == "TenGigabitEthernet1/1/8"
        nm2q = p.modules["NM-2Q"]
        assert len(nm2q.ports) == 2
        assert nm2q.ports[0].id == "FortyGigabitEthernet1/1/1"

    def test_module_sku_backfilled_from_dict_key(self, tmp_path):
        """Authors can omit the ``sku:`` field under each module —
        the dict key is the source of truth."""
        p = self._write(tmp_path, """
vendor: v
model: m
modules:
  NM-8X:
    description: "8x 10G"
    ports: []
""")
        assert p.modules["NM-8X"].sku == "NM-8X"

    def test_explicit_module_sku_wins_over_dict_key(self, tmp_path):
        """If the author set ``sku:`` explicitly we respect it, so
        authors can use alias keys (e.g. friendly URL slug) while
        keeping the part-number SKU."""
        p = self._write(tmp_path, """
vendor: v
model: m
modules:
  nm8x:
    sku: "NM-8X"
    description: "8x 10G"
    ports: []
""")
        assert p.modules["nm8x"].sku == "NM-8X"

    def test_module_not_mapping_rejected(self, tmp_path):
        with pytest.raises(ProfileLoadError, match="must be a mapping"):
            self._write(tmp_path, """
vendor: v
model: m
modules:
  NM-8X: "this should be a mapping not a string"
""")

    def test_module_range_error_identifies_module(self, tmp_path):
        with pytest.raises(ProfileLoadError, match=r"module 'NM-8X'"):
            self._write(tmp_path, """
vendor: v
model: m
modules:
  NM-8X:
    ports:
      - {range: "TenGig1/1/10-1", kind: uplink}
""")

    def test_no_modules_key_stays_legacy(self, tmp_path):
        p = self._write(tmp_path, """
vendor: aruba_aoss
model: 2930F
ports:
  - {range: "1-48", kind: physical, speed: gig}
""")
        assert p.modules == {}
        assert p.has_modules is False
        # effective_ports with no arg returns base ports only.
        assert len(p.effective_ports()) == 48

    def test_empty_modules_dict_stays_legacy(self, tmp_path):
        p = self._write(tmp_path, """
vendor: v
model: m
ports: []
modules: {}
""")
        assert p.has_modules is False
        assert p.default_module_sku() is None

    def test_module_round_trips_through_api_serialization(self, tmp_path):
        """The serialized JSON shape must preserve the ``modules:``
        dict — that's what the GET /target-profiles response
        depends on.  This smoke-tests the pydantic round-trip."""
        p = self._write(tmp_path, """
vendor: cisco_iosxe
model: C9300-24UX
ports:
  - {range: "GigabitEthernet1/0/1-2", kind: physical}
modules:
  NM-2Q:
    description: "2x 40G QSFP+"
    ports:
      - {id: "FortyGigabitEthernet1/1/1", kind: uplink, speed: 40gig}
""")
        dumped = p.model_dump()
        assert "modules" in dumped
        assert "NM-2Q" in dumped["modules"]
        assert dumped["modules"]["NM-2Q"]["ports"][0]["id"] == (
            "FortyGigabitEthernet1/1/1"
        )
        # Legacy field remains populated and distinct from module ports.
        assert len(dumped["ports"]) == 2
        # Rehydrate and verify behaviour survives.
        p2 = TargetProfile.model_validate(dumped)
        assert p2.default_module_sku() == "NM-2Q"
        assert len(p2.effective_ports("NM-2Q")) == 3
