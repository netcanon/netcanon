"""
Unit tests for the OPNsense codec interface-name round-trip contract.

Covers two cooperating defects that previously corrupted the canonical
interface identity on parse -> render -> parse cycles when the source
intent originated outside OPNsense (e.g. an Aruba switch carrying
bare-numeric port names):

1. Empty-zone drop
   ``opnsense/render.py`` previously emitted a self-closing zone
   element when the interface had no IP / descr / mtu / enable, and
   ``opnsense/parse.py`` then dropped it under the "no <if> AND zero
   children -> return None" rule.  Sparse OPNsense exports (or
   cross-vendor intents with disabled-only ifaces) lost entire zones.

2. Zone-tag mangling is non-invertible
   ``_zone_tag_for(iface.name)`` lower-cases and replaces non-
   alphanumeric chars with ``_``, prepending ``if_`` when the first
   char is a digit.  So ``Ethernet0`` becomes ``<ethernet0>``,
   ``1/A1`` becomes ``<if_1_a1>``, ``A1`` becomes ``<a1>``.  Original
   port-name identity is destroyed.

Fix: render emits ``<if>`` carrying the canonical name verbatim as
the FIRST child of every zone element; parser prefers ``<if>`` text
when present, falling back to the zone tag for legacy XML.

See also:
- ``tests/fixtures/real/phase4_findings_aruba_aoss.md`` O1 + O2
- ``tests/fixtures/real/phase4_findings_arista_eos.md`` OP-1
- ``netcanon/migration/codecs/opnsense/render.py`` per-iface emit
- ``netcanon/migration/codecs/opnsense/parse.py``
  ``_parse_interface_zone_canonical``
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
)
from netcanon.migration.codecs.opnsense.parse import parse_intent
from netcanon.migration.codecs.opnsense.render import render_intent

pytestmark = pytest.mark.unit


def test_zone_round_trip_preserves_name_and_count():
    """A heterogeneous canonical intent must survive the zone-tag
    sanitisation: every iface name comes back exactly as it went in,
    and the count is preserved."""
    intent = CanonicalIntent(
        source_vendor="test",
        source_format="test",
        interfaces=[
            CanonicalInterface(name="Ethernet0", enabled=True),
            CanonicalInterface(name="A1", enabled=True),
            CanonicalInterface(name="1/A1", enabled=True),
            CanonicalInterface(name="GigabitEthernet0/0/0", enabled=True),
            CanonicalInterface(name="port15", enabled=False),
        ],
    )
    out_xml = render_intent(intent)
    roundtrip = parse_intent(out_xml)
    names = sorted(i.name for i in roundtrip.interfaces)
    assert names == sorted(i.name for i in intent.interfaces)


def test_zone_round_trip_preserves_disabled_iface():
    """A disabled-only interface (no IP, no descr, no MTU) used to be
    dropped by the empty-zone rule.  It must now round-trip."""
    intent = CanonicalIntent(
        source_vendor="test",
        source_format="test",
        interfaces=[
            CanonicalInterface(name="port1", enabled=False),
        ],
    )
    out_xml = render_intent(intent)
    roundtrip = parse_intent(out_xml)
    assert len(roundtrip.interfaces) == 1
    assert roundtrip.interfaces[0].name == "port1"
    assert roundtrip.interfaces[0].enabled is False


def test_zone_collision_disambiguation():
    """Two distinct canonical names that sanitise to the same XML tag
    must each get a unique zone element so neither is dropped on
    re-parse.  ``A1`` and ``a1`` both collapse to ``a1`` under
    ``_zone_tag_for``; the second occurrence gets ``_2`` appended."""
    intent = CanonicalIntent(
        source_vendor="test",
        source_format="test",
        interfaces=[
            CanonicalInterface(name="A1", enabled=True),
            CanonicalInterface(name="a1", enabled=True),
        ],
    )
    out_xml = render_intent(intent)
    # Render should produce two distinct zone tags, not collide on one.
    assert out_xml.count("<if>A1</if>") == 1
    assert out_xml.count("<if>a1</if>") == 1
    roundtrip = parse_intent(out_xml)
    names = sorted(i.name for i in roundtrip.interfaces)
    assert names == ["A1", "a1"]


def test_render_emits_if_element_first_child():
    """The ``<if>`` child must be emitted on every zone element so
    parse can recover the canonical name (regardless of whether
    other fields are populated)."""
    intent = CanonicalIntent(
        source_vendor="test",
        source_format="test",
        interfaces=[
            CanonicalInterface(name="Ethernet0", enabled=True),
        ],
    )
    out_xml = render_intent(intent)
    assert "<if>Ethernet0</if>" in out_xml


def test_legacy_xml_without_if_falls_back_to_zone_tag():
    """Legacy fallback: XML that lacks ``<if>`` (sparse hand-written
    fixtures, older OPNsense exports) must still parse, using the
    zone tag as the canonical name."""
    raw = (
        '<?xml version="1.0"?>'
        "<opnsense><interfaces>"
        "<lan><enable/></lan>"
        "</interfaces></opnsense>"
    )
    intent = parse_intent(raw)
    assert len(intent.interfaces) == 1
    assert intent.interfaces[0].name == "lan"
    assert intent.interfaces[0].enabled is True
