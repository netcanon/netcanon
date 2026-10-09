"""Device models — schema, compiler, loader and the legacy-profile reader.

These tests run on a small synthetic family defined in this file, so
they pin the BEHAVIOUR of :mod:`netcanon.migration.device_models`
without depending on any shipped model data.  The shipped families are
checked against real captures in ``test_device_models_shipped.py``.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

import pytest
import yaml

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration import device_models as dm
from netcanon.migration.codecs.aruba_aoss.port_names import physical_port_name
from netcanon.migration.device_models import (
    SPEED_RANK,
    Deployment,
    DeploymentError,
    DeviceModelLoadError,
    DeviceModelRegistry,
    FamilyDef,
    Grade,
    Inventory,
    MemberSpec,
    NamingRuleSpec,
    check_family,
    compile_deployment,
    inventory_from_profile,
    load_family_file,
    load_model_families_dir,
    weakest_grade,
)
from netcanon.migration.target_profiles import TargetProfile, load_profiles_dir
from netcanon.models.port_inventory import (
    MAX_DECLARED_BAYS,
    MAX_DECLARED_NAME,
    MAX_DEPLOYMENT_MEMBERS,
    DeploymentSpec,
)

pytestmark = pytest.mark.unit


# A made-up family in the AOS-S grammar.  None of this is a claim
# about real hardware.  "Testbox" has a fixed-panel model (TB-8), a
# model with a module bay (TB-4M), a standalone and a stacked mode,
# and ONE capture: a TB-4M with a MOD4, stacked, as member 1.
FAMILY_YAML = """
schema: 1
vendor: aruba_aoss
family: Testbox
display_name: "Testbox"
naming: aoss
default_mode: standalone
modes:
  standalone:
    label: "standalone"
    naming: {grade: vendor-doc, ref: "Testbox guide"}
    bay_naming:
      grade: inferred
      ref: "Testbox guide, by analogy"
      caveat: "Standalone module port names are unverified."
  stacked:
    label: "stacked"
    member_ids: [1, 4]
    naming: {grade: vendor-doc, ref: "Testbox stacking guide"}
    caveat: "Stack links carry no configuration."
modules:
  MOD4:
    description: "4-port uplink module"
    inventory: {grade: vendor-doc, ref: "MOD4 sheet"}
    ports:
      - {role: uplink, count: 4, speed: 10gig, cage: sfp+}
  MOD1:
    description: "1-port uplink module"
    caveat: "Breakout is not modelled."
    inventory:
      grade: inferred
      ref: "a reseller listing"
      caveat: "MOD1 port count is from a listing."
    ports:
      - {role: uplink, count: 1, speed: 40gig, cage: qsfp+}
models:
  TB-8:
    skus: [TB008A, TB008B]
    display_name: "Testbox 8 (TB008A)"
    panel: {grade: vendor-doc, ref: "TB-8 sheet"}
    ports:
      - {role: access, count: 8, speed: gig, cage: rj45, poe: true, notes: "PoE+"}
      - {role: uplink, count: 2, speed: 10gig, cage: sfp+}
  TB-4M:
    skus: [TB004M]
    display_name: "Testbox 4M (TB004M)"
    panel: {grade: vendor-doc, ref: "TB-4M sheet"}
    ports:
      - {role: access, count: 4, speed: gig}
    bays:
      A: {accepts: [MOD4, MOD1]}
captures:
  - fixture: tests/fixtures/real/x.cfg
    marker: "testbox 4m"
    mode: stacked
    members: [{model: TB-4M, id: 1, modules: {A: MOD4}}]
"""

#: The synthetic claim, as the trust table lists a shipped one.
TESTBOX_CLAIM = (
    "aruba_aoss/Testbox", "tests/fixtures/real/x.cfg", "stacked",
    (("TB-4M", 1, (("A", "MOD4"),)),),
)

OTHER_FAMILY_YAML = """
schema: 1
vendor: aruba_aoss
family: Otherbox
naming: aoss
default_mode: only
modes:
  only: {label: "only", naming: {grade: vendor-doc}}
models:
  OB-2:
    panel: {grade: vendor-doc}
    ports:
      - {role: access, count: 2}
