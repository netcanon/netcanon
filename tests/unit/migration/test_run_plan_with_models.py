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

from collections.abc import Iterator
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
    route_port_reference,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.device_models import (
    Deployment,
    Inventory,
    MemberSpec,
    compile_deployment,
    inventory_from_profile,
    load_model_families_dir,
)
from netcanon.migration.port_mapping import plan_port_mapping
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


def _same(codec, name: str) -> str:
    """*name* as *codec*'s platform compares names: with its case
    where the platform has case-sensitive names."""
    text = name.strip()
    return text if getattr(codec, "port_names_case_sensitive", False) else text.casefold()


def _shared_final_names(source, target, raw_text: str, job: MigrationJob) -> dict[str, list[str]]:
    """Final names that more than one source name ended on, where one
    of those names is a hardware port.

    The grouping is written out here rather than imported from the
    engine: the engine's own check once looked only at the names its
    plan was made for, and a test that called the same function over
    the same list had the same blind spot.

    Two logical names the ordinary translation puts on one name (two
    loopbacks, on a target with one loopback form) are left out, as
    the engine leaves them out: that is the translator's own, older
    behaviour, and it warns about it itself.

    The LIST OF NAMES is still the engine's (``collect_port_names``).
    What does not depend on that list is the pair of checks below,
    which read the rendered output.
    """
    dropped = set(job.port_drops)
    hardware = {_same(source, name) for name in job.source_ports}
    ended: dict[str, set[str]] = {}
    for name in collect_port_names(source.parse(raw_text)):
        if name in dropped:
            continue
        final = job.port_renames.get(name, name)
        ended.setdefault(_same(target, final), set()).add(_same(source, name))
    return {
        final: sorted(names) for final, names in ended.items()
        if len(names) > 1 and hardware.intersection(names)
    }


def _text_values(node) -> Iterator[str]:
    """Every text value anywhere in a dumped tree."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _text_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _text_values(value)


def _names_left_behind(source, target, raw_text: str, job: MigrationJob) -> list[str]:
    """Source names that were renamed away or dropped and are STILL in
    the output.

    The output is parsed again with the target codec and every text
    value in it is looked at -- no list of fields, the engine's or
    this file's.  A field the rename pass does not reach, read by a
    renderer, shows up here whatever it is called: RouterOS's factory
    port name did, which the engine's own check could not see because
    its list of places did not have it.

    A moved name may legitimately appear when it is also where some
    surviving name ENDED (``49`` moves to ``25`` while ``25`` is
    dropped) -- or where a port's hardware ended, on a platform that
    keeps that apart from the port's name -- so those are not counted.
    That excuse is also this check's limit: where the moved names are
    a permutation of one another every one of them is a place
    something ended, and it sees nothing.
    :func:`_not_where_the_job_says` is what covers that.
    """
    before = set(_text_values(source.parse(raw_text).model_dump()))
    dropped = set(job.port_drops)
    moved = {
        _same(target, name) for name in dropped | {
            name for name, final in job.port_renames.items() if final != name
        }
    }
    # Compared as the target platform compares names: AOS-S writes a
    # LAG ``trk1`` where it is defined and ``Trk1`` where a VLAN
    # lists it, and that is one name.
    finals = {
        _same(target, job.port_renames.get(text, text))
        for text in before if text not in dropped
    }
    finals.update(
        _same(target, where) for where in job.port_mapping_plan.target_hardware.values()
    )
    finals.update(
        _same(target, where) for where in job.port_mapping_plan.source_hardware.values()
    )
    after = set(_text_values(target.parse(job.rendered).model_dump()))
    return sorted(
        text for text in after
        if _same(target, text) in moved and _same(target, text) not in finals
    )


def _merged_addresses(source, target, raw_text: str, job: MigrationJob) -> dict[str, list[str]]:
    """Output interfaces that carry the addresses of MORE THAN ONE
    source interface -- two interfaces made one, read from the
    rendered output and not from the job's lists."""
    owner: dict[tuple, str] = {}
    for iface in source.parse(raw_text).interfaces:
        for address in (*iface.ipv4_addresses, *iface.ipv6_addresses):
            owner.setdefault((address.ip, address.prefix_length), iface.name)
    merged: dict[str, list[str]] = {}
    for iface in target.parse(job.rendered).interfaces:
        sources = sorted({
            owner[key] for address in (*iface.ipv4_addresses, *iface.ipv6_addresses)
            if (key := (address.ip, address.prefix_length)) in owner
        })
        if len(sources) > 1:
            merged[iface.name] = sources
    return merged


def _shared_hardware(target, job: MigrationJob) -> dict[str, list[str]]:
    """Factory names that more than one interface of the rendered
    output is looked up by: two ports on one piece of hardware under
    two names.  Only a platform that keeps a factory name beside a
    port's own has any (RouterOS)."""
    found: dict[str, set[str]] = {}
    for iface in target.parse(job.rendered).interfaces:
        if iface.default_name:
            found.setdefault(_same(target, iface.default_name), set()).add(iface.name)
    return {where: sorted(names) for where, names in found.items() if len(names) > 1}


def _said(job: MigrationJob, name: str) -> str:
    """Where the job says the port the source config calls *name* is
    on the target: its hardware where the plan records that apart from
    its name, else the name it was given."""
    plan = job.port_mapping_plan
    return plan.target_hardware.get(
        name, plan.source_hardware.get(name, job.port_renames.get(name, name)),
    )


def _not_where_the_job_says(
    source, target, raw_text: str, job: MigrationJob, target_ports: set[str] | None = None,
) -> list[str]:
    """Source interfaces whose config is NOT on the port the job
    says it is on.

    Read from the rendered output.  An interface that carries an
    address no other interface of the source carries is found in the
    output by that address, and the port it is on there -- its factory
    name where the platform keeps one, else its name -- is compared
    with what the job and the plan report.

    This is the check that ties the report to the output.  The two
    below it ask whether an old name is gone; neither asks whether the
    config is where the plan says.  A pairing that was reported and
    never reached the rendered config, or reached it on the wrong
    hardware, fails here whatever names happen to be in the text --
    including when the moved names are a permutation of one another,
    which the old-name check cannot see.

    On a target that finds a port by a factory name, a PAIRED port
    whose output interface has none, under a name that is no port of
    the declared device, is on no hardware at all -- whatever the job
    says of it.  (Given *target_ports*, the declared target's ports;
    without it that case is not judged.)  The engine once rendered
    such a port as "find the port called <the operator's name>" and
    reported exactly that, so comparing report with output agreed.
    The one thing a job may say of such a port is that no line finds
    it by its hardware (``unbound_ports``) -- and then none may.
    """
    unbound = job.port_mapping_plan.unbound_ports
    dropped = set(job.port_drops)
    paired = {pairing.source for pairing in job.port_mapping_plan.used_pairings}
    by_factory = getattr(target, "ports_keep_a_factory_name", False) and target_ports is not None
    owners: dict[tuple, set[str]] = {}
    for iface in source.parse(raw_text).interfaces:
        for address in (*iface.ipv4_addresses, *iface.ipv6_addresses):
            owners.setdefault((address.ip, address.prefix_length), set()).add(iface.name)
    wrong: set[str] = set()
    for iface in target.parse(job.rendered).interfaces:
        on = iface.default_name or iface.name
        for address in (*iface.ipv4_addresses, *iface.ipv6_addresses):
            names = owners.get((address.ip, address.prefix_length), set())
            if len(names) != 1 or names & dropped:
                continue
            (name,) = names
            said = _said(job, name)
            if name in unbound:
                if iface.default_name:
                    wrong.add(
                        f"{name}: the job says no line finds it by its hardware, "
                        f"the output has it on {on}"
                    )
            elif (
                by_factory and name in paired and not iface.default_name
                and _same(target, iface.name) not in target_ports
            ):
                wrong.add(
                    f"{name}: the job says {said}, the output looks it up by "
                    f"the name {iface.name}, which no port of the target has"
                )
            elif _same(target, on) != _same(target, said):
                wrong.add(f"{name}: the job says {said}, the output has it on {on}")
    return sorted(wrong)


def _ports_nobody_reported(source, target, raw_text: str, job: MigrationJob) -> list[str]:
    """Hardware ports in the rendered output that are not where the
    job says ANY source name went.

    The other half of the same tie, for a port that carries no
    address (on AOS-S none does): every port the output names must be
    one the job reports a source name on.  A port left under its
    source name while the job reports it moved is here.
    """
    dropped = set(job.port_drops)
    said = {
        _same(target, job.port_renames.get(name, name))
        for name in collect_port_names(source.parse(raw_text)) if name not in dropped
    }
    said.update(
        _same(target, where) for where in job.port_mapping_plan.target_hardware.values()
    )
    said.update(
        _same(target, where) for where in job.port_mapping_plan.source_hardware.values()
    )
    # A unit the job reports (``ge-0/0/7.54``) brings its port with it.
    said.update(
        name.rpartition(".")[0] for name in list(said)
        if name.rpartition(".")[2].isdigit() and name.rpartition(".")[0]
    )
    tree = target.parse(job.rendered)
    found = set(collect_hardware_port_names(tree, classify=target.classify_port_name))
    found.update(iface.default_name for iface in tree.interfaces if iface.default_name)
    return sorted(name for name in found if _same(target, name) not in said)


def run_plan_with_models(
    *args, expect_fused: bool = False, free_text: tuple[str, ...] = (), **kwargs,
) -> MigrationJob:
    """The real function, with what must hold of EVERY job checked.

    Every test in this module calls the pipeline through here -- but
    for the few that say why they cannot -- so the
    central promise is checked on each run rather than in one test:

    * no hardware port shares a target name with another name the
      config references -- the grouping recomputed here
      (:func:`_shared_final_names`) -- unless the test says the
      operator asked for it;
    * when the operator did, the plan's record names the same targets;
    * a job with a fused target, or with a port nobody decided, is
      not ``completed``;
    * what the plan says happened to an unplaced port is what the
      job's drop list says happened to it;
    * read from the RENDERED OUTPUT, parsed again: every interface
      that can be recognised by its address is on the port the job
      says, and on a port at all (:func:`_not_where_the_job_says`);
      the output names no port
      the job does not report (:func:`_ports_nobody_reported`); no
      name that moved or was dropped is still in it
      (:func:`_names_left_behind`); no interface carries the addresses
      of two source interfaces (:func:`_merged_addresses`); and no two
      interfaces are looked up by one factory name
      (:func:`_shared_hardware`).

    What these can and cannot see is pinned below, in
    ``TestTheChecksOnEveryJobCanFail``: each is handed a job with the
    defect it is for and has to fail.

    *free_text* names a moved name that the output legitimately still
    holds as free text and not as a port: the FortiGate parser names a
    VLAN after its interface, so ``vlan 20 / name DMZ`` survives the
    interface ``DMZ`` being renamed, and should.
    """
    job = migration_pipeline.run_plan_with_models(*args, **kwargs)
    plan = job.port_mapping_plan
    if plan is None or not plan.applied or job.rendered is None:
        return job
    source, target, raw_text = args[0], args[1], args[2]
    declared_target = args[4] if len(args) > 4 else kwargs["target_inventory"]
    target_ports = {_same(target, name) for name in declared_target.names()}
    shared = {
        **_shared_final_names(source, target, raw_text, job),
        **_shared_hardware(target, job),
    }
    if expect_fused:
        assert shared and plan.fused
        assert {_same(target, t) for t in plan.fused} == set(shared)
    else:
        assert shared == {}, f"two names on one target name: {shared}"
        assert plan.fused == {}
        merged = _merged_addresses(source, target, raw_text, job)
        assert merged == {}, f"two source interfaces in one output interface: {merged}"
        elsewhere = _not_where_the_job_says(source, target, raw_text, job, target_ports)
        assert elsewhere == [], f"config is not on the port the job reports: {elsewhere}"
    unreported = _ports_nobody_reported(source, target, raw_text, job)
    assert unreported == [], f"ports in the output that the job does not report: {unreported}"
    left = [
        name for name in _names_left_behind(source, target, raw_text, job)
        if name not in free_text
    ]
    assert left == [], f"names that moved are still in the output: {left}"
    if plan.fused or plan.unresolved_ports or plan.unbound_ports:
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
        assert "Port mapping is incomplete: 24 name(s) in the source config need a decision" in job.error
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
        assert "23 name(s)" in job.error


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


