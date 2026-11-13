"""A review line a renderer writes for a loss holds the job ``partial``,
and the job says it.

A renderer writes a ``review:`` line where it leaves a record out, or
writes it otherwise than the tree holds it, for a reason of the
target's own: a VRRP group of a protocol the target does not run, a
VLAN FortiOS can give no parent, a trunk of every VLAN on OS10, an
SNMP trap host given a community the source did not state.  The
validation report is made from the tree before the renderer decides,
so it listed none of these, and a job whose only loss was such a line
said ``completed``.  Each such line is made through
:func:`netcanon.migration._said.review`, which adds a warning of the
job that restates it (``Review: <where> -- <why>.``), and the job is
``partial``.

Every line of an output that says ``review`` is one of:

* a line a warning restates: the job is ``partial``, and each such
  warning has its line;
* a DOUBT, which writes what the source holds and asks for a check on
  the device: no warning restates it, and it does not hold the job;
* a line a target says through another channel (a credential, an
  account, a DHCP pool, a bond, the AOS-S management plane and VLAN
  interfaces, a name two source names collide on): the job is
  ``partial``.

The words of the last two are typed here, from what each line says.  A
line that is none of them fails: a renderer that writes a line for a
loss and does not say it.

The guard reads the output and the job, and asks the renderer nothing.
It reads every committed input onto every public codec with no port
map, and synthetic trees that reach the lines no input reaches.  Where
the warnings are made it records which call made each, so that every
call of ``review`` or ``review_line`` in the product -- found by
reading the source -- is reached by one of them.  The lines of
:mod:`netcanon.migration._one_value` are held by their own guard,
``test_a_value_said_holds_the_job.py``, which builds a tree for each.
"""
from __future__ import annotations

import ast
import functools
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from netcanon.migration import _said
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJobStatus
from netcanon.services import migration_pipeline
from netcanon.services.migration_pipeline import run_plan, run_plan_with_checked_names

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures"
PUBLIC = list_public_codecs()
_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py"}
PARTIAL = MigrationJobStatus.partial

#: The words of a review line that writes what the source holds and
#: asks for a check on the device, or says what to do when it is edited
#: there: no warning restates it, and it does not hold the job.
_DOUBTS = (
    # A VLAN device name OPNsense runs as written and whose form
    # refuses it when the VLAN is saved again.
    "OPNsense's VLAN form refuses the device name",
    # A value written as it stands where no page says its place reads
    # to the end of the line (``_one_value``).
    "check it on the device",
    # A trunk's untagged VLAN, written as the tree holds it, where the
    # vendor's pages disagree on what the switch does with it (OS10)
    # or the line says what it does (AOS-S).  Not the IOS-XE or NX-OS
    # trunk that carries no VLAN untagged: that output cannot say so,
    # and the line is a loss.
    "Dell's pages disagree",
    "so no untagged line is written for this port",
    # A Junos unit with no tag beside tagged ones.
    "not established that a unit with no tag commits there",
    # A Junos family MTU and the media MTU it needs.
    "needs a media MTU on",
    # An IOS-XE DHCP pool in a VRF.
    "check that this release takes the vrf form",
)

#: The words of a review line a target says through another channel --
#: ``render_warnings``, the validation report, the check of the names
#: two source names share: the job is ``partial``.
_SAID_ELSEWHERE = (
    # A credential the target cannot carry, and an account.
    "hash from source vendor cannot be re-used on",
    "no password for this account",
    "USM key",
    "shared secret",
    "below an administrator",
    "the source holds this password as typed",
    "a hashed password line",
    "AOS-S keeps one manager account",
    # A DHCP pool.
    "the source states no range for",
    "the source serves this pool on",
    "the source serves this subnet on",
    "names no interface",
    "is not written: EOS states a domain",
    # A bond the target makes no aggregate of.
    "is a bond in the source that needs no aggregate",
    # The AOS-S management plane, VLAN interfaces and loopbacks.
    "a time server of the source",
    "a syslog server of the source",
    "a DNS resolver of the source",
    "is a unit of",
    "stands for VLAN",
    "matches two",
    "is disabled, and an AOS-S VLAN cannot be",
    "which the config also has as a VLAN",
    "an AOS-S loopback",
    # An address AOS-CX takes on no port that has sub-interfaces.
    "beside its sub-interfaces",
    # A name two source names share.
    "collides — kept first occurrence",
    "duplicate dropped -- review source names for unique mapping",
    # A RouterOS tunnel's ends, which no parser reads.
    "tunnel endpoint placeholder",
)


def _flat(text: str) -> str:
    """*text* with no white space: a comment form can space a marker
    (an XML comment holds no ``--``, a VyOS one no ``*/``)."""
    return re.sub(r"\s+", "", text)