"""


def _data(text: str = FAMILY_YAML) -> dict:
    return yaml.safe_load(text)


def _family(data: dict | str = FAMILY_YAML) -> FamilyDef:
    raw = copy.deepcopy(data) if isinstance(data, dict) else _data(data)
    for section, field in (("models", "model"), ("modules", "sku")):
        for key, entry in (raw.get(section) or {}).items():
            entry.setdefault(field, key)
    return FamilyDef(**raw)


@pytest.fixture(autouse=True)
def _the_testbox_claim_is_proven(monkeypatch: pytest.MonkeyPatch) -> None:
    """A capture claim grants its grade only when it is one the
    shipped-data test re-proves (``PROVEN_CAPTURE_CLAIMS``).  These
    tests are about what a proven claim grants, so the synthetic one
    is listed; ``TestUnprovenClaims`` takes it out again."""
    monkeypatch.setattr(
        dm, "PROVEN_CAPTURE_CLAIMS", dm.PROVEN_CAPTURE_CLAIMS | {TESTBOX_CLAIM},
    )


@pytest.fixture()
def registry() -> DeviceModelRegistry:
    return DeviceModelRegistry([_family(), _family(OTHER_FAMILY_YAML)])


def _compile(
    registry: DeviceModelRegistry, mode: str | None, *members: dict,
) -> Inventory:
    return compile_deployment(
        Deployment(
            vendor="aruba_aoss", mode=mode,
            members=[MemberSpec(**m) for m in members],
        ),
        registry,
    )


# ---------------------------------------------------------------------------
# The AOS-S naming rule
# ---------------------------------------------------------------------------


class TestAossPhysicalPortName:
    @pytest.mark.parametrize(
        ("member", "slot", "port", "expected"),
        [
            (None, "", 24, "24"),       # standalone fixed port
            (None, "A", 1, "A1"),       # standalone module port
            (1, "", 24, "1/24"),        # stacked fixed port
            (1, "A", 1, "1/A1"),        # stacked module port
            (2, "b", 8, "2/B8"),        # slot letter is upper-cased
        ],
    )
    def test_the_four_shapes(self, member, slot, port, expected):
        assert physical_port_name(member=member, slot=slot, port=port) == expected

    @pytest.mark.parametrize(
        ("member", "slot", "port", "expected"),
        [
            # HPE's own printed examples, none of them member 1:
            (3, "", 10, "3/10"),    # Basic Operation Guide 16.06, stacking chapter
            (2, "", 24, "2/24"),    # Management and Configuration Guide, VSF naming
            (3, "", 25, "3/25"),    # MCG VSF example, a lone commander numbered 3
            # 2930M stack, Advanced Traffic Management Guide 16.11 p.291:
            (3, "A", 1, "3/A1"),
            (5, "A", 4, "5/A4"),
        ],
    )
    def test_the_vendors_printed_examples(self, member, slot, port, expected):
        assert physical_port_name(member=member, slot=slot, port=port) == expected

    def test_an_absent_member_is_not_member_one(self):
        """The whole reason the mode is an input: ``24`` and ``1/24``
        are different names for the same port in different states."""
        assert physical_port_name(member=None, slot="", port=24) != (
            physical_port_name(member=1, slot="", port=24)
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"member": None, "slot": "", "port": 0},
            {"member": 0, "slot": "", "port": 1},
            {"member": None, "slot": "AB", "port": 1},
            {"member": None, "slot": "1", "port": 1},
            # A letter, but not an ASCII one: its upper case is "SS".
            {"member": None, "slot": "\u00df", "port": 1},
        ],
    )
    def test_out_of_grammar_inputs_are_refused(self, kwargs):
        with pytest.raises(ValueError):
            physical_port_name(**kwargs)


# ---------------------------------------------------------------------------
# Compiling a deployment
# ---------------------------------------------------------------------------


class TestCompileStandalone:
    def test_fixed_panel_numbers_run_on_through_the_uplinks(self, registry):
        inv = _compile(registry, None, {"model": "TB-8"})
        assert inv.names() == [str(n) for n in range(1, 11)]
        assert inv.names(role="access") == [str(n) for n in range(1, 9)]
        assert inv.names(role="uplink") == ["9", "10"]

    def test_roles_ordinals_and_positions(self, registry):
        inv = _compile(registry, None, {"model": "TB-8"})
        first_uplink = inv.port("9")
        assert first_uplink is not None
        assert (first_uplink.role, first_uplink.ordinal) == ("uplink", 0)
        assert (first_uplink.slot, first_uplink.index, first_uplink.module) == ("", 8, "")
        assert (inv.port("10").role, inv.port("10").ordinal) == ("uplink", 1)
        assert [p.ordinal for p in inv.ports if p.role == "access"] == list(range(8))
        assert [p.index for p in inv.ports] == list(range(10))
        assert {p.member_rank for p in inv.ports} == {0}
        assert {p.member_id for p in inv.ports} == {None}

    def test_port_attributes_carry_through(self, registry):
        inv = _compile(registry, None, {"model": "TB-8"})
        access, uplink = inv.port("1"), inv.port("9")
        assert (access.speed, access.cage, access.poe, access.notes) == (
            "gig", "rj45", True, "PoE+",
        )
        assert (uplink.speed, uplink.cage, uplink.poe, uplink.notes) == (
            "10gig", "sfp+", False, "",
        )

    def test_a_sku_resolves_to_its_model_in_any_case(self, registry):
        by_key = _compile(registry, None, {"model": "TB-8"})
        for spelling in ("TB008A", "tb008b", " TB-8 "):
            inv = _compile(registry, None, {"model": spelling})
            assert inv.names() == by_key.names()
            # ...and the inventory says which model that was.
            assert inv.members[0].model == "TB-8"


class TestCompileStacked:
    def test_every_port_takes_the_member_id_uplinks_included(self, registry):
        inv = _compile(registry, "stacked", {"model": "TB-8"})
        assert inv.names() == [f"1/{n}" for n in range(1, 11)]
        assert {p.member_id for p in inv.ports} == {1}

    def test_members_without_ids_take_the_lowest_free_ones(self, registry):
        inv = _compile(
            registry, "stacked",
            {"model": "TB-8"}, {"model": "TB-8"}, {"model": "TB-8"},
        )
        assert inv.member_count == 3
        assert [m.member_id for m in inv.members] == [1, 2, 3]
        assert inv.names(member_rank=0)[0] == "1/1"
        assert inv.names(member_rank=1)[0] == "2/1"
        assert inv.names(member_rank=2)[-1] == "3/10"

    def test_a_lone_member_need_not_be_member_one(self, registry):
        """Rank is 0 whatever the vendor id — pairing must not care
        that this unit calls itself 3."""
        inv = _compile(registry, "stacked", {"model": "TB-8", "id": 3})
        assert inv.names()[0] == "3/1"
        assert {p.member_rank for p in inv.ports} == {0}
        assert {p.member_id for p in inv.ports} == {3}
        assert (inv.members[0].rank, inv.members[0].member_id) == (0, 3)

    def test_declared_ids_are_kept_and_the_rest_fill_around_them(self, registry):
        inv = _compile(
            registry, "stacked",
            {"model": "TB-8"}, {"model": "TB-8", "id": 1}, {"model": "TB-8"},
        )
        assert [inv.names(member_rank=r)[0] for r in range(3)] == [
            "2/1", "1/1", "3/1",
        ]

    def test_ordinals_restart_for_each_member(self, registry):
        inv = _compile(registry, "stacked", {"model": "TB-8"}, {"model": "TB-8"})
        second = [p for p in inv.ports if p.member_rank == 1]
        assert [p.ordinal for p in second if p.role == "access"] == list(range(8))
        assert [p.ordinal for p in second if p.role == "uplink"] == [0, 1]

    def test_members_of_one_family_may_differ_in_model(self, registry):
        inv = _compile(
            registry, "stacked",
            {"model": "TB-8"}, {"model": "TB-4M", "modules": {"A": "MOD4"}},
        )
        assert inv.names(member_rank=1) == [
            "2/1", "2/2", "2/3", "2/4", "2/A1", "2/A2", "2/A3", "2/A4",
        ]
        assert [m.model for m in inv.members] == ["TB-8", "TB-4M"]


class TestCompileModules:
    def test_an_empty_bay_contributes_nothing(self, registry):
        """No module is a real configuration, not an error."""
        for modules in ({}, {"A": None}, {"A": ""}):
            inv = _compile(registry, None, {"model": "TB-4M", "modules": modules})
            assert inv.names() == ["1", "2", "3", "4"]
            assert inv.members[0].modules == {}

    def test_not_stated_is_kept_apart_from_stated_empty(self, registry):
        """A source config often cannot say which module is fitted.
        Both compile as empty; only one of them is a known fact."""
        unstated = _compile(registry, None, {"model": "TB-4M"})
        stated = _compile(registry, None, {"model": "TB-4M", "modules": {"A": None}})
        assert unstated.members[0].unstated_bays == ["A"]
        assert stated.members[0].unstated_bays == []
        note = "Testbox 4M (TB004M): bay A was not stated and is assumed empty."
        assert note in unstated.caveats
        assert note not in stated.caveats

    def test_module_ports_restart_at_one_inside_the_bay(self, registry):
        inv = _compile(registry, None, {"model": "TB-4M", "modules": {"A": "MOD4"}})
        assert inv.names(role="uplink") == ["A1", "A2", "A3", "A4"]
        port = inv.port("A1")
        assert (port.slot, port.index, port.module, port.ordinal) == ("A", 0, "MOD4", 0)
        assert inv.members[0].modules == {"A": "MOD4"}

    def test_stacked_module_ports_carry_member_and_letter(self, registry):
        inv = _compile(
            registry, "stacked", {"model": "TB-4M", "modules": {"A": "MOD1"}},
        )
        assert inv.names(role="uplink") == ["1/A1"]

    def test_bay_and_module_match_in_any_case(self, registry):
        inv = _compile(registry, None, {"model": "TB-4M", "modules": {"a": "mod4"}})
        assert inv.names(role="uplink") == ["A1", "A2", "A3", "A4"]
        assert inv.members[0].modules == {"A": "MOD4"}

    def test_a_fitted_modules_note_reaches_the_inventory(self, registry):
        with_one = _compile(registry, None, {"model": "TB-4M", "modules": {"A": "MOD1"}})
        with_four = _compile(registry, None, {"model": "TB-4M", "modules": {"A": "MOD4"}})
        assert "Breakout is not modelled." in with_one.caveats
        assert "Breakout is not modelled." not in with_four.caveats


class TestFixedPanelSlots:
    def test_each_slot_counts_from_one(self):
        data = _data()
        data["models"]["TB-BANK"] = {
            "panel": {"grade": "vendor-doc"},
            "ports": [
                {"role": "access", "count": 2},
                {"role": "access", "count": 2},
                {"role": "uplink", "count": 2, "slot": "B"},
            ],
        }
        inv = _compile(DeviceModelRegistry([_family(data)]), None, {"model": "TB-BANK"})
        assert inv.names() == ["1", "2", "3", "4", "B1", "B2"]
        assert [(p.slot, p.index) for p in inv.ports][-2:] == [("B", 0), ("B", 1)]

    def test_a_later_group_in_a_slot_carries_on_where_it_stopped(self):
        """Numbering is per slot, not per run of groups: going back
        to a slot resumes it."""
        data = _data()
        data["models"]["TB-BANK"] = {
            "panel": {"grade": "vendor-doc"},
            "ports": [
                {"role": "access", "count": 4},
                {"role": "uplink", "count": 2, "slot": "C"},
                {"role": "access", "count": 2},
                {"role": "uplink", "count": 1, "slot": "C"},
            ],
        }
        inv = _compile(DeviceModelRegistry([_family(data)]), None, {"model": "TB-BANK"})
        assert inv.names() == ["1", "2", "3", "4", "C1", "C2", "5", "6", "C3"]


class TestResolvedDeployment:
    def test_the_inventory_says_what_it_compiled(self, registry):
        inv = _compile(
            registry, "stacked", {"model": "tb004m", "modules": {"A": "MOD4"}},
        )
        assert inv.origin == "family"
        assert inv.family == "aruba_aoss/Testbox"
        assert (inv.mode, inv.mode_label, inv.mode_defaulted) == ("stacked", "stacked", False)
        assert inv.description == "Testbox 4M (TB004M) + MOD4 as member 1 — stacked"
        member = inv.members[0]
        assert (member.rank, member.member_id, member.model) == (0, 1, "TB-4M")
        assert member.display_name == "Testbox 4M (TB004M)"

    def test_a_defaulted_mode_is_reported(self, registry):
        """The mode decides every name; an operator who left it out
        must be told which one they got."""
        inv = _compile(registry, None, {"model": "TB-8"})
        assert (inv.mode, inv.mode_defaulted) == ("standalone", True)
        assert any("No deployment mode was stated" in c for c in inv.caveats)
        stated = _compile(registry, "standalone", {"model": "TB-8"})
        assert not stated.mode_defaulted
        assert not any("No deployment mode was stated" in c for c in stated.caveats)
        assert stated.names() == inv.names()

    @pytest.mark.parametrize("mode", ["", "   "])
    def test_an_empty_mode_is_not_a_stated_one(self, registry, mode):
        """A picker with an empty first option posts ``""``.  That is
        the family default being taken, and has to be said just as
        for an absent mode."""
        inv = _compile(registry, mode, {"model": "TB-8"})
        assert (inv.mode, inv.mode_defaulted) == ("standalone", True)
        assert any("No deployment mode was stated" in c for c in inv.caveats)

    def test_a_mode_name_matches_in_any_case(self, registry):
        """As a model key, a SKU, a bay name and a module SKU do."""
        inv = _compile(registry, " STACKED ", {"model": "TB-8"})
        assert (inv.mode, inv.mode_defaulted) == ("stacked", False)
        assert inv.names()[0] == "1/1"

    def test_a_family_with_one_mode_has_nothing_to_report(self, registry):
        inv = _compile(registry, None, {"model": "OB-2"})
        assert inv.mode_defaulted
        assert not any("No deployment mode was stated" in c for c in inv.caveats)

    def test_the_modes_own_note_applies_to_every_deployment_in_it(self, registry):
        inv = _compile(registry, "stacked", {"model": "TB-8"})
        assert "Stack links carry no configuration." in inv.caveats
        assert "Stack links carry no configuration." not in (
            _compile(registry, None, {"model": "TB-8"}).caveats
        )


class TestCompileRefusals:
    @pytest.mark.parametrize(
        ("mode", "members", "needle"),
        [
            (None, [{"model": "TB-99"}], "no device model 'TB-99'"),
            ("vsf", [{"model": "TB-8"}], "has no mode 'vsf'"),
            (None, [{"model": "TB-8"}, {"model": "TB-8"}], "is a single device"),
            (None, [{"model": "TB-8", "id": 1}], "without a member id"),
            ("stacked", [{"model": "TB-8", "id": 5}], "outside 1-4"),
            ("stacked", [{"model": "TB-8", "id": 2}, {"model": "TB-8", "id": 2}],
             "declared twice"),
            ("stacked", [{"model": "TB-8"}] * 5, "at most 4 members"),
            (None, [{"model": "TB-8", "modules": {"A": "MOD4"}}], "has no bay 'A'"),
            (None, [{"model": "TB-4M", "modules": {"B": "MOD4"}}], "has no bay 'B'"),
            (None, [{"model": "TB-4M", "modules": {"A": "MOD9"}}],
             "does not take 'MOD9'"),
            (None, [{"model": "TB-4M", "modules": {"A": "MOD4", "a": "MOD1"}}],
             "stated twice"),
        ],
    )
    def test_each_refusal_says_what_is_allowed(self, registry, mode, members, needle):
        with pytest.raises(DeploymentError) as exc:
            _compile(registry, mode, *members)
        assert needle in str(exc.value)

    def test_models_of_different_families_cannot_share_a_deployment(self, registry):
        with pytest.raises(DeploymentError, match="cannot share a deployment"):
            _compile(registry, "stacked", {"model": "TB-8"}, {"model": "OB-2"})

    def test_a_vendor_is_part_of_the_lookup(self, registry):
        with pytest.raises(DeploymentError, match="no device model"):
            compile_deployment(
                Deployment(vendor="cisco_iosxe", members=[MemberSpec(model="TB-8")]),
                registry,
            )

    def test_a_model_may_be_limited_to_some_modes(self):
        data = _data()
        data["models"]["TB-8"]["modes"] = ["standalone"]
        registry = DeviceModelRegistry([_family(data)])
        assert _compile(registry, "standalone", {"model": "TB-8"}).names()[0] == "1"
        with pytest.raises(DeploymentError, match="does not support mode 'stacked'"):
            _compile(registry, "stacked", {"model": "TB-8"})

    def test_a_deployment_needs_a_member(self):
        with pytest.raises(ValueError):
            Deployment(vendor="aruba_aoss", members=[])

    def test_a_rule_error_is_a_deployment_error_not_a_crash(self, registry, monkeypatch):
        """A naming rule raises ValueError for coordinates outside its
        grammar.  That must reach an API caller as a refusal, not as an
        unhandled exception."""
        def refuse(_request):
            raise ValueError("no such port")

        monkeypatch.setattr(dm, "_naming_rules", lambda: {
            "aoss": NamingRuleSpec(render=refuse, roles=frozenset({"access", "uplink"})),
        })
        with pytest.raises(DeploymentError, match="cannot name port 1"):
            _compile(registry, None, {"model": "TB-8"})

    def test_a_naming_defect_is_reported_as_one(self, registry, monkeypatch):
        """If the model data and the rule ever produce one name twice,
        the inventory must not quietly carry a duplicate."""
        monkeypatch.setattr(dm, "_naming_rules", lambda: {
            "aoss": NamingRuleSpec(
                render=lambda _req: "1", roles=frozenset({"access", "uplink"}),
            ),
        })
        with pytest.raises(DeploymentError, match="names a port twice"):
            _compile(registry, None, {"model": "TB-8"})


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    """A port's grade is the weakest of the facts that produced it, and
    ``capture`` is granted only where a claim matches exactly."""

    def test_the_captured_deployment_is_capture_graded(self, registry):
        inv = _compile(registry, "stacked", {"model": "TB-4M", "modules": {"A": "MOD4"}})
        assert inv.evidence == "capture"
        assert {p.evidence for p in inv.ports} == {"capture"}
        # The fixture, and what establishes each part -- a capture
        # proves the names, not what each port is.
        assert inv.evidence_refs == [
            "tests/fixtures/real/x.cfg", "TB-4M sheet", "MOD4 sheet",
        ]
        assert inv.members[0].evidence == "capture"

    def test_a_sibling_model_does_not_inherit_the_capture(self, registry):
        """The capture is of a TB-4M.  A TB-8 in the same mode is only
        as good as its documents."""
        inv = _compile(registry, "stacked", {"model": "TB-8"})
        assert inv.evidence == "vendor-doc"
        assert inv.evidence_refs == ["Testbox stacking guide", "TB-8 sheet"]

    def test_another_member_id_does_not_inherit_the_capture(self, registry):
        """The capture shows member 1.  The same model as member 2 has
        names no capture shows."""
        inv = _compile(
            registry, "stacked", {"model": "TB-4M", "id": 2, "modules": {"A": "MOD4"}},
        )
        assert inv.evidence == "vendor-doc"
        assert "capture" not in {p.evidence for p in inv.ports}

    def test_another_mode_does_not_inherit_the_capture(self):
        """The capture is of the stacked mode.  A second mode that
        also carries member ids names these ports identically -- and
        is still a deployment no capture shows."""
        data = _data()
        data["modes"]["ring"] = dict(data["modes"]["stacked"], label="ring")
        registry = DeviceModelRegistry([_family(data)])
        member = {"model": "TB-4M", "id": 1, "modules": {"A": "MOD4"}}
        stacked = _compile(registry, "stacked", member)
        ring = _compile(registry, "ring", member)
        assert ring.names() == stacked.names()
        assert (stacked.evidence, ring.evidence) == ("capture", "vendor-doc")

    def test_a_module_the_capture_does_not_show_is_graded_on_its_own(self, registry):
        """Fixed panel: captured.  A MOD1 in the bay: not in the
        capture, and its port count is only inferred."""
        inv = _compile(registry, "stacked", {"model": "TB-4M", "modules": {"A": "MOD1"}})
        assert {p.evidence for p in inv.ports if not p.module} == {"capture"}
        assert inv.port("1/A1").evidence == "inferred"
        assert inv.evidence == "inferred"
        assert "MOD1 port count is from a listing." in inv.caveats

    def test_a_stack_is_as_good_as_its_weakest_member(self, registry):
        inv = _compile(
            registry, "stacked",
            {"model": "TB-4M", "modules": {"A": "MOD4"}}, {"model": "TB-8"},
        )
        assert [m.evidence for m in inv.members] == ["capture", "vendor-doc"]
        assert inv.evidence == "vendor-doc"

    def test_an_empty_bay_does_not_drag_in_the_bays_doubt(self, registry):
        """Standalone module-port names are inferred — but a standalone
        unit with NOTHING in the bay has no such port, so nothing
        inferred was compiled in."""
        inv = _compile(registry, "standalone", {"model": "TB-4M", "modules": {"A": None}})
        assert inv.evidence == "vendor-doc"
        assert "Standalone module port names are unverified." not in inv.caveats

    def test_a_fitted_bay_takes_the_bay_naming_grade(self, registry):
        inv = _compile(registry, "standalone", {"model": "TB-4M", "modules": {"A": "MOD4"}})
        assert {p.evidence for p in inv.ports if not p.module} == {"vendor-doc"}
        assert {p.evidence for p in inv.ports if p.module} == {"inferred"}
        assert inv.evidence == "inferred"
        assert "Standalone module port names are unverified." in inv.caveats

    def test_a_part_cannot_grade_itself_capture(self):
        with pytest.raises(ValueError, match="cannot be graded `capture`"):
            Grade(grade="capture")

    def test_an_inferred_grade_must_say_what_is_unverified(self):
        with pytest.raises(ValueError, match="what is unverified"):
            Grade(grade="inferred", caveat="  ")
        assert Grade(grade="inferred", caveat="Unchecked.").grade == "inferred"

    def test_weakest_grade(self):
        assert weakest_grade(["capture", "vendor-doc"]) == "vendor-doc"
        assert weakest_grade(["capture", "inferred", "vendor-doc"]) == "inferred"
        assert weakest_grade(["capture", None]) is None
        assert weakest_grade([]) is None


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestFamilySchema:
    def test_a_misspelt_field_is_an_error_not_a_silent_default(self):
        """A typo'd ``evidence`` on a target profile is ignored by
        pydantic and the profile loses its grade unnoticed.  The
        family schema forbids unknown keys instead."""
        data = _data()
        data["models"]["TB-8"]["pannel"] = {"grade": "vendor-doc"}
        with pytest.raises(ValueError, match="pannel"):
            _family(data)

    def test_the_schema_version_is_required_and_checked(self):
        data = _data()
        del data["schema"]
        with pytest.raises(ValueError, match="schema"):
            _family(data)
        data["schema"] = 2
        with pytest.raises(ValueError, match="schema"):
            _family(data)

    @pytest.mark.parametrize(
        ("field", "value", "needle"),
        [("naming", "nope", "unknown naming rule"), ("default_mode", "nope", "default_mode")],
    )
    def test_top_level_references_must_resolve(self, field, value, needle):
        data = _data()
        data[field] = value
        with pytest.raises(ValueError, match=needle):
            _family(data)

    def test_a_role_is_required_on_every_group(self):
        """A group that silently defaulted to ``access`` would turn a
        model's uplinks into access ports with every name intact."""
        data = _data()
        del data["models"]["TB-8"]["ports"][1]["role"]
        with pytest.raises(ValueError, match="role"):
            _family(data)

    def test_a_role_the_rule_cannot_name_is_refused(self):
        """AOS-S out-of-band management is the ``oobm`` context, not a
        numbered port.  A counted ``mgmt`` group would be handed the
        next free number and become port 5 of a 4-port switch."""
        data = _data()
        data["models"]["TB-4M"]["ports"].append({"role": "mgmt", "count": 1})
        with pytest.raises(ValueError, match="cannot name a 'mgmt' port"):
            _family(data)
        data = _data()
        data["modules"]["MOD4"]["ports"].append({"role": "mgmt", "count": 1})
        with pytest.raises(ValueError, match="oobm"):
            _family(data)

    @pytest.mark.parametrize(
        ("field", "value"), [("speed", "10g"), ("cage", "sfpp"), ("speed", "fast-ish")],
    )
    def test_speed_and_cage_are_closed_vocabularies(self, field, value):
        """A misspelt speed would otherwise compare as "unknown" and
        silently switch off the slower-port warning."""
        data = _data()
        data["models"]["TB-8"]["ports"][1][field] = value
        with pytest.raises(ValueError, match=field):
            _family(data)

    def test_every_speed_in_the_vocabulary_is_ranked(self):
        speeds = set(dm.PortSpeed.__args__) - {""}
        assert set(SPEED_RANK) == speeds
        assert SPEED_RANK["gig"] < SPEED_RANK["10gig"] < SPEED_RANK["40gig"]

    def test_a_bay_may_only_accept_modules_the_family_defines(self):
        data = _data()
        data["models"]["TB-4M"]["bays"]["A"]["accepts"].append("MOD99")
        with pytest.raises(ValueError, match="MOD99"):
            _family(data)

    def test_a_bay_cannot_share_a_fixed_slots_name(self):
        data = _data()
        data["models"]["TB-4M"]["ports"].append({"role": "access", "count": 2, "slot": "A"})
        with pytest.raises(ValueError, match="collide"):
            _family(data)

    def test_two_bays_cannot_differ_only_in_case(self):
        data = _data()
        data["models"]["TB-4M"]["bays"]["a"] = {"accepts": ["MOD4"]}
        with pytest.raises(ValueError, match="differs only in case"):
            _family(data)

    def test_a_module_group_cannot_choose_its_own_slot(self):
        data = _data()
        data["modules"]["MOD4"]["ports"][0]["slot"] = "B"
        with pytest.raises(ValueError, match="named by the bay"):
            _family(data)

    def test_a_model_cannot_list_a_mode_the_family_lacks(self):
        data = _data()
        data["models"]["TB-8"]["modes"] = ["vsf"]
        with pytest.raises(ValueError, match="does not define"):
            _family(data)

    def test_a_capture_must_name_a_mode_the_family_defines(self):
        data = _data()
        data["captures"][0]["mode"] = "vsf"
        with pytest.raises(ValueError, match="does not define"):
            _family(data)

    @pytest.mark.parametrize(
        "member_ids", [[4, 1], [-1, 2], [1, MAX_DEPLOYMENT_MEMBERS + 1]],
    )
    def test_incoherent_member_ranges_are_refused(self, member_ids):
        data = _data()
        data["modes"]["stacked"]["member_ids"] = member_ids
        with pytest.raises(ValueError):
            _family(data)

    def test_a_member_range_may_span_exactly_the_cap(self):
        data = _data()
        data["modes"]["stacked"]["member_ids"] = [1, MAX_DEPLOYMENT_MEMBERS]
        assert _family(data).modes["stacked"].member_limit == MAX_DEPLOYMENT_MEMBERS

    @pytest.mark.parametrize("count", [0, -1, dm._MAX_GROUP_PORTS + 1])
    def test_a_port_group_count_is_bounded(self, count):
        data = _data()
        data["models"]["TB-8"]["ports"][0]["count"] = count
        with pytest.raises(ValueError):
            _family(data)

    def test_a_port_group_may_hold_exactly_the_cap(self):
        data = _data()
        data["models"]["TB-8"]["ports"][0]["count"] = dm._MAX_GROUP_PORTS
        assert _family(data).models["TB-8"].ports[0].count == dm._MAX_GROUP_PORTS

    @pytest.mark.parametrize("member_ids", [["1", "4"], [True, 4], [1.0, 4.0]])
    def test_a_member_range_is_two_integers_and_nothing_else(self, member_ids):
        data = _data()
        data["modes"]["stacked"]["member_ids"] = member_ids
        with pytest.raises(ValueError, match="member_ids"):
            _family(data)

    @pytest.mark.parametrize("sku", ["a/b", "TB 8", "", "-x"])
    def test_a_part_number_is_a_plain_token(self, sku):
        data = _data()
        data["models"]["TB-8"]["skus"] = [sku]
        with pytest.raises(ValueError, match="must be a plain name"):
            _family(data)

    @pytest.mark.parametrize("count", ["4", 4.0, True])
    def test_a_count_is_an_integer_and_nothing_else(self, count):
        data = _data()
        data["models"]["TB-8"]["ports"][0]["count"] = count
        with pytest.raises(ValueError, match="count"):
            _family(data)

    @pytest.mark.parametrize("owner", ["models", "modules"])
    def test_the_groups_of_one_panel_or_module_are_bounded(self, owner):
        key = "TB-8" if owner == "models" else "MOD4"
        group = {"role": "uplink", "count": 1}
        data = _data()
        data[owner][key]["ports"] = [group] * dm._MAX_PORT_GROUPS
        assert len(getattr(_family(data), owner)[key].ports) == dm._MAX_PORT_GROUPS
        data[owner][key]["ports"] = [group] * (dm._MAX_PORT_GROUPS + 1)
        with pytest.raises(ValueError, match="ports"):
            _family(data)

    @pytest.mark.parametrize("value", [True, 1.0, "1"])
    def test_the_schema_number_is_the_integer(self, value):
        data = _data()
        data["schema"] = value
        with pytest.raises(ValueError, match="schema"):
            _family(data)

    @pytest.mark.parametrize(
        ("field", "value"),
        [("family", "a/b"), ("family", ""), ("vendor", "Aruba_AOSS"), ("vendor", "a/b")],
    )
    def test_a_vendor_and_a_family_are_plain_tokens(self, field, value):
        data = _data()
        data[field] = value
        with pytest.raises(ValueError, match=field):
            _family(data)

    def test_a_claim_in_a_mode_with_member_ids_must_state_them(self):
        """A default would grant ``capture`` to whichever id happened
        to be free -- an id the capture never shows."""
        data = _data()
        del data["captures"][0]["members"][0]["id"]
        with pytest.raises(ValueError, match="must state the `id`"):
            _family(data)


