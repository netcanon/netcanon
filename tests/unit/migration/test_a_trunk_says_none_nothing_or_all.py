"""A trunk that says none, nothing, or all carries that on every target.

The canonical tree had ONE value, an empty list, for three statements:
a trunk that allows no VLAN, a trunk that states no list, and AOS-CX's
own `all`.  Each renderer picked a reading for all three, and
`switchport trunk allowed vlan none` came out as a trunk of every VLAN
on four targets, in a job that said `completed`.  A list now means what
it says -- empty is none, every id is every VLAN -- and the parser,
which knows its platform, resolves "nothing stated" from one table.

Every public codec is a target here.  The sources say each statement in
their OWN grammar, and what each means is written out here by hand
(`NOTHING_MEANS`, `_means`): it is not taken from the table the parsers
read, which is compared with it in a test of its own.  The OUTPUT is
read two ways, and neither asks the code under test what a default is:

* as TEXT, by a reader written here for each target's grammar.  The
  target's own parser was blind to this defect: it read its own "no
  allowed line", and AOS-CX its own `all`, as the same empty list the
  source had, so a check that only parsed the output passed every wrong
  cell;
* with the target's parser, as ports in VLANs.

Two things about WHO states a list follow from that, and have a
section each.  A stanza met twice is one interface: what it states is
kept by its name, not resolved a stanza.  And the platform's list is
given to a port that SAYS it is a trunk, not to one a parser took for
a trunk from a trunk line with no mode line.

Four gaps are known and NOT closed by the code under test.  Each is a
named set that is compared for equality with what is measured, so the
change that closes one fails here until its pin is taken out:
`CANNOT_BE_TOLD_ALL` (OS10 has no word for every VLAN),
`AOSS_WRITES_NO_PORT_OF` (AOS-S has no name for some sources' ports),
`TAKES_A_TRUNK_LINE_FOR_A_TRUNK` (two parsers infer a trunk) and
`THE_ADD_IS_LOST_ON` (a second stanza with no mode line is a record
with no mode).  A fifth is pinned by a test of its own: `none` on a
port that is not a trunk is dropped.

At the foot: a public codec whose parser can make a trunk is in the
table or is named, with its reason, among those that have no allowed
list -- so the next codec cannot join without saying which.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent, CanonicalInterface, CanonicalVlan
from netcanon.migration.canonical.transforms import is_every_vlan
from netcanon.migration.codecs._helpers import (
    TRUNK_ALL,
    TRUNK_NONE,
    TRUNK_SOME,
    TRUNK_THAT_STATES_NO_LIST,
    VLAN_IDS,
    TrunksByName,
    merge_trunk_allowed,
    switchport_trunk_allowed_value,
    trunk_list_says,
    unstated_trunk_list,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.services.migration_pipeline import run_plan_with_overrides
from tests.unit.migration.test_a_vlan_left_out_stays_out import WRITES_A_TRUNKS_VLANS

pytestmark = pytest.mark.unit

NONE, ALL = "none", "all"
DECLARED = (10, 100, 999)
EVERY_ID = set(range(1, 4095))

# ---------------------------------------------------------------------------
# Sources: one trunk, one access port in VLAN 10, three declared VLANs
# ---------------------------------------------------------------------------


def _iosxe(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "!",
        "vlan 10", " name users", "!", "vlan 100", " name secure", "!", "vlan 999", " name mgmt", "!",
        "interface GigabitEthernet1/0/1", " switchport mode trunk", *(f" {line}" for line in trunk), "!",
        "interface GigabitEthernet1/0/2", " switchport mode access", " switchport access vlan 10", "!",
        "end", "",
    ])


def _eos(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "!",
        "vlan 10", "   name users", "!", "vlan 100", "   name secure", "!", "vlan 999", "   name mgmt", "!",
        "interface Ethernet1", "   switchport mode trunk", *(f"   {line}" for line in trunk), "!",
        "interface Ethernet2", "   switchport access vlan 10", "!",
        "end", "",
    ])


def _nxos(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "",
        "vlan 10", "  name users", "vlan 100", "  name secure", "vlan 999", "  name mgmt", "",
        "interface Ethernet1/1", "  switchport mode trunk", *(f"  {line}" for line in trunk), "",
        "interface Ethernet1/2", "  switchport access vlan 10", "",
    ])


def _os10(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1", "!",
        "interface vlan10", " description users", " no shutdown", "!",
        "interface vlan100", " description secure", " no shutdown", "!",
        "interface vlan999", " description mgmt", " no shutdown", "!",
        "interface ethernet1/1/1", " no shutdown", " switchport mode trunk", *(f" {line}" for line in trunk), "!",
        "interface ethernet1/1/2", " no shutdown", " switchport access vlan 10", "!",
        "",
    ])


def _aoscx(*trunk: str) -> str:
    return "\n".join([
        "hostname sw1",
        "vlan 10", "    name users", "vlan 100", "    name secure", "vlan 999", "    name mgmt",
        "interface 1/1/1", "    no shutdown", "    no routing", *(f"    {line}" for line in trunk),
        "interface 1/1/2", "    no shutdown", "    no routing", "    vlan access 10",
        "",
    ])


def _junos(*trunk: str) -> str:
    return "\n".join([
        "set system host-name sw1",
        "set vlans users vlan-id 10", "set vlans secure vlan-id 100", "set vlans mgmt vlan-id 999",
        "set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk",
        *(f"set interfaces ge-0/0/1 {line}" for line in trunk),
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching interface-mode access",
        "set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members users",
        "",
    ])


_ALLOWED = "switchport trunk allowed vlan"
_NATIVE = "switchport trunk native vlan 999"

#: The statements the three platforms with the Cisco list grammar can
#: make: what follows `switchport mode trunk`, and what it means.
_CISCO_STATEMENTS: dict[str, tuple[str, ...]] = {
    "none": (f"{_ALLOWED} none",),
    "none, native 999": (_NATIVE, f"{_ALLOWED} none"),
    "a remove that empties": (f"{_ALLOWED} 100", f"{_ALLOWED} remove 100"),
    "except every id": (f"{_ALLOWED} except 1-4094",),
    "nothing": (),
    "native 999 only": (_NATIVE,),
    "add on the first line": (f"{_ALLOWED} add 100",),
    "all": (f"{_ALLOWED} all",),
}

#: (source codec, what the trunk says) -> the text, in that codec's
#: own grammar.
SOURCES: dict[tuple[str, str], str] = {
    **{
        (codec, says): write(*lines)
        for codec, write in (("cisco_iosxe_cli", _iosxe), ("arista_eos", _eos), ("cisco_nxos", _nxos))
        for says, lines in _CISCO_STATEMENTS.items()
    },
    # OS10 has no way to say every VLAN: no word, ids that end at 4093,
    # and a VLAN has to exist before it is listed.  Its native VLAN is
    # the access VLAN of a trunk.
    ("dell_os10", "nothing"): _os10(),
    ("dell_os10", "native 999 only"): _os10("switchport access vlan 999"),
    # AOS-CX has no way to say no VLAN.  A trunk there is a native line,
    # an allowed line, or both; the native line alone is "nothing".
    ("aruba_aoscx", "nothing"): _aoscx("vlan trunk native 1"),
    ("aruba_aoscx", "native 999 only"): _aoscx("vlan trunk native 999"),
    ("aruba_aoscx", "all"): _aoscx("vlan trunk native 1", "vlan trunk allowed all"),
    ("juniper_junos", "nothing"): _junos(),
    ("juniper_junos", "native 999 only"): _junos("native-vlan-id 999"),
    ("juniper_junos", "all"): _junos("unit 0 family ethernet-switching vlan members all"),
}

#: What a trunk that states NO allowed list carries on each platform.
#: Written here by hand from the vendors' own pages (the sentences and
#: their sources are in
#: docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md):
#: every VLAN on IOS-XE, EOS and NX-OS; every VLAN on AOS-CX, where
#: the switch adds `vlan trunk allowed all` itself; no tagged VLAN on
#: OS10; no VLAN on Junos.
NOTHING_MEANS = {
    "cisco_iosxe_cli": ALL,
    "arista_eos": ALL,
    "cisco_nxos": ALL,
    "aruba_aoscx": ALL,
    "dell_os10": NONE,
    "juniper_junos": NONE,
}

#: What each statement means that is not the platform's "nothing".
_STATED = {
    "none": NONE, "none, native 999": NONE, "a remove that empties": NONE, "except every id": NONE, "all": ALL,
}


def _means(source: str, says: str) -> str:
    """NONE or ALL.  A native VLAN alone, and `add` on a stanza's first
    allowed line, both leave the list at what the platform's trunk
    carries when it states none (`add` adds to that list)."""
    return _STATED.get(says) or NOTHING_MEANS[source]


def _native(says: str) -> int | None:
    return 999 if "native 999" in says else None


# ``WRITES_A_TRUNKS_VLANS``: the targets whose output says which VLANs a
# trunk carries.  The rest (routers, firewalls, the NETCONF stub) write
# none, for any list.  The set is the one of the module it is imported
# from, which measures it: a codec that starts to write a trunk's VLANs
# fails there until it is listed, and fails here until it has a reader
# (`_says_in_text`).

#: KNOWN GAP, pinned.  Targets that cannot be told "every VLAN" and do
#: not yet write the nearest thing they have.  OS10 has no word for
#: it, its ids end at 4093, and a VLAN must exist before a port is put
#: in it; the renderer writes `1-4094` under a review line that says
#: so (`test_os10_says_so_beside_every_vlan`).  The change that makes
#: OS10 write the VLANs it declares takes it out of here.
CANNOT_BE_TOLD_ALL = frozenset({"dell_os10"})

#: What the text reader below gives for the form that gap takes.
_IDS_OS10_HAS_NOT = "ids OS10 does not have"

#: KNOWN GAP, pinned, and not this module's subject.  AOS-S has no
#: name for a port of these sources (`Ethernet1/1`, `1/1/1`,
#: `ethernet1/1/1`): the name is left as it was, and the AOS-S renderer
#: then writes NO membership for the port, tagged or untagged, in a job
#: that warns about the name and says `completed`.  Measured below, so
#: that these cells are not skipped in silence; the change that mends
#: it takes the sources out of here.
AOSS_WRITES_NO_PORT_OF = frozenset({"aruba_aoscx", "cisco_nxos", "dell_os10"})

# ---------------------------------------------------------------------------
# The output, read as TEXT: one reader for each target grammar
# ---------------------------------------------------------------------------

#: Targets on which a trunk with no allowed line carries every VLAN.
_NO_LINE_IS_EVERY_VLAN = frozenset({"arista_eos", "cisco_iosxe_cli", "cisco_nxos"})

_IDS_SPELLED_OUT = "every id spelled out"
_THE_WORD_ALL = "the word all on a trunk"
_SOME = "some"


def _ids(text: str) -> set[int]:
    ids: set[int] = set()
    for part in text.replace(" ", "").split(","):
        low, _, high = part.partition("-")
        if low.isdigit() and (high.isdigit() or not high):
            ids.update(range(int(low), int(high or low) + 1))
    return ids


def _stanzas(rendered: str) -> list[list[str]]:
    """`interface ...` stanzas: the header and its indented lines."""
    out: list[list[str]] = []
    for line in rendered.splitlines():
        if line.startswith("interface "):
            out.append([line])
        elif out and line[:1] in (" ", "\t"):
            out[-1].append(line.strip())
        elif out and line.strip():
            out.append([])            # a column-0 line closes the stanza
    return [stanza for stanza in out if stanza]


def _the_trunk(target: str, rendered: str) -> list[str]:
    trunks = [stanza for stanza in _stanzas(rendered) if "switchport mode trunk" in stanza]
    assert len(trunks) == 1, f"{target}: {len(trunks)} trunk stanzas"
    return trunks[0]


def _switchport_text(target: str, rendered: str, declared: tuple[int, ...] = DECLARED) -> str:
    """IOS-XE, EOS, NX-OS and OS10: the `switchport trunk allowed vlan`
    line of the one trunk stanza, or the lack of one."""
    return _switchport_says(target, _the_trunk(target, rendered), declared)


def _switchport_says(target: str, stanza: list[str], declared: tuple[int, ...] = DECLARED) -> str:
    """The same, of one trunk stanza."""
    allowed = [line for line in stanza if line.startswith(_ALLOWED + " ")]
    if not allowed:
        return ALL if target in _NO_LINE_IS_EVERY_VLAN else NONE
    assert len(allowed) == 1, allowed
    value = allowed[0].removeprefix(_ALLOWED + " ").strip()
    if value == "none":
        return NONE
    if target == "dell_os10":
        # No word for every VLAN and no id past 4093.  The nearest OS10
        # has is the VLANs the output declares.
        if value == "all" or max(_ids(value), default=0) > 4093:
            return _IDS_OS10_HAS_NOT
        return ALL if _ids(value) >= set(declared) else _SOME
    if value == "all":
        # Grammar, but not what the device prints, and not what makes a
        # trunk that stated no list come back as it went.
        return _THE_WORD_ALL
    if _ids(value) == EVERY_ID:
        # 19,000 characters on IOS-XE and EOS, and ids NX-OS keeps for
        # itself: every VLAN is the trunk with no allowed line.
        return _IDS_SPELLED_OUT
    return _SOME


def _aoscx_text(rendered: str) -> str:
    """AOS-CX: the `vlan trunk` lines of the one L2 port that is not
    an access port."""
    l2 = _aoscx_trunks(rendered)
    assert len(l2) == 1, f"aruba_aoscx: {len(l2)} L2 stanzas that are not access ports"
    return _aoscx_says(l2[0])


def _aoscx_trunks(rendered: str) -> list[list[str]]:
    return [
        stanza for stanza in _stanzas(rendered)
        if "no routing" in stanza and not any(line.startswith("vlan access") for line in stanza)
    ]


def _aoscx_says(stanza: list[str]) -> str:
    """The same, of one such stanza."""
    allowed = [line for line in stanza if line.startswith("vlan trunk allowed ")]
    native = [line for line in stanza if line.startswith("vlan trunk native ")]
    if not allowed:
        # A native line alone makes the switch run `vlan trunk allowed
        # all` itself.  Neither line is no trunk at all.
        return ALL if native else NONE
    assert len(allowed) == 1, allowed
    value = allowed[0].removeprefix("vlan trunk allowed ").strip()
    if value == "all":
        return ALL
    if _ids(value) == EVERY_ID:
        return _IDS_SPELLED_OUT       # its word is `all`, and reads back otherwise
    return _SOME


def _junos_text(rendered: str) -> str:
    # (A set: two records of one interface write its mode line twice,
    # and it is one trunk.)
    trunk = sorted(set(re.findall(
        r"^set interfaces (\S+) unit 0 family ethernet-switching interface-mode trunk$", rendered, re.M,
    )))
    assert len(trunk) == 1, f"juniper_junos: {len(trunk)} trunks"
    members = re.findall(
        rf"^set interfaces {re.escape(trunk[0])} unit 0 family ethernet-switching vlan members (\S+)$",
        rendered, re.M,
    )
    if not members:
        return NONE
    return ALL if members == ["all"] else _SOME


def _aoss_text(rendered: str, native: int | None, declared: tuple[int, ...] = DECLARED) -> str:
    """AOS-S says it VLAN by VLAN: the port is tagged in each VLAN the
    output declares (but its own untagged one), or in none."""
    tagged_in: set[int] = set()
    vid = None
    for line in rendered.splitlines():
        stanza = re.match(r"^vlan (\d+)\s*$", line)
        if stanza:
            vid = int(stanza.group(1))
        elif line.strip() == "exit":
            vid = None
        elif vid is not None and line.strip().startswith("tagged "):
            tagged_in.add(vid)
    if not tagged_in:
        return NONE
    return ALL if tagged_in >= set(declared) - {native} else _SOME


def _says_in_text(
    target: str, rendered: str, native: int | None = None, declared: tuple[int, ...] = DECLARED,
) -> str:
    """What the TEXT of an output with one trunk says the trunk
    carries: NONE, ALL, or the name of another form.  *declared* is
    the VLANs the output declares, for the two targets whose nearest
    thing to "every VLAN" is those."""
    if target in ("arista_eos", "cisco_iosxe_cli", "cisco_nxos", "dell_os10"):
        return _switchport_text(target, rendered, declared)
    if target == "aruba_aoscx":
        return _aoscx_text(rendered)
    if target == "juniper_junos":
        return _junos_text(rendered)
    assert target == "aruba_aoss", target
    return _aoss_text(rendered, native, declared)


# ---------------------------------------------------------------------------
# The output, read with the target's parser
# ---------------------------------------------------------------------------


def _ports_in(parsed, vid: int) -> set[str]:
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


def _job(source: str, says: str, target: str):
    job = run_plan_with_overrides(
        get_codec(source), get_codec(target), SOURCES[(source, says)], port_rename_map={}, force=True,
    )
    assert job.rendered, f"{source} ({says}) to {target}: nothing rendered ({job.status})"
    return job


_WORDS_FOR_EVERYTHING = ("vlan members all", "allowed vlan all", "vlan trunk allowed all", "allowed vlan 1-4094")


@pytest.mark.parametrize("target", list_public_codecs())
@pytest.mark.parametrize("source,says", sorted(SOURCES))
def test_the_output_says_what_the_source_did(source: str, says: str, target: str) -> None:
    means = _means(source, says)
    job = _job(source, says, target)
    if target not in WRITES_A_TRUNKS_VLANS:
        # A router, a firewall, the NETCONF stub: no trunk VLANs for any list.
        for word in _WORDS_FOR_EVERYTHING:
            assert word not in job.rendered, (source, says, target, word)
        return
    if target == "aruba_aoss" and source in AOSS_WRITES_NO_PORT_OF:
        return                      # the pinned gap above; see its own test
    # 1. As text.
    said = _says_in_text(target, job.rendered, _native(says))
    if target in CANNOT_BE_TOLD_ALL and means == ALL:
        assert said == _IDS_OS10_HAS_NOT, (source, says, target, said)   # pinned; see its own test
    else:
        assert said == means, (
            f"{source} says {says!r} (which is {means}); the {target} output says {said}"
        )
    # 2. With the target's parser: VLANs 100 and 999 are on the trunk
    # alone, or on no port.  (Where 999 is the source's native VLAN it
    # is left out: what a native VLAN outside the list does differs by
    # platform, and is not this module's question.)
    parsed = get_codec(target).parse(job.rendered)
    for vid in ((100,) if _native(says) else (100, 999)):
        ports = _ports_in(parsed, vid)
        if means == NONE:
            assert not ports, f"{source} ({says}) to {target}: VLAN {vid} is on {sorted(ports)}"
        else:
            assert len(ports) == 1, f"{source} ({says}) to {target}: VLAN {vid} is on {sorted(ports)}"


def test_each_source_parses_as_it_is_meant() -> None:
    """One trunk and one access port on its own parser, and the trunk's
    list is empty or every id as the statement means."""
    for (source, says), text in SOURCES.items():
        parsed = get_codec(source).parse(text)
        modes = sorted(iface.switchport_mode for iface in parsed.interfaces if iface.switchport_mode)
        assert modes == ["access", "trunk"], (source, says, modes)
        # (AOS-CX: `vlan trunk native 1` makes VLAN 1 a VLAN of the tree too.)
        assert set(DECLARED) <= {vlan.id for vlan in parsed.vlans} <= {1, *DECLARED}, (source, says)
        trunk = next(iface for iface in parsed.interfaces if iface.switchport_mode == "trunk")
        listed = set(trunk.trunk_allowed_vlans)
        assert listed == (EVERY_ID if _means(source, says) == ALL else set()), (source, says, len(listed))
        assert trunk.trunk_native_vlan == (1 if "native 1" in text else _native(says)), (source, says)


def test_the_statements_reach_both_meanings() -> None:
    """Every source codec is among the statements, and the two meanings
    are each reached from a platform whose "nothing" is the other."""
    assert {source for source, _ in SOURCES} == set(NOTHING_MEANS)
    reached = {(NOTHING_MEANS[source], _means(source, says)) for source, says in SOURCES}
    assert (ALL, NONE) in reached and (ALL, ALL) in reached and (NONE, NONE) in reached and (NONE, ALL) in reached


_OWN_WORDS = {
    "cisco_iosxe_cli": _ALLOWED, "arista_eos": _ALLOWED, "cisco_nxos": _ALLOWED, "dell_os10": _ALLOWED,
    "aruba_aoscx": "vlan trunk allowed", "juniper_junos": "vlan members",
}


@pytest.mark.parametrize("source,says", sorted(SOURCES))
def test_the_same_vendor_text_is_as_stated(source: str, says: str) -> None:
    """A trunk that states no list comes back stating none (the device
    prints no line for its default), and `none` comes back as `none`."""
    job = _job(source, says, source)
    lines = [line.strip() for line in job.rendered.splitlines() if _OWN_WORDS[source] in line]
    # (Junos: the access port's own `vlan members users` is not the trunk's.)
    lines = [line for line in lines if not line.endswith("vlan members users")]
    means = _means(source, says)
    if source == "aruba_aoscx":
        # The one platform here that prints its default: a native line
        # alone is shown by the switch with `vlan trunk allowed all`.
        assert lines == ["vlan trunk allowed all"], (source, says, lines)
    elif means == NOTHING_MEANS[source]:
        assert lines == [], f"{source} ({says}): a trunk of its platform's own list came back with {lines}"
    elif means == NONE:
        assert lines == [f"{_ALLOWED} none"], (source, says, lines)
    else:
        assert source == "juniper_junos" and len(lines) == 1 and lines[0].endswith(" vlan members all"), (
            source, says, lines,
        )


def test_the_table_is_the_one_written_here() -> None:
    """Two places, on purpose: a correction to a platform's default is
    made in the code's table AND here, with the vendor's sentence."""
    assert TRUNK_THAT_STATES_NO_LIST == NOTHING_MEANS


# ---------------------------------------------------------------------------
# The two known gaps, measured
# ---------------------------------------------------------------------------


def test_what_is_not_told_all_is_as_pinned() -> None:
    measured = set()
    for target in sorted(WRITES_A_TRUNKS_VLANS):
        for source, says in sorted(SOURCES):
            if _means(source, says) != ALL or (target == "aruba_aoss" and source in AOSS_WRITES_NO_PORT_OF):
                continue
            if _says_in_text(target, _job(source, says, target).rendered, _native(says)) != ALL:
                measured.add(target)
    assert measured == CANNOT_BE_TOLD_ALL


def test_the_aoss_port_name_gap_is_as_pinned() -> None:
    measured = set()
    for source in sorted({source for source, _ in SOURCES}):
        # Every source has an access port in VLAN 10: `untagged <port>` at the least.
        if "tagged " not in _job(source, "nothing", "aruba_aoss").rendered:    # matches `untagged ` as well
            measured.add(source)
    assert measured == AOSS_WRITES_NO_PORT_OF


# ---------------------------------------------------------------------------
# Where a target cannot say it, the output says so
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source,says", sorted(key for key in SOURCES if _means(*key) == ALL))
def test_os10_says_so_beside_every_vlan(source: str, says: str) -> None:
    """OS10 cannot be told "every VLAN".  The range it is given is
    written under a line that tells the operator why it will not do."""
    trunk = _the_trunk("dell_os10", _job(source, says, "dell_os10").rendered)
    at = trunk.index(f"{_ALLOWED} 1-4094")
    review = trunk[at - 1]
    assert review.startswith("! review: "), trunk
    for words in ("allows every VLAN", "no word", "4093", "must exist"):
        assert words in review, (words, review)


@pytest.mark.parametrize("source,says", sorted(key for key in SOURCES if _means(*key) == NONE))
def test_os10_says_nothing_of_the_rest(source: str, says: str) -> None:
    assert "review" not in "\n".join(_the_trunk("dell_os10", _job(source, says, "dell_os10").rendered))


@pytest.mark.parametrize("source,says", sorted(key for key in SOURCES if _means(*key) == NONE))
def test_aoscx_says_so_for_no_vlan(source: str, says: str) -> None:
    """AOS-CX has no form for a trunk that allows no VLAN: a native line
    alone is every VLAN there.  Neither `vlan trunk` line is written,
    and a line in the stanza says what the source said."""
    rendered = _job(source, says, "aruba_aoscx").rendered
    stanza = next(
        stanza for stanza in _stanzas(rendered)
        if "no routing" in stanza and not any(line.startswith("vlan access") for line in stanza)
    )
    assert not [line for line in stanza if line.startswith("vlan trunk")], stanza
    review = [line for line in stanza if line.startswith("! review: ")]
    assert len(review) == 1, stanza
    assert "the source trunk allows no VLAN" in review[0] and "AOS-CX has no form" in review[0], review
    assert ("(native VLAN 999)" in review[0]) is (_native(says) == 999), review
    # Indented, so that it is a line of the stanza and not the end of it.
    written = next(line for line in rendered.splitlines() if "! review: the source trunk" in line)
    assert written.startswith("    !"), written


def test_aoscx_says_nothing_of_the_rest() -> None:
    for source, says in sorted(SOURCES):
        if _means(source, says) == ALL:
            assert "review: the source trunk" not in _job(source, says, "aruba_aoscx").rendered, (source, says)


# ---------------------------------------------------------------------------
# The readers are handed each form, and have to tell them apart
# ---------------------------------------------------------------------------

_SPELLED = ",".join(str(vid) for vid in range(1, 4095))


def _stanza(*lines: str) -> str:
    return "\n".join(["interface X", *(f" {line}" for line in lines), "!", ""])


@pytest.mark.parametrize("target,rendered,says", [
    ("cisco_iosxe_cli", _stanza("switchport mode trunk"), ALL),
    ("cisco_iosxe_cli", _stanza("switchport mode trunk", _NATIVE), ALL),
    ("cisco_iosxe_cli", _stanza("switchport mode trunk", f"{_ALLOWED} none"), NONE),
    ("cisco_iosxe_cli", _stanza("switchport mode trunk", f"{_ALLOWED} {_SPELLED}"), _IDS_SPELLED_OUT),
    ("cisco_nxos", _stanza("switchport mode trunk", f"{_ALLOWED} 1-4094"), _IDS_SPELLED_OUT),
    ("arista_eos", _stanza("switchport mode trunk", f"{_ALLOWED} all"), _THE_WORD_ALL),
    ("arista_eos", _stanza("switchport mode trunk", f"{_ALLOWED} 10,999"), _SOME),
    ("dell_os10", _stanza("switchport mode trunk"), NONE),
    ("dell_os10", _stanza("switchport mode trunk", f"{_ALLOWED} 1-4094"), _IDS_OS10_HAS_NOT),
    ("dell_os10", _stanza("switchport mode trunk", f"{_ALLOWED} 10,100,999"), ALL),
    ("dell_os10", _stanza("switchport mode trunk", f"{_ALLOWED} 10"), _SOME),
    ("aruba_aoscx", _stanza("no routing"), NONE),
    ("aruba_aoscx", _stanza("no routing", "vlan trunk native 999"), ALL),
    ("aruba_aoscx", _stanza("no routing", "vlan trunk native 1", "vlan trunk allowed all"), ALL),
    ("aruba_aoscx", _stanza("no routing", "vlan trunk allowed 1-4094"), _IDS_SPELLED_OUT),
    ("aruba_aoscx", _stanza("no routing", "vlan trunk allowed 10"), _SOME),
    ("juniper_junos", "set interfaces a unit 0 family ethernet-switching interface-mode trunk\n", NONE),
    ("juniper_junos", "set interfaces a unit 0 family ethernet-switching interface-mode trunk\n"
                      "set interfaces a unit 0 family ethernet-switching vlan members all\n", ALL),
    ("juniper_junos", "set interfaces a unit 0 family ethernet-switching interface-mode trunk\n"
                      "set interfaces a unit 0 family ethernet-switching vlan members 1-4094\n", _SOME),
    ("aruba_aoss", "vlan 10\n   untagged 2\n   exit\nvlan 100\n   exit\n", NONE),
    ("aruba_aoss", "".join(f"vlan {vid}\n   tagged 1\n   exit\n" for vid in DECLARED), ALL),
    ("aruba_aoss", "vlan 10\n   tagged 1\n   exit\nvlan 100\n   exit\n", _SOME),
])
def test_the_readers_tell_the_forms_apart(target: str, rendered: str, says: str) -> None:
    assert _says_in_text(target, rendered) == says


# ---------------------------------------------------------------------------
# A list stated on a port that is not a trunk (IOS-XE keeps one)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stated,kept", [("all", "all"), ("1-4094", "all"), ("10,999", "10,999"), ("none", None)])
def test_a_list_on_a_port_that_is_no_trunk(stated: str, kept: str | None) -> None:
    """IOS-XE keeps an allowed list on an access port for the day its
    mode is flipped, and a list that names VLANs comes back as it
    was.  There the word for every id is written: no line would be no
    statement at all.

    KNOWN LIMITATION, pinned by the last case: `none` does NOT come
    back.  On a port that is not `switchport mode trunk` the tree has
    one value, an empty list, for `none` and for no list at all, and
    no line is written for it.  For an access port that is a
    statement lost; for a port in a dynamic mode it is more, because
    a port that negotiates a trunk then carries every VLAN
    (`test_none_on_a_dynamic_port_is_lost`)."""
    text = _iosxe().replace(
        " switchport access vlan 10\n", f" switchport access vlan 10\n {_ALLOWED} {stated}\n", 1,
    )
    codec = get_codec("cisco_iosxe_cli")
    rendered = codec.render(codec.parse(text))
    access = next(stanza for stanza in _stanzas(rendered) if "switchport mode access" in stanza)
    assert [line for line in access if line.startswith(_ALLOWED)] == ([f"{_ALLOWED} {kept}"] if kept else [])


def test_none_on_a_dynamic_port_is_lost() -> None:
    """KNOWN LIMITATION, pinned, and in the CHANGELOG.  `switchport
    trunk allowed vlan none` on a port that is not `switchport mode
    trunk` is dropped, same vendor included.  The change that keeps
    it fails here."""
    for mode in ("switchport mode dynamic desirable", "switchport mode dynamic auto", None):
        lines = [f" {mode}"] if mode else []
        text = "\n".join([
            "hostname sw1", "!", "vlan 10", " name users", "!",
            "interface GigabitEthernet1/0/1", *lines, f" {_ALLOWED} none", "!", "end", "",
        ])
        codec = get_codec("cisco_iosxe_cli")
        parsed = codec.parse(text)
        assert [(iface.switchport_mode == "trunk", iface.trunk_allowed_vlans) for iface in parsed.interfaces] == [
            (False, []),
        ], mode
        assert _ALLOWED not in codec.render(parsed), mode


# ---------------------------------------------------------------------------
# A stanza met twice
# ---------------------------------------------------------------------------
#
# A config can hold the stanza of one interface more than once, and the
# device applies every line under the name to ONE interface.  Whether
# an interface states an allowed list is a fact about the interface.
# Four parsers make a record a stanza, and resolved "no allowed line"
# a stanza: a trunk of VLAN 10 whose stanza was met again with only
# its mode line came out with a second record of every VLAN (from
# OS10: of none), and `add` in a second stanza was added to the
# platform's list and not to the interface's.

_MODE = "switchport mode trunk"
_WRITERS = {
    "cisco_iosxe_cli": _iosxe, "arista_eos": _eos, "cisco_nxos": _nxos,
    "dell_os10": _os10, "aruba_aoscx": _aoscx, "juniper_junos": _junos,
}

#: The header of each source's trunk, the indent of its lines, and
#: what closes its stanza.
_TRUNK_STANZA = {
    "cisco_iosxe_cli": ("interface GigabitEthernet1/0/1", " ", ("!",)),
    "arista_eos": ("interface Ethernet1", "   ", ("!",)),
    "cisco_nxos": ("interface Ethernet1/1", "  ", ("",)),
    "dell_os10": ("interface ethernet1/1/1", " ", ("!",)),
    "aruba_aoscx": ("interface 1/1/1", "    ", ()),
}


def _met_again(source: str, text: str, *lines: str) -> str:
    """*text* with the stanza of its trunk met a second time, holding
    *lines*.  (Junos has no stanzas: the lines are stated again.)"""
    if source == "juniper_junos":
        return text + "".join(f"set interfaces ge-0/0/1 {line}\n" for line in lines)
    header, indent, close = _TRUNK_STANZA[source]
    again = "\n".join([header, *(indent + line for line in lines), *close]) + "\n"
    if text.endswith("end\n"):
        return text.removesuffix("end\n") + again + "end\n"
    return text + again


_CISCO_TWICE: dict[str, tuple[tuple[str, ...], tuple[str, ...], set[int]]] = {
    "its list, then the mode line again": ((f"{_ALLOWED} 10",), (_MODE,), {10}),
    "its list, then an add": ((f"{_ALLOWED} 10",), (f"{_ALLOWED} add 100",), {10, 100}),
    "the mode line, then its list": ((), (f"{_ALLOWED} 10",), {10}),
}

#: (source codec, what its two stanzas hold) -> (the trunk's lines in
#: the first, in the second, the declared VLANs the device then has on
#: the trunk).  Every one of the six parsers of the table is here: the
#: four that make a record a stanza, and the two that keep one record
#: a name and read these as the device does already.
TWICE: dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...], set[int]]] = {
    **{
        (source, title): case
        for source in ("cisco_iosxe_cli", "arista_eos", "cisco_nxos", "dell_os10")
        for title, case in _CISCO_TWICE.items()
    },
    ("aruba_aoscx", "its list, then the native line again"): (
        ("vlan trunk native 1", "vlan trunk allowed 10"), ("vlan trunk native 1",), {10},
    ),
    ("aruba_aoscx", "the native line, then its list"): (
        ("vlan trunk native 1",), ("vlan trunk allowed 10",), {10},
    ),
    ("juniper_junos", "its members, then the mode line again"): (
        ("unit 0 family ethernet-switching vlan members users",),
        ("unit 0 family ethernet-switching interface-mode trunk",), {10},
    ),
}


#: KNOWN GAP, pinned, and older than this module's subject.  A stanza
#: met twice is still two records for everything but the allowed
#: list, and IOS-XE's parser gives a stanza with no mode line a record
#: with no mode (which is right for a port met once: it is `dynamic
#: auto`).  Here the interface said `switchport mode trunk` in its
#: first stanza and `add 100` in a second that states no mode: the
#: second record holds VLANs 10 and 100 and is no trunk, the first is
#: a trunk of VLAN 10, and the targets below write a list for a trunk
#: alone.  VLAN 100 is not carried there -- fewer than the device
#: carries, as it was, where for a while it was every VLAN.  The
#: other targets make a trunk of the second record from the VLANs
#: that list it.  Measured below.
THE_ADD_IS_LOST_ON = frozenset({"aruba_aoscx", "aruba_aoss", "cisco_nxos", "dell_os10"})
_THE_ADD = ("cisco_iosxe_cli", "its list, then an add")


def _twice(source: str, title: str) -> str:
    first, second, _carried = TWICE[(source, title)]
    return _met_again(source, _WRITERS[source](*first), *second)


def test_twice_asks_each_parser_of_the_table() -> None:
    assert {source for source, _ in TWICE} == set(TRUNK_THAT_STATES_NO_LIST)


@pytest.mark.parametrize("source,title", sorted(TWICE))
def test_a_stanza_met_twice_is_one_interface(source: str, title: str) -> None:
    """No record of the interface holds a VLAN its interface does not
    carry, and between them they hold the ones it does."""
    carried = TWICE[(source, title)][2]
    parsed = get_codec(source).parse(_twice(source, title))
    records = [iface for iface in parsed.interfaces if iface.switchport_mode != "access"]
    lists = [set(iface.trunk_allowed_vlans) for iface in records if iface.switchport_mode == "trunk"]
    assert lists, (source, title)
    for listed in lists:
        assert listed and listed <= carried, f"{source} ({title}): a record of {len(listed)} VLANs"
    assert set().union(*(set(iface.trunk_allowed_vlans) for iface in records)) == carried, (source, title)


def _each_trunk_says(target: str, rendered: str) -> list[str]:
    """What each trunk stanza of an output says, as text: an interface
    whose stanza was met twice is written twice by some targets."""
    if target in ("arista_eos", "cisco_iosxe_cli", "cisco_nxos", "dell_os10"):
        trunks = [stanza for stanza in _stanzas(rendered) if _MODE in stanza]
        return [_switchport_says(target, stanza) for stanza in trunks]
    if target == "aruba_aoscx":
        return [_aoscx_says(stanza) for stanza in _aoscx_trunks(rendered)]
    return [_says_in_text(target, rendered)]


@pytest.mark.parametrize("target", sorted(WRITES_A_TRUNKS_VLANS))
@pytest.mark.parametrize("source,title", sorted(TWICE))
def test_a_stanza_met_twice_on_each_target(source: str, title: str, target: str) -> None:
    if target == "aruba_aoss" and source in AOSS_WRITES_NO_PORT_OF:
        return                      # the pinned gap above
    carried = TWICE[(source, title)][2]
    if (source, title) == _THE_ADD and target in THE_ADD_IS_LOST_ON:
        carried = carried - {100}   # the pinned gap above
    job = run_plan_with_overrides(
        get_codec(source), get_codec(target), _twice(source, title), port_rename_map={}, force=True,
    )
    assert job.rendered, (source, title, target, job.status)
    # 1. As text: every trunk stanza of the output states a list, and
    # none of them says every VLAN, or none.
    said = _each_trunk_says(target, job.rendered)
    assert said and set(said) == {_SOME}, f"{source} ({title}) to {target}: its trunk stanzas say {said}"
    # 2. With the target's parser: the VLANs the device has on the
    # trunk, and the access port in VLAN 10 beside it.
    parsed = get_codec(target).parse(job.rendered)
    for vid in DECLARED:
        assert len(_ports_in(parsed, vid)) == (vid in carried) + (vid == 10), (
            f"{source} ({title}) to {target}: VLAN {vid} is on {sorted(_ports_in(parsed, vid))}"
        )


def test_where_the_add_is_lost_is_as_pinned() -> None:
    measured = set()
    for target in sorted(WRITES_A_TRUNKS_VLANS):
        job = run_plan_with_overrides(
            get_codec(_THE_ADD[0]), get_codec(target), _twice(*_THE_ADD), port_rename_map={}, force=True,
        )
        if not _ports_in(get_codec(target).parse(job.rendered), 100):
            measured.add(target)
    assert measured == THE_ADD_IS_LOST_ON


def test_a_stanza_that_is_no_trunk_has_none() -> None:
    """What the interface states goes to the records that are TRUNKS.
    A second stanza that states no mode and no list (a description
    added later, say) is a record with no mode, and is given no list
    in the tree: an access stanza of the same name would otherwise
    come back with an allowed line its text never had.  (A stanza
    that is no trunk keeps a list it states itself, as IOS-XE does:
    `test_a_list_on_a_port_that_is_no_trunk`.)"""
    for second, mode in (("description uplink", None), ("switchport mode access", "access")):
        text = _met_again("cisco_iosxe_cli", _iosxe(f"{_ALLOWED} 10"), second)
        parsed = get_codec("cisco_iosxe_cli").parse(text)
        records = [iface for iface in parsed.interfaces if iface.name == "GigabitEthernet1/0/1"]
        assert [(iface.switchport_mode, iface.trunk_allowed_vlans) for iface in records] == [
            ("trunk", [10]), (mode, []),
        ], second


def test_each_record_has_a_list_of_its_own() -> None:
    """Two records of one interface are not handed one list object: a
    pass that edits one in place would edit both."""
    parsed = get_codec("cisco_nxos").parse(_twice("cisco_nxos", "its list, then the mode line again"))
    first, second = (iface for iface in parsed.interfaces if iface.switchport_mode == "trunk")
    assert first.trunk_allowed_vlans == second.trunk_allowed_vlans == [10]
    assert first.trunk_allowed_vlans is not second.trunk_allowed_vlans


#: Two port-channels written with a space before the number, as an
#: operator types them.  The IOS-XE and NX-OS parsers read both
#: headers as one name, `Port-channel` (an older fault of theirs: the
#: name is the header's first word).  They are two interfaces all the
#: same, and what one states is not the other's.
_TWO_PORTS_ONE_NAME = {
    "cisco_iosxe_cli": ("interface Port-channel {n}", " ", ("!",)),
    "cisco_nxos": ("interface port-channel {n}", "  ", ("",)),
}


def _two_port_channels(source: str, first: tuple[str, ...], second: tuple[str, ...]) -> str:
    header, indent, close = _TWO_PORTS_ONE_NAME[source]
    text = _WRITERS[source]().replace(_TRUNK_STANZA[source][1] + _MODE + "\n", "", 1)   # no other trunk
    for number, lines in ((1, first), (2, second)):
        stanza = "\n".join([header.format(n=number), *(indent + line for line in lines), *close]) + "\n"
        text = text.removesuffix("end\n") + stanza + ("end\n" if text.endswith("end\n") else "")
    return text


@pytest.mark.parametrize("source", sorted(_TWO_PORTS_ONE_NAME))
def test_two_ports_read_as_one_name_are_two(source: str) -> None:
    """The first states its list; the second states the mode alone,
    then an `add`, then a `remove`.  Each is read against the second
    port's OWN list -- every VLAN, the platform's -- and not the
    first port's."""
    for second, listed in (
        ((_MODE,), EVERY_ID),
        ((_MODE, f"{_ALLOWED} add 100"), EVERY_ID),
        ((_MODE, f"{_ALLOWED} remove 100"), EVERY_ID - {100}),
    ):
        parsed = get_codec(source).parse(_two_port_channels(source, (_MODE, f"{_ALLOWED} 10"), second))
        trunks = _trunks(parsed)
        assert len({iface.name for iface in trunks}) == 1, "the fault this test is about has been mended: rewrite it"
        assert [set(iface.trunk_allowed_vlans) for iface in trunks] == [{10}, listed], (source, second)


