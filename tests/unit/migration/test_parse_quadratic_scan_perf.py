"""Quadratic-scan sweep — parse hot paths must stay linear (#30-#33).

The 2026-07-06 Fable review flagged five ``next()`` / list-membership scans
against a list that grows per iteration inside parse hot paths — one shape,
several sites (theme 5).  ``merge_trunk_allowed`` (#11) shipped in the prior
wave; this batch closes the remaining four:

* ``fortigate_cli`` LAG first-pass reverse-link — O(members x interfaces) (#30)
* ``arista_eos`` channel-group reverse-link — O(D**2) via ``next()`` (#31)
* ``juniper_junos`` ``set vlans`` id/name + irb-fold scans — O(n**2) (#32)
* ``services.diff`` ``SequenceMatcher(autojunk=False)`` — O(n**2) (#33)

Each fix is a behaviour-identical dict/set swap (order + values preserved), so
the cross-mesh baseline is unchanged; these tests pin BOTH the behaviour
(identity on the tricky edges) and the now-linear complexity.

The perf assertions are negative controls: verified to FAIL against the
pre-fix quadratic (times below are local, measured by stashing the fix) and
pass with a wide margin post-fix.  Bounded cases (junos VLANs cap at VID 4094,
so the absolute time can't blow up) use a machine-independent scaling ratio
instead of an absolute ceiling.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.juniper_junos import JunosCodec
from netcanon.models.backup import ConfigRecord
from netcanon.services.diff import compute_diff

pytestmark = pytest.mark.unit


# ── #30 fortigate LAG reverse-link ─────────────────────────────────────


def _fortigate_lag_config(n: int) -> str:
    """``n`` member ports followed by ``n`` single-member aggregates."""
    lines = ["config system interface"]
    for i in range(n):
        lines += [f'    edit "port{i}"', "        set vdom root", "    next"]
    for a in range(n):
        lines += [
            f'    edit "agg{a}"',
            "        set type aggregate",
            f'        set member "port{a}"',
            "    next",
        ]
    lines.append("end")
    return "\n".join(lines) + "\n"


class TestFortigateLagReverseLinkLinear:
    def test_member_reverse_link_unchanged(self) -> None:
        # Both the first-pass (member defined BEFORE its aggregate) and the
        # second-pass (member defined AFTER) reverse-links must stamp.
        cfg = (
            "config system interface\n"
            '    edit "port1"\n        set vdom root\n    next\n'      # before agg
            '    edit "ag1"\n        set type aggregate\n'
            '        set member "port1" "port2"\n    next\n'
            '    edit "port2"\n        set vdom root\n    next\n'      # after agg
            "end\n"
        )
        intent = FortiGateCLICodec().parse(cfg)
        by_name = {i.name: i for i in intent.interfaces}
        assert by_name["port1"].lag_member_of == "ag1"   # first-pass
        assert by_name["port2"].lag_member_of == "ag1"   # second-pass

    def test_first_pass_reverse_link_is_linear(self) -> None:
        # Pre-fix (O(members x interfaces)): n=8000 ~3 s.  Post-fix ~0.26 s.
        cfg = _fortigate_lag_config(8000)
        start = time.perf_counter()
        intent = FortiGateCLICodec().parse(cfg)
        elapsed = time.perf_counter() - start
        assert len(intent.lags) == 8000
        assert elapsed < 1.5, f"fortigate LAG reverse-link is quadratic ({elapsed:.2f}s)"


# ── #31 arista channel-group reverse-link ──────────────────────────────


class TestAristaChannelGroupLinear:
    def test_channel_group_binding_unchanged(self) -> None:
        cfg = (
            "hostname sw1\n"
            "interface Ethernet1\n   channel-group 5 mode active\n"
            "interface Ethernet2\n   channel-group 5 mode active\n"
        )
        intent = AristaEOSCodec().parse(cfg)
        lag = next(lag for lag in intent.lags if lag.name == "Port-Channel5")
        assert sorted(lag.members) == ["Ethernet1", "Ethernet2"]
        by_name = {i.name: i for i in intent.interfaces}
        assert by_name["Ethernet1"].lag_member_of == "Port-Channel5"

    def test_channel_group_reverse_link_is_linear(self) -> None:
        # Pre-fix (O(D**2) next() rescan): D=16000 ~3.9 s.  Post-fix ~0.19 s.
        lines = ["hostname sw1"]
        for i in range(1, 16001):
            lines += [f"interface Ethernet{i}", f"   channel-group {i} mode active"]
        cfg = "\n".join(lines) + "\n"
        start = time.perf_counter()
        intent = AristaEOSCodec().parse(cfg)
        elapsed = time.perf_counter() - start
        assert len(intent.lags) == 16000
        assert elapsed < 1.5, f"arista channel-group scan is quadratic ({elapsed:.2f}s)"


# ── #32 junos set-vlans id/name index ──────────────────────────────────


class TestJunosVlanIndexLinear:
    def test_duplicate_name_keeps_first_for_vxlan(self) -> None:
        # Two VLANs share a name (different ids): the vxlan-vni binding by
        # name must still resolve to the FIRST (keep-first, as next() did).
        cfg = (
            "set vlans DUP vlan-id 10\n"
            "set vlans DUP vlan-id 20\n"
            "set vlans DUP vxlan vni 5000\n"
        )
        intent = JunosCodec().parse(cfg)
        assert sorted(v.id for v in intent.vlans) == [10, 20]
        assert [(x.vlan_id, x.vni) for x in intent.vxlan_vnis] == [(10, 5000)]

    def test_same_id_second_line_renames(self) -> None:
        # ``vlan-id`` lookup is by id: the second line renames the id-10 VLAN
        # rather than creating a duplicate.
        cfg = "set vlans FOO vlan-id 10\nset vlans BAR vlan-id 10\n"
        intent = JunosCodec().parse(cfg)
        assert len(intent.vlans) == 1
        assert intent.vlans[0].id == 10
        assert intent.vlans[0].name == "BAR"

    def test_vlan_index_is_linear_not_quadratic(self) -> None:
        # VLAN ids cap at 4094 so the absolute time can't blow up — assert the
        # SHAPE instead: doubling the VLAN count must not ~4x the time.
        # Pre-fix ratio ~3.6 (quadratic); post-fix ~2.0 (linear).
        def parse_v(v: int) -> None:
            lines = [f"set vlans V{i} vlan-id {i}" for i in range(2, v + 2)]
            JunosCodec().parse("\n".join(lines) + "\n")

        def best(v: int) -> float:
            times = []
            for _ in range(3):
                start = time.perf_counter()
                parse_v(v)
                times.append(time.perf_counter() - start)
            return min(times)

        parse_v(1500)  # warm up import/JIT caches
        ratio = best(3000) / best(1500)
        assert ratio < 3.0, f"junos vlan index scales quadratically (2x count -> {ratio:.1f}x time)"


# ── #33 services.diff autojunk ─────────────────────────────────────────


def _rec() -> ConfigRecord:
    return ConfigRecord(
        device_type="Cisco",
        host="10.0.0.1",
        timestamp=datetime(2026, 4, 16, tzinfo=UTC),
        filename="c.cfg",
        file_extension="cfg",
        size_bytes=100,
    )


class TestDiffAutojunkLinear:
    def test_realistic_diff_stays_minimal(self) -> None:
        # On a realistic config (diverse interface stanzas with ``!``
        # delimiters) dropping autojunk=False leaves the diff minimal: a
        # single changed line -> exactly 1 removed + 1 added, the rest equal.
        # (autojunk only degrades minimality on pathological >90%-repeated
        # inputs, where the result is still correct — just noisier.)
        lines: list[str] = []
        for i in range(60):
            lines += [f"interface Gi0/{i}", f" description uplink-{i}", " no shutdown", "!"]
        left = "\n".join(lines)
        changed = list(lines)
        changed[1] = " description CHANGED"
        right = "\n".join(changed)
        report = compute_diff(_rec(), left, _rec(), right)
        assert report.stats["removed"] == 1
        assert report.stats["added"] == 1

    def test_identical_configs_diff_fully_equal(self) -> None:
        # The invariant that must hold regardless of autojunk: identical
        # inputs produce zero add/remove churn.
        text = "\n".join(["!" if i % 2 else f"line{i % 10}" for i in range(500)])
        report = compute_diff(_rec(), text, _rec(), text)
        assert report.stats["added"] == 0
        assert report.stats["removed"] == 0

    def test_diff_of_repeated_lines_is_linear(self) -> None:
        # Pre-fix (autojunk=False -> O(n**2) on repeated ``!``): 30k lines
        # ~18 s.  Post-fix (default autojunk) ~0.08 s.
        left = "\n".join(["!" if i % 2 else f"line{i % 50}" for i in range(30000)])
        right = left.replace("line3", "lineX", 1)
        start = time.perf_counter()
        compute_diff(_rec(), left, _rec(), right)
        elapsed = time.perf_counter() - start
        assert elapsed < 3.0, f"compute_diff is quadratic on repeated lines ({elapsed:.2f}s)"


# ── HEAD-review P1: junos trunk ``members`` range x growing-list dedup ──
# The #8 numeric-range spelling (in-range since the last review) made the junos
# trunk dedup O(range x list): ``members 1-4094`` expands to 4094 VIDs, each
# previously ``not in``-tested over a list that grows to 4094 (~16.7M compares
# per line).  Set-guarded, mirroring #11.  Un-hardened sibling of that fix.

_JUNOS_TRUNK_BASE = (
    "set interfaces xe-0/0/0 unit 0 family ethernet-switching interface-mode trunk\n"
)
_JUNOS_TRUNK_FULL_RANGE = (
    "set interfaces xe-0/0/0 unit 0 family ethernet-switching vlan members 1-4094\n"
)


class TestJunosTrunkMembersLinear:
    def test_repeated_full_range_dedup_unchanged(self) -> None:
        # A second full-range line must not duplicate: set-guarded dedup keeps
        # first-seen (VID-ascending) order -> the union is exactly 1..4094.
        intent = JunosCodec().parse(
            _JUNOS_TRUNK_BASE + _JUNOS_TRUNK_FULL_RANGE * 2
        )
        trunk = next(
            i.trunk_allowed_vlans for i in intent.interfaces if i.trunk_allowed_vlans
        )
        assert trunk == list(range(1, 4095))

    def test_repeated_full_range_is_linear(self) -> None:
        # Pre-fix (O(range x list)): 32 full-range lines ~1.1 s.  Post-fix
        # (set-guard): ~5 ms.  The ~265x separation makes an absolute ceiling a
        # clean, machine-tolerant negative control.
        cfg = _JUNOS_TRUNK_BASE + _JUNOS_TRUNK_FULL_RANGE * 32
        start = time.perf_counter()
        intent = JunosCodec().parse(cfg)
        elapsed = time.perf_counter() - start
        trunk = next(
            i.trunk_allowed_vlans for i in intent.interfaces if i.trunk_allowed_vlans
        )
        assert len(trunk) == 4094
        assert elapsed < 0.5, f"junos trunk range dedup is quadratic ({elapsed:.2f}s)"


# ── HEAD-review P2: mgmt-plane server-list dedup via list membership ────
# The #347/#352-#354 DNS/NTP/syslog wire-ups deduped additive server lists with
# ``token not in intent.<list>`` -> O(N**2) in the count of DISTINCT servers.
# Fixed with a per-list ``set`` seen-guard (finditer sites) or append-then-
# dedup-once-at-parse-end (junos per-stanza).  Both preserve first-seen order.


class TestMgmtPlaneServerDedupLinear:
    def test_arista_syslog_dedup_first_seen_unchanged(self) -> None:
        cfg = (
            "hostname r\nlogging host 10.0.0.1\nlogging host 10.0.0.2\n"
            "logging host 10.0.0.1\n"
        )
        assert AristaEOSCodec().parse(cfg).syslog_servers == ["10.0.0.1", "10.0.0.2"]

    def test_junos_server_lists_dedup_at_end_unchanged(self) -> None:
        # Append-then-dedup-once: duplicates removed, first-seen order kept.
        cfg = (
            "set system name-server 10.0.0.1\nset system name-server 10.0.0.1\n"
            "set system name-server 10.0.0.2\n"
            "set system ntp server 10.1.0.1\nset system ntp server 10.1.0.1\n"
            "set system syslog host 10.2.0.1\nset system syslog host 10.2.0.1\n"
        )
        intent = JunosCodec().parse(cfg)
        assert intent.dns_servers == ["10.0.0.1", "10.0.0.2"]
        assert intent.ntp_servers == ["10.1.0.1"]
        assert intent.syslog_servers == ["10.2.0.1"]

    def test_arista_syslog_dedup_is_linear(self) -> None:
        # Pre-fix O(N**2) in distinct servers; post-fix set-guarded linear.
        # 4x the server count -> ~4x time when linear, ~16x when quadratic;
        # assert well under the quadratic line (machine-independent ratio).
        def parse_n(n: int) -> None:
            lines = ["hostname r"]
            lines += [f"logging host 10.{i // 256 % 256}.{i % 256}.1" for i in range(n)]
            AristaEOSCodec().parse("\n".join(lines) + "\n")

        def best(n: int) -> float:
            times = []
            for _ in range(3):
                start = time.perf_counter()
                parse_n(n)
                times.append(time.perf_counter() - start)
            return min(times)

        best(4000)  # warm up import/JIT caches
        ratio = best(16000) / best(4000)
        assert ratio < 8.0, f"arista syslog dedup scales quadratically (4x count -> {ratio:.1f}x time)"
