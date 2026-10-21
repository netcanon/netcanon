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

## A banner is text

The parser reads a banner as text, not as lines of the config: each
line of it is passed over by every reader of the parse (the Tier-3
rows, the check for a JSON or XML paste and the check for a text with
no indentation included), and nothing of it is translated.  Up to
0.7.7 every line of a banner was read as configuration: a body line
`username <name>` with ` group root-lr` under it was an account on 12
of the 13 public targets (with privilege 15 on nine), and a `vrf` line
a VRF, in jobs that said `completed`.  Detection still reads the text as it came.

- **What opens one**: a line in column 0, `banner` and its type --
  `exec`, `incoming`, `login`, `motd`, `prompt-timeout` or `slip-ppp`,
  the six of Cisco's `Cisco-IOS-XR-um-banner-cfg` model; Cisco's IOS XR
  command reference lists each in global configuration only -- or
  `aaa banner login`, whose value Cisco's AAA model describes in the
  same words.  Then white space and the delimiter.
- **The delimiter is the one character after the type.**  Unlike IOS,
  which prints every banner between two `^C`, IOS XR prints `banner
  <type>` and the text as it is stored, beginning with the delimiter
  that was typed: printed configs show `;`, `#`, `/`, `^`, `"`, `c` and
  `^C`.  Cisco calls it "a delimiting character" ("End with the
  character 'c'"), so `^C` is the delimiter `^` and a text that begins
  with `C`, as Batfish and scrapli_cfg read it.  Whether the router
  takes `^C` as one delimiter is not established.  The two readings end
  a banner on the same line unless a line holds a `^` without the `C`
  (or `c`) after it: read as one character the banner would end there
  and the lines after it be configuration, read as two it would run on.
  Such a line is refused (below); no printed config seen has one.  The
  delimiter is compared by its case.
- **Where the banner ends**: at the next occurrence of the delimiter,
  anywhere (Cisco: "terminating the message with the second occurrence
  of the delimiting character") -- on the line that opens it (`banner
  motd cc`, a banner with no text, is printed so), in the middle of a
  later line, or at its start or end (`<text>^C`, `<text>"`).  The
  whole of the line that ends it is the banner's: IOS XR prints what
  follows the delimiter there (spaces, or more text) as part of the
  stored text.  A line `!` or `end` inside it is its text.
- **A row for each kind of banner**: `banner motd (9 lines, from line
  4)` in the sections not translated.  It quotes nothing of the text
  and says how many lines the banners of that kind took -- see the
  limitation below.
- **Refused in words**, naming the line and quoting nothing (`parse
  failed: cisco_iosxr: line <n> ...`): a banner with no end before the
  end of the text (`opens a banner that runs to the end of this text`;
  read as it stands, nothing after it is configuration); a line in
  column 0 that names a banner IOS XR does not print (`banner` and a
  delimiter with no type, or `banner config-save`, as IOS has them; a
  type with no text after it; another `aaa banner`); a line of a
  banner printed with `^C` that holds a `^` and not the two (`holds a
  caret with no C after it`); and a line of a
  banner that ends in another character than a line feed -- a form
  feed, a vertical tab, a carriage return on its own (`is a line of a
  banner, or of another block of text, and ends in a character ...`).
- **Not handled**: the value of `crypto key generate rsa ... pubkey`,
  which Cisco's model calls "Generated keys in pem format" and whose
  printed form no source shows.  No other body of free text was found
  in Cisco's IOS XR configuration models or in printed configs.
- **A limitation: a banner set through NETCONF can be printed with no
  end.**  Cisco's xrdocs.io shows a banner set through the YANG model
  printed as `banner login ! <text>`, with no second `!`.  Its text then
  runs on to the next `!` in the config, and the lines between are
  taken for the banner's text: none of them is read (the safe side --
  no line of a banner becomes an account), but configuration among
  them is not translated, in a job that says nothing else of it.  The
  banner's row counts its lines: a banner that took many more lines
  than you wrote ended later than you meant.  Give the banner an end on
  the router (set it again from the CLI), or remove its line from the
  text you paste.

## Common gotchas

- **An interface's `mtu` counts the Ethernet header.**  Cisco: the
  L2 MTU "includes 14 bytes for an Ethernet interface", and 4 bytes
  more for each tag of a sub-interface.  The tree's MTU is the
  payload, so `mtu 9014` is `mtu 9000` on IOS-XE, NX-OS, EOS and
  AOS-CX, and their `mtu 9000` is written `mtu 9014` here (`mtu 9018`
  on a sub-interface with a tag).  A port, a management port, a
  `Bundle-Ether` and their sub-interfaces are converted; a loopback,
  a tunnel and a `BVI` are copied as they stand.  A second tag
  (Q-in-Q) is not read, and its 4 bytes are counted in the payload.
  ⚠️ Up to 0.7.7 the number was copied as it stood: IOS XR `mtu
  1514`, its default, was an IP MTU 14 bytes too large on the
  target, and IOS-XE `mtu 9000` an IP MTU of 8986 here.  Check MTUs
  migrated then.  The vendors' sentences are in the
  [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/mtu.md).
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
