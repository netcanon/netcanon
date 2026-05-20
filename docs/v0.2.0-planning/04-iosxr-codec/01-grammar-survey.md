# 01 — IOS-XR grammar survey

> Derived from sampling 7 configs across 3 batfish/lab-validation
> snapshots (`cisco_xr_ios_vpnv4/configs/{PE1,PE2,PE3}`,
> `iosxr_ebgp_basic/configs/{border01,border02}`,
> `iosxr_ibgp_rr_over_ospf/configs/{RR,border01}`).  Apache-2.0,
> publicly available; URLs in `05-fixture-targets.md`.

## Corpus inventory

| Snapshot | Config | Bytes | XR version | Highlights |
|---|---|---|---|---|
| `cisco_xr_ios_vpnv4` | PE1 | 2,671 | 6.6.2 | VRFs (red/blue/management), MPLS LDP, BGP vpnv4 RR client, route-policy PASS_ALL |
| `cisco_xr_ios_vpnv4` | PE2 | 2,251 | 6.6.2 | Same shape as PE1, single VRF |
| `cisco_xr_ios_vpnv4` | PE3 | 2,253 | 6.6.2 | RR endpoint config |
| `iosxr_ebgp_basic` | border01 | 2,608 | 6.2.2 | eBGP with route-policy + prefix-set; encapsulation dot1q sub-interface |
| `iosxr_ebgp_basic` | border02 | 1,901 | 6.2.2 | Smaller peer config |
| `iosxr_ibgp_rr_over_ospf` | RR | 2,630 | 6.2.2 | Bundle-Ether LAGs, OSPF underlay, BGP RR |
| `iosxr_ibgp_rr_over_ospf` | border01 | 2,899 | 6.2.2 | Bundle-Ether members, aggregate-address, route-policy |

Total: 17,213 bytes across 7 configs.  Enough coverage to fully
inventory the Tier-1 + Tier-2 grammar surface and the Tier-3
stanzas (BGP / OSPF / route-policy / MPLS) that the codec will
flag-and-skip.

---

## Top-level grammar inventory

Below: every top-level command observed in the corpus, grouped by
canonical translation tier.  IOS-XE comparison column flags major
divergences.

### Tier 1 (auto-translatable)

| XR command | Example from corpus | IOS-XE equivalent | Notes |
|---|---|---|---|
| `!! IOS XR Configuration <version>` | `!! IOS XR Configuration 6.6.2` | (none — IOS-XE uses `Building configuration...` / `Current configuration : N bytes` / `version 17.9`) | Top-of-file signature; **the** probe signal |
| `hostname <name>` | `hostname PE1` | `hostname Router` | Identical |
| `domain name <fqdn>` | `domain name test.lab` | `ip domain name test.lab` / `ip domain-name test.lab` | Note: XR uses `domain name`, IOS-XE uses `ip domain name` |
| `interface <name>` ... `!` | `interface GigabitEthernet0/0/0/0` ... `!` | `interface GigabitEthernet0/0/0` ... `!` | **4-segment vs 3-segment** port names |
| `interface MgmtEth0/RP0/CPU0/0` | (literal) | `interface GigabitEthernet0/0` (out-of-band) | XR has a dedicated `MgmtEth` interface kind |
| `interface Loopback<N>` | `interface Loopback0` | `interface Loopback0` | Identical name form |
| `interface Bundle-Ether<N>` | `interface Bundle-Ether23` | `interface Port-channel23` | LAG name divergence; render must convert |
| `interface <iface>.<subif-id>` | `interface GigabitEthernet0/0/0/1.35` | `interface GigabitEthernet0/0/0.35` | Subinterface — used with `encapsulation dot1q` |
| `  ipv4 address <ip> <mask>` | `  ipv4 address 10.254.1.1 255.255.255.255` | `  ip address 10.254.1.1 255.255.255.255` | **`ipv4 address`** vs IOS-XE `ip address` |
| `  ipv6 address <prefix>` | (not in seed corpus; documented in XR CLI) | `  ipv6 address 2001:db8::1/64` | Same on both — note IOS-XE has both `ipv6 address dhcp` and `autoconfig` keywords XR also accepts |
| `  description <text>` | `  description RR1` | `  description RR1` | Identical |
| `  shutdown` / (no shutdown by default) | `  shutdown` | `  shutdown` / `  no shutdown` | XR has no `no shutdown` form on output — absence means enabled |
| `  mtu <n>` | `  mtu 9216` | `  mtu 9216` | Identical |
| `  vrf <name>` (under interface) | `  vrf management` | `  vrf forwarding mgmt` / `  ip vrf forwarding mgmt` | **`vrf <name>`** vs IOS-XE `vrf forwarding <name>` |
| `  encapsulation dot1q <vlan-id>` | `  encapsulation dot1q 35` | `  encapsulation dot1q 35` | Identical syntax on subinterfaces |
| `  bundle id <n> mode <active\|passive\|on>` | `  bundle id 23 mode active` | `  channel-group 23 mode active` | LAG membership form divergence |
| `  bundle minimum-active links <n>` (on Bundle-Ether stanza) | `  bundle minimum-active links 2` | `  lacp min-bundle <n>` (under `interface Port-channel`) | LAG tuning |
| `router static / address-family ipv4 unicast / <prefix> <next-hop>` | `  11.0.0.0/8 GigabitEthernet0/0/0/2 11.1.1.2` | `ip route 11.0.0.0 255.0.0.0 GigabitEthernet0/0/0/2 11.1.1.2` | XR uses CIDR + a hierarchical stanza; IOS-XE uses one-line dotted-mask form |
| `router static / vrf <name> / address-family ipv4 unicast / ...` | `router static / vrf blue / ...` | `ip route vrf <name> <prefix> ...` | Per-VRF static routes |
| `username <name> / group <g> / password|secret <type> <hash>` | `username cisco / group root-lr / password 7 030752180500` | `username cisco privilege 15 secret 5 $1$...` | XR uses hierarchical `group` directive; IOS-XE inlines `privilege` |

