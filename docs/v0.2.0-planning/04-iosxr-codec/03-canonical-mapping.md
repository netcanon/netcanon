# 03 — Canonical mapping (canonical fields ↔ IOS-XR grammar)

> Per-field mapping table from `CanonicalIntent` to IOS-XR wire form.
> Used by the implementor to wire each parse rule + render emitter
> to the right canonical surface.  Also flags canonical-model
> extensions that would be needed (and explicitly rejected for v1).

## Top-level `CanonicalIntent` fields

| Canonical field | XR wire form (parse) | XR wire form (render) | Tier | Notes |
|---|---|---|---|---|
| `hostname` | `^hostname (\S+)` | `hostname <name>` | 1 | Sanitise via shared `sanitise_hostname` helper; XR's hostname parser is greedy like IOS-XE |
| `domain` | `^domain name (\S+)` | `domain name <fqdn>` | 1 | Note: NOT `ip domain name` |
| `dns_servers` | `^domain name-server (\S+)$` (multi-line; rare in seed) | `domain name-server <ip>` (one per line) | 1 | XR accepts the same dotted-decimal IPv4 and IPv6 forms IOS-XE does |
| `ntp_servers` | `^ntp server (\S+)` | `ntp server <ip>` | 1 | One per line |
| `timezone` | `^clock timezone (\S+)` | `clock timezone <tz>` | 1 | Optional offset; preserved verbatim |
| `syslog_servers` | `^logging (\d+\.\d+\.\d+\.\d+)` | `logging <ip>` | 1 | Single-IP form; XR also has `logging trap`, `logging buffered` — Tier-3 ignore |
| `interfaces` | `^interface <name>` block | `interface <name>` ... `!` | 1 | See §"Interface mapping" |
| `vlans` | (no native top-level form) | (no native render) | 1 | XR has no `vlan <N> / name X` stanza; VLAN-id appears only as `encapsulation dot1q <vid>` on subinterfaces.  Synthesise on parse from `.subif` stanzas |
| `static_routes` | `router static / address-family ipv4 unicast / ...` | `router static / address-family ipv4 unicast / ...` | 1 | See §"Static route mapping" |
| `dhcp_servers` | `dhcp ipv4 / profile <N> / pool / pool-range ...` (not in seed) | Tier-3 unsupported in v1 | 2 | XR DHCP grammar is distinctly different from IOS-XE — defer to follow-up phase |
| `snmp` | `snmp-server community <name>` / `snmp-server location` / etc. (not in seed) | Same | 2 | Same shape as IOS-XE — implement together with the cross-vendor SNMP coverage already in T4 backlog |
| `lags` | `interface Bundle-Ether<N>` + per-member `bundle id <n> mode <m>` | Same on emit | 2 | See §"LAG mapping" |
| `local_users` | `username <name> / group <g> / password|secret <type> <hash>` | Same on emit | 2 | See §"Local user mapping" |
| `radius_servers` | `radius-server host <ip> auth-port N acct-port N key <secret>` (not in seed; documented) | Same | 2 | Same shape as IOS-XE — no schema change |
| `routing_instances` | `vrf <name> / address-family ipv4 unicast / import|export route-target / ...` + `router bgp / vrf <name> / rd <rd>` | Same on emit | 2 | See §"VRF mapping" |
| `vxlan_vnis` | XR `nve <n>` (rare in SP corpus; NCS 5500 platform-specific) | Unsupported in v1 | 2 | Declare unsupported in capability matrix; revisit if a hyperscaler XR EVPN corpus surfaces |
| `evpn_type5_routes` | `l2vpn / evpn` + `bridge group ...` | Unsupported in v1 | 2 | XR EVPN is grammatically distant from IOS-XE/Arista/NX-OS — defer |
| `raw_sections` | n/a | n/a | 3 | Empty in v1 — Tier-3 stanzas are summarised in `dropped_tier3_sections` instead |
| `dropped_tier3_sections` | Populated by `detect_tier3_sections_iosxr` | (notification only) | 3 | See `02-codec-architecture.md` §"dropped_tier3_sections detection" for the header list |
| `source_vendor` | (set by parser) | "cisco_iosxr" | meta | NEW vendor_id |
| `source_format` | (set by parser) | "cli-iosxr" | meta | NEW input_format |
| `source_version` | Extracted from `!! IOS XR Configuration <version>` banner | (emit in banner) | meta | E.g. "6.6.2" |

