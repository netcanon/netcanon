"""``run_plan_with_models`` — a translation with both device models declared.

The headline case is the one the feature was built for: a real
standalone Aruba 2930F-48G config moved onto a 2930M-48G with an SFP+
module, deployed as a one-member stack.  The name-shape translator
cannot do it — on a same-vendor pair it is the identity, and it could
never know that port ``49`` of one switch is ``1/A1`` of the other.

Everything here runs the committed real captures through the real
codecs and the real pipeline; nothing is mocked.  The pairing policy
itself is pinned on synthetic inventories in ``test_port_mapping.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface
from netcanon.migration.canonical.port_names import (
    HARDWARE_PORT_KINDS,
    NON_HARDWARE_INTERFACE_TYPES,
    NON_HARDWARE_PORT_KINDS,
    PortIdentity,
    collect_hardware_port_names,
    collect_port_names,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.device_models import (
    Deployment,
    Inventory,
    MemberSpec,
    compile_deployment,
    inventory_from_profile,
    load_model_families_dir,
)
from netcanon.migration.target_profiles import TargetProfile, load_profiles_dir
from netcanon.models.migration import MigrationJob, MigrationJobStatus
from netcanon.services import migration_pipeline
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = load_model_families_dir(LIBRARY_DIR / "model_families")
PROFILES = load_profiles_dir(LIBRARY_DIR / "target_profiles")
AOSS = get_codec("aruba_aoss")

#: A real standalone 2930F-48G-4SFP (JL260A).  Its VLAN membership lines
#: name every port from 1 to 52; it has one ``interface`` stanza.
CAPTURE_2930F = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
).read_text(encoding="utf-8")

#: A real one-member 2930M stack: JL323A with a JL083A.
CAPTURE_2930M = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg"
).read_text(encoding="utf-8")


#: A minimal AOS-S config with a LAG, named ``trk1`` where it is defined
#: and ``Trk1`` where a VLAN lists it.
_CONFIG_WITH_A_TRUNK = """
; JL260A Configuration Editor; Created on release #WC.16.07.0002
hostname "sw"
trunk 51-52 trk1 lacp
vlan 1
   name "DEFAULT_VLAN"
   untagged 1-50
   tagged Trk1
   exit
""".lstrip()


def _device(mode: str | None, *members: dict) -> Inventory:
    return compile_deployment(
        Deployment(
            vendor="aruba_aoss", mode=mode,
            members=[MemberSpec(**m) for m in members],
        ),
        REGISTRY,
    )


def _bare(start: int, count: int) -> list[str]:
    return [str(n) for n in range(start, start + count)]


def _hardware_names(rendered: str) -> set[str]:
    """Hardware ports in a rendered AOS-S config, read back by the parser."""
    return set(collect_hardware_port_names(AOSS.parse(rendered)))


def _shared_final_names(source, raw_text: str, job: MigrationJob) -> dict[str, list[str]]:
    """Final names that more than one source name ended on.

    Written out here, on purpose, rather than imported from the engine:
    the engine's own check once looked only at the names its plan was
    made for, and a test that called the same function over the same
    list had the same blind spot.  This reads EVERY name the parsed
    config references and groups by where the job says each ended.
    """
    dropped = set(job.port_drops)
    ended: dict[str, set[str]] = {}
    for name in collect_port_names(source.parse(raw_text)):
        if name in dropped:
            continue
        final = job.port_renames.get(name, name)
        ended.setdefault(final.strip().casefold(), set()).add(name.casefold())
    return {final: sorted(names) for final, names in ended.items() if len(names) > 1}


def run_plan_with_models(*args, expect_fused: bool = False, **kwargs) -> MigrationJob:
    """The real function, with what must hold of EVERY job checked.

    Every test in this module calls the pipeline through here, so the
    central promise is checked on each run rather than in one test:

    * no two names the config references end on one target name --
      recomputed independently (:func:`_shared_final_names`), over
      logical names as well as ports -- unless the test says the
      operator asked for it;
    * when the operator did, the plan's record names the same targets;
    * a job with a fused target, or with a port nobody decided, is
      not ``completed``;
    * what the plan says happened to an unplaced port is what the
      job's drop list says happened to it.
    """
    job = migration_pipeline.run_plan_with_models(*args, **kwargs)
    plan = job.port_mapping_plan
    if plan is None or not plan.applied:
        return job
    source, raw_text = args[0], args[2]
    shared = _shared_final_names(source, raw_text, job)
    if expect_fused:
        assert shared and plan.fused
        assert {t.strip().casefold() for t in plan.fused} == set(shared)
    else:
        assert shared == {}, f"two names on one target name: {shared}"
        assert plan.fused == {}
    if plan.fused or plan.unresolved_ports:
        assert job.status != MigrationJobStatus.completed
    for port in plan.used_unplaced:
        assert port.dropped == (port.source in job.port_drops), port.source
        assert bool(port.landed) == (not port.dropped), port.source
    return job


SOURCE_2930F_48G = _device("standalone", {"model": "JL260A"})
TARGET_2930M_48G = _device("stacked", {"model": "JL322A", "modules": {"A": "JL083A"}})
TARGET_2930M_24G = _device("stacked", {"model": "JL320A", "modules": {"A": "JL083A"}})


# ---------------------------------------------------------------------------
# The corridor the feature was built for
# ---------------------------------------------------------------------------


class TestStandalone2930FOntoStacked2930M:
    """2930F-48G (standalone) -> 2930M-48G-PoE+ with a JL083A, stacking
    enabled, one unit.  Every one of the 52 ports has a place."""

    @pytest.fixture(scope="class")
    def job(self):
        return run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
        )

    def test_all_fifty_two_ports_land(self, job) -> None:
        plan = job.port_mapping_plan
        assert plan is not None and plan.applied and plan.is_clean
        assert len(plan.used_pairings) == 52
        assert plan.unplaced == [] and plan.off_inventory == []
        assert job.status == MigrationJobStatus.completed
        assert job.port_drops == []

    def test_access_ports_take_the_member_number(self, job) -> None:
        assert job.port_renames["1"] == "1/1"
        assert job.port_renames["48"] == "1/48"

    def test_built_in_uplinks_become_the_modules_ports(self, job) -> None:
        """``49``-``52`` are the 2930F's built-in SFP cages.  The 2930M
        has no port 49: its uplinks are the module's, ``1/A1``-``1/A4``."""
        assert [job.port_renames[n] for n in ("49", "50", "51", "52")] == [
            "1/A1", "1/A2", "1/A3", "1/A4",
        ]

    def test_the_rendered_config_names_exactly_the_targets_ports(self, job) -> None:
        """Read the output back: its hardware ports are the target
        inventory's, all of them, and nothing is left under a bare
        number."""
        assert _hardware_names(job.rendered) == set(TARGET_2930M_48G.names())

    def test_every_reference_moved(self, job) -> None:
        assert "interface 1/1" in job.rendered
        assert "untagged 1/48,1/A1,1/A2,1/A3,1/A4" in job.rendered
        lines = [ln.strip() for ln in job.rendered.splitlines()]
        assert "interface 1" not in lines
        assert not [ln for ln in lines if ln.startswith(("untagged 48", "tagged 35"))]

    def test_the_plan_says_what_each_side_resolved_to(self, job) -> None:
        plan = job.port_mapping_plan
        assert plan.source.members[0].model == "2930F-48G-4SFP"
        assert plan.source.mode == "standalone"
        assert plan.target.members[0].model == "2930M-48G-PoEP"
        assert plan.target.members[0].modules == {"A": "JL083A"}
        assert (plan.target.mode, plan.target.members[0].member_id) == ("stacked", 1)
        assert (plan.source.port_count, plan.target.port_count) == (52, 52)

    def test_the_plan_is_as_well_established_as_its_weaker_side(self, job) -> None:
        """The source is a committed capture; the target rests on HPE's
        documents.  Each pairing carries the weaker of its two ports."""
        plan = job.port_mapping_plan
        assert SOURCE_2930F_48G.evidence == "capture"
        assert plan.evidence == "vendor-doc"
        assert {p.evidence for p in plan.pairings} == {"vendor-doc"}

    def test_no_port_gains_a_slower_or_unpowered_target(self, job) -> None:
        plan = job.port_mapping_plan
        assert not [p for p in plan.pairings if p.slower or p.poe_lost]
        assert not [w for w in job.warnings if w.startswith("port mapping:")]


