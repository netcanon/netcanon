"""One name written in two letter cases is one name.

AOS-S writes a LAG ``trk1`` where it is defined (``trunk 51-52 trk1
lacp``) and ``Trk1`` where a VLAN lists it or an ``interface Trk1``
stanza configures it.  The platform's names have no letter case, so
that is one LAG.  Kept as two names it was two ports to everything
downstream:

* the port translator's warning for two source ports on one target
  counted them: "multiple source ports map to 'Trk1' (sources: Trk1,
  trk1) ... their VLAN membership will be merged", on every job for a
  config that names a LAG in both cases, with nothing merged at all;
* the job's ``port_renames`` had a key for each, so the rename modal
  drew the LAG as two rows aimed at one target, counted a collision
  and would not apply;
* a rename map had two keys for one LAG, and an entry for one left the
  other where it was.

Three things hold that shut, and each is tested here by itself:

1. the AOS-S parser gives every reference to a LAG the spelling of its
   definition, so the tree has one name;
2. on a platform whose names have no case, an operator's key in
   another letter case reaches the name the config uses;
3. where one name does reach the translator in two cases (a hardware
   port an operator typed ``a1`` beside the device's ``A1``), the two
   count as one source -- and if a rename map sends them apart, the
   job says so.

On FortiOS and RouterOS, where an operator chooses interface names,
``DMZ`` and ``dmz`` are two interfaces, and none of this applies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.port_names import collect_port_names, translate_port_names
from netcanon.migration.codecs.aruba_aoss.parse import _one_name_per_lag
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.device_models import Deployment, compile_deployment, load_model_families_dir
from netcanon.services.migration_pipeline import run_plan_with_models, run_plan_with_overrides

pytestmark = pytest.mark.unit

AOSS = get_codec("aruba_aoss")
REGISTRY = load_model_families_dir(LIBRARY_DIR / "model_families")
REPO_ROOT = Path(__file__).resolve().parents[3]
KITCHEN_SINK = (REPO_ROOT / "tests/fixtures/synthetic/aruba_aoss/kitchen_sink.cfg").read_text(encoding="utf-8")

#: A LAG in every spelling a config can hold: its definition, a VLAN
#: that lists it as the device prints it, its own interface stanza, and
#: a spelling no device prints but a hand can.
_ONE_LAG = """; JL260A Configuration Editor; Created on release #WC.16.07.0002
hostname "sw"
trunk 51-52 trk1 lacp
interface Trk1
   name "uplink"
   exit
vlan 1
   name "DEFAULT_VLAN"
   untagged 1-50
   tagged Trk1
   exit
vlan 20
   name "TWENTY"
   tagged TRK1,5
   exit
