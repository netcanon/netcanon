"""Onto FortiOS, a VLAN is written on an interface that can carry it.

A FortiOS VLAN interface names its parent (``set interface``), and a
VLAN whose source states none is written on the port the renderer
chooses.  Its scorer ranked a private address above a trunk, so a
loopback with a private /32 -- which every fabric switch has -- out-
scored every trunk, and so did the switch's out-of-band management
port: every VLAN of thirteen committed captures came out ``set
interface "loopback0"`` and of eleven more ``set interface "mgmt1"``,
in jobs that said nothing of it.  A loopback carries no frames and a
tunnel no 802.1Q tag; a management port is not where the data VLANs
came in.

Now a loopback or a tunnel is no VLAN's parent, a management port is
chosen only where the output has no other, and a VLAN left with no
parent says so in a ``# review:`` line.  The output is read here as
text, by a reader of its own: each ``edit`` block of ``config system
interface`` that is ``set type vlan``, and the block its ``set
interface`` names.  Each check is handed the defect it is for.

Not judged: which port of several a VLAN is put on (the scorer puts a
private address before a trunk, pinned in
``test_the_trunk_that_names_a_vlan.py``), and a parent the source
states (FortiOS, RouterOS and OPNsense keep theirs).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import netcanon.migration.codecs.fortigate_cli.render as fgt_render
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.services.migration_pipeline import run_plan_with_checked_names

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
PUBLIC = list_public_codecs()

#: The sources whose parser reads the parent a VLAN states, which a
#: FortiOS output keeps whatever it is.
_STATE_A_PARENT = frozenset({"fortigate_cli", "mikrotik_routeros", "opnsense"})

_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py"}

_CANNOT_CARRY = re.compile(r"(?i)(loopback\d*|gre\d+|ssl\.root)")
_MANAGEMENT = re.compile(r"(?i)mgmt\d*")


def _captures() -> list[tuple[str, str, Path]]:
    """(codec, path under tests/fixtures, path) for every committed
    capture of a public codec but FortiOS."""
    found: list[tuple[str, str, Path]] = []
    for root in ("real", "synthetic", "iosxe", "opnsense"):
        for path in sorted(p for p in (FIXTURES / root).rglob("*") if p.is_file()):
            if path.suffix.lower() in _NOT_A_CAPTURE:
                continue
            parts = path.relative_to(FIXTURES).parts
            label = parts[1] if root in ("real", "synthetic") else {"iosxe": "cisco_iosxe"}.get(root, root)
            codec = DIR_TO_CODEC_NAME.get(label, label)
            if label == "cisco_iosxe" and path.suffix.lower() == ".xml":
                codec = "cisco_iosxe"
            if codec in PUBLIC and codec != "fortigate_cli":
                found.append((codec, "/".join(parts), path))
    return found


CAPTURES = _captures()


# ---------------------------------------------------------------------------
# The reader, and the check.
# ---------------------------------------------------------------------------


def _blocks(text: str) -> dict[str, list[str]]:
    """Each ``edit`` block of ``config system interface``: its name and
    its lines, stripped.  A block opens at ``    edit "X"`` and closes at
    ``    next``, four spaces in; anything deeper is the block's."""
    blocks: dict[str, list[str]] = {}
    inside = False
    current: list[str] | None = None
    for line in text.splitlines():
        if line == "config system interface":
            inside = True
        elif inside and line == "end":
            inside = False
        elif inside and (m := re.fullmatch(r'    edit "(.*)"', line)):
            current = blocks.setdefault(m.group(1), [])
        elif inside and line == "    next":
            current = None
        elif inside and current is not None:
            current.append(line.strip())
    return blocks


def _can_carry(name: str, body: list[str]) -> bool:
    return not (
        _CANNOT_CARRY.fullmatch(name)
        or "set type loopback" in body
        or "set type tunnel" in body
        or "set type vlan" in body
    )


def wrong_parents(source: str, text: str) -> list[str]:
    """What is wrong with the parents of the VLAN interfaces of a
    FortiOS output from *source*: a parent that cannot carry a VLAN; a
    VLAN with no parent and no line that says so; and, from a source
    that states no parent, a management port where the output has
    another port to choose."""
    blocks = _blocks(text)
    other_ports = [
        name for name, body in blocks.items()
        if _can_carry(name, body) and not _MANAGEMENT.fullmatch(name)
    ]
    wrong: list[str] = []
    for name, body in blocks.items():
        if "set type vlan" not in body:
            continue
        parents = [m.group(1) for line in body if (m := re.fullmatch(r'set interface "(.*)"', line))]
        if not parents:
            if not any(line.startswith("# review:") for line in body):
                wrong.append(f"{name}: no parent and no review line")
            continue
        parent = parents[0]
        if not _can_carry(parent, blocks.get(parent, [])):
            wrong.append(f"{name}: on {parent!r}, which cannot carry a VLAN")
        elif (
            source not in _STATE_A_PARENT
            and _MANAGEMENT.fullmatch(parent)
            and other_ports
        ):
            wrong.append(f"{name}: on the management port {parent!r} beside {other_ports[0]!r}")
    return wrong


