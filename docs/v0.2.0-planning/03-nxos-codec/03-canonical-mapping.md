# 03 — Canonical-model mapping

Table of canonical-tree xpaths ↔ NX-OS grammar tokens, plus the
identified schema extensions the codec needs before it can ship
round-trip fidelity.

Cross-references T1 (VRRP/HSRP canonical surface) and T2 (anycast
gateway) where NX-OS depends on those landing first.

---

## 1. Tier 1 — auto-translatable

Every xpath below is **already in the canonical schema** in
`netcanon/migration/canonical/intent.py`.  No schema additions
required for Tier 1.

| Canonical xpath | NX-OS grammar | Notes |
|---|---|---|
| `/system/hostname` | `hostname <name>` | Phase 1.  Identical to IOS-XE. |
| `/system/dns-server` | (n/a; corpus does not show DNS resolvers) | Defer. NX-OS uses `ip name-server` if present. |
| `/system/ntp-server` | `ntp server <ip>` | Defer to Phase 3 — no NTP in v1 corpus.  Same shape as IOS-XE. |
| `/interfaces/interface/name` | `interface <name>` | Phase 1. |
| `/interfaces/interface/config/description` | `  description <text>` | Phase 1. |
| `/interfaces/interface/config/enabled` | `  shutdown` / `  no shutdown` | Phase 1.  Default = enabled. |
| `/interfaces/interface/config/type` | (inferred from name) | Phase 1.  `_infer_type` from name prefix: `Ethernet*` → ethernetCsmacd, `loopback*` → softwareLoopback, `Vlan*` → l3ipvlan, `port-channel*` → ieee8023adLag, `nve*` → tunnel (or new vxlan IANA type), `mgmt0` → ethernetCsmacd. |
| `/interfaces/interface/config/mtu` | `  mtu <N>` | Phase 1.  Identical to IOS-XE. |
| `/interfaces/interface/ipv4/address/ip` | `  ip address X/N` (split on `/`) | Phase 1.  CIDR form only. |
| `/interfaces/interface/ipv4/address/prefix-length` | (the `<N>` after `/`) | Phase 1. |
| `/interfaces/interface/ipv6/address/ip` | `  ipv6 address X::Y/N` | Phase 1 (low priority — only mgmt0 in 10.x corpus uses ipv6). |
| `/interfaces/interface/ipv6/address/prefix-length` | (the `<N>`) | Phase 1. |
| `/interfaces/interface/ipv6/address/scope` | `link-local` keyword or `fe80::` prefix detection | Phase 1; defaults to global. |
| `/interfaces/interface/dhcp-client-v6` | (n/a; not in corpus) | NX-OS supports `ipv6 address autoconfig`; defer. |
| `/interfaces/interface/tunnel-type` | (n/a in v1) | NX-OS has `interface Tunnel<N>` blocks but corpus doesn't exercise them.  Defer. |
| `/interfaces/interface/vrf` | `  vrf member <name>` | Phase 1.  Empty = default VRF. |
| `/interfaces/interface/kind` (`"mgmt"` override) | `mgmt0` always; any port bound to vrf `management` | Phase 1.  Heuristic: name == "mgmt0" OR `vrf member management`. |
| `/interfaces/interface/switchport-mode` | `  switchport mode access|trunk` (with L2-default flip) | Phase 2.  Default on `Ethernet1/N` = access; `no switchport` = None. |
| `/interfaces/interface/access-vlan` | `  switchport access vlan <N>` | Phase 2. |
| `/interfaces/interface/trunk-allowed-vlans` | `  switchport trunk allowed vlan <list>` | Phase 2.  Same comma+range form as VLAN top-level. |
| `/interfaces/interface/trunk-native-vlan` | `  switchport trunk native vlan <N>` | Phase 2. |
| `/interfaces/interface/lag-member-of` | `  channel-group N mode <m>` | Phase 2.  Synthesises `port-channelN` reference. |
| `/vlans/vlan/id` | `vlan <N>` | Phase 1.  Expanded from comma+range form. |
| `/vlans/vlan/name` | `vlan N / name <text>` | Phase 1. |
| `/vlans/vlan/tagged-ports` | per-port `switchport trunk allowed vlan <list>` projection | Phase 2.  Same `project_switchport_to_vlan` transform. |
| `/vlans/vlan/untagged-ports` | per-port `switchport access vlan <N>` projection | Phase 2. |
| `/vlans/vlan/ipv4-addresses` (SVI absorb) | n/a — NX-OS keeps SVI as standalone `interface Vlan<N>` | `absorbs_svi_into_vlan = False`. |
| `/routing/static-route` | `ip route DEST/N GW` (top-level + per-VRF) | Phase 3.  Per-VRF form needs new schema field — see § 4. |

