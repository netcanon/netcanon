"""Onto OS10 a VLAN's name is the description of the SVI the config has.

OS10 has one label for a VLAN: the ``description`` of its ``interface
vlan<N>`` (``show vlan`` prints it as the VLAN's ``Description``), which
the parser reads as the VLAN's name.  The renderer wrote a VLAN's name
there only on an SVI it made for a VLAN that had none, so IOS-XE ``vlan
10`` / ``name USERS`` beside ``interface Vlan10`` came out with no
``USERS``, in a job that said ``completed``.

Now an SVI of the config that states no description is given its
VLAN's name.  One that states a description of its own keeps it -- it
is the interface's statement -- and a name it does not hold is written
in a ``! review:`` line of its stanza; the matrix lists
``/vlans/vlan/name`` as lossy for that case.  And where the config holds
an SVI's stanza more than once, the parser takes the last description
one of them states, as OS10 applies them in turn.

An SVI is what the OS10 parser reads as one.  The render writes a
name as the tree holds it, and asked the classifier, which reads
only ``vlan<N>``: an AOS-CX ``vlan 101`` was no SVI to it, so the
render made a second ``interface vlan101`` for the VLAN, and OS10,
which takes ``interface vlan 101`` for the same interface, applied
the description of the stanza that came last.

The output is read with a reader typed here for OS10's grammar and with
the OS10 parser, and each check is handed the renderer as it was.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalVlan,
)
from netcanon.migration.codecs.dell_os10 import render as os10_render
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[5]

# ---------------------------------------------------------------------------
# Sources, typed by hand: VLAN 10 has an SVI with no description, VLAN 20
# one with a description of its own, VLAN 30 none, VLAN 40 one whose
# description is the VLAN's name.
# ---------------------------------------------------------------------------

IOSXE = """hostname sw1
!
vlan 10
 name USERS
!
vlan 20
 name VOICE
!
vlan 30
 name PRINTERS
!
vlan 40
 name SAME
!
interface Vlan10
 ip address 10.0.10.1 255.255.255.0
!
interface Vlan20
 description voice gateway
 ip address 10.0.20.1 255.255.255.0
!
interface Vlan40
 description SAME
 ip address 10.0.40.1 255.255.255.0
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 30
!
end
"""

NXOS = """hostname sw1
feature interface-vlan
vlan 10
  name USERS
vlan 20
  name VOICE
vlan 30
  name PRINTERS
vlan 40
  name SAME

interface Vlan10
  no shutdown
  ip address 10.0.10.1/24

interface Vlan20
  description voice gateway
  no shutdown
  ip address 10.0.20.1/24

interface Vlan40
  description SAME
  no shutdown
  ip address 10.0.40.1/24

interface Ethernet1/1
  switchport
  switchport access vlan 30
"""

EOS = """hostname sw1
!
vlan 10
   name USERS
!
vlan 20
   name VOICE
!
vlan 30
   name PRINTERS
!
vlan 40
   name SAME
!
interface Ethernet1
   switchport access vlan 30
!
interface Vlan10
   ip address 10.0.10.1/24
!
interface Vlan20
   description voice gateway
   ip address 10.0.20.1/24
!
interface Vlan40
   description SAME
   ip address 10.0.40.1/24
!
end
"""

JUNOS = """set system host-name sw1
set vlans USERS vlan-id 10
set vlans USERS l3-interface irb.10
set vlans VOICE vlan-id 20
set vlans VOICE l3-interface irb.20
set vlans PRINTERS vlan-id 30
set vlans SAME vlan-id 40
set vlans SAME l3-interface irb.40
set interfaces irb unit 10 family inet address 10.0.10.1/24
set interfaces irb unit 20 description "voice gateway"
set interfaces irb unit 20 family inet address 10.0.20.1/24
set interfaces irb unit 40 description SAME
set interfaces irb unit 40 family inet address 10.0.40.1/24
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members PRINTERS
"""

#: AOS-CX writes an SVI's name with a space (``interface vlan 10``),
#: which the bare path writes as it is.
AOSCX = """hostname sw1
vlan 10
    name USERS
vlan 20
    name VOICE
vlan 30
    name PRINTERS
vlan 40
    name SAME
interface 1/1/1
    no shutdown
    no routing
    vlan access 30
interface vlan 10
    ip address 10.0.10.1/24
interface vlan 20
    description voice gateway
    ip address 10.0.20.1/24
interface vlan 40
    description SAME
    ip address 10.0.40.1/24