def _find_lines(job: MigrationJob) -> list[str]:
    """The RouterOS lines that look a port up on the device."""
    return [line for line in job.rendered.splitlines() if "find default-name=" in line]


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
        # The line that finds the port on the TARGET names the target's
        # port, not the source's.
        assert _find_lines(job) == ['set [ find default-name=ether1 ] comment="to-core" disabled=no']

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
        # This test once pinned everything above while the output said
        # "find the port called ether1 and name it ether8".
        assert sorted(_find_lines(job)) == [
            'set [ find default-name=ether1 ] comment="to-core" disabled=no',
            'set [ find default-name=ether8 ] comment="oob management" disabled=no',
        ]

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
        assert any(
            "override target(s) are not names the declared target device lists" in w
            and ": 77;" in w for w in job.warnings
        )

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
        """A per-vendor classifier, an arbitrary string from a
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
    """``collect_port_names`` lists the port names a canonical tree
    holds.  Each place it reads is pinned here, because a place missing
    from it is a name the fusion check never looks at.  That pins the
    list against itself; whether the list is COMPLETE is what the
    experiment in ``test_port_name_universe.py`` looks for, as far as
    the committed captures reach."""

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


# ---------------------------------------------------------------------------
# A port with two names (RouterOS)
# ---------------------------------------------------------------------------

_CRS310_CAPTURE = (
    REPO_ROOT / "tests/fixtures/real/mikrotik/user_contrib_crs310_ros7.rsc"
).read_text(encoding="utf-8")

_ROUTEROS_NAMED = """/interface ethernet
set [ find default-name=sfp-sfpplus1 ] name=core-a comment="core A"
set [ find default-name=ether1 ] comment="oob"
/ip address
add address=10.0.0.1/30 interface=core-a
add address=192.0.2.10/24 interface=ether1
"""

_ROUTEROS_PLAIN = """/interface ethernet
set [ find default-name=ether1 ] comment="wan"
set [ find default-name=ether2 ] comment="lan"
/ip address
add address=192.0.2.2/30 interface=ether1
add address=10.0.0.1/24 interface=ether2
"""

_ROUTEROS_NAMED_ROUTE = """/interface ethernet
set [ find default-name=ether1 ] comment="wan"
set [ find default-name=ether2 ] name=core-a comment="core A"
set [ find default-name=sfp-sfpplus1 ] name=uplink
/ip address
add address=192.0.2.2/30 interface=ether1
add address=10.0.0.1/24 interface=core-a
add address=10.1.0.1/24 interface=uplink
/ip route
add dst-address=10.9.0.0/16 gateway=core-a
"""

_ROUTEROS_SWAPPED_NAMES = """/interface ethernet
set [ find default-name=ether1 ] name=ether2 comment="first"
set [ find default-name=ether2 ] name=ether1 comment="second"
/ip address
add address=10.0.1.1/24 interface=ether2
add address=10.0.2.1/24 interface=ether1
"""

_CCR2004 = "mikrotik_routeros/CCR2004-1G-12S+2XS"
_CRS310 = "mikrotik_routeros/CRS310-8G+2S+"


class TestAPortsFactoryName:
    """RouterOS keeps a port's factory name (``ether1``) beside the
    name an operator may have given it, and its renderer finds the
    port on the device by the factory name:
    ``set [ find default-name=ether1 ] ...``.  The factory name is the
    hardware.

    Whether an entry MOVES a port onto other hardware or NAMES it can
    only be told from the declared target, so it is decided here and
    never by the translator: a request that declares no devices
    renders a rename as it always did (``find default-name=ether1 ]
    name=WAN``; pinned in ``test_port_name_universe.py``)."""

    def test_a_real_capture_between_the_two_shipped_models(self) -> None:
        """A committed CRS310 capture, declared as a CRS310, onto the
        CCR2004.  Ten ports move; each line must look up the port the
        pairing chose, and rename nothing.

        The capture names nine of these ports.  It is a verbose
        export that wraps each ``name=`` onto the next line, which
        the parser does not read, so no name survives: a known limit
        of the codec (see its vendor page), not the expectation of
        this test, which is about the lookups."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _CRS310_CAPTURE, _profile(_CRS310), _profile(_CCR2004),
        )
        assert job.status == MigrationJobStatus.completed
        lines = _find_lines(job)
        assert [line.split("default-name=")[1].split(" ")[0] for line in lines] == [
            *(f"sfp-sfpplus{n}" for n in range(1, 9)), "sfp28-1", "sfp28-2",
        ]
        assert not [line for line in lines if " name=" in line]
        assert job.port_mapping_plan.target_hardware == {}

    def test_an_entry_that_is_not_a_port_names_the_port(self) -> None:
        """The operator gives a paired port a name.  ``LAN`` is not a
        port of the CCR2004, so it is what the port is CALLED; the
        hardware still goes where the pairing put it.  Moved with the
        name, the line read ``find default-name=LAN``: a lookup that
        matches no port, in a job that said ``completed``."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PLAIN, _profile(_CRS310), _profile(_CCR2004),
            port_rename_map={"ether2": "LAN"},
        )
        plan = job.port_mapping_plan
        assert sorted(_find_lines(job)) == [
            'set [ find default-name=sfp-sfpplus1 ] comment="wan" disabled=no',
            'set [ find default-name=sfp-sfpplus2 ] name=LAN comment="lan" disabled=no',
        ]
        assert "add address=10.0.0.1/24 interface=LAN" in job.rendered
        assert job.port_renames == {"ether1": "sfp-sfpplus1", "ether2": "LAN"}
        assert plan.target_hardware == {"ether2": "sfp-sfpplus2"}
        # A name is not an off-target port while the hardware has a place.
        assert plan.off_target == []
        assert job.status == MigrationJobStatus.completed
        # It is a decision taken for the operator between two readings
        # of what they typed, so it is said -- for the innocent case too.
        (line,) = [w for w in job.warnings if "taken as NAMES" in w]
        assert "(ether2 is on sfp-sfpplus2)" in line

    @pytest.mark.parametrize(
        "typed", ["sfp-sfpplus13", "SFP-SFPPLUS7", "sfp-sfplus7", "ether5"],
        ids=["one-past-the-last", "another-case", "a-letter-short", "a-port-of-the-source"],
    )
    def test_a_mistyped_port_is_a_name_and_the_plan_says_so(self, typed: str) -> None:
        """None of these is a port of the CCR2004 (RouterOS names are
        kept apart by case), so each NAMES the port, which stays on its
        pairing's hardware.  The job is clean -- and a job that reads
        clean after a typo has to say what it took the typo for."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PLAIN, _profile(_CRS310), _profile(_CCR2004),
            port_rename_map={"ether2": typed},
        )
        assert f"set [ find default-name=sfp-sfpplus2 ] name={typed} " in job.rendered
        assert job.port_mapping_plan.off_target == []
        assert job.status == MigrationJobStatus.completed
        assert [w for w in job.warnings if "taken as NAMES" in w and "ether2 is on sfp-sfpplus2" in w]

    def test_a_name_that_reads_like_a_port_of_another_model_is_still_a_name(self) -> None:
        """``sfp1`` is a port of some RouterOS models and not of this
        one.  Only the declared target can tell, which is why the
        decision is made from its port list and not from the shape of
        the name."""
        mikrotik = get_codec("mikrotik_routeros")
        assert mikrotik.classify_port_name("sfp1").kind == "physical"
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PLAIN, _profile(_CRS310), _profile(_CCR2004),
            port_rename_map={"ether2": "sfp1"},
        )
        assert (
            'set [ find default-name=sfp-sfpplus2 ] name=sfp1 comment="lan" disabled=no'
            in job.rendered
        )

    def test_an_entry_that_is_a_port_of_the_target_moves_the_port(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PLAIN, _profile(_CRS310), _profile(_CCR2004),
            port_rename_map={"ether2": "sfp-sfpplus7"},
        )
        assert sorted(_find_lines(job)) == [
            'set [ find default-name=sfp-sfpplus1 ] comment="wan" disabled=no',
            'set [ find default-name=sfp-sfpplus7 ] comment="lan" disabled=no',
        ]
        assert job.port_mapping_plan.target_hardware == {}

    def test_a_port_the_operator_named_is_still_a_port_of_the_model(self) -> None:
        """``core-a`` is the first SFP+ cage under another name.  With
        the same model on both sides nothing moves, nothing is "not a
        port of the declared source", and the job is complete.  The
        port goes by the config's name everywhere; the plan says which
        port of the model it is."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED, _profile(_CCR2004), _profile(_CCR2004),
        )
        plan = job.port_mapping_plan
        assert job.status == MigrationJobStatus.completed
        assert plan.off_inventory == [] and plan.unresolved_ports == []
        assert plan.labelled_ports == {"core-a": "sfp-sfpplus1"}
        assert sorted(job.source_ports) == ["core-a", "ether1"]
        assert ("core-a", "sfp-sfpplus1") in [(p.source, p.target) for p in plan.used_pairings]
        assert (
            'set [ find default-name=sfp-sfpplus1 ] name=core-a comment="core A" disabled=no'
            in job.rendered
        )

    def test_its_hardware_moves_and_its_name_stays(self) -> None:
        """Onto the CRS310 the cage is paired with ``ether1``.  The
        port is found there by its new factory name and keeps the name
        the operator gave it, which is what the address refers to.
        No NAME changed, so ``port_renames`` has nothing; the plan says
        where the hardware is."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED, _profile(_CCR2004), _profile(_CRS310),
        )
        plan = job.port_mapping_plan
        assert job.port_renames == {}
        assert plan.target_hardware == {"core-a": "ether1"}
        assert _find_lines(job) == [
            'set [ find default-name=ether1 ] name=core-a comment="core A" disabled=no',
        ]
        assert "add address=10.0.0.1/30 interface=core-a" in job.rendered
        # The CCR2004's own management ether1 has no place, and would
        # have been a second port on that hardware under another name:
        # displaced, although the two share no NAME.
        assert plan.displaced == ["ether1"]
        assert "ether1" not in plan.unused_target

    def test_a_named_port_given_another_name_keeps_its_place(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED, _profile(_CCR2004), _profile(_CCR2004),
            port_rename_map={"core-a": "core-b"},
        )
        assert (
            'set [ find default-name=sfp-sfpplus1 ] name=core-b comment="core A" disabled=no'
            in job.rendered
        )
        assert "add address=10.0.0.1/30 interface=core-b" in job.rendered
        assert job.port_mapping_plan.off_target == []
        assert job.status == MigrationJobStatus.completed

    def test_a_named_port_sent_to_a_port_goes_there_under_that_ports_name(self) -> None:
        """An entry whose target IS a port moves the port there, and
        the port is then called what that hardware is called.  The
        hardware must not go one way and the name another: that was a
        port found by one factory name and given another real port's
        name."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED, _profile(_CCR2004), _profile(_CCR2004),
            port_rename_map={"core-a": "sfp-sfpplus3"},
        )
        assert 'set [ find default-name=sfp-sfpplus3 ] comment="core A" disabled=no' in job.rendered
        assert "add address=10.0.0.1/30 interface=sfp-sfpplus3" in job.rendered
        assert "core-a" not in job.rendered

    def test_two_ports_on_one_piece_of_hardware_are_fused(self) -> None:
        """``core-a`` keeps its name and is paired onto ``ether1``; the
        operator sends the management port to ``ether1`` as well.  The
        two share no name -- and the output would look one piece of
        hardware up twice."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED, _profile(_CCR2004), _profile(_CRS310),
            port_rename_map={"ether1": "ether1"}, expect_fused=True,
        )
        assert job.port_mapping_plan.fused == {"ether1": ["ether1", "core-a"]}
        assert job.status == MigrationJobStatus.partial

    def test_onto_another_vendor_a_named_port_is_the_port_it_was_paired_with(self) -> None:
        """Only RouterOS can keep an operator's name beside the
        hardware.  On any other target the name IS the port, so a port
        the operator named takes the name of the port it was paired
        with -- and so does everything that referred to it.  It used to
        be reported as moved while the output still said
        ``interface core-a``, in a job that said ``completed``."""
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        job = run_plan_with_models(
            mikrotik, eos, _ROUTEROS_NAMED_ROUTE,
            _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"),
        )
        plan = job.port_mapping_plan
        assert plan.labelled_ports == {"core-a": "ether2", "uplink": "sfp-sfpplus1"}
        assert job.port_renames == {
            "ether1": "Ethernet1", "core-a": "Ethernet2", "uplink": "Ethernet49/1",
        }
        stanzas = [line for line in job.rendered.splitlines() if line.startswith("interface ")]
        assert stanzas == ["interface Ethernet1", "interface Ethernet2", "interface Ethernet49/1"]
        assert "ip route 10.9.0.0/16 Ethernet2" in job.rendered
        assert "core-a" not in job.rendered and "uplink" not in job.rendered
        assert plan.off_inventory == [] and job.status == MigrationJobStatus.completed

    def test_the_key_of_an_entry_is_the_name_the_config_uses(self) -> None:
        """The plan, the job's lists and an entry's key all speak the
        name the config uses."""
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        job = run_plan_with_models(
            mikrotik, eos, _ROUTEROS_NAMED_ROUTE,
            _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"),
            port_rename_map={"core-a": "Ethernet7"},
        )
        assert "interface Ethernet7" in job.rendered and "interface Ethernet2" not in job.rendered
        assert job.port_mapping_plan.overridden == ["core-a"]

    @pytest.mark.parametrize(
        ("entry", "stanzas", "drops"),
        [
            ({"ether2": "Ethernet7"}, ["Ethernet1", "Ethernet7", "Ethernet49/1"], []),
            ({"ether2": None}, ["Ethernet1", "Ethernet49/1"], ["core-a"]),
        ],
        ids=["a-target", "a-drop"],
    )
    def test_an_entry_keyed_by_the_factory_name_is_taken_for_the_port(
        self, entry: dict, stanzas: list[str], drops: list[str],
    ) -> None:
        """The device model lists ``ether2``; the config calls the
        port ``core-a``.  With devices declared the plan knows which
        port ``ether2`` is, so the entry is taken for it.  Ignored, a
        requested drop was not made and the job said ``completed``."""
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        job = run_plan_with_models(
            mikrotik, eos, _ROUTEROS_NAMED_ROUTE,
            _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"),
            port_rename_map=entry,
        )
        found = [
            line.removeprefix("interface ") for line in job.rendered.splitlines()
            if line.startswith("interface ")
        ]
        assert found == stanzas
        assert job.port_drops == drops
        assert job.port_mapping_plan.overridden == ["core-a"]
        assert not [w for w in job.warnings if "does not exist in the parsed config" in w]

    def test_a_factory_key_beside_the_ports_own_name_is_not_guessed_at(self) -> None:
        """Both keys for one port: the config's name decides, and the
        other entry matches nothing, which the translator says."""
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        job = run_plan_with_models(
            mikrotik, eos, _ROUTEROS_NAMED_ROUTE,
            _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"),
            port_rename_map={"core-a": "Ethernet7", "ether2": "Ethernet9"},
        )
        assert job.port_renames["core-a"] == "Ethernet7"
        assert "Ethernet9" not in job.rendered
        assert any(
            "source port 'ether2' does not exist in the parsed config" in w
            for w in job.warnings
        )

    def test_without_devices_a_factory_key_matches_nothing(self) -> None:
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        job = run_plan_with_overrides(
            mikrotik, eos, _ROUTEROS_NAMED_ROUTE, port_rename_map={"ether2": None},
        )
        assert job.port_drops == []
        assert "interface core-a" in job.rendered

    def test_a_name_that_is_a_port_of_the_target_is_not_kept(self) -> None:
        """The operator had swapped the names of two ports, and both
        are paired onto SFP+ cages of a CCR2004.  That device has a
        port ``ether1``: a port that carried ``ether1`` as a mere name
        could only be THAT port there, so it takes its paired port's
        name instead, like a port with no name of its own.  It has no
        ``ether2``, so there ``ether2`` is only a name, and is kept."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_SWAPPED_NAMES, _profile(_CRS310), _profile(_CCR2004),
        )
        plan = job.port_mapping_plan
        assert plan.labelled_ports == {"ether2": "ether1", "ether1": "ether2"}
        assert sorted(_find_lines(job)) == [
            'set [ find default-name=sfp-sfpplus1 ] name=ether2 comment="first" disabled=no',
            'set [ find default-name=sfp-sfpplus2 ] comment="second" disabled=no',
        ]
        assert "add address=10.0.1.1/24 interface=ether2" in job.rendered
        assert "add address=10.0.2.1/24 interface=sfp-sfpplus2" in job.rendered
        assert job.port_renames == {"ether1": "sfp-sfpplus2"}
        assert plan.target_hardware == {"ether2": "sfp-sfpplus1"}

    def test_a_port_named_like_another_port_cannot_be_told_apart(self) -> None:
        """``ether1`` is called ``ether2`` and the config says nothing
        of the real ``ether2``.  A name then no longer says which port
        is meant, and no pairing is made rather than a wrong one."""
        mikrotik = get_codec("mikrotik_routeros")
        job = migration_pipeline.run_plan_with_models(
            mikrotik, mikrotik,
            "/interface ethernet\nset [ find default-name=ether1 ] name=ether2\n"
            "/ip address\nadd address=10.0.1.1/24 interface=ether2\n",
            _profile(_CRS310), _profile(_CCR2004),
        )
        plan = job.port_mapping_plan
        assert plan.applied is False
        assert job.status == MigrationJobStatus.partial
        assert "the name another port of the source device has (ether2)" in job.error

    def test_the_two_names_of_one_port_in_a_tree(self) -> None:
        tree = _tree(interfaces=[
            {"name": "core-a", "default_name": "ether2"},
            {"name": "ether1", "default_name": "ether1"},
        ])
        # The names the CONFIG uses.  The factory name of a port the
        # operator named is not one of them: nothing refers to the port
        # by it, and an entry keyed by it matches nothing.
        assert collect_port_names(tree) == ["core-a", "ether1"]
        assert collect_hardware_port_names(tree) == ["core-a", "ether1"]


# ---------------------------------------------------------------------------
# A name the translator drops on its own
# ---------------------------------------------------------------------------

_IOS_AUTODROP = """hostname sw
!
interface GigabitEthernet1/0/5
 description KEEPME
 switchport mode access
 switchport access vlan 10