class TestOntoASmallerSwitch:
    """The same 48-port config onto a 24-port 2930M.  Ports 25-48 have
    nowhere to go; the plan says exactly which, and they are not
    rendered under any name."""

    @pytest.fixture(scope="class")
    def job(self):
        return run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_24G,
        )

    def test_the_plan_names_exactly_the_ports_that_do_not_fit(self, job) -> None:
        plan = job.port_mapping_plan
        assert [p.source for p in plan.unplaced] == _bare(25, 24)
        assert {(p.role, p.reason, p.dropped) for p in plan.unplaced} == {
            ("access", "no-position", True),
        }
        assert len(plan.used_pairings) == 28

    def test_they_are_dropped_not_left_under_their_old_names(self, job) -> None:
        """A port left out of the map would keep the name ``25`` — a
        bare number inside a config whose every other port is ``1/N``,
        and a name a stacked switch does not have."""
        assert job.port_drops == _bare(25, 24)
        assert _hardware_names(job.rendered) == set(TARGET_2930M_24G.names())

    def test_the_uplinks_still_land(self, job) -> None:
        assert [job.port_renames[n] for n in ("49", "50", "51", "52")] == [
            "1/A1", "1/A2", "1/A3", "1/A4",
        ]

    def test_it_is_not_reported_as_a_clean_success(self, job) -> None:
        assert job.status == MigrationJobStatus.partial
        assert "Port mapping is incomplete: 24 port(s)" in job.error
        (warning,) = [w for w in job.warnings if w.startswith("port mapping:")]
        assert "24 source access port(s)" in warning and "DROPPED" in warning

    def test_deciding_every_unplaced_port_makes_it_clean_again(self) -> None:
        """An operator override for a port — here an explicit drop — is
        the operator having looked at it."""
        decided = dict.fromkeys(_bare(25, 24))
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_24G,
            port_rename_map=decided,
        )
        assert job.status == MigrationJobStatus.completed
        assert job.error is None
        assert job.port_mapping_plan.overridden == sorted(decided)
        assert job.port_drops == _bare(25, 24)

    def test_deciding_only_some_leaves_it_partial(self) -> None:
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_24G,
            port_rename_map={"25": None},
        )
        assert job.status == MigrationJobStatus.partial
        assert "23 port(s)" in job.error


class TestNoUplinksOnTheTarget:
    def test_uplinks_are_not_spilled_onto_access_ports(self) -> None:
        """A 2930M with an EMPTY bay has no uplink port.  The 2930F's
        four uplinks are reported and dropped — not put on 1/45-1/48
        or anywhere else by guesswork."""
        target = _device("stacked", {"model": "JL322A", "modules": {"A": None}})
        job = run_plan_with_models(AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, target)
        plan = job.port_mapping_plan
        assert [p.source for p in plan.unplaced] == ["49", "50", "51", "52"]
        assert {p.role for p in plan.unplaced} == {"uplink"}
        assert job.port_drops == ["49", "50", "51", "52"]
        assert _hardware_names(job.rendered) == set(target.names())
        assert job.status == MigrationJobStatus.partial


# ---------------------------------------------------------------------------
# Operator overrides
# ---------------------------------------------------------------------------


class TestOperatorOverridesWin:
    def test_an_override_replaces_the_plans_entry(self) -> None:
        """Positional pairing is a pre-fill.  The operator moves the
        last uplink to a different target port; that is what renders."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G,
            _device("stacked", {"model": "JL322A", "modules": {"A": "JL083A"}}, {"model": "JL319A"}),
            port_rename_map={"52": "2/1"},
        )
        assert job.port_renames["52"] == "2/1"
        assert job.port_renames["51"] == "1/A3"
        assert job.port_mapping_plan.overridden == ["52"]
        # The plan still records what it would have done.
        assert job.port_mapping_plan.rename_map["52"] == "1/A4"

    def test_an_override_for_a_port_outside_the_plan_is_not_counted(self) -> None:
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
            port_rename_map={"Trk9": "Trk1"},
        )
        assert job.port_mapping_plan.overridden == []

    def test_a_dropped_ports_place_is_free(self) -> None:
        """Same model on both sides: every port is paired with its
        namesake and none is spare.  Drop port 5 and its place on
        the target is free -- a dropped port holds nothing."""
        same = _device("standalone", {"model": "JL260A"})
        kept = run_plan_with_models(AOSS, AOSS, CAPTURE_2930F, same, same)
        assert kept.port_mapping_plan.unused_target == []
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, same, same, port_rename_map={"5": None},
        )
        assert job.port_drops == ["5"]
        assert job.port_mapping_plan.unused_target == ["5"]


# ---------------------------------------------------------------------------
# The tripwire for a wrongly declared source
# ---------------------------------------------------------------------------


class TestWrongSourceModel:
    """The config is from a 48-port switch; the operator declares the
    24-port model.  Twenty-four names in the config are not ports of
    that model."""

    @pytest.fixture(scope="class")
    def job(self):
        return run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F,
            _device("standalone", {"model": "JL253A"}), TARGET_2930M_48G,
        )

    def test_the_names_the_model_lacks_are_reported(self, job) -> None:
        assert job.port_mapping_plan.off_inventory == sorted(_bare(29, 24))

    def test_it_is_not_a_clean_success(self, job) -> None:
        assert job.status == MigrationJobStatus.partial
        assert not job.port_mapping_plan.is_clean
        (warning,) = [
            w for w in job.warnings if "not ports of the declared source device" in w
        ]
        assert "24 port name(s)" in warning and "check the source model" in warning

    def test_they_are_not_dropped(self, job) -> None:
        """Off-inventory names are left to the name-shape translator:
        the declaration is what is in doubt, not the config.  Here
        none of them lands on a port the pairing assigned (the
        target's names all carry a member number), so none is lost."""
        assert job.port_drops == []
        assert job.port_mapping_plan.displaced == []
        assert job.port_mapping_plan.unresolved_ports == sorted(_bare(29, 24))

    def test_unless_one_would_land_on_a_port_the_pairing_assigned(self) -> None:
        """The same wrong declaration onto a STANDALONE 48-port 2930F.
        The declared uplinks ``25``-``28`` pair onto ``49``-``52``; the
        real ``49``-``52`` are off-inventory and, left to the
        name-shape translator, would keep those very names.  They
        are dropped instead -- displaced -- so no target port holds
        two source ports."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F,
            _device("standalone", {"model": "JL253A"}),
            _device("standalone", {"model": "JL254A"}),
        )
        plan = job.port_mapping_plan
        assert [job.port_renames[n] for n in ("25", "26", "27", "28")] == [
            "49", "50", "51", "52",
        ]
        assert plan.displaced == ["49", "50", "51", "52"]
        assert job.port_drops == ["49", "50", "51", "52"]
        assert job.status == MigrationJobStatus.partial
        (line,) = [w for w in job.warnings if "nobody decided" in w]
        assert "49, 50, 51, 52" in line and "DROPPED" in line


# ---------------------------------------------------------------------------
# Other deployments
# ---------------------------------------------------------------------------


class TestOtherShapes:
    def test_the_same_model_on_both_sides_changes_nothing(self) -> None:
        """Identity pairing.  ``port_renames`` records only names that
        changed, so it is empty — the plan and ``source_ports`` are how
        a client sees the 52 ports."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, SOURCE_2930F_48G,
        )
        assert job.status == MigrationJobStatus.completed
        assert job.port_renames == {}
        assert len(job.port_mapping_plan.pairings) == 52
        assert sorted(job.source_ports, key=int) == _bare(1, 52)
        assert job.port_mapping_plan.evidence == "capture"

    def test_onto_a_vsf_member_that_is_not_member_one(self) -> None:
        target = _device("vsf", {"model": "JL260A", "id": 3})
        job = run_plan_with_models(AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, target)
        assert job.port_renames["1"] == "3/1"
        assert job.port_renames["52"] == "3/52"
        assert job.port_mapping_plan.is_clean

    def test_the_reverse_corridor(self) -> None:
        """A stacked 2930M back onto a standalone 2930F-48G-4SFP+: the
        member number goes, and the module's ports become 49-52."""
        source = _device(
            "stacked", {"model": "JL323A", "id": 1, "modules": {"A": "JL083A"}},
        )
        target = _device("standalone", {"model": "JL254A"})
        job = run_plan_with_models(AOSS, AOSS, CAPTURE_2930M, source, target)
        plan = job.port_mapping_plan
        assert plan.is_clean and len(plan.used_pairings) == 52
        assert job.port_renames["1/1"] == "1"
        assert [job.port_renames[f"1/A{n}"] for n in (1, 2, 3, 4)] == [
            "49", "50", "51", "52",
        ]
        assert _hardware_names(job.rendered) == set(target.names())
        assert source.evidence == "capture"

    def test_a_faster_port_landing_on_a_slower_one_is_flagged(self) -> None:
        """The JL323A's first eight ports are 10G Smart Rate; a
        2930F-48G's first eight are gigabit."""
        source = _device(
            "stacked", {"model": "JL323A", "id": 1, "modules": {"A": "JL083A"}},
        )
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930M, source, _device("standalone", {"model": "JL254A"}),
        )
        slower = [p.source for p in job.port_mapping_plan.pairings if p.slower]
        assert slower == [f"1/{n}" for n in range(1, 9)]
        assert any("land on a slower target port" in w for w in job.warnings)