def test_the_key_of_a_header() -> None:
    key = TrunksByName.key
    assert key("interface Vlan 10") == key("interface vlan10") == key("interface  VLAN10 ")
    assert key("interface port-channel 1") != key("interface port-channel 2")
    assert key("interface GigabitEthernet1/0/1") != key("interface GigabitEthernet1/0/11")


# ---------------------------------------------------------------------------
# A trunk line and no mode line
# ---------------------------------------------------------------------------

#: KNOWN GAP, pinned, and older than this module's subject.  The
#: parsers that take a port for a trunk from a trunk line alone
#: (`switchport trunk native vlan N` and no `switchport mode trunk`).
#: An NX-OS or EOS port is an access port until it is told otherwise,
#: and EOS keeps a trunk line on an access port without acting on it;
#: IOS-XE's parser leaves such a port with no mode.  Measured below.
#: The change that mends the inference takes them out of here.
#:
#: What IS built: a trunk taken this way is given nothing from the
#: platform's list.  Its list is what its lines name, or empty --
#: fewer VLANs than a trunk would carry, and never every VLAN.
TAKES_A_TRUNK_LINE_FOR_A_TRUNK = frozenset({"arista_eos", "cisco_nxos"})


def _no_mode_line(source: str, *trunk: str) -> str:
    """The source's text with *trunk* as its trunk's lines and the
    `switchport mode trunk` line that the writer puts first taken out."""
    text = _WRITERS[source](*trunk)
    mode = _TRUNK_STANZA[source][1] + _MODE + "\n"
    assert mode in text, source
    return text.replace(mode, "", 1)


