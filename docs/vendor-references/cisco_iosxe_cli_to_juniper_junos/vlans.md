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
hierarchy (`native-vlan-id`), NOT under the unit -- in the ELS
grammar shown here, which is the one the codec writes; the older
grammar (`port-mode trunk`) keeps it under the unit, and the two
differ in what a native VLAN on `vlan members` means (see the foot
of this file).  Voice VLAN is not
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
  each codec's render path.  Whether the allowed list (`vlan
  members`) names the native VLAN is carried as the text has it, in
  both directions: a native VLAN its list leaves out stays out.
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
  set to `none`.  (Whether the native VLAN's traffic passes when the
  native VLAN is not in the allowed list has a section of its own,
  below.)
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
- Whether the allowed list holds the native VLAN differs by platform
  (H1, D2), and is one convention in the tree: the list is what the
  trunk carries, its native VLAN among them.  The next section has
  every platform.

## A trunk's untagged VLAN and its allowed list, platform by platform

A trunk states which VLAN it carries untagged and which VLANs it
carries.  Whether the second statement has to name the first is not
one grammar, and what a switch does when it does not is not one
answer.  In the canonical tree it is one convention: a trunk's
`trunk_allowed_vlans` is what the trunk carries, its native VLAN among
them, and a `trunk_native_vlan` the list does not hold is stated and
not carried (`trunk_untagged_vlan` in
`netcanon/migration/canonical/transforms.py`).  Each parser and
renderer gets from its platform's text to that convention by one
table, `NATIVE_VLAN_AND_THE_LIST` in
`netcanon/migration/codecs/_helpers.py`.  This is where its rows come
from, and where what each vendor says of the case is kept.  Retrieved
2026-10-13; every quoted sentence was matched, as a string, against
the text of the page fetched that day.

| Platform | Where its text states the untagged VLAN | A native VLAN the list leaves out | That stands on | Row of the table |
|---|---|---|---|---|
| Cisco IOS-XE (Catalyst switches) | `switchport trunk native vlan`, a line of its own; the allowed line may name it or leave it out | VLAN 1, the default native VLAN: not carried for user traffic.  Another id: not carried, by inference | Cisco's sentence for VLAN 1 (C4).  For another id no Cisco sentence: an inference from Cisco's rule that a trunk is a member of the VLANs its list allows (C4), with which the community accounts found agree; two phrases of the command reference read the other way (C5) | `LIST_DECIDES` |
| Cisco NX-OS | `switchport trunk native vlan`, a line of its own | VLAN1, the default: data traffic blocked, control traffic goes on.  Another id: not carried, by inference | Cisco's sentence for VLAN1 (N3).  For another id no Cisco sentence: an inference from Cisco's definition of the allowed list (N3) | `LIST_DECIDES` |
| Arista EOS | `switchport trunk native vlan`, a line of its own | **not established** | nothing: Arista's sentences read both ways (A1), and no account of the case was found | `LIST_DECIDES`, for how the text is written and no more |
| Aruba AOS-CX | `vlan trunk native`, a line of its own | untagged frames dropped on receive; the native VLAN not forwarded | HPE's sentences (H4, H5, H6) | `LIST_DECIDES` |
| Junos, ELS grammar | `native-vlan-id` on the physical interface, beside the unit's `vlan members` | the unit has to have the native VLAN for untagged packets to be received; that a frame is dropped otherwise is not printed, and the send direction is not established | Juniper's requirement and its procedure (J3) | `LIST_DECIDES` |
| Junos, older grammar (`port-mode trunk`) | `native-vlan-id` under the unit, beside `vlan members` | carried untagged both ways -- and when the VLAN is ALSO on `vlan members`, sent TAGGED | one Juniper knowledge-base article for EX Series, read in an archived copy (J4) | none: the parser reads this grammar as the ELS one (see below) |
| Dell OS10 | the trunk's `switchport access vlan`; the allowed line names tagged VLANs | no such state: the access VLAN is carried, and cannot be on the allowed line as well | Dell's sentences (D3, D4); one Dell article for "cannot" (D2) | `BESIDE_THE_LIST` |
| Aruba AOS-S | a VLAN's `untagged <ports>` line; there is no allowed list | no such state: the port carries the VLAN that lists it untagged | HPE's sentences for receive (H7); HPE's examples for send (H6) | none: it is told VLAN by VLAN |

And when the config states no untagged VLAN at all (the rows of
`TRUNK_THAT_STATES_NO_NATIVE` in the same module; AOS-S is not in it,
being told VLAN by VLAN):

| Platform | A trunk that states no native VLAN | Source |
|---|---|---|
| Cisco IOS-XE | native VLAN 1 | C4 |
| Cisco NX-OS | the default VLAN, which the same page names VLAN1: native VLAN 1 | N3 |
| Arista EOS | native VLAN 1 | A1 |
| Aruba AOS-CX | native VLAN 1 | H8 |
| Junos | none: untagged packets are dropped | J2 |
| Dell OS10 | the switch's default VLAN | D5 |
| Aruba AOS-S | a port is in the default VLAN (VID 1) in the factory default configuration, and remains in it until it is removed; tagged or untagged is not in the sentences, and nothing was found for a trunk group or a port that is in one | H7 |

### Sources

- **C4** -- Cisco, *VLAN Configuration Guide, Cisco IOS XE Dublin
  17.12.x (Catalyst 9300 Switches)*, Configuring VLAN Trunks:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/vlan/b_1712_vlan_9300_cg/configuring_vlan_trunks.html>.
  - "The native VLAN is VLAN 1 by default."
  - Of disabling VLAN 1 on a trunk: "so that no user traffic
    (including spanning-tree advertisements) is sent or received on
    VLAN 1."  The sentence is about VLAN 1, not about "the native
    VLAN"; it answers for a trunk that states no native VLAN because
    VLAN 1 is that trunk's native VLAN.
  - What goes on in VLAN 1 all the same: "the interface continues to
    send and receive management traffic"; the sentence names CDP,
    PAgP, LACP, DTP and VTP.
  - The rule the inference for another id is drawn from: "However,
    you can remove VLANs from the allowed list, preventing traffic
    from those VLANs from passing over the trunk."
- **C5** -- Cisco, *Command Reference, Cisco IOS XE Dublin 17.12.x
  (Catalyst 9300 Switches)*, VLAN Commands, `switchport trunk`:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/command_reference/b_1712_9300_cr/vlan_commands.html>.
  The two phrases that read the other way, neither of which names
  the case:
  - "Sets the list of allowed VLANs that can receive and send traffic
    on this interface in tagged format when in trunking mode."
  - "All untagged traffic received on an IEEE 802.1Q trunk port is
    forwarded with the native VLAN configured for the port."
- **N3** -- Cisco, *Cisco Nexus 9000 Series NX-OS Interfaces
  Configuration Guide, Release 10.6(x)*, Configuring Layer 2
  Interfaces:
  <https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-106x/m_configuring_layer_2_interfaces_9x.html>.
  - "If you do not configure a native VLAN ID, the trunk port uses the
    default VLAN."
  - Which VLAN that is, in the task "Configure a VLAN Interface as a
    Layer 2 Access Port" of the same page: "The default VLAN is
    VLAN1."
  - "When you remove VLAN1, all data traffic for VLAN1 on this port is
    blocked, but the control traffic continues to move on the port."
  - "Allowed VLANs are the set of VLANs permitted to send and receive
    traffic over a trunk port, controlling which VLAN traffic
    traverses the trunk link."
  - Cisco's own example on the page names the native VLAN in the list
    as well: `switchport trunk native vlan 10`, then `switchport
    trunk allowed vlan 5, 10`.
- **A1** -- Arista, the page above (*EOS User Manual*, Virtual LANs).
  - "The default native VLAN for all interfaces is VLAN 1."
  - The list, worded as a list for tagged traffic: the command
    "creates or modifies the list of VLANs for which the
    configuration mode interface, in trunk mode, handles tagged
    traffic."
  - And as the port's membership: "The interface may be a member of
    multiple VLANs, as configured by the switchport trunk allowed
    vlan command."
  - "Interfaces in trunk mode associate untagged frames with the
    native VLAN."
- **H4** -- HPE, *AOS-CX 10.16 Layer-2 Bridging Guide, 6300, 6400
  Switch Series*, Trunk interface:
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/l2_bridging_6300-6400/Content/Chp_vlans/tru-int.htm>.
  "If the native VLAN is not included in the allowed list, all
  untagged frames that ingress on the trunk interface are dropped."
- **H5** -- HPE, *AOS-CX 10.16 Link Aggregation Guide*, `vlan trunk
  native`:
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/link_aggregation/Content/Chp_LAG/LACP_LAG_cmds/vla-tru-nat-lac-lag-10.htm>.
  "For the interface to forward the native VLAN traffic, the
  interface has to be allowed explicitly by entering vlan trunk
  allowed <ID>"; and: "This setting is also applicable to the
  physical interface."
- **H6** -- HPE, the same Layer-2 guide, Comparing VLAN commands on
  PVOS, Comware, and AOS-CX:
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/l2_bridging_6300-6400/Content/Chp_vlans/com-vla-com-pvo-com-aos-cx..htm>
  (two dots: the page's own name).  HPE's side-by-side of the two
  grammars: the AOS-S port `untagged vlan 5` with `tagged vlan
  10,30,50` is the AOS-CX port `vlan trunk native 5` with `vlan trunk
  allowed 5, 10,30,50`, and: "VLAN 5 must be allowed on the trunk so
  that untagged traffic is not dropped."
- **H7** -- HPE, *Aruba 2930F / 2930M Advanced Traffic Management
  Guide for ArubaOS-Switch 16.10* (part 5200-6759a, February 2020),
  chapter "VLANs":
  <https://arubanetworking.hpe.com/techdocs/AOS-Switch/16.10/Aruba%202930F%26M%20Advanced%20Traffic%20Management%20Guide%20for%20AOS-S%20Switch%2016.10.pdf>.
  - "A port can be a member of one untagged, port-based VLAN. All
    other port-based VLAN assignments for that port must be tagged."
  - "If the port is a member of an untagged, port-based VLAN, the
    switch forwards the packet to that VLAN."
  - "If the port has no untagged VLAN memberships, the switch drops
    the packet."
  - "In the factory default configuration, all ports are assigned to
    the default VLAN (DEFAULT_VLAN; VID=1)."
  - "Any ports not specifically removed from the default VLAN remain
    in the DEFAULT_VLAN, regardless of other port assignments."
- **H8** -- HPE, the same AOS-CX Layer-2 guide, `vlan trunk native`:
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/l2_bridging_6300-6400/Content/Chp_vlans/vlan_cmds/vla-tru-nat.htm>.
  "By default, VLAN ID 1 is assigned as the native VLAN ID for all
  trunk interfaces."
- **D2** -- Dell KB 000137464, above.  "The Native VLAN (untagged) is
  configured as access VLAN."  And: "An interface cannot be an access
  and trunk member of the same VLAN. The vlan must first be removed
  from the trunk and added back as access."
- **D3** -- Dell, *SmartFabric OS10 User Guide, Release 10.5.5*,
  `switchport mode`:
  <https://www.dell.com/support/manuals/en-us/smartfabric-os10-emp-partner/smartfabric-os-user-guide-10-5-5/switchport-mode?guid=guid-587e60fa-4585-439e-9e07-931503bed2fb&lang=en-us>.
  Of the `trunk` keyword: "Enables L2 switching of untagged frames on
  the access VLAN, and of tagged frames on the VLANs specified with
  the switchport trunk allowed vlan command."
- **D4** -- Dell, the same guide, `switchport trunk allowed vlan`:
  <https://www.dell.com/support/manuals/en-us/smartfabric-os10-emp-partner/smartfabric-os-user-guide-10-5-5/switchport-trunk-allowed-vlan?guid=guid-12846a2d-1b7d-40cb-9aa5-b7d126b89de8&lang=en-us>.
  "Configures the tagged VLAN traffic that a L2 trunk interface can
  carry."
- **D5** -- Dell, the same guide, L2 mode configuration:
  <https://www.dell.com/support/manuals/en-us/smartfabric-os10-emp-partner/smartfabric-os-user-guide-10-5-5/l2-mode-configuration?guid=guid-faef203b-d086-4ec4-9197-4142ca391ca0&lang=en-us>.
  "By default, native VLAN of a port is the default VLAN ID of the
  switch."
- **D6** -- Dell, the same guide, three pages on taking the access
  VLAN off a port, which do not agree.  `switchport access vlan`
  (`.../switchport-access-vlan?guid=guid-d1c6090e-b9d2-4c09-b5fc-cbd36e8daf01&lang=en-us`):
  "The no version of this command resets access VLAN membership on a
  L2 access or trunk port to VLAN 1."  `no switchport access vlan`
  (`.../no-switchport-access-vlan?guid=guid-21bdcf0b-12f3-4590-8d06-1c4826db0283&lang=en-us`):
  "Resets access VLAN membership on a range of interfaces or an
  individual interface."  The procedure for a trunk
  (`.../configure-trunk-port?guid=guid-b6d5f654-5ecb-4525-b5d5-eb04355037f7&lang=en-us`)
  has the same line as the step "Remove access VLAN membership."
- **J2**, **J3** -- Juniper, the two pages above.  J2: "By default,
  the untagged packets are dropped on trunk interfaces."  J3, of the
  ELS grammar: "The logical interface on which untagged packets are
  to be received must be configured with the same VLAN ID as the
  native VLAN ID configured on the physical interface."  The step of
  the procedure that fulfils it is `vlan members`: "Specify that the
  logical interface that will receive the untagged data packets is a
  member of the native VLAN:".  J3's example for the ELS grammar ends
  in `native-vlan-id 1;` and `members [ 1 sales support ];`; its
  example for the older grammar has `members [ sales support ];`
  beside `native-vlan-id 1;`.
- **J4** -- Juniper Knowledge Base, KB17419, *[EX] Native VLAN ID and
  tagged behavior in EX-series switches* (version 6.0, last updated
  March 2020), read in the Internet Archive's copy of 2021-04-20:
  <http://web.archive.org/web/20210420081719/https://kb.juniper.net/InfoCenter/index?page=content&id=KB17419>.
  It says of itself that it "applies to switches running non-ELS
  Junos OS versions".  The native VLAN outside the members: "MGMT is
  NOT a member of trunk, but it is a member of native VLAN: Transmit
  = untagged (pass) Receive = untagged (pass)".  The native VLAN on
  the members as well: "MGMT IS a member of the trunk and native
  VLANs: Transmit = tagged (pass) Receive = untagged (pass - mapped
  to MGMT)".

### Not established from a vendor's page

- **Arista EOS**: the answer itself, for any native VLAN, in either
  direction.  A device would settle it; reading has not.
- **IOS-XE and NX-OS**: a vendor's sentence for a native VLAN other
  than 1.  What is written above for that case is an inference, and
  Cisco's command reference has two phrases against it.
- **Junos, ELS**: that an untagged frame is dropped when the unit is
  not a member (the requirement is printed, the consequence is not);
  the send direction; whether `vlan members all` takes the native
  VLAN in.
- **Junos, older grammar**: anything beyond the one archived article.
- **OS10**: what `no switchport access vlan` leaves a trunk with --
  no untagged VLAN, or VLAN 1.  Dell's pages do not agree (D6).  And
  the text of the refusal D2 implies: no page shows it.
- **AOS-S**: a vendor's sentence for the send direction.  HPE's
  examples assume it.  Whether a port's membership of the default
  VLAN is tagged or untagged: H7's two sentences say that all ports
  are assigned to it and remain in it, and no more.  And what a
  trunk group (`Trk<n>`), or a port once it is in one, is in by
  default: H7's sentences speak of ports, and none was found for
  either.
- **OS10**: the id of "the default VLAN ID of the switch" (D5) for a
  given switch.  It is a setting, and no trunk's stanza states it;
  the codec fills nothing in.
- **Every platform that has a default native VLAN**: its form for a
  trunk that is to carry NO VLAN untagged.  None has been read.
- **Every platform**: what its CLI does on entry when one statement
  meets the other, and what happens to control and spanning-tree
  traffic of a native VLAN other than 1 that is off the list.

### Mapping notes

- A parser of a `LIST_DECIDES` platform puts the list its text
  states, and its renderer writes the list as it stands: a native
  line beside a list that leaves the VLAN out is text these platforms
  print, and it comes back as it went.
- The OS10 parser adds the trunk's access VLAN to the list
  (`access vlan 1` beside `allowed vlan 32,34` is native 1 and the
  list `1,32,34`), and its renderer writes the allowed line without
  the native VLAN, so no VLAN is on both lines (D2).  The AOS-S
  parser puts the VLAN a port is untagged in into the port's list,
  as HPE's own side-by-side does (H6).
- So an AOS-S or OS10 trunk that carries an untagged VLAN is written
  for IOS-XE, NX-OS, EOS, AOS-CX and Junos with that VLAN on the
  allowed line beside the native line.  That is what the vendor asks
  for on AOS-CX, on IOS-XE and NX-OS for VLAN 1, and in the Junos ELS
  grammar; for another VLAN on IOS-XE and NX-OS it follows the
  inference above; on EOS its effect is not established.
- The other way, a native VLAN the source's list leaves out is not
  carried by the source trunk as the tree reads it.  AOS-S is written
  no `untagged` for it, and a `review:` line in that VLAN's stanza
  that says so.  For a port the line says what H7's two sentences
  say of one, and no more: it is in the default VLAN, and remains
  there until it is removed.  For a trunk group, and for a port the
  same output puts on a `trunk` line, it says that what such a name
  is in by default is not established.  OS10 is written `no
  switchport access vlan` under a `review:` line, because Dell's
  pages do not agree on what that line leaves (D6).  Neither line
  calls the VLAN the source's: its id is the output's.
- A VLAN map does not turn "stated and not carried" into "carried".
  Where it would bring a native VLAN that the list leaves out INTO
  the list, the rename pass asks which ids of the list the map puts
  on the native VLAN's id.  One that the list names as a VLAN -- a
  VLAN of the config, or any id of a short allowed list -- is a
  VLAN the trunk carried tagged, and the two have been merged: the
  native VLAN is cleared.  Where none is -- the list is a range
  written around the native VLAN (`native vlan 1000` beside `allowed
  vlan 2-999,1001-4094`), and the new id is a number the range
  covers -- nothing was merged: the new id is taken out of the list
  and the native VLAN is kept.
- The Junos codec writes the ELS grammar only.  On a switch that
  takes the older grammar the native VLAN belongs OFF `vlan members`
  (J4): an output of this codec is not for such a switch as it
  stands.  The Junos parser reads `port-mode trunk` as it reads
  `interface-mode trunk` and does not read `native-vlan-id` under the
  unit, so a trunk in the older grammar loses its native VLAN on the
  way in.
- A trunk that states no native VLAN has its platform's default in
  the tree (the second table), where that default is an id: the
  parsers of IOS-XE, NX-OS, EOS and AOS-CX put `trunk_native_vlan =
  1` for a trunk whose list holds VLAN 1 -- the list names it, or the
  trunk states no list, which is every VLAN (C4, N3, A1, H8).  Where
  the list leaves VLAN 1 out nothing is filled in.  That is a native
  VLAN outside its list, which the first table of this section is
  about: for VLAN 1, no user traffic on IOS-XE (C4) and data traffic
  blocked on NX-OS (N3) by Cisco's sentences, not forwarded on AOS-CX
  by HPE's (H4, H5), and for EOS not established.  In the tree
  "stated and not carried" is kept for a native line the config HAS,
  so such a trunk has `trunk_native_vlan` unset, and an unset
  `trunk_native_vlan` in a tree a parser made says that the tree
  reads the port as carrying no VLAN untagged, as far as the text and
  the platform's default go.  Junos has no default (J2) and OS10's is
  not an id the text gives (D5): those two parsers fill nothing in.
- The default is a TRUNK's, like the list of the first section, and
  is put only for a port that SAYS it is a trunk: `switchport mode
  trunk`, or on AOS-CX a `vlan trunk` line, which is how a trunk is
  stated there.  A port in another mode that keeps trunk lines
  (IOS-XE), and a port the NX-OS and EOS parsers take for a trunk
  from a trunk line with no mode line, are given none: the default
  mode of a port is not trunk on any of these platforms (C2, N2,
  A1), and A1 says such a line has no effect on an access port.
- Junos, OS10 and AOS-S are then written VLAN 1 untagged for such a
  trunk (`native-vlan-id 1` with the port a member of VLAN 1;
  `switchport access vlan 1` with VLAN 1 off the allowed line;
  `untagged`), and AOS-CX `vlan trunk native 1`.  Where the trunk is
  every VLAN the Junos output is `vlan members all` beside
  `native-vlan-id 1`, and whether `all` takes the native VLAN in is
  not established (above): J3 asks for the unit to be a member of
  the native VLAN, and its example names the VLAN.  IOS-XE, NX-OS and
  EOS are written NO native line for VLAN 1 on a trunk whose list
  holds it: it is their default (C4, N3, A1), and no real capture of
  the three prints the line.  A native VLAN 1 the list leaves out is
  written, being stated and not carried.
- The default trunk's VLAN 1 has a record in the tree, with the
  trunk as its untagged member, and every renderer writes a `vlan`
  line for every VLAN of the tree.  So an IOS-XE or EOS output has a
  `vlan 1` line for such a source, though no real capture of either
  platform prints one.  No sentence quoted on this page says what
  either switch does with a `vlan 1` line, or that VLAN 1 is there
  without one: nothing is claimed for it.
- Nothing is filled in under the words that say a native VLAN is
  sent tagged (`vlan dot1q tag native`; `switchport trunk native
  vlan tag`).  Those words are not read into the tree.
- The other way is not mended.  A port that carries no VLAN untagged
  (a Junos trunk with no `native-vlan-id`: J2) is written for IOS-XE,
  NX-OS, EOS and AOS-CX as a trunk with no native line, and where
  its list holds VLAN 1 the target's default makes VLAN 1 its
  untagged VLAN.  No form for "no untagged VLAN" is written, and
  none has been read from a vendor.
