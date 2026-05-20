# 03 — Parse / render touchpoints

For each codec this file pinpoints the **exact file:line** where new
parse-dispatch and render-emission code should land, along with
regex / token-pattern sketches and the code shape (in markdown fenced
blocks — NOT to be edited into production files from this doc).

All `file:line` references are to the worktree's current head
(commit 8afed7c). Line numbers shift when other code lands first;
the surrounding context (function name, neighbouring sentinels) is
the durable anchor.

---

## 1. cisco_iosxe_cli — easiest path; existing fixture exists

### Parse insertion

**File:** [`netcanon/migration/codecs/cisco_iosxe_cli/parse.py`](../../../netcanon/migration/codecs/cisco_iosxe_cli/parse.py)
**Insertion point — regex block:** add new `_VRRP_*_RE` constants
after the existing `_TUNNEL_MODE_RE` definition at line 102.

```python
# Sketch — would land at parse.py around line 110, contiguous with
# the other interface-body regexes.

_VRRP_IP_RE = re.compile(
    r"^\s+vrrp\s+(?P<group>\d+)\s+ip\s+(?P<ip>\S+)"
    r"(?P<secondary>\s+secondary)?\s*$",
    re.IGNORECASE,
)
_VRRP_IPV6_RE = re.compile(
    r"^\s+vrrp\s+(?P<group>\d+)\s+ipv6\s+(?P<ip>\S+)\s*$",
    re.IGNORECASE,
)
_VRRP_PRIORITY_RE = re.compile(
    r"^\s+vrrp\s+(?P<group>\d+)\s+priority\s+(?P<priority>\d+)\s*$",
    re.IGNORECASE,
)
_VRRP_PREEMPT_RE = re.compile(
    r"^\s+(?P<no>no\s+)?vrrp\s+(?P<group>\d+)\s+preempt\b.*$",
    re.IGNORECASE,
)
_VRRP_DESCRIPTION_RE = re.compile(
    r'^\s+vrrp\s+(?P<group>\d+)\s+description\s+(?P<text>.+?)\s*$',
    re.IGNORECASE,
)
_VRRP_AUTH_MD5_RE = re.compile(
    r"^\s+vrrp\s+(?P<group>\d+)\s+authentication\s+md5\s+"
    r"key-string\s+(?P<key>\S+)\s*$",
    re.IGNORECASE,
)
_VRRP_AUTH_TEXT_RE = re.compile(
    r"^\s+vrrp\s+(?P<group>\d+)\s+authentication\s+text\s+"
    r"(?P<key>\S+)\s*$",
    re.IGNORECASE,
)
_VRRP_TRACK_RE = re.compile(
    r"^\s+vrrp\s+(?P<group>\d+)\s+track\s+(?P<object>\S+)"
    r"(?:\s+decrement\s+(?P<dec>\d+))?\s*$",
    re.IGNORECASE,
)
_VRRP_TIMERS_RE = re.compile(
    r"^\s+vrrp\s+(?P<group>\d+)\s+timers\s+advertise\s+"
    r"(?P<msec>msec\s+)?(?P<value>\d+)\s*$",
    re.IGNORECASE,
)
```

**Insertion point — dispatch logic:** inside
`_parse_interfaces()` at parse.py:585. The current per-line loop
matches sub-commands until it sees `!` or a non-whitespace line
(line 620). Add a VRRP block between the `vfm = _IFACE_VRF_FORWARDING_RE`
match (line 761) and the loop tail (line 788).

```python
# Sketch — would land at parse.py around line 760, after vrf handling.
# `current` is the parse-time scratch dict (line 597); the VRRP groups
# accumulate in current["vrrp_groups"] as a dict[int, dict] keyed by
# group_id, materialised into list[CanonicalVRRPGroup] at
# _build_canonical_interface time.

vm = _VRRP_IP_RE.match(line)
if vm:
    gid = int(vm.group("group"))
    g = current.setdefault("vrrp_groups", {}).setdefault(gid, {
        "group_id": gid, "mode": "vrrp",
        "virtual_ips": [], "virtual_ipv6s": [],
        "priority": 100, "preempt": True,
        "advertisement_interval": 1,
        "virtual_mac": "", "authentication": "",
        "track_interfaces": [], "description": "",
    })
    g["virtual_ips"].append(vm.group("ip"))
    continue

vm = _VRRP_IPV6_RE.match(line)
if vm:
    gid = int(vm.group("group"))
    g = current.setdefault("vrrp_groups", {}).setdefault(gid, ...)
    g["virtual_ipv6s"].append(vm.group("ip"))
    continue

vm = _VRRP_PRIORITY_RE.match(line)
if vm:
    gid = int(vm.group("group"))
    g = current.setdefault("vrrp_groups", {}).setdefault(gid, ...)
    g["priority"] = int(vm.group("priority"))
    continue

# ... and so on for preempt / description / auth / track / timers.
```

The materialisation in `_build_canonical_interface` (parse.py:796)
extends to walk the scratch dict and emit a `list[CanonicalVRRPGroup]`
on the canonical interface.

### Render insertion

**File:** [`netcanon/migration/codecs/cisco_iosxe_cli/render.py`](../../../netcanon/migration/codecs/cisco_iosxe_cli/render.py)
**Insertion point:** inside the interface render loop at
render.py:252. After `dhcp_client` emission (line 377) and before
the elision predicate (line 380).