---

## 2. Tier 2 — auto-translate with review banner

| Canonical xpath | NX-OS grammar | Notes |
|---|---|---|
| `/local-users/user/name` | `username <name>` | Phase 2. |
| `/local-users/user/role` | `role <name>` | Phase 2.  NX-OS uses `role`, not `privilege`. |
| `/local-users/user/hashed-password` | `password <hash-type> <hash>` | Phase 2.  Hash-types: 5 = $5$ SHA-256 crypt (modern), 7 = reversible (legacy). |
| `/local-users/user/privilege-level` | (derived from role) | Phase 2.  Map `network-admin` → 15, `network-operator` → 1, others → 1.  Lossy. |
| `/snmp/community` | `snmp-server community <s>` (rare; legacy v2c) | Phase 2.  Most NX-OS modern captures have only v3. |
| `/snmp/location` | `snmp-server location <text>` | Phase 2 (not in corpus; verify against NX-OS docs). |
| `/snmp/contact` | `snmp-server contact <text>` | Phase 2 (same). |
| `/snmp/trap-host` | `snmp-server host <ip> traps ...` | Phase 2 (not in corpus; defer to Phase 3 if needed). |
| `/snmp/v3-user/name` | `snmp-server user <name>` | Phase 2. |
| `/snmp/v3-user/group` | `snmp-server user <name> <group>` (optional 2nd token) | Phase 2.  `network-admin` / `network-operator` group names. |
| `/snmp/v3-user/auth-protocol` | `auth md5|sha|sha224|sha256` | Phase 2. |
| `/snmp/v3-user/auth-passphrase` | hex-encoded hash after `auth ...` | Phase 2.  Preserve verbatim. |
| `/snmp/v3-user/priv-protocol` | `priv des|aes-128|aes-192|aes-256|3des` | Phase 2. |
| `/snmp/v3-user/priv-passphrase` | hex-encoded hash after `priv ...` | Phase 2. |
| `/snmp/v3-user/engine-id` | `engineID <colon-decimal>` | Phase 2.  Cross-vendor lossy (colon-decimal vs hex). |
| `/lags/lag/name` | `interface port-channel<N>` | Phase 2. |
| `/lags/lag/members` | per-port `channel-group N mode m` | Phase 2. |
| `/lags/lag/mode` | `channel-group N mode active|passive|on` | Phase 2.  `on` → `static`. |
| `/dhcp-servers/pool/*` | (n/a; NX-OS rarely runs DHCP servers — usually relay) | Defer.  If needed: `ip dhcp pool <name> / network X/N / default-router Y`. |
| `/radius-servers/server/*` | `radius-server host X.X.X.X key <s>` | Defer to Phase 3 (not in corpus). |
| `/vxlan-vnis/vni` | `vlan N / vn-segment <vni>` + `interface nve1 / member vni N` | Phase 4. |
| `/vxlan-vnis/source-interface` | `interface nve1 / source-interface loopback0` | Phase 4.  Broadcast value. |
| `/vxlan-vnis/udp-port` | (default 4789; not configured in corpus) | Phase 4.  Default. |
| `/vxlan-vnis/mcast-group` | `member vni N / mcast-group X` (corpus uses head-end) | Phase 4.  Often unset. |
| `/vxlan-vnis/flood-list` | (head-end replication; corpus uses `ingress-replication protocol bgp`) | Phase 4. |
| `/routing-instances/instance/name` | `vrf context <name>` | Phase 3. |
| `/routing-instances/instance/route-distinguisher` | `vrf context X / rd <rd>` (or `rd auto` sentinel) | Phase 3. |
| `/routing-instances/instance/rt-imports` | `vrf context X / address-family ipv4 unicast / route-target import <rt>` (or `both <rt>`) | Phase 3. |
| `/routing-instances/instance/rt-exports` | `route-target export <rt>` (or `both <rt>`) | Phase 3. |
| `/routing-instances/instance/description` | `vrf context X / description <text>` (rare; not in corpus) | Phase 3. |
| `/routing-instances/instance/l3-vni` | `vrf context X / vni <N>` | Phase 4. |
| `/evpn-type5-routes/route` | derived from `router bgp / vrf X / address-family ipv4 unicast / redistribute direct ...` | Phase 4.  Best-effort; lossy. |

