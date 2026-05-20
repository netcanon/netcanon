# 01 — NX-OS grammar survey

Comprehensive inventory of the `show running-config` grammar surfaces
the codec must handle, based on direct inspection of the batfish/lab-
validation corpus.  All grammar samples below were extracted from
real captures fetched into `/tmp/nxos-corpus/` via curl (Apache-2.0,
not modified in the repo).

For each top-level stanza, the survey documents:
* the sub-grammar (which lines may appear inside the block)
* a comparison to the closest IOS-XE equivalent
* whether the canonical model already supports the surface, needs
  extension, or is out of scope

---

## 1. Corpus inventory

Files fetched (line counts after Apache-2.0 download):

| File | Lines | OS version | Grammar coverage |
|---|---|---|---|
| `nxos_hsrp_nxos1.txt` | 337 | 9.2(3) | HSRP + VLAN/SVI + port-channel + LACP + iBGP + loopback |
| `nxos_evpn_l3vni_NX1.txt` | 349 | 9.2(3) | EVPN L3VNI + nve1 VTEP + vrf-context + anycast-gateway-mac + l2vpn evpn neighbor |
| `nxos_evpn_l2vni_NX1.txt` | 355 | 9.2(3) | EVPN L2VNI + nve1 multi-VNI + vlan/vn-segment + evpn vni l2 block |
| `nxos_static_route_D1.txt` | 302 | 9.2(3) | Bare-bones: hostname + static route + 2 routed ports |
| `nxos_ebgp_loop_d1.txt` | 310 | 9.2(3) | eBGP + multiple loopbacks + network statements |
| `nxos_bgp_redist_d1.txt` | 323 | 9.2(3) | BGP redistribution |
| `nxos_eigrp_nxos1.txt` | 366 | 9.2(3) | EIGRP with per-interface `ip router eigrp N` + multi-AS |
| `nxos_redist_d4_ebgp.txt` | 307 | 9.2(3) | redistribution flavours across multiple ASes |
| `nxos_n9kv_r1.txt` | 191 | 10.3(9) | Newer OS — `feature netconf` / `feature grpc` / `feature nxapi` + AES-128 SNMPv3 |

Total: 2,840 lines of real NX-OS config across two OS versions.

---

## 2. Universal preamble (every config)

Every NX-OS file starts with:

```
!Command: show running-config
!Running configuration last done at: <timestamp>
!Time: <timestamp>

version <N.N(N)> Bios:version[ <bios-ver>]
hostname <name>
vdc <name> id 1
  limit-resource vlan minimum 16 maximum 4094
  limit-resource vrf minimum 2 maximum 4096
  limit-resource port-channel minimum 0 maximum 511
  limit-resource u4route-mem minimum 248 maximum 248
  limit-resource u6route-mem minimum 96 maximum 96
  limit-resource m4route-mem minimum 58 maximum 58
  limit-resource m6route-mem minimum 8 maximum 8
```

| Line | Codec action | IOS-XE delta |
|---|---|---|
| `!Command: show running-config` | **Strong probe marker (95)**.  Unique to NX-OS in the Cisco family. | IOS-XE emits `Building configuration...` instead. |
| `!Running configuration last done at: ...` | Weak probe marker; parse-discard. | IOS-XE has `! Last configuration change at`. |
| `version 9.2(3) Bios:version` | Captured as `intent.source_version`. | IOS-XE has `version 17.9`. |
| `hostname <name>` | Standard `intent.hostname` parse. | Identical. |
| `vdc <name> id 1` + `limit-resource ...` | Preserve full block in `intent.raw_sections["vdc"]`.  NX-OS-specific; no canonical model. | IOS-XE has no equivalent. |

**`vdc` is critical to render correctly**: it's a wrapper around the
rest of the config on N7K hardware (and emitted as a single id-1
container on N9K).  The codec must preserve the original `limit-resource`
values verbatim — operators occasionally tune these and a render that
elides them changes the resource budget on the device.

---

## 3. The `feature` declaration block

