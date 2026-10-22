"""An IP MTU of its own is read, carried and written as an IP MTU.

Four platforms state the largest IP packet apart from the interface MTU:
IOS-XE and AOS-CX ``ip mtu``, IOS XR ``ipv4 mtu``, Junos ``family inet
mtu``.  The tree had no field for it.  The AOS-CX parser skipped ``ip
mtu``, so every jumbo VLAN interface of the committed AOS-CX captures --
``ip mtu 9198`` and no ``mtu`` -- came out with no MTU line on every
target, an IP MTU of 1500, in jobs that said ``completed``; the IOS-XE
and IOS XR parsers skipped theirs; and the Junos parser read a unit's
``family inet mtu`` as the unit's MTU, which IOS-XE and IOS XR then wrote
as an ``mtu`` on a sub-interface.  The other way, AOS-CX -- whose IP MTU
stays 1500 under a raised ``mtu`` unless ``ip mtu`` says otherwise -- was
written ``mtu 9000`` alone for an IOS-XE port that sent 9000-byte IP
packets.

Every check agreed, since no tree held the number: the source's tree and
the target's both lacked it.  So the IP MTU each output SENDS is read
here from its text, by a reader per grammar written here, with each
platform's own value for an interface that states none typed by hand
from the vendors' sentences
(``docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/mtu.md``), and
compared with what the source sends, typed by hand too.  The interface is
found by its address, not its name.  Each check is handed the defect it
is for.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from netcanon.migration.codecs import _helpers
from netcanon.migration.codecs.aruba_aoscx import parse as aoscx_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

_IP_MTU = "/interfaces/interface/config/ip-mtu"
_BESIDE = "/interfaces/interface/config/ip-mtu-beside-mtu"

#: The IP MTU of an interface whose config states none, where it is not
#: the payload, typed by hand: AOS-CX ``ip mtu`` "Default: 1500".
_NOT_STATED_BY_HAND = {"aruba_aoscx": 1500}


def _stanza_with(text: str, address: str) -> list[str]:
    """The ``interface`` stanza -- a line in column 0 and the indented
    lines after it -- that holds *address*."""
    stanza: list[str] = []
    found: list[str] | None = None
    for line in text.splitlines():
        if line and not line[0].isspace():
            if found is not None:
                return found
            stanza = [line]
        else:
            stanza.append(line)
        if found is None and stanza[:1] and stanza[0].startswith("interface ") and (
            re.search(rf"(?<![\d.]){re.escape(address)}(?![\d])", line)
        ):
            found = stanza
    return found or []


def _number(stanza: list[str], pattern: str) -> int | None:
    for line in stanza:
        m = re.fullmatch(pattern, line)
        if m:
            return int(m.group(1))
    return None


def _sends_iosxe(text: str, address: str) -> int | None:
    """``ip mtu``; else ``mtu``, which an unstated IP MTU is taken to
    follow (not established by a vendor sentence); else 1500."""
    stanza = _stanza_with(text, address)
    if not stanza:
        return None
    stated = _number(stanza, r"[ \t]+ip[ \t]+mtu[ \t]+(\d+)[ \t]*")
    if stated is None:
        stated = _number(stanza, r"[ \t]+mtu[ \t]+(\d+)[ \t]*")
    return 1500 if stated is None else stated


def _sends_iosxr(text: str, address: str) -> int | None:
    """``ipv4 mtu``; else ``mtu`` less the 14-byte Ethernet header and 4
    for a tag ("IP MTU value in the hardware is Ethernet MTU-14B");
    else 1500."""
    stanza = _stanza_with(text, address)
    if not stanza:
        return None
    stated = _number(stanza, r"[ \t]+ipv4[ \t]+mtu[ \t]+(\d+)[ \t]*")
    if stated is not None:
        return stated
    media = _number(stanza, r"[ \t]+mtu[ \t]+(\d+)[ \t]*")
    if media is None:
        return 1500
    tagged = any(re.match(r"[ \t]+encapsulation[ \t]+dot1q[ \t]", ln) for ln in stanza)
    return media - 14 - (4 if tagged else 0)


def _sends_aoscx(text: str, address: str) -> int | None:
    """``ip mtu``; else 1500, whatever ``mtu`` says."""
    stanza = _stanza_with(text, address)
    if not stanza:
        return None
    stated = _number(stanza, r"[ \t]+ip[ \t]+mtu[ \t]+(\d+)[ \t]*")
    return 1500 if stated is None else stated


def _sends_one_mtu(text: str, address: str) -> int | None:
    """NX-OS and EOS: ``mtu`` is the IP MTU; else 1500."""
    stanza = _stanza_with(text, address)
    if not stanza:
        return None
    stated = _number(stanza, r"[ \t]+mtu[ \t]+(\d+)[ \t]*")
    return 1500 if stated is None else stated


def _sends_junos(text: str, address: str) -> int | None:
    """The unit's ``family inet mtu``; else its device's media ``mtu``
    less the 14-byte header and 4 on a ``vlan-tagging`` device; else
    1500."""
    m = re.search(
        rf"^set interfaces (\S+) unit (\d+) family inet address {re.escape(address)}/",
        text, re.MULTILINE,
    )
    if m is None:
        return None
    device, unit = m.group(1), m.group(2)
    family = re.search(
        rf"^set interfaces {re.escape(device)} unit {unit} family inet mtu (\d+)$",
        text, re.MULTILINE,
    )
    if family is not None:
        return int(family.group(1))
    media = re.search(rf"^set interfaces {re.escape(device)} mtu (\d+)$", text, re.MULTILINE)
    if media is None:
        return 1500
    tagged = re.search(rf"^set interfaces {re.escape(device)} vlan-tagging$", text, re.MULTILINE)
    return int(media.group(1)) - 14 - (4 if tagged else 0)


#: What an output's interface sends, read from its text, by target.
_SENDS: dict[str, Callable[[str, str], int | None]] = {
    "arista_eos": _sends_one_mtu,
    "aruba_aoscx": _sends_aoscx,
    "cisco_iosxe_cli": _sends_iosxe,
    "cisco_iosxr": _sends_iosxr,
    "cisco_nxos": _sends_one_mtu,
    "juniper_junos": _sends_junos,
}

#: Targets with one MTU for the payload and the IP packet, whose
#: grammar is read here by I-1's guard (one ``mtu`` per output): where
#: the tree states an IP MTU and no payload, the output's MTU lines are
#: the IP MTU.
_ONE_MTU_LINE: dict[str, re.Pattern[str]] = {
    "fortigate_cli": re.compile(r"^[ \t]*set mtu (\d+)[ \t]*$", re.MULTILINE),
    "mikrotik_routeros": re.compile(r"(?<![\w-])mtu=(\d+)"),
    "opnsense": re.compile(r"<mtu>(\d+)</mtu>"),
    "vyos": re.compile(r"^[ \t]+mtu[ \t]+(\d+)[ \t]*$", re.MULTILINE),
}

#: The targets that write no IP MTU, and say so in the job's report.
_SAID_LOST: dict[str, str] = {
    "aruba_aoss": "no per-interface MTU: the IP MTU is the global `jumbo ip-mtu`",
    "cisco_iosxe": "the NETCONF codec carries no IP MTU between OpenConfig and the tree",
    "dell_os10": "the IP MTU is a setting apart from the link MTU, and how it is set is not established",
}

#: The platforms whose payload and IP MTU are one number.
_ONE_MTU = {"arista_eos", "cisco_nxos", *_ONE_MTU_LINE}


def _source(codec: str, text: str, address: str, sends: int, payload: int | None, sid: str):
    return pytest.param(sid, codec, text, address, sends, payload, id=sid)


#: A source, the address of its interface, the IP MTU that interface
#: sends and its payload (``None`` where the source states none), typed
#: by hand.  Its ports have names every target's translator reads.
_SOURCES = [
    _source(
        "aruba_aoscx",
        "hostname s1\n"
        "vlan 101\n"
        "interface vlan 101\n"
        "    ip mtu 9198\n"
        "    ip address 203.0.113.2/24\n",
        "203.0.113.2", 9198, None, "aoscx-vlan-ip-mtu",
    ),
    _source(
        "aruba_aoscx",
        "hostname s1\n"
        "interface 1/1/1\n"
        "    no shutdown\n"
        "    mtu 9198\n"
        "    ip address 192.0.2.1/31\n",
        "192.0.2.1", 1500, 9198, "aoscx-port-mtu-alone",
    ),
    _source(
        "aruba_aoscx",
        "hostname s1\n"
        "interface 1/1/1\n"
        "    no shutdown\n"
        "    mtu 9198\n"
        "    ip mtu 9198\n"
        "    ip address 192.0.2.1/31\n",
        "192.0.2.1", 9198, 9198, "aoscx-port-both",
    ),
    _source(
        "cisco_iosxe_cli",
        "hostname r1\n"
        "interface GigabitEthernet1/0/1\n"
        " no switchport\n"
        " ip mtu 1400\n"
        " ip address 192.0.2.1 255.255.255.0\n"
        "!\n",
        "192.0.2.1", 1400, None, "iosxe-ip-mtu",
    ),
    _source(
        "cisco_iosxe_cli",
        "hostname r1\n"
        "interface GigabitEthernet1/0/1\n"
        " no switchport\n"
        " mtu 9000\n"
        " ip address 192.0.2.1 255.255.255.0\n"
        "!\n",
        "192.0.2.1", 9000, 9000, "iosxe-mtu-alone",
    ),
    _source(
        "cisco_iosxr",
        "hostname r1\n"
        "interface TenGigE0/0/0/1\n"
        " mtu 9014\n"
        " ipv4 mtu 1400\n"
        " ipv4 address 192.0.2.1 255.255.255.0\n"
        "!\n",
        "192.0.2.1", 1400, 9000, "iosxr-both",
    ),
    _source(
        "juniper_junos",
        "set system host-name r1\n"
        "set interfaces ge-0/0/1 mtu 9014\n"
        "set interfaces ge-0/0/1 unit 0 family inet mtu 1400\n"
        "set interfaces ge-0/0/1 unit 0 family inet address 192.0.2.1/24\n",
        "192.0.2.1", 1400, 9000, "junos-unit-0",
    ),
    _source(
        "juniper_junos",
        "set system host-name r1\n"
        "set interfaces ge-0/0/2 vlan-tagging\n"
        "set interfaces ge-0/0/2 mtu 9022\n"
        "set interfaces ge-0/0/2 unit 10 vlan-id 10\n"
        "set interfaces ge-0/0/2 unit 10 family inet mtu 9000\n"
        "set interfaces ge-0/0/2 unit 10 family inet address 198.51.100.1/24\n",
        "198.51.100.1", 9000, None, "junos-tagged-unit",
    ),
]

#: Cells where the target has no place for the source's interface, so
#: there is no stanza to read, with the reason: the job says so
#: (``partial``, the interface listed as not placed), which is held
#: below, as is the absence of the stanza.
_NO_SUCH_INTERFACE: dict[tuple[str, str], str] = {
    ("aoscx-vlan-ip-mtu", "cisco_iosxr"): "IOS XR has no VLAN interface",
    ("aoscx-vlan-ip-mtu", "vyos"): "the translator has no VyOS name for `vlan 101`",
}

#: Cells known to be wrong for a reason that is not the IP MTU, pinned:
#: the change that mends one fails here until its pin is taken out.
_OPEN: dict[tuple[str, str], str] = {}


def _job(source: str, target: str, text: str):
    return run_plan_with_checked_names(get_codec(source), get_codec(target), text, port_rename_map={})


def _problem(source: str, text: str, address: str, sends: int, payload: int | None, target: str) -> str:
    """What is wrong with the IP MTU *target*'s output sends, or ``""``."""
    job = _job(source, target, text)
    lossy = {p.path for p in job.validation.lossy_paths} if job.validation else set()
    if target in _ONE_MTU and payload is not None and payload != sends:
        # One number for both: the payload is written, and the loss said.
        want = payload
        if _BESIDE not in lossy:
            return f"{target}: the IP MTU {sends} is lost and the report does not say so"
    else:
        want = sends
    if target in _SENDS:
        got = _SENDS[target](job.rendered, address)
        if got is None:
            return f"{target}: no interface with {address} in the output"
        return "" if got == want else f"{target}: sends {got}, want {want}"
    if target in _ONE_MTU_LINE:
        got_lines = [int(n) for n in _ONE_MTU_LINE[target].findall(job.rendered)]
        return "" if want in got_lines or (want == 1500 and not got_lines) else (
            f"{target}: mtu lines {got_lines}, want {want}"
        )
    return ""