!
interface TenGigabitEthernet1/0/5
 vrf forwarding Mgmt-vrf
 ip address 192.0.2.5 255.255.255.0
!
end
"""


class TestANameTheTranslatorDropsOnItsOwn:
    def test_it_does_not_take_a_paired_port_with_it(self) -> None:
        """``TenGigabitEthernet1/0/5`` is not a port of the declared
        C9300-48P and is in the management VRF; IOS-XE has no form for
        a management port, so the translator drops it.  The pairing put
        ``GigabitEthernet1/0/5`` ON that name.  The drop used to be
        applied by name after the renames, and took both."""
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_models(
            ios, ios, _IOS_AUTODROP,
            _profile("cisco_iosxe/C9300-48P"), _profile("cisco_iosxe/C9300-24UX"),
        )
        assert job.port_renames == {"GigabitEthernet1/0/5": "TenGigabitEthernet1/0/5"}
        assert job.port_drops == ["TenGigabitEthernet1/0/5"]
        assert job.rendered.count("interface TenGigabitEthernet1/0/5") == 1
        assert "description KEEPME" in job.rendered
        assert "192.0.2.5" not in job.rendered
        assert job.port_mapping_plan.off_inventory == ["TenGigabitEthernet1/0/5"]
        assert job.status == MigrationJobStatus.partial
        # One port was dropped and one kept: nothing was merged, and the
        # translator must not say that something was.
        assert not [w for w in job.warnings if "multiple source ports map to" in w]


# ---------------------------------------------------------------------------
# Letter case
# ---------------------------------------------------------------------------

_FORTIGATE_CASE = """config system interface
    edit "dmz"
        set ip 10.10.10.1 255.255.255.0
        set type physical
    next
    edit "port1"
        set ip 10.1.1.1 255.255.255.0
        set type physical
    next
    edit "DMZ"
        set ip 10.20.20.1 255.255.255.0
        set interface "port1"
        set vlanid 20
    next
end
"""


class TestCaseIsAFactAboutThePlatform:
    """On AOS-S ``1/a1`` is the port ``1/A1``.  On FortiOS ``DMZ`` and
    ``dmz`` are two interfaces.  Each codec says which its platform is."""

    def test_the_codecs_say_which_they_are(self) -> None:
        """There is no safe default, so no codec may leave it to one:
        each states the rule in its own class body.  ``True`` only
        where an operator chooses interface names as free text and
        case keeps them apart."""
        undecided = sorted(
            name for name in list_public_codecs()
            if "port_names_case_sensitive" not in vars(type(get_codec(name)))
        )
        assert undecided == []
        sensitive = {
            name for name in list_public_codecs()
            if get_codec(name).port_names_case_sensitive
        }
        assert sensitive == {"fortigate_cli", "mikrotik_routeros"}

    def test_a_misspelt_port_is_the_port_where_the_system_names_every_interface(self) -> None:
        """Junos names are case-sensitive, and that is the wrong
        question: every interface name is the system's, in lower case,
        so ``GE-0/0/2`` is never a second interface.  Taken as typed it
        came out as one, beside ``ge-0/0/2``, in a job that said
        ``completed``."""
        junos = get_codec("juniper_junos")
        same = _profile("juniper_junos/EX4300-48T")
        job = run_plan_with_models(
            junos, junos,
            "set interfaces ge-0/0/1 unit 0 family inet address 10.0.1.1/24\n"
            "set interfaces ge-0/0/2 unit 0 family inet address 10.0.2.1/24\n",
            same, same, port_rename_map={"ge-0/0/1": "GE-0/0/2"}, expect_fused=True,
        )
        assert job.port_mapping_plan.fused == {"ge-0/0/2": ["ge-0/0/1", "ge-0/0/2"]}
        assert "GE-0/0/2" not in job.rendered
        assert job.status == MigrationJobStatus.partial

    def test_a_target_is_stripped_where_it_is_taken_as_typed(self) -> None:
        """On a platform with case the target is not re-spelt, and
        surrounding space is still not part of a name."""
        fortigate = get_codec("fortigate_cli")
        same = _profile("fortigate/100E")
        job = run_plan_with_models(
            fortigate, fortigate, _FORTIGATE_CASE, same, same,
            port_rename_map={"port1": " dmz "}, expect_fused=True,
        )
        assert job.port_mapping_plan.fused == {"dmz": ["dmz", "port1"]}

    def test_an_interface_kept_under_its_own_name_is_not_turned_into_a_port(self) -> None:
        """A VLAN interface ``DMZ`` beside the physical ``dmz``, and the
        operator keeps it as it is.  Read without case that entry named
        the PORT: one interface came out, and the other's address was
        gone, in a job that said ``completed``."""
        fortigate = get_codec("fortigate_cli")
        same = _profile("fortigate/100E")
        job = run_plan_with_models(
            fortigate, fortigate, _FORTIGATE_CASE, same, same,
            port_rename_map={"DMZ": "DMZ"},
        )
        assert 'edit "dmz"' in job.rendered and 'edit "DMZ"' in job.rendered
        assert "10.10.10.1" in job.rendered and "10.20.20.1" in job.rendered
        assert job.port_renames == {}
        assert job.port_mapping_plan.fused == {}
        assert job.status == MigrationJobStatus.completed

    def test_sending_one_onto_the_other_is_two_interfaces_on_one_name(self) -> None:
        """The same two interfaces, and this time the operator does
        point ``DMZ`` at ``dmz``.  They are two source interfaces, not
        two spellings of one, so this is a fused target and the job is
        not a clean success -- the contract for every override."""
        fortigate = get_codec("fortigate_cli")
        same = _profile("fortigate/100E")
        job = run_plan_with_models(
            fortigate, fortigate, _FORTIGATE_CASE, same, same,
            port_rename_map={"DMZ": "dmz"}, expect_fused=True,
        )
        assert job.port_mapping_plan.fused == {"dmz": ["dmz", "DMZ"]}
        assert job.status == MigrationJobStatus.partial

    def test_where_case_is_not_part_of_a_name_two_spellings_are_still_one_port(self) -> None:
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
            port_rename_map={"52": "1/a1"}, expect_fused=True,
        )
        assert job.port_mapping_plan.fused == {"1/A1": ["49", "52"]}
        assert job.status == MigrationJobStatus.partial

    def test_the_rule_with_and_without_case(self) -> None:
        """An aggregate that ends on ``SFP1`` beside a target port
        ``sfp1``: the same port where case does not count, another
        name where it does."""
        job = SimpleNamespace(port_renames={"agg": "SFP1"}, port_drops=[])
        arguments = (["agg", "p1"], ["p1"], {"p1": "sfp2"}, job, ["sfp1", "sfp2"])
        assert migration_pipeline._undecided_clashes(*arguments) == ["agg"]
        assert migration_pipeline._undecided_clashes(*arguments, fold_target=False) == []


# ---------------------------------------------------------------------------
# A next hop that is an interface
# ---------------------------------------------------------------------------

_JUNOS_NEXT_HOP = """set system host-name sw
set interfaces et-0/0/24 unit 0 family inet address 10.0.0.1/30
set interfaces xe-0/0/1 unit 0 family inet address 10.1.0.1/24
set routing-options static route 0.0.0.0/0 next-hop et-0/0/24.0
"""

_JUNOS_NEXT_HOP_DROPPED = """set system host-name sw
set interfaces xe-0/0/30 unit 0 family inet address 10.30.0.1/24
set interfaces xe-0/0/1 unit 0 family inet address 10.1.0.1/24
set routing-options static route 10.30.0.0/16 next-hop xe-0/0/30.0
set routing-options static route 0.0.0.0/0 next-hop 10.1.0.254
"""

_ROUTEROS_NEXT_HOPS = """/interface ethernet
set [ find default-name=sfp28-1 ] comment="wan"
set [ find default-name=sfp-sfpplus1 ] comment="lan"
/ip address
add address=192.0.2.2/30 interface=sfp28-1
add address=10.9.0.1/24 interface=sfp-sfpplus1
/ip route
add dst-address=0.0.0.0/0 gateway=sfp28-1
add dst-address=10.9.0.0/16 gateway=sfp-sfpplus1
"""


class TestANextHopThatIsAnInterface:
    """Junos ``next-hop et-0/0/24.0`` and RouterOS ``gateway=ether1``
    put an interface name where an address usually is.  The route
    follows its interface, and goes with it when it is dropped."""

    def test_a_junos_route_follows_the_port(self) -> None:
        junos = get_codec("juniper_junos")
        job = run_plan_with_models(
            junos, junos, _JUNOS_NEXT_HOP,
            _profile("juniper_junos/EX4600-40F"), _profile("juniper_junos/QFX5120-48Y"),
        )
        assert job.port_renames == {"et-0/0/24": "et-0/0/48"}
        assert "static route 0.0.0.0/0 next-hop et-0/0/48.0" in job.rendered
        assert "et-0/0/24" not in job.rendered

    def test_a_junos_route_goes_with_a_dropped_port_and_is_listed(self) -> None:
        junos = get_codec("juniper_junos")
        job = run_plan_with_models(
            junos, junos, _JUNOS_NEXT_HOP_DROPPED,
            _profile("juniper_junos/QFX5120-48Y"), _profile("juniper_junos/EX4600-40F"),
        )
        plan = job.port_mapping_plan
        assert job.port_drops == ["xe-0/0/30"]
        assert plan.lost_routes == ["10.30.0.0/16"]
        assert "10.30.0.0/16" not in job.rendered
        assert "static route 0.0.0.0/0 next-hop 10.1.0.254" in job.rendered

    def test_routeros_gateways_follow_their_ports(self) -> None:
        """The two ports change places, more or less: before the fix
        ``gateway=sfp-sfpplus1`` was left naming the port the UPLINK had
        been paired onto -- a real port, and the wrong one."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NEXT_HOPS, _profile(_CCR2004), _profile(_CRS310),
        )
        assert job.port_renames == {"sfp-sfpplus1": "ether1", "sfp28-1": "sfp-sfpplus1"}
        assert "add dst-address=0.0.0.0/0 gateway=sfp-sfpplus1" in job.rendered
        assert "add dst-address=10.9.0.0/16 gateway=ether1" in job.rendered

    def test_an_address_is_never_taken_for_an_interface(self) -> None:
        def reference(gateway: str, names: set[str], units: bool = True):
            return route_port_reference(SimpleNamespace(gateway=gateway), names, units=units)

        assert reference("10.0.0.1", {"ether1", "10.0.0.2"}) is None
        assert reference("", {"ether1"}) is None
        assert reference("ether1", {"ether1"}) == ("ether1", "")
        assert reference("et-0/0/24.0", {"et-0/0/24"}) == ("et-0/0/24", ".0")
        assert reference("et-0/0/24.0", {"et-0/0/24"}, units=False) is None
        assert reference("et-0/0/24.x", {"et-0/0/24"}) is None


# ---------------------------------------------------------------------------
# What else a dropped port takes
# ---------------------------------------------------------------------------

_IOS_TRACK = """hostname sw
!
interface GigabitEthernet1/0/30
 description uplink
!
interface Vlan10
 ip address 10.10.0.2 255.255.255.0
 vrrp 20 ip 10.10.0.1
 vrrp 20 track GigabitEthernet1/0/30 decrement 20
!
end
"""