```
feature bgp
feature interface-vlan
feature hsrp
feature lacp
feature lldp
feature nv overlay
feature vn-segment-vlan-based
feature fabric forwarding
feature netconf
feature grpc
feature nxapi
feature telnet
feature scp-server
```

| Feature | Subsystem unlocked | Required when canonical tree contains |
|---|---|---|
| `feature bgp` | BGP routing | `raw_sections["router bgp"]` populated |
| `feature ospf` | OSPF | `raw_sections["router ospf"]` populated |
| `feature eigrp` | EIGRP | `raw_sections["router eigrp"]` populated |
| `feature interface-vlan` | SVI (`interface Vlan<N>`) | any interface with `kind="svi"` |
| `feature hsrp` | HSRP groups | any `CanonicalHSRPGroup` |
| `feature lacp` | LACP (port-channels) | any `CanonicalLAG` |
| `feature nv overlay` | VXLAN VTEP (`interface nve1`) | any `CanonicalVxlan` |
| `feature vn-segment-vlan-based` | VLAN-to-VNI mapping | any `CanonicalVxlan` (paired with `nv overlay`) |
| `feature fabric forwarding` | Anycast-gateway DAG | `fabric forwarding anycast-gateway-mac` line OR per-SVI `fabric forwarding mode anycast-gateway` |
| `feature lldp` | LLDP | parse-discard (no canonical LLDP yet) |
| `feature netconf` / `feature nxapi` / `feature grpc` / `feature telnet` / `feature scp-server` | Management API enables | parse-discard |

**IOS-XE delta**: IOS-XE has no equivalent gate — every subsystem is
implicitly available; `router bgp 65000` just works.  NX-OS rejects
`router bgp` until `feature bgp` is on.  The render path MUST emit
the full `feature` set before any dependent stanza or the device
rejects the commit at install time.

---

## 4. Interfaces — physical, SVI, LAG, loopback, mgmt, nve1

### 4.1 Physical Ethernet (`interface Ethernet1/N`)

```
interface Ethernet1/1
  description TO->NX-2
  no switchport            ← required for routed port (default is L2)
  ip address 10.1.12.1/30  ← CIDR form, NOT dotted mask
  no shutdown
```

L2 access port:

```
interface Ethernet1/3
  shutdown
  switchport access vlan 10
```

L2 trunk:

```
interface Ethernet1/1
  switchport mode trunk
  switchport trunk allowed vlan 10,2000
  channel-group 1 mode active
```

| Field | NX-OS | IOS-XE |
|---|---|---|
| Port name | `Ethernet1/1` (no speed prefix) | `GigabitEthernet1/0/1` (speed prefix encoded) |
| L2/L3 default | **L2 switchport** | **L3 routed** |
| Enable L3 | `no switchport` | `no switchport` only on L3 switches; routers default to L3 |
| IP address | `ip address X.X.X.X/N` (CIDR) | `ip address X.X.X.X Y.Y.Y.Y` (dotted mask) |
| Shutdown | `shutdown` / `no shutdown` | identical |
| LAG bind | `channel-group N mode active|passive|on` | identical |
| Trunk allowed | `switchport trunk allowed vlan 10,2000` (no `add` form) | `switchport trunk allowed vlan add ...` accepted |
| VRF | `vrf member <name>` | `vrf forwarding <name>` |

The L2/L3 default flip is the single biggest behavioural pitfall.
The parser must treat the **absence** of `no switchport` as "this
is a switchport".  When a routed port has no `switchport mode`
declaration explicitly, NX-OS defaults to access-vlan-1.  The
codec should encode this convention in `_parse_interfaces`.

### 4.2 SVI (`interface Vlan<N>`)

```
interface Vlan10
  no shutdown
  ip address 10.10.10.1/24
  hsrp 10
    preempt
    ip 10.10.10.3
```

EVPN L3VNI variant:

```
interface Vlan777
  no shutdown
  mtu 9216
  vrf member TENANT-777
  ip forward
```

