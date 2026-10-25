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
the text of the page fetched that day.  The sources of a trunk that
carries no VLAN untagged (C6-C11, T1, N4, N5, N8, X1, A2, H9, H12,
H13, and H4's second example) were fetched on 2026-10-13 and matched
again against pages fetched on 2026-10-14.

| Platform | Where its text states the untagged VLAN | A native VLAN the list leaves out | That stands on | Row of the table |
|---|---|---|---|---|
| Cisco IOS-XE (Catalyst switches) | `switchport trunk native vlan`, a line of its own; the allowed line may name it or leave it out | VLAN 1, the default native VLAN: not carried for user traffic.  Another id: not carried, by inference | Cisco's sentence for VLAN 1 (C4).  For another id no Cisco sentence: an inference from Cisco's rule that a trunk is a member of the VLANs its list allows (C4), with which the community accounts found agree; two phrases of the command reference read the other way (C5) | `LIST_DECIDES` |
| Cisco NX-OS | `switchport trunk native vlan`, a line of its own | VLAN1, the default: data traffic blocked, control traffic goes on.  Another id: not carried, by inference | Cisco's sentence for VLAN1 (N3).  For another id no Cisco sentence: an inference from Cisco's definition of the allowed list (N3) | `LIST_DECIDES` |
| Arista EOS | `switchport trunk native vlan`, a line of its own | **not established** | nothing: Arista's sentences read both ways (A1), and no account of the case was found | `LIST_DECIDES`, for how the text is written and no more |
| Aruba AOS-CX | `vlan trunk native`, a line of its own | untagged frames dropped on receive; the native VLAN not forwarded | HPE's sentences (H4, H5, H6) | `LIST_DECIDES` |
| Junos, ELS grammar | `native-vlan-id` on the physical interface, beside the unit's `vlan members` | the unit has to have the native VLAN for untagged packets to be received; that a frame is dropped otherwise is not printed, and the send direction is not established | Juniper's requirement and its procedure (J3) | `LIST_DECIDES` |
| Junos, older grammar (`port-mode trunk`) | `native-vlan-id` under the unit, beside `vlan members` | carried untagged both ways -- and when the VLAN is ALSO on `vlan members`, sent TAGGED | one Juniper knowledge-base article for EX Series, read in an archived copy (J4); the statement's page (J5) | the parser reads it by itself: off the members it is put into the list, on them it is said in a row (see below) |
| Dell OS10 | the trunk's `switchport access vlan`; the allowed line names tagged VLANs | no such state: the access VLAN is carried, and cannot be on the allowed line as well | Dell's sentences (D3, D4); one Dell article for "cannot" (D2) | `BESIDE_THE_LIST` |
| Aruba AOS-S | a VLAN's `untagged <ports>` line; there is no allowed list | no such state: the port carries the VLAN that lists it untagged | HPE's sentences for receive (H7); HPE's examples for send (H6) | none: it is told VLAN by VLAN |

And when the config states no untagged VLAN at all (the rows of
`TRUNK_THAT_STATES_NO_NATIVE` in the same module; AOS-S is not in it,
being told VLAN by VLAN), and the form each target is written for a
trunk that is to carry NO VLAN untagged and whose list holds that
default (`wants_no_untagged_vlan`, same module):

| Platform | A trunk that states no native VLAN | Source | Written for a trunk that carries no VLAN untagged, its list holding VLAN 1 | Source |
|---|---|---|---|---|
| Cisco IOS-XE | native VLAN 1 | C4 | `vlan dot1q tag native`, a line for every 802.1Q trunk of the switch, where no port the check reads blocks it: no port in trunk mode carries a VLAN untagged, and no port is in a mode no mode line is written for (dynamic, private-vlan, dot1q-tunnel, fex-fabric and the like) or holds trunk lines in no mode (`every_native_vlan_tagged`; a port with no mode and no trunk line is not counted); otherwise no native line, under a `! review:` line | C7, C8 |
| Cisco NX-OS | the default VLAN, which the same page names VLAN1: native VLAN 1 | N3 | the same | N4 |
| Arista EOS | native VLAN 1 | A1 | `switchport trunk native vlan tag` -- for the receive half; what is sent is not on Arista's page | A2 |
| Aruba AOS-CX | native VLAN 1 | H8 | `vlan trunk native 1 tag` | H9, H4 |
| Junos | none: untagged packets are dropped | J2 | nothing: no `native-vlan-id` is that form | J2 |
| Dell OS10 | the switch's default VLAN, whose id is a setting (`default vlan-id`) that no trunk states | D5, D8 | `no switchport access vlan` after `switchport mode trunk`, under a `! review:` line -- for every trunk with no native VLAN, whatever its list holds, but one of an interface another record of which states its untagged VLAN (a native VLAN, or an access VLAN), which the line would take back: the default is no id, so whether the list holds it cannot be asked.  Dell's pages disagree on what the line leaves a trunk with (D6, D7), and the review line says so; where the allowed line holds VLAN 1 it says too that no Dell page shows that | D5, D6, D7 |
| Aruba AOS-S | a port is in the default VLAN (VID 1) in the factory default configuration, and remains in it until it is removed; tagged or untagged is not in the sentences.  A new trunk group is placed in it, and a static one is configured for VLAN membership as a port is | H7, H15 | `no untagged <names>` in VLAN 1's stanza, after `name` and before the lists (the order of HPE's examples from 15.14 on, H14), for every name the output tags in some VLAN, lists untagged in none and names on no line of VLAN 1; a trunk that carries VLAN 1 tagged is `tagged` there, in a `vlan 1` stanza of its own where the tree has no VLAN 1 record.  A trunk that carries nothing has no form: a port is a member of at least one VLAN (H16) | H7, H14, H16 |

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
- **C6** -- Cisco, *Command Reference, Cisco IOS XE Dublin 17.12.x
  (Catalyst 9500 Switches)*, Layer 2/3 Commands, `switchport trunk`:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-12/command_reference/b_1712_9500_cr/layer_2_3_commands.html>
  (the same in the 17.3 and 17.18 editions).  The one per-port form:
  "The keyword native vlan tag is supported only on Cisco Catalyst
  9500 Series Switches - High Performance."; "Enables native VLAN
  tagging on a particular trunk port."; and "vlan dot1q tag native
  global command needs to be enabled to execute the switchport trunk
  native vlan tag command."  The 9500 models filed as High
  Performance are the C9500-32C, -32QC, -24Y4C and -48Y4C (C13).