"""

#: ``(source codec, text, paths)``.  The bare path renders the parsed
#: tree as it is, so only a source whose SVI name OS10 reads as an SVI
#: (``Vlan10``, ``vlan 10``) is on it; a Junos ``irb.10`` is an SVI of
#: the output once the port translator has renamed it.
SOURCES = {
    "iosxe": ("cisco_iosxe_cli", IOSXE, ("bare", "plan")),
    "nxos": ("cisco_nxos", NXOS, ("bare", "plan")),
    "eos": ("arista_eos", EOS, ("bare", "plan")),
    "aoscx": ("aruba_aoscx", AOSCX, ("bare", "plan")),
    "junos": ("juniper_junos", JUNOS, ("plan",)),
}

CELLS = [(key, path) for key, (_, _, paths) in SOURCES.items() for path in paths]

#: The sources whose VLAN 10 has an SVI record in the parsed tree.  The
#: Junos parser folds an IRB unit that holds nothing but an address onto
#: its VLAN and keeps no ``irb.10``, so onto OS10 its SVI is one the
#: renderer makes, which wrote the name before.
SVI_RECORD_OF_VLAN_10 = {"iosxe", "nxos", "eos", "aoscx"}

#: What every source is to come out as, by hand: ``{VLAN id: (the SVI's
#: description, the name a review line in its stanza says)}``.
WANT = {
    10: ("USERS", None),
    20: ("voice gateway", "VOICE"),
    30: ("PRINTERS", None),
    40: ("SAME", None),
}

#: What the OS10 parser reads back as each VLAN's name: its one label.
WANT_BACK = {10: "USERS", 20: "voice gateway", 30: "PRINTERS", 40: "SAME"}

# ---------------------------------------------------------------------------
# A reader of OS10's grammar
# ---------------------------------------------------------------------------

#: OS10 takes ``vlan 10`` for ``vlan10``.
_HEAD = re.compile(r"interface [Vv]lan ?(\d+)\s*")
_REVIEW = re.compile(r" ! review: VLAN (\d+) is named (.*) in the source; .*")


def _svi_stanzas(text: str) -> dict[int, list[list[str]]]:
    """``{VLAN id: [the body lines of each stanza of its SVI]}``."""
    out: dict[int, list[list[str]]] = {}
    body: list[str] | None = None
    for line in text.splitlines():
        head = _HEAD.fullmatch(line)
        if head:
            body = []
            out.setdefault(int(head.group(1)), []).append(body)
            continue
        if not line[:1].isspace():
            body = None
            continue
        if body is not None:
            body.append(line)
    return out


def _labels(text: str) -> dict[int, tuple[str | None, str | None]]:
    """``{VLAN id: (the description OS10 applies, the name a review line
    says)}`` -- the last ``description`` of the SVI's stanzas."""
    out: dict[int, tuple[str | None, str | None]] = {}
    for vid, stanzas in _svi_stanzas(text).items():
        description = review = None
        for body in stanzas:
            for line in body:
                found = re.fullmatch(r" description (.*?)\s*", line)
                if found:
                    description = found.group(1)
                said = _REVIEW.fullmatch(line)
                if said:
                    assert int(said.group(1)) == vid, line
                    review = said.group(2)
        out[vid] = (description, review)
    return out


def _render(key: str, path: str) -> tuple[str, object]:
    source, text, _ = SOURCES[key]
    if path == "bare":
        return get_codec("dell_os10").render(get_codec(source).parse(text)), None
    job = run_plan_with_checked_names(
        get_codec(source), get_codec("dell_os10"), text, port_rename_map={},
    )
    assert job.rendered, (job.status, job.error)
    return job.rendered, job


def _misses(key: str, path: str) -> list[str]:
    out, _ = _render(key, path)
    by_text = _labels(out)
    by_parser = {vlan.id: vlan.name for vlan in get_codec("dell_os10").parse(out).vlans}
    misses = []
    for vid, want in WANT.items():
        if by_text.get(vid) != want:
            misses.append(f"text: VLAN {vid} is {by_text.get(vid)!r}, not {want!r}")
        if by_parser.get(vid) != WANT_BACK[vid]:
            misses.append(f"parser: VLAN {vid} is {by_parser.get(vid)!r}, not {WANT_BACK[vid]!r}")
    return misses


# ---------------------------------------------------------------------------
# The name is on its SVI, or said beside the SVI's own description
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("key", "path"), CELLS)
def test_the_name_is_the_svis_description(key: str, path: str) -> None:
    assert not _misses(key, path)


@pytest.mark.parametrize(("key", "path"), CELLS)
def test_the_renderer_as_it_was_misses_the_name(key: str, path: str, monkeypatch) -> None:
    monkeypatch.setattr(
        os10_render, "_vlan_names_on_svis", lambda tree: (list(tree.interfaces), {}),
    )
    misses = _misses(key, path)
    assert any(miss.startswith("text: VLAN 20 ") for miss in misses), misses
    if key in SVI_RECORD_OF_VLAN_10:
        assert any(miss.startswith("text: VLAN 10 ") for miss in misses), misses
        assert any(miss.startswith("parser: VLAN 10 ") for miss in misses), misses


def test_the_sources_have_the_svis_the_test_is_about() -> None:
    for key, (source, text, _) in SOURCES.items():
        names = {
            iface.name.lower().replace(" ", "")
            for iface in get_codec(source).parse(text).interfaces
        }
        assert ("vlan10" in names) is (key in SVI_RECORD_OF_VLAN_10), key
        assert "vlan20" in names or "irb.20" in names, key