def _why(warning: str) -> str:
    """The words a ``Review:`` warning restates, after its place."""
    body = warning.removeprefix("Review: ").removesuffix(".")
    return body.split(" -- ", 1)[1] if " -- " in body else body


def _problems(job: Any) -> list[str]:
    """What is wrong between the review lines of *job*'s output and its
    warnings and status, a sentence each."""
    lines = [line.strip() for line in (job.rendered or "").splitlines() if "review" in line]
    warnings = [w for w in job.warnings if w.startswith("Review: ")]
    whys = [_flat(_why(w)) for w in warnings]
    used = [False] * len(warnings)
    held = job.status is PARTIAL
    problems: list[str] = []
    for line in lines:
        flat = _flat(line)
        said = next((n for n, why in enumerate(whys) if not used[n] and why in flat), None)
        if said is not None:
            used[said] = True
        if any(words in line for words in _DOUBTS):
            if said is not None:
                problems.append(f"a doubt said as a loss: {line[:100]}")
        elif said is not None:
            if not held:
                problems.append(f"a line said, in a job {job.status.value}: {line[:100]}")
        elif any(words in line for words in _SAID_ELSEWHERE):
            if not held:
                problems.append(f"a line said elsewhere, in a job {job.status.value}: {line[:100]}")
        else:
            problems.append(f"a review line no warning restates: {line[:100]}")
    problems += [
        f"a warning with no line: {warnings[n][:100]}"
        for n in range(len(warnings)) if not used[n]
    ]
    return problems


# ---------------------------------------------------------------------------
# Where the warnings are made
# ---------------------------------------------------------------------------


def _relative(filename: str) -> str:
    return Path(filename).resolve().relative_to(ROOT).as_posix()


class _Recorder(list):
    """The warnings of a render, and for each the call that made it:
    the first frame outside ``_said.py`` (``review_line`` calls
    ``review``)."""

    def __init__(self, reached: Counter[tuple[str, int]]) -> None:
        super().__init__()
        self._reached = reached

    def append(self, item: str) -> None:
        frame = sys._getframe(1)
        while frame is not None and Path(frame.f_code.co_filename).name == "_said.py":
            frame = frame.f_back
        assert frame is not None
        self._reached[(_relative(frame.f_code.co_filename), frame.f_lineno)] += 1
        super().append(item)


@contextmanager
def _recording(reached: Counter[tuple[str, int]]) -> Iterator[None]:
    """Every job run in the block records, in *reached*, which call
    made each of its warnings."""

    @contextmanager
    def said_while_rendering() -> Iterator[list[str]]:
        said = _Recorder(reached)
        token = _said._SAID.set(said)
        try:
            yield said
        finally:
            _said._SAID.reset(token)

    with mock.patch.object(migration_pipeline, "said_while_rendering", said_while_rendering):
        yield


def _sites() -> set[tuple[str, int]]:
    """Every call of ``review`` or ``review_line`` in the product, by
    file and line, read from the source: a call of a name a module
    imports from ``_said``, under whatever name it imports it."""
    found: set[tuple[str, int]] = set()
    for path in sorted((ROOT / "netcanon").rglob("*.py")):
        if path.name == "_said.py":
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        names = {
            alias.asname or alias.name
            for node in ast.walk(module)
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("_said")
            for alias in node.names
            if alias.name in ("review", "review_line")
        }
        found |= {
            (_relative(str(path)), node.lineno)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id in names
        }
    return found


# ---------------------------------------------------------------------------
# What is read
# ---------------------------------------------------------------------------


def _captures() -> list[tuple[str, Path]]:
    """(codec, path) for every committed input of a public codec."""
    found: list[tuple[str, Path]] = []
    for root in ("real", "synthetic", "iosxe", "opnsense"):
        for path in sorted(p for p in (FIXTURES / root).rglob("*") if p.is_file()):
            if path.suffix.lower() in _NOT_A_CAPTURE:
                continue
            parts = path.relative_to(FIXTURES).parts
            label = parts[1] if root in ("real", "synthetic") else {"iosxe": "cisco_iosxe"}.get(root, root)
            codec = DIR_TO_CODEC_NAME.get(label, label)
            if label == "cisco_iosxe" and path.suffix.lower() == ".xml":
                codec = "cisco_iosxe"
            if codec in PUBLIC:
                found.append((codec, path))
    return found


def _address(ip: str, length: int) -> CanonicalIPv4Address:
    return CanonicalIPv4Address(ip=ip, prefix_length=length)


