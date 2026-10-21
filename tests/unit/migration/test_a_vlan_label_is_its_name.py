"""A VLAN's label is its name, on a target whose VLAN has only a name.

OPNsense and RouterOS have no name for a VLAN of its own: the tree
names it after its interface (an OPNsense ``<vlanif>``, a RouterOS
``/interface vlan``), and the label an operator typed -- an OPNsense
``<descr>``, a RouterOS ``comment=`` -- is its description.  IOS-XE,
NX-OS, EOS, AOS-S and Junos write one label for a VLAN, its name, and
no description, and OS10 one, its SVI's description: the label was
not in their output at all, and the
name they wrote was a device name (``vlan0.10``) or, once the port
translator had renamed that interface, a name nothing else held.

So a VLAN whose name is empty or only the name of an interface of the
config is written with its description AS its name, on a target that
says its VLAN has only a name (``CodecBase.vlans_have_only_a_name``),
by one shared rule (``netcanon/migration/_vlan_labels.py``) applied in
``run_plan`` before the port translator and at the render boundary.
A name of the VLAN's own (an AOS-CX ``name``) is kept, and its
description stays the loss the matrix declares.  On OS10 an SVI of
the output with a description of its own keeps it, and the label
is said in a review line of its stanza.

The output is read three ways: as text, by a reader typed here for
each target's grammar; with the target's own parser; and on the plan
path, for what the job lists.  Each check is handed the defect it is
for: the flag taken off a target, and the pipeline's own step taken
out.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import pytest

from netcanon.migration._vlan_labels import vlan_labels_as_names
from netcanon.migration.codecs.base import CodecBase
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services import migration_pipeline
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]

#: The targets whose VLAN has only a name.
TARGETS = (
    "arista_eos", "aruba_aoss", "cisco_iosxe_cli", "cisco_nxos", "dell_os10",
    "juniper_junos",
)

_LABEL_OF_ITS_OWN = "a VLAN has a label of its own beside its name, and both are written"
_NAMED_BY_AN_INTERFACE = (
    "a VLAN is an interface of the config, and its name is the name other "
    "lines refer to it by; the label goes to that interface's own label"
)
_WRITES_NO_VLAN_NAME = "writes no VLAN name, so there is nothing to give the label to"

#: Every other public codec, and why its VLAN is not one name alone.
NOT_NAME_ONLY = {
    "opnsense": _LABEL_OF_ITS_OWN,
    "aruba_aoscx": _LABEL_OF_ITS_OWN,
    "fortigate_cli": _NAMED_BY_AN_INTERFACE,
    "mikrotik_routeros": _NAMED_BY_AN_INTERFACE,
    "vyos": _WRITES_NO_VLAN_NAME,
    "cisco_iosxr": _WRITES_NO_VLAN_NAME,
    "cisco_iosxe": _WRITES_NO_VLAN_NAME,
}

# ---------------------------------------------------------------------------
# Sources, typed by hand, with what each target is to write for them
# ---------------------------------------------------------------------------

#: Two VLANs with a device and a label, one with a label and no device,
#: one with a device and no label.  Each device name is OPNsense's own
#: form, which the port translator renames to a VLAN interface.
OPNSENSE = """<?xml version="1.0"?>
<opnsense>
  <system><hostname>fw</hostname></system>
  <interfaces>
    <lan><if>igb1</if><descr>LAN</descr><enable>1</enable><ipaddr>192.0.2.1</ipaddr><subnet>26</subnet></lan>
    <opt1><if>vlan0.20</if><descr>GUEST</descr><enable>1</enable><ipaddr>198.51.100.1</ipaddr><subnet>26</subnet></opt1>
  </interfaces>
  <vlans version="1.0.0">
    <vlan uuid="fakeuuid-0001"><if>igb1</if><tag>20</tag><pcp>0</pcp><proto/>
      <descr>Guest Wifi</descr><vlanif>vlan0.20</vlanif></vlan>
    <vlan uuid="fakeuuid-0002"><if>igb1</if><tag>40</tag><pcp>0</pcp><proto/>
      <descr>Spare</descr><vlanif>vlan0.40</vlanif></vlan>
    <vlan uuid="fakeuuid-0003"><if>igb1</if><tag>50</tag><pcp>0</pcp><proto/>
      <descr>Printers</descr></vlan>
    <vlan uuid="fakeuuid-0004"><if>igb1</if><tag>60</tag><pcp>0</pcp><proto/>
      <descr></descr><vlanif>vlan0.60</vlanif></vlan>
  </vlans>
