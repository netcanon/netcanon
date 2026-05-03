"""
Parse path for Juniper Junos CLI (set-form + block-form).

Public function: :func:`parse_intent` — raw text in,
:class:`CanonicalIntent` out.

Two-pass parse: groups bucketed first, replayed in reverse-apply-
groups order, then top-level dispatch.  Block-form (curly-brace
hierarchical) input is converted to set-form by
:func:`_blockform_to_setform` before the normal set-form parser
runs, so the dispatch surface is identical for both grammars.

Handles VXLAN switch-options globals (``set switch-options
vtep-source-interface`` / ``vxlan-port``) by stashing on intent
scratch attributes during dispatch and back-patching every
:class:`CanonicalVxlan` record uniformly in a post-pass — Junos
emits these lines in arbitrary order relative to the per-VLAN
``vxlan vni`` declarations.

Stable across Junos 15-21+.

Extracted verbatim from ``codec.py`` during the parse/render split;
behaviour is identical to the prior in-class implementation.  The
codec module's ``parse()`` method is now a one-line delegator to
:func:`parse_intent`.

Internal helpers (``_tokenise_set``, ``_dispatch_set``,
``_apply_system``, ``_apply_interfaces``, ``_apply_interface_range``,
``_apply_vlans``, ``_apply_switch_options``,
``_apply_routing_instances``, ``_apply_routing_options``,
``_apply_snmp``, ``_apply_snmp_v3``, ``_get_or_create_v3_user``,
``_looks_like_blockform``, ``_tokenise_blockform``,
``_blockform_to_setform``, ``_infer_iface_type``) and the module-
level constants (``_BLOCKFORM_COMMENT_RE``, ``_JUNOS_AUTH_MAP``,
``_JUNOS_PRIV_MAP``) live here because they are parse-only.
"""

from __future__ import annotations

import logging
import re
import shlex
from typing import Any

from ...canonical.intent import (
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRoutingInstance,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVxlan,
)
from ..base import ParseError