def _trunks(parsed) -> list:
    return [iface for iface in parsed.interfaces if iface.switchport_mode == "trunk"]


def test_who_infers_a_trunk_is_as_pinned() -> None:
    measured = {
        source for source in ("cisco_iosxe_cli", "arista_eos", "cisco_nxos")
        if _trunks(get_codec(source).parse(_no_mode_line(source, _NATIVE)))
    }
    assert measured == TAKES_A_TRUNK_LINE_FOR_A_TRUNK


#: What the trunk's lines are -> the VLANs of its list.
_INFERRED: dict[str, tuple[tuple[str, ...], set[int]]] = {
    "a native line": ((_NATIVE,), set()),
    "a list": ((f"{_ALLOWED} 10,100",), {10, 100}),
    "an add on its first line": ((f"{_ALLOWED} add 100",), {100}),
    "a remove on its first line": ((f"{_ALLOWED} remove 100",), set()),
    "an add, then a remove": ((f"{_ALLOWED} add 10,100", f"{_ALLOWED} remove 10"), {100}),
}


@pytest.mark.parametrize("title", sorted(_INFERRED))
@pytest.mark.parametrize("source", sorted(TAKES_A_TRUNK_LINE_FOR_A_TRUNK))
def test_an_inferred_trunk_has_its_own_list(source: str, title: str) -> None:
    lines, listed = _INFERRED[title]
    trunks = _trunks(get_codec(source).parse(_no_mode_line(source, *lines)))
    assert len(trunks) == 1, (source, title)
    assert set(trunks[0].trunk_allowed_vlans) == listed, (source, title, len(trunks[0].trunk_allowed_vlans))


