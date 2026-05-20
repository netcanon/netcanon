# 05 — CapabilityMatrix updates and docs/CAPABILITIES.md edits

This file lists the proposed per-codec `CapabilityMatrix` entries and
the matching `docs/CAPABILITIES.md` row edits. Both are markdown
code-block sketches — they do not modify production files from this
design folder.

The `CapabilityMatrix` model lives at
[`netcanon/models/migration.py:154`](../../../netcanon/models/migration.py).
Each codec declares its own matrix in
`netcanon/migration/codecs/<vendor>/codec.py` (Cisco IOS-XE
NETCONF: [`codec.py:191`](../../../netcanon/migration/codecs/cisco_iosxe/codec.py)
is the canonical example of the declaration shape).

---

## Canonical xpath strings (cross-codec contract)

The cross-mesh xpath classifier uses these strings. New paths
introduced by this feature:

* `/interfaces/interface/vrrp_groups` — top-level list marker
* `/interfaces/interface/vrrp_groups/group_id` — leaf
* `/interfaces/interface/vrrp_groups/mode` — leaf
* `/interfaces/interface/vrrp_groups/virtual_ips` — list-of-leaves
* `/interfaces/interface/vrrp_groups/virtual_ipv6s` — list-of-leaves
* `/interfaces/interface/vrrp_groups/virtual_mac` — leaf
* `/interfaces/interface/vrrp_groups/priority` — leaf
* `/interfaces/interface/vrrp_groups/preempt` — leaf
* `/interfaces/interface/vrrp_groups/advertisement_interval` — leaf
* `/interfaces/interface/vrrp_groups/authentication` — leaf
* `/interfaces/interface/vrrp_groups/track_interfaces` — list-of-leaves
* `/interfaces/interface/vrrp_groups/description` — leaf
* `/vrrp_groups` — top-level field marker (run-full-mesh shape match)

The cross-mesh audit's `f"/{field}"` shape match expects the
top-level marker. The granular paths support per-leaf
supported/lossy/unsupported declarations (mode-conditional).

---

## Per-codec matrix changes

### 1. cisco_iosxe_cli (`supported` for classic, `lossy` for anycast)

```python
# Sketch — additions to the _CAPS declaration in
# netcanon/migration/codecs/cisco_iosxe_cli/codec.py

# Add to .supported:
"/interfaces/interface/vrrp_groups",
"/interfaces/interface/vrrp_groups/group_id",
"/interfaces/interface/vrrp_groups/virtual_ips",
"/interfaces/interface/vrrp_groups/virtual_ipv6s",
"/interfaces/interface/vrrp_groups/priority",
"/interfaces/interface/vrrp_groups/preempt",
"/interfaces/interface/vrrp_groups/authentication",
"/interfaces/interface/vrrp_groups/description",

# Add to .lossy:
LossyPath(
    path="/interfaces/interface/vrrp_groups/track_interfaces",
    reason=(
        "IOS-XE 'track <object> decrement <D>' carries the "
        "tracked-object reference but the priority decrement "
        "value drops; canonical only carries the object name."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/vrrp_groups/advertisement_interval",
    reason=(
        "IOS-XE supports 'timers advertise msec <MS>' for "
        "sub-second VRRPv3 advertisements; canonical model "
        "stores seconds only.  Sub-second intervals collapse "
        "to the default 1s on round-trip."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/vrrp_groups/mode",
    reason=(
        "IOS-XE has no native anycast-gateway grammar.  "
        "Records with mode='anycast' or mode='carp' surface a "
        "render-time review comment and the group is not "
        "emitted; cross-vendor migration into IOS-XE drops the "
        "redundancy state."
    ),
    severity="warn",
),
```

### 2. cisco_iosxe (NETCONF stub — unsupported)

```python
# Sketch — additions to _CAPS.unsupported in
# netcanon/migration/codecs/cisco_iosxe/codec.py (line 219).

UnsupportedPath(
    path="/interfaces/interface/vrrp_groups",
    reason=(
        "Phase 0.5 stub render does not emit the "
        "openconfig-if-ip:vrrp augmentation under "
        "subinterfaces/subinterface/ipv4/addresses/address.  "
        "intent.interfaces[].vrrp_groups dropped on render — "
        "operators selecting this codec as TARGET should expect "
        "VRRP / VARP / anycast state to be absent from output XML.  "
        "Flips to supported once _render_canonical() walks "
        "vrrp_groups into the openconfig-if-ip:vrrp child."
    ),
),
UnsupportedPath(
    path="/vrrp_groups",
    reason="Top-level field marker — see /interfaces/interface/vrrp_groups.",
),
```

