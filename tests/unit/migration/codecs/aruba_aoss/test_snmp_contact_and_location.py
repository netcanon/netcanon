"""One ``snmp-server`` line may set the contact and the location.

HPE prints ``snmp-server contact "IT" location "1OG"`` (a committed
WB.16.08 capture does), and the parser read the rest of the line after
``contact`` as the contact: ``IT" location "1OG``, a value with two
quotes in it, written onto every target, and no location.  A quoted
value ends at its closing quote; a bare one is still the rest of the
line.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import get_codec

_CAPTURE = (
    Path(__file__).resolve().parents[4]
    / "fixtures" / "real" / "aruba_aoss" / "hpe_community_2920_wb1608_dhcp_snooping.cfg"
)


def _snmp(line: str) -> tuple[str, str]:
    snmp = get_codec("aruba_aoss").parse(f'hostname "h"\n{line}\n').snmp
    assert snmp is not None
    return snmp.contact, snmp.location


@pytest.mark.parametrize(
    ("line", "contact", "location"),
    [
        ('snmp-server contact "IT" location "1OG"', "IT", "1OG"),
        ('snmp-server location "Bldg 3" contact "NOC"', "NOC", "Bldg 3"),
        ('snmp-server location "Bldg 3"', "", "Bldg 3"),
        ('snmp-server contact "netadmin@example.test"', "netadmin@example.test", ""),
        ("snmp-server contact IT Dept", "IT Dept", ""),
        ('snmp-server contact "a\\"b"', 'a"b', ""),
        ('snmp-server contact "no end', "no end", ""),
    ],
)
def test_each_value_is_its_own(line: str, contact: str, location: str) -> None:
    assert _snmp(line) == (contact, location)


def test_the_capture_that_prints_both() -> None:
    text = _CAPTURE.read_text(encoding="utf-8")
    assert 'snmp-server contact "IT" location "1OG"' in text
    snmp = get_codec("aruba_aoss").parse(text).snmp
    assert snmp is not None
    assert (snmp.contact, snmp.location) == ("IT", "1OG")
