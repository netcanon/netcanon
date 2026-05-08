"""
Unit tests for the VXLAN + EVPN Type-5 canonical schema extension.

This is a **ship-before-wire** commit: the canonical model gains
``CanonicalVxlan`` and ``CanonicalEvpnType5Route`` plus the
``vxlan_vnis`` / ``evpn_type5_routes`` top-level lists on
:class:`CanonicalIntent`, but no codec populates them yet.

Tests verify:

1.  The new models construct with sensible defaults and validate the
    cross-vendor-stable fields (VNI range, VLAN range).
2.  The new list fields default to empty on a fresh :class:`CanonicalIntent`.
3.  Round-trip through ``model_dump()`` / ``model_validate()`` preserves
    the new data — proves JSON-serialisation doesn't drop it.
4.  Every DC-class codec's :class:`CapabilityMatrix` declares the new
    xpaths under ``unsupported`` so the UI banner surfaces the gap even
    before any codec wires up parse/render.

See ``docs/adding-a-canonical-field.md`` for the wire-through procedure
each codec will follow once EVPN-VXLAN demand arrives.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalEvpnType5Route,
    CanonicalIntent,
    CanonicalVxlan,
)
from netcanon.migration.codecs.arista_eos import AristaEOSCodec
from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netcanon.migration.codecs.juniper_junos import JunosCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# CanonicalVxlan — model-level
# ---------------------------------------------------------------------------


class TestCanonicalVxlan:
    def test_minimal_construct(self):
        v = CanonicalVxlan(vlan_id=100, vni=10100)
        assert v.vlan_id == 100
        assert v.vni == 10100
        assert v.mcast_group == ""
        assert v.flood_list == []

    def test_mcast_group_construct(self):
        v = CanonicalVxlan(vlan_id=200, vni=20200, mcast_group="239.1.1.100")
        assert v.mcast_group == "239.1.1.100"

    def test_flood_list_construct(self):
        v = CanonicalVxlan(
            vlan_id=300,
            vni=30300,
            flood_list=["10.0.0.1", "10.0.0.2"],
        )
        assert v.flood_list == ["10.0.0.1", "10.0.0.2"]

    def test_vni_min_valid(self):
        # Lowest legal VNI is 1.
        v = CanonicalVxlan(vlan_id=1, vni=1)
        assert v.vni == 1

    def test_vni_max_valid(self):
        # Highest legal VNI is 16777215 (2^24 - 1).
        v = CanonicalVxlan(vlan_id=4094, vni=16_777_215)
        assert v.vni == 16_777_215

    def test_vni_too_low_rejected(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            CanonicalVxlan(vlan_id=10, vni=0)

    def test_vni_too_high_rejected(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            CanonicalVxlan(vlan_id=10, vni=16_777_216)

    def test_vlan_id_out_of_range_rejected(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            CanonicalVxlan(vlan_id=4095, vni=100)
        with pytest.raises(Exception):  # pydantic ValidationError
            CanonicalVxlan(vlan_id=0, vni=100)


# ---------------------------------------------------------------------------
# CanonicalEvpnType5Route — model-level
# ---------------------------------------------------------------------------


class TestCanonicalEvpnType5Route:
    def test_minimal_construct(self):
        r = CanonicalEvpnType5Route(vrf="TENANT_A", prefix="10.1.0.0/16")
        assert r.vrf == "TENANT_A"
        assert r.prefix == "10.1.0.0/16"
        assert r.rt_imports == []
        assert r.rt_exports == []

    def test_rt_communities(self):
        r = CanonicalEvpnType5Route(
            vrf="TENANT_A",
            prefix="10.1.0.0/16",
            rt_imports=["65001:100", "65001:200"],
            rt_exports=["65001:100"],
        )
        assert r.rt_imports == ["65001:100", "65001:200"]
        assert r.rt_exports == ["65001:100"]

    def test_ipv6_prefix_accepted(self):
        """Prefix is stored as opaque CIDR; codecs decide address-family."""
        r = CanonicalEvpnType5Route(vrf="V6_TENANT", prefix="2001:db8::/48")
        assert r.prefix == "2001:db8::/48"

    def test_vrf_required(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            CanonicalEvpnType5Route(prefix="10.1.0.0/16")  # type: ignore[call-arg]

    def test_prefix_required(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            CanonicalEvpnType5Route(vrf="TENANT_A")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# CanonicalIntent — top-level integration
# ---------------------------------------------------------------------------


class TestCanonicalIntentVxlanEvpnFields:
    def test_fresh_intent_has_empty_lists(self):
        """Default-constructed intent must expose the new lists as [].

        Regression guard: if the fields go missing (e.g. merge conflict
        drops them), existing trees still construct but panes that rely
        on these fields would silently fail.  Here we fail loud.
        """
        i = CanonicalIntent()
        assert i.vxlan_vnis == []
        assert i.evpn_type5_routes == []

    def test_roundtrip_through_model_dump(self):
        """Serialisation preserves the new fields — proves the pydantic
        shape is JSON-safe and any code path that dumps+reloads the
        tree (background job persistence, API responses) carries the
        fabric data through intact."""
        original = CanonicalIntent(
            hostname="leaf-01",
            vxlan_vnis=[
                CanonicalVxlan(vlan_id=100, vni=10100, mcast_group="239.1.1.100"),
                CanonicalVxlan(vlan_id=200, vni=20200, flood_list=["10.0.0.1"]),
            ],
            evpn_type5_routes=[
                CanonicalEvpnType5Route(
                    vrf="TENANT_A",
                    prefix="10.1.0.0/16",
                    rt_imports=["65001:100"],
                    rt_exports=["65001:100"],
                ),
            ],
        )
        dumped = original.model_dump()
        restored = CanonicalIntent.model_validate(dumped)
        assert restored.vxlan_vnis == original.vxlan_vnis
        assert restored.evpn_type5_routes == original.evpn_type5_routes

    def test_fields_are_additive(self):
        """Adding fabric data must not require clearing existing fields."""
        i = CanonicalIntent(
            hostname="spine-01",
            interfaces=[],
            vlans=[],
            vxlan_vnis=[CanonicalVxlan(vlan_id=100, vni=10100)],
        )
        assert i.hostname == "spine-01"
        assert i.vxlan_vnis[0].vni == 10100


# ---------------------------------------------------------------------------
# CapabilityMatrix integration — DC codecs must declare the gap
# ---------------------------------------------------------------------------


class TestDCCodecsDeclareEvpnType5Lossy:
    """Per-prefix EVPN Type-5 records (`CanonicalEvpnType5Route`)
    are LOSSY on every DC codec (previously Unsupported; demoted
    post-GAP-6 as part of the Type-5-via-l3_vni-VRF-property
    canonical model).  Real configs don't enumerate per-prefix
    records — Type-5 announcements are implicit for any subnet
    carried by a VRF-bound interface whose VRF has a non-None
    l3_vni.  This test locks in the lossy classification with
    non-empty rationale so consumers know the semantic path to
    use.
    """

    _DC_CODECS = [
        (AristaEOSCodec, "arista_eos"),
        (CiscoIOSXECLICodec, "cisco_iosxe_cli"),
        (JunosCodec, "juniper_junos"),
    ]

    @pytest.mark.parametrize("codec_cls,name", _DC_CODECS)
    def test_declares_evpn_type5_lossy(self, codec_cls, name):
        caps = codec_cls().capabilities
        lossy_paths = {lp.path for lp in caps.lossy}
        assert "/evpn-type5-routes/route" in lossy_paths, (
            f"{name} missing lossy declaration for "
            "/evpn-type5-routes/route"
        )

    @pytest.mark.parametrize("codec_cls,name", _DC_CODECS)
    def test_evpn_classify_returns_lossy(self, codec_cls, name):
        caps = codec_cls().capabilities
        assert caps.classify("/evpn-type5-routes/route") == "lossy"

    @pytest.mark.parametrize("codec_cls,name", _DC_CODECS)
    def test_lossy_reason_non_empty(self, codec_cls, name):
        """Every lossy declaration must explain what's lossy about
        the path + what the supported canonical alternative is."""
        caps = codec_cls().capabilities
        by_path = {lp.path: lp for lp in caps.lossy}
        reason = by_path["/evpn-type5-routes/route"].reason
        assert reason.strip() != ""
        # Sanity: the reason should mention l3_vni as the
        # supported alternative.
        assert "l3_vni" in reason

    @pytest.mark.parametrize("codec_cls,name", _DC_CODECS)
    def test_evpn_no_longer_in_unsupported(self, codec_cls, name):
        """Regression guard — after the demotion, the path must
        NOT appear in the Unsupported list (otherwise classify()
        strictest-wins logic would call it unsupported, not lossy)."""
        caps = codec_cls().capabilities
        unsupported_paths = {u.path for u in caps.unsupported}
        assert "/evpn-type5-routes/route" not in unsupported_paths


class TestAristaJunosVxlanVniDemoted:
    """GAP 6: arista_eos + juniper_junos both PARSE + RENDER
    VLAN↔VNI mappings now; ``/vxlan-vnis/vni`` is supported on both."""

    def test_arista_vxlan_supported(self):
        caps = AristaEOSCodec().capabilities
        assert caps.classify("/vxlan-vnis/vni") == "supported"

    def test_arista_routing_instances_supported(self):
        caps = AristaEOSCodec().capabilities
        assert caps.classify("/routing-instances/instance") == "supported"

    def test_junos_vxlan_supported(self):
        caps = JunosCodec().capabilities
        assert caps.classify("/vxlan-vnis/vni") == "supported"

    def test_junos_routing_instances_supported(self):
        caps = JunosCodec().capabilities
        assert caps.classify("/routing-instances/instance") == "supported"
