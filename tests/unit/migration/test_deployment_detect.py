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

import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration import deployment_detect
from netcanon.migration.codecs.aruba_aoss.deployment_detect import detect_deployment
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.deployment_detect import (
    MAX_EVIDENCE_LINES,
    MAX_MISSING_PORTS,
    MAX_NOTE_LENGTH,
    MAX_NOTES,
    detection_vendors,
    propose_deployment,
)
from netcanon.migration.device_models import (
    Deployment,
    DeviceModelRegistry,
    FamilyDef,
    compile_deployment,
    load_model_families_dir,
)
from netcanon.models.migration import MigrationJobStatus
from netcanon.models.port_inventory import (
    MAX_DECLARED_BAYS,
    MAX_DEPLOYMENT_MEMBERS,
    DeploymentProposal,
    DetectedDeployment,
    DetectedMember,
)
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


#: Which codec reads a vendor's configs.  A vendor that gains a
#: detector has to be named here: the tests that walk every detector
#: fail until it is.
_CODEC_OF = {"aruba_aoss": "aruba_aoss"}

#: The words a vendor's detector reports as ``fabric``: its configs'
#: own names for the stanza a stack's members are in.
_STANZA_WORDS = {"aruba_aoss": ("stacking", "vsf")}

_T = TypeVar("_T")


def _members(detected: DetectedDeployment) -> list[tuple[int | None, str, dict[str, str]]]:
    return [(m.id, m.part, m.modules) for m in detected.members]


def _within(seconds: float, call: Callable[[], _T]) -> _T:
    """Run *call*, and fail if it is slow twice.

    The clock is the wall's, on a machine doing other things: one slow
    reading is the machine, two are the code.  A reading several times
    over is not asked for again -- work that grows with the square of
    the text takes minutes, and a second run of it holds the job.
    """
    took = 0.0
    for _ in range(2):
        started = time.perf_counter()
        result = call()
        took = time.perf_counter() - started
        if took < seconds:
            return result
        if took >= 4 * seconds:
            break
    raise AssertionError(f"took {took:.1f} s; work that fits the length of this text is milliseconds")


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
        # A nested type line does not say whose it is; the evidence does.
        assert detected.evidence == [
            "; hpStack_WC Configuration Editor", "vsf",
            'member 1: type "JL557A"', 'member 3: type "JL262A"',
        ]

    def test_a_part_number_need_not_start_with_j(self) -> None:
        """R0M67A and R0M68A are 2930M chassis.  Each way a part is
        read has to take one: the banner alone, the ``module 1`` line,
        and a member line of a stanza."""
        banner_only = '; R0M68A Configuration Editor; Created on release #WC.16.07.0003\nhostname "sw"\n'
        assert _members(detect_deployment(banner_only)) == [(None, "R0M68A", {})]
        module_line = STANDALONE.replace("JL322A", "R0M68A").replace("jl322a", "r0m68a")
        assert _members(detect_deployment(module_line))[0][1] == "R0M68A"
        assert _members(detect_deployment(STACKED))[1][:2] == (2, "R0M67A")

    def test_the_banner_alone_is_enough_for_a_standalone_switch(self) -> None:
        text = STANDALONE.replace("module 1 type jl322a\n", "")
        assert _members(detect_deployment(text)) == [(None, "JL322A", {"A": "JL083A"})]

    @pytest.mark.parametrize("banner", ["hpStack_WC", "Stack_WC"])
    def test_both_spellings_of_the_stack_banner(self, banner: str) -> None:
        """The committed stacked capture says ``hpStack_WC``; HPE's
        guides print ``Stack_WC`` in places.  Neither is a part number."""
        text = STACKED.replace("hpStack_WC", banner)
        assert _members(detect_deployment(text))[0] == (1, "JL322A", {"A": "JL083A"})

    @pytest.mark.parametrize("banner", ["hpStack_WC", "Stack_WC", "hpStack_KB", "HPSTACK_WC"])
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
            assert not [line for line in detected.evidence if _MAC_SHAPE.search(line)]

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
        # A family of a vendor with no detector has no second
        # statement to compare, and is passed over.
        assert set(_CODEC_OF) == set(detection_vendors())
        checked = 0
        for family in REGISTRY.families.values():
            if family.vendor not in _CODEC_OF:
                continue
            for claim in family.captures:
                raw = (REPO_ROOT / claim.fixture).read_text(encoding="utf-8")
                proposal = propose_deployment(get_codec(_CODEC_OF[family.vendor]), raw, REGISTRY)
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
        assert proposal.notes == [
            "No detector reads the hardware lines of cisco_iosxe configurations yet; "
            "declare the device yourself."
        ]

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

    def test_a_stacking_stanza_that_names_a_2930f_is_its_one_stacking_mode(self) -> None:
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

    @pytest.mark.parametrize("raised", [ValueError("no"), ParseError("no"), RecursionError()])
    def test_a_config_that_cannot_be_parsed_is_proposed_unchecked(self, monkeypatch, raised) -> None:
        """``ParseError`` is what a parser is documented to raise; the
        others are what one may raise anyway."""
        def boom(_raw: str):
            raise raised

        monkeypatch.setattr(AOSS, "parse", boom)
        proposal = propose_deployment(AOSS, CAPTURE_2930F_48, REGISTRY)
        assert proposal.deployment is not None
        assert proposal.consistent is None
        assert any("could not be parsed" in n for n in proposal.notes)

    def test_text_the_parser_itself_refuses(self) -> None:
        """Nothing put in the parser's place: a paste that begins like
        JSON is refused by the AOS-S parser, and states a device."""
        text = '{"a": 1}\n' + _JL322A_TOP + "vlan 1\n   untagged 1-4\n   exit\n"
        with pytest.raises(ParseError):
            AOSS.parse(text)
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment is not None and proposal.consistent is None
        assert proposal.notes[-1].startswith("The config could not be parsed")


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
        assert any("a module is fitted that the config does not state" in n for n in proposal.notes)
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


# ---------------------------------------------------------------------------
# Text nobody vouches for
# ---------------------------------------------------------------------------

_STACK_BANNER = "; hpStack_WC Configuration Editor; Created on release #WC.16.07.0003\n"
_JL322A_TOP = (
    "; JL322A Configuration Editor; Created on release #WC.16.07.0003\n"
    'hostname "sw"\nmodule 1 type jl322a\n'
)
#: Far longer than any id, number or part a device prints.
_LONG = "J" * 100_000
_MAC_SHAPE = re.compile(r"[0-9a-f]{6}-[0-9a-f]{6}", re.IGNORECASE)


def _stanza(*lines: str) -> str:
    return _STACK_BANNER + "stacking\n" + "".join(f"   {line}\n" for line in lines) + "   exit\n"


