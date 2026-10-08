"""Defect D2 — two physically distinct source ports fusing into one
target port must not happen silently.

Aruba AOS-S distinguishes an uplink-MODULE port (``1/A1``, the letter is
the module slot) from an access port (``1/1``).  ``classify_port_name``
gets this right and records ``subslot_letter="A"``.  No target's
``format_port_identity`` consumes that field, so both names render to a
single target name — ``ge-1/0/1`` on Junos, ``Ethernet1/0/1`` on NX-OS,
``port1`` on FortiGate — on 9 of the 11 public targets.  Two ports
become one and their VLAN memberships merge.

The collision detector already existed.  It could not see this, because
it walked ``intent.interfaces`` and ``intent.lags``, and the AOS-S
captures that exercise the bug carry **zero** ``interface`` stanzas —
every port is named only inside ``vlans[].tagged_ports`` /
``untagged_ports``.  Both lists were empty, so the fusion went out with
``warnings == []``.

That is the same scoping mistake in two places: ``translate_port_names``
rewrites the ``present_names`` set, which is strictly larger than
``interfaces[].name``.  Detection now reads ``memo`` — every source →
final pair actually applied — so it sees a rename wherever the name
lived.

We warn rather than repair: no target models a letter slot, and
synthesising an offset port number would fabricate topology the operator
never wrote.  An explicit ``port_rename_map`` entry overrides, which is
the documented escape hatch and is pinned below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical.port_names import translate_port_names
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit


_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "real"
    / "aruba_aoss"
    / "user_contrib_2930m_wc1611.cfg"
)

#: Targets whose port grammar collapses the Aruba letter slot.
_FUSING_TARGETS = (
    "aruba_aoscx",
    "cisco_iosxr",
    "cisco_nxos",
    "dell_os10",
    "fortigate_cli",
    "juniper_junos",
    "mikrotik_routeros",
    "opnsense",
    "vyos",
)


def _raw() -> str:
    return _FIXTURE.read_text(encoding="utf-8", errors="replace")


def _fusion_warnings(result) -> list[str]:
    return [w for w in result.warnings if "multiple source ports" in w]


def test_the_fixture_has_no_interface_stanzas() -> None:
    """Guard the guard.

    The whole point is that the old detector saw empty lists.  If this
    capture ever grows ``interface`` stanzas, the assertions below stop
    exercising the bug and start passing for the wrong reason.
    """
    intent = get_codec("aruba_aoss").parse(_raw())
    assert not intent.interfaces, (
        "fixture now has interface stanzas — the old interfaces-walking "
        "detector would catch the fusion, so this module no longer pins "
        "the reported defect"
    )
    named_in_vlans: set[str] = set()
    for vlan in intent.vlans:
        named_in_vlans.update(vlan.tagged_ports)
        named_in_vlans.update(vlan.untagged_ports)
    assert {"1/1", "1/A1"} <= named_in_vlans, (
        "fixture no longer names both an access port and its "
        "letter-slot twin"
    )


@pytest.mark.parametrize("target_name", _FUSING_TARGETS)
def test_fusion_is_reported(target_name: str) -> None:
    source = get_codec("aruba_aoss")
    intent = source.parse(_raw())

    result = translate_port_names(
        intent, source, get_codec(target_name), rename_map={},
    )

    warnings = _fusion_warnings(result)
    assert warnings, (
        f"{target_name}: distinct source ports fused into one target "
        f"port with no warning"
    )
    assert any("1/A1" in w for w in warnings), (
        f"{target_name}: the warning does not name the uplink-module "
        f"port that was fused"
    )


def test_no_warning_when_the_target_keeps_them_distinct() -> None:
    """cisco_iosxe_cli's grammar does not collapse the letter slot.

    A detector that fired everywhere would be noise, not signal.
    """
    source = get_codec("aruba_aoss")
    intent = source.parse(_raw())

    result = translate_port_names(
        intent, source, get_codec("cisco_iosxe_cli"), rename_map={},
    )

    assert not _fusion_warnings(result)


def test_an_explicit_map_entry_resolves_the_fusion() -> None:
    """The documented escape hatch must actually work.

    An operator who maps the colliding ports apart should stop being
    warned about them -- otherwise the warning is unactionable.
    """
    source = get_codec("aruba_aoss")
    target = get_codec("juniper_junos")
    intent = source.parse(_raw())

    result = translate_port_names(
        intent,
        source,
        target,
        rename_map={
            "1/A1": "xe-1/1/1",
            "1/A2": "xe-1/1/2",
            "1/A3": "xe-1/1/3",
            "1/A4": "xe-1/1/4",
        },
    )

    assert not _fusion_warnings(result), (
        "an explicit distinct mapping did not clear the collision"
    )


# ---------------------------------------------------------------------------
# The masked shape (found 2026-10-07).
#
# Everything above runs against a capture with ZERO interface stanzas -- and
# `test_the_fixture_has_no_interface_stanzas` insists on it.  That is the one
# shape the following defect did NOT hide behind: the membership sweep skipped
# any final name present in `intent.interfaces`, whether or not anything had
# warned about it.  So a single `interface 1/1` record suppressed the report
# for a `1/A1` that lived only in a VLAN's port list.  Measured on the
# committed corpus, 12 real fusions went out with no warning at all.
# ---------------------------------------------------------------------------


def _tree_with_one_stanza_and_a_vlan_only_twin():
    from netcanon.migration.canonical.intent import (
        CanonicalIntent,
        CanonicalInterface,
        CanonicalVlan,
    )

    return CanonicalIntent(
        source_vendor="aruba_aoss",
        interfaces=[CanonicalInterface(name="1/1")],
        vlans=[CanonicalVlan(id=10, untagged_ports=["1/1", "1/A1"])],
    )


def test_an_interface_stanza_does_not_mask_a_vlan_only_fusion() -> None:
    intent = _tree_with_one_stanza_and_a_vlan_only_twin()
    result = translate_port_names(
        intent, get_codec("aruba_aoss"), get_codec("juniper_junos"),
        rename_map={},
    )
    # The fusion itself is unchanged -- we warn, we do not invent topology.
    assert intent.vlans[0].untagged_ports == ["ge-1/0/1", "ge-1/0/1"]
    warnings = _fusion_warnings(result)
    assert warnings, "two distinct ports fused with no warning"
    assert "1/A1" in warnings[0] and "1/1" in warnings[0]


def test_a_fusion_is_reported_once_not_twice() -> None:
    """The fix must not turn one collision into two warnings: when the
    interface sweep already reported a name, the membership sweep stays
    quiet about it."""
    from netcanon.migration.canonical.intent import (
        CanonicalIntent,
        CanonicalInterface,
    )

    intent = CanonicalIntent(
        source_vendor="aruba_aoss",
        interfaces=[
            CanonicalInterface(name="1/1"),
            CanonicalInterface(name="1/A1"),
        ],
    )
    result = translate_port_names(
        intent, get_codec("aruba_aoss"), get_codec("juniper_junos"),
        rename_map={},
    )
    assert len(_fusion_warnings(result)) == 1


def test_a_port_that_keeps_its_name_still_counts_as_a_source() -> None:
    """Identity pairs used to be excluded, so a port renamed ONTO a name
    another port already held looked like a single source."""
    from netcanon.migration.canonical.intent import (
        CanonicalIntent,
        CanonicalVlan,
    )

    intent = CanonicalIntent(
        source_vendor="aruba_aoss",
        vlans=[CanonicalVlan(id=10, untagged_ports=["1/1", "1/2"])],
    )
    result = translate_port_names(
        intent, get_codec("aruba_aoss"), get_codec("aruba_aoss"),
        rename_map={"1/2": "1/1"},
    )
    assert _fusion_warnings(result), (
        "1/2 was mapped onto 1/1, which 1/1 still holds, with no warning"
    )