Also extend `unsupported_rename_categories` at line 168:

```python
unsupported_rename_categories: ClassVar[frozenset[str]] = frozenset({
    "snmpv3",
    "vrrp",   # added
})
```

### 3. arista_eos (`supported` for both classic + VARP)

```python
# Sketch — additions in arista_eos/codec.py.

# Add to .supported:
"/interfaces/interface/vrrp_groups",
"/interfaces/interface/vrrp_groups/group_id",
"/interfaces/interface/vrrp_groups/mode",       # supports both vrrp + anycast
"/interfaces/interface/vrrp_groups/virtual_ips",
"/interfaces/interface/vrrp_groups/virtual_ipv6s",
"/interfaces/interface/vrrp_groups/virtual_mac",
"/interfaces/interface/vrrp_groups/priority",
"/interfaces/interface/vrrp_groups/preempt",

# Add to .lossy:
LossyPath(
    path="/interfaces/interface/vrrp_groups/authentication",
    reason=(
        "Arista EOS deprecated VRRP authentication; classic "
        "vrrp authentication tokens parse-and-ignore.  "
        "Cross-vendor migration FROM an authenticated source "
        "surfaces a render-time review comment in EOS output."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/vrrp_groups/track_interfaces",
    reason=(
        "EOS 'vrrp N track Ethernet1 decrement 10' carries an "
        "interface reference plus a decrement value; canonical "
        "stores the interface name only.  Decrement drops on "
        "round-trip."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/vrrp_groups/description",
    reason=(
        "Pre-4.21 EOS does not support 'vrrp N description'.  "
        "Old-firmware targets emit a review comment in place "
        "of the description line."
    ),
    severity="warn",
),
```

### 4. juniper_junos (`supported` for both classic + anycast)

```python
# Sketch — additions in juniper_junos/codec.py.

# Add to .supported:
"/interfaces/interface/vrrp_groups",
"/interfaces/interface/vrrp_groups/group_id",
"/interfaces/interface/vrrp_groups/mode",
"/interfaces/interface/vrrp_groups/virtual_ips",
"/interfaces/interface/vrrp_groups/virtual_ipv6s",
"/interfaces/interface/vrrp_groups/virtual_mac",
"/interfaces/interface/vrrp_groups/priority",
"/interfaces/interface/vrrp_groups/preempt",
"/interfaces/interface/vrrp_groups/authentication",  # md5 + plain
"/interfaces/interface/vrrp_groups/track_interfaces",
"/interfaces/interface/vrrp_groups/description",

# Add to .lossy:
LossyPath(
    path="/interfaces/interface/vrrp_groups/advertisement_interval",
    reason=(
        "Junos 'fast-interval <MS>' supports sub-second VRRPv3; "
        "canonical model carries seconds only.  Sub-second "
        "intervals collapse to 1s on round-trip."
    ),
    severity="warn",
),
```

### 5. aruba_aoss (`supported` for classic vrrp, `unsupported` for anycast/carp)

```python
# Sketch — additions in aruba_aoss/codec.py.

# Add to .supported:
"/interfaces/interface/vrrp_groups",
"/interfaces/interface/vrrp_groups/group_id",
"/interfaces/interface/vrrp_groups/virtual_ips",
"/interfaces/interface/vrrp_groups/priority",
"/interfaces/interface/vrrp_groups/preempt",
"/interfaces/interface/vrrp_groups/authentication",
"/interfaces/interface/vrrp_groups/track_interfaces",

# Add to .lossy:
LossyPath(
    path="/interfaces/interface/vrrp_groups/virtual_ips",
    reason=(
        "AOS-S 'virtual-ip-address' accepts ONE address per "
        "vrid.  Cross-vendor migration FROM Cisco IOS-XE or "
        "Junos sources with multi-IP groups drops secondary "
        "virtuals with a review comment."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/vrrp_groups/virtual_ipv6s",
    reason=(
        "AOS-S 16.10 IPv6 VRRPv3 support is partial; "
        "pre-16.11 firmware drops v6 virtuals.  Codec emits "
        "v6 lines but warns about firmware compatibility."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/vrrp_groups/description",
    reason=(
        "AOS-S 'description' on vrid is 16.11+; older targets "
        "drop with review comment."
    ),
    severity="warn",
),

# Add to .unsupported:
UnsupportedPath(
    path="/interfaces/interface/vrrp_groups/mode",
    reason=(
        "AOS-S supports classic VRRP only.  Records with "
        "mode='anycast' or mode='carp' surface a review "
        "comment and the group is not emitted."
    ),
),
```

