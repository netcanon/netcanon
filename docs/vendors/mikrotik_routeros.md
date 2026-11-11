# MikroTik RouterOS — What works for me?

If you operate MikroTik RouterOS devices and want to know what
Netcanon does for you, this is the page.

## TL;DR

- **`mikrotik_routeros`** — RouterOS `/path` slash-prefixed CLI
  export (`/export verbose` output) parse + render.
  **Certification: certified.**  Bidirectional.

The codec covers RouterOS 6.48.x and 7.18+ across home-router (RB952),
provisioning-script, and CRS310 + Proxmox-cluster fixtures.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname` (`/system identity`)
- Interfaces — physical (`ether<N>`, `sfp<N>`, `combo<N>`,
  `sfp-sfpplus<N>`, `sfp28-<N>`, `qsfp28-<N>-<lane>`), bridge
  (`/interface bridge`), VLAN (`/interface vlan` named e.g.
  `gn-mgmt`, with its `mtu`; ⚠️ not written or read up to 0.7.7);
  IPv4 (`/ip address`), IPv6 (`/ipv6 address`).  RouterOS has one
  MTU: another vendor's IP MTU of its own is written as `mtu` where
  no other MTU is stated, and is lost where one is (the job's
  report says so).  A sub-interface of another vendor (IOS-XE
  `GigabitEthernet1/0/2.10` with `encapsulation dot1Q 10`, Junos
  `unit 10 vlan-id 10`) is a VLAN interface on its port: `/interface
  vlan add interface=ether2 name=ether2.10 vlan-id=10`, and is read
  back as a sub-interface of the port.  A sub-interface you name
  with no port in it (`wan10`) rides on the parent chosen for every
  VLAN, under a `# review:` line: move it to its port.  A
  sub-interface of two tags (IOS-XE `second-dot1q`, EOS `inner`,
  Junos `vlan-tags`) is a VLAN interface on the VLAN interface of
  its port with its outer tag -- "In RouterOS, Q-in-Q can be
  configured by adding one VLAN interface over another" (MikroTik,
  "VLAN") -- and where the source has none for that tag, one is
  made, `<port>.<outer>`, under a comment that says so.  ⚠️ Up to
  0.7.7 such a sub-interface got no line, and its address named an
  interface the output did not define.  A VLAN interface read FROM
  RouterOS is a sub-interface where it rides on a port (a port an
  `/interface ethernet` line names, or one whose name says it is a
  port) or on a bond: onto another vendor it goes where its port
  goes, named by its tag whatever you named it (`gn-mgmt` on
  `ether3`, VLAN 11, is EOS `Ethernet3.11`).  A VLAN interface on
  such a sub-interface is a second tag: a sub-interface of the port
  with two 802.1Q tags, which reaches IOS-XE, IOS XR, EOS and Junos
  named by its inner tag.  ⚠️ Up to 0.7.7 it was read as a VLAN
  interface of one tag, its inner tag, in jobs that said nothing.
  One that says `use-service-tag=yes` on a port, a bond or a VLAN
  interface is an 802.1ad tag, and one on a VLAN interface that is
  not one 802.1Q tag on a port (a bridge's VLAN interface, a third
  tag) has no form in the tree: each is left out, with its
  addresses, and a row of the Tier-3 banner names it (a route or a
  DHCP server that names it keeps the name, which is then defined by
  nothing in the output).  On a
  bridge it is a VLAN interface and a VLAN.  A VLAN interface whose
  `vlan-id=` is no VLAN id (0, 4095, or nothing after the `=`) is
  left out the same way, with a VLAN interface on it: ⚠️ up to 0.7.7
  such a `vlan-id=` refused the whole config.  One that states no
  `vlan-id=` at all is VLAN 1, MikroTik's default ("vlan-id (integer:
  1..4094; Default: 1)", "VLAN"), which an export leaves out: ⚠️ up
  to 0.7.7 such a line was passed over, and its addresses were
  written on a name the output defined nowhere.  AOS-S, AOS-CX, OS10 and IOS-XE NETCONF
  have no form for a sub-interface's tag, and a job onto them is
  `partial` for it.  ⚠️ Up to 0.7.7 every one was a VLAN interface
  and a VLAN, which no port carried on the target.  Another
  platform's VLAN (`vlan 10` with tagged ports) is an `/interface
  vlan` too: on the one port or bond with an address or a trunk,
  where the config has exactly one, and otherwise on a bridge
  (`bridge1` where the config has none).  It is read back as a VLAN
  only on a bridge: on a port or a bond it is a
  sub-interface of it, its tag the VLAN's id, with no VLAN record
  (`/vlans/vlan/id` is lossy).
- Tunnels — `/interface gre`, `/interface eoip`, `/interface ipip`:
  name, comment and `mtu`.  The endpoints are not translated: they
  come out as `remote-address=0.0.0.0`, for you to fill in.
  ⚠️ Up to 0.7.7 a tunnel's MTU was not written or read.
- VLANs — `/interface bridge port` with vlan-id mappings + tagged
  / untagged port assignment
- Static routes (`/ip route`)
- LAGs (`/interface bonding`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP — `/snmp community` (RouterOS overloads its `/snmp community`
  section for both v1/v2c and v3 — community + auth-protocol +
  auth-password + encryption-protocol + encryption-password)
- RADIUS — `/radius`
- Local users — `/user`.  An export prints no passwords, so as a
  source every user of an export is a `review:` line on every target,
  RouterOS included (no target writes an account with no password;
  RouterOS gives one an empty password): add each on the device with
  a password.  A `password=` on an `add` line (a config written by
  hand, or Netcanon's own output) is the password as typed, and goes
  to every target that takes a typed password; Junos and OPNsense
  take only a hash, and leave the account out under a `review:` line.
  ⚠️ Up to 0.7.7 it was read as no password, so such a user was a
  `review:` line on every target, RouterOS included
- DHCP server pools — `/ip dhcp-server` + `/ip pool` + `/ip
  dhcp-server network`.  A pool of the tree is an enabled server that
  serves clients of its own (no `relay=`, or `relay=0.0.0.0`): its
  interface, its lease time, the range of its `address-pool=`, and
  the gateway, DNS servers and domain of the first `/ip dhcp-server
  network` that holds the start of that range.  Two servers of one
  pool are two pools.  A server that states no `lease-time=` has
  RouterOS's default, 30m (MikroTik's CLI reference of `/ip
  dhcp-server`); from an export that does not say it is of RouterOS
  7 that is also a row of the sections not translated, since the
  default of the source's release is not established.  What is not
  translated is a row of those sections, which names the server, the
  pool or the network: a server of static leases only
  (`address-pool=static-only`, or none), one of the requests a relay
  sends, one whose `address-pool=` names no pool or a pool with no
  range the parser reads, a `lease-time=` in a form it does not read
  (read as 30m), a pool's `next-pool=`, a pool no server takes (a pool
  can be PPP's, a hotspot's or IPsec's), and a network no server
  uses.  A server of `disabled=yes` is not in force: it is left out
  and said.  Static leases (`/ip dhcp-server lease`), `/ip dhcp-server
  option` and the keys the tree has no place for (`ntp-server=`,
  `next-server=`, `dhcp-option=` and the like) are not translated,
  and nothing says so yet.  ⚠️ Up to 0.7.7 a pool was made of each
  network and each pool whether or not a server served it, with no
  interface and a lease of one day.  Onto RouterOS each pool is an
  `/ip pool` (`dhcp_pool<N>`), an `/ip dhcp-server` (`dhcp<N>`,
  `disabled=no`, on the pool's interface, with its lease time) and an
  `/ip dhcp-server network`.  A server runs on an interface
  ("(mandatory)", in that reference), so a pool on no interface -- an
  AOS-S or IOS-XE pool kept for clients a relay forwards, a Junos pool
  no `dhcp-local-server` group binds -- has a `# review:` line in
  place of its server, and serves nothing until one is added; read
  back, it is no pool.  A lease that does not end is written with no
  `lease-time=` (RouterOS states no such lease), and a pool that
  states a gateway, DNS servers or a domain and no network is written
  without them (they are given from an `/ip dhcp-server network`,
  whose `address` is the network): each under a `# review:` line.
  ⚠️ Up to 0.7.7 no `/ip dhcp-server` was written, so no pool was
  served on the target.  The
  tree holds one run of a pool: of a `ranges=` that states several
  (`10.0.0.10-10.0.0.20,10.0.0.100-10.0.0.200`) the largest is kept
  (the lower of two as large), and the others are a row of the
  sections not translated; so is a piece in a form the parser does
  not read (it reads `<from>-<to>`).  ⚠️ Up to 0.7.7 the first run
  was kept and the others dropped, silently.  Onto RouterOS,
  `ranges` is mandatory (MikroTik's manual, `/ip pool`), so a pool
  the source states no range for -- a Junos or IOS-XE pool with no
  range hands out every host of its network -- or one end of one is
  written `ranges=` its network's hosts, less the addresses the
  output gives its own interfaces, a run each side of one that falls
  inside; one that can be given no range (no network, a range
  outside its network, no address left) is a `# review:` line in
  place of its `add`.  Each is also a warning of the job.  ⚠️ Up to
  0.7.7 such a pool was left out of `/ip pool`, and nothing said so
- **Renamed-port preservation** — RouterOS lets operators rename
  `ether2` to "Access Point" etc.; Netcanon preserves the renamed
  name + the factory `default-name` so render emits
  `set [ find default-name=ether2 ] ...` lookup syntax (intra-vendor
  round-trip preservation; not a cross-vendor translation surface)
- Wireless config — `/interface wireless` (parse-tolerant; carry-
  through for cross-vendor scenarios where wireless isn't shared)

## L3 redundancy: VRRP (no anycast)

**New in v0.2.0** (Wave B — classic VRRP wire-up).

RouterOS models VRRP as a top-level pseudo-interface declared in
`/interface vrrp`, with the virtual IP bound via a separate
`/ip address` line that references the synthetic pseudo-name.  The
codec does a two-stage cross-reference: parse walks both sections
and stitches the VIP onto the parent interface; render emits the
two-stage structure with a deterministic `vrrp<vrid>` pseudo-name.

### Grammar

```text
/interface vrrp
add interface=ether1 name=vrrp10 vrid=10 priority=110 \
    preemption-mode=yes interval=3s \
    authentication=ah password=hmackey
/ip address
add address=10.0.10.254/24 interface=vrrp10
```

Keywords handled (on `/interface vrrp add ...`): `interface=` (the
parent — the group lands here, NOT on the pseudo-name), `vrid`,
`priority`, `preemption-mode=yes|no`, `interval=Ns` (the trailing
`s` time-unit suffix is stripped), `v3-protocol=ipv4|ipv6` (an IPv6
discriminator — when `ipv6`, the cross-referenced `/ipv6 address`
populates `virtual_ipv6s`), `authentication=simple|ah` +
`password=<token>` (merged into `<scheme>:<token>` canonical form).

The pseudo-name (`vrrp10`) is NOT materialised as a
`CanonicalInterface` — the v0.2.0 schema models the group as a
property of the parent.  Pre-walk ordering is tolerant: `/ip address`
can appear BEFORE `/interface vrrp` in the source.

### Known limitations

- **No description / track surface.**  RouterOS `/interface vrrp`
  has no description field and no native interface-track grammar
  (priority adjustments come from `on-master` / `on-backup` scripts).
  Canonical `description` and `track_interfaces` round-trip empty
  when RouterOS is the target, and nothing in the output says so.
  No virtual MAC is written either.  The capability matrix declares
  the three `lossy` (severity `warn`), so the job says so.
- **`on-master` / `on-backup` scripts are Tier-3** and drop with
  a review comment.
- **No anycast-gateway grammar.**  All three anycast canonical
  paths (`virtual-gateway-address` v4/v6, `anycast-gateway-mac`)
  are declared `unsupported` — RouterOS targets a SOHO / SMB
  router niche without fabric-anycast primitives.
- **HSRP / CARP / anycast modes** on incoming canonical records
  (e.g. cross-vendor migration FROM an NX-OS HSRP or OPNsense
  CARP source) surface as `# review:` comments on render instead of
  silently dropping; the group itself is not written, and is
  declared `lossy`.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model; see `02-per-vendor-grammar.md` §
  "MikroTik RouterOS" for the pseudo-interface cross-reference
  pattern.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (RouterOS out of scope; SOHO/SMB
  platform without fabric grammar).

## Lossy paths

- **`/local-users/user/role`** — a local user's role is a name of the
  platform that defines it.  RouterOS writes `group=full` at privilege
  15, `group=write` from 10 to 14 and `group=read` below 10, chosen
  from the privilege level from any source, a RouterOS one included: a
  custom group is read as privilege 1 and written `read`.
- **Tunnels** — `/interface gre`, `/interface eoip`,
  `/interface ipip`.  The canonical model holds no tunnel endpoints,
  so a tunnel is written with a placeholder `remote-address=0.0.0.0`
  (with a `review:` comment when it has no description of its own);
  set `local-address` / `remote-address` before it carries anything.
  A tunnel that is shut on the source is written `disabled=yes`
  (MikroTik's GRE and EoIP pages list the property; for IPIP it is
  inferred from the `X - disabled` flag that page prints).
- **`/queue tree`** — QoS queue tree carry-through; cross-vendor QoS
  translation doesn't share semantics, so this drops on cross-
  vendor render (intra-MikroTik round-trip preserves it).
- **`/interfaces/interface/dhcp-client`** — RouterOS keeps a DHCP
  client in `/ip dhcp-client`, which the codec neither reads nor
  writes: the interface is written without one (severity `warn`).
- **No VRF is written.**  `/routing-instances/instance` is
  `unsupported`, and so is each field of a VRF and each interface's
  VRF: no interface is placed in one.
- See per-codec `CapabilityMatrix.lossy` declarations.

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall** — `/ip firewall filter`, `/ip firewall mangle`,
  `/ip firewall raw`
- **NAT** — `/ip firewall nat`
- **VPN** — `/ip ipsec`, `/interface ovpn-server`,
  `/interface l2tp-server`, `/interface sstp-server`,
  `/interface wireguard`
- **QoS** — `/queue simple`, `/queue tree` (carry-through only;
  not translated across vendors)
- **Routing protocols** — `/routing bgp`, `/routing ospf`,
  `/routing rip`
- **MPLS** — `/mpls`
- **PKI** — `/certificate`

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`ntc_ip_address_export.rsc`** — RouterOS 6.48.6 `/export verbose`
  snippet from the networktocode/ntc-templates corpus (Apache-2.0)
- **`routeros_diff_verbose_export.rsc`** — RouterOS 6.48.1
  `/export verbose` from RB952Ui-5ac2nD home router ("Quinta
  Router") with bridge / VLAN (gn-mgmt) / DHCP / queue tree
  (MIT, adamcharnock/routeros-diff)
- **`taqavi_initial_provisioning.rsc`** — provisioning script
  (not a `/export` capture — a script an admin runs to provision
  an L009UiGS-2HaxD), bridge port + ip service + DHCP +
  WireGuard + firewall (MIT)
- **`user_contrib_crs310_ros7.rsc`** — operator-contributed
  CRS310-8G+2S+ on RouterOS 7.18.2 (630 lines; renamed
  ethernet-port fleet "Desktop" / "Access Point" / "CLUSTER -
  PVE3/5/NAS" / "PROD - PVE3/5/NAS" / "UPLINKSFP", 5 VLANs
  cluster/IOT/mgmt/server/user, BGP template stub, IPv6 ND,
  l2tp-server, sstp-server, MPLS, system clock + leds + watchdog)

Spans RouterOS 6.48.1, 6.48.6, and 7.18.2 — three OS versions.

## Common gotchas

- **A value is written as one string where it holds anything but
  letters, digits and `- . _ / : , %`** — white space, `;`, `$`, a
  bracket, a quote.  RouterOS reads an imported `.rsc` as a script:
  outside a string white space parts two words, `;` ends the command
  and `$` and the brackets substitute a variable or run a command, and
  inside a string `$` still substitutes, so it is escaped there (`\$`),
  as an export escapes it.  ⚠️ Up to 0.7.7 the renderer escaped only
  `\` and `"` and wrote most values bare: a description
  `$[/system reset-configuration]` from any source was that command on
  the router that imported the output, and a value with a space or a
  `;` in it was cut there or ran on as another command.  Read an older
  output for `$`, `;`, `[` and `(` before it reaches a router.  The
  parser reads a string back whole.
- **A string's escapes are read by MikroTik's table.**  `\_` is a
  space, `\t` a tab, `\n`, `\r`, `\v` and `\f` line breaks (each
  written as a space onto any target, and said in the job), and a
  run of hex escapes (`\C3\A9`) the text its bytes are in UTF-8.  The
  page gives `\f` as "form feed (0xFF)"; it is read as the form
  feed.  RouterOS keeps a string as bytes and an export does not say
  their encoding, so a run that is not UTF-8 -- a comment typed in
  Windows-1251 -- is kept as written: the target is given the
  escape's text, and so is RouterOS, where the string then holds a
  backslash and two digits in place of the byte.  `\a` (bell), `\b`
  (backspace) and a control character's byte (`\1B`) are read as the
  character, which no target is given: each run is written as a
  space, and said in the job.  ⚠️ Up to 0.7.7 a
  backslash took the character after it whatever it was, so
  `Caf\C3\A9` reached the target as `CafC3A9` and `\n` as `n`.
- **A user whose password cannot be carried is left out** as a target,
  with a `# ... review:` line in its place.  ⚠️ Up to 0.7.7 the `/user
  add group=... name=...` line stayed without its password, and
  RouterOS gives such a user a blank one; read old outputs for an
  `add` after a `review:` line.
- **A bridge's tag type is not read.**  A VLAN interface on a
  bridge that says `use-service-tag=yes` -- the VLAN of a bridge
  whose `ether-type` is 802.1ad -- is read as the bridge's VLAN
  interface, and its VLAN as an 802.1Q VLAN on every target.
- **VLAN interfaces, bridges and names of your own, onto another
  vendor** — the port translator reads the names RouterOS gives a
  port or a bond (`ether2`, `sfp-sfpplus1`, `bonding1`).  A VLAN
  interface, a named bridge or a port an operator named (`vlan10`,
  `bridge-lan`, `eth3_vlan1`) it does not read, and leaves under
  that name on the target.  With no
  devices declared such a job is `partial` and lists each in
  `untranslated_ports` until an entry of `port_rename_map` gives it
  the target's name — also where the name happens to read as one
  of the target's (`vlan100` onto OS10): a RouterOS name is
  whatever was typed, and `vlan100` may carry VLAN 20.  A bridge
  it does read (`bridge`, `br-lan`) is RouterOS's own, and no other
  vendor has a form for it: it is dropped with what is on it -- the
  LAN address of the default configuration included -- and listed
  in `unresolved_ports`; an entry that names the target's interface
  for the LAN keeps it.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § D1.
- **Renaming or dropping a VLAN interface in the rename modal is
  not shown by the output.**  A translation from RouterOS to
  RouterOS lists each under *Other names in the config*.  RouterOS
  output writes a VLAN interface from the VLAN itself: renamed, the
  interface is written under the new name — with the number in that
  name as its `vlan-id` — and the old one again; dropped, it comes
  back; and one with a name of its own (`clustervlan100`) can come
  back as `vlan<id>`.  The job records the entry and says nothing.
  Edit the output.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § F.
- **Renamed ports** — operators commonly rename `ether2` to
  meaningful names like "Access Point" or "PROD - PVE3"; the
  parser captures both `name` and `default-name`, and the renderer
  emits `set [ find default-name=X ] ...` lookup syntax so the
  config remains valid even if port enumeration changes between
  device replacements.  An entry of `port_rename_map` gives a port a
  NAME: `{"ether1": "WAN"}` renders
  `set [ find default-name=ether1 ] name=WAN`, and the port is still
  found by the factory name it had: a `set [ find default-name= ]`
  line's, or the port's own name where that is one a MikroTik device
  gives a port — `etherN`, `sfpN`, `comboN`, `sfp-sfpplusN`, `sfp28-N`, and the
  QSFP lanes `qsfpplusN-L`, `qsfp28-N-L`, `qsfp56-N-L` and
  `qsfp56-dd-N-L`, whole and in lower case, as MikroTik's
  manual and exports show them.  So an SFP port the export mentions
  only in `/ip address` is found too.  A name of yours
  (`ether1_ADMIN`, `Ether1`) is not one, and a port known only by
  such a name, with no `set [ find default-name= ]` line for it, has
  none recorded: naming it renders `set [ find name=WAN ]`, a lookup
  by the new name that matches no port, unless both device models
  are declared (below).  RouterOS names are free text in their own
  letter case, so `SFP-SFPPLUS1` is not read as a port: onto another
  vendor the job lists it as a name the translator could not read.
  The key of an entry is the name the config uses for the port —
  yours, where you gave one; without devices declared an entry keyed
  by the factory name of a port you named matches nothing and is
  ignored with a warning.  Onto another vendor with no devices
  declared, a port you named is translated only by an entry: the
  translator reads a RouterOS port by the shape of its name, a name
  of your own has none, and the port's factory name is not used to
  place it.  The job lists such a port (`untranslated_ports`) and is
  `partial` until an entry decides it.
- **Moving a port onto other hardware needs both device models
  declared** (the *Source device* and *Target device* rows of the
  Interface rename modal; on the API, `source_profile` /
  `target_profile`).  Then every
  port the mapping places that the config has an interface for is
  looked up by the port of the target it is on — also when the config
  came from another vendor, or stated no factory name for the port —
  and a name you gave it is kept, unless that name is itself a port
  of the target; an
  entry whose target is a port of the declared target moves the port
  there, and one whose target is not names it (the plan says so in a
  line).  Nothing else can tell a move from a name: `sfp1` is a port
  of some RouterOS models and not of others.  Onto another vendor a
  port you named takes the name of the port it was paired with.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § G.
- **A port named like a VLAN, a bridge, a LAG or a loopback**
  (`bond1`, `bridge-uplink`, `vlan10`, `lo0`) gets no Ethernet line
  in the output: the renderer goes by the shape of the name.  With
  both devices declared the plan lists such a port (`unbound_ports`)
  and the job is `partial`; without, nothing is reported.  Give the
  port another name.
- **`lo` is RouterOS's own loopback, from 7.14.**  Every router of
  7.14 or later has an interface `lo` that cannot be removed, and no
  interface can be added under its name.  So the renderer writes no
  line for a `lo` and puts its addresses on it, and a loopback from
  another vendor (an IOS `Loopback0`, a Junos `lo0`, a VyOS `lo`) is
  the empty bridge `loopback<N>`, which loads on 6 and on 7.  What no
  line can say of `lo` -- its description, that it is disabled -- is
  a `# review:` line and a warning, and the addresses of a `lo` the
  source holds disabled are left out rather than put into service.  A
  bridge a config names `lo` (a RouterOS 6 config can have one) is
  written as a bridge.  RouterOS 6 has no `lo`, so an output with
  addresses on it -- from a RouterOS 7 config -- needs a bridge of
  that name before a 6.x router takes it.  An output of 0.7.7 or
  earlier has `add name=lo` under `/interface bridge`, which 7.14 and
  later refuses: see
  [TROUBLESHOOTING](../TROUBLESHOOTING.md#routeros-refuses-interface-bridge-add-namelo).
- **A port numbered 0 at the source is written as port 1 here.**
  RouterOS counts a port from 1 (with no configuration of its own a
  router puts its address "on ether1, or combo1, or sfp1", in
  MikroTik's Default configurations).  With no devices declared, a
  VyOS `eth0`, an OPNsense `igb0` and a Junos `ge-0/0/0` are
  `ether1`, an OPNsense `ixl0` and a Junos `xe-0/0/0`
  `sfp-sfpplus1`, and `bond0` and `ae0` `bond1`.  Beside the same
  port numbered 1 that is one name: the job is `partial` and lists
  both, and an entry in the port map settles it.  A port of a Junos
  FPC 0 or 1 is written by its port number alone, so `ge-0/0/3` and
  `ge-1/0/3` are both `ether3`, listed the same way.  ⚠️ Up to 0.7.7
  a port 0 was written `ether0` or `sfp-sfpplus0`, a port no router
  has, in a job that said `completed`.  Look for them in an old
  output.
- **A port a config from another vendor names only as a LAG member
  or in a route** (an IOS route's interface that no stanza configures)
  has no interface of its own, and so no line of its own in the
  output.  The name the mapping gives it — the target port's — needs
  none.  A name YOU give it in `port_rename_map` is written into
  `slaves=` or `gateway=` and defined nowhere; with both devices
  declared the plan lists a port the mapping PLACED (`unbound_ports`)
  and the job is `partial`.  Give such a port a port of the target,
  not a name.  A port with no place that you keep under a name is
  written the same way, and is said in a line of the plan, not in
  `unbound_ports`.  (A comma parts two names in either list, and an
  `@` or a `%` a next hop, so a name that holds one is pieces there;
  with both devices declared a placed port under such a name is
  listed in `unbound_ports`, whether or not it has a line of its
  own.)
- **`gateway=<interface>` routes** follow the interface when it is
  renamed, and are removed with it when it is dropped.  A list of
  gateways (`gateway=ether1,ether2`) and a routing-table suffix
  (`ether3@main`) are left as written.  A gateway that is one name
  and not an address is read as the route's interface, the form
  RouterOS output is written in for a route out of an interface.
  ⚠️ Up to 0.7.7 it was read as the route's gateway: onto a target
  whose matrix declares a route out of an interface lost (AOS-S,
  which writes none), the job said `completed`; Junos wrote the name
  as a next hop, and FortiOS as a gateway address.
- **A VLAN interface's parent** (`/interface vlan add
  interface=bridge name=mgmtvlan11 vlan-id=11`) is kept, and onto
  RouterOS the VLAN is written on it again.  An entry of
  `port_rename_map` for the parent moves its VLANs with it; an entry
  that drops it is said in the job's warnings, and the renderer then
  chooses a parent for the VLAN as below.  Onto FortiOS and OPNsense
  the parent is carried, and a FortiGate VLAN or an OPNsense VLAN
  device comes with its own.  Onto any other vendor it is not — no other codec writes a VLAN interface on a
  parent the config names — and nothing reports it.  From any other
  vendor every VLAN interface of a RouterOS output is on ONE parent
  the renderer chooses: the config's one port with an address or an
  allowed list, or a `bridge1` it adds where there is not exactly
  one.
- **A VLAN's `comment=` is its label.**  RouterOS names a VLAN after
  its `/interface vlan` (`vlan10`, `clustervlan100`), and the parser
  reads the `comment=` as the description of the VLAN and of the
  interface.  Onto IOS-XE CLI, NX-OS, EOS, AOS-S and Junos, which
  write one label for a VLAN, the comment is written as the VLAN's
  name (`name Cluster`; spaces become `_` on EOS, and Junos quotes a
  name that has one); a VLAN with no comment is named after its
  interface.  The comment is also the VLAN interface's description,
  and a target that writes that interface writes it there (FortiOS
  as its `alias`).  Onto RouterOS another platform's VLAN label (an
  IOS-XE `name`, an OPNsense `<descr>`) is the `comment=` of the
  VLAN's `/interface vlan` where that interface states no
  description of its own; where it states one, the comment is the
  interface's description and the label is in a `# review:` line
  above it.
- **6.x vs 7.x grammar drift** — RouterOS 7 reorganises some
  sections (`/snmp` vs `/snmp community`, `/routing/bgp/instance`
  vs `/routing bgp instance`); the parser handles both.
- **Bridge port + VLAN mapping** — RouterOS has a different
  data model from switch-vendor switches; the codec normalises
  via VLAN-centric projection so cross-vendor port-list
  semantics work.
- **Backup-side**: definition YAML lives at
  [`../../netcanon/definitions/library/mikrotik/`](../../netcanon/definitions/library/mikrotik/);
  uses `cisco_more_paging: false`.
- **Declaring a MikroTik device as the source or target.**  The
  CRS305-1G-4S+, CRS309-1G-8S+, CRS310-8G+2S+, CRS317-1G-16S+,
  CRS326-24G-2S+, CRS326-24S+2Q+, CRS328-24P-4S+, CRS354-48G-4S+2Q+
  and CRS354-48P-4S+2Q+ (family CRS3xx), the CRS504-4XQ,
  CRS510-8XS-2XQ and CRS518-16XS-2XQ (CRS5xx), and the
  CCR2004-1G-12S+2XS, CCR2004-16G-2S+ and CCR2216-1G-12XS-2XQ
  (CCR2000) are model families with one mode, `standalone`: a
  device on its own, each port at its full speed and none broken
  out.  A port is named by its factory name, each type counted from
  1 (`ether1`, `sfp-sfpplus1`, `sfp28-1`), and a QSFP port by its
  first lane (`qsfpplus1-1`, `qsfp28-1-1`): a lane of a port broken
  out comes back as off-inventory.  A model that sets an Ethernet
  port apart for management has it as its management port
  (`ether1`, or `ether49` on a CRS354), which pairs with the other
  side's management port.  The CRS310-8G+2S+ is graded `capture`,
  from a committed export; a panel whose names or management port
  MikroTik's pages leave in doubt is graded `inferred`, and its
  caveat says why.  An export prints its model on its `# model =`
  line, and detection reads it: the source picker of the Interface
  rename modal offers the device it names (`POST
  /api/v1/migration/detect-deployment` on the API).  The software id
  and the serial number beside it are never read.  A port the config
  renamed is checked by its factory name, as a translation pairs it.
  The flat target profiles of the CRS310-8G+2S+ and the
  CCR2004-1G-12S+2XS are still offered beside the families, and
  describe the same ports.  Not described, each for a reason its
  family's file gives: the CRS312-4C+8XG, CRS328-4C-20S-4S+ and
  CRS326-4C+20G+2Q+ (their combo ports), the CRS520-4XS-16XQ and
  CRS504-4XQ-OUT, the CCR2116-12G-4S+ (no MikroTik text read says
  which port is its management port), the CCR2004-16G-2S+PC and the
  CCR2004-1G-2XS-PCIe.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