# ---------------------------------------------------------------------------
# Flat target profiles as either end
# ---------------------------------------------------------------------------


class TestLegacyProfilesAsDevices:
    """A model no family describes yet can still be declared, through
    its flat target profile — one device, in the one state the profile
    documents."""

    def test_a_profile_works_as_the_target(self) -> None:
        target = inventory_from_profile(PROFILES["aruba_aoss/3810M-48G-PoEP"], "JL083A")
        job = run_plan_with_models(AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, target)
        assert job.port_renames["48"] == "1/48"
        assert job.port_renames["49"] == "1/A1"
        assert job.port_mapping_plan.target.origin == "legacy-profile"
        assert any("list order of a target profile" in w for w in job.warnings)

    def test_cross_vendor_with_a_profile_on_each_side(self) -> None:
        """Catalyst 9300-24UX -> Aruba 3810M-24G.  The access ports
        pair one to one, and a management port is not deleted for want
        of a management interface on AOS-S."""
        ios = get_codec("cisco_iosxe_cli")
        raw = (
            REPO_ROOT / "tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt"
        ).read_text(encoding="utf-8")
        job = run_plan_with_models(
            ios, AOSS, raw,
            inventory_from_profile(PROFILES["cisco_iosxe/C9300-24UX"]),
            inventory_from_profile(PROFILES["aruba_aoss/3810M-24G-PoEP"], "JL083A"),
        )
        plan = job.port_mapping_plan
        assert job.port_renames["TenGigabitEthernet1/0/1"] == "1/1"
        assert job.port_renames["TenGigabitEthernet1/0/24"] == "1/24"
        assert job.port_renames["TenGigabitEthernet1/1/1"] == "1/A1"
        management = [p for p in plan.unplaced if p.role == "mgmt"]
        assert [(p.source, p.dropped) for p in management] == [
            ("GigabitEthernet0/0", False),
        ]
        assert "GigabitEthernet0/0" not in job.port_drops
        assert job.port_renames["GigabitEthernet0/0"] == "oobm"
        assert management[0].landed == "oobm"
        # Kept -- but the target profile lists no management port, and
        # whether the switch has one is not something the plan knows.
        assert "GigabitEthernet0/0" in plan.unresolved_ports
        # 10G multigigabit access ports onto gigabit ones: said, not hidden.
        assert len([p for p in plan.pairings if p.slower]) == 24

    def test_a_name_the_plan_left_alone_cannot_take_an_assigned_port(self) -> None:
        """The same run.  ``AppGigabitEthernet1/0/1`` is not a port of
        the declared source; by name shape it becomes ``1/1`` -- the
        port ``TenGigabitEthernet1/0/1`` was paired onto.  It is
        dropped instead, and the job says so in ``error`` although it
        was already partial for another reason."""
        ios = get_codec("cisco_iosxe_cli")
        raw = (
            REPO_ROOT / "tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt"
        ).read_text(encoding="utf-8")
        job = run_plan_with_models(
            ios, AOSS, raw,
            inventory_from_profile(PROFILES["cisco_iosxe/C9300-24UX"]),
            inventory_from_profile(PROFILES["aruba_aoss/3810M-24G-PoEP"], "JL083A"),
        )
        plan = job.port_mapping_plan
        assert plan.displaced == ["AppGigabitEthernet1/0/1"]
        assert "AppGigabitEthernet1/0/1" in job.port_drops
        assert "AppGigabitEthernet1/0/1" not in job.port_renames
        assert job.port_renames["TenGigabitEthernet1/0/1"] == "1/1"
        assert job.status == MigrationJobStatus.partial
        assert job.error.startswith("Render completed but")
        assert "Port mapping is incomplete:" in job.error
        assert "AppGigabitEthernet1/0/1" in plan.unresolved_ports

    def test_a_catalyst_config_lists_modules_that_are_not_fitted(self) -> None:
        """KNOWN LIMITATION, pinned so it is not mistaken for a clean
        result.  IOS-XE prints the interfaces of EVERY network module
        the chassis could take, whichever one is fitted, plus an
        application-hosting port.  Declared with one module, the other
        modules' names are in the config and not in the inventory, so
        they are reported as off-inventory.  Telling them apart from a
        wrongly declared model needs the Catalyst family data."""
        ios = get_codec("cisco_iosxe_cli")
        raw = (
            REPO_ROOT / "tests/fixtures/real/cisco_iosxe/user_contrib_cat9300_iosxe1712.txt"
        ).read_text(encoding="utf-8")
        job = run_plan_with_models(
            ios, AOSS, raw,
            inventory_from_profile(PROFILES["cisco_iosxe/C9300-24UX"]),
            inventory_from_profile(PROFILES["aruba_aoss/3810M-24G-PoEP"], "JL083A"),
        )
        assert job.port_mapping_plan.off_inventory == [
            "AppGigabitEthernet1/0/1",
            "FortyGigabitEthernet1/1/1", "FortyGigabitEthernet1/1/2",
            "GigabitEthernet1/1/1", "GigabitEthernet1/1/2",
            "GigabitEthernet1/1/3", "GigabitEthernet1/1/4",
            "TwentyFiveGigE1/1/1", "TwentyFiveGigE1/1/2",
        ]

    def test_a_profile_that_lists_no_ports_is_not_modelled(self) -> None:
        """A generic profile with no port list must not read as "a
        device with no ports" — that would drop everything."""
        empty = inventory_from_profile(TargetProfile(vendor="aruba_aoss", model="Generic"))
        job = run_plan_with_models(AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, empty)
        plan = job.port_mapping_plan
        assert plan is not None and not plan.applied
        assert plan.rename_map == {}
        assert job.port_drops == [] and job.port_renames == {}
        assert any("lists no ports" in w for w in job.warnings)
        # Devices were declared and no pairing was made: every name
        # went by name shape, which is what declaring them was for.
        assert job.status == MigrationJobStatus.partial
        assert job.error.startswith("Port mapping was not made: the target device")

    def test_a_plan_that_was_not_made_drops_nothing_of_its_own(self) -> None:
        """Two Junos management ports both become ``oobm`` on AOS-S by
        name shape.  With both devices modelled the second is
        displaced; with no pairing made there is no plan to protect,
        and the output is the ordinary translation's, untouched."""
        junos = get_codec("juniper_junos")
        empty = inventory_from_profile(TargetProfile(vendor="juniper_junos", model="Generic"))
        job = run_plan_with_models(junos, AOSS, _JUNOS_TWO_MGMT, empty, TARGET_2930M_48G)
        plain = run_plan_with_overrides(junos, AOSS, _JUNOS_TWO_MGMT, port_rename_map={})
        plan = job.port_mapping_plan
        assert not plan.applied and plan.displaced == []
        assert plain.port_renames["em0"] == plain.port_renames["em1"] == "oobm"
        assert (job.port_drops, job.port_renames) == (plain.port_drops, plain.port_renames)
        assert job.rendered == plain.rendered


# ---------------------------------------------------------------------------
# It never changes how a failure is reported
# ---------------------------------------------------------------------------


class TestFailuresAreThePipelinesOwn:
    def test_a_parse_failure_is_the_same_failed_job(self, monkeypatch) -> None:
        from netcanon.migration.codecs.base import ParseError

        def boom(_raw):
            raise ParseError("not a config")

        monkeypatch.setattr(AOSS, "parse", boom)
        job = run_plan_with_models(AOSS, AOSS, "x", SOURCE_2930F_48G, TARGET_2930M_48G)
        assert job.status == MigrationJobStatus.failed
        assert job.error == "parse failed: not a config"
        assert job.port_mapping_plan is None

    def test_a_refused_device_class_pair_is_refused_as_before(self, monkeypatch) -> None:
        """The class guard runs before any parse; a refused pair gets
        no plan and no pairing warnings.  No shipped codec pair is
        refused today, so the refusal is forced."""
        refused = SimpleNamespace(compatible=False, reasons=["no class in common"])
        monkeypatch.setattr(migration_pipeline, "check_class_compat", lambda *_: refused)
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
        )
        assert job.status == MigrationJobStatus.failed
        assert job.error.startswith("Device-class guard refused")
        assert job.port_mapping_plan is None and job.rendered is None
        assert not [w for w in job.warnings if w.startswith("port mapping:")]

    def test_input_the_source_codec_does_not_recognise(self) -> None:
        job = run_plan_with_models(
            AOSS, AOSS, "this is not a switch config\n",
            SOURCE_2930F_48G, TARGET_2930M_48G,
        )
        plain = run_plan_with_overrides(
            AOSS, AOSS, "this is not a switch config\n", port_rename_map={},
        )
        assert job.status == plain.status
        assert job.error == plain.error


# ---------------------------------------------------------------------------
# source_ports, with or without models
# ---------------------------------------------------------------------------


