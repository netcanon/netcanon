"""Unit tests for OPNsense VLAN ``<if>`` parent-binding emission.

Real OPNsense ``<vlan>`` elements REQUIRE a ``<if>`` child naming the
parent physical / lagg interface; without it the VLAN cannot bind at
the kernel level and the OPNsense UI also refuses to save.  See real
fixtures under ``tests/fixtures/real/opnsense/`` (every ``<vlan>``
carries ``<if>`` + ``<tag>`` + ``<pcp>`` + ``<proto/>`` + ``<descr>``
+ ``<vlanif>``) and the OPNsense docs at
https://docs.opnsense.org/manual/other-interfaces.html.

Render previously emitted ``<vlan><tag>11</tag></vlan>`` with no
parent — operators saw VLANs that would fail to bind on a real device
(see ``tests/fixtures/real/user_smoke_findings.md`` issue #5).

Lookup strategy (codec-side, deterministic):

1. A LAG whose ``trunk_allowed_vlans`` (declared on its members or
   on the LAG-named interface) contains ``vlan.id``.
2. A non-LAG, non-VLAN interface carrying this VLAN.
3. Fallback: first LAG, then first physical, then literal ``"lan"``.

See also:
- ``netconfig/migration/codecs/opnsense/render.py`` —
  ``_vlan_parent_for`` + ``_vlan_parent_default``
- ``tests/fixtures/real/opnsense/user_contrib_supergate_opn25.xml``
  — reference real-OPNsense VLAN XML shape
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalVlan,
)
from netconfig.migration.codecs.opnsense.render import render_intent

pytestmark = pytest.mark.unit


def test_vlan_emits_with_if_parent_binding() -> None:
    """A VLAN whose trunk parent is a LAG must emit
    ``<if>laggN</if>`` inside its ``<vlan>`` element."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="lagg1",
                switchport_mode="trunk",
                trunk_allowed_vlans=[11, 100],
            ),
        ],
        lags=[CanonicalLAG(name="lagg1", members=["ix0", "ix1"])],
        vlans=[CanonicalVlan(id=11, name="MGMT")],
    )
    out = render_intent(intent)
    # The <vlan> element must carry the <if> child naming the parent
    # LAG, plus the <tag> sibling.  Real OPNsense reads both.
    assert "<if>lagg1</if>" in out
    assert "<tag>11</tag>" in out
    # Required schema children present on every vlan.
    assert "<pcp>0</pcp>" in out
    assert "<proto/>" in out
    assert "<descr>MGMT</descr>" in out
    assert "<vlanif>lagg1_vlan11</vlanif>" in out


def test_vlan_with_no_svi_falls_back_to_first_lagg() -> None:
    """A VLAN with no explicit trunk-list match must fall back to the
    first declared LAG so the resulting XML is still bindable."""
    intent = CanonicalIntent(
        # Two LAGs; neither carries the VLAN on a trunk list — pick lagg0
        # (the first one) deterministically.
        lags=[
            CanonicalLAG(name="lagg0", members=["em0", "em1"]),
            CanonicalLAG(name="lagg1", members=["em2", "em3"]),
        ],
        vlans=[CanonicalVlan(id=42, name="UNBOUND")],
    )
    out = render_intent(intent)
    # First lagg is picked — not lagg1.
    assert "<vlan>" in out
    assert "<tag>42</tag>" in out
    assert "<vlanif>lagg0_vlan42</vlanif>" in out
    # The vlan's <if> must be lagg0; lagg1 only appears in <laggs>.
    # Find the <vlan> block and assert lagg0 is its <if>.
    vlan_start = out.find("<vlan>")
    vlan_end = out.find("</vlan>", vlan_start)
    vlan_block = out[vlan_start:vlan_end]
    assert "<if>lagg0</if>" in vlan_block
    assert "<if>lagg1</if>" not in vlan_block


def test_vlan_with_no_svi_no_lagg_falls_back_to_first_physical() -> None:
    """No LAGs declared — fall back to the first physical-looking
    interface in the canonical interface list."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(name="em0", enabled=True),
            CanonicalInterface(name="em1", enabled=True),
        ],
        vlans=[CanonicalVlan(id=42, name="UNBOUND")],
    )
    out = render_intent(intent)
    # Find the <vlan> block; its <if> must be em0 (first physical).
    vlan_start = out.find("<vlan>")
    vlan_end = out.find("</vlan>", vlan_start)
    vlan_block = out[vlan_start:vlan_end]
    assert "<if>em0</if>" in vlan_block
    assert "<tag>42</tag>" in vlan_block
    assert "<vlanif>em0_vlan42</vlanif>" in vlan_block
