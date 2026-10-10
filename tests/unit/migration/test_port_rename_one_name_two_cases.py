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

Four things hold that shut, and each is tested here by itself:

1. the AOS-S parser writes a LAG one way, ``trk<n>``, wherever it
   reads one, so the tree has one name;
2. on a platform whose names have no case, an operator's key in
   another letter case reaches the name the config uses -- with or
   without devices declared, by one rule;
3. where one name does reach the translator in two cases (a hardware
   port an operator typed ``a1`` beside the device's ``A1``), the two
   count as one source -- and if a rename map sends them apart, the
   job says so;
4. two FINAL names that differ only in letter case are one place on a
   target without case, and two source ports sent there are reported.

On FortiOS and RouterOS, where an operator chooses interface names,
``DMZ`` and ``dmz`` are two interfaces, and none of this applies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.port_names import collect_port_names, translate_port_names
from netcanon.migration.codecs.aruba_aoss.parse import _one_name_per_lag, _parse_port_list
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.device_models import (
    Deployment,
    compile_deployment,
    inventory_from_profile,
    load_model_families_dir,
)
from netcanon.migration.target_profiles import load_profiles_dir
from netcanon.services.migration_pipeline import run_plan_with_models, run_plan_with_overrides

pytestmark = pytest.mark.unit

AOSS = get_codec("aruba_aoss")
JUNOS = get_codec("juniper_junos")
REGISTRY = load_model_families_dir(LIBRARY_DIR / "model_families")
PROFILES = load_profiles_dir(LIBRARY_DIR / "target_profiles")
REPO_ROOT = Path(__file__).resolve().parents[3]
KITCHEN_SINK = (REPO_ROOT / "tests/fixtures/synthetic/aruba_aoss/kitchen_sink.cfg").read_text(encoding="utf-8")
#: A real 2930M stack of one member with an uplink module: ``1/A1``.
CAPTURE_2930M = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg"
).read_text(encoding="utf-8")
#: A real Junos config whose ``fxp0`` is no port of an EX4300.
CAPTURE_JUNOS = (
    REPO_ROOT / "tests/fixtures/real/junos/tsg8139_evpn_leaf_dhcpv6_junos232.set"
).read_text(encoding="utf-8")

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


def _stack():
    """The device ``CAPTURE_2930M`` is of."""
    return compile_deployment(
        Deployment(vendor="aruba_aoss", mode="stacked", members=[
            {"model": "JL323A", "id": 1, "modules": {"A": "JL083A"}},
        ]),
        REGISTRY,
    )


def _facts(job) -> dict:
    """A job without what differs between any two runs."""
    data = job.model_dump(mode="json")
    for key in ("id", "created_at", "completed_at"):
        data.pop(key, None)
    return data


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
        to decide: nothing says which spelling is the port's."""
        tree = AOSS.parse(_ONE_LAG.replace("tagged TRK1,5", "tagged TRK1,5,A1,a1"))
        assert _spellings(collect_port_names(tree), "a1") == {"A1", "a1"}

    def test_with_its_trunk_line_cut_off_the_lag_still_has_one_name(self) -> None:
        """The one name does not wait for a definition: a paste that
        lost its ``trunk`` line refers to the LAG two ways all the
        same, and they are still one LAG."""
        text = _ONE_LAG.replace("trunk 51-52 trk1 lacp\n", "")
        tree = AOSS.parse(text)
        assert tree.lags == []
        assert _spellings(collect_port_names(tree), "trk1") == {"trk1"}

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
        paths = sorted(
            path for path in (REPO_ROOT / "tests/fixtures").rglob("*")
            if path.is_file() and path.parent.name == "aruba_aoss" and path.suffix in {".cfg", ".txt"}
        )
        assert "show_run_simple.txt" in {path.name for path in paths}
        for path in paths:
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
# 2b. The same key with both devices declared
# ---------------------------------------------------------------------------