_IOS_TUNNEL_ROUTE = """hostname sw
!
interface GigabitEthernet1/0/1
 description user
!
interface Tunnel0
 ip address 10.255.0.1 255.255.255.252
!
ip route 10.8.0.0 255.255.0.0 Tunnel0
!
end
"""

_EOS_VTEP = """hostname leaf
!
interface Ethernet1
   description up
!
interface Loopback0
   ip address 10.255.0.1/32
!
interface Vxlan1
   vxlan source-interface Loopback0
   vxlan udp-port 4789
   vxlan vlan 10 vni 10010
!
vlan 10
!
end
"""


class TestWhatElseADroppedPortTakes:
    def test_a_vrrp_track_entry_on_an_interface_that_stays(self) -> None:
        """Port 30 has no place on a 24-port switch.  ``Vlan10`` stays,
        and its VRRP group no longer tracks anything -- which the job
        used to leave for the operator to find."""
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_models(
            ios, ios, _IOS_TRACK,
            _profile("cisco_iosxe/C9300-48P"), _profile("cisco_iosxe/C9300-24P"),
        )
        plan = job.port_mapping_plan
        assert job.port_drops == ["GigabitEthernet1/0/30"]
        assert "interface Vlan10" in job.rendered and "track" not in job.rendered
        assert plan.lost_tracking == ["Vlan10"]
        assert any(
            "1 interface(s) lost a VRRP track entry with what it named" in w
            and "Vlan10" in w for w in job.warnings
        )

    def test_nothing_is_listed_when_the_tracked_port_has_a_place(self) -> None:
        ios = get_codec("cisco_iosxe_cli")
        same = _profile("cisco_iosxe/C9300-48P")
        job = run_plan_with_models(ios, ios, _IOS_TRACK, same, same)
        assert job.port_mapping_plan.lost_tracking == []
        assert "vrrp 20 track GigabitEthernet1/0/30" in job.rendered

    def test_a_vtep_source(self) -> None:
        """The operator drops the loopback the VTEP is bound to.

        Called without the wrapper on purpose: the Arista renderer
        writes its default source name, ``Loopback0``, when the binding
        is empty, so the dropped name IS still in the output -- which
        is exactly why the plan has to say the source is gone."""
        eos = get_codec("arista_eos")
        same = _profile("arista_eos/DCS-7050SX-64")
        job = migration_pipeline.run_plan_with_models(
            eos, eos, _EOS_VTEP, same, same, port_rename_map={"Loopback0": None},
        )
        assert job.port_mapping_plan.lost_vtep_sources == ["Loopback0"]
        assert "interface Loopback0" not in [
            line.strip() for line in job.rendered.splitlines()
        ]
        assert any("the VXLAN source interface was dropped (Loopback0)" in w for w in job.warnings)

    def test_a_lag_no_member_of_which_was_parsed_is_not_emptied(self) -> None:
        """A LAG with no members cannot have lost them all."""
        tree = _tree(lags=[{"name": "fortilink", "members": []}])
        _dropped, taken = migration_pipeline._taken_with_dropped_ports(tree, ["port1"])
        assert taken["emptied_lags"] == [] and taken["shrunk_lags"] == []

    def test_members_are_counted_from_what_the_run_dropped(self) -> None:
        """...not from what a map asked for: a member the translator
        dropped on its own shrinks the LAG just the same."""
        tree = _tree(lags=[{"name": "Trk1", "members": ["51", "52"]}])
        _dropped, taken = migration_pipeline._taken_with_dropped_ports(tree, ["52"])
        assert taken["shrunk_lags"] == ["Trk1"] and taken["emptied_lags"] == []
        _dropped, taken = migration_pipeline._taken_with_dropped_ports(tree, ["51", "52"])
        assert taken["emptied_lags"] == ["Trk1"]

    def test_a_port_is_dropped_by_the_name_the_config_uses(self) -> None:
        tree = _tree(
            interfaces=[{"name": "core-a", "default_name": "ether2"}],
            static_routes=[{"destination": "10.0.0.0/8", "gateway": "core-a"}],
            dhcp_servers=[{"interface": "core-a", "network": "10.1.0.0/24"}],
        )
        dropped, taken = migration_pipeline._taken_with_dropped_ports(tree, ["core-a"])
        assert dropped == {"core-a"}
        assert taken["lost_routes"] == ["10.0.0.0/8"]
        assert taken["lost_dhcp_pools"] == ["10.1.0.0/24"]
        # Its factory name is not a key: nothing in the config goes by it.
        _dropped, taken = migration_pipeline._taken_with_dropped_ports(tree, ["ether2"])
        assert taken["lost_routes"] == [] and taken["lost_dhcp_pools"] == []

    def test_what_a_drop_took_is_read_from_the_run_not_from_the_map(self) -> None:
        """Nobody asked for the tunnel to go: the translator dropped
        it because the target cannot express one.  Its route went with
        it all the same, and the plan has to say so."""
        job = run_plan_with_models(
            get_codec("cisco_iosxe_cli"), AOSS, _IOS_TUNNEL_ROUTE,
            _profile("cisco_iosxe/C9300-48P"), _device("standalone", {"model": "JL260A"}),
        )
        assert "Tunnel0" in job.port_drops
        assert job.port_mapping_plan.lost_routes == ["10.8.0.0/16"]

    def test_a_vtep_source_that_stays_is_not_listed(self) -> None:
        eos = get_codec("arista_eos")
        same = _profile("arista_eos/DCS-7050SX-64")
        job = run_plan_with_models(
            eos, eos, _EOS_VTEP, same, same, port_rename_map={"Ethernet1": None},
        )
        assert job.port_drops == ["Ethernet1"]
        assert job.port_mapping_plan.lost_vtep_sources == []

    def test_an_interface_that_went_did_not_lose_its_tracking(self) -> None:
        """``lost_tracking`` is about an interface that STAYS and no
        longer follows the port it tracked."""
        tree = _tree(interfaces=[
            {"name": "Vlan10", "vrrp_groups": [{"group_id": 1, "track_interfaces": ["p30"]}]},
            {"name": "Vlan20", "vrrp_groups": [{"group_id": 2, "track_interfaces": ["p30"]}]},
            {"name": "p30"},
        ])
        _dropped, taken = migration_pipeline._taken_with_dropped_ports(tree, ["p30", "Vlan20"])
        assert taken["lost_tracking"] == ["Vlan10"]


# ---------------------------------------------------------------------------
# Smaller rules
# ---------------------------------------------------------------------------

_IOS_TWO_MGMT = """hostname sw
!
interface GigabitEthernet0/1
 vrf forwarding Mgmt-vrf
 ip address 192.0.2.11 255.255.255.0
!
interface GigabitEthernet0/0
 vrf forwarding Mgmt-vrf
 ip address 192.0.2.10 255.255.255.0
!
interface GigabitEthernet1/0/1
 description user
!
end
"""

_IOS_ONE_MGMT = """hostname sw
!
interface GigabitEthernet0/0
 vrf forwarding Mgmt-vrf
 ip address 192.0.2.10 255.255.255.0
!
interface GigabitEthernet1/0/1
 description user
!
end
"""

_IOS_TWO_PORTS = """hostname sw
!
interface GigabitEthernet1/0/1
 description one
!
interface GigabitEthernet1/0/2
 description two
!
end
"""


class TestSmallerRules:
    def test_the_declared_devices_own_port_keeps_a_name_nobody_decided(self) -> None:
        """Two management ports, both ``oobm`` by name shape.  The one
        the config writes first is not a port of the declared C9300;
        the device's own port keeps the name all the same."""
        job = run_plan_with_models(
            get_codec("cisco_iosxe_cli"), AOSS, _IOS_TWO_MGMT,
            _profile("cisco_iosxe/C9300-48P"), TARGET_2930M_48G,
        )
        assert job.port_renames["GigabitEthernet0/0"] == "oobm"
        assert job.port_mapping_plan.displaced == ["GigabitEthernet0/1"]
        assert "192.0.2.10" in job.rendered and "192.0.2.11" not in job.rendered

    def test_only_the_targets_own_form_for_a_management_port_is_exempt(self) -> None:
        """``oobm`` is where AOS-S keeps a management port, and naming
        it is not "a target the device does not list".  Keeping the
        port under its Cisco name is."""
        ios = get_codec("cisco_iosxe_cli")
        source = _profile("cisco_iosxe/C9300-48P")
        named = run_plan_with_models(
            ios, AOSS, _IOS_ONE_MGMT, source, TARGET_2930M_48G,
            port_rename_map={"GigabitEthernet0/0": "oobm"},
        )
        assert named.port_mapping_plan.off_target == []
        assert named.status == MigrationJobStatus.completed
        kept = run_plan_with_models(
            ios, AOSS, _IOS_ONE_MGMT, source, TARGET_2930M_48G,
            port_rename_map={"GigabitEthernet0/0": "GigabitEthernet0/0"},
        )
        assert kept.port_mapping_plan.off_target == ["GigabitEthernet0/0"]

    def test_a_target_that_is_not_text_is_set_aside(self) -> None:
        """Neither a name nor a drop.  Passed on, it replaced the
        pairing's entry with nothing and the port kept its old name."""
        ios = get_codec("cisco_iosxe_cli")
        job = run_plan_with_models(
            ios, AOSS, _IOS_TWO_PORTS,
            _profile("cisco_iosxe/C9300-48P"), TARGET_2930M_48G,
            port_rename_map={"GigabitEthernet1/0/2": 7},
        )
        plan = job.port_mapping_plan
        assert plan.ignored_overrides == ["GigabitEthernet1/0/2"] and plan.overridden == []
        assert job.port_renames["GigabitEthernet1/0/2"] == "1/2"

    def test_an_abbreviated_target_is_reported_but_not_recognised(self) -> None:
        """A limit, pinned so it is not mistaken for a guarantee:
        ``Gi1/0/1`` is the port ``GigabitEthernet1/0/1`` to the device
        and a different name to netcanon.  The job is ``completed``;
        what it says is that the name is not one the model lists, and
        that it may be another spelling of a port."""
        ios = get_codec("cisco_iosxe_cli")
        same = _profile("cisco_iosxe/C9300-48P")
        job = run_plan_with_models(
            ios, ios, _IOS_TWO_PORTS, same, same,
            port_rename_map={"GigabitEthernet1/0/2": "Gi1/0/1"},
        )
        plan = job.port_mapping_plan
        assert plan.off_target == ["Gi1/0/1"] and plan.fused == {}
        assert job.status == MigrationJobStatus.completed
        (line,) = [w for w in job.warnings if "override target(s)" in w]
        assert "it may share that port with the source port already paired to it" in line

    def test_a_unit_suffix_is_a_number(self) -> None:
        plan = SimpleNamespace(
            off_inventory=["ether1.backup", "ge-0/0/0.54", "ge-0/0/0."],
            rename_map={"ether1": "sfp1", "ge-0/0/0": "ge-0/0/5"},
        )
        names = dict(plan.rename_map)
        assert migration_pipeline._sub_interface_followers(plan, {}, names) == {
            "ge-0/0/0.54": "ge-0/0/5.54",
        }

    def test_a_unit_of_a_port_that_keeps_its_name_keeps_its_own(self) -> None:
        """The parent's NAME on the target is what a unit follows.  A
        port an operator named keeps that name while its hardware
        moves, so its unit keeps its name too."""
        plan = SimpleNamespace(
            off_inventory=["core-a.100"], rename_map={"core-a": "sfp-sfpplus2"},
        )
        assert migration_pipeline._sub_interface_followers(
            plan, {}, {"core-a": "core-a"},
        ) == {"core-a.100": "core-a.100"}
        assert migration_pipeline._sub_interface_followers(
            plan, {"core-a": "wan"}, {"core-a": "core-a"},
        ) == {"core-a.100": "wan.100"}

    def test_an_ignored_entry_for_a_name_the_config_lacks_is_not_listed(self) -> None:
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
            port_rename_map={"999": "", "7": " "},
        )
        assert job.port_mapping_plan.ignored_overrides == ["7"]

    def test_a_logical_name_an_operator_put_on_a_port_occupies_it(self) -> None:
        """``unused_target`` is the ports still free.  A port the
        operator gave to an aggregate is not one of them."""
        job = run_plan_with_models(
            get_codec("fortigate_cli"), get_codec("arista_eos"), _FORTIGATE,
            _profile("fortigate/100E"), _profile("arista_eos/DCS-7050SX-64"),
            port_rename_map={"fortilink": "Ethernet9"},
        )
        unused = job.port_mapping_plan.unused_target
        assert "Ethernet9" not in unused and "Ethernet10" in unused


# ---------------------------------------------------------------------------
# A logical name on a port the target does not have
# ---------------------------------------------------------------------------


