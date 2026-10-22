# Juniper Junos — What works for me?

If you operate Juniper Junos devices and want to know what Netcanon
does for you, this is the page.

## TL;DR

- **`juniper_junos`** — `set`-form CLI parse + render.
  **Certification: certified.**  Bidirectional.

The codec works against `show configuration | display set` output
across Junos majors from 15.1 through 25.4, and reads the
hierarchical output of `show configuration` too — what of it is
read, and what is not, is under *Common gotchas* below.  Fixtures
cover QFX,
EX, and vMX-style platforms; the set-form grammar is consistent
across Junos platform families, so SRX / MX would parse + render
through the same pipeline (insofar as the surfaces overlap with
Tier 1+2; SRX firewall / NAT / VPN are Tier-3 deferred regardless).
SRX-platform fixtures aren't in the corpus yet — operator captures
welcome.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname` (via `set system host-name`), `domain`, DNS / NTP /
  syslog servers
- Interfaces — `set interfaces <name> unit <N> family inet address`
  CIDR form; IPv4 + IPv6; per-unit and bare-interface forms
- VLANs (`set vlans <name> vlan-id <id>`) with VLAN-centric
  membership projection
- Static routes (`set routing-options static route ...`)
- LAGs (`ae<N>` aggregated-ethernet, reconciled with cross-vendor
  names like `Port-channel<N>` / `trk<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 USM — `set snmp v3 usm local-engine user`
  authentication-key + privacy-key forms; VACM mappings via
  `security-to-group`
- RADIUS — `set system radius-server`
- DHCP server pools (where present)
- Local users with hashed passwords — `$1$` / `$5$` / `$6$` / `$9$`
  form-preserving migration
- **`apply-groups`** + group content — preserved byte-for-byte
  through round-trip (Junos-specific structural primitive)
- Routing instances + VRFs

## L3 redundancy: VRRP + virtual-gateway-address anycast

**New in v0.2.0** (Waves B + C — VRRP and anycast-gateway wire-up).

Junos's grammar is distinctive: every redundancy sub-command nests
under a parent `family inet address <X>/<prefix>` line, so the
address acts as the binding anchor.  The canonical model uses
interface-scope (`vrrp_groups` on `CanonicalInterface`), so the
parser records the binding-address anchor for round-trip; render-
side re-attaches the group to the primary address.  Exercised by the
QFX10K2 fixture (`ksator_labmgmt_qfx10k2_junos173.set`).

### Classic vrrp-group grammar

```text
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 virtual-address 10.1.1.1
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 priority 200
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 no-preempt
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 description "core-gw"
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 authentication-type simple
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 authentication-key "OPAQUE-KEY"
set interfaces ge-0/0/0 unit 0 family inet address 10.1.1.5/24 vrrp-group 10 track interface ge-0/0/1
```

Sub-commands handled: `virtual-address`, `priority`, `preempt` /
`no-preempt`, `description`, `authentication-type` +
`authentication-key` (merged into the canonical
`<scheme>:<value>` form), `track interface` (per-iface `priority-cost`
decrement is lossy), `fast-interval` (sub-second; drops to lossy as
canonical `advertisement_interval` is integer-seconds).  Multiple
groups can attach to the same address.

### Anycast-gateway (virtual-gateway-address)

DC-fabric anycast on the IRB unit — both halves of the surface
arrive on one `set` line:

```text
set interfaces irb unit 2021 family inet address 10.221.0.5/16 virtual-gateway-address 10.221.0.1
set interfaces irb unit 2021 family inet6 address fd20:2021::5/64 virtual-gateway-address fd20:2021::1
set interfaces irb unit 2021 family inet6 address fe80:2021::1/64
set interfaces irb unit 2021 virtual-gateway-v4-mac 02:00:21:00:00:01
set interfaces irb unit 2021 virtual-gateway-v6-mac 02:00:21:06:00:01
```

Canonical mapping:

- `family inet address X/M virtual-gateway-address Y` populates
  `CanonicalIPv4Address(ip=X, prefix_length=M,
  virtual_gateway_address=Y)` — both halves on the same record.