class TestAKeyInAnotherCaseDevicesDeclared:
    """The pairing has an entry of its own for every port it placed,
    under the name the config uses.  An operator's entry in another
    letter case has to replace THAT entry, and the plan has to say
    what the job did.  The rule is applied before the two are merged:
    merged first, the pairing's entry was "an entry of its own" and the
    operator's was set aside -- a drop that was asked for was not made,
    in a job that said ``completed``."""

    @pytest.mark.parametrize("value", [None, "1/A4"])
    def test_a_paired_port_is_the_same_job_as_under_the_configs_spelling(self, value) -> None:
        exact = run_plan_with_models(AOSS, AOSS, CAPTURE_2930M, _stack(), _stack(), port_rename_map={"1/A1": value})
        other = run_plan_with_models(AOSS, AOSS, CAPTURE_2930M, _stack(), _stack(), port_rename_map={"1/a1": value})
        assert _facts(other) == _facts(exact)
        assert other.port_mapping_plan.overridden == ["1/A1"]
        if value is None:
            assert other.port_drops == ["1/A1"]
        else:
            assert other.port_renames["1/A1"] == "1/A4"

    @pytest.mark.parametrize("value", [None, "ge-0/0/47"])
    def test_a_port_the_plan_did_not_place_is_decided_under_either_spelling(self, value) -> None:
        """``fxp0`` is no port of an EX4300: the job is partial until
        the operator decides it.  Deciding it as ``FXP0`` is deciding
        it -- the entry was applied and the plan still called the port
        undecided."""
        ex = inventory_from_profile(PROFILES["juniper_junos/EX4300-48T"])
        exact = run_plan_with_models(JUNOS, JUNOS, CAPTURE_JUNOS, ex, ex, port_rename_map={"fxp0": value})
        other = run_plan_with_models(JUNOS, JUNOS, CAPTURE_JUNOS, ex, ex, port_rename_map={"FXP0": value})
        assert "fxp0" not in other.port_mapping_plan.unresolved_ports
        assert _facts(other) == _facts(exact)

    def test_the_same_body_with_and_without_devices_drops_the_same_port(self) -> None:
        plain = run_plan_with_overrides(AOSS, AOSS, CAPTURE_2930M, port_rename_map={"1/a1": None})
        declared = run_plan_with_models(AOSS, AOSS, CAPTURE_2930M, _stack(), _stack(), port_rename_map={"1/a1": None})
        assert plain.port_drops == declared.port_drops == ["1/A1"]
        assert not [w for w in declared.warnings if "does not exist" in w]

    def test_an_entry_set_aside_is_reported_under_the_configs_spelling(self) -> None:
        """A blank target decides nothing and is set aside.  It is
        reported by the name of the port it was for, not by a key the
        config does not hold."""
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930M, _stack(), _stack(), port_rename_map={"1/a1": "  "},
        )
        assert job.port_mapping_plan.ignored_overrides == ["1/A1"]
        assert job.port_drops == []

    def test_the_source_platforms_rule_decides_whatever_the_target(self) -> None:
        """AOS-S names have no letter case; FortiOS names have.  The key
        is a SOURCE name, so it is the source's rule that makes ``1/a1``
        the port ``1/A1`` -- onto a FortiGate as onto anything else."""
        forti = get_codec("fortigate_cli")
        assert forti.port_names_case_sensitive and not AOSS.port_names_case_sensitive
        target = inventory_from_profile(PROFILES["fortigate/60F"])
        exact = run_plan_with_models(AOSS, forti, CAPTURE_2930M, _stack(), target, port_rename_map={"1/A1": None})
        other = run_plan_with_models(AOSS, forti, CAPTURE_2930M, _stack(), target, port_rename_map={"1/a1": None})
        assert other.port_drops == exact.port_drops and "1/A1" in other.port_drops
        assert _facts(other) == _facts(exact)

    def test_both_spellings_given_the_exact_one_stands_and_the_other_is_said(self) -> None:
        job = run_plan_with_models(
            AOSS, AOSS, CAPTURE_2930M, _stack(), _stack(), port_rename_map={"1/A1": None, "1/a1": "1/A4"},
        )
        assert job.port_drops == ["1/A1"]
        assert [w for w in job.warnings if "'1/a1' is another spelling of '1/A1'" in w]

    @pytest.mark.parametrize("source", ["fortigate_cli", "mikrotik_routeros"])
    def test_where_names_have_case_a_key_is_still_the_name_exactly(self, source: str) -> None:
        """The rule is not applied for a platform where another letter
        case is another interface."""
        from netcanon.services.migration_pipeline import _key_by_the_configs_name

        codec = get_codec(source)
        assert codec.port_names_case_sensitive
        entries: dict = {"DMZ": None}
        plan = run_plan_with_models(AOSS, AOSS, CAPTURE_2930M, _stack(), _stack()).port_mapping_plan
        _key_by_the_configs_name(entries, plan, ["dmz"], [], fold_source=False)
        assert entries == {"DMZ": None}
        _key_by_the_configs_name(entries, plan, ["dmz"], [], fold_source=True)
        assert entries == {"dmz": None}