"""


def _merged(job) -> list[str]:
    return [w for w in job.warnings if "multiple source ports map to" in w]


def _apart(warnings: list[str]) -> list[str]:
    return [w for w in warnings if "do not end together" in w]


def _spellings(names, of: str) -> set[str]:
    return {name for name in names if name.casefold() == of}


# ---------------------------------------------------------------------------
# 1. The parser: one LAG, one name
# ---------------------------------------------------------------------------


class TestTheParserGivesALagOneName:
    def test_every_reference_takes_the_spelling_of_the_definition(self) -> None:
        tree = AOSS.parse(_ONE_LAG)
        assert [lag.name for lag in tree.lags] == ["trk1"]
        assert _spellings(collect_port_names(tree), "trk1") == {"trk1"}
        assert _spellings((iface.name for iface in tree.interfaces), "trk1") == {"trk1"}
        vlans = {vlan.id: vlan for vlan in tree.vlans}
        assert vlans[1].tagged_ports == ["trk1"]
        assert sorted(vlans[20].tagged_ports) == ["5", "trk1"]

    def test_the_interface_stanza_keeps_what_it_configured(self) -> None:
        """Renamed, not dropped: it is the LAG's own interface record."""
        tree = AOSS.parse(_ONE_LAG)
        (uplink,) = [iface for iface in tree.interfaces if iface.name == "trk1"]
        assert uplink.description == "uplink"

    def test_a_list_that_named_the_lag_twice_names_it_once(self) -> None:
        tree = AOSS.parse(_ONE_LAG.replace("tagged TRK1,5", "tagged TRK1,5,Trk1"))
        vlans = {vlan.id: vlan for vlan in tree.vlans}
        assert sorted(vlans[20].tagged_ports) == ["5", "trk1"]

    def test_the_same_text_comes_back(self) -> None:
        """The renderer writes each form where the device does,
        whatever the tree calls the LAG."""
        rendered = AOSS.render(AOSS.parse(_ONE_LAG))
        assert "trunk 51-52 trk1 lacp" in rendered
        assert "   tagged Trk1" in rendered and "interface Trk1" in rendered
        again = AOSS.parse(rendered).model_dump(exclude={"source_version"})
        assert again == AOSS.parse(_ONE_LAG).model_dump(exclude={"source_version"})

    def test_only_a_lag_is_given_one_name(self) -> None:
        """A hardware port typed in another case is not the parser's
        to decide: no definition says which spelling is the port's."""
        tree = AOSS.parse(_ONE_LAG.replace("tagged TRK1,5", "tagged TRK1,5,A1,a1"))
        assert _spellings(collect_port_names(tree), "a1") == {"A1", "a1"}

    def test_a_config_with_no_lag_is_left_alone(self) -> None:
        text = _ONE_LAG.replace("trunk 51-52 trk1 lacp\n", "")
        tree = AOSS.parse(text)
        assert tree.lags == []
        assert _spellings(collect_port_names(tree), "trk1") == {"Trk1", "TRK1"}

    def test_every_place_a_port_name_is_kept_is_reached(self) -> None:
        """The parser uses the translator's own sweep.  A tree built by
        hand with the other spelling in each kind of place."""
        tree = CanonicalIntent.model_validate({
            "interfaces": [
                {"name": "Trk1"},
                {"name": "51", "lag_member_of": "TRK1"},
            ],
            "vlans": [{"id": 10, "tagged_ports": ["Trk1"], "untagged_ports": ["tRK1"]}],
            "lags": [{"name": "trk1", "members": ["51", "52"]}],
            "static_routes": [
                {"destination": "10.0.0.0/8", "gateway": "", "interface": "Trk1"},
                {"destination": "10.1.0.0/16", "gateway": "Trk1"},
            ],
        })
        _one_name_per_lag(tree)
        assert _spellings(collect_port_names(tree), "trk1") == {"trk1"}
        assert tree.interfaces[1].lag_member_of == "trk1"
        assert (tree.vlans[0].tagged_ports, tree.vlans[0].untagged_ports) == (["trk1"], ["trk1"])
        assert [route.interface or route.gateway for route in tree.static_routes] == ["trk1", "trk1"]

    def test_no_committed_aos_s_config_has_a_lag_under_two_names(self) -> None:
        checked = 0
        for path in sorted((REPO_ROOT / "tests/fixtures").rglob("*aruba_aoss*/*.cfg")):
            tree = AOSS.parse(path.read_text(encoding="utf-8"))
            for lag in tree.lags:
                checked += 1
                assert _spellings(collect_port_names(tree), lag.name.casefold()) == {lag.name}, path.name
        assert checked


# ---------------------------------------------------------------------------
# What a job then says, on every target
# ---------------------------------------------------------------------------