class TestSourcePortsAreCaptured:
    def test_every_hardware_port_is_listed_even_when_none_is_renamed(self) -> None:
        """A same-vendor translation renames nothing, so
        ``port_renames`` is empty.  The rename modal used to show "No
        port names recognised" for exactly that reason."""
        job = run_plan_with_overrides(AOSS, AOSS, CAPTURE_2930F, port_rename_map={})
        assert job.port_renames == {}
        assert sorted(job.source_ports, key=int) == _bare(1, 52)

    def test_svis_are_not_hardware_ports(self) -> None:
        """The AOS-S parser gives each routed VLAN an interface named
        ``Vlan<N>``.  It is a name the translator rewrites, and not a
        port a switch model has."""
        tree = AOSS.parse(CAPTURE_2930F)
        every = set(collect_port_names(tree))
        hardware = set(collect_hardware_port_names(tree))
        svis = {n for n in every if n.startswith("Vlan")}
        assert svis and hardware == every - svis

    def test_a_lag_is_not_a_hardware_port_in_either_case(self) -> None:
        """AOS-S prints a trunk as ``trk1`` where it is defined and as
        ``Trk1`` in a VLAN's port list.  Neither spelling is a port;
        the trunk's MEMBERS are."""
        tree = AOSS.parse(_CONFIG_WITH_A_TRUNK)
        every = collect_port_names(tree)
        hardware = collect_hardware_port_names(tree)
        assert {n.lower() for n in every} >= {"trk1", "51", "52"}
        assert not [n for n in hardware if n.lower() == "trk1"]
        assert {"51", "52", "1", "50"} <= set(hardware)

    def test_a_port_named_only_in_a_vlan_list_counts(self) -> None:
        """The 2930F capture has ONE interface stanza; the other 51
        ports appear only in VLAN membership lines."""
        tree = AOSS.parse(CAPTURE_2930F)
        assert len([i for i in tree.interfaces if i.name.isdigit()]) == 1
        assert len(collect_hardware_port_names(tree)) == 52


# ---------------------------------------------------------------------------
# Names the plan does not decide
# ---------------------------------------------------------------------------

_ROUTEROS = """/interface ethernet
set [ find default-name=ether1 ] comment="oob management"
set [ find default-name=sfp-sfpplus1 ] comment="to-core"
/ip address
add address=192.0.2.10/24 interface=ether1
add address=10.0.0.1/30 interface=sfp-sfpplus1
"""

_IOS_BARE_MGMT = """hostname sw
interface GigabitEthernet0/0
 ip address 192.0.2.10 255.255.255.0
!
interface GigabitEthernet1/0/1
 description user
 switchport mode access
 switchport access vlan 10
!
"""

_EOS_MGMT = """hostname sw
interface Management1
   ip address 192.0.2.10/24
!
interface Ethernet1
   description up
!
"""

_IOS_ROUTE_ONLY = """hostname sw
interface GigabitEthernet1/0/1
 description user
!
ip route 10.50.0.0 255.255.0.0 GigabitEthernet1/0/30 10.0.100.254
"""


def _profile(key: str, module: str | None = None) -> Inventory:
    return inventory_from_profile(PROFILES[key], module)


class TestNamesThePlanDoesNotDecide:
    """The pairing decides paired and unplaced data ports.  An unplaced
    management port and an off-inventory name go to the name-shape
    translator -- whose answer may be a port the pairing gave to
    another.  Left unchecked that is two ports fused into one in a job
    that reports success, so the finished run is checked."""

    def test_a_management_port_cannot_take_an_access_ports_name(self) -> None:
        """Two shipped MikroTik profiles.  ``ether1`` is the management
        port of one and the first access port of the other; the first
        SFP+ port is paired onto ``ether1``.  Before the check, both
        addresses ended on one interface and the job was ``completed``."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS,
            _profile("mikrotik_routeros/CCR2004-1G-12S+2XS"),
            _profile("mikrotik_routeros/CRS310-8G+2S+"),
        )
        plan = job.port_mapping_plan
        assert job.port_renames == {"sfp-sfpplus1": "ether1"}
        assert plan.displaced == ["ether1"]
        assert job.port_drops == ["ether1"]
        assert "192.0.2.10" not in job.rendered
        assert job.rendered.count("interface=ether1") == 1
        assert job.status == MigrationJobStatus.partial
        assert plan.unresolved_ports == ["ether1"]

    def test_the_operator_can_place_it_instead(self) -> None:
        """Naming the port in the override map is the operator deciding
        it: it goes where they say and nothing is displaced."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS,
            _profile("mikrotik_routeros/CCR2004-1G-12S+2XS"),
            _profile("mikrotik_routeros/CRS310-8G+2S+"),
            port_rename_map={"ether1": "ether8"},
        )
        assert job.port_renames == {"sfp-sfpplus1": "ether1", "ether1": "ether8"}
        assert job.port_mapping_plan.displaced == []
        assert job.port_drops == []
        assert job.port_mapping_plan.unresolved_ports == []
        assert job.status == MigrationJobStatus.completed

    def test_a_management_port_the_classifier_does_not_know_is_one(self) -> None:
        """A Catalyst ``GigabitEthernet0/0`` with no ``vrf forwarding
        Mgmt-vrf`` line is not stamped as management by the parser, so
        by name shape it becomes port ``1`` of a standalone 2930F --
        where ``GigabitEthernet1/0/1`` was paired."""
        job = run_plan_with_models(
            get_codec("cisco_iosxe_cli"), AOSS, _IOS_BARE_MGMT,
            _profile("cisco_iosxe/C9300-48P"),
            _device("standalone", {"model": "JL260A"}),
        )
        assert job.port_renames == {"GigabitEthernet1/0/1": "1"}
        assert job.port_mapping_plan.displaced == ["GigabitEthernet0/0"]
        assert job.status == MigrationJobStatus.partial

    def test_a_management_port_the_target_cannot_express_is_reported_dropped(self) -> None:
        """RouterOS has no form for a management interface, so the
        name-shape translator drops ``Management1``.  The plan must not
        go on saying the port was kept, and the job is not complete."""
        job = run_plan_with_models(
            get_codec("arista_eos"), get_codec("mikrotik_routeros"), _EOS_MGMT,
            _profile("arista_eos/DCS-7050SX-64"),
            _profile("mikrotik_routeros/CRS310-8G+2S+"),
        )
        plan = job.port_mapping_plan
        assert job.port_drops == ["Management1"]
        (port,) = plan.used_unplaced
        assert (port.source, port.role, port.dropped) == ("Management1", "mgmt", True)
        assert plan.displaced == []
        assert plan.unresolved_ports == ["Management1"]
        assert job.status == MigrationJobStatus.partial
        (line,) = [w for w in job.warnings if "management port(s)" in w]
        assert "DROPPED" in line and "translated by name shape" not in line

    def test_a_port_named_only_by_a_static_route_is_part_of_the_plan(self) -> None:
        """The rename sweep rewrites a route's interface, so the plan
        has to account for it: port 30 of a 48-port switch has no place
        on a 24-port one, and must not survive under its old name."""
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_models(
            ios, ios, _IOS_ROUTE_ONLY,
            _profile("cisco_iosxe/C9300-48P"), _profile("cisco_iosxe/C9300-24P"),
        )
        assert "GigabitEthernet1/0/30" in job.source_ports
        assert job.port_drops == ["GigabitEthernet1/0/30"]
        assert "GigabitEthernet1/0/30" not in job.rendered
        assert job.status == MigrationJobStatus.partial
        # The translator removes a route with the port it names.  That
        # is a loss the port's own line does not mention.
        assert "ip route" not in job.rendered
        assert job.port_mapping_plan.lost_routes == ["10.50.0.0/16"]
        (line,) = [w for w in job.warnings if "static route(s)" in w]
        assert "removed with it: 10.50.0.0/16" in line

    def test_a_logical_interface_is_not_a_port_of_the_wrong_model(self) -> None:
        """An OPNsense tree does not type its interfaces, so ``lo0`` and
        every ``vlan0.N`` used to count as hardware -- and a correctly
        declared firewall was ``partial``, told to check its source
        model.  The codec's own classifier knows they are not ports."""
        opnsense = get_codec("opnsense")
        raw = (
            REPO_ROOT / "tests/fixtures/real/opnsense/user_contrib_supergate_opn25.xml"
        ).read_text(encoding="utf-8")
        device = _profile("opnsense/Protectli-VP6600-IGC-IXL")
        job = run_plan_with_models(opnsense, opnsense, raw, device, device)
        assert job.source_ports == ["igc0", "ixl0"]
        assert job.port_mapping_plan.off_inventory == []
        assert job.status == MigrationJobStatus.completed

    def test_a_lag_left_without_ports_is_named(self) -> None:
        """Both members of the trunk are uplinks; the target has none.
        Dropping them leaves a LAG the renderer cannot emit and a VLAN
        that still refers to it."""
        job = run_plan_with_models(
            AOSS, AOSS, _CONFIG_WITH_A_TRUNK, SOURCE_2930F_48G,
            _device("stacked", {"model": "JL322A", "modules": {"A": None}}),
        )
        plan = job.port_mapping_plan
        assert job.port_drops == ["49", "50", "51", "52"]
        assert [name.lower() for name in plan.emptied_lags] == ["trk1"]
        assert any("every member port of 1 LAG(s) was dropped" in w for w in job.warnings)