@pytest.mark.parametrize("target", sorted(WRITES_A_TRUNKS_VLANS))
@pytest.mark.parametrize("title", sorted(_INFERRED))
@pytest.mark.parametrize("source", sorted(TAKES_A_TRUNK_LINE_FOR_A_TRUNK))
def test_an_inferred_trunk_is_not_every_vlan(source: str, title: str, target: str) -> None:
    """On every target: no VLAN where its lines name none, and the
    VLANs they name where they name some."""
    if target == "aruba_aoss" and source in AOSS_WRITES_NO_PORT_OF:
        return                      # the pinned gap above
    lines, listed = _INFERRED[title]
    native = 999 if _NATIVE in lines else None
    job = run_plan_with_overrides(
        get_codec(source), get_codec(target), _no_mode_line(source, *lines), port_rename_map={}, force=True,
    )
    assert job.rendered, (source, title, target, job.status)
    said = _says_in_text(target, job.rendered, native)
    assert said == (_SOME if listed else NONE), f"{source} ({title}) to {target}: the output says {said}"
    parsed = get_codec(target).parse(job.rendered)
    for vid in ((100,) if native else (100, 999)):
        assert len(_ports_in(parsed, vid)) == (vid in listed), (source, title, target, vid)


@pytest.mark.parametrize("source", sorted(TAKES_A_TRUNK_LINE_FOR_A_TRUNK))
def test_the_mode_line_may_come_second(source: str) -> None:
    """The mode line may come after the trunk line: the interface says
    it is a trunk, and its list is the platform's."""
    trunks = _trunks(get_codec(source).parse(_no_mode_line(source, _NATIVE, _MODE)))
    assert [set(iface.trunk_allowed_vlans) for iface in trunks] == [EVERY_ID], source


