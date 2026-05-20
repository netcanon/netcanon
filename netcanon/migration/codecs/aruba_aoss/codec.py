"""
``ArubaAOSSCodec`` — 4th real codec, Session C of vendor-config-research.

See package ``__init__`` for scope and structural-quirks notes.

Module layout (post-split per the codecs/README.md split-codec
convention):

* ``codec.py`` (this file) — the ``ArubaAOSSCodec`` class with
  metadata (capabilities / classvars / probe / iter_xpaths /
  port-name delegates).  ``parse()`` and ``render()`` are two-line
  delegators to the corresponding functions in the sibling modules.
* ``parse.py`` — line-walker + per-stanza dispatchers that consume
  AOS-S ``show running-config`` text and produce :class:`CanonicalIntent`.
* ``render.py`` — canonical tree to AOS-S CLI text.
* ``port_names.py`` — cross-vendor port-name identity bridge
  (shared with the rename-modal orchestrator).
* ``_svi_absorption.py`` — single source of truth for the
  ``absorbs_svi_into_vlan`` capability flag.

Test-import symbols (``_format_port_list``, ``_parse_port_list``)
are re-exported here so ``tests/unit/migration/test_aruba_aoss.py``
doesn't need updating for the split.  Their canonical homes are
:mod:`.parse` and :mod:`.render`; this module's re-exports are
purely for backwards compatibility.
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
from ._svi_absorption import ABSORBS_SVI_INTO_VLAN
from .parse import _parse_port_list, parse_intent
from .render import _format_port_list, render_intent

# Re-export the internal helpers that tests pin against the codec's
# structural contract (see module docstring).
__all__ = [
    "ArubaAOSSCodec",
    "_format_port_list",
    "_parse_port_list",
]


@register
class ArubaAOSSCodec(CodecBase):
    """Codec for Aruba AOS-S ``show running-config`` text.

    Declares ``device_classes=[switch, router]`` — AOS-S ships
    primarily as L2 access switches but L3 features (routed ports,
    static routes) are in scope here.
    """

    name: ClassVar[str] = "aruba_aoss"
    version_hint: ClassVar[str | None] = "16.x"
    input_format: ClassVar[str] = "cli-aruba-aoss"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    #: AOS-S absorbs the SVI's L3 state into the VLAN stanza itself.
    #: Full explanation + list of participating code paths lives in
    #: :mod:`._svi_absorption`; the value is imported from there so
    #: the rule has a single source of truth.
    absorbs_svi_into_vlan: ClassVar[bool] = ABSORBS_SVI_INTO_VLAN
    description: ClassVar[str] = (
        "Paste the output of `show running-config` from an Aruba AOS-S "
        "(ProCurve / ArubaOS-Switch 16.x) device.  NOT the same as "
        "AOS-CX — CX uses a different codec."
    )
    sample_input: ClassVar[str] = (
        '; J9729A Configuration Editor; Created on release #WC.16.11\n'
        'hostname "sw-edge-01"\n'
        'snmp-server community "public" Operator\n'
        'vlan 1\n'
        '   name "DEFAULT_VLAN"\n'
        '   untagged 1-24\n'
        '   no ip address\n'
        '   exit\n'
        'vlan 10\n'
        '   name "USERS"\n'
        '   untagged 1-24\n'
        '   tagged 25-26\n'
        '   ip address 192.168.10.1/24\n'
        '   exit\n'
        'interface 1\n'
        '   name "Desk 1"\n'
        '   enable\n'
        '   exit\n'
        'ip default-gateway 192.168.10.254\n'
    )
    output_extension: ClassVar[str] = "cfg"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="aruba_aoss",
        vendor_id="aruba_aoss",
        version_range="16.x",
        device_classes=[DeviceClass.switch, DeviceClass.router],
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
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/vlans/vlan/tagged-ports",
            "/vlans/vlan/untagged-ports",
            "/routing/static-route",
            # Tier 2 — SNMP
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            "/snmp/v3-user",
            # Wave B (v0.2.0) — classic VRRP wire-up.  AOS-S nests
            # ``ip vrrp vrid N`` inside ``vlan N`` stanzas; canonical
            # attaches the group to the synthesised Vlan<N>
            # CanonicalInterface (see _svi_absorption.py).  Anycast
            # / HSRP / CARP paths remain unsupported below — AOS-S
            # has no native grammar for those.
            "/interfaces/interface/vrrp-groups/group",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/type",
                reason=(
                    "AOS-S does not declare IANA ifType; the codec "
                    "infers type from interface-name shape (bare "
                    "number -> ethernet, 'Trk' -> port-channel, "
                    "'Vlan' -> l3ipvlan)."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/dhcp-client-v6",
                reason=(
                    "AOS-S has no native IPv6 DHCPv6 / SLAAC client "
                    "configuration on routed interfaces — the canonical "
                    "dhcp_client_v6 field drops on render to AOS-S."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/tunnel-type",
                reason=(
                    "AOS-S is a campus L2/L3 codec with no GRE / IPIP "
                    "tunnel grammar; tunnel_type is not surfaced on "
                    "render."
                ),
                severity="warn",
            ),
            # Wave B (v0.2.0) — VRRP virtual_ips lossy.  AOS-S
            # ``virtual-ip-address`` accepts ONE address per vrid;
            # cross-vendor migration FROM Cisco IOS-XE or Junos
            # sources with multi-IP groups drops secondary virtuals
            # with a review comment.  See render.py inside the VRRP
            # emission block for the per-group comment form.
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group/virtual-ips",
                reason=(
                    "AOS-S 'virtual-ip-address' accepts only ONE "
                    "address per vrid; cross-vendor migration from "
                    "Cisco IOS-XE secondaries or Junos virtual-"
                    "address lists drops the tail with a review "
                    "comment."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "AOS-S access-lists are Tier 3 (informational) "
                    "and not yet auto-rendered."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason="VXLAN not modelled — AOS-S is a campus L2/L3 codec.",
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
            # VRRP itself moved to ``supported`` above when Wave B
            # wire-up landed.  Anycast / virtual-gateway-address
            # paths remain unsupported because AOS-S is a campus
            # L2/L3 codec with no anycast-gateway grammar.
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
        from ..._tier3_detection import detect_tier3_sections_iosxe_cli

        intent = parse_intent(raw)
        # Aruba AOS-S uses Cisco-derived ACL grammar (`access-list extended`,
        # `policy-map`, etc.); reuse the IOS-XE CLI detector.  Notification-only.
        intent.dropped_tier3_sections = detect_tier3_sections_iosxe_cli(raw)
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
            # VLAN port-membership xpaths (this codec is the first
            # that actually populates them).
            for vlan in tree.vlans:
                for _ in vlan.tagged_ports:
                    yield "/vlans/vlan/tagged-ports"
                for _ in vlan.untagged_ports:
                    yield "/vlans/vlan/untagged-ports"

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------
    # Implementation extracted to :mod:`.port_names` — these methods
    # delegate so the codec class stays focused on parse/render while
    # the pure port-name translation primitives remain importable
    # independently by the orchestrator.

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect AOS-S running-config by its unique structural cues.

        Key discriminators vs. Cisco IOS CLI:
          * ``;`` banner comment (IOS uses ``!``)
          * ``interface <N>`` with a bare number, no ``Ethernet``/``Gig`` prefix
          * ``vlan <N>`` ... ``untagged <range>`` inside the stanza
          * ``routing`` keyword on a port (not ``no switchport``)
        """
        # XML / JSON shape — shared helper tolerates leading shell-echo
        # / banner framing so real captures don't bypass the guard.
        if detect_input_shape(raw_prefix) is not None:
            return None

        # Unique banner.  Three observed shapes:
        #   ``; J9850A Configuration Editor`` — older J-prefix part
        #     numbers (J9729A, J9850A, etc.)
        #   ``; JL260A Configuration Editor`` — newer JL-prefix part
        #     numbers (JL256A, JL260A — found on 2930F / 2930M)
        #   ``; hpStack_WC Configuration Editor`` — stacking banner
        #     (multi-member 2930M / 5400 stacks)
        # All three are unambiguously Aruba/HPE.  Match anywhere in
        # the input (not just first line) because operators sometimes
        # include the prompt-echo + ``show running-config`` command
        # before the actual config — the banner shows up a few lines
        # in.
        if re.search(
            r"^;\s*(J[A-Z]?\d+[A-Z]*|hpStack_\w+)\s+Configuration",
            raw_prefix, re.MULTILINE,
        ):
            return (98, "AOS-S ProCurve / Aruba configuration banner present")

        # Structural: vlan stanzas with inline untagged/tagged.
        has_vlan_with_untagged = bool(re.search(
            r"^vlan\s+\d+[\s\S]{0,400}?^\s+untagged\s+\d",
            raw_prefix, re.MULTILINE,
        ))
        has_iface_bare_num = bool(re.search(
            r"^interface\s+[A-Z]?\d+(/\d+)?\s*$",
            raw_prefix, re.MULTILINE,
        ))
        has_routing_keyword = bool(re.search(
            r"^\s+routing\s*$", raw_prefix, re.MULTILINE,
        ))
        has_aos_comment = bool(re.search(
            r"^;", raw_prefix, re.MULTILINE,
        ))

        strong_hits = sum((
            has_vlan_with_untagged,
            has_iface_bare_num,
            has_routing_keyword,
        ))
        if strong_hits >= 2 and has_aos_comment:
            return (95, f"{strong_hits} AOS-S structural markers + ';' comment")
        if strong_hits >= 2:
            return (88, f"{strong_hits} AOS-S structural markers present")
        if has_vlan_with_untagged:
            return (78, "VLAN stanza with inline 'untagged' port list")
        if has_iface_bare_num and has_aos_comment:
            return (70, "'interface <N>' shape + ';' comment prefix")
        return None