# ---------------------------------------------------------------------------
# 4. One TARGET in two letter cases
# ---------------------------------------------------------------------------


class TestOneTargetInTwoLetterCases:
    def test_a_port_sent_onto_the_lag_by_the_name_the_tree_uses(self) -> None:
        """The tree calls the LAG ``trk1`` and the translator writes it
        ``Trk1``: on AOS-S that is one place, and port 5 is on it.
        Grouped by the exact string, nothing was said."""
        job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={"5": "trk1"})
        (line,) = _merged(job)
        assert "(sources: 5, trk1)" in line
        assert "map to 'Trk1' (also written 'trk1': one port on aruba_aoss)" in line

    def test_two_overrides_that_differ_only_in_letter_case(self) -> None:
        job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={"1": "9/Z1", "2": "9/z1"})
        (line,) = [w for w in _merged(job) if "9/" in w]
        assert "(sources: 1, 2)" in line

    def test_where_the_target_has_case_two_spellings_are_two_places(self) -> None:
        forti = get_codec("fortigate_cli")
        assert forti.port_names_case_sensitive
        job = run_plan_with_overrides(AOSS, forti, _ONE_LAG, port_rename_map={"1": "Wan", "2": "wan"})
        assert not [w for w in _merged(job) if "wan" in w.lower()]

    def test_two_records_on_one_name_are_said_once(self) -> None:
        """Two interface stanzas renamed onto one name are reported by
        the sweep of the records; the sweep of every other reference
        does not say it a second time."""
        text = _ONE_LAG.replace(
            "vlan 1\n", 'interface 1\n   name "a"\n   exit\ninterface 2\n   name "b"\n   exit\nvlan 1\n', 1,
        )
        job = run_plan_with_overrides(AOSS, AOSS, text, port_rename_map={"1": "2"})
        (line,) = _merged(job)
        assert "(sources: 1, 2)" in line and "interface stanzas" in line

    def test_one_final_spelling_reads_as_it_always_did(self) -> None:
        job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={"5": "Trk1"})
        (line,) = _merged(job)
        assert "map to 'Trk1' (sources: 5, trk1)" in line


# ---------------------------------------------------------------------------
# 1b. The parser, where the first tests did not look
# ---------------------------------------------------------------------------


