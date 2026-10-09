"""Source-device detection — what a config says it came from, and the proposal built on it.

Two layers, tested apart:

* the AOS-S **detector** reads the lines that state the hardware.  It
  is pinned on short configs written for the purpose (every stanza form
  HPE's guides and real captures show) and on the committed captures;
* :func:`propose_deployment` resolves a detection against the model
  registry and checks it against the port names the config uses.

The detector must agree with the capture claims.  A claim says, by
hand, which deployment a committed capture is of; the detector says
the same thing by reading the capture.  If the two ever differ, one of
them is wrong about a real device.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration import deployment_detect
from netcanon.migration.codecs.aruba_aoss.deployment_detect import detect_deployment
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.deployment_detect import detection_vendors, propose_deployment
from netcanon.migration.device_models import (
    Deployment,
    DeviceModelRegistry,
    FamilyDef,
    compile_deployment,
    load_model_families_dir,
)
from netcanon.models.migration import MigrationJobStatus
from netcanon.models.port_inventory import DeploymentProposal, DetectedDeployment, DetectedMember
from netcanon.services.migration_pipeline import run_plan_with_models

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = load_model_families_dir(LIBRARY_DIR / "model_families")
AOSS = get_codec("aruba_aoss")
FIXTURES = REPO_ROOT / "tests/fixtures/real/aruba_aoss"


def _capture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


CAPTURE_2930F_48 = _capture("hpe_community_2930f_wc1607_intervlan.cfg")
CAPTURE_2930F_8 = _capture("hpe_community_2930f_wc1610_dhcp_server.cfg")
CAPTURE_2930M = _capture("user_contrib_2930m_wc1611.cfg")

# None of the addresses below is a real device's: aabbcc-... is a
# placeholder in the AOS-S MAC notation.
STANDALONE = """; JL322A Configuration Editor; Created on release #WC.16.07.0003
; Ver #14:01.4f.f8.1d.9b.3f.bf.bb.ef.7c.59.fc.6b.fb.9f.fc.ff.ff.37.ef:02
hostname "sw"
module 1 type jl322a
flexible-module A type JL083A
vlan 1
   name "DEFAULT_VLAN"
   untagged 1-48,A1-A4
   exit
"""

STACKED = """; hpStack_WC Configuration Editor; Created on release #WC.16.07.0003
hostname "stack"
stacking
   member 1 type "JL322A" mac-address aabbcc-000001
   member 1 priority 200
   member 1 flexible-module A type JL083A
   member 2 type "R0M67A" mac-address aabbcc-000002
   member 2 flexible-module A type JL078A
   exit
vlan 1
   name "DEFAULT_VLAN"
   untagged 1/1-1/48,1/A1-1/A4,2/1-2/48,2/A1
   exit
"""

VSF = """; hpStack_WC Configuration Editor; Created on release #WC.16.06.0006
hostname "fabric"
vsf
   enable domain 1
   member 1
      type "JL557A" mac-address aabbcc-000011
      priority 200
      link 1 1/1-1/4
      exit
   member 3
      type "JL262A" mac-address aabbcc-000013
      link 1 3/49
      exit
   port-speed 1g
   exit
vlan 1
   name "DEFAULT_VLAN"
   untagged 1/5-1/52,3/1-3/48,3/50-3/52
   exit