def test_nxos_says_so_in_another_stanza() -> None:
    """NX-OS makes a record a stanza.  The trunk line in one and the
    mode line in the next is one interface that says it is a trunk."""
    text = _met_again("cisco_nxos", _no_mode_line("cisco_nxos", _NATIVE), _MODE)
    trunks = _trunks(get_codec("cisco_nxos").parse(text))
    assert [set(iface.trunk_allowed_vlans) for iface in trunks] == [EVERY_ID, EVERY_ID]


def test_eos_access_port_with_a_trunk_line() -> None:
    """The older half, on EOS, as it stands: `switchport access vlan
    10` and a trunk line left behind is read as a trunk -- even after
    `switchport mode access`.  It is a trunk of NO VLAN, where it was
    a trunk of every VLAN on every target."""
    for lines in (
        ("switchport access vlan 10", _NATIVE),
        ("switchport mode access", "switchport access vlan 10", _NATIVE),
    ):
        text = _no_mode_line("arista_eos", *lines)
        trunks = _trunks(get_codec("arista_eos").parse(text))
        assert len(trunks) == 1 and trunks[0].trunk_allowed_vlans == [], lines
        job = run_plan_with_overrides(
            get_codec("arista_eos"), get_codec("juniper_junos"), text, port_rename_map={}, force=True,
        )
        assert _says_in_text("juniper_junos", job.rendered) == NONE, lines


