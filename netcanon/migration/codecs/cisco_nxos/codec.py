"""
``CiscoNXOSCodec`` — bidirectional codec for Cisco NX-OS
``show running-config`` text.

Targets the Nexus 3000 / 5000 / 7000 / 9000 series and the Nexus 9000V
virtual platform.  Distinct vendor identity from ``cisco_iosxe`` — a
different CLI grammar, a different ``CapabilityMatrix``, and a different
render path (use the ``cisco_iosxe_cli`` codec for Catalyst / ASR / ISR
captures).

Module layout mirrors the ``cisco_iosxe_cli`` post-split shape:

* ``codec.py`` (this file) — the class with metadata / capabilities /
  probe / port-name delegates.  ``parse()`` / ``render()`` are one-line
  delegators to the sibling modules.
* ``parse.py`` — line-scan + per-stanza dispatch over NX-OS text.
* ``render.py`` — canonical tree → NX-OS running-config text.
* ``port_names.py`` — cross-vendor port-name bridge.

``iter_xpaths`` reuses ``_walk_canonical`` from
:mod:`netcanon.migration.codecs.cisco_iosxe_cli.codec` — NX-OS
introduces no new canonical xpaths in Phase 1, so the shared walker
yields exactly the right set.

This codec lands in four phases (see
``docs/v0.2.0-planning/03-nxos-codec/``).  **All four phases are
complete**: Phase 1 (hostname, basic-L3 interfaces, VLANs, ``vrf
context`` name+description, default-VRF static routes), Phase 2a (L2
switchport with the NX-OS default-flip, VLAN-centric port projection,
LAG / ``channel-group`` membership), Phase 2b (SNMPv2c community + v3
USM users + local-users), Phase 2c (HSRP via
``CanonicalVRRPGroup(mode="hsrp")``), Phase 3 (VRF RD / route-target +
per-VRF static routes nested inside ``vrf context``), and Phase 4
(VXLAN-EVPN — ``vlan N / vn-segment`` VLAN↔VNI bindings, the ``interface
nve1`` VTEP source-interface, and per-VRF L3VNI ``vrf context X / vni
N``, plus the ``vtep`` PortKind).  Only the T2 anycast-gateway surface
remains ``unsupported`` in the matrix below.  ``certainty`` is
``best_effort``; it reaches ``certified`` once a real-capture corpus
across two OS versions lands.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Iterable

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
class CiscoNXOSCodec(CodecBase):
    """Bidirectional codec for Cisco NX-OS ``show running-config`` output.

    Separate ``vendor_id=cisco_nxos`` from the IOS-XE codecs — its own
    vendor row in ``definitions/vendors.yaml``.
    """

    name: ClassVar[str] = "cisco_nxos"
    version_hint: ClassVar[str | None] = "9.x / 10.x"
    input_format: ClassVar[str] = "cli-nxos"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "best_effort"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the output of `show running-config` from a Cisco Nexus "
        "switch.  NX-OS is Cisco's data-center NOS; its grammar is "
        "distinct from IOS-XE (use the `cisco_iosxe_cli` codec for "
        "Catalyst / ASR / ISR captures)."
    )
    sample_input: ClassVar[str] = (
        "!Command: show running-config\n"
        "version 9.3(11) Bios:version\n"
        "hostname Nexus-Leaf1\n"
        "vdc Nexus-Leaf1 id 1\n"
        "\n"
        "feature interface-vlan\n"
        "\n"
        "vlan 1,10\n"
        "vlan 10\n"
        "  name PROD\n"
        "\n"
        "vrf context management\n"
        "\n"
        "interface Vlan10\n"
        "  no shutdown\n"
        "  ip address 10.10.10.1/24\n"
        "\n"
        "interface Ethernet1/1\n"
        "  no shutdown\n"
        "  ip address 192.0.2.1/31\n"
        "\n"
        "interface mgmt0\n"
        "  vrf member management\n"
        "  ip address 192.0.2.10/24\n"
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="cisco_nxos",
        vendor_id="cisco_nxos",
        version_range="9.x+",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[
            # System
            "/system/hostname",
            # Interfaces — name + basic L3
            "/interfaces/interface/name",
            "/interfaces/interface/config/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",
            "/interfaces/interface/ipv6/address/prefix-length",
            "/interfaces/interface/vrf",
            # Interfaces — L2 switchport + LAG membership (Phase 2a)
            "/interfaces/interface/switchport-mode",
            "/interfaces/interface/access-vlan",
            "/interfaces/interface/trunk-allowed-vlans",
            "/interfaces/interface/trunk-native-vlan",
            "/interfaces/interface/lag-member-of",
            # VLANs (id/name + Phase-2a port projection)
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/vlans/vlan/tagged-ports",
            "/vlans/vlan/untagged-ports",
            # LAGs (Phase 2a)
            "/lags/lag/name",
            "/lags/lag/members",
            "/lags/lag/mode",
            # SNMP (Phase 2b) — v2c community + v3 USM
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            # Local users (Phase 2b)
            "/local-users/user/name",
            "/local-users/user/role",
            "/local-users/user/hashed-password",
            # VRF (name + description + Phase-3 RD / route-target)
            "/routing-instances/instance/name",
            "/routing-instances/instance/description",
            "/routing-instances/instance/route-distinguisher",
            "/routing-instances/instance/rt-imports",
            "/routing-instances/instance/rt-exports",
            # Static routes (default VRF + Phase-3 per-VRF)
            "/routing/static-route",
            "/routing/static-route/vrf",
            # VXLAN-EVPN (Phase 4) — L2 VLAN↔VNI + VTEP + L3VNI
            "/vxlan-vnis/vni",
            "/vxlan-vnis/source-interface",
            "/vxlan-vnis/udp-port",
            "/vxlan-vnis/mcast-group",
            "/vxlan-vnis/flood-list",
            "/routing-instances/instance/l3-vni",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "NX-OS interface-type is inferred from the name "
                    "prefix (Ethernet -> ethernetCsmacd, loopback -> "
                    "softwareLoopback, Vlan -> l3ipvlan, port-channel -> "
                    "ieee8023adLag, nve -> tunnel, mgmt -> "
                    "ethernetCsmacd).  Inference is best-effort and may "
                    "not catch every IANA type."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/system/raw-sections/vdc",
                reason=(
                    "NX-OS `vdc <name> id N / limit-resource ...` is N7K "
                    "virtualisation grammar with no canonical primitive.  "
                    "Phase 1 discards the source block and synthesises a "
                    "default single-VDC `vdc <hostname> id 1` wrapper on "
                    "render; verbatim same-vendor preservation in "
                    "raw_sections lands in a later phase."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/system/raw-sections/features",
                reason=(
                    "NX-OS `feature <name>` declarations are derived on "
                    "render from the canonical-tree shape (any SVI -> "
                    "`feature interface-vlan`, etc).  Source `feature` "
                    "lines that aren't motivated by a canonical surface "
                    "(e.g. `feature scp-server`, `feature telnet`) are "
                    "dropped; the operator must re-authorise management-"
                    "API features on the target device."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/local-users/user/privilege-level",
                reason=(
                    "NX-OS uses a named `role` (network-admin / "
                    "network-operator / custom) instead of a numeric "
                    "privilege.  The codec maps network-admin / vdc-admin "
                    "-> 15 and everything else -> 1, so cross-vendor "
                    "renderers expecting numeric privilege round-trip "
                    "non-admin roles as privilege 1.  The named role "
                    "round-trips losslessly same-vendor."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/auth-passphrase",
                reason=(
                    "NX-OS 10.x introduced the `localizedV2key` digest "
                    "format; the v1 codec normalises to the older "
                    "`localizedkey` form on render.  Operators migrating "
                    "between OS versions or vendors must re-key SNMPv3 "
                    "users on the target device."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/engine-id",
                reason=(
                    "NX-OS emits engineID in colon-decimal "
                    "(`128:0:0:9:...`); cross-vendor sources typically "
                    "use hex.  Preserved verbatim same-vendor; "
                    "cross-vendor render may emit a syntactically-valid "
                    "but functionally-incorrect engineID requiring "
                    "re-keying."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group",
                reason=(
                    "NX-OS expresses FHRP as HSRP (`interface VlanN / "
                    "hsrp N / ip <vip> / priority / preempt`).  The codec "
                    "renders EVERY CanonicalVRRPGroup as an `hsrp` block "
                    "regardless of the source `mode` discriminator, so a "
                    "cross-vendor VRRP / CARP group normalises to HSRP on "
                    "NX-OS — the operator's redundancy intent for the "
                    "virtual IP survives, but the wire protocol changes.  "
                    "Same-vendor HSRP round-trips losslessly.  Sub-second "
                    "timers, virtual-MAC, and track objects are not "
                    "modelled in v1."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance/route-distinguisher",
                reason=(
                    "NX-OS supports `rd auto` (deriving the RD from the "
                    "BGP ASN + VRF VNI) as well as an explicit "
                    "`rd <asn>:<nn>`.  The codec preserves `auto` verbatim "
                    "as a sentinel; cross-vendor renderers that don't "
                    "recognise it must synthesise an explicit RD or emit "
                    "nothing.  An explicit RD round-trips losslessly."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance/rt-imports",
                reason=(
                    "NX-OS `route-target both <rt> evpn` advertises the RT "
                    "in both the IPv4-unicast AND the L2VPN-EVPN address-"
                    "family.  The `evpn` discriminator does not round-trip "
                    "cross-vendor — the RT value is preserved but the "
                    "address-family scope reverts to IPv4 unicast on a "
                    "cross-vendor target.  Same-vendor RTs round-trip "
                    "(the `both`/import/export split is reconstructed)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vxlan-vnis/vni",
                reason=(
                    "NX-OS `interface nve1 / member vni N` per-VNI "
                    "sub-flags (`suppress-arp`, `ingress-replication "
                    "protocol bgp`) do not round-trip — the codec emits "
                    "the modern BGP-EVPN head-end-replication shape on "
                    "every render (constant `host-reachability protocol "
                    "bgp`).  Source configs using legacy flood-and-learn "
                    "or alternate ingress-replication protocols normalise "
                    "to the default.  The VLAN↔VNI binding itself "
                    "round-trips via `vlan N / vn-segment`."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/evpn-type5-routes/route",
                reason=(
                    "EVPN Type-5 (IP-prefix) announcements are modelled as "
                    "a VRF property via `CanonicalRoutingInstance.l3_vni` "
                    "(`vrf context X / vni N` + `interface nve1 / member "
                    "vni N associate-vrf`), not per-prefix records.  The "
                    "codec does not enumerate per-prefix "
                    "`CanonicalEvpnType5Route` entries (no route-map / "
                    "prefix-filter parsing in v1); the supported canonical "
                    "alternative is the l3_vni VRF binding."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            # ── Anycast-gateway — T2 surface, deferred beyond Phase 4 ──
            UnsupportedPath(
                path="/anycast-gateway",
                reason=(
                    "Anycast-gateway-mac (`fabric forwarding "
                    "anycast-gateway-mac`) + the per-SVI fabric-forwarding "
                    "mode are the T2 canonical surface; deferred beyond "
                    "Phase 4 (VXLAN-EVPN shipped without the anycast SVI "
                    "slice)."
                ),
            ),
            # ── Tier-3 — never auto-translatable ──
            UnsupportedPath(
                path="/routing-protocols/bgp",
                reason=(
                    "NX-OS `router bgp <asn>` is Tier-3 — captured for "
                    "the dropped_tier3_sections notification banner but "
                    "never auto-rendered cross-vendor."
                ),
            ),
            UnsupportedPath(path="/routing-protocols/ospf", reason="Tier-3."),
            UnsupportedPath(path="/routing-protocols/eigrp", reason="Tier-3."),
            UnsupportedPath(path="/routing-protocols/isis", reason="Tier-3."),
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
                reason="Tier-3 (mirrors cisco_iosxe_cli).",
            ),
            UnsupportedPath(path="/access-list/ipv6", reason="Tier-3."),
            UnsupportedPath(
                path="/firewall",
                reason=(
                    "NX-OS does not host a stateful firewall; declared "
                    "unsupported for consistency with the cross-vendor "
                    "capability surface."
                ),
            ),
            UnsupportedPath(
                path="/nat",
                reason="NX-OS does not host typical edge NAT.",
            ),
            UnsupportedPath(
                path="/qos",
                reason=(
                    "QoS (`class-map type qos` / `policy-map type qos` / "
                    "`service-policy`) is Tier-3 — DC-grade QoS is too "
                    "platform-specific to auto-translate."
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
        from ..._tier3_detection import detect_tier3_sections_nxos

        intent = parse_intent(raw)
        # Surface Tier-3 stanza headers the parser deliberately drops
        # (BGP / OSPF / EIGRP / ACLs / route-maps / QoS).  Notification-
        # only — never read by any render-side code.
        intent.dropped_tier3_sections = detect_tier3_sections_nxos(raw)
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
        """Detect Cisco NX-OS ``show running-config`` text.

        Primary marker: ``!Command: show running-config`` is the first
        line of every modern NX-OS ``show running-config`` and is
        unambiguously NX-OS (IOS-XE classic emits ``Building
        configuration...`` / ``Current configuration :`` instead, which
        we treat as a hard NOT-NX-OS signal).

        Without the banner we fall back to NX-OS-SPECIFIC structural
        markers (`feature <name>` / `vdc <name> id N` / `vrf context` /
        `interface nve1`).  The bare CIDR-address form is only a bonus
        on top of those — never sufficient alone — so the probe does not
        steal captures from the CIDR-using Arista / Aruba codecs.
        """
        lowered = raw_prefix.lower()

        # Reject XML / JSON early (shared shape helper).
        if detect_input_shape(raw_prefix) is not None:
            return None

        # IOS-XE classic banners are a hard NOT-NX-OS signal.
        if "building configuration" in lowered:
            return None
        if "current configuration :" in lowered:
            return None

        # NX-OS-specific structural markers.
        nxos_specific = 0
        if re.search(r"^feature\s+\S+", raw_prefix, re.MULTILINE | re.IGNORECASE):
            nxos_specific += 1
        if re.search(r"^vdc\s+\S+\s+id\s+\d+", raw_prefix,
                     re.MULTILINE | re.IGNORECASE):
            nxos_specific += 1
        if re.search(r"^vrf\s+context\s+\S+", raw_prefix,
                     re.MULTILINE | re.IGNORECASE):
            nxos_specific += 1
        if re.search(r"^interface\s+nve1\b", raw_prefix,
                     re.MULTILINE | re.IGNORECASE):
            nxos_specific += 1

        if "!command: show running-config" in lowered:
            if nxos_specific >= 1:
                return (98, "NX-OS !Command banner + structural markers")
            # Banner alone is still unambiguous, but require a CIDR
            # interface address as a minimal structural sanity check so
            # a bare banner pasted with non-NX-OS body doesn't claim it.
            if re.search(r"^\s+ip\s+address\s+\d+\.\d+\.\d+\.\d+/\d+",
                         raw_prefix, re.MULTILINE | re.IGNORECASE):
                return (98, "NX-OS !Command banner + CIDR addressing")
            return (90, "NX-OS !Command banner")

        # No banner — lean on NX-OS-specific markers only.
        if nxos_specific >= 2:
            return (90, f"NX-OS structural markers ({nxos_specific})")
        if nxos_specific == 1:
            return (70, "one NX-OS structural marker")
        return None
