"""
Regression tests for the trunk ``allowed vlan add`` / ``remove`` collapse
(blind-audit ``65f9c01`` T0-1).

``show running-config`` renders a long trunk allowed-list across multiple
lines using the relative keyword forms::

    switchport trunk allowed vlan 10,20
    switchport trunk allowed vlan add 30,40

Before the fix, every Cisco-family parser (``cisco_iosxe_cli``,
``cisco_nxos``, ``arista_eos``) OVERWROTE ``trunk_allowed`` per line
(keeping only the last) AND the leading ``add`` keyword glued onto the
first id token (``"add 30"`` -> non-numeric -> silently skipped).  So the
sequence above collapsed to ``[40]`` — VLANs 10/20 lost to the overwrite,
30 lost as non-numeric — with no warning and ``severity=ok``.  This is the
*default* rendering of a long allowed-list, not an edge case.

The fix routes all three through
:func:`netcanon.migration.codecs._helpers.merge_trunk_allowed`, which
strips the keyword and applies it (union / subtract / set / none / all /
except) relative to the running list.  The bare single-line form is
byte-identical to the prior behaviour, so existing round-trips are
unchanged.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs._helpers import merge_trunk_allowed
from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.cisco_nxos import CiscoNXOSCodec

pytestmark = pytest.mark.unit


# ── shared-helper logic ───────────────────────────────────────────────


class TestMergeTrunkAllowed:
    def test_bare_list_sets_membership(self) -> None:
        # No keyword -> identical to the prior ``_parse_vlan_list`` path:
        # input order preserved, ranges expanded, no de-dup.
        assert merge_trunk_allowed([], "10,20,30-32") == [10, 20, 30, 31, 32]

    def test_bare_list_replaces_existing(self) -> None:
        # A second bare line SETS (replaces) — Cisco's non-keyword form.
        assert merge_trunk_allowed([10, 20], "30,40") == [30, 40]

    def test_add_unions_in_order(self) -> None:
        assert merge_trunk_allowed([10, 20], "add 30,40") == [10, 20, 30, 40]

    def test_add_with_no_prior_list(self) -> None:
        # The exact audit repro for a lone ``add`` line: used to drop to
        # [40] (``"add 30"`` eaten), now keeps both ids.
        assert merge_trunk_allowed([], "add 30,40") == [30, 40]

    def test_add_is_idempotent_on_duplicates(self) -> None:
        assert merge_trunk_allowed([10, 20], "add 20,30") == [10, 20, 30]

    def test_remove_subtracts_preserving_order(self) -> None:
        assert merge_trunk_allowed([10, 20, 30, 40], "remove 20") == [
            10,
            30,
            40,
        ]

    def test_none_clears(self) -> None:
        assert merge_trunk_allowed([10, 20], "none") == []

    def test_all_is_full_range(self) -> None:
        assert merge_trunk_allowed([10], "all") == list(range(1, 4095))

    def test_except_is_complement(self) -> None:
        result = merge_trunk_allowed([10], "except 100,200")
        assert 100 not in result and 200 not in result
        assert result[0] == 1 and result[-1] == 4094
        assert len(result) == 4094 - 2

    def test_keyword_is_case_insensitive(self) -> None:
        assert merge_trunk_allowed([10], "ADD 20") == [10, 20]


# ── per-codec wiring (the regex must capture the keyword and the call
#    must route through the merge helper) ──────────────────────────────


def _iosxe_trunk(*allowed_lines: str) -> list[int]:
    cfg = (
        "hostname r1\n"
        "!\n"
        "interface GigabitEthernet0/0/0\n"
        " switchport mode trunk\n"
        + "".join(f" switchport trunk allowed vlan {ln}\n" for ln in allowed_lines)
        + "!\n"
        "end\n"
    )
    intent = CiscoIOSXECLICodec().parse(cfg)
    iface = next(
        i for i in intent.interfaces if i.name == "GigabitEthernet0/0/0"
    )
    return iface.trunk_allowed_vlans


def _nxos_trunk(*allowed_lines: str) -> list[int]:
    cfg = (
        "hostname r1\n"
        "feature interface-vlan\n"
        "interface Ethernet1/1\n"
        "  switchport mode trunk\n"
        + "".join(
            f"  switchport trunk allowed vlan {ln}\n" for ln in allowed_lines
        )
    )
    intent = CiscoNXOSCodec().parse(cfg)
    iface = next(i for i in intent.interfaces if i.name == "Ethernet1/1")
    return iface.trunk_allowed_vlans


def _arista_trunk(*allowed_lines: str) -> list[int]:
    cfg = (
        "hostname sw1\n"
        "interface Ethernet1\n"
        "   switchport mode trunk\n"
        + "".join(
            f"   switchport trunk allowed vlan {ln}\n" for ln in allowed_lines
        )
    )
    intent = AristaEOSCodec().parse(cfg)
    iface = next(i for i in intent.interfaces if i.name == "Ethernet1")
    return iface.trunk_allowed_vlans


class TestMultiLineAddWiring:
    """The continuation-line ``add`` form must union, not collapse to
    ``[40]``, for every Cisco-family codec."""

    def test_iosxe_add_unions(self) -> None:
        assert _iosxe_trunk("10,20", "add 30,40") == [10, 20, 30, 40]

    def test_nxos_add_unions(self) -> None:
        assert _nxos_trunk("10,20", "add 30,40") == [10, 20, 30, 40]

    def test_arista_add_unions(self) -> None:
        assert _arista_trunk("10,20", "add 30,40") == [10, 20, 30, 40]

    def test_iosxe_remove_subtracts(self) -> None:
        assert _iosxe_trunk("10,20,30", "remove 20") == [10, 30]

    def test_nxos_remove_subtracts(self) -> None:
        assert _nxos_trunk("10,20,30", "remove 20") == [10, 30]

    def test_arista_remove_subtracts(self) -> None:
        assert _arista_trunk("10,20,30", "remove 20") == [10, 30]

    def test_bare_single_line_unchanged_iosxe(self) -> None:
        # Lock the byte-identical single-line behaviour the whole corpus
        # relies on (input order preserved, range expanded).
        assert _iosxe_trunk("10,20,30-32") == [10, 20, 30, 31, 32]

    def test_bare_single_line_unchanged_arista(self) -> None:
        assert _arista_trunk("10,20,30-32") == [10, 20, 30, 31, 32]


class TestAddIsLinearNotQuadratic:
    """(#11) The ``add`` branch used ``vid not in base`` (O(len(base)) per
    id), so K repeated ``add 1-4094`` lines cost ~8.4M comparisons each.
    The set-membership fix is behaviour-identical AND linear."""

    def test_add_semantics_unchanged(self) -> None:
        # Behaviour identity: union, order preserved, no re-dup of ids
        # already present, ids duplicated within one line still resolve
        # the same (the comprehension never observed its own additions).
        assert merge_trunk_allowed([10, 20], "add 30,40") == [10, 20, 30, 40]
        assert merge_trunk_allowed([10, 20], "add 20,30") == [10, 20, 30]
        assert merge_trunk_allowed([10], "add 30,30") == [10, 30, 30]

    def test_repeated_full_range_add_is_fast(self) -> None:
        # Pre-fix: 200× ``add 1-4094`` against a growing 4094-list took
        # ~7 s (quadratic).  Post-fix it's ~0.03 s.  A 4 s ceiling fails
        # the quadratic path with a wide margin either direction.
        import time

        existing: list[int] = []
        start = time.perf_counter()
        for _ in range(200):
            existing = merge_trunk_allowed(existing, "add 1-4094")
        elapsed = time.perf_counter() - start
        assert existing == list(range(1, 4095))
        assert elapsed < 4.0, f"add merge is quadratic ({elapsed:.1f}s)"