# ---------------------------------------------------------------------------
# Lists that are not every VLAN, and every VLAN in another order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("listed", ["10,100", "10", "2-4094"])
def test_os10_says_nothing_above_some_list(listed: str) -> None:
    """The review line is for a trunk of every VLAN and for no other.
    (`2-4094` names ids OS10 does not have as well, and VLANs the
    output does not declare: it is written as it always was, with no
    line -- the older half of `CANNOT_BE_TOLD_ALL`, in Known
    limitations.)"""
    job = run_plan_with_overrides(
        get_codec("cisco_iosxe_cli"), get_codec("dell_os10"), _iosxe(f"{_ALLOWED} {listed}"),
        port_rename_map={}, force=True,
    )
    trunk = _the_trunk("dell_os10", job.rendered)
    assert [line for line in trunk if line.startswith(_ALLOWED)] == [f"{_ALLOWED} {listed}"], trunk
    assert not [line for line in trunk if "review" in line], trunk


def test_os10_first_line_add_on_each_target() -> None:
    """An OS10 trunk carries no tagged VLAN until a line names one, so
    `add 100` on its first allowed line is VLAN 100 and no more."""
    assert "dell_os10" in AOSS_WRITES_NO_PORT_OF
    for target in sorted(WRITES_A_TRUNKS_VLANS - {"aruba_aoss"}):
        job = run_plan_with_overrides(
            get_codec("dell_os10"), get_codec(target), _os10(f"{_ALLOWED} add 100"), port_rename_map={}, force=True,
        )
        assert _says_in_text(target, job.rendered) == _SOME, target
        parsed = get_codec(target).parse(job.rendered)
        assert len(_ports_in(parsed, 100)) == 1 and not _ports_in(parsed, 999), target