- `family inet6 address X/M virtual-gateway-address Y` mirrors the
  IPv4 path onto `CanonicalIPv6Address`.  The auto-emitted
  `fe80::/10` link-local lives on a SEPARATE record with
  `scope="link-local"` and no anycast companion.
- `virtual-gateway-v4-mac <MAC>` / `-v6-mac <MAC>` are per-IRB-unit
  (one MAC per address-family per unit) and apply to every
  global-scope address on the unit.  They land on
  `CanonicalIP{v4,v6}Address.virtual_gateway_mac`; the MAC line can
  come BEFORE or AFTER the address lines (order-independent parse).

### Known limitations

- **No system-wide anycast-gateway MAC.**  Junos models MAC per IRB
  unit / per family.  `CanonicalIntent.anycast_gateway_mac`
  (Arista's `ip virtual-router mac-address` / Cisco's
  `fabric forwarding anycast-gateway-mac`) is silently dropped on
  render — operator must distribute the value across every IRB
  unit's per-address MAC on the receiving Junos side.  The
  capability matrix declares `/anycast-gateway-mac` `unsupported`
  on the Junos codec.
- **Per-address binding round-trip.**  Junos binds the group to the
  address; the canonical model is interface-scope.  Parser picks
  the source address as the anchor; render re-attaches to the
  primary address.  If multiple addresses on the same unit each
  carry a vrrp-group in the source, the cross-vendor round-trip
  through interface-scope may consolidate them onto the primary
  (lossy when both addresses are present).
- **Track priority-cost decrement is lossy** (mirror of IOS-XE
  decrement / Arista decrement — only the interface name survives).
- **Sub-second `fast-interval`** drops to canonical
  `advertisement_interval=1` (lossy).

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model; see `02-per-vendor-grammar.md` §
  "Juniper Junos" for the per-address-binding rationale.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (`01-canonical-model.md` covers the
  decision to keep per-IP virtual_gateway_mac despite no other
  vendor having it).

## Lossy paths

- **`/routing-instances/instance`** — VRFs translate cleanly between
  Junos and Arista EOS; sub-field drift exists when targeting
  Cisco IOS-XE (per-VRF static-route VRF discriminator drops on
  round-trip).
- EVPN Type-5 routes — schema shipped, codec wire-up in progress;
  ship-before-wire path.

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall filters** — `set firewall family inet filter ...`
- **NAT** — `set security nat source rule-set ...`
- **IPsec VPN** — `set security ipsec ...`
- **QoS / CoS** — `set class-of-service ...`
- **Routing protocols** — BGP / OSPF / IS-IS / MPLS / LDP stanzas
  (informational only)
- **PKI / crypto material**

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`buraglio_netlab_junos184.set`** — Junos 18.4R1-S1.1 from a
  public ES.net netlab-ns demo (Nick Buraglio, BGP / IS-IS / MPLS
  parse-tolerance)
- **`ksator_labmgmt_qfx5100_junos173.set`** — Junos 17.3R1.10 on
  QFX5100 (DC access leaf with `apply-groups POC_Lab`, ae0/ae1 LAGs,
  16 VLANs)
- **`ksator_labmgmt_ex4550_junos151.set`** — Junos 15.1R6.7 on
  EX4550 (oldest Junos major in corpus; xe-0/0/0-2 trunk ports
  with `vlan members`)
- **`batfish_evpntype5_router1_junos2541.set`** — Junos 25.4R1.12
  EVPN Type-5 lab snapshot (4 IRB sub-interfaces, VRRP, VXLAN VNIs)
- **`batfish_l3vpn_pe1_junos2541.set`** — Junos 25.4R1.12 MPLS L3VPN
  PE (VRF + iBGP `family inet-vpn unicast` + LDP)
- **`ksator_labmgmt_qfx5110_junos173.set`** — Junos 17.3 on
  QFX5110 (DC leaf grammar; complements the QFX5100 fixture above)
- **`ksator_labmgmt_qfx10k2_junos173.set`** — Junos 17.3 on
  QFX10K2; **7 IRB units (2021-2025, 2031)** with v4 + v6
  anycast + per-unit v4/v6 MAC overrides.  Wave-C anycast-gateway
  reference fixture; closes the channelized-subinterface render
  bug fix from commit `f52489c`

