"""Defect D5 — Dell Force10 OS9 / FTOS must not be claimed by Cisco IOS-XE.

This is #475 (`b22d279`) one Dell NOS generation earlier, and it arrives by a
different marker.  OS10 was claimed via `! Last configuration change at`; OS9
has no such line, but it emits `service timestamps` — another weight-2 entry in
`_IOS_BANNER_HITS`, and since the `>= 2` threshold returns 95, that ONE line is
enough.

Measured over the 41-entry dev corpus before the fix: four real Dell S4810
captures were each claimed by `cisco_iosxe_cli` at confidence **95**, reason
"IOS-specific banner sequence detected", and mis-parsed into 90 interfaces
collapsed onto 5 distinct names (Force10 writes `interface TenGigabitEthernet
0/1` with a SPACE, so the Cisco regex captures the type and drops the number),
0 VLANs and 0 IPv4 addresses.

There is no `dell_os9` codec, so the correct outcome is **no candidate** rather
than a confident wrong one.

⚠️ Why these fixtures are inline rather than committed
------------------------------------------------------
There is no `tests/fixtures/real/dell_os10/` directory at all, and the OS9
captures live only in the gitignored, dev-only corpus at `local/dell-os10/`,
which must never be committed (it carries real credential hashes).  So the
committed corpus can never regression-guard this fix, and the samples below are
synthetic — structurally faithful to a Force10 OS9 header, with no real values.

⚠️ Marker scope
---------------
The veto matches two markers, both from the Force10 `stack-unit` family.  They
are the only candidates that fall inside the 500-byte probe window on all four
real captures (offsets 86-89 and 376-379).  A `! Version 9.x(y)` banner clause
was evaluated and REJECTED: it adds zero recall and is the one shape that can
collide, since NX-OS writes `version 9.2(3)` / `version 9.3(12)` and differs
only by the leading `!`.  `test_nxos_version_banner_is_not_vetoed` pins that.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec
from netcanon.services.migration_detect import detect_codec

pytestmark = pytest.mark.unit


# A Force10 OS9 header in the shape the real captures use: version banner,
# boot statement, then `service timestamps` — the line that used to win.
# Offsets here mirror the real captures closely enough that every marker
# lands inside the 500-byte production probe window.
_OS9_HEADER = """! Version 9.9(0.0)
! Startup-config last updated at Fri Jan  1 00:00:00 2016 by admin
!
boot system stack-unit 1 primary system://A
boot system stack-unit 1 secondary system://B
boot system stack-unit 1 default system://A
!
hardware watchdog
!
service timestamps log datetime
service timestamps debug datetime
!
logging coredump stack-unit 1
!
hostname EXAMPLE-TOR
!
"""

# The same file WITHOUT the stack-unit family, to prove the markers are what
# does the work (and not, say, the version banner).
_OS9_WITHOUT_MARKERS = _OS9_HEADER.replace(
    "boot system stack-unit 1 primary system://A\n", ""
).replace(
    "boot system stack-unit 1 secondary system://B\n", ""
).replace(
    "boot system stack-unit 1 default system://A\n", ""
).replace(
    "logging coredump stack-unit 1\n", ""
)


def test_os9_header_alone_used_to_score_95() -> None:
    """Pin the pre-fix mechanism so the test cannot pass vacuously.

    Strip the two markers and the probe still returns 95 off
    `service timestamps` — which is exactly the defect.  If this ever
    stops being true, the veto below is guarding nothing and the real
    cause has moved.

    Note the header says `! Startup-config last updated at`, which is
    Force10's wording.  Cisco's is `! Last configuration change at`, and
    that difference is load-bearing: OS9 matches exactly ONE banner entry
    (`service timestamps`) for a total weight of 2, which is why it lands
    on 95 rather than 98.
    """
    result = CiscoIOSXECLICodec.probe(_OS9_WITHOUT_MARKERS[:500])
    assert result is not None, (
        "the pre-fix scoring path is gone — re-derive why OS9 scored 95 "
        "before trusting the veto below"
    )
    assert result[0] == 95


def test_os9_is_declined_by_the_iosxe_probe() -> None:
    assert CiscoIOSXECLICodec.probe(_OS9_HEADER[:500]) is None


def test_os9_gets_no_detection_candidate_at_all() -> None:
    """End to end, at production defaults.

    No `dell_os9` codec exists, so silence is the honest answer.  What
    must NOT happen is a confident wrong one.
    """
    candidates = detect_codec(_OS9_HEADER)
    assert not candidates, (
        f"Dell OS9 was claimed by {[(c.codec, c.confidence) for c in candidates]}"
    )


@pytest.mark.parametrize(
    "marker",
    [
        "boot system stack-unit 1 primary system://A",
        "logging coredump stack-unit 1",
    ],
)
def test_each_marker_independently_triggers_the_deferral(marker: str) -> None:
    """Either marker alone suffices — a capture starting mid-file still
    defers."""
    sample = f"{marker}\nservice timestamps log datetime\nhostname X\n!\n"
    assert CiscoIOSXECLICodec.probe(sample[:500]) is None


def test_nxos_version_banner_is_not_vetoed() -> None:
    """The rejected banner clause, pinned as a negative.

    NX-OS `version 9.2(3)` differs from Force10's `! Version 9.9(0.0)`
    only by the leading `!`.  Had the veto matched on the version major,
    a commented-out or collector-prefixed NX-OS banner would silence a
    correct NX-OS detection.  This asserts we did not take that risk.
    """
    nxos = (
        "!Command: show running-config\n"
        "version 9.3(12) Bios:version 07.69\n"
        "hostname leaf1\n"
        "!\n"
        "feature bgp\n"
    )
    candidates = detect_codec(nxos)
    assert candidates, "NX-OS lost its detection candidate"
    assert candidates[0].codec == "cisco_nxos", (
        f"NX-OS now detects as {candidates[0].codec}"
    )


def test_genuine_iosxe_still_detects() -> None:
    """The veto must not cost real IOS-XE detection.

    Measured across the 90 committed fixtures: 0 verdicts changed.  This
    is the inline canary for the same property.
    """
    iosxe = (
        "Building configuration...\n"
        "\n"
        "Current configuration : 4231 bytes\n"
        "!\n"
        "! Last configuration change at 10:00:00 UTC Mon Jan 1 2024\n"
        "!\n"
        "version 17.3\n"
        "service timestamps debug datetime msec\n"
        "hostname router1\n"
        "!\n"
    )
    candidates = detect_codec(iosxe)
    assert candidates, "genuine IOS-XE lost its detection candidate"
    assert candidates[0].codec == "cisco_iosxe_cli"
    assert candidates[0].confidence >= 95
