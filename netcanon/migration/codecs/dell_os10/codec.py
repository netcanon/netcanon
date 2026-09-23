"""
``DellOS10Codec`` — Dell SmartFabric OS10 ``show running-configuration``
codec.

Targets the Dell EMC PowerSwitch S-series (S3048-ON / S4100 / S5200 /
S5232F) and Z-series running OS10 10.5.x.  Distinct vendor identity from
Dell's older Force10 NOS (OS9 / FTOS), whose grammar is VLAN-centric
(``interface Vlan N`` + ``tagged`` / ``untagged``) and uses
``TenGigabitEthernet`` port naming — a separate codec if it ever ships.

Module layout mirrors the ``cisco_nxos`` post-split shape:

* ``codec.py`` (this file) — the class with metadata / capabilities /
  probe / port-name delegates.
* ``parse.py`` — line-scan + per-stanza dispatch over OS10 text.
* ``render.py`` — canonical tree → OS10 running-configuration text.
* ``port_names.py`` — cross-vendor port-name bridge.

⚠️ **NOT YET REGISTERED.**  The ``@register`` decorator is deliberately
absent.  Registering a 13th codec takes the cross-vendor mesh from 132 to
156 ordered pairs, and
``tests/integration/test_cross_mesh_ci_guard.py`` asserts
``cells_total == 1224`` EXACTLY — so registration is inseparable from
re-cutting the baseline (``python tools/run_phase4_reconciliation.py
--write-baseline``) and authoring 24 new expectation YAMLs.  That is
scoped as Phase 4 in ``docs/vendor-research/dell_os10/30-codec-plan.md``
§ 8, and deliberately not smuggled into the parser phase.  The class is
exercised directly by ``tests/unit/migration/test_dell_os10.py``.

Phasing (``30-codec-plan.md`` § 8):

* Phase 0 — ✅ shipped (PR #475): ``cisco_iosxe_cli.probe()`` defers on
  OS10 markers, closing the live fail-open where every Dell config was
  confidently parsed as Cisco IOS-XE.
* Phase 1 — ✅ hostname, interfaces, VLANs, switchport, LAGs, VRF
  declarations and static routes, parse-only.
* Phase 2 — **this change**: the render path, a canonical-stable
  parse→render→parse round-trip, and Tier-3 loss surfacing
  (``dropped_tier3_sections``).
* Phase 3 — VRRP, local users, SNMP **including the USM ``localized``
  marker from day one** (retrofitting key provenance is what #471 / #472
  had to do across nine codecs).
* Phase 4 — registration, the 24 expectation YAMLs, mesh re-baseline.
"""

from __future__ import annotations