class TestWhatHostileTextCannotDo:
    """The route hands this code whatever was pasted.  It answers in
    time that grows with the text and no faster, never raises, and
    what it hands back is capped."""

    def test_a_run_of_spaces_inside_a_hardware_line_costs_nothing(self) -> None:
        """A pattern applied to each matched fragment once took time
        that grew with the SQUARE of a run of spaces in it: a quarter
        of a megabyte held the server for a minute.  The fragment is
        now collapsed, not searched."""
        text = _STACK_BANNER + "stacking\n   member" + " " * 400_000 + '1 type "JL322A"\n   exit\n'
        # Linear work on this text is a few milliseconds; the old
        # pattern needed minutes.  The margin is for a loaded machine.
        detected = _within(5.0, lambda: detect_deployment(text))
        assert _members(detected) == [(1, "JL322A", {})]
        assert detected.evidence[-1] == 'member 1 type "JL322A"'

    def test_evidence_is_the_line_as_far_as_the_part_number(self) -> None:
        """Runs of space collapsed, and nothing after the part: the MAC
        address of a member line comes after it and is never read."""
        detected = detect_deployment(_stanza('member  1\ttype   "JL322A"   mac-address aabbcc-000001'))
        assert detected.evidence == [
            "; hpStack_WC Configuration Editor", "stacking", 'member 1 type "JL322A"',
        ]

    @pytest.mark.parametrize("text", [STACKED, VSF, CAPTURE_2930M], ids=["stacked", "vsf", "capture"])
    def test_nothing_shaped_like_a_mac_address_is_in_a_proposal(self, text: str) -> None:
        """Not the word ``mac-address``: the SHAPE, anywhere in what a
        client is sent."""
        assert _MAC_SHAPE.search(text)
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert not _MAC_SHAPE.search(proposal.model_dump_json())

    def test_more_devices_than_a_declaration_may_list(self) -> None:
        text = _stanza(*(f'member {n} type "JL322A"' for n in range(1, MAX_DEPLOYMENT_MEMBERS + 2)))
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.stated and proposal.deployment is None and proposal.members == []
        assert any("states 65 devices" in n and "at most 64" in n for n in proposal.notes)
        assert len(proposal.evidence) <= MAX_EVIDENCE_LINES

    def test_the_evidence_is_capped(self) -> None:
        text = _stanza(*(f'member {n} type "JL322A"' for n in range(1, 201)))
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert len(detect_deployment(text).evidence) == 202
        assert len(proposal.evidence) == MAX_EVIDENCE_LINES
        assert proposal.evidence[:3] == [
            "; hpStack_WC Configuration Editor", "stacking", 'member 1 type "JL322A"',
        ]
        # A list that was cut says so.
        assert "The config has 202 hardware lines; the first 136 are listed." in proposal.notes

    def test_a_detection_no_declaration_could_hold_is_an_answer(self, monkeypatch) -> None:
        """No AOS-S text reaches this: its detector's patterns are
        tighter than a declaration's bounds.  The next detector's may
        not be, and the proposer is what answers for it."""
        bays = {f"B{n}": "JL083A" for n in range(MAX_DECLARED_BAYS + 1)}
        detected = DetectedDeployment(
            members=[DetectedMember(part="JL322A", modules=bays)], notes=["a remark of the detector's"],
        )
        monkeypatch.setattr(deployment_detect, "_detectors", lambda: {"aruba_aoss": lambda _raw: detected})
        proposal = propose_deployment(AOSS, STANDALONE, REGISTRY)
        assert proposal.deployment is None and proposal.consistent is None
        assert (proposal.family, proposal.mode) == ("aruba_aoss/2930M", "standalone")
        note, remark = proposal.notes
        assert note.startswith("What the config states cannot be a deployment of Aruba 2930M: 1 member(s) stated;")
        assert remark == "a remark of the detector's"
        assert "JL083A" not in note

    def test_the_most_a_declaration_may_list_is_still_answered_in_words(self) -> None:
        """Sixty-four members is a declaration; ten is the most this
        mode allows, and that is the registry's to say."""
        text = _stanza(*(f'member {n} type "JL322A"' for n in range(1, MAX_DEPLOYMENT_MEMBERS + 1)))
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment is None and len(proposal.members) == MAX_DEPLOYMENT_MEMBERS
        assert proposal.mode == "stacked" and proposal.family == "aruba_aoss/2930M"
        assert any("does not compile as a deployment of" in n for n in proposal.notes)

    @pytest.mark.parametrize(
        "line",
        ['member 1 type "' + "J" * 200 + '"', "member " + "9" * 5000 + ' type "JL322A"'],
        ids=["a part of 200 characters", "a member number of 5,000 digits"],
    )
    def test_a_line_no_device_prints_is_not_a_member(self, line: str) -> None:
        proposal = propose_deployment(AOSS, _stanza(line), REGISTRY)
        assert not proposal.stated and proposal.deployment is None
        assert any("no line in it names a member" in n for n in proposal.notes)
        assert any(n.startswith("1 line(s) of the stanza begin") for n in proposal.notes)
        assert max(len(entry) for entry in proposal.evidence) < 64
        assert max(len(note) for note in proposal.notes) < 400

    def test_a_detector_that_raises_is_an_answer(self, monkeypatch, caplog) -> None:
        def broken(_text: str) -> None:
            raise RuntimeError("hostname core-sw-01 was in the text")

        monkeypatch.setattr(deployment_detect, "_detectors", lambda: {"aruba_aoss": broken})
        with caplog.at_level(logging.WARNING, logger="netcanon.migration.deployment_detect"):
            proposal = propose_deployment(AOSS, STANDALONE, REGISTRY)
        assert proposal.deployment is None and not proposal.stated
        (note,) = proposal.notes
        assert "could not be read" in note and "core-sw-01" not in note
        # The log says that it happened and what kind of error it was.
        # The message of the error can quote the config, and is not in it.
        (record,) = caplog.records
        assert record.getMessage() == "deployment detector for aruba_aoss raised RuntimeError"
        assert "core-sw-01" not in caplog.text

    def test_a_part_stated_for_many_members_is_listed_once(self) -> None:
        proposal = propose_deployment(
            AOSS, _stanza(*(f'member {n} type "ZZ999A"' for n in (1, 2, 3))), REGISTRY,
        )
        assert proposal.unknown_parts == ["ZZ999A"]
        assert len(proposal.members) == 3

    def test_the_list_of_missing_ports_is_capped_and_counted(self) -> None:
        """Eleven short ranges are 480 names the device does not have."""
        ranges = ",".join(f"{member}/1-{member}/48" for member in range(1, 11))
        text = _JL322A_TOP + f"vlan 1\n   untagged 1-48,{ranges}\n   exit\n"
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert (proposal.used_port_count, proposal.missing_port_count) == (528, 480)
        assert len(proposal.missing_ports) == MAX_MISSING_PORTS
        assert len(set(proposal.missing_ports)) == MAX_MISSING_PORTS
        assert proposal.consistent is False
        assert any("uses 480 port name(s)" in n and "and 472 more" in n for n in proposal.notes)


class TestTheFirstNoteSaysWhyNothingWasProposed:
    """A client should not have to search prose for the reason.  What
    the detector says about the lines it read comes after it."""

    @pytest.mark.parametrize(
        ("text", "why"),
        [
            (_stanza(*(f'member {n} type "JL322A"' for n in range(1, 66))), "The config states 65 devices"),
            (_stanza('member 1 type "ZZ999A"'), "No model family describes ZZ999A"),
            (
                _stanza('member 1 type "JL322A"', 'member 2 type "JL260A"'),
                "The members belong to different model families",
            ),
            (
                _stanza('member 1 type "JL322A"', "member 1 flexible-module A type JL079A"),
                "does not compile as a deployment of",
            ),
            (_stanza('member 0 type "JL322A"'), "does not compile as a deployment of"),
            (_stanza(*(f'member {n} type "JL322A"' for n in range(1, 12))), "does not compile as a deployment of"),
            (_stanza('member 1 type "' + "J" * 200 + '"'), "no line in it names a member"),
            (_stanza("member 1 priority 200") + "vsf\n   exit\n", "no line in it names a member"),
            (_stanza("member 1 priority 200") + "module A type j9534a\n", "no line in it names a member"),
            (
                "; JL322A Configuration Editor; Created on release #WC.16.07.0003\n"
                + _stanza("member 1 priority 200").removeprefix(_STACK_BANNER) + "module 1 type jl322a\n",
                "no line in it names a member",
            ),
            (_STACK_BANNER + 'hostname "x"\n', "The banner is a stack's"),
            ('hostname "x"\nmodule 1 type jl322a#abb\n', "it could not be read as a chassis part number"),
            ('hostname "x"\n', "The config does not say which device it came from"),
        ],
        ids=[
            "more devices than a declaration", "a part no family describes", "two families",
            "a module the bay does not take", "a member number out of range", "more members than the mode allows",
            "a stanza that names no member", "no member, and a second stanza", "no member, and line cards",
            "no member, a part banner and a module 1 line", "a stack banner with no stanza",
            "a module 1 line that could not be read", "nothing stated",
        ],
    )
    def test_each_way_of_not_arriving(self, text: str, why: str) -> None:
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment is None
        assert why in proposal.notes[0], proposal.notes

    def test_a_mode_that_is_in_doubt(self, monkeypatch) -> None:
        monkeypatch.setattr(deployment_detect, "_mode_for", lambda _family, _fabric: (None, "which mode?"))
        proposal = propose_deployment(AOSS, STACKED, REGISTRY)
        assert proposal.deployment is None and proposal.notes[0] == "which mode?"
        assert len(proposal.notes) > 1

    def test_with_a_proposal_the_detectors_notes_keep_their_place(self) -> None:
        proposal = propose_deployment(AOSS, STACKED, REGISTRY)
        assert proposal.deployment is not None
        assert proposal.notes[0].startswith("A member line shows what the stack is provisioned for")


