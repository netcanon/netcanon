# Arista EOS — What works for me?

If you operate Arista EOS devices and want to know what Netcanon
does for you, this is the page.

## TL;DR

- **`arista_eos`** — EOS CLI parse + render.  **Certification:
  certified.**  Bidirectional.

The codec covers EOS 4.21 through 4.26 across DCS-7150S, DC1-LEAF
(vEOS EVPN/MLAG), and DuplicatePrivate-style fixtures.  The
underlying CLI grammar is stable from EOS 4.20+; newer LTS releases
parse / render cleanly but aren't covered by a fixture in the
corpus yet — operator captures from EOS 4.27+ are welcome (see
[`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)).

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname`, `domain`, DNS / NTP / `syslog_servers` (`logging host
  <ip>` harvest + render, promotion #11).  `timezone` is declared
  **unsupported** on this codec — see the capability matrix; it does
  not round-trip.
- Interfaces — `Ethernet<N>` and QSFP-breakout `Ethernet<N>/<M>`,
  Loopback, Management1; descriptions, IPv4 + IPv6, VRF binding
- VLANs — ID, name, tagged/untagged member lists
- Static routes
- LAGs (`Port-Channel<N>` reconciled with cross-vendor `ae<N>` /
  `Po<N>` / `trk<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 — community, contact, location, traps; v3 USM
  with auth + priv per user
- RADIUS — `radius-server host`
- Local users with hashed passwords — `secret sha512 $6$` and
  `secret 5 $1$` form-preserving cross-vendor migration
- MLAG — peer link + per-Port-Channel `mlag <id>` mapping
- VRF definitions (`vrf instance ...`)
- VXLAN — `interface Vxlan1` + `vxlan vlan <id> vni <vni>` mappings
  (ship-before-wire path stabilised)
- Routing instances (`/routing-instances/instance` declared
  supported on Arista — VRF + EVPN paths translate cleanly)

## L3 redundancy: VRRP + VARP anycast-gateway

**New in v0.2.0** (Waves B + C — VRRP and anycast-gateway wire-up).

### Classic VRRP

Multi-line per-group grammar inside an SVI / routed-port stanza.  The
codec accepts both the modern `ipv4` keyword (EOS 4.21+) and the
legacy `ip` form on parse; render always emits the modern `ipv4` form.

```text
interface Vlan30
   ip address 10.0.30.1/24
   vrrp 10 ipv4 10.0.30.254
   vrrp 10 priority 110
   no vrrp 10 preempt
   vrrp 10 track Ethernet1
   vrrp 10 description primary HA pair
   vrrp 10 timers advertise 3
!
```

Sub-commands handled: `ipv4` / `ip` (legacy) / `ipv6` (VRRPv3),
`priority`, `preempt` (+ `no` form), `description`, `track <iface>`
(decrement value lossy), `timers advertise <S>`, `mac-address`
(per-group override), `authentication text` / `authentication md5
key-string`.  Multiple `vrrp <gid> ...` lines on the same interface
converge onto one `CanonicalVRRPGroup` keyed by VRID; multiple VRIDs
on the same SVI surface as multiple records.

### VARP (Virtual ARP) anycast-gateway

DC-fabric anycast — every leaf SVI carries the same virtual IP, no
per-leaf primary on the wire.  Two surfaces:

```text
interface Vlan110
   ip address virtual 10.1.10.1/24
   ip address virtual 10.1.100.1/24 secondary
   ipv6 address virtual fd20:1::1/64
!
ip virtual-router mac-address 00:1c:73:00:dc:01
```

Canonical mapping:

- `ip address virtual X/Y [secondary]` lands on
  `CanonicalIPv4Address` with `ip=""` (no per-leaf primary) and
  `virtual_gateway_address="X"`; the `secondary` trailer round-trips
  via `is_secondary=True`.
- `ipv6 address virtual X/Y` (EOS 4.30+) mirrors the IPv4 path onto
  `CanonicalIPv6Address.virtual_gateway_address`.
- Top-level `ip virtual-router mac-address <MAC>` lands on
  `CanonicalIntent.anycast_gateway_mac` (system-wide; one MAC per
  device, cascades to every VARP IP).
- `ip address virtual source-nat vrf <V> address <Z>` is a DISTINCT
  feature (VARP source-NAT for VRF-leaked traffic, Tier 3) and is
  parse-and-ignored — does NOT pollute the VARP anycast surface.

### Known limitations

- **Per-IP virtual MAC is lossy.** EOS only supports a system-wide
  `ip virtual-router mac-address`; per-address MAC overrides (Junos
  `virtual-gateway-v4-mac` / `-v6-mac`) have no Arista equivalent.
  Cross-vendor renders from Junos sources surface a review banner on
  the migrate page.
- **VARP has no group_id on the wire.**  Discrimination is purely
  structural — `virtual_gateway_address != ""` on the address record
  IS the anycast intent.
- VARP source-NAT (`ip address virtual source-nat ...`) is Tier-3 and
  not modelled.
- **An interface's own address beside a shared gateway is two
  lines.**  From a source that has both on one interface (a Junos
  `virtual-gateway-address`, an AOS-CX `active-gateway`, an NX-OS
  anycast SVI) the output has `ip address virtual <gateway>` and
  then `ip address <own>`.  This codec reads those two lines back
  as two address records, and nothing here establishes that an
  EOS interface holds the two together: check on the device after
  loading that it has both.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model design rationale (`CanonicalVRRPGroup` +
  `mode="vrrp"` discriminator).
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (per-IP companion fields + system-wide
  MAC; § "Arista EOS (VARP)" covers the no-primary edge case).

## Lossy paths

- See per-codec `CapabilityMatrix.lossy` declarations.  Most fields
  parse + render cleanly within the documented surface; lossy paths
  surface only when translating to vendors with sub-field drift
  (e.g. per-IP virtual-MAC overrides collapsing onto EOS's single
  chassis-wide virtual-router MAC).

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall ACLs**
- **NAT**
- **IPsec VPN**
- **QoS**
- **Routing protocols** — `router bgp`, `router ospf`, EVPN
  redistribution policies (`address-family evpn`, route-map in/out
  filters) are parse-tolerant but not auto-rendered to other
  vendors
- **`management api http-commands`** / `daemon TerminAttr` —
  parse-tolerant
- **PKI / crypto material**

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`ksator_dcs_7150s64_eos4224.txt`** — DCS-7150S-64-CL on
  EOS 4.22.4M-2GB (256 lines; first Arista fixture); 5 local users
  mixing `nopassword` / `secret sha512 $6$` / `secret 5 $1$`;
  spanning-tree mstp, parse-and-ignore `router bgp` / `daemon
  TerminAttr` / `transceiver qsfp default-mode 4x10G`
- **`batfish_labval_dc1_leaf2a_eos4230.txt`** — vEOS DC1-LEAF2A
  EVPN leaf on EOS 4.23.0.1F (429 lines); MLAG peer link + 5
  Port-Channels, VXLAN1 overlay, 15 tenant VLANs, router bgp 65102,
  VRF definitions, Vlan3009 with VARP virtual-router MAC
- **`batfish_duplicateprivate_eos4211.txt`** — vEOS DuplicatePrivate
  on EOS 4.21.1.1F; private-ASN scenario (router bgp 65001 +
  neighbor remote-as 65001)
- **`karneliuk_a_eos1_eos4260.txt`** — vEOS on EOS-4.26.0.1F; full
  EVPN/VXLAN kitchen-sink (route-maps, BGP EVPN address-family,
  VLAN VNI mappings)
- **`batfish_eos_evpn_vlan_based_leaf.txt`** — Batfish public
  corpus VLAN-based EVPN leaf reference (Apache-2.0).  6 SVIs
  including a VARP secondary on Vlan110 + system-wide MAC.  Wave-C
  reference for Arista VARP wire-up

Spans 4 distinct EOS majors (4.21 + 4.22 + 4.23 + 4.26).

## Common gotchas

- **`secret 0 <password>` is read as a password as typed**, and is
  written so onto every target that takes one.  Up to 0.7.7 it was
  read as an algorithm `0` that no target takes, and the account was
  left out everywhere, EOS included.  A printed EOS config holds no
  `secret 0`: the switch hashes the password when it is entered.
- **Paste the config as the switch prints it, with its
  indentation.**  This parser tells which lines belong to a stanza by
  their indentation.  A text with no line indented but a comment, the
  lines of a stanza it reads (`interface`, `vlan <id>`, `vrf instance`
  / `vrf definition`, `ip dhcp pool`, `router bgp`) at the left
  margin, is refused: the job is `failed`, its error `parse failed:
  arista_eos: this text has no indentation. ...`, naming the first
  line that opens a stanza with the line after it at the margin.  It
  quotes nothing of the text.  Indentation is a space or a tab: a
  no-break space in front of a line (a paste out of a web page) is
  none, and the stanza readers take such a line for one at the
  margin, so a text indented that way is refused too.  What the
  switch itself makes of such a text
  Arista does not say.  Typed or pasted, a line runs in the deepest
  open mode that accepts it, and otherwise in a parent mode (Arista's
  manual, with its transcripts), and Arista's own config generator
  deploys a config through eAPI as a flat stream of commands, its
  indentation and `!` lines removed: so the switch most likely reads a
  flat text by the mode each command leaves open (inferred -- strongly
  for a configuration session and eAPI, less so for a file loaded with
  `copy` or `configure replace`; whether a file's indentation is
  consulted when it is there is not established).  Reading it that
  way would need the words each mode takes -- `router bgp` takes
  `vlan` and `vrf`, `group interface` takes `interface` -- and no
  Arista page lists them, so Netcanon refuses the text rather than
  guess where its lines belong.  A text in which only some lines lost
  their indentation is read by its indentation.  ⚠️ Up to 0.7.7 a
  text with no indentation was read: a `vlan <id>` block under
  `router bgp` became a second VLAN of that id, and every interface
  address, description, VLAN membership, LAG, VXLAN VNI, route
  distinguisher and route target was lost, in jobs that said
  `completed` or were `partial` for another reason; none said a line
  was not read.  Make such a translation again from `show
  running-config`.
- **A banner is text, never configuration.**  `banner login` and
  `banner motd` are printed with their body as it was typed and a line
  `EOF` in column 0 after it (so Arista's own pyeapi reads a printed
  banner): the body ends there, and a line ` EOF` with white space in
  front of it is the banner's text.  The body is the switch's to show,
  and Netcanon translates no banner.  The same holds for every other
  body that Arista's tools end at an `EOF` line, indented or not: a
  `comment` typed in a mode, RCF `code unit <name>`, a multi-line
  `action bash`, and after `protocol https certificate` a certificate
  and then its key -- a shape Arista's config generator prints, so
  each of those two bodies is taken for one only where its first line
  begins as PEM text does (`-----BEGIN`), and a printout with one
  body, or none, is read as before.  Each line of such a body is
  passed over by every reader of the parse, the Tier-3 rows and the
  check for a JSON or XML paste included (detection still reads the
  text as it came).  A body with no `EOF` line before the end of the
  text is refused (`parse failed: arista_eos: line <n> opens a block
  of text ...`): read, every line after it would be the body's text.
  So is a line that opens a body, or is in one, and ends in another
  character than a line feed -- a form feed, a vertical tab, a carriage
  return on its own (`... is a line of a banner, or of another block of
  text, and ends in a character ...`): the switch ends a line at a line
  feed, so its `EOF` line is not where those lines say, and a banner
  cut short there had its next lines read as configuration.
  ⚠️ Up to 0.7.7 a banner's lines were read as lines of the config: a
  line `username <name> privilege 15 nopassword` in a banner became
  an administrator account with no secret on the target, and a
  banner's `vlan`, `interface`, `ip route` and `ip access-list` lines
  became VLANs, interfaces, routes and a Tier-3 row, in jobs that
  said `completed`.  If you translated an EOS config with a banner (or
  any other body ended by `EOF`) with 0.7.7 or earlier, translate it
  again, and look in the old output for accounts, interfaces, VLANs
  and routes the switch does not have.
- **`router bgp` is read by relative depth, not by its width.**  The
  section's own lines are at the shallowest indentation of any of its
  lines; a `vrf <name>` or `vlan <id>` block's header has to stand
  there, and its lines deeper -- its body is every line deeper than
  it, up to the next line at the section's own depth.  So tabs, or two
  or four spaces a level, read as EOS's own three do, and a `!` inside
  `router bgp` closes no block.  A header deeper than another line of
  the section's own (a hand edit) opens no block, and its lines land
  on nothing.  An interface or a VLAN stanza takes every indented line
  as its own, at any depth: EOS places a line by the mode it is typed
  in, not by its indentation, so no depth tells a submode's line from
  the interface's -- a line this parser reads (`shutdown`,
  `description`, ...) typed inside an interface's submode (`tx-queue`,
  `evpn ethernet-segment`) is read as the interface's (no Arista
  printout shows one there).  An empty line closes nothing anywhere (a
  paste that doubled every line end reads as the config).  ⚠️ Up to
  0.7.7 the `router bgp` reader counted EOS's own widths exactly, so a
  config indented otherwise lost its MAC-VRFs, route distinguishers
  and route targets, and an empty line ended the interface, VLAN or
  `router bgp` it was in, its addresses and descriptions lost after
  it.  If you translated an EOS config indented with tabs or another
  width, or with empty lines in it, with 0.7.7 or earlier, translate
  it again: the old output may lack its MAC-VRFs, route
  distinguishers and route targets, or its addresses and
  descriptions.
- **A trunk's allowed list means what it says.**  A trunk with no
  `switchport trunk allowed vlan` line is read as a trunk of EVERY
  VLAN — the EOS default, which EOS states by the absence of the
  line — and reaches another vendor as that.  `switchport trunk
  allowed vlan none`, and a list emptied by `remove` or `except`, is
  a trunk of NO VLAN.  `add` and `remove` on an interface's first
  allowed line start from every VLAN.  As a target: every VLAN is
  written as
  a trunk with no allowed line (never the ids, which are one line of
  some 19,000 characters); no VLAN is `switchport trunk allowed vlan
  none`; any other list is written as it stands.  Release 0.7.7 and
  earlier had one value, an empty list, for a trunk that allows no
  VLAN and for one that states no list: a `none` trunk came out here
  as a trunk of every VLAN, and a trunk with no list reached Junos,
  OS10 and AOS-S carrying none — check trunks translated that way.
  A port with a `switchport trunk` line and no `switchport mode
  trunk` line is read as a trunk — even after `switchport mode
  access` — though an EOS port is an access port until it is told
  otherwise and keeps a trunk line without acting on it.  That is an
  older fault of the parser.  Such a port is given nothing from the
  default: it is a trunk of the VLANs its lines name, or of NO VLAN
  (`switchport trunk native vlan 999` alone comes back with
  `switchport trunk allowed vlan none`), never of every VLAN, and
  it is given no default native VLAN either: VLAN 1 on its list is
  a tagged VLAN of it.  The last of its lines decides what it is
  read as: `switchport access vlan 10` followed by `switchport
  trunk allowed vlan 1,10,20` is a trunk with NO access VLAN, and
  the two lines the other way round are an access port in VLAN 10
  that keeps the list.  Take the trunk lines off an access port
  before translating, or add `switchport mode trunk` to a trunk.  The
  vendors' own sentences are in the
  [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunk-that-states-no-allowed-list-platform-by-platform).
- **A trunk's native VLAN, and whether its allowed list names it.**
  `switchport trunk native vlan <N>` is a line of its own, and the
  allowed line can name N or leave it out; either is read as it is
  written and comes back so.  In the canonical tree the list is what
  a trunk carries, so a native VLAN the list leaves out is stated
  and not carried: it reaches AOS-S with no `untagged` line, and a
  `; review:` line that says so, and OS10 as `no switchport access
  vlan` under a `! review:` line (release 0.7.7 and earlier wrote
  the port untagged in that VLAN on both).
  **What an EOS switch does with a native VLAN its list leaves out
  is not established**: Arista's manual words the list as a list for
  tagged traffic in one sentence and as the port's VLAN membership
  in another, and no account of the case was found.  As a target, an
  AOS-S port that is untagged in one VLAN and tagged in others, and
  an OS10 trunk with an access VLAN, are written with that VLAN on
  the allowed line beside the native line (`switchport trunk native
  vlan 10`, `switchport trunk allowed vlan 10,20,30`).  Release
  0.7.7 and earlier left it off the allowed line, in jobs that said
  `completed`: check the allowed list of every trunk with a native
  line migrated then from AOS-S or OS10.  **A trunk that states no
  native VLAN has native VLAN 1** (Arista: "The default native VLAN
  for all interfaces is VLAN 1.").  Where its allowed list holds
  VLAN 1 -- the list names it, or there is no allowed line -- a
  port that says `switchport mode trunk` is read as carrying VLAN 1
  untagged, and Junos, OS10 and AOS-S are written so
  (`native-vlan-id 1`; `switchport access vlan 1`; `untagged`).
  Release 0.7.7 and earlier wrote VLAN 1 TAGGED on those three, in
  jobs that said nothing: check such trunks migrated then.  Where
  the list leaves VLAN 1 out nothing is filled in.  That is a
  native VLAN outside its list, and what an EOS switch does with
  one is not established (above): the trunk is read as having no
  untagged VLAN, which says nothing about the switch.  As a
  target, no `switchport trunk native vlan 1` line is written for
  a trunk whose list holds VLAN 1: it is the default, and no real
  EOS capture prints the line.  A `vlan 1` line IS written where a
  trunk of the source carries VLAN 1 untagged by its platform's
  default, though the source may have no word for VLAN 1 and no
  real EOS capture prints the line: the tree has the VLAN, and
  every VLAN of the tree is declared.  A port that carries NO VLAN
  untagged at its source and has VLAN 1 on its list (a Junos trunk
  of `vlan members all` with no `native-vlan-id`, say) is written
  `switchport trunk native vlan tag` (Arista: "tag interface drops
  all untagged frames."), where it was written no native line and
  carried VLAN 1 untagged by that default.  What such an interface
  SENDS for VLAN 1 is not on Arista's page: check it on the switch.
  As a source, `switchport trunk native vlan tag` is read as no
  untagged VLAN, and comes back as it went where the trunk's list
  holds VLAN 1.  Where the list leaves VLAN 1 out it comes back with
  no native line, and what EOS does with untagged frames on such a
  trunk is not established.  The id and `tag` are one argument of
  the line, so the one met last stands.  The
  Cisco line `vlan dot1q tag native` is read as well, as words, and
  is not written: no line for every trunk is in Arista's VLAN
  pages.  The VLAN pane's map keeps to that
  reading.  Where a map would bring a native VLAN that the list
  leaves out INTO the list, the native VLAN is cleared if the map
  has merged it with a VLAN of the config that the list names, and
  the new id is taken out of the list if the list only covered that
  number with a range
  (`switchport trunk native vlan 1000` beside `switchport trunk
  allowed vlan 2-999,1001-4094`, and 1000 renumbered to 900); the
  job says which, in a `vlan_rename:` warning
  ([`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A trunk's
  allowed list is not what I wrote").  The vendors' own sentences
  are in the
  [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunks-untagged-vlan-and-its-allowed-list-platform-by-platform).
- **MLAG is NOT translated** — corrected 2026-09-24; this entry
  previously claimed the parser "round-trips the peer-link mapping",
  which was wrong in both halves.  There is no MLAG or peer record on
  the canonical tree and no codec models one, so neither the
  `mlag configuration` block (domain-id / peer-address / peer-link) nor
  the per-bundle `mlag <N>` marker reaches the canonical tree or the
  rendered output.  What *does* round-trip is the Port-Channel itself —
  its name, members and description, via `CanonicalLAG` — and
  cross-vendor renaming of that name works.  That is a LAG surviving,
  not an MLAG surviving: a bundle that was dual-homed across the peer
  pair becomes an ordinary single-chassis Port-Channel on the target.
  Both halves are now reported in the Tier-3 banner (with the bundle id,
  so you can see which Port-Channels changed meaning) rather than
  dropped silently.  The same defect, and the same fix, applies to Dell
  OS10's VLT — see [`dell_os10.md`](dell_os10.md).
- **`channel-group` emission on member Ethernets** — render-side
  bug fixed early in the codec history (`channel-group N mode
  <mode>` on member Ethernet interfaces was missing); regression
  test pinned in `tests/unit/migration/test_arista_eos.py`.
- **EVPN/VXLAN ship-before-wire** — schema shipped early; render
  + parse for `interface Vxlan1` and per-VLAN VNI mappings stabilised
  in Wave 10β-B.
- **`service routing protocols model multi-agent`** — preserved as
  raw section; not in canonical model.
- **Renaming or dropping `Vlan<N>` in the rename modal is not shown
  by the output.**  A translation from EOS to EOS lists each VLAN
  interface under *Other names in the config*.  EOS output writes
  `interface Vlan<id>` from the VLAN itself: renamed, the interface
  is written under the new name and the old one again; dropped, it
  comes back.  And a loopback that is the VXLAN source can be
  renamed there, but dropped it is still named by `vxlan
  source-interface`.  The job records each entry and says nothing.
  Renumber or drop the VLAN on the VLANs pane, which takes its
  interface with it.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § F.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