"""


def _members(detected: DetectedDeployment) -> list[tuple[int | None, str, dict[str, str]]]:
    return [(m.id, m.part, m.modules) for m in detected.members]


# ---------------------------------------------------------------------------
# The AOS-S detector
# ---------------------------------------------------------------------------


class TestAossDetector:
    def test_a_switch_that_is_not_stacked(self) -> None:
        """The banner and the ``module 1`` line carry the chassis part
        number; the bay is a top-level line."""
        detected = detect_deployment(STANDALONE)
        assert detected.fabric == ""
        assert _members(detected) == [(None, "JL322A", {"A": "JL083A"})]
        assert detected.evidence == [
            "; JL322A Configuration Editor",
            "module 1 type jl322a",
            "flexible-module A type JL083A",
        ]

    def test_backplane_stacking(self) -> None:
        """Each member's model and module are in the ``stacking``
        stanza; the banner names no model at all."""
        detected = detect_deployment(STACKED)
        assert detected.fabric == "stacking"
        assert _members(detected) == [
            (1, "JL322A", {"A": "JL083A"}),
            (2, "R0M67A", {"A": "JL078A"}),
        ]

    def test_vsf_nests_each_member(self) -> None:
        """A member's type is on its own line inside a ``member N``
        block, and member ids need not be consecutive."""
        detected = detect_deployment(VSF)
        assert detected.fabric == "vsf"
        assert _members(detected) == [(1, "JL557A", {}), (3, "JL262A", {})]

    def test_a_part_number_need_not_start_with_j(self) -> None:
        """R0M67A and R0M68A are 2930M chassis.  A detector keyed to a
        leading ``J`` would miss a quarter of the family."""
        text = STANDALONE.replace("JL322A", "R0M68A").replace("jl322a", "r0m68a")
        assert _members(detect_deployment(text))[0][1] == "R0M68A"

    def test_the_banner_alone_is_enough_for_a_standalone_switch(self) -> None:
        text = STANDALONE.replace("module 1 type jl322a\n", "")
        assert _members(detect_deployment(text)) == [(None, "JL322A", {"A": "JL083A"})]

    @pytest.mark.parametrize("banner", ["hpStack_WC", "Stack_WC"])
    def test_both_spellings_of_the_stack_banner(self, banner: str) -> None:
        """Every real capture says ``hpStack_WC``; HPE's guides print
        ``Stack_WC`` in places.  Neither is a part number."""
        text = STACKED.replace("hpStack_WC", banner)
        assert _members(detect_deployment(text))[0] == (1, "JL322A", {"A": "JL083A"})

    @pytest.mark.parametrize("banner", ["hpStack_WC", "Stack_WC", "hpStack_KB"])
    def test_a_stack_banner_with_the_stanza_cut_off_states_nothing(self, banner: str) -> None:
        """The stack banner carries no model.  Without the stanza the
        text does not say what it came from.  That is reported as a
        detection with no members and the reason, not as "this config
        states nothing"."""
        text = f"; {banner} Configuration Editor; Created on release #WC.16.10.0015\nvlan 1\n   exit\n"
        detected = detect_deployment(text)
        assert detected.members == []
        assert "names no model" in detected.notes[0]

    def test_a_fabric_stanza_that_names_no_member(self) -> None:
        detected = detect_deployment("vsf\n   enable domain 1\n   exit\n")
        assert (detected.fabric, detected.members) == ("vsf", [])
        assert "no line in it names a member" in detected.notes[0]

    @pytest.mark.parametrize("text", ["", "hostname x\n", "vlan 1\n   untagged 1-48\n   exit\n"])
    def test_text_that_states_no_device(self, text: str) -> None:
        assert detect_deployment(text) is None

    def test_windows_line_endings(self) -> None:
        for text in (STANDALONE, STACKED, VSF):
            assert _members(detect_deployment(text.replace("\n", "\r\n"))) == (
                _members(detect_deployment(text))
            )

    def test_a_mac_address_never_reaches_the_evidence(self) -> None:
        """A member's MAC identifies one physical device.  The evidence
        lines are shown to an operator and may be logged."""
        for text in (STACKED, VSF, CAPTURE_2930M):
            detected = detect_deployment(text)
            assert detected.evidence
            assert not [line for line in detected.evidence if "mac-address" in line]
            assert not [line for line in detected.evidence if "aabbcc" in line]

    def test_the_notes_say_what_the_lines_do_not_prove(self) -> None:
        stacked = detect_deployment(STACKED).notes
        assert any("provisioned for" in n and "member" in n for n in stacked)
        assert any("does not show that a module is fitted" in n for n in stacked)
        assert detect_deployment(STANDALONE.replace("flexible-module A type JL083A\n", "")).notes == []

    def test_a_modular_chassis_is_said_to_be_one(self) -> None:
        detected = detect_deployment(_capture("hpe_community_5406rzl2_kb1515.cfg"))
        assert _members(detected) == [(None, "J9850A", {})]
        assert any("modular chassis" in n for n in detected.notes)

    def test_a_banner_that_disagrees_with_the_module_line(self) -> None:
        text = STANDALONE.replace("module 1 type jl322a", "module 1 type jl321a")
        detected = detect_deployment(text)
        assert _members(detected)[0][1] == "JL321A"
        assert "banner says JL322A" in detected.notes[0]

    def test_a_member_block_of_another_stanza_is_not_a_stack_member(self) -> None:
        """A stacked config nests ``member N`` blocks under ``oobm`` too.
        Only the ``stacking`` / ``vsf`` stanza names members."""
        assert _members(detect_deployment(CAPTURE_2930M)) == [(1, "JL323A", {"A": "JL083A"})]