class TestCheckFamily:
    """Every combination a family allows is compiled when it is
    registered, so a defect is found at load and not when an operator
    first picks that combination."""

    def test_a_bay_name_the_rule_refuses_fails_at_load(self):
        data = _data()
        data["models"]["TB-4M"]["bays"] = {"AA": {"accepts": ["MOD4"]}}
        data["captures"] = []
        family = _family(data)
        with pytest.raises(DeploymentError, match="single letter"):
            check_family(family)
        with pytest.raises(DeviceModelLoadError, match="single letter"):
            DeviceModelRegistry([family])

    def test_the_combinations_compiled_at_load_are_bounded(self, monkeypatch):
        """Every bay-and-module combination of a model is compiled
        when the family loads.  That product is capped, so a file
        cannot make a start take minutes."""
        family = _family()
        check_family(family)                      # TB-4M: one bay, three choices
        monkeypatch.setattr(dm, "_MAX_BAY_COMBINATIONS", 3)
        check_family(family)
        monkeypatch.setattr(dm, "_MAX_BAY_COMBINATIONS", 2)
        with pytest.raises(DeploymentError, match="3 bay-and-module combinations"):
            check_family(family)

    def test_a_claim_in_a_mode_none_of_its_models_supports_fails_at_load(self):
        """Claims are compiled at load in their own right.  One in a
        mode no model of the family supports is never reached by
        compiling the models, and would otherwise sit in the file
        granting nothing and saying nothing."""
        data = _data()
        for model in data["models"].values():
            model["modes"] = ["standalone"]
        with pytest.raises(DeviceModelLoadError, match="does not support mode 'stacked'"):
            DeviceModelRegistry([_family(data)])

    def test_a_capture_of_a_model_the_family_lacks_fails_at_load(self):
        data = _data()
        data["captures"][0]["members"] = [{"model": "TB-404", "id": 1}]
        with pytest.raises(DeviceModelLoadError, match="no model 'TB-404'"):
            DeviceModelRegistry([_family(data)])

    def test_a_capture_with_a_module_the_bay_refuses_fails_at_load(self):
        data = _data()
        data["captures"][0]["members"] = [
            {"model": "TB-4M", "id": 1, "modules": {"A": "MOD9"}},
        ]
        with pytest.raises(DeviceModelLoadError, match="does not take 'MOD9'"):
            DeviceModelRegistry([_family(data)])

    def test_a_refused_family_leaves_the_registry_untouched(self):
        data = _data()
        data["captures"][0]["members"] = [{"model": "TB-404", "id": 1}]
        registry = DeviceModelRegistry([_family(OTHER_FAMILY_YAML)])
        with pytest.raises(DeviceModelLoadError):
            registry.add(_family(data))
        assert list(registry.families) == ["aruba_aoss/Otherbox"]
        assert registry.resolve("aruba_aoss", "TB-8") is None


