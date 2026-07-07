"""Arista legacy ``vrf definition`` body harvest (2026-07-06 review MEDIUM #21).

Pre-4.23 EOS carries the RD / description / route-targets INSIDE the
``vrf definition <name>`` stanza (IOS-style).  The harvest read only the
header, so those dropped: an EOS->EOS re-render emitted ``vrf instance RED``
with no rd (silent same-vendor loss) and L3VPN targets lost the RD.  The fix
harvests the stanza body; the router-bgp pass still merges by name on top.

No committed arista fixture carries an inline-VRF-body, so this is mesh-flat.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.arista_eos import AristaEOSCodec

pytestmark = pytest.mark.unit


def _ri(intent, name):
    return next(r for r in intent.routing_instances if r.name == name)


class TestVrfDefinitionBodyHarvest:
    def test_legacy_vrf_definition_body_is_harvested(self):
        cfg = (
            "vrf definition RED\n"
            "   rd 65000:1\n"
            "   description tenant red\n"
            "   route-target import 100:1\n"
            "   route-target export 100:2\n"
            "!\n"
        )
        ri = _ri(AristaEOSCodec().parse(cfg), "RED")
        assert ri.route_distinguisher == "65000:1"
        assert ri.description == "tenant red"
        assert ri.rt_imports == ["100:1"]
        assert ri.rt_exports == ["100:2"]

    def test_route_target_both_expands(self):
        cfg = (
            "vrf definition GREEN\n"
            "   rd 65000:3\n"
            "   route-target both 100:3\n"
            "!\n"
        )
        ri = _ri(AristaEOSCodec().parse(cfg), "GREEN")
        assert ri.rt_imports == ["100:3"]
        assert ri.rt_exports == ["100:3"]

    def test_modern_header_only_vrf_instance_still_works(self):
        # 4.23+ ``vrf instance`` is header-only (RD comes from router bgp);
        # the harvester must still create the bare instance.
        cfg = "vrf instance BLUE\n!\n"
        ri = _ri(AristaEOSCodec().parse(cfg), "BLUE")
        assert ri.name == "BLUE"
        assert ri.route_distinguisher == ""

    def test_router_bgp_rd_wins_over_stanza_body(self):
        # EOS precedence: the router-bgp submode RD overrides the deprecated
        # stanza-body RD.  The merge-by-name must keep the router-bgp value.
        cfg = (
            "vrf definition RED\n"
            "   rd 65000:1\n"
            "!\n"
            "router bgp 65000\n"
            "   vrf RED\n"
            "      rd 65000:999\n"
        )
        ri = _ri(AristaEOSCodec().parse(cfg), "RED")
        assert ri.route_distinguisher == "65000:999"
