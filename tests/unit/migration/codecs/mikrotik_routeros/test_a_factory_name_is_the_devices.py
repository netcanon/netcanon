"""A RouterOS port is looked up by the name the device gave it, and by no other.

``set [ find default-name=<name> ]`` finds a port by the name the device
gave it, whatever the port has since been called; a name the device did
not give finds nothing.  The parser recorded such a name only for a ``set
[ find default-name= ]`` line, or for a name that BEGAN ``ether`` and a
digit, in any case:

* an SFP, SFP+, SFP28 or combo port the config names only in ``/ip
  address``, a bonding's ``slaves=`` or a VRRP's ``interface=`` -- an
  export writes no ``/interface ethernet`` line for a port with nothing
  set on it -- had none, so an entry that gave it a name of its own was
  written ``set [ find name=<new> ]``, a lookup no device matches, in a
  job that said ``completed``;
* a name an operator chose -- ``ether1_ADMIN``, ``ether2-master``,
  ``Ether1`` -- was taken for a factory name and written ``find
  default-name=ether1_ADMIN``, which matches nothing either.

And the classifier read ``SFP-SFPPLUS1`` and ``Ether1`` as ports, and
``sfp28-1``, ``combo1`` and ``qsfp28-1-1`` as nothing at all.

The shapes are typed here by hand, from MikroTik's pages and an export
of a real device (the sources are listed at
``port_names.is_factory_port_name``), and the output is read as text,
by a reader of the lookup line of its own -- never the RouterOS parser.

See also ``netcanon/migration/codecs/mikrotik_routeros/port_names.py``
and ``parse.py`` (``_name_the_hardware``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import netcanon.migration.codecs  # noqa: F401  (registers the codecs)
from netcanon.migration.codecs.mikrotik_routeros import parse as ros_parse
from netcanon.migration.codecs.mikrotik_routeros import render as ros_render
from netcanon.migration.codecs.mikrotik_routeros.port_names import (
    classify_port_name,
    format_port_identity,
    is_factory_port_name,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
ROS = get_codec("mikrotik_routeros")

# ---------------------------------------------------------------------------
# What MikroTik shows, typed by hand
# ---------------------------------------------------------------------------

#: Names a MikroTik device gives its own ports, each as a page of the
#: RouterOS manual or an export of a real device shows it.
FACTORY = (
    "ether1",         # "Default configurations"; "Ethernet"
    "ether24",
    "sfp1",           # "Default configurations"
    "sfp3",           # "Ethernet"
    "combo1",         # "Default configurations"
    "sfp-sfpplus1",   # "Ethernet"
    "sfp-sfpplus12",
    "sfp28-1",        # export of a CCR2004-1G-12S+2XS, forum thread 266127
    "sfp28-2",
    "qsfpplus1-1",    # "MikroTik wired interface compatibility"
    "qsfpplus1-4",
    "qsfp28-1-1",     # "Ethernet"; "MikroTik wired interface compatibility"
    "qsfp28-2-1",
    "qsfp56-1-1",     # "MikroTik wired interface compatibility"
    "qsfp56-dd-1-8",
)

#: Names that are not: an operator's, or a shape nobody has shown.
NOT_FACTORY = (
    "ether1_ADMIN",    # an operator's name, in that same export
    "sfp28-1_UPLINK",  # the same kind
    "ether2-master",
    "Ether1",          # RouterOS names are free text, and in their own case
    "SFP-SFPPLUS1",
    "sfpplus1",        # read as a port by the classifier, shown by nothing
    "qsfpplus1",       # likewise: every name shown for QSFP is a lane
    "qsfp28-1",
    "ether",
    "ether1.10",
    "vlan10",
    "bond1",
    "bridge",
)

#: The shapes the classifier reads as a port of its own.  ``qsfp56``
#: is a factory name it has no speed for, and reads as nothing.
CLASSIFIED = tuple(n for n in FACTORY if not n.startswith("qsfp56"))


@pytest.mark.parametrize("name", FACTORY)
def test_a_name_the_device_gives_is_a_factory_name(name: str) -> None:
    assert is_factory_port_name(name)


@pytest.mark.parametrize("name", NOT_FACTORY)
def test_a_name_an_operator_gives_is_not(name: str) -> None:
    assert not is_factory_port_name(name)


@pytest.mark.parametrize("name", CLASSIFIED)
def test_the_classifier_reads_each_port_and_writes_it_back(name: str) -> None:
    identity = classify_port_name(name)
    assert identity.kind in ("physical", "breakout"), identity
    assert format_port_identity(identity) == name


@pytest.mark.parametrize("name", ("Ether1", "SFP-SFPPLUS1", "Sfp28-1", "COMBO1"))
def test_a_name_in_another_case_is_no_port(name: str) -> None:
    assert classify_port_name(name).kind == "unknown"


# ---------------------------------------------------------------------------
# The output, read as text
# ---------------------------------------------------------------------------

#: ``set [ find default-name=<x> ] ...`` or ``set [ find name=<x> ] ...``,
#: and the ``name=`` the line gives the port, if it gives one.
_LOOKUP_RE = re.compile(
    r"^set \[ find (?P<key>default-name|name)=(?P<value>\S+) \]"
    r"(?: name=(?P<new>\S+))?"
)


def _lookups(text: str) -> list[tuple[str, str, str | None]]:
    return [
        (m["key"], m["value"], m["new"])
        for line in text.splitlines()
        if (m := _LOOKUP_RE.match(line))
    ]


#: Where a config names a port with no line of its own.
WHERE = {
    "address": "/ip address\nadd address=10.0.0.1/24 interface={name} network=10.0.0.0\n",
    "slaves": "/interface bonding\nadd mode=802.3ad name=bond1 slaves={name}\n",
    "vrrp": (
        "/interface vrrp\nadd interface={name} name=vrrp1 vrid=1\n"
        "/ip address\nadd address=10.0.0.1/24 interface={name} network=10.0.0.0\n"
        "add address=10.0.0.254/24 interface=vrrp1 network=10.0.0.0\n"
    ),
}


def _entry_findings(name: str, where: str) -> list[str]:
    """What is wrong with the output when an entry names a port the
    config names only *where*."""
    text = WHERE[where].format(name=name)
    job = run_plan_with_checked_names(ROS, ROS, text, port_rename_map={name: "uplink"})
    if job.status is MigrationJobStatus.failed:
        return [f"failed: {job.error}"]
    out = job.rendered or ""
    found = _lookups(out)
    wrong = []
    if ("default-name", name, "uplink") not in found:
        wrong.append(f"no line finds {name} by its factory name and names it uplink: {found}")
    if any(key == "name" and value == "uplink" for key, value, _ in found):
        wrong.append("a line looks up `uplink`, which no device has")
    return wrong


@pytest.mark.parametrize("where", sorted(WHERE))
@pytest.mark.parametrize("name", FACTORY)
def test_an_entry_finds_the_port_by_its_factory_name(name: str, where: str) -> None:
    assert _entry_findings(name, where) == []


def _operator_findings(name: str) -> list[str]:
    """What is wrong with the output for a port the operator named."""
    text = WHERE["address"].format(name=name)
    job = run_plan_with_checked_names(ROS, ROS, text)
    found = _lookups(job.rendered or "")
    return [
        f"{name} is looked up as a factory name: {found}"
        for key, value, _ in found
        if key == "default-name" and value == name
    ]


@pytest.mark.parametrize("name", [n for n in NOT_FACTORY if n.startswith(("ether", "Ether", "sfp", "SFP", "qsfp"))])
def test_an_operators_name_is_not_looked_up_as_hardware(name: str) -> None:
    assert _operator_findings(name) == []


@pytest.mark.parametrize("name", ("ether1", "sfp-sfpplus1"))
def test_a_line_that_still_uses_a_renamed_ports_factory_name(name: str) -> None:
    """After ``set [ find default-name=<x> ] name=wan`` a line that
    still says ``interface=<x>`` -- a hand-merged file -- is a second
    record that looks the port up, for an SFP port as for ``ether1``:
    the mapping onto a declared device refuses to pair the two
    (``TestOneFactoryNameOnTwoInterfaces``)."""
    tree = ROS.parse(
        f"/interface ethernet\nset [ find default-name={name} ] name=wan\n"
        f"/ip address\nadd address=10.0.0.1/24 interface={name} network=10.0.0.0\n"
    )
    held = sorted((i.name, i.default_name) for i in tree.interfaces if i.default_name)
    assert held == [(name, name), ("wan", name)]


def test_a_vlan_named_like_a_port_is_no_port() -> None:
    tree = ROS.parse(
        "/interface vlan\nadd interface=ether1 name=ether5 vlan-id=5\n"
        "/ip address\nadd address=10.0.0.1/24 interface=ether5 network=10.0.0.0\n"
    )
    by_name = {i.name: i.default_name for i in tree.interfaces}
    assert by_name["ether5"] == ""


def test_a_port_from_elsewhere_is_translated() -> None:
    """``sfp28-1`` is a port onto another vendor; ``SFP-SFPPLUS1`` is a
    name the translator cannot read, and the job says so.  (An empty
    map is the automatic translation the API asks for.)"""
    text = (
        "/ip address\nadd address=10.0.0.1/24 interface=sfp28-1 network=10.0.0.0\n"
        "add address=10.0.1.1/24 interface=SFP-SFPPLUS1 network=10.0.1.0\n"
    )
    job = run_plan_with_checked_names(ROS, get_codec("cisco_iosxe_cli"), text, port_rename_map={})
    assert "sfp28-1" not in job.untranslated_ports
    assert "SFP-SFPPLUS1" in job.untranslated_ports
    assert job.status is MigrationJobStatus.partial


# ---------------------------------------------------------------------------
# Every capture
# ---------------------------------------------------------------------------

#: The factory shapes again, for the captures, typed apart from the
#: module's own pattern.
_HAND = re.compile(
    r"ether[0-9]+|sfp[0-9]+|combo[0-9]+|sfp-sfpplus[0-9]+|sfp28-[0-9]+"
    r"|qsfpplus[0-9]+-[0-9]+|qsfp28-[0-9]+-[0-9]+|qsfp56-(?:dd-)?[0-9]+-[0-9]+"
)
CAPTURES = sorted((FIXTURES / "real" / "mikrotik").glob("*.rsc"))


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.name)
def test_every_capture_every_port_by_its_factory_name(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    tree = ROS.parse(text)
    ports = [
        i.name for i in tree.interfaces
        if _HAND.fullmatch(i.name) and i.interface_type in ("", "ianaift:ethernetCsmacd")
    ]
    entries = {name: f"p{n}" for n, name in enumerate(ports)}
    job = run_plan_with_checked_names(ROS, ROS, text, port_rename_map=entries)
    found = _lookups(job.rendered or "")
    missing = [
        name for name, new in entries.items()
        if ("default-name", name, new) not in found
    ]
    assert missing == [], found


# ---------------------------------------------------------------------------
# The check, handed the old code
# ---------------------------------------------------------------------------


def test_the_check_sees_the_old_parse_and_render(monkeypatch) -> None:
    def as_before(name: str) -> bool:
        return bool(re.match(r"^ether\d", name, re.IGNORECASE))

    monkeypatch.setattr(ros_parse, "is_factory_port_name", as_before)
    monkeypatch.setattr(ros_render, "is_factory_port_name", as_before)
    assert _entry_findings("sfp-sfpplus1", "address")
    assert _entry_findings("combo1", "slaves")
    assert _operator_findings("ether2-master")
    assert _operator_findings("Ether1")


# ---------------------------------------------------------------------------
# Still open
# ---------------------------------------------------------------------------


def test_still_open_an_entry_for_a_port_with_no_factory_name() -> None:
    """A port known only by an operator's name has no factory name to
    look it up by, and the tree keeps no other: an entry that renames
    it is written as a lookup of the NEW name, which no device has.
    Pinned so that the change that mends it takes this out."""
    text = WHERE["address"].format(name="ether2-master")
    job = run_plan_with_checked_names(ROS, ROS, text, port_rename_map={"ether2-master": "wan"})
    assert ("name", "wan", None) in _lookups(job.rendered or "")