logger = logging.getLogger(__name__)


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse Junos ``set``-form (or block-form) text to CanonicalIntent."""
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
    # Phase 4 rank-4: LAG accumulator (ae<N> aggregated-ether-
    # options).  Keyed by ae-name; each entry holds members + LACP mode.
    lag_state: dict[str, dict[str, Any]] = {}
    # Phase 4 rank-4: IRB SVI accumulator.  Keyed by vid (the irb
    # unit number); each entry holds the per-vid IPv4 list.
    irb_state: dict[int, dict[str, Any]] = {}
    # Structural-collapse accumulator: Junos's ``set interfaces
    # interface-range <name>`` grammar declares shared config
    # across multiple physical interfaces.  We collect members
    # + shared attrs per range, then apply to each member at
    # materialisation time so the canonical tree looks the
    # same whether the operator wrote interface-range blocks
    # or flat per-interface lines.
    range_state: dict[str, dict[str, Any]] = {}
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
            _dispatch_set(
                tokens, intent, iface_state, range_state,
                lag_state, irb_state,
            )
    # Pass 2b: apply top-level content.  Scalars set by group
    # content get overwritten; list-shaped fields accumulate
    # (duplicate-add protection lives in each _apply_* function).
    for tokens in top_level_lines:
        _dispatch_set(
            tokens, intent, iface_state, range_state,
            lag_state, irb_state,
        )

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

    # Structural collapse: before materialising, fold each
    # interface-range's shared attrs onto every member that was
    # declared via `... interface-range X member <iface>`.  Each
    # member still gets its per-interface state from iface_state
    # (if any); range attrs act as defaults that per-interface
    # lines can overwrite.  Record per-member the range name so
    # render can re-emit the collapsed block.
    range_membership: dict[str, str] = {}
    for rname, rstate in range_state.items():
        attrs = rstate.get("attrs", {})
        for member in rstate.get("members", []):
            member_state = iface_state.setdefault(member, {})
            range_membership[member] = rname
            # Shared scalars default when member-state doesn't
            # override.  member_state wins on conflict.
            if "description" in attrs and not member_state.get("description"):
                member_state["description"] = attrs["description"]
            if "mtu" in attrs and "mtu" not in member_state:
                member_state["mtu"] = attrs["mtu"]
            if attrs.get("enabled") is False and "enabled" not in member_state:
                member_state["enabled"] = False
            for addr in attrs.get("ipv4", []):
                if "/" in addr:
                    ip_str, prefix_str = addr.split("/", 1)
                    try:
                        prefix = int(prefix_str)
                        existing = member_state.setdefault("ipv4", [])
                        pair = (ip_str, prefix)
                        if pair not in existing:
                            existing.append(pair)
                    except ValueError:
                        pass
            # GAP-EVPN-3: same shape for v6 addresses on
            # interface-range members.
            for addr in attrs.get("ipv6", []):
                if "/" in addr:
                    ip_str, prefix_str = addr.split("/", 1)
                    try:
                        prefix = int(prefix_str)
                        existing = member_state.setdefault("ipv6", [])
                        pair = (ip_str, prefix)
                        if pair not in existing:
                            existing.append(pair)
                    except ValueError:
                        pass

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
            # interface-range / structural collapse: mtu may
            # have been populated from a ``set interfaces
            # interface-range <r> mtu <N>`` line via the
            # range-fold pass.
            mtu=state.get("mtu"),
            # Phase 4 rank-4: L2 switchport semantics.
            switchport_mode=state.get("switchport_mode"),
            trunk_native_vlan=state.get("trunk_native_vlan"),
            lag_member_of=state.get("lag_member_of"),
            # Wave-6 render-side emit at 5edf800 surfaces
            # ``set interfaces <name> unit 0 family inet dhcp`` for
            # ``iface.dhcp_client=True``.  Parser symmetry: recognise
            # the same token shape and round-trip the flag.
            dhcp_client=state.get("dhcp_client", False),
        )
        for ip, prefix in state.get("ipv4", []):
            iface.ipv4_addresses.append(
                CanonicalIPv4Address(ip=ip, prefix_length=prefix)
            )
        # GAP-EVPN-3: IPv6 addresses.  Scope inferred from the
        # fe80::/10 prefix (Junos doesn't keyword-tag link-local).
        # fe80::/10 covers fe80::/16 through febf::/16 (first 10
        # bits are 1111111010 = fe + {8,9,a,b}<rest>).
        for ip, prefix in state.get("ipv6", []):
            lo = ip.lower()
            scope = (
                "link-local"
                if (
                    len(lo) >= 3
                    and lo[:2] == "fe"
                    and lo[2] in ("8", "9", "a", "b")
                )
                else "global"
            )
            iface.ipv6_addresses.append(
                CanonicalIPv6Address(
                    ip=ip,
                    prefix_length=prefix,
                    scope=scope,
                )
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
            # Phase 4 rank-5: routing-instances reference UNITs
            # (``Loopback0.0``); canonical stores parent (``Loopback0``).
            # See PHASE4_RECONCILIATION.md rank 5 (~18 cells).
            if iface is None and iface_name.endswith(".0"):
                iface = iface_by_name.get(iface_name[:-2])
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

    # --- Phase 4 rank-4: LAG / IRB / L2 vlan-members post-pass ---
    #
    # 1. Materialise CanonicalLAG records from the lag_state
    #    accumulator.  Each entry is keyed by ae-name (e.g. ``ae0``)
    #    with the ordered member list and the LACP mode.
    for ae_name, lag_entry in lag_state.items():
        members = list(lag_entry.get("members", []))
        mode = lag_entry.get("mode", "active") or "active"
        # Don't accumulate duplicates if the same LAG already exists
        # (defensive for groups + apply-groups composition).
        existing = next(
            (l for l in intent.lags if l.name == ae_name), None,
        )
        if existing is None:
            intent.lags.append(
                CanonicalLAG(name=ae_name, members=members, mode=mode)
            )
        else:
            existing.mode = mode
            for m in members:
                if m not in existing.members:
                    existing.members.append(m)

    # 2. Resolve L2 ``vlan members <NAME>`` lists on access / trunk
    #    interfaces — convert vlan-name lookups to numeric VIDs by
    #    consulting intent.vlans.  Names that don't resolve are
    #    silently dropped (parse tolerance).
    vid_by_vlan_name = {v.name: v.id for v in intent.vlans if v.name}
    for name, state in iface_state.items():
        names_list = state.get("l2_vlan_member_names")
        if not names_list:
            continue
        iface = iface_by_name.get(name)
        if iface is None:
            continue
        if iface.switchport_mode == "access":
            # Access mode: the first resolved member becomes the
            # access_vlan (operators rarely declare more than one).
            for vname in names_list:
                vid = vid_by_vlan_name.get(vname)
                if vid is not None:
                    iface.access_vlan = vid
                    break
        elif iface.switchport_mode == "trunk":
            # Junos `vlan members all` is the operator-form for "all
            # VLANs allowed on this trunk" — match Arista's
            # `switchport trunk allowed vlan all` / `1-4094` /
            # `2-4094`.  Expand to the full VID range so canonical
            # comparison and any cross-vendor render carry the same
            # semantic (Arista will collapse 2-4094 back to its own
            # all-form on the symmetric render path).
            if any(vname == "all" for vname in names_list):
                iface.trunk_allowed_vlans = list(range(1, 4095))
                continue
            for vname in names_list:
                vid = vid_by_vlan_name.get(vname)
                if vid is not None and vid not in iface.trunk_allowed_vlans:
                    iface.trunk_allowed_vlans.append(vid)

    # 3. Attach IRB SVI L3 addresses to the matching CanonicalVlan
    #    AND prune the redundant irb.<vid> interface — but ONLY
    #    when:
    #
    #    * The operator declared a ``set vlans <NAME> l3-interface
    #      irb.<vid>`` binding (signalling SVI intent), AND
    #    * The irb.<vid> interface has no load-bearing fields
    #      beyond IPv4 (no VRF binding, no description, no IPv6,
    #      no LAG membership).
    #
    #    A real-capture fixture from Batfish (``junos2541``) carries
    #    irb.<vid> bindings inside ``routing-instances`` (VRF) — we
    #    must preserve those interfaces as-is so the routing-
    #    instance round-trips correctly.  The cross-vendor
    #    Aruba/OPNsense -> Junos render case the rank-4 fix
    #    targets always emits a fresh irb.<vid> with no VRF binding,
    #    which IS safe to fold onto the vlan.
    bound_vids: set[int] = set()
    for vid, irb_entry in irb_state.items():
        if "vlan_name" not in irb_entry:
            # No l3-interface binding — preserve irb.<vid> as-is.
            continue
        # Check whether the irb.<vid> interface (if it exists) has
        # any load-bearing field that would be lost on prune.
        sub_iface = iface_by_name.get(f"irb.{vid}")
        if sub_iface is not None and (
            sub_iface.vrf
            or sub_iface.description
            or sub_iface.ipv6_addresses
            or sub_iface.lag_member_of
        ):
            # Load-bearing — leave the iface alone, don't fold to vlan.
            continue
        vlan = next((v for v in intent.vlans if v.id == vid), None)
        if vlan is None:
            stub_name = irb_entry.get("vlan_name", f"VLAN-{vid}")
            vlan = CanonicalVlan(id=vid, name=stub_name)
            intent.vlans.append(vlan)
        for ip, prefix in irb_entry.get("ipv4", []):
            existing_addrs = {
                (a.ip, a.prefix_length) for a in vlan.ipv4_addresses
            }
            if (ip, prefix) not in existing_addrs:
                vlan.ipv4_addresses.append(
                    CanonicalIPv4Address(ip=ip, prefix_length=prefix)
                )
        bound_vids.add(vid)

    # 4. Prune the synthetic ``irb`` carrier and any ``irb.<vid>``
    #    sub-interfaces that were folded onto a CanonicalVlan in
    #    step 3.  ``bound_vids`` only contains vids that were
    #    safely foldable (no VRF / description / v6 / LAG).
    pruned: list[CanonicalInterface] = []
    for iface in intent.interfaces:
        if iface.name == "irb":
            # The bare ``irb`` carrier — only prune when at least
            # one bound vid was folded.  Otherwise keep it.
            if (
                bound_vids
                and not iface.description
                and not iface.ipv6_addresses
                and not iface.lag_member_of
                and not iface.vrf
            ):
                continue
        elif iface.name.startswith("irb."):
            try:
                sub_vid = int(iface.name[4:])
            except ValueError:
                sub_vid = -1
            if sub_vid in bound_vids:
                continue
        pruned.append(iface)
    if len(pruned) != len(intent.interfaces):
        intent.interfaces = pruned
        iface_by_name = {i.name: i for i in intent.interfaces}

    # GAP-EVPN-2: stamp every CanonicalVxlan record with the
    # switch-level vtep-source-interface + vxlan-port we observed.
    # Both default to no-op; non-default values overwrite every
    # record uniformly (matches Junos's switch-level semantic).
    pending_si = getattr(intent, "_pending_vxlan_source_interface", "")
    pending_up = getattr(intent, "_pending_vxlan_udp_port", 4789)
    if intent.vxlan_vnis and (pending_si or pending_up != 4789):
        for rec in intent.vxlan_vnis:
            if pending_si and not rec.source_interface:
                rec.source_interface = pending_si
            if pending_up and rec.udp_port == 4789:
                rec.udp_port = pending_up
    # Clean up scratch attrs so they don't leak.
    for attr in ("_pending_vxlan_source_interface", "_pending_vxlan_udp_port"):
        try:
            object.__delattr__(intent, attr)
        except AttributeError:
            pass

    # Bug 3 transpose: mirror per-port switchport state into the
    # VLAN-centric tagged_ports / untagged_ports lists so VLAN-
    # centric renderers (Aruba, OPNsense) can emit the membership.
    # Junos parses ethernet-switching subcommands into per-iface
    # switchport_mode / access_vlan / trunk_allowed_vlans; without
    # this projection, those bindings never reach a VLAN-centric
    # target.  See translator-plans.txt BUG 3.
    from ...canonical.transforms import project_switchport_to_vlan
    project_switchport_to_vlan(intent)

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
    range_state: dict[str, dict[str, Any]] | None = None,
    lag_state: dict[str, dict[str, Any]] | None = None,
    irb_state: dict[int, dict[str, Any]] | None = None,
) -> None:
    """Apply one set-line's token list to *intent*.

    Dispatches on the first 1-3 tokens to find the applier.  Unknown
    paths silently no-op (Tier-3 tolerance).

    ``set groups`` and ``set apply-groups`` are NOT handled here —
    the parse() two-pass structure (GAP 8) intercepts those at the
    file-line level and replays group content through this dispatcher
    with the group-name token stripped.

    ``range_state`` is the interface-range accumulator (optional —
    callers in isolated tests may omit it).  ``lag_state`` /
    ``irb_state`` cover the Phase 4 rank-4 surfaces (LAG ae<N> +
    IRB SVI L3); also optional for legacy callers.
    """
    if not tokens:
        return
    head = tokens[0]
    if head == "system":
        _apply_system(tokens[1:], intent)
    elif head == "interfaces":
        _apply_interfaces(
            tokens[1:], iface_state, range_state, lag_state, irb_state,
        )
    elif head == "vlans":
        _apply_vlans(tokens[1:], intent, irb_state)
    elif head == "routing-options":
        _apply_routing_options(tokens[1:], intent)
    elif head == "snmp":
        _apply_snmp(tokens[1:], intent)
    elif head == "routing-instances":
        # GAP 6: ``set routing-instances <name> ...`` populates
        # CanonicalRoutingInstance + per-interface VRF membership.
        _apply_routing_instances(tokens[1:], intent)
    elif head == "switch-options":
        # GAP-EVPN-2: ``set switch-options vtep-source-interface <NAME>``
        # and ``set switch-options vxlan-port <N>`` are switch-level
        # globals that apply to every CanonicalVxlan record.  Capture
        # into intent-level scratch state on the intent so the post-
        # pass can stamp them onto records (which may have been
        # appended by ``set vlans <NAME> vxlan vni <N>`` either before
        # or after these lines).
        _apply_switch_options(tokens[1:], intent)
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
    range_state: dict[str, dict[str, Any]] | None = None,
    lag_state: dict[str, dict[str, Any]] | None = None,
    irb_state: dict[int, dict[str, Any]] | None = None,
) -> None:
    """Parse ``interfaces <name> ...`` variants.

    Special case: ``interfaces interface-range <rname> ...`` routes to
    the structural-collapse accumulator so shared attrs apply to each
    member interface at materialisation time.

    Phase 4 rank-4 additions (when *lag_state* / *irb_state* are
    provided):

    * ``interfaces ae<N> aggregated-ether-options lacp <mode>`` —
      captured into *lag_state* under the ae-name; the materialiser
      turns it into a :class:`CanonicalLAG` record.
    * ``interfaces <member> ether-options 802.3ad ae<N>`` — sets the
      member's ``lag_member_of`` and registers the member with
      *lag_state*.
    * ``interfaces <name> unit 0 family ethernet-switching ...`` —
      switchport semantics (interface-mode + vlan members).
    * ``interfaces <name> native-vlan-id <vid>`` — trunk native VLAN.
    * ``interfaces irb unit <vid> family inet address <ip>/<prefix>`` —
      VLAN SVI L3 address; captured into *irb_state* keyed by vid.
    """
    if not tokens:
        return
    # Interface-range special case: ``interfaces interface-range
    # <rname> ...`` declares shared config across multiple members.
    if (
        tokens[0] == "interface-range"
        and len(tokens) >= 2
        and range_state is not None
    ):
        _apply_interface_range(tokens[1:], range_state)
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

    # ``interfaces <name> mtu <N>`` — shared attribute the
    # structural-collapse render auto-detects.
    if second == "mtu" and len(tokens) >= 3:
        try:
            state["mtu"] = int(tokens[2])
        except ValueError:
            pass
        return

    # --- Phase 4 rank-4: LAG ae<N> aggregated-ether-options ---
    if (
        second == "aggregated-ether-options"
        and len(tokens) >= 4
        and tokens[2] == "lacp"
        and lag_state is not None
    ):
        ae_name = name
        mode = tokens[3]
        if mode not in ("active", "passive"):
            mode = "active"
        entry = lag_state.setdefault(ae_name, {"members": [], "mode": "active"})
        entry["mode"] = mode
        return

    # --- Phase 4 rank-4: LAG member binding ---
    if (
        second == "ether-options"
        and len(tokens) >= 4
        and tokens[2] == "802.3ad"
        and lag_state is not None
    ):
        ae_name = tokens[3]
        state["lag_member_of"] = ae_name
        entry = lag_state.setdefault(ae_name, {"members": [], "mode": "active"})
        if name not in entry["members"]:
            entry["members"].append(name)
        return

    # --- Phase 4 rank-4: trunk native VLAN ---
    if second == "native-vlan-id" and len(tokens) >= 3:
        try:
            state["trunk_native_vlan"] = int(tokens[2])
        except ValueError:
            pass
        return

    # ``interfaces <name>.<unit> family inet dhcp`` — the dotted-unit
    # shorthand for ``unit <N> family inet dhcp``.  Wave-6 render
    # symmetry: only the bare-unit-0 form is currently emitted, but
    # operators can paste either form and we should round-trip both.
    # Any other ``family`` payload on the dotted-unit form falls
    # through to parse-and-ignore (the regular sub-finding for IPv4
    # / IPv6 addresses on dotted-unit names is out of scope here).
    if (
        second == "family"
        and len(tokens) == 4
        and tokens[2] == "inet"
        and tokens[3] == "dhcp"
    ):
        # Resolve dotted-unit ``<name>.<unit>`` to the right state
        # bucket: unit 0 collapses onto the parent interface (matching
        # the ``unit 0 family inet dhcp`` branch above); units 1+ are
        # distinct sub-interfaces with compound names.
        m = re.match(r"^(.+)\.(\d+)$", name)
        if m:
            parent, unit_str = m.group(1), m.group(2)
            try:
                unit_num = int(unit_str)
            except ValueError:
                return
            if unit_num == 0:
                target_state = iface_state.setdefault(parent, {})
                # The bucket originally created under the dotted name
                # is empty / spurious — drop it so it doesn't leak
                # an empty ``ge-0/0/0.0`` interface into materialisation.
                iface_state.pop(name, None)
            else:
                target_state = state
            target_state["dhcp_client"] = True
        else:
            # No unit suffix — treat as bare interface (rare but
            # possible for non-physical names).
            state["dhcp_client"] = True
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
        # ``unit <N> family inet dhcp`` — parser symmetry for the
        # wave-6 render-side emit at 5edf800.  Junos models the DHCP
        # client as a property of ``family inet`` (replacing the
        # ``address`` clause); same-vendor round-trip and any
        # cross-vendor flow that lands on Junos-set-input must
        # recover ``iface.dhcp_client=True``.
        if (
            len(tokens) == 6
            and tokens[3] == "family"
            and tokens[4] == "inet"
            and tokens[5] == "dhcp"
        ):
            target_state["dhcp_client"] = True
        # GAP-EVPN-3: ``unit <N> family inet6 address <ipv6>/<prefix>``.
        # Junos treats global / link-local uniformly here (unlike
        # Cisco / Arista which keyword-tag link-local); we infer the
        # canonical scope from the fe80::/10 prefix at materialisation
        # time so render-side scope handling is loss-free.
        if (
            len(tokens) >= 7
            and tokens[3] == "family"
            and tokens[4] == "inet6"
            and tokens[5] == "address"
        ):
            addr = tokens[6]
            if "/" in addr:
                ip_str, prefix_str = addr.split("/", 1)
                try:
                    prefix = int(prefix_str)
                    existing = target_state.setdefault("ipv6", [])
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

        # --- Phase 4 rank-4: L2 family ethernet-switching ---
        # ``unit 0 family ethernet-switching interface-mode access|trunk``
        if (
            unit_num == 0
            and len(tokens) >= 7
            and tokens[3] == "family"
            and tokens[4] == "ethernet-switching"
            and tokens[5] == "interface-mode"
        ):
            mode = tokens[6]
            if mode in ("access", "trunk"):
                target_state["switchport_mode"] = mode

        # ``unit 0 family ethernet-switching vlan members <NAME>``
        if (
            unit_num == 0
            and len(tokens) >= 8
            and tokens[3] == "family"
            and tokens[4] == "ethernet-switching"
            and tokens[5] == "vlan"
            and tokens[6] == "members"
        ):
            target_state.setdefault(
                "l2_vlan_member_names", [],
            ).append(tokens[7])

        # --- Phase 4 rank-4: IRB SVI L3 ---
        # ``set interfaces irb unit <vid> family inet address <ip>/<prefix>``
        if (
            name == "irb"
            and irb_state is not None
            and len(tokens) >= 7
            and tokens[3] == "family"
            and tokens[4] == "inet"
            and tokens[5] == "address"
        ):
            addr = tokens[6]
            if "/" in addr:
                ip_str, prefix_str = addr.split("/", 1)
                try:
                    prefix = int(prefix_str)
                    entry = irb_state.setdefault(unit_num, {"ipv4": []})
                    pair = (ip_str, prefix)
                    if pair not in entry["ipv4"]:
                        entry["ipv4"].append(pair)
                except ValueError:
                    pass


def _apply_interface_range(
    tokens: list[str],
    range_state: dict[str, dict[str, Any]],
) -> None:
    """Parse ``interfaces interface-range <rname> ...`` variants.

    Supported sub-paths (subset of Junos full grammar — we capture
    the attributes the render side auto-collapses, plus members):

    * ``interface-range <rname> member <iface>``
    * ``interface-range <rname> description "<desc>"``
    * ``interface-range <rname> mtu <N>``
    * ``interface-range <rname> disable``
    * ``interface-range <rname> unit 0 family inet address <ip>/<prefix>``

    Collected state gets applied to each member interface at
    materialisation time so the canonical tree looks identical
    whether the operator wrote interface-range blocks or flat
    per-interface lines.  Unknown sub-paths parse-and-ignore.
    """
    if not tokens:
        return
    rname = tokens[0]
    state = range_state.setdefault(rname, {"members": [], "attrs": {}})
    if len(tokens) < 2:
        return
    sub = tokens[1]
    if sub == "member" and len(tokens) >= 3:
        member = tokens[2]
        if member not in state["members"]:
            state["members"].append(member)
        return
    if sub == "description" and len(tokens) >= 3:
        state["attrs"]["description"] = tokens[2]
        return
    if sub == "mtu" and len(tokens) >= 3:
        try:
            state["attrs"]["mtu"] = int(tokens[2])
        except ValueError:
            pass
        return
    if sub == "disable":
        state["attrs"]["enabled"] = False
        return
    # ``unit 0 family inet address <ip>/<prefix>`` — shared IP
    # across members is rare but legal; collect for post-pass.
    if (
        sub == "unit"
        and len(tokens) >= 7
        and tokens[2] == "0"
        and tokens[3] == "family"
        and tokens[4] == "inet"
        and tokens[5] == "address"
    ):
        state["attrs"].setdefault("ipv4", []).append(tokens[6])
    # GAP-EVPN-3: ``unit 0 family inet6 address <ipv6>/<prefix>``.
    if (
        sub == "unit"
        and len(tokens) >= 7
        and tokens[2] == "0"
        and tokens[3] == "family"
        and tokens[4] == "inet6"
        and tokens[5] == "address"
    ):
        state["attrs"].setdefault("ipv6", []).append(tokens[6])
    # Everything else parses-and-ignores.


def _apply_vlans(
    tokens: list[str],
    intent: CanonicalIntent,
    irb_state: dict[int, dict[str, Any]] | None = None,
) -> None:
    """``set vlans <NAME> vlan-id <N>``
    ``set vlans <NAME> vxlan vni <VNI>``  (GAP 6)
    ``set vlans <NAME> l3-interface irb.<vid>``  (Phase 4 rank-4)
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
    # Phase 4 rank-4: l3-interface binding.  Capture the name->vid
    # link so the post-pass can attach IRB addresses to the right
    # CanonicalVlan.
    if tokens[1] == "l3-interface" and irb_state is not None:
        irb_target = tokens[2]
        if irb_target.startswith("irb."):
            try:
                vid = int(irb_target[4:])
            except ValueError:
                return
            entry = irb_state.setdefault(vid, {"ipv4": []})
            entry["vlan_name"] = vlan_name
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


