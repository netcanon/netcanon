"""An AOS-CX VLAN interface is up unless it says ``shutdown``.

AOS-CX prints the admin state of a port, a LAG, ``interface mgmt`` and
``interface vxlan`` whichever it is -- every such stanza of the committed
captures has a ``no shutdown`` or a ``shutdown`` line -- and prints no
admin line under a VLAN interface or a loopback.  The parser read every
interface but a loopback as down until a line said otherwise, so each
``interface vlan`` stanza of the captures, with the addresses and the
routing of a working fabric under it, was a shut interface: written
``shutdown`` (or its own form of it) onto ten targets, in jobs that said
nothing of it.

What says the default is the device's printout and HPE's own templates
(``aruba/aoscx-ansible-dcn-workflows``, whose sample configs are among
the captures), which write ``no shutdown`` under every port, LAG,
``interface mgmt`` and ``interface vxlan`` and under no ``interface
vlan`` or loopback.  It is inferred: no HPE command page read for this
states the default of a VLAN interface.

The captures are read by hand here, and every target's output twice: as
text, by a reader of its own for the targets whose shut interface is a
line (``shutdown``, Junos ``disable``, RouterOS ``disabled=yes``), and
with the target's parser.  Each check is handed the defect it is for and
has to fail.  Not reached: a target that writes no interface for the
VLAN's address (pinned below; each such job is ``partial``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import netcanon.migration.codecs.aruba_aoscx.parse as aoscx_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[3]
_CAPTURES = sorted((_REPO / "tests/fixtures/real/aruba_aoscx").glob("*.cfg"))

#: The targets that write no interface for an AOS-CX VLAN interface's
#: address, and how many of the captures' VLAN interfaces each leaves so.
#: IOS XR and VyOS say "no native representation for svi" and the job is
#: `partial`.
_NOT_ON_AN_INTERFACE = {"cisco_iosxr": 16, "vyos": 16}

#: The targets whose output states a shut interface in a line of its own,
#: and how the reader below finds it.
_LINE_UNDER_THE_INTERFACE = (
    "arista_eos", "aruba_aoscx", "cisco_iosxe_cli", "cisco_nxos", "dell_os10",
)


def _stanzas(text: str) -> list[tuple[str, list[str]]]:
    """Each ``interface`` line in column 0, with the indented lines under
    it; any other line in column 0 ends the stanza."""
    out: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in text.splitlines():
        if line.startswith("interface "):
            current = (line.rstrip(), [])
            out.append(current)
        elif current is not None and line[:1] in (" ", "\t") and line.strip():
            current[1].append(line.strip())
        elif line.strip():
            current = None
    return out


def _by_hand(text: str) -> dict[str, bool]:
    """Whether each interface of an AOS-CX text is up, read here: a
    ``shutdown`` line says down, a ``no shutdown`` line up, and with
    neither a VLAN interface or a loopback is up and anything else
    down."""
    states: dict[str, bool] = {}
    for header, body in _stanzas(text):
        name = re.sub(r"\s+multi-chassis$", "", header[len("interface "):].strip())
        if "shutdown" in body:
            states[name] = False
        elif "no shutdown" in body:
            states[name] = True
        else:
            states[name] = bool(re.match(r"(vlan|loopback) \d+$", name))
    return states


def _vlan_interfaces(text: str) -> list[tuple[str, list[str]]]:
    """The ``interface vlan N`` stanzas of an AOS-CX text and the IPv4
    addresses each states (``ip address A/N``), read here."""
    out = []
    for header, body in _stanzas(text):
        if re.match(r"interface vlan \d+$", header):
            ips = [m.group(1) for line in body
                   if (m := re.match(r"ip address (\d+\.\d+\.\d+\.\d+)/\d+$", line))]
            out.append((header, ips))
    return out


# ---------------------------------------------------------------------------
# The checks.  Each returns what it found wrong; a test asserts none, and a
# test at the foot hands it the defect it is for.
# ---------------------------------------------------------------------------


def _parse_disagrees(text: str) -> list[str]:
    """The interfaces whose state the parser reads otherwise than
    :func:`_by_hand`."""
    tree = get_codec("aruba_aoscx").parse(text)
    parsed = {i.name: i.enabled for i in tree.interfaces}
    return [
        f"{name}: by hand {up}, parsed {parsed[name]}"
        for name, up in _by_hand(text).items()
        if name in parsed and parsed[name] != up
    ]


def _shut_in_the_text(target: str, rendered: str, ip: str) -> list[str]:
    """The places of ``target``'s text that shut the interface holding
    ``ip``, read by a reader of the target's grammar."""
    if target in _LINE_UNDER_THE_INTERFACE:
        return [
            header for header, body in _stanzas(rendered)
            if any(re.match(rf"ip address {re.escape(ip)}[/ ]", line) for line in body)
            and "shutdown" in body
        ]
    if target == "juniper_junos":
        units = re.findall(
            rf"^set interfaces (\S+) unit (\d+) family inet address {re.escape(ip)}/",
            rendered, re.M,
        )
        return [
            line for name, unit in units
            for line in (f"set interfaces {name} unit {unit} disable",
                         f"set interfaces {name} disable")
            if re.search(rf"^{re.escape(line)}$", rendered, re.M)
        ]
    if target == "mikrotik_routeros":
        names = re.findall(
            rf"^add address={re.escape(ip)}/\d+ interface=(\S+)", rendered, re.M,
        )
        return [
            line for name in names for line in rendered.splitlines()
            if re.search(rf"\bname={re.escape(name)}(\s|$)", line)
            and re.search(r"\bdisabled=yes\b", line)
        ]
    return []