def _stanza_counts(key: str, path: str) -> dict[int, int]:
    return {vid: len(stanzas) for vid, stanzas in _svi_stanzas(_render(key, path)[0]).items()}


@pytest.mark.parametrize(("key", "path"), CELLS)
def test_each_svi_is_one_stanza(key: str, path: str) -> None:
    """Each source states each SVI once, and the output says it once."""
    assert _stanza_counts(key, path) == dict.fromkeys(WANT, 1)


def test_the_classifier_as_it_was_made_a_second_svi(monkeypatch) -> None:
    """Asked of the classifier, an AOS-CX ``vlan 10`` is no SVI, and
    the bare path writes its VLAN a second one."""

    def classified(name: str) -> int | None:
        ident = os10_render._port_names.classify_port_name(name)
        return ident.index if ident.kind == "svi" else None

    monkeypatch.setattr(os10_render, "_svi_of", classified)
    counts = _stanza_counts("aoscx", "bare")
    assert counts[10] == counts[20] == counts[40] == 2, counts
    assert _misses("aoscx", "bare")


@pytest.mark.parametrize("key", list(SOURCES))
def test_the_job_lists_the_name_where_it_can_be_lost(key: str) -> None:
    _, job = _render(key, "plan")
    lossy = {issue.path: issue for issue in job.validation.lossy_paths}
    assert "/vlans/vlan/name" in lossy
    assert lossy["/vlans/vlan/name"].severity == "warn"
    assert "review" in lossy["/vlans/vlan/name"].reason


# ---------------------------------------------------------------------------
# A stanza met more than once
# ---------------------------------------------------------------------------


def _svi(name: str, description: str = "") -> CanonicalInterface:
    return CanonicalInterface(
        name=name, description=description, interface_type="ianaift:l3ipvlan",
    )


def test_the_name_goes_on_the_first_record_where_none_states_one() -> None:
    tree = CanonicalIntent(
        interfaces=[_svi("vlan10"), _svi("vlan10")],
        vlans=[CanonicalVlan(id=10, name="USERS")],
    )
    stanzas = _svi_stanzas(get_codec("dell_os10").render(tree))[10]
    assert [" description USERS" in body for body in stanzas] == [True, False]


def test_the_review_is_in_the_stanza_whose_description_is_not_the_name() -> None:
    tree = CanonicalIntent(
        interfaces=[_svi("vlan20", "VOICE"), _svi("vlan20"), _svi("vlan20", "voice gateway")],
        vlans=[CanonicalVlan(id=20, name="VOICE")],
    )
    stanzas = _svi_stanzas(get_codec("dell_os10").render(tree))[20]
    said = [[_REVIEW.fullmatch(line) is not None for line in body] for body in stanzas]
    assert [any(row) for row in said] == [False, False, True]


def test_no_review_where_the_last_description_is_the_name() -> None:
    tree = CanonicalIntent(
        interfaces=[_svi("vlan20", "voice gateway"), _svi("vlan20", "VOICE")],
        vlans=[CanonicalVlan(id=20, name="VOICE")],
    )
    assert "review: VLAN" not in get_codec("dell_os10").render(tree)


def test_the_parser_takes_the_last_description() -> None:
    """OS10 applies an interface's stanzas in turn."""
    text = (
        "interface vlan10\n no shutdown\n!\n"
        "interface vlan10\n description USERS\n!\n"
        "interface vlan20\n description FIRST\n!\n"
        "interface vlan20\n no shutdown\n!\n"
        "interface vlan20\n description SECOND\n!\n"
    )
    names = {vlan.id: vlan.name for vlan in get_codec("dell_os10").parse(text).vlans}
    assert names == {10: "USERS", 20: "SECOND"}


# ---------------------------------------------------------------------------
# What else holds
# ---------------------------------------------------------------------------


def test_the_render_leaves_the_tree_as_it_was() -> None:
    tree = get_codec("cisco_iosxe_cli").parse(IOSXE)
    before = tree.model_dump()
    get_codec("dell_os10").render(tree)
    assert tree.model_dump() == before


_CAPTURES = sorted((_REPO / "tests/fixtures/real/dell_os10").glob("*.*"))
_CAPTURES = [path for path in _CAPTURES if path.suffix in {".cfg", ".txt"}]


def test_there_are_os10_captures() -> None:
    assert len(_CAPTURES) >= 5


@pytest.mark.parametrize("path", _CAPTURES, ids=lambda path: path.name)
def test_an_os10_config_onto_os10_says_nothing_of_names(path: Path) -> None:
    """On OS10 a VLAN's name came from its SVI's description, so the
    render writes no review line and the names come back as they were."""
    codec = get_codec("dell_os10")
    tree = codec.parse(path.read_text(encoding="utf-8"))
    out = codec.render(tree)
    assert "review: VLAN" not in out
    back = {vlan.id: vlan.name for vlan in codec.parse(out).vlans}
    assert back == {vlan.id: vlan.name for vlan in tree.vlans}