### Tier 2 (auto-translatable with review)

| XR command | Example | IOS-XE equivalent | Notes |
|---|---|---|---|
| `vrf <name>` (top-level) | `vrf red / address-family ipv4 unicast / import route-target / 65102:2 / 65102:4 / export route-target / ...` | `vrf definition red / address-family ipv4 / route-target import 65102:2 / route-target export 65102:2` | **Most significant divergence.**  XR puts RT imports/exports in a sub-block; IOS-XE inlines them per line.  **RD lives elsewhere** in XR (under `router bgp`). |
| `ssh server v2` | (literal) | `ip ssh version 2` | Top-level (not per-protocol) |
| `ssh server vrf <name>` | `ssh server vrf management` | `ssh server vrf <name>` (variant) | Restricts SSH to a specific VRF |
| `line default / transport input ssh` | (literal) | `line vty 0 4 / transport input ssh` | Console / line config |
| `call-home / service active / contact ...` | (literal) | `call-home / contact-email-addr ...` | Smart Licensing call-home block; **Tier-3 in practice** (Cisco-specific, no canonical model) |

### Tier 3 (parse for display, never auto-render)

| XR stanza | Example trigger | IOS-XE equivalent | Notes |
|---|---|---|---|
| `router bgp <asn>` | `router bgp 65001` | `router bgp 65001` | Stanza grammar diverges significantly (see §"Router BGP deep-dive") |
| `router ospf <pid>` | `router ospf 1` | `router ospf 1` | XR: `router-id` + `network point-to-point` + `area <n> / interface <iface>` |
| `router isis <name>` | (not in seed corpus) | `router isis <id>` | Named instance |
| `mpls ldp / interface <iface>` | `mpls ldp / igp sync delay on-session-up 5 / interface GigabitEthernet0/0/0/0` | `mpls ldp router-id <iface>` (IOS-XE) | Distinct top-level stanza |
| `mpls te` / `mpls oam` | (not in seed) | `mpls traffic-eng tunnels` | MPLS TE |
| `route-policy <NAME> / ... / end-policy` | `route-policy AZURE-EAST-IN / if destination in AZURE-EAST-IN then / pass / elseif destination in AZURE-WEST-IN then / prepend as-path 65300 1 / pass / else / drop / endif / end-policy` | `route-map AZURE-EAST-IN permit 10 / match ip address prefix-list AZURE-EAST-IN / ...` | **Completely different grammar.**  See §"Route-policy DSL" |
| `prefix-set <NAME> / <prefix>[ le <n>], / ... / end-set` | `prefix-set AZURE-EAST-IN / 10.77.128.0/17 le 32, / 192.168.122.0/24 / end-set` | `ip prefix-list AZURE-EAST-IN seq 10 permit 10.77.128.0/17 le 32` | Set-form, not sequence-form |
| `community-set <NAME> / <community>, / ... / end-set` | (not in seed; documented) | `ip community-list standard <NAME> permit <community>` | Same set-form pattern |
| `as-path-set <NAME> / ...` / `extcommunity-set <NAME> / ...` | (not in seed) | `ip as-path access-list <N> permit <regex>` / `ip extcommunity-list ...` | Same pattern |
| `class-map` / `policy-map` (QoS) | (not in seed) | `class-map ... / policy-map ...` | XR has hierarchical-policer extensions; otherwise similar |
| `ipv4 access-list <NAME>` / `ipv6 access-list <NAME>` | (not in seed) | `ip access-list extended <NAME>` | XR uses sequence-numbered ACL entries (e.g. `10 permit ip any any`) |
| `lldp` (top-level) | (not in seed) | `lldp run` | Global LLDP enable |
| `cdp` (top-level + per-interface) | `  cdp` (per-interface in seed) | `cdp run` / `cdp enable` | Top-level + per-interface enable |
| `snmp-server <subcommand>` | (not in seed; documented in XR) | `snmp-server <subcommand>` | Same shape as IOS-XE; Tier-2 in IOS-XE codec but no examples in batfish corpus so deferred to Phase 3 in T4 |
| `aaa authentication ...` / `aaa authorization ...` | (not in seed) | `aaa authentication ...` | Similar |
| `tacacs-server host <ip>` / `radius-server host <ip>` | (not in seed) | `tacacs-server host <ip>` | Similar |
| `banner login | exec | motd` | (not in seed; documented) | `banner login ^C ... ^C` | Same shape |
| `logging <host>` | (not in seed; documented) | `logging host <host>` | Slight variation |

