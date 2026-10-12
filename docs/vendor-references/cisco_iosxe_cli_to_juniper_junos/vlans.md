# VLANs and switchport membership: Cisco IOS-XE versus Juniper Junos

How VLANs are declared and how interfaces are bound to them.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/configuration_guide/vlan/b_179_vlan_9300_cg/configuring_vlans.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html (retrieved 2026-04-30)

Citation ids: `cisco-vlan-cg`, `junos-vlans-statement`, `junos-bridging-overview`.

## Cisco IOS-XE form

VLAN declarations live under the global `vlan <N>` stanza; per-port
membership lives under the `interface` stanza:

```
vlan 100
 name Production-Servers
!
vlan 200
 name VoIP
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 100
 switchport voice vlan 200
!
interface GigabitEthernet1/0/2
 switchport mode trunk
 switchport trunk allowed vlan 100,200,300
 switchport trunk native vlan 1
```

VLAN 1 is the implicit default on every switchport.  Voice VLAN is a
first-class field surfaced via LLDP-MED.

## Junos form

Junos declares VLANs and per-interface membership independently;
membership is expressed on the unit-side:

```
set vlans Production-Servers vlan-id 100
set vlans VoIP vlan-id 200

set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members Production-Servers
set interfaces ge-0/0/0 native-vlan-id 1

set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members [ Production-Servers VoIP ]
```

VLANs are referenced by name on the per-unit `vlan members` line,
or by id or range of ids (Junos takes all three; the renderer uses
names for the VLANs it defines and ids for the rest).  The native VLAN id lives at the parent interface
hierarchy (`native-vlan-id`), NOT under the unit.  Voice VLAN is not
a first-class Junos construct — operators surface it through
`protocols lldp-med` or via dedicated VLAN names that map to the
voice phone tag.

## Mapping notes