- **C7** -- Cisco, the C5 page (*Command Reference, Cisco IOS XE
  Dublin 17.12.x (Catalyst 9300 Switches)*, VLAN Commands), `vlan
  dot1q tag native`: "To enable tagging of native VLAN frames on all
  IEEE 802.1Q trunk ports, use the vlan dot1q tag native command in
  global configuration mode."  Its default: "The IEEE 802.1Q native
  VLAN tagging is disabled."  And: "When enabled, native VLAN packets
  going out of all IEEE 802.1Q trunk ports are tagged."  The 9300's
  `switchport trunk` takes no `tag` keyword, in this chapter or in
  its Layer 2/3 Commands chapter.
- **C8** -- Cisco, *Layer 2 Configuration Guide, Cisco IOS XE Dublin
  17.12.x (Catalyst 9300 Switches)*, Configuring IEEE 802.1Q
  Tunneling:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/lyr2/b_1712_lyr2_9300_cg/configuring_ieee_802_1q_tunneling.html>.
  On receive, section "Native VLANs": "If the switch is configured to
  tag native VLAN packets on all IEEE 802.1Q trunks, the switch drops
  untagged packets, and sends and receives only tagged packets."  And
  of a port's mode: "By default, IEEE 802.1Q tunneling is disabled
  because the default switchport mode is dynamic auto. Tagging of IEEE
  802.1Q native VLAN packets on all IEEE 802.1Q trunk ports is also
  disabled."  **C9**, the Catalyst 9500 edition of the same chapter
  (`.../catalyst9500/software/release/17-12/configuration_guide/lyr2/b_1712_lyr2_9500_cg/configuring_ieee_802_1q_tunneling.html`),
  has the same receive sentence.
- **C10** -- Cisco, *Layer 2 Configuration Guide, Cisco IOS XE Dublin
  17.12.x (Catalyst 9500 Switches)*, Configuring VLAN Mapping:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/software/release/17-12/configuration_guide/lyr2/b_1712_lyr2_9500_cg/configuring_vlan_mapping.html>.
  The per-port way out of the global line, for a 9500 High
  Performance model: "If the native VLAN tagging global command is
  enabled on the switch, you should disable the tagging of native
  VLAN packets on the QinQ enabled trunk ports using the command no
  switchport trunk native vlan tag command."