</opnsense>
"""

ROUTEROS = """/interface vlan
add comment=Cameras interface=ether2 name=vlan30 vlan-id=30
add comment="Door Locks" interface=ether2 name=locks vlan-id=31
/ip address
add address=198.51.100.65/26 interface=vlan30
"""

#: A name of the VLAN's own beside a description (kept), and a
#: description with no name (written as the name).
AOSCX = """hostname sw1
vlan 1
vlan 60
    name OFFICE
    description Second-floor
vlan 70
    description Lab
interface 1/1/1
    no shutdown
    vlan access 60
interface 1/1/2
    no shutdown
    vlan access 70
"""

#: ``(source codec, text, {VLAN id: the label written as its name})``.
#: A VLAN that is not here keeps the name it has.
HAND = {
    "opnsense": ("opnsense", OPNSENSE, {20: "Guest Wifi", 40: "Spare", 50: "Printers", 60: "vlan0.60"}),
    "routeros": ("mikrotik_routeros", ROUTEROS, {30: "Cameras", 31: "Door Locks"}),
    "aoscx": ("aruba_aoscx", AOSCX, {60: "OFFICE", 70: "Lab"}),
}


def _opnsense_labels(text: str) -> dict[int, str]:
    """``{tag: <descr>}`` of every ``<vlan>`` with a label, from the XML."""
    root = ElementTree.fromstring(text)
    out: dict[int, str] = {}
    for vlan in root.iter("vlan"):
        descr = (vlan.findtext("descr") or "").strip()
        if descr:
            out[int(vlan.findtext("tag") or "0")] = descr
    return out


def _routeros_labels(text: str) -> dict[int, str]:
    """``{vlan-id: comment}`` of every ``/interface vlan`` with one."""
    joined = re.sub(r"\\\r?\n\s*", "", text)
    out: dict[int, str] = {}
    section = ""
    for line in joined.splitlines():
        if line.startswith("/"):
            section = line.strip()
            continue
        if section != "/interface vlan" or not line.startswith("add "):
            continue
        comment = re.search(r'(?:^|\s)comment=("[^"]*"|\S+)', line)
        vid = re.search(r"(?:^|\s)vlan-id=(\d+)", line)
        if comment and vid and comment.group(1).strip('"').strip():
            out[int(vid.group(1))] = comment.group(1).strip('"')
    return out


def _opnsense_interface_labels(text: str) -> dict[int, str]:
    """``{tag: <descr>}`` of every assigned interface whose device is
    a ``<vlan>``'s ``<vlanif>``, from the XML: the label the interface
    has of its own."""
    root = ElementTree.fromstring(text)
    tag_of = {
        (vlan.findtext("vlanif") or "").strip(): int(vlan.findtext("tag") or "0")
        for vlan in root.iter("vlan")
    }
    out: dict[int, str] = {}
    for section in root.iter("interfaces"):
        for iface in section:
            device = (iface.findtext("if") or "").strip()
            descr = (iface.findtext("descr") or "").strip()
            if device in tag_of and descr:
                out[tag_of[device]] = descr
    return out


def _capture(path: str, reader) -> tuple[str, dict[int, str]]:
    text = (_REPO / path).read_text(encoding="utf-8")
    return text, reader(text)


CAPTURES = {
    "supergate": ("opnsense", "tests/fixtures/real/opnsense/user_contrib_supergate_opn25.xml", _opnsense_labels),
    "crs310": ("mikrotik_routeros", "tests/fixtures/real/mikrotik/user_contrib_crs310_ros7.rsc", _routeros_labels),
}


#: Onto OS10, on the plan path, the VLANs whose SVI has a label of its
#: own: the port translator makes an OPNsense VLAN's device the SVI,
#: and the interface assigned to it has a ``<descr>``.  OS10 has one
#: label for a VLAN; the SVI keeps its own, and the VLAN's label is
#: in a review line of the stanza.  Read from the XML, never from the
#: tree.
OS10_SVI_OF_ITS_OWN = {
    "opnsense": lambda: _opnsense_interface_labels(OPNSENSE),
    "supergate": lambda: _opnsense_interface_labels(_source("supergate")[1]),
}


def _source(key: str) -> tuple[str, str, dict[int, str]]:
    if key in HAND:
        return HAND[key]
    codec, path, reader = CAPTURES[key]
    text, labels = _capture(path, reader)
    return codec, text, labels


# ---------------------------------------------------------------------------
# The output read as text, a reader for each target's grammar
# ---------------------------------------------------------------------------


def _names_in_stanzas(text: str, *, quoted: bool) -> dict[int, str]:
    """``vlan <id>`` in column 0, then an indented ``name <value>``."""
    out: dict[int, str] = {}
    current: int | None = None
    for line in text.splitlines():
        head = re.fullmatch(r"vlan (\d+)\s*", line)
        if head:
            current = int(head.group(1))
            continue
        if not line[:1].isspace():
            current = None
            continue
        name = re.fullmatch(r"\s+name (.*?)\s*", line)
        if current is not None and name:
            value = name.group(1)
            if quoted:
                assert value.startswith('"') and value.endswith('"'), line
                value = value[1:-1]
            out[current] = value
    return out


def _junos_names(text: str) -> dict[int, str]:
    """``set vlans <name> vlan-id <id>``, the name quoted where it has a space."""
    out: dict[int, str] = {}
    for line in text.splitlines():
        found = re.fullmatch(r'set vlans ("[^"]*"|\S+) vlan-id (\d+)', line.strip())
        if found:
            out[int(found.group(2))] = found.group(1).strip('"')
    return out


def _os10_descriptions(text: str) -> dict[int, str]:
    """``interface vlan<id>`` in column 0 (any letter case, as the
    bare path writes the source's spelling), then an indented
    ``description <value>``: the last one, as OS10 applies them."""
    out: dict[int, str] = {}
    current: int | None = None
    for line in text.splitlines():
        head = re.fullmatch(r"interface [Vv]lan(\d+)\s*", line)
        if head:
            current = int(head.group(1))
            continue
        if not line[:1].isspace():
            current = None
            continue
        found = re.fullmatch(r" description (.*?)\s*", line)
        if current is not None and found:
            out[current] = found.group(1)
    return out


def _os10_review_names(text: str) -> dict[int, str]:
    """``{VLAN id: name}`` of each review line that says a VLAN's name
    is not its SVI's description, in the stanza of that SVI."""
    out: dict[int, str] = {}
    current: int | None = None
    for line in text.splitlines():
        head = re.fullmatch(r"interface [Vv]lan(\d+)\s*", line)
        if head:
            current = int(head.group(1))
            continue
        if not line[:1].isspace():
            current = None
            continue
        found = re.fullmatch(r" ! review: VLAN (\d+) is named (.*) in the source; .*", line)
        if current is not None and found and int(found.group(1)) == current:
            out[current] = found.group(2)
    return out


READERS = {
    "cisco_iosxe_cli": lambda text: _names_in_stanzas(text, quoted=False),
    "cisco_nxos": lambda text: _names_in_stanzas(text, quoted=False),
    "arista_eos": lambda text: _names_in_stanzas(text, quoted=False),
    "aruba_aoss": lambda text: _names_in_stanzas(text, quoted=True),
    "juniper_junos": _junos_names,
    "dell_os10": _os10_descriptions,
}


def _as_written(target: str, label: str) -> str:
    """The label as the target writes a name: EOS takes no white space."""
    return re.sub(r"\s+", "_", label) if target == "arista_eos" else label


def _render(source: str, text: str, target: str, path: str) -> str:
    if path == "bare":
        return get_codec(target).render(get_codec(source).parse(text))
    job = run_plan_with_checked_names(get_codec(source), get_codec(target), text, port_rename_map={})
    assert job.rendered, (job.status, job.error)
    return job.rendered


def _misses(source_key: str, target: str, path: str) -> list[str]:
    """What the output of one source onto one target gets wrong, read
    as text and with the target's parser."""
    source, text, labels = _source(source_key)
    out = _render(source, text, target, path)
    by_text = READERS[target](out)
    by_parser = {vlan.id: vlan.name for vlan in get_codec(target).parse(out).vlans}
    own = (
        OS10_SVI_OF_ITS_OWN[source_key]()
        if target == "dell_os10" and path == "plan" and source_key in OS10_SVI_OF_ITS_OWN
        else {}
    )
    reviewed = _os10_review_names(out) if target == "dell_os10" else {}
    misses = []
    for vid, label in sorted(labels.items()):
        want = _as_written(target, own.get(vid, label))
        if by_text.get(vid) != want:
            misses.append(f"text: VLAN {vid} is {by_text.get(vid)!r}, not {want!r}")
        if by_parser.get(vid) != want:
            misses.append(f"parser: VLAN {vid} is {by_parser.get(vid)!r}, not {want!r}")
        said = label if vid in own and own[vid] != label else None
        if reviewed.get(vid) != said:
            misses.append(f"review: VLAN {vid} says {reviewed.get(vid)!r}, not {said!r}")
    return misses


# ---------------------------------------------------------------------------
# Every public codec says which it is
# ---------------------------------------------------------------------------


def test_each_public_codec_is_a_target_or_named() -> None:
    public = set(list_public_codecs())
    assert public == set(TARGETS) | set(NOT_NAME_ONLY)
    assert not set(TARGETS) & set(NOT_NAME_ONLY)
    for name in TARGETS:
        assert get_codec(name).vlans_have_only_a_name is True, name
    for name in NOT_NAME_ONLY:
        assert get_codec(name).vlans_have_only_a_name is False, name
    assert CodecBase.vlans_have_only_a_name is False


def test_a_codec_with_a_label_of_its_own_writes_both() -> None:
    tree = get_codec("opnsense").parse(OPNSENSE)
    for name, reason in NOT_NAME_ONLY.items():
        if reason is not _LABEL_OF_ITS_OWN:
            continue
        out = get_codec(name).render(tree)
        assert "vlan0.20" in out and "Guest Wifi" in out, name


def test_a_codec_that_writes_no_vlan_name_writes_none() -> None:
    tree = get_codec("aruba_aoscx").parse(AOSCX)
    for name, reason in NOT_NAME_ONLY.items():
        if reason is _WRITES_NO_VLAN_NAME:
            assert "OFFICE" not in get_codec(name).render(tree), name


def test_a_codec_named_by_an_interface_keeps_the_interfaces_name() -> None:
    tree = get_codec("opnsense").parse(OPNSENSE)
    for name, reason in NOT_NAME_ONLY.items():
        if reason is _NAMED_BY_AN_INTERFACE:
            assert "vlan0.20" in get_codec(name).render(tree), name


# ---------------------------------------------------------------------------
# The label is the name, both paths, read as text and by the parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["bare", "plan"])
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("source_key", [*HAND, *CAPTURES])
def test_the_label_is_the_name(source_key: str, target: str, path: str) -> None:
    assert not _misses(source_key, target, path)


def test_the_captures_have_labels_to_move() -> None:
    """The readers of the captures find what the test is about."""
    for key in CAPTURES:
        assert len(_source(key)[2]) >= 2, key


def test_the_svis_of_their_own_are_read() -> None:
    """The reader of an OPNsense interface's own label finds labels
    that are not the VLAN's, or the OS10 cells test nothing."""
    for key, read in OS10_SVI_OF_ITS_OWN.items():
        own, labels = read(), _source(key)[2]
        assert own and all(own[vid] != labels[vid] for vid in own), key


@pytest.mark.parametrize("target", TARGETS)
def test_a_target_without_the_flag_misses_the_label(target: str, monkeypatch) -> None:
    monkeypatch.setattr(type(get_codec(target)), "vlans_have_only_a_name", False)
    for path in ("bare", "plan"):
        assert _misses("opnsense", target, path), path


@pytest.mark.parametrize(
    "target", ["arista_eos", "cisco_iosxe_cli", "cisco_nxos", "dell_os10", "juniper_junos"],
)
def test_the_plan_path_needs_its_own_step(target: str, monkeypatch) -> None:
    """The port translator renames ``vlan0.20`` to the target's VLAN
    interface and leaves the VLAN's name as it was, so the render's
    rule no longer finds the interface: the pipeline applies it first.
    AOS-S is not here: the translator leaves that name as it is there."""
    monkeypatch.setattr(migration_pipeline, "vlan_labels_as_names", lambda tree: tree)
    assert not _misses("opnsense", target, "bare")
    assert _misses("opnsense", target, "plan")


# ---------------------------------------------------------------------------
# What else holds
# ---------------------------------------------------------------------------


def test_a_name_of_its_own_and_its_description() -> None:
    tree = get_codec("aruba_aoscx").parse(AOSCX)
    moved = {vlan.id: (vlan.name, vlan.description) for vlan in vlan_labels_as_names(tree).vlans}
    assert moved[60] == ("OFFICE", "Second-floor")
    assert moved[70] == ("Lab", "")


def test_a_vlan_with_no_label_keeps_its_name() -> None:
    tree = get_codec("opnsense").parse(OPNSENSE)
    moved = {vlan.id: (vlan.name, vlan.description) for vlan in vlan_labels_as_names(tree).vlans}
    assert moved[60] == ("vlan0.60", "")
    assert moved[50] == ("Printers", "")


@pytest.mark.parametrize("target", TARGETS)
def test_the_render_leaves_the_tree_as_it_was(target: str) -> None:
    tree = get_codec("opnsense").parse(OPNSENSE)
    before = tree.model_dump()
    get_codec(target).render(tree)
    assert tree.model_dump() == before


@pytest.mark.parametrize("target", TARGETS)
def test_the_job_says_what_is_lost_and_not_what_moved(target: str) -> None:
    """A label written as the name is in the output; a description beside
    a name of the VLAN's own is not, and the job says so."""
    for source_key, listed in (("opnsense", False), ("routeros", False), ("aoscx", True)):
        source, text, _ = HAND[source_key]
        job = run_plan_with_checked_names(get_codec(source), get_codec(target), text, port_rename_map={})
        lossy = {issue.path for issue in job.validation.lossy_paths}
        assert ("/vlans/vlan/description" in lossy) is listed, source_key


@pytest.mark.parametrize("target", ["opnsense", "aruba_aoscx"])
def test_a_target_with_a_label_keeps_name_and_label_apart(target: str) -> None:
    out = _render("opnsense", OPNSENSE, target, "plan")
    back = {vlan.id: vlan for vlan in get_codec(target).parse(out).vlans}
    assert back[20].description == "Guest Wifi"
    assert back[20].name != "Guest Wifi"
