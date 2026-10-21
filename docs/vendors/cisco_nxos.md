# Cisco NX-OS — What works for me?

If you operate Cisco Nexus (NX-OS) data-center switches and want to
know what Netcanon does for you, this is the page.

## TL;DR

- **`cisco_nxos`** — `show running-config` text **bidirectional**
  (parse AND render).  **Certification: certified.**

NX-OS is a distinct grammar from IOS-XE — it gets its own codec, its
own `CapabilityMatrix`, and its own render path.  The codec targets
the NX-OS 9.x+ data-center surface (Nexus 3000/9000-class): L2
switchport + VLAN database, port-channel LAGs, VRFs with RD /
route-target, VXLAN-EVPN (L2VNI + symmetric-IRB L3VNI), HSRP, and the
IPv4 Distributed Anycast Gateway.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, enabled state, MTU, IPv4 + IPv6
  addresses, VRF binding
- L2 switchport — access / trunk mode, access-VLAN, trunk allowed-VLAN
  list, trunk native VLAN, port-channel (`channel-group`) membership
- VLANs — ID, name, tagged/untagged port lists (VLAN-centric
  projection from the per-interface `switchport` form)
- Static routes — default VRF **and** per-VRF (`ip route … vrf X`)
- LAGs (`port-channel<N>` reconciled with cross-vendor names like
  `ae<N>` / `Port-channel<N>` / `trk<N>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- SNMP v2c community + v3 USM (community, location, contact,
  trap-hosts, v3 users with auth + priv)
- Local users — named NX-OS `role` (network-admin / network-operator
  / custom) + hashed password, form-preserving
- VRFs — name, description, route-distinguisher, route-target
  import/export
- VXLAN-EVPN — VLAN↔VNI binding (`vlan N / vn-segment`), the `nve1`
  VTEP (source-interface, UDP port, multicast group, flood list), and
  the symmetric-IRB **L3VNI** (`vrf context X / vni N`)

> **Management-plane caveat.**  When NX-OS is the **target**, the codec
> now renders `ip domain-name` / `ip name-server` / `ntp server` /
> `logging server` (promotion #4 — domain / DNS / NTP / syslog
> round-trip), but still emits no `ip dhcp` / `radius-server` / `clock
> timezone` config — those surfaces stay declared `unsupported` (the
> live validation report flags the loss rather than reporting
> `severity: ok`).  See [What we don't do](#what-we-dont-do).

## L3 redundancy: HSRP + IPv4 Distributed Anycast Gateway

### HSRP (FHRP)

NX-OS expresses first-hop redundancy as HSRP, nested under the SVI:

```text
interface Vlan10
  hsrp 10
    priority 110
    preempt
    ip 10.1.10.1
```

The canonical model is vendor-neutral (`CanonicalVRRPGroup` with a
`mode in {"vrrp", "hsrp", "carp"}` discriminator).  On render, the
codec emits **every** group as an `hsrp` block regardless of the
source `mode` — so a cross-vendor VRRP / CARP group normalises to
HSRP on NX-OS.  The operator's redundancy intent for the virtual IP
survives; the wire protocol changes (this is declared
[lossy](#lossy-paths)).  Same-vendor HSRP round-trips losslessly.

### IPv4 Distributed Anycast Gateway

Fabric-mode anycast: a chassis-wide MAC plus a per-SVI marker.

```text
fabric forwarding anycast-gateway-mac 0001.c73a.0000
!
interface Vlan100
  ip address 10.1.100.1/24
  fabric forwarding mode anycast-gateway
```

Canonical mapping:

- `fabric forwarding anycast-gateway-mac AABB.CCDD.EEFF` lands on
  `CanonicalIntent.anycast_gateway_mac` (dotted-triplet ↔ canonical
  colon-hex).
- Per-SVI `fabric forwarding mode anycast-gateway` mirrors the
  primary IP as the anycast (`virtual_gateway_address = ip`).  This
  is the same IP-mirror semantic shared with the IOS-XE SD-Access
  codec.

**IPv6 anycast is unsupported** — IPv4 DAG is fully wired; the IPv6
companion parses-and-ignores in v1 (parity with the IOS-XE codec's
identical IPv6-anycast deferral).

## Lossy paths

- **`/interfaces/interface/vrrp-groups/group`** — VRRP / CARP groups
  normalise to HSRP on render (see above); sub-second timers,
  virtual-MAC, and track objects are not modelled in v1.
- **`/routing/static-route/description`** — render emits destination
  + next-hop + metric only; the static-route name/description drops.
- **`/routing-instances/instance/route-distinguisher`** — `rd auto`
  is preserved verbatim as a sentinel; cross-vendor renderers that
  don't recognise it must synthesise an explicit RD.  An explicit RD
  round-trips losslessly.
- **`/routing-instances/instance/rt-imports`** — `route-target both
  <rt> evpn` preserves the RT value but the L2VPN-EVPN address-family
  discriminator reverts to IPv4-unicast cross-vendor.
- **`/vxlan-vnis/vni`** — per-VNI sub-flags (`suppress-arp`,
  alternate ingress-replication) don't round-trip; the codec emits
  the modern BGP-EVPN head-end-replication shape on every render.
  The VLAN↔VNI binding itself round-trips.
- **`/local-users/user/privilege-level`** — NX-OS named roles map to
  numeric privilege (network-admin / vdc-admin → 15, else → 1) for
  cross-vendor targets; the named role round-trips losslessly
  same-vendor.
- **SNMPv3 `auth-passphrase` / `engine-id`** — the 10.x
  `localizedV2key` digest normalises to the older `localizedkey`
  form, and engineIDs are colon-decimal; cross-vendor / cross-version
  migration requires re-keying the v3 user on the target.
- **`/system/raw-sections/vdc`** and **`…/features`** — N7K VDC
  virtualisation grammar is discarded (a default single-VDC wrapper
  is synthesised on render); `feature <name>` lines are derived on
  render from the canonical-tree shape, so source `feature` lines not
  motivated by a canonical surface (e.g. `feature scp-server`) drop.

## What we don't do

**Management-plane Tier-1/2 surfaces NX-OS render drops** (declared
`unsupported` so the loss is visible, not silent):

- `timezone` (`domain`, DNS, NTP and syslog servers now round-trip —
  promotion #4)
- DHCP server pools
- RADIUS servers (host + shared secret)
- IPv6 anycast-gateway

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Routing protocols** — `router bgp` / `router ospf` / `eigrp` /
  `isis` stanzas (surfaced on the `dropped_tier3_sections` banner;
  not auto-rendered)
- **ACLs** — standard / extended / IPv6 (auto-translating ACL
  semantics across vendors risks shipping subtly-permissive rules)
- **Firewall / NAT** — NX-OS does not host a stateful firewall or
  typical edge NAT
- **QoS** — `class-map type qos` / `policy-map type qos` /
  `service-policy`

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).
Six `batfish/lab-validation` configs (Apache-2.0), all NX-OS 9.2(3),
spanning four scenarios:

- **`batfish_nxos_hsrp_nxos1.txt`** / **`…nxos2.txt`** — HSRP (FHRP)
  HA pair + port-channel LAG
- **`batfish_nxos_evpn_l3vni_nx1.txt`** / **`…nx2.txt`** —
  VXLAN-EVPN symmetric-IRB **L3VNI** + `nve1` VTEP
- **`batfish_nxos_evpn_l2vni_nx1.txt`** — VXLAN-EVPN **L2VNI**
  (`vn-segment`)
- **`batfish_nxos_bgp_redist_d1.txt`** — BGP redistribute-connected
  + VRF

(The high interface counts in these captures reflect batfish's full
chassis dumps — every Ethernet port appears, most unconfigured.)
Operator captures from a **newer NX-OS major** (10.x) and a second
source are the highest-value contributions — see
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## A banner is text

The parser reads a banner, and a scheduler job's commands, as text,
not as lines of the config: each line of it is passed over by every
reader of the parse (the Tier-3 rows and the check for a JSON or XML
paste included), and nothing of it is translated.  Detection still
reads the text as it came.

- **`banner motd` and `banner exec`** in column 0, then the delimiter:
  the first character after the type that is not white space (Cisco:
  "Very first char is delimiter char"; every printout has one space
  there, and Batfish passes over any).  NX-OS prints the delimiter as
  it was typed, and a config carried over an upgrade keeps one that
  10.1(x) no longer takes for a new banner, so any character is one,
  compared by its case.  `banner motd` with nothing after it opens
  nothing, nor does `no banner ...`.
- **Where the body ends**: at the next occurrence of the delimiter,
  anywhere -- on the line that opens it (`banner motd #Welcome to the
  Switch#`, Cisco's own example), in the middle of a later line, or at
  its start; every published printout has it alone on a line.  What
  follows it on its line is discarded: Cisco's NX-API page pairs the
  line `banner exec 123:12` with the message `23:` (the rule that
  pairing needs is inferred from it).  A typed text ends at the
  delimiter's first occurrence, and the printer writes the delimiter
  that was typed, so no stored text holds its own end.
- **`scheduler job name <name>`** runs to a line that is `end-job`, in
  column 0 (an indented `end-job`, or `end-jobs`, is the job's text).
  The job's commands are printed as they were entered -- in column 0
  on 9.2(2), indented on 10.3(3) -- and run when the job runs; they
  are not configuration in force.  (The end line is from published
  `show running-config` files; no Cisco page prints a job.)
- **Refused in words**, naming the line and quoting nothing (`parse
  failed: cisco_nxos: line <n> ...`): a body with no end before the end
  of the text (`opens a block of text ...`; every printout has the
  closer, so the text was cut short; read as it stands, nothing after
  it is configuration), and a line of a body that ends in another
  character than a line feed -- a form feed, a vertical tab, a carriage
  return on its own (`is a line of a banner, or of another block of
  text, and ends in a character ...`): the switch ends a line at a line
  feed, so where it ends the body is not where those lines say.  Paste
  the whole of `show running-config`.

⚠️ Up to 0.7.7 a banner's lines were read as lines of the config: a
banner line `username <name> password ... role network-admin` became
an account with privilege 15 on the target, and its `vlan`,
`interface`, `ip route` and `ip access-list` lines became VLANs,
interfaces, routes and a Tier-3 row, in jobs that said `completed`.
If you translated an NX-OS config with a banner with 0.7.7 or earlier,
translate it again, and look in the old output for accounts,
interfaces, VLANs and routes the switch does not have.

## A config without its indentation

The parser reads a stanza's lines by their indentation: `show running-config`
prints an interface's lines, a VLAN's and a VRF context's indented under it.  A text with NO indentation -- no
line but a comment begins with white space, and a stanza is followed
by a line at the left margin that is no other stanza, no `!` and no
`exit` or `end` -- is refused in words (`parse failed: cisco_nxos: this
text has no indentation. ...`), naming the line of the first such
stanza and quoting nothing of the text.  The parser cannot tell where
a stanza of such a text ends, and a guess would put a line where the
switch does not; what the switch itself makes of such a text is not
established here.  Any white space in front of a line is indentation,
a no-break space included, as the parser's readers take it: a config
copied out of a web page is read.  A text in which only SOME lines
lost their indentation is read by its indentation, each dedented line
as a line of the top level.

An `ip route` after an empty `vrf context` is one such line: typed
after it, it is the VRF's route, and read as a line of the top level
it would be a global one.

⚠️ Up to 0.7.7 such a text was read: every interface address, description and VLAN membership was lost,
and the VLAN names and VNIs, in a job that did not say
so.  If you translated an NX-OS config that had lost its indentation,
translate it again from `show running-config` as the switch prints it.

## Common gotchas

- **One tag per sub-interface.**  The sub-interface statement this
  codec reads and writes is `encapsulation dot1q <id>`, one tag: a
  source's sub-interface of two tags (IOS-XE `second-dot1q`, EOS
  `inner`, Junos `vlan-tags`) is written with its outer tag, and the
  job is `partial`, the validation report listing the inner tag.
- **A trunk's allowed list means what it says.**  A trunk with no
  `switchport trunk allowed vlan` line — a vPC peer link, usually —
  is read as a trunk of EVERY VLAN, the NX-OS default, and reaches
  another vendor as that.  `switchport trunk allowed vlan none`, and
  a list emptied by `remove` or `except`, is a trunk of NO VLAN.
  `add` and `remove` on an interface's first allowed line start from
  every VLAN, and an interface whose stanza is met twice has ONE
  list.  As a target: every VLAN is written as a trunk with no
  allowed line, never as `1-4094` — NX-OS keeps a block of ids for
  itself (3968-4047 unless it is moved) and does not take them in a
  list; no VLAN is `switchport trunk allowed vlan none`; any other
  list is written as ranges.  Release 0.7.7 and earlier had one
  value, an empty list, for a trunk that allows no VLAN and for one
  that states no list: a `none` trunk came out here as a trunk of
  every VLAN, and a peer link reached Junos, OS10 and AOS-S carrying
  none — check trunks translated that way.  A port with a
  `switchport trunk` line and no `switchport mode trunk` line is read
  as a trunk, though an NX-OS port is an access port until it is told
  otherwise.  That is an older fault of the parser.  Such a port is
  given nothing from the default: it is a trunk of the VLANs its
  lines name, or of NO VLAN, never of every VLAN, and it is given
  no default native VLAN either: VLAN 1 on its list is a tagged
  VLAN of it.  The first of its lines decides what it is read as:
  `switchport trunk allowed vlan 1,10,20` followed by `switchport
  access vlan 10` is a trunk that keeps the access VLAN beside its
  list, and the two lines the other way round, or under
  `switchport mode access`, are an access port that keeps the
  list.  Take the trunk lines off an access port before
  translating, or add `switchport mode trunk` to a trunk.  A port
  that says
  `switchport mode trunk` and takes its list from `inherit
  port-profile`, which is not read, is a trunk of every VLAN; so is a
  port-channel member that states the mode and leaves the list to its
  port-channel.  The vendors' own sentences are in the
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
  What Cisco says of it: a trunk with no native line uses the default
  VLAN, and "When you remove VLAN1, all data traffic for VLAN1 on
  this port is blocked, but the control traffic continues to move on
  the port."  For a native VLAN other than 1 there is no sentence of
  Cisco's; that it is not carried either follows from Cisco's
  definition of the allowed list, and is an inference.  As a target,
  an AOS-S port that is untagged in one VLAN and tagged in others,
  and an OS10 trunk with an access VLAN, are written with that VLAN
  on the allowed line beside the native line (`switchport trunk
  native vlan 10`, `switchport trunk allowed vlan 10,20,30`), as
  Cisco's own example on that page does.  Release 0.7.7 and earlier
  left it off the allowed line, in jobs that said `completed`: check
  the allowed list of every trunk with a native line migrated then
  from AOS-S or OS10.  **A trunk that states no native VLAN has
  native VLAN 1.**  Cisco: "If you do not configure a native VLAN
  ID, the trunk port uses the default VLAN.", and on the same
  page: "The default VLAN is VLAN1."  Where the trunk's allowed
  list holds VLAN 1 -- the list names it, or there is no allowed
  line -- a port that says `switchport mode trunk` is read as
  carrying VLAN 1 untagged, and Junos, OS10 and AOS-S are written
  so (`native-vlan-id 1`; `switchport access vlan 1`; `untagged`).
  Release 0.7.7 and earlier wrote VLAN 1 TAGGED on those three, in
  jobs that said nothing: check such trunks migrated then.  Where
  the list leaves VLAN 1 out nothing is filled in, and the trunk is
  read as having no untagged VLAN (Cisco: "When you remove VLAN1,
  all data traffic for VLAN1 on this port is blocked, but the
  control traffic continues to move on the port.").  As a target,
  no `switchport trunk native vlan 1` line is written for a trunk
  whose list holds VLAN 1: it is the default, and no real NX-OS
  capture prints the line.  A port that carries NO VLAN untagged
  at its source and has VLAN 1 on its list (a Junos trunk of `vlan
  members all` with no `native-vlan-id`, say) would have the default
  here if it were written no native line.  The one form Cisco
  documents for it on the Nexus 9000 is `vlan dot1q tag native`,
  and it is the device's: "This configuration is global; trunk ports
  on the device either do or do not retain the tagging for the
  native VLAN."  So it is written, once, before the VLANs, where no
  port the check reads blocks it: no port in trunk mode carries a
  VLAN untagged, and no port is in a mode no mode line is written
  for (dynamic, private-vlan, dot1q-tunnel, fex-fabric and the like)
  or holds trunk lines in no mode.  A port written with no mode and
  no trunk line is not counted; should it become a trunk, the line
  tags its native VLAN as well.  Otherwise
  such a trunk is written no native line under a
  `! review:` line that says so
  ([`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A trunk's allowed
  list is not what I wrote").  Its send half is settled (tagged);
  what it does with an untagged frame it receives, Cisco's pages
  disagree on.  Cisco recommends leaving it off where the connected
  switch does not have it.  **vPC:** Cisco lists "Tagging of native
  VLAN traffic" among the parameters that "must be configured
  identically on both devices of the vPC Peer-Link".  The line is
  decided for one output at a time, so two vPC peers translated
  apart can differ -- one written the line, the other review lines.
  Compare the two peers' outputs.  As a source, `vlan dot1q tag native`
  (with `exclude control` or without) and `switchport trunk native
  vlan tag` are read: a trunk under either carries no VLAN
  untagged, and has no native VLAN in the tree, a stated one
  included; `no switchport trunk native vlan tag` takes a trunk out
  of the line for every trunk.  The VLAN pane's map keeps to that
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
- **HSRP is the FHRP, not VRRP.**  Cross-vendor VRRP / CARP groups
  render as `hsrp` blocks; same-vendor HSRP round-trips cleanly.
- **`nve1` is the VTEP, not a routed port.**  The codec intercepts
  `interface nve1` as the VXLAN tunnel-endpoint container (`tunnel`
  kind), not an L3 interface.
- **Some management services don't carry.**  DHCP / RADIUS / timezone
  are render-dropped on an NX-OS target — re-apply them on the device.
  The validation panel flags each.  (DNS / NTP / syslog / domain now
  round-trip — promotion #4.)
- **`feature` lines are regenerated.**  The renderer derives `feature
  interface-vlan` / `feature lacp` / `feature hsrp` etc. from the
  canonical shape; it does not preserve arbitrary source `feature`
  declarations.
- **Dropping the loopback a VTEP sources from leaves the VTEP naming
  it.**  A translation from NX-OS to NX-OS lists the loopback under
  *Other names in the config* in the rename modal.  Renamed there,
  the output follows.  Dropped, its stanza goes and the VXLAN
  source line still names it; the job records the drop and says
  nothing.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § F.

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