- **C11** -- Cisco, *Security Configuration Guide, Cisco IOS XE Dublin
  17.12.x (Catalyst 9300 Switches)*, Configuring IEEE 802.1x
  Port-Based Authentication, restrictions:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-12/configuration_guide/sec/b_1712_sec_9300_cg/configuring_ieee_802_1x_port_based_authentication.html>.
  "If the dot1q tag vlan native command is configured globally, the
  dot1x reauthentication will fail on trunk ports."  (The words are
  Cisco's, in that order.)
- **C13** -- Cisco, *Cisco Catalyst 9500 Series Switches Hardware
  Installation Guide*, Product Overview, the switch-models table:
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9500/hardware/install/b_catalyst_9500_hig/9500_product-overview.html>.
- **T1** -- Cisco TechNote 217726, *Configure and Troubleshoot QinQ
  and L2PT on Catalyst 9000 Switches* (updated September 17, 2024):
  <https://www.cisco.com/c/en/us/support/docs/switches/catalyst-9300-switch/217726-configure-and-verify-and-troubleshoot-qi.html>.
  "The vlan dot1q tag native enables 802.1Q native VLAN to be tagged
  on all trunk interfaces by default, but this can be disabled at the
  interface level with no switchport trunk native vlan tag
  configuration."  A TechNote, not a guide or a command reference,
  and its lab is a C9500-12Q, which C13 does not file as a High
  Performance model.
- **N4** -- Cisco, the N3 page (*Cisco Nexus 9000 Series NX-OS
  Interfaces Configuration Guide, Release 10.6(x)*, Configuring
  Layer 2 Interfaces).  "This configuration is global; trunk ports on
  the device either do or do not retain the tagging for the native
  VLAN."  "The vlan dot1q tag native global command changes the
  behavior of all native VLAN ID interfaces on all trunks on the
  device."  Sent: "With vlan dot1Q tag native enabled, untagged
  frames will have a native VLAN tag added to transmitted frames."
  Received, under the command's step: "Modifies the behavior of a
  802.1Q trunked native VLAN ID interface. The interface maintains the
  taggings for all packets that enter with a tag that matches the
  value of the native VLAN ID and drops all untagged traffic. The
  control traffic is still carried on the native VLAN."  And of the
  neighbour: "Therefore, it is recommended to have the vlan dot1q tag
  native command disabled in case the connected switch does not have
  it configured."
- **N5** -- Cisco, the same 10.6(x) guide, Configuring Q-in-Q VLAN
  Tunnels:
  <https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-106x/m_configuring_q-in-q_vlan_tunnels_9x.html>.
  Section "Native VLAN Hazards": "If the switch is configured to tag
  native VLAN packets on all 802.1Q trunks, the switch accepts
  untagged packets but sends only tagged packets."  Against it, the
  same chapter's "Guidelines and Limitations for Q-in-Q Tunneling and
  Layer 2 Protocol Tunneling": "You should enter the vlan dot1Q tag
  native command to maintain the tagging on the native VLAN and drop
  untagged traffic."
- **N8** -- Cisco, the same 10.6(x) guide, Configuring vPCs, section
  "Configuration Parameters That Must Be Identical":
  <https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/106x/configuration/interfaces/cisco-nexus-9000-series-nx-os-interfaces-configuration-guide-release-106x/m_configuring_vpcs_9x.html>.
  The parameters that "must be configured identically on both devices
  of the vPC Peer-Link" include, under "Trunk mode per channel:",
  "Native VLAN", "VLANs allowed on trunk" and "Tagging of native VLAN
  traffic".
- **X1** -- Cisco, *Cisco Nexus 7000 Series NX-OS Interfaces Command
  Reference*, V Commands, `vlan dot1q tag native`, a Nexus 7000 page:
  <https://www.cisco.com/c/en/us/td/docs/switches/datacenter/nexus7000/sw/interfaces/command/cisco_nexus7000_interfaces_command_ref/v_commands.html>.
  Of `exclude control`: "Excludes untagged control traffic on the
  native VLAN in a trunk."