| Field | Notes |
|---|---|
| `ip forward` | Bare flag enabling L3 forwarding for an SVI in an L3VNI fabric.  Distinct from `ip address X/N` which is the IRB scenario.  L3VNI SVIs typically have `ip forward` but no IP address. |
| `hsrp N` | Sub-stanza requires `feature hsrp`.  T1 canonical surface. |
| `vrf member <name>` | Binds SVI to VRF. |
| `mtu <N>` | Identical to IOS-XE. |

### 4.3 LAG (`interface port-channel<N>`)

```
interface port-channel1
  switchport mode trunk
  switchport trunk allowed vlan 10,2000
```

Members declared on the physical port via `channel-group N mode M`.
Identical pattern to IOS-XE + Arista.  No `lacp` config below the
`channel-group` line in any sample.

### 4.4 Mgmt port (`interface mgmt0`)

```
interface mgmt0
  vrf member management
  ip address 10.150.0.146/16
```

Always named `mgmt0` (no `interface mgmt1`).  Always bound to the
`management` VRF.  The codec should classify this port as
`kind="mgmt"` (mirroring the IOS-XE Mgmt-vrf heuristic).

### 4.5 Loopbacks (`interface loopback<N>`)

```
interface loopback0
  description BGP_PEERING_VTEP
  ip address 1.1.1.1/32
```

Identical shape to IOS-XE except:
* lowercase `loopback` prefix (IOS-XE: `Loopback`)
* CIDR form for IP

### 4.6 VTEP (`interface nve1`)

The single most NX-OS-specific construct in the corpus.

```
interface nve1
  no shutdown
  host-reachability protocol bgp
  source-interface loopback0
  member vni 100777 associate-vrf       ← L3VNI
```

Or multi-VNI L2 variant:

```
interface nve1
  no shutdown
  host-reachability protocol bgp
  source-interface loopback0
  member vni 5010
    suppress-arp
    ingress-replication protocol bgp
  member vni 5020
    suppress-arp
    ingress-replication protocol bgp
```

| Field | Canonical mapping | Notes |
|---|---|---|
| `source-interface loopback0` | `CanonicalVxlan.source_interface` | Same value broadcast to every `CanonicalVxlan` record for the switch (per canonical-model docstring convention). |
| `host-reachability protocol bgp` | parse-discard (not modelled) | NX-OS supports only `bgp` and the legacy `flood-and-learn` (no protocol declared); v1 codec assumes BGP-EVPN.  Render-side: always emit `host-reachability protocol bgp`. |
| `member vni <N>` | `CanonicalVxlan.vni` (L2 binding) | The VLAN ID side of the binding comes from `vlan <N> / vn-segment <vni>`; codec joins the two on `vni`. |
| `member vni <N> associate-vrf` | `CanonicalRoutingInstance.l3_vni` (L3 binding) | No L2VNI record for this — L3VNI is per-VRF, not per-VLAN. |
| `suppress-arp` | parse-discard | Sub-flag; v1 scope. |
| `ingress-replication protocol bgp` | parse-discard | Implied head-end replication; v1 scope. |

**Note**: NX-OS only ever uses `nve1` — there is no `nve2` or
`nve3`.  This means the codec can hard-code the name (mirroring how
`mgmt0` is hard-coded).

### 4.7 The empty-port phenomenon

Every N9K/N7K config in the corpus has 100+ bare
`interface Ethernet1/N` lines for unconfigured physical ports.
For `nxos_hsrp_nxos1.txt` this is **128 empty interfaces**.
The HSRP fixture has 4 configured ports (`Ethernet1/1` through
`Ethernet1/4`) and 124 empty ones.

See README.md Q3 for the recommended handling.

---

## 5. VLAN top-level

NX-OS supports three syntactic forms:

```
vlan 1
vlan 1,10,2000           ← comma-separated list
vlan 10-20               ← range form
vlan 10
  name PROD-WEB
  vn-segment 5010        ← VLAN-to-VNI binding for EVPN
```

The codec must:
* Parse comma + range forms into N separate `CanonicalVlan`
  records.
