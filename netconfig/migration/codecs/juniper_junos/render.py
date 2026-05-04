"""
Render path: emits set-form Junos config from CanonicalIntent.

Public function: :func:`render_intent` — :class:`CanonicalIntent`
in, Junos ``set``-form text out.

Emits the same surfaces the parse path consumes: hostname / domain /
DNS / NTP / syslog (under ``set system``), local users
(``set system login user``), interfaces (with IPv4 / IPv6, MTU,
disable, sub-interface unit splits, access_vlan as per-unit
``vlan-id``), interface-range auto-collapse for >=3 simple
interfaces sharing a (mtu, description, enabled) tuple, VLANs
(plus VLAN-to-VNI mappings for VXLAN), switch-options
(``vtep-source-interface`` / ``vxlan-port`` switch-level globals),
routing-instances (instance-type, RD/RT, interface bindings, L3
VNI for EVPN Type-5), routing-options static routes, SNMP
(community / location / contact / trap-group / v3 USM users +
VACM groups), and apply-groups + group-content for round-trip
fidelity (GAP 9b).

Strings with whitespace or shell-special characters are double-
quoted via :func:`_quote_if_needed`; free-text fields use
:func:`_quote_always`.  Hashes stored under the ``junos:<hash>``
vendor tag get their prefix stripped on render so
``parse(render(tree))`` is a true round-trip.

Cross-vendor user-secret hashes (Cisco type-9 ``9 $9$..``,
FortiGate ``ENC ..``, etc.) cannot be re-used on Junos.  The
``..._user_secrets`` module's :func:`is_migratable` policy gate
decides per-hash whether to emit ``set system login user X
authentication encrypted-password "..."`` or fall back to a
``# password manager user-name "X" -- review:`` comment line.
Junos comments use ``#`` (or ``/* .. */``) so :func:`format_review_comment`
is called with ``comment_syntax="hash"``.  Empty interface stubs
(no IP / no description / no L2 / no LAG / no VRF binding, and
not the parent of any sub-unit) are suppressed entirely; VRF-bound
stubs keep the bare ``set interfaces <name>`` line because Junos's
commit-time validator requires the interface to be defined under
``[edit interfaces]`` before a routing-instance can reference it.

Apply-groups inheritance is wired both ways: parse buckets group
content separately and replays it via the two-pass dispatch in
``parse.py``; render re-emits the captured group bodies + the
``set apply-groups`` statements so the rendered output looks like
hand-written Junos again.

Extracted verbatim from ``codec.py`` during the parse/render split;
behaviour is identical to the prior in-class implementation.  The
codec module's ``render()`` method is now a one-line delegator to
:func:`render_intent`.

Internal helpers (``_split_subiface_name``, ``_quote_if_needed``,
``_quote_always``) and module-level constants (``_QUOTE_NEEDED_RE``,
``_SUBIFACE_RE``) live here because they are render-only.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..._user_secrets import (
    classify_hash,
    format_review_comment,
    is_migratable,
)
from ...canonical.intent import CanonicalIntent

logger = logging.getLogger(__name__)


def render_intent(tree: Any) -> str:
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

    # Materialise port-centric switchport state from VLAN-centric
    # membership lists.  Required for cross-vendor renders from
    # codecs that emit no per-port stanzas (Aruba AOS-S, OPNsense)
    # — without this, a tree whose only L2 information lives in
    # ``CanonicalVlan.tagged_ports`` / ``untagged_ports`` would
    # render zero L2 config on Junos.  Idempotent + additive —
    # same-vendor round-trips where iface fields are already
    # populated are no-ops.  Mirrors the same call in the Cisco
    # IOS-XE CLI render path.  Phase 4 rank-4 finding (~22 cells).
    from ...canonical.transforms import project_vlan_to_switchport
    project_vlan_to_switchport(tree)

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
        # Hash-gate FIRST: when the source hash is unmigratable to
        # Junos, drop the user entirely.  Emitting just the bare
        # ``set system login user X class Y`` line (without any
        # ``authentication encrypted-password`` line) creates a
        # passwordless account at commit time on Junos — strictly
        # worse than the source state.  Mirror Cisco IOS-XE's
        # ``continue``-on-unmigratable pattern (cisco_iosxe_cli/
        # render.py line ~117): emit the review comment naming the
        # user and skip the rest of the user-emit body.  Operator
        # gets an explicit "reset this password manually" signal
        # without a security regression in the deployed config.
        # Finding #16 in user_smoke_findings.md.
        # Cross-vendor canonical sources tag md5crypt payloads in
        # several shapes (``md5crypt:$1$..``, ``5 $1$..``); the shared
        # _TARGET_ACCEPTS["juniper_junos"] set doesn't include those
        # algorithm tokens, but Junos's commit-time hasher consumes
        # any ``$1$..`` payload natively.  :func:`_is_md5crypt_tagged`
        # widens the migratable set codec-locally so cross-vendor
        # render-into-Junos doesn't drop the user when the source
        # canonical happens to use a tagged form rather than a bare
        # crypt string.  Empty ``hashed_password`` falls through to
        # the bare ``class`` line below — Junos accepts that form
        # as a console-only / no-password account.
        if (
            user.hashed_password
            and not user.hashed_password.startswith("junos:")
            and not is_migratable(user.hashed_password, "juniper_junos")
            and not _is_md5crypt_tagged(user.hashed_password)
        ):
            algorithm, _payload = classify_hash(user.hashed_password)
            out.append(
                format_review_comment(
                    user.name, algorithm, comment_syntax="hash",
                    target_label="Junos",
                )
            )
            continue
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
            hsh = user.hashed_password
            if hsh.startswith("junos:"):
                # Native Junos hash — strip the vendor tag and emit
                # verbatim.  Round-trip path: parse stores
                # ``junos:<crypt>``, render strips it back out.  No
                # migratability check needed here — by definition the
                # hash came from a Junos parser.
                out.append(
                    f"set system login user {_quote_if_needed(user.name)} "
                    f"authentication encrypted-password "
                    f"{_quote_always(hsh[len('junos:'):])}"
                )
            else:
                # Foreign-source hash whose algorithm Junos can
                # consume natively (sha512 -> $6$ / md5crypt -> $1$
                # via Junos's commit-time hasher; plaintext is
                # always emit-safe).  Strip the canonical
                # ``vendor:alg:`` prefix and emit just the payload.
                # Unmigratable hashes were already short-circuited
                # via the ``continue`` above.
                _alg, payload = classify_hash(hsh)
                out.append(
                    f"set system login user {_quote_if_needed(user.name)} "
                    f"authentication encrypted-password "
                    f"{_quote_always(payload)}"
                )

    # --- structural collapse detection (render-side auto-
    #     synthesise interface-range blocks for ≥3 interfaces
    #     sharing identical shared-attr tuples) ---
    #
    # Only applies to "simple" interfaces (not sub-interfaces,
    # not VRF-bound, not LAG members) since those have richer
    # per-interface semantics.  Shared attrs we collapse on:
    # mtu + description.  Emit `set interfaces interface-range
    # <auto-name> member <iface>` + one line per shared attr.
    # Per-interface render SUPPRESSES the shared attrs when the
    # interface is a range member.
    range_emit_by_name: dict[str, list[str]] = {}
    iface_range_membership: dict[str, str] = {}
    collapsed_iface_count = 0
    _candidates: dict[tuple, list[str]] = {}
    for iface in tree.interfaces:
        # Skip sub-interfaces (they emit under parent/unit).
        _parent, _unit = _split_subiface_name(iface.name)
        if _parent is not None and _unit is not None:
            continue
        # Skip VRF-bound interfaces (per-VRF semantics matter
        # too much to auto-collapse across them).
        if iface.vrf:
            continue
        # Skip access-vlan / switchport / trunk-configured
        # interfaces.  Collapse only ROUTED or BARE interfaces.
        if (
            iface.access_vlan is not None
            or iface.switchport_mode is not None
            or iface.trunk_allowed_vlans
        ):
            continue
        # Collapse key: (mtu, description, enabled).  We DON'T
        # include IP addresses — those are per-interface.
        key = (iface.mtu, iface.description, iface.enabled)
        # Skip all-default tuples — nothing worth collapsing.
        if key == (None, "", True):
            continue
        _candidates.setdefault(key, []).append(iface.name)
    # Promote candidate groups with ≥3 members into
    # interface-range emissions.
    _next_range_id = 1
    for key, members in sorted(_candidates.items(), key=lambda kv: (
        # Sort by member count descending so AUTO-RANGE-1 is the
        # biggest group.
        -len(kv[1]), sorted(kv[1])[0] if kv[1] else "",
    )):
        if len(members) < 3:
            continue
        range_name = f"AUTO-RANGE-{_next_range_id}"
        _next_range_id += 1
        lines: list[str] = []
        for m in members:
            lines.append(
                f"set interfaces interface-range {range_name} "
                f"member {m}"
            )
            iface_range_membership[m] = range_name
        mtu, description, enabled = key
        if description:
            lines.append(
                f"set interfaces interface-range {range_name} "
                f"description {_quote_always(description)}"
            )
        if mtu is not None:
            lines.append(
                f"set interfaces interface-range {range_name} "
                f"mtu {mtu}"
            )
        if not enabled:
            lines.append(
                f"set interfaces interface-range {range_name} "
                f"disable"
            )
        range_emit_by_name[range_name] = lines
        collapsed_iface_count += len(members)

    # Emit interface-range blocks FIRST so operators see the
    # shared config before per-interface specifics.
    for _rname, lines in range_emit_by_name.items():
        out.extend(lines)

    # --- L2 / LAG / SVI lookups (Phase 4 rank-4) ---
    #
    # Junos references VLANs by NAME (not VID) inside
    # ``family ethernet-switching vlan members``; build a
    # vid -> vlan-key lookup once.  ``vlan_key`` mirrors the
    # convention used a few lines below in the ``set vlans`` block:
    # use ``vlan.name`` when populated, fall back to ``VLAN-<id>``.
    vlan_name_by_id: dict[int, str] = {}
    for _v in tree.vlans:
        vlan_name_by_id[_v.id] = _v.name or f"VLAN-{_v.id}"

    # LAG mode lookup so we know whether to emit ``lacp active /
    # passive`` or static (no LACP).  LAG name is the canonical-side
    # vendor-native name (Cisco/Arista ``Port-Channel10``,
    # Aruba/AOS-S ``Trk1``, MikroTik ``bond1``).  Map to Junos's
    # ``ae<N>`` form via :func:`_lag_name_to_ae`.
    lag_mode_by_canonical_name = {
        lag.name: (lag.mode or "active") for lag in tree.lags
    }
    lag_ae_by_canonical_name: dict[str, str] = {}
    _used_ae_ids: set[int] = set()
    _next_ae_fallback_state = [0]  # list-of-one so closures can mutate
    for lag in tree.lags:
        ae_name, ae_id = _lag_name_to_ae(
            lag.name, _used_ae_ids, _next_ae_fallback_state[0],
        )
        if ae_id is not None:
            _used_ae_ids.add(ae_id)
        else:
            _next_ae_fallback_state[0] += 1
        lag_ae_by_canonical_name[lag.name] = ae_name

    # --- empty-interface elision predicate ------------------------
    #
    # When an interface carries zero canonical content (no L3 IPs,
    # no description, no MTU, enabled, no L2 / LAG state), the only
    # value of emitting ``set interfaces <name>`` is to declare the
    # interface so a *routing-instance* binding can reference it,
    # OR because there are sub-units (``<name>.<vid>``) that need a
    # parent stub on reparse to keep the canonical-iface list stable.
    # Cisco IOS-XE ``vrf forwarding Mgmt-vrf`` translates into
    # ``iface.vrf="Mgmt-vrf"`` on the canonical side, which triggers
    # a ``set routing-instances Mgmt-vrf interface <name>.0`` line
    # below — Junos's commit-time validator requires the interface
    # to be defined under ``[edit interfaces]`` before that
    # reference resolves (KB: "Interface must already be defined
    # under [edit interfaces]").  Without that VRF binding (and
    # without any sub-units), an empty stub is pure noise in the
    # rendered config.  Issue #9 in user_smoke_findings.md.
    iface_is_vrf_bound: dict[str, bool] = {
        i.name: bool(i.vrf) for i in tree.interfaces
    }
    # Names that show up as the parent of an ``<name>.<unit>`` sub-
    # interface — e.g. ``irb`` is the parent of ``irb.100``.
    # Junos parse creates BOTH a parent-name canonical and a unit
    # canonical for ``set interfaces <parent> unit <N> ...`` lines
    # (the parent is bodyless when no per-iface attrs land on it),
    # so a stable parse->render->parse cycle requires the parent
    # stub to be re-emitted.
    iface_has_subunits: set[str] = set()
    for i in tree.interfaces:
        if "." in i.name:
            parent_name = i.name.rsplit(".", 1)[0]
            iface_has_subunits.add(parent_name)

    # --- interfaces ---
    for iface in tree.interfaces:
        name = iface.name
        has_renderable_attr = (
            bool(iface.description)
            or (not iface.enabled)
            or bool(iface.ipv4_addresses)
            or bool(iface.ipv6_addresses)              # GAP-EVPN-3
            or iface.dhcp_client                       # sub-finding 9b
        )
        # Structural collapse: if this interface is a member of
        # an auto-synthesised range, suppress the shared-attr
        # emission (description + mtu + disable).  Per-interface
        # specifics (IP addresses) still emit.
        is_range_member = name in iface_range_membership
        emit_description = (
            bool(iface.description) and not is_range_member
        )
        emit_mtu = (iface.mtu is not None) and not is_range_member
        emit_disable = (not iface.enabled) and not is_range_member
        # GAP 4: sub-interface naming.  The parse side materialises
        # ``set interfaces <parent> unit N ...`` (N>0) as a
        # CanonicalInterface named ``<parent>.<N>``.  Render has to
        # split the compound name back into parent + unit so the
        # emitted set-lines use Junos's native grammar.
        #
        # Logical SVI names (``irb.<vid>`` / ``vlan.<vid>``) follow
        # the same Junos shorthand — ``irb.10`` IS ``irb unit 10``
        # in native Junos grammar — but ``_split_subiface_name``
        # deliberately rejects them (its ``parent`` group requires
        # a ``<media>-<fpc>/<pic>/<port>`` shape) so they used to
        # fall through to the regular-interface branch below and
        # render as ``set interfaces irb.10 unit 0 family inet
        # address ...`` — which Junos's commit-time validator
        # rejects because ``irb.10 unit 0`` expands to ``irb unit
        # 10 unit 0``.  The cross-vendor render INTO Junos for
        # any source codec that emits SVIs (OPNsense, Cisco IOS-XE
        # ``Vlan10`` -> ``irb.10`` via the rename mesh) would
        # silently produce a non-deployable config.  Issue #3 in
        # ``user_smoke_findings.md``.
        #
        # Detect the irb.N / vlan.N shape and route through the
        # sub-interface branch with parent="irb" (or "vlan") and
        # unit_num=N so the same correct ``set interfaces irb
        # unit 10 family inet address ...`` lines come out.
        parent, unit_num = _split_subiface_name(name)
        if parent is None or unit_num is None:
            m = _LOGICAL_SVI_NAME_RE.match(name)
            if m is not None:
                parent = m.group("parent")
                unit_num = int(m.group("unit"))
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
            # Sub-finding 9b: DHCP client.  Junos models the DHCP
            # client as a property of ``family inet`` (replacing the
            # ``address`` clause).  Emit the family inet dhcp form
            # only when no static IPv4 address is also configured —
            # Junos rejects ``family inet dhcp`` alongside a static
            # ``address`` line at commit time.
            if iface.dhcp_client and not iface.ipv4_addresses:
                out.append(
                    f"set interfaces {parent} unit {unit_num} "
                    f"family inet dhcp"
                )
            for addr in iface.ipv4_addresses:
                out.append(
                    f"set interfaces {parent} unit {unit_num} "
                    f"family inet address "
                    f"{addr.ip}/{addr.prefix_length}"
                )
            # GAP-EVPN-3: IPv6 addresses on sub-interfaces.
            # Junos emits scope-uniformly under family inet6 —
            # the canonical scope discriminator is informational
            # only on this codec.
            for v6 in iface.ipv6_addresses:
                out.append(
                    f"set interfaces {parent} unit {unit_num} "
                    f"family inet6 address "
                    f"{v6.ip}/{v6.prefix_length}"
                )
            if not sub_has_renderable:
                out.append(
                    f"set interfaces {parent} unit {unit_num}"
                )
            continue
        # Regular (unit-0 or non-unitised) interface.
        if emit_description:
            out.append(
                f"set interfaces {name} description "
                f"{_quote_always(iface.description)}"
            )
        if emit_disable:
            out.append(f"set interfaces {name} disable")
        if emit_mtu:
            out.append(f"set interfaces {name} mtu {iface.mtu}")
        # Sub-finding 9b: DHCP client.  Junos models the DHCP client
        # as ``family inet dhcp`` on ``unit 0``, replacing the static
        # ``address`` clause.  Emit only when no static IPv4 address
        # is configured — Junos rejects ``family inet dhcp`` alongside
        # a static ``address`` line at commit time.  Cisco IOS-XE
        # ``ip address dhcp`` and MikroTik DHCP-client interfaces
        # canonicalise to ``iface.dhcp_client=True`` and reach this
        # path on render-into-Junos cross-vendor flows.
        if iface.dhcp_client and not iface.ipv4_addresses:
            out.append(
                f"set interfaces {name} unit 0 family inet dhcp"
            )
        # IPv4 addresses — emit under unit 0 (v1's convention).
        for addr in iface.ipv4_addresses:
            out.append(
                f"set interfaces {name} unit 0 family inet "
                f"address {addr.ip}/{addr.prefix_length}"
            )
        # GAP-EVPN-3: IPv6 addresses also emit under unit 0.
        for v6 in iface.ipv6_addresses:
            out.append(
                f"set interfaces {name} unit 0 family inet6 "
                f"address {v6.ip}/{v6.prefix_length}"
            )

        # --- L2 switchport emission (Phase 4 rank-4) ---
        #
        # Junos models L2 ports as ``unit 0 family ethernet-
        # switching`` with ``interface-mode access|trunk`` and
        # ``vlan members <NAME>`` (NAME, not VID).
        # ``trunk_native_vlan`` surfaces as ``native-vlan-id <vid>``
        # at the iface level.  Emitted after IP addresses so the
        # L2 lines follow the L3 lines in deterministic order.
        emitted_l2 = False
        if iface.switchport_mode == "access":
            out.append(
                f"set interfaces {name} unit 0 family ethernet-switching "
                f"interface-mode access"
            )
            if iface.access_vlan is not None:
                vname = vlan_name_by_id.get(
                    iface.access_vlan, f"VLAN-{iface.access_vlan}",
                )
                out.append(
                    f"set interfaces {name} unit 0 family "
                    f"ethernet-switching vlan members "
                    f"{_quote_if_needed(vname)}"
                )
            emitted_l2 = True
        elif iface.switchport_mode == "trunk":
            out.append(
                f"set interfaces {name} unit 0 family ethernet-switching "
                f"interface-mode trunk"
            )
            # Detect Arista's "trunk all" form (literal `1-4094` or
            # `2-4094` — common on MLAG peer-link ports).  Without
            # this guard, render would emit one `vlan members VLAN-N`
            # line per VID, exploding to 4000+ lines per port.  Junos
            # has a clean equivalent: `vlan members all` matches the
            # operator-intent of "all VLANs, including ones not yet
            # defined".
            allowed = iface.trunk_allowed_vlans
            is_trunk_all = (
                len(allowed) >= 4000
                or set(allowed) == set(range(1, 4095))
                or set(allowed) == set(range(2, 4095))
            )
            if is_trunk_all:
                out.append(
                    f"set interfaces {name} unit 0 family "
                    f"ethernet-switching vlan members all"
                )
            else:
                for vid in allowed:
                    # Skip VIDs that have no matching CanonicalVlan —
                    # Junos rejects `vlan members VLAN-X` at commit
                    # time when VLAN-X isn't declared in `vlans`.
                    # Operators on the receiving side prefer a clean
                    # config that commits over one that lists phantom
                    # VLANs.  If the source codec carried a name, use
                    # it; otherwise fall back to the synthetic
                    # `VLAN-<id>` form (preserves the round-trip
                    # promise on same-vendor cycles).
                    vname = vlan_name_by_id.get(vid)
                    if vname is None:
                        vname = f"VLAN-{vid}"
                    out.append(
                        f"set interfaces {name} unit 0 family "
                        f"ethernet-switching vlan members "
                        f"{_quote_if_needed(vname)}"
                    )
            if iface.trunk_native_vlan is not None:
                out.append(
                    f"set interfaces {name} native-vlan-id "
                    f"{iface.trunk_native_vlan}"
                )
            emitted_l2 = True

        # --- LAG membership emission (Phase 4 rank-4) ---
        #
        # Junos puts LAG membership on the child:
        # ``set interfaces <member> ether-options 802.3ad ae<N>``.
        # Map the canonical LAG name (Cisco/Arista
        # ``Port-Channel10``, Aruba ``Trk1``, MikroTik ``bond1``)
        # to the matching ``ae<N>`` via the lookup built above.
        emitted_lag_member = False
        if iface.lag_member_of:
            ae_name = lag_ae_by_canonical_name.get(iface.lag_member_of)
            if ae_name is None:
                # The canonical tree carries a lag_member_of pointer
                # but no matching CanonicalLAG record (parser drift
                # or partial input).  Synthesise one inline so the
                # rendered config still wires the member up.
                ae_name, ae_id = _lag_name_to_ae(
                    iface.lag_member_of, _used_ae_ids,
                    _next_ae_fallback_state[0],
                )
                if ae_id is not None:
                    _used_ae_ids.add(ae_id)
                else:
                    _next_ae_fallback_state[0] += 1
                lag_ae_by_canonical_name[iface.lag_member_of] = ae_name
            out.append(
                f"set interfaces {name} ether-options 802.3ad {ae_name}"
            )
            emitted_lag_member = True

        # Empty-stub handling: the parse side creates an interface
        # entry for every ``set interfaces <name> ...`` line, even
        # when the trailing tokens land entirely in unmodelled
        # (Tier-3) grammar like ``unit 0 family ethernet-switching
        # ...``.  Or: the interface IS range-collapsed with no
        # per-interface specifics (no IP) — still need a placeholder
        # so round-trip keeps the interface in the canonical tree
        # even when the range block alone carries all its
        # attributes.
        #
        # When the canonical record is fully empty (no body, not in
        # an interface-range, no L2 / LAG): emit the bare line ONLY
        # when (a) a routing-instance binding requires it, OR (b)
        # this name is the parent of a sub-unit (``irb`` is parent
        # of ``irb.100``; reparse round-trip needs the parent
        # canonical to come back).  Otherwise skip entirely.
        # Cross-vendor renders into Junos used to leak ``set
        # interfaces irb.1`` and ``set interfaces ge-0/0/0`` stubs
        # from Cisco-source canonical trees where a Vlan or a
        # ``vrf forwarding Mgmt-vrf`` binding produced an interface
        # record with no other state.  Issue #9 in
        # tests/fixtures/real/user_smoke_findings.md.
        if (
            not has_renderable_attr
            and not is_range_member
            and not emitted_l2
            and not emitted_lag_member
        ):
            if iface_is_vrf_bound.get(name, False):
                # VRF-bound stub — keep the bare line so Junos's
                # commit-time validator finds the interface, with
                # an explanatory comment so operators don't wonder
                # why it's bodyless.
                out.append(
                    f"# set interfaces {name} -- bare stub kept; "
                    f"required by routing-instance binding below"
                )
                out.append(f"set interfaces {name}")
            elif name in iface_has_subunits:
                # Parent of one or more sub-units — round-trip
                # stability needs the bare line.
                out.append(f"set interfaces {name}")
            elif _IS_JUNOS_PHYSICAL_PORT_RE.match(name):
                # Junos-shaped physical port name (``ge-0/0/0``,
                # ``xe-1/0/24``, ``et-0/0/0``, ``mge-0/0/0``,
                # ``fxp0``, ``me0``, ``lo0``).  Junos parse creates
                # canonical entries for unmodelled (Tier-3) L2
                # grammar like the older ``unit 0 family ethernet-
                # switching port-mode trunk`` form (ksator EX4550
                # fixture, GAP 3 origin).  For round-trip stability
                # on Junos source, keep the bare line so reparse
                # restores the iface canonical.  Sub-interfaces
                # (``irb.1``, ``ge-0/0/0.100``) and non-Junos names
                # (``Vlan1``, ``Ethernet1/1``) deliberately don't
                # match — they're either logical-only or come from
                # a cross-vendor rename and the leak fix wins.
                out.append(f"set interfaces {name}")
            # else: fully empty, no reference, no children — skip.

    # --- aggregated-ether (LAG) stanzas (Phase 4 rank-4) ---
    #
    # Junos requires:
    #   * ``set chassis aggregated-devices ethernet device-count <N>``
    #     once at the chassis level — N must be at least the highest
    #     ae<id> in use; we use ``max(used_ae_ids) + 1``.
    #   * ``set interfaces ae<N> aggregated-ether-options lacp <mode>``
    #     per LAG.  Member binding lives on the child via
    #     ``ether-options 802.3ad ae<N>`` (emitted inside the iface
    #     loop above).
    if tree.lags:
        if _used_ae_ids:
            device_count = max(_used_ae_ids) + 1
        else:
            device_count = max(len(tree.lags), 1)
        out.append(
            f"set chassis aggregated-devices ethernet device-count "
            f"{device_count}"
        )
        for lag in tree.lags:
            ae_name = lag_ae_by_canonical_name.get(lag.name)
            if ae_name is None:
                # Shouldn't happen — every CanonicalLAG was assigned
                # an ae-name in the lookup pass — but guard anyway.
                continue
            mode = lag_mode_by_canonical_name.get(lag.name, "active")
            # Junos LACP modes: ``active`` | ``passive``.  Static
            # (non-LACP) bundles emit no ``lacp`` line at all.
            if mode in ("active", "passive"):
                out.append(
                    f"set interfaces {ae_name} aggregated-ether-options "
                    f"lacp {mode}"
                )

    # --- vlans + VLAN-to-VNI mappings (GAP 6) ---
    # Pre-index VXLAN VNIs by vlan_id for matched emission.
    vni_by_vlan = {v.vlan_id: v.vni for v in tree.vxlan_vnis}
    # Pre-index irb.<vid> interfaces so SVI emission can defer to
    # an explicit ``irb.<vid>`` CanonicalInterface when one is
    # already in the tree (preserves identity for round-trip on
    # fixtures that carry the irb stanzas as interfaces, e.g.
    # the Batfish ``junos2541`` EVPN-Type-5 capture).
    existing_irb_vids: set[int] = set()
    for _i in tree.interfaces:
        if _i.name.startswith("irb."):
            try:
                existing_irb_vids.add(int(_i.name[4:]))
            except ValueError:
                pass
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
        # --- SVI L3 emission (Phase 4 rank-4) ---
        #
        # When a CanonicalVlan carries IPv4 addresses AND no
        # explicit irb.<vid> CanonicalInterface exists in the tree,
        # synthesise the SVI via Junos's ``irb`` (Integrated
        # Routing and Bridging) interface plus the
        # ``set vlans <NAME> l3-interface irb.<vid>`` binding.  When
        # an explicit irb.<vid> iface IS present, the iface loop
        # already emitted its ``family inet address`` lines — only
        # emit the l3-interface binding here.
        if vlan.ipv4_addresses and vlan.id not in existing_irb_vids:
            for addr in vlan.ipv4_addresses:
                out.append(
                    f"set interfaces irb unit {vlan.id} family inet "
                    f"address {addr.ip}/{addr.prefix_length}"
                )
            out.append(
                f"set interfaces irb unit {vlan.id} vlan-id {vlan.id}"
            )
            out.append(
                f"set vlans {_quote_if_needed(vlan_key)} l3-interface "
                f"irb.{vlan.id}"
            )
        elif vlan.id in existing_irb_vids:
            # Explicit irb.<vid> iface present — just emit the
            # l3-interface binding so reparse can re-attach it.
            out.append(
                f"set vlans {_quote_if_needed(vlan_key)} l3-interface "
                f"irb.{vlan.id}"
            )

    # GAP-EVPN-2: emit ``set switch-options vtep-source-interface ...``
    # + ``set switch-options vxlan-port ...`` once per switch.  These
    # are switch-level on Junos; pull from the first CanonicalVxlan
    # record carrying a non-empty / non-default value.  Skip when no
    # VXLAN records exist (no-op for non-VXLAN configs).
    if tree.vxlan_vnis:
        src_iface = ""
        for v in tree.vxlan_vnis:
            if v.source_interface:
                src_iface = v.source_interface
                break
        udp_port = 4789
        for v in tree.vxlan_vnis:
            if v.udp_port and v.udp_port != 4789:
                udp_port = v.udp_port
                break
        if src_iface:
            out.append(
                f"set switch-options vtep-source-interface {src_iface}"
            )
        if udp_port != 4789:
            out.append(f"set switch-options vxlan-port {udp_port}")

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
        # SNMPv3 users — emit USM (auth / priv keys) lines then
        # VACM (group binding).  Inverse mappings of
        # _JUNOS_AUTH_MAP / _JUNOS_PRIV_MAP.  Empty auth / priv
        # emit nothing for that half — noAuthNoPriv leaves just
        # the VACM binding (expressible on Junos too).
        _auth_to_junos = {
            "md5": "authentication-md5",
            "sha": "authentication-sha",
            "sha224": "authentication-sha224",
            "sha256": "authentication-sha256",
            "sha384": "authentication-sha384",
            "sha512": "authentication-sha512",
        }
        _priv_to_junos = {
            "des": "privacy-des",
            "3des": "privacy-3des",
            "aes": "privacy-aes128",        # canonical "aes" → aes128
            "aes128": "privacy-aes128",
            "aes192": "privacy-aes192",
            "aes256": "privacy-aes256",
        }
        for u in tree.snmp.v3_users:
            if u.auth_protocol and u.auth_protocol in _auth_to_junos:
                auth_cmd = _auth_to_junos[u.auth_protocol]
                out.append(
                    f"set snmp v3 usm local-engine user "
                    f"{_quote_if_needed(u.name)} {auth_cmd} "
                    f"authentication-key "
                    f"{_quote_always(u.auth_passphrase)}"
                )
            if u.priv_protocol and u.priv_protocol in _priv_to_junos:
                priv_cmd = _priv_to_junos[u.priv_protocol]
                out.append(
                    f"set snmp v3 usm local-engine user "
                    f"{_quote_if_needed(u.name)} {priv_cmd} "
                    f"privacy-key "
                    f"{_quote_always(u.priv_passphrase)}"
                )
            if u.group:
                out.append(
                    f"set snmp v3 vacm security-to-group "
                    f"security-model usm security-name "
                    f"{_quote_if_needed(u.name)} group "
                    f"{_quote_if_needed(u.group)}"
                )

    # --- DHCP server pools (Cluster E.1-B) ---
    #
    # Junos has two DHCP server grammars:
    #
    #  * Modern stack-based form (used here):
    #     ``set access address-assignment pool <P> family inet
    #     network <CIDR>``
    #     ``set access address-assignment pool <P> family inet
    #     range <R> low <ip> / high <ip>``
    #     ``set access address-assignment pool <P> family inet
    #     dhcp-attributes router|name-server|maximum-lease-time
    #     |domain-name <val>``
    #     ``set system services dhcp-local-server group <G>
    #     interface <iface>``
    #     Supported on every current LTS Junos 22.x train.
    #
    #  * Legacy form: ``set system services dhcp pool <network>
    #    ...`` (deprecated on M / MX / SRX from ~2010; still works
    #    on EX 4.x trains).  Parser accepts it for fixture
    #    compatibility, render never emits it.
    #
    # Doc reference: Junos OS Network Management -- "Configuring
    # Address-Assignment Pools" / dhcp-local-server hierarchy.
    # https://www.juniper.net/documentation/us/en/software/junos/dhcp/topics/topic-map/dhcp-address-assignment-pool.html
    #
    # Pool / group naming: derive a stable, deterministic name from
    # ``CanonicalDHCPPool.interface`` when populated -- the iface
    # name minus illegal Junos identifier chars (``/`` and ``.``)
    # gives a unique-by-iface name that round-trips through parser.
    # When ``interface`` is empty, fall back to ``pool0``, ``pool1``,
    # ... by list position.  Both the address-assignment pool AND the
    # dhcp-local-server group use the same name so parse can re-link
    # them via the equal-name rule.
    #
    # ``CanonicalDHCPPool.start_ip`` / ``end_ip`` is a single range;
    # Junos supports multiple ``range <R>`` entries per pool but the
    # canonical model carries only one, so we emit exactly one
    # ``range r1 low / high`` pair.  Operators with multi-range
    # source pools see one collapsed range on cross-vendor render
    # (Cluster E DHCP-only scope; multi-range DHCP defers to Tier 3).
    if tree.dhcp_servers:
        for idx, pool in enumerate(tree.dhcp_servers):
            pool_name = _dhcp_pool_name(pool, idx)
            pool_path = (
                f"set access address-assignment pool "
                f"{_quote_if_needed(pool_name)} family inet"
            )
            if pool.network:
                out.append(f"{pool_path} network {pool.network}")
            if pool.start_ip:
                out.append(f"{pool_path} range r1 low {pool.start_ip}")
            if pool.end_ip:
                out.append(f"{pool_path} range r1 high {pool.end_ip}")
            if pool.gateway:
                out.append(
                    f"{pool_path} dhcp-attributes router {pool.gateway}"
                )
            for dns in pool.dns_servers:
                out.append(
                    f"{pool_path} dhcp-attributes name-server {dns}"
                )
            # Junos defaults to 86400s if not declared; we still emit
            # the explicit value so a same-vendor round-trip from
            # canonical (which always carries lease_time=86400 by
            # default) re-parses to the same value.  Keeps parse and
            # render symmetric without special-casing the default.
            if pool.lease_time:
                out.append(
                    f"{pool_path} dhcp-attributes maximum-lease-time "
                    f"{pool.lease_time}"
                )
            if pool.domain_name:
                out.append(
                    f"{pool_path} dhcp-attributes domain-name "
                    f"{_quote_always(pool.domain_name)}"
                )
            # dhcp-local-server group binding: only emit when the
            # canonical pool carries an explicit interface.  Emitting
            # a group with no interface is a commit-time error on
            # Junos (the group MUST bind at least one iface).
            if pool.interface:
                out.append(
                    f"set system services dhcp-local-server group "
                    f"{_quote_if_needed(pool_name)} interface "
                    f"{pool.interface}"
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_QUOTE_NEEDED_RE = re.compile(r"[\s\"';$`\\]")

# Junos physical port-name shapes.  Used by the empty-stub
# elision predicate to decide whether a content-free canonical
# iface is "really there" (Junos source with Tier-3 L2 grammar
# the parser couldn't surface) and therefore needs the bare
# placeholder for parse->render->parse stability.  Matches the
# core families from the ``port_names`` module's
# ``classify_port_name``: media+FPC/PIC/port (``ge-0/0/24``),
# router-style fxp0 / me0, and the loopback / irb base names.
# Sub-interfaces (``ge-0/0/0.100``, ``irb.1``) deliberately
# don't match — they're logical-only and an empty sub-iface in
# canonical means "no logical attributes", which is fine to drop.
_IS_JUNOS_PHYSICAL_PORT_RE = re.compile(
    r"^(?:"
    r"(?:[a-z]{2,4})-\d+/\d+/\d+"     # ge-X/Y/Z, xe-, et-, mge-, etc.
    r"|fxp\d+|me\d+|vme|lo\d+|irb"   # mgmt + loopback + irb base
    r")$"
)

# ``<parent>.<unit>`` — e.g. ``ge-0/0/0.100``.  ``parent`` must
# contain a slash (``ge-0/0/0``) to distinguish from normal names
# like ``irb.10`` where the dot is part of the base port name.
_SUBIFACE_RE = re.compile(r"^(?P<parent>[A-Za-z]+-\d+/\d+/\d+)\.(?P<unit>\d+)$")


# Logical SVI names where the trailing ``.<N>`` IS the Junos unit
# number (``irb.10`` is shorthand for ``irb unit 10``; same for
# ``vlan.<N>`` on older platforms).  The render path treats these
# the same as physical sub-interfaces — split into parent + unit
# so the emitted ``set interfaces`` lines use Junos's native
# grammar (``set interfaces irb unit 10 family inet address ...``)
# rather than the malformed double-unit form (``irb.10 unit 0
# family ...``) that the iface loop's regular branch would
# otherwise produce.  Issue #3 in user_smoke_findings.md.
_LOGICAL_SVI_NAME_RE = re.compile(
    r"^(?P<parent>irb|vlan)\.(?P<unit>\d+)$"
)


# Pattern for extracting a digit suffix from a canonical LAG name.
# ``Port-Channel10`` -> ``10``; ``Trk1`` -> ``1``; ``bond5`` -> ``5``.
# Digits anchored at the END of the name to handle shapes where the
# vendor prefix is not separated by a delimiter.
_LAG_DIGIT_SUFFIX_RE = re.compile(r"(\d+)\s*$")


def _lag_name_to_ae(
    name: str,
    used_ae_ids: set[int],
    fallback_index: int,
) -> tuple[str, int | None]:
    """Map a canonical LAG name to a Junos ``ae<N>`` interface name.

    Phase 4 rank-4 helper.  Strategy:

    * Extract the trailing digit run from *name* (e.g. ``Port-Channel10``
      -> ``10``, ``Trk1`` -> ``1``, ``bond5`` -> ``5``).  If the
      resulting numeric id is not already in *used_ae_ids*, return
      ``(f"ae{N}", N)``.
    * Otherwise, fall back to ``(f"ae{fallback_index}", None)`` —
      caller is expected to bump its fallback counter on receiving
      ``None``.  This handles edge cases where two distinct canonical
      LAG names happen to extract the same digit suffix (e.g.
      ``Port-Channel1`` colliding with ``bond1``).

    Returns:
        Tuple ``(ae_name, ae_id_or_None)``.  ``ae_id_or_None`` is the
        integer id when the digit suffix was usable; ``None`` when we
        fell back to enumeration.
    """
    if not name:
        return (f"ae{fallback_index}", None)
    m = _LAG_DIGIT_SUFFIX_RE.search(name)
    if m is None:
        return (f"ae{fallback_index}", None)
    try:
        ae_id = int(m.group(1))
    except ValueError:
        return (f"ae{fallback_index}", None)
    if ae_id in used_ae_ids:
        return (f"ae{fallback_index}", None)
    return (f"ae{ae_id}", ae_id)


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


def _is_md5crypt_tagged(hashed: str) -> bool:
    """Return True when ``hashed`` is a tagged form of md5crypt that
    Junos can consume via ``authentication encrypted-password``.

    The shared :func:`is_migratable` allowlist for Junos covers
    plaintext, the native ``junos:`` tag, and the bare ``$6$..`` /
    ``$1$..`` crypt strings (those classify as algorithm="plaintext"
    and pass through unconditionally).  It does NOT cover the
    Cisco-source canonical shapes ``md5crypt:$1$..`` and ``5 $1$..``
    where the algorithm token explicitly tags the payload.

    Junos's commit-time hasher recognises any ``$1$..`` payload
    regardless of how it was tagged on the canonical side, so the
    safe expansion is: when the algorithm is a known synonym for
    md5crypt AND the payload still starts with ``$1$``, treat it
    as locally-migratable.  Mirrors Arista's ``_ARISTA_SECRET_TYPE``
    table which maps both ``5`` and ``md5crypt`` to the same
    ``secret 5 ..`` emit form.
    """
    if not hashed:
        return False
    algorithm, payload = classify_hash(hashed)
    if algorithm not in ("md5crypt", "1", "5"):
        return False
    return payload.startswith("$1$")


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


_DHCP_NAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_]")


def _dhcp_pool_name(pool: Any, idx: int) -> str:
    """Derive a stable Junos pool / group name from a CanonicalDHCPPool.

    Cluster E.1-B helper.  Junos identifiers must match
    ``[A-Za-z][A-Za-z0-9_-]*``; interface names contain ``/`` and
    ``.`` which are illegal.  Strategy:

    * When ``pool.interface`` is populated, sanitise it
      (``ge-0/0/1.0`` -> ``ge_0_0_1_0``) and prefix with ``pool_``.
      Same iface always yields same name -- byte-identical round-trip.
    * When ``pool.interface`` is empty, fall back to ``pool<idx>``
      where ``idx`` is the pool's position in
      ``tree.dhcp_servers``.  List-position is the only stable
      handle we have without an iface.

    The same name is used for BOTH the ``address-assignment pool``
    body AND the ``dhcp-local-server group`` binding so parse can
    re-link them via equal-name on a same-vendor round-trip.
    """
    if pool.interface:
        sanitised = _DHCP_NAME_SAFE_RE.sub("_", pool.interface)
        return f"pool_{sanitised}"
    return f"pool{idx}"


def _quote_always(s: str) -> str:
    """Always-quoted variant for free-text fields (description,
    location, contact, password hash).  Junos tolerates quoted simple
    strings; operators expect quotes around free-text regardless.
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