```python
# Sketch — would land at render.py around line 378.
# `iface` is the CanonicalInterface; `body` is the running list of
# stanza-body lines.

for group in iface.vrrp_groups:
    if group.mode != "vrrp":
        # Anycast / CARP — not native to IOS-XE.  Surface a review
        # comment and skip (matches the dhcp_client_v6 "review:"
        # pattern at line 291).
        body.append(
            f" ! review: vrrp_groups[{group.group_id}].mode="
            f"{group.mode!r} has no IOS-XE equivalent"
        )
        continue
    # Primary virtual IP — first element.
    if not group.virtual_ips:
        continue
    body.append(
        f" vrrp {group.group_id} ip {group.virtual_ips[0]}"
    )
    for vip in group.virtual_ips[1:]:
        body.append(f" vrrp {group.group_id} ip {vip} secondary")
    for vip6 in group.virtual_ipv6s:
        body.append(f" vrrp {group.group_id} ipv6 {vip6}")
    if group.priority != 100:
        body.append(
            f" vrrp {group.group_id} priority {group.priority}"
        )
    if group.preempt:
        body.append(f" vrrp {group.group_id} preempt")
    else:
        body.append(f" no vrrp {group.group_id} preempt")
    if group.description:
        body.append(
            f" vrrp {group.group_id} description {group.description}"
        )
    if group.authentication.startswith("md5:"):
        body.append(
            f" vrrp {group.group_id} authentication md5 key-string "
            f"{group.authentication[4:]}"
        )
    elif group.authentication.startswith("plain:"):
        body.append(
            f" vrrp {group.group_id} authentication text "
            f"{group.authentication[6:]}"
        )
    elif group.authentication and ":" not in group.authentication:
        body.append(
            f" ! review: vrrp authentication blob "
            f"{group.authentication!r} could not be cleanly emitted"
        )
    for tracked in group.track_interfaces:
        body.append(f" vrrp {group.group_id} track {tracked}")
    if group.advertisement_interval not in (0, 1):
        body.append(
            f" vrrp {group.group_id} timers advertise "
            f"{group.advertisement_interval}"
        )
```

---

## 2. arista_eos — classic + VARP

### Parse insertion

**File:** [`netcanon/migration/codecs/arista_eos/parse.py`](../../../netcanon/migration/codecs/arista_eos/parse.py)
**Insertion point:** inside `_apply_iface_subcommand()` (parse.py:860).
Add VRRP + VARP branches after the `no switchport` handler at line 1014
and before the `vrf` handler at line 1019.

```python
# Sketch — would land at parse.py around line 1015.

# Classic VRRP: `vrrp N ipv4 X` / `vrrp N ip X` (legacy).
m = re.match(
    r"^vrrp\s+(\d+)\s+(ipv4|ip)\s+(\S+)\s*$", line,
)
if m:
    gid = int(m.group(1))
    g = _vrrp_group_for(iface, gid, mode="vrrp")
    g.virtual_ips.append(m.group(3))
    return

m = re.match(r"^vrrp\s+(\d+)\s+ipv6\s+(\S+)\s*$", line)
if m:
    gid = int(m.group(1))
    g = _vrrp_group_for(iface, gid, mode="vrrp")
    g.virtual_ipv6s.append(m.group(2))
    return

m = re.match(r"^vrrp\s+(\d+)\s+priority\s+(\d+)\s*$", line)
if m:
    g = _vrrp_group_for(iface, int(m.group(1)), mode="vrrp")
    g.priority = int(m.group(2))
    return

m = re.match(r"^(no\s+)?vrrp\s+(\d+)\s+preempt\b", line)
if m:
    g = _vrrp_group_for(iface, int(m.group(2)), mode="vrrp")
    g.preempt = not bool(m.group(1))
    return

m = re.match(
    r"^vrrp\s+(\d+)\s+track\s+(\S+)"
    r"(?:\s+decrement\s+(\d+))?\s*$",
    line,
)
if m:
    g = _vrrp_group_for(iface, int(m.group(1)), mode="vrrp")
    g.track_interfaces.append(m.group(2))
    # decrement value (group 3) drops to Lossy
    return

m = re.match(
    r'^vrrp\s+(\d+)\s+description\s+(.+?)\s*$', line,
)
if m:
    g = _vrrp_group_for(iface, int(m.group(1)), mode="vrrp")
    g.description = m.group(2).strip('"')
    return

# VARP: `ip address virtual X/Y` / `ipv6 address virtual X/Y`.
m = re.match(r"^ip\s+address\s+virtual\s+(\S+)\s*$", line)
if m:
    addr = m.group(1)
    # The VARP IP shares a record with the global mac (cascaded
    # from top-level `ip virtual-router mac-address` at parse_intent
    # level).  Group_id = SVI VLAN id derived from iface.name when
    # parseable; falls back to 0 otherwise (anycast doesn't model
    # group_id on the wire).
    gid = _derive_anycast_group_id(iface)
    g = _vrrp_group_for(iface, gid, mode="anycast")
    ip_part, _slash, _prefix = addr.partition("/")
    g.virtual_ips.append(ip_part)
    return

m = re.match(r"^ipv6\s+address\s+virtual\s+(\S+)\s*$", line)
if m:
    addr = m.group(1)
    gid = _derive_anycast_group_id(iface)
    g = _vrrp_group_for(iface, gid, mode="anycast")
    ip_part, _slash, _prefix = addr.partition("/")
    g.virtual_ipv6s.append(ip_part)
    return
```

