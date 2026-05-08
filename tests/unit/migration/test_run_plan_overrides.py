"""
Unit tests for :func:`netcanon.services.migration_pipeline.run_plan_with_overrides`.

This is the shared engine introduced in P2C1.  It subsumes the port-
rename-specific path that :func:`run_plan_with_rename` used to provide
directly; the wrapper now delegates here.  Future commits (P2C2+) will
extend this function with additional per-category override parameters
(VLAN mapping, local users, SNMP, …) — each a same-signature addition.

Invariants these tests lock in:

  1. Wrapper delegation — ``run_plan_with_rename`` and
     ``run_plan_with_overrides`` produce identical canonical outcomes
     when given the same port_rename_map.  Signature of the wrapper
     is frozen per CLAUDE.md; the implementation can change as long
     as this invariant holds.

  2. ``port_rename_map=None`` means "don't engage the rename
     pipeline" — same behaviour as calling :func:`run_plan` directly.
     The UI's "no target profile selected, no overrides" state maps
     here.

  3. ``port_rename_map={}`` means "engage the rename pipeline,
     auto-heuristic only" — this is the opt-in sentinel the UI
     sends when a target profile IS selected but no rows have been
     customised.  Distinct from None above.

  4. Per-category outcomes (``port_renames`` / ``port_drops`` /
     ``warnings``) are populated only when their category's override
     was engaged.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.aruba_aoss import ArubaAOSSCodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.services.migration_pipeline import (
    run_plan,
    run_plan_with_overrides,
    run_plan_with_rename,
)

pytestmark = pytest.mark.unit


#: Minimal Cisco IOS-XE config that exercises the rename orchestrator
#: (real port names on a stacked chassis so the Cisco→Aruba
#: ``GigabitEthernet1/0/N`` → ``1/N`` stripping path is engaged).
_IOSXE_SRC = """\
hostname Core-SW
!
interface GigabitEthernet1/0/1
 description Desk
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet1/0/24
 description Uplink
!
vlan 10
 name USERS
!
"""


class TestWrapperDelegation:
    """``run_plan_with_rename`` is now a thin wrapper around
    ``run_plan_with_overrides``.  These tests lock in the delegation:
    same inputs → same outcome."""

    def test_wrapper_normalises_none_to_empty_map(self):
        """Pre-P2C1 behaviour preservation: calling the wrapper with
        no rename map ALWAYS engaged the rename pipeline (the
        pre-refactor code unconditionally called
        ``build_port_rename_transform``).  The new engine treats
        ``None`` as "don't engage"; the wrapper normalises ``None``
        → ``{}`` to keep legacy callers' behaviour intact.

        Verified by comparing wrapper(no_map) to engine({}): same
        outcome."""
        source, target = CiscoIOSXECLICodec(), CiscoIOSXECLICodec()
        wrapper_no_map = run_plan_with_rename(source, target, _IOSXE_SRC)
        engine_empty = run_plan_with_overrides(
            source, target, _IOSXE_SRC, port_rename_map={}
        )
        assert wrapper_no_map.status == engine_empty.status
        assert wrapper_no_map.rendered == engine_empty.rendered
        assert wrapper_no_map.port_renames == engine_empty.port_renames

    def test_wrapper_delegates_with_empty_map(self):
        """Empty dict is the UI's "engage auto-heuristic" sentinel —
        wrapper and engine must agree on what that means."""
        source, target = CiscoIOSXECLICodec(), ArubaAOSSCodec()
        wrapper = run_plan_with_rename(
            source, target, _IOSXE_SRC, port_rename_map={}
        )
        direct = run_plan_with_overrides(
            source, target, _IOSXE_SRC, port_rename_map={}
        )
        assert wrapper.status == direct.status
        assert wrapper.rendered == direct.rendered
        assert wrapper.port_renames == direct.port_renames

    def test_wrapper_delegates_with_user_overrides(self):
        source, target = CiscoIOSXECLICodec(), CiscoIOSXECLICodec()
        overrides = {"GigabitEthernet1/0/1": "GigabitEthernet1/0/99"}
        wrapper = run_plan_with_rename(
            source, target, _IOSXE_SRC, port_rename_map=overrides
        )
        direct = run_plan_with_overrides(
            source, target, _IOSXE_SRC, port_rename_map=overrides
        )
        assert wrapper.status == direct.status
        assert wrapper.rendered == direct.rendered
        assert wrapper.port_renames == direct.port_renames


class TestRenameEngagementSentinel:
    """``port_rename_map=None`` disengages the rename orchestrator;
    ``port_rename_map={}`` engages it (with auto-heuristic only).
    This distinction is load-bearing for the UI: passing {} when
    a target profile is selected lets the server compute auto-
    renames the UI can present for review."""

    def test_none_map_leaves_port_renames_empty(self):
        source, target = CiscoIOSXECLICodec(), CiscoIOSXECLICodec()
        job = run_plan_with_overrides(source, target, _IOSXE_SRC)
        # port_renames defaults to empty dict; no orchestrator ran.
        assert job.port_renames == {}

    def test_none_map_matches_run_plan_rendered_output(self):
        """With port_rename_map=None the overrides function should
        produce byte-identical rendered output to plain run_plan
        (no additional transforms applied)."""
        source, target = CiscoIOSXECLICodec(), CiscoIOSXECLICodec()
        plain = run_plan(source, target, _IOSXE_SRC)
        overrides = run_plan_with_overrides(source, target, _IOSXE_SRC)
        assert plain.rendered == overrides.rendered

    def test_empty_map_engages_pipeline_for_cross_vendor(self):
        """Cisco→Aruba with empty override map: auto-heuristic runs
        and produces port_renames reflecting the ``/0/`` strip."""
        source, target = CiscoIOSXECLICodec(), ArubaAOSSCodec()
        job = run_plan_with_overrides(
            source, target, _IOSXE_SRC, port_rename_map={}
        )
        # port_renames populated by the auto-heuristic for cross-
        # vendor translation.
        assert job.port_renames
        # The classic auto-heuristic strips the middle /0/ so
        # GigabitEthernet1/0/1 → 1/1 on the Aruba side.
        assert job.port_renames.get("GigabitEthernet1/0/1") == "1/1"


class TestUserOverrideWinsOverAutoHeuristic:
    """Explicit entries in port_rename_map take precedence over the
    codec pair's auto-classification.  Tier-3 operator intent
    overrides Tier-2 heuristics."""

    def test_user_rename_wins(self):
        source, target = CiscoIOSXECLICodec(), ArubaAOSSCodec()
        overrides = {"GigabitEthernet1/0/1": "1/A1"}  # user-forced uplink
        job = run_plan_with_overrides(
            source, target, _IOSXE_SRC, port_rename_map=overrides
        )
        # Auto would have produced "1/1"; user override takes precedence.
        assert job.port_renames.get("GigabitEthernet1/0/1") == "1/A1"


class TestDropSentinel:
    """``port_rename_map[src] = None`` is the "drop this port"
    sentinel — the port is removed from the rendered output
    entirely.  Reports as job.port_drops on the resulting job."""

    def test_explicit_drop_appears_in_port_drops(self):
        source, target = CiscoIOSXECLICodec(), CiscoIOSXECLICodec()
        overrides = {"GigabitEthernet1/0/24": None}
        job = run_plan_with_overrides(
            source, target, _IOSXE_SRC, port_rename_map=overrides
        )
        assert "GigabitEthernet1/0/24" in job.port_drops
