"""A unit of a LAG is no LAG.

``interface Port-channel1.10`` is a sub-interface of the LAG
``Port-channel1``: a routed unit with an 802.1Q tag and an address of
its own, and no LAG.  The IOS-XE CLI, NX-OS and IOS XR parsers took
every ``interface`` header that began with the LAG's prefix for a
declaration of a LAG, so the unit was also an empty LAG of its own
name, and each target wrote it as one, in jobs whose status did not
move for it: Junos an ``ae10`` with LACP, RouterOS a bonding
``bond1.10``, OPNsense a ``lagg``, FortiOS the unit itself as an LACP
aggregate (its address on an aggregate with no member, where a VLAN
on its parent was meant), and AOS-S a line saying a LAG had no
members.

Each is read here from the OUTPUT: a small config from each grammar
that has such a unit goes through the plan path the API uses onto
every public codec, and the rendered text is read for the LAGs it
declares by a reader of each target's grammar typed here, and with
the target's own parser.  The readers are handed the old parse too,
and have to find the phantom on the targets that wrote one.
"""

from __future__ import annotations

import functools
import re
import xml.etree.ElementTree as ET

import pytest

from netcanon.migration.canonical.intent import CanonicalLAG
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

PUBLIC = list_public_codecs()

#: One LAG of one member, and a routed unit of it with tag 10 and an
#: address -- in each grammar that writes such a unit.  EOS and Junos
#: were read right before; they are here so that a parser that comes
#: to read them otherwise fails too.
SOURCES = {
    "cisco_iosxe_cli": (
        "Port-channel1",
        "Port-channel1.10",
        "hostname r1\n!\ninterface GigabitEthernet1/0/1\n channel-group 1 mode active\n!\n"
        "interface Port-channel1\n no switchport\n no ip address\n!\n"
        "interface Port-channel1.10\n encapsulation dot1Q 10\n"
        " ip address 10.0.10.1 255.255.255.0\n!\nend\n",
    ),
    "cisco_nxos": (
        "port-channel1",
        "port-channel1.10",
        "hostname r1\n!\ninterface Ethernet1/1\n  channel-group 1 mode active\n!\n"
        "interface port-channel1\n  no switchport\n!\n"
        "interface port-channel1.10\n  encapsulation dot1q 10\n  ip address 10.0.10.1/24\n!\n",
    ),
    "cisco_iosxr": (
        "Bundle-Ether1",
        "Bundle-Ether1.10",
        "hostname r1\ninterface TenGigE0/0/0/1\n bundle id 1 mode active\n!\n"
        "interface Bundle-Ether1\n!\ninterface Bundle-Ether1.10\n encapsulation dot1q 10\n"
        " ipv4 address 10.0.10.1 255.255.255.0\n!\nend\n",
    ),
    "arista_eos": (
        "Port-Channel1",
        "Port-Channel1.10",
        "hostname r1\n!\ninterface Ethernet1\n   channel-group 1 mode active\n!\n"
        "interface Port-Channel1\n   no switchport\n!\n"
        "interface Port-Channel1.10\n   encapsulation dot1q vlan 10\n"
        "   ip address 10.0.10.1/24\n!\n",
    ),
    "juniper_junos": (
        "ae1",
        "ae1.10",
        "set system host-name r1\n"
        "set interfaces ge-0/0/1 ether-options 802.3ad ae1\n"
        "set interfaces ae1 aggregated-ether-options lacp active\n"
        "set interfaces ae1 vlan-tagging\n"
        "set interfaces ae1 unit 10 vlan-id 10\n"
        "set interfaces ae1 unit 10 family inet address 10.0.10.1/24\n",
    ),
}


# ---------------------------------------------------------------------------
# What each target's text declares a LAG with, typed from its grammar
# ---------------------------------------------------------------------------


def _numbered(header: str, member: str):
    """A reader of the LAG numbers a text declares: an ``interface``
    header that names a LAG and nothing after its number, or a member
    port's line that puts it into one (``channel-group 1`` makes
    ``Port-channel1`` where no header does)."""
    headers = re.compile(rf"^interface {header}(\d+)[ \t]*$", re.MULTILINE | re.IGNORECASE)
    members = re.compile(rf"^[ \t]+{member}(\d+)\b", re.MULTILINE)
    return lambda text: {m.group(1) for m in headers.finditer(text)} | {
        m.group(1) for m in members.finditer(text)
    }


def _junos(text: str) -> set[str]:
    """``aggregated-ether-options`` on a device, or a port bundled into one."""
    own = re.findall(r"^set interfaces (\S+) aggregated-ether-options\b", text, re.MULTILINE)
    bundled = re.findall(r"^set interfaces \S+ ether-options 802\.3ad (\S+)$", text, re.MULTILINE)
    return set(own) | set(bundled)


def _routeros(text: str) -> set[str]:
    """Every ``add`` of the ``/interface bonding`` menu."""
    names: set[str] = set()
    menu = ""
    for line in text.splitlines():
        if line.startswith("/"):
            menu = line.strip()
        elif menu == "/interface bonding" and line.startswith("add "):
            m = re.search(r'\bname=("?)([^"\s]+)\1', line)
            names.add(m.group(2) if m else line)
    return names


