"""Regression-guard: the cisco_iosxe_cli probe must DEFER (return None)
when a config carries NX-OS- or AOS-CX-exclusive markers, so a
bannerless containerlab / golden-config capture does not tie IOS-XE at
confidence 90 and lose the alphabetical tie-break (mis-detecting NX-OS
or AOS-CX as IOS-XE).

Same hazard + fix pattern as the IOS-XR deferral (2026-06 review #21 /
the #64 XR-vs-XE fix): the generic ``no shutdown`` / ``interface
loopback`` / ``switchport`` IOS-shape markers ALSO appear in NX-OS and
AOS-CX, so without a deferral the IOS-XE structural probe ties the real
vendor at 90.  The deferral keys ONLY on markers that never appear in
genuine IOS-XE running-config, so it cannot regress IOS-XE detection
(guarded by ``test_plain_iosxe_still_detects`` below).

See also:
- netcanon/migration/codecs/cisco_iosxe_cli/codec.py — the deferral block
- tests/fixtures/real/cisco_nxos/networklessons_clab_vxlan_mcast_leaf2_nxos.cfg
  — the bannerless NX-OS capture this unblocks
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.cisco_iosxe_cli import CiscoIOSXECLICodec

pytestmark = pytest.mark.unit


_NXOS_NVE = """\
hostname LEAF2
feature nv overlay
feature vn-segment-vlan-based
vlan 10
  vn-segment 10010
interface nve1
  no shutdown
  source-interface loopback0
  member vni 10010
"""

_AOSCX_LAG_VRF = """\
hostname CX-SPINE
interface lag 1
interface 1/1/1
  no shutdown
  vrf attach RED
"""

_PLAIN_IOSXE = """\
hostname R1
!
interface GigabitEthernet0/0
 ip address 10.0.0.1 255.255.255.0
 no shutdown
!
interface Loopback0
 ip address 10.255.0.1 255.255.255.255
!
"""


def test_defers_on_nxos_nve_markers() -> None:
    # feature nv overlay / feature vn-segment-vlan-based / interface nve1
    # / vn-segment are all NX-OS-exclusive — IOS-XE has no ``feature``
    # command nor an ``nve`` interface.
    assert CiscoIOSXECLICodec.probe(_NXOS_NVE) is None


def test_defers_on_aoscx_lag_vrf_markers() -> None:
    # interface lag <N> (IOS-XE uses Port-channel) + the per-interface
    # ``vrf attach`` (IOS-XE uses ``vrf forwarding``) are AOS-CX-exclusive.
    assert CiscoIOSXECLICodec.probe(_AOSCX_LAG_VRF) is None


def test_plain_iosxe_still_detects() -> None:
    # No NX-OS / AOS-CX marker present — the deferral must NOT fire, and a
    # genuine IOS-XE running-config still probes at medium-or-better.
    result = CiscoIOSXECLICodec.probe(_PLAIN_IOSXE)
    assert result is not None
    assert result[0] >= 70
