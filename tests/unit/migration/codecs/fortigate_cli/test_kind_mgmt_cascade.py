"""
FortiGate CLI: kind=mgmt cascade from cisco_iosxe_cli Mgmt-vrf source.

Closes the cross-vendor cascade gap identified in commit ``56a4cde``
(Wave 2): the cisco_iosxe_cli parser promotes ``GigabitEthernet0/0``
bound to ``Mgmt-vrf`` to ``CanonicalInterface.kind="mgmt"``, but the
FortiGate render ignored the override and emitted the interface as a
regular ``port1``.  After this fix the FortiGate ``format_port_identity``
returns ``mgmt1`` (FortiOS's standard out-of-band port name on FG-100F+
hardware) so the rename mesh produces ``edit "mgmt1"`` blocks.

Mirrors ``test_mgmt_vrf_cascades_to_aruba_oobm`` from the cisco_iosxe_cli
unit tests, which validated the same cascade against Aruba's ``oobm``
top-level block.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalIPv4Address,
    CanonicalInterface,
)
from netconfig.migration.canonical.port_names import (
    PortIdentity,
    translate_port_names,
)
from netconfig.migration.codecs.cisco_iosxe_cli.codec import (
    CiscoIOSXECLICodec,
)
from netconfig.migration.codecs.fortigate_cli import FortiGateCLICodec
from netconfig.migration.codecs.fortigate_cli.port_names import (
    format_port_identity,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Identity-level: kind=mgmt → "mgmt1"
# ---------------------------------------------------------------------------


def test_kind_mgmt_renders_as_mgmt_port() -> None:
    """A bare ``kind="mgmt"`` :class:`PortIdentity` (no FortiGate role
    meta — i.e. cross-vendor source) formats to ``mgmt1`` so the
    target render emits a dedicated FortiOS management interface
    rather than a regular numbered port."""
    ident = PortIdentity(kind="mgmt", original="GigabitEthernet0/0")
    assert format_port_identity(ident) == "mgmt1"


def test_kind_mgmt_same_vendor_round_trip_preserves_bare_mgmt() -> None:
    """Same-vendor round-trip: a FortiGate source ``mgmt`` interface
    classifies with ``fortigate_role="mgmt"`` and ``port=1``.  The
    formatter MUST preserve the bare ``mgmt`` (no numeric suffix) so
    intra-vendor renders don't gain a spurious ``1`` on small FG-60F
    appliances where ``mgmt`` is the literal port name."""
    ident = PortIdentity(
        kind="mgmt",
        port=1,
        meta={"fortigate_role": "mgmt"},
        original="mgmt",
    )
    assert format_port_identity(ident) == "mgmt"


def test_kind_mgmt_in_render_appears_as_mgmt1_edit() -> None:
    """A synthetic canonical intent with a kind=mgmt interface produces
    a FortiOS ``edit "mgmt1"`` block carrying the IP — the rename mesh
    runs externally so the test simulates a post-rename state where
    the iface name has already been rewritten to ``mgmt1``."""
    tree = CanonicalIntent(
        hostname="fw01",
        interfaces=[
            CanonicalInterface(
                name="mgmt1",
                kind="mgmt",
                ipv4_addresses=[
                    CanonicalIPv4Address(
                        ip="10.10.10.252", prefix_length=24,
                    ),
                ],
                enabled=True,
            ),
        ],
    )
    out = FortiGateCLICodec().render(tree)
    assert 'edit "mgmt1"' in out
    assert "set ip 10.10.10.252 255.255.255.0" in out


# ---------------------------------------------------------------------------
# Full pipeline cascade: cisco Mgmt-vrf → fortigate mgmt port
# ---------------------------------------------------------------------------


def test_cisco_mgmt_vrf_cascades_to_fortigate_mgmt_port() -> None:
    """End-to-end cascade — Cisco IOS-XE source with
    ``vrf forwarding Mgmt-vrf`` on ``GigabitEthernet0/0`` translates
    to a FortiGate output containing ``edit "mgmt1"`` with the IP
    preserved.  Mirrors the Aruba ``oobm`` cascade test in
    tests/unit/migration/codecs/cisco_iosxe_cli/test_mgmt_vrf_kind_promotion.py.

    Without the kind=mgmt branch in fortigate_cli's port_names, the
    cisco source would render as ``edit "port1"`` (or worse, a
    multi-axis collision with operator ports) — the operator's
    intended out-of-band management address would be silently merged
    with regular data-plane traffic.
    """
    cfg = (
        "hostname r1\n"
        "interface GigabitEthernet0/0\n"
        " vrf forwarding Mgmt-vrf\n"
        " ip address 10.10.10.252 255.255.255.0\n"
        "!\n"
    )
    cisco_codec = CiscoIOSXECLICodec()
    forti_codec = FortiGateCLICodec()
    intent = cisco_codec.parse(cfg)

    # Sanity: parser set the kind override.
    gi = next(
        i for i in intent.interfaces if i.name == "GigabitEthernet0/0"
    )
    assert gi.kind == "mgmt"

    # Translate port names cisco → fortigate.  The override threads
    # through to format_port_identity and produces "mgmt1".
    result = translate_port_names(intent, cisco_codec, forti_codec)
    assert result.applied.get("GigabitEthernet0/0") == "mgmt1"

    # Render and confirm the dedicated mgmt edit emits.
    out = forti_codec.render(intent)
    assert 'edit "mgmt1"' in out, (
        "FortiGate render should emit the dedicated mgmt1 edit block "
        "when the source's mgmt-vrf-bound port cascades to kind=mgmt"
    )
    assert "set ip 10.10.10.252 255.255.255.0" in out
    # The cascade must NOT leave the port renamed as a regular port.
    assert 'edit "port1"' not in out