- **A2** -- Arista, the A1 page (*EOS User Manual*, Virtual LANs
  (VLANs), titled "EOS 4.36.2F"), entry `switchport trunk native
  vlan`, whose one argument is a VLAN number or `tag`: "Trunk mode
  interfaces can also be configured to drop untagged frames.", and of
  the option: "tag interface drops all untagged frames."  The `no` and
  `default` forms "restore vlan 1 as the trunk mode native VLAN".  No
  sentence of the page speaks of frames the interface SENDS under
  `tag`, and the VLAN chapter lists no line for every trunk.
- **H9** -- HPE, the H4 guide, `vlan trunk native tag`:
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/l2_bridging_6300-6400/Content/Chp_vlans/vlan_cmds/vla-tru-nat-tag.htm>.
  "Enables tagging on a native VLAN."  "Only incoming packets that are
  tagged with the matching VLAN ID are accepted. Incoming packets that
  are untagged are dropped except for BPDUs. Egress packets are
  tagged."  "The no form of this command removes tagging on a native
  VLAN."  And H4's "Example 2: Native tagged VLAN": "An ingress
  untagged frame arrives on interface 1/1/13. The switch drops this
  frame since the interface is configured as native tagged (all
  untagged frames a dropped in such a configuration)."
- **H12** -- HPE, the same guide, "Assigning a native VLAN ID to a
  trunk interface":
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/l2_bridging_6300-6400/Content/Chp_vlans/asi-nat-vla-id-tru-int.htm>.
  "Allow traffic tagged with the native VLAN ID to be transported by
  the trunk using the command vlan trunk allowed."
- **H13** -- HPE, the same guide, "Assigning a VLAN ID to a trunk
  interface":
  <https://arubanetworking.hpe.com/techdocs/AOS-CX/10.16/HTML/l2_bridging_6300-6400/Content/Chp_vlans/asi-vla-id-tru-int.htm>.
  "With trunk configuration, when native membership is not specified,
  the port automatically becomes a native member of VLAN 1."
- **H14** -- HPE, the order of lines in a printed `vlan 1` stanza
  (examples, no sentence).  Full configs created on K.14.54C to
  K.15.10 print `no untagged` last: `name`, `untagged`, `ip address`,
  [`tagged`], `no untagged` (*Basic Operation Guide for AOS-S 16.10*
  pp.88, 113; *2930F / 2930M Management and Configuration Guide 16.09*
  p.150).  Configs created on YB.15.14, KA.15.18 and every 16.x
  release shown (WC.16.02, WC.16.05, KB.16.04), and the 2930F
  (JL254A / JL255A) examples that name no release, print it first:
  `name`, `no untagged`, `untagged`, `ip address` (the 2930F/M guide
  16.09 pp.554, 566; *3810 / 5400R Management and Configuration Guide
  16.09* p.348; *2930F / 2930M Multicast and Routing Guide 16.09*
  pp.26, 167; *3810M / 5400R Multicast and Routing Guide 16.09*
  pp.45, 140, 427-434; *2930F / 2930M Access Security Guide 16.09*
  p.671).  The guides:
  <https://arubanetworking.hpe.com/techdocs/AOS-Switch/16.10/Aruba%20Basic%20Operation%20Guide%20for%20AOS-S%20Switch%2016.10.pdf>,
  <https://www.arubanetworks.com/techdocs/AOS-Switch/16.09/Aruba%202930F%20_%202930M%20Management%20and%20Configuration%20Guide%20for%20ArubaOS-Switch%2016.09.pdf>,
  <https://www.arubanetworks.com/techdocs/AOS-Switch/16.09/Aruba%203810%20_%205400R%20Management%20and%20Configuration%20Guide%20for%20ArubaOS-Switch%2016.09.pdf>,
  <https://www.arubanetworks.com/techdocs/AOS-Switch/16.09/Aruba%202930F%26M%20Multicast%20and%20Routing%20Guide%20for%20AOS-S%20Switch%2016.09.pdf>,
  <https://www.arubanetworks.com/techdocs/AOS-Switch/16.09/Aruba%203810M%265400R%20Multicast%20and%20Routing%20Guide%20for%20ArubaOS-Switch%2016.09.pdf>,
  <https://www.arubanetworks.com/techdocs/AOS-Switch/16.09/Aruba%202930F%26M%20Access%20Security%20Guide%20for%20AOS-S%20Switch%2016.09.pdf>.
  In every full config HPE's 16.09-16.11 guides print, a port that
  another VLAN names is on one of `vlan 1`'s lines, and those lines
  never share a port; a per-interface view
  (`show config interface <ports>`) prints a removed port with no
  line for VLAN 1.  Where a 16.x switch prints a `tagged` line in
  `vlan 1` no HPE example shows.  The committed AOS-S
  captures of WC.16.07, WC.16.10 and WC.16.11 print the second order.
