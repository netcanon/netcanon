"""The OS10 probe is limited by the detection WINDOW, not by its marker
set — and this pins the difference.

``detect_codec()`` hands each codec only ``DEFAULT_PROBE_BYTES`` leading
bytes.  OS10 captures in the wild routinely spend a small budget before
emitting a single OS10-exclusive token:

* **comment/template preambles** — jinja2-rendered configs open with
  ``! system.j2 - hostname`` / ``! Name:`` / ``! Make:`` header blocks
* **console captures** — a switch scraped over the serial console
  carries ``OS10 login:`` + the Debian boot banner first
* **QoS-leading configs** — the DellGEOS S5212F captures open with
  ~500 bytes of ``class-map type queuing`` / ``trust dot1p-map``

The markers themselves are fine; they are simply out of range.  These
tests prove exactly that by probing the SAME text twice — once
truncated, once whole.

⚠️ **UPDATED 2026-09-23 (#483): the window was widened, 500 -> 65536.**
This module's original header said the 500-byte limit was "a KNOWN,
DOCUMENTED limitation, not an unnoticed bug", pinned "rather than
'fixed' with a weak structural guess, because a loose OS10 heuristic
would start stealing other Cisco-shaped vendors' configs".  That
reasoning was about the MARKER SET and it still stands — no marker was
loosened.  What changed is the budget those markers are given, which
was measured rather than guessed: over the 90 committed fixtures the
window took detection from 73 correct / 0 wrong / 17 silent to a
perfect **90 / 0 / 0**, and over the 40-capture Dell corpus from
19/10/11 to 29/4/7.

The assertions below therefore now pass ``probe_bytes`` / a slice
EXPLICITLY rather than reading the default, because what they test is
the window MECHANISM — that a marker out of range is not seen — which
is true at any width and is the thing worth pinning.  See the sweep
table in ``netcanon/services/migration_detect.py``, including the
warning that widening is **not monotonic**.

See also:
- netcanon/services/migration_detect.py — DEFAULT_PROBE_BYTES + the sweep
- netcanon/migration/codecs/dell_os10/codec.py — the marker ladder
- tests/unit/migration/test_real_captures.py — the corpus-wide guard
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.dell_os10 import DellOS10Codec
from netcanon.services.migration_detect import DEFAULT_PROBE_BYTES

pytestmark = pytest.mark.unit


# A serial-console capture: the login prompt and OS banner burn the whole
# probe window before any config line appears.  Synthetic text in the
# SHAPE of a console scrape (login prompt, kernel banner, MOTD, then the
# command) — deliberately not copied from any captured session.
_CONSOLE_BANNER_LEAD = (
    "\nOS10 login: netops\nPassword:\n"
    "Last login: Mon Jan  1 00:00:00 UTC 2024 on ttyS0\n"
    "Linux example-switch 0.0.0 #1 SMP x86_64\n"
    + "-- banner filler line to exhaust the probe window --\n" * 12
    + "OS10# show running-configuration\n"
    "! Version 10.5.4.4\n"
    "!\n"
    "interface breakout 1/1/1 map 100g-1x\n"
    "!\n"
    "interface ethernet1/1/1\n"
)

# A jinja2-rendered config: the template's own provenance header sits
# where the version banner would normally be.
_TEMPLATE_COMMENT_LEAD = (
    "! system.j2 - hostname\n! Name: tor-1a\n! Make: dellemc\n"
    "! Model: s5248f-on\n"
    + "! template provenance comment line\n" * 14
    + "ip vrf default\n"
    "!\n"
    "interface ethernet1/1/1\n"
)

# The DellGEOS S5212F shape: bare `!`, hostname, then pure QoS.
_QOS_LEAD = (
    "!\nhostname OS10-S5212F-TOR1\n!\ndcbx enable\n!\n"
    + "".join(
        f"class-map type queuing Q{n}\n match queue {n}\n!\n" for n in range(9)
    )
)

# An ordinary `show running-configuration` — the control case.
_PLAIN_OS10 = (
    "! Version 10.5.1.4\n"
    "! Last configuration change at Jul  20 22:15:13 2021\n"
    "!\n"
    "ip vrf default\n"
    "!\n"
    "interface breakout 1/1/1 map 25g-4x\n"
    "!\n"
    "hostname leaf-1\n"
)


#: The width these boundary samples were authored against.  Kept as a
#: module constant, NOT read from DEFAULT_PROBE_BYTES, so that widening
#: the production window never silently turns these into no-ops: at 64 KiB
#: every sample below is shorter than the window and the truncation half
#: of each assertion would stop testing anything.
_AUTHORED_WINDOW = 500


def test_the_production_window_is_at_least_the_authored_one() -> None:
    """A narrowing would be a silent regression for every capture this
    module describes, so catch it here."""
    assert DEFAULT_PROBE_BYTES >= _AUTHORED_WINDOW


@pytest.mark.parametrize(
    "sample,label",
    [
        (_CONSOLE_BANNER_LEAD, "console login banner"),
        (_TEMPLATE_COMMENT_LEAD, "jinja2 provenance header"),
    ],
)
def test_marker_outside_the_window_is_not_seen(sample: str, label: str) -> None:
    """The WHOLE file is recognisable; the truncated prefix is not.

    This is the crux: both halves of the assertion run against identical
    text, so a failure here can only mean the window changed — never
    that the marker set regressed.
    """
    truncated = sample[:_AUTHORED_WINDOW]
    assert DellOS10Codec.probe(truncated) is None, (
        f"{label}: expected no candidate inside the {_AUTHORED_WINDOW}-byte window"
    )

    whole = DellOS10Codec.probe(sample)
    assert whole is not None, (
        f"{label}: the full text carries an OS10 marker and must be claimed"
    )
    assert whole[0] >= 95


def test_qos_leading_config_returns_no_candidate() -> None:
    """The DellGEOS case named in the ``probe()`` docstring.

    Unlike the two above, the marker is far enough in that a modest
    window widening would not reach it.

    ⚠️ Corrected 2026-09-23 (#482): this docstring used to say the real
    captures were "genuinely markerless, so widening the window alone
    would not rescue them".  That is false.  Measured on the real
    `dellgeos_S5212F-TOR1-Advanced.cfg` (2802 bytes): `interface
    mgmt1/1/1` at byte **849** and `vlt-domain 1` at byte **1270** —
    both OS10 markers, both merely outside the 500-byte window.  The
    sample below (`_QOS_LEAD`) is a truncated excerpt and IS markerless,
    which is what this test actually pins; the claim about the captures
    was an over-generalisation from it.  Widening the window is a live
    option, not a foreclosed one.
    """
    assert DellOS10Codec.probe(_QOS_LEAD) is None


def test_ordinary_running_config_still_detects_outright() -> None:
    """Regression guard: none of the above is achieved by weakening the
    probe.  A normal OS10 capture is still claimed at high confidence."""
    result = DellOS10Codec.probe(_PLAIN_OS10)
    assert result is not None
    assert result[0] >= 95