def _each_kind() -> CanonicalIntent:
    """A tree that reaches the review lines no committed input reaches:
    a VRRP group with two addresses, two tracked interfaces and an
    authentication that names no scheme; HSRP groups (one with a key no
    target takes as typed and a description, one with nothing at all);
    an EoIP tunnel; a DHCPv6 client of OPNsense's own (``track6``) on a
    port and on a unit; a trunk that allows no VLAN; ports a VLAN names
    (one routed); routed sub-interfaces whose names give no port, one
    of them riding on a port the output does not have, and one whose
    unit is not its tag; a VLAN named as another's id; a static route
    of distance 255; resolvers past three and one that is not an
    address; and a domain that is not a domain name."""
    return CanonicalIntent(
        hostname="s1",
        interfaces=[
            CanonicalInterface(
                name="Vlan10", ipv4_addresses=[_address("192.0.2.3", 26)],
                vrrp_groups=[CanonicalVRRPGroup(
                    group_id=1, virtual_ips=["192.0.2.1", "192.0.2.2"],
                    authentication="zzblob", track_interfaces=["Ethernet3", "Ethernet4"],
                    mode="vrrp",
                )],
            ),
            CanonicalInterface(
                name="Ethernet2", ipv4_addresses=[_address("192.0.2.66", 26)],
                dhcp_client_v6="track6",
                vrrp_groups=[
                    CanonicalVRRPGroup(
                        group_id=2, virtual_ips=["192.0.2.65"], authentication="sha:zz",
                        description="first", mode="hsrp",
                    ),
                    CanonicalVRRPGroup(group_id=3, mode="hsrp", preempt=False),
                ],
            ),
            CanonicalInterface(
                name="Tunnel1", tunnel_type="eoip", interface_type="ianaift:tunnel",
                ipv4_addresses=[_address("192.0.2.129", 30)],
            ),
            CanonicalInterface(name="Ethernet5", switchport_mode="trunk", trunk_allowed_vlans=[]),
            CanonicalInterface(name="1/1/5", switchport_mode="trunk", trunk_allowed_vlans=[]),
            CanonicalInterface(name="igb3"),
            CanonicalInterface(name="igb4"),
            CanonicalInterface(name="igb5", switchport_mode="routed"),
            CanonicalInterface(
                name="subA", dot1q_vlan=200, ipv4_addresses=[_address("192.0.2.133", 30)],
            ),
            CanonicalInterface(
                name="subB", dot1q_vlan=300, vlan_parent="zzport9",
                ipv4_addresses=[_address("192.0.2.137", 30)],
            ),
            CanonicalInterface(
                name="eth1.100", dot1q_vlan=201, dhcp_client_v6="track6",
                ipv4_addresses=[_address("192.0.2.141", 30)],
            ),
        ],
        vlans=[
            CanonicalVlan(id=1, untagged_ports=["igb4"]),
            CanonicalVlan(id=10, name="ten", tagged_ports=["igb3", "igb5"]),
            CanonicalVlan(id=30, name="31"),
        ],
        static_routes=[
            CanonicalStaticRoute(destination="198.51.100.0/24", gateway="192.0.2.70", metric=255),
        ],
        dns_servers=["192.0.2.53", "resolver.invalid", "198.51.100.53", "203.0.113.53", "192.0.2.54"],
        domain="lab_example.net",
    )


def _a_vlan_alone() -> CanonicalIntent:
    """A VLAN and no interface: nothing of the output can carry it."""
    return CanonicalIntent(hostname="s2", vlans=[CanonicalVlan(id=10, name="ten")])


_TREES: dict[str, Callable[[], CanonicalIntent]] = {
    "each kind": _each_kind,
    "a VLAN alone": _a_vlan_alone,
}


class _Gives:
    """A source that gives *tree* for any text, and is otherwise the
    codec it stands in front of."""

    def __init__(self, codec: Any, tree: CanonicalIntent) -> None:
        self._codec = codec
        self._tree = tree

    def __getattr__(self, name: str) -> Any:
        return getattr(self._codec, name)

    def parse(self, text: str) -> CanonicalIntent:
        return self._tree.model_copy(deep=True)


@functools.cache
def _sweep() -> SimpleNamespace:
    """Every committed input and every tree onto every public codec,
    with no port map: what is wrong in each job, how many lines each
    says, and which calls made the warnings."""
    reached: Counter[tuple[str, int]] = Counter()
    inputs: list[str] = []
    trees: list[str] = []
    said = 0
    with _recording(reached):
        for codec, path in _captures():
            text = path.read_text(encoding="utf-8", errors="replace")
            for target in PUBLIC:
                job = run_plan_with_checked_names(
                    get_codec(codec), get_codec(target), text, port_rename_map={},
                )
                where = f"{path.relative_to(FIXTURES).as_posix()} -> {target}"
                inputs += [f"{where}: {problem}" for problem in _problems(job)]
                said += sum(w.startswith("Review: ") for w in job.warnings)
        for name, build in _TREES.items():
            for target in PUBLIC:
                job = run_plan(_Gives(get_codec("cisco_iosxe_cli"), build()), get_codec(target), "x\n")
                trees += [f"{name} -> {target}: {problem}" for problem in _problems(job)]
    return SimpleNamespace(inputs=inputs, trees=trees, said=said, reached=reached)


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def test_every_review_line_of_the_inputs_is_said_doubted_or_said_elsewhere() -> None:
    sweep = _sweep()
    assert sweep.inputs == []
    # A sweep that reads no line passes the line above.
    assert sweep.said > 0