def _shut_in_the_output(target: str) -> tuple[list[str], int, int]:
    """Every capture onto ``target``: what shuts a VLAN interface of the
    source in the output, read as text and with the target's parser,
    with how many VLAN interfaces were found there and how many were
    not."""
    codec = get_codec(target)
    problems: list[str] = []
    found = missing = 0
    for capture in _CAPTURES:
        raw = capture.read_text(encoding="utf-8")
        svis = [(h, ips) for h, ips in _vlan_interfaces(raw) if ips]
        if not svis:
            continue
        job = run_plan_with_checked_names(
            get_codec("aruba_aoscx"), codec, raw, port_rename_map={},
        )
        out = codec.parse(job.rendered)
        for header, ips in svis:
            holders = [
                i for i in out.interfaces
                if any(a.ip == ips[0] for a in i.ipv4_addresses)
            ]
            if not holders:
                missing += 1
                continue
            found += 1
            problems += [
                f"{capture.name} {header}: {h.name} parsed shut"
                for h in holders if not h.enabled
            ]
            problems += [
                f"{capture.name} {header}: {line}"
                for line in _shut_in_the_text(target, job.rendered, ips[0])
            ]
    return problems, found, missing


# ---------------------------------------------------------------------------
# The tests.
# ---------------------------------------------------------------------------


def test_the_captures_print_a_ports_state_and_not_a_vlan_interfaces() -> None:
    """The evidence, as the captures hold it: every stanza that is not a
    VLAN interface or a loopback has an admin line, so the default down
    decides none of them, and VLAN interfaces with addresses have none."""
    unstated = []
    quiet_svis = 0
    for capture in _CAPTURES:
        for header, body in _stanzas(capture.read_text(encoding="utf-8")):
            if re.match(r"interface (vlan|loopback) \d+$", header):
                quiet_svis += header.startswith("interface vlan") and not (
                    {"shutdown", "no shutdown"} & set(body)
                )
            elif not {"shutdown", "no shutdown"} & set(body):
                unstated.append(f"{capture.name} {header}")
    assert unstated == []
    assert quiet_svis >= 16


@pytest.mark.parametrize("capture", _CAPTURES, ids=lambda p: p.stem)
def test_the_parser_reads_each_state_as_written(capture: Path) -> None:
    assert _parse_disagrees(capture.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("body", "up"),
    [("", True), ("    shutdown\n", False), ("    no shutdown\n", True)],
    ids=["nothing", "shutdown", "no-shutdown"],
)
def test_a_vlan_interface_alone(body: str, up: bool) -> None:
    raw = (
        "!Version ArubaOS-CX FL.10.13.1000\n"
        "hostname x\n"
        "vlan 10\n"
        "interface vlan 10\n"
        f"{body}"
        "    ip address 198.51.100.1/24\n"
        "interface mgmt\n"
        "    ip static 192.0.2.10/24\n"
    )
    by_name = {i.name: i for i in get_codec("aruba_aoscx").parse(raw).interfaces}
    assert by_name["vlan 10"].enabled is up
    # The management interface keeps the default of a port.
    assert by_name["mgmt"].enabled is False


@pytest.mark.parametrize("target", list_public_codecs())
def test_onto_every_target_a_vlan_interface_stays_up(target: str) -> None:
    problems, found, missing = _shut_in_the_output(target)
    assert problems == []
    assert missing == _NOT_ON_AN_INTERFACE.get(target, 0)
    assert found + missing >= 16


def test_the_pins_name_public_codecs() -> None:
    assert set(_NOT_ON_AN_INTERFACE) <= set(list_public_codecs())


# ---------------------------------------------------------------------------
# Each check, handed the defect it is for.
# ---------------------------------------------------------------------------


def _the_old_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The parser as it was: every interface but a loopback down."""
    monkeypatch.setattr(
        aoscx_parse, "_default_enabled",
        lambda name: aoscx_parse._port_names.classify_port_name(name).kind == "loopback",
    )


def test_the_hand_reading_sees_the_old_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _the_old_default(monkeypatch)
    wrong = [p for c in _CAPTURES for p in _parse_disagrees(c.read_text(encoding="utf-8"))]
    assert len(wrong) >= 16
    assert all(p.startswith("vlan ") for p in wrong)


@pytest.mark.parametrize(
    "target",
    [*_LINE_UNDER_THE_INTERFACE, "juniper_junos", "mikrotik_routeros"],
)
def test_the_text_reader_sees_a_shut_interface(
    target: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the old default each VLAN interface is shut in the output,
    and the reader of the target's text says so, apart from its parser."""
    _the_old_default(monkeypatch)
    capture = next(c for c in _CAPTURES if c.name == "aoscx_dcn_arch4_core1_1.cfg")
    raw = capture.read_text(encoding="utf-8")
    job = run_plan_with_checked_names(
        get_codec("aruba_aoscx"), get_codec(target), raw, port_rename_map={},
    )
    shut = [ip for _, ips in _vlan_interfaces(raw) if ips
            for ip in ips[:1] if _shut_in_the_text(target, job.rendered, ip)]
    assert len(shut) == 3


def test_the_output_check_sees_the_old_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _the_old_default(monkeypatch)
    problems, found, _ = _shut_in_the_output("cisco_iosxe_cli")
    assert found >= 16
    assert sum("parsed shut" in p for p in problems) == found
    assert sum("parsed shut" not in p for p in problems) == found
