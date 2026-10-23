"""Onto FortiOS, a VLAN is written on an interface that can carry it,
and on one that DOES where the source has one.

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

A VLAN the source carries on a trunk rides on that trunk, or on the
LAG it is a member of.  The renderer chose one parent for every VLAN
interface (the first LAG for a VLAN, a scored port for an interface
of a VLAN), and the VLANs of a switch were written on a port that
carries none of them -- a routed port with a private address, or
another trunk than the one the source lists the VLAN on -- in jobs
that said nothing of it.  Which ports carry a VLAN is read here from
the source's own tree by hand, and the output's parent is held to
them under the names the job gave them.  A VLAN whose every carrier
is left out of the output (a port the target has no name for) is
not judged, and its job is held to not saying ``completed``.

Not judged: which port of several carriers a VLAN is put on (the
first, pinned in ``test_the_trunk_that_names_a_vlan.py``), which port
a VLAN nothing carries is put on (the scorer, pinned there), a
routed sub-interface (it rides on the port its name is a unit of),
and a parent the source states (FortiOS, RouterOS and OPNsense keep
theirs).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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


def _job(source: str, raw: str) -> Any:
    return run_plan_with_checked_names(
        get_codec(source), get_codec("fortigate_cli"), raw, port_rename_map={},
    )


def _output(source: str, raw: str) -> str:
    return _job(source, raw).rendered or ""


def _carried_by(tree: Any) -> dict[int, set[str]]:
    """VLAN id -> the names of the source that carry it on a trunk: a
    LAG for its own interface and each of its members, any other
    interface for itself.  Read from the source's tree, not through the
    renderer's rule."""
    lag_of: dict[str, str] = {}
    for lag in tree.lags:
        lag_of[lag.name] = lag.name
        for member in lag.members:
            lag_of[member] = lag.name
    carried: dict[int, set[str]] = {}
    for iface in tree.interfaces:
        for vid in set(iface.trunk_allowed_vlans):
            carried.setdefault(vid, set()).add(lag_of.get(iface.name, iface.name))
    return carried


def off_its_carrier(source: str, raw: str, job: Any) -> tuple[list[str], int, list[str]]:
    """``(VLAN interfaces of the output on a port that does not carry
    their VLAN, how many were judged, VLAN interfaces none of whose
    carriers is in the output)``, for a source that states no parent."""
    if source in _STATE_A_PARENT:
        return [], 0, []
    tree = get_codec(source).parse(raw)
    renamed = dict(job.port_renames)
    subs = {renamed.get(i.name, i.name) for i in tree.interfaces if i.dot1q_vlan is not None}
    carried = _carried_by(tree)
    blocks = _blocks(job.rendered or "")
    wrong: list[str] = []
    gone: list[str] = []
    judged = 0
    for name, body in blocks.items():
        if "set type vlan" not in body or name in subs:
            continue
        vid = next((int(m.group(1)) for line in body if (m := re.fullmatch(r"set vlanid (\d+)", line))), None)
        parent = next((m.group(1) for line in body if (m := re.fullmatch(r'set interface "(.*)"', line))), None)
        if vid is None or parent is None or vid not in carried:
            continue
        carriers = {renamed.get(n, n) for n in carried[vid]} & set(blocks)
        if not carriers:
            gone.append(name)
            continue
        judged += 1
        if parent not in carriers:
            wrong.append(f"{name}: VLAN {vid} on {parent!r}, carried by {sorted(carriers)[:3]}")
    return wrong, judged, gone


# ---------------------------------------------------------------------------
# The captures.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "label", "path"), CAPTURES, ids=[c[1] for c in CAPTURES])
def test_each_vlan_rides_a_port(source: str, label: str, path: Path) -> None:
    raw = path.read_text(encoding="utf-8")
    job = _job(source, raw)
    assert wrong_parents(source, job.rendered or "") == []
    wrong, _judged, gone = off_its_carrier(source, raw, job)
    assert wrong == []
    assert _left_out_is_said(job, gone), gone


def _left_out_is_said(job: Any, gone: list[str]) -> bool:
    """A VLAN whose carriers are all left out of the output: the job
    does not say ``completed``."""
    return not gone or job.status.value != "completed"


def test_the_captures_have_vlans_on_their_carriers() -> None:
    """The carrier check reads something: many VLAN interfaces of the
    captures are carried by a port of the output."""
    judged = 0
    for source, _, path in CAPTURES:
        raw = path.read_text(encoding="utf-8")
        judged += off_its_carrier(source, raw, _job(source, raw))[1]
    assert judged >= 200, judged


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


