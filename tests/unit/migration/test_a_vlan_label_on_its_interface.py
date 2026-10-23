"""Onto RouterOS and FortiOS a VLAN's label is its interface's label.

On RouterOS and FortiOS a VLAN is an interface (``/interface vlan``,
``set type vlan``), named as one and labelled as one, with ``comment=``
or ``set alias``.  The two renderers wrote the interface's own
description there and nothing else, so a VLAN's label was lost
wherever the VLAN has an interface: IOS-XE ``vlan 10`` / ``name USERS``
beside ``interface Vlan10`` came out with no ``USERS``, and every
OPNsense ``<descr>`` was lost on both (on RouterOS since the OPNsense
VLAN device became an interface of the tree), in jobs that said
``completed``.  FortiOS also wrote no label for a VLAN it makes an
interface for, and its matrix listed ``/vlans/vlan/name`` as supported.

Now the interface's own description is written where it states one,
and otherwise the VLAN's label (``_vlan_labels.vlan_labels``); where
the interface has a description of its own, the label is written in a
``# review:`` line beside it.  The FortiOS parser reads the alias of a
VLAN interface back as the VLAN's description, as the RouterOS parser
reads ``comment=``.

The label is a VLAN's name only where the config chose it.  OPNsense,
RouterOS and FortiOS name a VLAN after its interface, and the port
translator renames the interface and not the VLAN: after it, OPNsense's
``vlan0.60`` names no interface, and the tree alone cannot tell it from
a name an operator chose.  So the platform the tree was parsed from
says it (``NAMES_A_VLAN_AFTER_ITS_INTERFACE``), and the set is held
equal to the parsers that do so on the committed captures.

The output is read with a reader typed here for each grammar and with
the target's parser, and each check is handed the renderer as it was.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration import _vlan_labels
from netcanon.migration.codecs.fortigate_cli import render as fortios_render
from netcanon.migration.codecs.mikrotik_routeros import render as routeros_render
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_pipeline import run_plan_with_checked_names
from tests.unit.migration.test_a_vlan_label_is_its_name import _names_in_stanzas
from tests.unit.migration.test_vlan_members_reach_the_output import _captures

pytestmark = pytest.mark.unit

TARGETS = ("mikrotik_routeros", "fortigate_cli")

# ---------------------------------------------------------------------------
# Sources, typed by hand, with what each target is to write for them
# ---------------------------------------------------------------------------

#: VLAN 10 has an SVI with no description, VLAN 20 none, VLAN 30 one
#: with a description of its own, VLAN 40 one whose description is the
#: VLAN's name.
IOSXE = """hostname sw1
!
vlan 10
 name USERS
!
vlan 20
 name VOICE
!
vlan 30
 name CAMERAS
!
vlan 40
 name SAME
!
interface Vlan10
 ip address 192.0.2.1 255.255.255.0
!
interface Vlan30
 description camera gateway
 ip address 198.51.100.1 255.255.255.0
!
interface Vlan40
 description SAME
 ip address 203.0.113.1 255.255.255.0
!
"""

#: A VLAN with a name and a description (called by its name), one with
#: a description alone, and VLAN 1 with neither.
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
"""

#: VLAN 20 has a device assigned to an interface with a ``<descr>`` of
#: its own, VLAN 40 a device and no assignment, VLAN 50 no device, VLAN
#: 60 a device and no label: its name ``vlan0.60`` is no label, on
#: either path.
OPNSENSE_ON_A_PORT = """<?xml version="1.0"?>
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

#: The same VLAN devices on a bridge, where each is a VLAN interface
#: and a VLAN; on the port above each is a sub-interface of it.
OPNSENSE = OPNSENSE_ON_A_PORT.replace("<if>igb1</if><tag>", "<if>bridge0</if><tag>").replace(
    "  <vlans ",
    "  <bridges>\n    <bridged><members>lan</members><bridgeif>bridge0</bridgeif></bridged>\n"
    "  </bridges>\n  <vlans ",
)

ROUTEROS = """/interface vlan
add comment=Cameras interface=ether2 name=vlan30 vlan-id=30
add comment="Door Locks" interface=ether2 name=locks vlan-id=31
add interface=ether2 name=vlan32 vlan-id=32
/ip address
add address=198.51.100.65/26 interface=vlan30
"""

FORTIOS = """config system global
    set hostname "fw1"
end
config system interface
    edit "port1"
        set vdom "root"
        set ip 192.0.2.1 255.255.255.0
        set type physical
    next
    edit "VL_100"
        set vdom "root"
        set alias "Users"
        set interface "port1"
        set vlanid 100
    next
    edit "VL_200"
        set vdom "root"
        set interface "port1"
        set vlanid 200
    next
