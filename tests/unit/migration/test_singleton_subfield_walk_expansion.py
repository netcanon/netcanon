"""PR-2c (audit e5b77d7) walk-expansion guard for the three singleton leaves.

These were the LAST three ``KNOWN_GAP`` exemptions in
``test_walker_completeness.py`` -- the tail of the silent capability-loss class
that PR-2a (SNMPv3) and PR-2b (VRRP/FHRP) began closing:

* ``/routing/static-route/gateway``            -- the next-hop
* ``/routing-instances/instance/instance-type``-- mac-vrf vs vrf discriminator
* ``/interfaces/interface/ipv6/address/scope`` -- link-local vs global

The anchors were walked but these sub-paths were not, so ``classify()``
fail-opened any codec that dropped or downgraded them to ``supported`` -- a
silent loss reported ``severity: ok`` (a dropped default-route next-hop, a
mac-vrf flattened to a plain vrf, a link-local address that loses its scope).

PR-2c walks them and adds the per-codec dispositions, verified by a
render -> parse round-trip probe (``supported`` only where the value actually
survives the round-trip; ``lossy`` where the anchor renders but the field is
dropped/downgraded; ``unsupported`` where the codec renders no instance of the
anchor at all).  This guard pins BOTH halves so a regression -- un-walking a
path, or dropping a declaration so ``classify()`` silently fail-opens again --
turns RED.  With this surface closed the ``KNOWN_GAP`` exemption set is empty;
the walk-expansion is complete.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.xpath_walker import _walk_canonical
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from tests.unit.migration.test_registry_capability_honesty import _maximal_intent

pytestmark = pytest.mark.unit

_SR = "/routing/static-route/"
_RI = "/routing-instances/instance/"
_V6 = "/interfaces/interface/ipv6/address/"

_SUBPATHS = [_SR + "gateway", _RI + "instance-type", _V6 + "scope"]

#: Verified disposition matrix (PR-2c).  A codec ABSENT from a leaf's dict
#: relies on the classify() supported default BECAUSE the value round-trips
#: (render -> parse recovers it -- verified by the round-trip probe); a codec
#: LISTED here must carry an explicit lossy/unsupported declaration or the
#: silent loss returns.  ``lossy`` = the anchor renders but the field is
#: dropped/downgraded; ``unsupported`` = the codec renders no instance of the
#: anchor at all.
_EXPECTED: dict[str, dict[str, str]] = {
    # Gateway: every codec renders `ip route <dest> <next-hop>` faithfully
    # except OPNsense (renders no <staticroutes> -> lossy, parity with the
    # route anchor) and the NETCONF stub (renders no static routes -> unsupp).
    _SR + "gateway": {
        "opnsense": "lossy",
        "cisco_iosxe": "unsupported",
    },
    # instance-type: only Arista (mac-vrf/vrf branch) and Junos (explicit
    # `instance-type`) round-trip the discriminator.  The CLI VRF renderers
    # emit a plain `vrf <name>` (lossy); the codecs with no VRF model at all
    # are unsupported.
    _RI + "instance-type": (
        dict.fromkeys(
            ("aruba_aoscx", "cisco_iosxe_cli", "cisco_iosxr", "cisco_nxos", "vyos"),
            "lossy",
        )
        | dict.fromkeys(
            ("aruba_aoss", "cisco_iosxe", "fortigate_cli", "mikrotik_routeros",
             "opnsense"),
            "unsupported",
        )
    ),
    # scope: codecs that re-infer link-local from the fe80::/10 prefix on parse
    # round-trip the scope and stay supported (cisco_iosxe_cli, aruba_aoscx, and
    # now VyOS via the shared ``_is_link_local_v6`` helper — promotion #10);
    # FortiGate still hardcodes scope=global on parse and the NETCONF stub emits
    # no scope -> lossy (the IPv6 address itself still renders, so this is a
    # downgrade, not unsupported).
    _V6 + "scope": dict.fromkeys(
        ("cisco_iosxe", "fortigate_cli"), "lossy",
    ),
}


@pytest.mark.parametrize("path", _SUBPATHS)
def test_subpath_is_walked(path: str) -> None:
    """The maximal intent populates a gateway route, a routing-instance, and an
    IPv6 address, so every singleton sub-path must be emitted by the walker
    (else classify() never sees it = silent loss)."""
    walked = set(_walk_canonical(_maximal_intent()))
    assert path in walked, f"{path} is no longer walked -- PR-2c regressed"


@pytest.mark.parametrize("path", _SUBPATHS)
def test_every_codec_declares_or_faithfully_supports(path: str) -> None:
    """Every codec classifies each singleton sub-path per the verified matrix;
    a codec that drops or downgrades the field must NOT silently rely on the
    supported default (that is exactly the silent loss the walk-expansion
    closes)."""
    for name in list_public_codecs():
        got = get_codec(name).capabilities.classify(path)
        exp = _EXPECTED[path].get(name, "supported")
        assert got == exp, (
            f"{name} classifies {path} as {got!r}, expected {exp!r} "
            f"(PR-2c disposition regression)"
        )