class TestWhatWasNotChecked:
    def test_a_config_that_names_no_port_is_not_a_check_that_passed(self) -> None:
        """Only the top of a config was pasted.  The device is stated;
        whether the config's ports are that device's is not known."""
        proposal = propose_deployment(AOSS, _JL322A_TOP, REGISTRY)
        assert proposal.deployment is not None and proposal.used_port_count == 0
        assert proposal.consistent is None
        assert any("names no port" in n for n in proposal.notes)

    def test_used_port_count_is_what_the_config_uses_not_what_the_device_has(self) -> None:
        text = _JL322A_TOP + "vlan 1\n   untagged 1-4\n   exit\n"
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert (proposal.used_port_count, proposal.inventory.port_count) == (4, 48)
        assert proposal.consistent is True and proposal.missing_port_count == 0

    def test_a_stack_banner_with_no_stanza_goes_no_further(self) -> None:
        proposal = propose_deployment(AOSS, _STACK_BANNER + 'hostname "x"\n', REGISTRY)
        assert not proposal.stated and proposal.deployment is None and proposal.members == []
        assert proposal.evidence == ["; hpStack_WC Configuration Editor"]


class TestMembersAsTheStanzaStatesThem:
    def test_members_come_back_in_number_order_whatever_the_stanza_lists_first(self) -> None:
        """Two stacks are paired in LIST order, so the order a proposal
        lists members in decides the pairing: ascending member number."""
        proposal = propose_deployment(
            AOSS, _stanza('member 2 type "JL322A"', 'member 1 type "JL320A"'), REGISTRY,
        )
        assert [(m.id, m.model) for m in proposal.deployment.members] == [
            (1, "2930M-24G-PoEP"), (2, "2930M-48G-PoEP"),
        ]

    def test_a_member_stated_twice_is_what_its_last_line_says(self) -> None:
        detected = detect_deployment(_stanza('member 1 type "JL322A"', 'member 1 type "JL320A"'))
        assert _members(detected) == [(1, "JL320A", {})]
        assert propose_deployment(
            AOSS, _stanza('member 1 type "JL322A"', 'member 1 type "JL322A"'), REGISTRY,
        ).evidence == ["; hpStack_WC Configuration Editor", "stacking", 'member 1 type "JL322A"']

    def test_a_member_block_under_oobm_is_not_a_stack_member(self) -> None:
        """Written for it: a stanza of one member, and an ``oobm``
        block with a ``member 2`` of its own."""
        text = _stanza('member 1 type "JL322A"') + (
            "oobm\n   ip address dhcp-bootp\n   member 2\n"
            '      type "JL999A"\n      ip address 198.51.100.12 255.255.255.0\n      exit\n   exit\n'
        )
        assert _members(detect_deployment(text)) == [(1, "JL322A", {})]

    def test_nor_does_it_make_a_switch_that_stands_alone_a_stack(self) -> None:
        text = _JL322A_TOP + 'oobm\n   member 1\n      type "JL999A"\n      exit\n   exit\n'
        detected = detect_deployment(text)
        assert detected.fabric == "" and _members(detected) == [(None, "JL322A", {})]

    def test_the_eight_port_capture(self) -> None:
        proposal = propose_deployment(AOSS, CAPTURE_2930F_8, REGISTRY)
        assert [(m.id, m.model) for m in proposal.deployment.members] == [
            (None, "2930F-8G-PoEP-2SFPP"),
        ]
        assert proposal.mode == "standalone" and proposal.consistent is True
        assert (proposal.used_port_count, proposal.missing_port_count) == (10, 0)


class TestWhatTheDetectorSaysItDidNotRead:
    """A stack that comes back a member short, or a fact stated two
    ways, is said in the notes -- not left for the port check to show."""

    def test_two_lines_that_state_one_member_differently(self) -> None:
        detected = detect_deployment(_stanza('member 1 type "JL322A"', 'member 1 type "JL320A"'))
        assert any("More than one line states member 1" in n and "the last was used" in n for n in detected.notes)

    def test_one_member_stated_twice_the_same_is_not_a_contradiction(self) -> None:
        detected = detect_deployment(_stanza('member 1 type "JL322A"', 'member 1 type "JL322A"'))
        assert _members(detected) == [(1, "JL322A", {})]
        assert not [n for n in detected.notes if "More than one line" in n]

    def test_a_vsf_member_stated_twice(self) -> None:
        text = _STACK_BANNER + (
            'vsf\n   member 1\n      type "JL557A"\n      exit\n'
            '   member 1\n      type "JL262A"\n      exit\n   exit\n'
        )
        detected = detect_deployment(text)
        assert _members(detected) == [(1, "JL262A", {})]
        assert any("More than one line states member 1" in n for n in detected.notes)

    def test_a_member_line_that_could_not_be_read_is_counted(self) -> None:
        """An order suffix on the part, an option code, a member number
        no device prints.  Each line is left out, and the stack is said
        to be three lines short of what the text set out to state."""
        detected = detect_deployment(_stanza(
            'member 1 type "JL322A"',
            'member 2 type "JL322A-B21"',
            'member 3 type "JL322A#ABB"',
            "member -1 type JL322A",
        ))
        assert _members(detected) == [(1, "JL322A", {})]
        assert detected.evidence[-1] == 'member 1 type "JL322A"'
        (note,) = [n for n in detected.notes if "could not be read as a member" in n]
        assert note.startswith("3 line(s) of the stanza begin `member <number> type`")

    def test_the_other_member_lines_of_a_stanza_are_not_counted(self) -> None:
        """``member 1 priority 200`` states no model and is not a line
        that failed to."""
        assert not [n for n in detect_deployment(STACKED).notes if "could not be read" in n]
        assert not [n for n in detect_deployment(VSF).notes if "could not be read" in n]
        assert not [n for n in detect_deployment(CAPTURE_2930M).notes if "could not be read" in n]

    def test_a_vsf_member_block_with_no_type_line(self) -> None:
        text = _STACK_BANNER + (
            'vsf\n   enable domain 1\n   member 1\n      type "JL557A"\n      exit\n'
            "   member 2\n      priority 100\n      exit\n   exit\n"
        )
        detected = detect_deployment(text)
        assert _members(detected) == [(1, "JL557A", {})]
        assert any("`member` block with no `type` line that could be read for member 2;" in n for n in detected.notes)
        assert not [n for n in detect_deployment(VSF).notes if "no `type` line" in n]

    def test_a_module_line_for_a_member_nothing_states(self) -> None:
        detected = detect_deployment(_stanza(
            'member 1 type "JL322A"', "member 2 flexible-module A type JL083A",
        ))
        assert _members(detected) == [(1, "JL322A", {})]
        assert any("names member 2" in n and "the module was left out" in n for n in detected.notes)
        assert not [n for n in detect_deployment(STACKED).notes if "was left out" in n]

    def test_a_second_stanza(self) -> None:
        text = _stanza('member 1 type "JL322A"') + (
            'vsf\n   member 1\n      type "JL557A"\n      exit\n   exit\n'
        )
        detected = detect_deployment(text)
        assert detected.fabric == "stacking" and _members(detected) == [(1, "JL322A", {})]
        assert any("more than one `stacking` or `vsf` stanza" in n for n in detected.notes)
        assert not [n for n in detect_deployment(STACKED).notes if "more than one" in n]

    def test_line_cards_are_said_of_a_stack_too(self) -> None:
        detected = detect_deployment(_stanza('member 1 type "JL322A"') + "module A type j9534a\n")
        assert any("modular chassis" in n for n in detected.notes)
        assert not [n for n in detect_deployment(STACKED).notes if "modular chassis" in n]


class TestWhereALineEnds:
    def test_a_form_feed_is_a_line_break_as_it_is_to_the_parser(self) -> None:
        """The AOS-S parser cuts lines with ``str.splitlines``; a
        detector that cut them at ``\\n`` only would read this banner
        and stanza header as one line and see no stanza."""
        text = _STACK_BANNER.rstrip("\n") + "\x0c" + 'stacking\n   member 1 type "JL322A"\n   exit\n'
        assert _members(detect_deployment(text)) == [(1, "JL322A", {})]

    def test_bare_carriage_returns(self) -> None:
        text = _stanza('member 1 type "JL322A"').replace("\n", "\r")
        assert _members(detect_deployment(text)) == [(1, "JL322A", {})]

    def test_a_blank_line_does_not_end_the_stanza(self) -> None:
        text = _STACK_BANNER + 'stacking\n   member 1 type "JL322A"\n\n   member 2 type "JL320A"\n   exit\n'
        assert [m.id for m in detect_deployment(text).members] == [1, 2]

    def test_the_next_line_at_the_margin_does(self) -> None:
        """A ``member`` line under another stanza is not a stack member."""
        text = _stanza('member 1 type "JL322A"') + 'vlan 1\n   member 2 type "JL320A"\n   exit\n'
        assert [m.id for m in detect_deployment(text).members] == [1]