- **Stanza-form versus set-form.** Cisco's per-stanza grammar
  (`interface ... / switchport ...`) parses into the same canonical
  shape as Junos's per-line set grammar (`set interfaces ... family
  ethernet-switching ...`).  The codec parsers normalise; the
  canonical model is `CanonicalVlan` (vlan-centric) plus
  `CanonicalInterface.{switchport_mode, access_vlan,
  trunk_allowed_vlans, trunk_native_vlan}`.
- **VLAN naming.** A Junos VLAN has a name, and `vlan members`
  takes that name (or an id, or a range of ids); the codec render
  path synthesises a
  default name (typically `vlan<N>`) when the source VLAN had no
  explicit name.  Junos VLAN names are constrained to letters,
  digits, hyphens, and periods (see `vlan-name-constraints.md`).
- **Native VLAN hierarchy.** Junos splits the native VLAN id away
  from the unit (`native-vlan-id` at the parent), where Cisco keeps
  it inline as `switchport trunk native vlan <N>`.  Round-trip
  preserves the integer; the structural difference is internal to
  each codec's render path.
- **Voice VLAN.** Cisco's `switchport voice vlan <N>` has no clean
  Junos equivalent; the canonical
  `CanonicalInterface.voice_vlan` field carries the value but the
  Junos render emits a comment (informational) rather than a real
  config line.
- **Trunk allowed-VLAN list.** Cisco's `switchport trunk allowed
  vlan add 200` (incremental form) vs `switchport trunk allowed
  vlan 100,200,300` (replace form) both flatten to the same
  `CanonicalInterface.trunk_allowed_vlans` list; canonical doesn't
  preserve the order or the add/remove semantic.  A Cisco trunk that
  states no allowed list is every VLAN and is written `vlan members
  all`; `switchport trunk allowed vlan none` is a Junos trunk with no
  members.  The table at the foot of this file has every platform.

Disposition: **lossy** on `voice_vlan`, **good** on
`switchport_mode` / `access_vlan` / `trunk_allowed_vlans` / VLAN
declarations.

## A trunk that states no allowed list, platform by platform

What a trunk carries when its config has no allowed line is the
platform's own default, and the platforms split.  The canonical tree
has no value for "not stated": each parser puts what its platform
does, from one table (`TRUNK_THAT_STATES_NO_LIST` in
`netcanon/migration/codecs/_helpers.py`).  This is where the rows of
that table come from.  It is kept in this pair's file because the two
platforms of the pair are on opposite sides of it; it covers every
codec that writes a trunk's VLANs.  Retrieved 2026-10-12.

| Platform | A trunk that states no allowed list carries | Its form for no VLAN | Its form for every VLAN | Source |
|---|---|---|---|---|
| Cisco IOS-XE | every VLAN, 1-4094 | `switchport trunk allowed vlan none` | `... all`, which is the default; a default is not printed | C1, C2, C3 |
| Cisco NX-OS | every VLAN — 1-3967 and 4048-4094: a block of ids is reserved, and can be moved | the keyword `none` | the keyword `all`, which is the default | N1 |
| Arista EOS | every VLAN | `switchport trunk allowed vlan none` | `... all`; the default is the absence of the statement | A1 |
| Aruba AOS-CX | every VLAN: defining a native VLAN makes the switch run `vlan trunk allowed all` | none exists | `vlan trunk allowed all` | H1 |
| Aruba AOS-S | no allowed list: a port carries the VLANs that name it | tagged in no VLAN | no word: `tagged <port>` in every VLAN | H1, H2, H3 |
| Dell OS10 | untagged traffic on its access VLAN; no tagged VLAN | no keyword: no allowed line | no keyword: each VLAN is listed, must exist first, and ids end at 4093 | D1, D2 |
| Junos (ELS) | the VLANs its `vlan members` name, so none | no `vlan members` statement | `vlan members all` | J1, J2, J3 |

### Sources

Quoted text below is byte for byte the vendor's, taken from the PDF
edition of the document named.  Where a page could not be copied
exactly, what it says is given in other words and marked "says".

- **C1** — Cisco, *Command Reference, Cisco IOS XE 17.15.x (Catalyst
  9300 Switches)*, VLAN Commands, `switchport trunk`:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-15/command_reference/b_1715_9300_cr/vlan_commands.html>.
  Says: the default for all VLAN lists is to include all VLANs; `all`
  is every VLAN from 1 to 4094 and is the default; `none` is an empty
  list; `add` and `remove` add to and take from the list currently
  set; `except` inverts the list given; the `no` form resets the list
  to the default, which allows all VLANs.
- **C2** — Cisco, *VLAN Configuration Guide, Cisco IOS XE 17.13.x
  (Catalyst 9300 Switches)*, Configuring VLAN Trunks:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-13/configuration_guide/vlan/b_1713_vlan_9300_cg/configuring_vlan_trunks.html>.
  Says: by default a trunk port sends traffic to and receives traffic
  from all VLANs; the default switchport mode of an Ethernet
  interface is `dynamic auto`, not trunk.
- **C3** — Cisco, *Configuration Fundamentals Command Reference, Cisco
  IOS XE Release 3SE (Catalyst 3850 Switches)*, `show running-config`:
  <https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/fundamentals/command/xe3se/3850/fundamentals-xe-3se-3850-cr-book/show-commands-xe-3se.html>.
  Says: without the `all` keyword the output does not show commands
  configured with default parameters.
- **N1** — Cisco, *Cisco Nexus 9000 NX-OS Interfaces Configuration
  Guide, Release 10.1(x)*, Configuring Layer 2 Interfaces:
  <https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/101x/configuration/interfaces/cisco-nexus-9000-nx-os-interfaces-configuration-guide-101x/b-cisco-nexus-9000-nx-os-interfaces-configuration-guide-93x_chapter_0100.html>.
  Says: by default a trunk port sends traffic to and receives traffic
  from all VLANs; the default is to allow all VLANs on the trunk, 1
  to 3967 and 4048 to 4094; VLANs 3968 to 4047 are reserved for
  internal use by default, and the block can be changed; an
  internally allocated VLAN cannot be added as an allowed VLAN.  The
  syntax lists `none`; no sentence on the page defines it.
- **N2** — Cisco, the Release 6.x edition of the same chapter, table
  of default settings:
  <https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus9000/sw/6-x/interfaces/configuration/guide/b_Cisco_Nexus_9000_Series_NX-OS_Interfaces_Configuration_Guide/b_Cisco_Nexus_9000_Series_NX-OS_Interfaces_Configuration_Guide_chapter_011.html>.
  Says: the default switchport mode is access.
- **A1** — Arista, *EOS User Manual*, Virtual LANs (VLANs):
  <https://www.arista.com/en/um-eos/eos-virtual-lans-vlans>.  Says: by
  default interfaces handle tagged traffic for all VLANs; `none`
  makes the VLAN list empty; `all` makes it all VLANs; the `no` and
  `default` forms restore the default of all by removing the
  statement from running-config; trunk settings persist in
  running-config without taking effect while the interface is not in
  trunk mode; `no switchport mode` returns an interface to its
  default, an access port.
- **H1** — HPE, *AOS-CX 10.14 Layer-2 Bridging Guide, 6300, 6400
  Switch Series* (published May 2024, edition 1); the commands'
  own pages are
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.14/HTML/l2_bridging_8400/Content/Chp_vlans/vlan_cmds/vla-tru-nat.htm>
  and
  <https://support.hpe.com/hpesc/public/docDisplay?docId=sd00007217en_us&page=GUID-D7ACDC60-C5BC-4C2E-9385-0CDF2316E64A.html&docLocale=en_US>.
  - `vlan trunk allowed`: "The no form of this command removes one or
    more VLAN IDs from a trunk interface. When the last VLAN is
    removed from a trunk interface, the interface continues to
    operate in trunk mode, and will trunk all the VLANs currently
    defined on the switch, and any new VLANs defined in the future.
    To disable the trunk interface, use the command shutdown."
  - `all`: "Configures the trunk interface to allow all the VLANs
    currently configured on the switch and any new VLANs that are
    configured in the future."
  - `vlan trunk native`: "When a native VLAN is defined, the switch
    automatically executes the vlan trunk allowed all command to
    ensure that the default VLAN is allowed on the trunk. To only
    allow specific VLANs on the trunk, issue the vlan trunk allowed
    command specifying only specific VLANs."
  - The native VLAN and the list, from the guide's table of
    equivalent configurations: "VLAN 5 must be allowed on the trunk
    so that untagged traffic is not dropped."
- **H2** — HPE, *Aruba Basic Operation Guide for ArubaOS-Switch
  16.10*: "In the factory default configuration, the switch has one,
  permanent default VLAN (named DEFAULT_VLAN) that includes all ports
  on the switch."
- **H3** — HPE, *Aruba 2930M/F Access Security Guide for AOS-S
  16.11*: "a port can be an untagged member of only one VLAN at a
  time."
- **D1** — Dell, *OS10 Enterprise Edition User Guide, Release
  10.4.0E(R2)* (Rev. A02, 2018-10), read from a copy at
  <https://cdn.iceshop.nl/objects/mmo_59211473_1573036230_9391_3406.pdf>;
  Dell's page for the command in release 10.5.1 is
  <https://www.dell.com/support/manuals/en-us/dell-emc-smartfabric-os10/smartfabric-os-user-guide-10-5-1/switchport-trunk-allowed-vlan?guid=guid-12846a2d-1b7d-40cb-9aa5-b7d126b89de8&lang=en-us>.
  - "By default, an interface is configured in Access mode."
  - "By default, a trunk interface carries only untagged traffic on
    the Access VLAN. You must manually configure other VLANs for
    tagged traffic."
  - "By default, a trunk port is not added to any tagged VLAN. You
    must create a VLAN before you can assign the interface to it."
  - "VLAN IDs range from 1 to 4093 and can provide a total of 4093
    logical networks."
- **D2** — Dell KB 000137464, on the native VLAN of a trunk port:
  <https://www.dell.com/support/kbdoc/en-us/000137464/dell-emc-networking-os10-how-to-configure-native-access-untagged-vlan-on-a-trunk-port>.
  Says: the native (untagged) VLAN is configured as the access VLAN,
  and an interface cannot be an access and a trunk member of the same
  VLAN.
- **J1** — Juniper, `members` (QFX Series):
  <https://www.juniper.net/documentation/en_US/junos/topics/reference/configuration-statement/members-edit-interfaces-qfx-series.html>.
  Says: for trunk interfaces the statement configures the VLANs for
  which the interface can carry traffic; `all` makes the trunk a
  member of all VLANs configured on the switch, and of each VLAN
  configured later; `all` cannot be the name of a VLAN.
- **J2** — Juniper, `native-vlan-id`:
  <https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/native-vlan-id-edit-interfaces-qfx-series.html>.
  Says: untagged packets are dropped on a trunk interface unless
  `native-vlan-id` is configured.
- **J3** — Juniper, *Bridging and VLANs*:
  <https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans.html>.
  Says: on a factory-default switch every interface is in access
  mode; a trunk's logical interface has to be a member of the native
  VLAN to receive its untagged packets.

### Not established from a vendor's page

- **Junos**: the sentence that says what a trunk with no `vlan
  members` carries, and whether such a config commits.  "None" is
  read from J1 and J2.
- **IOS-XE, NX-OS, EOS**: what the running config prints for a trunk
  set to `none`, and whether the native VLAN's traffic passes when
  the native VLAN is not in the allowed list.  HPE says it outright
  for AOS-CX (H1).
- **NX-OS**: what the switch does with a list that names a reserved
  id.
- **AOS-CX**: whether an allowed list may name VLANs the switch does
  not define; and what a port with `no routing` and no `vlan` line
  is.  It is taken to be an access port in VLAN 1.
- **OS10**: the text of the 10.5.x guide itself.  The quotes are from
  the 10.4.0E(R2) guide.

### Mapping notes

- On a trunk, `CanonicalInterface.trunk_allowed_vlans == []` is no
  VLAN and a list of every id, 1-4094, is every VLAN.  A parser fills
  an unstated list from the table; a renderer writes the form in the
  third or fourth column, or no allowed line where that is the
  platform's own default for the list.
- The table's second column is about a TRUNK.  The default mode of a
  port is not trunk on any of these platforms (C2, N2, A1, D1, J3),
  so the list is filled only for a port that says it is a trunk.  The
  NX-OS and EOS parsers take a port for a trunk from a trunk line
  with no mode line, which A1 says has no effect on an access port;
  a trunk read that way is given nothing from the second column.
- Some cells have no form.  AOS-CX cannot be told "no VLAN": neither
  `vlan trunk` line is written, and a review line says so.  OS10
  cannot be told "every VLAN": the range is written, under a review
  line.  AOS-S is told VLAN by VLAN.
- Whether the allowed list holds the native VLAN differs (H1, D2) and
  is not yet one convention in the tree: each parser puts what its
  platform's text lists.
