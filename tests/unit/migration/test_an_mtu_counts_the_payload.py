"""An interface's MTU is one number, read and written as each platform counts it.

The tree's ``CanonicalInterface.mtu`` counts the payload: the largest IP
packet the interface carries, with no Ethernet header, tag or FCS -- the
number IOS-XE, NX-OS, EOS and AOS-CX print for the link.  Three
platforms count more.  A Junos media MTU and an IOS XR ``mtu`` count
the 14-byte Ethernet header, and the tag on a tagged interface; a Dell
OS10 link MTU is a frame, header and FCS included.  Every codec copied
the number as it stood, so Junos ``mtu 1514`` -- its own default -- was
IOS-XE ``mtu 1514``, an IP MTU 14 bytes larger, and IOS-XE ``mtu 9000``
was Junos ``mtu 9000``, an IP MTU of 8986, in jobs that said
``completed``.  Every check agreed: the target's parser read back the
number the renderer had written, and the cross-mesh audit compares two
trees that both held the copied number.

So the offsets are typed here by hand, from the vendors' sentences
(``docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/mtu.md``),
and each output is read as TEXT by a reader written here for its
grammar -- not with the target's parser, which shares the codec's
reading of its own number.  The table in ``codecs/_helpers.py`` is held
to the hand-typed one for equality, and each check is handed the defect
it is for.
"""

from __future__ import annotations

import re

import pytest

from netcanon.migration.codecs import _helpers
from netcanon.migration.codecs._helpers import MTU_BEYOND_THE_PAYLOAD, MtuCounts
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

#: What each platform's ``mtu`` counts beyond the payload: (bytes on an
#: untagged Ethernet interface, bytes more for each 802.1Q tag), typed
#: by hand from the vendors' sentences.
_BY_HAND: dict[str, tuple[int, int]] = {
    "arista_eos": (0, 0),
    "aruba_aoscx": (0, 0),
    "cisco_iosxe_cli": (0, 0),
    "cisco_iosxr": (14, 4),
    "cisco_nxos": (0, 0),
    "dell_os10": (22, 0),
    "fortigate_cli": (0, 0),
    "juniper_junos": (14, 4),
    "mikrotik_routeros": (0, 0),
    "opnsense": (0, 0),
    "vyos": (0, 0),
}

#: The codecs that read and write no interface MTU, with the reason.
NO_INTERFACE_MTU: dict[str, str] = {
    "aruba_aoss": "no per-interface MTU: the frame size and the IP MTU are global `jumbo` settings",
    "cisco_iosxe": "OpenConfig's config/mtu is read into the codec's own record and not carried to the tree",
}

#: Each target's ``mtu`` lines, as its grammar writes them: one group,
#: the number.  Written here, not taken from a codec.
_MTU_LINE: dict[str, re.Pattern[str]] = {
    "arista_eos": re.compile(r"^[ \t]+mtu[ \t]+(\d+)[ \t]*$", re.MULTILINE),
    "aruba_aoscx": re.compile(r"^[ \t]+mtu[ \t]+(\d+)[ \t]*$", re.MULTILINE),
    "cisco_iosxe_cli": re.compile(r"^[ \t]+mtu[ \t]+(\d+)[ \t]*$", re.MULTILINE),
    "cisco_iosxr": re.compile(r"^[ \t]+mtu[ \t]+(\d+)[ \t]*$", re.MULTILINE),
    "cisco_nxos": re.compile(r"^[ \t]+mtu[ \t]+(\d+)[ \t]*$", re.MULTILINE),
    "dell_os10": re.compile(r"^[ \t]+mtu[ \t]+(\d+)[ \t]*$", re.MULTILINE),
    "fortigate_cli": re.compile(r"^[ \t]*set mtu (\d+)[ \t]*$", re.MULTILINE),
    # A media MTU, on a device or an interface range; not a family's.
    "juniper_junos": re.compile(
        r"^set interfaces (?:interface-range )?\S+ mtu (\d+)$", re.MULTILINE,
    ),
    "mikrotik_routeros": re.compile(r"(?<![\w-])mtu=(\d+)"),
    "opnsense": re.compile(r"<mtu>(\d+)</mtu>"),
    "vyos": re.compile(r"^[ \t]+mtu[ \t]+(\d+)[ \t]*$", re.MULTILINE),
}