class TestThePartAsPrinted:
    def test_a_banner_part_and_a_module_are_upper_cased(self) -> None:
        banner_only = '; jl322a Configuration Editor; Created on release #WC.16.07.0003\nhostname "sw"\n'
        assert _members(detect_deployment(banner_only)) == [(None, "JL322A", {})]
        detected = detect_deployment(_JL322A_TOP + "flexible-module a type jl083a\n")
        assert _members(detected) == [(None, "JL322A", {"A": "JL083A"})]

    def test_a_module_1_line_with_more_on_it_is_not_the_chassis_line(self) -> None:
        text = "; JL320A Configuration Editor; Created on release #WC.16.07.0003\nmodule 1 type jl322a spare\n"
        assert _members(detect_deployment(text)) == [(None, "JL320A", {})]

    def test_a_banner_and_a_module_1_line_that_disagree(self) -> None:
        text = "; JL320A Configuration Editor; Created on release #WC.16.07.0003\nmodule 1 type jl322a\n"
        detected = detect_deployment(text)
        assert _members(detected) == [(None, "JL322A", {})]
        assert detected.notes == [
            "The banner says JL320A and the `module 1` line says JL322A; the `module 1` line was used."
        ]

    @pytest.mark.parametrize(
        ("ident", "is_a_part"),
        [("AB12", False), ("AB123", True), ("AB123456", True), ("AB1234567", False)],
    )
    def test_how_long_a_banner_part_may_be(self, ident: str, is_a_part: bool) -> None:
        detected = detect_deployment(f"; {ident} Configuration Editor; Created on release #WC.16.07.0003\n")
        assert (detected is not None) == is_a_part

    def test_a_part_is_looked_up_whole(self) -> None:
        """``JL322AB`` is not a JL322A with something after it."""
        proposal = propose_deployment(AOSS, _stanza('member 1 type "JL322AB"'), REGISTRY)
        assert proposal.unknown_parts == ["JL322AB"] and proposal.deployment is None


class TestTheModeAConfigIsIn:
    """``_mode_for`` on families made for it: the two shipped ones each
    have one mode of each kind, so they reach only its first branch."""

    FAMILY = REGISTRY.families["aruba_aoss/2930F"]

    def _with(self, **modes: str) -> object:
        return self.FAMILY.model_copy(
            update={"modes": {name: self.FAMILY.modes[like] for name, like in modes.items()}},
        )

    def test_the_stanzas_the_shipped_families_print_need_no_note(self) -> None:
        for text in (STACKED, VSF, CAPTURE_2930M):
            proposal = propose_deployment(AOSS, text, REGISTRY)
            assert proposal.deployment is not None
            assert not [n for n in proposal.notes if "stanza" in n]

    @pytest.mark.parametrize(
        ("member", "kind", "mode"),
        [('member 1 type "JL322A"', "vsf", "stacked"), ('member 1 type "JL557A"', "stacking", "vsf")],
        ids=["a vsf stanza that names a 2930M", "a stacking stanza that names a 2930F"],
    )
    def test_a_stanza_the_family_does_not_print_is_said(self, member: str, kind: str, mode: str) -> None:
        """No device prints it: the text is hand-made or from two
        devices.  It is still a config in a stacking mode of a family
        with one such mode, so that mode is proposed -- and said."""
        text = _STACK_BANNER + f"{kind}\n   {member}\n   exit\n"
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.mode == mode and proposal.deployment is not None
        (note,) = [n for n in proposal.notes if "stanza" in n]
        assert f"has a `{kind}` stanza" in note and f"is `{mode}`" in note

    def test_a_family_with_no_mode_of_the_kind(self) -> None:
        mode, said = deployment_detect._mode_for(self._with(standalone="standalone"), "vsf")
        assert mode is None
        assert "is in `vsf` mode" in said and "has no deployment mode of that kind (modes: standalone)" in said
        mode, said = deployment_detect._mode_for(self._with(vsf="vsf"), "")
        assert mode is None and "is not in a stacking mode" in said

    def test_a_family_with_two_modes_of_the_kind(self) -> None:
        two = self._with(standalone="standalone", vsf="vsf", ring="vsf")
        assert deployment_detect._mode_for(two, "vsf") == ("vsf", "")
        assert deployment_detect._mode_for(two, "ring") == ("ring", "")
        mode, said = deployment_detect._mode_for(two, "stacking")
        assert mode is None and "more than one such mode (vsf, ring)" in said

    def test_the_stanzas_word_may_be_in_the_modes_name_or_in_its_label(self) -> None:
        """Either will do, and one of them has to: with the word in
        neither, the note is on every config of the family."""
        shipped = self.FAMILY.modes["vsf"]
        assert "vsf" in shipped.label.casefold()
        plain = shipped.model_copy(update={"label": "members share one control plane"})

        def family(**modes: object) -> object:
            return self.FAMILY.model_copy(update={"modes": {"standalone": self.FAMILY.modes["standalone"], **modes}})

        assert deployment_detect._mode_for(family(vsf=plain), "vsf") == ("vsf", "")
        assert deployment_detect._mode_for(family(fabric=shipped), "vsf") == ("fabric", "")
        mode, said = deployment_detect._mode_for(family(fabric=plain), "vsf")
        assert mode == "fabric" and "which is not called that" in said

    def test_every_shipped_stacking_mode_goes_by_a_word_its_configs_print(self) -> None:
        """A shipped family whose stacking mode had the stanza's word
        in neither its name nor its label would get the note on every
        one of its own configs.  A family file is where that is kept:
        see ``ModeDef.label``."""
        checked = 0
        for family in REGISTRY.families.values():
            for name, mode in family.modes.items():
                if family.vendor not in _STANZA_WORDS or mode.member_ids is None:
                    continue
                checked += 1
                answers = [deployment_detect._mode_for(family, word) for word in _STANZA_WORDS[family.vendor]]
                assert (name, "") in answers, (family.key, name, mode.label)
        assert checked

    def test_every_detectors_stanza_words_are_listed(self) -> None:
        assert set(_STANZA_WORDS) == set(detection_vendors())


class TestTheCheckIsTheOneATranslationMakes:
    """``missing_ports`` and a translation's ``off_inventory`` are two
    callers of one collection.  If they could differ, a proposal would
    call a config consistent that the translation then drops ports of."""

    @pytest.mark.parametrize(
        "body",
        [
            _JL322A_TOP + "flexible-module A type JL083A\nvlan 1\n   untagged 1-48,a1\n   exit\n",
            _JL322A_TOP + "vlan 1\n   untagged 1-48,A1-A4\n   exit\n",
            _JL322A_TOP + "flexible-module A type JL083A\nvlan 1\n   untagged 1-48,A1-A4,Trk1\n   exit\n"
            "trunk 47-48 trk1 lacp\n",
            STACKED,
            VSF,
            _JL322A_TOP + "vlan 1\n   untagged 1-46,TRK1,Dyn1,TrK7\n   exit\ntrunk 47-48 trk1 lacp\n",
            _JL322A_TOP + "flexible-module A type JL083A\nvlan 1\n   untagged 1-46,A1-A4,Trk1\n   exit\n",
            _JL322A_TOP + "vlan 1\n   untagged 1-48,1/1-1/12\n   exit\n",
        ],
        ids=["a module port in lower case", "no module stated", "a LAG", "a stack", "a fabric",
             "a LAG in other letter cases", "a LAG with its trunk line cut off", "more than nine of them"],
    )
    def test_missing_ports_are_the_plans_off_inventory(self, body: str) -> None:
        """The same NAMES and the same number of them.  Not the same
        order: a proposal lists them as the parsed config does, a plan
        sorts them as text (``1/1, 1/10, 1/11``)."""
        proposal = propose_deployment(AOSS, body, REGISTRY)
        declared = compile_deployment(
            Deployment(vendor="aruba_aoss", **proposal.deployment.model_dump()), REGISTRY,
        )
        job = run_plan_with_models(AOSS, AOSS, body, declared, declared)
        off_inventory = job.port_mapping_plan.off_inventory
        assert proposal.missing_port_count == len(off_inventory) < MAX_MISSING_PORTS
        assert sorted(proposal.missing_ports) == sorted(off_inventory)
        assert proposal.consistent is (not off_inventory)

    def test_what_those_configs_are_missing(self) -> None:
        """So that the comparison above is not between two empty lists."""
        def missing(body: str) -> list[str]:
            return propose_deployment(AOSS, _JL322A_TOP + body, REGISTRY).missing_ports

        # ``TRK1`` is the LAG the ``trunk`` line defines as ``trk1``, and
        # ``TrK7`` is a LAG by its shape: a trunk's name has no letter
        # case.  ``Dyn1`` is no name the codec knows.
        assert missing("vlan 1\n   untagged 1-46,TRK1,Dyn1,TrK7\n   exit\ntrunk 47-48 trk1 lacp\n") == [
            "Dyn1",
        ]
        # ``Trk1`` is a LAG by its shape, whether or not its line was pasted.
        assert missing("flexible-module A type JL083A\nvlan 1\n   untagged 1-46,A1-A4,Trk1\n   exit\n") == []
        assert len(missing("vlan 1\n   untagged 1-48,1/1-1/12\n   exit\n")) == 12

    def test_no_detector_yet_for_a_vendor_whose_ports_keep_a_factory_name(self) -> None:
        """A translation does more for such a vendor than the check in
        a proposal does.  The first one to get a detector fails here
        until that check is taught the same."""
        for vendor in detection_vendors():
            assert not getattr(get_codec(_CODEC_OF[vendor]), "ports_keep_a_factory_name", False), vendor