def _opnsense(text: str) -> set[str]:
    return {el.text or "" for el in ET.fromstring(text).iter("laggif")}


def _fortios(text: str) -> set[str]:
    """Every ``edit`` of ``config system interface`` set ``type aggregate``."""
    names: set[str] = set()
    name = None
    for line in text.splitlines():
        m = re.match(r'^\s*edit "([^"]*)"', line)
        if m:
            name = m.group(1)
        elif line.strip() == "set type aggregate" and name is not None:
            names.add(name)
        elif line.strip() == "next":
            name = None
    return names


def _aoss(text: str) -> set[str]:
    """A ``trunk <ports> trkN`` line, or the renderer's own word that
    there was a LAG it could not write."""
    trunks = re.findall(r"^trunk \S+ (trk\d+)\b", text, re.MULTILINE | re.IGNORECASE)
    unwritten = re.findall(r"^; LAG (\S+) declared without members", text, re.MULTILINE)
    return {t.lower() for t in trunks} | set(unwritten)


def _vyos(text: str) -> set[str]:
    return set(re.findall(r"^\s*bonding (\S+) \{", text, re.MULTILINE)) | set(
        re.findall(r"^set interfaces bonding (\S+)", text, re.MULTILINE)
    )


LAGS_IN = {
    "arista_eos": _numbered("Port-Channel", "channel-group "),
    "aruba_aoscx": _numbered("lag ", "lag "),
    "aruba_aoss": _aoss,
    "cisco_iosxe_cli": _numbered("Port-channel", "channel-group "),
    "cisco_iosxr": _numbered("Bundle-Ether", "bundle id "),
    "cisco_nxos": _numbered("port-channel", "channel-group "),
    "dell_os10": _numbered("port-channel", "channel-group "),
    "fortigate_cli": _fortios,
    "juniper_junos": _junos,
    "mikrotik_routeros": _routeros,
    "opnsense": _opnsense,
    "vyos": _vyos,
}

#: Targets that write no LAG: the IOS-XE NETCONF codec models no
#: membership, and its parser reads none back.
WRITES_NO_LAG = {"cisco_iosxe"}


@functools.cache
def _plan(source: str, target: str) -> MigrationJob:
    return run_plan_with_checked_names(
        get_codec(source), get_codec(target), SOURCES[source][2], port_rename_map={},
    )


def test_every_target_has_a_reader_or_is_named() -> None:
    assert set(LAGS_IN) | WRITES_NO_LAG == set(PUBLIC)
    assert not set(LAGS_IN) & WRITES_NO_LAG


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_the_parser_reads_one_lag_and_a_unit(source: str) -> None:
    lag, unit, text = SOURCES[source]
    tree = get_codec(source).parse(text)
    assert [entry.name for entry in tree.lags] == [lag]
    (record,) = [i for i in tree.interfaces if i.name == unit]
    assert record.dot1q_vlan == 10
    assert [str(a.ip) for a in record.ipv4_addresses] == ["10.0.10.1"]


@pytest.mark.parametrize("target", PUBLIC)
@pytest.mark.parametrize("source", sorted(SOURCES))
def test_the_output_declares_one_lag(source: str, target: str) -> None:
    job = _plan(source, target)
    rendered = job.rendered or ""
    read_back = get_codec(target).parse(rendered).lags
    if target in WRITES_NO_LAG:
        assert read_back == []
        return
    assert len(LAGS_IN[target](rendered)) == 1, LAGS_IN[target](rendered)
    names = [entry.name for entry in read_back]
    if job.unresolved_ports:
        # The member has no place on the target, and the job lists it:
        # AOS-S writes no trunk without a port, and reads no LAG back.
        assert len(read_back) <= 1, names
    else:
        assert len(read_back) == 1, names
        assert read_back[0].members


# ---------------------------------------------------------------------------
# The check, handed the parse it was written for
# ---------------------------------------------------------------------------


#: Where the old parse put a second LAG into the output's text.  On the
#: others the unit's header and the LAG's were one stanza, or the target
#: writes a unit by its name alone.
PHANTOM_WRITTEN = {
    "aruba_aoss",
    "fortigate_cli",
    "juniper_junos",
    "mikrotik_routeros",
    "opnsense",
}


def _the_old_parse(source: str):
    """The source codec, reading the unit as a LAG as well, as the
    parser did before."""
    codec = get_codec(source)
    unit = SOURCES[source][1]

    class OldParse(type(codec)):
        def parse(self, text, *args, **kwargs):
            tree = super().parse(text, *args, **kwargs)
            tree.lags.append(CanonicalLAG(name=unit))
            return tree

    return OldParse()


@pytest.mark.parametrize("source", ["cisco_iosxe_cli", "cisco_nxos", "cisco_iosxr"])
def test_the_readers_find_the_phantom_where_it_was_written(source: str) -> None:
    found = set()
    for target in sorted(LAGS_IN):
        job = run_plan_with_checked_names(
            _the_old_parse(source), get_codec(target), SOURCES[source][2],
            port_rename_map={},
        )
        if len(LAGS_IN[target](job.rendered or "")) != 1:
            found.add(target)
    assert found == PHANTOM_WRITTEN
