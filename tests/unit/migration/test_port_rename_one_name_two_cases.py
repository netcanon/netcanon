"""One LAG written in two letter cases is one source name.

AOS-S writes a LAG ``trk1`` where it is defined and ``Trk1`` where a
VLAN lists it.  The port translator keeps both spellings, and its
warning for two source ports that end on one target name once counted
them as two: "multiple source ports map to 'Trk1' (sources: Trk1,
trk1); these are distinct ports ... their VLAN membership will be
merged" -- on every AOS-S config with a LAG, whenever a port map was
in play, with nothing merged at all.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.canonical.port_names import translate_port_names
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.unit

AOSS = get_codec("aruba_aoss")

_ONE_LAG = """; JL260A Configuration Editor; Created on release #WC.16.07.0002
hostname "sw"
trunk 51-52 trk1 lacp
vlan 1
   name "DEFAULT_VLAN"
   untagged 1-50
   tagged Trk1
   exit
"""


def _merged(job) -> list[str]:
    return [w for w in job.warnings if "multiple source ports map to" in w]


@pytest.mark.parametrize("target", ["aruba_aoss", "juniper_junos", "cisco_iosxe_cli", "arista_eos"])
def test_one_lag_in_two_cases_is_not_two_ports_merged(target: str) -> None:
    """With the browser's empty port map, which is enough to run the
    translator: no line says two ports were merged."""
    job = run_plan_with_overrides(AOSS, get_codec(target), _ONE_LAG, port_rename_map={})
    assert _merged(job) == []


def test_two_ports_on_one_name_are_still_said() -> None:
    """The warning itself is untouched: two ports an operator sends
    to one name are two ports."""
    job = run_plan_with_overrides(AOSS, AOSS, _ONE_LAG, port_rename_map={"1": "2"})
    (line,) = _merged(job)
    assert "(sources: 1, 2)" in line and "Trk" not in line


@pytest.mark.parametrize(
    ("source", "merged"),
    [("fortigate_cli", True), ("mikrotik_routeros", True), ("aruba_aoss", False), ("cisco_iosxe_cli", False)],
)
def test_two_cases_are_two_names_only_where_the_platform_has_case(source: str, merged: bool) -> None:
    """Two names that differ only in letter case, known from a VLAN's
    list alone and sent to one target.  On FortiOS and RouterOS, where
    an operator chooses interface names, ``DMZ`` is not ``dmz``: two
    sources, and the line says so.  Where names have no case it is one
    name written twice."""
    tree = CanonicalIntent.model_validate({"vlans": [{"id": 10, "tagged_ports": ["DMZ", "dmz"]}]})
    result = translate_port_names(
        tree, get_codec(source), AOSS, rename_map={"DMZ": "1/9", "dmz": "1/9"},
    )
    lines = [w for w in result.warnings if "multiple source ports map to" in w]
    assert bool(lines) is merged
    if merged:
        assert "(sources: DMZ, dmz)" in lines[0]