### 6. fortigate_cli (`supported` for classic vrrp)

```python
# Sketch — additions in fortigate_cli/codec.py.

# Add to .supported:
"/interfaces/interface/vrrp_groups",
"/interfaces/interface/vrrp_groups/group_id",
"/interfaces/interface/vrrp_groups/virtual_ips",
"/interfaces/interface/vrrp_groups/virtual_ipv6s",
"/interfaces/interface/vrrp_groups/priority",
"/interfaces/interface/vrrp_groups/preempt",
"/interfaces/interface/vrrp_groups/advertisement_interval",
"/interfaces/interface/vrrp_groups/authentication",
"/interfaces/interface/vrrp_groups/track_interfaces",

# Add to .lossy:
LossyPath(
    path="/interfaces/interface/vrrp_groups/description",
    reason=(
        "FortiOS does not model a per-group description string; "
        "cross-vendor migration FROM Junos / IOS-XE sources "
        "drops the description on render."
    ),
    severity="warn",
),

# Add to .unsupported:
UnsupportedPath(
    path="/interfaces/interface/vrrp_groups/mode",
    reason=(
        "FortiGate supports classic VRRP only.  Records with "
        "mode='anycast' or mode='carp' surface a review "
        "comment and the group is not emitted."
    ),
),
```

### 7. mikrotik_routeros (`supported` for classic vrrp)

```python
# Sketch — additions in mikrotik_routeros/codec.py.

# Add to .supported:
"/interfaces/interface/vrrp_groups",
"/interfaces/interface/vrrp_groups/group_id",
"/interfaces/interface/vrrp_groups/virtual_ips",
"/interfaces/interface/vrrp_groups/virtual_ipv6s",
"/interfaces/interface/vrrp_groups/priority",
"/interfaces/interface/vrrp_groups/preempt",
"/interfaces/interface/vrrp_groups/advertisement_interval",
"/interfaces/interface/vrrp_groups/authentication",

# Add to .lossy:
LossyPath(
    path="/interfaces/interface/vrrp_groups/track_interfaces",
    reason=(
        "RouterOS lacks first-class VRRP interface-tracking; "
        "on-backup script bindings are Tier-3 and not modelled "
        "in canonical state.  Tracked-interface lists drop on "
        "render with a review comment."
    ),
    severity="warn",
),

# Add to .unsupported:
UnsupportedPath(
    path="/interfaces/interface/vrrp_groups/mode",
    reason=(
        "RouterOS supports classic VRRP only.  Records with "
        "mode='anycast' or mode='carp' surface a review "
        "comment and the group is not emitted."
    ),
),
```

### 8. opnsense (`supported` for CARP + VRRP modes)

```python
# Sketch — additions in opnsense/codec.py.

# Add to .supported:
"/interfaces/interface/vrrp_groups",
"/interfaces/interface/vrrp_groups/group_id",
"/interfaces/interface/vrrp_groups/mode",            # both carp + vrrp
"/interfaces/interface/vrrp_groups/virtual_ips",
"/interfaces/interface/vrrp_groups/virtual_ipv6s",
"/interfaces/interface/vrrp_groups/priority",
"/interfaces/interface/vrrp_groups/advertisement_interval",
"/interfaces/interface/vrrp_groups/authentication",  # CARP key
"/interfaces/interface/vrrp_groups/description",

# Add to .lossy:
LossyPath(
    path="/interfaces/interface/vrrp_groups/preempt",
    reason=(
        "CARP has no preempt knob — the lowest advskew (and "
        "highest priority) always wins.  Canonical preempt "
        "field is ignored on render to OPNsense; preempt=False "
        "from a source vendor surfaces no behavioural change."
    ),
    severity="warn",
),
LossyPath(
    path="/interfaces/interface/vrrp_groups/track_interfaces",
    reason=(
        "OPNsense CARP has no first-class interface-tracking; "
        "<carp_status_change> hook scripts are Tier-3.  "
        "Cross-vendor track_interfaces lists drop on render."
    ),
    severity="warn",
),

# No unsupported entries needed — OPNsense's mode discriminator
# accepts both 'carp' and 'vrrp' natively; 'anycast' falls out
# (no native form), which is handled at render time via a review
# comment, NOT a matrix declaration (the canonical record itself
# is supported; the specific mode value isn't).  Cross-mesh
# classification flags the gap via the granular path lossy entry
# on /mode if that matters operationally.
UnsupportedPath(
    path="/interfaces/interface/vrrp_groups/virtual_mac",
    reason=(
        "OPNsense CARP derives the virtual MAC from VHID + "
        "advskew — operators cannot override.  Cross-vendor "
        "virtual_mac strings drop on render."
    ),
),
```

