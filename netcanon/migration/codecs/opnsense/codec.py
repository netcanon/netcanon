"""
``OPNsenseCodec`` — second real adapter (XML wire format).

See package ``__init__`` for scope and structural notes.

Module layout (post-split):

* ``codec.py`` (this file) — the ``OPNsenseCodec`` class with
  metadata (capabilities / classvars / probe / port-name delegates).
  ``parse()`` and ``render()`` are two-line delegators to the
  corresponding functions in the sibling modules.
* ``parse.py`` — XML-to-CanonicalIntent.  Owns the bounded
  envelope-trim helper that rescues legacy paramiko-shell backups
  with PTY-echo preamble + shell-prompt postamble noise.
* ``render.py`` — CanonicalIntent (or legacy dict) to ``config.xml``
  text.  Emits the OPNsense convention (no XML declaration, two-space
  indent, stable block order) to keep round-trip diffs friendly.
* ``port_names.py`` — cross-vendor port-name identity bridge
  (shared with the rename-modal orchestrator).

Test-import symbols (``_trim_xml_envelope``, ``_trim_xml_prologue``)
are re-exported here so existing tests in
``tests/unit/migration/test_opnsense.py`` and the integration suite
don't need updating for the split.  The canonical home is
:mod:`.parse`; this module's re-exports are purely for backwards
compatibility.

Tree shape (canonical model)
----------------------------
Every codec parses INTO and renders FROM :class:`CanonicalIntent`.
OPNsense's native ``<wan>``/``<lan>``/``<optN>`` zone-keyed
interfaces are flattened into a list of :class:`CanonicalInterface`
records on parse and reconstituted as zone elements on render.
Round-trip invariant: ``parse(render(intent))`` reproduces the
canonical fields the codec wires through.

DHCP server zones (``<dhcpd>/<wan>``, ``<dhcpd>/<lan>``, ``<dhcpd>/<optN>``)
parse to :class:`CanonicalDHCPPool` records; the canonical surface is the
same list-of-pools shape every other codec uses.
"""

from __future__ import annotations

from typing import Any, ClassVar, Iterable

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import CanonicalIntent
from ..base import CodecBase
from ..registry import register
from . import port_names as _port_names
from .parse import (
    _trim_xml_envelope,
    _trim_xml_prologue,
    parse_intent,
)
from .render import render_intent

# Re-export the internal helpers that tests pin against the codec's
# structural contract (see module docstring).
__all__ = [
    "OPNsenseCodec",
    "_trim_xml_envelope",
    "_trim_xml_prologue",
]