* Re-coalesce contiguous IDs into the range form on render
  (or emit one-per-line — both are syntactically valid; the
  range form is what `show running-config` emits).
* Recognise the `vn-segment <vni>` sub-line and link to
  `CanonicalVxlan`.

The arista_eos codec already has the comma + range coalescing
helper.  Lift it into a shared helper in
`netcanon/migration/canonical/vlan_range_utils.py` (new module),
or just duplicate — both are acceptable.

---

## 6. VRF context

```
vrf context management

vrf context TENANT-777
  vni 100777
  rd auto
  address-family ipv4 unicast
    route-target both auto
    route-target both auto evpn
```

| Sub-line | Canonical mapping |
|---|---|
| `vni <N>` | `CanonicalRoutingInstance.l3_vni` |
| `rd auto` | parse-discard (no canonical for "auto") OR encode as `route_distinguisher = "auto"` to round-trip the keyword.  The latter is preferred. |
| `rd <asn>:<nn>` | `route_distinguisher` |
| `address-family ipv4 unicast` (opening line) | parse-discard (gate marker) |
| `route-target import|export|both <rt>` | `rt_imports` / `rt_exports` |
| `route-target both <rt> evpn` | Same `rt_imports` + `rt_exports`; the `evpn` suffix means "advertise in l2vpn evpn AF too" — augment with a flag if needed, otherwise parse-discard. |

IOS-XE delta:
* IOS-XE uses `vrf definition <name>` (different keyword).
* IOS-XE's `address-family ipv4 / route-target import X / exit-address-family`
  has explicit close markers; NX-OS relies on indentation only.
* IOS-XE has no `vni` sub-line — L3VNI is declared elsewhere
  (typically inside a `bridge-domain` on Catalyst 9k).

`mgmt` is always present as `vrf context management` (no
sub-config beyond optional `ip route` lines).

---

## 7. Static routes

```
ip route 192.168.123.2/32 10.12.11.2
ip route 2.2.2.2/32 10.1.12.2
```

Per-VRF form (inside `vrf context`):

```
vrf context management
  ip route 0.0.0.0/0 10.0.0.2
  ipv6 route 0::/0 2001:db8::1
```

Top-level form is unconditional default-VRF.  Per-VRF form is
indented under the `vrf context` block.

| Field | NX-OS | IOS-XE |
|---|---|---|
| Top-level form | `ip route DEST/N GW` | `ip route DEST MASK GW` |
| Per-VRF form | indented under `vrf context X` | `ip route vrf X DEST MASK GW` (flat) |
| Default | `0.0.0.0/0` | `0.0.0.0 0.0.0.0` |
| Gateway-of-last-resort | none (use default) | `ip default-gateway X` (L2-switch only) |

`CanonicalStaticRoute` already has the right shape.  The per-VRF
form needs a new `vrf` field on `CanonicalStaticRoute` to round-trip
cleanly — currently the IOS-XE codec drops the VRF discriminator
(declared `lossy` in the IOS-XE matrix).  **Recommendation**: add
`vrf: str = ""` to `CanonicalStaticRoute` as part of Phase 3.  This
unblocks IOS-XE too.

IPv6 `ipv6 route DEST/N GW` is identical shape.  `CanonicalStaticRoute`
already accepts IPv6 CIDR strings.

---

## 8. SNMP

Cisco NX-OS only emits SNMPv3 in the modern corpus (no v1/v2c community
strings except via opt-in legacy config).

```
snmp-server user admin auth md5 0x40e2f8daf334a9b5cc9dec71f39993eb \
  priv 0x40e2f8daf334a9b5cc9dec71f39993eb localizedkey \
  engineID 128:0:0:9:3:12:226:241:132:47:0
```

10.3(9) variant with AES-128:

```
snmp-server user admin network-admin auth md5 3772B6814E2F5118AC2A4E7168119A482CAF \
  priv aes-128 480BFF9262537174D84867393908B07C2FB5 localizedV2key
```