_READ = sorted(set(_SENDS) | set(_ONE_MTU_LINE))
_PARAMS = ("sid", "source", "text", "address", "sends", "payload")


def _not_placed(job, source: str, text: str, address: str) -> bool:
    """Whether *job* says the source interface that holds *address* is
    not placed: ``partial``, with its name listed."""
    names = {
        i.name for i in get_codec(source).parse(text).interfaces
        if any(a.ip == address for a in i.ipv4_addresses)
    } or {i.name for i in get_codec(source).parse(text).interfaces}
    listed = set(job.unresolved_ports) | set(job.untranslated_ports)
    return job.status.value == "partial" and bool(names & listed)


@pytest.mark.parametrize(_PARAMS, _SOURCES)
@pytest.mark.parametrize("target", _READ)
def test_the_ip_mtu_is_sent_as_the_source_sends_it(
    sid: str, source: str, text: str, address: str, sends: int, payload: int | None,
    target: str,
) -> None:
    if (sid, target) in _NO_SUCH_INTERFACE:
        job = _job(source, target, text)
        assert address not in (job.rendered or "")
        assert _not_placed(job, source, text, address)
        return
    problem = _problem(source, text, address, sends, payload, target)
    if (sid, target) in _OPEN:
        assert problem, f"mended -- take the pin out: {_OPEN[(sid, target)]}"
    else:
        assert problem == ""


