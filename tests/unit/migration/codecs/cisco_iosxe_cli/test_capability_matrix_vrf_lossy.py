"""
Regression guard: `cisco_iosxe_cli` declares VRF / routing-instances
as `lossy` (not `unsupported`).

The CapabilityMatrix entry for ``/routing-instances/instance`` was
historically declared ``unsupported`` with reason "wire-up deferred".
That declaration became stale — both parse (`_parse_routing_instances`
at parse.py around line 348 — populates `intent.routing_instances`
from `vrf definition` blocks) and render (the VRF emission loop in
render.py emits `vrf definition <name>` + `rd` + RT imports/exports +
description) are wired.  Wave 10β-B (commit `40de39c`) confirmed the
cross-vendor round-trip to Junos `set routing-instances <name>` works
and re-flipped the per-pair YAML disposition `unsupported → good`.

This test pins the corrected matrix declaration so the contradiction
between codec.py (claiming unsupported) and parse.py / render.py
(actively populating + emitting) doesn't reappear.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


def _build_codec() -> CiscoIOSXECLICodec:
    return CiscoIOSXECLICodec()


class TestRoutingInstancesNoLongerUnsupported:
    """The old `unsupported` declaration was an active lie — both
    parse and render are wired.  Pin that it stays out of the
    unsupported set."""

    def test_routing_instances_not_in_unsupported(self):
        codec = _build_codec()
        unsupported_paths = {
            entry.path for entry in codec.capabilities.unsupported
        }
        assert "/routing-instances/instance" not in unsupported_paths, (
            "VRF wire-up has shipped (parse._parse_routing_instances "
            "+ render VRF emission loop + Wave 10β-B cross-vendor "
            "confirmation).  Capability matrix must not claim it is "
            "unsupported.  See codec.py LossyPath entry for the "
            "documented sub-field drift on per-VRF static routes "
            "and IPv6/EVPN VRF sub-stanzas."
        )


class TestRoutingInstancesDeclaredLossy:
    """Pin the corrected declaration: `lossy` (info-severity)
    with rationale citing the round-trip behavior + known sub-
    field drift."""

    def test_routing_instances_in_lossy(self):
        codec = _build_codec()
        lossy_paths = {
            entry.path for entry in codec.capabilities.lossy
        }
        assert "/routing-instances/instance" in lossy_paths

    def test_routing_instances_lossy_severity_warn(self):
        codec = _build_codec()
        for entry in codec.capabilities.lossy:
            if entry.path == "/routing-instances/instance":
                # `LossyPath` literal accepts only "warn" or "error"
                # (per netcanon/models/migration.py:133).  "warn"
                # matches the sibling /evpn-type5-routes/route entry.
                assert entry.severity == "warn"
                break
        else:
            pytest.fail("/routing-instances/instance not in lossy list")

    def test_routing_instances_lossy_reason_mentions_bidirectional(self):
        """The reason must document the round-trip support so a future
        contributor doesn't see "lossy" and assume the codec doesn't
        emit VRFs."""
        codec = _build_codec()
        for entry in codec.capabilities.lossy:
            if entry.path == "/routing-instances/instance":
                # Reason should mention parse + render + the cross-
                # vendor confirmation (Wave 10β-B / commit ref).
                assert "parse" in entry.reason.lower()
                assert "render" in entry.reason.lower()
                assert "wave 10" in entry.reason.lower() or \
                       "40de39c" in entry.reason
                break

    def test_routing_instances_lossy_reason_documents_subfield_drift(self):
        """The reason must document WHAT is lossy so operators know
        what to verify post-migration."""
        codec = _build_codec()
        for entry in codec.capabilities.lossy:
            if entry.path == "/routing-instances/instance":
                # Sub-field drift: per-VRF static routes (no vrf
                # discriminator on CanonicalStaticRoute) and ipv6 /
                # evpn VRF sub-stanzas.
                reason_lower = entry.reason.lower()
                assert "static route" in reason_lower or \
                       "vrf forwarding" in reason_lower or \
                       "address-family ipv6" in reason_lower or \
                       "evpn" in reason_lower, (
                    "Lossy reason must document the specific sub-"
                    "field drift surfaces (per-VRF static routes / "
                    "IPv6 / EVPN sub-stanzas) so operators know "
                    "what to verify."
                )
                break


class TestVxlanNveSupported:
    """VXLAN-EVPN nve1 is genuinely supported (promotion #16).

    ``cisco_iosxe_cli`` now intercepts ``interface nve1`` on parse (mirrors
    cisco_nxos), correlates the ``vlan configuration N / member
    [evpn-instance M] vni V`` bindings, and re-emits the VTEP on render.  The
    W11-A-era "still unsupported" pins were correct at the time but are now
    stale — this class pins the graduated dispositions instead."""

    def test_vni_and_source_interface_supported(self):
        codec = _build_codec()
        supported = set(codec.capabilities.supported)
        unsupported = {e.path for e in codec.capabilities.unsupported}
        for path in ("/vxlan-vnis/vni", "/vxlan-vnis/source-interface",
                     "/vxlan-vnis/mcast-group",
                     "/routing-instances/instance/l3-vni"):
            assert path in supported, (
                f"{path} should be supported — promotion #16 wired "
                f"parse (interface nve1 interception) + render (VTEP emit)."
            )
            assert path not in unsupported, f"{path} must not be unsupported"

    def test_udp_port_and_flood_list_lossy(self):
        codec = _build_codec()
        lossy = {e.path for e in codec.capabilities.lossy}
        unsupported = {e.path for e in codec.capabilities.unsupported}
        # udp-port: render emits no `vxlan udp-port` override (re-parses as
        # 4789).  flood-list: no per-VNI static ingress-replication grammar.
        for path in ("/vxlan-vnis/udp-port", "/vxlan-vnis/flood-list"):
            assert path in lossy, (
                f"{path} should be lossy — the NVE render keeps the VNI "
                f"identity but drops this sub-detail (mirrors cisco_nxos)."
            )
            assert path not in unsupported, f"{path} must not be unsupported"
