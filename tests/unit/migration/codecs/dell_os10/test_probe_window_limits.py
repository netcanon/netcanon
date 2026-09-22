"""The OS10 probe is limited by the 500-byte detection WINDOW, not by
its marker set — and this pins the difference.

``detect_codec()`` hands each codec only
``DEFAULT_PROBE_BYTES = 500`` leading bytes
(``netcanon/services/migration_detect.py:31``).  OS10 captures in the
wild routinely spend that entire budget before emitting a single
OS10-exclusive token:

* **comment//template preambles** — jinja2-rendered configs open with
  ``! system.j2 - hostname`` / ``! Name:`` / ``! Make:`` header blocks
* **console captures** — a switch scraped over the serial console
  carries ``OS10 login:`` + the Debian boot banner first
* **QoS-leading configs** — the DellGEOS S5212F captures open with
  ~500 bytes of ``class-map type queuing`` / ``trust dot1p-map``

The markers themselves are fine; they are simply out of range.  These
tests prove exactly that by probing the SAME text twice — once
truncated to the production window (no candidate) and once whole
(claimed at high confidence).  If someone later widens the window or
adds an early structural marker, the first assertion flips and this
module is the place that explains why that is a deliberate change.

⚠️ This is a KNOWN, DOCUMENTED limitation, not an unnoticed bug — see
``dell_os10/codec.py::probe`` docstring and
``docs/vendor-research/dell_os10/30-codec-plan.md`` §9 item 1.  It is
pinned here rather than "fixed" with a weak structural guess, because a
loose OS10 heuristic would start stealing other Cisco-shaped vendors'
configs — the failure mode PR #475 closed.

See also:
- netcanon/services/migration_detect.py — DEFAULT_PROBE_BYTES = 500
- netcanon/migration/codecs/dell_os10/codec.py — the marker ladder
- tests/unit/migration/test_detect.py — the cross-codec deferral suite
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


def test_probe_window_is_still_500_bytes() -> None:
    """Pin the constant these tests reason about.  If it moves, the
    window-boundary assertions below stop meaning what they claim."""
    assert DEFAULT_PROBE_BYTES == 500


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
    truncated = sample[:DEFAULT_PROBE_BYTES]
    assert DellOS10Codec.probe(truncated) is None, (
        f"{label}: expected no candidate inside the 500-byte window"
    )

    whole = DellOS10Codec.probe(sample)
    assert whole is not None, (
        f"{label}: the full text carries an OS10 marker and must be claimed"
    )
    assert whole[0] >= 95


def test_qos_leading_config_returns_no_candidate() -> None:
    """The DellGEOS case named in the ``probe()`` docstring.

    Unlike the two above there is no marker later in the file either —
    these captures are genuinely markerless, so widening the window
    alone would not rescue them.
    """
    assert DellOS10Codec.probe(_QOS_LEAD) is None


def test_ordinary_running_config_still_detects_outright() -> None:
    """Regression guard: none of the above is achieved by weakening the
    probe.  A normal OS10 capture is still claimed at high confidence."""
    result = DellOS10Codec.probe(_PLAIN_OS10)
    assert result is not None
    assert result[0] >= 95
