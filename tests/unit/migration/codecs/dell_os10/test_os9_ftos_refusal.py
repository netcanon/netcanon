"""Dell's OLDER Force10 OS9 / FTOS grammar must be refused outright by
the OS10 codec — never parsed into a plausible-looking wrong answer.

OS9 and OS10 are both Dell and both Cisco-shaped (``!`` delimiters,
indented sub-commands), which makes a fail-open here very easy and very
expensive: the result is a config that parses "successfully" into
nonsense rather than an honest no-candidate.

The three discriminators, all of which OS10 never emits:

===================================== ==========================
OS9 / FTOS                            OS10
===================================== ==========================
``interface TenGigabitEthernet 0/1``  ``interface ethernet1/1/1``
``interface ManagementEthernet 0/0``  ``interface mgmt1/1/1``
``! Version 9.9(0.0)``                ``! Version 10.5.1.4``
===================================== ==========================

Samples below follow the shape of real Dell S4810 captures (OS9
9.9(0.0)) used as negative controls during codec development.

⚠️ Scope note — this pins what the **OS10 codec** does.  It does NOT
assert that OS9 gets no candidate at all: ``cisco_iosxe_cli`` still
claims FTOS via ``service timestamps``, which FTOS genuinely emits, and
PR #475 left that deliberately unchanged.  Conflating the two would make
this test fail for a reason that has nothing to do with Dell OS10.

See also:
- netcanon/migration/codecs/dell_os10/codec.py — the OS9 rejection block
- docs/vendor-research/dell_os10/40-os9-appendix.md — the parked OS9 work
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.dell_os10 import DellOS10Codec

pytestmark = pytest.mark.unit


_OS9_TENGIG = (
    "! Version 9.9(0.0)\n"
    "! Startup-config last updated at Thu Mar 17 15:28:30 2016 by admin\n"
    "boot system stack-unit 0 primary system: A:\n"
    "!\n"
    "hostname S4810-TOR1\n"
    "!\n"
    "interface TenGigabitEthernet 0/1\n"
    " no ip address\n"
    " switchport\n"
    " no shutdown\n"
)

_OS9_MGMT = (
    "! Version 9.9(0.0)\n"
    "!\n"
    "interface ManagementEthernet 0/0\n"
    " ip address 10.0.0.9/24\n"
    " no shutdown\n"
)

_OS9_FORTYGIGE = (
    "! Version 9.9(0.0)\n"
    "!\n"
    "interface fortyGigE 0/48\n"
    " no shutdown\n"
)


@pytest.mark.parametrize(
    "sample,label",
    [
        (_OS9_TENGIG, "TenGigabitEthernet"),
        (_OS9_MGMT, "ManagementEthernet"),
        (_OS9_FORTYGIGE, "fortyGigE"),
    ],
)
def test_os9_port_grammar_is_refused(sample: str, label: str) -> None:
    """Each OS9-exclusive port keyword vetoes the OS10 claim."""
    assert DellOS10Codec.probe(sample) is None, (
        f"OS10 codec claimed an OS9 config via {label}"
    )


def test_os9_veto_beats_an_otherwise_scoring_marker() -> None:
    """The veto is checked BEFORE the marker ladder.

    This sample carries ``ip vrf default`` — a column-0 OS10 marker
    worth 95 — alongside OS9 port grammar.  Ordering matters: if the
    marker ladder ran first, the capture would be claimed at 95.  This
    is the non-vacuous case; without it the tests above could pass on a
    codec that simply had no marker to match.
    """
    mixed = (
        "! Version 9.9(0.0)\n"
        "!\n"
        "ip vrf default\n"
        "!\n"
        "interface TenGigabitEthernet 0/1\n"
        " no shutdown\n"
    )
    assert DellOS10Codec.probe(mixed) is None


def test_os10_three_segment_naming_still_claimed() -> None:
    """Regression guard: the veto keys on OS9 grammar only.

    The equivalent OS10 config — same vendor, same ``!`` shape — is
    still claimed outright.
    """
    os10 = (
        "! Version 10.5.1.4\n"
        "!\n"
        "ip vrf default\n"
        "!\n"
        "interface ethernet1/1/1\n"
        " no shutdown\n"
    )
    result = DellOS10Codec.probe(os10)
    assert result is not None
    assert result[0] >= 95