@pytest.mark.parametrize(
    _PARAMS,
    # The sources whose tree holds an IP MTU apart from the payload.
    [p for p in _SOURCES if p.values[4] != p.values[5]],
)
@pytest.mark.parametrize("target", sorted(_SAID_LOST))
def test_a_target_that_writes_no_ip_mtu_says_so(
    sid: str, source: str, text: str, address: str, sends: int, payload: int | None,
    target: str,
) -> None:
    job = _job(source, target, text)
    declared = {p.path for p in job.validation.lossy_paths} | {
        p.path for p in job.validation.unsupported_paths
    }
    assert _IP_MTU in declared or _not_placed(job, source, text, address)


def test_each_codec_is_read_or_named() -> None:
    """A new codec is read here, or named with the reason it writes no
    IP MTU: there is no safe default."""
    read = set(_SENDS) | set(_ONE_MTU_LINE)
    assert read.isdisjoint(_SAID_LOST)
    assert read | set(_SAID_LOST) == set(list_public_codecs())


def test_the_table_is_the_one_typed_by_hand() -> None:
    assert _helpers.IP_MTU_THAT_IS_NOT_STATED == _NOT_STATED_BY_HAND


def test_a_parser_that_skips_the_ip_mtu_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed the AOS-CX parser that read no ``ip mtu`` -- the defect it
    is for -- the check fails."""
    monkeypatch.setattr(aoscx_parse, "_IP_MTU_RE", re.compile(r"(?!)"))
    source = _SOURCES[0].values[1:]
    assert _problem(*source, "cisco_iosxe_cli")
    assert _problem(*source, "cisco_nxos")


def test_a_default_left_out_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed codecs that take AOS-CX's IP MTU to follow ``mtu``: read
    from AOS-CX, a port with ``mtu`` alone sends jumbo IP packets on
    IOS-XE, and written onto AOS-CX, an IOS-XE port's 9000-byte IP MTU
    is 1500."""
    monkeypatch.setattr(_helpers, "IP_MTU_THAT_IS_NOT_STATED", {})
    assert _problem(*_SOURCES[1].values[1:], "cisco_iosxe_cli")
    assert _problem(*_SOURCES[4].values[1:], "aruba_aoscx")


def test_a_loss_not_said_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Handed an NX-OS matrix that does not declare the IP MTU lost
    beside a payload, the check fails."""
    caps = get_codec("cisco_nxos").capabilities
    monkeypatch.setattr(caps, "lossy", [p for p in caps.lossy if p.path != _BESIDE])
    assert _problem(*_SOURCES[5].values[1:], "cisco_nxos")


def test_a_routeros_vlan_interface_that_writes_no_mtu_is_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Handed the RouterOS renderer that wrote no ``mtu=`` on a VLAN
    interface, the check fails."""
    from netcanon.migration.codecs.mikrotik_routeros import render as ros_render

    real = ros_render.one_mtu_written
    monkeypatch.setattr(
        ros_render, "one_mtu_written",
        lambda iface: None if iface.interface_type == "ianaift:l3ipvlan" else real(iface),
    )
    assert _problem(*_SOURCES[0].values[1:], "mikrotik_routeros")
