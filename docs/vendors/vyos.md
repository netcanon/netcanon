# VyOS — What works for me?

If you operate VyOS routers / firewalls (the open-source Vyatta
successor) and want to know what Netcanon does for you, this is the
page.

## TL;DR

- **`vyos`** — `config.boot` (curly-brace) **bidirectional** (parse
  AND render).  **Certification: certified.**

VyOS is Netcanon's 12th codec and its **first curly-brace parser** (a
brace-stack walker, distinct from the `set`-form `juniper_junos`
codec).  The codec targets VyOS 1.3 / 1.4 / 1.5: interfaces with
`vif` VLAN sub-interfaces and DHCP clients, `system login` users, NTP,
`interfaces bonding` LAGs, `service snmp`, VRFs, and `interfaces
vxlan` netdevs.  Routing-protocol + firewall stanzas (`protocols bgp`
/ `protocols ospf` / `firewall`) are surfaced on the migrate banner
via `dropped_tier3_sections`, **not** translated.

> **Input forms.**  Both `config.boot` (curly-brace) and `show
> configuration commands` (set-form) are accepted — set-form is
> converted to curly-brace up front so the brace-stack walker is
> reused.  The probe disambiguates VyOS set-form from the Junos
> set-form that the `juniper_junos` codec owns.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, enabled state, MTU, IPv4 + IPv6
  addresses, `dhcp` / `dhcpv6` client, per-interface VRF binding.
  802.1Q VLANs are `vif <vid>` sub-interfaces, modelled as
  `ethN.<vid>` interfaces (there is **no** top-level VLAN database).
- Static routes — of the global table and of a VRF (`vrf name <X> {
  protocols { static { … } } }`), with administrative `distance`.
  Only the `next-hop <address>` form is read: a route `interface
  <name>`, `blackhole`, `reject` or `dhcp-interface` is not, and
  nothing says so yet — re-create it on the target.  A next hop in
  another VRF, and a next hop held `disable`, are left out and said
  (see the gotchas)
- NTP servers (`system ntp` / `service ntp`, bare + block form)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- Local users — `system login user` (name + `encrypted-password`
  hash; VyOS states no role).  A user with no `authentication` is a
  `review:` line on every target, VyOS included: no target writes an
  account with no password
- LAGs — `interfaces bonding bondN` (members + `lag-member-of`
  back-link).  Members are read as VyOS prints them — one bare
  `interface ethN` line each under `member`, or `member interface
  'ethN'` in the set form — and written the first way; a `vif <vid>`
  under a bond is a unit of the LAG, `bondN.<vid>`, as it is under an
  ethernet port
- SNMP — `service snmp` v1/v2c community + v3 USM (community,
  location, contact, v3 users)
- VRFs — `vrf name <X>` instances + the per-interface binding
  (`interfaces ethernet ethN { vrf X }`)
- VXLAN — `interfaces vxlan vxlanN` netdevs (one VNI per netdev:
  VNI, source, multicast group / flood list, UDP port)