---

## 3. Tier 3 — informational only

These surfaces parse-and-preserve in `raw_sections`; never auto-rendered
from canonical and never round-tripped cross-vendor.

| `raw_sections` key | NX-OS grammar | Surfaced where |
|---|---|---|
| `vdc` | `vdc <name> id N / limit-resource ...` block | round-tripped same-vendor |
| `features` | `feature <name>` lines that aren't render-derived | informational |
| `boot` | `boot nxos bootflash:...` | same-vendor round-trip |
| `line` | `line console / line vty` blocks | same-vendor round-trip |
| `rmon` | `rmon event N ...` | same-vendor round-trip |
| `copp` | `copp profile <name>` | same-vendor round-trip |
| `hardware` | `hardware access-list tcam region ... <N>` | same-vendor round-trip |
| `mac-table` | `mac address-table aging-time N` | same-vendor round-trip |
| `router bgp` | full `router bgp <asn>` block | `dropped_tier3_sections` notify |
| `router ospf` | full block | notify |
| `router eigrp` | full block | notify |
| `router isis` | full block | notify |
| `ip access-list` / `ipv6 access-list` / `mac access-list` | full blocks | notify |
| `route-map` | full block | notify |
| `class-map` / `policy-map` | full block | notify |
| `crypto` | full block | notify |
| `aaa` | full block | notify |
| `monitor session` | full block | notify (SPAN/RSPAN) |
| `feature pim` / `ip pim` | block | notify |
| `icam` | `icam monitor scale` (10.x) | same-vendor round-trip |
| `ssh-keys` | `ssh key rsa 2048` | same-vendor round-trip |
| `password-policy` | `no password strength-check` | same-vendor round-trip |

---

## 4. Canonical-model extensions REQUIRED by the codec

The codec cannot ship Phase 3 / Phase 4 without these schema
additions.  Each row lists the file:line and the proposed
change.

### 4.1 `CanonicalStaticRoute.vrf` (Phase 3 prerequisite)

**Why**: NX-OS embeds per-VRF static routes inside `vrf context X` —
the canonical model currently has no place to store the VRF the
route belongs to, so per-VRF static routes silently drop on
cross-vendor round-trip.

**File**: `netcanon/migration/canonical/intent.py`, the
`CanonicalStaticRoute` class (~line 261).

**Change**:
```python
class CanonicalStaticRoute(BaseModel):
    destination: str
    gateway: str = ""
    interface: str = ""
    metric: int = 0
    description: str = ""
    vrf: str = ""                       # NEW — empty = default VRF
```

**Knock-on effects**:
* `_walk_canonical` in `cisco_iosxe_cli/codec.py` (~line 481) gets
  one new yield for `/routing/static-route/vrf` when present.
* IOS-XE `_parse_static_routes` (which currently sees
  `ip route vrf X DEST MASK GW` but drops the VRF discriminator)
  starts populating the new field.
* IOS-XE `lossy` declaration on `/routing-instances/instance` can
  be tightened (the per-VRF static-route gap is now closed).
* MikroTik / Junos / Aruba / Arista codecs need a one-line patch
  in their respective static-route renderers to honour the field.

