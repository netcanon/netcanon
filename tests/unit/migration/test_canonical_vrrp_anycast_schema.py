"""
Unit tests for the v0.2.0 Wave A schema additions:

* :class:`CanonicalVRRPGroup` — new classic FHRP redundancy primitive
* :attr:`CanonicalInterface.vrrp_groups` list
* :attr:`CanonicalIPv4Address.virtual_gateway_address` /
  ``virtual_gateway_mac`` / ``is_secondary``
* :attr:`CanonicalIPv6Address.virtual_gateway_address` /
  ``virtual_gateway_mac`` / ``is_secondary``
* :attr:`CanonicalStaticRoute.vrf`
* :attr:`CanonicalIntent.anycast_gateway_mac`

These tests pin the schema shape so subsequent Wave B (VRRP wire-up
per codec) and Wave C (anycast wire-up per codec) PRs can rely on
the defaults + validation behavior.

See ``docs/v0.2.0-planning/`` for the full design rationale.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalStaticRoute,
    CanonicalVRRPGroup,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# CanonicalVRRPGroup — new type
# ---------------------------------------------------------------------------


class TestCanonicalVRRPGroupDefaults:
    """Construction with only the required ``group_id`` field populates
    operator-natural defaults so per-codec parse paths only have to set
    the fields they actually saw in the source."""

    def test_minimal_construction(self):
        g = CanonicalVRRPGroup(group_id=10)
        assert g.group_id == 10
        assert g.mode == "vrrp"
        assert g.virtual_ips == []
        assert g.virtual_ipv6s == []
        assert g.virtual_mac == ""
        assert g.priority == 100
        assert g.preempt is True
        assert g.advertisement_interval == 1
        assert g.authentication == ""
        assert g.track_interfaces == []
        assert g.description == ""

    def test_full_construction(self):
        g = CanonicalVRRPGroup(
            group_id=42,
            mode="hsrp",
            virtual_ips=["192.168.1.254", "192.168.1.253"],
            virtual_ipv6s=["fe80::1"],
            virtual_mac="00:1c:73:00:dc:01",
            priority=110,
            preempt=False,
            advertisement_interval=3,
            authentication="md5:abcd1234",
            track_interfaces=["Ethernet1", "Ethernet2"],
            description="primary HA pair",
        )
        assert g.mode == "hsrp"
        assert len(g.virtual_ips) == 2
        assert g.priority == 110
        assert g.preempt is False

    def test_mode_accepts_carp(self):
        """OPNsense BSD CARP uses ``mode='carp'`` — semantically related
        but wire-protocol-distinct from IETF VRRP."""
        g = CanonicalVRRPGroup(group_id=20, mode="carp")
        assert g.mode == "carp"

    def test_mode_is_free_string(self):
        """``mode`` is intentionally a string literal, not an enum, so
        future codecs can extend without a schema change."""
        g = CanonicalVRRPGroup(group_id=20, mode="future-protocol")
        assert g.mode == "future-protocol"


class TestCanonicalVRRPGroupValidation:
    """Schema enforces VRID and priority ranges per RFC 5798."""

    def test_group_id_lower_bound(self):
        with pytest.raises(ValidationError):
            CanonicalVRRPGroup(group_id=0)

    def test_group_id_upper_bound(self):
        with pytest.raises(ValidationError):
            CanonicalVRRPGroup(group_id=256)

    def test_group_id_boundary_ok(self):
        CanonicalVRRPGroup(group_id=1)
        CanonicalVRRPGroup(group_id=255)

    def test_priority_lower_bound(self):
        with pytest.raises(ValidationError):
            CanonicalVRRPGroup(group_id=10, priority=0)

    def test_priority_upper_bound(self):
        """255 is the reserved "address owner" value per RFC 5798 — we
        cap at 254 to keep the canonical model declaratively safe."""
        with pytest.raises(ValidationError):
            CanonicalVRRPGroup(group_id=10, priority=255)

    def test_priority_boundary_ok(self):
        CanonicalVRRPGroup(group_id=10, priority=1)
        CanonicalVRRPGroup(group_id=10, priority=254)


# ---------------------------------------------------------------------------
# CanonicalInterface.vrrp_groups — new field
# ---------------------------------------------------------------------------


class TestVRRPGroupsOnInterface:
    def test_default_is_empty_list(self):
        iface = CanonicalInterface(name="Vlan10")
        assert iface.vrrp_groups == []

    def test_multiple_groups_per_interface(self):
        """IOS-XE / Junos / Aruba all accept multiple groups per
        interface (dual-stack v4+v6 designs or multi-tenant SVIs)."""
        iface = CanonicalInterface(
            name="Vlan10",
            vrrp_groups=[
                CanonicalVRRPGroup(group_id=10, virtual_ips=["10.0.10.254"]),
                CanonicalVRRPGroup(group_id=20, virtual_ips=["10.0.20.254"]),
            ],
        )
        assert len(iface.vrrp_groups) == 2
        assert iface.vrrp_groups[0].group_id == 10
        assert iface.vrrp_groups[1].group_id == 20

    def test_model_dump_round_trip(self):
        """The schema round-trips through dict (used by the JSON jobs
        store + the migrate-page POST body)."""
        original = CanonicalInterface(
            name="Vlan10",
            vrrp_groups=[
                CanonicalVRRPGroup(
                    group_id=10,
                    virtual_ips=["10.0.10.254"],
                    priority=110,
                ),
            ],
        )
        dumped = original.model_dump()
        restored = CanonicalInterface.model_validate(dumped)
        assert restored == original


# ---------------------------------------------------------------------------
# CanonicalIPv4Address / IPv6Address — new fields for anycast + secondary
# ---------------------------------------------------------------------------


class TestIPv4AnycastFields:
    def test_defaults(self):
        a = CanonicalIPv4Address(ip="10.1.1.1", prefix_length=24)
        assert a.is_secondary is False
        assert a.virtual_gateway_address == ""
        assert a.virtual_gateway_mac == ""

    def test_set_anycast_companion(self):
        """Junos one-line source: ``family inet address X
        virtual-gateway-address Y`` produces both fields on the same
        record."""
        a = CanonicalIPv4Address(
            ip="10.221.0.5",
            prefix_length=16,
            virtual_gateway_address="10.221.0.1",
            virtual_gateway_mac="02:00:21:00:00:01",
        )
        assert a.virtual_gateway_address == "10.221.0.1"
        assert a.virtual_gateway_mac == "02:00:21:00:00:01"

    def test_secondary_flag(self):
        """EOS ``ip address virtual X/Y secondary`` and Cisco
        ``ip address X/Y secondary`` both surface as ``is_secondary``."""
        a = CanonicalIPv4Address(
            ip="10.1.100.1", prefix_length=24, is_secondary=True,
        )
        assert a.is_secondary is True


class TestIPv6AnycastFields:
    def test_defaults(self):
        a = CanonicalIPv6Address(ip="2001:db8::1", prefix_length=64)
        assert a.is_secondary is False
        assert a.virtual_gateway_address == ""
        assert a.virtual_gateway_mac == ""
        assert a.scope == "global"

    def test_set_anycast_companion(self):
        a = CanonicalIPv6Address(
            ip="fd20:2021::5",
            prefix_length=64,
            virtual_gateway_address="fd20:2021::1",
            virtual_gateway_mac="02:00:21:06:00:01",
        )
        assert a.virtual_gateway_address == "fd20:2021::1"
        assert a.virtual_gateway_mac == "02:00:21:06:00:01"

    def test_link_local_scope_with_anycast(self):
        """Link-local + anycast is unusual but legal — the canonical
        model preserves both signals."""
        a = CanonicalIPv6Address(
            ip="fe80:2021::1",
            prefix_length=64,
            scope="link-local",
            virtual_gateway_address="fe80:2021::1",
        )
        assert a.scope == "link-local"
        assert a.virtual_gateway_address == "fe80:2021::1"


# ---------------------------------------------------------------------------
# CanonicalStaticRoute.vrf — new field
# ---------------------------------------------------------------------------


class TestStaticRouteVrfField:
    def test_default_is_global(self):
        """Empty string = global routing table (the common case)."""
        r = CanonicalStaticRoute(destination="0.0.0.0/0", gateway="10.0.0.1")
        assert r.vrf == ""

    def test_per_vrf_route(self):
        """Cisco ``ip route vrf <NAME> ...`` populates this field."""
        r = CanonicalStaticRoute(
            destination="172.16.0.0/16",
            gateway="10.0.0.2",
            vrf="CUSTOMER-A",
        )
        assert r.vrf == "CUSTOMER-A"


# ---------------------------------------------------------------------------
# CanonicalIntent.anycast_gateway_mac — new field
# ---------------------------------------------------------------------------


class TestAnycastGatewayMacOnIntent:
    def test_default_empty(self):
        intent = CanonicalIntent()
        assert intent.anycast_gateway_mac == ""

    def test_set_system_mac(self):
        """Arista ``ip virtual-router mac-address`` / NX-OS ``fabric
        forwarding anycast-gateway-mac`` populate this."""
        intent = CanonicalIntent(anycast_gateway_mac="00:1c:73:00:dc:01")
        assert intent.anycast_gateway_mac == "00:1c:73:00:dc:01"


# ---------------------------------------------------------------------------
# Capability-matrix ship-before-wire declarations
# ---------------------------------------------------------------------------


class TestShipBeforeWireUnsupportedDeclarations:
    """Wave A ship-before-wire invariant — but now with per-codec
    wire-up tracking.

    On Wave A, every codec declared the new paths as ``unsupported``
    (the original ship-before-wire stance — "the schema exists,
    nothing renders it yet, so report it loud").

    On Waves B + C, each codec progressively GRADUATES individual
    paths from ``unsupported`` to either ``supported`` (full parse +
    render wire-up) or ``lossy`` (parses but emits a review comment
    on cross-vendor render — typical pattern when the codec has the
    grammar but the cross-vendor mapping is partial).

    This test enforces the invariant in BOTH directions:

    * For paths a codec has NOT yet graduated (still in
      ``_WIRED_UP_PATHS`` set or its own ``_WIRED_UP_BY_CODEC`` entry
      missing), the path MUST be in ``unsupported`` — guards against
      silent removal that would make the migrate-page banner stop
      firing for the surface.
    * For paths a codec HAS graduated (listed in
      ``_WIRED_UP_BY_CODEC[codec]``), the path MUST NOT be in
      ``unsupported`` — guards against the matrix forgetting to flip
      its declaration.

    The two-sided invariant means any codec that lists a path in
    ``_WIRED_UP_BY_CODEC`` but forgets to remove it from
    ``unsupported`` (or vice versa) gets a loud test failure.

    See ``docs/v0.2.0-planning/`` for the per-wave plan + cross-task
    synthesis explaining the wire-up sequencing.
    """

    # The five paths Wave A declared as unsupported across every
    # codec.  Per-IP ``virtual-gateway-mac`` xpaths are NOT in this
    # list — they're a vendor-specific surface (Junos per-unit MAC
    # override) and only codecs with that grammar declare them
    # (Junos supported, Arista lossy).  See per-codec capability
    # matrix for the per-MAC declarations.
    _NEW_PATHS = (
        "/interfaces/interface/vrrp-groups/group",
        "/interfaces/interface/ipv4/address/virtual-gateway-address",
        "/interfaces/interface/ipv6/address/virtual-gateway-address",
        "/anycast-gateway-mac",
        "/routing/static-route/vrf",
    )

    # Per-codec wire-up state.  Each codec's set lists the paths it
    # has GRADUATED from ``unsupported`` — they now appear under
    # ``supported`` or ``lossy`` instead.  Paths NOT listed for a
    # codec must remain ``unsupported``.
    _WIRED_UP_BY_CODEC: dict[str, set[str]] = {
        # Wave B + C — see commit feat(cisco_iosxe_cli): wire VRRP
        # groups + SD-Access anycast-gateway.  IPv6 anycast remains
        # ``unsupported`` (no fixture coverage); per-VRF static
        # routes remain ``unsupported`` (separate scope).
        "cisco_iosxe_cli": {
            "/interfaces/interface/vrrp-groups/group",
            "/interfaces/interface/ipv4/address/virtual-gateway-address",
            "/anycast-gateway-mac",
        },
        # NETCONF stub — every path still ``unsupported`` (the
        # codec's matrix declares every canonical surface unsupported
        # per its Phase-0.5 stub policy).
        "cisco_iosxe": set(),
        # Wave B + C — see commit feat(junos): wire VRRP groups +
        # anycast-gateway.  Per-VRF static route flipped to ``lossy``
        # (parses but routing-instances dispatcher doesn't yet
        # harvest per-VRF statics; separate scope).  Anycast MAC stays
        # ``unsupported`` (Junos uses per-unit MAC, not chassis-wide).
        "juniper_junos": {
            "/interfaces/interface/vrrp-groups/group",
            "/interfaces/interface/ipv4/address/virtual-gateway-address",
            "/interfaces/interface/ipv6/address/virtual-gateway-address",
            "/routing/static-route/vrf",
        },
        # Wave B + C — see commit feat(arista_eos): wire VRRP +
        # VARP.  Per-IP virtual-gateway-mac is ``lossy`` (Arista
        # only has chassis-wide ``ip virtual-router mac-address``;
        # per-IP override doesn't exist).
        "arista_eos": {
            "/interfaces/interface/vrrp-groups/group",
            "/interfaces/interface/ipv4/address/virtual-gateway-address",
            "/interfaces/interface/ipv6/address/virtual-gateway-address",
            "/anycast-gateway-mac",
        },
        # Wave B — see commit feat(aruba_aoss): wire VRRP groups.
        # AOS-S has no native anycast grammar; those paths stay
        # ``unsupported``.
        "aruba_aoss": {
            "/interfaces/interface/vrrp-groups/group",
        },
        # Wave B — see commit feat(fortigate_cli): wire VRRP groups.
        "fortigate_cli": {
            "/interfaces/interface/vrrp-groups/group",
        },
        # Wave B — see commit feat(mikrotik_routeros): wire VRRP.
        "mikrotik_routeros": {
            "/interfaces/interface/vrrp-groups/group",
        },
        # Wave B (CARP variant) — see commit feat(opnsense): wire
        # CARP groups with mode="carp" discriminator.
        "opnsense": {
            "/interfaces/interface/vrrp-groups/group",
        },
    }

    @pytest.mark.parametrize(
        "codec_name",
        [
            "cisco_iosxe_cli",
            "cisco_iosxe",
            "juniper_junos",
            "arista_eos",
            "aruba_aoss",
            "fortigate_cli",
            "mikrotik_routeros",
            "opnsense",
        ],
    )
    def test_codec_declares_new_paths_unsupported(self, codec_name):
        # Side-effect import to populate the registry — uses the same
        # mechanism as test_real_captures.py.
        from netcanon.migration.codecs import (  # noqa: F401
            arista_eos,
            aruba_aoss,
            cisco_iosxe,
            cisco_iosxe_cli,
            fortigate_cli,
            juniper_junos,
            mikrotik_routeros,
            opnsense,
        )
        from netcanon.migration.codecs.registry import get_codec

        codec = get_codec(codec_name)
        unsupported = {u.path for u in codec.capabilities.unsupported}
        supported = set(codec.capabilities.supported)
        lossy = {p.path for p in codec.capabilities.lossy}
        wired_up = self._WIRED_UP_BY_CODEC.get(codec_name, set())

        for path in self._NEW_PATHS:
            if path in wired_up:
                # Codec has graduated this path from ``unsupported``
                # — it must now appear under ``supported`` OR
                # ``lossy`` (codec's choice based on the cross-vendor
                # translation completeness).  Must NOT be in
                # ``unsupported`` any more.
                assert path in supported or path in lossy, (
                    f"{codec_name} graduated {path} from "
                    f"unsupported (per _WIRED_UP_BY_CODEC) but the "
                    f"capability matrix does not list it under "
                    f"supported or lossy.  Either flip the matrix "
                    f"declaration or remove the path from "
                    f"_WIRED_UP_BY_CODEC."
                )
                assert path not in unsupported, (
                    f"{codec_name} lists {path} as both "
                    f"{'supported' if path in supported else 'lossy'}"
                    f" and unsupported in the capability matrix.  "
                    f"Remove the duplicate ``unsupported`` entry."
                )
                continue
            # Not yet wired up — must still be ``unsupported``.
            assert path in unsupported, (
                f"{codec_name} missing unsupported declaration for "
                f"{path}.  Ship-before-wire requires un-graduated "
                f"paths to remain ``unsupported`` so the migrate-"
                f"page banner fires for the dropped surface.  Either "
                f"add the UnsupportedPath declaration to the codec "
                f"matrix, OR if the codec has been wired up, add "
                f"{path!r} to "
                f"_WIRED_UP_BY_CODEC[{codec_name!r}]."
            )
