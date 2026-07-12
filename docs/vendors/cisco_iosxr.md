# Cisco IOS-XR — What works for me?

If you operate Cisco IOS-XR service-provider routers (ASR 9000 / NCS
5500 / NCS 540 / XRd) and want to know what Netcanon does for you,
this is the page.

## TL;DR

- **`cisco_iosxr`** — `show running-config` text **bidirectional**
  (parse AND render).  **Certification: certified.**

IOS-XR is a routing-only platform with grammar distinct from both
IOS-XE and NX-OS — it gets its own codec and `CapabilityMatrix`.  The
codec targets the IOS-XR 6.x / 7.x surface: 4-segment interface
naming, Bundle-Ether LAGs, top-level `vrf` stanzas with route-targets
(and route-distinguishers harvested from the BGP block), dot1q
sub-interface VLANs, and the `username` block.  The SP-routing /
policy stanzas (`router bgp` / `router ospf` / `router isis` / `mpls
ldp` / `route-policy` / `prefix-set`) are surfaced on the migrate
banner via `dropped_tier3_sections`, **not** translated.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, enabled state, MTU, IPv4 + IPv6
  addresses, per-interface VRF membership (bare `vrf <name>`)
- VLANs — id + name, synthesised from `encapsulation dot1q` on
  sub-interfaces (no port-membership model; the name is always empty)