class TestEveryDetector:
    """Whatever a vendor's detector reads, the text is not vouched for.
    These bodies state no device; reading them must cost what their
    length costs."""

    BODIES = {
        "spaces": " " * 400_000,
        "blank lines": "\n" * 200_000,
        "lines of spaces": "   \n" * 100_000,
        "one token": "x" * 500_000,
        "comment marks": "; " * 200_000,
        "member lines": '   member 1 type "X"\n' * 50_000,
        "a word again and again": "module " * 60_000,
        "a line of bays": "flexible-module " + "A " * 100_000,
        "tabs then a word": ("\t" * 2_000 + "member\n") * 100,
        "control characters": "\x00\x0b\x0c\x1c\x85\u2028" * 50_000,
    }

    @pytest.mark.parametrize("vendor", detection_vendors())
    @pytest.mark.parametrize("title", sorted(BODIES))
    def test_text_that_states_no_device_is_read_in_time_that_fits_its_length(
        self, vendor: str, title: str,
    ) -> None:
        codec = get_codec(_CODEC_OF[vendor])
        # A few milliseconds when the work is linear; minutes when a
        # pattern backtracks over a run.  The margin is for a loaded
        # machine.
        proposal = _within(5.0, lambda: propose_deployment(codec, self.BODIES[title], REGISTRY))
        assert proposal.deployment is None and proposal.notes
        assert len(proposal.model_dump_json()) < 20_000


class TestTheAossDetectorOnTextMadeToBeSlow:
    """Each tail is built to make one pattern of the detector go back
    over a run it has already crossed.  ``TestEveryDetector`` cannot
    reach most of them: its bodies state no device, and the detector
    returns before the patterns for modules and members run.  Here the
    text states one -- a chassis line, a ``stacking`` header, a ``vsf``
    header -- and the tail follows it.  The detector is called by
    itself: with a device stated, a proposal goes on to parse the text,
    and the parser's cost is not what this pins."""

    PREFIXES = {
        "nothing stated": "",
        "a chassis": _JL322A_TOP,
        "a stacking header": _STACK_BANNER + "stacking\n",
        "a vsf header": _STACK_BANNER + "vsf\n",
    }
    TAILS = {
        "a module word and spaces": "flexible-module" + " " * 300_000,
        "a bay and spaces": "flexible-module A" + " " * 300_000 + "type",
        "module lines that trail off": ("flexible-module A type" + " " * 3000 + "\n") * 100,
        "a line card word and spaces": "module" + " " * 300_000 + "x",
        "line card lines that trail off": ("module a" + " " * 3000 + "\n") * 100,
        "blank lines": "\n" * 300_000,
        "lines of spaces": "   \n" * 100_000,
        "member and spaces": ("   member" + " " * 3000 + "\n") * 100,
        "a member, spaces, type": "   member 1" + " " * 300_000 + "type",
        "member module lines that trail off": ("   member 1 flexible-module A" + " " * 3000 + "\n") * 100,
        "type and spaces": "   type" + " " * 300_000,
        "member blocks with nothing in them": "".join(f"   member {n}\n" for n in range(50_000)),
        "one line of member types": "   " + "member 1 type " * 50_000,
        "more members than any stack": "".join(f'   member {n} type "JL322A"\n' for n in range(20_000)),
        "modules of members nothing states": "".join(
            f"   member {n} flexible-module A type JL083A\n" for n in range(50_000)
        ),
        "module lines no pattern reads": "   member 1 flexible-module AB type JL083A\n" * 50_000,
        "chassis lines no pattern reads": "module 1 type jl322a spare\n" * 50_000,
        "an open quote, again and again": '   member 1 type "\n' * 100_000,
        "tabs then a word": ("\t" * 3000 + "member\n") * 100,
        "stanza headers": "stacking\n" * 100_000,
        "headers that trail off": ("vsf" + " " * 3000 + "\n") * 100,
        "banners": "; X Configuration Editor\n" * 100_000,
        "a comment mark, an id and spaces": ("; JL322A" + " " * 3000 + "\n") * 100,
    }

    @pytest.mark.parametrize("prefix", sorted(PREFIXES))
    @pytest.mark.parametrize("tail", sorted(TAILS))
    def test_the_work_fits_the_length_of_the_text(self, prefix: str, tail: str) -> None:
        text = self.PREFIXES[prefix] + self.TAILS[tail]
        # Well under a second each when measured; a pattern that goes
        # back over a run of 300,000 needs minutes.
        detected = _within(5.0, lambda: detect_deployment(text))
        # And what comes back does not grow with the text either.
        if detected is not None:
            assert sum(map(len, detected.notes)) < 4_000


class TestTheBoundOnEachPattern:
    """Every pattern takes a bounded id, number and part, and a part
    ends where the line or a space does.  One pattern's bounds do not
    vouch for another's, so each is pinned on a line of its own."""

    @pytest.mark.parametrize(
        ("text", "said"),
        [
            ("; hpStack_" + "x" * 100_000 + " Configuration Editor\n", "does not say which device"),
            (
                _STACK_BANNER + 'vsf\n   member 1\n      type "' + _LONG + '"\n      exit\n   exit\n',
                "no `type` line that could be read for member 1",
            ),
            (
                _stanza('member 1 type "JL322A"', "member 1 flexible-module A type " + _LONG),
                "could not be read as a module",
            ),
            (_JL322A_TOP + "flexible-module A type " + _LONG + "\n", "could not be read as a module"),
            (
                "; JL322A Configuration Editor; Created on release #WC.16.07.0003\nmodule 1 type " + _LONG + "\n",
                "could not be read as the chassis line",
            ),
        ],
        ids=["a banner id", "a nested type", "a member's module", "a module", "the chassis line"],
    )
    def test_a_part_or_an_id_of_any_length_is_not_taken(self, text: str, said: str) -> None:
        """A hundred thousand characters where a part goes.  Taken, it
        came back in the answer several times over."""
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert any(said in n for n in proposal.notes), proposal.notes
        assert len(proposal.model_dump_json()) < 6_000

    @pytest.mark.parametrize(
        ("text", "members", "said"),
        [
            (
                _stanza('member 1 type "JL322A"', "member " + "9" * 5000 + " flexible-module A type JL083A"),
                [(1, "JL322A", {})],
                "could not be read as a module",
            ),
            (
                _STACK_BANNER + 'vsf\n   member 1\n      type "JL557A"\n      exit\n   member ' + "9" * 5000
                + '\n      type "JL557A"\n      exit\n   exit\n',
                [(1, "JL557A", {})],
                "whose number could not be read",
            ),
        ],
        ids=["on a module line", "on a nested header"],
    )
    def test_a_member_number_no_device_prints_loses_its_own_line_and_no_other(
        self, text: str, members: list, said: str,
    ) -> None:
        """A number of thousands of digits is past what ``int`` will
        convert.  Read whole it raised, and the member that WAS read
        went with it."""
        detected = detect_deployment(text)
        assert _members(detected) == members
        assert any(said in n for n in detected.notes), detected.notes
        assert propose_deployment(AOSS, text, REGISTRY).deployment is not None

    @pytest.mark.parametrize(
        ("text", "members", "said"),
        [
            (
                _JL322A_TOP + "flexible-module A type JL083A#ABB\n",
                [(None, "JL322A", {})],
                "1 line(s) begin `flexible-module",
            ),
            (
                _JL322A_TOP + 'flexible-module A type "JL083A-B21"\n',
                [(None, "JL322A", {})],
                "1 line(s) begin `flexible-module",
            ),
            (
                _stanza('member 1 type "JL322A"', "member 1 flexible-module A type JL083A#ABB"),
                [(1, "JL322A", {})],
                "flexible-module <bay> type` and could not be read as a module",
            ),
            (
                _STACK_BANNER + 'vsf\n   member 1\n      type "JL557A-B21"\n      exit\n   exit\n',
                [],
                "no `type` line that could be read for member 1",
            ),
            (
                _STACK_BANNER + "vsf\n   member 1\n      type JL557A#ABB\n      exit\n   exit\n",
                [],
                "no `type` line that could be read for member 1",
            ),
        ],
        ids=["a module, option code", "a module, order suffix", "a member's module", "a nested type, suffix",
             "a nested type, option code"],
    )
    def test_a_part_with_more_after_it_is_not_the_part_before_it(
        self, text: str, members: list, said: str,
    ) -> None:
        """``JL083A#ABB`` is an order code, not a JL083A.  Cut at the
        ``#`` it names a module the line does not state."""
        detected = detect_deployment(text)
        assert _members(detected) == members
        assert any(said in n for n in detected.notes), detected.notes