class TestALogicalNameOnAPortTheTargetLacks:
    """The complement of "a logical name ended on a port of the
    target".  A VLAN interface the FortiGate codec reads as a physical
    port is formatted as one for the target.  Where the target has that
    port the name is displaced.  Where it has not, nothing collides --
    and the interface's address is on a port the declared device does
    not have, which used to be ``completed`` with nothing said."""

    def test_it_is_listed_and_asks_for_a_decision(self) -> None:
        job = run_plan_with_models(
            get_codec("fortigate_cli"), get_codec("cisco_iosxe_cli"), _FORTIGATE_CASE,
            _profile("fortigate/100E"), _profile("cisco_iosxe/C9300-24P"),
            free_text=("DMZ",),
        )
        plan = job.port_mapping_plan
        assert " name DMZ" in job.rendered.splitlines()
        assert plan.landed_off_target == {"DMZ": "GigabitEthernet0/1"}
        assert "GigabitEthernet0/1" not in _profile("cisco_iosxe/C9300-24P").names()
        # Nothing shares the name, so it is not dropped.
        assert plan.displaced == [] and job.port_drops == []
        assert plan.unresolved_ports == ["DMZ"]
        assert job.status == MigrationJobStatus.partial
        assert any(
            "were given a port name the declared target device does not list "
            "(DMZ -> GigabitEthernet0/1)" in w for w in job.warnings
        )

    def test_between_two_devices_of_one_model_as_well(self) -> None:
        fortigate = get_codec("fortigate_cli")
        same = _profile("fortigate/100E")
        job = run_plan_with_models(fortigate, fortigate, _FORTIGATE_CASE, same, same)
        assert job.port_mapping_plan.landed_off_target == {"DMZ": "dmz1"}
        assert job.status == MigrationJobStatus.partial

    def test_the_operator_deciding_it_clears_it(self) -> None:
        job = run_plan_with_models(
            get_codec("fortigate_cli"), get_codec("cisco_iosxe_cli"), _FORTIGATE_CASE,
            _profile("fortigate/100E"), _profile("cisco_iosxe/C9300-24P"),
            port_rename_map={"DMZ": "Vlan20"}, free_text=("DMZ",),
        )
        plan = job.port_mapping_plan
        assert plan.landed_off_target == {} and plan.unresolved_ports == []
        assert job.status == MigrationJobStatus.completed

    def test_a_logical_name_given_the_targets_own_form_is_where_it_belongs(self) -> None:
        """A LAG that becomes the target's LAG name is not a landing
        on a port: only a name the target codec reads as a physical
        port counts."""
        job = SimpleNamespace(
            port_renames={"Port-channel1": "ae0", "Vlan10": "irb.10"}, port_drops=[],
        )
        junos = get_codec("juniper_junos")
        assert migration_pipeline._unlisted_landings(
            ["Port-channel1", "Vlan10", "p1"], ["p1"], {"p1": "ge-0/0/1"}, job,
            get_codec("cisco_iosxe_cli"), junos, ["ge-0/0/1"], True,
        ) == {}

    def test_a_classifier_that_raises_cannot_fail_the_job(self) -> None:
        def explode(_name: str):
            raise RuntimeError("no")

        job = SimpleNamespace(port_renames={"agg": "ge-0/0/9"}, port_drops=[])
        broken = SimpleNamespace(classify_port_name=explode)
        assert migration_pipeline._unlisted_landings(
            ["agg"], [], {}, job, broken, broken, ["ge-0/0/1"], True,
        ) == {}


# ---------------------------------------------------------------------------
# A next hop the rewrite does not reach
# ---------------------------------------------------------------------------

_ROUTEROS_HOP_FORMS = """/interface ethernet
set [ find default-name=ether1 ] comment="a"
set [ find default-name=ether2 ] comment="b"
set [ find default-name=ether3 ] comment="c"
set [ find default-name=ether4 ] comment="d"
/ip address
add address=192.0.2.2/30 interface=ether1
add address=192.0.2.6/30 interface=ether2
add address=192.0.2.10/30 interface=ether3
add address=192.0.2.14/30 interface=ether4
/ip route
add dst-address=0.0.0.0/0 gateway=ether1,ether2
add dst-address=10.23.0.0/16 gateway=ether3@main
add dst-address=10.24.0.0/16 gateway=ether4
add dst-address=10.25.0.0/16 gateway=192.0.2.1
"""


class TestANextHopTheRewriteDoesNotReach:
    """A next hop that is exactly an interface name follows the
    interface.  A list of them, a routing-table suffix, and -- across
    vendors -- a unit of an interface are left as written.  The job
    used to be ``completed`` with the route still naming a port that
    had moved; it now says which routes, and is ``partial``."""

    def test_a_list_and_a_table_suffix_are_reported(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_HOP_FORMS, _profile(_CRS310), _profile(_CCR2004),
        )
        plan = job.port_mapping_plan
        assert "gateway=ether1,ether2" in job.rendered
        assert "gateway=ether3@main" in job.rendered
        # The plain one followed, and an address is never a port.
        assert "dst-address=10.24.0.0/16 gateway=sfp-sfpplus4" in job.rendered
        assert plan.stale_next_hops == ["0.0.0.0/0", "10.23.0.0/16"]
        assert not plan.is_clean
        assert job.status == MigrationJobStatus.partial
        assert "2 static route(s) still name, as next hop" in job.error
        assert any("0.0.0.0/0, 10.23.0.0/16" in w for w in job.warnings)

    def test_nothing_is_reported_while_the_named_ports_stay_where_they_are(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        same = _profile(_CRS310)
        job = run_plan_with_models(mikrotik, mikrotik, _ROUTEROS_HOP_FORMS, same, same)
        assert job.port_mapping_plan.stale_next_hops == []
        assert job.status == MigrationJobStatus.completed

    def test_a_dropped_port_in_a_list_is_reported_too(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        same = _profile(_CRS310)
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_HOP_FORMS, same, same,
            port_rename_map={"ether2": None},
        )
        assert job.port_mapping_plan.stale_next_hops == ["0.0.0.0/0"]

    def test_across_vendors_a_unit_of_an_interface(self) -> None:
        """``next-hop xe-0/0/1.0`` means unit 0 of the port only on
        Junos, so onto another vendor it is not rewritten -- and is now
        said.  Dropped, the route goes with its port and is listed
        there instead."""
        junos, eos = get_codec("juniper_junos"), get_codec("arista_eos")
        text = _JUNOS_NEXT_HOP.replace("et-0/0/24", "xe-0/0/3")
        devices = (_profile("juniper_junos/QFX5120-48Y"), _profile("arista_eos/DCS-7050SX-64"))
        job = run_plan_with_models(junos, eos, text, *devices)
        plan = job.port_mapping_plan
        assert job.port_renames["xe-0/0/3"] != "xe-0/0/3"
        assert "ip route 0.0.0.0/0 xe-0/0/3.0" in job.rendered
        assert plan.stale_next_hops == ["0.0.0.0/0"]
        assert job.status == MigrationJobStatus.partial
        job = run_plan_with_models(
            junos, eos, text, *devices, port_rename_map={"xe-0/0/3": None},
        )
        plan = job.port_mapping_plan
        assert plan.stale_next_hops == [] and plan.lost_routes == ["0.0.0.0/0"]

    def test_a_route_that_went_with_its_interface_is_not_stale(self) -> None:
        tree = _tree(
            interfaces=[{"name": "p1"}, {"name": "p2"}],
            static_routes=[
                {"destination": "10.0.0.0/8", "interface": "p1", "gateway": "p2,p1"},
                {"destination": "10.1.0.0/16", "gateway": "p2 , p9"},
                {"destination": "10.2.0.0/16", "gateway": "192.0.2.1"},
            ],
        )
        job = SimpleNamespace(port_renames={"p2": "q2"}, port_drops=["p1"])
        assert migration_pipeline._stale_next_hops(tree, job, True, {}) == ["10.1.0.0/16"]


# ---------------------------------------------------------------------------
# More small rules
# ---------------------------------------------------------------------------


class TestMoreSmallRules:
    def test_the_management_form_in_another_case_is_the_form(self) -> None:
        """``OOBM`` used to be exempt from the off-target report (the
        comparison folds case) and not re-spelt, so the output carried
        ``interface OOBM`` instead of the ``oobm`` block, with nothing
        reported."""
        job = run_plan_with_models(
            get_codec("cisco_iosxe_cli"), AOSS, _IOS_ONE_MGMT,
            _profile("cisco_iosxe/C9300-48P"), TARGET_2930M_48G,
            port_rename_map={"GigabitEthernet0/0": "OOBM"},
        )
        assert job.port_renames["GigabitEthernet0/0"] == "oobm"
        lines = [line.strip() for line in job.rendered.splitlines()]
        assert "oobm" in lines and "interface OOBM" not in lines
        assert job.port_mapping_plan.off_target == []

    def test_a_unit_of_a_port_of_the_target_is_not_off_target(self) -> None:
        junos = get_codec("juniper_junos")
        device = _profile("juniper_junos/EX4300-48T")
        job = run_plan_with_models(
            junos, junos, _JUNOS_UNITS, device, device,
            port_rename_map={"ge-0/0/0.54": "ge-0/0/7.54"},
        )
        assert job.port_renames["ge-0/0/0.54"] == "ge-0/0/7.54"
        assert job.port_mapping_plan.off_target == []

    def test_dropped_ports_are_mentioned_only_when_an_undecided_one_was(self) -> None:
        """The operator dropped a port themselves, and a kept
        management port still asks for a decision.  Nothing that needs
        deciding was dropped, so the job's sentence must not say
        "unplaced ports were dropped"."""
        job = run_plan_with_models(
            get_codec("cisco_iosxe_cli"), AOSS, _IOS_ONE_MGMT,
            _profile("cisco_iosxe/C9300-48P"), TARGET_2930M_48G,
            port_rename_map={"GigabitEthernet1/0/1": None},
        )
        assert job.port_drops == ["GigabitEthernet1/0/1"]
        assert job.port_mapping_plan.unresolved_ports == ["GigabitEthernet0/0"]
        assert "need a decision" in job.error
        assert "Unplaced ports were dropped" not in job.error


# ---------------------------------------------------------------------------
# The checks made on every job can fail
# ---------------------------------------------------------------------------


class TestTheChecksOnEveryJobCanFail:
    """Every test above calls the pipeline through a wrapper that
    reads the rendered output back.  A check nobody has seen fail is
    not known to check anything: each is handed, here, a job with the
    defect it is for.  Each defect is one this change really had."""

    def _two_routeros_ports_exchanged(self) -> tuple[MigrationJob, MigrationJob]:
        """A job that MOVES two ports onto each other's hardware, and
        the output an entry that merely NAMES them produces -- which
        is what the first job rendered while the factory name was left
        behind: ``find default-name=ether1 ] name=ether2``."""
        mikrotik = get_codec("mikrotik_routeros")
        same = _profile(_CRS310)
        swap = {"ether1": "ether2", "ether2": "ether1"}
        moved = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PLAIN, same, same, port_rename_map=swap,
        )
        named = run_plan_with_overrides(mikrotik, mikrotik, _ROUTEROS_PLAIN, port_rename_map=swap)
        return moved, named

    def test_hardware_left_behind_under_a_permutation(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        moved, named = self._two_routeros_ports_exchanged()
        assert "set [ find default-name=ether2 ] comment=\"wan\"" in moved.rendered
        assert _not_where_the_job_says(mikrotik, mikrotik, _ROUTEROS_PLAIN, moved) == []
        assert "set [ find default-name=ether1 ] name=ether2" in named.rendered
        moved.rendered = named.rendered
        assert _not_where_the_job_says(mikrotik, mikrotik, _ROUTEROS_PLAIN, moved) == [
            "ether1: the job says ether2, the output has it on ether1",
            "ether2: the job says ether1, the output has it on ether2",
        ]
        # The limit of the old-name check, shown rather than asserted
        # in prose: both moved names are also places something ended.
        assert _names_left_behind(mikrotik, mikrotik, _ROUTEROS_PLAIN, moved) == []

    def test_a_pairing_that_never_reached_the_output(self) -> None:
        """Reported as ``core-a -> Ethernet2`` while the config still
        said ``interface core-a``."""
        mikrotik, eos = get_codec("mikrotik_routeros"), get_codec("arista_eos")
        job = run_plan_with_models(
            mikrotik, eos, _ROUTEROS_NAMED_ROUTE,
            _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"),
        )
        job.rendered = job.rendered.replace("interface Ethernet2\n", "interface core-a\n")
        assert _ports_nobody_reported(mikrotik, eos, _ROUTEROS_NAMED_ROUTE, job) == ["core-a"]
        assert _not_where_the_job_says(mikrotik, eos, _ROUTEROS_NAMED_ROUTE, job) == [
            "core-a: the job says Ethernet2, the output has it on core-a",
        ]

    def test_a_port_with_no_address_left_under_its_old_name(self) -> None:
        """On AOS-S no hardware port carries an address, so the
        address check cannot see one.  The port list can."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
        )
        assert _ports_nobody_reported(AOSS, AOSS, CAPTURE_2930F, job) == []
        job.rendered = job.rendered.replace("1/A1", "49")
        assert _ports_nobody_reported(AOSS, AOSS, CAPTURE_2930F, job) == ["49"]
        assert _names_left_behind(AOSS, AOSS, CAPTURE_2930F, job) == ["49"]

    def test_two_interfaces_made_one(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PLAIN, _profile(_CRS310), _profile(_CCR2004),
        )
        assert _merged_addresses(mikrotik, mikrotik, _ROUTEROS_PLAIN, job) == {}
        job.rendered = job.rendered.replace("interface=sfp-sfpplus2", "interface=sfp-sfpplus1")
        assert _merged_addresses(mikrotik, mikrotik, _ROUTEROS_PLAIN, job) == {
            "sfp-sfpplus1": ["ether1", "ether2"],
        }

    def test_two_ports_looked_up_by_one_factory_name(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED, _profile(_CCR2004), _profile(_CCR2004),
        )
        assert _shared_hardware(mikrotik, job) == {}
        job.rendered = job.rendered.replace(
            "find default-name=ether1 ]", "find default-name=sfp-sfpplus1 ] name=oob",
        )
        assert _shared_hardware(mikrotik, job) == {"sfp-sfpplus1": ["core-a", "oob"]}

    def test_the_wrapper_itself_refuses_a_fused_job(self) -> None:
        """If the wrapper returned before its checks, every test in
        this module would still pass.  This one would not."""
        with pytest.raises(AssertionError, match="two names on one target name"):
            run_plan_with_models(
                AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G,
                port_rename_map={"52": "1/A1"},
            )

    def test_the_wrapper_refuses_a_job_whose_output_is_not_what_it_reports(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The whole wrapper, on an engine that reports a move and
        does not make it."""
        real = migration_pipeline.run_plan_with_models

        def reports_and_does_not_move(*args, **kwargs) -> MigrationJob:
            job = real(*args, **kwargs)
            job.rendered = job.rendered.replace("interface Ethernet2\n", "interface core-a\n")
            return job

        monkeypatch.setattr(migration_pipeline, "run_plan_with_models", reports_and_does_not_move)
        with pytest.raises(AssertionError, match="not on the port the job reports"):
            run_plan_with_models(
                get_codec("mikrotik_routeros"), get_codec("arista_eos"), _ROUTEROS_NAMED_ROUTE,
                _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"),
            )


# ---------------------------------------------------------------------------
# A port the operator named, in the places a name is read
# ---------------------------------------------------------------------------

_ROUTEROS_NAMED_MGMT = """/interface ethernet
set [ find default-name=ether1 ] name=oob-mgmt comment="oob"
set [ find default-name=sfp-sfpplus1 ] comment="up"
/ip address
add address=192.0.2.10/24 interface=oob-mgmt
add address=10.0.0.1/30 interface=sfp-sfpplus1
"""

_ROUTEROS_NAMED_LIKE_A_LAG = """/interface ethernet
set [ find default-name=ether1 ] comment="wan"
set [ find default-name=ether2 ] name=bond1 comment="was a bond once"
/ip address
add address=192.0.2.2/30 interface=ether1
add address=10.0.0.1/24 interface=bond1
"""


class TestANamedPortWhereANameIsRead:
    def test_a_named_management_port_is_read_by_what_it_is(self) -> None:
        """The CCR2004's management port, called ``oob-mgmt``, onto a
        switch whose model lists no management port.  The form the
        target gives a management port is worked out from the port's
        factory name -- the label says nothing about what the port is
        -- so an override that names that form, in any case, is the
        ``oobm`` block and is not off-target."""
        mikrotik = get_codec("mikrotik_routeros")
        target = _device("standalone", {"model": "JL260A"})
        job = run_plan_with_models(
            mikrotik, AOSS, _ROUTEROS_NAMED_MGMT, _profile(_CCR2004), target,
        )
        plan = job.port_mapping_plan
        assert plan.labelled_ports == {"oob-mgmt": "ether1"}
        assert plan.unresolved_ports == ["oob-mgmt"]
        assert job.status == MigrationJobStatus.partial
        job = run_plan_with_models(
            mikrotik, AOSS, _ROUTEROS_NAMED_MGMT, _profile(_CCR2004), target,
            port_rename_map={"oob-mgmt": "OOBM"},
        )
        assert job.port_renames["oob-mgmt"] == "oobm"
        assert job.port_mapping_plan.off_target == []
        assert job.status == MigrationJobStatus.completed

    def test_a_name_that_reads_like_a_lag_is_still_the_port(self) -> None:
        """``bond1`` reads as a LAG to the RouterOS codec.  The port
        is a port of the declared device whatever it is called, so it
        counts as used and is paired.  What the output then makes of
        that name is ``TestAPortTheOutputDoesNotLookUp``."""
        mikrotik = get_codec("mikrotik_routeros")
        assert mikrotik.classify_port_name("bond1").kind == "lag"
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED_LIKE_A_LAG, _profile(_CRS310), _profile(_CCR2004),
        )
        plan = job.port_mapping_plan
        assert plan.labelled_ports == {"bond1": "ether2"}
        assert ("bond1", "sfp-sfpplus2") in [(p.source, p.target) for p in plan.used_pairings]
        assert plan.off_inventory == []

    def test_a_port_of_the_source_is_not_a_logical_name_on_a_stray_port(self) -> None:
        """A hardware name the config uses that ends on a port-shaped
        name the target lacks is an off-inventory port, reported as
        that.  The landing list is for LOGICAL names only."""
        job = SimpleNamespace(
            port_renames={"p9": "ge-0/0/9", "DMZ": "ge-0/0/8", "agg": "GE-0/0/1"}, port_drops=[],
        )
        # ``agg`` ended on a port the target HAS (in another case, on a
        # platform where that is the same port): that is the other
        # rule's to deal with, not a landing on a port that is absent.
        junos = get_codec("juniper_junos")
        assert migration_pipeline._unlisted_landings(
            ["p9", "DMZ", "agg"], ["p9"], {}, job, junos, junos, ["ge-0/0/1"], True,
        ) == {"DMZ": "ge-0/0/8"}