class TestOverridesThatDoNotFit:
    """An operator's entry always wins.  What it produces is still
    described truthfully."""

    SAME = _device("standalone", {"model": "JL260A"})

    def test_an_override_onto_a_port_the_pairing_uses(self) -> None:
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, self.SAME,
            port_rename_map={"5": "1"}, expect_fused=True,
        )
        assert job.port_mapping_plan.fused == {"1": ["1", "5"]}
        assert job.status == MigrationJobStatus.partial
        assert "1 target port(s) received more than one source port" in job.error
        assert any("1 <- 1, 5" in w for w in job.warnings)

    def test_naming_both_ports_does_not_make_a_fused_target_complete(self) -> None:
        """Acknowledging a port clears a drop.  It cannot clear two
        ports sharing a name."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, self.SAME,
            port_rename_map={"5": "1", "1": "1"}, expect_fused=True,
        )
        assert job.status == MigrationJobStatus.partial

    def test_an_override_to_a_name_the_target_does_not_have(self) -> None:
        """Allowed -- the operator may know something the model data
        does not -- and said."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, self.SAME,
            port_rename_map={"5": "77"},
        )
        assert job.port_mapping_plan.off_target == ["77"]
        assert job.status == MigrationJobStatus.completed
        assert any("override target(s) are not ports" in w and "77" in w for w in job.warnings)

    def test_keeping_unplaced_ports_under_their_old_names(self) -> None:
        """The rename modal's "keep verbatim" sends ``{port: port}``.
        Onto a 24-port switch that keeps 48 access names; four of them
        are names the uplinks were paired onto.  The plan must not say
        those ports "were DROPPED" when the drop list is empty."""
        keep = {n: n for n in _bare(25, 24)}
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G,
            _device("standalone", {"model": "JL253A"}),
            port_rename_map=keep, expect_fused=True,
        )
        plan = job.port_mapping_plan
        assert job.port_drops == []
        assert not [w for w in job.warnings if "were DROPPED" in w]
        assert sorted(plan.fused) == ["25", "26", "27", "28"]
        assert plan.off_target == _bare(29, 20)
        assert job.status == MigrationJobStatus.partial


class TestWhichNamesAreHardware:
    """``collect_hardware_port_names`` -- the set a mapping is made for."""

    def test_a_port_named_only_by_a_route_counts_when_it_is_recognised(self) -> None:
        """A route's interface is a REFERENCE, not evidence that the
        device has such a port: it counts when the classifier says it
        is a port, or the declared inventory lists it."""
        ios = get_codec("cisco_iosxe_cli")
        tree = ios.parse(_IOS_ROUTE_ONLY)
        both = ["GigabitEthernet1/0/1", "GigabitEthernet1/0/30"]
        assert collect_hardware_port_names(tree) == both[:1]
        assert collect_hardware_port_names(tree, classify=ios.classify_port_name) == both
        assert collect_hardware_port_names(tree, always=both[1:]) == both

    def test_a_positive_classification_takes_a_name_out(self) -> None:
        tree = AOSS.parse(_CONFIG_WITH_A_TRUNK)

        def classify(name: str) -> PortIdentity:
            return PortIdentity(kind="loopback" if name == "50" else "unknown")

        assert "50" in collect_hardware_port_names(tree)
        assert "50" not in collect_hardware_port_names(tree, classify=classify)

    def test_unknown_is_never_grounds_for_leaving_a_name_out(self) -> None:
        """On AOS-S the classifier returns ``unknown`` for a real uplink
        named ``A1`` -- which is why the split is not made on it."""
        tree = AOSS.parse(_CONFIG_WITH_A_TRUNK)
        everything = collect_hardware_port_names(tree)
        assert collect_hardware_port_names(
            tree, classify=lambda _name: PortIdentity(kind="unknown"),
        ) == everything

    def test_a_declared_port_counts_whatever_the_classifier_says(self) -> None:
        """A classifier that misreads a real port must not be able to
        take it out of the set a mapping is made for."""
        tree = AOSS.parse(_CONFIG_WITH_A_TRUNK)
        names = collect_hardware_port_names(
            tree,
            classify=lambda _name: PortIdentity(kind="virtual"),
            always=["1", "2"],
        )
        assert names == ["1", "2"]

    def test_a_classifier_that_raises_cannot_fail_the_read(self) -> None:
        """Fourteen per-vendor classifiers, an arbitrary string from a
        pasted config.  A name one of them chokes on is kept, which is
        what ``unknown`` already means."""
        tree = AOSS.parse(_CONFIG_WITH_A_TRUNK)

        def classify(name: str) -> PortIdentity:
            if name == "50":
                raise ValueError("cannot read this one")
            return PortIdentity(kind="unknown")

        assert "50" in collect_hardware_port_names(tree, classify=classify)

    def test_the_pipeline_protects_a_declared_port_from_its_classifier(self, monkeypatch) -> None:
        """``always=`` is passed: a port of the declared source is part
        of the mapping even if the codec's classifier calls its name
        something else."""
        real = AOSS.classify_port_name
        monkeypatch.setattr(
            AOSS, "classify_port_name",
            lambda name: PortIdentity(kind="virtual") if name == "7" else real(name),
        )
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
        )
        assert job.port_renames["7"] == "1/7"
        assert len(job.port_mapping_plan.used_pairings) == 52


def _tree(**parts) -> CanonicalIntent:
    return CanonicalIntent(**parts)


class TestWhereATreeHoldsPortNames:
    """``collect_port_names`` is the single statement of where a
    canonical tree holds port names.  Each place is pinned, because a
    place missing from it is a name the fusion check never looks at."""

    @pytest.mark.parametrize(
        ("parts", "name"),
        [
            ({"interfaces": [{"name": "p1"}]}, "p1"),
            ({"interfaces": [{"name": "p1", "lag_member_of": "ae0"}]}, "ae0"),
            ({"interfaces": [{"name": "p1", "vrrp_groups": [
                {"group_id": 1, "track_interfaces": ["p9"]}]}]}, "p9"),
            ({"vlans": [{"id": 2, "tagged_ports": ["p2"]}]}, "p2"),
            ({"vlans": [{"id": 2, "untagged_ports": ["p3"]}]}, "p3"),
            ({"lags": [{"name": "ae1", "members": ["p4"]}]}, "ae1"),
            ({"lags": [{"name": "ae1", "members": ["p4"]}]}, "p4"),
            ({"static_routes": [{"destination": "0.0.0.0/0", "interface": "p5"}]}, "p5"),
            ({"dhcp_servers": [{"interface": "p6"}]}, "p6"),
            ({"vxlan_vnis": [{"vni": 10, "vlan_id": 10, "source_interface": "lo0"}]},
             "lo0"),
        ],
    )
    def test_each_place(self, parts: dict, name: str) -> None:
        assert name in collect_port_names(_tree(**parts))

    def test_which_places_are_evidence_of_a_port(self) -> None:
        """An interface stanza, a VLAN list and a LAG member list are
        evidence.  The other places are references: without a
        classifier or an inventory to vouch for them they do not count."""
        tree = _tree(
            interfaces=[{"name": "p1", "lag_member_of": "ae0",
                         "vrrp_groups": [{"group_id": 1, "track_interfaces": ["1"]}]}],
            vlans=[{"id": 2, "tagged_ports": ["p2"], "untagged_ports": ["p3"]}],
            lags=[{"name": "ae1", "members": ["p4"]}],
            static_routes=[{"destination": "0.0.0.0/0", "interface": "Null0"}],
            dhcp_servers=[{"interface": "lan"}],
            vxlan_vnis=[{"vni": 10, "vlan_id": 10, "source_interface": "192.168.100.1"}],
        )
        assert collect_hardware_port_names(tree) == ["p1", "p2", "p3", "p4"]
        physical = collect_hardware_port_names(
            tree, classify=lambda _name: PortIdentity(kind="physical"),
        )
        assert physical == ["p1", "1", "p2", "p3", "p4", "Null0", "lan", "192.168.100.1"]

    def test_the_kinds_and_types_that_are_not_hardware(self) -> None:
        """The membership of both sets, written out: a kind moved from
        one to the other changes which names a mapping is made for."""
        assert {
            "lag", "svi", "loopback", "tunnel", "vtep", "virtual", "hw_aggregate",
        } == NON_HARDWARE_PORT_KINDS
        assert {"physical", "breakout", "mgmt"} == HARDWARE_PORT_KINDS
        assert {
            "ianaift:l3ipvlan", "ianaift:l2vlan", "ianaift:ieee8023adLag",
            "ianaift:softwareLoopback", "ianaift:bridge", "ianaift:tunnel",
        } == NON_HARDWARE_INTERFACE_TYPES

    @pytest.mark.parametrize("kind", sorted(NON_HARDWARE_PORT_KINDS))
    def test_a_positive_non_hardware_kind_takes_evidence_out(self, kind: str) -> None:
        tree = _tree(interfaces=[{"name": "x1"}, {"name": "x2"}])
        names = collect_hardware_port_names(
            tree, classify=lambda name: PortIdentity(kind=kind if name == "x1" else "unknown"),
        )
        assert names == ["x2"]

    @pytest.mark.parametrize("kind", sorted(HARDWARE_PORT_KINDS))
    def test_a_hardware_kind_lets_a_reference_in(self, kind: str) -> None:
        tree = _tree(static_routes=[{"destination": "0.0.0.0/0", "interface": "r1"}])
        assert collect_hardware_port_names(
            tree, classify=lambda _name: PortIdentity(kind=kind),
        ) == ["r1"]

    @pytest.mark.parametrize("iftype", sorted(NON_HARDWARE_INTERFACE_TYPES))
    def test_a_non_hardware_type_takes_an_interface_out(self, iftype: str) -> None:
        tree = _tree(interfaces=[
            {"name": "x1", "interface_type": iftype}, {"name": "x2"},
        ])
        assert collect_hardware_port_names(tree, always=["x1"]) == ["x2"]

    def test_a_lag_named_only_by_its_member_is_not_a_port(self) -> None:
        tree = _tree(interfaces=[{"name": "p1", "lag_member_of": "Bond0"}],
                     vlans=[{"id": 2, "tagged_ports": ["bond0"]}])
        assert collect_hardware_port_names(tree) == ["p1"]