- **H15** -- HPE, *Aruba 2930F / 2930M Management and Configuration
  Guide for ArubaOS-Switch 16.09* (5200-5906a, February 2020),
  pp.130, 131, 134, 141, 145:
  <https://www.arubanetworks.com/techdocs/AOS-Switch/16.09/Aruba%202930F%20_%202930M%20Management%20and%20Configuration%20Guide%20for%20ArubaOS-Switch%2016.09.pdf>;
  the same sentences in its 16.11 HTML edition (topics `sta-tru`,
  `vla-dyn-lac`,
  `https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/WC/content/common%20files/<topic>.htm`),
  in the 3810 / 5400R guide 16.09 and in the 2530 edition.  "Creating
  a new trunk automatically places the trunk in the DEFAULT_VLAN,
  regardless of whether the ports in the trunk were in another VLAN."
  "You can configure a static trunk in the same way that you configure
  a port for membership in any VLAN."  "For spanning-tree or VLAN
  operation, configuration for all ports in a trunk is done at the
  trunk level."  "A dynamic LACP trunk operates only in the default
  VLAN (unless you have enabled GVRP on the switch and use Forbid to
  prevent the ports from joining the default VLAN)."  p.134's table
  has "TrkX (Static)" and "DynX (Dynamic)", and `trunk < port-list > <
  trk1 ... trk60 > {<trunk | lacp>}` "Configures the specified static
  trunk type."  The groups netcanon writes are `Trk<n>`, the static
  kind, so the limit of a dynamic LACP trunk does not bear on them.
