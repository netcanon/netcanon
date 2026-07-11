"""audit 276eaeb T0-1 — multi-address interfaces walk ``secondary-ip`` by
CARDINALITY, not the ``is_secondary`` flag.

The walker used to yield ``/interfaces/interface/ipv{4,6}/address/secondary-ip``
only when an address carried ``is_secondary=True``.  But:

* IPv6 has no ``secondary`` keyword at all, so ``is_secondary`` is structurally
  never set on a v6 address; and
* IPv4 sources that don't model a primary/secondary distinction (Junos /
  OPNsense parse) leave ``is_secondary`` False on *every* address.

So a genuinely multi-address interface from such a source emitted NO
``secondary-ip`` xpath, ``classify()`` was never invoked, and a single-address
target codec (FortiGate / OPNsense — which render only the first address and
silently drop the rest) reported ``severity: ok`` while a whole subnet's
reachability vanished.

The fix walks ``secondary-ip`` for every address beyond the first (cardinality
> 1), regardless of the flag.  This guard pins that: the flagless multi-address
case must emit the xpath, a single address must not, and the loss must surface
end-to-end on a dropping codec.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalVlan,
)
from netcanon.migration.canonical.xpath_walker import _walk_canonical
from netcanon.migration.codecs import (  # noqa: F401  (register codecs)
    cisco_iosxe_cli,
    fortigate_cli,
    opnsense,
)
from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_validate import validate_against

pytestmark = pytest.mark.unit

_V4_SEC = "/interfaces/interface/ipv4/address/secondary-ip"
_V6_SEC = "/interfaces/interface/ipv6/address/secondary-ip"


def _intent(v4: list[CanonicalIPv4Address], v6: list[CanonicalIPv6Address]):
    return CanonicalIntent(
        hostname="r1",
        interfaces=[CanonicalInterface(
            name="GigabitEthernet0/1", default_name="GigabitEthernet0/1",
            ipv4_addresses=v4, ipv6_addresses=v6,
        )],
    )


def _v4(ip: str, *, sec: bool = False) -> CanonicalIPv4Address:
    return CanonicalIPv4Address(ip=ip, prefix_length=24, is_secondary=sec)


def _v6(ip: str, *, sec: bool = False) -> CanonicalIPv6Address:
    return CanonicalIPv6Address(ip=ip, prefix_length=64, is_secondary=sec)


class TestCardinalityDiscriminator:
    """``_walk_canonical`` emits ``secondary-ip`` from address count alone."""

    def test_flagless_multi_ipv4_yields_secondary(self):
        """The core T0-1 bug shape: two IPv4 addresses, NEITHER flagged
        is_secondary, must still emit the secondary-ip xpath."""
        paths = set(_walk_canonical(_intent([_v4("10.0.0.1"), _v4("10.0.9.1")], [])))
        assert _V4_SEC in paths

    def test_flagless_multi_ipv6_yields_secondary(self):
        """IPv6 can never set is_secondary, so cardinality is the ONLY
        signal — two v6 addresses must emit the secondary-ip xpath."""
        paths = set(_walk_canonical(
            _intent([], [_v6("2001:db8::1"), _v6("2001:db8:9::1")])
        ))
        assert _V6_SEC in paths

    def test_single_address_does_not_yield_secondary(self):
        """No false positive: one address per family emits no secondary-ip
        (else single-address codecs would be wrongly flagged lossy)."""
        paths = set(_walk_canonical(_intent([_v4("10.0.0.1")], [_v6("2001:db8::1")])))
        assert _V4_SEC not in paths
        assert _V6_SEC not in paths

    def test_explicit_single_secondary_still_yields(self):
        """Backward-compat: the original flag-based trigger still fires for
        a lone is_secondary=True address (cisco/arista classic secondary)."""
        paths = set(_walk_canonical(
            _intent([_v4("10.0.0.1", sec=True)], [])
        ))
        assert _V4_SEC in paths


_VLAN_V4_SEC = "/vlans/vlan/ipv4/address/secondary-ip"


class TestVlanMountCardinalityDiscriminator:
    """MTX-5 (2026-07-03 review): the VLAN/SVI-mount walk must use the same
    cardinality discriminator as the interface-mount twin — a multi-address
    SVI whose extra addresses are flagless (is_secondary False) previously
    walked only ``.../ip`` and rode classify() to a silent ``supported``."""

    @staticmethod
    def _vlan_intent(v4: list[CanonicalIPv4Address]) -> CanonicalIntent:
        return CanonicalIntent(
            hostname="r1",
            vlans=[CanonicalVlan(id=10, name="SVI", ipv4_addresses=v4)],
        )

    def test_flagless_multi_svi_ipv4_yields_secondary(self):
        paths = set(_walk_canonical(
            self._vlan_intent([_v4("10.0.10.1"), _v4("10.0.99.1")])
        ))
        assert _VLAN_V4_SEC in paths

    def test_single_svi_address_does_not_yield_secondary(self):
        paths = set(_walk_canonical(self._vlan_intent([_v4("10.0.10.1")])))
        assert _VLAN_V4_SEC not in paths

    def test_explicit_flagged_svi_secondary_still_yields(self):
        paths = set(_walk_canonical(
            self._vlan_intent([_v4("10.0.10.1", sec=True)])
        ))
        assert _VLAN_V4_SEC in paths


class TestEndToEndLossSurfaces:
    """The flagless multi-address loss surfaces in the live validation
    report on a single-address target codec (was a silent ``ok``)."""

    @pytest.mark.parametrize(
        "target,expect_v4_unsup",
        [("opnsense", True), ("fortigate_cli", False)],
    )
    def test_flagless_multiaddress_blocks_on_single_address_codec(
        self, target, expect_v4_unsup,
    ):
        tree = _intent(
            [_v4("10.0.0.1"), _v4("10.0.9.1")],
            [_v6("2001:db8::1"), _v6("2001:db8:9::1")],
        )
        report = validate_against(
            tree, get_codec(target), source=get_codec("cisco_iosxe_cli"),
        )
        unsup = {u.path for u in report.unsupported_paths}
        # fortigate_cli graduated the interface-mount v4 secondary-ip
        # (promotion #3 — `config secondaryip`), so its v4 secondaries now
        # round-trip; the v6 twin still drops, so the report stays
        # incompatible via the v6 loss.  opnsense still drops both.
        assert (_V4_SEC in unsup) is expect_v4_unsup
        assert _V6_SEC in unsup
        assert report.compatible is False