def test_each_vlan_on_the_trunk_that_carries_it() -> None:
    """A port-channel of VLANs 10 and 20, a port of 10, 20 and 30, and
    a routed port with a private address: VLANs 10 and 20 (each with an
    address) ride on the port-channel, VLAN 30 on the port -- not on
    the routed port, which carries none of them."""
    text = (
        "hostname x\n"
        "feature interface-vlan\n"
        "feature lacp\n"
        "vlan 10,20,30\n"
        "interface Vlan10\n  no shutdown\n  ip address 10.1.10.1/24\n"
        "interface Vlan20\n  no shutdown\n  ip address 10.1.20.1/24\n"
        "interface port-channel1\n  switchport mode trunk\n  switchport trunk allowed vlan 10,20\n"
        "interface Ethernet1/1\n  switchport mode trunk\n  switchport trunk allowed vlan 10,20\n"
        "  channel-group 1 mode active\n"
        "interface Ethernet1/2\n  no switchport\n  ip address 192.168.1.1/24\n"
        "interface Ethernet1/4\n  switchport mode trunk\n  switchport trunk allowed vlan 10,20,30\n"
    )
    job = _job("cisco_nxos", text)
    renamed = dict(job.port_renames)
    blocks = _blocks(job.rendered or "")
    parent_of = {
        int(next(line for line in body if line.startswith("set vlanid ")).split()[-1]):
        next(line for line in body if line.startswith("set interface ")).split('"')[1]
        for body in blocks.values() if "set type vlan" in body
    }
    assert parent_of == {
        10: renamed["port-channel1"], 20: renamed["port-channel1"], 30: renamed["Ethernet1/4"],
    }, parent_of
    assert off_its_carrier("cisco_nxos", text, job)[:2] == ([], 3)


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


def _no_carriers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer before it looked for the port that carries a VLAN:
    the scorer chose for every one."""
    monkeypatch.setattr(fgt_render, "_carriers_here", lambda tree, parents: {})


def test_the_check_sees_a_vlan_on_a_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer as it was: anything but a routed sub-interface may
    be a VLAN's parent."""
    _no_carriers(monkeypatch)
    monkeypatch.setattr(fgt_render, "_may_carry_a_vlan", lambda iface: iface.dot1q_vlan is None)
    for source, label, path in _sample():
        if _SAMPLE[label] == "loopback":
            wrong = wrong_parents(source, _output(source, path.read_text(encoding="utf-8")))
            assert wrong and all("cannot carry" in w for w in wrong), label


def test_the_check_sees_a_vlan_on_the_management_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer with a management port ranked as any other."""
    _no_carriers(monkeypatch)
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


def test_the_check_sees_a_vlan_off_its_carrier(monkeypatch: pytest.MonkeyPatch) -> None:
    """The renderer before it looked: on the switch by hand and on the
    captures, VLANs come out on a port that does not carry them."""
    _no_carriers(monkeypatch)
    wrong_somewhere = 0
    for source, _, path in CAPTURES:
        raw = path.read_text(encoding="utf-8")
        wrong_somewhere += bool(off_its_carrier(source, raw, _job(source, raw))[0])
    assert wrong_somewhere >= 10, wrong_somewhere


def test_the_job_check_sees_a_carrier_left_out_said_nowhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """A VLAN whose one carrier the output leaves out, in a job that
    says ``completed``, is seen: the check does not pass it for having
    nothing to judge."""
    text = (
        "hostname x\nvlan 30\n"
        "interface Ethernet1/4\n  switchport mode trunk\n  switchport trunk allowed vlan 30\n"
        "interface Ethernet1/5\n  no switchport\n  ip address 192.168.1.1/24\n"
    )
    job = _job("cisco_nxos", text)
    wrong, judged, gone = off_its_carrier("cisco_nxos", text, job)
    assert (wrong, judged, gone) == ([], 1, [])
    # The output with the trunk's block taken out.
    port = dict(job.port_renames)["Ethernet1/4"]
    lines = (job.rendered or "").splitlines()
    start = lines.index(f'    edit "{port}"')
    end = lines.index("    next", start)
    job.rendered = "\n".join(lines[:start] + lines[end + 1:])
    job.status = type(job.status)("completed")
    wrong, judged, gone = off_its_carrier("cisco_nxos", text, job)
    assert gone and judged == 0
    assert not _left_out_is_said(job, gone)
