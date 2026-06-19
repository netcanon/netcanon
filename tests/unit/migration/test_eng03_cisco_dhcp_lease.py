"""ENG-03 regression: cisco_iosxe_cli DHCP lease-time round-trips losslessly.

The old render emitted ``lease 0 <total_hours>`` — it truncated days
into hours and dropped minutes entirely (e.g. ``lease 2 6 30`` = 196200s
rendered as ``lease 0 54`` = 194400s, losing 30 min and collapsing the
day field), and never emitted the ``lease infinite`` marker.  The parser
already read the full ``lease <days> <hours> <minutes>`` + ``infinite``
grammar, so the render was the lossy side.  Render now emits the matching
day/hour/minute triple (audit finding ENG-03).
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit

_BASE = """hostname r1
!
ip dhcp pool LAN
 network 10.0.0.0 255.255.255.0
 default-router 10.0.0.1
 {lease}
!
"""


def _roundtrip(lease_line: str):
    codec = CiscoIOSXECLICodec()
    intent = codec.parse(_BASE.format(lease=lease_line))
    rendered = codec.render(intent)
    reparsed = codec.parse(rendered)
    return intent, rendered, reparsed


def test_multi_day_lease_with_minutes_roundtrips_without_truncation():
    # 2 days 6 hours 30 minutes = 196200s.  The old render collapsed this
    # to `lease 0 54` (194400s), silently losing 30 minutes.
    intent, rendered, reparsed = _roundtrip("lease 2 6 30")
    assert intent.dhcp_servers[0].lease_time == 196200
    assert " lease 2 6 30" in rendered
    assert "lease 0 " not in rendered  # the old truncated form is gone
    assert reparsed.dhcp_servers[0].lease_time == 196200


def test_sub_hour_lease_preserves_minutes():
    # 30 minutes = 1800s.  The old render emitted `lease 0 0`, dropping it.
    intent, rendered, reparsed = _roundtrip("lease 0 0 30")
    assert intent.dhcp_servers[0].lease_time == 1800
    assert " lease 0 0 30" in rendered
    assert reparsed.dhcp_servers[0].lease_time == 1800


def test_infinite_lease_roundtrips():
    intent, rendered, reparsed = _roundtrip("lease infinite")
    assert intent.dhcp_servers[0].lease_time == 0xFFFFFFFF
    assert " lease infinite" in rendered
    assert reparsed.dhcp_servers[0].lease_time == 0xFFFFFFFF


def test_whole_hour_multi_day_lease_roundtrips():
    # 7 days exactly = 604800s.  Even the old render happened to be
    # value-lossless here (`lease 0 168`), but it lost the human-readable
    # day field; the triple now preserves the operator's `lease 7 0 0`.
    intent, rendered, reparsed = _roundtrip("lease 7 0 0")
    assert intent.dhcp_servers[0].lease_time == 604800
    assert " lease 7 0 0" in rendered
    assert reparsed.dhcp_servers[0].lease_time == 604800