Top-level `ip virtual-router mac-address` (NOT inside the interface
stanza — it's a global line) must be caught in `_parse_stanzas`
at parse.py:549. After parse completes, walk `intent.interfaces`
and fan-out the captured MAC into every anycast group.

```python
# Sketch — would land at parse.py around line 549, in the
# `_parse_stanzas` top-level walker.

_GLOBAL_VARP_MAC_RE = re.compile(
    r"^ip\s+virtual-router\s+mac-address\s+(\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# After all stanzas parsed:
global_mac_match = _GLOBAL_VARP_MAC_RE.search(raw)
if global_mac_match:
    mac = global_mac_match.group(1)
    for iface in intent.interfaces:
        for group in iface.vrrp_groups:
            if group.mode == "anycast" and not group.virtual_mac:
                group.virtual_mac = mac
```

### Render insertion

**File:** [`netcanon/migration/codecs/arista_eos/render.py`](../../../netcanon/migration/codecs/arista_eos/render.py)
**Insertion point:** inside the interface render loop at
render.py:478. After the IPv4 address emit at line 549, before the
LAG channel-group emit.

```python
# Sketch — would land at render.py around line 553.

# VARP / VARP-v6 emission BEFORE classic VRRP so multi-line stanzas
# stay readable.
for group in iface.vrrp_groups:
    if group.mode == "anycast":
        for vip in group.virtual_ips:
            # Reconstruct prefix-length from the parent address.
            # In v0.2.0 we use the first ipv4_address's prefix as
            # the VARP prefix (Arista convention).
            prefix = (
                iface.ipv4_addresses[0].prefix_length
                if iface.ipv4_addresses else 32
            )
            out.append(f"   ip address virtual {vip}/{prefix}")
        for vip6 in group.virtual_ipv6s:
            prefix6 = (
                iface.ipv6_addresses[0].prefix_length
                if iface.ipv6_addresses else 128
            )
            out.append(f"   ipv6 address virtual {vip6}/{prefix6}")
        continue
    if group.mode == "vrrp":
        for vip in group.virtual_ips:
            out.append(f"   vrrp {group.group_id} ipv4 {vip}")
        for vip6 in group.virtual_ipv6s:
            out.append(f"   vrrp {group.group_id} ipv6 {vip6}")
        if group.priority != 100:
            out.append(f"   vrrp {group.group_id} priority {group.priority}")
        if group.preempt:
            out.append(f"   vrrp {group.group_id} preempt")
        else:
            out.append(f"   no vrrp {group.group_id} preempt")
        if group.description:
            out.append(
                f'   vrrp {group.group_id} description "{group.description}"'
            )
        for tracked in group.track_interfaces:
            out.append(f"   vrrp {group.group_id} track {tracked}")
```

**Global VARP MAC hoisting.** Walk `tree.interfaces` for the first
non-empty `virtual_mac` on any anycast group; emit a single
`ip virtual-router mac-address X` line in the global section.
Insertion point: render.py around line 670 (post-LAG, pre-Vxlan
stanza emission).

```python
# Sketch — top-level Arista section emission.

global_varp_mac = next(
    (g.virtual_mac for i in tree.interfaces for g in i.vrrp_groups
     if g.mode == "anycast" and g.virtual_mac),
    "",
)
if global_varp_mac:
    out.append(f"ip virtual-router mac-address {global_varp_mac}")
```

---

## 3. juniper_junos — both classic and anycast

### Parse insertion

**File:** [`netcanon/migration/codecs/juniper_junos/parse.py`](../../../netcanon/migration/codecs/juniper_junos/parse.py)
**Insertion point — IRB anycast + virtual-gateway-v4-mac:** inside
`_apply_interfaces()` (parse.py:1099). Add new branches after the
existing IRB IPv4 address handler at line 1380.

```python
# Sketch — would land at parse.py around line 1400, inside
# `_apply_interfaces`.  The function already handles `set
# interfaces irb unit <vid> family inet address <ip>/<prefix>` —
# we extend the same branch to look for trailing tokens
# `virtual-gateway-address X` and pick up sibling
# `virtual-gateway-v4-mac M` set-lines for the same unit.

# IRB anycast: `set interfaces irb unit <vid> family inet
# address <ip>/<prefix> virtual-gateway-address <vip>`
if (
    name == "irb"
    and irb_state is not None
    and len(tokens) >= 9
    and tokens[3] == "family"
    and tokens[4] == "inet"
    and tokens[5] == "address"
    and tokens[7] == "virtual-gateway-address"
):
    vip = tokens[8]
    entry = irb_state.setdefault(unit_num, {"ipv4": []})
    grp = entry.setdefault("vrrp_anycast", {
        "group_id": unit_num, "mode": "anycast",
        "virtual_ips": [], "virtual_ipv6s": [],
        "virtual_mac": "",
    })
    grp["virtual_ips"].append(vip)
    return

# IRB anycast v6 — `family inet6 address X virtual-gateway-address Y`
if (
    name == "irb"
    and irb_state is not None
    and len(tokens) >= 9
    and tokens[3] == "family"
    and tokens[4] == "inet6"
    and tokens[5] == "address"
    and tokens[7] == "virtual-gateway-address"
):
    vip = tokens[8]
    entry = irb_state.setdefault(unit_num, {"ipv4": []})
    grp = entry.setdefault("vrrp_anycast", {
        "group_id": unit_num, "mode": "anycast",
        "virtual_ips": [], "virtual_ipv6s": [],
        "virtual_mac": "",
    })
    grp["virtual_ipv6s"].append(vip)
    return

# `set interfaces irb unit <vid> virtual-gateway-v4-mac <mac>`
if (
    name == "irb"
    and irb_state is not None
    and len(tokens) >= 4
    and tokens[2] in ("virtual-gateway-v4-mac", "virtual-gateway-v6-mac")
):
    entry = irb_state.setdefault(unit_num, {"ipv4": []})
    grp = entry.setdefault("vrrp_anycast", {...})
    grp["virtual_mac"] = tokens[3]
    return
```

For classic `vrrp-group N virtual-address Y`, extend the unit
walk at parse.py:1262 (the `family inet address` handler) to detect
the `vrrp-group` continuation:

```python
# Sketch — extension to the existing `family inet address` branch
# at parse.py:1262.  Tokens after the address can carry
# `vrrp-group N <sub>` continuations.

if (
    len(tokens) >= 9
    and tokens[3] == "family"
    and tokens[4] == "inet"
    and tokens[5] == "address"
    and tokens[7] == "vrrp-group"
):
    gid = int(tokens[8])
    # Materialise scratch group on target_state.
    groups = target_state.setdefault("vrrp_groups", {})
    g = groups.setdefault(gid, {
        "group_id": gid, "mode": "vrrp",
        "virtual_ips": [], "virtual_ipv6s": [],
        "priority": 100, "preempt": True,
        "_addr_anchor": tokens[6],  # which address this binds to
        "virtual_mac": "", "authentication": "",
        "track_interfaces": [], "description": "",
        "advertisement_interval": 1,
    })
    if len(tokens) >= 11 and tokens[9] == "virtual-address":
        g["virtual_ips"].append(tokens[10])
    elif len(tokens) >= 11 and tokens[9] == "priority":
        g["priority"] = int(tokens[10])
    elif len(tokens) >= 10 and tokens[9] == "preempt":
        g["preempt"] = True
    elif len(tokens) >= 10 and tokens[9] == "no-preempt":
        g["preempt"] = False
    elif len(tokens) >= 11 and tokens[9] == "authentication-type":
        # Merge with -key on a second pass: store "type only" first,
        # then either combine with -key value or surface as-is.
        existing = g.get("authentication", "")
        g["authentication"] = f"{tokens[10]}:{existing.split(':', 1)[-1] if ':' in existing else ''}"
    elif len(tokens) >= 11 and tokens[9] == "authentication-key":
        existing = g.get("authentication", "")
        scheme = existing.split(":", 1)[0] if ":" in existing else "plain"
        g["authentication"] = f"{scheme}:{tokens[10].strip('\"')}"
    elif (
        len(tokens) >= 13
        and tokens[9] == "track"
        and tokens[10] == "interface"
    ):
        g["track_interfaces"].append(tokens[11])
    return
```

### Render insertion

**File:** [`netcanon/migration/codecs/juniper_junos/render.py`](../../../netcanon/migration/codecs/juniper_junos/render.py)

**For sub-interface anycast on IRB:** insert at render.py:444 after
the `family inet address` emit.

```python
# Sketch — would land at render.py around line 445.

for addr in iface.ipv4_addresses:
    # Track which anycast group binds to this address.
    anycast_vips: list[str] = []
    for g in iface.vrrp_groups:
        if g.mode == "anycast":
            anycast_vips.extend(g.virtual_ips)
    if anycast_vips:
        vip = anycast_vips[0]  # one virtual-gateway-address per addr
        out.append(
            f"set interfaces {parent} unit {unit_num} "
            f"family inet address {addr.ip}/{addr.prefix_length} "
            f"virtual-gateway-address {vip}"
        )
    else:
        out.append(
            f"set interfaces {parent} unit {unit_num} "
            f"family inet address {addr.ip}/{addr.prefix_length}"
        )
    # Classic vrrp-group emission immediately follows.
    for g in iface.vrrp_groups:
        if g.mode != "vrrp":
            continue
        # Bind to this address (Junos requires it).
        for vip in g.virtual_ips:
            out.append(
                f"set interfaces {parent} unit {unit_num} "
                f"family inet address {addr.ip}/{addr.prefix_length} "
                f"vrrp-group {g.group_id} virtual-address {vip}"
            )
        if g.priority != 100:
            out.append(
                f"set interfaces {parent} unit {unit_num} "
                f"family inet address {addr.ip}/{addr.prefix_length} "
                f"vrrp-group {g.group_id} priority {g.priority}"
            )
        if g.preempt:
            out.append(
                f"set interfaces {parent} unit {unit_num} "
                f"family inet address {addr.ip}/{addr.prefix_length} "
                f"vrrp-group {g.group_id} preempt"
            )
        # ... auth, track-interface, description ...

# Virtual-gateway-v4-mac is per-unit (not per-address).
mac = next((g.virtual_mac for g in iface.vrrp_groups
            if g.mode == "anycast" and g.virtual_mac), "")
if mac:
    out.append(
        f"set interfaces {parent} unit {unit_num} "
        f"virtual-gateway-v4-mac {mac}"
    )
```

---

## 4. aruba_aoss — VLAN-stanza nested

### Parse insertion

**File:** [`netcanon/migration/codecs/aruba_aoss/parse.py`](../../../netcanon/migration/codecs/aruba_aoss/parse.py)
**Insertion point:** inside `_parse_vlan_stanza()` (parse.py:424).
The function currently walks until `exit` (line 442). VRRP grammar
uses NESTED `exit` markers (one for `ip vrrp vrid N`, one for the
parent vlan). Add a nested walker.

```python
# Sketch — would land at parse.py around line 500 inside the vlan
# stanza walker.

_VRRP_VRID_HEADER_RE = re.compile(
    r"^ip\s+vrrp\s+vrid\s+(\d+)\s*$", re.IGNORECASE,
)

# Inside _parse_vlan_stanza's while loop, AFTER the ip-address
# handler (line 494):
vrid_m = _VRRP_VRID_HEADER_RE.match(stripped)
if vrid_m:
    # Start a nested block.
    gid = int(vrid_m.group(1))
    group, i = _parse_vrrp_group_stanza(lines, i + 1, gid)
    # Bind to the canonical interface synthesised from this VLAN
    # via the SVI absorption logic.  Stash on the VLAN object's
    # _vrrp_scratch list; aruba_aoss/_svi_absorption.py applies it
    # to the matching CanonicalInterface during materialisation.
    vlan_vrrp_scratch.setdefault(vlan.id, []).append(group)
    continue


def _parse_vrrp_group_stanza(
    lines: list[str], start: int, gid: int,
) -> tuple[CanonicalVRRPGroup, int]:
    """Walk the body of `ip vrrp vrid N` until the inner `exit`."""
    group = CanonicalVRRPGroup(group_id=gid, mode="vrrp")
    i = start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped == "exit":
            return group, i + 1
        if not stripped:
            i += 1
            continue
        m = re.match(r"^virtual-ip-address\s+(\S+)\s*$", stripped)
        if m:
            group.virtual_ips.append(m.group(1))
        elif re.match(r"^priority\s+(\d+)\s*$", stripped):
            group.priority = int(stripped.split()[1])
        elif stripped == "preempt-mode":
            group.preempt = True
        elif stripped == "no preempt-mode":
            group.preempt = False
        elif stripped == "enable":
            pass  # implicit
        elif m := re.match(
            r"^authentication\s+(plain-text-key|md5)\s+(\S+)$",
            stripped,
        ):
            scheme = "plain" if m.group(1) == "plain-text-key" else "md5"
            group.authentication = f"{scheme}:{m.group(2)}"
        elif m := re.match(r"^track-id\s+(\d+)\s*$", stripped):
            # Top-level `track <id> interface <iface>` lookup
            # happens in the post-pass.
            group.track_interfaces.append(f"_track_id_{m.group(1)}")
        elif m := re.match(r'^description\s+"?(.+?)"?\s*$', stripped):
            group.description = m.group(1)
        i += 1
    return group, i
```

A second-pass walker resolves `_track_id_N` placeholders by reading
top-level `track <id> interface <iface>` lines from the raw input.

### Render insertion

**File:** [`netcanon/migration/codecs/aruba_aoss/render.py`](../../../netcanon/migration/codecs/aruba_aoss/render.py)
**Insertion point:** inside `render_intent()` at render.py:578
(the `lines.append(f"vlan {vlan.id}")` loop). After IP address
emission, emit the nested `ip vrrp vrid` block.

```python
# Sketch — would land at render.py around line 620, after SVI IP
# emission inside the vlan stanza render.

# Top-level `router vrrp` enabler (must precede any vlan stanza).
# Walk tree.interfaces for any group with mode="vrrp"; emit once.
has_any_vrrp = any(
    g.mode == "vrrp"
    for i in tree.interfaces
    for g in i.vrrp_groups
)
if has_any_vrrp:
    # Emit before the first vlan stanza — easiest hook is the
    # globals section at render.py:545 or so.
    lines.append("router vrrp")

# Inside the vlan stanza loop:
svi_iface = vlan_ifaces_by_name.get(f"Vlan{vlan.id}")
if svi_iface is not None:
    for group in svi_iface.vrrp_groups:
        if group.mode != "vrrp":
            # AOS-S has no anycast/CARP — surface review comment.
            lines.append(
                f"   ; review: vrrp_groups[{group.group_id}].mode="
                f"{group.mode!r} has no AOS-S equivalent"
            )
            continue
        lines.append(f"   ip vrrp vrid {group.group_id}")
        if group.virtual_ips:
            # AOS-S accepts at most one virtual-ip-address.
            lines.append(
                f"      virtual-ip-address {group.virtual_ips[0]}"
            )
            for extra in group.virtual_ips[1:]:
                lines.append(
                    f"      ; review: AOS-S supports only one "
                    f"virtual-ip-address per vrid; secondary "
                    f"{extra} dropped"
                )
        if group.priority != 100:
            lines.append(f"      priority {group.priority}")
        if group.preempt:
            lines.append("      preempt-mode")
        else:
            lines.append("      no preempt-mode")
        # Auth, description, etc.
        lines.append("      enable")
        lines.append("      exit")
```

---

## 5. fortigate_cli — nested `config vrrp` inside `config system interface`

### Parse insertion

**File:** [`netcanon/migration/codecs/fortigate_cli/parse.py`](../../../netcanon/migration/codecs/fortigate_cli/parse.py)
**Insertion point:** inside `_apply_system_interface()` at
parse.py:301. The function already iterates edits (line 304); each
edit can have sub-blocks (via `edit.sub_blocks`). Add a sub-block
handler for `config vrrp`.

```python
# Sketch — would land at parse.py around line 425, inside the
# per-edit body of _apply_system_interface.

# Walk sub-blocks for `config vrrp` (sibling of `config ip-range`
# already handled in DHCP applier).
for sub in edit.sub_blocks:
    if sub.config_path != "vrrp":
        continue
    for vrrp_edit in sub.edits:
        try:
            gid = int(vrrp_edit.edit_id)
        except ValueError:
            continue
        vrip = vrrp_edit.settings.get("vrip")
        if not vrip:
            continue
        group = CanonicalVRRPGroup(
            group_id=gid,
            mode="vrrp",
            virtual_ips=[vrip[0]],
            priority=int(vrrp_edit.settings.get("priority", ["100"])[0]),
            preempt=(
                vrrp_edit.settings.get("preempt", ["disable"])[0].lower()
                == "enable"
            ),
        )
        vrip6 = vrrp_edit.settings.get("vrip6")
        if vrip6:
            group.virtual_ipv6s.append(vrip6[0])
        adv = vrrp_edit.settings.get("adv-interval")
        if adv:
            try:
                group.advertisement_interval = int(adv[0])
            except ValueError:
                pass
        auth_token = vrrp_edit.settings.get("authentication")
        if auth_token:
            group.authentication = f"plain:{auth_token[0]}"
        vrdst = vrrp_edit.settings.get("vrdst")
        if vrdst:
            group.track_interfaces.append(vrdst[0])
        iface.vrrp_groups.append(group)
```

### Render insertion

**File:** [`netcanon/migration/codecs/fortigate_cli/render.py`](../../../netcanon/migration/codecs/fortigate_cli/render.py)
Render emits `config system interface / edit ... / config vrrp /
edit N ... / next / end` inside the interface body. Insert AFTER
the interface settings (IP, mtu, status) but BEFORE the `next`
keyword.

```python
# Sketch — would land at render.py inside the per-interface emit,
# after `set ip X Y` and before `next`.

if iface.vrrp_groups:
    out.append("        config vrrp")
    for group in iface.vrrp_groups:
        if group.mode != "vrrp":
            out.append(
                f"        # review: vrrp_groups[{group.group_id}].mode="
                f"{group.mode!r} has no FortiOS equivalent"
            )
            continue
        out.append(f"            edit {group.group_id}")
        if group.virtual_ips:
            out.append(f'                set vrip {group.virtual_ips[0]}')
        if group.virtual_ipv6s:
            out.append(f'                set vrip6 {group.virtual_ipv6s[0]}')
            out.append(f'                set version 3')
        if group.priority != 100:
            out.append(f'                set priority {group.priority}')
        out.append(
            f'                set preempt '
            f'{"enable" if group.preempt else "disable"}'
        )
        if group.advertisement_interval != 1:
            out.append(
                f'                set adv-interval '
                f'{group.advertisement_interval}'
            )
        if group.authentication.startswith("plain:"):
            out.append(
                f'                set authentication '
                f'"{group.authentication[6:]}"'
            )
        if group.track_interfaces:
            out.append(
                f'                set vrdst {group.track_interfaces[0]}'
            )
        out.append("                set status enable")
        out.append("            next")
    out.append("        end")
```

---

## 6. mikrotik_routeros — top-level `/interface vrrp` section

### Parse insertion

**File:** [`netcanon/migration/codecs/mikrotik_routeros/parse.py`](../../../netcanon/migration/codecs/mikrotik_routeros/parse.py)
**Insertion point:** in `parse_intent()` (parse.py:53). Add new
`elif section == "/interface vrrp":` branch after the existing
`/interface bonding` dispatch at line 121.

Then add a corresponding handler that builds a SCRATCH dict keyed
by VRRP pseudo-interface name (since the IP comes from a different
section). After both sections parse, materialise.

```python
# Sketch — would land at parse.py around line 124, then a new
# handler function after _parse_interface_bonding.

# Inside parse_intent's section dispatch:
elif section == "/interface vrrp":
    _parse_interface_vrrp(lines, vrrp_scratch, iface_by_name)

# ...

def _parse_interface_vrrp(
    lines: list[str],
    vrrp_scratch: dict[str, dict[str, Any]],
    iface_by_name: dict[str, CanonicalInterface],
) -> None:
    """Parse /interface vrrp section.

    Pseudo-interface names (`name=vrrp1`) are stashed for the
    post-pass that walks /ip address lines and binds the virtual
    IP back to the parent interface.
    """
    for line in lines:
        if not line.startswith("add "):
            continue
        kv = _parse_kv(line[4:])
        vrrp_name = kv.get("name", "")
        parent = kv.get("interface", "")
        if not parent:
            continue
        vrid = int(kv.get("vrid", "1"))
        scratch = vrrp_scratch.setdefault(vrrp_name, {
            "parent": parent,
            "group_id": vrid,
            "priority": int(kv.get("priority", "100")),
            "preempt": (
                kv.get("preemption-mode", "yes").lower() in
                ("yes", "true")
            ),
            "advertisement_interval": int(
                kv.get("interval", "1").rstrip("s")
            ),
            "v3_protocol": kv.get("v3-protocol", "ipv4"),
            "authentication": _build_routeros_auth(kv),
            "virtual_ips": [],
            "virtual_ipv6s": [],
        })

# After /ip address parsing, in parse_intent:
for ip_line in deferred_ip_address_lines:
    bind_iface = ip_line["interface"]
    if bind_iface in vrrp_scratch:
        scratch = vrrp_scratch[bind_iface]
        if scratch["v3_protocol"] == "ipv6":
            scratch["virtual_ipv6s"].append(ip_line["address_only"])
        else:
            scratch["virtual_ips"].append(ip_line["address_only"])

# Materialise into iface_by_name:
for scratch in vrrp_scratch.values():
    parent_iface = iface_by_name.get(scratch["parent"])
    if parent_iface is None:
        continue
    parent_iface.vrrp_groups.append(CanonicalVRRPGroup(
        group_id=scratch["group_id"],
        mode="vrrp",
        virtual_ips=scratch["virtual_ips"],
        virtual_ipv6s=scratch["virtual_ipv6s"],
        priority=scratch["priority"],
        preempt=scratch["preempt"],
        advertisement_interval=scratch["advertisement_interval"],
        authentication=scratch["authentication"],
    ))
```

### Render insertion

**File:** [`netcanon/migration/codecs/mikrotik_routeros/render.py`](../../../netcanon/migration/codecs/mikrotik_routeros/render.py)

Render emits TWO sections — `/interface vrrp` for the pseudo-iface
and an `/ip address` line for the VIP. Insertion point: a new
top-level emission block in `render_intent()` at render.py:93,
ideally before the `/ip address` section emission.

```python
# Sketch — would land at render.py, top-level VRRP emit block.

vrrp_lines: list[str] = []
vrrp_ip_lines: list[str] = []
synth_idx = 1
for iface in tree.interfaces:
    for group in iface.vrrp_groups:
        if group.mode != "vrrp":
            vrrp_lines.append(
                f"# review: vrrp_groups[{group.group_id}].mode="
                f"{group.mode!r} has no RouterOS equivalent"
            )
            continue
        pseudo_name = f"vrrp{synth_idx}"
        synth_idx += 1
        parts = [
            "add",
            f"interface={_quote_if_needed(iface.name)}",
            f"name={pseudo_name}",
            f"vrid={group.group_id}",
        ]
        if group.priority != 100:
            parts.append(f"priority={group.priority}")
        if not group.preempt:
            parts.append("preemption-mode=no")
        if group.advertisement_interval != 1:
            parts.append(f"interval={group.advertisement_interval}s")
        if group.virtual_ipv6s:
            parts.append("v3-protocol=ipv6")
        vrrp_lines.append(" ".join(parts))
        # IP address binding.
        for vip in group.virtual_ips:
            # Prefix from parent iface address.
            prefix = (
                iface.ipv4_addresses[0].prefix_length
                if iface.ipv4_addresses else 32
            )
            vrrp_ip_lines.append(
                f"add address={vip}/{prefix} interface={pseudo_name}"
            )
        for vip6 in group.virtual_ipv6s:
            vrrp_ip_lines.append(
                f"add address={vip6}/128 interface={pseudo_name}"
            )

if vrrp_lines:
    out.append("/interface vrrp")
    out.extend(vrrp_lines)
if vrrp_ip_lines:
    # Append to the existing /ip address (or /ipv6 address) emit block.
    pass
```

---

## 7. opnsense — `<virtualip>` walker

### Parse insertion

**File:** [`netcanon/migration/codecs/opnsense/parse.py`](../../../netcanon/migration/codecs/opnsense/parse.py)
**Insertion point:** in `parse_intent()` at parse.py:132. Add a
new section after the existing `<interfaces>` block at line 306
and before the `<vlans>` block at line 314.

```python
# Sketch — would land at parse.py around line 313, between
# <interfaces> and <vlans> blocks.

# ----- <virtualip>/<vip> block — CARP / VRRP -----
vip_parent = root.find("virtualip")
if vip_parent is not None:
    iface_by_canonical_name = {
        i.name: i for i in intent.interfaces
    }
    for vip_el in vip_parent.findall("vip"):
        mode_el = vip_el.find("mode")
        if mode_el is None:
            continue
        mode = (mode_el.text or "").strip().lower()
        if mode not in ("carp", "vrrp"):
            # other modes (alias, proxyarp, ipalias) are Tier-3
            continue
        vhid_el = vip_el.find("vhid")
        if vhid_el is None or not (vhid_el.text or "").strip():
            continue
        try:
            vhid = int(vhid_el.text.strip())
        except ValueError:
            continue
        iface_logical = (vip_el.findtext("interface") or "").strip()
        subnet = (vip_el.findtext("subnet") or "").strip()
        bits = (vip_el.findtext("subnet_bits") or "32").strip()
        advskew = int((vip_el.findtext("advskew") or "0").strip() or "0")
        advbase = int((vip_el.findtext("advbase") or "1").strip() or "1")
        password = (vip_el.findtext("password") or "").strip()
        descr = (vip_el.findtext("descr") or "").strip()

        # Resolve interface logical name to canonical name via
        # the OPNsense interface alias map.
        canonical_iface_name = _resolve_opnsense_iface(
            iface_logical, root,
        )
        target_iface = iface_by_canonical_name.get(canonical_iface_name)
        if target_iface is None:
            continue

        group = CanonicalVRRPGroup(
            group_id=vhid,
            mode=mode,
            virtual_ips=[subnet] if "." in subnet else [],
            virtual_ipv6s=[subnet] if ":" in subnet else [],
            priority=255 - advskew,
            advertisement_interval=advbase,
            authentication=(
                f"carp-key:{password}" if password and mode == "carp" else ""
            ),
            description=descr,
        )
        target_iface.vrrp_groups.append(group)
```

### Render insertion

**File:** [`netcanon/migration/codecs/opnsense/render.py`](../../../netcanon/migration/codecs/opnsense/render.py)
Render builds an `<opnsense>/<virtualip>/<vip>` subtree from the
canonical groups. Insertion point: alongside the `<interfaces>`
emit (look for the `interfaces_el = ET.SubElement(root,
"interfaces")` line in render.py — typically near line 200).

```python
# Sketch — would land in opnsense/render.py.

vip_root = ET.SubElement(root, "virtualip")
vip_root.set("version", "1.0.1")
for iface in tree.interfaces:
    for group in iface.vrrp_groups:
        if group.mode not in ("carp", "vrrp"):
            # Anycast doesn't map to OPNsense.
            continue
        vip_el = ET.SubElement(vip_root, "vip")
        ET.SubElement(vip_el, "mode").text = group.mode
        ET.SubElement(vip_el, "vhid").text = str(group.group_id)
        ET.SubElement(vip_el, "interface").text = (
            _opnsense_logical_name_for(iface.name)
        )
        if group.virtual_ips:
            ET.SubElement(vip_el, "subnet").text = group.virtual_ips[0]
            # Prefix from parent iface address.
            prefix = (
                iface.ipv4_addresses[0].prefix_length
                if iface.ipv4_addresses else 32
            )
            ET.SubElement(vip_el, "subnet_bits").text = str(prefix)
        ET.SubElement(vip_el, "advskew").text = str(255 - group.priority)
        ET.SubElement(vip_el, "advbase").text = str(
            group.advertisement_interval
        )
        if group.authentication.startswith("carp-key:"):
            ET.SubElement(vip_el, "password").text = group.authentication[9:]
        elif group.mode == "carp":
            # CARP requires password.  Surface as a review marker.
            ET.SubElement(vip_el, "password").text = "REVIEW-SET-CARP-PASSWORD"
        if group.description:
            ET.SubElement(vip_el, "descr").text = group.description
```

---

## 8. cisco_iosxe (NETCONF stub) — matrix change only

**File:** [`netcanon/migration/codecs/cisco_iosxe/codec.py`](../../../netcanon/migration/codecs/cisco_iosxe/codec.py)
**Insertion point:** add new `UnsupportedPath` entry to the
`_CAPS.unsupported` list at line 219, between the existing
`/snmp/v3-user` entry (line 294) and the `/vxlan-vnis/vni` entry
(line 306).

```python
# Sketch — add inside the _CAPS unsupported list:
UnsupportedPath(
    path="/interfaces/interface/vrrp_groups",
    reason=(
        "Phase 0.5 stub render does not emit the "
        "openconfig-if-ip:vrrp augmentation.  intent.interfaces[]."
        "vrrp_groups dropped on render — operators selecting this "
        "codec as TARGET should expect VRRP / VARP state to be "
        "absent from output XML.  Flips to supported once "
        "_render_canonical() walks vrrp_groups into the "
        "openconfig-if-ip:vrrp child of openconfig-if-ip:address."
    ),
),
UnsupportedPath(
    path="/vrrp_groups",
    reason="Top-level field marker — see /interfaces/interface/vrrp_groups.",
),
```

Also add the `unsupported_rename_categories` entry at line 168
(currently `{"snmpv3"}`) to include `"vrrp"` for UI pane-compat
banner consistency:

```python
unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset({
    "snmpv3",
    "vrrp",
})
```

---

## Cross-codec shared utilities (proposed)

A new helper module
`netcanon/migration/canonical/vrrp_helpers.py` would centralise:

* `_derive_anycast_group_id(iface) -> int` — VLAN-id from `Vlan<N>`
  / `irb.<N>` interface name; 0 fallback.
* `_synthesize_pseudo_iface_name(idx, mode) -> str` — for RouterOS.
* `_resolve_opnsense_iface(logical, root) -> str` — alias map for
  the OPNsense interface name lookup.

This module is OPTIONAL — codecs can carry their own
implementations if cross-vendor logic stays minimal. Defer the
decision to implementation time.

---

## Order of merging across codecs

For each codec, parse and render PRs MUST land in the SAME commit
(round-trip invariant: `parse(render(tree)) == tree`). The schema
PR lands first (with all codecs declaring `/interfaces/interface/vrrp_groups`
as `unsupported`); per-codec wire-up flips that to `supported` (or
keeps `lossy`/`unsupported` per the matrix in
[`05-capabilities-matrix-updates.md`](05-capabilities-matrix-updates.md)).