- Static routes — default VRF **and** per-VRF (`router static / vrf
  <name>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- VRFs — name, description, route-target import/export (the
  route-distinguisher is harvested from / rendered to the `router bgp`
  block; see [lossy](#lossy-paths))
- LAGs — Bundle-Ether (`bundle id <N> mode <m>` on member interfaces),
  reconciled with cross-vendor names like `Port-channel<N>` / `ae<N>`
- Local users — `username` block (group → role + secret hash),
  form-preserving

> **Management-plane caveat.**  When IOS-XR is the **target**, the codec
> now renders `domain name-server` / `ntp` / `logging <ip>` (promotion
> #13 — DNS / NTP / syslog round-trip, alongside the pre-existing
> `domain name`), but still emits no `clock timezone` / `dhcp` /
> `radius-server` / SNMP config — those surfaces stay declared
> `unsupported` (the live validation report flags the loss rather than
> reporting `severity: ok`).  See [What we don't do](#what-we-dont-do).

## Lossy paths

- **`/routing/static-route/metric`** — render emits destination +
  next-hop only; the administrative distance (metric) drops.
- **`/routing/static-route/description`** — the static-route name /
  description drops on render.
- **`/routing-instances/instance`** — VRF name / description /
  route-target round-trip cleanly, but the **route-distinguisher**
  lives in the BGP block (`router bgp <asn> / vrf <name> / rd <rd>`),
  not the `vrf` stanza.  The codec wires a minimal BGP-RD harvest +
  a minimal `router bgp` RD-carrier on render whose ASN is derived
  from the RD administrator field (`<asn>:<nn>` convention).  A config
  whose BGP ASN differs from the RD administrator re-emits the
  normalised ASN (cosmetic — the RD value itself round-trips).  An XR
  source with no `router bgp` stanza keeps `route_distinguisher=""`.
  `l3_vni` (EVPN Type-5) is not modelled — IOS-XR EVPN is a Tier-3
  `l2vpn` / `evpn` surface.
- **`/interfaces/interface/4th-port-segment`** — IOS-XR port names
  have **4 segments** (rack/slot/instance/port) while the
  cross-vendor `PortIdentity` supports 3 (stack/module/port).  The
  4th segment is preserved via `PortIdentity.meta['iosxr_port_index']`
  for the same-vendor round-trip but **drops to `0`** when renaming to
  a 3-segment target (IOS-XE / Arista).  Verify port mappings via the
  rename modal.
- **`/interfaces/interface/config/type`** — interface type is
  inferred from the name prefix (GigabitEthernet → ethernetCsmacd,
  Bundle-Ether → ieee8023adLag, etc.); sub-interfaces with
  vendor-specific encapsulation classify as `other`.

## What we don't do

**Surfaces IOS-XR render drops** (declared `unsupported` so the loss
is visible, not silent):

- **L2 switchport** — IOS-XR has no Cisco-style access/trunk model
  (VLANs are dot1q sub-interfaces); switchport mode / access-VLAN /
  trunk allowed-list / native VLAN / voice-VLAN all drop on render
- **Management plane** — `timezone`, DHCP server pools, RADIUS servers
  (host + secret).  (DNS / NTP / syslog servers now round-trip —
  promotion #13.)
- **SNMP** — parse + render is out of the v1 XR scope

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Routing protocols** — `router bgp` / `router ospf` / `router
  isis` / `mpls ldp` / `mpls traffic-eng` (surfaced on the
  `dropped_tier3_sections` banner; not auto-rendered)
- **Routing policy** — `route-policy` (the structured
  if/elseif/else/endif DSL), `prefix-set` / `community-set` /
  `as-path-set` set-form lists
- **EVPN / VXLAN** — IOS-XR EVPN runs under top-level `l2vpn` +
  `evpn` + `bridge group` stanzas, grammatically distant from the
  IOS-XE / Arista / NX-OS model; no canonical mapping in v1
- **ACLs / firewall / NAT** — `ipv4 access-list` / stateful firewall
  / `nat64` / `cgnat`

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).
Ten configs from **two independent sources** (both Apache-2.0):

- **`batfish/lab-validation`** (7 configs) — `cisco_xr_ios_vpnv4` PEs
  (`batfish_vpnv4_pe1/2/3.txt`), `iosxr_ebgp_basic` borders
  (`batfish_ebgp_border01/02.txt`), `iosxr_ibgp_rr_over_ospf` RR +
  client (`batfish_ibgp_rr.txt` / `batfish_ibgp_border01.txt`).  IP-
  based RDs (`10.254.1.1:65102`) harvested from `router bgp / vrf /
  rd`; dot1q `.35` sub-interface → synthesised VLAN.
- **`ios-xr/xrd-tools` `xr_compose_topos`** (3 configs) —
  `xrdtools_srv6_pe1.cfg` (SRv6 L3VPN PE), `xrdtools_sr_xrd1.cfg`
  (SR-MPLS), `xrdtools_isis_r1.cfg` (IS-IS IP-FRR).  These add the
  IS-IS / SR / SRv6 grammar the batfish trio lacks.

Collectively the corpus exercises 4-segment ports, Bundle-Ether LAGs,
MgmtEth / Loopback, the top-level `vrf` stanza with RT import/export,
RD-from-BGP harvest, per-interface `vrf` membership, per-VRF + default
`router static`, and the `username` block.  The certification spans
two independent upstreams so it doesn't rest on one source's grammar
conventions.  Further grammar diversity (flex-algo, L2VPN
bridge-groups, ACL, QoS) is welcomed via
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## Common gotchas

- **4-segment port names.**  `GigabitEthernet0/0/0/3` is
  rack/slot/instance/port.  Same-vendor round-trip preserves all four;
  renaming to a 3-segment vendor (IOS-XE / Arista) drops the 4th
  segment to `0` — confirm via the rename modal.
- **The RD lives in `router bgp`, not `vrf`.**  IOS-XR keeps the VRF
  route-distinguisher under `router bgp <asn> / vrf <name> / rd <rd>`.
  The codec harvests it from there and re-emits a minimal RD-carrier
  `router bgp` block on render.
- **VLANs are sub-interfaces.**  There is no VLAN database — a tagged
  VLAN appears as `encapsulation dot1q <vid>` on a sub-interface and
  is synthesised into the canonical VLAN id-list (no port membership).
- **SP routing is Tier-3.**  BGP / OSPF / IS-IS / MPLS / route-policy
  are surfaced on the migrate banner but never auto-rendered — every
  fixture's routing stanzas show up there.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md) — when something
  doesn't translate cleanly
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) — diagnostic
  flowchart
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md) — the cross-mesh audit