**Effort**: ~30 LOC across all codecs + intent.py + tests.  Worth
landing as a standalone PR alongside Phase 3 of the NX-OS work.

### 4.2 `PortIdentity.kind = "vtep"` (Phase 4 prerequisite)

**Why**: NX-OS's `nve1` is a distinct virtual interface kind
(VXLAN tunnel endpoint).  Currently classifies as `unknown` and
fails cross-vendor port-name translation.

**File**: `netcanon/migration/canonical/port_names.py`, the
`PortKind` literal type.

**Change**: Add `"vtep"` to the enum literal.  Other codecs'
`format_port_identity` returns `None` for `kind="vtep"` (no
native equivalent), which is the correct fall-through — the
orchestrator leaves the name verbatim and emits a warning.

**Effort**: ~10 LOC.

### 4.3 `CanonicalVxlan` RT auto-derivation (Phase 4 — optional)

**Why**: NX-OS emits `evpn / vni N l2 / rd auto / route-target
import|export auto` — Arista does the same.  Junos uses
`vrf-target target:<rt>` with explicit values.  The canonical
`CanonicalVxlan` has no RT field today.

**Option A**: Add `rt_imports: list[str]` and `rt_exports: list[str]`
to `CanonicalVxlan`, accepting `"auto"` as a sentinel.

**Option B**: Add `rt_auto: bool = False` flag.  When True, source
declared auto-derivation; when False, the RTs (if any) live
under `CanonicalEvpnType5Route.rt_imports/rt_exports`.

**Recommendation**: Option A — strings with `"auto"` sentinel.  Same
shape as `route_distinguisher = "auto"` already in
`CanonicalRoutingInstance`.

**Effort**: ~20 LOC schema + Arista + NX-OS codec wiring.

### 4.4 `CanonicalHSRPGroup` (T1 dependency, Phase 2 gating)

Owned by **T1** (`../01-vrrp-canonical/`).  NX-OS Phase 2 cannot
ship the HSRP slice until T1 lands.  Phase 2 minus HSRP is still
useful (SVI / VLAN / LAG / SNMPv3 / local users); HSRP can be
added in a Phase 2.5 follow-up PR after T1.

Cross-reference: see T1's `01-canonical-model.md` (when written)
for the schema.  Phase 2 of NX-OS will need the per-vendor
grammar table to claim its row:

```
| Cisco NX-OS | `interface Vlan<N> / hsrp <N> / preempt / ip <addr> / priority <N>` |
```

### 4.5 `CanonicalAnycastGateway` (T2 dependency, Phase 4 gating)

Owned by **T2** (`../02-anycast-gateway/`).  NX-OS Phase 4 needs:
* The system-level `fabric forwarding anycast-gateway-mac <mac>`
  → top-level canonical primitive.
* The per-SVI `fabric forwarding mode anycast-gateway` flag →
  per-interface canonical primitive.

If T2 lands as `CanonicalVRRPGroup(mode="anycast")` (T1 + T2
unified), NX-OS Phase 4 uses that.  If T2 lands as a separate
`CanonicalAnycastGateway`, NX-OS Phase 4 uses that.  Either way,
the Phase 4 design freezes once T2 freezes.

If T2 doesn't land by Phase 4, declare both anycast surfaces as
`unsupported` in the Phase 4 capability matrix and revisit when
T2 lands.

---

## 5. The `feature` declaration: NOT a canonical primitive

NX-OS's `feature <name>` lines are an implementation detail of the
NX-OS render path, not a cross-vendor concept.  IOS-XE has no
equivalent; Arista has no equivalent; Junos has no equivalent.

**Decision** (locked in `02-codec-architecture.md` § 5): derive on
render from what the canonical tree already implies.  No canonical
schema addition.

Implication for parse: the parser sees `feature bgp` etc. and
discards them.  If the source had a `feature` line not motivated by
any other canonical-tree surface (e.g. `feature scp-server`, which
controls a management API and has no canonical analogue), that line
is **lost** in cross-vendor round-trip.  Same-vendor round-trip
recovers it via `raw_sections["features"]`.

