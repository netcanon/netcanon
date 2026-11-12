# Aruba AOS-CX — What works for me?

If you operate modern Aruba (AOS-CX) switches — the 6300 / 6400 /
8320 / 8325 / 8400 class — and want to know what Netcanon does for
you, this is the page.

## TL;DR

- **`aruba_aoscx`** — `show running-config` text **bidirectional**
  (parse AND render).  **Certification: certified.**

AOS-CX is the modern Aruba NOS, **distinct from the legacy
`aruba_aoss`** (ProVision / AOS-Switch) codec — different grammar,
different codec, different `CapabilityMatrix`.  The codec targets the
AOS-CX 10.x surface: L2 switchport + VLAN port membership, `interface
lag N` LAGs, VRFs, `active-gateway` anycast (the VSX / EVPN
distributed gateway), and VXLAN L2VNI bindings.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, enabled state, MTU, IPv4 + IPv6
  addresses, VRF binding, and `ip mtu`, the IP MTU.  AOS-CX's IP MTU
  stays 1500 under a raised `mtu` unless `ip mtu` says otherwise
  (HPE: `ip mtu` "Default: 1500"), so a port with `mtu 9198` alone
  is an IP MTU of 1500 on every target, and a port another vendor
  sends jumbo IP packets on is written `ip mtu` here.  ⚠️ Up to 0.7.7
  `ip mtu` was not read: a VLAN interface's `ip mtu 9198` was an IP
  MTU of 1500 on every target.  See the [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/mtu.md).
  A VLAN interface (`interface vlan N`) and a loopback are up unless
  they say `shutdown`; a port, a LAG, `interface mgmt` and `interface
  vxlan` are down unless they say `no shutdown`.  AOS-CX prints the
  state of each of the latter whichever it is, and prints none under
  a VLAN interface that is up (inferred from its printout and HPE's
  own templates).  ⚠️ Up to 0.7.7 every VLAN interface was read as
  shut, and written so onto every target.
- L2 switchport — access / trunk mode, access-VLAN, trunk allowed-VLAN
  list, trunk native VLAN, `lag` membership
- VLANs — ID, name, description, tagged/untagged port lists, and an
  address held on the VLAN record (see Common gotchas)
- Static routes — of the global table and of a VRF (`ip route
  <destination> <next hop> [distance <n>] [vrf <name>]`, and `ipv6
  route`; see Common gotchas).  ⚠️ Up to 0.7.7 a route of a VRF was
  read as a route of the global table, and written so onto every
  target: the management default route (`vrf mgmt`) was the
  switch's default route.  Look for one in an old output.
- VRFs — name (a bare `vrf <name>` stanza in v1)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- LAGs (`interface lag N`, reconciled with cross-vendor names like
  `Port-channel<N>` / `ae<N>`)
- SNMP v2c community + v3 USM (community, location, contact, v3 users)
- Local users — named AOS-CX `group` (administrators / operators /
  auditors / custom) + `password ciphertext` blob
- VXLAN — VLAN↔VNI binding (`interface vxlan 1 / vni <VNI>` with
  nested `vlan <VLAN>`)