class TestSmallThingsNothingElsePins:
    def test_a_part_a_bay_and_a_module_come_back_in_capitals(self) -> None:
        """A registry is looked up by the part as HPE writes it; a
        config prints it in either case (``module 1 type jl322a``)."""
        detected = detect_deployment(_stanza('member 1 type "jl322a"', "member 1 flexible-module a type jl083a"))
        assert _members(detected) == [(1, "JL322A", {"A": "JL083A"})]
        nested = _STACK_BANNER + 'vsf\n   member 1\n      type "jl557a"\n      exit\n   exit\n'
        assert _members(detect_deployment(nested)) == [(1, "JL557A", {})]

    def test_what_is_said_of_a_stack_with_no_module_and_a_switch_with_one(self) -> None:
        """The remark about a bay is made where a bay is stated, and
        only there."""
        member = (
            "A member line shows what the stack is provisioned for; a member can be "
            "configured before it is connected."
        )
        module = (
            "A flexible-module line shows what the bay is provisioned for; it does not "
            "show that a module is fitted."
        )
        assert detect_deployment(_stanza('member 1 type "JL322A"')).notes == [member]
        assert detect_deployment(STACKED).notes == [member, module]
        assert detect_deployment(STANDALONE).notes == [module]

    def test_a_second_banner_is_said_of_a_stack_too(self) -> None:
        text = "; JL320A Configuration Editor; Created on release #WC.16.07.0003\n" + _stanza('member 1 type "JL322A"')
        assert detect_deployment(text).notes[-1] == (
            "The config has more than one banner (JL320A, then hpStack_WC); the first was read."
        )

    def test_an_indented_module_1_line_is_not_the_chassis_line(self) -> None:
        """``module 1 type`` under another stanza states no chassis,
        and is not a chassis line that failed to."""
        stacked = detect_deployment(_stanza('member 1 type "JL322A"', "module 1 type jl322a"))
        assert not [n for n in stacked.notes if "`module 1` line" in n]
        alone = detect_deployment(_JL322A_TOP + "interface 1\n   module 1 type jl322a#abb\n   exit\n")
        assert alone.notes == []

    def test_an_indented_module_line_is_not_a_module_of_the_switch(self) -> None:
        detected = detect_deployment(_JL322A_TOP + "interface 1\n   flexible-module A type JL083A#ABB\n   exit\n")
        assert _members(detected) == [(None, "JL322A", {})] and detected.notes == []

    def test_a_member_line_inside_a_vsf_stanza_does_not_head_a_block(self) -> None:
        """``member 2 priority 100`` is a line about member 2, not the
        header of a block for it: it ends no block and starts none."""
        text = _STACK_BANNER + (
            'vsf\n   member 1\n      member 2 priority 100\n      type "JL557A"\n      exit\n   exit\n'
        )
        detected = detect_deployment(text)
        assert _members(detected) == [(1, "JL557A", {})]
        assert detected.notes == [
            "A member line shows what the stack is provisioned for; a member can be configured before it is connected."
        ]

    def test_a_vsf_block_with_two_type_lines(self) -> None:
        """The last is used and the two are said to differ, as for a
        member stated twice anywhere else."""
        text = _STACK_BANNER + 'vsf\n   member 1\n      type "JL557A"\n      type "JL262A"\n      exit\n   exit\n'
        detected = detect_deployment(text)
        assert _members(detected) == [(1, "JL262A", {})]
        assert detected.evidence[-1] == 'member 1: type "JL262A"'
        assert any("More than one line states member 1" in n for n in detected.notes)

    def test_the_evidence_for_a_bay_stated_twice_is_the_line_that_was_used(self) -> None:
        detected = detect_deployment(_stanza(
            'member 1 type "JL322A"',
            "member 1 flexible-module A type JL083A",
            "member 1 flexible-module A type JL078A",
        ))
        assert detected.evidence[-1] == "member 1 flexible-module A type JL078A"
        alone = detect_deployment(_JL322A_TOP + "flexible-module A type JL083A\nflexible-module A type JL078A\n")
        assert alone.evidence[-1] == "flexible-module A type JL078A"

    def test_the_configs_word_for_its_stanza_is_in_the_proposal(self) -> None:
        assert [propose_deployment(AOSS, text, REGISTRY).fabric for text in (STANDALONE, STACKED, VSF)] == [
            "", "stacking", "vsf",
        ]

    def test_evidence_a_detector_repeats_is_listed_once(self, monkeypatch) -> None:
        detected = DetectedDeployment(members=[DetectedMember(part="JL322A")], evidence=["a", "b", "a", "b", "c"])
        monkeypatch.setattr(deployment_detect, "_detectors", lambda: {"aruba_aoss": lambda _raw: detected})
        assert propose_deployment(AOSS, STANDALONE, REGISTRY).evidence == ["a", "b", "c"]

    def test_a_member_number_is_not_sent_in_a_mode_that_has_none(self, monkeypatch) -> None:
        """A declaration in a mode without member ids refuses one.  No
        AOS-S text gives a member a number outside a stanza; the next
        detector's may."""
        detected = DetectedDeployment(fabric="", members=[DetectedMember(part="JL322A", id=3)])
        monkeypatch.setattr(deployment_detect, "_detectors", lambda: {"aruba_aoss": lambda _raw: detected})
        proposal = propose_deployment(AOSS, STANDALONE, REGISTRY)
        assert proposal.mode == "standalone" and proposal.deployment.members[0].id is None


class TestWhatHeadsAStanza:
    @pytest.mark.parametrize("header", ["stacking  ", "stacking\t", "vsf "])
    def test_space_after_the_word(self, header: str) -> None:
        """A paste often leaves trailing space on its lines."""
        text = _STACK_BANNER + header + '\n   member 1 type "JL322A"\n   exit\n'
        detected = detect_deployment(text)
        assert detected.fabric == header.strip() and [m.id for m in detected.members] == [1]

    @pytest.mark.parametrize(
        "line",
        ["no stacking\n", "no vsf\n", "interface 1\n   vsf\n   exit\n", "   stacking\n", "stacking enable\n"],
        ids=["no stacking", "no vsf", "the word under another stanza", "the word indented", "the word and more"],
    )
    def test_the_word_elsewhere_is_not_a_stanza(self, line: str) -> None:
        """``no stacking`` is how a 2930M says it is NOT stacked: read
        as a stanza it made a switch that stands alone a stack that
        names no member, and a proposal into none."""
        detected = detect_deployment(_JL322A_TOP + line)
        assert detected.fabric == "" and _members(detected) == [(None, "JL322A", {})]
        assert propose_deployment(AOSS, _JL322A_TOP + line, REGISTRY).mode == "standalone"

    def test_indentation_that_is_not_a_space_or_a_tab(self) -> None:
        """A no-break space indents the line as far as the stanza goes
        -- it is not at the margin -- and no pattern reads it: the line
        is counted, not passed over."""
        text = _STACK_BANNER + "stacking\n" + chr(0xA0) + ' member 1 type "JL322A"\n   exit\n'
        detected = detect_deployment(text)
        assert detected.fabric == "stacking" and detected.members == []
        assert any(n.startswith("1 line(s) of the stanza begin `member <number> type`") for n in detected.notes)