The `0x` hex-prefixed form (9.x) and bare-hex form (10.x) both
appear.  The codec must accept either.  `engineID` is colon-separated
decimal; `CanonicalSNMPv3User.engine_id` is documented as hex but
"opaque string" is the actual contract — the codec can preserve
verbatim.

`network-admin` between `<name>` and `auth` is the SNMPv3 **group**
(maps to `CanonicalSNMPv3User.group`).  When absent (9.2 default),
the group is the implicit `network-operator`.

| Token | Canonical |
|---|---|
| `user <name>` | `CanonicalSNMPv3User.name` |
| `<group>` (optional, before `auth`) | `CanonicalSNMPv3User.group` |
| `auth md5\|sha\|sha224\|sha256` | `CanonicalSNMPv3User.auth_protocol` |
| `0x<hex>` / `<hex>` / `<plaintext>` | `CanonicalSNMPv3User.auth_passphrase` (preserve verbatim) |
| `priv des\|aes-128\|aes-192\|aes-256\|3des` | `CanonicalSNMPv3User.priv_protocol` |
| `<hex>` after `priv ...` | `CanonicalSNMPv3User.priv_passphrase` |
| `localizedkey` / `localizedV2key` | Discriminator — store as meta on a vendor-extension field, OR collapse into "always emit `localizedkey` on render" (lossy if source used v2key). |
| `engineID <colon-decimal>` | `CanonicalSNMPv3User.engine_id` (preserve verbatim) |

`localizedkey` vs `localizedV2key` is the only loss point — recommend
declaring `localizedV2key` as lossy and emitting `localizedkey` on
all renders (matches the older format).

---

## 9. Local users

```
username admin password 5 $5$EDLMEF$.8ntNyDgFtWzZRmwFbZsaDZbpWRh5t.QoWsJDIA76CD  role network-admin
no password strength-check
```

| Token | Canonical |
|---|---|
| `username <name>` | `CanonicalLocalUser.name` |
| `password <hash-type> <hash>` | `CanonicalLocalUser.hashed_password` |
| `role <role>` | `CanonicalLocalUser.role` |

Identical to IOS-XE except:
* NX-OS uses `role` (not `privilege`).
* Hash-type 5 = $5$ SHA-256 crypt; preserved verbatim.

`no password strength-check` is a global system flag; parse-discard
or preserve in `raw_sections["password-policy"]`.

---

## 10. BGP (router bgp)

```
router bgp 65000
  router-id 1.1.1.1
  address-family ipv4 unicast
    network 192.168.122.0/24
    network 192.168.123.1/32
  neighbor 172.16.10.2
    remote-as 65000
    address-family ipv4 unicast
      soft-reconfiguration inbound always
```

L2VPN EVPN variant:

```
router bgp 65000
  router-id 1.1.1.1
  neighbor 2.2.2.2
    remote-as 65000
    update-source loopback0
    address-family l2vpn evpn
      send-community
      send-community extended
  vrf TENANT-777
    address-family ipv4 unicast
      redistribute direct route-map all
```

**Tier-3 scope.**  Codec captures the entire `router bgp` block into
`intent.raw_sections["router bgp"]` and surfaces the
`router bgp` header in `dropped_tier3_sections` for the migrate-page
notification banner.  No semantic parsing.

Implementor's optional enhancement: extract `router bgp <asn>` /
`router-id <ip>` / `vrf <name>` headers into a lightweight
informational record so the validation report can show "5 BGP
neighbors detected; not auto-translated".

IOS-XE delta: nearly identical block shape.  Same Tier-3 treatment.

The `router bgp / vrf <name> / address-family ipv4 unicast /
route-target import|export evpn` sub-block is the NX-OS L3VNI
RT-attachment form — already covered by Phase 4's EVPN parse
(Section 4.6 + canonical `l3_vni` field).

---

## 11. OSPF / EIGRP (Tier-3)

EIGRP variant:

```
router eigrp 1
router eigrp 23
router eigrp 45
```

And per-interface:

```
interface loopback1
  ip address 172.16.1.1/32
  ip router eigrp 1
```