# ---------------------------------------------------------------------------
# Every port the mapping placed is found by the hardware it is on
# ---------------------------------------------------------------------------

_EOS_TWO_ROUTED_PORTS = """hostname sw
!
interface Ethernet1
   description wan
   no switchport
   ip address 192.0.2.1/24
!
interface Ethernet2
   description lan
   no switchport
   ip address 10.0.0.1/24
!
end
"""

#: A RouterOS config whose SFP ports are named by an address line and
#: by nothing else: the parser records a factory name only for a port
#: with an ``/interface ethernet`` line, or one called ``etherN``.
_ROUTEROS_PORTS_WITH_NO_ETHERNET_LINE = """/interface ethernet
set [ find default-name=ether1 ] comment="oob"
/ip address
add address=192.0.2.9/24 interface=ether1
add address=10.66.0.1/24 interface=sfp-sfpplus1
add address=10.67.0.1/24 interface=sfp-sfpplus2
/ip route
add dst-address=0.0.0.0/0 gateway=sfp-sfpplus1
"""

_ROUTEROS_AN_UNLISTED_PORT = """/interface ethernet
set [ find default-name=ether1 ] comment="wan"
set [ find default-name=ether9 ] comment="not on a CRS310"
/ip address
add address=192.0.2.2/30 interface=ether1
add address=10.9.0.1/24 interface=ether9
"""

_ROUTEROS_A_NAMED_NINTH_CAGE = """/interface ethernet
set [ find default-name=ether1 ] comment="oob"
set [ find default-name=sfp-sfpplus9 ] name=spare9 comment="ninth"
/ip address
add address=192.0.2.9/24 interface=ether1
add address=10.9.0.1/24 interface=spare9
"""


class TestEveryPlacedPortIsFoundByItsHardware:
    """A RouterOS target finds a port by its factory name, and the
    plan knows which port of the target every paired port is on --
    whatever vendor the config came from, and whether or not the
    source config happened to state a factory name for the port.

    The rule was first applied only between two RouterOS configs, and
    only to an interface the parser had recorded a factory name for.
    Anywhere else an entry that NAMES a port rendered
    ``set [ find name=WAN ]``: a lookup by a name no device has, in a
    job that said ``completed``."""

    def test_a_port_from_another_vendor(self) -> None:
        eos, mikrotik = get_codec("arista_eos"), get_codec("mikrotik_routeros")
        devices = (_profile("arista_eos/DCS-7050SX-64"), _profile(_CCR2004))
        job = run_plan_with_models(eos, mikrotik, _EOS_TWO_ROUTED_PORTS, *devices)
        assert _find_lines(job) == [
            'set [ find default-name=sfp-sfpplus1 ] comment="wan" disabled=no',
            'set [ find default-name=sfp-sfpplus2 ] comment="lan" disabled=no',
        ]
        assert job.port_mapping_plan.target_hardware == {}

    def test_a_port_from_another_vendor_that_the_operator_names(self) -> None:
        eos, mikrotik = get_codec("arista_eos"), get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            eos, mikrotik, _EOS_TWO_ROUTED_PORTS,
            _profile("arista_eos/DCS-7050SX-64"), _profile(_CCR2004),
            port_rename_map={"Ethernet1": "WAN"},
        )
        plan = job.port_mapping_plan
        assert 'set [ find default-name=sfp-sfpplus1 ] name=WAN comment="wan" disabled=no' in job.rendered
        assert "find name=" not in job.rendered
        assert "add address=192.0.2.1/24 interface=WAN" in job.rendered
        assert plan.target_hardware == {"Ethernet1": "sfp-sfpplus1"}
        assert plan.off_target == []
        assert job.status == MigrationJobStatus.completed

    def test_a_port_the_source_config_states_no_factory_name_for(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        tree = mikrotik.parse(_ROUTEROS_PORTS_WITH_NO_ETHERNET_LINE)
        assert {iface.name: iface.default_name for iface in tree.interfaces} == {
            "ether1": "ether1", "sfp-sfpplus1": "", "sfp-sfpplus2": "",
        }
        same = _profile(_CCR2004)
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PORTS_WITH_NO_ETHERNET_LINE, same, same,
            port_rename_map={"sfp-sfpplus1": "core-uplink"},
        )
        plan = job.port_mapping_plan
        assert sorted(_find_lines(job)) == [
            'set [ find default-name=ether1 ] comment="oob" disabled=no',
            "set [ find default-name=sfp-sfpplus1 ] name=core-uplink disabled=no",
            "set [ find default-name=sfp-sfpplus2 ] disabled=no",
        ]
        assert "add dst-address=0.0.0.0/0 gateway=core-uplink" in job.rendered
        assert plan.target_hardware == {"sfp-sfpplus1": "sfp-sfpplus1"}
        assert "sfp-sfpplus1" not in plan.unused_target
        assert plan.off_target == []

    def test_it_goes_to_its_pairing_and_what_was_there_gives_way(self) -> None:
        """Onto the CRS310 the first cage is paired with ``ether1``.
        Named, it is still on ``ether1`` -- where the CCR2004's own
        management port, which has no place, would have stayed."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PORTS_WITH_NO_ETHERNET_LINE,
            _profile(_CCR2004), _profile(_CRS310),
            port_rename_map={"sfp-sfpplus1": "core-uplink"},
        )
        plan = job.port_mapping_plan
        assert "set [ find default-name=ether1 ] name=core-uplink disabled=no" in job.rendered
        assert plan.target_hardware == {"sfp-sfpplus1": "ether1"}
        assert plan.displaced == ["ether1"] and job.port_drops == ["ether1"]

    def test_a_port_nobody_placed_stays_on_the_hardware_it_had(self) -> None:
        """``ether9`` is not a port of a CRS310, so nothing pairs it.
        It keeps its own factory name -- it is not handed some other
        port's place -- and is reported as off-inventory."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_AN_UNLISTED_PORT, _profile(_CRS310), _profile(_CCR2004),
        )
        plan = job.port_mapping_plan
        assert sorted(_find_lines(job)) == [
            'set [ find default-name=ether9 ] comment="not on a CRS310" disabled=no',
            'set [ find default-name=sfp-sfpplus1 ] comment="wan" disabled=no',
        ]
        assert plan.off_inventory == ["ether9"] and plan.target_hardware == {}
        assert job.status == MigrationJobStatus.partial

    def test_an_unplaced_port_the_operator_only_names_has_no_place(self) -> None:
        """A CRS310 has no ninth cage.  Named and kept, the port is
        still looked up by ``sfp-sfpplus9``; what the plan reports is
        the target the operator typed, as for any vendor."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik,
            _ROUTEROS_PORTS_WITH_NO_ETHERNET_LINE.replace("sfp-sfpplus2", "sfp-sfpplus9"),
            _profile(_CCR2004), _profile(_CRS310),
            port_rename_map={"sfp-sfpplus9": "spare", "ether1": None},
        )
        plan = job.port_mapping_plan
        assert "set [ find default-name=sfp-sfpplus9 ] name=spare disabled=no" in job.rendered
        assert plan.off_target == ["spare"]
        assert "sfp-sfpplus9" not in plan.target_hardware
        assert plan.source_hardware == {"sfp-sfpplus9": "sfp-sfpplus9"}
        assert any(
            "still looked up by the factory name they had on the SOURCE device" in w
            and "(sfp-sfpplus9 by sfp-sfpplus9)" in w for w in job.warnings
        )

    def test_a_named_port_with_no_place_is_dropped_like_any_other(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_A_NAMED_NINTH_CAGE, _profile(_CCR2004), _profile(_CRS310),
        )
        plan = job.port_mapping_plan
        assert plan.labelled_ports == {"spare9": "sfp-sfpplus9"}
        assert job.port_drops == ["spare9"]
        assert "spare9" in plan.unresolved_ports and "spare9" not in job.rendered
        assert job.status == MigrationJobStatus.partial

    def test_a_name_and_a_move_onto_one_piece_of_hardware_are_fused(self) -> None:
        """``ether1`` is NAMED and stays on its pairing, ``sfp-sfpplus1``;
        ``ether2`` is MOVED there.  They share no name."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_PLAIN, _profile(_CRS310), _profile(_CCR2004),
            port_rename_map={"ether1": "WAN", "ether2": "sfp-sfpplus1"}, expect_fused=True,
        )
        assert job.port_mapping_plan.fused == {"sfp-sfpplus1": ["ether1", "ether2"]}
        assert job.status == MigrationJobStatus.partial

    def test_two_ports_sent_to_one_name_are_listed_once_each(self) -> None:
        """The clash is found by name and, where any port has its
        hardware apart from its name, by hardware as well.  One entry,
        each source once."""
        mikrotik = get_codec("mikrotik_routeros")
        same = _profile(_CCR2004)
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED, same, same,
            port_rename_map={"ether1": "sfp-sfpplus5", "core-a": "sfp-sfpplus5"},
            expect_fused=True,
        )
        assert job.port_mapping_plan.fused == {"sfp-sfpplus5": ["ether1", "core-a"]}

    def test_a_name_in_another_case_than_a_port_is_a_name(self) -> None:
        """RouterOS keeps names apart by case: a port the config calls
        ``SFP28-1`` is not the CCR2004's ``sfp28-1``, and keeps its name."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED.replace("core-a", "SFP28-1"),
            _profile(_CCR2004), _profile(_CCR2004),
        )
        assert (
            'set [ find default-name=sfp-sfpplus1 ] name=SFP28-1 comment="core A" disabled=no'
            in job.rendered
        )

    def test_it_is_done_before_a_callers_own_transforms_run(self) -> None:
        seen: list[tuple[str, str]] = []

        def look(tree):
            seen.extend((iface.name, iface.default_name) for iface in tree.interfaces)
            return tree

        eos, mikrotik = get_codec("arista_eos"), get_codec("mikrotik_routeros")
        run_plan_with_models(
            eos, mikrotik, _EOS_TWO_ROUTED_PORTS,
            _profile("arista_eos/DCS-7050SX-64"), _profile(_CCR2004),
            port_rename_map={"Ethernet1": "WAN"}, transforms=[look],
        )
        assert ("WAN", "sfp-sfpplus1") in seen

    def test_a_target_with_one_name_per_port_gets_no_factory_name(self) -> None:
        """Only a codec that says it finds ports by a factory name is
        given one."""
        assert get_codec("mikrotik_routeros").ports_keep_a_factory_name is True
        assert [
            name for name in list_public_codecs()
            if get_codec(name).ports_keep_a_factory_name
        ] == ["mikrotik_routeros"]
        seen: list[str] = []

        def look(tree):
            seen.extend(iface.default_name for iface in tree.interfaces)
            return tree

        run_plan_with_models(
            get_codec("mikrotik_routeros"), get_codec("arista_eos"), _ROUTEROS_PLAIN,
            _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"), transforms=[look],
        )
        # Untouched: what the RouterOS parser recorded, which no other
        # renderer reads.
        assert seen == ["ether1", "ether2"]


class TestOneFactoryNameOnTwoInterfaces:
    def test_no_pairing_is_made(self) -> None:
        """A port that was renamed, beside a line that still uses its
        old name -- not what a device exports, what a hand-merged file
        has.  Which of the two is the port cannot be told.  Paired
        anyway, both were put on the hardware one of them was paired
        with, and once the stray name was acknowledged the job was
        ``completed`` with two lines looking one port up."""
        mikrotik = get_codec("mikrotik_routeros")
        text = (
            "/interface ethernet\n"
            'set [ find default-name=ether5 ] name=lan5 comment="first"\n'
            "/ip address\n"
            "add address=192.0.2.1/24 interface=lan5\n"
            "add address=198.51.100.1/24 interface=ether5\n"
        )
        for entries in (None, {"ether5": "ether5"}):
            job = migration_pipeline.run_plan_with_models(
                mikrotik, mikrotik, text, _profile(_CRS310), _profile(_CCR2004),
                port_rename_map=entries,
            )
            assert job.port_mapping_plan.applied is False
            assert job.status == MigrationJobStatus.partial
            assert "more than one interface up by one factory name (ether5)" in job.error


class TestAPortNamedLikeALagInAnotherCase:
    def test_it_is_still_a_port_where_case_tells_names_apart(self) -> None:
        """``ether2`` is called ``BOND1`` and there is a bond ``bond1``:
        two names on RouterOS.  Compared without case the port was
        taken for the LAG, left out of the pairing, and folded onto the
        bond by the shape of its name -- two interfaces' addresses on
        one, ``completed``.

        Called without the wrapper for the reason given in
        ``test_a_name_that_reads_like_a_lag_is_still_the_port``: the
        RouterOS renderer writes no ``/interface ethernet`` line for a
        port whose name reads as a bond."""
        mikrotik = get_codec("mikrotik_routeros")
        text = (
            "/interface ethernet\n"
            'set [ find default-name=ether2 ] name=BOND1 comment="in capitals"\n'
            'set [ find default-name=ether7 ] comment="s1"\n'
            'set [ find default-name=ether8 ] comment="s2"\n'
            "/interface bonding\n"
            "add mode=802.3ad name=bond1 slaves=ether7,ether8\n"
            "/ip address\n"
            "add address=192.0.2.1/24 interface=BOND1\n"
            "add address=10.70.0.1/24 interface=bond1\n"
        )
        job = migration_pipeline.run_plan_with_models(
            mikrotik, mikrotik, text, _profile(_CRS310), _profile(_CCR2004),
        )
        plan = job.port_mapping_plan
        assert ("BOND1", "sfp-sfpplus2") in [(p.source, p.target) for p in plan.used_pairings]
        assert "BOND1" not in job.port_renames
        assert "add address=192.0.2.1/24 interface=BOND1" in job.rendered
        assert "add address=10.70.0.1/24 interface=bond1" in job.rendered
        assert _merged_addresses(mikrotik, mikrotik, text, job) == {}
        assert collect_hardware_port_names(
            mikrotik.parse(text), classify=mikrotik.classify_port_name, fold=True,
        ) == ["ether7", "ether8"]


_FORTIGATE_MGMT_VLAN = """config system interface
    edit "port1"
        set ip 10.1.1.1 255.255.255.0
        set type physical
    next
    edit "port2"
        set ip 10.2.2.1 255.255.255.0
        set type physical
    next
    edit "MGMT"
        set ip 10.90.0.1 255.255.255.0
        set interface "port1"
        set vlanid 90
    next
