"""
``ArubaAOSCXCodec`` — bidirectional codec for Aruba AOS-CX
``show running-config`` text.

Targets the modern Aruba switch portfolio (6000 / 6100 / 6200 / 6300 /
6400 / 8100 / 8320 / 8325 / 8360 / 8400 / 9300 / CX-10000) on AOS-CX
10.x.  **Distinct vendor identity from ``aruba_aoss``** — AOS-CX is a
ground-up redesign (explicitly inspired by Arista EOS), NOT a successor
to the ProVision/AOS-S grammar; the two share nothing beyond the vendor
logo.  Use the ``aruba_aoss`` codec for legacy ArubaOS-Switch (16.x)
captures.

Module layout mirrors the ``cisco_nxos`` post-split shape:

* ``codec.py`` (this file) — the class with metadata / capabilities /
  probe / port-name delegates.  ``parse()`` / ``render()`` are one-line
  delegators to the sibling modules.
* ``parse.py`` — line-scan + per-stanza dispatch over AOS-CX text.
* ``render.py`` — canonical tree → AOS-CX running-config text.
* ``port_names.py`` — cross-vendor port-name bridge (the multi-token
  ``vlan N`` / ``lag N`` / ``1/1/1`` name shapes).

``iter_xpaths`` reuses ``_walk_canonical`` from
:mod:`netcanon.migration.codecs.cisco_iosxe_cli.codec` — AOS-CX
introduces no new canonical xpaths in Phase 1, so the shared walker
yields exactly the right set.

This codec landed in phases (Tier-1 first, mirroring the ``cisco_nxos``
cadence).  **Phase 1**: hostname, basic-L3 interfaces (description /
admin-state / mtu / IPv4 + IPv6 CIDR / ``vrf attach``), VLANs (id + name
+ description), top-level ``vrf`` declarations (name), and default-VRF
static routes.  **Phase 2**: the L2 switchport surface (``no routing`` +
``vlan access`` / ``vlan trunk native`` / ``vlan trunk allowed``) with
VLAN-centric port projection, LAGs (``interface lag N`` + per-port ``lag
N`` + ``lacp mode``), and local users (``user <name> group <group>
password ciphertext <blob>``).  **Phase 2b**: SNMP — v2c community,
``system-location`` / ``system-contact``, and ``snmpv3 user`` USM users
(``auth-pass`` / ``priv-pass`` ciphertext).  **Phase 3**: the
``active-gateway`` anycast surface (the VSX/EVPN distributed gateway —
``active-gateway ip <vip>`` mirrors into ``virtual_gateway_address`` +
``active-gateway ip mac <mac>`` -> ``anycast_gateway_mac``; reuses the
certified NX-OS DAG / IOS-XE SD-Access canonical surface).  **Phase 4**
(this commit): the L2 VXLAN VLAN↔VNI binding (``interface vxlan 1`` /
``source ip <X>`` / ``vni <VNI>`` / nested ``vlan <VLAN>`` ->
:class:`CanonicalVxlan`), and a real-capture corpus (the Apache-2.0
``aruba/aoscx-ansible-dcn-workflows`` reference fabric — VXLAN leaves +
active-gateway cores) wired into ``test_real_captures``.  ``certainty``
is now ``certified`` — the supported surface round-trips on the real
corpus (the active-gateway surface, synthetic-only through Phase 3, is
now exercised by the real arch4 core configs).  Still deferred: the
per-VLAN L2VNI RD/RT (``auto``-derived, no canonical home), symmetric-
IRB L3VNI (``vni N / vrf``), VSX, and VRRP.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, ClassVar

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import CanonicalIntent
from .._input_shape import detect_input_shape
from ..base import CodecBase
from ..registry import register
from . import port_names as _port_names
from .parse import parse_intent
from .render import render_intent


@register
class ArubaAOSCXCodec(CodecBase):
    """Bidirectional codec for Aruba AOS-CX ``show running-config`` output.

    Separate ``vendor_id=aruba_aoscx`` from ``aruba_aoss`` — its own
    vendor row in ``netcanon/migration/vendors/aruba_aoscx.yaml``.
    """

    name: ClassVar[str] = "aruba_aoscx"
    version_hint: ClassVar[str | None] = "10.x"
    input_format: ClassVar[str] = "cli-aoscx"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-config` from an Aruba AOS-CX "
        "switch (6000 / 8000 / 9300 / CX-10000 series).  AOS-CX is "
        "Aruba's modern NOS; its grammar is distinct from the legacy "
        "ArubaOS-Switch (use the `aruba_aoss` codec for AOS-S / ProVision "
        "captures)."
    )
    sample_input: ClassVar[str] = (
        "!\n"
        "!Version ArubaOS-CX Virtual.10.13.1000\n"
        "!export-password: default\n"
        "hostname Aruba-Leaf1\n"
        "!\n"
        "vrf RED\n"
        "vlan 1\n"
        "vlan 10\n"
        "    name PROD\n"
        "    description Production servers\n"
        "interface 1/1/1\n"
        "    no shutdown\n"
        "    mtu 9198\n"
        "    ip address 192.0.2.1/31\n"
        "interface vlan 10\n"
        "    no shutdown\n"
        "    vrf attach RED\n"
        "    ip address 10.10.10.1/24\n"
        "interface loopback 0\n"
        "    ip address 192.0.2.255/32\n"
        "ip route 0.0.0.0/0 192.0.2.2\n"
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="aruba_aoscx",
        vendor_id="aruba_aoscx",
        version_range="10.x",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[
            # System
            "/system/hostname",
            # Interfaces — name + basic L3 (Phase 1)
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",
            "/interfaces/interface/ipv6/address/prefix-length",
            "/interfaces/interface/config/vrf",
            # VLANs — id + name + description (Phase 1)
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/vlans/vlan/description",
            # Static routes (default VRF)
            "/routing/static-route",
            # VRF — name only (Phase 1)
            "/routing-instances/instance/name",
            # ── Phase 2: L2 switchport + VLAN port membership ──
            "/interfaces/interface/switchport-mode",
            "/interfaces/interface/access-vlan",
            "/interfaces/interface/trunk-allowed-vlans",
            "/interfaces/interface/trunk-native-vlan",
            "/interfaces/interface/lag-member-of",
            "/vlans/vlan/tagged-ports",
            "/vlans/vlan/untagged-ports",
            # ── Phase 2: LAGs (`interface lag N`) ──
            "/lags/lag/name",
            "/lags/lag/members",
            # /lags/lag/mode is LOSSY, not supported — see the lossy list
            # below (passive re-parses as static; audit bb47f21 T0-1).
            # ── Phase 2: local users (`user X group G password ciphertext`) ──
            "/local-users/user/name",
            "/local-users/user/role",
            "/local-users/user/hashed-password",
            # ── Phase 2b: SNMP (v2c community + v3 USM) ──
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/v3-user",
            # ── Phase 3: active-gateway anycast (VSX/EVPN distributed
            # gateway) — `active-gateway ip <vip>` mirrors into
            # virtual_gateway_address + `active-gateway ip mac <mac>`. ──
            "/interfaces/interface/ipv4/address/virtual-gateway-address",
            "/anycast-gateway-mac",
            # ── Phase 4: VXLAN L2 VLAN↔VNI binding (`interface vxlan 1`
            # / `vni <VNI>` / nested `vlan <VLAN>`). ──
            "/vxlan-vnis/vni",
        ],
        lossy=[
            LossyPath(
                path="/lags/lag/mode",
                reason=(
                    "AOS-CX renders the LAG `lacp mode`, but a `passive` LACP "
                    "bundle re-parses as `static` -- the passive mode is not "
                    "preserved (audit bb47f21 T0-1, verified by round-trip "
                    "probe)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance/instance-type",
                reason=(
                    "Renders the VRF anchor as a bare `vrf <name>` stanza with no "
                    "mac-vrf syntax, so the mac-vrf vs vrf instance-type "
                    "discriminator downgrades to vrf on render. Declared lossy so "
                    "validate_against surfaces the loss instead of reporting "
                    "severity:ok (audit e5b77d7, PR-2c)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/ip",
                reason=(
                    "Renders VLAN SVI / management L3 only from a sibling "
                    "interface stanza; an L3 address carried on the VLAN record "
                    "itself (the Junos irb / Aruba SVI-on-VLAN shape, folded onto "
                    "CanonicalVlan.ipv4_addresses) is dropped on render because "
                    "this codec does not synthesize an SVI from the VLAN record. "
                    "Declared lossy so validate_against surfaces the loss instead "
                    "of reporting severity:ok (blind-audit 3ec11f3 T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/secondary-ip",
                reason=(
                    "VLAN-SVI mount, subsumed by the whole-SVI-L3 drop (see "
                    "/vlans/vlan/ipv4/address/ip): this codec renders no SVI "
                    "from the VLAN record, so a secondary IP carried there is "
                    "dropped with it. Declared lossy so validate_against "
                    "surfaces the loss (blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-address",
                reason=(
                    "VLAN-SVI mount, subsumed by the whole-SVI-L3 drop (see "
                    "/vlans/vlan/ipv4/address/ip): the anycast virtual-gateway "
                    "IP carried on the VLAN record drops with the unrendered "
                    "SVI. Declared lossy (blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-mac",
                reason=(
                    "VLAN-SVI mount, subsumed by the whole-SVI-L3 drop (see "
                    "/vlans/vlan/ipv4/address/ip): the anycast virtual-gateway "
                    "MAC carried on the VLAN record drops with the unrendered "
                    "SVI. Declared lossy (blind-audit f92e97a T0-2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
                reason=(
                    "Render emits the per-address active-gateway VIP "
                    "(`active-gateway ip <vip>`) and hoists the anycast MAC "
                    "to the switch-wide `active-gateway ip mac <mac>` "
                    "(canonical anycast_gateway_mac), but the per-address "
                    "virtual_gateway_mac is not emitted, so per-address MAC "
                    "granularity drops while the VIP + switch-wide MAC "
                    "survive (silent-loss guard, Bucket-C stage 3)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/tunnel-type",
                reason=(
                    "AOS-CX Phase 1 does not model generic GRE/IPsec tunnel "
                    "interfaces; a `Tunnel<N>` interface renders as a "
                    "generic interface with no tunnel encapsulation, so the "
                    "canonical tunnel_type drops while the interface name "
                    "survives (silent-loss guard, Bucket-C stage 3)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/engine-id",
                reason=(
                    "The SNMPv3 USM user round-trips but a per-user "
                    "engineID is not emitted on render (engineIDs are "
                    "device-assigned / global), so the canonical engine_id "
                    "drops (silent-loss guard, Bucket-C stage 2)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing/static-route/description",
                reason=(
                    "Render emits destination + next-hop only; the static-"
                    "route name / description is dropped (run3)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "AOS-CX declares no IANA ifType; the codec infers it "
                    "from the interface-name shape (`1/1/1` -> "
                    "ethernetCsmacd, `vlan N` -> l3ipvlan, `lag N` -> "
                    "ieee8023adLag, `loopback N` -> softwareLoopback, "
                    "`mgmt` -> ethernetCsmacd, `vxlan N` -> tunnel).  "
                    "Inference is best-effort and may not catch every "
                    "IANA type."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/system/raw-sections/version-banner",
                reason=(
                    "The `!Version ArubaOS-CX <release>` banner + the "
                    "`!export-password` / service footer lines (`ssh "
                    "server`, `https-server`, `clock`, `ntp`, "
                    "`spanning-tree`, `system interface-group`) are "
                    "discarded on parse and a synthesised banner is "
                    "emitted on render.  The parsed `source_version` is "
                    "metadata only; the operator must re-apply "
                    "management-plane services on the target device."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/local-users/user/privilege-level",
                reason=(
                    "AOS-CX uses a named `group` (administrators / "
                    "operators / auditors / custom) instead of a numeric "
                    "privilege.  The codec maps administrators -> 15 and "
                    "everything else -> 1, so cross-vendor renderers "
                    "expecting numeric privilege round-trip non-admin "
                    "groups as 1.  The named group round-trips losslessly "
                    "same-vendor.  The `password ciphertext` blob is "
                    "AES-encrypted with the device key (portable "
                    "same-device only); cross-vendor migration requires "
                    "re-keying on the target."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/auth-passphrase",
                reason=(
                    "AOS-CX renders SNMPv3 with SHA-1 auth and AES-128 priv "
                    "ONLY: a stronger source algorithm (SHA-224/256/384/512 "
                    "auth, or AES-192/256 / 3DES priv) is silently DOWNGRADED "
                    "to fit the target's grammar -- verify the resulting "
                    "security level is acceptable, this is a cryptographic "
                    "downgrade, not just a re-key.  The auth/priv keys are "
                    "also `ciphertext` blobs encrypted with the device key "
                    "(portable same-device only), so cross-vendor / cross-"
                    "device migration emits the blob verbatim and the "
                    "operator must RE-KEY the SNMPv3 user on the target (the "
                    "`plaintext` key form is normalised to `ciphertext` on "
                    "render)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/auth-protocol",
                reason=(
                    "AOS-CX renders SNMPv3 auth with SHA-1 only: a stronger "
                    "source auth algorithm (SHA-224/256/384/512) is silently "
                    "DOWNGRADED to SHA-1 on render -- a cryptographic "
                    "downgrade, not a re-key; verify the resulting security "
                    "level is acceptable."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/priv-protocol",
                reason=(
                    "AOS-CX renders SNMPv3 privacy with AES-128 / DES only: a "
                    "stronger source cipher (AES-192/256) is DOWNGRADED to "
                    "AES-128 and 3DES to DES on render -- a cryptographic "
                    "downgrade, verify the resulting security level."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/priv-passphrase",
                reason=(
                    "The SNMPv3 privacy key is a `ciphertext` blob encrypted "
                    "with the device key (portable same-device only); cross-"
                    "vendor / cross-device migration emits it verbatim and the "
                    "operator must RE-KEY the user on the target."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/group",
                reason=(
                    "AOS-CX `snmpv3 user` syntax carries no VACM group "
                    "binding; the user renders but the canonical group is "
                    "dropped on render."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vxlan-vnis/source-interface",
                reason=(
                    "AOS-CX states the VTEP source as an IPv4 *address* "
                    "(`interface vxlan 1 / source ip <X>`), not an interface "
                    "name like NX-OS / Arista (`source-interface loopbackN`). "
                    "The address is stored verbatim in the opaque "
                    "`source_interface` field and round-trips losslessly "
                    "same-vendor; a cross-vendor source carrying an interface "
                    "*name* there has no AOS-CX `source ip` form, so the "
                    "`source ip` line is omitted on render (the VLAN↔VNI "
                    "bindings still emit).  Operators set the loopback->IP "
                    "mapping on the target manually."
                ),
                severity="warn",
            ),
            # -- VXLAN BUM-replication underlay (silent-loss guard) --
            # Render emits the ``interface vxlan 1`` VTEP (source ip +
            # per-VNI ``vni``/``vlan`` bindings) but not the flood/multicast
            # underlay, so those sub-details drop while the VNI binding
            # (declared supported above) survives — declared here so the
            # validation report warns instead of reporting ``severity: ok``.
            LossyPath(
                path="/vxlan-vnis/mcast-group",
                reason=(
                    "Render emits the VTEP `source ip` + per-VNI "
                    "`vni <N>` / nested `vlan <V>` bindings, but not the "
                    "BUM-replication underlay: a per-VNI multicast group "
                    "drops on render while the VLAN↔VNI binding survives.  "
                    "The operator re-applies the multicast/flood underlay "
                    "on the target."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vxlan-vnis/flood-list",
                reason=(
                    "Companion to /vxlan-vnis/mcast-group: head-end / "
                    "ingress-replication VTEP flood-lists are not emitted, "
                    "so a source carrying static flood VTEPs loses them on "
                    "render while the VLAN↔VNI binding survives."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vxlan-vnis/udp-port",
                reason=(
                    "Render emits the `interface vxlan 1` VTEP + per-VNI "
                    "`vni`/`vlan` bindings but no UDP-port override, so a "
                    "non-default VXLAN UDP port (e.g. the legacy 8472) is "
                    "dropped on render and re-parses as the IANA default "
                    "4789.  The VLAN↔VNI binding survives; only the custom "
                    "port is lost.  Previously undeclared (classify() "
                    "fail-opened to supported) — Fable review MTX-2."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/interfaces/interface/dot1q-vlan",
                reason=(
                    "AOS-CX has NO routed sub-interface construct (no "
                    "`<parent>.<subid>` naming) — tagged L3 is done via "
                    "SVIs (`interface vlan N`), not `encapsulation dot1q` "
                    "sub-interfaces.  So the routed-subif 802.1Q tag (GAP "
                    "7) is architecturally unsupported here, not merely "
                    "un-wired: a cross-vendor source's tag is flagged as a "
                    "drop rather than mis-rendered."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group/mode",
                reason=(
                    "AOS-CX VRRP is a deferred phase (the group anchor is "
                    "unsupported); the FHRP mode is dropped on migration."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group/priority",
                reason=(
                    "AOS-CX VRRP is a deferred phase (the group anchor is "
                    "unsupported); the master-election priority is dropped."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group/preempt",
                reason=(
                    "AOS-CX VRRP is a deferred phase (the group anchor is "
                    "unsupported); the preempt flag is dropped."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group/advertisement-interval",
                reason=(
                    "AOS-CX VRRP is a deferred phase (the group anchor is "
                    "unsupported); the advertisement interval is dropped."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group/authentication",
                reason=(
                    "AOS-CX VRRP is a deferred phase (the group anchor is "
                    "unsupported); the FHRP authentication secret is dropped."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group/virtual-ipv6s",
                reason=(
                    "AOS-CX VRRP is a deferred phase (the group anchor is "
                    "unsupported); the IPv6 virtual addresses are dropped."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group/description",
                reason=(
                    "AOS-CX VRRP is a deferred phase (the group anchor is "
                    "unsupported); the group description is dropped."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/voice-vlan",
                reason=(
                    "This codec does not model AOS-CX per-port voice VLAN; "
                    "dropped on render (blind-audit 65f9c01 #11)."
                ),
            ),
            # ── Tier-1/2 surfaces this codec drops on render — declared so the
            #    live validation report flags the loss instead of reporting
            #    `severity: ok` (2026-06 adversarial review #9). ──
            UnsupportedPath(
                path="/system/domain",
                reason="Render emits no system domain-name; intent.domain is dropped on migration.",
            ),
            UnsupportedPath(
                path="/system/timezone",
                reason="Render emits no clock/timezone stanza; intent.timezone is dropped on migration.",
            ),
            UnsupportedPath(
                path="/system/dns-server",
                reason="Render emits no name-server config; intent.dns_servers are dropped on migration.",
            ),
            UnsupportedPath(
                path="/system/ntp-server",
                reason="Render emits no NTP config; intent.ntp_servers are dropped on migration.",
            ),
            UnsupportedPath(
                path="/system/syslog-server",
                reason="Render emits no logging/syslog config; intent.syslog_servers are dropped on migration.",
            ),
            UnsupportedPath(
                path="/dhcp-servers/pool",
                reason="Render emits no DHCP server pool; intent.dhcp_servers are dropped on migration.",
            ),
            UnsupportedPath(
                path="/radius-servers/server/host",
                reason="Render emits no AAA radius-server config; RADIUS host is dropped on migration.",
            ),
            UnsupportedPath(
                path="/radius-servers/server/key",
                reason="Render emits no AAA radius-server config; the RADIUS shared secret is dropped on migration.",
            ),
            # ── SNMP trap hosts (deferred — `snmp-server host` grammar) ──
            UnsupportedPath(
                path="/snmp/trap-host",
                reason=(
                    "The `snmp-server host <ip> trap version ... community "
                    "...` trap-receiver grammar is deferred; v2c community "
                    "+ system-location / system-contact + v3 USM users are "
                    "supported."
                ),
            ),
            # ── VRF description + RD / route-target + per-VRF static ──
            UnsupportedPath(
                path="/routing-instances/instance/description",
                reason=(
                    "The AOS-CX `vrf <name>` stanza is a bare name in v1; "
                    "VRF descriptions / RD / route-target live under the "
                    "deferred `evpn` / `router bgp` blocks."
                ),
            ),
            UnsupportedPath(
                path="/routing-instances/instance/route-distinguisher",
                reason="VRF RD lives under the deferred `evpn` block.",
            ),
            UnsupportedPath(
                path="/routing-instances/instance/rt-imports",
                reason="VRF route-targets live under the deferred `evpn` block.",
            ),
            UnsupportedPath(
                path="/routing-instances/instance/rt-exports",
                reason="VRF route-targets live under the deferred `evpn` block.",
            ),
            UnsupportedPath(
                path="/routing/static-route/vrf",
                reason=(
                    "Per-VRF static-route binding parses-and-ignores in "
                    "Phase 1; only default-VRF `ip route` is wired."
                ),
            ),
            # ── FHRP VRRP (later phase — distinct from active-gateway) ──
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group",
                reason=(
                    "AOS-CX VRRP (`vrrp <vrid> address-family` under an "
                    "SVI) is a later phase; the `active-gateway` anycast "
                    "surface (the VSX/EVPN distributed gateway) IS "
                    "supported."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-address",
                reason=(
                    "IPv4 active-gateway is supported; the IPv6 anycast "
                    "companion parses-and-ignores in v1 (parity with the "
                    "NX-OS / IOS-XE IPv6-anycast deferral)."
                ),
            ),
            # ── VXLAN / EVPN — L2 VLAN↔VNI binding IS supported (Phase 4);
            # the per-VLAN L2VNI RD/RT + symmetric-IRB L3VNI are not. ──
            UnsupportedPath(
                path="/vxlan-vnis/l2vni-route-target",
                reason=(
                    "The per-VLAN L2VNI route-distinguisher / route-target "
                    "(`evpn / vlan N / rd auto / route-target export|import "
                    "...`) is almost always `auto`-derived and has no "
                    "cross-vendor canonical home — NX-OS / Arista / Junos all "
                    "auto-derive the L2VNI RD/RT from the VNI too.  The "
                    "VLAN↔VNI binding (`/vxlan-vnis/vni`) IS translated; the "
                    "RD/RT is dropped (re-derived on the target)."
                ),
            ),
            UnsupportedPath(
                path="/routing-instances/instance/l3-vni",
                reason=(
                    "EVPN symmetric-IRB L3VNI (`vni N / vrf <name>` under the "
                    "VTEP + `router bgp / vrf`) is a later phase; the L2VNI "
                    "VLAN↔VNI binding (`/vxlan-vnis/vni`) IS supported."
                ),
            ),
            # ── Tier-3 — never auto-translatable ──
            UnsupportedPath(
                path="/routing-protocols/bgp",
                reason=(
                    "AOS-CX `router bgp <asn>` (incl. the EVPN address-"
                    "family) is Tier-3 — captured for the "
                    "dropped_tier3_sections banner but never auto-rendered "
                    "cross-vendor."
                ),
            ),
            UnsupportedPath(path="/routing-protocols/ospf", reason="Tier-3."),
            UnsupportedPath(
                path="/access-list/extended",
                reason=(
                    "ACLs are Tier-3 — auto-translating ACL semantics "
                    "across vendors risks shipping subtly-permissive "
                    "rules.  Operator authors firewall policy manually."
                ),
            ),
            UnsupportedPath(
                path="/access-list/standard",
                reason="Tier-3 (mirrors cisco_nxos).",
            ),
            UnsupportedPath(
                path="/qos",
                reason=(
                    "QoS (`class` / `policy` / `apply qos`) is Tier-3 — "
                    "too platform-specific to auto-translate."
                ),
            ),
            UnsupportedPath(
                path="/nat",
                reason="AOS-CX does not host typical edge NAT.",
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse / Render — delegate to sibling modules
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        from ..._tier3_detection import detect_tier3_sections_aoscx

        intent = parse_intent(raw)
        # Surface Tier-3 stanza headers the parser deliberately drops
        # (BGP / OSPF / ACLs / class / policy).  Notification-only —
        # never read by any render-side code.
        intent.dropped_tier3_sections = detect_tier3_sections_aoscx(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    # -----------------------------------------------------------------
    # iter_xpaths — reuse the shared canonical walker
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent`."""
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation (delegated to .port_names)
    # -----------------------------------------------------------------

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect Aruba AOS-CX ``show running-config`` text.

        Primary marker: the ``!Version ArubaOS-CX <release>`` banner is
        the first content line of every AOS-CX ``show running-config``
        and is unambiguously AOS-CX.

        Without the banner we fall back to AOS-CX-SPECIFIC structural
        markers — the ``interface <m>/<s>/<p>`` member/slot/port triple,
        ``interface lag N``, the ``vlan access`` / ``vlan trunk`` L2
        grammar, ``vrf attach``, and the ``no routing`` keyword.  These
        do not collide with the legacy ``aruba_aoss`` codec (which keys
        off a ``;`` banner + bare-numeric ``interface N`` + ``untagged``)
        or the Arista codec (which requires ``interface Ethernet`` /
        ``! device: ... EOS-``).
        """
        # Reject XML / JSON early (shared shape helper).
        if detect_input_shape(raw_prefix) is not None:
            return None

        lowered = raw_prefix.lower()

        # Definitive banner.
        if "!version arubaos-cx" in lowered:
            return (99, "AOS-CX !Version banner present")

        # Structural fallback (no banner — e.g. an operator paste).
        markers = 0
        if re.search(r"^interface\s+\d+/\d+/\d+\b", raw_prefix, re.MULTILINE):
            markers += 1  # member/slot/port triple
        if re.search(
            r"^interface\s+lag\s+\d+", raw_prefix,
            re.MULTILINE | re.IGNORECASE,
        ):
            markers += 1
        if re.search(
            r"^\s+vlan\s+(?:access|trunk)\b", raw_prefix,
            re.MULTILINE | re.IGNORECASE,
        ):
            markers += 1
        if re.search(
            r"^\s+vrf\s+attach\s+\S+", raw_prefix,
            re.MULTILINE | re.IGNORECASE,
        ):
            markers += 1
        if re.search(
            r"^\s+no\s+routing\s*$", raw_prefix,
            re.MULTILINE | re.IGNORECASE,
        ):
            markers += 1

        if markers >= 2:
            return (90, f"AOS-CX structural markers ({markers})")
        if markers == 1:
            return (60, "one AOS-CX structural marker")
        return None