class TestTheParserWhereNoTestLooked:
    def test_an_untagged_list_that_named_the_lag_twice_names_it_once(self) -> None:
        tree = AOSS.parse(_ONE_LAG.replace("untagged 1-50", "untagged 1-50,Trk1,trk1"))
        (vlan,) = [v for v in tree.vlans if v.id == 1]
        assert vlan.untagged_ports.count("trk1") == 1

    @pytest.mark.parametrize("target", list_public_codecs())
    def test_a_definition_typed_in_capitals_is_still_a_lag_on_every_target(self, target: str) -> None:
        """``TRK1`` on a ``trunk`` line is a spelling a hand can type.
        The references the device prints (``Trk1``) must not be dragged
        onto a name the codec's own classifier cannot read."""
        text = _ONE_LAG.replace("trunk 51-52 trk1 lacp", "trunk 51-52 TRK1 lacp")
        job = run_plan_with_overrides(AOSS, get_codec(target), text, port_rename_map={})
        assert job.rendered
        assert not [w for w in job.warnings if "could not classify" in w]
        assert "TRK1" not in job.rendered
        assert _spellings(job.port_renames, "trk1") == {"trk1"}

    @pytest.mark.parametrize("typed", ["Trk1", "TRK1", "tRk1"])
    def test_however_the_definition_is_typed_the_tree_is_the_same(self, typed: str) -> None:
        """So that a config comes back, and parsed again, is the tree
        it was: with the definition's own spelling kept, ``Trk1`` on a
        ``trunk`` line parsed to ``Trk1`` and its render to ``trk1``."""
        text = _ONE_LAG.replace("trunk 51-52 trk1 lacp", f"trunk 51-52 {typed} lacp")
        tree = AOSS.parse(text)
        assert tree.model_dump() == AOSS.parse(_ONE_LAG).model_dump()
        assert AOSS.parse(AOSS.render(tree)).model_dump(exclude={"source_version"}) == (
            tree.model_dump(exclude={"source_version"})
        )

    def test_a_lag_with_another_ports_name_does_not_take_the_port(self) -> None:
        """Only a name the platform calls a trunk is one name with its
        other spellings: ``a1`` on a pasted ``trunk`` line is not the
        uplink ``A1``."""
        text = _ONE_LAG.replace("trunk 51-52 trk1 lacp", "trunk 51-52 a1 lacp").replace("tagged Trk1", "tagged A1")
        tree = AOSS.parse(text)
        assert {"A1", "a1"} <= set(collect_port_names(tree))

    def test_two_trunk_lines_for_one_lag_are_one_lag(self) -> None:
        """The second adds its ports to the first, as on the device."""
        text = _ONE_LAG.replace("trunk 51-52 trk1 lacp", "trunk 51 trk1 lacp\ntrunk 52,51 TRK1 trunk")
        tree = AOSS.parse(text)
        assert [(lag.name, lag.members, lag.mode) for lag in tree.lags] == [("trk1", ["51", "52"], "active")]
        assert _spellings(collect_port_names(tree), "trk1") == {"trk1"}

    def test_two_stanzas_for_one_interface_are_one_record(self) -> None:
        """``interface trk1`` and ``interface Trk1`` are one interface;
        the second stanza goes on with the first.  Two records of one
        name rendered as the first alone, and the job said two source
        ports shared a target, naming one."""
        text = _ONE_LAG.replace(
            'interface Trk1\n   name "uplink"\n   exit\n',
            'interface trk1\n   name "first"\n   exit\ninterface Trk1\n   name "uplink"\n   disable\n   exit\n',
        )
        tree = AOSS.parse(text)
        (record,) = [iface for iface in tree.interfaces if iface.name == "trk1"]
        assert (record.description, record.enabled) == ("uplink", False)
        job = run_plan_with_overrides(AOSS, AOSS, text, port_rename_map={})
        assert _merged(job) == []

    def test_any_interface_met_twice_is_one_record(self) -> None:
        text = _ONE_LAG.replace(
            "vlan 1\n", 'interface 5\n   name "a"\n   exit\ninterface 5\n   disable\n   exit\nvlan 1\n', 1,
        )
        (record,) = [iface for iface in AOSS.parse(text).interfaces if iface.name == "5"]
        assert (record.description, record.enabled) == ("a", False)

    def test_a_lag_untagged_in_a_later_vlan_leaves_the_earlier_one(self) -> None:
        """A port is untagged in one VLAN: a later ``untagged`` moves
        it.  Under two spellings the LAG stayed untagged in both."""
        text = _ONE_LAG.replace("untagged 1-50", "untagged 1-50,Trk1").replace("tagged TRK1,5", "untagged trk1")
        vlans = {vlan.id: vlan for vlan in AOSS.parse(text).vlans}
        assert "trk1" not in vlans[1].untagged_ports and vlans[20].untagged_ports == ["trk1"]

    def test_two_lines_of_one_stanza_that_name_the_lag_name_it_once(self) -> None:
        text = _ONE_LAG.replace("tagged TRK1,5", "tagged TRK1,5\n   tagged Trk1,6")
        vlans = {vlan.id: vlan for vlan in AOSS.parse(text).vlans}
        assert vlans[20].tagged_ports == ["5", "6", "trk1"]

    def test_a_port_list_is_read_in_the_one_spelling_and_names_a_port_once(self) -> None:
        assert _parse_port_list("Trk1,5,trk1,TRK1,5") == ["trk1", "5"]
        assert _parse_port_list("A1,a1") == ["A1", "a1"]

    def test_a_range_of_lags_is_read_in_the_one_spelling(self) -> None:
        text = _ONE_LAG.replace("tagged TRK1,5", "tagged TRK1-TRK3")
        vlans = {vlan.id: vlan for vlan in AOSS.parse(text).vlans}
        assert vlans[20].tagged_ports == ["trk1", "trk2", "trk3"]


