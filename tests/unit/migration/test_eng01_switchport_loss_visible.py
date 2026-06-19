"""ENG-01 regression: L2 switchport-membership loss must be VISIBLE.

A switch → firewall/router migration that drops per-port VLAN membership
must surface that loss as an ``unsupported`` path in the validation
report — not silently classify ``severity: ok``.

Before this fix the L3-only target codecs (FortiGate, OPNsense, IOS-XR,
RouterOS, VyOS) declared *none* of the switchport xpaths, so
``CapabilityMatrix.classify`` defaulted them to ``supported`` and a
dropped trunk/access membership shipped with a green banner — reproduced
live in the 2026-06 blind audit (finding ENG-01).  Each of those targets
now declares the switchport surface ``unsupported`` (it has no Cisco-style
access/trunk port model), so the walker-yielded loss is reported.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli.codec import CiscoIOSXECLICodec
from netcanon.migration.codecs.cisco_iosxr.codec import CiscoIOSXRCodec
from netcanon.migration.codecs.fortigate_cli.codec import FortiGateCLICodec
from netcanon.migration.codecs.mikrotik_routeros.codec import MikroTikRouterOSCodec
from netcanon.migration.codecs.opnsense.codec import OPNsenseCodec
from netcanon.migration.codecs.vyos.codec import VyOSCodec
from netcanon.services.migration_validate import validate_against

pytestmark = pytest.mark.unit

# A Cisco access switch: one access port (VLAN 10) + one trunk port
# (VLANs 10,20).  Explicit ``switchport mode`` lines so the parse is
# unambiguous.
_SWITCH_CONFIG = """hostname access-sw-01
!
vlan 10
 name DATA
!
vlan 20
 name VOICE
!
interface GigabitEthernet1/0/1
 description Server-A
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet1/0/2
 description Uplink
 switchport mode trunk
 switchport trunk allowed vlan 10,20
!
"""

# The per-port L2 surface the switch config carries (and the walker
# therefore yields) — every one must land in ``unsupported`` on an
# L3-only target, not be silently blessed as supported.
_DROPPED_SWITCHPORT_XPATHS = {
    "/interfaces/interface/switchport-mode",
    "/interfaces/interface/access-vlan",
    "/interfaces/interface/trunk-allowed-vlans",
}

# Targets with no Cisco-style L2 switchport model — they drop the
# membership on render, so the matrix must declare it unsupported.
_L3_ONLY_TARGETS = [
    FortiGateCLICodec,
    OPNsenseCodec,
    CiscoIOSXRCodec,
    MikroTikRouterOSCodec,
    VyOSCodec,
]


@pytest.mark.parametrize(
    "target_cls", _L3_ONLY_TARGETS, ids=lambda c: c.__name__
)
def test_switchport_loss_surfaces_as_unsupported(target_cls):
    source = CiscoIOSXECLICodec()
    tree = source.parse(_SWITCH_CONFIG)
    # Sanity: the source genuinely parsed the L2 membership the audit
    # showed being silently dropped.
    g1 = next(i for i in tree.interfaces if i.name == "GigabitEthernet1/0/1")
    g2 = next(i for i in tree.interfaces if i.name == "GigabitEthernet1/0/2")
    assert g1.switchport_mode == "access" and g1.access_vlan == 10
    assert g2.switchport_mode == "trunk" and g2.trunk_allowed_vlans == [10, 20]

    report = validate_against(tree, target_cls(), source=source)
    unsupported = {u.path for u in report.unsupported_paths}

    missing = _DROPPED_SWITCHPORT_XPATHS - unsupported
    assert not missing, (
        f"{target_cls.__name__}: switchport loss NOT surfaced — these dropped "
        f"L2 paths classified as supported instead of unsupported: {sorted(missing)}"
    )
    # Any unsupported path forces a block-severity, incompatible report.
    assert report.severity == "block"
    assert report.compatible is False