---

## Indentation and stanza-delimiter conventions

XR's wire format uses **leading spaces + `!` delimiters** for
hierarchical structure — identical to IOS-XE.  Each indentation
level is one or two spaces (parser must accept both).  A `!` line
closes the *current* stanza only — a 3-level-deep block uses 3 `!`
lines to unwind.

Sample from `vpnv4_PE1.txt`:

```
vrf red
 address-family ipv4 unicast        ← indent 1
  import route-target               ← indent 2
   65102:2                          ← indent 3 (leaf — list element)
   65102:4
  !                                 ← close indent-2 import block
  export route-target
   65102:2
   65102:4
  !                                 ← close indent-2 export block
 !                                  ← close indent-1 address-family
!                                   ← close vrf stanza
```

**Implication for parse:** the line-walker must track an indent
stack and unwind on each `!`.  This is a strict superset of the
IOS-XE walker (which has 1 indent level for `interface` stanzas
plus the top level — 2 states total).  XR routinely runs 3-4 deep.

---

## Route-policy DSL deep-dive

XR's `route-policy` is a **structured DSL**, not a sequence-numbered
list like IOS-XE `route-map`.  Sample:

```
route-policy AZURE-EAST-IN
  if destination in AZURE-EAST-IN then
    pass
  elseif destination in AZURE-WEST-IN then
    prepend as-path 65300 1
    pass
  else
    drop
  endif
end-policy
```

Statements:

- `if <condition> then ... endif` — conditional
- `elseif <condition> then ...` — chained alternative
- `else ...` — fallback
- `pass` / `drop` — verdict
- `set <attribute> <value>` — mutate the route (e.g. `set local-pref 200`)
- `prepend as-path <asn> <count>` — AS-path manipulation

Conditions:

- `destination in <prefix-set-name>` — prefix-list match
- `community matches-any <community-set-name>` — community match
- `as-path in <as-path-set-name>` — AS-path match
- Compound conditions via `and` / `or`

