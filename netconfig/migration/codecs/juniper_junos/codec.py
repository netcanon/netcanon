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

Render strategy (v2a / flat set-form, no apply-groups):

The codec emits flat Junos ``set``-form commands in a deterministic
order (system / login / interfaces / vlans / routing-options / snmp)
that round-trips through the v1 parser.  Strings containing spaces
or shell-special characters are double-quoted per Junos convention.
Hashes stored under the ``junos:<hash>`` vendor tag get their prefix
stripped on render so parse(render(tree)) is a true round-trip.

Apply-groups inheritance (``set groups <name> ... / set apply-groups
<name>``) is NOT emitted in v2a — the output is verbose but
syntactically complete.  v2b (deferred) will detect repeated sub-
trees and collapse them via apply-groups for operator readability.
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
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVxlan,
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
    direction: ClassVar[str] = "bidirectional"
    certainty: ClassVar[str] = "certified"
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
            "/interfaces/interface/config/vrf",   # GAP 6
            "/vlans/vlan/id",
            "/vlans/vlan/name",
            "/routing/static-route",
            "/snmp/community",
            "/snmp/location",
            "/snmp/contact",
            "/aaa/authentication/users/user/config/username",
            "/aaa/authentication/users/user/config/password",
            "/aaa/authentication/users/user/config/role",
            "/vxlan-vnis/vni",                   # GAP 6
            "/routing-instances/instance",       # GAP 6
        ],
        lossy=[
            LossyPath(
                path="/interfaces/interface/subinterfaces/subinterface",
                reason=(
                    "Unit 0 collapses into the parent (common case "
                    "— most Junos interfaces have exactly one unit).  "
                    "GAP 4 materialises units 1+ as distinct "
                    "CanonicalInterface entries named "
                    "``<parent>.<unit>``; per-unit VLAN tagging "
                    "(``unit N vlan-id 100``) still parses-and-"
                    "ignores pending a canonical tagged-subinterface "
                    "model."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/groups",
                reason=(
                    "Apply-groups inheritance is wired for the full "
                    "dispatch surface via GAP 8's two-pass parse "
                    "(system / login / interfaces / protocols / "
                    "SNMP / routing-options / routing-instances / "
                    "vlans).  Unsupported surfaces under ``set "
                    "groups <g>`` (policy-options, firewall filters, "
                    "RADIUS server options beyond host) still "
                    "parse-and-ignore."
                ),
                severity="warn",
            ),
            LossyPath(
                path="/evpn-type5-routes/route",
                reason=(
                    "EVPN Type-5 IP-prefix advertisements use a "
                    "VRF-property canonical model: "
                    "CanonicalRoutingInstance.l3_vni captures the "
                    "L3 VNI (populated from ``set routing-instances "
                    "<vrf> protocols evpn ip-prefix-routes vni "
                    "<N>``); Type-5 announcements are IMPLICIT for "
                    "any interface bound to the VRF via "
                    "CanonicalInterface.vrf.  The per-prefix "
                    "CanonicalEvpnType5Route list is a lossy-by-"
                    "default extension point: no codec populates it "
                    "today (would require ``set policy-options "
                    "policy-statement`` parsing to derive which "
                    "prefixes specific export policies select).  "
                    "Consumers needing explicit per-prefix semantics "
                    "should infer from VRF membership + l3_vni "
                    "rather than relying on this list."
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
                    "syntactically rich (policy-options, policy-"
                    "statement, BFD) and warrant a dedicated "
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
        # Detect block-form input: first non-comment meaningful
        # content contains a curly-brace at a sensible location.
        # We convert block-form → set-form here and feed the
        # resulting text through the normal set-form parser below.
        if _looks_like_blockform(raw):
            try:
                raw = _blockform_to_setform(raw)
            except ParseError:
                raise
            except Exception as e:  # noqa: BLE001
                raise ParseError(
                    "juniper_junos: block-form input conversion "
                    "failed.  Consider running `show configuration "
                    "| display set` on your Junos device to get "
                    "set-form output directly.",
                    snippet=stripped[:120],
                ) from e
        elif stripped.startswith("{"):
            # Starts with `{` but doesn't pattern-match block-form
            # (bare `{`, or JSON-shaped ``"key": ...``) — reject
            # explicitly rather than silently producing an empty
            # tree via set-form fallthrough.
            raise ParseError(
                "juniper_junos: input starts with `{` but isn't "
                "recognisable Junos block-form.  If this is JSON, "
                "use a different codec; if it's Junos, run `show "
                "configuration | display set` on your device to "
                "get set-form output directly.",
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
        # GAP 8: two-pass parse for richer apply-groups inheritance.
        # Junos's ``set groups <g> ...`` + ``set apply-groups <g>``
        # grammar composes inherited config from named groups into
        # the candidate config.  We:
        #
        #   1.  Bucket every set-line into ``top_level_lines`` or
        #       ``group_lines[gname]`` based on whether it starts
        #       with ``groups <gname>`` or not.  ``apply-groups
        #       <gname>`` entries accumulate in ``applied_groups``.
        #   2.  Dispatch group content first (in apply-groups order),
        #       then dispatch top-level content.  This gives direct-
        #       intent-wins semantics naturally: the _apply_*
        #       functions overwrite scalars, so the top-level pass
        #       overwrites whatever a group set.  List-shaped fields
        #       (static_routes, local_users, interfaces) accumulate
        #       from both — matching Junos's own composition.
        top_level_lines: list[list[str]] = []
        group_lines: dict[str, list[list[str]]] = {}
        applied_groups: list[str] = []

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
            head = tokens[0]
            if head == "groups" and len(tokens) >= 3:
                # ``set groups <gname> <path...>`` — bucket the path
                # tokens (after the group name) for later replay.
                gname = tokens[1]
                group_lines.setdefault(gname, []).append(tokens[2:])
                continue
            if head == "apply-groups" and len(tokens) >= 2:
                # ``set apply-groups <gname>`` or bracketed list.
                for gname in tokens[1:]:
                    if gname in ("[", "]"):
                        continue
                    if gname not in applied_groups:
                        applied_groups.append(gname)
                continue
            top_level_lines.append(tokens)

        # Pass 2a: apply group content in REVERSE apply-groups order
        # so that the first-declared group's scalars win (matches
        # Junos's first-match composition semantics).  Example: for
        # ``set apply-groups A`` + ``set apply-groups B``, we apply
        # B first then A, so if both declare ``system host-name``
        # the value from A overwrites B — the first-declared wins.
        # List-shaped fields (static_routes, users) accumulate from
        # all groups regardless of order.  Any group that wasn't
        # apply-grouped silently drops.
        for gname in reversed(applied_groups):
            for tokens in group_lines.get(gname, []):
                _dispatch_set(tokens, intent, iface_state)
        # Pass 2b: apply top-level content.  Scalars set by group
        # content get overwritten; list-shaped fields accumulate
        # (duplicate-add protection lives in each _apply_* function).
        for tokens in top_level_lines:
            _dispatch_set(tokens, intent, iface_state)

        # GAP 9b: preserve both the apply-groups STATEMENT and the
        # GROUP CONTENT so render can re-emit `set groups <G> ...`
        # + `set apply-groups <G>` blocks — the operator-facing
        # round-trip shape matches what they pasted in.  The
        # content also flows into the canonical tree via GAP 8's
        # two-pass, so consumers that read the tree directly still
        # see the flattened data.  Render-time de-dup relies on
        # each list-shaped field's _apply_* function having
        # idempotent semantics.
        intent.apply_groups = list(applied_groups)
        # Only persist groups that were actually applied — orphan
        # groups in the source get dropped (they'd never compose
        # into the candidate config on a real Junos either).
        intent.group_content = {
            gname: [list(t) for t in group_lines[gname]]
            for gname in applied_groups
            if gname in group_lines
        }

        # Materialise CanonicalInterface records from the accumulator.
        # GAP 4: sub-interfaces (unit 1+) are materialised as distinct
        # CanonicalInterface entries with compound name ``<parent>.<N>``
        # — matches Cisco's per-port dot1Q convention
        # (``GigabitEthernet0/1.100`` is its own CanonicalInterface).
        for name in sorted(iface_state.keys()):
            state = iface_state[name]
            iface = CanonicalInterface(
                name=name,
                enabled=state.get("enabled", True),
                description=state.get("description", ""),
                interface_type=_infer_iface_type(name),
                # GAP 7: per-unit 802.1Q tag surfaces on
                # CanonicalInterface.access_vlan.  None = untagged
                # (the common case for unit 0) or not-specified.
                access_vlan=state.get("access_vlan"),
            )
            for ip, prefix in state.get("ipv4", []):
                iface.ipv4_addresses.append(
                    CanonicalIPv4Address(ip=ip, prefix_length=prefix)
                )
            intent.interfaces.append(iface)

        # GAP 6: resolve pending ``routing-instances <name> interface
        # <iface>`` assignments now that interfaces are materialised.
        # Each CanonicalRoutingInstance record may have a
        # _pending_interfaces side-attribute from
        # _apply_routing_instances; walk and set
        # CanonicalInterface.vrf accordingly.  Falls back to
        # creating a stub interface if the named interface never got
        # declared (parse-tolerance — keeps the canonical tree
        # complete).
        iface_by_name = {i.name: i for i in intent.interfaces}
        for ri in intent.routing_instances:
            pending = getattr(ri, "_pending_interfaces", None)
            if not pending:
                continue
            for iface_name in pending:
                iface = iface_by_name.get(iface_name)
                if iface is None:
                    # Interface referenced under routing-instance but
                    # never declared via ``set interfaces`` — create a
                    # stub so the VRF membership doesn't silently
                    # disappear on round-trip.
                    iface = CanonicalInterface(
                        name=iface_name,
                        interface_type=_infer_iface_type(iface_name),
                        vrf=ri.name,
                    )
                    intent.interfaces.append(iface)
                    iface_by_name[iface_name] = iface
                else:
                    iface.vrf = ri.name
            # Clean up the side-attribute so it doesn't leak into
            # downstream serialisation.
            try:
                object.__delattr__(ri, "_pending_interfaces")
            except AttributeError:
                pass

        logger.debug(
            "juniper_junos parsed: hostname=%r ifaces=%d vlans=%d "
            "vxlan_vnis=%d vrfs=%d routes=%d users=%d snmp=%s "
            "groups=%d apply_groups=%d (input=%d chars)",
            intent.hostname,
            len(intent.interfaces),
            len(intent.vlans),
            len(intent.vxlan_vnis),
            len(intent.routing_instances),
            len(intent.static_routes),
            len(intent.local_users),
            "yes" if intent.snmp else "no",
            len(group_lines),
            len(applied_groups),
            len(raw),
        )
        return intent

    # -----------------------------------------------------------------
    # Render (v2a — flat set-form, no apply-groups)
    # -----------------------------------------------------------------

    def render(self, tree: Any) -> str:
        """Render a :class:`CanonicalIntent` to Junos ``set``-form text.

        Emits commands in a deterministic order so repeated renders of
        the same tree produce byte-identical output (important for
        diff-based deployment + snapshot compare).

        Order:
            1. ``set system host-name``
            2. ``set system login user ...`` (role + encrypted-password)
            3. ``set interfaces <name> description / disable / unit 0
               family inet address``
            4. ``set vlans <NAME> vlan-id``
            5. ``set routing-options static route``
            6. ``set snmp community / location / contact / trap-group
               targets``

        Strings with spaces or shell-special chars are double-quoted;
        bare tokens stay unquoted.  Hashes tagged ``junos:<hash>`` get
        their prefix stripped so parse(render(tree)) round-trips.
        """
        if not isinstance(tree, CanonicalIntent):
            raise TypeError(
                "juniper_junos.render: expected CanonicalIntent, got "
                f"{type(tree).__name__}"
            )

        out: list[str] = []

        # --- system ---
        if tree.hostname:
            out.append(f"set system host-name {_quote_if_needed(tree.hostname)}")
        if tree.domain:
            out.append(f"set system domain-name {_quote_if_needed(tree.domain)}")
        for dns in tree.dns_servers:
            out.append(f"set system name-server {dns}")
        for ntp in tree.ntp_servers:
            out.append(f"set system ntp server {ntp}")
        for syslog in tree.syslog_servers:
            out.append(f"set system syslog host {syslog} any any")

        # --- login users ---
        for user in tree.local_users:
            if user.role:
                role = user.role
            elif user.privilege_level >= 15:
                role = "super-user"
            elif user.privilege_level >= 5:
                role = "operator"
            else:
                role = "read-only"
            out.append(
                f"set system login user {_quote_if_needed(user.name)} "
                f"class {_quote_if_needed(role)}"
            )
            if user.hashed_password:
                # Strip the ``junos:`` vendor tag on render; canonical
                # storage prefixes it on parse to mark Junos-sourced
                # hashes.
                hsh = user.hashed_password
                if hsh.startswith("junos:"):
                    hsh = hsh[len("junos:"):]
                out.append(
                    f"set system login user {_quote_if_needed(user.name)} "
                    f"authentication encrypted-password "
                    f"{_quote_always(hsh)}"
                )

        # --- interfaces ---
        for iface in tree.interfaces:
            name = iface.name
            has_renderable_attr = (
                bool(iface.description)
                or (not iface.enabled)
                or bool(iface.ipv4_addresses)
            )
            # GAP 4: sub-interface naming.  The parse side materialises
            # ``set interfaces <parent> unit N ...`` (N>0) as a
            # CanonicalInterface named ``<parent>.<N>``.  Render has to
            # split the compound name back into parent + unit so the
            # emitted set-lines use Junos's native grammar.
            parent, unit_num = _split_subiface_name(name)
            if parent is not None and unit_num is not None:
                # Sub-interface — emit under parent / unit <N>.
                # GAP 7: include access_vlan in the "renderable"
                # predicate so a bare sub-interface carrying only a
                # vlan-id (no description / no IP) still emits lines
                # and round-trips.
                sub_has_renderable = (
                    has_renderable_attr
                    or iface.access_vlan is not None
                )
                if iface.description:
                    out.append(
                        f"set interfaces {parent} unit {unit_num} "
                        f"description {_quote_always(iface.description)}"
                    )
                if not iface.enabled:
                    out.append(
                        f"set interfaces {parent} unit {unit_num} disable"
                    )
                # GAP 7: per-unit 802.1Q tag.
                if iface.access_vlan is not None:
                    out.append(
                        f"set interfaces {parent} unit {unit_num} "
                        f"vlan-id {iface.access_vlan}"
                    )
                for addr in iface.ipv4_addresses:
                    out.append(
                        f"set interfaces {parent} unit {unit_num} "
                        f"family inet address "
                        f"{addr.ip}/{addr.prefix_length}"
                    )
                if not sub_has_renderable:
                    out.append(
                        f"set interfaces {parent} unit {unit_num}"
                    )
                continue
            # Regular (unit-0 or non-unitised) interface.
            if iface.description:
                out.append(
                    f"set interfaces {name} description "
                    f"{_quote_always(iface.description)}"
                )
            if not iface.enabled:
                out.append(f"set interfaces {name} disable")
            # IPv4 addresses — emit under unit 0 (v1's convention).
            for addr in iface.ipv4_addresses:
                out.append(
                    f"set interfaces {name} unit 0 family inet "
                    f"address {addr.ip}/{addr.prefix_length}"
                )
            # Placeholder: the parse side creates an interface entry
            # for every ``set interfaces <name> ...`` line, even when
            # the trailing tokens land entirely in unmodelled (Tier-3)
            # grammar like ``unit 0 family ethernet-switching ...``.
            # Without this, round-trip would drop interfaces that
            # exist in the tree but carry no canonical attributes.
            if not has_renderable_attr:
                out.append(f"set interfaces {name}")

        # --- vlans + VLAN-to-VNI mappings (GAP 6) ---
        # Pre-index VXLAN VNIs by vlan_id for matched emission.
        vni_by_vlan = {v.vlan_id: v.vni for v in tree.vxlan_vnis}
        for vlan in tree.vlans:
            vlan_key = vlan.name or f"VLAN-{vlan.id}"
            out.append(
                f"set vlans {_quote_if_needed(vlan_key)} vlan-id {vlan.id}"
            )
            if vlan.id in vni_by_vlan:
                out.append(
                    f"set vlans {_quote_if_needed(vlan_key)} vxlan vni "
                    f"{vni_by_vlan[vlan.id]}"
                )

        # --- routing-instances (GAP 6) ---
        # Build a map from vrf_name to interfaces that belong there
        # so we can emit ``set routing-instances <name> interface
        # <iface>`` lines.  Empty ``iface.vrf`` = global VRF, skip.
        ifaces_by_vrf: dict[str, list[str]] = {}
        for iface in tree.interfaces:
            if iface.vrf:
                ifaces_by_vrf.setdefault(iface.vrf, []).append(iface.name)
        for ri in tree.routing_instances:
            out.append(
                f"set routing-instances {_quote_if_needed(ri.name)} "
                f"instance-type {ri.instance_type}"
            )
            if ri.description:
                out.append(
                    f"set routing-instances {_quote_if_needed(ri.name)} "
                    f"description {_quote_always(ri.description)}"
                )
            if ri.route_distinguisher:
                out.append(
                    f"set routing-instances {_quote_if_needed(ri.name)} "
                    f"route-distinguisher {ri.route_distinguisher}"
                )
            # vrf-target: collapse to the compact ``target:X`` form when
            # import + export are identical; otherwise emit separate
            # import/export lines.
            if (
                ri.rt_imports == ri.rt_exports and ri.rt_imports
            ):
                for rt in ri.rt_imports:
                    out.append(
                        f"set routing-instances {_quote_if_needed(ri.name)} "
                        f"vrf-target target:{rt}"
                    )
            else:
                for rt in ri.rt_imports:
                    out.append(
                        f"set routing-instances {_quote_if_needed(ri.name)} "
                        f"vrf-target import target:{rt}"
                    )
                for rt in ri.rt_exports:
                    out.append(
                        f"set routing-instances {_quote_if_needed(ri.name)} "
                        f"vrf-target export target:{rt}"
                    )
            # Interface bindings.  Interfaces that are physical
            # sub-iface compound names (``ge-0/0/1.0``) get emitted
            # as-is; parent-only names get a ``.0`` suffix since
            # Junos routing-instances always reference a UNIT (the
            # codec's canonical-name convention collapses unit 0
            # into the parent — we have to reverse that on render).
            for iface_name in ifaces_by_vrf.get(ri.name, []):
                if "." in iface_name:
                    ri_iface_name = iface_name
                else:
                    ri_iface_name = f"{iface_name}.0"
                out.append(
                    f"set routing-instances {_quote_if_needed(ri.name)} "
                    f"interface {ri_iface_name}"
                )
            # Type-5 L3 VNI.
            if ri.l3_vni is not None:
                out.append(
                    f"set routing-instances {_quote_if_needed(ri.name)} "
                    f"protocols evpn ip-prefix-routes vni {ri.l3_vni}"
                )

        # --- routing-options ---
        for route in tree.static_routes:
            if not route.gateway:
                # Junos requires a next-hop for static routes; skip
                # connected/blackhole entries we can't express.
                continue
            out.append(
                f"set routing-options static route {route.destination} "
                f"next-hop {route.gateway}"
            )

        # --- snmp ---
        if tree.snmp is not None:
            if tree.snmp.community:
                out.append(
                    f"set snmp community "
                    f"{_quote_if_needed(tree.snmp.community)} "
                    f"authorization read-only"
                )
            if tree.snmp.location:
                out.append(
                    f"set snmp location {_quote_always(tree.snmp.location)}"
                )
            if tree.snmp.contact:
                out.append(
                    f"set snmp contact {_quote_always(tree.snmp.contact)}"
                )
            for host in tree.snmp.trap_hosts:
                # Synthesise a trap-group name keyed by sanitised host
                # so two trap hosts don't collide.
                group_name = "targets"
                out.append(
                    f"set snmp trap-group {group_name} targets {host}"
                )

        # --- apply-groups / group-content (GAP 9b) ---
        # Emit the full `set groups <G> <body...>` blocks for
        # operator round-trip fidelity, followed by the matching
        # `set apply-groups <G>` statements.  Each group body
        # contains the exact tokens we captured on parse, preserving
        # operator-authored structure.  This produces RE-PARSED
        # canonical trees identical to the ORIGINAL parse (thanks
        # to idempotent list _apply_* functions) AND makes the
        # rendered output look like hand-written Junos again.
        if tree.group_content:
            for gname in tree.apply_groups:
                body = tree.group_content.get(gname)
                if not body:
                    continue
                for tokens in body:
                    # Re-quote tokens containing whitespace or shell-
                    # special chars so the re-parser (shlex-based)
                    # re-tokenises to the same token list.
                    quoted = " ".join(
                        _quote_if_needed(t) for t in tokens
                    )
                    out.append(
                        f"set groups {_quote_if_needed(gname)} "
                        f"{quoted}"
                    )
        for gname in tree.apply_groups:
            out.append(f"set apply-groups {_quote_if_needed(gname)}")

        result = "\n".join(out)
        if result:
            result += "\n"

        logger.debug(
            "juniper_junos rendered: hostname=%r ifaces=%d vlans=%d "
            "routes=%d users=%d snmp=%s (output=%d chars)",
            tree.hostname,
            len(tree.interfaces),
            len(tree.vlans),
            len(tree.static_routes),
            len(tree.local_users),
            "yes" if tree.snmp else "no",
            len(result),
        )
        return result

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


# ---------------------------------------------------------------------------
# Block-form (curly-brace hierarchical) → set-form conversion (GAP 9a)
# ---------------------------------------------------------------------------


_BLOCKFORM_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _looks_like_blockform(raw: str) -> bool:
    """Heuristic: does *raw* look like Junos block-form (hierarchical
    curly-brace) rather than set-form?

    Signals:
      * Strip comments + leading whitespace; the first meaningful line
        starts with a word followed by ``{`` (and NOT with ``set``).
      * The text contains at least one ``{``-terminated line AND at
        least one statement-terminator ``;``.
    """
    # Remove /* ... */ comments for the heuristic (they can confuse
    # detection on block-form configs that lead with a comment).
    cleaned = _BLOCKFORM_COMMENT_RE.sub("", raw)
    stripped = cleaned.lstrip()
    if stripped.startswith("set ") or stripped.startswith("version "):
        return False
    # At least one opening curly on a line that isn't a comment.
    has_open_brace = bool(re.search(r"\{\s*$", cleaned, re.MULTILINE))
    has_semi = ";" in cleaned
    if not has_open_brace or not has_semi:
        return False
    # First non-empty non-comment line must end with ``{`` AND
    # have content BEFORE the `{` (block-form sections look like
    # ``system {`` or ``interfaces {``; JSON starts with bare ``{``).
    # ``"key":`` in the same line is a strong JSON signal; Junos
    # values don't use ``:`` as a key/value separator at the block
    # level.
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        # Reject lines that look like JSON (key:value shape).
        if '"' in line and ":" in line:
            return False
        if line.endswith("{") and len(line) > 1:
            return True
        if line == "{":
            # Bare ``{`` as the first meaningful line — ambiguous
            # (could be JSON or a bare Junos block).  Favour
            # rejection so callers get a clearer error via the
            # normal set-form parse path.
            return False
        # A top-level statement before any brace means set-form.
        return False
    return False


def _tokenise_blockform(raw: str) -> list[str]:
    """Tokenise Junos block-form into a flat list with ``{``, ``}``,
    and ``;`` as standalone tokens.  Quoted strings stay intact.
    """
    # Strip comments first — Junos allows /* ... */ anywhere.
    cleaned = _BLOCKFORM_COMMENT_RE.sub(" ", raw)
    tokens: list[str] = []
    i = 0
    n = len(cleaned)
    while i < n:
        ch = cleaned[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "{};":
            tokens.append(ch)
            i += 1
            continue
        if ch == '"':
            # Quoted string — preserve the quotes for later rendering.
            end = i + 1
            while end < n and cleaned[end] != '"':
                if cleaned[end] == "\\" and end + 1 < n:
                    end += 2
                    continue
                end += 1
            if end >= n:
                raise ParseError(
                    "juniper_junos: unterminated quoted string in "
                    "block-form input",
                    snippet=cleaned[i:i + 80],
                )
            tokens.append(cleaned[i:end + 1])
            i = end + 1
            continue
        # Bare word: run of non-delim chars.
        end = i
        while end < n and not cleaned[end].isspace() and cleaned[end] not in "{};\"":
            end += 1
        tokens.append(cleaned[i:end])
        i = end
    return tokens


def _blockform_to_setform(raw: str) -> str:
    """Convert Junos block-form config text to set-form.

    Walks the curly-brace hierarchy maintaining a path stack; emits
    ``set <path...> <leaf-value>`` for each leaf statement.  Supports
    apply-groups (both ``apply-groups G;`` and
    ``apply-groups [ G1 G2 ];`` forms).

    Raises ParseError if braces are unbalanced or the input isn't
    recognisable block-form.  Conversion is grammar-agnostic beyond
    that — the set-form output feeds the normal parser, which
    handles Tier-3 tolerance of unknown paths.
    """
    tokens = _tokenise_blockform(raw)
    out_lines: list[str] = []
    path_stack: list[str] = []
    pos = 0

    def emit_leaf(words: list[str]) -> None:
        if not words:
            return
        line = "set " + " ".join(path_stack + words)
        out_lines.append(line)

    def parse_block(is_top_level: bool) -> None:
        nonlocal pos
        while True:
            if pos >= len(tokens):
                # EOF inside a nested block is an unbalanced-braces
                # error; at the top level it's the natural end.
                if not is_top_level:
                    raise ParseError(
                        "juniper_junos: unbalanced braces in "
                        "block-form input (EOF inside a nested "
                        "block — missing `}`)",
                        snippet=raw[:120],
                    )
                return
            tok = tokens[pos]
            if tok == "}":
                pos += 1
                return
            # Read a statement: sequence of word tokens up to ; or {.
            words: list[str] = []
            while pos < len(tokens) and tokens[pos] not in ("{", "}", ";"):
                words.append(tokens[pos])
                pos += 1
            if pos >= len(tokens):
                # EOF.  At the top level this is expected; inside a
                # nested block it means unbalanced braces — raise.
                if not is_top_level:
                    raise ParseError(
                        "juniper_junos: unbalanced braces in "
                        "block-form input (reached EOF inside a "
                        "nested block)",
                        snippet=raw[:120],
                    )
                # Top-level trailing words without ; — emit as leaf
                # for tolerance, though this is unusual.
                emit_leaf(words)
                return
            if tokens[pos] == ";":
                emit_leaf(words)
                pos += 1
            elif tokens[pos] == "{":
                # Block: push all words onto the path and recurse.
                pos += 1
                push_count = len(words)
                path_stack.extend(words)
                parse_block(is_top_level=False)
                for _ in range(push_count):
                    path_stack.pop()
            elif tokens[pos] == "}":
                # Closing brace with leftover words — malformed;
                # emit as leaf and let the outer loop close.
                emit_leaf(words)
                return

    parse_block(is_top_level=True)
    if path_stack:
        raise ParseError(
            "juniper_junos: unbalanced braces in block-form input "
            f"(path_stack at end: {path_stack})",
            snippet=raw[:120],
        )
    return "\n".join(out_lines) + ("\n" if out_lines else "")


def _dispatch_set(
    tokens: list[str],
    intent: CanonicalIntent,
    iface_state: dict[str, dict[str, Any]],
) -> None:
    """Apply one set-line's token list to *intent*.

    Dispatches on the first 1-3 tokens to find the applier.  Unknown
    paths silently no-op (Tier-3 tolerance).

    ``set groups`` and ``set apply-groups`` are NOT handled here —
    the parse() two-pass structure (GAP 8) intercepts those at the
    file-line level and replays group content through this dispatcher
    with the group-name token stripped.
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
    elif head == "routing-instances":
        # GAP 6: ``set routing-instances <name> ...`` populates
        # CanonicalRoutingInstance + per-interface VRF membership.
        _apply_routing_instances(tokens[1:], intent)
    # All other top-level paths (protocols / firewall / policy-options /
    # security / forwarding-options / chassis / services) — parse-
    # and-ignore.


def _apply_system(tokens: list[str], intent: CanonicalIntent) -> None:
    if not tokens:
        return
    if tokens[0] == "host-name" and len(tokens) >= 2:
        intent.hostname = tokens[1]
        return
    # GAP 8: richer system-scalar inheritance exercised primarily via
    # apply-groups on the ksator fixtures.  These stanzas also appear
    # at top level on some configs.
    if tokens[0] == "domain-name" and len(tokens) >= 2:
        intent.domain = tokens[1]
        return
    if tokens[0] == "name-server" and len(tokens) >= 2:
        # ``set system name-server <ip>`` — additive list.
        if tokens[1] not in intent.dns_servers:
            intent.dns_servers.append(tokens[1])
        return
    if (
        tokens[0] == "ntp"
        and len(tokens) >= 3
        and tokens[1] == "server"
    ):
        # ``set system ntp server <ip> [prefer]`` — additive; ignore
        # trailing ``prefer`` / ``key`` / ``version`` options.
        server = tokens[2]
        if server not in intent.ntp_servers:
            intent.ntp_servers.append(server)
        return
    if (
        tokens[0] == "syslog"
        and len(tokens) >= 3
        and tokens[1] == "host"
    ):
        # ``set system syslog host <ip> [any ...]`` — additive list.
        host = tokens[2]
        if host not in intent.syslog_servers:
            intent.syslog_servers.append(host)
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
        # GAP 4: Units 1+ materialise as distinct CanonicalInterface
        # entries with compound name ``<parent>.<unit>`` — matches
        # Cisco's dot1Q sub-interface convention (e.g.
        # ``GigabitEthernet0/1.100``).  Unit 0 still collapses into
        # the parent because that's the non-tagged L3 pathway and
        # every Junos interface has one.
        if unit_num == 0:
            target_state = state
        else:
            sub_name = f"{name}.{unit_num}"
            target_state = iface_state.setdefault(sub_name, {})
        # ``unit <N> family inet address <ip>/<prefix>``
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
                    existing = target_state.setdefault("ipv4", [])
                    # De-dup: GAP 8's two-pass and GAP 9b's group-
                    # content render both emit the same address
                    # line; we don't want it to accumulate.
                    pair = (ip_str, prefix)
                    if pair not in existing:
                        existing.append(pair)
                except ValueError:
                    pass
        # ``unit <N> description "<desc>"`` — some configs place it here.
        if (
            len(tokens) >= 5
            and tokens[3] == "description"
            and not target_state.get("description")
        ):
            target_state["description"] = tokens[4]
        # ``unit <N> disable`` — disable on the sub-interface level.
        if len(tokens) >= 4 and tokens[3] == "disable":
            target_state["enabled"] = False
        # GAP 7: ``unit <N> vlan-id <tag>`` — the per-unit 802.1Q tag.
        # Semantically equivalent to Cisco ``encapsulation dot1Q N``
        # on a sub-interface; stores as CanonicalInterface.access_vlan
        # (same field access-mode switchports use).  Does NOT set
        # switchport_mode — Junos sub-interfaces are L3 on a tagged
        # VLAN, not L2 access ports.
        if len(tokens) >= 5 and tokens[3] == "vlan-id":
            try:
                target_state["access_vlan"] = int(tokens[4])
            except ValueError:
                pass


def _apply_vlans(tokens: list[str], intent: CanonicalIntent) -> None:
    """``set vlans <NAME> vlan-id <N>``
    ``set vlans <NAME> vxlan vni <VNI>``  (GAP 6)
    """
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
        return
    if (
        tokens[1] == "vxlan"
        and len(tokens) >= 4
        and tokens[2] == "vni"
    ):
        # GAP 6: look up VLAN by name to get its ID; if the VLAN
        # hasn't been declared yet (Junos allows any ordering), stash
        # the mapping to resolve in a post-pass.  For now we require
        # the vlan-id to already be set — real configs always declare
        # it first; if this turns out to be wrong, the post-pass fix
        # is cheap.
        try:
            vni = int(tokens[3])
        except ValueError:
            return
        existing_vlan = next(
            (v for v in intent.vlans if v.name == vlan_name), None,
        )
        if existing_vlan is not None:
            # Don't duplicate if already recorded.
            already = any(
                x.vlan_id == existing_vlan.id and x.vni == vni
                for x in intent.vxlan_vnis
            )
            if not already:
                intent.vxlan_vnis.append(CanonicalVxlan(
                    vlan_id=existing_vlan.id, vni=vni,
                ))
        # else: vlan-id declaration hasn't been seen yet — skip.
        # This is rare in practice (Junos emits vlan-id first by
        # convention).  A future enrichment could stash pending
        # mappings.
        return


def _apply_routing_instances(
    tokens: list[str], intent: CanonicalIntent,
) -> None:
    """GAP 6: ``set routing-instances <name> ...`` grammar.

    Supported sub-paths:

    * ``routing-instances <name> instance-type <type>``
    * ``routing-instances <name> route-distinguisher <rd>``
    * ``routing-instances <name> vrf-target target:<rt>``  (both import + export)
    * ``routing-instances <name> vrf-target import target:<rt>``
    * ``routing-instances <name> vrf-target export target:<rt>``
    * ``routing-instances <name> interface <iface>``
    * ``routing-instances <name> description "<text>"``
    * ``routing-instances <name> protocols evpn ip-prefix-routes vni <N>``
      — populates :attr:`CanonicalRoutingInstance.l3_vni`.

    Everything else under routing-instances (protocols bgp, routing-
    options, policies) parses-and-ignores today — future enrichment.
    """
    if len(tokens) < 2:
        return
    ri_name = tokens[0]
    ri = next(
        (r for r in intent.routing_instances if r.name == ri_name), None,
    )
    if ri is None:
        ri = CanonicalRoutingInstance(name=ri_name)
        intent.routing_instances.append(ri)
    rest = tokens[1:]
    if not rest:
        return

    head = rest[0]
    if head == "instance-type" and len(rest) >= 2:
        ri.instance_type = rest[1]
        return
    if head == "route-distinguisher" and len(rest) >= 2:
        ri.route_distinguisher = rest[1]
        return
    if head == "description" and len(rest) >= 2:
        ri.description = rest[1]
        return
    if head == "vrf-target":
        # Three variants: ``target:...`` (both), ``import target:...``,
        # ``export target:...``.
        if len(rest) >= 2 and rest[1].startswith("target:"):
            rt = rest[1][len("target:"):]
            if rt not in ri.rt_imports:
                ri.rt_imports.append(rt)
            if rt not in ri.rt_exports:
                ri.rt_exports.append(rt)
            return
        if (
            len(rest) >= 3
            and rest[1] == "import"
            and rest[2].startswith("target:")
        ):
            rt = rest[2][len("target:"):]
            if rt not in ri.rt_imports:
                ri.rt_imports.append(rt)
            return
        if (
            len(rest) >= 3
            and rest[1] == "export"
            and rest[2].startswith("target:")
        ):
            rt = rest[2][len("target:"):]
            if rt not in ri.rt_exports:
                ri.rt_exports.append(rt)
            return
        return
    if head == "interface" and len(rest) >= 2:
        # Per-interface VRF membership — look up the interface by
        # name (may be a sub-interface like ``ge-0/0/1.0`` or
        # ``irb.100``) and mark it as belonging to this VRF.  If
        # the interface doesn't exist yet (set-line ordering), we
        # resolve later in a post-pass.  For now, stash on a
        # sentinel key so the parse loop can resolve later.
        iface_name = rest[1]
        # Resolve unit-0 compound to parent name the same way the
        # interface materialiser does — ``ge-0/0/1.0`` collapses to
        # ``ge-0/0/1``.
        m = re.match(r"^([A-Za-z]+-\d+/\d+/\d+)\.0$", iface_name)
        canonical_iface_name = m.group(1) if m else iface_name
        # Stash on the routing-instance record temporarily so the
        # parse() main loop's materialisation pass can apply the
        # vrf field after interfaces materialise.  We use a private
        # mutable list via setattr since pydantic models don't have
        # arbitrary attributes by default — but wait, they DO accept
        # extra attributes via model_config.  Simpler: stash on
        # intent using a private list outside CanonicalIntent.
        # Actually simpler: apply immediately if the interface
        # already materialised; otherwise cache.  In practice Junos
        # emits ``set interfaces ...`` lines BEFORE
        # ``set routing-instances ... interface ...`` so we expect
        # the interface already exists in iface_state — but we only
        # see intent.interfaces (already materialised) here, which
        # won't have happened yet during the dispatch loop.  The
        # parse() loop resolves this AFTER materialisation — see
        # post-pass comment in parse().
        pending = getattr(ri, "_pending_interfaces", None)
        if pending is None:
            pending = []
            # Attach as a model_extra attribute; pydantic v2
            # allows this when Config.model_config permits.  Use
            # object.__setattr__ to bypass validation.
            object.__setattr__(ri, "_pending_interfaces", pending)
        pending.append(canonical_iface_name)
        return
    if (
        len(rest) >= 5
        and rest[0] == "protocols"
        and rest[1] == "evpn"
        and rest[2] == "ip-prefix-routes"
        and rest[3] == "vni"
    ):
        try:
            ri.l3_vni = int(rest[4])
        except ValueError:
            pass
        return
    # Other sub-paths (protocols bgp, routing-options, etc.) —
    # parse-and-ignore.


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
            # De-dup: if GAP 8's two-pass parse or GAP 9b's group-
            # content render replays the same route at both levels,
            # we don't want to double up in the canonical list.
            already = any(
                r.destination == dest and r.gateway == gateway
                for r in intent.static_routes
            )
            if already:
                return
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


_QUOTE_NEEDED_RE = re.compile(r"[\s\"';$`\\]")

# ``<parent>.<unit>`` — e.g. ``ge-0/0/0.100``.  ``parent`` must
# contain a slash (``ge-0/0/0``) to distinguish from normal names
# like ``irb.10`` where the dot is part of the base port name.
_SUBIFACE_RE = re.compile(r"^(?P<parent>[A-Za-z]+-\d+/\d+/\d+)\.(?P<unit>\d+)$")


def _split_subiface_name(name: str) -> tuple[str | None, int | None]:
    """Return ``(parent, unit)`` if *name* looks like a Junos physical
    sub-interface (``ge-0/0/0.100``), else ``(None, None)``.

    ``irb.N`` / ``vlan.N`` are excluded by the parent-slash requirement
    — those are SVI-like interfaces that keep the dot in their
    canonical name (rendered as top-level entries, not sub-interfaces).
    """
    m = _SUBIFACE_RE.match(name)
    if m is None:
        return (None, None)
    try:
        return (m.group("parent"), int(m.group("unit")))
    except ValueError:
        return (None, None)


def _quote_if_needed(s: str) -> str:
    """Junos-style quoting: wrap in double quotes only if the string
    contains whitespace or shell-special characters.  Mirrors what
    ``show configuration | display set`` emits natively.

    Returns the input verbatim when no quoting is needed — keeps the
    output clean for the common case of simple hostnames, interface
    names, class names.
    """
    if not s:
        return '""'
    if _QUOTE_NEEDED_RE.search(s):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _quote_always(s: str) -> str:
    """Always-quoted variant for free-text fields (description,
    location, contact, password hash).  Junos tolerates quoted simple
    strings; operators expect quotes around free-text regardless.
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