end
"""

#: The same VLAN interfaces on a hardware switch, where FortiOS makes
#: a VLAN of each; on the port above each is a sub-interface of it.
FORTIOS_ON_A_SWITCH = FORTIOS.replace('"port1"', '"internal"').replace(
    "set type physical", "set type hard-switch",
)

#: ``(source codec, text, {VLAN id: (the label written, the label in a
#: review line)})``.  ``None`` is none written.
SOURCES = {
    "iosxe": ("cisco_iosxe_cli", IOSXE, {
        10: ("USERS", None),
        20: ("VOICE", None),
        30: ("camera gateway", "CAMERAS"),
        40: ("SAME", None),
    }),
    "aoscx": ("aruba_aoscx", AOSCX, {1: (None, None), 60: ("OFFICE", None), 70: ("Lab", None)}),
    "opnsense": ("opnsense", OPNSENSE, {
        20: ("GUEST", "Guest Wifi"),
        40: ("Spare", None),
        50: ("Printers", None),
        60: (None, None),
    }),
    # On a port, VLAN 20's device is a sub-interface labelled by its
    # zone, and the device's own label is in a row of the job.
    "opnsense_port": ("opnsense", OPNSENSE_ON_A_PORT, {
        20: ("GUEST", None),
        40: ("Spare", None),
        50: ("Printers", None),
        60: (None, None),
    }),
    "routeros": ("mikrotik_routeros", ROUTEROS, {
        30: ("Cameras", None),
        31: ("Door Locks", None),
        32: (None, None),
    }),
    "fortios": ("fortigate_cli", FORTIOS, {100: ("Users", None), 200: (None, None)}),
    "fortios_switch": (
        "fortigate_cli", FORTIOS_ON_A_SWITCH, {100: ("Users", None), 200: (None, None)},
    ),
}

# ---------------------------------------------------------------------------
# The output read as text, a reader for each target's grammar
# ---------------------------------------------------------------------------

_ROUTEROS_REVIEW = re.compile(r"# review: VLAN (\d+) is called (.*) in the source; RouterOS ")
_FORTIOS_REVIEW = re.compile(r"\s+# review: VLAN (\d+) is called (.*) in the source; FortiOS ")


def _routeros_read(text: str) -> tuple[dict[int, str], dict[int, str]]:
    """``{vlan-id: comment}`` of every ``/interface vlan`` line with one,
    and ``{vlan-id: label}`` of every review line in that section."""
    joined = re.sub(r"\\\r?\n\s*", "", text)
    labels: dict[int, str] = {}
    reviews: dict[int, str] = {}
    section = ""
    for line in joined.splitlines():
        if line.startswith("/"):
            section = line.strip()
            continue
        if section != "/interface vlan":
            continue
        review = _ROUTEROS_REVIEW.match(line)
        if review:
            reviews[int(review.group(1))] = review.group(2)
            continue
        if not line.startswith("add "):
            continue
        comment = re.search(r'(?:^|\s)comment=("(?:[^"\\]|\\.)*"|\S+)', line)
        vid = re.search(r"(?:^|\s)vlan-id=(\d+)", line)
        if comment and vid:
            value = comment.group(1)
            if value.startswith('"'):
                value = re.sub(r"\\(.)", r"\1", value[1:-1])
            if value.strip():
                labels[int(vid.group(1))] = value
    return labels, reviews


def _fortios_read(text: str) -> tuple[dict[int, str], dict[int, str]]:
    """``{vlanid: alias}`` of every ``edit`` of ``config system
    interface`` with a ``set vlanid`` and a ``set alias``, and
    ``{vlanid: label}`` of every review line naming a VLAN there."""
    labels: dict[int, str] = {}
    reviews: dict[int, str] = {}
    inside = False
    alias: str | None = None
    vid: int | None = None
    for line in text.splitlines():
        if line == "config system interface":
            inside = True
            continue
        if not inside:
            continue
        if line == "end":
            break
        if re.fullmatch(r'    edit "(?:[^"\\]|\\.)*"', line):
            alias, vid = None, None
            continue
        if line == "    next":
            if vid is not None and alias:
                labels[vid] = alias
            continue
        found = re.fullmatch(r'        set alias "((?:[^"\\]|\\.)*)"', line)
        if found:
            alias = re.sub(r"\\(.)", r"\1", found.group(1))
            continue
        found = re.fullmatch(r"        set vlanid (\d+)", line)
        if found:
            vid = int(found.group(1))
            continue
        review = _FORTIOS_REVIEW.match(line)
        if review:
            reviews[int(review.group(1))] = review.group(2)
    return labels, reviews


READERS = {"mikrotik_routeros": _routeros_read, "fortigate_cli": _fortios_read}


def _render(source_key: str, target: str, path: str) -> str:
    source, text, _ = SOURCES[source_key]
    if path == "bare":
        return get_codec(target).render(get_codec(source).parse(text))
    job = run_plan_with_checked_names(
        get_codec(source), get_codec(target), text, port_rename_map={},
    )
    assert job.rendered, (job.status, job.error)
    return job.rendered


def _misses(source_key: str, target: str, path: str) -> list[str]:
    """Every way the output departs from what is wanted, read three
    ways: the label by text, the review line by text, the label by the
    target's parser (the VLAN's description, or, for a VLAN interface
    on a port, which is read back as a sub-interface of it and no
    VLAN, the sub-interface's)."""
    out = _render(source_key, target, path)
    labels, reviews = READERS[target](out)
    tree = get_codec(target).parse(out)
    parsed = {}
    for vlan in tree.vlans:
        parsed.setdefault(vlan.id, vlan.description)
    for iface in tree.interfaces:
        if iface.dot1q_vlan is not None and iface.interface_type != "ianaift:l3ipvlan":
            parsed.setdefault(iface.dot1q_vlan, iface.description)
    misses = []
    for vid, (label, review) in SOURCES[source_key][2].items():
        if labels.get(vid) != label:
            misses.append(f"VLAN {vid}: label {labels.get(vid)!r}, want {label!r}")
        if reviews.get(vid) != review:
            misses.append(f"VLAN {vid}: review {reviews.get(vid)!r}, want {review!r}")
        if (parsed.get(vid) or None) != label:
            misses.append(f"VLAN {vid}: parsed {parsed.get(vid)!r}, want {label!r}")
    return misses


