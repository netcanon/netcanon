# Fortinet FortiGate — What works for me?

If you operate Fortinet FortiGate devices and want to know what
Netcanon does for you, this is the page.

## TL;DR

- **`fortigate_cli`** — FortiOS `show full-configuration` (nested
  `config / edit / set / next / end` syntax) parse + render.
  **Certification: certified.**  Bidirectional.

The codec covers FortiOS 7.2.x through 7.6.x across FortiGate VM,
70G branch, and 100E physical-appliance fixtures.

**Important Tier-3 boundary**: FortiGate's flagship surfaces —
firewall policy table, NAT, IPsec VPN, SSL-VPN, web-filter,
antivirus, IPS — are **deliberately deferred** (see Tier 3 below).
Netcanon translates the SHARED-NETWORK-FUNCTION subset (interfaces,
VLANs, DHCP, RADIUS, SNMP) — not the security-product DNA.  If
firewall translation is your primary need, see
[`../COMPARISON.md`](../COMPARISON.md) for adjacent tools.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname` (alias / hostname), `domain`, DNS / NTP servers
  (`syslog_servers` is declared **unsupported** in the capability
  matrix and does not round-trip)
- Interfaces — physical (`port1`-`portN`, `wan1`/`wan2`,
  `internal1`-`internalN`), VLAN sub-interfaces (`VL_<id>`,
  `LAN_TRUNK`), aggregate (`fortilink`, `LAG_INTERNAL`), tunnel
  (SSL-VPN, IPsec); descriptions, IPv4 + IPv6, enabled state.
  **Note:** per-interface MTU round-trips both directions — parsed from
  `set mtu N` into the canonical model, and emitted on render as
  `set mtu-override enable` + `set mtu N` (FortiOS requires the override
  flag before `set mtu` takes effect on physical ports).  `mtu` is declared
  `supported` in the codec capability matrix.  Per-interface VRF is
  routing-instance-scoped, not a Tier-1 binding.
  **hardware-switch members:** on small appliances (40F/60F/80F)
  `internal1`-`internalN` / `lanN` are *switched ports* of the
  `internal` / `lan` L2 fabric, not standalone routed ports.  They
  translate to a positional target name (`internal3` → MikroTik
  `ether3`, etc.), so a **cross-vendor** run surfaces a soft advisory in
  the port-rename panel: the name maps by shape only and does **not**
  carry the L2-switch membership — verify the target port's physical
  cabling and L2 role.  Same-vendor round-trip preserves the name, so no
  advisory fires.  The bare aggregate (`internal` / `lan` with no
  number) has no cross-vendor equivalent at all and warns separately.
- VLANs — VLAN sub-interface form (`config system interface` →
  `set type vlan` + `set vlanid <N>`), on the interface its
  `set interface` names, with the tag its `set vlanid` states --
  not the digits of its name (`edit "vlan100"` may `set vlanid 20`;
  an OPNsense device `vlan01` may be VLAN 20) -- where that
  interface is a FortiLink aggregate, a hardware or software switch
  (`internal`, `lan`), another VLAN interface, or anything that is
  not a port or an aggregate (on those, below).  The parent is kept
  onto FortiOS, RouterOS and OPNsense; onto any other vendor it is
  not carried, and nothing reports it.  Where the output has no interface of that name, a
  parent is chosen and a `# review:` line in the VLAN's block names
  the one the source stated.  A VLAN that states no parent, or one
  from another vendor, is on the parent the renderer chooses: a
  port with a private address before a trunk, never a loopback or
  a tunnel, and a management port only where the output has no
  other; where it has none, the block says so in a `# review:`
  line.  ⚠️ Up to 0.7.7 a loopback with a private address was
  chosen before every trunk, and a switch's management port
  before its trunks, so every VLAN of a fabric switch was written
  `set interface "loopback0"` or `set interface "mgmt1"`.
