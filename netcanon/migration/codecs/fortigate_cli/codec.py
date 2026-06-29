"""
``FortiGateCLICodec`` — 5th real codec, Session D.

See package ``__init__`` for scope and structural notes.

Module layout (post-split):

* ``codec.py`` (this file) — the ``FortiGateCLICodec`` class with
  metadata (capabilities / classvars / probe / port-name delegates).
  ``parse()`` and ``render()`` are two-line delegators to the
  corresponding functions in the sibling modules.
* ``parse.py`` — block-model tokeniser + per-stanza dispatchers that
  consume FortiOS text and mutate :class:`CanonicalIntent`.
* ``render.py`` — canonical tree to FortiOS CLI text.
* ``vlan_heuristics.py`` — ifType inference + VLAN-naming helpers
  shared between parse and render.
* ``port_names.py`` — cross-vendor port-name identity bridge
  (shared with the rename-modal orchestrator).

Test-import symbols (``_parse_blocks``, ``_prefix_to_mask``,
``_mask_to_prefix``) are re-exported here so
``tests/unit/migration/test_fortigate_cli.py`` doesn't need updating
for the split.  The canonical home is :mod:`.parse`; this module's
re-exports are purely for backwards compatibility.
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
from .parse import (
    _mask_to_prefix,
    _parse_blocks,
    _prefix_to_mask,
    parse_intent,
)
from .render import render_intent

# Re-export the internal helpers that tests pin against the codec's
# structural contract (see module docstring).
__all__ = [
    "FortiGateCLICodec",
    "_mask_to_prefix",
    "_parse_blocks",
    "_prefix_to_mask",
]


@register
class FortiGateCLICodec(CodecBase):
    """Codec for FortiGate CLI (``config/edit/set/next/end``)."""

    name: ClassVar[str] = "fortigate_cli"
    version_hint: ClassVar[str | None] = "7.x"
    input_format: ClassVar[str] = "cli-fortigate"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste FortiOS CLI export (`config/edit/set/next/end` grammar).  "
        "The codec parses system global, dns, ntp, interface, and "
        "router static blocks.  Firewall policies are Tier 3 and not "
        "yet auto-translated."
    )
    sample_input: ClassVar[str] = (
        '#config-version=FGT60E-7.4\n'
        'config system global\n'
        '    set hostname "fgt-edge"\n'
        'end\n'
        'config system interface\n'
        '    edit "port1"\n'
        '        set alias "WAN"\n'
        '        set ip 198.51.100.2 255.255.255.252\n'
        '        set status up\n'
        '    next\n'
        'end\n'
        'config router static\n'
        '    edit 1\n'
        '        set dst 0.0.0.0 0.0.0.0\n'
        '        set gateway 198.51.100.1\n'
        '    next\n'
        'end\n'
    )
    output_extension: ClassVar[str] = "conf"

    # unsupported_rename_categories is intentionally empty — the
    # FortiGate CLI codec round-trips CanonicalLocalUser through
    # ``config system admin`` blocks (see :mod:`.parse._apply_system_admin`
    # and the matching :mod:`.render` path that emits ``edit "NAME" /
    # set password ENC ... / set accprofile "..."``).  Coverage locked
    # in by ``tests/unit/migration/test_local_users_wire_through.py``
    # (TestFortiGateLocalUsersParseRender).  A prior pre-Option-A
    # declaration had this list as ``{"local_users"}`` under the
    # incorrect assumption that user handling was Tier-3-only —
    # cleared as part of Option A.

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="fortigate_cli",
        vendor_id="fortigate",
        version_range="7.x",
        device_classes=[DeviceClass.firewall, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/type",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            # Per-interface MTU — parse (`set mtu N` →
            # CanonicalInterface.mtu) + render (`set mtu-override enable`
            # + `set mtu N`) both wired; see
            # tests/unit/migration/test_mtu_wire_through.py
            # ::TestFortiGateMTUParseRender and the MTU worked example in
            # docs/adding-a-canonical-field.md.  The `mtu-override enable`
            # gate is a FortiOS render-side quirk, not a lossiness — full
            # round-trip parity, so `supported` (matches cisco_iosxe_cli /
            # arista_eos / juniper_junos, which carry mtu implicitly).
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/dhcp-client-v6",          # set ip6-mode dhcp
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            "/routing/static-route/gateway",     # audit e5b77d7 — next-hop round-trips
            "/routing/static-route/interface",   # run3 — `set device <iface>`
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            # Tier 2 — local admin users.  FortiGate admin accounts
            # map to CanonicalLocalUser: super_admin accprofile →
            # privilege 15; other profiles → privilege 1 with the
            # profile name preserved in ``role`` for lossless intra-
            # vendor round-trip.  Hashes carry the ``fortios:`` tag.
            "/local-users/user/name",
            "/local-users/user/hashed-password",
            "/local-users/user/role",
            # -- Wave B (v0.2.0) -- VRRP groups (FHRP) --
            # Nested ``config vrrp / edit N`` block inside ``config
            # system interface / edit X``.  Parses ``vrip``, ``vrip6``,
            # ``priority``, ``preempt``, ``adv-interval``,
            # ``authentication``, ``vrdst`` into :class:`CanonicalVRRPGroup`;
            # render emits the inverse.  Anycast-gateway companion
            # paths stay ``unsupported`` — FortiGate is a firewall /
            # edge platform with no native anycast surface (HA is
            # delivered via VRRP groups, not anycast-MAC fabrics).
            "/interfaces/interface/vrrp-groups/group",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/ipv6/address/scope",
                reason=(
                    "Renders the IPv6 address but parse hardcodes scope=global "
                    "(never re-infers link-local from the fe80::/10 prefix), so the "
                    "link-local vs global discriminator is lost. Declared lossy so "
                    "validate_against surfaces the loss instead of reporting "
                    "severity:ok (audit e5b77d7, PR-2c)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/mode",
                reason=(
                    "FortiOS renders only IETF VRRP; a cross-family source "
                    "mode (HSRP / CARP) drops to a review comment on render -- "
                    "the FHRP protocol silently changes, verify."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/description",
                reason=(
                    "FortiOS `config vrrp` carries no per-group description; "
                    "the group renders but the operator description is dropped."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vlans/vlan/description",
                reason=(
                    "Render emits the VLAN name but not a separate "
                    "description line, so the canonical VLAN description "
                    "(distinct from the name) drops on render (silent-loss "
                    "guard, Bucket-C stage 2)."
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
                path="/snmp/v3-user/priv-protocol",
                reason=(
                    "FortiOS has no 3DES privacy cipher; a `3des` source "
                    "cipher is substituted with AES on render (a cipher "
                    "change, not a re-key) -- verify the resulting security "
                    "level.  AES-128/192/256 and DES round-trip faithfully."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/group",
                reason=(
                    "FortiOS `config system snmp user` carries no VACM group "
                    "(users are grouped implicitly by security-level); the "
                    "user renders but the canonical group is dropped."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing/static-route/metric",
                reason=(
                    "Render emits destination + next-hop + device only; the "
                    "static-route administrative distance (metric) is "
                    "dropped (run3)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/config/description",
                reason=(
                    "FortiOS limits alias to 25 characters; longer "
                    "descriptions from other vendors will be truncated."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "FortiOS has no IANA ifType; inferred from 'type vlan' "
                    "sub-setting or name shape."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/tunnel-type",
                reason=(
                    "FortiOS expresses tunnels in separate top-level "
                    "sections (config system gre-tunnel, config vpn ipsec "
                    "phase1-interface) rather than as encap discriminator "
                    "on a tunnel interface — tunnel_type does not survive "
                    "render-into-FortiGate."
                ),
                severity="warn",
            ),
            # -- Wave B (v0.2.0) -- VRRP per-group lossy edges --
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/virtual-ips",
                reason=(
                    "FortiOS ``config vrrp / edit N`` accepts a single "
                    "``set vrip`` line per group.  Multi-IP canonical "
                    "groups (IOS-XE repeated ``vrrp N ip X`` for "
                    "secondaries; Junos ``virtual-address [ X Y Z ]``) "
                    "emit the first VIP and drop the tail with a "
                    "``# review:`` line — operator must split into "
                    "multiple groups manually if redundancy on all "
                    "addresses is required."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/virtual-mac",
                reason=(
                    "FortiOS uses ``set vrrp-virtual-mac enable/disable`` "
                    "as an interface-wide toggle (defaults to disable, "
                    "meaning FortiOS uses its own NPU MAC instead of "
                    "00:00:5E:00:01:VRID).  The canonical "
                    "``virtual_mac`` per-group override has no FortiOS "
                    "equivalent and is silently dropped — cross-vendor "
                    "renders into FortiGate cannot pin a custom VRID "
                    "MAC at the group level."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/track-interfaces",
                reason=(
                    "FortiOS ``set vrdst <iface>`` accepts a single "
                    "destination-tracking entry per group.  Multi-track "
                    "canonical groups (IOS-XE ``track`` objects, Arista "
                    "``vrrp N track Ethernet1 decrement 10``) emit the "
                    "first and drop the rest with a ``# review:`` line.  "
                    "The decrement value is also lossy — FortiOS "
                    "vrdst is a binary up/down trigger, not a "
                    "priority-decrement scheme."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/routing-instances/instance/instance-type",
                reason=(
                    "FortiGate models tenancy as VDOMs, not VRFs, and renders no "
                    "routing-instance (see /routing-instances/instance), so the "
                    "mac-vrf vs vrf instance-type discriminator is dropped "
                    "(audit e5b77d7, PR-2c)."
                ),
            ),
            UnsupportedPath(
                path="/vlans/vlan/ipv4/address/secondary-ip",
                reason=(
                    "VLAN-SVI mount: FortiOS models one IP per interface (cf. "
                    "the unsupported interface-mount twin), so a secondary IP "
                    "on a VLAN SVI is dropped — a whole-subnet reachability "
                    "loss. Declared unsupported (blind-audit f92e97a T0-2)."
                ),
            ),
            UnsupportedPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-address",
                reason=(
                    "VLAN-SVI mount: FortiGate is a firewall/edge platform with "
                    "no anycast-gateway fabric primitive (cf. the unsupported "
                    "interface-mount twin), so an anycast virtual-gateway IP on "
                    "a VLAN SVI cannot be modelled. Declared unsupported "
                    "(blind-audit f92e97a T0-2)."
                ),
            ),
            UnsupportedPath(
                path="/vlans/vlan/ipv4/address/virtual-gateway-mac",
                reason=(
                    "VLAN-SVI mount: FortiOS has no anycast/VARP virtual-MAC "
                    "surface (see the unsupported system-wide "
                    "/anycast-gateway-mac), so a per-address virtual-gateway "
                    "MAC on a VLAN SVI is dropped. Declared unsupported "
                    "(blind-audit f92e97a T0-2)."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/ipv4/address/secondary-ip",
                reason=(
                    "Render emits one IPv4 address per interface; "
                    "is_secondary addresses are dropped — a whole-subnet "
                    "reachability loss (run3)."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/ipv6/address/secondary-ip",
                reason=(
                    "Render emits one IPv6 address per interface; "
                    "is_secondary addresses are dropped (run3)."
                ),
            ),
            # ── L2 switchport surface (ENG-01) — this codec has no
            #    Cisco-style access/trunk port model, so the per-port VLAN
            #    membership the walker yields is dropped on render.  Declared
            #    unsupported so a switch→{firewall,router} migration surfaces
            #    the L2 loss instead of reporting `severity: ok`. ──
            UnsupportedPath(
                path="/interfaces/interface/switchport-mode",
                reason="FortiOS has no switchport access/trunk mode — every port is L3; the mode is dropped.",
            ),
            UnsupportedPath(
                path="/interfaces/interface/access-vlan",
                reason="FortiOS has no per-port access-VLAN; the port→VLAN binding is dropped on render.",
            ),
            UnsupportedPath(
                path="/interfaces/interface/trunk-allowed-vlans",
                reason="FortiOS trunks via stacked VLAN child-interfaces, not an allowed-list; dropped.",
            ),
            UnsupportedPath(
                path="/interfaces/interface/trunk-native-vlan",
                reason="FortiOS has no native-VLAN on a routed port; dropped on render.",
            ),
            UnsupportedPath(
                path="/interfaces/interface/voice-vlan",
                reason="FortiOS has no per-port voice-VLAN; dropped on render.",
            ),
            # ── VLAN-centric L2 membership — the twin of the per-port
            #    switchport surface above.  FortiOS models a VLAN as a single-
            #    parent child interface (``set interface <phys>`` +
            #    ``set vlanid N``), so a VLAN that spans several switch ports
            #    collapses to one sub-interface and the tagged/untagged port
            #    LISTS are dropped on render.  Declared unsupported so a
            #    switch→firewall migration surfaces the membership loss
            #    instead of reporting ``severity: ok`` while the walker yields
            #    these paths (silent-loss naming-sensitive guard). ──
            UnsupportedPath(
                path="/vlans/vlan/tagged-ports",
                reason="FortiOS binds a VLAN to a single parent child-interface; "
                "multi-port tagged membership (switchport's VLAN-centric twin) "
                "is dropped on render.",
            ),
            UnsupportedPath(
                path="/vlans/vlan/untagged-ports",
                reason="FortiOS binds a VLAN to a single parent child-interface; "
                "multi-port untagged membership (switchport's VLAN-centric twin) "
                "is dropped on render.",
            ),
            # ── Tier-1/2 surfaces this codec drops on render — declared so the
            #    live validation report flags the loss instead of reporting
            #    `severity: ok` (2026-06 adversarial review #9). ──
            UnsupportedPath(
                path="/system/timezone",
                reason="Render emits no clock/timezone stanza; intent.timezone is dropped on migration.",
            ),
            UnsupportedPath(
                path="/system/syslog-server",
                reason="Render emits no logging/syslog config; intent.syslog_servers are dropped on migration.",
            ),
            UnsupportedPath(
                path="/routing-instances/instance",
                reason="Render emits no VRF/routing-instance construct "
                "(VDOMs not modelled); intent.routing_instances are "
                "dropped on migration.",
            ),
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "FortiGate policy rules (config firewall policy) are "
                    "Tier 3 — policy semantics differ fundamentally from "
                    "other vendors (session-based, zone-aware, UTM-enabled)."
                ),
            ),
            UnsupportedPath(
                path="/nat/rule",
                reason=(
                    "FortiGate NAT lives inside firewall policy and "
                    "address/VIP objects — not auto-translatable."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason="VXLAN not modelled — FortiGate is a firewall codec.",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/source-interface",
                reason="VXLAN not modelled (see /vxlan-vnis/vni).",
            ),
            UnsupportedPath(
                path="/vxlan-vnis/udp-port",
                reason="VXLAN not modelled (see /vxlan-vnis/vni).",
            ),
            # -- Ship-before-wire (v0.2.0) -- anycast / per-VRF static routes --
            # VRRP groups WIRED in Wave B (see ``supported`` block).
            # Anycast paths remain unsupported because FortiGate is a
            # firewall / edge platform — anycast-gateway is a fabric
            # primitive on data-centre switches (Arista VARP, NX-OS
            # DAG, Junos enhanced-IP), not on edge firewalls.
            UnsupportedPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-address",
                reason=(
                    "Anycast-gateway virtual IPv4 companion parses-and-"
                    "ignores in v1.  Schema exists on "
                    "CanonicalIPv4Address; wire-up scheduled for v0.2.0 "
                    "Wave C (see docs/v0.2.0-planning/02-anycast-gateway/)."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-address",
                reason=(
                    "IPv6 anycast-gateway virtual IP companion parses-"
                    "and-ignores in v1.  Schema exists on "
                    "CanonicalIPv6Address; wire-up scheduled for v0.2.0 "
                    "Wave C."
                ),
            ),
            UnsupportedPath(
                path="/anycast-gateway-mac",
                reason=(
                    "System-wide anycast-gateway MAC parses-and-ignores "
                    "in v1.  Schema exists on CanonicalIntent; wire-up "
                    "scheduled for v0.2.0 Wave C."
                ),
            ),
            UnsupportedPath(
                path="/routing/static-route/vrf",
                reason=(
                    "Per-VRF static-route binding parses-and-ignores in "
                    "v1.  Schema exists on CanonicalStaticRoute.vrf; "
                    "wire-up scheduled for v0.2.0 (closes existing "
                    "per-VRF static-route lossy declaration)."
                ),
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
        from ..._tier3_detection import detect_tier3_sections_fortios

        intent = parse_intent(raw)
        # Surface Tier-3 `config` blocks the parser drops (firewall
        # policies, VIPs, VPN, UTM profiles, router policy/route-maps).
        # Notification-only.
        intent.dropped_tier3_sections = detect_tier3_sections_fortios(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    # -----------------------------------------------------------------
    # iter_xpaths
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        if isinstance(tree, CanonicalIntent):
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------
    # Implementation extracted to :mod:`.port_names` — these methods
    # delegate so the codec class stays focused on parse/render.

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect FortiOS CLI.

        Signals:
            * ``#config-version=`` banner on the first line (unique)
            * ``config system global`` stanza header
            * ``config/edit/set/next/end`` 5-keyword grammar presence
        """
        # XML / JSON shape — shared helper tolerates leading shell-echo
        # / banner framing so real captures don't bypass the guard.
        if detect_input_shape(raw_prefix) is not None:
            return None
        if raw_prefix.startswith("#config-version="):
            return (98, "FortiOS '#config-version=' banner present")
        hits = 0
        if re.search(r"^config\s+system\s+global\s*$",
                     raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(r"^config\s+system\s+interface\s*$",
                     raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(r"^\s*edit\s+\"?\S+\"?\s*$",
                     raw_prefix, re.MULTILINE):
            hits += 1
        if re.search(r"^\s*(next|end)\s*$", raw_prefix, re.MULTILINE):
            hits += 1
        if hits >= 3:
            return (92, f"{hits} FortiOS grammar markers present")
        if hits == 2:
            return (75, "partial FortiOS grammar match")
        return None