> **Management-plane caveat.**  When VyOS is the **target**, the codec
> renders no `system syslog` / DHCP-server / `radius-server` /
> `time-zone` config — those surfaces are declared `unsupported` (the
> live validation report flags the loss rather than reporting
> `severity: ok`).  **NTP, `system domain-name`, and `system
> name-server` (DNS) ARE translated** (#347).  See
> [What we don't do](#what-we-dont-do).

## Lossy paths

- **`/routing/static-route/description`** — render emits destination +
  next-hop + distance only; the static-route name / description drops.
- **`/lags/lag/mode`** — bonding `mode 802.3ad`, and a bond with no
  `mode` line ("The default is 802.3ad", VyOS), is LACP; a passive
  LACP bundle is written with no `mode` line.  `round-robin`,
  `xor-hash` and `broadcast` are a static aggregate, whose peer groups
  its ports too, and are written `mode xor-hash`; `active-backup`,
  `transmit-load-balance` and `adaptive-load-balance` need nothing of
  their peer and are written `mode active-backup`.  The balancing
  algorithm is not carried — re-select it on the target.  Onto a
  switch, which has no bond that needs nothing of its peer, an
  `active-backup` bond is a static aggregate with a review line beside
  it and a warning in the job.  ⚠️ Up to 0.7.7 a bond with no `mode`
  line was read as a static aggregate, a bond that needs nothing of
  its peer was read as one too, and a static aggregate of another
  vendor was written with no `mode` line — an LACP bond: translate a
  config with a LAG again.
- **`/routing-instances/instance/table`** — VyOS requires a numeric
  `table <id>` on every `vrf name <X>`; the canonical model carries no
  table number, so the codec synthesises a deterministic id
  (`100 + sort-index`) on render.  The original table id is not
  preserved.
- **`/vxlan-vnis/source-interface`** — the VTEP source is
  `source-address <ip>` (or `source-interface <if>`); a cross-vendor
  source (e.g. `Loopback0`) is re-emitted verbatim and may need an
  operator port-rename.
- **`/vxlan-vnis/vlan-id`** — VyOS models one VNI per `vxlan vxlanN`
  netdev with no on-device VLAN (the L2 binding lives on a separate
  `bridge`); the canonical `vlan_id` is synthesised from the VNI and
  the netdev name regenerated `vxlan<index>` on render (deterministic;
  same-vendor round-trip stable, cross-vendor advisory).
- **`/local-users/user/privilege-level`** — VyOS login users have no
  numeric privilege in the common case; the codec reads every login
  user as privilege 15 with no role.  The `encrypted-password` hash
  round-trips verbatim same-vendor; cross-vendor requires re-keying.
- **`/local-users/user/role`** — a local user's role is a name of the
  platform that defines it.  VyOS states no role: every login user on
  VyOS 1.3 to 1.5 has full configuration access and sudo.  An account
  at privilege 15 is written without its role, and one below it is a
  review comment rather than an administrator.
- **SNMPv3 `auth-passphrase` / `engine-id`** — v3 USM keys are opaque
  `encrypted-password` blobs (re-key cross-vendor); VyOS declares a
  single config-wide `engineid`, which the codec maps onto every v3
  user.
- **`/interfaces/interface/dot1q-vlan`** — a routed sub-interface of
  another vendor (`encapsulation dot1Q 200` under
  `GigabitEthernet0/0/1.100`, Junos `unit 100 vlan-id 200`) is a
  `vif` of its TAG under its port: `eth1.200`, `vif 200`.  Its unit
  number is not kept where it is not the tag, and two units of one
  port with one tag are one `vif`, which the job lists as two names
  on one (`partial`).  Only the port translator makes that name;
  without it a sub-interface of another vendor's name is written
  under that name with no tag, beneath a `/* review */` line.
- **`/interfaces/interface/config/type`** — inferred from the name
  shape (`ethN` → ethernetCsmacd, `lo`/`dumN` → softwareLoopback,
  `bondN` → ieee8023adLag); best-effort.
- **`/routing-instances/instance/{description,route-distinguisher,rt-imports,rt-exports}`**
  — VyOS writes a VRF as its name and its table only: its
  description, route distinguisher and route targets are not
  written.
- **`/routing/static-route/interface`** — a route that names an
  interface and no gateway is written as `next-hop <interface>`,
  which is not a next hop VyOS takes (an interface route is
  `interface <name>`): the route is not written as one out of that
  interface.
- **`/snmp/trap-host`** — the codec writes no SNMP trap target: the
  trap hosts are dropped.

The last three are severity `warn`: the job says so and stays
`completed`.

## What we don't do

**Surfaces VyOS render drops** (declared `unsupported` so the loss is
visible, not silent):

- **L2 switchport** — VyOS has no access/trunk model (L2 via
  `bridge` / `vif`); switchport mode / access-VLAN / trunk
  allowed-list / native VLAN / voice-VLAN all drop on render
- **Management plane** — `timezone`, syslog servers, DHCP server
  pools, RADIUS servers (host + secret).  *(NTP, `domain`, and DNS
  name-servers ARE supported — #347.)*
- **Top-level VLAN database** — VyOS has none; 802.1Q VLANs are `vif`
  sub-interfaces (which ARE supported).  Nothing held on a VLAN
  record is written as a VLAN's: neither its name, its description,
  its port lists nor its address
- **First-hop redundancy** — no VRRP group is written, so neither
  are its virtual IPs, its tracked interfaces or its virtual MAC
- **VXLAN control plane** — per-VNI EVPN RD/RT and symmetric-IRB
  **L3VNI**; the L2 VLAN↔VNI binding itself IS supported

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Routing protocols** — `protocols bgp` / `protocols ospf`
  (surfaced on the `dropped_tier3_sections` banner; not auto-rendered)
- **Firewall** — `firewall` rule-sets (auto-translating firewall
  policy across vendors risks subtly-permissive rules)
- **NAT** — `nat source` / `nat destination`
- **Policy** — `policy` route-maps / prefix-lists

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).
Ten real `config.boot` files from **four sources**, spanning three
VyOS majors (1.3 / 1.4 / 1.5):

- **`cisagov/prescup-challenges`** (6 configs, MIT (SEI), VyOS
  1.4-rolling) — round-1 IPv4 / OSPF border + core (`pc5-round1-*`)
  and round-3b IPv6 / BGP routers (`pc5-round3b-*`, AS65001-65005;
  the `routere` capture is a dense 8-interface / 8-neighbor box)
- **`zhouleyan/wcni-kind`** (2 configs, Apache-2.0, VyOS 1.4-rolling)
  — `wcni-kind-gw0/gw1`, the two ends of one `vni 10` VXLAN tunnel
- **`scottlaird/vyos-parser`** (Apache-2.0, VyOS **1.5**) —
  `service snmp` (`community public`); 5 block-form NTP
- **`rapid7/metasploit-framework`** (BSD-3, VyOS **1.3**) — `service
  snmp` (`community ro` / `write`)

The round-tripping surface is interfaces + hostname + local-users +
NTP (bare + block form) + `interfaces vxlan` + `service snmp`;
OSPF / BGP / firewall are Tier-3.  **Honest scope:** only **VRF**
round-trip remains validated by the synthetic kitchen-sink alone — a
2026-06 hunt found no permissive + curly-brace real capture carrying
`vrf name` (only GPL `vyos-1x` smoketests or unlicensed configs), so
VRF stays synthetic-validated.  A permissive real `vrf name` (and a
real set-form) capture are welcomed via
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## Common gotchas

- **A route of a VRF is in its VRF, both ways.**  VyOS writes a
  route of a VRF under the VRF (`set vrf name <name> protocols static
  ...`, VyOS, "VRF"), and it is read from there and written there,
  a route of another vendor's VRF included.  A VRF that a route names
  and no instance declares — OS10 `management`, AOS-CX `mgmt` — is
  written after the declared VRFs, with a table id of its own; every
  VRF's table id is synthesised (`100` up), so set the ones the
  device needs.  ⚠️ Up to 0.7.7 a route under `vrf name <X>` was read
  as a route of the global table, onto every target VyOS included, in
  a job that said `completed`, and VyOS as a target wrote every route
  into its global table: re-check the routes of a VRF on a device
  migrated from or onto VyOS with an earlier release.
- **A next hop in another VRF, or held `disable`, is left out and
  said.**  `next-hop <address> vrf <name>` looks the next hop up in
  another VRF (as the route-leaking and NAT examples of VyOS's "VRF"
  page write it; `vrf default` is the global table), which the tree
  has no form for: the route is left out, and one `protocols
  static:` row of the Tier-3 banner counts such routes.  A next hop that names the route's own
  table is read as the route.  `next-hop <address> disable` ("Disable
  the route via the specified next-hop IP address", VyOS, "Static")
  installs nothing, and is left out with a `disabled:` row that names
  it.
- **A user or community whose NAME holds white space is left out as
  a target.**  `user <name> {` and `community <name> {` are tag
  nodes, one word, so such a record is left out with a `/* review */`
  line that names it.  A password or SNMPv3 passphrase that holds a
  space is written in quotes; one that holds a `"` is left out, since
  VyOS refuses an embedded quote even escaped (vyos.dev/T1246) and a
  secret with its quote replaced is another secret.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § C.
- **A host name or VRF name that holds white space or a `"` is
  written with `_` and `'` as a target**, the VRF at every place it is
  named, with a `review:` line.  A `"` in a description or the SNMP
  location or contact is written `'` (VyOS refuses one even escaped).
  An NTP or DNS server, the domain or a route's gateway that holds
  either is left out and said, the route whole.
- **A review comment shows `*/` in a name as `* /`.**  VyOS ends a
  `/* */` comment at its first `*/`, so a name that held one (a source
  account left out for its password) would have ended the comment, and
  what followed was configuration.  The name in the comment is the
  source's name with that one change.
- **QinQ (`vif-s`) is not translated.**  A `vif-s <id>` block is a
  service VLAN whose tag is 802.1ad, Ethertype 0x88a8 by default
  (VyOS, "QinQ (802.1ad)"), and its `vif-c <id>` blocks the
  sub-interfaces inside it; the tree has no form for an 802.1ad tag.
  The block is left out, with a row of the Tier-3 banner (`interfaces
  ethernet eth0 vif-s 1000: an 802.1ad service VLAN; it and its vif-c
  sub-interfaces are not translated`).  ⚠️ Up to 0.7.7 it went with
  nothing said.  A source's sub-interface of two 802.1Q tags (IOS-XE
  `second-dot1q`, EOS `inner`, Junos `vlan-tags`) has no form here
  either: the job is `partial`.  A `vif 0` is left out with its
  addresses, and a row names it (`interfaces ethernet eth0: vif 0 --
  not one 802.1Q tag and at most one inner tag, so the sub-interface
  is not translated`): VID 0 is a priority tag and no VLAN (IEEE
  802.1Q).  ⚠️ Up to 0.7.7 it was a sub-interface of tag 0 on
  every target that writes a tag.
- **VLANs are `vif` sub-interfaces.**  There is no VLAN database — a
  tagged VLAN is `interfaces ethernet ethN vif <vid>`, modelled as an
  `ethN.<vid>` interface.  A switch-source's per-port VLAN membership
  drops (declared `unsupported`).  Onto another vendor a `vif` goes
  where its port goes, with its number (`Ethernet1.54`).  ⚠️ Up to
  0.7.7 a `vif` was written onto its parent port — and a translation
  from VyOS to VyOS lost it with its addresses; translate such a
  config again.  ⚠️ Up to 0.7.7 a `vif` under a **bond** was not
  read at all, and a bond printed in the block form had no members:
  translate a config with a bond again too.
- **Onto VyOS a sub-interface is named by its tag.**  `vif 200` is
  VLAN 200 whatever the source called the unit, so a Junos `unit
  100 vlan-id 200` is `eth1.200`.  An entry in `port_rename_map`
  that names such a unit `eth1.100` gives it VLAN 100: the job warns
  and the output has a `/* review */` line before the `vif`.  A
  Q-in-Q unit is a `vif` of its outer tag, its inner tag listed as a
  loss, so the units of one service VLAN on a port are one name, which
  the job lists.  ⚠️ Up to 0.7.7 every such unit was written with its
  unit number, a VLAN it is not tagged with; translate such a config
  again.
- **`protocols bgp` / `protocols ospf` are SHARED with Junos.**  Both
  VyOS and Junos use `set protocols …` — the probe disambiguates by
  config shape, not by that keyword alone.  Pick the right vendor in
  the target dropdown if detection is ambiguous.
- **Curly-brace vs set-form.**  Either input works — `config.boot`
  (curly-brace) is the native form; `show configuration commands`
  (set-form) is converted up front.  Distinct from the `juniper_junos`
  codec, which owns the Junos set-form.
- **A node with nothing under it is printed on one line.**  VyOS
  writes `server time1.vyos.net { }`, `loopback lo { }` or `disable
  { }` for a node that holds nothing; such a line is read as a block
  that opens and closes (`disable { }` as the leaf `disable`), the
  reading the set form gives the same path.  ⚠️ Up to 0.7.7 it was
  read as a word with ` { }` in it: an NTP server's name came out with
  its braces, and an empty loopback, `vif` or `next-hop` was lost;
  translate such a config again.
- **A set line nested more than 64 levels deep is a parse failure.**
  A real path is a dozen words.  Set-form input is written out as
  nested blocks before it is read, each level indented once more, so
  what a line becomes grows with the square of its depth; the
  characters of those blocks are held to the server's config size
  limit (`text`).  See [`../CAPABILITIES.md`](../CAPABILITIES.md) § H.
- **VRF table ids are synthesised.**  Render emits a deterministic
  `table <id>` per VRF (`100 + sort-index`); the source table id is
  not preserved.

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
