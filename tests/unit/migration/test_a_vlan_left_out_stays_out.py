"""A VLAN a trunk leaves out is not on that trunk in the output.

`switchport trunk allowed vlan 1-99,101-4094` says one thing about VLAN
100: not here.  The Junos renderer wrote any list of 4,000 ids or more
as `vlan members all`, which is every VLAN the switch has, and the job
said `completed` with nothing to report; `2-4094` was "all" to the
shared projection as well, which stamped the trunk onto a declared
VLAN 1 for every VLAN-centric target.  A target's word for "everything"
is right for a list that is everything and for no other.

Every public codec is a target here, and the OUTPUT is read three ways.
With the target's own parser: a port carries a VLAN if the id is in the
port's list, or the port is among the VLAN's ports -- and "not carried"
passes for a target that carries nothing, so the targets that do write
a trunk's VLANs are listed and each has to carry the VLANs the list
does hold.  As a whole list, where the target's parser reads a trunk's
list: the declared VLANs are a handful of ids, and a renderer that
loses or adds thousands of the others would pass a check that looks
at those alone.  And as text, for the word itself: a parser that reads
its own word for "all" as an empty list (AOS-CX does) would hide it
from the first two.

One neighbour of this is NOT mended and is pinned at the foot of the
module: a trunk that allows no VLAN at all.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_overrides

pytestmark = pytest.mark.unit

_VLANS = (("10", "users"), ("100", "secure"), ("999", "mgmt"))


def _iosxe(allowed: str, declare_vlan_1: bool) -> str:
    vlans = (("1", "default"), *_VLANS) if declare_vlan_1 else _VLANS
    return "\n".join([
        "hostname sw1", "!",
        *(line for vid, name in vlans for line in (f"vlan {vid}", f" name {name}", "!")),
        "interface GigabitEthernet1/0/1", " switchport mode trunk",
        f" switchport trunk allowed vlan {allowed}", "!",
        "interface GigabitEthernet1/0/2", " switchport mode access", " switchport access vlan 10", "!",
        "end", "",
    ])


def _eos(allowed: str, declare_vlan_1: bool) -> str:
    vlans = (("1", "default"), *_VLANS) if declare_vlan_1 else _VLANS
    return "\n".join([
        "hostname sw1", "!",
        *(line for vid, name in vlans for line in (f"vlan {vid}", f"   name {name}", "!")),
        "interface Ethernet1", "   switchport mode trunk",
        f"   switchport trunk allowed vlan {allowed}", "!",
        "interface Ethernet2", "   switchport access vlan 10", "!",
        "end", "",
    ])


SOURCES = {"cisco_iosxe_cli": _iosxe, "arista_eos": _eos}

#: (what the trunk allows, the declared VLAN that leaves out).  The
#: last holds every VLAN the config declares and is still not every
#: VLAN: "all this config has" is the next rule a renderer would reach
#: for, and a VLAN made later is not on such a trunk.
LISTS = [
    ("1-99,101-4094", 100),
    ("2-99,101-4094", 100),
    ("1-99,101-4000", 100),
    ("1-99,101-3999", 100),
    ("2-4094", 1),
    ("10,999", 100),
    ("1-4000", None),
]

#: Targets whose output says which VLANs a trunk carries.  The rest
#: (routers, firewalls, the NETCONF stub) carry none, for any list.
WRITES_A_TRUNKS_VLANS = frozenset({
    "arista_eos", "aruba_aoscx", "aruba_aoss", "cisco_iosxe_cli", "cisco_nxos",
    "dell_os10", "juniper_junos",
})


def _ports_in(parsed, vid: int) -> set[str]:
    """The ports the tree puts in VLAN *vid*, by either record."""
    names = {
        iface.name for iface in parsed.interfaces
        if vid in (iface.trunk_allowed_vlans or [])
        or vid in (iface.access_vlan, iface.trunk_native_vlan)
    }
    for vlan in parsed.vlans:
        if vlan.id == vid:
            names.update(vlan.tagged_ports or [])
            names.update(vlan.untagged_ports or [])
    return names


#: Targets whose parser reads a trunk's list back as a list.  (AOS-S
#: writes a trunk as the VLANs that tag the port: declared ones only.)
READS_A_TRUNKS_LIST = WRITES_A_TRUNKS_VLANS - {"aruba_aoss"}

#: The targets' words for every VLAN, as they stand in an output.
_WORDS_FOR_EVERYTHING = ("vlan members all", "allowed vlan all", "vlan trunk allowed all")


def _ids(allowed: str) -> set[int]:
    ids: set[int] = set()
    for part in allowed.split(","):
        low, _, high = part.partition("-")
        ids.update(range(int(low), int(high or low) + 1))
    return ids


def _job(source: str, target: str, allowed: str, declare_vlan_1: bool = False):
    job = run_plan_with_overrides(
        get_codec(source), get_codec(target), SOURCES[source](allowed, declare_vlan_1),
        port_rename_map={}, force=True,
    )
    assert job.rendered, f"{source} to {target}: nothing rendered ({job.status})"
    return job


def _read_back(source: str, target: str, allowed: str, declare_vlan_1: bool = False):
    return get_codec(target).parse(_job(source, target, allowed, declare_vlan_1).rendered)


def _the_trunks_list(parsed) -> set[int]:
    trunks = [iface for iface in parsed.interfaces if iface.switchport_mode == "trunk"]
    assert len(trunks) == 1, [iface.name for iface in trunks]
    return set(trunks[0].trunk_allowed_vlans or [])


@pytest.mark.parametrize("target", list_public_codecs())
@pytest.mark.parametrize("allowed,left_out", LISTS)
@pytest.mark.parametrize("source", sorted(SOURCES))
def test_the_vlan_left_out_is_on_no_port(
    source: str, allowed: str, left_out: int | None, target: str,
) -> None:
    job = _job(source, target, allowed, declare_vlan_1=left_out == 1)
    parsed = get_codec(target).parse(job.rendered)
    for word in _WORDS_FOR_EVERYTHING:
        assert word not in job.rendered, f"{source} to {target}: {allowed} is written {word!r}"
    if target in READS_A_TRUNKS_LIST:
        # Every id, not only the declared ones.
        assert _the_trunks_list(parsed) == _ids(allowed), (source, target, allowed)
    assert left_out is None or not _ports_in(parsed, left_out), (
        f"{source} to {target}: the trunk allows {allowed}, and VLAN {left_out} "
        f"is on {sorted(_ports_in(parsed, left_out))} in the output"
    )
    if target in WRITES_A_TRUNKS_VLANS:
        # The VLANs the list holds are still there: on the trunk and,
        # for 10, on the access port beside it.
        assert len(_ports_in(parsed, 999)) == 1, (source, target, allowed)
        assert len(_ports_in(parsed, 10)) == 2, (source, target, allowed)


@pytest.mark.parametrize("target", list_public_codecs())
@pytest.mark.parametrize("source", sorted(SOURCES))
def test_a_trunk_of_every_vlan_carries_each_one_declared(source: str, target: str) -> None:
    """The other way round: `all` is still all."""
    parsed = _read_back(source, target, "1-4094", declare_vlan_1=True)
    if target in WRITES_A_TRUNKS_VLANS:
        for vid in (1, 10, 100, 999):
            assert _ports_in(parsed, vid), (source, target, vid)
    if target in READS_A_TRUNKS_LIST:
        assert _the_trunks_list(parsed) == _ids("1-4094"), (source, target)


def test_the_targets_listed_are_the_ones_that_write_a_trunks_vlans() -> None:
    """Measured, so that a codec which starts to write them is not left
    out of the half of the check that can see a VLAN dropped."""
    writes = {
        target for target in list_public_codecs()
        if _ports_in(_read_back("cisco_iosxe_cli", target, "10,999"), 999)
    }
    assert writes == WRITES_A_TRUNKS_VLANS


# ---------------------------------------------------------------------------
# Not mended: a trunk that allows nothing
# ---------------------------------------------------------------------------

#: Targets on which a trunk with no allowed line carries every VLAN: the
#: platform's default for a trunk (Cisco and Arista say so of their own).
_NO_LIST_IS_EVERY_VLAN = frozenset({"arista_eos", "cisco_iosxe_cli", "cisco_nxos"})

#: Targets that write a trunk which allows NO VLAN as a trunk of every
#: VLAN.  A defect, known and open: the tree holds one value, an empty
#: list, for "none", for "nothing stated" and for AOS-CX's own `all`,
#: and each renderer picks a reading.  Pinned so that it is not
#: forgotten, does not spread to another target unseen, and has to be
#: taken out of here by the change that mends it.
WRITES_NOTHING_AS_EVERYTHING = frozenset({
    "arista_eos", "aruba_aoscx", "cisco_iosxe_cli", "cisco_nxos",
})


def _allows_everything(target: str, rendered: str) -> bool:
    if any(word in rendered for word in _WORDS_FOR_EVERYTHING):
        return True
    return (
        target in _NO_LIST_IS_EVERY_VLAN
        and "switchport mode trunk" in rendered
        and "switchport trunk allowed vlan" not in rendered
    )


def test_a_trunk_that_allows_nothing_and_what_each_target_makes_of_it() -> None:
    """`switchport trunk allowed vlan none` parks a trunk.  On four
    targets it comes out carrying everything, in a job that says
    `completed`; on the rest it carries nothing, as it should."""
    measured = set()
    for target in list_public_codecs():
        job = _job("cisco_iosxe_cli", target, "none")
        if _allows_everything(target, job.rendered):
            measured.add(target)
        elif target in WRITES_A_TRUNKS_VLANS:
            parsed = get_codec(target).parse(job.rendered)
            assert not _ports_in(parsed, 999), target
            assert not _ports_in(parsed, 100), target
    assert measured == WRITES_NOTHING_AS_EVERYTHING