def test_every_review_line_of_the_trees_is_said_doubted_or_said_elsewhere() -> None:
    assert _sweep().trees == []


def test_every_call_that_makes_a_review_line_is_reached() -> None:
    """Completeness by experiment, not by a list: a call no input and
    no tree reaches is a line nothing above has read."""
    sites = _sites()
    reached = set(_sweep().reached)
    # The recorder and the reading of the source agree on what a call
    # is: none was reached that the reading did not find.
    assert reached - sites == set()
    own = {site for site in sites if not site[0].endswith("/_one_value.py")}
    assert sorted(own - reached) == []
    # A reading that finds nothing passes the line above.
    assert len(own) > 1


# ---------------------------------------------------------------------------
# Each check, handed what it is for
# ---------------------------------------------------------------------------


def _job(rendered: str, warnings: list[str], status: MigrationJobStatus = PARTIAL) -> Any:
    return SimpleNamespace(rendered=rendered, warnings=warnings, status=status)


_LINE = "        # review: VLAN 10 has no parent -- set the port it rides on"
_SAID = "Review: interface vlan10 -- VLAN 10 has no parent -- set the port it rides on."


class TestEachCheckFails:
    def test_a_line_and_its_warning_pass(self) -> None:
        assert _problems(_job(_LINE, [_SAID])) == []

    def test_a_line_no_warning_restates(self) -> None:
        assert _problems(_job(_LINE, [])) == [
            "a review line no warning restates: " + _LINE.strip(),
        ]

    def test_a_warning_with_no_line(self) -> None:
        assert _problems(_job("hostname s1", [_SAID])) == ["a warning with no line: " + _SAID]

    def test_two_lines_and_one_warning(self) -> None:
        problems = _problems(_job(f"{_LINE}\n{_LINE}", [_SAID]))
        assert problems == ["a review line no warning restates: " + _LINE.strip()]

    def test_a_line_said_in_a_job_that_says_completed(self) -> None:
        problems = _problems(_job(_LINE, [_SAID], MigrationJobStatus.completed))
        assert problems == ["a line said, in a job completed: " + _LINE.strip()]

    def test_a_doubt_said_as_a_loss(self) -> None:
        line = "! review: it is written as it stands, check it on the device"
        assert _problems(_job(line, [])) == []
        assert _problems(_job(line, [], MigrationJobStatus.completed)) == []
        problems = _problems(_job(line, ["Review: it is written as it stands, check it on the device."]))
        assert problems == ["a doubt said as a loss: " + line]

    def test_a_line_said_elsewhere_in_a_job_that_says_completed(self) -> None:
        line = "! review: sha512 hash from source vendor cannot be re-used on Cisco IOS-XE"
        assert _problems(_job(line, [])) == []
        assert _problems(_job(line, [], MigrationJobStatus.completed)) == [
            "a line said elsewhere, in a job completed: " + line,
        ]

    def test_a_comment_that_spaces_its_marker(self) -> None:
        """An XML comment holds no ``--``: the line is ``- -``."""
        line = "<!-- review: VLAN 10 has no parent - - set the port it rides on -->"
        assert _problems(_job(line, [_SAID])) == []

    def test_a_render_that_does_not_say_its_line(self) -> None:
        """A real render whose warnings are not collected: its line is
        found with no warning."""
        target = get_codec("fortigate_cli")
        with mock.patch.object(migration_pipeline, "said_while_rendering", _not_collected):
            job = run_plan(_Gives(get_codec("cisco_iosxe_cli"), _a_vlan_alone()), target, "x\n")
        problems = _problems(job)
        assert problems and all("no warning restates" in p for p in problems), problems

    def test_the_recorder_names_the_call(self) -> None:
        reached: Counter[tuple[str, int]] = Counter()
        with _recording(reached):
            run_plan(_Gives(get_codec("cisco_iosxe_cli"), _a_vlan_alone()), get_codec("fortigate_cli"), "x\n")
        assert reached
        assert {path for path, _line in reached} == {
            "netcanon/migration/codecs/fortigate_cli/render.py",
        }
        assert set(reached) <= _sites()


@contextmanager
def _not_collected() -> Iterator[list[str]]:
    """A render whose review lines are made with no job to say them in."""
    yield []