NX-OS uses **per-interface activation** (`ip router eigrp N` inside
the interface stanza), not network-statements.  The codec parses
EIGRP and OSPF as Tier-3 raw sections; the per-interface
activation lines are also Tier-3 (no canonical EIGRP/OSPF model).

---

## 12. EVPN top-level block

```
evpn
  vni 5010 l2
    rd auto
    route-target import auto
    route-target export auto
  vni 5020 l2
    rd auto
    route-target import auto
    route-target export auto
```

Phase 4 surface.  Augments matching `CanonicalVxlan` records with
RT auto-derivation metadata.  Since `auto` implies "derived from
the BGP ASN + VNI", the codec can emit a flag rather than capturing
the literal RT value.  `CanonicalVxlan` schema may need a
`rt_auto: bool = False` field — OR the simpler thing: treat `auto`
as a sentinel string `"auto"` in a hypothetical `rt_imports`/`rt_exports`
field on `CanonicalVxlan` (currently the schema has no RT
field for VNIs; T2 / Phase 4 design decision).

Cross-vendor consideration: Arista EOS has the equivalent
`vlan-to-vni / vni 5010 / rd auto / route-target both auto`.  Junos
has `routing-instances <vrf> / vrf-target target:65000:5010`.
All three converge if we model `rt_imports`/`rt_exports` on
`CanonicalVxlan` as strings with `"auto"` accepted as a sentinel.

---

## 13. Fabric forwarding (anycast)

System level:

```
fabric forwarding anycast-gateway-mac 0a0a.1111.2222
```

Per-SVI:

```
interface Vlan10
  no shutdown
  vrf member TENANT-777
  ip address 10.10.10.1/24
  fabric forwarding mode anycast-gateway
```

T2 surface.  Phase 4 wires through whatever canonical model T2 ships.
If T2 deferred, declare both as `unsupported`.

---

## 14. Routing protocol metadata / Tier-3 sections

Catalogued for `_tier3_detection.detect_tier3_sections_nxos`:

| Stanza header | Tier-3 reason |
|---|---|
| `router bgp` | Tier-3 — operator must hand-author after migration |
| `router ospf` | Tier-3 |
| `router eigrp` | Tier-3 |
| `router isis` | Tier-3 |
| `ip access-list` | Tier-3 — same reason as IOS-XE |
| `ipv6 access-list` | Tier-3 |
| `route-map` | Tier-3 |
| `class-map` / `policy-map` | Tier-3 (QoS) |
| `crypto` | Tier-3 |
| `aaa` | Tier-3 (auth) |
| `mac access-list` | Tier-3 |
| `monitor session` (SPAN/RSPAN) | Tier-3 |

---

## 15. Boot + console + line vty (preserved raw)

```
line console
line vty
boot nxos bootflash:/nxos.9.2.3.bin
```

`boot nxos ...` is the firmware-version pin — preserved verbatim
in `intent.raw_sections["boot"]` so render emits it back unchanged.
Critical: cross-vendor migration target should NOT render this line
(other vendors have completely different boot statements); the
NX-OS render emits it only when source was NX-OS too.

---

## 16. RMON + copp + hardware (preserved raw)

```
copp profile strict
rmon event 1 description FATAL(1) owner PMON@FATAL
rmon event 2 description CRITICAL(2) owner PMON@CRITICAL
... (5 events total, identical across captures)
hardware access-list tcam region racl 512
hardware access-list tcam region copp 512
hardware access-list tcam region arp-ether 256 double-wide
```

All preserved in `raw_sections`.  The `rmon event N description ...`
block is boilerplate emitted by every NX-OS device with identical
content; the codec can either preserve verbatim or normalise to a
known-good default.  Recommendation: preserve verbatim — same as how
the IOS-XE codec handles `service timestamps` / `service
password-encryption`.

---

## 17. mac address-table

```
mac address-table aging-time 0
```

Switch-global L2-table tuning.  Preserved raw.

---

## 18. ip domain-lookup

```
ip domain-lookup
```

