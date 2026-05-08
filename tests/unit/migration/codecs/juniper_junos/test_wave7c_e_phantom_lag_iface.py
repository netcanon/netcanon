"""
Wave 7c-E regression tests: phantom ae<N> LAG-name iface suppression.

When Junos render emits a LAG (``set interfaces ae<N> aggregated-ether-
options lacp <mode>``) without any per-iface body attrs, the parser's
``_apply_interfaces`` dispatcher unconditionally seeds an empty
``iface_state[name]`` entry.  Pre-fix, the materialisation loop turned
every such entry into a phantom CanonicalInterface, shifting the
alphabetically-sorted iface list and corrupting the index-aligned drift
comparison for cross-vendor cells.  fortigate_cli -> juniper_junos
surfaced 3 CODEC_BUGs from this single root cause: cluster-vlan / dmz /
fortihome-ssl IPv4 + description + enabled all "shifted by 2" because
two phantom ae0 / ae1 iface records appeared at the start of the
sorted list.

The fix elides the phantom at materialisation: an empty iface_state
entry whose name appears in lag_state never creates a
CanonicalInterface.  The CanonicalLAG record alone carries the LAG
identity.

References:
- Junos `aggregated-ether-options` grammar:
  https://www.juniper.net/documentation/us/en/software/junos/interfaces-ethernet/topics/topic-map/configuring-aggregated-ethernet-interfaces.html
- Phase 4 finding doc: tests/fixtures/real/phase4_findings_fortigate_cli.md
  (the 3-CODEC_BUG signature on user_contrib_fg100e_fos7213.conf was
  *misdiagnosed* there as an interface-range collapse asymmetry; the
  actual root cause is this LAG-name phantom at parse-time).
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalInterface,
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalLAG,
)
from netcanon.migration.codecs.juniper_junos.parse import parse_intent
from netcanon.migration.codecs.juniper_junos.render import render_intent

pytestmark = pytest.mark.unit


def test_phantom_ae_lag_iface_suppressed_when_iface_state_empty() -> None:
    """A LAG stanza with no per-iface body must not materialise a
    phantom CanonicalInterface for the ae-name."""
    cfg = (
        "set interfaces ae0 aggregated-ether-options lacp active\n"
        "set interfaces ge-0/0/1 ether-options 802.3ad ae0\n"
        "set interfaces ge-0/0/2 ether-options 802.3ad ae0\n"
    )
    intent = parse_intent(cfg)
    iface_names = {i.name for i in intent.interfaces}
    # Member ports DO materialise.
    assert "ge-0/0/1" in iface_names
    assert "ge-0/0/2" in iface_names
    # The LAG aggregator name must NOT materialise as a phantom iface.
    assert "ae0" not in iface_names
    # The LAG record IS materialised.
    lag_names = {l.name for l in intent.lags}
    assert lag_names == {"ae0"}


def test_ae_iface_with_real_body_still_materialises() -> None:
    """When operators DO configure per-iface attrs on the ae<N>
    (description / L3 IP), the phantom-suppression must NOT fire."""
    cfg = (
        "set interfaces ae0 description \"uplink-bundle\"\n"
        "set interfaces ae0 aggregated-ether-options lacp active\n"
        "set interfaces ae0 unit 0 family inet address 10.0.0.1/24\n"
    )
    intent = parse_intent(cfg)
    iface_names = {i.name for i in intent.interfaces}
    assert "ae0" in iface_names
    ae0 = next(i for i in intent.interfaces if i.name == "ae0")
    assert ae0.description == "uplink-bundle"
    assert ae0.ipv4_addresses[0].ip == "10.0.0.1"


def test_fortigate_to_junos_no_phantom_ae_in_round_trip() -> None:
    """End-to-end cross-vendor: rendering a FortiGate-sourced canonical
    intent (carries ``fortilink`` / ``lacp-trunk`` LAG-name ifaces) into
    Junos and reparsing must not append phantom ``ae<N>`` entries to
    the iface list — those were the root cause of the shifted-by-N
    drift on cluster-vlan / dmz / fortihome-ssl in the Phase 4 matrix."""
    intent = CanonicalIntent(
        interfaces=[
            CanonicalInterface(
                name="cluster-vlan",
                description="cluster-vlan",
                enabled=True,
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.10.10.100", prefix_length=24,
                    ),
                ],
            ),
            CanonicalInterface(
                name="fortilink",
                interface_type="ianaift:ieee8023adLag",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.255.1.1", prefix_length=24,
                    ),
                ],
            ),
            CanonicalInterface(
                name="port1",
                lag_member_of="lacp-trunk",
            ),
        ],
        lags=[
            CanonicalLAG(name="fortilink", members=[], mode="active"),
            CanonicalLAG(
                name="lacp-trunk",
                members=["port1"],
                mode="active",
            ),
        ],
    )
    rendered = render_intent(intent)
    reparsed = parse_intent(rendered)
    iface_names = sorted(i.name for i in reparsed.interfaces)
    # No phantom ae<N> record should appear.
    leaked = [
        n for n in iface_names
        if n.startswith("ae") and n[2:].isdigit()
    ]
    assert not leaked, f"phantom ae<N> entries leaked: {leaked}"