**This DSL cross-maps to IOS-XE `route-map` only at the
semantically-equivalent statement level**, not lexically.  Each
`if/elseif` branch is a separate `route-map ... permit <seq>` entry
on IOS-XE.  Translating cross-vendor without loss requires a full
expression-tree implementation.

**Codec treatment in v1:** parse-and-ignore Tier-3.  Surface the
stanza header in `dropped_tier3_sections` so operators see the gap.
Modeling `route-policy` would mirror the Junos `policy-options`
decision (intentionally unsupported — see `juniper_junos/codec.py`
LossyPath at `/groups` + the BGP `unsupported` declaration).

---

## Router BGP deep-dive (sketch — Phase 3 scope)

XR `router bgp <asn>` is the most divergent stanza from IOS-XE.
Per-VRF address-family setup uses a *nested* form not seen in
IOS-XE:

```
router bgp 65001
 bgp router-id 10.254.1.1
 address-family ipv4 unicast          ← global IPv4 AF
  redistribute static
 !
 address-family vpnv4 unicast         ← global VPNv4 AF
  additional-paths receive
  additional-paths send
 !
 neighbor-group RRs                   ← named template
  remote-as 65001
  update-source Loopback0
  address-family vpnv4 unicast
  !
 !
 neighbor 10.254.1.2                  ← uses the template
  use neighbor-group RRs
  description RR1
 !
 vrf red                              ← per-VRF override
  rd 10.254.1.1:65102                 ← RD lives HERE in XR (not in `vrf red` stanza!)
  address-family ipv4 unicast
   label mode per-vrf
   redistribute connected route-policy PASS_ALL
  !
  neighbor 11.1.1.2
   remote-as 65102
   ...
  !
 !
!
```