class TestANoteCountsWhatItDoesNotList:
    """The text is whatever was pasted.  A note that named every member
    it had something to say about was megabytes long."""

    @pytest.mark.parametrize(
        ("text", "said"),
        [
            (
                _STACK_BANNER + "vsf\n" + "".join(f"   member {n}\n" for n in range(1, 20_001)) + "   exit\n",
                "no `type` line that could be read for member 1, 2, 3, 4, 5, 6, 7, 8 and 19992 more",
            ),
            (
                _stanza(
                    'member 1 type "JL322A"',
                    *(f"member {n} flexible-module A type JL083A" for n in range(2, 20_002)),
                ),
                "names member 2, 3, 4, 5, 6, 7, 8, 9 and 19992 more",
            ),
            (
                _stanza(
                    *(f'member {n} type "JL322A"' for n in range(1, 5001)),
                    *(f'member {n} type "JL320A"' for n in range(1, 5001)),
                ),
                "states member 1, 2, 3, 4, 5, 6, 7, 8 and 4992 more with different part numbers",
            ),
            (
                _stanza(*(
                    line for n in range(1, 5001) for line in (
                        f'member {n} type "JL322A"',
                        f"member {n} flexible-module A type JL083A",
                        f"member {n} flexible-module A type JL078A",
                    )
                )),
                "a bay of member 1, 2, 3, 4, 5, 6, 7, 8 and 4992 more with different modules",
            ),
        ],
        ids=["blocks with no type", "modules of members nothing states", "members stated two ways",
             "bays stated two ways"],
    )
    def test_a_few_members_are_named_and_the_rest_counted(self, text: str, said: str) -> None:
        detected = detect_deployment(text)
        (note,) = [n for n in detected.notes if said in n]
        assert len(note) < 200
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert max(len(n) for n in proposal.notes) <= MAX_NOTE_LENGTH
        assert len(proposal.model_dump_json()) < 12_000

    @pytest.mark.parametrize(("blocks", "ending"), [(8, "member 1, 2, 3, 4, 5, 6, 7, 8;"), (9, "7, 8 and 1 more;")])
    def test_where_the_counting_starts(self, blocks: int, ending: str) -> None:
        text = _STACK_BANNER + "vsf\n" + "".join(f"   member {n}\n" for n in range(1, blocks + 1)) + "   exit\n"
        (note,) = [n for n in detect_deployment(text).notes if "no `type` line" in n]
        assert ending in note

    def test_the_missing_port_note_lists_eight_and_counts_from_the_ninth(self) -> None:
        def note(last: int) -> str:
            text = _JL322A_TOP + f"vlan 1\n   untagged 1-48,1/1-1/{last}\n   exit\n"
            (said,) = [n for n in propose_deployment(AOSS, text, REGISTRY).notes if "port name(s)" in n]
            return said

        assert "(1/1, 1/2, 1/3, 1/4, 1/5, 1/6, 1/7, 1/8)" in note(8)
        assert "(1/1, 1/2, 1/3, 1/4, 1/5, 1/6, 1/7, 1/8 and 1 more)" in note(9)


class TestWhatADetectorHandsBackIsCutToSize:
    """The next detector may not keep its notes short or put its reason
    first.  What a proposal carries does not depend on it."""

    @staticmethod
    def _answering(monkeypatch, detected: DetectedDeployment) -> None:
        monkeypatch.setattr(deployment_detect, "_detectors", lambda: {"aruba_aoss": lambda _raw: detected})

    def test_the_caps_are_what_the_documents_say(self) -> None:
        """A client sizes its list for these.  Each is compared with
        the constant elsewhere, which a change to the constant passes."""
        assert (MAX_EVIDENCE_LINES, MAX_MISSING_PORTS, MAX_NOTES, MAX_NOTE_LENGTH) == (136, 256, 24, 600)

    def test_long_notes_many_notes_and_long_evidence(self, monkeypatch) -> None:
        self._answering(monkeypatch, DetectedDeployment(
            members=[DetectedMember(part="JL322A")],
            evidence=[f"line {n}" for n in range(500)],
            notes=[f"remark {n} " + "x" * 5000 for n in range(40)],
        ))
        proposal = propose_deployment(AOSS, STANDALONE, REGISTRY)
        assert proposal.deployment is not None
        assert proposal.evidence == [f"line {n}" for n in range(MAX_EVIDENCE_LINES)]
        remarks = proposal.notes[:MAX_NOTES]
        assert [n.split()[1] for n in remarks] == [str(n) for n in range(MAX_NOTES)]
        assert {len(n) for n in remarks} == {MAX_NOTE_LENGTH}
        assert proposal.notes[MAX_NOTES:MAX_NOTES + 2] == [
            "16 more remark(s) about the hardware lines are not shown.",
            "The config has 500 hardware lines; the first 136 are listed.",
        ]
        assert len(proposal.model_dump_json()) < 30_000

    def test_a_list_that_fits_is_not_said_to_be_cut(self) -> None:
        for text in (STANDALONE, STACKED, VSF, CAPTURE_2930M):
            notes = propose_deployment(AOSS, text, REGISTRY).notes
            assert not [n for n in notes if "not shown" in n or "are listed" in n]

    def test_a_detector_that_gives_no_reason_gets_one(self, monkeypatch) -> None:
        self._answering(monkeypatch, DetectedDeployment(members=[], notes=[]))
        proposal = propose_deployment(AOSS, STANDALONE, REGISTRY)
        assert proposal.deployment is None and not proposal.stated
        assert proposal.notes == [
            "The lines that state the hardware name no device's model; declare the device yourself."
        ]

    def test_with_no_member_the_detectors_first_note_stays_first(self, monkeypatch) -> None:
        """The rule a detector has to follow: with no member read, its
        reason goes first.  What is added here goes after it."""
        self._answering(monkeypatch, DetectedDeployment(
            members=[], evidence=[f"line {n}" for n in range(500)], notes=["the reason", "a remark"],
        ))
        proposal = propose_deployment(AOSS, STANDALONE, REGISTRY)
        assert proposal.notes == [
            "the reason", "a remark", "The config has 500 hardware lines; the first 136 are listed.",
        ]

    def test_the_evidence_is_the_lines_that_were_used(self) -> None:
        """Member 1 stated three hundred ways and then as what it is.
        The proposal is for the last; the evidence is that line, not
        the first hundred and thirty-four of the others."""
        text = _stanza(*(f'member 1 type "ZZ{n:03d}A"' for n in range(300)), 'member 1 type "JL322A"')
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment is not None
        assert proposal.evidence == ["; hpStack_WC Configuration Editor", "stacking", 'member 1 type "JL322A"']
        assert any("More than one line states member 1" in n for n in proposal.notes)

    def test_a_line_stated_many_times_does_not_push_another_out(self) -> None:
        text = _stanza(*(['member 1 type "JL322A"'] * 200), "member 1 flexible-module A type JL083A")
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.evidence[-1] == "member 1 flexible-module A type JL083A"
        assert proposal.deployment.members[0].modules == {"A": "JL083A"}

    def test_the_largest_stack_a_declaration_may_list_keeps_its_last_module_line(self) -> None:
        text = _stanza(*(
            line for n in range(1, MAX_DEPLOYMENT_MEMBERS + 1)
            for line in (f'member {n} type "JL322A"', f"member {n} flexible-module A type JL083A")
        ))
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert len(proposal.evidence) == 2 + 2 * MAX_DEPLOYMENT_MEMBERS
        assert proposal.evidence[-2:] == ['member 64 type "JL322A"', "member 64 flexible-module A type JL083A"]
        assert not [n for n in proposal.notes if "are listed" in n]

    def test_evidence_goes_a_member_at_a_time(self) -> None:
        """Whatever order the stanza has them in."""
        text = _stanza(
            "member 2 flexible-module A type JL078A", 'member 2 type "R0M67A"',
            "member 1 flexible-module A type JL083A", 'member 1 type "JL322A"',
        )
        assert detect_deployment(text).evidence == [
            "; hpStack_WC Configuration Editor", "stacking",
            'member 1 type "JL322A"', "member 1 flexible-module A type JL083A",
            'member 2 type "R0M67A"', "member 2 flexible-module A type JL078A",
        ]