end
"""


class TestAManagementShapedLanding:
    """``MGMT`` is what operators call a management VLAN, and the
    FortiGate codec reads the name as the management PORT.  It was
    written onto ``em1`` of a switch whose management port is ``me0``,
    and into the ``oobm`` block of a switch with no such port, in jobs
    that said ``completed``: the rule for a logical name on a port the
    target lacks counted physical ports only, and asked only the
    target's classifier -- which does not read ``oobm`` back as
    anything."""

    def test_onto_a_port_the_target_codec_reads_as_management(self) -> None:
        job = run_plan_with_models(
            get_codec("fortigate_cli"), get_codec("juniper_junos"), _FORTIGATE_MGMT_VLAN,
            _profile("fortigate/100E"), _profile("juniper_junos/EX4300-48T"),
            free_text=("MGMT",),
        )
        plan = job.port_mapping_plan
        assert "em1" not in _profile("juniper_junos/EX4300-48T").names()
        assert plan.landed_off_target == {"MGMT": "em1"}
        assert plan.unresolved_ports == ["MGMT"]
        assert job.status == MigrationJobStatus.partial

    def test_into_a_form_the_target_codec_does_not_read_back(self) -> None:
        job = run_plan_with_models(
            get_codec("fortigate_cli"), AOSS, _FORTIGATE_MGMT_VLAN,
            _profile("fortigate/100E"), _device("standalone", {"model": "JL259A"}),
            free_text=("MGMT",),
        )
        assert AOSS.classify_port_name("oobm").kind == "unknown"
        assert job.port_mapping_plan.landed_off_target == {"MGMT": "oobm"}
        assert job.status == MigrationJobStatus.partial

    def test_where_the_target_has_that_port_it_is_displaced_instead(self) -> None:
        fortigate = get_codec("fortigate_cli")
        same = _profile("fortigate/100E")
        job = run_plan_with_models(
            fortigate, fortigate, _FORTIGATE_MGMT_VLAN, same, same, free_text=("MGMT",),
        )
        plan = job.port_mapping_plan
        assert plan.displaced == ["MGMT"] and plan.landed_off_target == {}

    def test_each_kind_of_port_counts_and_case_is_the_targets(self) -> None:
        junos, fortigate = get_codec("juniper_junos"), get_codec("fortigate_cli")
        eos = get_codec("arista_eos")
        job = SimpleNamespace(
            port_renames={"a": "ge-0/0/9", "b": "me0", "d": "ae3", "e": "DMZ", "f": "Ethernet49/1"},
            port_drops=[],
        )
        assert migration_pipeline._unlisted_landings(
            ["a", "b", "d"], [], {}, job, junos, junos, ["ge-0/0/1"], True,
        ) == {"a": "ge-0/0/9", "b": "me0"}
        # A lane of a broken-out cage is a port too.
        assert eos.classify_port_name("Ethernet49/1").kind == "breakout"
        assert migration_pipeline._unlisted_landings(
            ["f"], [], {}, job, eos, eos, ["Ethernet1"], True,
        ) == {"f": "Ethernet49/1"}
        # ``DMZ`` beside a port ``dmz``: the same port where case does
        # not count, a port the device lacks where it does.
        for fold, expected in ((True, {}), (False, {"e": "DMZ"})):
            assert migration_pipeline._unlisted_landings(
                ["e"], [], {}, job, fortigate, fortigate, ["dmz"], fold,
            ) == expected


class TestMoreNextHops:
    def test_a_port_the_config_names_only_as_a_next_hop(self) -> None:
        """``ether1`` and ``sfp-sfpplus1`` are ports of the declared
        CRS310 that this config has no interface record for.  The
        translator cannot know they are ports and leaves the routes;
        the pairing knows where each went."""
        mikrotik = get_codec("mikrotik_routeros")
        text = (
            "/interface ethernet\n"
            'set [ find default-name=ether2 ] comment="lan"\n'
            "/ip address\n"
            "add address=198.51.100.1/24 interface=ether2\n"
            "/ip route\n"
            "add dst-address=0.0.0.0/0 gateway=ether1\n"
            "add dst-address=10.9.0.0/16 gateway=sfp-sfpplus1\n"
            "add dst-address=10.8.0.0/16 gateway=192.0.2.1\n"
        )
        job = run_plan_with_models(
            mikrotik, mikrotik, text, _profile(_CRS310), _profile(_CCR2004),
        )
        assert job.port_mapping_plan.stale_next_hops == ["0.0.0.0/0", "10.9.0.0/16"]
        assert job.status == MigrationJobStatus.partial
        same = _profile(_CRS310)
        job = run_plan_with_models(mikrotik, mikrotik, text, same, same)
        assert job.port_mapping_plan.stale_next_hops == []
        assert job.status == MigrationJobStatus.completed

    def test_a_list_that_names_the_same_ports_afterwards_is_still_right(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        same = _profile(_CRS310)
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_HOP_FORMS, same, same,
            port_rename_map={"ether1": "ether2", "ether2": "ether1"},
        )
        assert "gateway=ether1,ether2" in job.rendered
        assert job.port_mapping_plan.stale_next_hops == []
        assert job.status == MigrationJobStatus.completed

    def test_units_in_a_list(self) -> None:
        tree = _tree(
            interfaces=[{"name": "a"}, {"name": "b"}],
            static_routes=[{"destination": "10.0.0.0/8", "gateway": "a.0,b.0"}],
        )
        job = SimpleNamespace(port_renames={"a": "c"}, port_drops=[])
        assert migration_pipeline._stale_next_hops(tree, job, True, {}) == ["10.0.0.0/8"]
        job = SimpleNamespace(port_renames={}, port_drops=[])
        assert migration_pipeline._stale_next_hops(tree, job, True, {}) == []

    def test_they_are_read_from_the_run_that_was_kept(self) -> None:
        """From the CCR2004 side its management ``ether1`` is displaced
        by the cage paired onto ``ether1``, so there are two runs.  The
        route that names ``ether1`` alone goes with it; what is still
        stale is read from the second run."""
        mikrotik = get_codec("mikrotik_routeros")
        text = _ROUTEROS.replace(
            "/ip address",
            "/ip address\nadd address=10.2.0.1/30 interface=sfp-sfpplus2",
        ) + "/ip route\nadd dst-address=0.0.0.0/0 gateway=sfp-sfpplus1,sfp-sfpplus2\n"
        job = run_plan_with_models(
            mikrotik, mikrotik, text, _profile(_CCR2004), _profile(_CRS310),
        )
        plan = job.port_mapping_plan
        assert plan.displaced == ["ether1"]
        assert plan.stale_next_hops == ["0.0.0.0/0"]
        assert "need a decision" in job.error
        assert job.error.index("Review the port mapping") < job.error.index("static route(s) still name")

    def test_a_followed_unit_hop_is_not_stale(self) -> None:
        junos = get_codec("juniper_junos")
        job = run_plan_with_models(
            junos, junos, _JUNOS_NEXT_HOP.replace("et-0/0/24", "xe-0/0/3"),
            _profile("juniper_junos/QFX5120-48Y"), _profile("juniper_junos/QFX5120-48Y"),
            port_rename_map={"xe-0/0/3": "xe-0/0/7"},
        )
        assert "next-hop xe-0/0/7.0" in job.rendered
        assert job.port_mapping_plan.stale_next_hops == []
        assert job.status == MigrationJobStatus.completed


class TestALandingAfterADisplacement:
    def test_it_is_read_from_the_run_that_was_kept(self) -> None:
        """Two logical names nobody decided: one would take a port of
        the target and is displaced, which costs a second run; the
        other is on a port the target lacks, and must still be listed."""
        fortigate = get_codec("fortigate_cli")
        text = _FORTIGATE_MGMT_VLAN.replace(
            "end\n",
            '    edit "fortilink"\n        set ip 10.255.1.1 255.255.255.0\n'
            "        set type aggregate\n    next\nend\n",
        )
        job = run_plan_with_models(
            fortigate, fortigate, text, _profile("fortigate/100E"), _profile("fortigate/100E"),
            free_text=("MGMT",),
        )
        plan = job.port_mapping_plan
        assert plan.displaced == ["MGMT"]
        assert plan.landed_off_target == {"fortilink": "fortilink1"}


class TestWhoKeepsANameNobodyDecided:
    def test_a_port_of_the_declared_source_under_the_configs_name(self) -> None:
        """The keeper of a clash nobody decided is a port of the
        declared source -- which the config may know by a name of its
        own."""
        job = SimpleNamespace(port_renames={"stray": "x1", "core-a": "x1"}, port_drops=[])
        arguments = (["stray", "core-a"], ["stray", "core-a"], {}, job, ["t1"])
        assert migration_pipeline._undecided_clashes(*arguments, source_names=["core-a"]) == ["stray"]
        assert migration_pipeline._undecided_clashes(*arguments, source_names=["ether2"]) == ["core-a"]


# ---------------------------------------------------------------------------
# The wrapper applies every one of its checks
# ---------------------------------------------------------------------------


_EOS_A_LAG_AND_A_THIRTEENTH_PORT = """hostname sw
!
interface Port-Channel1
   no switchport
   ip address 10.50.0.1/24
!
interface Ethernet1
   no switchport
   ip address 192.0.2.1/24
!
interface Ethernet13
   no switchport
   ip address 10.0.13.1/24