#: An IOS-XE routed port with a jumbo payload, and a port whose
#: sub-interface carries a tag.  IOS-XE counts the payload.
_IOSXE = (
    "hostname r1\n"
    "interface GigabitEthernet1/0/1\n"
    " no switchport\n"
    " mtu 9000\n"
    " ip address 192.0.2.1 255.255.255.0\n"
    "!\n"
    "interface GigabitEthernet1/0/2\n"
    " no switchport\n"
    " mtu 1500\n"
    "!\n"
    "interface GigabitEthernet1/0/2.10\n"
    " encapsulation dot1Q 10\n"
    " ip address 198.51.100.1 255.255.255.0\n"
    "!\n"
)


def _numbers(target: str, text: str) -> list[int]:
    return sorted(int(n) for n in _MTU_LINE[target].findall(text))


def _written(payload: int, target: str, tags: int = 0) -> int:
    header, per_tag = _BY_HAND[target]
    return payload + header + per_tag * tags


def _expected_from_iosxe(target: str) -> list[int]:
    """The ``mtu`` numbers the IOS-XE source is written with on
    *target*: 9000 on an untagged port; 1500 on the port whose unit is
    tagged -- on Junos the device counts the tag, on IOS XR the
    sub-interface would, and it states no MTU of its own."""
    tagged_device = 1 if target == "juniper_junos" else 0
    return sorted([_written(9000, target), _written(1500, target, tagged_device)])


def _problems_onto(target: str) -> list[str]:
    job = run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(target), _IOSXE, port_rename_map={},
    )
    found = _numbers(target, job.rendered)
    want = _expected_from_iosxe(target)
    return [] if found == want else [f"{target}: mtu lines {found}, want {want}"]


_TARGETS = sorted(t for t in list_public_codecs() if t not in NO_INTERFACE_MTU)


def test_the_table_is_the_one_typed_by_hand() -> None:
    assert {k: (v.header, v.per_tag) for k, v in MTU_BEYOND_THE_PAYLOAD.items()} == _BY_HAND


def _in_neither_or_both(codecs: list[str], table: dict, named: dict) -> list[str]:
    return [c for c in codecs if (c in table) == (c in named)]


def test_each_codec_says_what_its_mtu_counts() -> None:
    """A new codec states what its ``mtu`` counts beyond the payload:
    there is no safe default.  It is in the table, or named here with
    the reason it reads no interface MTU."""
    assert not _in_neither_or_both(list_public_codecs(), MTU_BEYOND_THE_PAYLOAD, NO_INTERFACE_MTU), (
        "say what this platform's interface mtu counts (MTU_BEYOND_THE_PAYLOAD in "
        "codecs/_helpers.py), or name it in NO_INTERFACE_MTU with the reason"
    )
    assert not set(MTU_BEYOND_THE_PAYLOAD) - set(list_public_codecs())
    assert all(NO_INTERFACE_MTU.values())


def test_a_codec_in_neither_is_reported() -> None:
    codecs = [*list_public_codecs(), "a_fourteenth"]
    assert _in_neither_or_both(codecs, MTU_BEYOND_THE_PAYLOAD, NO_INTERFACE_MTU) == ["a_fourteenth"]
    doubled = {**NO_INTERFACE_MTU, "dell_os10": "also named here"}
    assert _in_neither_or_both(list_public_codecs(), MTU_BEYOND_THE_PAYLOAD, doubled) == ["dell_os10"]


@pytest.mark.parametrize("target", _TARGETS)
def test_the_payload_is_written_as_the_target_counts_it(target: str) -> None:
    assert _problems_onto(target) == []


