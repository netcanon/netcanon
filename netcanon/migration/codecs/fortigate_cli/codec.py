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
    "_parse_blocks",
    "_prefix_to_mask",
    "_mask_to_prefix",
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
            "/interfaces/interface/dhcp-client-v6",          # set ip6-mode dhcp
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
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
            "/aaa/authentication/users/user/config/username",
            "/aaa/authentication/users/user/config/password",
            "/aaa/authentication/users/user/config/role",
        ],
        lossy=[
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
        ],
        unsupported=[
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
            # -- Ship-before-wire (v0.2.0) -- VRRP / anycast / per-VRF static routes --
            UnsupportedPath(
                path="/interfaces/interface/vrrp-groups/group",
                reason=(
                    "VRRP / HSRP / CARP redundancy groups parse-and-"
                    "ignore in v1.  CanonicalVRRPGroup schema exists; "
                    "wire-up scheduled for v0.2.0 Wave B (see "
                    "docs/v0.2.0-planning/01-vrrp-canonical/)."
                ),
            ),
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