class TestRegistry:
    def test_a_model_key_is_unique_across_a_vendors_families(self):
        registry = DeviceModelRegistry([_family()])
        data = _data()
        data["family"] = "Clone"
        with pytest.raises(DeviceModelLoadError, match="identifies both"):
            registry.add(_family(data))
        assert list(registry.families) == ["aruba_aoss/Testbox"]

    def test_a_sku_cannot_belong_to_two_models(self):
        data = _data()
        data["models"]["TB-4M"]["skus"].append("tb008a")
        with pytest.raises(DeviceModelLoadError, match="identifies both"):
            DeviceModelRegistry([_family(data)])

    def test_a_model_key_cannot_be_another_models_sku(self):
        """Lookup accepts a key or a SKU, so the two share one
        namespace: ``TB-8`` as some other model's part number would
        make the lookup depend on load order."""
        data = _data()
        data["models"]["TB-4M"]["skus"].append("TB-8")
        with pytest.raises(DeviceModelLoadError, match="identifies both"):
            DeviceModelRegistry([_family(data)])

    def test_the_same_family_cannot_load_twice(self):
        registry = DeviceModelRegistry([_family()])
        with pytest.raises(DeviceModelLoadError, match="already loaded and is not replaced"):
            registry.add(_family())

    def test_lookup(self, registry):
        assert registry.resolve("aruba_aoss", "TB-8")[1].model == "TB-8"
        assert registry.resolve("aruba_aoss", " tb004m ")[1].model == "TB-4M"
        assert registry.resolve("aruba_aoss", "nope") is None
        assert registry.resolve("cisco_iosxe", "TB-8") is None
        assert registry.model_keys("aruba_aoss") == ["TB-8", "TB-4M", "OB-2"]
        assert len(registry) == 2


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class TestLoader:
    def test_keys_are_backfilled(self, tmp_path: Path):
        path = tmp_path / "testbox.yaml"
        path.write_text(FAMILY_YAML, encoding="utf-8")
        family = load_family_file(path)
        assert family.key == "aruba_aoss/Testbox"
        assert family.models["TB-8"].model == "TB-8"
        assert family.modules["MOD4"].sku == "MOD4"

    @pytest.mark.parametrize(
        "text",
        [
            "- just\n- a list\n",
            "vendor: [unclosed",
            FAMILY_YAML.replace("models:", "models: [1, 2]\nignored:", 1),
            FAMILY_YAML.replace("naming: aoss", "naming: aoss\nnamming: aoss", 1),
        ],
    )
    def test_a_bad_file_raises_with_its_path(self, tmp_path: Path, text: str):
        path = tmp_path / "bad.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(DeviceModelLoadError, match="bad.yaml"):
            load_family_file(path)

    def test_a_repeated_key_is_an_error_not_last_one_wins(self, tmp_path: Path):
        """Plain YAML loading keeps the LAST of two equal keys.  A
        model block pasted twice — a merge artefact — would silently
        replace the first with whatever the second says."""
        duplicate = FAMILY_YAML.replace(
            "captures:",
            "  TB-8:\n"
            "    panel: {grade: vendor-doc}\n"
            "    ports:\n"
            "      - {role: access, count: 2}\n"
            "captures:",
        )
        path = tmp_path / "dup.yaml"
        path.write_text(duplicate, encoding="utf-8")
        with pytest.raises(DeviceModelLoadError, match="duplicate key 'TB-8'"):
            load_family_file(path)

    @pytest.mark.parametrize(
        ("content", "needle"),
        [
            (FAMILY_YAML.encode("utf-16"), "cannot be read as UTF-8"),
            (FAMILY_YAML.encode("utf-8") + b"# caf\xe9\n", "cannot be read as UTF-8"),
            (b"1: x\n" + FAMILY_YAML.encode("utf-8"), "schema validation failed"),
            (b"models: &m {x: *m}\n", "aliases"),
            (b"a: &a [1]\nb: *a\n", "aliases"),
            (FAMILY_YAML.replace("  TB-8:", "  yes:", 1).encode(), "must be a plain name"),
            (FAMILY_YAML.replace("  TB-8:", "  0755:", 1).encode(), "must be a plain name"),
            (FAMILY_YAML.replace("  TB-8:", "  'a/b':", 1).encode(), "must be a plain name"),
            (FAMILY_YAML.replace("  MOD1:", "  ~:", 1).encode(), "must be a plain name"),
        ],
    )
    def test_every_kind_of_bad_file_is_the_one_load_error(
        self, tmp_path: Path, content: bytes, needle: str,
    ):
        """A caller that skips a bad file catches ``DeviceModelLoadError``
        and nothing else, so nothing else may escape: not a decode
        error, not a ``TypeError`` for a non-string key, not the
        recursion of a self-referential alias."""
        path = tmp_path / "bad.yaml"
        path.write_bytes(content)
        with pytest.raises(DeviceModelLoadError, match=needle):
            load_family_file(path)

    def test_a_directory_named_like_a_file_is_a_load_error(self, tmp_path: Path):
        (tmp_path / "folder.yaml").mkdir()
        with pytest.raises(DeviceModelLoadError, match="cannot be read"):
            load_family_file(tmp_path / "folder.yaml")

    def test_no_bad_file_can_stop_the_directory_loading(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """The contract the application start relies on.  The files
        here are ones an operator can produce by accident (Notepad's
        "Unicode" is UTF-16) plus a failure nobody listed."""
        (tmp_path / "a_good.yaml").write_text(FAMILY_YAML, encoding="utf-8")
        (tmp_path / "b_utf16.yaml").write_bytes(OTHER_FAMILY_YAML.encode("utf-16"))
        (tmp_path / "c_latin1.yaml").write_bytes(b"# caf\xe9\n")
        (tmp_path / "d_folder.yaml").mkdir()
        (tmp_path / "e_intkey.yaml").write_bytes(b"1: x\n")
        (tmp_path / "f_alias.yaml").write_bytes(b"models: &m {x: *m}\n")
        (tmp_path / "z_other.yaml").write_text(OTHER_FAMILY_YAML, encoding="utf-8")
        real = dm.load_family_file

        def flaky(path: Path) -> FamilyDef:
            if path.name == "z_other.yaml":
                raise RuntimeError("something nobody listed")
            return real(path)

        monkeypatch.setattr(dm, "load_family_file", flaky)
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            registry = load_model_families_dir(tmp_path)
        assert list(registry.families) == ["aruba_aoss/Testbox"]
        text = caplog.text
        for name in ("b_utf16", "c_latin1", "d_folder", "e_intkey", "f_alias"):
            assert f"skip {name}.yaml" in text
        assert "skip z_other.yaml: RuntimeError: something nobody listed" in text

    def test_the_directory_loader_skips_a_bad_file_and_says_so(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ):
        (tmp_path / "a_good.yaml").write_text(FAMILY_YAML, encoding="utf-8")
        (tmp_path / "b_bad.yaml").write_text("vendor: [unclosed", encoding="utf-8")
        # The same family key with different contents: a conflict.
        (tmp_path / "c_dup.yaml").write_text(
            FAMILY_YAML.replace("count: 8,", "count: 6,"), encoding="utf-8",
        )
        (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            registry = load_model_families_dir(tmp_path)
        assert list(registry.families) == ["aruba_aoss/Testbox"]
        skipped = [r.getMessage() for r in caplog.records]
        assert any("b_bad.yaml" in m for m in skipped)
        assert any(
            "c_dup.yaml" in m and "already loaded and is not replaced" in m
            for m in skipped
        )

    def test_a_family_saved_as_yml_is_said_to_be_ignored(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ):
        """The loader and the wheel both match ``*.yaml``.  Loading
        nothing and logging "0 new family file(s)" would read as
        "there is no such family"."""
        (tmp_path / "testbox.yml").write_text(FAMILY_YAML, encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            registry = load_model_families_dir(tmp_path)
        assert len(registry) == 0
        assert "ignored testbox.yml" in caplog.text

    def test_a_missing_directory_is_an_empty_registry(self, tmp_path: Path):
        registry = load_model_families_dir(tmp_path / "absent")
        assert len(registry) == 0


class TestOverlay:
    """An operator's own families are laid over the shipped ones.  An
    overlay can ADD; it can never silently replace."""

    def _dirs(self, tmp_path: Path) -> tuple[Path, Path]:
        shipped, custom = tmp_path / "shipped", tmp_path / "custom"
        shipped.mkdir()
        custom.mkdir()
        (shipped / "testbox.yaml").write_text(FAMILY_YAML, encoding="utf-8")
        return shipped, custom

    def test_an_overlay_adds_a_family(self, tmp_path: Path):
        shipped, custom = self._dirs(tmp_path)
        (custom / "otherbox.yaml").write_text(OTHER_FAMILY_YAML, encoding="utf-8")
        registry = load_model_families_dir(shipped)
        assert load_model_families_dir(custom, into=registry) is registry
        assert list(registry.families) == [
            "aruba_aoss/Testbox", "aruba_aoss/Otherbox",
        ]

    def test_an_identical_copy_is_skipped_without_a_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ):
        """A desktop install keeps a copy of the shipped library beside
        the executable; that must not log a refusal per family on every
        start."""
        shipped, custom = self._dirs(tmp_path)
        (custom / "testbox.yaml").write_text(FAMILY_YAML, encoding="utf-8")
        registry = load_model_families_dir(shipped)
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            load_model_families_dir(custom, into=registry)
        assert list(registry.families) == ["aruba_aoss/Testbox"]
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    def test_a_changed_copy_cannot_replace_the_shipped_family(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ):
        shipped, custom = self._dirs(tmp_path)
        (custom / "testbox.yaml").write_text(
            FAMILY_YAML.replace("count: 8,", "count: 6,"), encoding="utf-8",
        )
        registry = load_model_families_dir(shipped)
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            load_model_families_dir(custom, into=registry)
        assert "is already loaded and is not replaced" in caplog.text
        inv = _compile(registry, None, {"model": "TB-8"})
        assert len(inv.names(role="access")) == 8

    def test_an_overlay_cannot_add_a_model_to_a_shipped_family(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ):
        """An overlay adds FAMILIES.  A copy of a shipped family with
        one model appended is the same family key with other
        contents: refused whole, and the new model does not resolve."""
        shipped, custom = self._dirs(tmp_path)
        (custom / "testbox.yaml").write_text(
            FAMILY_YAML.replace(
                "captures:",
                "  TB-NEW:\n"
                "    panel: {grade: vendor-doc}\n"
                "    ports:\n"
                "      - {role: access, count: 2}\n"
                "captures:",
            ),
            encoding="utf-8",
        )
        registry = load_model_families_dir(shipped)
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            load_model_families_dir(custom, into=registry)
        assert "is already loaded and is not replaced" in caplog.text
        assert registry.resolve("aruba_aoss", "TB-NEW") is None

    def test_a_missing_shipped_directory_is_a_warning_not_a_shrug(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """The shipped families are package data: their directory not
        being there is a packaging fault, and must not look like the
        optional operator directory being absent."""
        import netcanon.definitions as definitions

        monkeypatch.setattr(definitions, "LIBRARY_DIR", tmp_path / "no-library")
        custom = tmp_path / "defs"
        (custom / "model_families").mkdir(parents=True)
        (custom / "model_families" / "testbox.yaml").write_text(
            FAMILY_YAML, encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            registry = dm.load_model_families(custom)
        assert list(registry.families) == ["aruba_aoss/Testbox"]
        assert "shipped with netcanon were not found" in caplog.text

    def test_the_application_registry_always_has_the_shipped_families(
        self, tmp_path: Path,
    ):
        """An operator who points the definitions directory somewhere
        else — to keep their own backup definitions — has no
        ``model_families/`` there.  They keep the shipped ones."""
        registry = dm.load_model_families(tmp_path)
        assert "aruba_aoss/2930F" in registry.families
        (tmp_path / "model_families").mkdir()
        (tmp_path / "model_families" / "testbox.yaml").write_text(
            FAMILY_YAML, encoding="utf-8",
        )
        overlaid = dm.load_model_families(tmp_path)
        assert {"aruba_aoss/2930F", "aruba_aoss/Testbox"} <= set(overlaid.families)

    def test_the_shipped_directory_is_not_laid_over_itself(
        self, caplog: pytest.LogCaptureFixture,
    ):
        with caplog.at_level(logging.DEBUG, logger=dm.logger.name):
            dm.load_model_families(LIBRARY_DIR)
        assert "already loaded" not in caplog.text


# ---------------------------------------------------------------------------
# Legacy target profiles, read as inventories
# ---------------------------------------------------------------------------


class TestInventoryFromProfile:
    PROFILES = load_profiles_dir(LIBRARY_DIR / "target_profiles")

    def test_names_are_verbatim_and_roles_come_from_kind(self):
        profile = self.PROFILES["aruba_aoss/2930F-48G"]
        inv = inventory_from_profile(profile)
        assert inv.names() == profile.port_ids()
        assert inv.names(role="access") == [str(n) for n in range(1, 49)]
        assert inv.names(role="uplink") == ["49", "50", "51", "52"]
        assert [p.ordinal for p in inv.ports if p.role == "uplink"] == [0, 1, 2, 3]
        assert {p.member_rank for p in inv.ports} == {0}

    def test_it_says_it_is_a_legacy_read(self):
        """The order is the profile's YAML list order, which nobody has
        vouched for as faceplate order, and the member id is not known
        separately from the name."""
        profile = self.PROFILES["aruba_aoss/3810M-48G-PoEP"]
        inv = inventory_from_profile(profile)
        assert inv.origin == "legacy-profile"
        assert inv.family == "" and inv.mode == ""
        assert inv.mode_label == profile.deployment_state
        assert {p.member_id for p in inv.ports} == {None}
        assert inv.members[0].model == "3810M-48G-PoEP"

    def test_provenance_is_the_profiles_own(self):
        profile = self.PROFILES["aruba_aoss/2930F-48G"]
        inv = inventory_from_profile(profile)
        assert inv.vendor == "aruba_aoss"
        assert inv.evidence == profile.evidence == "capture"
        assert {p.evidence for p in inv.ports} == {"capture"}
        assert inv.evidence_refs == [profile.evidence_ref]
        assert inv.caveats == [profile.caveat]
        assert profile.deployment_state in inv.description

    def test_an_ungraded_profile_stays_ungraded(self):
        ungraded = next(p for p in self.PROFILES.values() if p.evidence is None)
        inv = inventory_from_profile(ungraded)
        assert inv.evidence is None
        assert inv.caveats == []

    def test_the_cage_is_not_invented_from_the_sfp_flag(self):
        """``sfp: true`` on a profile means "a pluggable cage of some
        kind" — this one is a QSFP+.  Saying ``sfp`` would be a made-up
        fact."""
        profile = self.PROFILES["aruba_aoss/3810M-24G-PoEP"]
        port = inventory_from_profile(profile, "JL078A").port("1/A1")
        assert (port.speed, port.cage) == ("40gig", "")
        assert "QSFP+" in port.notes

    def test_module_choice_follows_effective_ports(self):
        """Same semantics as the profile API: no choice means the
        default module, an unknown SKU means chassis only."""
        profile = self.PROFILES["aruba_aoss/3810M-48G-PoEP"]
        default = inventory_from_profile(profile)
        assert default.names() == profile.port_ids()
        assert default.names(role="uplink") == ["1/A1", "1/A2", "1/A3", "1/A4"]
        assert default.port("1/A1").module == "JL083A"
        qsfp = inventory_from_profile(profile, "JL078A")
        assert qsfp.names(role="uplink") == ["1/A1"]
        assert qsfp.names() == profile.port_ids(module_sku="JL078A")
        bare = inventory_from_profile(profile, "NOT-A-MODULE")
        assert bare.names(role="uplink") == []
        assert bare.names() == [p.id for p in profile.ports]

    def test_a_console_port_is_not_an_inventory_port(self):
        profile = TargetProfile(
            vendor="x", model="y",
            ports=[
                {"id": "1", "kind": "physical"},
                {"id": "con0", "kind": "console"},
                {"id": "mgmt0", "kind": "mgmt"},
            ],
        )
        inv = inventory_from_profile(profile)
        assert inv.names() == ["1", "mgmt0"]
        assert inv.port("mgmt0").role == "mgmt"
        assert [p.index for p in inv.ports] == [0, 2]

    def test_a_profile_with_no_ports_is_an_empty_ungraded_inventory(self):
        """``opnsense/Generic`` lists no ports.  That means "not
        modelled", and must not read as a graded, zero-port device."""
        profile = TargetProfile(vendor="x", model="y", evidence="vendor-doc")
        inv = inventory_from_profile(profile)
        assert inv.ports == []
        assert inv.evidence is None

    def test_every_shipped_profile_reads_without_a_duplicate_name(self):
        for key, profile in self.PROFILES.items():
            for sku in [None, *profile.module_skus()]:
                names = inventory_from_profile(profile, sku).names()
                assert len(names) == len(set(names)), (key, sku)


class TestUnprovenClaims:
    """``capture`` means a test re-proves the claim against a committed
    fixture on every run.  A claim nothing re-proves -- any claim in an
    operator's own family file -- names a fixture nobody reads, so it
    grants nothing."""

    @pytest.fixture(autouse=True)
    def _not_proven(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            dm, "PROVEN_CAPTURE_CLAIMS", dm.PROVEN_CAPTURE_CLAIMS - {TESTBOX_CLAIM},
        )

    def test_it_grants_no_capture_grade(self, registry):
        inv = _compile(registry, "stacked", {"model": "TB-4M", "modules": {"A": "MOD4"}})
        assert inv.evidence == "vendor-doc"
        assert "capture" not in {p.evidence for p in inv.ports}
        assert "tests/fixtures/real/x.cfg" not in inv.evidence_refs

    def test_it_cannot_retire_an_inferred_caveat(self):
        data = _data()
        data["models"]["TB-4M"]["panel"] = {
            "grade": "inferred", "caveat": "TB-4M panel is a guess.",
        }
        registry = DeviceModelRegistry([_family(data)])
        inv = _compile(registry, "stacked", {"model": "TB-4M", "modules": {"A": "MOD4"}})
        assert inv.evidence == "inferred"
        assert "TB-4M panel is a guess." in inv.caveats

    def test_the_directory_loader_says_which_claims_grant_nothing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ):
        (tmp_path / "testbox.yaml").write_text(FAMILY_YAML, encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger=dm.logger.name):
            registry = load_model_families_dir(tmp_path)
        assert list(registry.families) == ["aruba_aoss/Testbox"]
        assert "1 capture claim(s) are not re-proven" in caplog.text
        assert "tests/fixtures/real/x.cfg" in caplog.text


class TestAClaimIsTheWholeClaim:
    """What is trusted is one claim in full: this fixture, this
    mode, these members with these modules."""

    def test_the_same_members_cited_from_another_fixture_grant_nothing(self):
        data = _data()
        data["captures"][0]["fixture"] = "tests/fixtures/real/another.cfg"
        registry = DeviceModelRegistry([_family(data)])
        inv = _compile(registry, "stacked", {"model": "TB-4M", "id": 1, "modules": {"A": "MOD4"}})
        assert inv.evidence == "vendor-doc"
        assert "tests/fixtures/real/another.cfg" not in inv.evidence_refs

    def test_a_bay_the_capture_shows_empty_proves_nothing_about_a_module(self, monkeypatch):
        """A claim for the chassis with the bay empty.  The panel is
        proven; a module fitted to the bay is not, although the
        model and member match."""
        data = _data()
        data["captures"][0]["members"] = [{"model": "TB-4M", "id": 1, "modules": {"A": None}}]
        claim = ("aruba_aoss/Testbox", "tests/fixtures/real/x.cfg", "stacked", (("TB-4M", 1, ()),))
        monkeypatch.setattr(dm, "PROVEN_CAPTURE_CLAIMS", dm.PROVEN_CAPTURE_CLAIMS | {claim})
        registry = DeviceModelRegistry([_family(data)])
        inv = _compile(registry, "stacked", {"model": "TB-4M", "id": 1, "modules": {"A": "MOD4"}})
        grades = {port.name: port.evidence for port in inv.ports}
        assert grades["1/1"] == "capture" and grades["1/A1"] == "vendor-doc"

    def test_a_claim_that_does_not_compile_fails_the_family(self):
        """A claim is compiled when its family loads, so one that
        names a member number outside the mode is found then, not
        when somebody declares that deployment."""
        data = _data()
        data["captures"][0]["members"] = [{"model": "TB-4M", "id": 9, "modules": {"A": "MOD4"}}]
        with pytest.raises(Exception, match="9"):
            check_family(_family(data))


class TestWhatACaptureProves:
    """Names, and nothing else: it retires the caveat of the naming fact
    and keeps the caveat of the panel or module fact."""

    def _registry(self) -> DeviceModelRegistry:
        data = _data()
        data["modes"]["stacked"]["naming"]["caveat"] = "Stacked names are taken on trust."
        data["models"]["TB-4M"]["panel"] = {
            "grade": "inferred", "caveat": "TB-4M port roles are a guess.",
        }
        return DeviceModelRegistry([_family(data)])

    def test_the_names_are_proven_and_the_naming_caveat_goes(self):
        inv = _compile(self._registry(), "stacked", {"model": "TB-4M", "modules": {"A": "MOD4"}})
        assert inv.evidence == "capture"
        assert "Stacked names are taken on trust." not in inv.caveats

    def test_the_panel_caveat_stays(self):
        """That a port is an access port is a fact about the panel; no
        config shows it."""
        inv = _compile(self._registry(), "stacked", {"model": "TB-4M", "modules": {"A": "MOD4"}})
        assert "TB-4M port roles are a guess." in inv.caveats

    def test_a_deployment_the_claim_does_not_cover_keeps_both(self):
        inv = _compile(self._registry(), "stacked", {"model": "TB-8"})
        assert "Stacked names are taken on trust." in inv.caveats


class TestDeclarationsAreBounded:
    """What a request carries selects from loaded data.  It is typed
    strictly and bounded, so a declaration cannot be read as something
    the client did not say, nor made arbitrarily large."""

    @pytest.mark.parametrize("member_id", ["2", 2.0, True])
    def test_a_member_id_is_an_integer_and_nothing_else(self, member_id):
        with pytest.raises(ValueError, match="id"):
            MemberSpec(model="TB-8", id=member_id)
        assert MemberSpec(model="TB-8", id=2).id == 2

    def test_a_deployment_holds_at_most_the_member_cap(self):
        member = {"model": "TB-8"}
        full = DeploymentSpec(members=[member] * MAX_DEPLOYMENT_MEMBERS)
        assert len(full.members) == MAX_DEPLOYMENT_MEMBERS
        with pytest.raises(ValueError, match="members"):
            DeploymentSpec(members=[member] * (MAX_DEPLOYMENT_MEMBERS + 1))

    def test_names_and_bays_are_bounded(self):
        assert MemberSpec(model="m" * MAX_DECLARED_NAME).model
        with pytest.raises(ValueError, match="model"):
            MemberSpec(model="m" * (MAX_DECLARED_NAME + 1))
        bays = {f"B{n}": "MOD4" for n in range(MAX_DECLARED_BAYS + 1)}
        with pytest.raises(ValueError, match="modules"):
            MemberSpec(model="TB-8", modules=bays)
        with pytest.raises(ValueError, match="mode"):
            DeploymentSpec(mode="m" * (MAX_DECLARED_NAME + 1), members=[{"model": "TB-8"}])