- **A VLAN interface on a port or an aggregate is a sub-interface
  of it.**  FortiOS writes a VLAN interface on a port and on a
  switch with the same lines, so the parser reads the parent: one
  whose own edit says `set type physical`, or `set type aggregate`
  without `set fortilink enable`, or, where its edit states no type
  or there is none, one whose name says it is a port (`port4`,
  `wan1`).  Such a VLAN interface is typed as its parent, its tag
  its own, and makes no VLAN; its alias is its description.  Onto
  another vendor it goes where its parent goes, named by its tag
  (`gn-mgmt` on `port3` onto EOS is `interface Ethernet3.11` with
  `encapsulation dot1q vlan 11`); between two FortiOS configs it
  keeps its name.  An aggregate's name is your own, which no
  classifier reads: the job lists it, and the sub-interfaces on it,
  until an entry in the port map names it, and they go with that
  entry (`{"LAG_INTERNAL": "Port-Channel1"}` onto EOS puts `VL_100`
  on `interface Port-Channel1.100`).  Onto AOS-S, AOS-CX, OS10 and
  IOS-XE over NETCONF, which have no form for a sub-interface's tag,
  the job is `partial`, the validation report listing the tag.
  ⚠️ Up to 0.7.7 every VLAN interface was a VLAN interface and a
  VLAN: onto IOS-XE, NX-OS, EOS or Junos one on an aggregate came
  out as `interface Vlan100` or `irb.100`, which nothing on the
  aggregate carries.
- **Another platform's VLAN is a VLAN interface, and comes back as a
  VLAN where it rides on a switch interface.**  FortiOS has no VLAN
  apart from a VLAN interface on one parent, so the renderer writes a
  switch's VLAN (`vlan 10` with tagged ports) on the port it chooses
  for every VLAN interface (one with a private address or a trunk
  first, a management port last).  Where that parent is a port the
  parser knows (`port1`) or an aggregate, it reads the interface back as a
  sub-interface of it (above): its tag is the VLAN's id, and there
  is no VLAN record (`/vlans/vlan/id` is lossy).  ⚠️ Up to 0.7.7
  every VLAN interface was read back as a VLAN.