- **H16** -- HPE, *AOS-S 16.11 Advanced Traffic Management Guide*,
  HTML (2530), "VLAN operating notes"
  (`https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/ATMG/YAYB/content/common%20files/vla-ope-not.htm`):
  "Also, a port must always be a tagged or untagged member of at least
  one port-based VLAN."  And the H7 guide, p.54: "You can remove all
  ports from the default VLAN by placing them in another port-based
  VLAN, but this VLAN remains and cannot be deleted from the switch."
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
- **D7** -- Dell, *SmartFabric OS10 User Guide*, Releases 10.5.5,
  10.5.6, 10.6.0 and 10.6.1 (the same text in each), VLAN stacking,
  "Configuration notes"
  (`.../configuration-notes?guid=guid-fbdee4bf-6cdb-41cc-836c-f119901fdf70&lang=en-us`):
  "Configure the ports between the PE and Provider Core as pure trunk
  ports without any access VLAN membership. This configuration is to
  drop any untagged or tagged (with other than configured TPID)
  traffic on those ports."  The same chapter's "Configure trunk port"
  (the D6 procedure) reaches that state with step "7. Remove access
  VLAN membership." -- `no switchport access vlan`.  And `switchport
  trunk tpid`: "The action that is taken on untagged packets is based
  on the port access membership."  The note is written for a VLAN
  stacking port, which has a TPID as well; it is general in form.
  Against it stands D6's command page ("... to VLAN 1").
- **D8** -- Dell, the same guides, `default vlan-id`
  (`.../default-vlan-id?guid=guid-966d250a-d5e0-471b-8fe0-c6d00d6f3e64&lang=en-us`):
  "Reconfigures the VLAN ID of the default VLAN."; Default "VLAN1";
  "The command reconfigures the access VLAN ID, the default VLAN, of
  all ports in Switchport Acess mode." (Dell's spelling).  No sentence
  says what the command does to a trunk (its Usage Information names
  trunks only in "By default, VLAN1 serves as the default VLAN for
  switching untagged L2 traffic on OS10 ports in Trunk or Access
  mode.").  No Dell example prints the line as configuration --
  the command's own example cuts its `show running-configuration` at
  "..." -- and no committed capture has it: the codec does not read
  it.
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
- **J5** -- Juniper, *native-vlan-id*, the configuration statement for
  EX Series switches, Junos OS 13.2:
  <https://juniper.net/documentation/en_US/junos13.2/topics/reference/configuration-statement/native-vlan-id-bridging.html>.
  Syntax `native-vlan-id vlan-id;` at `[edit interfaces
  interface-name unit 0 family ethernet-switching]`, "Statement
  introduced in Junos OS Release 9.0 for EX Series switches";
  "Configure the VLAN identifier to associate with untagged packets
  received on the interface"; the option is "Numeric identifier of
  the VLAN", range 0 through 4095.  The page says nothing of the
  trunk's members.

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
- **Junos, older grammar**: anything beyond the one archived article
  and the statement's page; whether the statement takes a VLAN's name
  (J5 names a number only, and the parser reads a number only).
- **OS10**: what `no switchport access vlan` leaves a trunk with --
  no untagged VLAN, or VLAN 1.  Dell's pages do not agree: the
  command page says VLAN 1 (D6), the VLAN-stacking notes describe the
  trunk the same line makes as one "without any access VLAN
  membership" that drops untagged traffic (D7).  And the text of the
  refusal D2 implies: no page shows it.  Nor does any Dell example
  put VLAN 1 on the allowed line of a trunk, with an access VLAN or
  without.
- **AOS-S**: a vendor's sentence for the send direction.  HPE's
  examples assume it.  Whether a port's membership of the default
  VLAN is tagged or untagged: H7's two sentences say that all ports
  are assigned to it and remain in it, and no more.  That a static
  trunk group's own membership of the default VLAN is untagged: H15
  says it is placed there, and one HPE example (K.15.10; *Basic
  Operation Guide for AOS-S 16.10* pp.112-113, H14) prints a `Trk1`
  on `vlan 1`'s `untagged` line.  An HPE-printed full config
  with `no untagged Trk<n>`: the line is in HPE's hand-written
  listings only.  And where a 16.x switch prints a `tagged` line in
  `vlan 1` (H14).
- **OS10**: the id of "the default VLAN ID of the switch" (D5) for a
  given switch.  It is a setting (D8), and no trunk's stanza states
  it; the codec fills nothing in, and does not read `default
  vlan-id`, which no Dell example prints as configuration.  What a
  trunk's untagged VLAN becomes when that id is changed: the sentence
  of D8 on what the command reconfigures names access ports only.
- **A trunk that is to carry NO VLAN untagged.**  Each platform with
  a default native VLAN has a form for it (C6-C8, N4, A2, H9), and
  these parts of them are not established:
  - *EOS*: what an interface under `tag` sends for its native VLAN,
    which VLAN is native while `tag` is set, and whether EOS has a
    line for every trunk (none in its VLAN chapter).  A2 has the
    receive half only.
  - *NX-OS*: what the line for every trunk does with an untagged frame
    it receives -- Cisco's pages disagree (N4 and N5's guideline:
    dropped; N5's "Native VLAN Hazards": accepted).  The send half is
    settled: tagged.  Its default in 10.x (no 10.x page prints one),
    and whether `exclude control` exists on a Nexus 9000 (X1 is a
    Nexus 7000 page).
  - *IOS-XE*: what control traffic does under the line for every
    trunk, on a Catalyst 9300 or 9500.  And the per-port form of the
    9500 High Performance models (C6): its default under the line, and
    how a running config prints it, rest on a TechNote whose lab is
    not such a model (T1).
  - *AOS-CX*: how a switch prints `vlan trunk native N tag` in its
    running config.  HPE's examples show it typed; the committed
    captures print one line beside `vlan trunk allowed all`, in two of
    Aruba's published sample configurations and in two configurations
    made by tools.
  - *OS10*: what `no switchport access vlan` leaves a trunk with
    (above).  *AOS-S*: whether the order of VLAN 1's lines matters to
    a switch when a config is typed or downloaded (the output is
    written in the order of HPE's examples from 15.14 on; older
    examples print `no untagged` last): the lists share no port, so
    neither order takes out what another line put in (an inference,
    H14).
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
  that says so.  Where VLAN 1's `no untagged` line takes the name out
  of the default VLAN (the port is tagged elsewhere: the last bullet
  of these notes) the line says that, and no more.  Otherwise, for a port
  it says what H7's two sentences say of one: it is in the default
  VLAN, and remains there until it is removed; for a trunk group,
  and for a port the same output puts on a `trunk` line, it gives
  H15: a new trunk group is placed in the default VLAN, and a static
  one is configured as a port is.  OS10 is written `no
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
  `interface-mode trunk`, and reads `native-vlan-id` under the unit by
  the older grammar's own rule (J4): a native VLAN off the members is
  the trunk's native VLAN and is put into its list; one on the
  members as well -- received untagged and sent tagged, which the
  tree has no form for -- is said in a row, and the VLAN stays on the
  list, tagged.  So is one on a port that is not a trunk, one beside
  a `native-vlan-id` on the interface itself, and one that is not a
  VLAN id (1 to 4094).
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
- Under the words that say a native VLAN is sent tagged the trunk
  carries NO VLAN untagged, and has no native VLAN in the tree: not
  the default, and not one it states.  The words are `vlan dot1q tag
  native`, with `exclude control` or without (IOS-XE, NX-OS; the EOS
  parser reads them as well), `switchport trunk native vlan tag`, and
  on AOS-CX `vlan trunk native N tag` (H9, H4).  An IOS-XE or NX-OS
  trunk that states `no switchport trunk native vlan tag` leaves the
  line for every trunk, and has the default again (C10, T1).  On EOS
  the id and `tag` are one argument, so the one met last stands.  The
  id of a native VLAN sent tagged is not kept.  By HPE's sentences
  such an AOS-CX trunk accepts only tagged frames and tags what it
  sends, so `native 20 tag` and `native 1 tag` beside one list carry
  the same VLANs (H12 asks for the native VLAN to be on the list for
  its traffic to pass): it comes back as `vlan trunk native 1 tag`
  where its list holds VLAN 1, and with no native line where it does
  not.