Seven real captures covering four distinct Junos majors: 15.1, 17.3,
18.4, 25.4 (the 17.3 captures span EX4550 / QFX5100 / QFX5110 /
QFX10K2 hardware; the 25.4 captures are two scenario-distinct
EVPN-Type-5 and MPLS L3VPN snapshots).

## Common gotchas

- **An account whose password the source holds as typed is left out**
  as a target, with a review line in its place.  Junos takes a
  password into its config only as a hash (`encrypted-password`;
  `plain-text-password` asks at a prompt), and up to 0.7.7 the typed
  string was written as `encrypted-password "<typed>"`, which no
  password matches.
- **Tagged units and their device.**  A unit's tag is `vlan-id N`,
  or `vlan-tags outer N inner M` for two (a TPID of `0x8100` is read);
  the output gives the device the statement its units need --
  `vlan-tagging` for units of one tag, `stacked-vlan-tagging` for units
  of two, `flexible-vlan-tagging` for both (Juniper, "Binding VLAN IDs
  to Logical Interfaces") -- on a port, an `ae` bundle, a channel or a
  `reth`.  ⚠️ Up to 0.7.7 no such statement was written, from any
  source, Junos included; translate a config with tagged units again.
  A routed port's `native-vlan-id` is written with
  `flexible-vlan-tagging` ("To accept untagged packets, include the
  native-vlan-id statement and the flexible-vlan-tagging statement").
  Onto another vendor it is read as a trunk's native VLAN: IOS-XE
  writes it as `switchport trunk native vlan` on a routed port and
  EOS drops it, with nothing said -- set the native sub-interface by
  hand.  `encapsulation flexible-ethernet-services` is not read.  A
  unit with an address and no tag beside tagged units -- the address
  on the port of an IOS-XE router-on-a-stick -- is written as it
  stands with a `# review:` line: Juniper documents untagged frames on
  such a device through `native-vlan-id` and a unit of that id, and
  the output cannot choose the id without a guess.  A unit whose tag
  statement matches more than one tag (`vlan-id-range`, `vlan-id
  none`, an `inner-range`, a TPID other than `0x8100`, or two tag
  statements) is left out, with a row of the Tier-3 banner (`... -- not one 802.1Q tag and at most one inner tag, so the
  sub-interface is not translated`).
- **Block-form input is counted in the set commands it becomes.**  A
  block-form config is converted to set commands before it is read,
  and the whole path is written again for every statement under it, so
  a deep hierarchy with many statements is many times its own size
  (a statement marked `inactive:` is two commands, its `set` line and
  a `deactivate` line, and both are counted).
  The server's config size limit counts it in words (`words`), and a
  config past it is `refused:` with advice that is also the cure:
  paste `show configuration | display set`, which is not converted and
  not counted in words.  An `interface-range` with addresses on it is
  counted too (`copies`): every address goes onto every member.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § H.
- **A trunk's allowed list is written as a list.**  `vlan members
  all` is written only when the list is every VLAN id (1-4094).
  Any other list is cut into runs of consecutive ids: a run made
  only of VLANs this config defines is written by name; any other
  run is written as one id range, which covers the defined VLANs
  inside it (`1-99,101-4094` becomes `vlan members 1-99` and `vlan
  members 101-4094`; `2-4094` becomes `vlan members 2-4094`).  The
  output is the ELS form (`interface-mode`).  Release 0.7.7 and
  earlier wrote `all` for any list of 4,000 ids or more, which put
  the VLANs the source left out back on the trunk: check the `vlan
  members` line of any trunk translated that way.  Not verified on
  a device: that a switch commits a member range most of whose ids
  have no VLAN — run `commit check` on the output before relying on
  it.  A Junos trunk with no `vlan members` is read as a trunk of NO
  VLAN, and reaches IOS-XE, NX-OS and EOS as `switchport trunk
  allowed vlan none` (release 0.7.7 and earlier wrote it there as a
  trunk with no allowed line, which is every VLAN).  The other way: a
  Cisco or Arista trunk that states no list, and an AOS-CX `vlan
  trunk allowed all`, are every VLAN and are written `vlan members
  all` (those releases wrote them with **no** members).  So is a
  source port that states the trunk mode and keeps its list where it
  is not read — a port-channel member that leaves the list to its
  port-channel, a port that takes it from `inherit port-profile` or
  `source template`: check `vlan members all` on a port whose source
  stanza has no allowed line.  Not
  established from Juniper's pages: the sentence that says what a
  trunk with no members carries; it is read as none from the page
  for `members` and the one for `native-vlan-id`.  The vendors' own
  sentences are in the [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunk-that-states-no-allowed-list-platform-by-platform).
- **A trunk's native VLAN is among its `vlan members`, in the ELS
  grammar this codec writes.**  `native-vlan-id <N>` is written on
  the physical interface, beside the unit's `interface-mode trunk`
  and `vlan members`.  Juniper, of that grammar: "The logical
  interface on which untagged packets are to be received must be
  configured with the same VLAN ID as the native VLAN ID configured
  on the physical interface." — and its procedure fulfils that with
  `vlan members`.  So an AOS-S port that is untagged in one VLAN and
  tagged in others, and an OS10 trunk with an access VLAN, are
  written with that VLAN among the members as well as on
  `native-vlan-id`.  Release 0.7.7 and earlier left it off the
  members, in jobs that said `completed`: check the `vlan members`
  of every trunk with a `native-vlan-id` migrated then from AOS-S or
  OS10.  (That an untagged frame is dropped otherwise is not printed
  by Juniper, and the send direction is not established.)  A source
  trunk whose own list leaves its native VLAN out is written as it
  stands: `native-vlan-id` and members without it.  **The older
  grammar is another matter.**  On a switch that takes `port-mode
  trunk`, with `native-vlan-id` under the unit, the native VLAN
  belongs OFF the members: Juniper's knowledge base (KB17419, for EX
  Series, read in an archived copy) has it carried untagged both
  ways when it is not a member, and SENT TAGGED when it is.  An
  output of this codec is not for such a switch as it stands.  And
  as a source, a trunk in that grammar is read as an ELS one and its
  `native-vlan-id` under the unit is not read: the port's untagged
  VLAN is lost, and the job does not say so.  A Junos trunk with no
  `native-vlan-id` has no untagged VLAN (Juniper: "By default, the
  untagged packets are dropped on trunk interfaces."), and is
  written none.  **As a target, a Cisco, Arista or AOS-CX trunk that
  states no native VLAN and has VLAN 1 on its list is written
  `native-vlan-id 1`**, with the port a member of VLAN 1 and a `set
  vlans VLAN-1 vlan-id 1` line where the source declared no VLAN 1:
  on those platforms such a trunk has native VLAN 1, and carries it
  untagged.  Release 0.7.7 and earlier wrote the port a member of
  VLAN 1 with no `native-vlan-id`, a tagged VLAN: check such trunks
  migrated then.  Where the source trunk is every VLAN -- it states
  no allowed list -- the output is `vlan members all` beside
  `native-vlan-id 1`.  Juniper asks for the logical interface to be
  a member of the native VLAN ("The logical interface on which
  untagged packets are to be received must be configured with the
  same VLAN ID as the native VLAN ID configured on the physical
  interface."), and whether `all` takes the native VLAN in is not
  established: check on the switch that such a trunk receives
  untagged frames into VLAN 1, or name the VLAN on `vlan members`
  as Juniper's procedure does.  **As a source**, a Junos trunk with
  no `native-vlan-id` and VLAN 1 among its members (or `vlan members
  all`) drops untagged packets, and is written so on the four
  targets whose trunk would otherwise have native VLAN 1: AOS-CX
  `vlan trunk native 1 tag`, EOS `switchport trunk native vlan tag`,
  and on IOS-XE and NX-OS `vlan dot1q tag native`, a line for every
  trunk of the switch, where no port of the output that the check
  reads blocks it (a trunk that carries a VLAN untagged, a port in a
  mode no mode line is written for, trunk lines in no mode) -- or,
  where one does, no native line under a `! review:` line, with VLAN 1
  untagged by the target's default
  ([`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A trunk's
  allowed list is not what I wrote").  Release 0.7.7 and earlier
  wrote it no native line on all four, and it carried VLAN 1
  untagged there.  OS10 is written `no switchport access vlan` for it,
  under a `! review:` line (Dell's pages disagree on what that line
  leaves a trunk with), and AOS-S `tagged` in VLAN 1 where its members
  hold VLAN 1 or are `all` -- in a `vlan 1` stanza of its own where the
  Junos config declares no VLAN 1 -- and otherwise `no untagged` in
  VLAN 1 (see [`aruba_aoss.md`](aruba_aoss.md) and the limits in
  [`CAPABILITIES.md`](../CAPABILITIES.md)).
  The VLAN pane's map keeps to that
  reading.  Where a map would bring a native VLAN that the list
  leaves out INTO the list, the native VLAN is cleared if the map
  has merged it with a VLAN of the config that the list names, and
  the new id is taken out of the list if the list only covered that
  number with a range
  (`native-vlan-id 1000` beside `vlan members 2-999` and
  `1001-4094`, and 1000 renumbered to 900); the job says which, in
  a `vlan_rename:` warning
  ([`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A trunk's
  allowed list is not what I wrote").  The vendors' own sentences
  are in the
  [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunks-untagged-vlan-and-its-allowed-list-platform-by-platform).
- **A VLAN named `all`, or named like another VLAN's number or
  like a range (`50` for VLAN 100, `200-330`)** is written as
  `VLAN-<id>`, with a `# review:` line saying so: in a member list
  those names read as every VLAN, or as VLAN ids.  A VLAN named by
  its own number keeps its name.
- **A static route whose next hop is an interface**
  (`next-hop et-0/0/24.0`) follows that interface when a translation
  between two Junos configs renames it, and is removed with it when
  it is dropped.  Across vendors the unit form is left as written;
  with both devices declared (in the Interface rename modal or on
  the API) the route is then listed
  (`stale_next_hops`) and the job is `partial`.
- **Units.**  A tagged unit (`set interfaces ge-0/0/1 unit 54
  vlan-id 54`) is an interface of its own here, `ge-0/0/1.54`.
  Between two Junos configs it keeps its name, and follows a
  `port_rename_map` entry for its port (`ge-0/0/7.54`).  Onto another
  vendor it goes where its port goes, with its unit and its tag
  (`Ethernet1.54`, `encapsulation dot1q vlan 54`).
- **Loopbacks.**  Junos has one loopback interface, `lo0`: unit 0 is
  the loopback of the global routing table, and each routing
  instance takes a unit of its own.  A unit of `lo0` is the loopback
  of that number on another platform (`lo0.2` is `Loopback2` on
  IOS-XE, `loopback2` on NX-OS), and a reference to unit 0 (`lo0.0`)
  is the loopback itself.  Onto Junos the translator places the
  config's loopbacks together: the one loopback of the global table
  is `lo0` (of several, the one numbered 0), and a routing
  instance's one loopback numbered N is `lo0.N`, in that routing
  instance.  A loopback with no place — a second one in the global
  table, one of several in a routing instance, one numbered 0 in a
  routing instance, a number two routing instances share — is
  dropped and listed in `unresolved_ports`, with a warning that says
  why.  An entry decides it: `lo0` for the loopback of the global
  table (and `null` for the one that had the place), or another unit
  (`{"Loopback1": "lo0.1"}`), which Junos takes only in a routing
  instance — put the unit in one yourself.  Names the port
  translator does not read — `vme`, the
  units of `st0`, a channelized `xe-0/0/6:2`, and a bare `irb` or
  `st0` that a line configures — are left as they are on the
  target, and such a job lists them in `untranslated_ports` until
  each has an entry.  An interface is a name some line configures:
  `set interfaces irb unit 100 ...` configures `irb.100` and makes
  no `irb`, and `lo0 unit 1` alone makes `lo0.1` and no `lo0`.  The
  bare name is made by a line on the device itself or on its unit
  0, whether or not the rest of the line is read — a description,
  an MTU, `gratuitous-arp-reply`, a bare `set interfaces st0`, or
  `set interfaces st0 unit 0 family inet`, the unnumbered tunnel a
  route to `st0.0` goes out of.  A name the port translator reads
  as a port or as an `ae` bundle keeps its record whatever the
  config says of it: `ge-0/0/3` with only tagged units keeps its
  record.  (Not yet every port is read as one: with only units
  above 0 and no line of its own, a channelized `xe-0/0/6:2`, a
  `so-0/0/0` or a `reth0` has its units and no record.)  For an
  empty `st0` a Junos output has a bare `set interfaces st0` where
  the config has a unit of it too or a routing instance names it,
  and no line where it stands alone: an unnumbered `st0` is listed
  onto other platforms, and alone it is not written back to Junos.
  ⚠️ Up to 0.7.7 an empty `irb` (or `st0`, or `lo0`) was made beside
  its units, written into other platforms' output under that name
  and into a Junos output as a `set interfaces irb` line the source
  did not have; and an MTU or a unit-0 address on `irb` was lost
  where a unit beside it was folded onto its VLAN.  ⚠️ Up to
  0.7.7 a unit was written ONTO its port, also in a translation from
  Junos to Junos, where `fxp0` and `me0` also came back as `em0`;
  translate such a config again.  A unit of any device is written
  under its device (`set interfaces lo0 unit 10`, `set interfaces
  st0 unit 100`, `set interfaces ae1 unit 10 vlan-id 10`).  ⚠️ Up to
  0.7.7 that was so only for a device shaped like a port: a unit of
  `lo0`, `st0`, `ae`, `reth`, `me0`, `em0`, `fxp0` or `vme` was
  written `set interfaces lo0.10 unit 0 ...`, which Junos refuses,
  and a unit of an aggregate lost its `vlan-id`; translate such a
  config again.  A unit's MTU is written and read per family
  (`family inet mtu`, `family inet6 mtu`; on `family inet` where the
  unit has no address).  Where both families state one, inet's is
  kept, and unit 0's family MTU is not read: its record holds the
  device's own (media) MTU.  Juniper requires the device's media MTU
  to hold a family MTU and its encapsulation overhead, so where the
  device states no MTU (and the unit's is above 1500) or one no
  larger than the unit's, a `# review:` line says so.  ⚠️ Up to
  0.7.7 a unit's MTU was not read, and was written only under a name
  Junos refuses.  An IRB unit that a VLAN names (`l3-interface
  irb.100`) is folded onto the VLAN -- its address goes on the VLAN
  -- unless it holds what a VLAN record cannot: a description, a
  VRF, an IPv6 address or an MTU.  Such a unit stays `irb.100`.
  ⚠️ Until then an IRB unit's MTU was lost where it was folded.  `vlan-tagging` on the parent port is not
  read and not written: add it to an output that has tagged units.
- **Declaring a Junos device** — every interface name is the system's
  and is lower-case, so an override typed in another case
  (`GE-0/0/2`) is read as the port `ge-0/0/2`, not as a second
  interface.  A non-zero unit of a management port (`me0 unit 5`)
  follows its port (`set interfaces em0 unit 5 ...`).  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § G.
- **`apply-groups` content** is preserved byte-for-byte but is
  **opaque to translation** — group content stays in source-vendor
  syntax; the renaming operation (port / VLAN / user-name etc.)
  doesn't descend into `set groups ...` content.  When migrating
  TO Junos from a non-Junos source, configs come out flat (no
  apply-groups inheritance).
- **Renaming or dropping the bare `irb` in the rename modal does
  nothing to its units.**  Where a line configures the IRB device
  itself (a description, an MTU), a translation from
  Junos to Junos lists `irb` under *Other names in the config*
  beside each `irb.<unit>`.  An entry on an `irb.<unit>` row is
  shown by the output; one on the bare `irb` moves or removes what
  the device states, and the units stay under `irb`.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § F.
- **Root authentication** (`set system root-authentication
  encrypted-password`) is parse-and-ignore — root auth is
  distinct from user accounts and not in the canonical
  `local_users` model.
- **Bare-interface forms** (interface declared via `unit 0 family
  ethernet-switching ...` only) used to be dropped on render until
  the placeholder-line fix landed; now preserved with empty unit
  attributes.
- **Set-form and hierarchical** — both are read, detection offers
  the Junos codec for either, and both list the same Tier-3
  sections.  Of the hierarchical form, read:
  - what a device prints around its statements: the `## Last
    commit:` line, the `version` statement ahead of the first
    block, `## SECRET-DATA` after a secret, `##` warnings and the
    blocks of `display inheritance` and `display detail`,
    annotations (`/* */` above a statement, or `#`), `{ /* OMITTED
    */ }`, the `{ ... }` of `display max-depth` (what it elides is
    not in the text), a block with nothing in it;
  - the tags ahead of a statement: `inactive:` and `protect:`,
    which a device prints, and the operators of a load file, which
    no device prints — `replace:`, `active:` and `unprotect:` are
    taken off, and a statement under `delete:` is left out and
    listed as `delete: <path>`;
  - a capture as it leaves a terminal: the `{master:0}` line, the
    prompt with or without the command, `[edit]`, a pager's
    `---(more)---`, a Markdown fence, a byte-order mark, carriage
    returns.

  A comment begins only where a word could (`/* */`) or a
  statement could (`#`): `member ge-0/*/*;` and a group's `<*/*>`
  are words.  A `}` that closes nothing, a block left open and a
  `/*` opened after the first block and never closed are refused,
  each with a sentence.  (A `/*` left open ahead of the first
  block is not: the text is then not taken for this form.)  A
  secret the viewer was not shown (`encrypted-password /*
  SECRET-DATA */;`) is the same in both forms — the placeholder is
  the value, as `display set` prints it.  (Left out as a comment,
  it made a user with no credential at all.)

  **Not read:** the wildcards of an interface-range `member`
  (`ge-0/0/*`) and of a group (`<*>`) are not expanded — each
  becomes an interface of that name, and what the range or the
  group holds is not given to the ports it means; a `member-range`
  is not read at all, so nothing is made of it;
  `apply-groups "${node}"` (an SRX cluster) is not resolved, so
  what is under `node0` / `node1` is not read.  Both are the same
  in set-form.

  Every committed capture is set-form, so the hierarchical reader
  is held by built configs — each beside its set form typed by
  hand — and by public captures that were read and not committed.
  A real `show configuration` capture is welcome.
- **Deactivated statements are not translated.**  `deactivate
  <path>` in set-form and `inactive:` in the hierarchical form
  mark a statement the device holds and does not run.  It, and
  everything under it, is left out of the translation and listed
  in the Tier-3 banner as `inactive: <path>`.  (Before, its `set`
  lines were read as if in force, and an interface the source had
  switched off came out configured on the target.)  A Junos to
  Junos job does not write it back as inactive either.
  - The row names the statement and no secret: the path is cut
    after a word that names one (`inactive: snmp community ...`),
    and a leaf is named by its first word, as `display set` names
    one — so a deactivated `unit 0;` is listed as `... unit`.
  - What an applied group or an interface-range gives to a
    deactivated path is left out with it, and a group with nothing
    left is not applied.  No Juniper page was found that says what
    a device does there; batfish, an independent reader, prunes
    deactivated paths again after inheritance, and this follows it.
  - `activate <path>` further down takes a `deactivate` back (a
    typed script; no device prints one).  `delete <path>` is not
    read.
  - A `deactivate` that no `set` line is under is not listed.
  - **Not handled:** a reference to a deactivated statement from
    one that is in force.  An OSPF `interface` line for a
    deactivated port is still there to be read.  A port that a
    `routing-instances` statement still names comes back as a bare
    interface in that instance.  The member ports of a LAG whose
    own interface (`ae0`) is deactivated still say `802.3ad ae0`,
    and the LAG is made from them without the LACP mode or the
    `disable` it had: a target is given a static bundle that is
    up.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md) — when something
  doesn't translate cleanly
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