# ---------------------------------------------------------------------------
# The label is the interface's, both paths, read as text and by the parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["bare", "plan"])
@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("source_key", sorted(SOURCES))
def test_each_label_is_on_its_interface(source_key: str, target: str, path: str) -> None:
    assert _misses(source_key, target, path) == []


def test_the_check_sees_the_renderer_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no label read for a VLAN, as both renderers had it, the
    IOS-XE source misses its labels on both targets."""
    for module in (routeros_render, fortios_render):
        monkeypatch.setattr(module, "vlan_labels", lambda tree: {})
    for target in TARGETS:
        assert _misses("iosxe", target, "bare"), target


def test_the_check_sees_a_name_read_from_the_tree_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asked of the tree alone, the plan path takes OPNsense's
    ``vlan0.60``, which the port translator has left naming no
    interface, for a name an operator chose."""
    monkeypatch.setattr(_vlan_labels, "NAMES_A_VLAN_AFTER_ITS_INTERFACE", frozenset())
    for target in TARGETS:
        misses = _misses("opnsense", target, "plan")
        assert any(m.startswith("VLAN 60: label 'vlan0.60'") for m in misses), (target, misses)
    for target in TARGETS:
        assert _misses("opnsense", target, "bare") == [], target


# ---------------------------------------------------------------------------
# The platforms that name a VLAN after its interface, measured
# ---------------------------------------------------------------------------


def test_the_platforms_that_name_a_vlan_after_its_interface() -> None:
    """The set is the parsers that do so on the committed captures and
    on the sources typed here, and each of them does so for every VLAN
    it names: on such a tree no name is a label the rule throws away.
    The sources are read as well because no FortiOS capture has a
    VLAN interface on a switch, the one place FortiOS makes a VLAN."""
    after: set[str] = set()
    chosen: set[str] = set()
    texts = [(codec, path.read_text(encoding="utf-8")) for codec, _rel, path in _captures()]
    texts += [(codec, text) for codec, text, _ in SOURCES.values()]
    for codec, text in texts:
        tree = get_codec(codec).parse(text)
        names = {iface.name for iface in tree.interfaces}
        for vlan in tree.vlans:
            if not vlan.name.strip():
                continue
            (after if vlan.name in names else chosen).add(tree.source_vendor)
    assert after == set(_vlan_labels.NAMES_A_VLAN_AFTER_ITS_INTERFACE)
    assert not after & chosen, after & chosen


# ---------------------------------------------------------------------------
# What a FortiOS alias is read as, and the two codecs onto themselves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["bare", "plan"])
def test_a_fortios_alias_is_the_vlans_name_onto_iosxe(path: str) -> None:
    """The parser reads the alias as the VLAN's label, so a target whose
    VLAN has only a name writes it as the name."""
    out = _render("fortios_switch", "cisco_iosxe_cli", path)
    assert _names_in_stanzas(out, quoted=False).get(100) == "Users"


def test_on_a_port_the_alias_is_the_sub_interfaces_description() -> None:
    """On a port the VLAN interface is a sub-interface of it, and no
    VLAN: its alias is the sub-interface's description, after its port
    (the plan path; the bare path translates no name)."""
    out = _render("fortios", "cisco_iosxe_cli", "plan")
    assert _names_in_stanzas(out, quoted=False) == {}
    assert re.search(
        r"^interface GigabitEthernet0/1\.100\n description Users\n encapsulation dot1Q 100\n",
        out, re.M,
    ), out


@pytest.mark.parametrize(
    ("codec", "rel", "path"),
    [c for c in _captures() if c[0] in TARGETS],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_committed_input_onto_its_own_codec_keeps_its_labels(codec, rel, path) -> None:
    """No review line, and each VLAN interface labelled as it was."""
    text = path.read_text(encoding="utf-8")
    out = get_codec(codec).render(get_codec(codec).parse(text))
    labels, reviews = READERS[codec](out)
    assert reviews == {}
    assert labels == READERS[codec](text)[0]