---

## `docs/CAPABILITIES.md` row edits

The capability tables in `docs/CAPABILITIES.md` get a new row per
codec. Below is the proposed edit set (drafted as direct
diff-style markdown; the implementation PR makes the actual edits).

### Tier 2 features list (around line 67)

```diff
 ### Tier 2 — translatable with caveats
@@
 * `routing_instances` + per-interface `vrf` (cross-vendor VRF
   primitive — same ship-before-wire pattern)
+* `vrrp_groups` — L3 redundancy primitive on every interface.
+  Supports classic VRRPv2/v3 across all bidirectional codecs;
+  anycast-gateway (Arista VARP / Junos virtual-gateway-address)
+  and CARP (OPNsense) cross-translate via the `mode`
+  discriminator with documented Lossy boundaries (see per-codec
+  tables below)
 * `apply_groups` + `group_content` (Junos-specific; preserved
   byte-for-byte through round-trip)
```

### Per-codec table edits

**cisco_iosxe_cli (around line 131):**

```diff
 #### `cisco_iosxe_cli` (Cisco IOS-XE CLI, bidirectional)

 | Path | Class | Reason summary |
 |---|---|---|
+| `/interfaces/interface/vrrp_groups/mode` | Lossy | Records with mode='anycast' or 'carp' have no IOS-XE equivalent; render emits a review comment. |
+| `/interfaces/interface/vrrp_groups/track_interfaces` | Lossy | IOS-XE 'track <object> decrement <D>' decrement value drops on round-trip. |
+| `/interfaces/interface/vrrp_groups/advertisement_interval` | Lossy | Sub-second 'timers advertise msec' intervals collapse to default 1s. |
 | `/interfaces/interface/config/type` | Lossy | ... |
```

**cisco_iosxe (NETCONF — around line 144):**

```diff
 | Path (granular) | Class |
 |---|---|
 | `/interfaces/interface/config/mtu` | Lossy ... |
+| `/interfaces/interface/vrrp_groups` | Unsupported (Phase 0.5 stub render emits only the openconfig-interfaces subtree; openconfig-if-ip:vrrp augmentation not wired) |
 | `/system/{hostname,dns-server,ntp-server}` | Unsupported |
@@
 Top-level field markers (`/hostname`, ..., `/evpn_type5_routes`)
+`/vrrp_groups`
 are also declared unsupported ...
```

**arista_eos (around line 172):**

```diff
 #### `arista_eos` (bidirectional)
@@
 | `/interfaces/interface/config/type` | Lossy | ... |
+| `/interfaces/interface/vrrp_groups/authentication` | Lossy | Arista EOS deprecated VRRP authentication; tokens parse-and-ignore; cross-vendor migration surfaces a review comment. |
+| `/interfaces/interface/vrrp_groups/track_interfaces` | Lossy | Decrement value drops on round-trip; canonical carries only the tracked-interface name. |
 | `/evpn-type5-routes/route` | Lossy | ... |
```

**aruba_aoss (around line 182):**

```diff
 #### `aruba_aoss` (bidirectional)
@@
 | `/interfaces/interface/config/type` | Lossy | ... |
+| `/interfaces/interface/vrrp_groups/virtual_ips` | Lossy | AOS-S 'virtual-ip-address' accepts ONE address per vrid; secondary virtuals drop with review comment. |
+| `/interfaces/interface/vrrp_groups/mode` | Unsupported | AOS-S supports classic VRRP only; anycast/carp records drop with review comment. |
 | `/filter/rule` | Unsupported | ... |
```

**juniper_junos (around line 190):**