def _output(source: str, raw: str) -> str:
    job = run_plan_with_checked_names(
        get_codec(source), get_codec("fortigate_cli"), raw, port_rename_map={},
    )
    return job.rendered or ""


# ---------------------------------------------------------------------------
# The captures.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "label", "path"), CAPTURES, ids=[c[1] for c in CAPTURES])
def test_each_vlan_rides_a_port(source: str, label: str, path: Path) -> None:
    assert wrong_parents(source, _output(source, path.read_text(encoding="utf-8"))) == []


def test_the_captures_have_vlans_on_fortios() -> None:
    """The check above reads something: enough of the captures put a
    VLAN interface on a parent onto FortiOS."""
    with_a_parent = 0
    for source, _, path in CAPTURES:
        blocks = _blocks(_output(source, path.read_text(encoding="utf-8")))
        with_a_parent += any(
            "set type vlan" in body and any(line.startswith("set interface ") for line in body)
            for body in blocks.values()
        )
    assert with_a_parent >= 40


# ---------------------------------------------------------------------------
# One switch, by hand.
# ---------------------------------------------------------------------------

_NXOS = (
    "hostname x\n"
    "feature interface-vlan\n"
    "vlan 10\n"
    "interface Vlan10\n"
    "  no shutdown\n"
    "  ip address 10.1.10.1/24\n"
    "{trunk}"
    "{mgmt}"
    "interface loopback0\n"
    "  ip address 10.0.0.1/32\n"
)
_TRUNK = (
    "interface Ethernet1/1\n"
    "  switchport mode trunk\n"
    "  switchport trunk allowed vlan 10\n"
)
_MGMT = "interface mgmt0\n  vrf member management\n  ip address 10.9.9.9/24\n"


def _vlan_block(text: str) -> list[str]:
    blocks = _blocks(text)
    return next(body for body in blocks.values() if "set type vlan" in body and "set vlanid 10" in body)


def test_a_trunk_before_the_loopback_and_the_management_port() -> None:
    text = _output("cisco_nxos", _NXOS.format(trunk=_TRUNK, mgmt=_MGMT))
    parent = next(line for line in _vlan_block(text) if line.startswith("set interface "))
    assert "loopback" not in parent and "mgmt" not in parent
    assert wrong_parents("cisco_nxos", text) == []


def test_the_management_port_where_there_is_no_other() -> None:
    text = _output("cisco_nxos", _NXOS.format(trunk="", mgmt=_MGMT))
    assert 'set interface "mgmt1"' in _vlan_block(text)


def test_no_port_at_all_is_said() -> None:
    text = _output("cisco_nxos", _NXOS.format(trunk="", mgmt=""))
    body = _vlan_block(text)
    assert not any(line.startswith("set interface ") for line in body)
    assert any(line.startswith("# review: VLAN 10 has no parent") for line in body)


# ---------------------------------------------------------------------------
# Each check, handed the defect it is for.
# ---------------------------------------------------------------------------

_SAMPLE = {
    "real/aruba_aoscx/aoscx_dcn_arch4_core1_1.cfg": "loopback",
    "real/cisco_nxos/batfish_nxos_hsrp_nxos1.txt": "loopback",
    "real/dell_os10/dellgeos_S5212F-TOR1-Advanced.cfg": "management",
    "real/junos/ksator_labmgmt_ex4550_junos151.set": "management",
}


def _sample() -> list[tuple[str, str, Path]]:
    found = [c for c in CAPTURES if c[1] in _SAMPLE]
    assert {c[1] for c in found} == set(_SAMPLE)
    return found


def test_the_check_sees_a_vlan_on_a_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer as it was: anything but a routed sub-interface may
    be a VLAN's parent."""
    monkeypatch.setattr(fgt_render, "_may_carry_a_vlan", lambda iface: iface.dot1q_vlan is None)
    for source, label, path in _sample():
        if _SAMPLE[label] == "loopback":
            wrong = wrong_parents(source, _output(source, path.read_text(encoding="utf-8")))
            assert wrong and all("cannot carry" in w for w in wrong), label


def test_the_check_sees_a_vlan_on_the_management_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer with a management port ranked as any other."""
    monkeypatch.setattr(fgt_render, "_is_management_port", lambda iface: False)
    for source, label, path in _sample():
        if _SAMPLE[label] == "management":
            wrong = wrong_parents(source, _output(source, path.read_text(encoding="utf-8")))
            assert wrong and all("management port" in w for w in wrong), label


def test_the_check_sees_a_vlan_with_no_parent_said_nowhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer with no line for a VLAN it has no parent for."""
    monkeypatch.setattr(fgt_render, "_NO_PARENT_REVIEW", "")
    text = _output("cisco_nxos", _NXOS.format(trunk="", mgmt=""))
    # An empty line is not a review line; the reader strips it.
    assert any("no parent and no review line" in w for w in wrong_parents("cisco_nxos", text))
