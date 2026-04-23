"""
``JunosCodec`` — 7th shipped vendor.

See package ``__init__`` for scope + grammar notes.

Parse strategy (v1 / set-form only):

Junos ``set``-form is a flat sequence of ``set <space-separated
hierarchy path>`` commands.  The codec tokenises each line against a
small regex table keyed on the leading path segments (e.g.
``set interfaces``, ``set system host-name``).  Each matcher extracts
the payload and applies it to the CanonicalIntent.  Unrecognised
paths are silently ignored (Tier-3 parse-tolerance).

Block-form parse is reserved for a follow-up commit — the
transformation ``block-form → set-form`` is a separate well-defined
pass that can plug in ahead of this set-form parser without touching
any of the apply functions below.

Render is NOT implemented (direction=parse_only).  Junos migrations
are predominantly "FROM Junos TO something else"; render-side Junos
is higher-complexity (commit semantics, apply-groups, candidate
config) and warrants a dedicated v2 pass.
"""

from __future__ import annotations

import logging
import re
import shlex
from typing import Any, ClassVar, Iterable

from ....models.migration import (
    CapabilityMatrix,
    DeviceClass,
    LossyPath,
    UnsupportedPath,
)
from ...canonical.intent import (
    CanonicalIPv4Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLocalUser,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from ..base import CodecBase, ParseError
from ..registry import register
from . import port_names as _port_names

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Codec class
# ---------------------------------------------------------------------------


@register
class JunosCodec(CodecBase):
    """Parse-only codec for Juniper Junos ``set``-form configuration."""

    name: ClassVar[str] = "juniper_junos"
    version_hint: ClassVar[str | None] = "Junos 18.x+"
    input_format: ClassVar[str] = "cli-junos-set"
    direction: ClassVar[str] = "parse_only"
    certainty: ClassVar[str] = "experimental"
    canonical_model: ClassVar[str] = "openconfig-lite"
    description: ClassVar[str] = (
        "Paste Junos `set`-form configuration text — the output of "
        "`show configuration | display set` on any Junos EX/QFX/MX/SRX "
        "device.  Block-form (hierarchical curly-brace) input is NOT "
        "parsed in v1; run `| display set` on your Junos device to "
        "produce compatible input."
    )
    sample_input: ClassVar[str] = (
        "set version 23.2R1.14\n"
        "set system host-name sw-edge-01\n"
        "set system root-authentication encrypted-password "
        '"$6$abcd$fake"\n'
        "set system login user netadmin class super-user\n"
        "set system login user netadmin authentication "
        'encrypted-password "$6$efgh$fake"\n'
        "set interfaces em0 unit 0 family inet address "
        "192.0.2.1/24\n"
        "set interfaces ge-0/0/0 description \"uplink to core\"\n"
        "set interfaces ge-0/0/0 unit 0 family inet address "
        "10.0.0.1/31\n"
        "set interfaces lo0 unit 0 family inet address "
        "172.16.0.1/32\n"
        "set vlans USERS vlan-id 10\n"
        "set vlans VOICE vlan-id 20\n"
        "set routing-options static route 0.0.0.0/0 next-hop "
        "10.0.0.2\n"
        "set snmp community public authorization read-only\n"
        'set snmp location "Rack 4 DC1"\n'
    )
    output_extension: ClassVar[str] = "conf"

    _CAPS: ClassVar[CapabilityMatrix] = CapabilityMatrix(
        adapter="juniper_junos",
        vendor_id="juniper_junos",
        version_range="18.x+",
        device_classes=[DeviceClass.switch, DeviceClass.router],
        supported=[
            "/system/hostname",
            "/interfaces/interface/name",
            "/interfaces/interface/config/description",
            "/interfaces/interface/config/enabled",
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/aaa/authentication/users/user/config/username",
            "/aaa/authentication/users/user/config/password",
            "/aaa/authentication/users/user/config/role",
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/subinterfaces/subinterface",
                reason=(
                    "Junos models per-unit sub-interfaces explicitly "
                    "(``interface em0 unit 0``).  v1 collapses unit "
                    "0 into the parent and ignores units 1+ — a "
                    "future enrichment pass will populate "
                    "CanonicalInterface.subinterfaces properly."
                ),
                severity="warn",
            ),
        ],
        unsupported=[
            UnsupportedPath(
                path="/routing/bgp",
                reason=(
                    "BGP / IS-IS / OSPF / MPLS stanzas parse-and-"
                    "ignore in v1.  Junos routing-options are "
                    "syntactically rich (groups, policy-options, "
                    "routing-instances) and warrant a dedicated "
                    "follow-up commit."
                ),
            ),
            UnsupportedPath(
                path="/firewall/filter",
                reason=(
                    "Junos firewall filters are Tier-3 — the grammar "
                    "(family / term / from / then) is distinct from "
                    "ACL models in other codecs and defers."
                ),
            ),
            UnsupportedPath(
                path="/vxlan-vnis/vni",
                reason=(
                    "VLAN-to-VNI mappings (`set vlans <name> vxlan "
                    "vni <N>`) parse-and-ignore in v1.  "
                    "CanonicalVxlan schema landed; Junos codec "
                    "wire-up pending render-side promotion."
                ),
            ),
            UnsupportedPath(
                path="/evpn-type5-routes/route",
                reason=(
                    "EVPN Type-5 advertisements (`set "
                    "routing-instances <vrf> protocols evpn ip-"
                    "prefix-routes`) parse-and-ignore in v1.  "
                    "CanonicalEvpnType5Route schema exists; Junos "
                    "wire-up deferred alongside routing-instances "
                    "support."
                ),
            ),
        ],
    )

    @property
    def capabilities(self) -> CapabilityMatrix:
        return self._CAPS

    # -----------------------------------------------------------------
    # Parse
    # -----------------------------------------------------------------

    def parse(self, raw: str) -> CanonicalIntent:
        if not raw.strip():
            raise ParseError(
                "juniper_junos: empty input", snippet="",
            )
        stripped = raw.lstrip()
        if stripped.startswith("<"):
            raise ParseError(
                "juniper_junos: input looks like XML, not Junos "
                "set-form.  If you have NETCONF get-config XML, use "
                "a different codec.",
                snippet=stripped[:120],
            )
        if stripped.startswith("{"):
            # Could be block-form Junos ({ system { ... } }).  v1
            # doesn't parse block-form; hint operator toward
            # ``| display set``.
            raise ParseError(
                "juniper_junos: input looks like Junos block-form "
                "(curly-brace hierarchical) or JSON.  v1 parses set-"
                "form only — run `show configuration | display set` "
                "on your Junos device and paste that output.",
                snippet=stripped[:120],
            )

        intent = CanonicalIntent(
            source_vendor="juniper_junos",
            source_format="cli-junos-set",
        )

        # Interface accumulator — Junos set-form spreads interface
        # config across many lines; we collect per-iface state
        # before materialising CanonicalInterface objects.
        iface_state: dict[str, dict[str, Any]] = {}

        for raw_line in raw.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Junos set-form begins with `set ` (or `delete ` /
            # `deactivate ` which we skip).
            if not line.startswith("set "):
                continue
            tokens = _tokenise_set(line[4:])
            if not tokens:
                continue
            _dispatch_set(tokens, intent, iface_state)

        # Materialise CanonicalInterface records from the accumulator.
        for name in sorted(iface_state.keys()):
            state = iface_state[name]
            iface = CanonicalInterface(
                name=name,
                enabled=state.get("enabled", True),
                description=state.get("description", ""),
                interface_type=_infer_iface_type(name),
            )
            for ip, prefix in state.get("ipv4", []):
                iface.ipv4_addresses.append(
                    CanonicalIPv4Address(ip=ip, prefix_length=prefix)
                )
            intent.interfaces.append(iface)

        logger.debug(
            "juniper_junos parsed: hostname=%r ifaces=%d vlans=%d "
            "routes=%d users=%d snmp=%s (input=%d chars)",
            intent.hostname,
            len(intent.interfaces),
            len(intent.vlans),
            len(intent.static_routes),
            len(intent.local_users),
            "yes" if intent.snmp else "no",
            len(raw),
        )
        return intent

    # -----------------------------------------------------------------
    # Render — NOT IMPLEMENTED in v1
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        raise NotImplementedError(
            "juniper_junos: render is parse-only in v1.  Junos "
            "render-side requires commit / apply-groups / candidate-"
            "config handling that warrants a dedicated follow-up "
            "commit.  Migrate FROM Junos TO another vendor instead."
        )

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

    def classify_port_name(self, name: str):
        return _port_names.classify_port_name(name)

    def format_port_identity(self, identity) -> str | None:
        return _port_names.format_port_identity(identity)

    # -----------------------------------------------------------------
    # Auto-detection probe (R5)
    # -----------------------------------------------------------------

    @classmethod
    def probe(cls, raw_prefix: str) -> tuple[int, str] | None:
        """Detect Junos set-form config.

        Signals:
          * ``set version <X>`` banner on the first non-comment line.
          * ``set system host-name`` — universal Junos line shape.
          * ``set interfaces <media>-<fpc>/<pic>/<port>`` —
            Junos-specific port naming.
        """
        stripped = raw_prefix.lstrip()
        if stripped.startswith("<") or stripped.startswith("{"):
            return None
        if re.search(
            r"^set version \d",
            raw_prefix, re.MULTILINE,
        ):
            return (90, "Junos 'set version X' banner present")
        hits = 0
        if re.search(
            r"^set system host-name\s+\S+",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^set interfaces (?:ge|xe|et|fe|em|me|fxp|ae|lo|irb)",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^set (?:routing-options|protocols|policy-options|firewall)",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if re.search(
            r"^set vlans \S+ vlan-id \d+",
            raw_prefix, re.MULTILINE,
        ):
            hits += 1
        if hits >= 3:
            return (88, f"{hits} Junos set-form grammar markers")
        if hits == 2:
            return (68, "partial Junos set-form grammar match")
        return None


# ---------------------------------------------------------------------------
# Tokeniser + dispatch
# ---------------------------------------------------------------------------


def _tokenise_set(payload: str) -> list[str]:
    """Split a Junos set-line payload into tokens, honouring quoted
    string values that contain spaces (e.g. ``description "WAN uplink"``).
    """
    try:
        return shlex.split(payload, posix=True)
    except ValueError:
        return payload.split()


def _dispatch_set(
    tokens: list[str],
    intent: CanonicalIntent,
    iface_state: dict[str, dict[str, Any]],
) -> None:
    """Apply one set-line's token list to *intent*.

    Dispatches on the first 1-3 tokens to find the applier.  Unknown
    paths silently no-op (Tier-3 tolerance).
    """
    if not tokens:
        return
    head = tokens[0]
    if head == "system":
        _apply_system(tokens[1:], intent)
    elif head == "interfaces":
        _apply_interfaces(tokens[1:], iface_state)
    elif head == "vlans":
        _apply_vlans(tokens[1:], intent)
    elif head == "routing-options":
        _apply_routing_options(tokens[1:], intent)
    elif head == "snmp":
        _apply_snmp(tokens[1:], intent)
    # All other top-level paths (protocols / firewall / policy-options /
    # routing-instances / groups / security / forwarding-options /
    # chassis / services) — parse-and-ignore.


def _apply_system(tokens: list[str], intent: CanonicalIntent) -> None:
    if not tokens:
        return
    if tokens[0] == "host-name" and len(tokens) >= 2:
        intent.hostname = tokens[1]
        return
    if tokens[0] == "login" and len(tokens) >= 3 and tokens[1] == "user":
        # ``set system login user <name> class <class>``
        # ``set system login user <name> authentication encrypted-password "<hash>"``
        user_name = tokens[2]
        # Find (or create) the user in intent.local_users.
        existing = next(
            (u for u in intent.local_users if u.name == user_name),
            None,
        )
        if existing is None:
            existing = CanonicalLocalUser(name=user_name, privilege_level=1)
            intent.local_users.append(existing)
        if len(tokens) >= 5 and tokens[3] == "class":
            existing.role = tokens[4]
            # Junos ``super-user`` ≈ privilege 15; ``read-only`` ≈ 1.
            if tokens[4] in ("super-user", "superuser"):
                existing.privilege_level = 15
        elif (
            len(tokens) >= 6
            and tokens[3] == "authentication"
            and tokens[4] == "encrypted-password"
        ):
            # Store hash with vendor tag for future render.
            existing.hashed_password = f"junos:{tokens[5]}"


def _apply_interfaces(
    tokens: list[str],
    iface_state: dict[str, dict[str, Any]],
) -> None:
    """Parse ``interfaces <name> ...`` variants."""
    if not tokens:
        return
    name = tokens[0]
    state = iface_state.setdefault(name, {})

    if len(tokens) < 2:
        # bare ``set interfaces <name>`` — unusual but valid, ensures
        # the interface exists.
        return

    second = tokens[1]

    # ``interfaces <name> disable``
    if second == "disable":
        state["enabled"] = False
        return

    # ``interfaces <name> description "<desc>"``
    if second == "description" and len(tokens) >= 3:
        state["description"] = tokens[2]
        return

    # ``interfaces <name> unit <N> ...``
    if second == "unit" and len(tokens) >= 3:
        try:
            unit_num = int(tokens[2])
        except ValueError:
            return
        if len(tokens) < 4:
            return
        # v1: collapse unit 0 into parent (most common case).
        # Units 1+ on non-physical interfaces are sub-interfaces we
        # don't currently model — parse-and-ignore with an optional
        # warning in a future enrichment pass.
        if unit_num != 0:
            return
        # ``unit 0 family inet address <ip>/<prefix>``
        if (
            len(tokens) >= 7
            and tokens[3] == "family"
            and tokens[4] == "inet"
            and tokens[5] == "address"
        ):
            addr = tokens[6]
            if "/" in addr:
                ip_str, prefix_str = addr.split("/", 1)
                try:
                    prefix = int(prefix_str)
                    state.setdefault("ipv4", []).append((ip_str, prefix))
                except ValueError:
                    pass
        # ``unit 0 description "<desc>"`` — some configs place it here.
        if (
            len(tokens) >= 5
            and tokens[3] == "description"
            and not state.get("description")
        ):
            state["description"] = tokens[4]


def _apply_vlans(tokens: list[str], intent: CanonicalIntent) -> None:
    """``set vlans <NAME> vlan-id <N>``"""
    if len(tokens) < 3:
        return
    vlan_name = tokens[0]
    if tokens[1] == "vlan-id":
        try:
            vid = int(tokens[2])
        except ValueError:
            return
        existing = next((v for v in intent.vlans if v.id == vid), None)
        if existing is None:
            intent.vlans.append(CanonicalVlan(id=vid, name=vlan_name))
        else:
            existing.name = vlan_name


def _apply_routing_options(
    tokens: list[str], intent: CanonicalIntent,
) -> None:
    """``set routing-options static route <dest>/<prefix> next-hop <gw>``"""
    if len(tokens) < 5:
        return
    if tokens[0] == "static" and tokens[1] == "route":
        dest = tokens[2]
        if "/" not in dest:
            return
        if tokens[3] == "next-hop" and len(tokens) >= 5:
            gateway = tokens[4]
            intent.static_routes.append(CanonicalStaticRoute(
                destination=dest,
                gateway=gateway,
                interface="",
            ))


def _apply_snmp(tokens: list[str], intent: CanonicalIntent) -> None:
    """``set snmp community <name> authorization read-only|read-write``
    ``set snmp location "<loc>"``
    ``set snmp contact "<contact>"``
    """
    if not tokens:
        return
    head = tokens[0]
    if intent.snmp is None:
        intent.snmp = CanonicalSNMP()
    if head == "community" and len(tokens) >= 2:
        # First community wins (matches EOS + Cisco convention).
        if not intent.snmp.community:
            intent.snmp.community = tokens[1]
    elif head == "location" and len(tokens) >= 2:
        intent.snmp.location = tokens[1]
    elif head == "contact" and len(tokens) >= 2:
        intent.snmp.contact = tokens[1]
    elif (
        head == "trap-group"
        and len(tokens) >= 4
        and tokens[2] == "targets"
    ):
        # ``set snmp trap-group <name> targets <ip>``
        intent.snmp.trap_hosts.append(tokens[3])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _infer_iface_type(name: str) -> str:
    """Infer IANA iftype from a Junos interface name."""
    lower = name.lower()
    if lower.startswith(("ge-", "xe-", "et-", "fe-", "mge-", "xle-")):
        return "ianaift:ethernetCsmacd"
    if lower.startswith(("em", "me", "fxp")):
        return "ianaift:ethernetCsmacd"
    if lower.startswith("lo"):
        return "ianaift:softwareLoopback"
    if lower.startswith("ae"):
        return "ianaift:ieee8023adLag"
    if lower.startswith("irb") or lower.startswith("vlan."):
        return "ianaift:l3ipvlan"
    return ""