class TestTheRendererWritesTheDevicesForm:
    @pytest.mark.parametrize("held", ["trk1", "Trk1", "TRK1"])
    def test_whatever_spelling_a_tree_holds(self, held: str) -> None:
        """A tree need not have come from this parser."""
        tree = CanonicalIntent.model_validate({
            "interfaces": [{"name": held, "description": "uplink"}],
            "vlans": [{"id": 10, "name": "TEN", "tagged_ports": [held]}],
            "lags": [{"name": held, "members": ["51", "52"], "mode": "active"}],
            "static_routes": [{"destination": "10.1.0.0/16", "gateway": held}],
        })
        rendered = AOSS.render(tree)
        assert "trunk 51-52 trk1 lacp" in rendered
        assert "   tagged Trk1" in rendered and "interface Trk1" in rendered
        assert "ip route 10.1.0.0/16 Trk1" in rendered
        assert held not in rendered or held in {"trk1", "Trk1"}

    @pytest.mark.parametrize("held", ["trk1", "Trk1", "TRK1"])
    def test_a_lag_with_nothing_configured_on_it_keeps_its_stanza(self, held: str) -> None:
        """A stanza with no body is written for a name of this
        platform's own shape and for no other; a trunk's name is one in
        any letter case."""
        tree = CanonicalIntent.model_validate({"interfaces": [{"name": held}, {"name": "ge-0/0/0"}]})
        rendered = AOSS.render(tree)
        assert "interface Trk1" in rendered and "ge-0/0/0" not in rendered

    def test_a_next_hop_that_is_an_address_is_left_as_it_is(self) -> None:
        tree = CanonicalIntent.model_validate({
            "static_routes": [{"destination": "10.1.0.0/16", "gateway": "192.0.2.1"}],
        })
        assert "ip route 10.1.0.0/16 192.0.2.1" in AOSS.render(tree)


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
        assert (
            "port_rename: source port 'Trk1' is another spelling of 'trk1', which has an entry of its own; "
            "entry ignored"
        ) in job.warnings
        assert not [w for w in job.warnings if "does not exist" in w]

    def test_of_two_keys_in_other_cases_the_first_is_taken_and_the_other_said(self) -> None:
        job = run_plan_with_overrides(
            AOSS, AOSS, _ONE_LAG, port_rename_map={"Trk1": "Trk7", "TRK1": "Trk8"},
        )
        assert job.port_renames["trk1"] == "Trk7"
        assert [w for w in job.warnings if "'TRK1' is another spelling of 'trk1'" in w]

    @pytest.mark.parametrize("value", ["Trk7", None])
    def test_two_spellings_that_say_the_same_thing_are_not_remarked_on(self, value) -> None:
        job = run_plan_with_overrides(
            AOSS, AOSS, _ONE_LAG, port_rename_map={"Trk1": value, "trk1": value},
        )
        assert not [w for w in job.warnings if "another spelling" in w or "does not exist" in w]

    @pytest.mark.parametrize("source", ["fortigate_cli", "mikrotik_routeros"])
    def test_where_names_have_case_a_second_spelling_is_a_name_that_does_not_exist(self, source: str) -> None:
        """``DMZ`` beside ``dmz`` is another interface there, and one
        the config does not have: it is not called a spelling of
        anything."""
        tree = CanonicalIntent.model_validate({"vlans": [{"id": 10, "tagged_ports": ["dmz"]}]})
        result = translate_port_names(
            tree, get_codec(source), get_codec(source), rename_map={"DMZ": "x1", "dmz": "x2"},
        )
        assert [w for w in result.warnings if "source port 'DMZ' does not exist" in w]
        assert not [w for w in result.warnings if "another spelling" in w]

    def test_a_key_is_compared_as_typed_apart_from_its_letter_case(self) -> None:
        """Space around a key is not letter case: the key names nothing."""
        job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={" Trk1 ": "Trk7"})
        assert job.port_renames["trk1"] == "Trk1"
        assert [w for w in job.warnings if "source port ' Trk1 ' does not exist" in w]

    def test_a_key_reaches_a_lag_that_has_no_stanza(self) -> None:
        """The one real capture with a trunk defines it and names it
        nowhere else: no ``interface`` record holds the name."""
        text = (
            '; JL260A Configuration Editor; Created on release #WC.16.07.0002\nhostname "sw"\n'
            "trunk 51-52 trk1 lacp\nvlan 1\n   untagged 1-50\n   exit\n"
        )
        tree = AOSS.parse(text)
        assert not [iface for iface in tree.interfaces if iface.name == "trk1"]
        result = translate_port_names(tree, AOSS, AOSS, rename_map={"Trk1": "Trk7"})
        assert [lag.name for lag in tree.lags] == ["Trk7"] and result.applied == {"trk1": "Trk7"}

    def test_a_key_reaches_a_name_that_only_a_vlan_lists(self) -> None:
        tree = CanonicalIntent.model_validate({"vlans": [{"id": 10, "tagged_ports": ["a1"]}]})
        result = translate_port_names(tree, AOSS, AOSS, rename_map={"A1": "1/9"})
        assert tree.vlans[0].tagged_ports == ["1/9"] and result.applied == {"a1": "1/9"}

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
