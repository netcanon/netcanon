"""
Unit tests for the CanonicalRoutingInstance schema (GAP 5).

Like GAP 1's VXLAN/EVPN schema, this is a **ship-before-wire** commit:
the canonical model gains :class:`CanonicalRoutingInstance` + the
``routing_instances`` list on :class:`CanonicalIntent` + the
``vrf`` field on :class:`CanonicalInterface`.  No codec populates any
of these in v1.

Tests verify:

1. Construction + defaults on the new model.
2. :attr:`CanonicalInterface.vrf` defaults to empty string (global VRF).
3. :attr:`CanonicalIntent.routing_instances` defaults to empty list.
4. Round-trip through ``model_dump()`` / ``model_validate()`` preserves
   the new data.
5. Every DC-class codec's :class:`CapabilityMatrix` declares
   ``/routing-instances/instance`` under ``unsupported`` so the UI
   surfaces the gap.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalRoutingInstance,
)
from netconfig.migration.codecs.arista_eos import AristaEOSCodec
from netconfig.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec
from netconfig.migration.codecs.juniper_junos import JunosCodec

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# CanonicalRoutingInstance — model-level
# ---------------------------------------------------------------------------


class TestCanonicalRoutingInstance:
    def test_minimal_construct(self):
        ri = CanonicalRoutingInstance(name="TENANT_A")
        assert ri.name == "TENANT_A"
        assert ri.instance_type == "vrf"
        assert ri.route_distinguisher == ""
        assert ri.rt_imports == []
        assert ri.rt_exports == []
        assert ri.description == ""

    def test_full_construct(self):
        ri = CanonicalRoutingInstance(
            name="TENANT_A",
            instance_type="vrf",
            route_distinguisher="65001:100",
            rt_imports=["65001:100", "65001:200"],
            rt_exports=["65001:100"],
            description="customer A",
        )
        assert ri.name == "TENANT_A"
        assert ri.route_distinguisher == "65001:100"
        assert ri.rt_imports == ["65001:100", "65001:200"]
        assert ri.rt_exports == ["65001:100"]
        assert ri.description == "customer A"

    def test_junos_instance_types_accepted(self):
        """Junos has variants beyond plain VRF; canonical stores the
        vendor-facing label so render-side codecs can distinguish."""
        for itype in ("vrf", "virtual-router", "l2vpn", "mac-vrf"):
            ri = CanonicalRoutingInstance(name="X", instance_type=itype)
            assert ri.instance_type == itype

    def test_name_required(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            CanonicalRoutingInstance()  # type: ignore[call-arg]

    def test_rd_ip_form_accepted(self):
        """Some vendors use `<ip>:<nn>` RD form; canonical is opaque
        string — validation belongs in render-side where the RD format
        matters to the target vendor."""
        ri = CanonicalRoutingInstance(
            name="TENANT",
            route_distinguisher="192.0.2.1:100",
        )
        assert ri.route_distinguisher == "192.0.2.1:100"


# ---------------------------------------------------------------------------
# CanonicalInterface.vrf
# ---------------------------------------------------------------------------


class TestCanonicalInterfaceVrf:
    def test_vrf_defaults_to_empty(self):
        iface = CanonicalInterface(name="ge-0/0/0")
        assert iface.vrf == ""

    def test_vrf_settable(self):
        iface = CanonicalInterface(name="ge-0/0/0", vrf="TENANT_A")
        assert iface.vrf == "TENANT_A"

    def test_vrf_field_roundtrips_through_dump(self):
        iface = CanonicalInterface(name="ge-0/0/0", vrf="TENANT_A")
        data = iface.model_dump()
        restored = CanonicalInterface.model_validate(data)
        assert restored.vrf == "TENANT_A"


# ---------------------------------------------------------------------------
# CanonicalIntent — top-level integration
# ---------------------------------------------------------------------------


class TestCanonicalIntentRoutingInstances:
    def test_fresh_intent_has_empty_list(self):
        i = CanonicalIntent()
        assert i.routing_instances == []

    def test_roundtrip_through_model_dump(self):
        """Serialisation preserves the new list — proves pydantic
        carries it through background-job persistence + API JSON."""
        original = CanonicalIntent(
            hostname="leaf-01",
            routing_instances=[
                CanonicalRoutingInstance(
                    name="TENANT_A",
                    route_distinguisher="65001:100",
                    rt_imports=["65001:100"],
                    rt_exports=["65001:100"],
                ),
                CanonicalRoutingInstance(
                    name="TENANT_B",
                    description="customer B",
                ),
            ],
            interfaces=[
                CanonicalInterface(name="ge-0/0/0.100", vrf="TENANT_A"),
                CanonicalInterface(name="ge-0/0/0.200", vrf="TENANT_B"),
                CanonicalInterface(name="ge-0/0/1"),  # global VRF
            ],
        )
        dumped = original.model_dump()
        restored = CanonicalIntent.model_validate(dumped)
        assert restored.routing_instances == original.routing_instances
        assert restored.interfaces[0].vrf == "TENANT_A"
        assert restored.interfaces[1].vrf == "TENANT_B"
        assert restored.interfaces[2].vrf == ""

    def test_vrf_membership_via_interface(self):
        """Per-interface `vrf` field is the source of truth for
        membership; routing-instances list carries metadata only."""
        intent = CanonicalIntent(
            routing_instances=[CanonicalRoutingInstance(name="TENANT_A")],
            interfaces=[
                CanonicalInterface(name="ge-0/0/0.100", vrf="TENANT_A"),
                CanonicalInterface(name="ge-0/0/0.200", vrf="TENANT_A"),
            ],
        )
        tenant_a_ifaces = [
            i.name for i in intent.interfaces if i.vrf == "TENANT_A"
        ]
        assert tenant_a_ifaces == ["ge-0/0/0.100", "ge-0/0/0.200"]


# ---------------------------------------------------------------------------
# CapabilityMatrix integration — DC codecs must declare the gap
# ---------------------------------------------------------------------------


class TestDCCodecsDeclareRoutingInstancesUnsupported:
    """Ship-before-wire contract — every DC-class codec declares
    /routing-instances/instance under Unsupported so the UI banner
    surfaces the gap."""

    # After GAP 6, Arista + Junos both PARSE + RENDER VRF declarations;
    # only Cisco IOS-XE CLI remains Unsupported (no wire-up planned
    # near-term — not a DC-fabric codec in most deployments).
    _DC_CODECS = [
        (CiscoIOSXECLICodec, "cisco_iosxe_cli"),
    ]

    @pytest.mark.parametrize("codec_cls,name", _DC_CODECS)
    def test_declares_routing_instances_unsupported(self, codec_cls, name):
        caps = codec_cls().capabilities
        paths = {u.path for u in caps.unsupported}
        assert "/routing-instances/instance" in paths, (
            f"{name} missing unsupported declaration for "
            "/routing-instances/instance — ship-before-wire contract "
            "requires DC codecs to report the gap"
        )

    @pytest.mark.parametrize("codec_cls,name", _DC_CODECS)
    def test_classify_returns_unsupported(self, codec_cls, name):
        caps = codec_cls().capabilities
        assert caps.classify("/routing-instances/instance") == "unsupported"

    @pytest.mark.parametrize("codec_cls,name", _DC_CODECS)
    def test_unsupported_reason_non_empty(self, codec_cls, name):
        caps = codec_cls().capabilities
        by_path = {u.path: u for u in caps.unsupported}
        assert by_path["/routing-instances/instance"].reason.strip() != ""


class TestWiredCodecsClassifySupported:
    """GAP 6: arista_eos + juniper_junos PARSE + RENDER
    ``/routing-instances/instance`` now.  Verify the matrix
    classifies it as ``supported`` (not leftover in the
    ``unsupported`` list)."""

    @pytest.mark.parametrize(
        "codec_cls,name",
        [
            (AristaEOSCodec, "arista_eos"),
            (JunosCodec, "juniper_junos"),
        ],
    )
    def test_routing_instances_supported(self, codec_cls, name):
        caps = codec_cls().capabilities
        assert caps.classify("/routing-instances/instance") == "supported"