class TestMoreThatTheDetectorSaysItDidNotRead:
    """The same for a module, a nested member and the chassis line as
    for a ``member <n> type`` line: what set out to state hardware and
    was not read is counted, and what was chosen between two is said."""

    def test_a_module_line_of_a_stack_that_could_not_be_read(self) -> None:
        """The config STATES the module.  Without the note the proposal
        has an empty bay and blames a module "the config does not
        state"."""
        text = _stanza(
            'member 1 type "JL322A"',
            "member 1 flexible-module A type JL083A#ABB",
            "member 1 flexible-module AB type JL083A",
        ) + "vlan 1\n   untagged 1/1-1/48,1/A1-1/A4\n   exit\n"
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment.members[0].modules == {}
        assert proposal.missing_ports == ["1/A1", "1/A2", "1/A3", "1/A4"]
        (note,) = [n for n in proposal.notes if "could not be read as a module" in n]
        assert note.startswith("2 line(s) of the stanza begin `member <number> flexible-module <bay> type`")
        assert "a bay may be proposed empty" in note

    def test_a_module_line_of_a_switch_that_is_not_stacked(self) -> None:
        text = _JL322A_TOP + "flexible-module A type JL083A-B21\nvlan 1\n   untagged 1-48,A1-A4\n   exit\n"
        proposal = propose_deployment(AOSS, text, REGISTRY)
        assert proposal.deployment.members[0].modules == {} and proposal.missing_port_count == 4
        (note,) = [n for n in proposal.notes if "could not be read as a module" in n]
        assert note.startswith("1 line(s) begin `flexible-module <bay> type`")

    def test_a_vsf_block_whose_number_could_not_be_read_is_not_the_block_before(self) -> None:
        """``member 1`` has no type line; ``member 2x`` has one.  The
        type line is not member 1's: read on past the header it could
        not read, the detector proposed member 1 as that model."""
        text = _STACK_BANNER + 'vsf\n   member 1\n      exit\n   member 2x\n      type "JL557A"\n      exit\n   exit\n'
        detected = detect_deployment(text)
        assert detected.members == []
        assert "no line in it names a member" in detected.notes[0]
        assert any("1 line(s) of the stanza begin a `member` block whose number could not be read" in n
                   for n in detected.notes)
        assert any("no `type` line that could be read for member 1;" in n for n in detected.notes)

    def test_a_vsf_member_dropped_for_its_number_is_said(self) -> None:
        text = _STACK_BANNER + (
            'vsf\n   member 1\n      type "JL557A"\n      exit\n'
            '   member 1234567\n      type "JL557A"\n      exit\n   exit\n'
        )
        detected = detect_deployment(text)
        assert _members(detected) == [(1, "JL557A", {})]
        assert any("whose number could not be read" in n for n in detected.notes)

    def test_a_vsf_member_headed_twice_and_typed_once_has_a_type(self) -> None:
        text = _STACK_BANNER + (
            'vsf\n   member 1\n      type "JL557A"\n      exit\n   member 1\n      priority 200\n      exit\n   exit\n'
        )
        detected = detect_deployment(text)
        assert _members(detected) == [(1, "JL557A", {})]
        assert not [n for n in detected.notes if "no `type` line" in n]

    def test_a_member_line_that_stops_at_the_word_type(self) -> None:
        detected = detect_deployment(_stanza('member 1 type "JL322A"', "member 2 type"))
        assert _members(detected) == [(1, "JL322A", {})]
        assert any(n.startswith("1 line(s) of the stanza begin `member <number> type`") for n in detected.notes)

    @pytest.mark.parametrize(
        ("text", "members", "said"),
        [
            (
                _stanza('member 1 type "JL322A"', "member 1 flexible-module A type JL083A",
                        "member 1 flexible-module A type JL078A"),
                [(1, "JL322A", {"A": "JL078A"})],
                "More than one line states a bay of member 1 with different modules; the last was used.",
            ),
            (
                _JL322A_TOP + "flexible-module A type JL083A\nflexible-module A type JL078A\n",
                [(None, "JL322A", {"A": "JL078A"})],
                "More than one line states a bay with different modules; the last was used.",
            ),
            (
                "; JL322A Configuration Editor; Created on release #WC.16.07.0003\n"
                "; JL320A Configuration Editor; Created on release #WC.16.07.0003\n",
                [(None, "JL322A", {})],
                "The config has more than one banner (JL322A, then JL320A); the first was read.",
            ),
            (
                _JL322A_TOP + "module 1 type jl320a\n",
                [(None, "JL322A", {})],
                "The config has more than one `module 1` line (JL322A, then JL320A); the first was used.",
            ),
            (
                "; JL322A Configuration Editor; Created on release #WC.16.07.0003\n"
                'stacking\n   member 1 type "JL322A"\n   exit\n',
                [(1, "JL322A", {})],
                "The banner names one switch (JL322A) and the config has a `stacking` stanza; the stanza was read.",
            ),
            (
                _stanza('member 1 type "JL322A"') + "module 1 type jl322a\n",
                [(1, "JL322A", {})],
                "The config has a `module 1` line, which a switch that is not stacked prints, and a `stacking` "
                "stanza; the stanza was read.",
            ),
            (
                "; JL320A Configuration Editor; Created on release #WC.16.07.0003\nmodule 1 type jl322a spare\n",
                [(None, "JL320A", {})],
                "1 line(s) begin `module 1 type` and could not be read as the chassis line; each was left out.",
            ),
        ],
        ids=["a bay of a member twice", "a bay twice", "two banners", "two module 1 lines",
             "a part banner and a stanza", "a module 1 line and a stanza", "a module 1 line with more on it"],
    )
    def test_what_was_chosen_between_two_is_said(self, text: str, members: list, said: str) -> None:
        detected = detect_deployment(text)
        assert _members(detected) == members
        assert said in detected.notes, detected.notes

    def test_a_bay_stated_twice_the_same_is_not_a_contradiction(self) -> None:
        text = _JL322A_TOP + "flexible-module A type JL083A\nflexible-module A type jl083a\n"
        assert not [n for n in detect_deployment(text).notes if "More than one" in n]

    def test_a_module_1_line_with_no_banner(self) -> None:
        """The banner is not what a note is about when there is none."""
        detected = detect_deployment('hostname "sw"\nmodule 1 type jl322a\n')
        assert _members(detected) == [(None, "JL322A", {})]
        assert detected.notes == [] and detected.evidence == ["module 1 type jl322a"]

    def test_a_module_1_line_that_could_not_be_read_and_no_banner(self) -> None:
        detected = detect_deployment('hostname "sw"\nmodule 1 type jl322a#abb\n')
        assert detected.members == [] and detected.fabric == ""
        assert detected.notes == [
            "The config has a `module 1` line, but it could not be read as a chassis part number, and no "
            "banner names a model."
        ]

    @pytest.mark.parametrize(
        "name",
        [
            "aruba_central_5memberstack_rendered.cfg",
            "hpe_community_2920_wb1608_dhcp_snooping.cfg",
            "hpe_community_2930f_wc1607_intervlan.cfg",
            "hpe_community_2930f_wc1610_dhcp_server.cfg",
            "hpe_community_5406rzl2_kb1515.cfg",
            "user_contrib_2930m_wc1611.cfg",
        ],
    )
    def test_nothing_of_the_kind_is_said_of_a_config_a_device_printed(self, name: str) -> None:
        """Every one of these notes is about text no device prints.
        On the committed captures the detector says only what a line
        cannot show."""
        detected = detect_deployment(_capture(name))
        cannot_show = (
            "A member line shows what the stack is provisioned for",
            "A flexible-module line shows what the bay is provisioned for",
            "The config lists line cards in lettered slots",
        )
        assert not [n for n in detected.notes if not n.startswith(cannot_show)], detected.notes

    def test_every_committed_capture_is_in_that_list(self) -> None:
        tested = {
            "aruba_central_5memberstack_rendered.cfg", "hpe_community_2920_wb1608_dhcp_snooping.cfg",
            "hpe_community_2930f_wc1607_intervlan.cfg", "hpe_community_2930f_wc1610_dhcp_server.cfg",
            "hpe_community_5406rzl2_kb1515.cfg", "user_contrib_2930m_wc1611.cfg",
        }
        assert {path.name for path in FIXTURES.glob("*.cfg")} == tested


class TestTheRequest:
    def test_the_text_is_capped_like_a_plan_requests(self) -> None:
        """This endpoint parses the text too."""
        from netcanon.api.routes.migration import DeploymentDetectRequest, MigrationPlanRequest

        (cap,) = [m.max_length for m in MigrationPlanRequest.model_fields["raw_text"].metadata]
        assert DeploymentDetectRequest(source="aruba_aoss", raw_text="x" * cap).raw_text is not None
        with pytest.raises(ValueError, match="at most"):
            DeploymentDetectRequest(source="aruba_aoss", raw_text="x" * (cap + 1))


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