DNS resolver enable.  IOS-XE has `ip domain lookup` (space-separated;
NX-OS uses the dash form).  Preserved as a global flag in
`raw_sections` for v1; could be promoted to a canonical
`intent.dns_lookup_enabled: bool` if multiple vendors want it
(low priority — same value across the entire corpus).

---

## 19. ssh / key

10.3(9) sample emits:

```
ssh key rsa 2048
```

Parse-discard.  RSA host-key generation is device-state, not config.

---

## 20. icam monitor / line tuning (newer NX-OS)

```
icam monitor scale
line console
line vty
```

Parse-discard (informational telemetry feature in 10.x).  Preserved
in `raw_sections["icam"]` for round-trip.

---

## 21. Per-stanza summary table

For quick reference (mirrors the README.md but with parse/render
column added):

| Stanza | Parse | Render | Canonical surface |
|---|---|---|---|
| `!Command: show running-config` | banner detect | first line of every render | n/a |
| `version N.N(N) Bios:version` | `source_version` | first line after banner | metadata only |
| `hostname <name>` | `intent.hostname` | `hostname <name>` | `/system/hostname` |
| `vdc <name> id N` block | `raw_sections["vdc"]` | round-trip verbatim | n/a |
| `feature <name>` | parse-discard | auto-emit per dependency rules | n/a (render-derived) |
| `username <name> password <h> <hash> role <r>` | `CanonicalLocalUser` | `username ... role` | `/local-users/user/*` |
| `no password strength-check` | `raw_sections` | round-trip | n/a |
| `ip domain-lookup` | `raw_sections` | round-trip | n/a |
| `copp profile strict` | `raw_sections` | round-trip | n/a |
| `snmp-server user ...` | `CanonicalSNMPv3User` | full re-emit | `/snmp/v3-user` |
| `rmon event N description ...` | `raw_sections["rmon"]` | round-trip | n/a |
| `mac address-table aging-time` | `raw_sections` | round-trip | n/a |
| `vlan <N>[,M,...]` | `CanonicalVlan` (expanded) | re-coalesced range form | `/vlans/vlan/*` |
| `vlan N / name X / vn-segment Y` | `CanonicalVlan.name` + `CanonicalVxlan` | re-emit | `/vlans/*` + `/vxlan-vnis/*` |
| `vrf context <name>` block | `CanonicalRoutingInstance` | full re-emit | `/routing-instances/instance/*` |
| `interface Ethernet1/N` | `CanonicalInterface` | full re-emit | `/interfaces/*` |
| `interface Vlan<N>` | `CanonicalInterface` (kind=svi) + VLAN sync | re-emit | `/interfaces/*` |
| `interface port-channel<N>` | `CanonicalLAG` | re-emit + members | `/lags/*` |
| `interface loopback<N>` | `CanonicalInterface` | re-emit | `/interfaces/*` |
| `interface mgmt0` | `CanonicalInterface` (kind=mgmt) | re-emit | `/interfaces/*` |
| `interface nve1` block | `CanonicalVxlan.source_interface` + per-VNI | re-emit | `/vxlan-vnis/*` |
| `evpn / vni N l2` block | augment `CanonicalVxlan` | re-emit if any vxlan | `/vxlan-vnis/*` |
| `fabric forwarding anycast-gateway-mac` | T2 surface | T2 | `/anycast-gateway/*` (T2) |
| `ip route` (top-level + per-vrf) | `CanonicalStaticRoute` | re-emit | `/routing/static-route` |
| `router bgp` block | `raw_sections["router bgp"]` + `dropped_tier3` | parse-discard | n/a (Tier-3) |
| `router ospf` / `router eigrp` | same | same | n/a (Tier-3) |
| `ip access-list` / etc. | parse-discard + Tier-3 notify | parse-discard | n/a (Tier-3) |
| `line console` / `line vty` | `raw_sections["line"]` | round-trip | n/a |
| `boot nxos bootflash:...` | `raw_sections["boot"]` | round-trip | n/a |
| `nv overlay evpn` | discard (flag) | auto-emit on vxlan | n/a |
| `hardware access-list tcam region ... <N>` | `raw_sections["hardware"]` | round-trip | n/a |