!
end
"""

_ROUTEROS_A_NAMED_NINTH_PORT = """/interface ethernet
set [ find default-name=sfp-sfpplus1 ] comment="wan"
set [ find default-name=sfp-sfpplus9 ] name=core-z comment="far"
/ip address
add address=192.0.2.2/30 interface=sfp-sfpplus1
add address=10.0.0.1/24 interface=core-z
"""

_ROUTEROS_A_PORT_NAMED_LIKE_ANOTHERS_FACTORY_NAME = """/interface ethernet
set [ find default-name=ether1 ] name=core-a
set [ find default-name=ether2 ] name=ether1
/ip address
add address=10.0.1.1/24 interface=core-a
add address=10.0.2.1/24 interface=ether1
"""


class TestWhatTheBinderLeavesAlone:
    """The binder sets a factory name on a port the mapping can
    account for, and on nothing else."""

    def test_a_port_from_another_vendor_that_nobody_placed(self) -> None:
        """The thirteenth port of an Arista switch has no place on a
        twelve-port router, and the operator keeps it under a name.
        It had no hardware this target knows: the name it had on the
        source device is not given to it as one, and the entry is
        reported as a name the target does not list."""
        job = run_plan_with_models(
            get_codec("arista_eos"), get_codec("mikrotik_routeros"),
            _EOS_A_LAG_AND_A_THIRTEENTH_PORT,
            _profile("arista_eos/DCS-7050SX-64"), _profile(_CCR2004),
            port_rename_map={"Ethernet13": "spare"},
        )
        plan = job.port_mapping_plan
        assert "default-name=Ethernet13" not in job.rendered
        assert "set [ find name=spare ]" in job.rendered
        assert (plan.target_hardware, plan.source_hardware) == ({}, {})
        assert plan.off_target == ["spare"]

    def test_a_named_port_nobody_placed_stays_on_the_hardware_it_had(self) -> None:
        """Between two RouterOS configs, a port the config calls
        ``core-z`` is the ninth SFP+ port, and the target has eight
        access ports.  Kept under a name, it is still looked up by its
        own factory name -- not by the name the config gave it -- and
        the plan says the target has no such port."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_A_NAMED_NINTH_PORT,
            _profile(_CCR2004), _profile(_CRS310),
            port_rename_map={"core-z": "far-end"},
        )
        plan = job.port_mapping_plan
        assert plan.labelled_ports == {"core-z": "sfp-sfpplus9"}
        assert 'set [ find default-name=sfp-sfpplus9 ] name=far-end comment="far"' in job.rendered
        assert plan.source_hardware == {"core-z": "sfp-sfpplus9"}
        assert plan.target_hardware == {}
        assert plan.off_target == ["far-end"]

    def test_a_logical_interface_an_operator_puts_on_a_port_is_not_a_port(self) -> None:
        """A LAG's address sent onto ``sfp-sfpplus5`` is an address on
        that port, which the device has.  The LAG is no port of the
        declared source, so the binder gives it no hardware -- and the
        read-back does not then report it as a port no line finds."""
        job = run_plan_with_models(
            get_codec("arista_eos"), get_codec("mikrotik_routeros"),
            _EOS_A_LAG_AND_A_THIRTEENTH_PORT,
            _profile("arista_eos/DCS-7050SX-64"), _profile(_CCR2004),
            port_rename_map={"Port-Channel1": "sfp-sfpplus5", "Ethernet13": None},
        )
        plan = job.port_mapping_plan
        assert "add address=10.50.0.1/24 interface=sfp-sfpplus5" in job.rendered
        assert plan.unbound_ports == {}
        assert plan.is_clean and job.status == MigrationJobStatus.completed

    def test_an_entry_keyed_by_a_name_the_config_uses_is_for_that_port(self) -> None:
        """The config calls one port ``ether1`` -- and ``ether1`` is
        also the FACTORY name of another port, which the config calls
        ``core-a``.  An entry keyed ``ether1`` is for the port the
        config calls that; it is not re-keyed to the other."""
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_A_PORT_NAMED_LIKE_ANOTHERS_FACTORY_NAME,
            _profile(_CRS310), _profile(_CCR2004),
            port_rename_map={"ether1": None},
        )
        assert job.port_mapping_plan.labelled_ports == {"core-a": "ether1", "ether1": "ether2"}
        assert job.port_drops == ["ether1"]
        assert "10.0.2.1" not in job.rendered
        assert "10.0.1.1" in job.rendered


class TestTheBinderRecordsOneRun:
    def test_what_a_run_recorded_does_not_outlive_it(self) -> None:
        """The translation can run twice (a displaced name is dropped
        and the run repeated).  What the binder recorded for the run
        that was thrown away says nothing about the one that is kept:
        a port that is gone from the second tree is gone from the
        record."""
        source = _profile(_CRS310)
        target = _profile(_CCR2004)
        plan = plan_port_mapping(source, target, ["ether1", "ether2"])
        hardware: dict[str, str] = {}
        sent: dict[str, str | None] = {"ether1": "WAN", "ether2": "LAN"}
        bind = migration_pipeline._hardware_binder(
            plan, {}, source.names(), sent, target.names(), False, False, hardware,
        )
        bind(CanonicalIntent.model_validate({"interfaces": [{"name": "WAN"}, {"name": "LAN"}]}))
        assert hardware == {"ether1": "sfp-sfpplus1", "ether2": "sfp-sfpplus2"}
        sent["ether2"] = None
        bind(CanonicalIntent.model_validate({"interfaces": [{"name": "WAN"}]}))
        assert hardware == {"ether1": "sfp-sfpplus1"}


class TestAPortTheOutputDoesNotLookUp:
    """The RouterOS renderer goes by the shape of an interface's name
    as well as by its type: one that reads as a VLAN, a bridge or a
    LAG gets no Ethernet line, whatever factory name it carries --
    with or without devices declared.  The mapping does not re-derive
    that rule.  It reads the finished output back with the target's
    own parser and says which ports it did not find by their
    hardware; the job is ``partial`` until each has another name."""

    def test_a_port_the_config_names_like_a_lag(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED_LIKE_A_LAG, _profile(_CRS310), _profile(_CCR2004),
        )
        plan = job.port_mapping_plan
        assert "sfp-sfpplus2" not in job.rendered
        assert plan.unbound_ports == {"bond1": "sfp-sfpplus2"}
        assert plan.target_hardware == {} and plan.source_hardware == {}
        assert "sfp-sfpplus2" in plan.unused_target
        assert not plan.is_clean and job.status == MigrationJobStatus.partial
        assert job.error == (
            "Port mapping is incomplete: 1 port(s) are not looked up by their "
            "hardware in the output; give each another name."
        )
        (line,) = [w for w in plan.warnings if "not looked up by their hardware" in w]
        assert "(bond1 on sfp-sfpplus2)" in line

    def test_another_name_puts_it_on_its_hardware(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = run_plan_with_models(
            mikrotik, mikrotik, _ROUTEROS_NAMED_LIKE_A_LAG, _profile(_CRS310), _profile(_CCR2004),
            port_rename_map={"bond1": "uplink-a"},
        )
        plan = job.port_mapping_plan
        assert "set [ find default-name=sfp-sfpplus2 ] name=uplink-a" in job.rendered
        assert plan.unbound_ports == {}
        assert plan.target_hardware == {"bond1": "sfp-sfpplus2"}
        assert plan.is_clean and job.status == MigrationJobStatus.completed

    @pytest.mark.parametrize("name", ["bridge-uplink", "vlan-trunk", "po1"])
    def test_a_name_an_operator_gives_a_port_from_another_vendor(self, name: str) -> None:
        """The entry is taken as a NAME (it is no port of the target),
        and the name is one the renderer writes no Ethernet line for.
        Nothing then says the port is on its paired hardware."""
        job = run_plan_with_models(
            get_codec("arista_eos"), get_codec("mikrotik_routeros"), _EOS_TWO_ROUTED_PORTS,
            _profile("arista_eos/DCS-7050SX-64"), _profile(_CCR2004),
            port_rename_map={"Ethernet1": name},
        )
        plan = job.port_mapping_plan
        assert "sfp-sfpplus1" not in job.rendered
        assert plan.unbound_ports == {"Ethernet1": "sfp-sfpplus1"}
        assert plan.target_hardware == {}
        assert plan.off_target == [name]
        assert not [w for w in plan.warnings if "taken as NAMES" in w]
        assert job.status == MigrationJobStatus.partial

    def test_output_that_cannot_be_read_back_confirms_no_port(self) -> None:
        class Unreadable:
            def parse(self, _text: str) -> None:
                raise ValueError("not a config")

        job = SimpleNamespace(rendered="x")
        assert migration_pipeline._unbound_hardware(
            Unreadable(), job, {"a": "ether1", "b": "ether2"},
        ) == ["a", "b"]

    def test_with_no_port_to_confirm_nothing_is_read(self) -> None:
        assert migration_pipeline._unbound_hardware(None, None, {}) == []

    def test_a_port_is_confirmed_by_its_factory_name_and_by_nothing_else(self) -> None:
        mikrotik = get_codec("mikrotik_routeros")
        job = SimpleNamespace(rendered=(
            "/interface ethernet\n"
            "set [ find default-name=sfp-sfpplus1 ] name=WAN\n"
            "/ip address\n"
            "add address=10.0.0.1/24 interface=LAN\n"
        ))
        assert migration_pipeline._unbound_hardware(
            mikrotik, job, {"a": "sfp-sfpplus1", "b": "sfp-sfpplus2", "c": "LAN"},
        ) == ["b", "c"]


class TestTheWrapperAppliesEveryCheck:
    """``TestTheChecksOnEveryJobCanFail`` shows that each check can
    fail.  This shows that the wrapper CALLS each: the engine is made
    to return a job with one defect, and the wrapper has to refuse it
    in that check's own words.  A check that could be taken out of the
    wrapper with every test still passing guards nothing."""

    @staticmethod
    def _engine_that(spoils, monkeypatch: pytest.MonkeyPatch) -> None:
        real = migration_pipeline.run_plan_with_models

        def spoiled(*args, **kwargs) -> MigrationJob:
            job = real(*args, **kwargs)
            spoils(job)
            return job

        monkeypatch.setattr(migration_pipeline, "run_plan_with_models", spoiled)

    def test_the_config_is_on_the_port_the_job_reports(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.rendered = job.rendered.replace("interface Ethernet2\n", "interface Ethernet9\n")

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError, match="not on the port the job reports"):
            run_plan_with_models(
                get_codec("mikrotik_routeros"), get_codec("arista_eos"), _ROUTEROS_NAMED_ROUTE,
                _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"),
            )

    def test_a_port_looked_up_by_a_name_no_port_has(self, monkeypatch) -> None:
        """The defect of this class's subject, as the engine once
        produced it: the output looks the port up by the operator's
        name, and the job's own report agrees with the output."""
        def spoils(job: MigrationJob) -> None:
            job.rendered = job.rendered.replace(
                "find default-name=sfp-sfpplus1 ] name=WAN", "find name=WAN ]",
            )
            job.port_mapping_plan.target_hardware = {}

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError, match="not on the port the job reports"):
            run_plan_with_models(
                get_codec("arista_eos"), get_codec("mikrotik_routeros"), _EOS_TWO_ROUTED_PORTS,
                _profile("arista_eos/DCS-7050SX-64"), _profile(_CCR2004),
                port_rename_map={"Ethernet1": "WAN"},
            )

    def test_a_port_no_line_finds_that_the_job_does_not_say(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.port_mapping_plan.unbound_ports = {}

        self._engine_that(spoils, monkeypatch)
        mikrotik = get_codec("mikrotik_routeros")
        with pytest.raises(AssertionError, match="which no port of the target has"):
            run_plan_with_models(
                mikrotik, mikrotik, _ROUTEROS_NAMED_LIKE_A_LAG,
                _profile(_CRS310), _profile(_CCR2004),
            )

    def test_a_port_the_job_says_no_line_finds_and_one_does(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.port_mapping_plan.unbound_ports = {"Ethernet1": "sfp-sfpplus1"}

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError, match="the job says no line finds it by its hardware"):
            run_plan_with_models(
                get_codec("arista_eos"), get_codec("mikrotik_routeros"), _EOS_TWO_ROUTED_PORTS,
                _profile("arista_eos/DCS-7050SX-64"), _profile(_CCR2004),
                port_rename_map={"Ethernet1": "WAN"},
            )

    def test_the_output_names_no_port_the_job_does_not_report(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.rendered = job.rendered.replace("1/A1", "1/A9")

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError, match="ports in the output that the job does not report"):
            run_plan_with_models(AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_48G)

    def test_no_name_that_moved_is_left(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.rendered = job.rendered.replace("description wan", "description ether1")

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError, match="names that moved are still in the output"):
            run_plan_with_models(
                get_codec("mikrotik_routeros"), get_codec("arista_eos"), _ROUTEROS_NAMED_ROUTE,
                _profile(_CRS310), _profile("arista_eos/DCS-7050SX-64"),
            )

    def test_no_interface_carries_two(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.rendered = job.rendered.replace("interface=sfp-sfpplus2", "interface=sfp-sfpplus1")

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError, match="two source interfaces in one output interface"):
            run_plan_with_models(
                get_codec("mikrotik_routeros"), get_codec("mikrotik_routeros"), _ROUTEROS_PLAIN,
                _profile(_CRS310), _profile(_CCR2004),
            )

    def test_no_two_ports_are_looked_up_by_one_factory_name(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.rendered = job.rendered.replace(
                "find default-name=ether1 ]", "find default-name=sfp-sfpplus1 ] name=oob",
            )

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError, match="two names on one target name"):
            run_plan_with_models(
                get_codec("mikrotik_routeros"), get_codec("mikrotik_routeros"), _ROUTEROS_NAMED,
                _profile(_CCR2004), _profile(_CCR2004),
            )

    def test_a_port_that_needs_a_decision_is_not_a_clean_success(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.status = MigrationJobStatus.completed

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError):
            run_plan_with_models(AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_24G)

    def test_what_the_plan_says_of_an_unplaced_port_is_what_happened(self, monkeypatch) -> None:
        def spoils(job: MigrationJob) -> None:
            job.port_mapping_plan.unplaced[0].dropped = False
            job.port_mapping_plan.unplaced[0].landed = "1/1"

        self._engine_that(spoils, monkeypatch)
        with pytest.raises(AssertionError):
            run_plan_with_models(AOSS, AOSS, CAPTURE_2930F, SOURCE_2930F_48G, TARGET_2930M_24G)