# ---------------------------------------------------------------------------
# The proposal
# ---------------------------------------------------------------------------


class TestProposal:
    def test_a_standalone_capture(self) -> None:
        proposal = propose_deployment(AOSS, CAPTURE_2930F_48, REGISTRY)
        assert proposal.stated and proposal.consistent
        assert (proposal.family, proposal.mode) == ("aruba_aoss/2930F", "standalone")
        assert proposal.deployment.model_dump() == {
            "mode": "standalone",
            "members": [{"model": "2930F-48G-4SFP", "id": None, "modules": {}}],
        }
        assert (proposal.used_port_count, proposal.missing_ports) == (52, [])
        assert proposal.inventory.port_count == 52

    def test_a_stacked_capture(self) -> None:
        proposal = propose_deployment(AOSS, CAPTURE_2930M, REGISTRY)
        assert proposal.consistent
        assert proposal.deployment.model_dump() == {
            "mode": "stacked",
            "members": [
                {"model": "2930M-40G-8SR-PoEP", "id": 1, "modules": {"A": "JL083A"}},
            ],
        }
        assert proposal.members == [
            DetectedMember(part="JL323A", id=1, modules={"A": "JL083A"},
                           model="2930M-40G-8SR-PoEP"),
        ]

    def test_a_two_member_stack_of_different_models(self) -> None:
        proposal = propose_deployment(AOSS, STACKED, REGISTRY)
        assert proposal.consistent, proposal.missing_ports
        assert [m.model for m in proposal.deployment.members] == [
            "2930M-48G-PoEP", "2930M-40G-8SR-PoE-Class6",
        ]
        assert [m.id for m in proposal.deployment.members] == [1, 2]

    def test_a_vsf_fabric_keeps_its_member_ids(self) -> None:
        proposal = propose_deployment(AOSS, VSF, REGISTRY)
        assert proposal.mode == "vsf" and proposal.consistent
        assert [(m.model, m.id) for m in proposal.deployment.members] == [
            ("2930F-48G-740W-PoEP-4SFP", 1), ("2930F-48G-PoEP-4SFP", 3),
        ]

    def test_the_mode_follows_the_stanza_not_the_family_default(self) -> None:
        """A 2930M's default mode is stacked.  A config with no
        ``stacking`` stanza is not stacked, whatever the default."""
        proposal = propose_deployment(AOSS, STANDALONE, REGISTRY)
        assert proposal.mode == "standalone"
        assert proposal.deployment.members[0].id is None
        assert proposal.consistent
        assert not proposal.inventory.mode_defaulted

    def test_every_proven_capture_claim_is_what_the_detector_reads(self) -> None:
        """A capture claim is written by hand; the detector reads the
        same capture.  They are two statements about one real device
        and must compile to the same ports."""
        checked = 0
        for family in REGISTRY.families.values():
            for claim in family.captures:
                raw = (REPO_ROOT / claim.fixture).read_text(encoding="utf-8")
                proposal = propose_deployment(AOSS, raw, REGISTRY)
                claimed = compile_deployment(
                    Deployment(vendor=family.vendor, mode=claim.mode, members=claim.members),
                    REGISTRY,
                )
                assert proposal.deployment is not None, claim.fixture
                assert proposal.mode == claim.mode, claim.fixture
                assert proposal.inventory == claimed.summary(), claim.fixture
                assert proposal.consistent, claim.fixture
                checked += 1
        assert checked

    def test_the_proposal_is_plain_data(self) -> None:
        proposal = propose_deployment(AOSS, CAPTURE_2930M, REGISTRY)
        assert DeploymentProposal.model_validate(proposal.model_dump()) == proposal