**Critical observation:** XR's RD lives under `router bgp / vrf <name>`,
**not** the top-level `vrf <name>` stanza.  IOS-XE's `vrf definition
<name>` carries RD inline.  This impacts T4's Phase 2 VRF
implementation directly — see `README.md` Open Question 4.

**Codec treatment in v1:** Phase 1-2 parse-and-ignore.  Phase 3 minimum
viable BGP harvest: `router bgp <asn>` (capture ASN), `bgp router-id
<ip>` (capture for downstream consumers if/when `CanonicalBgpRouter`
lands), `vrf <name> / rd <rd>` (lift to `CanonicalRoutingInstance.
route_distinguisher`).  Everything else surfaces via
`dropped_tier3_sections`.

---

## Major differences vs IOS-XE (call-out list)

For ease of reference during implementation:

1. **Port name has 4 segments** (rack/slot/instance/port) vs IOS-XE 3
   (stack/module/port).  All 4-segment XR fixtures use `0/0/0/N`
   exclusively because the seed devices are single-rack lab CSR
   1000v-XR / vRR / vXR; real ASR9k captures will have `0/RSP0/CPU0/0`
   for management and varied non-zero rack/slot for line cards.
2. **`ipv4 address` not `ip address`** inside interface stanzas.
3. **`vrf <name>` not `vrf forwarding <name>`** to bind interfaces.
4. **`Bundle-Ether<N>` LAG name not `Port-channel<N>`.**
5. **`bundle id <n> mode <m>` instead of `channel-group <n> mode <m>`**
   on member ports.
6. **`MgmtEth0/RP0/CPU0/0`** is the canonical XR management
   interface; no IOS-XE equivalent.  Cross-vendor mesh: kind=mgmt.
7. **`router static` is a stanza**, not a per-line directive.  IOS-XE:
   `ip route 10.0.0.0 255.0.0.0 1.1.1.1` (one line).  XR: `router
   static / address-family ipv4 unicast / 10.0.0.0/8 1.1.1.1`.
8. **`vrf <name>` (top-level) replaces `vrf definition <name>`** with
   different sub-structure: RT imports/exports go in a sub-block
   (not per-line directives), RD lives elsewhere.
9. **`!! IOS XR Configuration <version>` banner** at file head.
   This is the probe signal.
10. **`commit` semantics** — config is staged then committed.  Not
    visible in `show running-config` output; only in session
    transcripts.
11. **`route-policy` is a DSL**, not `route-map`.  Closed with
    `end-policy`, not `!`.
12. **`prefix-set`/`community-set`/`as-path-set`** are set-form,
    closed with `end-set` — not IOS-XE's sequence-form
    `ip prefix-list`/`ip community-list`/`ip as-path access-list`.
13. **`domain name` not `ip domain name`** at top level.
14. **`ssh server`** (no `ip`) at top level.
15. **No `service timestamps` line at top of file** — XR doesn't
    emit this in `show running-config`.

---

## Canonical-surface reuse vs extension

For each top-level `CanonicalIntent` field:

| Canonical field | XR coverage | Schema change needed? |
|---|---|---|
| `hostname` | `hostname <name>` | No |
| `domain` | `domain name <fqdn>` | No |
| `dns_servers` | `domain name-server <ip>` (rare; not in seed) | No |
| `ntp_servers` | `ntp server <ip>` (not in seed) | No |
| `interfaces` | full Tier-1 coverage | No (`PortIdentity` already supports kind="lag" / "mgmt" / "loopback") |
| `vlans` | XR doesn't have classic VLAN stanzas (no `vlan 100 / name X`) — VLAN-id appears only on `.subif` interfaces via `encapsulation dot1q` | No (current `CanonicalVlan` model supports vlan-id without name; codec emits a synthesised `CanonicalVlan` per `encapsulation dot1q`) |
| `static_routes` | `router static` stanza form | No (`CanonicalStaticRoute` already supports gateway + interface) |
| `dhcp_servers` | XR DHCP is via `dhcp ipv4 / profile ... / pool ...` (not in seed; defer to follow-up phase) | No |
| `snmp` | XR `snmp-server community / location / contact` (same shape as IOS-XE; not in seed) | No |
| `lags` | `Bundle-Ether<N>` + `bundle id N mode M` per-member.  Mode vocabulary: `active`/`passive`/`on` (same as IOS-XE) | No |
| `local_users` | XR `username X / group <g> / password|secret <type> <hash>` — hierarchical instead of inline `privilege` | Slight: `CanonicalLocalUser.privilege_level` carries the IOS-XE numeric form; XR `group root-lr` doesn't map to a privilege number directly.  Either (a) lift `group` to `role` and leave `privilege_level=1` default, or (b) hardcode `root-lr → 15`, `cisco-support → 15`, others → 1 |
| `radius_servers` | XR `radius-server host <ip> auth-port <n> acct-port <n>` (same as IOS-XE; not in seed) | No |
| `routing_instances` | `vrf <name>` + `address-family ipv4 unicast / import|export route-target` covers `name`/`rt_imports`/`rt_exports`.  `route_distinguisher` lives under `router bgp / vrf <name> / rd <rd>` — requires Phase 2 to peek at the BGP block | No |
| `vxlan_vnis` | XR has `nve <n>` interfaces on NCS 5500 / 540 platforms; rare in SP corpus.  Tier-3 unsupported | No |
| `evpn_type5_routes` | XR EVPN runs under `l2vpn` top-level + `bridge group` substructure; very different from IOS-XE/Arista/NX-OS.  Tier-3 unsupported | No |

**Net schema impact: zero.**  Every XR field maps onto the existing
canonical model.  The codec's job is to recognise the XR-specific
wire form and route to the right canonical field.

---

## What this survey does NOT cover

These XR areas would surface only if seed corpus widens — flagged as
deferred:

- IS-IS configuration (`router isis <name>` + `is-type level-1-2`)
- L2VPN configuration (`l2vpn / pw-class` / bridge-groups, EVPN BD)
- MPLS-TE (`mpls traffic-eng` + `interface ... mpls-te`)
- Segment Routing (`router isis ... / address-family ipv4 unicast /
  segment-routing mpls`)
- ACL extended grammar (sequence-numbered + `remark` lines + log
  modifiers)
- QoS (class-map / policy-map / hierarchical policer)
- Multicast (`multicast-routing / address-family ipv4 / interface
  all enable`)
- SNMPv3 USM (XR has the same shape as IOS-XE but no example in
  seed corpus)
- AAA + TACACS+ + RADIUS configuration
- NTP + DNS + logging + syslog server lines
- Banners (`banner login | motd | exec`)

All of these can land as follow-up grammar extensions once the v1
codec ships.  None are blocking for the Phase 1-4 scope above.