@register
class OPNsenseCodec(CodecBase):
    """Adapter for OPNsense ``config.xml`` (25.x).

    Declares ``device_classes=[firewall, router]`` — OPNsense's primary
    role is firewalling but it's also a competent L3 router (even
    without FRR installed).
    """

    name: ClassVar[str] = "opnsense"
    version_hint: ClassVar[str | None] = "25.x"
    input_format: ClassVar[str] = "xml-opnsense"
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste the contents of an OPNsense config.xml "
        "(root element <opnsense>)."
    )
    sample_input: ClassVar[str] = (
        '<?xml version="1.0"?>\n'
        '<opnsense>\n'
        '  <system>\n'
        '    <hostname>fw01</hostname>\n'
        '    <domain>example.com</domain>\n'
        '  </system>\n'
        '  <interfaces>\n'
        '    <wan>\n'
        '      <if>em0</if>\n'
        '      <descr>Upstream</descr>\n'
        '      <enable/>\n'
        '      <ipaddr>198.51.100.2</ipaddr>\n'
        '      <subnet>30</subnet>\n'
        '    </wan>\n'
        '  </interfaces>\n'
        '</opnsense>\n'
    )
    output_extension: ClassVar[str] = "xml"

    # OPNsense doesn't round-trip SNMPv3 USM users: the XML store
    # doesn't carry them (see /snmp/v3-user entry in capability
    # matrix unsupported[] above).  Declaring ``"snmpv3"`` here
    # surfaces the amber pane-compat banner when OPNsense is
    # selected as the target so operators see the gap BEFORE
    # committing overrides that won't render.
    unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset({
        "snmpv3",
    })

    # Historical note: local_users was removed from this frozenset
    # as part of Option A — OPNsense's parse + render both
    # round-trip CanonicalLocalUser via ``<system><user>`` blocks.
    # Coverage locked in by ``tests/unit/migration/
    # test_local_users_wire_through.py``.

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="opnsense",
        vendor_id="opnsense",
        version_range="24.x+",
        device_classes=[DeviceClass.firewall, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/system/domain",
            "/system/dns-server",
            "/system/ntp-server",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            "/interfaces/interface/dhcp-client-v6",          # OPNsense <ipaddrv6>{dhcp6|slaac|track6|6rd|6to4}</ipaddrv6>
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            # Tier 2 — SNMP (OPNsense snmpd plugin)
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/snmp/trap-host",
            # Tier 2 — local users (OPNsense <system><user> blocks).
            # Parse maps <groupname="admins"> → privilege 15; render
            # emits name / password / scope / groupname.  Hashes are
            # passed through verbatim under a ``bcrypt:`` tag so
            # target renderers can route appropriately.
            "/aaa/authentication/users/user/config/username",
            "/aaa/authentication/users/user/config/password",
            "/aaa/authentication/users/user/config/role",
            # Wave B (v0.2.0) — CARP groups on /virtualip/vip.
            # OPNsense's BSD-CARP HA primitive parses + renders
            # round-trip through CanonicalVRRPGroup with
            # ``mode="carp"``.  See LossyPath below for the mode-
            # restriction caveat (non-CARP modes drop on render).
            "/interfaces/interface/vrrp-groups/group",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/config/description",
                reason=(
                    "OPNsense imposes no length limit on description text; "
                    "other vendors (Cisco 240 chars, Juniper 900) may "
                    "truncate on render."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/tunnel-type",
                reason=(
                    "OPNsense's <interfaces> block does not encode tunnel "
                    "encapsulation — tunnel_type is not surfaced on parse "
                    "or render.  Tunnel interfaces (GRE, IPIP, IPSEC) live "
                    "under separate Tier-3 OPNsense sections."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/interfaces/interface/vrrp-groups/group",
                reason=(
                    "OPNsense's <virtualip> hosts CARP-only HA groups in "
                    "the v1 wire-up.  CanonicalVRRPGroup records with "
                    "mode='vrrp' or mode='hsrp' are SKIPPED on render — "
                    "OPNsense has no native HSRP wire protocol, and its "
                    "pure-VRRP mode under <virtualip> is rarely deployed "
                    "and not yet emitted by this codec.  Only mode='carp' "
                    "round-trips.  Additionally, the advskew↔priority "
                    "mapping (priority = 254 - advskew) preserves "
                    "relative HA-pair ordering but not exact election "
                    "timing — VRRP priorities are advisory weights, CARP "
                    "advskews are advertisement-interval offsets, so "
                    "cross-protocol migration loses the timing semantics."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/filter/rule",
                reason=(
                    "Firewall rules require the netcanon-ext YANG module "
                    "(Phase 2) — OpenConfig has no firewall model."
                ),
            ),
            UnsupportedPath(
                path="/nat/outbound",
                reason=(
                    "NAT table translation needs netcanon-ext + careful "
                    "semantic mapping to target stateful engines."
                ),
            ),
            UnsupportedPath(
                path="/snmp/v3-user",
                reason=(
                    "OPNsense's SNMPv3 user store lives in the bsnmpd "
                    "/ net-snmp plugin's own configuration format "
                    "(``/usr/local/etc/snmpd.conf`` createUser lines), "
                    "not in the config.xml this codec reads.  Tier-3 "
                    "carry-through is not wired; operators re-declare "
                    "v3 users on the target after migration."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason="VXLAN not modelled — OPNsense is a firewall codec.",
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
            # (Note: VRRP/HSRP/CARP was here but moved to supported[] with
            # a LossyPath in Wave B — see CARP wire-up above.)
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
        from ..._tier3_detection import detect_tier3_sections_opnsense

        intent = parse_intent(raw)
        # Surface Tier-3 XML elements the parser drops (`<filter>`,
        # `<nat>`, `<ipsec>`, `<openvpn>`, `<wireguard>`, captive
        # portal, traffic shaper, load balancer).  Notification-only.
        intent.dropped_tier3_sections = detect_tier3_sections_opnsense(raw)
        return intent

    def render(self, tree: Any) -> str:
        return render_intent(tree)

    # -----------------------------------------------------------------
    # iter_xpaths
    # -----------------------------------------------------------------

    def iter_xpaths(self, tree: Any) -> Iterable[str]:
        """Yield schema xpaths from a :class:`CanonicalIntent` or legacy dict."""
        if isinstance(tree, CanonicalIntent):
            # Reuse the CLI codec's canonical walker.
            from ..cisco_iosxe_cli.codec import _walk_canonical
            yield from _walk_canonical(tree)
            return
        if not isinstance(tree, dict):
            return
        for key, val in tree.items():
            yield from _walk(val, f"/{key}")

    # -----------------------------------------------------------------
    # Cross-vendor port-name translation
    # -----------------------------------------------------------------
    # Implementation extracted to :mod:`.port_names` — these methods
    # delegate so the codec class stays focused on parse/render.

    def classify_port_name(self, name: str):  # -> PortIdentity
        """Classify an OPNsense interface name into a :class:`PortIdentity`.

        Thin instance-method wrapper around the module-level
        :func:`port_names.classify_port_name`.  Extracted so the
        cross-vendor orchestrator can import the pure function
        without dragging in the parser / renderer; consistent with
        the other CLI codecs.  See ``port_names.py`` for the full
        pattern inventory and docstring."""
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        """Render a :class:`PortIdentity` as an OPNsense BSD-device name.

        Thin instance-method wrapper around
        :func:`port_names.format_port_identity`; see that module for
        the rendering rules (driver default, SVI parent fallback,
        kinds OPNsense can't represent)."""
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect OPNsense config.xml by its unique ``<opnsense>`` root."""
        lowered = raw_prefix.lower()
        # The <opnsense> tag is nearly unique to this vendor — only
        # false-positive would be a doc about OPNsense, which won't
        # survive the actual parse() anyway.
        if "<opnsense>" in lowered or "<opnsense " in lowered:
            return (98, "root element <opnsense> matches OPNsense config.xml")
        return None


# ---------------------------------------------------------------------------
# iter_xpaths walker — kept here because iter_xpaths() lives on the codec
# class and the legacy dict path is the only consumer.
# ---------------------------------------------------------------------------


def _walk(node: Any, prefix: str) -> Iterable[str]:
    """Recursively yield schema xpaths under *prefix*."""
    if isinstance(node, dict):
        # /interfaces/interface is the only list-wrapper in this adapter.
        if prefix == "/interfaces" and isinstance(
            node.get("interface"), list
        ):
            for item in node["interface"]:
                yield from _walk(item, "/interfaces/interface")
            return
        for key, val in node.items():
            yield from _walk(val, f"{prefix}/{key}")
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, prefix)
    else:
        # Leaf value.
        yield prefix
