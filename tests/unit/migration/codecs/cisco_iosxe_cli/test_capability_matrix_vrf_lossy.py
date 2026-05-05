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

from netconfig.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec

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
                # (per netconfig/models/migration.py:133).  "warn"
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


class TestVxlanStillUnsupported:
    """VXLAN remains genuinely unsupported (no parse + no render in
    `cisco_iosxe_cli`).  Pin that the W11-A-era declarations stay
    in the `unsupported` set — they're correct, unlike the VRF one
    that was stale."""

    def test_vxlan_paths_still_unsupported(self):
        codec = _build_codec()
        unsupported_paths = {
            entry.path for entry in codec.capabilities.unsupported
        }
        for path in (
            "/vxlan-vnis/vni",
            "/vxlan-vnis/source-interface",
            "/vxlan-vnis/udp-port",
        ):
            assert path in unsupported_paths, (
                f"{path} should remain unsupported — no VXLAN parse "
                f"or render code exists in `cisco_iosxe_cli` "
                f"(verified absence at commit `170a2c2` validation "
                f"audit)."
            )