- A trunk that carries no VLAN untagged and whose list holds VLAN 1
  is written each target's form for that, since written no native
  line it would carry VLAN 1 untagged there by the target's default
  (the table above).  AOS-CX: `vlan trunk native 1 tag`, before the
  allowed line, which HPE's sentences give both directions of (H9).
  EOS: `switchport trunk native vlan tag`; Arista's sentence is that
  the interface then drops all untagged frames (A2), and what it
  sends for VLAN 1 is not established.  IOS-XE and NX-OS: the one
  form documented for both the Catalyst 9300 and the Nexus 9000 is
  `vlan dot1q tag native`, which tags the native VLAN of EVERY trunk
  (C7, N4).  So it is written, once, before the VLANs and the
  interfaces, where no port the check reads blocks it.  The check
  reads the ports written in trunk mode, the ports with trunk lines
  and no mode, and the ports in a mode no mode line is written for
  (dynamic, private-vlan, dot1q-tunnel, fex-fabric and the like):
  the line is written where no trunk of the output carries a VLAN
  untagged, and no port is in such a mode or holds trunk lines in no
  mode.  A port written with no mode and no trunk line is not
  counted: on a Catalyst such a port is in dynamic auto by default
  (C8), and should it become a trunk the line tags its native VLAN
  as well (C7).  Otherwise each such trunk is written no native
  line and a `! review:` line where the native line would be, which
  says that the trunk carries no VLAN untagged in the translated
  config, that on this platform a trunk with no native line has
  native VLAN 1, and that the line that would tag it tags every
  trunk.  The per-port form of the Catalyst 9500 High Performance
  models (C6) is not written: it needs the line for every trunk, and
  knowing that the target is such a model.  On IOS-XE the line for
  every trunk has a side effect Cisco documents: the dot1x
  reauthentication of trunk ports fails (C11).  On NX-OS Cisco
  recommends leaving it off where the neighbour does not have it
  (N4), and lists "Tagging of native VLAN traffic" among the
  parameters that must be configured identically on both vPC peers
  (N8); the line is decided for one output at a time, so the outputs
  of two vPC peers translated apart can differ, one with the line and
  the other with review lines -- compare them.
- A list that leaves VLAN 1 out needs no form: the default native
  VLAN is then off the list, which is how a native VLAN that is not
  carried is written (the first table).  A record of an interface
  whose other stanza states a native VLAN is given none either.