> **Management-plane caveat.**  When AOS-CX is the **target**, the
> codec renders no `ip domain-name` / `ip dns` / `ntp server` /
> `logging` / `dhcp-server` / `radius-server` config — those surfaces
> are declared `unsupported` (the live validation report flags the
> loss rather than reporting `severity: ok`).  See
> [What we don't do](#what-we-dont-do).

## L3 redundancy: active-gateway anycast

AOS-CX models the VSX / EVPN distributed gateway as `active-gateway`
under the SVI — an Arista-VARP-style anycast (a stable IP present on
every switch, no group ID):

```text
interface vlan 100
    ip address 10.1.100.2/24
    active-gateway ip mac 12:01:00:00:01:00
    active-gateway ip 10.1.100.1
```

Canonical mapping:

- `active-gateway ip <vip>` mirrors into
  `CanonicalIPv4Address.virtual_gateway_address`.
- `active-gateway ip mac <mac>` lands on
  `CanonicalIntent.anycast_gateway_mac`.

This co-exists with — and is the inverse of — classic FHRP: **VRRP**
(`vrrp <vrid> address-family` under an SVI) is a later phase and stays
`unsupported`; the `active-gateway` anycast surface IS the supported
distributed-gateway path.  **IPv6 active-gateway** parses-and-ignores
in v1 (parity with the NX-OS / IOS-XE IPv6-anycast deferral).

## Lossy paths

- **`/routing/static-route/description`** — render emits destination +
  next-hop only; the static-route name / description drops.
- **`/interfaces/interface/config/type`** — AOS-CX declares no IANA
  ifType; the codec infers it from the name shape (`1/1/1` →
  ethernetCsmacd, `vlan N` → l3ipvlan, `lag N` → ieee8023adLag,
  `loopback N` → softwareLoopback, `vxlan N` → tunnel).
- **`/local-users/user/privilege-level`** — the named `group` maps to
  numeric privilege (administrators → 15, else → 1) for cross-vendor
  targets; the named group round-trips losslessly same-vendor.  The
  `password ciphertext` blob is AES-encrypted with the device key
  (portable same-device only) — cross-vendor migration requires
  re-keying: such an account is left out on every other target, with
  a review line that names it.  The keyword decides, not the value's
  shape: `ciphertext` is ciphertext whatever it looks like (a
  published capture holds a placeholder word there), and `plaintext`
  is a password as typed, which arrives on every target that takes
  one (not Junos or OPNsense).
- **`/local-users/user/role`** — a local user's role is a name of the
  platform that defines it.  It is written as it stands only from a
  config of AOS-CX.  From another platform the account is given `group
  administrators` at privilege 15 and `group operators` below it,
  chosen from the privilege level; the source's role is not carried.
- **`/snmp/v3-user/auth-passphrase`** — SNMPv3 auth/priv keys are
  device-key `ciphertext` blobs; emitted verbatim cross-vendor but the
  operator must re-key on the target.
- **`/vxlan-vnis/source-interface`** — AOS-CX states the VTEP source
  as an IPv4 *address* (`interface vxlan 1 / source ip <X>`), not an
  interface name like NX-OS / Arista.  A cross-vendor source carrying
  an interface *name* has no AOS-CX `source ip` form, so the `source
  ip` line is omitted on render (the VLAN↔VNI bindings still emit).
- **`/system/raw-sections/version-banner`** — the `!Version
  ArubaOS-CX <release>` banner + management-plane service footer
  (`ssh server`, `https-server`, `clock`, `ntp`, `spanning-tree`) is
  discarded on parse; a synthesised banner is emitted on render.
- **`/interfaces/interface/{dhcp-client,dhcp-client-v6}`** — the codec
  reads and writes no DHCP client, IPv4 or IPv6: the interface is
  written without one (severity `warn`: the job says so and stays
  `completed`).

## What we don't do

**Surfaces AOS-CX render drops** (declared `unsupported` so the loss
is visible, not silent):

- **Management plane** — `domain`, `timezone`, DNS / NTP / syslog
  servers, DHCP server pools, RADIUS servers (host + secret), SNMP
  trap-hosts (`snmp-server host`)
- **VRF detail** — VRF description, route-distinguisher and
  route-target (these live under the deferred `evpn` / `router bgp`
  blocks; only the bare `vrf <name>` is wired)
- **VRRP** (FHRP) and **IPv6 active-gateway** — and so no field of
  either: a group's virtual IPs, tracked interfaces and virtual MAC,
  and the MAC of an IPv6 gateway
- **DHCP server pool fields** — no pool is written, so neither is its
  gateway, its DNS servers, its domain or its lease
- **VXLAN control plane** — per-VLAN L2VNI RD/RT (almost always
  `auto`-derived), symmetric-IRB **L3VNI** (`vni N / vrf <name>`) and
  EVPN Type-5 routes; the L2 VLAN↔VNI binding itself IS supported

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Routing protocols** — `router bgp` (incl. the EVPN
  address-family) / `router ospf` (surfaced on the
  `dropped_tier3_sections` banner; not auto-rendered)
- **ACLs** — standard / extended
- **QoS** — `class` / `policy` / `apply qos`
- **VSF** — a CX 6200's or 6300's stack lines (`vsf member` with
  its `type` and `link` lines, `vsf secondary-member`, `vsf
  split-detect`): each line is a row of the
  `dropped_tier3_sections` banner.  The stack itself is declared as
  the deployment of a model family, which makes its port names right
- **NAT** — AOS-CX does not host typical edge NAT

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).
Four configs from Aruba's published `aruba/aoscx-ansible-dcn-workflows`
reference fabric (Apache-2.0), spanning two grammar families and two
AOS-CX majors:

- **`aoscx_dcn_arch3_ibgp_leaf1a.cfg`** / **`…ebgp_leaf1a.cfg`** —
  EVPN-VXLAN leaves (iBGP + eBGP), `interface vxlan` L2VNI, `rd auto`
  vs explicit `route-target 1:11` (GL.10.04.0020)
- **`aoscx_dcn_arch4_core1_1.cfg`** / **`…core1_2.cfg`** — L3-agg
  cores with real `active-gateway` SVIs + multi-chassis LAGs; the
  arch4 cores are the first **real** `active-gateway` capture (the
  anycast surface was synthetic-only through Phase 3) — the
  `core1_2` VSX-secondary peer has a dense 42-interface table
  (GL.10.13.1000)

The corpus is single-source; an operator capture from a different
source, plus configs exercising symmetric-IRB **L3VNI**, **VSX**, and
**VRRP**, are welcomed via
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## A banner is text

The parser reads a banner as text the switch shows, not as lines of
the config: each line of it is passed over by every reader of the
parse (the Tier-3 rows and the check for a JSON or XML paste
included), and nothing of it is translated.  Detection still reads
the text as it came.

- **`banner motd` and `banner exec`** in column 0, then ONE character
  and nothing else (HPE: `banner {motd | exec} <DELIMITER>`, "the
  character used to terminate the input string").  `show
  running-config` prints the banner's text on the lines below it.  The
  character is usually `!` (a published sample prints `$`), so it is
  taken from the line, never assumed; it is compared by its case.
  `banner motd` with nothing after it opens nothing, nor does `no
  banner ...`.  (No HPE page prints a banner in a running config; the
  printed form is from published captures.)
- **Where the banner ends**: at the first later line that ENDS with the
  character, white space after it allowed -- alone on a line, or at the
  end of the text's last line when the text was typed with no line end
  after it (HPE: the input "will be terminated when the delimiter
  character is encountered").  The whole of that line is the banner's.
  The switch prints the stored text and then the character and a line
  end, so the character with text after it on its line is the text's
  own: a banner line `WARNING! Authorised access only` is text, and the
  banner runs on past it.
- **Refused in words**, naming the line and quoting nothing (`parse
  failed: aruba_aoscx: line <n> ...`): a banner with no end before the
  end of the text; more than one character after the type (`banner
  motd !Welcome!` -- no printout has it, so where the text ends cannot
  be told; inferred); and a line of a banner that ends in another
  character than a line feed -- a form feed, a vertical tab, a carriage
  return on its own (the switch ends a line at a line feed, so where it
  ends the banner is not where those lines say).  Paste the whole of
  `show running-config`.  A text typed in a script with more after the
  character that ends it (which the switch discards) runs on to a later
  line that ends with the character, or to that first refusal: the safe
  side.
- **The known limit**: a banner whose text holds its delimiter at the
  END of a line (`WARNING!` alone, under the usual `!`) ends there.
  Nothing in the printout tells that line from the end -- and, since
  `!` is also the comment mark, nor does the line the switch printed
  after the text -- and the switch itself, loading the printout again,
  would end the banner there too (inferred from HPE's input rule; HPE
  says nothing of a banner in a loaded CLI file).  The lines after it
  are then read as configuration (measured: an account line there is
  an account on the target).
- **Not handled**: a `ta-certificate` paste, up to its
  `END_OF_CERTIFICATE` line (its lines are base64, which no reader
  takes).

⚠️ Up to 0.7.7 a banner's lines were read as lines of the config: a
banner line `user <name> group administrators ...` became an account
with privilege 15 on the target, and its `vlan`, `interface`, `ip
route` and `access-list` lines became VLANs, interfaces, routes and a
Tier-3 row, in jobs that said `completed`.  If you translated an
AOS-CX config with a banner with 0.7.7 or earlier, translate it again,
and look in the old output for accounts, interfaces, VLANs and routes
the switch does not have.

## A config without its indentation

The parser reads a stanza's lines by their indentation: `show running-config`
prints an interface's lines, a VLAN's and a VRF's indented under it.  A text with NO indentation -- no
line but a comment begins with white space, and a stanza is followed
by a line at the left margin that is no other stanza, no `!` and no
`exit` or `end` -- is refused in words (`parse failed: aruba_aoscx: this
text has no indentation. ...`), naming the line of the first such
stanza and quoting nothing of the text.  The parser cannot tell where
a stanza of such a text ends, and a guess would put a line where the
switch does not; what the switch itself makes of such a text is not
established here.  Any white space in front of a line is indentation,
a no-break space included, as the parser's readers take it: a config
copied out of a web page is read.  A text in which only SOME lines
lost their indentation is read by its indentation, each dedented line
as a line of the top level.

⚠️ Up to 0.7.7 such a text was read: every interface address, description and VLAN membership was lost,
and every interface was read as shut, in a job that did not say
so.  If you translated an AOS-CX config that had lost its indentation,
translate it again from `show running-config` as the switch prints it.

## Common gotchas

- **A member, slot, port or LAG numbered 0 at the source is written
  as 1 here.**  AOS-CX counts each from 1 (HPE gives a LAG id of "1 to
  256").  With no devices declared, a Junos `ge-0/0/2` is `1/1/2` and
  `ae0` is `lag 1`.  A port 0 beside a port 1 (`ge-0/0/0` and
  `ge-0/0/1`), or `ae0` beside `ae1`, is then one name: the job is
  `partial` and lists both, and an entry in the port map settles it.
  ⚠️ Up to 0.7.7 such a port was written `0/1/<n>` or `<m>/1/0`, and
  such a LAG `lag 0`, in a job that said `completed`.  Look for them
  in an old output.
- **A host's active-backup bond has no form on AOS-CX.**  A RouterOS
  `active-backup`, `balance-tlb` or `balance-alb` bond, a VyOS
  `active-backup`, `transmit-load-balance` or `adaptive-load-balance`
  bond, an OPNsense `failover` LAGG and a FortiOS redundant interface
  need no aggregate on the ports they face.
  AOS-CX has no such bond: the LAG is written as a static
  aggregate (`interface lag <N>` with no `lacp mode`) with a
  `! review:` line in its stanza, and the job carries a warning.
  Configure the ports it faces as a static aggregate too, or re-design
  the bond.
- **A VLAN's name is written whole as a target; a host name or VRF
  name is not.**  The switch reads a VLAN's `name` to the end of the
  line (a committed capture prints `name VLAN 11`), so a name with a
  space is written as it stands.  A host name or VRF name that holds
  white space or a `"` is written with `_` and `'`, the VRF at every
  place it is named, and a route whose gateway holds either is left
  out whole; each with a `review:` line.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § C.
- **A VLAN's address with no interface of its own gets one.**  A
  source can hold a VLAN's address on the VLAN itself: Junos folds
  the address of an `irb` unit that a VLAN binds with `l3-interface`
  onto the VLAN.  As a target, AOS-CX writes `interface vlan <N>`
  for it, with the addresses after the first `secondary`; an
  interface of the VLAN the source already has, in any spelling, is
  the one written.  The address's anycast virtual gateway is not
  written.  Release 0.7.7 and earlier wrote nothing for such an
  address, and the job's validation report listed it as lossy.  As
  a source, an AOS-CX `interface vlan 101` reaches EOS and IOS-XE as
  `Vlan101` where port names are translated (the API, the demo); a
  `render` of the parsed tree with no translation writes it as it
  stands, and 0.7.7 and earlier wrote an `interface Vlan101` beside
  it there.
- **A trunk's allowed list means what it says, and AOS-CX cannot say
  "no VLAN".**  `vlan trunk allowed all` is read as EVERY VLAN, and so
  is `vlan trunk native <N>` with no allowed line: the switch adds
  `all` itself.  Both reach another vendor as that.  As a target:
  every VLAN is `vlan trunk allowed all`, and only that list is
  (`1-4094` reads back as 4,094 VLANs).  A trunk of NO VLAN has no
  AOS-CX form — HPE: when the last VLAN is removed from a trunk it
  trunks every VLAN — so for a source trunk that allows none
  (`switchport trunk allowed vlan none`, a Junos trunk with no
  members, an OS10 trunk with no tagged VLAN and no access VLAN)
  neither `vlan trunk`
  line is written, and a `! review:` line in the stanza says what the
  source said and names its native VLAN.  The job does not report it:
  list the VLANs the port is to carry, or shut it down.  What IS
  written is a switched port (`no routing`) with no `vlan` line,
  which is taken here to be an access port in VLAN 1 by the switch's
  default — one untagged VLAN, on a port that is up, where the source
  had none.  That default is not established here from an HPE page or
  from a switch.  Release
  0.7.7 and earlier read `all` as an empty list, the value of a trunk
  that allows no VLAN, and wrote both as `vlan trunk allowed all` —
  check trunks translated that way.  The vendors'
  own sentences are in the [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunk-that-states-no-allowed-list-platform-by-platform).
- **A trunk's native VLAN has to be on its allowed list, and is
  written there.**  HPE: "If the native VLAN is not included in the
  allowed list, all untagged frames that ingress on the trunk
  interface are dropped."  So the list written here is everything
  the source trunk carries: an AOS-S port that is untagged in one
  VLAN and tagged in others, and an OS10 trunk with an access VLAN,
  are `vlan trunk native 5` beside `vlan trunk allowed 5,10,30` —
  which is how HPE's own side-by-side of the AOS-S and AOS-CX
  grammars writes it.  **Release 0.7.7 and earlier left the untagged
  VLAN off the list**, in jobs that said `completed`: check every
  trunk migrated then from AOS-S or OS10, and add its native VLAN to
  `vlan trunk allowed`.  As a source, an AOS-CX trunk whose own list
  leaves its native VLAN out is read as stating that VLAN and not
  carrying it.  It comes back as it was, is written as it stands for
  IOS-XE, NX-OS, EOS and Junos, reaches AOS-S with no `untagged`
  line (it was written `untagged` in that VLAN) and a `; review:`
  line that says so, and OS10 as `no switchport access vlan` under a
  `! review:` line (it was written that VLAN as its access VLAN).
  **A trunk that states no native VLAN has native VLAN 1** (HPE: "By
  default, VLAN ID 1 is assigned as the native VLAN ID for all trunk
  interfaces.").  A trunk stated by `vlan trunk allowed` alone is
  read so where its list holds VLAN 1, and comes back with `vlan
  trunk native 1` beside it, the line every trunk of the committed
  captures has; Junos, OS10 and AOS-S are written VLAN 1 untagged
  for it, where release 0.7.7 and earlier wrote it tagged.  As a
  target, a Cisco or Arista trunk that states no native VLAN and
  has VLAN 1 on its list is written `vlan trunk native 1`.  **`vlan
  trunk native <N> tag` is read as what it is** (HPE: "Only incoming
  packets that are tagged with the matching VLAN ID are accepted.
  Incoming packets that are untagged are dropped except for BPDUs.
  Egress packets are tagged."): a trunk that carries no VLAN
  untagged, with no native VLAN in the tree.  It was read as native
  VLAN N untagged, the word `tag` dropped -- so an AOS-CX source
  written for any target carried VLAN N untagged there, and came
  back onto AOS-CX without the word.  The id is not kept: such a
  trunk takes only tagged frames and tags what it sends, so it
  comes back as `vlan trunk native 1 tag` where its list holds VLAN
  1 and with no native line where it does not.  And a port of any
  source that carries no VLAN untagged and has VLAN 1 on its list (a
  Junos trunk of `vlan members all` with no `native-vlan-id`, say)
  is written `vlan trunk native 1 tag` before its allowed line,
  where it was written no native line and carried VLAN 1 untagged
  by that default.  The committed captures that have the line are
  two of Aruba's published sample configurations and two
  configurations made by tools.  How a switch prints it is not
  established ([vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md)).  The VLAN
  pane's map keeps to that reading.  Where a map would bring a
  native VLAN that the list leaves out INTO the list, the native
  VLAN is cleared if the map has merged it with a VLAN of the config
  that the list names, and the new id is taken out of the list if
  the list only covered that number with a range (`vlan trunk native
  1000` beside `vlan trunk allowed 2-999,1001-4094`, and 1000
  renumbered to 900); the job says which, in a `vlan_rename:`
  warning ([`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A
  trunk's allowed list is not what I wrote").  The vendors'
  own sentences are in the [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunks-untagged-vlan-and-its-allowed-list-platform-by-platform).
- **A static route's VRF and distance come after its next hop.**
  HPE's form is `ip route <destination> <next hop> [distance <n>]
  [vrf <name>]`; with no VRF the route is the default VRF's, and
  `vrf default` names that VRF.  As a target a distance is written
  `distance <n>`, before the VRF (no HPE page shows the two
  together, so the order is not established); HPE gives a range of
  1 to 255, and the 6200 takes no distance.  A source's management
  VRF keeps its name: a route of NX-OS's `management` is written
  into a VRF of that name, not into the switch's own `mgmt`, and
  `mgmt` is written as it stands onto every target.  `name`, `tag`,
  `track` and `bfd` are read past: a tracked route is translated as
  a route that is always installed.  ⚠️ Up to 0.7.7 a distance was
  written as a bare number after the next hop, a form no AOS-CX
  printout or guide shows; it is still read.
- **AOS-CX is L3-by-default; `no routing` opts into L2.**  This is the
  **inverse** of NX-OS (where ports are L2 by default).  A physical
  port with no `no routing` is a routed interface; the switchport L2
  model engages only when the port opts out of routing.
- **Declaring a CX 6300 or 6200 as the source or target device** —
  each is a model family with one mode, `vsf`: a stack of up to ten
  6300s (the 6300M and 6300F models HPE's VSF guide lists for `type`,
  JL658A to JL668A and JL762A) or up to eight 6200s (the 6200M and
  6200F).  A port is `<member>/1/<port>`, and a switch that is alone
  is member 1 ("If the switch is not a member of a VSF stack, then
  member is 1"), so its ports are `1/1/1` on.  The stack's one
  management interface, `mgmt`, belongs to no member and pairs with
  the other side's management port.  A 6300 and a 6200 do not stack
  together.  The four uplinks are numbered by HPE (`1/1/49-52` on a
  48-port model); that the RJ45 ports before them are `1/1/1-48` is
  `inferred` on every model, since no HPE text read numbers them (the
  JL658A's SFP+ ports are numbered).  The 6300L, the models whose
  ports or uplinks are of two kinds, the QSFP28 models and the TAA
  twins are not modelled; the families' files list them.  The source
  members are read from the config's `vsf member N` blocks (the `type`
  line under each is "The part number of the member being
  provisioned", HPE's VSF guide for the 6200 and 6300), and a switch
  that is alone prints the block too.  The `vsf` lines themselves are
  not translated: onto any target, AOS-CX included, the output has no
  `vsf` line, and the job lists each among the sections it did not
  translate (`vsf member 1`, `vsf split-detect mgmt`).  Another AOS-CX
  switch (a 6400, an 8xxx) is declared
  through a target profile.  The shipped 6300M profile lists `mgmt`,
  and is graded `inferred` for the reason its family's JL661A is.
  See [`../CAPABILITIES.md`](../CAPABILITIES.md) § G.
- **A routed sub-interface's tag is read and written.**  HPE's form is `interface 1/1/1.201` with
  `encapsulation dot1q 10` (one VLAN id, 1 to 4094, on the 6300/6400
  from 10.08 and the 8100, 83xx and 10000 series), and the parser
  reads it as sub-interface `1/1/1.201` with 802.1Q tag 10.  Onto
  another vendor it goes where its port goes, with tag 10
  (`encapsulation dot1q vlan 10` on EOS, `unit 201 vlan-id 10` on
  Junos, `vif 10` on VyOS, `set vlanid 10` on FortiOS).  Up to 0.7.7
  the line was not read, and the unit went with no VLAN, or on VyOS
  and FortiOS with its number as its VLAN id, in jobs that said
  `completed`.  A tag statement that is not one VLAN id (`0`,
  `4095`, `10 20`) leaves its sub-interface out of the output, and a
  row of the job says the statement.  Onto AOS-CX, from AOS-CX
  itself as from another vendor, the renderer writes `encapsulation
  dot1q <id>` first in the stanza; up to 0.7.7 it wrote none, and
  nothing said so.  HPE numbers a sub-interface 1 to 4094, so from
  another vendor a unit numbered above that goes by its tag
  (`GigabitEthernet0/0/1.4095` with `encapsulation dot1Q 11` is
  `1/1/1.11`), and one with no tag is listed in the job, which is
  `partial`.  A LAG's sub-interface (`interface lag 1.201`, which
  HPE documents on an L3 LAG) is read and written the same way, and goes
  where its LAG goes (`Port-Channel1.201` on EOS).  Up to 0.7.7 its
  header was read as `lag 1`: the sub-interface was a second record
  of the LAG, its address on the LAG itself, in jobs that said
  `completed`.  A split port's sub-interface (`1/1/1:1.201`) is not
  read as one, since the split port's name is not read: the job
  lists the name and is `partial`.
- **A port or LAG that has sub-interfaces is written with no address
  of its own.**  HPE's guide gives such an interface no IP address of
  its own, and an EOS or IOS-XE routed port has one beside its units.
  Onto AOS-CX that address is not written: the port's stanza has a
  `! review:` line that gives it, and the job is `partial`, its
  validation listing
  `/interfaces/interface/address-beside-sub-interfaces`.  Put the
  address on a sub-interface, or on another port.  Which interface
  has sub-interfaces is read off the names (`X` beside
  `X.<digits>`), by the rule the validation uses, so the job and the
  output agree on any vendor's names.  Up to 0.7.7 the address was
  written on the port as it stood.
- **A port under a name AOS-CX cannot read gets no VLAN line.**  As
  a target, AOS-CX writes a port's `vlan access` / `vlan trunk`
  lines only where the port's name reads as a port or a LAG
  (`1/1/3`, `lag 1`).  A port left under its source name, or given a
  name of your own in the port map (`{"3": "uplink-x"}`), has its
  `interface` stanza and no VLAN in it.  A name that was left is
  listed by the job; a name you chose is not.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § D1.
- **`active-gateway` is the anycast, not VRRP.**  The supported
  distributed-gateway surface is `active-gateway ip` / `active-gateway
  ip mac`; classic VRRP (`vrrp <vrid>`) is a later phase and drops.
- **Distinct from `aruba_aoss`.**  AOS-CX (10.x) and AOS-Switch /
  ProVision (16.x, the `aruba_aoss` codec) are different NOSes — the
  `!Version ArubaOS-CX` banner is the probe discriminator.  Pick the
  right vendor in the target dropdown.
- **Management services don't carry.**  DNS / NTP / syslog / DHCP /
  RADIUS / domain / timezone are render-dropped on an AOS-CX target —
  the validation panel flags each; re-apply them on the device.

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