import re
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
class DellOS10Codec(CodecBase):
    """Bidirectional codec for Dell SmartFabric OS10 running-configuration text.

    ``vendor_id=dell_os10`` — its own vendor row in
    ``netcanon/migration/vendors/dell_os10.yaml``.
    """

    name: ClassVar[str] = "dell_os10"
    version_hint: ClassVar[str | None] = "10.5.x"
    input_format: ClassVar[str] = "cli-dellos10"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "best_effort"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-configuration` from a Dell EMC "
        "PowerSwitch running SmartFabric OS10.  OS10 is Dell's modern "
        "Debian-based NOS; its grammar is distinct from the older Force10 "
        "OS9 / FTOS (which uses `TenGigabitEthernet` port naming and "
        "VLAN-centric `tagged` / `untagged` membership)."
    )
    sample_input: ClassVar[str] = (
        "! Version 10.5.1.0\n"
        "! Last configuration change at Feb  25 15:06:23 2020\n"
        "!\n"
        "ip vrf default\n"
        "!\n"
        "interface breakout 1/1/1 map 100g-1x\n"
        "hostname S5232F-1\n"
        "!\n"
        "interface vlan461\n"
        " description TENANT-A\n"
        " no shutdown\n"
        " ip address 192.168.46.3/26\n"
        "!\n"
        "interface port-channel100\n"
        " description Uplink\n"
        " no shutdown\n"
        " switchport mode trunk\n"
        " switchport access vlan 1\n"
        " switchport trunk allowed vlan 32,34,47,461\n"
        " mtu 9216\n"
        "!\n"
        "interface ethernet1/1/30\n"
        " description Up-po100\n"
        " no shutdown\n"
        " channel-group 100 mode active\n"
        " no switchport\n"
        "!\n"
        "interface mgmt1/1/1\n"
        " no shutdown\n"
        " ip address 192.168.33.44/24\n"
        "!\n"
        "management route 0.0.0.0/0 192.168.33.1\n"
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="dell_os10",
        vendor_id="dell_os10",
        version_range="10.5.x+",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        # The paths below describe ROUND-TRIP fidelity: Phase 2 shipped the
        # render path and `direction` is `bidirectional`, so each declaration
        # below is stated against an actual parse -> render -> parse probe
        # rather than against what parse() alone harvests.  Every `lossy`
        # entry is proved to drop by
        # `test_dell_os10.py::TestDeclaredLossesAreReal`.
        supported=[
            # System
            "/system/hostname",
            # Interfaces — name + basic L3
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",
            "/interfaces/interface/ipv6/address/prefix-length",
            "/interfaces/interface/config/vrf",
            # Interfaces — L2 switchport + LAG membership
            "/interfaces/interface/switchport-mode",
            "/interfaces/interface/access-vlan",
            "/interfaces/interface/trunk-allowed-vlans",
            "/interfaces/interface/trunk-native-vlan",
            "/interfaces/interface/lag-member-of",
            # VLANs — SVI-derived (OS10 has no top-level `vlan <id>` stanza)
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/vlans/vlan/tagged-ports",
            "/vlans/vlan/untagged-ports",
            # LAGs
            "/lags/lag/name",
            "/lags/lag/members",
            "/lags/lag/mode",
            # VRF declarations + static routes (incl. the management VRF)
            "/routing-instances/instance/name",
            "/routing/static-route",
            "/routing/static-route/vrf",
            # SNMP (Phase 3a) — v2c identity + v3 USM users
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            "/snmp/v3-user/group",
            # Local users (Phase 3a).  Unlike NX-OS, OS10 carries a REAL
            # numeric `priv-lvl` alongside the named role, so the privilege
            # level round-trips rather than being derived from the role.
            "/local-users/user/name",
            "/local-users/user/role",
            "/local-users/user/hashed-password",
            "/local-users/user/privilege-level",
            # VRRP (Phase 3b).  OS10 runs REAL VRRP, so a group renders as
            # itself — no HSRP normalisation, unlike the NX-OS codec.
            "/interfaces/interface/vrrp-groups/group",
            "/interfaces/interface/vrrp-groups/group/priority",
            "/interfaces/interface/vrrp-groups/group/preempt",
            "/interfaces/interface/vrrp-groups/group/virtual-ips",
        ],
        # ⚠️ Every leaf below renders its ANCHOR but drops or downgrades the
        # field itself.  `classify()` defaults an UNDECLARED xpath to
        # `supported`, so leaving any of these out makes validate_against
        # report `severity: ok` while the value is silently discarded — the
        # exact silent-loss class the PR-2a/2b/2c walk-expansions closed.
        # Each one is proved to drop by a render→parse probe in
        # `tests/unit/migration/test_dell_os10.py::TestDeclaredLossesAreReal`,
        # rather than merely asserted here.
        lossy=[
            LossyPath(
                path="/routing-instances/instance/instance-type",
                reason=(
                    "Renders the VRF as `ip vrf <name>`, which has no mac-vrf "
                    "form, so the mac-vrf vs vrf discriminator downgrades to "
                    "`vrf` on render.  The instance itself round-trips; only "
                    "the discriminator is lost."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/description",
                reason=(
                    "OS10 carries exactly one human label for a VLAN — the "
                    "SVI's `description` — and the render spends it on "
                    "CanonicalVlan.name.  A separate canonical VLAN "
                    "description has no second place to go and is dropped."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-address",
                reason=(
                    "OS10 has no VARP / distributed-anycast-gateway concept: "
                    "first-hop redundancy is expressed as real VRRP "
                    "(`vrrp-group` + `virtual-address`).  The interface "
                    "address renders, the anycast virtual IP does not."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-address",
                reason=(
                    "Same as the IPv4 companion — no anycast-gateway concept "
                    "on OS10.  The IPv6 address renders; the virtual gateway "
                    "IP is dropped."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/tunnel-type",
                reason=(
                    "Phase 1/2 model no OS10 tunnel encapsulation.  A tunnel "
                    "interface still renders as an `interface <name>` stanza, "
                    "so the port survives while its encapsulation type is "
                    "dropped — a downgrade, not a whole-surface drop."
                ),
                severity="warn",
            ),
            # ── Interface sub-details the stanza renders WITHOUT ──
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "OS10 interface-type is inferred from the name prefix "
                    "(ethernet -> ethernetCsmacd, vlan -> l3ipvlan, "
                    "port-channel -> ieee8023adLag, loopback -> "
                    "softwareLoopback, mgmt -> ethernetCsmacd).  Inference is "
                    "best-effort and will not recover every IANA type a "
                    "cross-vendor source carried."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/dhcp-client",
                reason=(
                    "OS10 spells this `ip address dhcp`, which Phase 1/2 "
                    "neither parse nor render (real captures carry the "
                    "negated `no ip address dhcp` on the mgmt port).  The "
                    "interface renders; the DHCP-client flag is dropped."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/dhcp-client-v6",
                reason=(
                    "OS10 spells this `ipv6 address autoconfig` / `ipv6 "
                    "address dhcp`; Phase 1/2 consume the marker but model no "
                    "canonical value for it, so it is dropped on render."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-mac",
                reason=(
                    "Subsumed by the anycast virtual-gateway drop (see the "
                    "IPv4 virtual-gateway-address entry): OS10 has no VARP / "
                    "anycast-gateway concept, so the MAC drops with it."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-mac",
                reason="IPv6 companion of the virtual-gateway-MAC drop above.",
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/ipv6/address/secondary-ip",
                reason=(
                    "The IPv4 render re-emits the `secondary` keyword and the "
                    "parser reads it back, but OS10's `ipv6 address` form is "
                    "rendered without it, so an IPv6 secondary flag is lost "
                    "while the address itself survives."
                ),
                severity="warn",
            ),
            # ── VRF sub-details: `ip vrf <name>` carries the name and
            #    nothing else, so every other instance field drops. ──
            LossyPath(
                path="/routing-instances/instance/description",
                reason=(
                    "The OS10 `ip vrf <name>` stanza carries no description "
                    "line; the VRF renders, its description does not."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance/route-distinguisher",
                reason=(
                    "Phase 1/2 render no per-VRF RD (an OS10 RD lives under "
                    "`router bgp`, which is Tier-3).  The VRF renders; the RD "
                    "is dropped."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance/rt-imports",
                reason="Route-targets live under Tier-3 `router bgp`; dropped.",
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance/rt-exports",
                reason="Route-targets live under Tier-3 `router bgp`; dropped.",
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance/l3-vni",
                reason=(
                    "OS10 binds an L3VNI through the `virtual-network` "
                    "indirection, which is deferred past v1.  The VRF "
                    "renders; its L3VNI binding is dropped."
                ),
                severity="warn",
            ),
            # ── Static-route sub-detail ──
            LossyPath(
                path="/routing/static-route/description",
                reason=(
                    "Render emits destination + next-hop + administrative "
                    "distance only; a route name / description is dropped."
                ),
                severity="warn",
            ),
            # ── VLAN-record L3 sub-details ──
            LossyPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-address",
                reason=(
                    "The VLAN's address renders (Phase 2 synthesises an "
                    "`interface vlan<N>` SVI for a VLAN that carries one), but "
                    "OS10 has no anycast virtual-gateway, so that IP drops."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-mac",
                reason="Drops with the VLAN-record virtual-gateway IP above.",
                severity="warn",
            ),
            # ── SNMPv3 USM (Phase 3a) ──
            LossyPath(
                path="/snmp/v3-user/auth-passphrase",
                reason=(
                    "A USM key is localised against the agent's OWN engine "
                    "ID, and Dell states such keys cannot be copied between "
                    "switches (10.5.2 User Guide L8942).  A key from another "
                    "agent is REFUSED (review comment, no `snmp-server user` "
                    "line) rather than emitted behind `localized`, which "
                    "would claim the digest was already this switch's.  A "
                    "source PASSPHRASE is portable and is emitted without "
                    "that keyword so OS10 localises it on commit.  Operators "
                    "migrating between vendors must re-key SNMPv3 users."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/priv-passphrase",
                reason=(
                    "Same engine-ID binding as the auth key: a privacy key "
                    "bound to the source agent is refused with its user."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/auth-protocol",
                reason=(
                    "OS10 offers only `auth md5` and `auth sha`, so every "
                    "SHA-2 variant (sha224 / sha256 / sha384 / sha512) "
                    "collapses to `sha` on render — a real crypto downgrade, "
                    "not a faithful round-trip."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/priv-protocol",
                reason=(
                    "OS10 offers only `priv des` and `priv aes`, so AES-192 "
                    "and AES-256 collapse to `aes` and 3DES to `des`."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/engine-id",
                reason=(
                    "OS10 states the engine ID on its own `snmp-server "
                    "engineID local` line rather than on the user, so a "
                    "per-user engine ID carried by a cross-vendor source is "
                    "dropped while the user itself renders."
                ),
                severity="warn",
            ),
            # ── VRRP sub-details (Phase 3b) ──
            # The PR-2b disposition guard
            # (`test_vrrp_subfield_walk_expansion._EXPECTED`) treats a codec
            # ABSENT from a leaf's dict as expected-`supported`, so every
            # leaf declared lossy below carries a matching `dell_os10` row
            # there.  `priority`, `preempt` and `virtual-ips` are deliberately
            # ABSENT from that dict: OS10 renders real VRRP, so they
            # round-trip and the supported default is the honest answer.
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/mode",
                reason=(
                    "OS10 renders real VRRP, so a cross-family source mode "
                    "(HSRP / CARP) is reinterpreted as VRRP on render — the "
                    "operator's redundancy intent for the virtual IP "
                    "survives, but the wire protocol changes.  Same-vendor "
                    "VRRP round-trips losslessly.  No codec renders every "
                    "FHRP family, so this discriminator can never rely on "
                    "the supported fail-open."
                ),
                severity="warn",
            ),
            LossyPath(
                path=(
                    "/interfaces/interface/vrrp-groups/group/"
                    "advertisement-interval"
                ),
                reason=(
                    "The v1 VRRP model carries no advertisement / hello "
                    "timer; the group renders but the interval is dropped "
                    "and the target uses its default."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/authentication",
                reason=(
                    "VRRP authentication is not modelled in v1; the group "
                    "renders without it."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/virtual-ipv6s",
                reason=(
                    "OS10 expresses IPv6 VRRP through a SEPARATE "
                    "`vrrp-ipv6-group` stanza, which v1 does not render, so "
                    "IPv6 virtual addresses drop while the IPv4 group "
                    "survives."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/virtual-mac",
                reason="Virtual-MAC is not modelled in v1; dropped on render.",
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/track-interfaces",
                reason=(
                    "OS10 tracks a TRACK-OBJECT id (`track <object-id>`), not "
                    "an interface name, so a canonical track-interface list "
                    "has no faithful OS10 form and is dropped."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/description",
                reason=(
                    "The OS10 `vrrp-group` grammar carries no description "
                    "line; the group renders, the description does not."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            # ── ⚠️ SUB-PATHS OF AN UNSUPPORTED ANCHOR ──
            # `CapabilityMatrix.classify()` is an EXACT-STRING match, so
            # declaring a parent (`/snmp/v3-user`) does NOT cover its
            # children — each undeclared child independently defaults to
            # `supported`.  Declaring the anchor alone produced a matrix
            # that said "VRRP is unsupported" while simultaneously
            # claiming every VRRP sub-field migrates faithfully.  Every
            # leaf below belongs to an anchor this codec renders NO
            # instance of, hence `unsupported` rather than `lossy`.
            #
            # VXLAN sub-fields — the `virtual-network` indirection is v2+.
            UnsupportedPath(
                path="/vxlan-vnis/vlan-id",
                reason="No VXLAN overlay is rendered (see /vxlan-vnis/vni).",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/source-interface",
                reason="No VXLAN overlay is rendered.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/mcast-group",
                reason="No VXLAN overlay is rendered.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/flood-list",
                reason="No VXLAN overlay is rendered.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/udp-port",
                reason="No VXLAN overlay is rendered.",
            ),
            UnsupportedPath(
                path="/evpn-type5-routes/route",
                reason="No EVPN is rendered; BGP / EVPN is Tier-3 on OS10.",
            ),
            UnsupportedPath(
                path="/anycast-gateway-mac",
                reason=(
                    "OS10 expresses first-hop redundancy as real VRRP, not a "
                    "chassis-wide anycast-gateway MAC; nothing renders it."
                ),
            ),
            # DHCP pool sub-fields — no pool stanza is rendered.
            UnsupportedPath(
                path="/dhcp-servers/pool/gateway",
                reason="No DHCP server pool is rendered.",
            ),
            UnsupportedPath(
                path="/dhcp-servers/pool/dns-servers",
                reason="No DHCP server pool is rendered.",
            ),
            UnsupportedPath(
                path="/dhcp-servers/pool/domain-name",
                reason="No DHCP server pool is rendered.",
            ),
            UnsupportedPath(
                path="/dhcp-servers/pool/lease-time",
                reason="No DHCP server pool is rendered.",
            ),
            # ── Tier-1/2 surfaces this codec does not parse in Phase 1.
            #    Declared so validate_against reports the gap instead of
            #    `severity: ok` — `classify()` defaults an UNDECLARED xpath to
            #    `supported`, i.e. silent loss (2026-06 adversarial review #9).
            UnsupportedPath(
                path="/system/timezone",
                reason=(
                    "Phase 1 parses no `clock timezone` stanza; "
                    "intent.timezone is dropped."
                ),
            ),
            UnsupportedPath(
                path="/system/domain",
                reason="Phase 1 parses no `ip domain-name`.",
            ),
            UnsupportedPath(
                path="/system/dns-server",
                reason="Phase 1 parses no `ip name-server`.",
            ),
            UnsupportedPath(
                path="/system/ntp-server",
                reason="Phase 1 parses no `ntp server`.",
            ),
            UnsupportedPath(
                path="/system/syslog-server",
                reason="Phase 1 parses no `logging server`.",
            ),
            UnsupportedPath(
                path="/interfaces/interface/dot1q-vlan",
                reason=(
                    "OS10 routed sub-interfaces are not modelled in Phase 1; "
                    "no capture in the corpus carries one."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/voice-vlan",
                reason="This codec does not model OS10 per-port voice VLAN.",
            ),
            UnsupportedPath(
                path="/dhcp-servers/pool",
                reason="Phase 1 parses no DHCP server pool.",
            ),
            UnsupportedPath(
                path="/radius-servers/server/host",
                reason="Phase 1 parses no AAA radius-server config.",
            ),
            UnsupportedPath(
                path="/radius-servers/server/key",
                reason="Phase 1 parses no AAA radius-server config.",
            ),
            # ── Tier 3 — never auto-translatable ──
            UnsupportedPath(
                path="/routing-protocols/bgp",
                reason="OS10 `router bgp <asn>` is Tier-3.",
            ),
            UnsupportedPath(path="/routing-protocols/ospf", reason="Tier-3."),
            UnsupportedPath(path="/routing-protocols/eigrp", reason="Tier-3."),
            UnsupportedPath(path="/routing-protocols/isis", reason="Tier-3."),
            UnsupportedPath(
                path="/access-list/extended",
                reason=(
                    "ACLs are Tier-3 — auto-translating ACL semantics across "
                    "vendors risks shipping subtly-permissive rules."
                ),
            ),
            UnsupportedPath(path="/access-list/standard", reason="Tier-3."),
            UnsupportedPath(path="/access-list/ipv6", reason="Tier-3."),
            UnsupportedPath(
                path="/firewall",
                reason=(
                    "OS10 does not host a stateful firewall; declared "
                    "unsupported for consistency with the cross-vendor surface."
                ),
            ),
            UnsupportedPath(
                path="/nat", reason="OS10 does not host typical edge NAT.",
            ),
            UnsupportedPath(
                path="/qos",
                reason=(
                    "OS10 DCB / RoCE QoS (`class-map type queuing`, `trust "
                    "dot1p-map`, `qos-map traffic-class`, `system qos`) is "
                    "Tier-3 — it is heavy in real Azure Local configs and is "
                    "far too platform-specific to auto-translate."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason=(
                    "OS10 VXLAN uses a `virtual-network <vnid>` indirection "
                    "between VLAN and VNI rather than NX-OS's direct `vlan N "
                    "/ vn-segment` binding; deferred past v1."
                ),
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse / Render
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        from ..._tier3_detection import detect_tier3_sections_dellos10

        intent = parse_intent(raw)
        # Surface the Tier-3 stanza headers the parser deliberately drops
        # (QoS / DCB, VLT, breakout, ACLs, route-maps, routing protocols).
        # Notification-only — never read by any render-side code.  VLT
        # alone appears in 10 of 12 OS10 captures, so this banner fires on
        # most real configs; that is correct behaviour, not a defect.
        intent.dropped_tier3_sections = detect_tier3_sections_dellos10(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

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
        """Detect Dell SmartFabric OS10 ``show running-configuration`` text.

        OS10 shares the Cisco-family shape — ``!`` comment delimiter,
        indented sub-commands, ``! Last configuration change at`` — which
        is exactly why every Dell capture used to be claimed by
        ``cisco_iosxe_cli`` at confidence 95 (PR #475).  Detection
        therefore leans ONLY on markers that are OS10-exclusive, each
        verified to appear zero times across every committed fixture:

        =============================== ===== ========================
        marker                          score occurrences in corpus
        =============================== ===== ========================
        ``interface breakout ... map``  98    148
        ``system-user linuxadmin``      98    6
        ``vlt-domain`` / port-channel   96    10 of 12 captures
        column-0 ``ip vrf default``     95    8
        column-0 ``vrrp version``       95    4
        =============================== ===== ========================

        ⚠️ OS9 / FTOS is explicitly REFUSED rather than silently claimed.
        Dell's older Force10 NOS is a different grammar (``interface
        TenGigabitEthernet 0/1``, ``ManagementEthernet``, VLAN-centric
        ``tagged`` / ``untagged``) and parsing it with this codec would
        reproduce the very fail-open #475 closed, only with Dell on both
        sides of it.

        The probe WINDOW, not the marker set, was the dominant limit
        here.  A capture that spends its opening bytes on a preamble
        reaches no marker: QoS-leading configs (the ``DellGEOS``
        captures open with ``class-map type queuing`` / ``trust
        dot1p-map``), jinja2 template headers (``! system.j2``), and
        serial-console login banners all do this.

        Measured over a 40-capture corpus: at ``probe_bytes=500``,
        19 detected correctly, 11 returned no candidate and 10 were
        claimed by ``cisco_iosxe_cli``.  #483 widened the window to
        65536 after measuring the full sweep, giving **29 / 7 / 4**.
        The four remaining mis-attributions are config FRAGMENTS (a
        VLAN-only or interface-only excerpt) carrying no OS10 token at
        all, so no window reaches them; closing those needs a marker,
        and a weak structural guess would start stealing other vendors'
        configs — the failure mode #475 closed.  Tracked in
        ``30-codec-plan.md`` § 9.  Pinned in
        ``tests/unit/migration/codecs/dell_os10/test_probe_window_limits.py``.
        """
        # Reject XML / JSON early (shared shape helper).
        if detect_input_shape(raw_prefix) is not None:
            return None

        lowered = raw_prefix.lower()

        # ── Hard NOT-OS10 signals ──
        # Other vendors' unambiguous banners.
        if "!command: show running-config" in lowered:      # NX-OS
            return None
        if "building configuration" in lowered:             # IOS-XE classic
            return None
        if "current configuration :" in lowered:            # IOS-XE classic
            return None
        # Dell OS9 / FTOS — a DIFFERENT Dell grammar, not this codec's.
        if re.search(
            r"^interface\s+(?:TenGigabitEthernet|GigabitEthernet|"
            r"fortyGigE|ManagementEthernet)\b",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            return None

        # ── OS10-exclusive markers ──
        if re.search(
            r"^interface\s+breakout\s+\S+\s+map\b",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            return (98, "OS10 `interface breakout ... map` port-splitting")
        if re.search(
            r"^system-user\s+linuxadmin\b",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            return (98, "OS10 `system-user linuxadmin` Linux account")
        if re.search(
            r"^vlt-domain\s+\d+|^\s*vlt-port-channel\s+\d+",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            return (96, "Dell VLT domain / port-channel")
        if re.search(
            r"^ip\s+vrf\s+default\s*$",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            return (95, "OS10 explicit `ip vrf default` stanza")
        if re.search(
            r"^vrrp\s+(?:version\s+\d|delay\s+reload\s+\d)",
            raw_prefix, re.IGNORECASE | re.MULTILINE,
        ):
            return (95, "OS10 chassis-level VRRP configuration")

        # ── Weaker structural combination ──
        # The `! Version 10.x.y.z` banner alone is not OS10-exclusive in
        # form, so pair it with OS10's three-segment lower-case port
        # naming before claiming the capture.
        has_version = bool(re.search(
            r"^!\s*Version\s+10\.\d+\.\d+", raw_prefix, re.IGNORECASE | re.MULTILINE,
        ))
        has_os10_ports = bool(re.search(
            r"^interface\s+(?:ethernet\d+/\d+/\d+|mgmt\d+/\d+/\d+)",
            raw_prefix, re.MULTILINE,
        ))
        if has_version and has_os10_ports:
            return (90, "OS10 version banner + three-segment ethernet naming")
        if has_os10_ports:
            return (75, "OS10 lower-case three-segment interface naming")
        return None
