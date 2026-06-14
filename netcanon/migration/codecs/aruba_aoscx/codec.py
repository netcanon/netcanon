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

This codec lands in phases (Tier-1 first, mirroring the ``cisco_nxos``
cadence).  **Phase 1**: hostname, basic-L3 interfaces (description /
admin-state / mtu / IPv4 + IPv6 CIDR / ``vrf attach``), VLANs (id + name
+ description), top-level ``vrf`` declarations (name), and default-VRF
static routes.  **Phase 2** (this commit): the L2 switchport surface
(``no routing`` + ``vlan access`` / ``vlan trunk native`` / ``vlan trunk
allowed``) with VLAN-centric port projection, LAGs (``interface lag N``
+ per-port ``lag N`` + ``lacp mode``), and local users (``user <name>
group <group> password ciphertext <blob>``).  **Phase 2b** (this
commit): SNMP — v2c community, ``system-location`` / ``system-contact``,
and ``snmpv3 user`` USM users (``auth-pass`` / ``priv-pass`` ciphertext).
``certainty`` is ``best_effort`` — synthetically round-trip-validated
across the supported surface; no real-capture corpus is wired yet (the
certified tier follows in a later phase).  Later phases add the
``active-gateway`` anycast surface, VSX, and VXLAN / EVPN.
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
class ArubaAOSCXCodec(CodecBase):
    """Bidirectional codec for Aruba AOS-CX ``show running-config`` output.

    Separate ``vendor_id=aruba_aoscx`` from ``aruba_aoss`` — its own
    vendor row in ``netcanon/migration/vendors/aruba_aoscx.yaml``.
    """

    name: ClassVar[str] = "aruba_aoscx"
    version_hint: ClassVar[str | None] = "10.x"
    input_format: ClassVar[str] = "cli-aoscx"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "best_effort"
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
            "/interfaces/interface/config/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",
            "/interfaces/interface/ipv6/address/prefix-length",
            "/interfaces/interface/vrf",
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
            "/lags/lag/mode",
            # ── Phase 2: local users (`user X group G password ciphertext`) ──
            "/local-users/user/name",
            "/local-users/user/role",
            "/local-users/user/hashed-password",
            # ── Phase 2b: SNMP (v2c community + v3 USM) ──
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/v3-user",
        ],
        lossy=[
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
                    "AOS-CX SNMPv3 auth/priv keys are `ciphertext` blobs "
                    "encrypted with the device key (portable same-device "
                    "only).  Cross-vendor / cross-device migration emits "
                    "the blob verbatim under `ciphertext`, but the operator "
                    "must re-key the SNMPv3 user on the target; the "
                    "`plaintext` key form is normalised to `ciphertext` on "
                    "render."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
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
            # ── FHRP / active-gateway anycast (later phase) ──
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group",
                reason=(
                    "AOS-CX VRRP (`vrrp <vrid> address-family` under an "
                    "SVI) is a later phase."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/ipv4/address/virtual-gateway-address",
                reason=(
                    "The AOS-CX `active-gateway ip` anycast-gateway "
                    "surface (the VSX/EVPN distributed gateway equivalent "
                    "of NX-OS DAG) is a later phase."
                ),
            ),
            UnsupportedPath(
                path="/interfaces/interface/ipv6/address/virtual-gateway-address",
                reason="IPv6 active-gateway anycast is a later phase.",
            ),
            UnsupportedPath(
                path="/anycast-gateway-mac",
                reason=(
                    "The chassis-wide `active-gateway mac` is a later "
                    "phase (companion to the active-gateway IP surface)."
                ),
            ),
            # ── VXLAN / EVPN (later phase) ──
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason=(
                    "VXLAN (`interface vxlan N` / `vni N` / `evpn`) is a "
                    "later phase."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/source-interface",
                reason="VXLAN VTEP source is a later phase (see /vxlan-vnis/vni).",
            ),
            UnsupportedPath(
                path="/routing-instances/instance/l3-vni",
                reason="EVPN L3VNI symmetric IRB is a later phase.",
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