class TestProposalsThatStopShort:
    """Each way a config can fail to yield a deployment, with the
    reason said."""

    def test_a_part_number_no_family_describes(self) -> None:
        proposal = propose_deployment(
            AOSS, _capture("hpe_community_2920_wb1608_dhcp_snooping.cfg"), REGISTRY,
        )
        assert proposal.stated
        assert proposal.deployment is None and proposal.consistent is None
        assert proposal.unknown_parts == ["J9729A"]
        assert proposal.members[0].model == ""
        assert any("No model family describes J9729A" in n for n in proposal.notes)

    def test_a_config_that_states_nothing(self) -> None:
        proposal = propose_deployment(AOSS, "hostname x\n", REGISTRY)
        assert not proposal.stated and proposal.deployment is None
        assert "does not say which device" in proposal.notes[0]

    def test_a_vendor_with_no_detector(self) -> None:
        proposal = propose_deployment(get_codec("cisco_iosxe_cli"), "hostname x\n", REGISTRY)
        assert not proposal.stated and proposal.deployment is None
        assert "No detector reads the hardware lines of a cisco_iosxe" in proposal.notes[0]

    def test_members_of_two_families(self) -> None:
        text = STACKED.replace('member 2 type "R0M67A"', 'member 2 type "JL260A"')
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment is None
        assert any("different model families" in n for n in proposal.notes)

    def test_a_module_the_bay_does_not_take(self) -> None:
        """JL079A is a 3810M module.  What the config states is passed
        on as stated, and the registry's refusal is the note."""
        text = STANDALONE.replace("flexible-module A type JL083A", "flexible-module A type JL079A")
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment is None
        assert any("does not compile" in n and "JL079A" in n for n in proposal.notes)

    def test_a_fabric_the_family_has_no_mode_for(self) -> None:
        """A 2930F stacks by VSF only.  A ``stacking`` stanza naming one
        is taken as stated — it maps to the one mode with member ids."""
        text = STACKED.replace("JL322A", "JL260A").replace("R0M67A", "JL260A").replace(
            "   member 1 flexible-module A type JL083A\n", "",
        ).replace("   member 2 flexible-module A type JL078A\n", "")
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.mode == "vsf"

    def test_two_modes_of_the_kind_and_no_way_to_choose(self) -> None:
        family = REGISTRY.families["aruba_aoss/2930F"]
        data = family.model_dump(by_alias=True)
        data["modes"]["ring"] = dict(data["modes"]["vsf"], label="ring")
        data["captures"] = []
        registry = DeviceModelRegistry([FamilyDef.model_validate(data)])
        chosen = propose_deployment(AOSS, VSF, registry)
        assert chosen.mode == "vsf"          # the config's own word names a mode
        ambiguous = propose_deployment(AOSS, VSF.replace("vsf\n", "stacking\n"), registry)
        assert ambiguous.deployment is None
        assert any("more than one such mode (vsf, ring)" in n for n in ambiguous.notes)

    def test_a_config_that_cannot_be_parsed_is_proposed_unchecked(self, monkeypatch) -> None:
        def boom(_raw: str):
            raise ValueError("no")

        monkeypatch.setattr(AOSS, "parse", boom)
        proposal = propose_deployment(AOSS, CAPTURE_2930F_48, REGISTRY)
        assert proposal.deployment is not None
        assert proposal.consistent is None
        assert any("could not be parsed" in n for n in proposal.notes)


class TestTheCheckAgainstTheConfig:
    """What makes a proposal worth more than a regex: the ports the
    config uses should all be ports of the device it says it is."""

    def test_a_module_the_config_does_not_state(self) -> None:
        """The config uses ``A1``-``A4`` and has no ``flexible-module``
        line.  The proposal is a 2930M with an empty bay — and says
        four names do not fit it."""
        text = STANDALONE.replace("flexible-module A type JL083A\n", "")
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment.members[0].modules == {}
        assert proposal.consistent is False
        assert proposal.missing_ports == ["A1", "A2", "A3", "A4"]
        assert any("A module may be fitted" in n for n in proposal.notes)
        assert any("bay A was not stated" in c for c in proposal.inventory.caveats)

    def test_port_names_from_the_other_mode(self) -> None:
        """A standalone banner over stacked port names: two texts
        pasted together, or a stanza cut off."""
        text = STANDALONE.replace("untagged 1-48,A1-A4", "untagged 1/1-1/48")
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.consistent is False
        assert len(proposal.missing_ports) == 48
        assert any("and 40 more" in n for n in proposal.notes)

    def test_a_lag_and_an_svi_are_not_missing_ports(self) -> None:
        text = STANDALONE.replace(
            "vlan 1\n", "trunk 47-48 trk1 lacp\nvlan 1\n   ip address 192.0.2.1 255.255.255.0\n",
        ).replace("untagged 1-48,A1-A4", "untagged 1-46,A1-A4\n   tagged Trk1")
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.consistent, proposal.missing_ports