---

## 22. Sample grammar that is NOT in the corpus (gaps)

The batfish corpus does not exercise:

* QoS (`class-map`, `policy-map type qos`, `service-policy`)
* TACACS+ / RADIUS server configuration (NX-OS uses `tacacs-server
  host` / `radius-server host`)
* DHCP relay (`ip dhcp relay`)
* IGMP snooping config beyond the bare `ip igmp snooping vxlan`
* Spanning-tree (`spanning-tree port type edge` etc.)
* IPv6 OSPFv3
* MPLS / SR
* Multicast routing (`feature pim`, `ip pim ...`)
* OOBM (`feature ssh` defaults to on; not the same as `feature
  scp-server`)

For Phase 4 closure the implementor should hunt for a real capture
that exercises QoS + spanning-tree + DHCP relay (the three most
common omissions).  See `05-fixture-targets.md` § 4.

---

## 23. IOS-XE → NX-OS grammar delta cheat-sheet

Single-table reference for cross-vendor migration:

| Concept | IOS-XE | NX-OS |
|---|---|---|
| Port name | `GigabitEthernet1/0/24` | `Ethernet1/24` |
| IP address | `ip address X.X.X.X Y.Y.Y.Y` | `ip address X.X.X.X/N` |
| VRF (top-level) | `vrf definition <name>` | `vrf context <name>` |
| VRF (interface bind) | `vrf forwarding <name>` | `vrf member <name>` |
| Switch-port default | L3 routed | L2 switchport |
| HSRP | `standby N` (`feature` not required) | `hsrp N` (requires `feature hsrp`) |
| VLAN id list | one per line OR `name X` | comma + range list accepted in one line |
| Loopback prefix | `Loopback0` (capital L) | `loopback0` (lowercase) |
| Mgmt port | `GigabitEthernet0/0` typically in Mgmt-vrf | `mgmt0` always in `management` VRF |
| BGP enable | implicit (`router bgp 65000`) | requires `feature bgp` |
| SVI enable | implicit | requires `feature interface-vlan` |
| LACP | requires `feature lacp` to use channel-group active/passive | requires `feature lacp` (same) |
| Static route per-VRF | `ip route vrf X DEST MASK GW` (flat) | indented under `vrf context X` block |
| Banner | `Building configuration...` | `!Command: show running-config` |
| VXLAN VTEP | `interface nveN / member vni X` (Catalyst 9k SDA) | `interface nve1 / member vni X [associate-vrf]` |
| Anycast gateway | `fabric forwarding mode anycast-gateway` (SD-Access) | identical phrase, but requires `feature fabric forwarding` |

This table is the operator-facing artifact the migrate-page should
surface as a banner when source vendor is IOS-XE and target is NX-OS
(or reverse).

---

## 24. Decisions captured here that propagate to `02-codec-architecture.md`

* Parse strategy: **line-scan + indentation-aware block detect**
  (mirrors `cisco_iosxe_cli/parse.py` exactly).  Indentation is
  consistent 2-space throughout the corpus.
* IP address parsing: single regex `ip address (\S+)/(\d+)` (NX-OS
  has only the CIDR form).  Much simpler than IOS-XE which has
  both `X Y Y Y Y` and `X.X.X.X/N` (the latter in newer captures).
* VRF parsing: parallel to IOS-XE's `_parse_routing_instances` but
  with `vrf context` keyword and embedded per-VRF static routes.
* Interface parsing: heavy reuse of IOS-XE's pattern (single big
  block-iterator state machine) but with NX-OS regex constants.
  No need to fork the helpers — the `cisco_iosxe_cli/parse.py`
  helpers are mostly regex-constant-driven; new constants for
  NX-OS + a new parser entrypoint.
* Render strategy: **emit feature block first, then top-level
  stanzas in canonical order**.  Order matters: `feature` must
  precede any dependent stanza.  See `02-codec-architecture.md`
  § 6 for the full render order.
