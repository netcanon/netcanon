"""
``VyOSCodec`` — bidirectional codec for VyOS ``config.boot`` /
``show configuration`` curly-brace text.

Targets the VyOS router/firewall NOS (Debian-derived; the OSS Vyatta
successor) on VyOS 1.3 / 1.4 / rolling.  VyOS stores its configuration
as a JunOS-style **curly-brace tree** — distinct from both the
line-oriented CLI of the other text codecs AND the Junos ``set``-form
the ``juniper_junos`` codec consumes (that codec keys off ``set `` lines
and ``ge-/xe-/et-`` interface names, neither of which appears in a VyOS
``config.boot``; see :meth:`VyOSCodec.probe`).

Module layout mirrors the ``cisco_nxos`` / ``aruba_aoscx`` post-split shape:

* ``codec.py`` (this file) — the class with metadata / capabilities /
  probe / port-name delegates.
* ``parse.py`` — brace-stack walker over VyOS config text.
* ``render.py`` — canonical tree → VyOS ``config.boot`` text.
* ``port_names.py`` — cross-vendor port-name bridge (Linux-style
  ``ethN`` / ``lo`` / ``bondN`` device names).

``iter_xpaths`` reuses ``_walk_canonical`` from
:mod:`netcanon.migration.codecs.cisco_iosxe_cli.codec` — VyOS introduces
no new canonical xpaths in Phase 1.

This codec lands in phases (Tier-1 first, mirroring the ``aruba_aoscx``
cadence).  **Phase 1**: ``system host-name``; interfaces (``ethernet``
/ ``loopback`` / ``dummy`` with ``address`` IPv4+IPv6 CIDR / ``dhcp`` /
``description`` / ``disable`` / ``mtu``); ``vif`` VLAN sub-interfaces;
and ``protocols static`` routes.  **Phase 2**: ``system login user``
local users (name + ``authentication encrypted-password``); ``system``
/ ``service`` ``ntp`` servers; and ``bonding bondN`` LAGs (``mode
802.3ad`` → LACP, members via both the 1.4 ``member interface`` form and
the legacy ``bond-group`` form).  **Phase 3**: ``service snmp`` (v1/v2c
community + ``location`` / ``contact`` + v3 USM users) and VRF (``vrf
name <X> { table <N> }`` routing instances + the per-interface ``vrf
<X>`` binding).  **Phase 4** flipped ``certainty`` to ``certified``
against a real-capture corpus of VyOS 1.4 ``config.boot`` files from the
MIT-licensed ``cisagov/prescup-challenges`` source (6 configs spanning
IPv4/OSPF + IPv6/BGP families).  **Phase 5** (this commit) adds
``interfaces vxlan vxlanN`` netdevs (one VNI each — ``vni`` / source /
``group`` or ``remote`` / ``port``) + block-form NTP servers, real-
validated against a 2-config ``zhouleyan/wcni-kind`` (Apache-2.0) VXLAN
tunnel pair.  **Phase 6** adds *set-form* input (``show configuration
commands``): :func:`~netcanon.migration.codecs.vyos.parse._setform_to_brace`
converts ``set <path> [value]`` lines to the equivalent curly-brace text up
front, so the brace-stack walker runs unchanged (mirroring the
``juniper_junos`` block-form→set-form front-end).  The probe disambiguates
VyOS set-form from Junos set-form (which the ``juniper_junos`` codec owns).
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
class VyOSCodec(CodecBase):
    """Bidirectional codec for VyOS ``config.boot`` curly-brace text."""

    name: ClassVar[str] = "vyos"
    version_hint: ClassVar[str | None] = "1.3/1.4"
    input_format: ClassVar[str] = "cli-vyos"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the contents of `/config/config.boot`, the output of "
        "`show configuration` (curly-brace), or `show configuration "
        "commands` (set-form) from a VyOS router.  VyOS is the OSS "
        "Vyatta-successor NOS.  Both grammars are accepted; VyOS set-form "
        "is distinct from Juniper's — use the `juniper_junos` codec for "
        "Juniper devices."
    )
    sample_input: ClassVar[str] = (
        "interfaces {\n"
        "    ethernet eth0 {\n"
        "        address 192.0.2.1/30\n"
        "        description \"uplink\"\n"
        "    }\n"
        "    ethernet eth1 {\n"
        "        vif 100 {\n"
        "            address 10.0.100.1/24\n"
        "        }\n"
        "    }\n"
        "    loopback lo {\n"
        "        address 192.0.2.255/32\n"
        "    }\n"
        "}\n"
        "protocols {\n"
        "    static {\n"
        "        route 0.0.0.0/0 {\n"
        "            next-hop 192.0.2.2 {\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "}\n"
        "system {\n"
        "    host-name vyos-router\n"
        "}\n"
        "// vyos-config-version: \"system@27:interfaces@29\"\n"
    )
    output_extension: ClassVar[str] = "conf"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="vyos",
        vendor_id="vyos",
        version_range="1.3/1.4",
        device_classes=[DeviceClass.router, DeviceClass.firewall],
        supported=[
            # System
            "/system/hostname",
            # Interfaces — name + basic L3 (Phase 1; incl. vif VLAN
            # sub-interfaces modelled as ethN.<vid> interfaces).
            "/interfaces/interface/name",
            "/interfaces/interface/config/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",
            "/interfaces/interface/ipv6/address/prefix-length",
            "/interfaces/interface/dhcp-client",
            "/interfaces/interface/dhcp-client-v6",
            # Static routes (default VRF)
            "/routing/static-route",
            # ── Phase 2: local users (`system login user`) ──
            "/local-users/user/name",
            "/local-users/user/role",
            "/local-users/user/hashed-password",
            # ── Phase 2: NTP servers (`system`/`service` ntp) ──
            "/system/ntp-server",
            # ── Phase 2: bonding LAGs (`interfaces bonding bondN`) ──
            "/lags/lag/name",
            "/lags/lag/members",
            "/interfaces/interface/lag-member-of",
            # ── Phase 3: SNMP (`service snmp`) — v1/v2c + v3 USM ──
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/v3-user",
            # ── Phase 3: VRF routing-instances (`vrf name <X>`) + the
            # per-interface binding (`interfaces ethernet ethN { vrf X }`).
            "/routing-instances/instance/name",
            "/interfaces/interface/config/vrf",
            # ── Phase 5: VXLAN netdevs (`interfaces vxlan vxlanN`) — one
            # VNI per netdev (vni + source + mcast/flood + udp port).
            "/vxlan-vnis/vni",
            "/vxlan-vnis/mcast-group",
            "/vxlan-vnis/flood-list",
            "/vxlan-vnis/udp-port",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "VyOS declares no IANA ifType; the codec infers it "
                    "from the interface-name shape (`ethN` -> "
                    "ethernetCsmacd, `lo`/`dumN` -> softwareLoopback, "
                    "`bondN` -> ieee8023adLag).  Best-effort."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/system/raw-sections/version-banner",
                reason=(
                    "The `// vyos-config-version` component-version trailer "
                    "+ the `service` / `system` management-plane blocks not "
                    "yet modelled (SSH / syslog / DNS) are discarded on parse "
                    "and a synthesised trailer is emitted on render.  The "
                    "operator must re-apply those services on the target."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/local-users/user/privilege-level",
                reason=(
                    "VyOS `system login user` accounts have no numeric "
                    "privilege level in the common case (configured users "
                    "have full operator/admin access); the codec maps every "
                    "login user to privilege 15 / role `admin`.  The "
                    "`encrypted-password` hash round-trips verbatim "
                    "same-vendor; cross-vendor migration requires re-keying."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/lags/lag/mode",
                reason=(
                    "VyOS bonding `mode 802.3ad` (LACP) maps to `active`; the "
                    "non-LACP modes (`active-backup` / `balance-rr` / "
                    "`balance-xor` / ...) collapse to `static` (the specific "
                    "balancing algorithm is dropped — re-select it on the "
                    "target)."
                ),
                severity="warn",
            ),
            # ── Phase 3: SNMP v3 USM keys + engineID, VRF table id ──
            LossyPath(
                path="/snmp/v3-user/auth-passphrase",
                reason=(
                    "VyOS stores the v3 USM auth / privacy keys as an opaque "
                    "`encrypted-password` blob; it round-trips verbatim "
                    "same-vendor but cross-vendor migration requires re-keying "
                    "on the target (hashes are salted with vendor-specific "
                    "constants).  Plaintext keys are never accepted."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/snmp/v3-user/engine-id",
                reason=(
                    "VyOS declares a single config-wide `engineid` for the "
                    "whole SNMP agent; the canonical model carries the "
                    "engineID per-user, so the codec maps the one VyOS value "
                    "onto every v3 user (and emits a single `engineid` on "
                    "render when the users share one)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/routing-instances/instance/table",
                reason=(
                    "VyOS requires a numeric `table <id>` on every `vrf name "
                    "<X>`; the canonical RoutingInstance carries no table "
                    "number, so the codec synthesises a deterministic id "
                    "(100 + sort-index) on render.  The original table id is "
                    "not preserved."
                ),
                severity="warn",
            ),
            # ── Phase 5: VXLAN ──
            LossyPath(
                path="/vxlan-vnis/source-interface",
                reason=(
                    "VyOS states the VTEP source as `source-address <ip>` (or "
                    "`source-interface <if>`) on the vxlan netdev; the opaque "
                    "string round-trips same-vendor but a cross-vendor source "
                    "(e.g. `Loopback0`) is re-emitted verbatim and may need an "
                    "operator port-rename."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/vxlan-vnis/vlan-id",
                reason=(
                    "VyOS models ONE VNI per `vxlan vxlanN` netdev with no "
                    "VLAN on the device (the L2 VLAN binding lives on a "
                    "separate `bridge`); the required canonical `vlan_id` is "
                    "synthesised from the VNI and the netdev name is "
                    "regenerated `vxlan<index>` on render — both deterministic "
                    "(same-vendor round-trip stable, cross-vendor advisory)."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            # VLAN database — VyOS has no top-level VLAN table.
            UnsupportedPath(
                path="/vlans/vlan/id",
                reason=(
                    "VyOS has no top-level VLAN database; 802.1Q VLANs are "
                    "modelled as `vif <vid>` sub-interfaces (rendered as "
                    "`ethN.<vid>` CanonicalInterfaces), which ARE supported."
                ),
            ),
            # VRF: the `vrf name <X>` instances + per-interface binding
            # ARE supported (Phase 3); the per-VRF static-route table
            # (`vrf name <X> { protocols static route ... }`) stays
            # deferred past the Phase-3 wire-up.
            UnsupportedPath(
                path="/routing/static-route/vrf",
                reason=(
                    "VyOS per-VRF static routes (`vrf name <X> { protocols "
                    "static route ... }`) are deferred past the Phase-3 VRF "
                    "wire-up; the `vrf name` instances + per-interface "
                    "binding ARE supported."
                ),
            ),
            # ── Phase 5: VXLAN — the L2 VNI binding IS supported; the EVPN
            # control-plane (per-VNI RD/RT) + symmetric-IRB L3VNI are
            # Tier-3 / out of scope for the per-netdev model.
            UnsupportedPath(
                path="/vxlan-vnis/l2vni-route-target",
                reason=(
                    "VyOS attaches EVPN per-VNI RD/route-target under "
                    "`protocols bgp ... address-family l2vpn-evpn` (Tier-3, "
                    "dropped) — the L2 VLAN<->VNI binding is supported but the "
                    "control-plane RD/RT is not auto-translated."
                ),
            ),
            UnsupportedPath(
                path="/routing-instances/instance/l3-vni",
                reason=(
                    "VyOS symmetric-IRB L3VNI (a VNI bound to a VRF for "
                    "inter-subnet routing) is out of scope for the Phase-5 "
                    "per-netdev L2-VNI model."
                ),
            ),
            # Tier-3 — never auto-translatable.
            UnsupportedPath(
                path="/routing-protocols/bgp",
                reason=(
                    "VyOS `protocols bgp` is Tier-3 — captured for the "
                    "dropped_tier3_sections banner but never auto-rendered "
                    "cross-vendor."
                ),
            ),
            UnsupportedPath(path="/routing-protocols/ospf", reason="Tier-3."),
            UnsupportedPath(
                path="/nat",
                reason=(
                    "VyOS `nat source`/`nat destination` is Tier-3 — NAT "
                    "semantics are too platform-specific to auto-translate."
                ),
            ),
            UnsupportedPath(
                path="/firewall",
                reason=(
                    "VyOS `firewall` rule-sets are Tier-3 — auto-translating "
                    "firewall policy across vendors risks subtly-permissive "
                    "rules.  Operator authors firewall policy manually."
                ),
            ),
            UnsupportedPath(
                path="/access-list/extended",
                reason="VyOS `policy` route-maps / prefix-lists are Tier-3.",
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
        from ..._tier3_detection import detect_tier3_sections_vyos
        from .parse import _setform_to_brace

        # Normalise set-form → curly-brace once so the Tier-3 banner
        # detector (curly-shape patterns) fires for set-form input too;
        # idempotent on curly-brace input.
        brace = _setform_to_brace(raw)
        intent = parse_intent(brace)
        intent.dropped_tier3_sections = detect_tier3_sections_vyos(brace)
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
        """Detect VyOS configuration text — curly-brace ``config.boot`` OR
        set-form (``show configuration commands``).

        **Curly-brace.**  Primary marker: the ``// vyos-config-version``
        trailer (present in every saved ``config.boot``; unambiguously
        VyOS).  Structural fallback (no trailer — e.g. a ``show
        configuration`` paste): a curly-brace tree with VyOS-specific
        markers (``interfaces {`` + ``ethernet ethN {`` + ``disable`` /
        ``loopback lo``).  ``;``-terminated leaves veto (that is a Junos
        curly capture; VyOS uses bare newlines).

        **Set-form** (``set `` lines).  Claimed only when a Junos-disjoint
        VyOS marker is present (Linux ``ethernet ethN`` / ``bonding bondN``
        / ``vxlan`` netdev names, top-level ``set service``, ``set
        protocols static route``, or ``set vrf name``).  Junos-defining
        markers (``set version``, ``ge-/xe-/…`` interface names,
        ``routing-options`` / ``routing-instances`` / ``set snmp`` / ``set
        vlans``) veto the match so the ``juniper_junos`` codec keeps its
        set-form.  (``set protocols bgp|ospf|…`` is deliberately NOT a veto
        — VyOS hosts routing protocols under ``protocols`` too.)
        """
        if detect_input_shape(raw_prefix) is not None:
            return None

        if "vyos-config-version" in raw_prefix.lower():
            return (99, "VyOS config-version trailer present")

        # Set-form candidate — any `set ` line routes here.
        if re.search(r"^\s*set\s+\S", raw_prefix, re.MULTILINE):
            return cls._probe_setform(raw_prefix)

        # ── Curly-brace structural fallback (no `set ` lines) ──
        # Veto: Junos curly-form — `;`-terminated leaves.  VyOS NEVER
        # terminates a leaf with `;` (its grammar uses bare newlines), so
        # even a single `;`-ended line means this is a Junos
        # `show configuration` capture, not VyOS.
        if re.search(r";\s*$", raw_prefix, re.MULTILINE):
            return None

        markers = 0
        if re.search(r"^\s*interfaces\s*\{", raw_prefix, re.MULTILINE):
            markers += 1
        if re.search(
            r"^\s+ethernet\s+eth\d+\s*\{", raw_prefix,
            re.MULTILINE | re.IGNORECASE,
        ):
            markers += 1
        if re.search(
            r"^\s+(?:loopback\s+lo|dummy\s+dum\d+|bonding\s+bond\d+)\s*\{",
            raw_prefix, re.MULTILINE | re.IGNORECASE,
        ):
            markers += 1
        if re.search(r"^\s+disable\s*$", raw_prefix, re.MULTILINE):
            markers += 1
        if re.search(
            r"^\s+host-name\s+\S", raw_prefix, re.MULTILINE | re.IGNORECASE,
        ):
            markers += 1

        if markers >= 2:
            return (90, f"VyOS curly-brace structural markers ({markers})")
        # A lone ``interfaces {`` is not VyOS-specific enough to claim
        # (Junos curly shares it); require >= 2 markers or the trailer.
        return None

    #: Junos-defining set-form markers — their presence means the capture
    #: belongs to the ``juniper_junos`` codec, not VyOS.  The Junos media-
    #: interface alternatives require a trailing ``-`` / digit so they do
    #: not false-match VyOS ``loopback`` / ``ethernet`` names.  Note: ``set
    #: protocols bgp|ospf|isis|…`` is deliberately NOT a veto — VyOS hosts
    #: routing protocols under ``protocols`` too, so it is shared syntax.
    _JUNOS_SETFORM_VETO: ClassVar[tuple[str, ...]] = (
        r"^set version \d",
        r"^set interfaces (?:ge-|xe-|et-|fe-|em\d|me\d|fxp\d|ae\d|lo\d|irb)",
        r"^set routing-options\b",
        r"^set routing-instances\b",
        r"^set (?:snmp|vlans|policy-options|security|chassis|"
        r"forwarding-options|class-of-service)\b",
    )

    @classmethod
    def _probe_setform(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Score a ``set ``-bearing prefix as VyOS set-form, or return
        None (vetoing to ``juniper_junos``) when Junos markers are seen."""
        for pat in cls._JUNOS_SETFORM_VETO:
            if re.search(pat, raw_prefix, re.MULTILINE):
                return None

        markers = strong = 0
        if re.search(
            r"^set interfaces (?:ethernet eth|bonding bond|dummy dum|"
            r"loopback lo|vxlan vxlan|bridge br|wireguard wg|tunnel tun|"
            r"pppoe pppoe|geneve gnv)\b",
            raw_prefix, re.MULTILINE,
        ):
            markers += 1
            strong += 1
        if re.search(r"^set service \S", raw_prefix, re.MULTILINE):
            markers += 1
            strong += 1
        if re.search(
            r"^set protocols static route6?\b", raw_prefix, re.MULTILINE
        ):
            markers += 1
            strong += 1
        if re.search(r"^set vrf name \S", raw_prefix, re.MULTILINE):
            markers += 1
            strong += 1
        if re.search(
            r"^set system (?:host-name|name-server|time-zone|login|"
            r"domain-name|domain-search)\b",
            raw_prefix, re.MULTILINE,
        ):
            markers += 1

        # Require >= 1 Junos-disjoint marker so an ambiguous
        # `set system …`-only snippet is not mis-claimed (it stays
        # undetected; the operator selects the codec manually).
        if strong >= 1:
            score = 89 if markers >= 2 else 80
            return (score, f"VyOS set-form grammar markers ({markers})")
        return None