class TestTheWholeCorridorWithoutTypingTheSource:
    def test_detect_then_translate(self) -> None:
        """What the picker in the rename modal will do: read the source
        device from the config, then pair it with the chosen target."""
        proposal = propose_deployment(AOSS, CAPTURE_2930F_48, REGISTRY)
        source = compile_deployment(
            Deployment(vendor="aruba_aoss", **proposal.deployment.model_dump()), REGISTRY,
        )
        target = compile_deployment(
            Deployment(vendor="aruba_aoss", mode="stacked", members=[
                {"model": "JL322A", "id": 1, "modules": {"A": "JL083A"}},
            ]),
            REGISTRY,
        )
        job = run_plan_with_models(AOSS, AOSS, CAPTURE_2930F_48, source, target)
        assert job.status == MigrationJobStatus.completed
        assert job.port_renames["49"] == "1/A1"
        assert len(job.port_mapping_plan.used_pairings) == 52

    def test_a_fabric_read_from_its_config_lands_on_a_stack_member_by_member(self) -> None:
        """A stack on both sides, the source never typed.  The fabric's
        members are numbered 1 and 3 in its own ``vsf`` stanza; the
        proposal lists them in that order, so member 3 is the second
        member and lands on member 2 of the stack -- and the plan says
        which member went to which."""
        proposal = propose_deployment(AOSS, VSF, REGISTRY)
        assert [m.id for m in proposal.deployment.members] == [1, 3]
        source = compile_deployment(
            Deployment(vendor="aruba_aoss", **proposal.deployment.model_dump()), REGISTRY,
        )
        target = compile_deployment(
            Deployment(vendor="aruba_aoss", mode="stacked", members=[
                {"model": "JL322A", "id": 1, "modules": {"A": "JL083A"}},
                {"model": "JL322A", "id": 2, "modules": {"A": "JL083A"}},
            ]),
            REGISTRY,
        )
        job = run_plan_with_models(AOSS, AOSS, VSF, source, target)
        plan = job.port_mapping_plan
        assert job.status == MigrationJobStatus.completed
        assert plan.off_inventory == [] and plan.unplaced == []
        # 104 ports, less the five the fabric uses as its own links.
        assert len(plan.used_pairings) == 99
        assert (job.port_renames["3/1"], job.port_renames["3/48"]) == ("2/1", "2/48")
        assert (job.port_renames["1/50"], job.port_renames["3/50"]) == ("1/A2", "2/A2")
        assert "1/5" not in job.port_renames
        (line,) = [w for w in job.warnings if "pair in the order they are declared" in w]
        assert line.endswith("source member 3 with target member 2")
        assert "vsf" not in job.rendered and "aabbcc" not in job.rendered


class TestDetectorTable:
    def test_every_detector_belongs_to_a_vendor_some_codec_has(self) -> None:
        from netcanon.migration.codecs.registry import list_public_codecs

        vendors = {get_codec(name).capabilities.vendor_id for name in list_public_codecs()}
        assert set(detection_vendors()) <= vendors
        assert "aruba_aoss" in detection_vendors()

    def test_a_detector_that_returns_nothing_is_not_an_error(self, monkeypatch) -> None:
        monkeypatch.setattr(deployment_detect, "_detectors", lambda: {"aruba_aoss": lambda _raw: None})
        proposal = propose_deployment(AOSS, CAPTURE_2930F_48, REGISTRY)
        assert not proposal.stated and proposal.deployment is None