@pytest.mark.parametrize("target", ["juniper_junos", "cisco_iosxr", "dell_os10"])
def test_a_copied_number_is_seen(target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check above, handed a codec that copies the number as it
    stands -- the defect it is for."""
    monkeypatch.setitem(_helpers.MTU_BEYOND_THE_PAYLOAD, target, MtuCounts(0))
    assert _problems_onto(target)


def test_a_tag_left_out_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed a Junos renderer that counts the header and not the tag."""
    monkeypatch.setitem(_helpers.MTU_BEYOND_THE_PAYLOAD, "juniper_junos", MtuCounts(14))
    assert _problems_onto("juniper_junos")


#: A source in each grammar that counts more than the payload, the
#: number it states, and the payload it carries, typed by hand.
_SOURCES = [
    pytest.param(
        "juniper_junos",
        "set system host-name r1\n"
        "set interfaces ge-0/0/1 mtu 9014\n"
        "set interfaces ge-0/0/1 unit 0 family inet address 192.0.2.1/24\n",
        9000,
        id="junos-port",
    ),
    pytest.param(
        "juniper_junos",
        "set system host-name r1\n"
        "set interfaces ge-0/0/2 vlan-tagging\n"
        "set interfaces ge-0/0/2 mtu 1522\n"
        "set interfaces ge-0/0/2 unit 10 vlan-id 10\n"
        "set interfaces ge-0/0/2 unit 10 family inet address 198.51.100.1/24\n",
        1504,
        id="junos-tagged-device",
    ),
    pytest.param(
        "juniper_junos",
        "set system host-name r1\n"
        "set interfaces ae0 mtu 1514\n"
        "set interfaces ae0 unit 0 family inet address 192.0.2.1/24\n",
        1500,
        id="junos-aggregate",
    ),
    pytest.param(
        "cisco_iosxr",
        "hostname r1\n"
        "interface TenGigE0/0/0/1\n"
        " mtu 9014\n"
        " ipv4 address 192.0.2.1 255.255.255.0\n"
        "!\n",
        9000,
        id="iosxr-port",
    ),
    pytest.param(
        "cisco_iosxr",
        "hostname r1\n"
        "interface TenGigE0/0/0/2.10\n"
        " mtu 1518\n"
        " encapsulation dot1q 10\n"
        " ipv4 address 198.51.100.1 255.255.255.0\n"
        "!\n",
        1500,
        id="iosxr-tagged-subinterface",
    ),
    pytest.param(
        "dell_os10",
        "hostname r1\n"
        "interface ethernet1/1/1\n"
        " no switchport\n"
        " mtu 9022\n"
        " ip address 192.0.2.1/24\n"
        "!\n",
        9000,
        id="os10-port",
    ),
]


@pytest.mark.parametrize(("source", "text", "payload"), _SOURCES)
def test_a_stated_mtu_is_read_as_its_payload(source: str, text: str, payload: int) -> None:
    """Read in its own grammar, the number is the payload: in the tree,
    and on IOS-XE, which counts the payload, as text."""
    tree = get_codec(source).parse(text)
    assert [i.mtu for i in tree.interfaces if i.mtu is not None] == [payload]
    job = run_plan_with_checked_names(
        get_codec(source), get_codec("cisco_iosxe_cli"), text, port_rename_map={},
    )
    assert _numbers("cisco_iosxe_cli", job.rendered) == [payload]


@pytest.mark.parametrize(("source", "text", "payload"), _SOURCES)
def test_a_job_to_itself_keeps_the_number(source: str, text: str, payload: int) -> None:
    """From a codec to itself the number is written as it was stated:
    the two conversions are each other's inverse."""
    job = run_plan_with_checked_names(get_codec(source), get_codec(source), text, port_rename_map={})
    assert _numbers(source, job.rendered) == _numbers(source, text)


#: What has no Ethernet header is copied as it stands: a Junos tunnel,
#: an IOS XR loopback.
_NOT_ETHERNET = [
    pytest.param(
        "juniper_junos",
        "set system host-name r1\n"
        "set interfaces st0 mtu 1400\n"
        "set interfaces st0 unit 0 family inet\n",
        1400,
        id="junos-st0",
    ),
    pytest.param(
        "cisco_iosxr",
        "hostname r1\n"
        "interface Loopback0\n"
        " mtu 1500\n"
        " ipv4 address 192.0.2.9 255.255.255.255\n"
        "!\n",
        1500,
        id="iosxr-loopback",
    ),
]


@pytest.mark.parametrize(("source", "text", "stated"), _NOT_ETHERNET)
def test_what_has_no_ethernet_header_is_copied(source: str, text: str, stated: int) -> None:
    tree = get_codec(source).parse(text)
    assert [i.mtu for i in tree.interfaces if i.mtu is not None] == [stated]
    assert _numbers(source, get_codec(source).render(tree)) == [stated]