- **A sub-interface of another vendor is a VLAN interface on its
  port.**  IOS-XE `GigabitEthernet0/0/1.100` with `encapsulation
  dot1Q 200`, or a Junos `unit 100 vlan-id 200`, is `edit
  "port1.100"` / `set type vlan` / `set vlanid 200` / `set interface
  "port1"`: the tag is the one the sub-interface states, not the
  number in its name.  Read back, it is a sub-interface of the port
  again where the port has a name a FortiGate gives a port (`port1`):
  the output writes no `set type` for a port, so the parser goes by
  its name, and on a port named otherwise -- another vendor's name,
  which the bare pipeline (`run_plan`) leaves as it is, or
  `port-0-1-2`, the name made for NX-OS `Ethernet1/2` -- it is read
  back as a VLAN interface and a VLAN.  A sub-interface you name with
  no port in it (`wan10`) rides on
  the parent chosen for every VLAN, under a `# review:` line: move it
  to its port.  A FortiGate takes a VLAN id once on an interface
  (Fortinet's "Rules about VLAN configuration and VDOM interface
  assignment"): where the output has one twice on a parent, the
  second block is under a `# review:` line that names the first.  A
  sub-interface of two tags (IOS-XE `second-dot1q`, EOS `inner`,
  Junos `vlan-tags`) is written with its outer tag, and the job is
  `partial`, the validation report listing the inner tag.
  ⚠️ Up to 0.7.7 the tag was the number in its name (`set vlanid
  100` for a unit tagged 200).
- **A VLAN's alias is its label.**  FortiOS names a VLAN after its
  interface (`VL_10`), and the parser reads the interface's `set
  alias` as the description of the VLAN and of the interface.  Onto
  IOS-XE CLI, NX-OS, EOS, AOS-S, Junos and OS10, which write one
  label for a VLAN, the alias is written as the VLAN's name (`name
  Users`).  Onto FortiOS another platform's VLAN label (an IOS-XE
  `name`, an OPNsense `<descr>`) is the alias of the VLAN's
  interface where that interface states no description of its own,
  cut to the 25 characters an alias holds; where it states one, the
  alias is the interface's description and the label is in a `#
  review:` line beside it.
- Static routes (`config router static`)
- LAGs (`config system interface` with `set type aggregate` +
  member lists; a member with no `edit` of its own, as in a pasted
  fragment, is given a port record)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 USM — `config system snmp community` for v1/v2c;
  `config system snmp user` with `auth-proto` / `priv-proto` /
  `auth-pwd ENC ...` for v3
- RADIUS servers — `config user radius` with shared secret
- DHCP servers — `config system dhcp server` with per-pool subnet,
  range, gateway, dns-server, options
- Local admin / user accounts — `config system admin` with
  `set password ENC ...` form-preserving migration

## L3 redundancy: VRRP (no anycast)

**New in v0.2.0** (Wave B — classic VRRP wire-up).

FortiGate delivers HA / L3 redundancy exclusively through VRRP
groups; there's no anycast-gateway surface (anycast is a fabric
primitive on DC switches, not on edge firewalls).  The codec parses
the nested `config vrrp / edit N` sub-block inside `config system
interface`.

### Grammar

```text
config system interface
    edit "vlan10"
        set vdom "root"
        set ip 10.0.10.1 255.255.255.0
        config vrrp
            edit 10
                set vrip 10.0.10.254
                set priority 110
                set preempt enable
                set adv-interval 1
                set authentication "secretpass"
                set vrdst port2
                set status enable
            next
        end
    next
end
```

Sub-commands handled: `set vrip <X>` (IPv4 virtual), `set vrip6 <X>`
(IPv6 VRRPv3), `set priority`, `set preempt enable|disable`,
`set adv-interval <S>`, `set authentication "<token>"` (→
`plain:<token>`), `set vrdst <iface>` (destination-tracking, maps
to canonical `track_interfaces`).  Multiple `edit N` blocks under
one `config vrrp` produce multiple `CanonicalVRRPGroup` records.

VRID is bounded to 1-255 (IETF spec + pydantic validator); edits
with out-of-range IDs or missing `set vrip` are silently dropped on
parse.

### Known limitations

- **Single VIP per group.**  FortiOS `set vrip` accepts a single
  address per group.  Cross-vendor migration from multi-IP sources
  (Cisco IOS-XE secondaries, Junos `virtual-address [ X Y Z ]`)
  emits the first VIP and drops the tail with a `# review:` line
  — operator must split into multiple groups manually.
- **Custom virtual-MAC per group drops.**  FortiOS uses
  `set vrrp-virtual-mac enable/disable` as an interface-wide toggle
  (defaults to disable — FortiOS uses its NPU MAC instead of the
  IETF `00:00:5E:00:01:VRID`).  The canonical `virtual_mac`
  per-group override has no FortiOS equivalent.
- **Single `vrdst` per group.**  FortiOS `set vrdst` takes one
  interface.  Multi-track canonical groups (IOS-XE `track` objects,
  Arista `vrrp N track ... decrement N`) emit the first and drop
  the rest with a `# review:` line.  The decrement value is also
  lossy — `vrdst` is a binary up/down trigger, not a priority-
  decrement scheme.
- **`vrgrp`, `vrdst-priority`, `start-time`**, and other FortiOS-
  specific knobs (group-of-groups synchronisation, alternate-
  priority for destination unreachable, startup-delay) are not in
  canonical scope and drop on cross-vendor render.
- **No anycast-gateway grammar.**  FortiGate is a firewall / edge
  platform; the three anycast canonical paths
  (`virtual-gateway-address` v4/v6, `anycast-gateway-mac`) are
  declared `unsupported` and parse-and-ignore.  The interface's own
  address beside a gateway (Junos `address X virtual-gateway-address
  Y`, AOS-CX `active-gateway`) is written; only the gateway is
  dropped, and the validation report lists it.  ⚠️ Up to 0.7.7 the
  address was dropped with it, and the interface had none.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model; see `02-per-vendor-grammar.md` §
  "FortiGate" for the per-knob lossiness rationale.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (FortiGate explicitly out of scope as a
  firewall/edge platform without fabric primitives).

## Lossy paths

- **`/system/dns`** with view scoping — view definitions parse-and-
  ignore (`config system dns-database`); cross-vendor mappings
  collapse to global DNS.
- See per-codec `CapabilityMatrix.lossy` declarations for the
  full list.

## What we don't do

These are the FortiGate flagship surfaces deliberately deferred to
[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall policy table** — `config firewall policy` (the
  zone-pair / interface-pair stateful policy table is FortiGate's
  primary semantic; cross-vendor translation doesn't preserve
  meaning)
- **NAT** — VIPs, IP pools, central-NAT, SNAT, DNAT
  (`config firewall vip` etc.)
- **IPsec VPN** — `config vpn ipsec phase1-interface` /
  `phase2-interface`
- **SSL-VPN** — `config vpn ssl settings`, portal config, web-mode
  bookmarks
- **Web-filter / antivirus / IPS / application-control** — UTM
  profiles
- **SD-WAN** — health-check, SLA, performance-SLA rules
- **FortiGuard categories** — license-bound URL category lists
- **Routing protocols** — BGP / OSPF stanzas (informational only)
- **Certificates / PKI**

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`kevinguenay_fgt_70g_branch.conf`** — FortiOS 7.6.6 branch
  config for FortiGate 70G ZTP deployment (12,317 lines covering
  system global, fortilink, LAG_INTERNAL aggregates, BGP loopback,
  SD-WAN, IPsec, firewall policies, web-filter, antivirus, IPS —
  the Tier-3 surface here is silently carried past)
- **`kevinguenay_fgt_vm_hub.conf`** — FortiOS 7.6.6 VM-based hub
  config (13,827 lines; hub-side counterpart to the branch)
- **`user_contrib_fg100e_fos7213.conf`** — operator-contributed
  physical FortiGate 100E on FortiOS 7.2.13 (35K+ lines, 34
  interfaces, 5 VLAN sub-interfaces, 2 LAGs, 6 DHCP servers,
  full firewall policy table, VIPs, SDWAN health-check, IPsec,
  SSL-VPN portal — first physical-appliance + first 7.2.x
  capture in the corpus)

Spans FortiOS 7.2.x and 7.6.x; FortiGate VM, 70G branch hardware,
and 100E physical hardware.

## A quoted value of several lines

FortiOS prints a value of several lines as it is, between its quotes,
as the committed captures show for a certificate (`set certificate
"-----BEGIN CERTIFICATE-----` ... `-----END CERTIFICATE-----"`), a
private key and a replacement message's HTML (`set buffer "<!DOCTYPE
html>` ... `"`).  A quote, an apostrophe or a backslash in a value is printed
with a backslash in front of it (`\"`, `\'`, `\\`), as the committed
captures show; the parser takes a backslash as escaping the character
after it, whichever character that is.

The parser reads such a statement whole, up to the line whose quote no
backslash escapes, so none of its lines is a statement of its own: a
line `end` in a value closes nothing, and a line of HTML that reads
`config system admin` is no account.  The Tier-3 detection and the
release (`#config-version`) are read from the text with the value's
lines emptied, each line keeping its number.  A line that begins with
`#` is a comment, whatever quotes it holds.

Refused, in words that name the line and quote nothing of the text:

- **a value that no later line ends** -- the rest of the config would
  be its text.  Paste the configuration whole, as the FortiGate prints
  it (a backup file, or the output of `show`);
- **a line of a value that ends in another character than a line feed**
  (a form feed, a vertical tab, a carriage return on its own; `\r\n`
  is a line feed) -- the device does not end a line there, so where the
  value ends is not where the lines say.

A value of several lines that the tree keeps -- an interface's alias,
a static route's comment -- reaches every target on one line, each
break as a space, and the job says where
([`../CAPABILITIES.md`](../CAPABILITIES.md) § C1).  A FortiGate target
loses the layout too.

## Common gotchas

- **A RADIUS secret typed without `ENC` migrates; an `ENC` secret goes
  to FortiOS only.**  FortiOS prints a stored secret as `set secret
  ENC <blob>`, encrypted under the FortiGate's own key: it is written
  back onto FortiOS, and onto any other target the server is written
  with no key, beside a review line.  A `set secret <secret>` written
  without `ENC` -- a config typed by hand, or a template -- is the
  secret itself, and migrates.  With 0.7.7 or earlier such a secret
  was refused on every other target as if it were encrypted.
- **A VLAN on a VLAN is one tag on a VLAN interface.**  A VLAN
  interface whose `set interface` is another VLAN interface (Q-in-Q
  on FortiOS) is read as a VLAN interface of one tag on that VLAN
  interface, not as a sub-interface of two tags.  Onto a target that
  writes tags the job is `partial`; a source's sub-interface of two
  tags (IOS-XE `second-dot1q`, EOS `inner`, Junos `vlan-tags`) has no
  form here, and is `partial` too.
- **Names no other vendor has** — a hardware switch (`internal`,
  `lan`) and the SSL-VPN pseudo-interface (`ssl.root`) have no form
  on another vendor and are dropped, with whatever address they
  hold; `naf.root`, `l2t.root` and an interface with a name of your
  own are not read by the port translator and are left under that
  name.  With no devices declared the job is `partial` for each —
  `unresolved_ports` for the dropped, `untranslated_ports` for the
  ones left — until an entry of `port_rename_map` decides it: a
  name on the target, or `null`.  A hardware switch that holds the
  LAN address wants a name (a VLAN interface, usually), not a drop.
  See [`../CAPABILITIES.md`](../CAPABILITIES.md) § D1.
- **`ENC <base64>` encrypted secrets** — round-trip through the
  canonical `hashed_password` field with format-preservation; never
  decoded to plaintext.
- **A password typed in the source** (AOS-S `plaintext`, AOS-CX
  `password plaintext`, VyOS `plaintext-password`) is written as
  FortiOS: `set password "<password>"`, for the FortiGate to encrypt
  on save.  ⚠️ Up to 0.7.7 it was written `set password ENC
  <password>` — a claim that it is a blob this FortiGate encrypted —
  so the account did not hold the password; translate such a config
  again.  Every value FortiOS takes in quotes -- an admin's name and
  access profile, the SNMP community, an SNMPv3 user and its keys, a
  VRRP key, an interface's name, a LAG's members, a VLAN's parent, a
  route's device, a DHCP pool's interface and domain, a RADIUS server,
  a description -- is written with FortiOS's escape for a `"` and a
  `\` (`\"`, `\\`), and the parser reads an `edit` name back through
  the same escape.  Not yet under it: a RADIUS key typed in the source
  is written bare (`set secret <key>`).
- **An admin whose password cannot be carried is left out** as a
  target, with a `# ... review:` line in its place.  ⚠️ Up to 0.7.7
  the admin was written without its password (`edit`, `set accprofile
  "super_admin"`) — an admin with no password; read old outputs for
  an `edit` after a `review:` line.
- **Declaring a FortiGate as the source device** — with both devices
  declared (in the Interface rename modal or on the API), a correctly
  declared FortiGate is still
  `partial`: pseudo-interfaces the codec does not classify come back
  as off-inventory, and — onto another vendor's device — the stock
  `fortilink` aggregate, which the ordinary translation gives a
  port-shaped name there, is dropped and
  reported (`displaced`) where that name is a port of the target, and
  listed (`landed_off_target`) where it is not.  A VLAN interface the
  codec reads as a physical port, or as a management port (`MGMT`),
  is treated the same way.  Name such
  an interface in `port_rename_map` to decide it.  Between two
  FortiGates such a name is not read at all: `fortilink`, `DMZ` and
  `MGMT` stay as they are written.
  FortiOS interface names are an operator's free text and are kept
  apart by case: `DMZ` beside a port `dmz` is its own interface.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § G.
- **`set vdom`** scoping — Netcanon parses single-VDOM configs
  cleanly; multi-VDOM scoping is a known gap (deferred follow-up).
- **Most of a FortiGate config is Tier-3** (firewall, NAT, VPN,
  UTM); Netcanon translates the cross-vendor-translatable subset
  (interfaces, VLANs, DHCP, RADIUS, SNMP) and silently carries the
  rest past on parse.  The migrate page's Tier-3 banner surfaces
  what was detected-but-not-translated.
- **Backup-side**: requires netmiko or paramiko-shell collector
  with `cisco_more_paging: false`.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../COMPARISON.md`](../COMPARISON.md) — Capirca / Aerleon for
  firewall ACL translation
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
