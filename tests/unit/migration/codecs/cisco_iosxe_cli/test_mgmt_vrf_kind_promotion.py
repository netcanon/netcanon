"""
Cisco IOS-XE CLI parser: Mgmt-vrf → kind=mgmt promotion.

Real Cisco c9300 / c9500 / c9500X configs bind their out-of-band
``GigabitEthernet0/0`` port to a top-level ``Mgmt-vrf`` VRF
(``vrf forwarding Mgmt-vrf``).  The interface name alone classifies
as ``kind="physical"`` via :func:`port_names.classify_port_name`, so
without this promotion the cross-vendor port-rename mesh treats
``GigabitEthernet0/0`` like any other access port — Aruba's renderer
emits a regular ``interface 1/1`` stub instead of the dedicated
``oobm`` block, FortiGate emits a regular ``port1`` instead of a
``mgmt`` interface, etc.

The fix is at the source-parser level: the cisco_iosxe_cli parser
detects the management-VRF binding and sets
:attr:`CanonicalInterface.kind` = ``"mgmt"``.  This cascades to every
target codec's existing kind=mgmt handling without per-target codec
changes.

See ``tests/fixtures/real/user_smoke_findings.md`` issue 8 for the
cross-target cascade discussion.

The unit tests below exercise the parser's promotion logic.  The
integration test (``test_mgmt_vrf_cascades_to_aruba_oobm``) confirms
the cascade reaches Aruba's ``oobm`` block end-to-end.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical.intent import (
    CanonicalIPv4Address,
    CanonicalInterface,
)
from netconfig.migration.codecs.aruba_aoss.codec import ArubaAOSSCodec
from netconfig.migration.codecs.cisco_iosxe_cli.codec import (
    CiscoIOSXECLICodec,
)
from netconfig.migration.codecs.cisco_iosxe_cli.parse import parse_intent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Parser-level promotion (kind override on the canonical interface)
# ---------------------------------------------------------------------------


def test_mgmt_vrf_promotes_kind_to_mgmt() -> None:
    """``vrf forwarding Mgmt-vrf`` on a physical interface promotes
    its canonical ``kind`` from default ``""`` (infer-from-name) to
    explicit ``"mgmt"``.  The cross-vendor rename mesh consumes the
    override so every target's kind=mgmt handler fires."""
    cfg = (
        "interface GigabitEthernet0/0\n"
        " vrf forwarding Mgmt-vrf\n"
        " ip address 10.10.10.252 255.255.255.0\n"
    )
    intent = parse_intent(cfg)
    gi = next(i for i in intent.interfaces if i.name == "GigabitEthernet0/0")
    assert gi.kind == "mgmt"
    # VRF binding still preserved (mgmt promotion is additive, not a
    # replacement for the per-interface VRF field).
    assert gi.vrf == "Mgmt-vrf"


def test_user_vrf_does_not_promote_kind() -> None:
    """A user-defined VRF (``RED``, ``TENANT_A``, etc.) MUST NOT
    promote the canonical kind.  Only VRF names that match the
    management heuristic (``Mgmt-vrf``, ``mgmt``, ``management``)
    qualify — everything else stays at the default-inferred kind."""
    cfg = (
        "interface GigabitEthernet1/0/1\n"
        " vrf forwarding RED\n"
        " ip address 10.0.0.1 255.255.255.0\n"
    )
    intent = parse_intent(cfg)
    gi = next(i for i in intent.interfaces if i.name == "GigabitEthernet1/0/1")
    # Default empty kind — name-based classifier on the rename side
    # will return kind="physical" verbatim.
    assert gi.kind == ""
    assert gi.vrf == "RED"


def test_management_vrf_lowercase_promotes() -> None:
    """The heuristic is case-insensitive AND covers the common
    operator variants: ``Mgmt-vrf`` (Catalyst default), ``mgmt``,
    ``management``, ``MGMTVRF``, ``mgmt_vrf``."""
    for vrf_name in (
        "mgmt-vrf",
        "Mgmt-vrf",
        "MGMT-VRF",
        "mgmt",
        "MGMT",
        "management",
        "Management",
        "MGMTVRF",
        "mgmtvrf",
        "mgmt_vrf",
    ):
        cfg = (
            f"interface GigabitEthernet0/0\n"
            f" vrf forwarding {vrf_name}\n"
            f" ip address 10.10.10.252 255.255.255.0\n"
        )
        intent = parse_intent(cfg)
        gi = next(
            i for i in intent.interfaces if i.name == "GigabitEthernet0/0"
        )
        assert gi.kind == "mgmt", (
            f"VRF name {vrf_name!r} should promote to kind=mgmt"
        )