# ---------------------------------------------------------------------------
# Names that are not ports of anything
# ---------------------------------------------------------------------------

_IOS_ROUTES_TO_NOWHERE = """hostname sw
interface GigabitEthernet1/0/1
 description user
!
interface GigabitEthernet1/0/2
 description user2
!
ip route 0.0.0.0 0.0.0.0 dhcp
ip route 10.0.0.0 255.0.0.0 Null0
"""


class TestTokensThatAreNotPorts:
    """A route to ``Null0`` or to the keyword ``dhcp``, a VTEP source
    address, a DHCP pool keyed by a zone name: the rename sweep visits
    those fields, and none of them holds a port.  A correctly declared
    device must not be told to check its source model on their
    account."""

    def test_a_route_to_null0_or_to_dhcp(self) -> None:
        ios = get_codec("cisco_iosxe_cli")
        same = _profile("cisco_iosxe/C9300-48P")
        job = run_plan_with_models(ios, ios, _IOS_ROUTES_TO_NOWHERE, same, same)
        assert job.source_ports == ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"]
        assert job.port_mapping_plan.off_inventory == []
        assert job.status == MigrationJobStatus.completed
        plain = run_plan_with_overrides(ios, ios, _IOS_ROUTES_TO_NOWHERE, port_rename_map={})
        assert plain.source_ports == job.source_ports

    def test_a_vtep_source_address(self) -> None:
        aoscx = get_codec("aruba_aoscx")
        raw = (
            REPO_ROOT / "tests/fixtures/real/aruba_aoscx/aoscx_dcn_arch3_ebgp_leaf1a.cfg"
        ).read_text(encoding="utf-8")
        assert "192.168.100.1" in collect_port_names(aoscx.parse(raw))
        device = _profile("aruba_aoscx/6300M-48G-PoE4-SFP56")
        job = run_plan_with_models(aoscx, aoscx, raw, device, device)
        assert "192.168.100.1" not in job.source_ports
        assert "192.168.100.1" not in job.port_mapping_plan.off_inventory

    def test_every_real_capture_lists_only_names_its_tree_has_evidence_for(self) -> None:
        """Over the committed corpus: a name in ``source_ports`` either
        has an interface stanza, a VLAN membership or a LAG membership,
        or its own codec's classifier calls it a hardware port."""
        checked = 0
        for name in ("cisco_iosxe_cli", "cisco_iosxr", "aruba_aoscx", "opnsense",
                     "arista_eos", "juniper_junos", "aruba_aoss"):
            codec = get_codec(name)
            folder = {"cisco_iosxe_cli": "cisco_iosxe", "juniper_junos": "junos"}.get(name, name)
            for path in sorted((REPO_ROOT / "tests/fixtures/real" / folder).iterdir()):
                if not path.is_file() or path.suffix in {".md"}:
                    continue
                try:
                    tree = codec.parse(path.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    continue
                evidenced = {i.name for i in tree.interfaces}
                for vlan in tree.vlans:
                    evidenced.update(vlan.tagged_ports)
                    evidenced.update(vlan.untagged_ports)
                for lag in tree.lags:
                    evidenced.update(lag.members)
                for port in collect_hardware_port_names(tree, classify=codec.classify_port_name):
                    kind = codec.classify_port_name(port).kind
                    assert port in evidenced or kind in HARDWARE_PORT_KINDS, (path.name, port)
                    checked += 1
        assert checked > 500


# ---------------------------------------------------------------------------
# Logical names, and names that clash only with each other
# ---------------------------------------------------------------------------

_FORTIGATE = """config system interface
    edit "dmz"
        set ip 10.10.10.1 255.255.255.0
        set type physical
    next
    edit "fortilink"
        set ip 10.255.1.1 255.255.255.0
        set type aggregate
        set member "port15" "port16"
    next
end
"""

_JUNOS_TWO_MGMT = """set system host-name sw
set interfaces em0 unit 0 family inet address 192.0.2.10/24
set interfaces em1 unit 0 family inet address 192.0.2.11/24
set interfaces xe-0/0/0 description up
"""


class TestTheCheckLooksAtEveryName:
    """The translator rewrites every name in the tree.  The check for
    two names on one target therefore has to read every name too -- a
    check over only the hardware ports the plan was made for misses an
    aggregate that the source codec's classifier calls a physical
    port."""

    @pytest.mark.parametrize(
        ("codec", "target"),
        [
            ("arista_eos", lambda: _profile("arista_eos/DCS-7050SX-64")),
            ("aruba_aoss", lambda: _device("standalone", {"model": "JL260A"})),
        ],
    )
    def test_an_aggregate_cannot_take_a_paired_ports_name(self, codec, target) -> None:
        """The stock FortiGate ``fortilink`` aggregate is typed as a LAG
        by the parser and called ``physical`` by the classifier.  By
        name shape it becomes the first port of every target -- the
        port ``dmz`` was paired onto."""
        fortigate = get_codec("fortigate_cli")
        job = run_plan_with_models(
            fortigate, get_codec(codec), _FORTIGATE, _profile("fortigate/100E"), target(),
        )
        plan = job.port_mapping_plan
        assert "fortilink" not in job.source_ports      # it is not a hardware port...
        assert plan.displaced == ["fortilink"]           # ...and it is still checked
        assert job.port_drops == ["fortilink"]
        assert "10.255.1.1" not in job.rendered and "10.10.10.1" in job.rendered
        assert job.status == MigrationJobStatus.partial
        assert plan.unresolved_ports == ["fortilink"]

    def test_an_aggregate_cannot_take_a_spare_port_of_the_target_either(self) -> None:
        """Onto Junos the aggregate becomes ``ge-0/0/1``, which nothing
        else holds: not a fusion, and still an aggregate's address on a
        physical port."""
        job = run_plan_with_models(
            get_codec("fortigate_cli"), get_codec("juniper_junos"), _FORTIGATE,
            _profile("fortigate/100E"), _profile("juniper_junos/EX4300-48T"),
        )
        assert job.port_mapping_plan.displaced == ["fortilink"]
        assert job.status == MigrationJobStatus.partial

    def test_the_operator_can_give_the_aggregate_a_name(self) -> None:
        job = run_plan_with_models(
            get_codec("fortigate_cli"), get_codec("arista_eos"), _FORTIGATE,
            _profile("fortigate/100E"), _profile("arista_eos/DCS-7050SX-64"),
            port_rename_map={"fortilink": "Port-Channel1"},
        )
        assert job.port_renames["fortilink"] == "Port-Channel1"
        assert job.port_mapping_plan.displaced == []

    def test_an_operator_decided_name_is_never_displaced(self) -> None:
        """Displacement is for names NOBODY decided.  If the operator
        points the aggregate at the paired port, that is theirs: it is
        done, and reported as a fused target."""
        job = run_plan_with_models(
            get_codec("fortigate_cli"), get_codec("arista_eos"), _FORTIGATE,
            _profile("fortigate/100E"), _profile("arista_eos/DCS-7050SX-64"),
            port_rename_map={"fortilink": "Ethernet1"}, expect_fused=True,
        )
        plan = job.port_mapping_plan
        assert plan.displaced == [] and job.port_drops == []
        assert plan.fused == {"Ethernet1": ["dmz", "fortilink"]}
        assert job.status == MigrationJobStatus.partial

    def test_names_that_clash_only_with_each_other_do_not_all_lose(self) -> None:
        """A Junos EX4600 has two management ports.  Onto AOS-S both
        become ``oobm``.  Nobody decided either, so the first keeps the
        name -- its place was good -- and only the second is dropped.
        Dropping both would lose the management address altogether."""
        job = run_plan_with_models(
            get_codec("juniper_junos"), AOSS, _JUNOS_TWO_MGMT,
            _profile("juniper_junos/EX4600-40F"),
            _device("stacked", {"model": "JL322A", "id": 1, "modules": {"A": "JL083A"}}),
        )
        plan = job.port_mapping_plan
        assert job.port_renames["em0"] == "oobm"
        assert "192.0.2.10" in job.rendered and "192.0.2.11" not in job.rendered
        assert plan.displaced == ["em1"] and job.port_drops == ["em1"]
        assert plan.unresolved_ports == ["em0", "em1"]


class TestTheRuleOnWrittenOutOutcomes:
    """``_undecided_clashes`` on outcomes written out by hand: the
    rule itself, apart from what any codec makes of a name.  Every
    case above reaches the rule through a target port; these are the
    ones that do not."""

    @staticmethod
    def _losers(every, used, merged, renames, drops=(), target=("1", "2")) -> list[str]:
        job = SimpleNamespace(port_renames=dict(renames), port_drops=list(drops))
        return migration_pipeline._undecided_clashes(
            list(every), list(used), dict(merged), job, list(target),
        )

    def test_a_logical_name_sharing_a_name_the_target_does_not_list(self) -> None:
        """The operator sent port ``a`` to a name outside the target
        inventory, and an aggregate nobody decided ends there too.
        ``X`` is no port of the target, so nothing but a comparison
        over EVERY name can see the two together."""
        assert self._losers(
            every=["a", "agg"], used=["a"], merged={"a": "X"},
            renames={"a": "X", "agg": "X"},
        ) == ["agg"]

    def test_a_hardware_port_keeps_the_name_ahead_of_a_logical_one(self) -> None:
        """Nobody decided either name.  The aggregate comes first in
        the config; the port is still the one that keeps the name."""
        assert self._losers(
            every=["agg", "p9"], used=["p9"], merged={},
            renames={"agg": "Y", "p9": "Y"},
        ) == ["agg"]

    def test_every_undecided_name_loses_to_a_decided_one(self) -> None:
        """Three names on one target, one of them decided by the
        operator: both undecided ones lose, in whatever order."""
        assert self._losers(
            every=["agg1", "a", "agg2"], used=["a"], merged={"a": "X"},
            renames={"agg1": "X", "a": "X", "agg2": "X"},
        ) == ["agg1", "agg2"]

    def test_two_logical_names_alone_are_left_as_the_translator_made_them(self) -> None:
        """No hardware port is involved and the shared name is not a
        port of the target: what the ordinary translation does with
        two loopbacks is not this check's to change."""
        assert self._losers(
            every=["lo0", "lo1"], used=[], merged={},
            renames={"lo0": "Z", "lo1": "Z"},
        ) == []

    def test_a_name_already_dropped_clashes_with_nothing(self) -> None:
        assert self._losers(
            every=["a", "agg"], used=["a"], merged={"a": "X"},
            renames={"a": "X", "agg": "X"}, drops=["agg"],
        ) == []

    def test_a_logical_name_left_under_its_own_name_on_a_target_port(self) -> None:
        """The run renamed nothing: the name went through as it was,
        and as it was it is a port of the target."""
        assert self._losers(
            every=["1"], used=[], merged={}, renames={},
        ) == ["1"]


class TestAKeptManagementPort:
    """A management port with no management port in the target model is
    kept by the name-shape translator where the target has a form for
    one.  Whether the target DEVICE has a management interface is not
    something the plan knows -- a 2930F has none -- so the port needs a
    decision, and the job says where it went."""

    CONFIG = """hostname sw
interface GigabitEthernet0/0
 vrf forwarding Mgmt-vrf
 ip address 192.0.2.10 255.255.255.0
!
interface GigabitEthernet1/0/1
 description user
!
"""

    def _run(self, **kwargs) -> MigrationJob:
        return run_plan_with_models(
            get_codec("cisco_iosxe_cli"), AOSS, self.CONFIG,
            _profile("cisco_iosxe/C9300-48P"), _device("standalone", {"model": "JL260A"}),
            **kwargs,
        )

    def test_it_is_kept_and_the_job_is_not_complete(self) -> None:
        job = self._run()
        (port,) = job.port_mapping_plan.used_unplaced
        assert (port.role, port.dropped, port.landed) == ("mgmt", False, "oobm")
        assert "oobm" in job.rendered
        assert job.port_mapping_plan.unresolved_ports == ["GigabitEthernet0/0"]
        assert job.status == MigrationJobStatus.partial
        assert "Unplaced ports were dropped" not in job.error
        (line,) = [w for w in job.warnings if "management port(s)" in w]
        assert "GigabitEthernet0/0 -> oobm" in line

    @pytest.mark.parametrize("answer", ["oobm", None])
    def test_naming_it_is_the_decision(self, answer) -> None:
        job = self._run(port_rename_map={"GigabitEthernet0/0": answer})
        plan = job.port_mapping_plan
        assert plan.unresolved_ports == [] and plan.off_target == []
        assert job.status == MigrationJobStatus.completed
        assert ("oobm" in job.rendered) == (answer is not None)


# ---------------------------------------------------------------------------
# What a dropped port takes with it
# ---------------------------------------------------------------------------


_FORTIGATE_DHCP = """config system interface
    edit "wan1"
        set ip 192.0.2.10 255.255.255.0
        set type physical
    next
    edit "internal1"
        set ip 10.1.0.1 255.255.255.0
        set type physical
    next
end
config system dhcp server
    edit 1
        set default-gateway 10.1.0.1
        set netmask 255.255.255.0
        set interface "internal1"
        config ip-range
            edit 1
                set start-ip 10.1.0.50
                set end-ip 10.1.0.200
            next
        end
    next
end
"""


class TestWhatADroppedPortTakesWithIt:
    def test_a_lag_that_loses_some_members(self) -> None:
        config = _CONFIG_WITH_A_TRUNK.replace("trunk 51-52 trk1", "trunk 48,51 trk1").replace(
            "untagged 1-50", "untagged 1-47,49-50,52",
        )
        job = run_plan_with_models(
            AOSS, AOSS, config, SOURCE_2930F_48G,
            _device("stacked", {"model": "JL322A", "modules": {"A": None}}),
        )
        plan = job.port_mapping_plan
        assert "51" in job.port_drops and "48" not in job.port_drops
        assert [name.lower() for name in plan.shrunk_lags] == ["trk1"]
        assert plan.emptied_lags == []
        assert any("lost a member port" in w for w in job.warnings)

    def test_an_operators_own_drop_reports_its_route_too(self) -> None:
        ios = get_codec("cisco_iosxe_cli")
        same = _profile("cisco_iosxe/C9300-48P")
        job = run_plan_with_models(
            ios, ios, _IOS_ROUTE_ONLY, same, same,
            port_rename_map={"GigabitEthernet1/0/30": None},
        )
        assert job.status == MigrationJobStatus.completed
        assert job.port_mapping_plan.lost_routes == ["10.50.0.0/16"]

    def test_a_dhcp_pool_bound_to_a_dropped_port(self) -> None:
        """The translator removes a pool whose interface is dropped.
        The job lists the port; the plan says the pool went too."""
        fortigate = get_codec("fortigate_cli")
        same = _profile("fortigate/60F")
        kept = run_plan_with_models(fortigate, fortigate, _FORTIGATE_DHCP, same, same)
        assert "config system dhcp server" in kept.rendered
        assert kept.port_mapping_plan.lost_dhcp_pools == []
        job = run_plan_with_models(
            fortigate, fortigate, _FORTIGATE_DHCP, same, same,
            port_rename_map={"internal1": None},
        )
        assert "config system dhcp server" not in job.rendered
        assert job.port_mapping_plan.lost_dhcp_pools == ["10.1.0.0/24"]
        assert any(
            "1 DHCP pool(s) bound to a dropped port were removed with it" in w
            for w in job.warnings
        )

    def test_a_lag_whose_membership_is_stated_on_its_members(self, monkeypatch) -> None:
        """Some trees name a LAG's members only through each member's
        ``lag_member_of``.  The LAG is emptied all the same."""
        tree = AOSS.parse(_CONFIG_WITH_A_TRUNK)
        for lag in tree.lags:
            for member in lag.members:
                tree.interfaces.append(
                    CanonicalInterface(name=member, lag_member_of=lag.name),
                )
            lag.members = []
        assert all(not lag.members for lag in tree.lags)
        real = AOSS.parse
        seen: list[str] = []

        def parse(raw: str):
            seen.append(raw)
            return tree.model_copy(deep=True) if len(seen) == 1 else real(raw)

        monkeypatch.setattr(AOSS, "parse", parse)
        job = migration_pipeline.run_plan_with_models(
            AOSS, AOSS, _CONFIG_WITH_A_TRUNK, SOURCE_2930F_48G,
            _device("stacked", {"model": "JL322A", "modules": {"A": None}}),
        )
        assert [n.lower() for n in job.port_mapping_plan.emptied_lags] == ["trk1"]


# ---------------------------------------------------------------------------
# Sub-interfaces
# ---------------------------------------------------------------------------

_JUNOS_UNITS = (
    REPO_ROOT / "tests/fixtures/real/junos/tsg8139_evpn_leaf_dhcpv6_junos232.set"
).read_text(encoding="utf-8")


class TestSubInterfaces:
    """``ge-0/0/0.54`` is a port of no inventory; its parent is."""

    def test_between_two_configs_of_one_codec_a_unit_follows_its_port(self) -> None:
        """The Junos classifier folds a unit into its port, so the
        name-shape path sends ``ge-0/0/0.54`` and ``ge-0/0/0.55`` both
        onto ``ge-0/0/0``.  With the same model declared on both sides
        each keeps its own name, and so its VLAN id."""
        junos = get_codec("juniper_junos")
        device = _profile("juniper_junos/EX4300-48T")
        job = run_plan_with_models(junos, junos, _JUNOS_UNITS, device, device)
        plan = job.port_mapping_plan
        assert plan.sub_interfaces == {
            name: name for name in
            ("ge-0/0/0.54", "ge-0/0/0.55", "ge-0/0/1.54", "ge-0/0/1.55")
        }
        assert plan.displaced == [] and job.port_drops == []
        assert not [n for n in plan.off_inventory if "." in n]
        assert "set interfaces ge-0/0/0 unit 54 vlan-id 54" in job.rendered
        assert "set interfaces ge-0/0/1 unit 55 vlan-id 55" in job.rendered

    def test_it_follows_where_the_operator_sends_the_port(self) -> None:
        junos = get_codec("juniper_junos")
        device = _profile("juniper_junos/EX4300-48T")
        job = run_plan_with_models(
            junos, junos, _JUNOS_UNITS, device, device,
            port_rename_map={"ge-0/0/0": "ge-0/0/7"},
        )
        assert job.port_mapping_plan.sub_interfaces["ge-0/0/0.54"] == "ge-0/0/7.54"
        assert "set interfaces ge-0/0/7 unit 54 vlan-id 54" in job.rendered
        assert "ge-0/0/0" not in job.rendered

    def test_it_is_dropped_with_a_port_that_is_dropped(self) -> None:
        junos = get_codec("juniper_junos")
        device = _profile("juniper_junos/EX4300-48T")
        job = run_plan_with_models(
            junos, junos, _JUNOS_UNITS, device, device,
            port_rename_map={"ge-0/0/1": None},
        )
        plan = job.port_mapping_plan
        assert plan.sub_interfaces["ge-0/0/1.54"] is None
        assert {"ge-0/0/1", "ge-0/0/1.54", "ge-0/0/1.55"} <= set(job.port_drops)
        assert any("DROPPED with the port they belong to" in w for w in job.warnings)

    def test_the_operators_own_entry_for_a_unit_wins(self) -> None:
        """Following its port is what a unit does when nobody says
        otherwise.  One the operator named goes where they said, and
        is not reported as having followed."""
        junos = get_codec("juniper_junos")
        device = _profile("juniper_junos/EX4300-48T")
        job = run_plan_with_models(
            junos, junos, _JUNOS_UNITS, device, device,
            port_rename_map={"ge-0/0/0.54": None},
        )
        plan = job.port_mapping_plan
        assert job.port_drops == ["ge-0/0/0.54"]
        assert "set interfaces ge-0/0/0 unit 54 vlan-id 54" not in job.rendered
        assert "set interfaces ge-0/0/0 unit 55 vlan-id 55" in job.rendered
        assert sorted(plan.sub_interfaces) == ["ge-0/0/0.55", "ge-0/0/1.54", "ge-0/0/1.55"]
        assert "ge-0/0/0.54" not in plan.unresolved_ports

    def test_across_codecs_a_unit_does_not_follow(self) -> None:
        """Junos to AOS-S: there is no unit suffix to carry over, so
        the units are left to the name-shape translator -- which
        gives all four one and the same name.  Three are dropped,
        in a line that says they are sub-interfaces; none ends on a
        name another interface holds (the wrapper checks that), and
        every one of them still needs a decision."""
        units = ["ge-0/0/0.54", "ge-0/0/0.55", "ge-0/0/1.54", "ge-0/0/1.55"]
        job = run_plan_with_models(
            get_codec("juniper_junos"), AOSS, _JUNOS_UNITS,
            _profile("juniper_junos/EX4300-48T"),
            _device("standalone", {"model": "JL260A"}),
        )
        plan = job.port_mapping_plan
        assert plan.sub_interfaces == {}
        assert len(set(units) & set(plan.displaced)) == 3
        assert set(units) <= set(plan.unresolved_ports)
        assert any(
            "3 sub-interface name(s) could not be given a name of their own" in w
            for w in job.warnings
        )
        assert job.status == MigrationJobStatus.partial


# ---------------------------------------------------------------------------
# An override as it is typed
# ---------------------------------------------------------------------------


class TestAnOverrideAsItIsTyped:
    """An override target is typed by a person or built by a client.  It
    is read as the declared target device spells it."""

    @pytest.mark.parametrize("typed", ["1/a1", " 1/A1", "1/A1 ", "1/A1"])
    def test_another_case_or_a_space_is_still_that_port(self, typed: str) -> None:
        """``49`` is paired onto ``1/A1``.  Sending ``50`` to ``1/a1``
        puts two source ports on one physical port, however it is
        spelt."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
            port_rename_map={"50": typed}, expect_fused=True,
        )
        plan = job.port_mapping_plan
        assert plan.fused == {"1/A1": ["49", "50"]}
        assert plan.off_target == []
        assert job.port_renames["50"] == "1/A1"
        assert job.status == MigrationJobStatus.partial

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_target_decides_nothing(self, blank: str) -> None:
        """An HTML form posts ``""`` for a field nobody touched.  That
        must not clear a drop, and must not render a port with no name."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_24G,
            port_rename_map={"25": blank, **dict.fromkeys(_bare(26, 23))},
        )
        plan = job.port_mapping_plan
        assert plan.ignored_overrides == ["25"]
        assert plan.unresolved_ports == ["25"]
        assert "25" in job.port_drops and "25" not in plan.overridden
        assert job.status == MigrationJobStatus.partial
        assert "untagged ," not in job.rendered and ",," not in job.rendered

    def test_an_entry_for_a_port_the_config_does_not_have(self) -> None:
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
            port_rename_map={"999": "77"},
        )
        assert job.port_mapping_plan.off_target == []
        assert job.status == MigrationJobStatus.completed


