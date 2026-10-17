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
  have **4 segments** (rack/slot/module/port) while the
  cross-vendor `PortIdentity` supports 3 (stack/module/port).  Slot,
  module and port are carried; the **rack** is kept for the same-vendor
  round-trip only and is not carried cross-vendor (it is `0` on every
  non-clustered system).  Verify port mappings via the rename modal.
  ⚠️ Releases up to and including v0.7.6 parked the *port* instead:
  every port on a card translated to the **same** cross-vendor name
  (`Gi0/0/0/0`, `/5` and `/17` all became `ge-0/0/0`).  This page
  described that as the segment "dropping to 0", which understated a
  many-to-one collapse.  Re-check any IOS-XR-sourced translation made
  on those releases.
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

- **Paste the config as the router prints it, with its
  indentation.**  IOS XR places each line of a configuration by its
  indentation when it loads a file: a line at the left margin is a
  line of the top level.  No Cisco manual says this in a sentence:
  Cisco's CLI model has an "indentation tracking" feature (`service
  cli indentation`, on unless disabled), and a Cisco engineer's router
  output (IOS XR 7.1.1) shows a file with no indentation loading with
  its VRFs' address-families moved to the top level and only the lines
  that then failed reported.  What the router does with such text
  typed or pasted at its prompt is not established.  A text with no
  indentation at all, the lines of a stanza this parser reads at the
  left margin, is refused (an indented comment is no indentation, nor
  is a no-break space in front of a line, which the `ntp` reader
  takes for the margin; `exit`, like `!` and `end`, is no line of a
  stanza's body): the job is `failed`,
  its error `parse failed: cisco_iosxr: this text has no
  indentation. ...`, naming the first line that opens a stanza with
  the line after it at the margin.  Neither the router nor Netcanon
  can tell where such a stanza ends -- the `!` lines say how many
  submodes close, not which line opened one -- so nothing is read
  rather than records made of the wrong lines.  A text in which only
  some lines lost their indentation is read by its indentation, as
  the router reads it: a line at the margin is a line of the top
  level.  ⚠️ Up to 0.7.7 a text with no indentation was read: it gave
  interfaces and VRFs made of lines nested under routing protocols,
  MPLS and config groups (interfaces called `all` or
  `'Bundle-Ether.*'` among them), with no address and no route, and
  local users with no secret, in jobs that said `completed`.  A
  translation made from such a text then holds interfaces and VRFs
  the router does not have, and none of its addresses: make it again
  from `show running-config`.
- **A whole `show running-config formal` config is refused, not
  read.**  A formal text is recognised by its `interface` lines: a
  line in column 0 that states an interface's setting on the
  `interface` line (`interface <name> description ...`, `... ipv4
  address ...`, `interface <name> l2transport encapsulation ...`) is
  the form `show running-config formal` prints, by the shape Cisco
  shows it printing for class and policy maps.  It is refused with its
  line number (the error begins `parse failed: cisco_iosxr: line <n>
  states an interface's setting`): paste `show running-config`
  without `formal`.  A one-line command typed
  into a printed config is refused the same way; write the setting on
  a line of its own under the interface.  A formal excerpt that holds
  no such `interface` line (`show running-config formal router
  static`, or formal output filtered by `| include`) is not
  recognised: it is read as almost nothing, in a job that can say
  `completed`.  ⚠️ Up to 0.7.7 each such line was a second record of
  the interface, with its setting lost; translate a config made of
  such lines again from `show running-config`.
- **A submode inside an interface does not end it.**  `ptp`, `lldp`
  and the like are closed by a `!` one level in; the interface's own
  lines after it are read, and a line indented under the submode is
  the submode's, not the interface's.  A line indented deeper than the
  interface's first line is read as nested, as the router reads it,
  and is not the interface's own: an `ipv4 address` indented one
  space too far is not translated.  ⚠️ Up to 0.7.7 the interface
  ended at the submode's `!`, and every line after it was lost: an
  address after a `ptp` block was not translated.  If you translated
  an IOS XR config whose interfaces hold a submode before their own
  lines with 0.7.7 or earlier, translate it again: its addresses, MTU,
  VRF and `shutdown` after the submode were not carried.
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
- **`interface preconfigure <name>` is not translated.**  IOS XR
  holds such a stanza for an interface it does not have until the
  line card is put in, and applies it then.  It makes no interface
  here — neither one called `preconfigure` nor the port it names —
  nothing in it is read, and the migrate banner lists it as a
  statement the source held and did not run (`preconfigure:
  interface <name> (held for an interface the source does not
  have; not translated)`).  Such a row is not counted with the
  sections, the rows are bounded, and a text that is nothing but
  such stanzas is `partial`: nothing of it was translated.  A job
  from IOS XR to IOS XR does not write the stanza back.  ⚠️ Up to
  0.7.7 it was an interface called `preconfigure` in every target's
  output: look for one in a config translated then.
- **A type and its number written apart** (`interface Bundle-Ether
  10`, `interface Loopback 0`) are one name, as the router reads
  them.  ⚠️ Up to 0.7.7 the name was the first word alone, and two
  such stanzas were one interface.  An interface written that way
  inside a `router static` line is still read a word at a time.  A
  header that begins `interface range` or `interface breakout`
  names no interface: it is not translated, and is listed on the
  migrate banner as a section (up to 0.7.7 it was an interface
  called `range` or `breakout`).

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