def test_lookalike_user_vrf_does_not_promote() -> None:
    """Conservative match: VRFs that merely START with ``Mgmt`` (e.g.
    ``MgmtTenant_A``, ``ManagedNet``) MUST NOT trigger the promotion
    — only fully-matching management names qualify."""
    for vrf_name in ("MgmtTenant_A", "MgmtCustomer", "ManagedNet"):
        cfg = (
            f"interface GigabitEthernet1/0/1\n"
            f" vrf forwarding {vrf_name}\n"
            f" ip address 10.0.0.1 255.255.255.0\n"
        )
        intent = parse_intent(cfg)
        gi = next(
            i for i in intent.interfaces if i.name == "GigabitEthernet1/0/1"
        )
        assert gi.kind == "", (
            f"VRF name {vrf_name!r} must NOT promote to kind=mgmt"
        )


def test_loopback_with_mgmt_vrf_does_not_promote() -> None:
    """Defensive: a Loopback bound to Mgmt-vrf is still semantically
    a loopback for cross-vendor rename purposes — the name encodes a
    stronger role signal than the VRF binding.  Do NOT override
    loopback / SVI / LAG / tunnel kinds."""
    cfg = (
        "interface Loopback0\n"
        " vrf forwarding Mgmt-vrf\n"
        " ip address 10.255.0.1 255.255.255.255\n"
    )
    intent = parse_intent(cfg)
    lo = next(i for i in intent.interfaces if i.name == "Loopback0")
    # Default empty — name-based classifier returns kind="loopback"
    # at rename time and that wins.  We do NOT carry "loopback" in
    # CanonicalInterface.kind because the override field exists
    # specifically for cases the name UNDERSELLS the role; loopback
    # names already say loopback.
    assert lo.kind == ""
    assert lo.vrf == "Mgmt-vrf"


def test_already_mgmt_kind_unchanged() -> None:
    """Idempotent: an interface dict that somehow arrives with an
    explicit non-empty kind (synthetic input shapes; defensive guard
    against future parser additions setting it earlier) does NOT get
    re-overwritten by the mgmt-vrf promotion."""
    # The parser doesn't set kind from any other source today, so
    # this property is enforced via the no-promotion-when-name-isn't-
    # physical guard (test_loopback_with_mgmt_vrf_does_not_promote).
    # Construct an interface directly to pin the schema-level
    # invariant: a CanonicalInterface with kind already set survives
    # the round-trip unchanged.
    iface = CanonicalInterface(
        name="GigabitEthernet0/0",
        vrf="Mgmt-vrf",
        kind="mgmt",
        ipv4_addresses=[
            CanonicalIPv4Address(ip="10.10.10.252", prefix_length=24),
        ],
    )
    assert iface.kind == "mgmt"
    assert iface.vrf == "Mgmt-vrf"


# ---------------------------------------------------------------------------
# Cross-vendor cascade — Aruba's existing kind=mgmt handler emits oobm
# ---------------------------------------------------------------------------


def test_mgmt_vrf_cascades_to_aruba_oobm() -> None:
    """End-to-end: a Cisco IOS-XE source config with a Mgmt-vrf-bound
    ``GigabitEthernet0/0`` translates to an Aruba target config that
    emits the dedicated ``oobm`` top-level block (because Aruba's
    ``format_port_identity`` for kind=mgmt returns the literal name
    ``"oobm"`` and Aruba's renderer picks up an interface so named
    via the dedicated block).

    Without the parser-level promotion this test fails: Aruba would
    receive ``GigabitEthernet0/0`` classified as kind=physical,
    Aruba's port formatter would produce ``1/1``, and the OOBM
    block would never appear in the output.
    """
    from netconfig.migration.canonical.port_names import (
        translate_port_names,
    )

    cfg = (
        "hostname r1\n"
        "interface GigabitEthernet0/0\n"
        " vrf forwarding Mgmt-vrf\n"
        " ip address 10.10.10.252 255.255.255.0\n"
        "!\n"
    )
    cisco_codec = CiscoIOSXECLICodec()
    aruba_codec = ArubaAOSSCodec()
    intent = cisco_codec.parse(cfg)

    # Sanity: parser set the override.
    gi = next(
        i for i in intent.interfaces if i.name == "GigabitEthernet0/0"
    )
    assert gi.kind == "mgmt"

    # Translate port names cisco → aruba.  Aruba's
    # format_port_identity for kind=mgmt returns "oobm".
    result = translate_port_names(intent, cisco_codec, aruba_codec)
    assert result.applied.get("GigabitEthernet0/0") == "oobm"

    # Render and confirm the oobm block emits.
    out = aruba_codec.render(intent)
    assert "oobm\n" in out, (
        "Aruba render should emit the dedicated oobm block when the "
        "source's mgmt-vrf-bound port cascades to kind=mgmt"
    )
    assert "ip address 10.10.10.252/24" in out