Capability matrix declares the gap:
```python
LossyPath(
    path="/system/raw-sections/features",
    reason=(
        "NX-OS 'feature <name>' lines that are not motivated by "
        "a canonical-tree surface (e.g. 'feature scp-server', "
        "'feature telnet') are preserved via raw_sections on "
        "same-vendor round-trip but dropped on cross-vendor "
        "render.  Operator must re-author management-API feature "
        "declarations manually on the target NX-OS device."
    ),
    severity="warn",
),
```

---

## 6. The `vdc` block: same-vendor preservation only

NX-OS's `vdc <name> id 1 / limit-resource ...` is virtual-device-context
configuration unique to NX-OS.  Preserve verbatim in
`raw_sections["vdc"]` for same-vendor round-trip; emit a hardcoded
default block when source was cross-vendor (so the rendered NX-OS
output is syntactically valid).

Capability matrix:
```python
LossyPath(
    path="/system/raw-sections/vdc",
    reason=(
        "NX-OS Virtual Device Context (VDC) configuration is an "
        "N7K-specific virtualisation primitive.  Cross-vendor "
        "source has no VDC concept; render emits a default "
        "id-1 single-VDC block.  Same-vendor round-trip is "
        "lossless via raw_sections."
    ),
    severity="warn",
),
```

---

## 7. The empty-interface preservation question

128-port chassis emit a bare `interface Ethernet1/N` line per
unused port.  Two options for canonical mapping:

* **Option A** (recommended): parse every bare interface into a
  `CanonicalInterface(name="Ethernet1/N", enabled=True)` record.
  Render walks `tree.interfaces` and re-emits.  Cross-vendor
  targets typically skip blank interfaces (no IP, no description,
  no shutdown override) so the bulk vanishes naturally.
* **Option B**: parse-discard bare interfaces; preserve the count
  in `raw_sections["chassis-ports"] = "Ethernet1/1-128"` so the
  render can re-emit on same-vendor round-trip.

**Recommendation**: Option A — preserves rename-modal UX (operator
can see all chassis ports), aligns with Arista EOS prior art, and
the cross-vendor render filter takes care of cleanup downstream.

Capability matrix: not a lossy declaration — this is a parse-time
choice that doesn't gate any xpath.

---

## 8. SNMP `localizedkey` vs `localizedV2key`

NX-OS hash format differs by OS version:
* 9.x: `0x<hex>` payloads + `localizedkey` keyword
* 10.x: bare-hex payloads + `localizedV2key` keyword (new digest
  format)

The canonical `CanonicalSNMPv3User` schema doesn't capture this
discriminator.  Three options:

* Add `CanonicalSNMPv3User.key_format: str = ""` (sentinel:
  `"v1"` / `"v2"` / `""` = vendor-default).  Schema bloat for one
  vendor.
* Always emit `localizedkey` on render (drop v2 on round-trip).
  Same-vendor 10.x → 10.x loses fidelity (the resulting config
  rejects on a 10.x device since the hex format differs).
* Add the discriminator to `CanonicalSNMPv3User` meta — store it as
  a free-form string in a hypothetical `meta` field.

**Recommendation**: declare `localizedV2key` lossy in the matrix.
NX-OS render always emits `localizedkey` with the `0x`-prefixed hex
form.  Operators rekey on the target device when migrating from
10.x.  Document this in the matrix's `lossy` row.

```python
LossyPath(
    path="/snmp/v3-user/auth-passphrase",
    reason=(
        "NX-OS 10.x introduced a new key digest format "
        "(`localizedV2key`).  v1 codec normalises to the older "
        "`localizedkey` form on render; operators migrating "
        "between OS versions or vendors must re-key SNMPv3 "
        "users on the target device."
    ),
    severity="warn",
),
```

---

## 9. Per-codec cross-reference table (Tier-1 grammar surface)

Quick reference: which xpaths the NX-OS codec shares with each
existing codec.