- OS10 and AOS-S have a default for a port that the output gives no
  untagged VLAN as well, and are written their form for "no VLAN
  untagged" by asking another question.  OS10's default is the
  switch's default VLAN (D5), an id no text gives (D8), so no "does
  the list hold it" can be asked: every trunk the tree gives no
  native VLAN -- whatever its list, the empty one included -- is
  written `no switchport access vlan` after `switchport mode trunk`
  (but not one of an interface another record of which states its
  untagged VLAN, a native VLAN or an access VLAN, which the line
  would take back), the line with which D6's procedure reaches D7's
  "pure trunk ports without any access VLAN membership", under a
  `! review:` line that says the
  pages disagree (D6, D7) and, where the allowed line holds VLAN 1,
  that no Dell page shows that.  The parser reads the line and its
  absence as one tree, so an OS10 trunk with neither comes back with
  it.  AOS-S is asked VLAN by VLAN, of the member lists the output is
  written from: a name some VLAN tags, none lists untagged, and no
  line of VLAN 1 names stays in the DEFAULT_VLAN (H7), so VLAN 1's
  stanza says `no untagged` for it, after `name` and before the
  lists (H14's later order); a trunk that carries VLAN 1 tagged, in a
  tree with no VLAN 1 record (a trunk of every VLAN is put only on
  the VLANs a tree declares), is written `tagged` in a `vlan 1`
  stanza written for it, first and with no `name` line.  The AOS-S
  parser reads a `no untagged` line above the lists as removing
  nothing, which on lists that share no port is the tree they came
  from.  A trunk that carries nothing has no AOS-S form (H16).

## A routed port's untagged frames: the native sub-interface

On a routed port whose sub-interfaces carry tags, both platforms can
name one sub-interface as the one that takes the frames that arrive
with no tag.  The tree states it on that sub-interface
(`CanonicalInterface.dot1q_native`), never as the port's
`trunk_native_vlan`, which is a switchport's.

| Platform | Form | Received untagged | Source |
|---|---|---|---|
| Cisco IOS-XE | `encapsulation dot1Q <tag> native` on the sub-interface | by that sub-interface | C-N1 |
| Juniper Junos | `native-vlan-id <tag>` on the device, with `flexible-vlan-tagging`, and the unit of `vlan-id <tag>` | by that unit | J-N1 |

### Sources

- **C-N1** — Cisco, *VLAN Configuration Guide, Cisco IOS XE Cupertino
  17.7.x (Catalyst 9400 Switches)*, "Configuring Layer 3
  Subinterfaces":
  <https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-7/configuration_guide/vlan/b_177_vlan_9400_cg/configuring_layer_3_subinterfaces.html>.
  Says: `encapsulation dot1q vlan-id [native]`; "native: To make a
  subinterface the default handler of untagged packets coming to the
  port, use this keyword"; "For a given physical interface, only one
  subinterface can have the encapsulation as native"; no IP address
  configuration is supported on the physical interface when one of
  its subinterfaces is native; the keyword is not supported on the
  Catalyst 9600X.
- **J-N1** — Juniper, "Configuring Tagged Interface with multiple
  tagged vlans and native vlan":
  <https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/task/tagged-interfaces-with-multiple-tagged-native-vlan.html>.
  Says: "To accept untagged packets, include the native-vlan-id
  statement and the flexible-vlan-tagging statement"; "The logical
  interface on which untagged packets are to be received must be
  configured with the same native VLAN ID".

### Not established from a vendor's page

- What either sub-interface SENDS without a tag.  Neither page above
  says; a Junos 12.3 page for the statement said the tag is popped on
  egress, and the note is not in later releases.
- What Junos does with a `native-vlan-id` that names no unit: the
  parser leaves such a statement out with a row.

### Mapping notes

The Junos parser reads `native-vlan-id` as the device's native unit
only on a device that is not a switchport (no `family
ethernet-switching` mode); on an ELS trunk it is the trunk's native
VLAN, as above.  The IOS-XE parser keeps `native` on the first
sub-interface of a port that says it and writes any other without it,
with a row.  Every other target reports
`/interfaces/interface/dot1q-native` unsupported: none of them writes
a form for it.