class TestAJobHasOneNameForTheLag:
    @pytest.mark.parametrize("target", list_public_codecs())
    def test_one_key_and_no_line_on_every_public_target(self, target: str) -> None:
        """``port_renames`` is what the rename modal draws its rows
        from: two keys on one target were two rows, a collision, and
        an Apply button that would not work.  The two targets whose own
        names have case are among these on purpose -- the rule is the
        SOURCE platform's."""
        job = run_plan_with_overrides(AOSS, get_codec(target), _ONE_LAG, port_rename_map={})
        assert job.rendered, "a job that did not render carries no line either"
        assert _merged(job) == [] and _apart(job.warnings) == []
        assert _spellings(job.port_renames, "trk1") == {"trk1"}

    @pytest.mark.parametrize("target", list_public_codecs())
    def test_the_committed_kitchen_sink_has_two_lags(self, target: str) -> None:
        """``trunk ... trk1`` / ``trk2`` beside ``interface Trk1`` /
        ``Trk2``: the one committed config that names a LAG two ways."""
        job = run_plan_with_overrides(AOSS, get_codec(target), KITCHEN_SINK, port_rename_map={})
        assert job.rendered
        assert not [line for line in _merged(job) if "rk" in line]
        assert _spellings(job.port_renames, "trk1") == {"trk1"}
        assert _spellings(job.port_renames, "trk2") == {"trk2"}

    def test_with_both_devices_declared(self) -> None:
        """A declared job always carries a port map."""
        source = compile_deployment(
            Deployment(vendor="aruba_aoss", mode="standalone", members=[{"model": "JL260A"}]), REGISTRY,
        )
        target = compile_deployment(
            Deployment(vendor="aruba_aoss", mode="stacked", members=[
                {"model": "JL322A", "id": 1, "modules": {"A": "JL083A"}},
            ]),
            REGISTRY,
        )
        job = run_plan_with_models(AOSS, AOSS, _ONE_LAG, source, target)
        assert job.rendered and _merged(job) == [] and _apart(job.warnings) == []
        assert _spellings(job.port_renames, "trk1") == {"trk1"}

    def test_a_port_sent_onto_the_lag_is_still_two_sources(self) -> None:
        job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={"5": "Trk1"})
        (line,) = _merged(job)
        assert "(sources: 5, trk1)" in line

    def test_two_ports_on_one_name_are_still_said(self) -> None:
        """The warning itself is untouched: two ports an operator sends
        to one name are two ports."""
        job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={"1": "2"})
        (line,) = _merged(job)
        assert "(sources: 1, 2)" in line and "rk" not in line


# ---------------------------------------------------------------------------
# 2. An operator's key in another letter case
# ---------------------------------------------------------------------------


class TestAKeyInAnotherLetterCase:
    @pytest.mark.parametrize("key", ["trk1", "Trk1", "TRK1"])
    def test_a_new_name_takes_the_whole_lag(self, key: str) -> None:
        """Half of it used to move: the definition under one key, the
        VLAN lists under the other."""
        job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={key: "Trk7"})
        assert job.port_renames["trk1"] == "Trk7"
        assert "trunk 51-52 trk7 lacp" in job.rendered and "interface Trk7" in job.rendered
        assert "Trk1" not in job.rendered and "trk1" not in job.rendered
        assert not [w for w in job.warnings if "does not exist in the parsed config" in w]

    @pytest.mark.parametrize("key", ["trk1", "Trk1"])
    def test_a_drop_takes_the_whole_lag(self, key: str) -> None:
        job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={key: None})
        assert job.port_drops == ["trk1"]
        assert "rk1" not in job.rendered.lower().replace("trunk-load-balance", "")

    def test_an_exact_key_is_not_laid_over_by_another_spelling(self) -> None:
        job = run_plan_with_overrides(
            AOSS, AOSS, _ONE_LAG, port_rename_map={"Trk1": "Trk7", "trk1": "Trk8"},
        )
        assert job.port_renames["trk1"] == "Trk8"
        assert [w for w in job.warnings if "source port 'Trk1' does not exist" in w]

    def test_a_key_is_not_guessed_between_two_names(self) -> None:
        """``A1`` and ``a1`` are both in the tree: a key ``A1`` is the
        name ``A1``, and a third spelling is neither."""
        tree = CanonicalIntent.model_validate({"vlans": [{"id": 10, "tagged_ports": ["A1", "a1"]}]})
        result = translate_port_names(tree, AOSS, AOSS, rename_map={"A1": "1/9"})
        assert tree.vlans[0].tagged_ports == ["1/9", "a1"]
        assert result.applied == {"A1": "1/9"}
        tree = CanonicalIntent.model_validate({"vlans": [{"id": 10, "tagged_ports": ["Dmz", "dMZ"]}]})
        result = translate_port_names(tree, AOSS, AOSS, rename_map={"DMZ": "1/9"})
        assert "1/9" not in tree.vlans[0].tagged_ports and result.applied == {}
        assert [w for w in result.warnings if "source port 'DMZ' does not exist" in w]

    @pytest.mark.parametrize("source", ["fortigate_cli", "mikrotik_routeros"])
    def test_where_names_have_case_a_key_is_the_name_exactly(self, source: str) -> None:
        tree = CanonicalIntent.model_validate({"vlans": [{"id": 10, "tagged_ports": ["dmz"]}]})
        result = translate_port_names(tree, get_codec(source), AOSS, rename_map={"DMZ": "1/9"})
        assert tree.vlans[0].tagged_ports != ["1/9"]
        assert [w for w in result.warnings if "source port 'DMZ' does not exist" in w]