---

## Interface mapping

`CanonicalInterface` field-by-field:

| Canonical field | XR wire form (parse) | XR wire form (render) | Notes |
|---|---|---|---|
| `name` | `interface (\S+)` head line | `interface <name>` | Vendor-native verbatim; `Bundle-Ether<N>` / `MgmtEth0/RP0/CPU0/0` / `GigabitEthernet<r>/<s>/<i>/<p>` all preserved as-is |
| `description` | `^\s+description (.+)` | `  description <text>` | Standard |
| `enabled` | True (default); False when `^\s+shutdown` | `  shutdown` if False; omit otherwise | XR has no `no shutdown` form in output |
| `interface_type` | Inferred from name prefix | (not emitted; metadata only) | Same `_TYPE_HINTS` table as IOS-XE; add `bundle-ether → ianaift:ieee8023adLag`, `mgmteth → ianaift:ethernetCsmacd`, `null → ianaift:other` |
| `mtu` | `^\s+mtu (\d+)` | `  mtu <n>` | Identical |
| `ipv4_addresses` | `^\s+ipv4 address (\S+) (\S+)` (dotted mask form) | `  ipv4 address <ip> <mask>` | **`ipv4 address`** keyword, not IOS-XE's `ip address`.  Use `_mask_to_prefix` / `_prefix_to_mask` helpers |
| `ipv6_addresses` | `^\s+ipv6 address (\S+/\d+)` (CIDR form) | `  ipv6 address <prefix>` | XR uses CIDR-with-prefix, not separate mask token |
| `switchport_mode` / `access_vlan` / `trunk_*` | No native XR equivalent (XR routers don't have classic L2 switchports) | Render as no-op | Always None on XR-parsed interfaces |
| `lag_member_of` | `^\s+bundle id (\d+) mode (\S+)` → `f"Bundle-Ether{n}"` | `  bundle id <n> mode <mode>` | Mode mapping: active/passive/on |
| `dhcp_client` | (not in seed; XR uses `^\s+ipv4 address dhcp` form) | `  ipv4 address dhcp` | Optional |
| `dhcp_client_v6` | `^\s+ipv6 address autoconfig` → `"slaac"`; `^\s+ipv6 address dhcp` → `"dhcp6"` | `  ipv6 address dhcp` / `autoconfig` | Same vocabulary as IOS-XE |
| `tunnel_type` | XR uses dedicated interface kinds (`tunnel-ip<N>` / `tunnel-te<N>`) — distinct from `interface Tunnel<N>` of IOS-XE | (emitted via interface kind; tunnel_type metadata not directly relevant on XR) | See §"Tunnel mapping" |
| `vrf` | `^\s+vrf (\S+)` (note: NOT `vrf forwarding`) | `  vrf <name>` | **Significant divergence** from IOS-XE which uses `vrf forwarding <name>` |
| `kind` | "" default; promoted to "mgmt" when interface name is `MgmtEth*` OR `vrf` field matches `_MGMT_VRF_RE` | (consumed by cross-vendor renamer) | Reuse `_is_mgmt_vrf` from IOS-XE parse |

### Subinterface synthesis

When the parser sees `interface GigabitEthernet0/0/0/1.35` with
`encapsulation dot1q 35` inside, it materialises:

- A `CanonicalInterface` with `name="GigabitEthernet0/0/0/1.35"` and
  the L3 config (IPv4 address, description, vrf) from the
  `.subif` stanza.  `access_vlan=35`.
- A `CanonicalVlan(id=35, name="")` if not already present in
  `intent.vlans`.

This matches the Junos GAP-4 approach (materialise sub-units as
distinct interfaces).  Render walks `intent.interfaces` and emits
each subinterface as its own `interface <parent>.<subif>` stanza
with `encapsulation dot1q <vid>`.

### Tunnel mapping (deferred)

XR uses distinct interface name prefixes for tunnel kinds rather
than IOS-XE's `tunnel mode <kind>` sub-directive:

- `interface tunnel-ip<N>` — GRE / IPv6-over-IPv4 tunnels
- `interface tunnel-te<N>` — MPLS-TE tunnels
- `interface tunnel-mte<N>` — multicast MPLS-TE

V1 codec parses these as kind=tunnel (PortIdentity) but does NOT
populate `tunnel_type`.  Cross-vendor tunnel translation defers
until a multi-vendor tunnel use case surfaces in real captures.

---

## VRF mapping

The most architecturally distinct surface.  See `01-grammar-survey.md`
§"Router BGP deep-dive" for full context.

### XR top-level `vrf <name>` stanza

```
vrf red
 address-family ipv4 unicast
  import route-target
   65102:2
   65102:4
  !
  export route-target
   65102:2
   65102:4
  !
 !
!
```

Maps to:

```python
CanonicalRoutingInstance(
    name="red",
    instance_type="vrf",
    route_distinguisher="",   # ← lives elsewhere (under router bgp)
    rt_imports=["65102:2", "65102:4"],
    rt_exports=["65102:2", "65102:4"],
    description="",
    l3_vni=None,
)
```

### RD from `router bgp / vrf X / rd <rd>`

Phase 2 minimal BGP harvest reads:

```
router bgp 65001
 ...
 vrf red
  rd 10.254.1.1:65102
  ...
 !
!
```

And **backfills** the `route_distinguisher` field on the matching
`CanonicalRoutingInstance`.  Without this, RD round-trip is lost on
every XR capture.

### Render — split emission

The render path emits two separate stanzas per VRF:

1. Top-level `vrf <name>` stanza with `address-family ipv4 unicast`
   + RT imports/exports.  Always emitted if the VRF has any
   canonical state.
2. RD goes into the `router bgp / vrf <name>` block.  Phase 2 ships
   a minimal-stub `router bgp <asn-of-1>` (placeholder ASN 1 if no
   BGP block was originally parsed) so RD can round-trip.

This split is **the** thing that makes XR's VRF model different
from every other vendor.  The codec implementor should test it
explicitly: parse → look at `CanonicalRoutingInstance.route_distinguisher`
→ confirm the source RD value made it through.

### Cross-vendor render

When the canonical tree comes from an IOS-XE source (with RD
populated from `vrf definition red / rd <rd>`), the XR render
emits the RD under the `router bgp` block.  Operators see the
RD survived; the migration is correct semantically.

---

## Static route mapping

### XR `router static` stanza

```
router static
 address-family ipv4 unicast
  10.0.0.0/8 GigabitEthernet0/0/0/0 192.0.2.1
  11.0.0.0/8 Null0
 !
 vrf blue
  address-family ipv4 unicast
   192.168.0.0/16 GigabitEthernet0/0/0/2 11.1.1.2
  !
 !
!
```

Each leaf line is one of:

- `<CIDR> <interface> <next-hop>` (full form)
- `<CIDR> <interface>` (egress-only — Null0 or onlink)
- `<CIDR> <next-hop>` (recursive next-hop only)

Parse:

```python
def _parse_static_leaf(line: str) -> CanonicalStaticRoute:
    """Parse one '<CIDR> [iface] [next-hop]' leaf into a route."""
    tokens = line.split()
    dest = tokens[0]  # already in CIDR
    rest = tokens[1:]
    iface = ""
    gw = ""
    for tok in rest:
        if _is_ipv4_or_ipv6(tok):
            gw = tok
        else:
            iface = tok
    return CanonicalStaticRoute(
        destination=dest,
        gateway=gw,
        interface=iface,
        metric=0,
        description="",
    )
```

### Per-VRF static routes — limitation

`CanonicalStaticRoute` carries no VRF field today.  Per-VRF static
routes parse correctly into individual routes, but the VRF
membership is **lost** — they all merge into the global-VRF
static-route list.  This matches the IOS-XE codec's
documented limitation (see `cisco_iosxe_cli/codec.py:158-184` —
`/routing-instances/instance` LossyPath, "per-VRF static routes
carry no `vrf` discriminator on `CanonicalStaticRoute` (route table
membership drops on round-trip)").

Render emits everything under the global static stanza in v1; the
gap is the same for both IOS-XE and IOS-XR, with the same
remediation path (add `CanonicalStaticRoute.vrf` field — cross-
vendor work item, out of T4 scope).

---

## LAG mapping

### Wire forms

**Bundle declaration:**
```
interface Bundle-Ether23
 description To_BORDER01
 mtu 9216
 ipv4 address 10.188.248.18 255.255.255.252
 bundle minimum-active links 2
!
```

**Member declarations** (separate interface stanzas):
```
interface GigabitEthernet0/0/0/2
 description To_BORDER01
 bundle id 23 mode active
 cdp
!
```

### Canonical population

```python
# Parse:
CanonicalLAG(
    name="Bundle-Ether23",
    members=["GigabitEthernet0/0/0/2", "GigabitEthernet0/0/0/3"],
    mode="active",
)
# Plus on each member CanonicalInterface:
iface.lag_member_of = "Bundle-Ether23"
```

`bundle minimum-active links N` is **not** modeled — Tier-3 ignore
(no canonical surface today; could be a `CanonicalLAG.min_active`
extension if cross-vendor demand surfaces).

### Cross-vendor mesh

Source IOS-XE `Port-channel23` with member `GigabitEthernet1/0/24
/ channel-group 23 mode active` migrates to XR via:

1. `classify_port_name` on IOS-XE side: `Port-channel23` →
   `PortIdentity(kind="lag", index=23)`.  Member port classified as
   physical.
2. `format_port_identity` on XR side: `kind="lag", index=23` →
   `"Bundle-Ether23"`.  Members re-keyed.
3. `intent.lags` carries the rename through render — the XR
   renderer sees the already-renamed `Bundle-Ether23` name.

No special XR mode mapping required — `active`/`passive`/`static`
already align across both vendors.

---

## Local user mapping

### XR wire form

```
username cisco
 group root-lr
 group cisco-support
 password 7 030752180500
!
```

Or with hashed secret:

```
username cisco
 group root-lr
 group cisco-support
 secret 5 $1$3mwn$QP.OpFp8iIl67DIyTuT.s/
!
```

### Canonical population

```python
CanonicalLocalUser(
    name="cisco",
    privilege_level=15,                # heuristic: root-lr → 15
    hashed_password="$1$3mwn$QP.OpFp8iIl67DIyTuT.s/",
    role="root-lr",                    # store the XR group name
)
```

### Privilege-level heuristic

XR uses named groups instead of numeric privilege levels.  Map:

| XR group | Canonical `privilege_level` | Canonical `role` |
|---|---|---|
| `root-lr` (root-level user) | 15 | "root-lr" |
| `cisco-support` (Cisco TAC group) | 15 | "cisco-support" |
| `root-system` | 15 | "root-system" |
| `netadmin` | 14 | "netadmin" |
| `sysadmin` | 14 | "sysadmin" |
| `operator` | 5 | "operator" |
| anything else | 1 | (verbatim group name) |

Multiple `group` lines join with `|` (XR allows multi-group users
— pick the highest-privilege match for `privilege_level`).

### Hash form

XR `password 7 <hash>` is reversible Cisco type-7 (same as IOS-XE).
XR `secret 5 <hash>` is type-5 MD5-crypt.  Both are preserved
verbatim through `hashed_password`.  Cross-vendor migration uses
the shared `_user_secrets.is_migratable` policy — type-5 is
generally migratable to Arista / Junos; type-7 is reversible and
flagged for re-key on cross-vendor.

### Render

```python
def _render_local_user(u: CanonicalLocalUser) -> str:
    out = [f"username {u.name}"]
    if u.role:
        # Reverse-map: if role is one of the well-known XR groups,
        # emit it.  Otherwise emit "group <role>" verbatim.
        out.append(f" group {u.role}")
    elif u.privilege_level == 15:
        out.append(" group root-lr")  # default for admins
    else:
        out.append(" group operator")
    if u.hashed_password:
        # Detect hash type via classify_hash; emit secret/password
        # with the right type marker (5 for $1$, 8 for $5$, 9 for $6$).
        ...
    out.append("!")
    return "\n".join(out)
```

---

## Cross-references to T1 (VRRP) and T2 (anycast)

### T1 — VRRP / HSRP grammar in XR

XR's VRRP differs from IOS-XE:

```
router vrrp
 interface GigabitEthernet0/0/0/0
  address-family ipv4
   vrrp 1 version 3
    address 10.0.0.254
    priority 110
    preempt
   !
  !
 !
!
```

Top-level `router vrrp` stanza wraps per-interface VRRP groups.
The canonical `CanonicalVRRPGroup` shape proposed in T1 covers the
fields needed (`group_id`, `virtual_ip`, `priority`, `preempt`).
**T4 codec consumes T1 canonical model once it lands** — no T4-side
schema change required.

### T2 — anycast in XR

XR's anycast story is split:

1. **`router vrrp` with `track interface`** — classic-VRRP-with-
   anycast-flavour; falls under T1's purview.
2. **SD-Access fabric forwarding** — `fabric forwarding mode anycast-
   gateway` on `interface BVI<N>`.  Rare in SP corpus; most XR
   SP deployments use plain VRRP for redundancy and don't run SDA.

V1 codec parses-and-ignores both; declares both unsupported on the
capability matrix.  T2's canonical model lands → T4 wires later.

---

## Canonical-model extensions evaluated and REJECTED for v1

The following schema additions would benefit XR coverage but are
**explicitly deferred** to keep T4's scope bounded:

1. **`CanonicalRoutePolicy`** — modeling the route-policy DSL.
   Rejected: Junos `policy-options` is declared unsupported under
   the same rationale (see `juniper_junos/codec.py:202-211`).  Once
   one vendor declares the surface unsupported as Tier-3, parity
   means the rest follow.  Cross-vendor route-policy translation
   is a Tier-3 / manual-review operation by design.

2. **`CanonicalPrefixSet` / `CanonicalCommunitySet`** — modeling
   set-form policy primitives.  Rejected: same as above — Tier-3
   bidirectional surface, parity with Junos / IOS-XE codecs which
   don't model these.

3. **`CanonicalStaticRoute.vrf`** — carrying per-VRF static routes
   through the canonical tree.  Rejected for v1: same gap exists in
   IOS-XE codec; addressing it is a cross-vendor canonical-model
   extension that should land independently (likely v0.3.0) and
   then both codecs pick it up.

4. **`CanonicalBgpRouter` / `CanonicalBgpNeighbor`** — modeling BGP
   configuration.  Rejected for v1: BGP is intentionally Tier-3 in
   every shipped codec (see `cisco_iosxe_cli/codec.py:218-226` for
   the explicit declaration on IOS-XE).  Adding the canonical surface
   means wiring it to every codec — too large to combine with T4.

5. **`CanonicalLAG.min_active`** — Bundle-Ether `minimum-active
   links` setting.  Rejected: no cross-vendor demand surfaced
   (Arista / IOS-XE don't expose this via canonical), and the
   default-of-1 is the common case.  Could be a follow-up if SP
   migration demand surfaces.

6. **`CanonicalInterface.iosxr_meta` / IPv4 secondary addresses /
   `bandwidth` per interface / `load-interval` — all parse-and-ignore
   in v1.  Most are cosmetic; secondary IPs are documented lossy on
   IOS-XE today (`/interfaces/interface/ipv4/secondary` not in the
   matrix).

All Tier-3 surfaces are surfaced via `dropped_tier3_sections` so
operators see what was dropped — same notification pattern as
every other codec.