```diff
 #### `juniper_junos` (bidirectional)
@@
 | `/interfaces/interface/subinterfaces/subinterface` | Lossy | ... |
+| `/interfaces/interface/vrrp_groups/advertisement_interval` | Lossy | Sub-second 'fast-interval' values collapse to default 1s. |
 | `/groups` | Lossy | ... |
```

**fortigate_cli (around line 200):**

```diff
 #### `fortigate_cli` (bidirectional)
@@
 | `/interfaces/interface/config/type` | Lossy | ... |
+| `/interfaces/interface/vrrp_groups/description` | Lossy | FortiOS does not model a per-group description string; descriptions from other vendors drop on render. |
+| `/interfaces/interface/vrrp_groups/mode` | Unsupported | FortiGate supports classic VRRP only; anycast/carp records drop with review comment. |
 | `/filter/rule` | Unsupported | ... |
```

**mikrotik_routeros (around line 210):**

```diff
 #### `mikrotik_routeros` (bidirectional)
@@
 | `/interfaces/interface/config/type` | Lossy | ... |
+| `/interfaces/interface/vrrp_groups/track_interfaces` | Lossy | RouterOS lacks first-class VRRP interface-tracking; tracked-interface lists drop on render. |
+| `/interfaces/interface/vrrp_groups/mode` | Unsupported | RouterOS supports classic VRRP only; anycast/carp records drop with review comment. |
 | `/vlans/vlan/name` | Lossy | ... |
```

**opnsense (around line 220):**

```diff
 #### `opnsense` (bidirectional)
@@
 | `/interfaces/interface/config/description` | Lossy | ... |
+| `/interfaces/interface/vrrp_groups/preempt` | Lossy | CARP has no preempt knob; preempt=False from source vendors surfaces no behavioural change on render. |
+| `/interfaces/interface/vrrp_groups/virtual_mac` | Unsupported | OPNsense CARP derives the virtual MAC from VHID + advskew — operators cannot override. |
 | `/filter/rule` | Unsupported | ... |
```

---

## Cross-mesh field-disposition matrix

The cross-mesh runner uses the top-level field marker
(`/vrrp_groups`) to drive `unsupported_in_target` flags. With the
matrix declarations above:

| Source / Target | iosxe-cli | iosxe-NC | EOS | Junos | AOS-S | FortiGate | MikroTik | OPNsense |
|---|---|---|---|---|---|---|---|---|
| **iosxe-cli** | n/a | UNS | OK | OK | OK | OK | OK | LOS (mode mismatch) |
| **iosxe-NC** | UNS | n/a | UNS | UNS | UNS | UNS | UNS | UNS |
| **EOS** | LOS (anycast→none) | UNS | n/a | OK | LOS (anycast→none) | LOS (anycast→none) | LOS (anycast→none) | LOS (anycast→none) |
| **Junos** | LOS (anycast→none) | UNS | OK | n/a | LOS (anycast→none) | LOS (anycast→none) | LOS (anycast→none) | LOS (anycast→none) |
| **AOS-S** | OK | UNS | OK | OK | n/a | OK | OK | OK |
| **FortiGate** | OK | UNS | OK | OK | OK | n/a | OK | OK |
| **MikroTik** | OK | UNS | OK | OK | OK | OK | n/a | OK |
| **OPNsense** | LOS (carp→vrrp; auth drops) | UNS | LOS (carp→vrrp) | LOS (carp→vrrp) | LOS (carp→vrrp) | LOS (carp→vrrp) | LOS (carp→vrrp) | n/a |

Legend: OK = supported, LOS = lossy, UNS = unsupported.

---

## Schema-PR matrix declaration (lands first)

Before any codec wires VRRP, the schema PR adds the canonical
field and declares EVERY codec's matrix to mark
`/interfaces/interface/vrrp_groups` as **unsupported** with a
"wire-up pending" reason. This is the ship-before-wire pattern
also used for `vxlan_vnis` and `evpn_type5_routes` (see
`intent.py` docstring at line 56).

```python
# Sketch — schema-PR matrix entry per codec:
UnsupportedPath(
    path="/interfaces/interface/vrrp_groups",
    reason=(
        "VRRP / anycast / CARP canonical surface shipped in "
        "v0.2.0 ahead of per-codec wire-up.  This codec will "
        "flip to supported once parse + render lands in a "
        "follow-up commit.  See "
        "docs/v0.2.0-planning/01-vrrp-canonical/."
    ),
),
```

Per-codec PRs then REMOVE this declaration and ADD the matching
supported/lossy entries from the lists above.