# ---------------------------------------------------------------------------
# 3. A name that reaches the translator in two cases
# ---------------------------------------------------------------------------


def _two_cases(source: str, target: str, rename_map: dict) -> list[str]:
    tree = CanonicalIntent.model_validate({"vlans": [{"id": 10, "tagged_ports": ["DMZ", "dmz"]}]})
    result = translate_port_names(tree, get_codec(source), get_codec(target), rename_map=rename_map)
    return [w for w in result.warnings if w.startswith("port_rename:")]


class TestOneNameInTwoCasesAtTheTranslator:
    @pytest.mark.parametrize(
        ("source", "merged"),
        [("fortigate_cli", True), ("mikrotik_routeros", True), ("aruba_aoss", False), ("cisco_iosxe_cli", False)],
    )
    def test_two_cases_are_two_sources_only_where_the_platform_has_case(self, source: str, merged: bool) -> None:
        """Sent to one target.  On FortiOS and RouterOS ``DMZ`` is not
        ``dmz``: two sources, and the line says so.  Where names have
        no case it is one name written twice."""
        lines = _two_cases(source, "aruba_aoss", {"DMZ": "1/9", "dmz": "1/9"})
        said = [line for line in lines if "multiple source ports map to" in line]
        assert bool(said) is merged
        if merged:
            assert "(sources: DMZ, dmz)" in said[0]
        assert _apart(lines) == []

    def test_a_real_clash_names_each_source_once(self) -> None:
        """Three names on one target, two of them one name: two
        sources, and the line shows the spelling that sorts first."""
        tree = CanonicalIntent.model_validate({"vlans": [{"id": 10, "tagged_ports": ["DMZ", "dmz", "x9"]}]})
        result = translate_port_names(
            tree, AOSS, AOSS, rename_map={"DMZ": "1/9", "dmz": "1/9", "x9": "1/9"},
        )
        (line,) = [w for w in result.warnings if "multiple source ports map to" in w]
        assert "(sources: DMZ, x9)" in line

    @pytest.mark.parametrize("target", ["aruba_aoss", "fortigate_cli", "mikrotik_routeros"])
    def test_the_rule_is_the_source_platforms_whatever_the_target(self, target: str) -> None:
        lines = _two_cases("aruba_aoss", target, {"DMZ": "x1", "dmz": "x1"})
        assert not [line for line in lines if "multiple source ports map to" in line]

    def test_sent_apart_it_is_said(self) -> None:
        """An entry for one spelling leaves the other where it was: one
        port's config in two places, which the count above would hide."""
        (line,) = _apart(_two_cases("aruba_aoss", "aruba_aoss", {"DMZ": "1/9"}))
        assert line == (
            "port_rename: DMZ and dmz are one name on aruba_aoss, written in more than one letter "
            "case, and do not end together (DMZ -> 1/9, dmz -> dmz) — give every spelling the same entry"
        )

    def test_one_dropped_and_one_kept_is_said(self) -> None:
        (line,) = _apart(_two_cases("aruba_aoss", "aruba_aoss", {"DMZ": None}))
        assert "(DMZ -> dropped, dmz -> dmz)" in line

    @pytest.mark.parametrize("rename_map", [{}, {"DMZ": "1/9", "dmz": "1/9"}, {"DMZ": None, "dmz": None}])
    def test_ending_together_is_not(self, rename_map: dict) -> None:
        assert _apart(_two_cases("aruba_aoss", "aruba_aoss", rename_map)) == []

    def test_together_is_the_targets_word(self) -> None:
        """Left as they are, ``DMZ`` and ``dmz`` are one port on a
        target with no case and two interfaces on one that has it."""
        assert _apart(_two_cases("aruba_aoss", "aruba_aoss", {})) == []
        (line,) = _apart(_two_cases("aruba_aoss", "fortigate_cli", {}))
        assert "(DMZ -> DMZ, dmz -> dmz)" in line

    @pytest.mark.parametrize("source", ["fortigate_cli", "mikrotik_routeros"])
    def test_where_names_have_case_two_names_may_end_anywhere(self, source: str) -> None:
        assert _apart(_two_cases(source, "aruba_aoss", {"DMZ": "1/9"})) == []