#: A port name each renderer writes switchport lines for.
_A_PORT = {
    "arista_eos": "Ethernet1", "aruba_aoscx": "1/1/1", "cisco_iosxe_cli": "GigabitEthernet1/0/1",
    "cisco_nxos": "Ethernet1/1", "dell_os10": "ethernet1/1/1", "juniper_junos": "ge-0/0/1",
}


@pytest.mark.parametrize("target", sorted(_A_PORT))
@pytest.mark.parametrize("order", ["backwards", "VLAN 1 last", "an id twice"])
def test_every_vlan_in_any_order_is_written(order: str, target: str) -> None:
    """A tree that was posted, or built by hand, need not list the ids
    in their order.  Every id is every VLAN however it is written."""
    allowed = {
        "backwards": list(range(4094, 0, -1)),
        "VLAN 1 last": [*range(2, 4095), 1],
        "an id twice": [*range(1, 4095), 7],
    }[order]
    tree = CanonicalIntent(
        hostname="sw1",
        vlans=[CanonicalVlan(id=vid) for vid in DECLARED],
        interfaces=[CanonicalInterface(
            name=_A_PORT[target], interface_type="ianaift:ethernetCsmacd",
            switchport_mode="trunk", trunk_allowed_vlans=allowed,
        )],
    )
    said = _says_in_text(target, get_codec(target).render(tree))
    assert said == (_IDS_OS10_HAS_NOT if target in CANNOT_BE_TOLD_ALL else ALL), (target, order, said)


def test_a_port_is_named_for_each_writer() -> None:
    assert set(_A_PORT) == WRITES_A_TRUNKS_VLANS - {"aruba_aoss"}   # AOS-S has no list to write


# ---------------------------------------------------------------------------
# The shared pieces, one at a time
# ---------------------------------------------------------------------------


class TestTheTableAndItsReaders:
    def test_what_a_list_says(self) -> None:
        assert trunk_list_says([]) == TRUNK_NONE
        assert trunk_list_says(list(range(1, 4095))) == TRUNK_ALL
        assert trunk_list_says(list(range(4094, 0, -1))) == TRUNK_ALL            # any order
        assert trunk_list_says([*range(1, 4095), 7, 7]) == TRUNK_ALL             # an id written twice
        for some in ([1], list(range(2, 4095)), list(range(1, 4094)), [*range(1, 4094), 4093]):
            assert trunk_list_says(some) == TRUNK_SOME, len(some)
        assert is_every_vlan(tuple(range(1, 4095))) and not is_every_vlan(())

    def test_an_unstated_list_is_the_platforms(self) -> None:
        for codec, default in TRUNK_THAT_STATES_NO_LIST.items():
            assert trunk_list_says(unstated_trunk_list(codec)) == default, codec
        one, two = unstated_trunk_list("cisco_nxos"), unstated_trunk_list("cisco_nxos")
        assert one == two and one is not two, "each trunk has a list of its own"
        assert all(vid is VLAN_IDS[vid] for vid in one), "and its ints are the shared ones"
        with pytest.raises(KeyError):
            unstated_trunk_list("a_codec_nobody_listed")

    @pytest.mark.parametrize("codec", ["arista_eos", "cisco_iosxe_cli", "cisco_nxos"])
    def test_what_the_three_write_for_a_list(self, codec: str) -> None:
        assert switchport_trunk_allowed_value(codec, [], coalesce=True) == "none"
        assert switchport_trunk_allowed_value(codec, list(range(1, 4095)), coalesce=True) is None
        assert switchport_trunk_allowed_value(codec, [30, 10, 11, 12], coalesce=True) == "10-12,30"
        assert switchport_trunk_allowed_value(codec, [30, 10, 11, 12], coalesce=False) == "30,10,11,12"

    def test_what_os10_writes_after_allowed_vlan(self) -> None:
        assert switchport_trunk_allowed_value("dell_os10", [], coalesce=True) is None
        assert switchport_trunk_allowed_value("dell_os10", list(range(1, 4095)), coalesce=True) == "1-4094"
        assert switchport_trunk_allowed_value("dell_os10", [30, 10, 11, 12], coalesce=True) == "10-12,30"

    def test_add_and_remove_start_from_that_list(self) -> None:
        every = tuple(range(1, 4095))
        # No allowed line yet (`None`) on a platform whose trunk carries every VLAN.
        assert merge_trunk_allowed(None, "add 30", unstated=every) == list(every)
        assert merge_trunk_allowed(None, "remove 10", unstated=every) == [vid for vid in every if vid != 10]
        # ... and on one whose trunk carries none.
        assert merge_trunk_allowed(None, "add 30") == [30]
        assert merge_trunk_allowed(None, "remove 10") == []
        # A line WAS stated, and emptied the list: `add` adds to nothing.
        assert merge_trunk_allowed([], "add 30", unstated=every) == [30]
        assert merge_trunk_allowed([], "remove 10", unstated=every) == []
        # The words that set a list do not look at what was there.
        for existing in (None, [], [5]):
            assert merge_trunk_allowed(existing, "none", unstated=every) == []
            assert merge_trunk_allowed(existing, "all", unstated=every) == list(every)
            assert merge_trunk_allowed(existing, "10,20", unstated=every) == [10, 20]

    @pytest.mark.parametrize("codec,write", [("cisco_iosxe_cli", _iosxe), ("arista_eos", _eos), ("cisco_nxos", _nxos)])
    def test_a_first_line_remove_is_all_but_that(self, codec: str, write) -> None:
        parsed = get_codec(codec).parse(write(f"{_ALLOWED} remove 100"))
        trunk = next(iface for iface in parsed.interfaces if iface.switchport_mode == "trunk")
        assert set(trunk.trunk_allowed_vlans) == EVERY_ID - {100}
        assert not _ports_in(parsed, 100) and len(_ports_in(parsed, 999)) == 1

    def test_os10_add_and_remove_start_empty(self) -> None:
        for line, listed in ((f"{_ALLOWED} add 100", [100]), (f"{_ALLOWED} remove 100", [])):
            parsed = get_codec("dell_os10").parse(_os10(line))
            trunk = next(iface for iface in parsed.interfaces if iface.switchport_mode == "trunk")
            assert trunk.trunk_allowed_vlans == listed, line