def _apply_switch_options(tokens: list[str], intent: CanonicalIntent) -> None:
    """GAP-EVPN-2: ``set switch-options vtep-source-interface <NAME>``
    and ``set switch-options vxlan-port <N>`` are switch-level globals
    that apply to every CanonicalVxlan record.  Stash on a scratch
    attribute on *intent*; a post-pass after the dispatcher finishes
    stamps the value onto every CanonicalVxlan record.

    The post-pass is needed (rather than stamping inline) because Junos
    set-form is order-independent — operators sometimes emit
    ``set vlans <NAME> vxlan vni <N>`` BEFORE the corresponding
    ``set switch-options vtep-source-interface <iface>`` line.

    Other sub-paths under ``switch-options`` (route-distinguisher,
    vrf-target, vtep-remote-vtep) parse-and-ignore today.  Their
    EVPN semantics overlap with CanonicalRoutingInstance fields but
    on a switch-options scope rather than a routing-instances scope,
    and the cross-vendor mapping is non-trivial enough to defer.
    """
    if len(tokens) < 2:
        return
    head = tokens[0]
    if head == "vtep-source-interface":
        # Stash on intent for the post-pass to consume.
        setattr(intent, "_pending_vxlan_source_interface", tokens[1])
        return
    if head == "vxlan-port":
        try:
            port = int(tokens[1])
        except ValueError:
            return
        setattr(intent, "_pending_vxlan_udp_port", port)
        return
    # Other switch-options paths — parse-and-ignore.


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
    ``set snmp trap-group <name> targets <ip>``
    ``set snmp v3 usm local-engine user <name> authentication-<proto>
        authentication-key "<key>"``
    ``set snmp v3 usm local-engine user <name> privacy-<proto>
        privacy-key "<key>"``
    ``set snmp v3 vacm security-to-group security-model usm
        security-name <name> group <group>``
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
    elif head == "v3":
        _apply_snmp_v3(tokens[1:], intent)