| xpath | NX-OS | IOS-XE | Arista | Junos | Aruba | FortiGate | MikroTik | OPNsense |
|---|---|---|---|---|---|---|---|---|
| `/system/hostname` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/interfaces/interface/name` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/interfaces/interface/ipv4/address/ip` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/interfaces/interface/ipv6/address/ip` | ✓ (mgmt only in corpus) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/interfaces/interface/vrf` | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| `/interfaces/interface/switchport-mode` | ✓ (L2 default) | ✓ (L3 default) | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ |
| `/interfaces/interface/lag-member-of` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| `/vlans/vlan/id` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/vlans/vlan/name` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| `/routing/static-route` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/routing/static-route/vrf` (NEW) | ✓ | ✓ (gap closure) | ✓ (gap closure) | ✓ (gap closure) | ✗ | ✗ | ✗ | ✗ |
| `/routing-instances/instance/*` | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| `/routing-instances/instance/l3-vni` | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| `/vxlan-vnis/*` | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| `/snmp/v3-user/*` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| `/local-users/user/*` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/lags/lag/*` | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| `/anycast-gateway/*` (T2) | ✓ | ✓ (SDA limited) | ✓ (VARP) | ✓ (virtual-gateway) | ✗ | ✗ | ✗ | ✗ |
| `/hsrp/*` (T1) | ✓ (`hsrp N`) | ✓ (`standby N`) | ✗ (uses VARP) | ✗ (uses VRRP) | ✗ | ✗ | ✗ | ✗ |
| `/vrrp/*` (T1) | ✗ (NX-OS uses HSRP) | ✓ (`vrrp N`) | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |

Reading the table:
* NX-OS adds the most overlap with **IOS-XE** (every Tier-1 xpath
  in common) — natural since both are Cisco.
* NX-OS adds **VXLAN + L3VNI** overlap with **Arista + Junos** —
  this is the high-leverage cross-vendor surface.
* NX-OS is the second vendor (alongside IOS-XE) needing the
  `/routing/static-route/vrf` schema extension — closing it in
  Phase 3 benefits IOS-XE too.

---

## 10. Cross-reference to T1 + T2 design docs

When T1 ships its canonical model:

* T1 must include a row for **NX-OS HSRP** in its per-vendor
  grammar table.  Sample shape:
  ```
  interface Vlan10
    hsrp 10
      preempt
      ip 10.10.10.3
      priority 110
  ```
* T1's `CanonicalVRRPGroup` (or `CanonicalHSRPGroup`) becomes the
  target schema NX-OS Phase 2 parses into.
* T1 must distinguish HSRP from VRRP semantically — both are
  "L3 redundancy with a virtual IP" but their hello protocols
  differ (HSRP UDP 1985 vs VRRP IP protocol 112).  Phase 2 of
  NX-OS will declare `protocol="hsrp"` (or similar) on every
  group.

When T2 ships its canonical model:

* T2 must include rows for NX-OS's **`fabric forwarding
  anycast-gateway-mac`** (system level) and **per-SVI
  `fabric forwarding mode anycast-gateway`** (per-interface
  flag).
* T2 should align with Arista's VARP (`ip address virtual`) and
  Junos's `virtual-gateway-address` — these three are the
  dominant DC fabric anycast forms.

---

## 11. Summary of canonical-schema deltas

* **PHASE 3**: `CanonicalStaticRoute.vrf: str = ""` (one-line
  schema addition; closes a current IOS-XE gap too).
* **PHASE 4**: `PortIdentity.kind` literal gains `"vtep"`
  (one-token addition).
* **PHASE 4** (optional): `CanonicalVxlan` gains `rt_imports`/
  `rt_exports`/`rt_auto` to model `evpn / vni N l2 / rd auto /
  route-target both auto`.

No new top-level collections.  All NX-OS surfaces fit the existing
shape (interfaces / vlans / vrf / vxlan / snmp / local_users /
lags / static_routes / raw_sections).  This is a credit to T1+T2's
forward-looking canonical model design (VRF / VXLAN / L3VNI all
landed before any codec exercised them).
