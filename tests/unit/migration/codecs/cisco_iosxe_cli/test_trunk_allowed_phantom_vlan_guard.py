"""
Regression tests for the cisco_iosxe_cli trunk-allowed phantom-VLAN guard.

Before this fix, ``netcanon/migration/codecs/cisco_iosxe_cli/parse.py``
called :func:`canonical.transforms.project_switchport_to_vlan` at the
end of parse to mirror per-port switchport state into the VLAN-centric
``tagged_ports`` / ``untagged_ports`` lists.  The shared transform
synthesises bare :class:`CanonicalVlan` records for every VID
referenced by a ``switchport ... vlan`` line that didn't have a
matching top-level ``vlan <N>`` stanza.  Its built-in guard only
suppressed the exact full ``1-4094`` / ``2-4094`` "trunk all" sentinel
— partial wide ranges (e.g. ``switchport trunk allowed vlan
100-3000``) silently inflated ``tree.vlans`` from a handful of
legitimate entries to thousands of phantom records.

Flagged by the arista_eos source Phase 4b agent as a top-3 fix (worst
real-capture case: 15 source VLANs → 4093 canonical VLANs).  Fix in
:func:`cisco_iosxe_cli.parse.parse_intent` snapshots the legitimate
VLAN-id set BEFORE projection and prunes phantoms AFTER.

The per-port :attr:`CanonicalInterface.trunk_allowed_vlans` is
unaffected — that's the L2 attribute the operator wrote and it must
round-trip through canonical unchanged.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.cisco_iosxe_cli.parse import parse_intent

pytestmark = pytest.mark.unit


def test_cisco_trunk_allowed_does_not_inflate_vlans() -> None:
    """``switchport trunk allowed vlan 1-4094`` with only ONE explicit
    ``vlan <N> / name X`` stanza must produce ``len(tree.vlans) == 1``
    (just the explicit one), not 4094 phantom synthesised records.

    The per-port ``trunk_allowed_vlans`` attribute carries the full
    1-4094 list as parsed — that's the L2 wire form and must
    round-trip unchanged.
    """
    cfg = (
        "hostname r1\n"
        "!\n"
        "vlan 10\n"
        " name FOO\n"
        "!\n"
        "interface GigabitEthernet0/0/0\n"
        " switchport mode trunk\n"
        " switchport trunk allowed vlan 1-4094\n"
        " no shutdown\n"
        "!\n"
        "end\n"
    )
    tree = parse_intent(cfg)
    # Only the explicit ``vlan 10`` stanza survives.
    assert len(tree.vlans) == 1
    assert tree.vlans[0].id == 10
    assert tree.vlans[0].name == "FOO"
    # Per-port attribute carries the full range as parsed.
    iface = next(
        i for i in tree.interfaces if i.name == "GigabitEthernet0/0/0"
    )
    assert iface.trunk_allowed_vlans == list(range(1, 4095))


def test_cisco_trunk_allowed_with_explicit_subset_keeps_explicit() -> None:
    """``switchport trunk allowed vlan 10,20,30`` with explicit
    ``vlan 10`` and ``vlan 20`` stanzas (and NO ``vlan 30``) must keep
    the 2 explicit definitions on ``tree.vlans`` and drop the phantom
    VID 30.  ``trunk_allowed_vlans`` on the interface stays at
    ``[10, 20, 30]`` — it's the per-port L2 attribute, not the VLAN
    database."""
    cfg = (
        "hostname r1\n"
        "!\n"
        "vlan 10\n"
        " name V10\n"
        "!\n"
        "vlan 20\n"
        " name V20\n"
        "!\n"
        "interface GigabitEthernet0/0/0\n"
        " switchport mode trunk\n"
        " switchport trunk allowed vlan 10,20,30\n"
        " no shutdown\n"
        "!\n"
        "end\n"
    )
    tree = parse_intent(cfg)
    ids = sorted(v.id for v in tree.vlans)
    assert ids == [10, 20]
    iface = next(
        i for i in tree.interfaces if i.name == "GigabitEthernet0/0/0"
    )
    assert iface.trunk_allowed_vlans == [10, 20, 30]
    # Surviving VLANs still gained the iface's tagged_ports projection
    # — the guard prunes phantoms but doesn't strip membership info
    # from legitimate records.
    by_id = {v.id: v for v in tree.vlans}
    assert "GigabitEthernet0/0/0" in by_id[10].tagged_ports
    assert "GigabitEthernet0/0/0" in by_id[20].tagged_ports


def test_cisco_trunk_allowed_round_trip_stable() -> None:
    """Full round-trip: build canonical with explicit VLANs +
    trunk-allowed list → render → reparse → identical VLAN-id set
    and per-port ``trunk_allowed_vlans``."""
    cfg = (
        "hostname r1\n"
        "!\n"
        "vlan 10\n"
        " name V10\n"
        "!\n"
        "vlan 20\n"
        " name V20\n"
        "!\n"
        "interface GigabitEthernet0/0/0\n"
        " switchport mode trunk\n"
        " switchport trunk allowed vlan 10,20\n"
        " no shutdown\n"
        "!\n"
    )
    codec = CiscoIOSXECLICodec()
    first = codec.parse(cfg)
    rendered = codec.render(first)
    second = codec.parse(rendered)
    assert sorted(v.id for v in first.vlans) == sorted(
        v.id for v in second.vlans
    )
    iface_first = next(
        i for i in first.interfaces if i.name == "GigabitEthernet0/0/0"
    )
    iface_second = next(
        i for i in second.interfaces if i.name == "GigabitEthernet0/0/0"
    )
    assert (
        iface_first.trunk_allowed_vlans
        == iface_second.trunk_allowed_vlans
        == [10, 20]
    )


def test_cisco_explicit_vlan_definitions_unchanged() -> None:
    """Regression guard: a config with only an explicit ``vlan 10 /
    name FOO`` stanza and NO trunk-allowed reference must still
    produce a single-VLAN ``tree.vlans`` (the explicit one).  The
    phantom-VLAN guard must not over-prune the non-trunk path."""
    cfg = (
        "hostname r1\n"
        "!\n"
        "vlan 10\n"
        " name FOO\n"
        "!\n"
        "end\n"
    )
    tree = parse_intent(cfg)
    assert len(tree.vlans) == 1
    assert tree.vlans[0].id == 10
    assert tree.vlans[0].name == "FOO"


def test_cisco_partial_wide_range_does_not_inflate() -> None:
    """Worst-case scenario from the arista_eos Phase 4b finding:
    a partial wide range like ``100-3000`` evaded the shared
    transform's exact-1-4094 sentinel and produced 2901 phantom
    VLANs.  Must now collapse to the explicit set."""
    cfg = (
        "hostname r1\n"
        "!\n"
        "vlan 10\n"
        " name FOO\n"
        "!\n"
        "interface GigabitEthernet0/0/0\n"
        " switchport mode trunk\n"
        " switchport trunk allowed vlan 100-3000\n"
        " no shutdown\n"
        "!\n"
        "end\n"
    )
    tree = parse_intent(cfg)
    assert len(tree.vlans) == 1
    assert tree.vlans[0].id == 10