class TestWhatAnInterfaceStates:
    """`TrunksByName`, on records built by hand: what a parser tells
    it, and the list each record is then given."""

    @staticmethod
    def _port(mode: str | None = "trunk") -> CanonicalInterface:
        return CanonicalInterface(name="Port1", switchport_mode=mode)

    def test_a_stated_trunk_has_the_platforms(self) -> None:
        for codec, default in TRUNK_THAT_STATES_NO_LIST.items():
            trunks = TrunksByName(codec)
            trunks.mode_line("Port1", "trunk")
            port = trunks.made("Port1", self._port())
            trunks.settle()
            assert trunk_list_says(port.trunk_allowed_vlans) == default, codec

    def test_an_inferred_trunk_has_none_of_it(self) -> None:
        trunks = TrunksByName("cisco_nxos")
        trunks.mode_line("Port1", "access")          # a mode, and not trunk
        port = trunks.made("Port1", self._port())
        trunks.settle()
        assert port.trunk_allowed_vlans == []
        # Its lines count, and an `add` on the first of them adds to nothing.
        trunks = TrunksByName("cisco_nxos")
        assert set(trunks.allowed_line("Port1", "add 30")) == EVERY_ID     # what a trunk would have
        assert trunks.allowed_line("Port1", "add 40,50") and trunks.allowed_line("Port1", "remove 40")
        port = trunks.made("Port1", self._port())
        trunks.settle()
        assert port.trunk_allowed_vlans == [30, 50]

    def test_a_stated_list_ends_the_adding(self) -> None:
        """After `add 30`, a line that states the list is the list for
        an inferred trunk as for any other; a later `add` adds to it."""
        trunks = TrunksByName("arista_eos")
        for line in ("add 30", "10,20", "add 40"):
            trunks.allowed_line("Port1", line)
        port = trunks.made("Port1", self._port())
        trunks.settle()
        assert port.trunk_allowed_vlans == [10, 20, 40]

    def test_saying_so_may_come_last(self) -> None:
        trunks = TrunksByName("cisco_iosxe_cli")
        trunks.allowed_line("Port1", "remove 10")
        first = trunks.made("Port1", self._port())
        trunks.says_trunk("Port1")                    # a later stanza
        second = trunks.made("Port1", self._port())
        trunks.settle()
        assert set(first.trunk_allowed_vlans) == set(second.trunk_allowed_vlans) == EVERY_ID - {10}
        assert first.trunk_allowed_vlans is not second.trunk_allowed_vlans

    def test_a_port_that_is_no_trunk(self) -> None:
        trunks = TrunksByName("cisco_iosxe_cli")
        trunks.allowed_line("Port1", "10,20")
        keeps = trunks.made("Port1", self._port(None))         # its own stanza states the list
        other = trunks.made("Port1", self._port("access"))     # another stanza of the name states none
        trunks.settle()
        assert keeps.trunk_allowed_vlans == [10, 20] and other.trunk_allowed_vlans == []

    def test_a_platform_of_none_adds_to_nothing(self) -> None:
        trunks = TrunksByName("dell_os10")
        trunks.mode_line("Port1", "trunk")
        trunks.allowed_line("Port1", "add 30")
        port = trunks.made("Port1", self._port())
        bare = trunks.made("Port2", CanonicalInterface(name="Port2", switchport_mode="trunk"))
        trunks.settle()
        assert port.trunk_allowed_vlans == [30] and bare.trunk_allowed_vlans == []

    def test_a_codec_nobody_listed(self) -> None:
        with pytest.raises(KeyError):
            TrunksByName("a_codec_nobody_listed")


# ---------------------------------------------------------------------------
# The next codec says which it is
# ---------------------------------------------------------------------------

#: Public codecs that are NOT in `TRUNK_THAT_STATES_NO_LIST`, each with
#: the reason: its platform has no allowed list that a trunk could leave
#: unstated, or its parser reads none.  A codec whose parser can make a
#: trunk with a list of its own belongs in the table instead.
NO_ALLOWED_LIST: dict[str, str] = {
    "aruba_aoss": (
        "no allowed list: a port is a trunk only by being tagged in a VLAN, and its list is those VLANs"
    ),
    "cisco_iosxe": "the NETCONF parser reads no switchport state",
    "cisco_iosxr": "no trunks: a VLAN is an l2transport sub-interface with its own encapsulation",
    "fortigate_cli": "no trunks: a VLAN is a sub-interface on a parent",
    "mikrotik_routeros": "the bridge VLAN table is not read",
    "opnsense": "no trunks: a VLAN is a device on a parent interface",
    "vyos": "a bridge member's allowed-vlan is not read; only vif sub-interfaces are",
}


def _in_neither_or_both(codecs: list[str]) -> list[str]:
    return sorted(
        codec for codec in codecs
        if (codec in TRUNK_THAT_STATES_NO_LIST) == (codec in NO_ALLOWED_LIST)
    )


def test_each_codec_is_in_the_table_or_named() -> None:
    """A parser that can make a trunk has to state the trunk's list when
    the text states none, and only the platform's own default is right.
    A new codec is in the table, or is named here with its reason."""
    assert not _in_neither_or_both(list_public_codecs()), (
        "say what a trunk that states no allowed list carries on this platform "
        "(TRUNK_THAT_STATES_NO_LIST in codecs/_helpers.py), or name it in NO_ALLOWED_LIST with the reason"
    )
    assert not set(TRUNK_THAT_STATES_NO_LIST) - set(list_public_codecs())
    assert not set(NO_ALLOWED_LIST) - set(list_public_codecs())
    assert all(NO_ALLOWED_LIST.values())


def test_a_codec_in_neither_is_reported() -> None:
    """The check above, handed a fourteenth codec nobody placed, and one
    that somebody placed twice."""
    assert _in_neither_or_both([*list_public_codecs(), "a_fourteenth"]) == ["a_fourteenth"]
    doubled = {**NO_ALLOWED_LIST, "dell_os10": "also named here"}
    assert [codec for codec in list_public_codecs() if codec in TRUNK_THAT_STATES_NO_LIST and codec in doubled] == [
        "dell_os10",
    ]


_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
_CAPTURE_SUFFIXES = {".txt", ".cfg", ".xml", ".conf", ".rsc", ".set"}


def _captures_of(codec: str) -> list[Path]:
    """The committed captures of *codec*: the synthetic ones, in a
    directory of the codec's name, and the real ones, in the
    directories the repository's one table maps to it."""
    directories = [_FIXTURES / "synthetic" / codec]
    directories += [_FIXTURES / "real" / label for label, name in DIR_TO_CODEC_NAME.items() if name == codec]
    return [
        path for directory in directories if directory.is_dir() for path in sorted(directory.iterdir())
        if path.is_file() and path.suffix.lower() in _CAPTURE_SUFFIXES
    ]


def _trunks_of(codec: str) -> list:
    captures = _captures_of(codec)
    assert captures, f"{codec}: no committed capture to read"
    return [
        iface for path in captures for iface in get_codec(codec).parse(path.read_text(encoding="utf-8")).interfaces
        if iface.switchport_mode == "trunk"
    ]


@pytest.mark.parametrize("codec", sorted(NO_ALLOWED_LIST))
def test_the_codecs_named_make_no_bare_trunk(codec: str) -> None:
    """What the reasons claim, measured on the committed captures: no
    parser named there makes a trunk whose list is empty.  (AOS-S makes
    trunks; each has the VLANs that tag it.  The rest make none.)"""
    trunks = _trunks_of(codec)
    empty = [iface.name for iface in trunks if not iface.trunk_allowed_vlans]
    assert not empty, f"{codec}: {len(empty)} of {len(trunks)} trunks have an empty list"
    if codec == "aruba_aoss":
        assert trunks, "aruba_aoss: no trunk in any capture, so nothing was measured"
    else:
        assert not trunks, f"{codec}: its parser makes trunks ({len(trunks)}); what does one with no list carry?"


def test_the_codecs_of_the_table_make_trunks() -> None:
    """And the other way round: each codec of the table makes trunks
    from its captures, so the check above is not passing on nothing."""
    for codec in TRUNK_THAT_STATES_NO_LIST:
        assert _trunks_of(codec), codec