# Junos authentication-* → canonical auth_protocol short form.
_JUNOS_AUTH_MAP = {
    "authentication-md5": "md5",
    "authentication-sha": "sha",
    "authentication-sha224": "sha224",
    "authentication-sha256": "sha256",
    "authentication-sha384": "sha384",
    "authentication-sha512": "sha512",
    "authentication-none": "",
}
# Junos privacy-* → canonical priv_protocol short form.
_JUNOS_PRIV_MAP = {
    "privacy-des": "des",
    "privacy-3des": "3des",
    "privacy-aes128": "aes128",
    "privacy-aes192": "aes192",
    "privacy-aes256": "aes256",
    "privacy-none": "",
}


def _get_or_create_v3_user(
    snmp: CanonicalSNMP,
    name: str,
) -> Any:
    """Look up the SNMPv3 user record by name, creating a stub if
    absent.  Merging lets the user's auth key, priv key, and VACM
    group binding arrive in any order (``set snmp v3`` lines can be
    scattered across the config).
    """
    from ...canonical.intent import CanonicalSNMPv3User
    for u in snmp.v3_users:
        if u.name == name:
            return u
    u = CanonicalSNMPv3User(name=name)
    snmp.v3_users.append(u)
    return u


def _apply_snmp_v3(tokens: list[str], intent: CanonicalIntent) -> None:
    """Handle ``set snmp v3 ...`` tails.

    Two families:

    * ``usm local-engine user <name> authentication-<proto>
      authentication-key "<key>"`` and
      ``usm local-engine user <name> privacy-<proto>
      privacy-key "<key>"`` — populate auth / priv fields.
    * ``vacm security-to-group security-model usm security-name
      <name> group <group>`` — populate group on the matching user.

    Malformed / unrecognised sub-paths are silently ignored — other
    ``set snmp v3`` lines (trap-target, notify-view, access) are
    Tier-3 and out of this codec's scope.
    """
    if intent.snmp is None:
        intent.snmp = CanonicalSNMP()
    # ``usm local-engine user <name> ...``
    if (
        len(tokens) >= 6
        and tokens[0] == "usm"
        and tokens[1] == "local-engine"
        and tokens[2] == "user"
    ):
        name = tokens[3]
        attr = tokens[4]
        value = tokens[5] if len(tokens) >= 6 else ""
        # Drop the trailing ``authentication-key`` / ``privacy-key``
        # sentinel if present (``authentication-sha
        # authentication-key "<hash>"`` lands as 6 tokens).
        if attr in _JUNOS_AUTH_MAP and len(tokens) >= 7:
            key_tok = tokens[5]
            key_val = tokens[6]
            if key_tok == "authentication-key":
                u = _get_or_create_v3_user(intent.snmp, name)
                u.auth_protocol = _JUNOS_AUTH_MAP[attr]
                u.auth_passphrase = key_val
                return
        if attr in _JUNOS_PRIV_MAP and len(tokens) >= 7:
            key_tok = tokens[5]
            key_val = tokens[6]
            if key_tok == "privacy-key":
                u = _get_or_create_v3_user(intent.snmp, name)
                u.priv_protocol = _JUNOS_PRIV_MAP[attr]
                u.priv_passphrase = key_val
                return
        # Bare ``authentication-none`` / ``privacy-none`` (no key
        # follows) — clears the corresponding field.
        if attr == "authentication-none":
            u = _get_or_create_v3_user(intent.snmp, name)
            u.auth_protocol = ""
            u.auth_passphrase = ""
            return
        if attr == "privacy-none":
            u = _get_or_create_v3_user(intent.snmp, name)
            u.priv_protocol = ""
            u.priv_passphrase = ""
            return
    # ``vacm security-to-group security-model usm security-name <n>
    # group <g>``
    if (
        len(tokens) >= 8
        and tokens[0] == "vacm"
        and tokens[1] == "security-to-group"
        and tokens[2] == "security-model"
        and tokens[3] == "usm"
        and tokens[4] == "security-name"
        and tokens[6] == "group"
    ):
        name = tokens[5]
        group = tokens[7]
        u = _get_or_create_v3_user(intent.snmp, name)
        u.group = group


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