class TestTheRunIsRepeatedOnlyWhenItMustBe:
    def test_a_plan_that_could_not_be_made_displaces_nothing(self, monkeypatch) -> None:
        calls: list[dict] = []
        real = migration_pipeline.run_plan_with_overrides

        def spy(**kwargs):
            calls.append(kwargs["port_rename_map"])
            return real(**kwargs)

        monkeypatch.setattr(migration_pipeline, "run_plan_with_overrides", spy)
        empty = inventory_from_profile(TargetProfile(vendor="aruba_aoss", model="Generic"))
        job = migration_pipeline.run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, empty,
        )
        assert calls == [{}]
        assert job.port_drops == [] and job.port_mapping_plan.displaced == []

    def test_a_second_run_that_fails_is_the_job(self, monkeypatch) -> None:
        """Displacement repeats the translation.  If that run does not
        render, its failure is what the caller gets -- not a plan
        attached to a job with no output."""
        real = migration_pipeline.run_plan_with_overrides
        runs: list[int] = []

        def flaky(**kwargs):
            runs.append(1)
            job = real(**kwargs)
            if len(runs) == 2:
                job.rendered = None
                job.status = MigrationJobStatus.failed
                job.error = "render failed"
            return job

        monkeypatch.setattr(migration_pipeline, "run_plan_with_overrides", flaky)
        mikrotik = get_codec("mikrotik_routeros")
        job = migration_pipeline.run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS,
            _profile("mikrotik_routeros/CCR2004-1G-12S+2XS"),
            _profile("mikrotik_routeros/CRS310-8G+2S+"),
        )
        assert len(runs) == 2
        assert job.status == MigrationJobStatus.failed
        assert job.port_mapping_plan is None
