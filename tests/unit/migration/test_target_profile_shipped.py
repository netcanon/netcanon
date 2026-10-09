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
  2. Module-variant allowlist drift — the canonical list of
     module-variant profiles lives in
     :mod:`tests.fixtures.module_variants` and is imported here
     + by the API-tier integration tests.  Single source, no
     manual sync.

Schema / accessor tests live in ``test_target_profile_schema.py``;
loader behaviour tests live in ``test_target_profile_loader.py``.
"""

from __future__ import annotations

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.target_profiles import (
    load_profile_file,
    load_profiles_dir,
)
from tests.fixtures.module_variants import MODULE_VARIANT_PROFILES

pytestmark = pytest.mark.unit


class TestRealProfilesShipped:
    """The YAML files under ``definitions/target_profiles/`` load
    cleanly and expose the documented port inventories.  Any breakage
    here means a published profile file was malformed."""

    REPO_PROFILES_DIR = LIBRARY_DIR / "target_profiles"

    def test_all_profiles_load(self):
        """Every YAML in the directory loads, and none shadows another.

        ``load_profiles_dir`` is deliberately permissive: a file that
        fails validation is logged and SKIPPED, so the app still
        starts.  That means a typo in a constrained field (an
        ``evidence:`` value that is not one of the three grades, say)
        removes the profile from the product with every other test
        green.  Load each file strictly here so the failure names the
        file and the field."""
        files = sorted(self.REPO_PROFILES_DIR.glob("*.yaml"))
        assert files, "no target-profile YAMLs found"
        keys = [load_profile_file(path).key for path in files]
        assert len(set(keys)) == len(keys), (
            "two profile files declare the same vendor/model key: "
            f"{sorted(k for k in set(keys) if keys.count(k) > 1)}"
        )
        assert set(load_profiles_dir(self.REPO_PROFILES_DIR)) == set(keys)

    def test_no_profile_repeats_a_port_id(self):
        """Within the chassis ports plus any ONE module, every id is
        unique.  (Two alternative modules may reuse an id -- a 3810M's
        JL083A and JL078A both start at ``1/A1`` -- because only one
        is fitted at a time.)  The loader does not check this."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        for key, p in profiles.items():
            for sku in [None, *p.module_skus()]:
                ids = p.port_ids(module_sku=sku)
                dupes = sorted({i for i in ids if ids.count(i) > 1})
                assert not dupes, f"{key} (module {sku}): {dupes}"

    def test_max_vlans_is_a_possible_vlan_count(self):
        """A VLAN ceiling above the 802.1Q id range cannot be right, and
        the loader accepts any integer."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        for key, p in profiles.items():
            assert p.max_vlans is not None and 1 <= p.max_vlans <= 4094, key

    def test_aruba_2930f_48g_poep(self):
        """2930F-48G-PoE+-4SFP+ (JL256A), standalone.  Until 2026-10
        this test pinned ``port_count == 50`` and two uplinks -- the
        profile declared ``1/A1`` and ``1/A2`` on a switch that has
        four SFP+ ports and no module slot."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["aruba_aoss/2930F-48G-PoEP"]
        assert p.port_ids(kind="physical") == [str(n) for n in range(1, 49)]
        assert p.port_ids(kind="uplink") == ["49", "50", "51", "52"]
        assert p.port_count == 52
        assert p.lags.max == 60
        assert p.lags.prefix == "Trk"
        # Every physical port has PoE.
        for port in p.ports:
            if port.kind == "physical":
                assert port.poe is True

    @pytest.mark.parametrize(
        ("model", "access", "poe", "uplink_speed", "jnum"),
        [
            ("2930F-24G", 24, False, "10gig", "JL253A"),
            ("2930F-24G-PoEP", 24, True, "10gig", "JL255A"),
            ("2930F-48G", 48, False, "gig", "JL260A"),
            ("2930F-48G-PoEP", 48, True, "10gig", "JL256A"),
        ],
    )
    def test_aruba_2930f_family_port_lists(
        self, model, access, poe, uplink_speed, jnum,
    ):
        """All four 2930F profiles describe the STANDALONE switch: bare
        port numbers, with the four uplinks continuing the access
        numbering.  A 2930F has no module slot, so no id carries a
        letter, and with VSF disabled none carries a member prefix.

        Also pins the J-number in the display name: ``2930F-24G`` was
        labelled JL258A (the 8-port model) and ``2930F-48G`` gave the
        1G-SFP JL260A 10G uplinks."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles[f"aruba_aoss/{model}"]
        assert p.port_ids() == [str(n) for n in range(1, access + 5)]
        assert p.port_ids(kind="uplink") == [
            str(n) for n in range(access + 1, access + 5)
        ]
        assert jnum in p.display_name
        assert "standalone" in p.deployment_state
        assert p.lags.max == 60
        for port in p.ports:
            if port.kind == "physical":
                assert port.speed == "gig"
                assert port.poe is poe
            else:
                assert port.speed == uplink_speed
                assert port.sfp is True

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
        assert p.lags.max == 128
        assert p.lags.prefix == "Port-channel"
        # The 24 mGig downlinks are TenGigabitEthernet — IOS-XE names a
        # port after its top speed.  Until 2026-10 this test pinned
        # ``GigabitEthernet1/0/1``, guarding a name that none of the 24
        # ports on a real C9300-24UX carries (see the capture cited in
        # the profile, and test_target_profile_evidence.py).
        assert p.port_ids(kind="physical", module_sku="NM-8X") == [
            f"TenGigabitEthernet1/0/{n}" for n in range(1, 25)
        ]
        assert p.lookup_port("GigabitEthernet1/0/1") is None
        first = p.lookup_port("TenGigabitEthernet1/0/1")
        assert first is not None
        assert first.speed == "10gig"  # max negotiated speed
        assert first.poe is True

    def test_cisco_c9300_etherchannel_limit(self):
        """A C9300 switch or stack supports 128 EtherChannels (IOS XE
        17.x Layer 2 configuration guide).  All six profiles said 48,
        which capped the LAG override dropdown at ``Port-channel48``."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        c9300 = {k: p for k, p in profiles.items()
                 if k.startswith("cisco_iosxe/C9300-")}
        assert len(c9300) == 6
        for key, p in c9300.items():
            assert p.lags.max == 128, key

    def test_cisco_c9300_48uxm(self):
        """C9300-48UXM: ports 1-36 are 2.5G multigigabit and 37-48 are
        10G multigigabit, and IOS-XE names a port after its top speed --
        so the downlinks are ``TwoGigabitEthernet1/0/1-36`` plus
        ``TenGigabitEthernet1/0/37-48``.

        The profile listed all 48 as ``GigabitEthernet1/0/N`` at 5G
        until 2026-10, and no test pinned its downlinks at all, so
        nothing noticed that none of the 48 names exists."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["cisco_iosxe/C9300-48UXM"]
        assert p.port_ids(kind="physical", module_sku="NM-8X") == (
            [f"TwoGigabitEthernet1/0/{n}" for n in range(1, 37)]
            + [f"TenGigabitEthernet1/0/{n}" for n in range(37, 49)]
        )
        assert p.lookup_port("GigabitEthernet1/0/1") is None
        assert p.lookup_port("TwoGigabitEthernet1/0/36").speed == "2.5gig"
        assert p.lookup_port("TenGigabitEthernet1/0/37").speed == "10gig"
        assert p.port_ids(kind="mgmt") == ["GigabitEthernet0/0"]
        assert p.port_count == 49
        assert set(p.module_skus()) == {"NM-8X", "NM-2Q"}

    def test_aruba_cx_6300m_48g(self):
        """Aruba CX 6300M 48G (JL661A) is an AOS-CX switch: ports are
        member/slot/port, ``1/1/1``..``1/1/48`` with SFP56 uplinks
        ``1/1/49``..``1/1/52``, and stacking is VSF.

        Until 2026-10 it was filed under ``aruba_aoss`` with AOS-S ids
        (``1/1-1/48``, ``1/A1-1/A4``) and ``vsx-stacking``.  The LAG
        prefix carries a trailing space because AOS-CX writes
        ``interface lag 1``; the rename modal builds options as
        prefix + number, and ``lag1`` is not a LAG name the aruba_aoscx
        codec recognises."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        assert "aruba_aoss/6300M-48G-PoE4-SFP56" not in profiles
        p = profiles["aruba_aoscx/6300M-48G-PoE4-SFP56"]
        assert p.port_ids(kind="physical") == [
            f"1/1/{n}" for n in range(1, 49)
        ]
        assert p.port_ids(kind="uplink") == [
            f"1/1/{n}" for n in range(49, 53)
        ]
        assert p.stacking == "vsf"
        assert "JL661A" in p.display_name
        assert p.lags.prefix == "lag "
        assert p.lags.max == 256
        assert p.max_local_users == 64
        # Every LAG name the modal can offer is one the codec accepts.
        from netcanon.migration.codecs.registry import get_codec

        codec = get_codec("aruba_aoscx")
        for n in (1, 256):
            name = f"{p.lags.prefix}{n}"
            assert codec.classify_port_name(name).kind == "lag", name

    #: Canonical allowlist imported from
    #: :mod:`tests.fixtures.module_variants` — single source of
    #: truth shared with the API-tier integration tests.
    MODULE_VARIANT_PROFILES = MODULE_VARIANT_PROFILES

    def test_module_variant_allowlist_shared_with_integration_tier(self):
        """CI-guard: the unit-tier and integration-tier tests reference
        THE SAME frozenset via :mod:`tests.fixtures.module_variants`.
        Pre-fix the allowlist was duplicated as two literal sets with
        a "keep in sync manually" comment; that manual-sync tax is gone.

        A regression here (either tier accidentally shadowing the
        import with a local literal) would re-open the drift hole.
        The import-identity check (``is`` rather than ``==``) catches
        it even if the two literals happen to match content-wise."""
        from tests.fixtures.module_variants import (
            MODULE_VARIANT_PROFILES as CANONICAL,
        )

        # Lazy-import the integration-tier class to avoid pulling the
        # full FastAPI TestClient graph into unit-test collection.
        from tests.integration.test_migration_target_profiles_api import (
            TestModulesFieldSerialization,
        )
        assert self.MODULE_VARIANT_PROFILES is CANONICAL, (
            "unit-tier allowlist no longer imports the canonical "
            "shared set"
        )
        assert TestModulesFieldSerialization.MODULE_VARIANT_PROFILES is CANONICAL, (
            "integration-tier allowlist no longer imports the "
            "canonical shared set — manual-sync tax has returned"
        )

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

    def test_every_shipped_profile_declares_max_vlans(self):
        """Data-enrichment lock-in: every shipped profile must declare
        ``max_vlans`` so the VLAN pane's fit-check banner renders
        something for every selectable target.  Profiles that omit the
        field fall through to the "no limit declared = banner hidden"
        branch, producing a worse operator experience than picking a
        conservative ceiling.  If a new profile ships without one,
        this test flags it at review time."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        missing = [
            key for key, p in profiles.items() if p.max_vlans is None
        ]
        assert missing == [], (
            f"profiles without max_vlans: {missing}.  Populate with a "
            f"datasheet-backed value (or the protocol ceiling 4094 for "
            f"software-VLAN devices) before committing."
        )

    def test_shipped_max_vlans_values_lock(self):
        """Lock in the per-vendor distribution so accidental drift
        (e.g. bulk-set everyone to 4094 when they shouldn't be) shows
        up at review.  Values rationale:
          * Aruba 2930F family: 2048 (the ``max-vlans`` ceiling, AOS-S
            16.11 Advanced Traffic Management Guide)
          * Aruba 3810M / 6300M / Cisco C9x00: 4094 (protocol ceiling,
            device enforces at full range)
          * MikroTik / OPNsense: 4094 (protocol ceiling)
          * Juniper: the figure each model's datasheet prints (4093 /
            4091 / 4093), not the VLAN-id range
          * FortiGate 40F / 60F: 512 (FortiOS 7.2 Max Values Table,
            per-VDOM `system.interface type=vlan`; conservative floor
            for the 7.x line, may drift ±1 on 7.4/7.6)
          * FortiGate 100E: 1024 (ditto; grounded by the FG-100E /
            FortiOS 7.2.13 real capture used for codec certification)

        FortiGate provenance is additionally asserted via
        :meth:`test_fortigate_profiles_declare_max_vlans_source` —
        the new ``max_vlans_source`` field pins which FortiOS version
        the cap was sourced from so future version-tuning passes are
        mechanically auditable (grep-able).
        """
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        # Aruba 2930F family — lower cap.
        for key in (
            "aruba_aoss/2930F-24G",
            "aruba_aoss/2930F-24G-PoEP",
            "aruba_aoss/2930F-48G",
            "aruba_aoss/2930F-48G-PoEP",
        ):
            assert profiles[key].max_vlans == 2048, key
        # Aruba 3810M / 6300M — full protocol range.
        for key in (
            "aruba_aoss/3810M-24G-PoEP",
            "aruba_aoss/3810M-48G-PoEP",
            "aruba_aoscx/6300M-48G-PoE4-SFP56",
        ):
            assert profiles[key].max_vlans == 4094, key
        # FortiGate model-specific.
        assert profiles["fortigate/40F"].max_vlans == 512
        assert profiles["fortigate/60F"].max_vlans == 512
        assert profiles["fortigate/100E"].max_vlans == 1024
        # MikroTik universal.
        assert profiles["mikrotik_routeros/CRS310-8G+2S+"].max_vlans == 4094
        assert profiles["mikrotik_routeros/CCR2004-1G-12S+2XS"].max_vlans == 4094
        # Cisco C9300 family uniformly 4094.
        for key, p in profiles.items():
            if key.startswith("cisco_iosxe/C9300-"):
                assert p.max_vlans == 4094, key
        # OPNsense profiles uniformly ship 4094.
        opnsense_profiles = {k: p for k, p in profiles.items()
                             if k.startswith("opnsense/")}
        assert len(opnsense_profiles) >= 16  # at least what we shipped
        for key, p in opnsense_profiles.items():
            assert p.max_vlans == 4094, key
        # Arista EOS family uniformly 4094: the usable VLAN-id range.
        # (Arista's datasheets print "4096 VLANs"; the source string
        # in each profile says so rather than citing them for 4094.)
        arista_profiles = {k: p for k, p in profiles.items()
                           if k.startswith("arista_eos/")}
        assert len(arista_profiles) >= 4   # 7050SX, 7050CX3, 7280CR3, 7060CX
        for key, p in arista_profiles.items():
            assert p.max_vlans == 4094, key
        # Juniper: per-model datasheet figures.  All three profiles
        # said 4094 -- the VLAN-id RANGE -- and named a datasheet that
        # prints a different number.
        junos_expected = {
            "juniper_junos/EX4300-48T": 4093,
            "juniper_junos/EX4600-40F": 4091,
            "juniper_junos/QFX5120-48Y": 4093,
        }
        junos_profiles = {k: p for k, p in profiles.items()
                          if k.startswith("juniper_junos/")}
        assert set(junos_profiles) == set(junos_expected)
        for key, expected in junos_expected.items():
            assert profiles[key].max_vlans == expected, key
            assert "datasheet" in profiles[key].max_vlans_source, key

    def test_fortigate_profiles_declare_max_vlans_source(self):
        """Version-tuning provenance lock-in: every shipped FortiGate
        profile must declare ``max_vlans_source`` so future
        Maximum-Values-Table re-verification passes (e.g. "FortiOS
        7.6 tightened `system.interface type=vlan` to 500 on the 40F
        class") are grep-able.  Catches drive-by YAML edits that
        tune ``max_vlans`` without updating the provenance string
        (common copy-paste hazard now that the field exists).

        Non-FortiGate profiles are intentionally NOT required to
        populate the field — it's optional and opportunistic.  When
        Aruba / Cisco / MikroTik / OPNsense caps get revisited the
        authoring session SHOULD populate it then, but until that
        revisit happens the empty default is legitimate.
        """
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        fortigate = {
            k: p for k, p in profiles.items() if k.startswith("fortigate/")
        }
        assert len(fortigate) >= 3, (
            "expected at least 3 shipped FortiGate profiles "
            "(40F / 60F / 100E); got: " + ", ".join(sorted(fortigate))
        )
        for key, p in fortigate.items():
            assert p.max_vlans_source, (
                f"{key}: max_vlans_source is empty — set it when "
                f"tuning max_vlans so the FortiOS version-pin is "
                f"auditable.  Format: '<FortiOS X.Y Max Values Table>, "
                f"per-VDOM <row-identifier>'."
            )
            # Must name a specific FortiOS minor (not just "FortiOS
            # 7.x") so version-drift passes can rebind mechanically.
            assert "FortiOS 7." in p.max_vlans_source, (
                f"{key}: max_vlans_source should pin a specific "
                f"FortiOS minor version (e.g. 'FortiOS 7.2' not "
                f"'FortiOS 7.x'); got: {p.max_vlans_source!r}"
            )

    def test_no_profile_for_hardware_opnsense_does_not_run_on(self):
        """The Netgate SG-1100 and SG-3100 are ARM boards that ship
        with pfSense Plus.  OPNsense publishes amd64 images only and
        has no build for either, so a profile filed under ``opnsense``
        described a target that cannot exist; both were deleted in
        2026-10.  (Their port names had also been wrong: the SG-3100
        profile had every role reversed.)  This keeps them from coming
        back, and keeps any other ``mvneta`` -- the Marvell ARM
        Ethernet driver -- port from being offered for OPNsense.  The
        x86 SG-5100 stays: OPNsense installs on it."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        assert "opnsense/Netgate-SG1100" not in profiles
        assert "opnsense/Netgate-SG3100" not in profiles
        assert "opnsense/Netgate-SG5100" in profiles
        for key, p in profiles.items():
            if not key.startswith("opnsense/"):
                continue
            arm = [pid for pid in p.port_ids() if pid.startswith("mvneta")]
            assert not arm, f"{key}: {arm}"

    def test_deciso_dec600_is_the_netboard_a8_profile(self):
        """There is no 5-port Celeron Deciso DEC600.  The DEC600 series
        (DEC677 / DEC697, and the rack DEC2687) is the Netboard A8 with
        four 2.5GbE ports, which ships as ``Netboard-A8-I225``.  The
        ``DEC600-IGC`` profile described a product that does not exist
        and was deleted in 2026-10; this keeps it from coming back and
        keeps the real one findable by the model numbers."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        assert "opnsense/DEC600-IGC" not in profiles
        a8 = profiles["opnsense/Netboard-A8-I225"]
        assert a8.port_ids() == ["igc0", "igc1", "igc2", "igc3"]
        for sku in ("DEC677", "DEC697", "DEC2687"):
            assert sku in a8.display_name

    def test_max_local_users_unset_on_soft_limit_vendors(self):
        """Contract lock-in: MikroTik / OPNsense / FortiGate profiles
        intentionally leave ``max_local_users`` unset.
          * MikroTik: RouterOS is software-unbounded — a fit-check
            banner would be noise.
          * OPNsense / FortiGate: post-Option-A both codecs DO
            round-trip CanonicalLocalUser, but the limit isn't a
            reliable datasheet number (OPNsense is functionally
            unbounded; FortiGate's admin-account cap varies by
            FortiOS version and isn't worth a fit-check).  Leaving
            unset hides the banner on those panes.
          * Aruba AOS-S: the six profiles carried 16 until 2026-10,
            which is not a vendor figure (HPE documents one manager
            and one operator credential plus up to 100 authorization
            accounts).  Unset until someone decides which of those
            the fit-check should count -- an unsourced cap drives a
            banner that is confidently wrong.
        The Aruba CX 6300M declares a vendor-documented 64; Cisco is
        unset because the IOS-XE limit is functionally unbounded."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        assert profiles["aruba_aoscx/6300M-48G-PoE4-SFP56"].max_local_users == 64
        for key, p in profiles.items():
            if key.startswith((
                "mikrotik_routeros/",
                "opnsense/",
                "fortigate/",
                "aruba_aoss/",
            )):
                assert p.max_local_users is None, (
                    f"{key} unexpectedly declares max_local_users="
                    f"{p.max_local_users!r}; the compat-banner + "
                    f"software-unbounded rationale in shipped YAMLs "
                    f"says this should stay unset"
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

    @pytest.mark.parametrize(
        ("model", "access", "jnum"),
        [("3810M-24G-PoEP", 24, "JL073A"), ("3810M-48G-PoEP", 48, "JL074A")],
    )
    def test_aruba_3810m_module_variants(self, model, access, jnum):
        """Aruba 3810M with its real flexible modules: JL083A (4x SFP+)
        and JL078A (1x QSFP+), both in slot A, so the two reuse the
        ``1/A1`` id at different speeds.

        Until 2026-10 this test pinned ``{JL083A, JL084A, JL085A}``.
        JL084A is the 3810M *stacking* module and JL085A a 250 W power
        supply; the profile offered them as "4x 40G" and "1x 40G"
        uplink modules.  The 48G chassis was also labelled JL076A."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles[f"aruba_aoss/{model}"]
        assert p.module_skus() == ["JL083A", "JL078A"]
        assert jnum in p.display_name
        # Chassis: stack-member-1 access ports only.  (The 3810M does
        # have an OOBM port; it is not modelled.)
        assert p.port_ids() == [f"1/{n}" for n in range(1, access + 1)] + [
            "1/A1", "1/A2", "1/A3", "1/A4",
        ]
        assert p.port_count == access
        # JL083A: +4 x 10G SFP+.
        assert p.port_ids(kind="uplink", module_sku="JL083A") == [
            "1/A1", "1/A2", "1/A3", "1/A4",
        ]
        assert all(pt.speed == "10gig" for pt in p.modules["JL083A"].ports)
        # JL078A: a single 40G QSFP+ on the same slot.
        assert p.port_ids(kind="uplink", module_sku="JL078A") == ["1/A1"]
        assert p.modules["JL078A"].ports[0].speed == "40gig"
        assert p.effective_port_count("JL078A") == access + 1
        # The ids are the stacked form, and the profile says so.
        assert "stack member 1" in p.deployment_state
        assert p.lags.max == 144

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
        (user_contrib_crs310_ros7.rsc).  ether1-8 are 2.5G RJ45,
        sfp-sfpplus1-2 are 10G SFP+.  The switch has no PoE-out — this
        test pinned ``poe is True`` until 2026-10, guarding a claim the
        vendor's own product page contradicts."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["mikrotik_routeros/CRS310-8G+2S+"]
        assert p.vendor == "mikrotik_routeros"
        assert p.device_class == "switch"
        assert p.port_count == 10
        # ether1..8 — 2.5G, none of them PoE
        ether_ids = [pt.id for pt in p.ports if pt.id.startswith("ether")]
        assert ether_ids == [f"ether{n}" for n in range(1, 9)]
        for pt in p.ports:
            assert pt.poe is False, pt.id
            if pt.id.startswith("ether"):
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

    # ------------------------------------------------------------------
    # Arista EOS target profiles (Phase 13)
    # ------------------------------------------------------------------

    def test_arista_dcs_7050sx_64(self):
        """Arista DCS-7050SX-64 -- 48x 10G SFP+ + 4x 40G QSFP+ TOR.
        SFP+ ports are single-lane ``Ethernet<N>``; the QSFP+ cages are
        multi-lane, so each is ``Ethernet<N>/1``.  Until 2026-10 this
        test pinned bare ``Ethernet49``..``52``, which a 7050SX-64 does
        not have."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["arista_eos/DCS-7050SX-64"]
        assert p.device_class == "switch"
        assert p.stacking == ""   # no traditional stacking on Arista
        assert p.port_ids() == (
            [f"Ethernet{n}" for n in range(1, 49)]
            + [f"Ethernet{n}/1" for n in range(49, 53)]
            + ["Management1"]
        )
        for n in (49, 50, 51, 52):
            assert p.lookup_port(f"Ethernet{n}") is None
            pt = p.lookup_port(f"Ethernet{n}/1")
            assert pt is not None and pt.kind == "uplink"
            assert pt.speed == "40gig"
        # Ethernet1-48 are physical 10G.
        for n in (1, 24, 48):
            pt = p.lookup_port(f"Ethernet{n}")
            assert pt is not None and pt.kind == "physical"
            assert pt.speed == "10gig"
        # LAG prefix is the Arista-canonical capital-C form.
        assert p.lags.prefix == "Port-Channel"

    def test_arista_dcs_7050cx3_32s(self):
        """DCS-7050CX3-32S -- 32x 100G QSFP + 2x 10G SFP+.  The QSFP
        cages are ``Ethernet<N>/1``; the two SFP+ are single-lane
        ``Ethernet33`` / ``Ethernet34``."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["arista_eos/DCS-7050CX3-32S"]
        assert p.port_ids() == (
            [f"Ethernet{n}/1" for n in range(1, 33)]
            + ["Ethernet33", "Ethernet34", "Management1"]
        )
        for n in range(1, 33):
            assert p.lookup_port(f"Ethernet{n}") is None
            pt = p.lookup_port(f"Ethernet{n}/1")
            assert pt is not None and pt.speed == "100gig"
            assert pt.kind == "uplink"

    def test_arista_dcs_7280cr3_32p4(self):
        """7280CR3-32P4 -- 32x 100G QSFP + 4x 400G OSFP (the ``P4``;
        QSFP-DD is the sibling ``-32D4``).  Every cage is multi-lane."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["arista_eos/DCS-7280CR3-32P4"]
        assert p.port_ids() == (
            [f"Ethernet{n}/1" for n in range(1, 37)] + ["Management1"]
        )
        for n in range(33, 37):
            pt = p.lookup_port(f"Ethernet{n}/1")
            assert pt is not None and pt.speed == "400gig"
            assert "OSFP" in pt.notes
        assert "QSFP-DD" not in p.display_name

    def test_arista_dcs_7060cx_32s(self):
        """DCS-7060CX-32S -- 32x 100G QSFP + 2x 10G SFP+.  Until
        2026-10 this test pinned 33 ports: the profile omitted the two
        SFP+ ports the switch has, and named the QSFP cages bare."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["arista_eos/DCS-7060CX-32S"]
        assert p.port_ids() == (
            [f"Ethernet{n}/1" for n in range(1, 33)]
            + ["Ethernet33", "Ethernet34", "Management1"]
        )
        for n in range(1, 33):
            pt = p.lookup_port(f"Ethernet{n}/1")
            assert pt is not None and pt.speed == "100gig"
        for n in (33, 34):
            pt = p.lookup_port(f"Ethernet{n}")
            assert pt is not None and pt.speed == "10gig"

    # ------------------------------------------------------------------
    # Juniper Junos target profiles (Phase 13)
    # ------------------------------------------------------------------

    def test_juniper_ex4300_48t(self):
        """Juniper EX4300-48T -- 48 x 1GbE, plus 4 x SFP+ on the
        optional uplink module.  Junos port naming: ge-0/0/N for access
        (1G), xe-0/2/N for the uplink module (PIC 2), me0 for
        management.  The rear QSFP+ ports are Virtual Chassis ports by
        default and are deliberately not listed."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["juniper_junos/EX4300-48T"]
        assert p.device_class == "switch"
        assert p.stacking == "virtual-chassis"
        assert p.port_ids() == (
            [f"ge-0/0/{n}" for n in range(48)]      # Junos is 0-indexed
            + [f"xe-0/2/{n}" for n in range(4)]
            + ["me0"]
        )
        for n in (0, 24, 47):
            pt = p.lookup_port(f"ge-0/0/{n}")
            assert pt is not None and pt.speed == "gig"
            assert pt.kind == "physical"
        for n in range(4):
            pt = p.lookup_port(f"xe-0/2/{n}")
            assert pt is not None and pt.speed == "10gig"
            assert pt.kind == "uplink"
        assert p.lookup_port("et-0/1/0") is None
        assert "uplink module" in p.caveat
        # Junos LAG prefix is `ae`.
        assert p.lags.prefix == "ae"

    def test_juniper_ex4600_40f(self):
        """EX4600-40F -- 24x 10G + 4x 40G, all 28 fixed ports on PIC 0.
        Management is ``em0`` / ``em1`` (the EX4600 follows the QFX
        convention, not the EX one).

        Until 2026-10 this test pinned the fixed uplinks as
        ``et-0/1/0``..``3`` -- the ports of an expansion module in bay 1,
        absent on a base chassis -- and management as ``me0``."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["juniper_junos/EX4600-40F"]
        assert p.port_ids() == (
            [f"xe-0/0/{n}" for n in range(24)]
            + [f"et-0/0/{n}" for n in range(24, 28)]
            + ["em0", "em1"]
        )
        for n in (0, 12, 23):
            pt = p.lookup_port(f"xe-0/0/{n}")
            assert pt is not None and pt.speed == "10gig"
        for n in range(24, 28):
            pt = p.lookup_port(f"et-0/0/{n}")
            assert pt is not None and pt.speed == "40gig"
        for gone in ("et-0/1/0", "me0"):
            assert p.lookup_port(gone) is None
        assert p.port_ids(kind="mgmt") == ["em0", "em1"]

    def test_juniper_qfx5120_48y(self):
        """QFX5120-48Y -- DC leaf: 48x SFP28 + 8x 100G QSFP28.  Junos
        names a port after the speed it runs at, and the SFP28 ports
        run at 10G by default, so the factory-default names are
        ``xe-0/0/0``..``47`` (25G would be ``et-``, 1G ``ge-``).

        Until 2026-10 this test pinned ``xle-0/0/N``.  ``xle`` is the
        40G type on QFabric-package QFX3500 / 3600 / 5100, and no
        QFX5120 port has ever carried it."""
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["juniper_junos/QFX5120-48Y"]
        assert p.port_ids() == (
            [f"xe-0/0/{n}" for n in range(48)]
            + [f"et-0/0/{n}" for n in range(48, 56)]
            + ["em0", "em1"]
        )
        assert not [pid for pid in p.port_ids() if pid.startswith("xle-")]
        assert p.lookup_port("me0") is None
        # ``speed`` is the cage's MAXIMUM (25G SFP28), not the 10G the
        # default ``xe-`` name reflects.
        assert all(
            p.lookup_port(f"xe-0/0/{n}").speed == "25gig" for n in range(48)
        )
        assert p.lags.max == 80
        for n in range(48, 56):
            pt = p.lookup_port(f"et-0/0/{n}")
            assert pt is not None and pt.speed == "100gig"
        # The profile describes ONE speed state and says which.
        assert "10G" in p.deployment_state
        assert "et-0/0/N" in p.caveat

# ---------------------------------------------------------------------------
# Module-variant support (schema-first Option B, milestone-1)
# ---------------------------------------------------------------------------


