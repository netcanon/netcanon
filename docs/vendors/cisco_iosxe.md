# Cisco IOS-XE — What works for me?

If you operate Cisco IOS-XE devices and want to know what Netcanon
does for you, this is the page.

## TL;DR

Two codecs ship for the IOS-XE family:

- **`cisco_iosxe_cli`** — `show running-config` text **bidirectional**
  (parse AND render).  Cisco IOS-XE CLI is used as both a translation
  *source* and a *target* throughout the walkthrough corpus and
  `tools/demo.py`.  **Certification: certified.**
- **`cisco_iosxe`** — NETCONF / OpenConfig XML.  **Certification:
  best_effort** (Phase 0.5 stub render — parses richly, renders the
  subset Netcanon's NETCONF stub knows how to emit).  Use only when
  you specifically need NETCONF output.

  > **Fixed in #482 — re-check any NETCONF output produced before it.**
  > Used as a migration **target**, this codec previously dropped
  > foreign port names instead of translating them, and because
  > unmappable names are *deleted* rather than preserved, the interfaces
  > carrying them went with them.  Measured across five source codecs,
  > 96% of interfaces were lost — 100% from Arista EOS, Cisco NX-OS and
  > Aruba AOS-CX — leaving a near-empty render that the job still
  > reported as `completed`.  It now shares the `cisco_iosxe_cli`
  > port-name bridge (same platform, different wire format), so Cisco
  > port names are emitted natively.  If you migrated **to**
  > `cisco_iosxe` previously, re-run the translation and diff the
  > interface list before trusting the earlier output.  Management
  > interfaces (`Management1` / `mgmt0` / `mgmt`) are still dropped, as
  > they are for `cisco_iosxe_cli` — that is reported in the job's
  > warnings, not silent, and in its status: with no devices declared
  > the job is `partial` and lists each in `unresolved_ports` until a
  > `port_rename_map` entry gives the port a name or confirms the drop.
  > So is a tunnel onto a target with no form for one, and a
  > `VirtualPortGroup` onto every other platform: no other vendor has
  > one.  And a port whose name the codec does not read — the
  > one-number ports of a virtual router, `GigabitEthernet1` — is left
  > under that name on every target and listed in `untranslated_ports`:
  > give it the name it is to have.  (Not between the CLI codec and
  > the NETCONF one: they are one platform, and the name is IOS-XE's
  > own on both.)

For 95% of operators wanting to translate IOS-XE configs to other
vendors (or vice versa), use `cisco_iosxe_cli`.

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`, `domain`, DNS / NTP / `syslog_servers` (`logging host
  <ip>` harvest + render, promotion #1 — applies to `cisco_iosxe_cli`).
  `timezone` is declared **unsupported** in the capability matrix and
  does not round-trip; the NETCONF `cisco_iosxe` stub renders interfaces
  only, so the rest of this list applies to `cisco_iosxe_cli`.
- Interfaces — name, description, enabled state, IPv4 + IPv6
  addresses, MTU, `ip mtu` (the IP MTU, a field of its own; ⚠️ not
  read up to 0.7.7), VRF binding, `kind` override.  `ipv6 mtu` is
  not read.
- VLANs — ID, name, tagged/untagged port lists, SVI L3 (via
  VLAN-centric projection from the `switchport` per-interface form)
- Static routes
- LAGs (`Port-channel<N>` reconciled with cross-vendor names like
  `ae<N>` / `trk<N>`); `Port-channel<N>.<M>` is a sub-interface of
  the LAG, read as an interface with its tag and not as a LAG of its
  own

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- SNMP v1 / v2c / v3 USM (community, contact, location, trap-hosts;
  v3 with auth + priv per user)
- RADIUS servers
- DHCP server pools (per-pool network, gateway, range, options)
- Local users with hashed passwords — `$5$` / `$6$` / `$8$` / `$9$`
  form-preserving cross-vendor migration

## L3 redundancy: VRRP + SD-Access anycast-gateway

**New in v0.2.0** (Waves B + C — VRRP and SD-Access anycast-gateway
wire-up).  `cisco_iosxe_cli` only — the NETCONF codec leaves these
paths `unsupported` (matrix-only declaration; matches the existing
`/snmp/v3-user` / `/vxlan-vnis/vni` Phase-0.5 stub pattern).

### Classic VRRP

Single-line per-attribute form, the broadly-supported surface across
every IOS-XE release from 15.x onward.  This is the form real
captures emit (see `tests/fixtures/real/cisco_iosxe/batfish_iosxe_basic_vrrp.txt`).

```text
interface GigabitEthernet0/2
 ip address 192.168.1.1 255.255.255.0
 vrrp 12 ip 192.168.1.254
 vrrp 12 priority 110
 vrrp 12 preempt
 vrrp 12 description Edge VRRP
 vrrp 12 timers advertise 3
 vrrp 12 authentication md5 key-string SECRET
 vrrp 12 track 100 decrement 20
!
```

Sub-commands handled: `vrrp N ip X` / `vrrp N ipv6 X` (VRRPv3),
`priority`, `preempt` (+ `no` form), `description`, `timers advertise
<S>`, `authentication text <key>` (→ `plain:<key>`),
`authentication md5 key-string <key>` (→ `md5:<key>`), `track <obj>
decrement <D>` (the object name surfaces; decrement is lossy).
Multiple VRIDs on the same interface produce multiple records.

### SD-Access anycast-gateway

Catalyst 9000 fabric-mode anycast: per-SVI marker plus a chassis-wide
MAC declaration.

```text
fabric forwarding anycast-gateway-mac 0001.c73a.0000
!
interface Vlan100
 ip address 10.1.100.1 255.255.255.0
 fabric forwarding mode anycast-gateway
!
```

Canonical mapping:

- Top-level `fabric forwarding anycast-gateway-mac AABB.CCDD.EEFF`
  lands on `CanonicalIntent.anycast_gateway_mac` (converted from
  Cisco's dotted-triplet to canonical colon-hex; renders back to
  dotted-triplet).
- Per-SVI `fabric forwarding mode anycast-gateway` mirrors the
  primary IP as the anycast: `virtual_gateway_address = ip` on every
  IPv4 address record.  Order-independent (works whether the marker
  precedes or follows `ip address`).
- The discriminator gate is structural — a plain SVI with no
  `fabric forwarding mode anycast-gateway` line parses with
  `virtual_gateway_address=""`.

### Known limitations

- **Modern address-family VRRP form is lossy.**  IOS-XE 17.12+ adds
  the nested `vrrp N address-family ipv4` block with indented
  `address` / `priority` / `preempt` sub-commands.  The parser
  detects the surface (so the lossiness is visible) but does NOT
  deep-populate the nested attributes; render always emits the
  classic single-line per-attribute form.  A config that uses ONLY
  the modern AF form round-trips as an empty group shell —
  intentional and operator-visible.
- **Track decrement value drops.**  `vrrp N track 100 decrement 20`
  preserves only the track-object name on the canonical
  `track_interfaces` field; the priority-decrement value is lossy
  across every codec that supports it.
- **IPv6 SD-Access anycast is unsupported.**  IPv4 SD-Access anycast
  is fully wired; IPv6 (`fabric forwarding ipv6 mode
  anycast-gateway`) is rare in production captures and stays
  declared `unsupported` until demand arrives.
- **Cross-vendor `virtual_gateway_address` divergent from primary.**
  When a Junos / Arista VARP source carries a virtual IP DIFFERENT
  from the SVI's primary IP, IOS-XE SD-Access has no equivalent
  expression — render emits a `! review:` comment line rather than
  silently dropping the discrepancy, and suppresses the SD-Access
  marker.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model + the modern-AF lossy rationale.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway canonical model; see `01-canonical-model.md`
  § "NX-OS shape" for the IP-mirror semantic shared with SD-Access.

## Lossy paths

- **`/routing-instances/instance`** — VRFs translate, but per-VRF
  static routes don't carry a VRF discriminator (route-table
  membership drops on round-trip).  `address-family ipv6` and EVPN
  sub-stanzas inside `vrf definition` are parse-and-ignore in v1.
  See the codec's `CapabilityMatrix.lossy` declarations.

## What we don't do

Deliberately deferred to [Tier
3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Firewall ACLs** — zone-based firewall, CBAC, reflexive ACLs
- **NAT rules** — `ip nat inside source list` etc.
- **IPsec VPN** — crypto maps, IKEv2 profiles, tunnel-protection
- **QoS** — `class-map` / `policy-map` / `service-policy`
- **Routing protocols** — BGP / OSPF / EIGRP stanzas (informational
  only; not auto-rendered to other vendors)
- **PKI / crypto** material — trustpoints, certificate chains, keys

If your migration involves these surfaces, plan to hand-translate
them or pair Netcanon with a complementary tool — see
[`../COMPARISON.md`](../COMPARISON.md).

## Real-world fixtures we've validated against

Provenance + per-fixture detail in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **Batfish public corpus** — AAA, interfaces, IP routes, logging,
  SNMP grammar kitchen-sinks (Apache-2.0)
- **`racc_csr1_iosxe173_umbrella_sig.txt`** — CSR1000v on IOS-XE 17.3
  with Cisco Umbrella SIG anycast routing
- **`racc_csr1000v_iosxe169_bgp_ospf.txt`** — CSR1000v on IOS-XE 16.9
  LTS (oldest LTS we validate against)
- **`racc_cat8000v_iosxe179_netconf.txt`** — Cat8000V on IOS-XE 17.9
  with NETCONF / RESTCONF + type-9 hash form
- **`user_contrib_cat9300_iosxe1712.txt`** — operator-contributed
  physical Cat 9300-24UX on IOS-XE 17.12 (47 interfaces, 3 LAGs,
  full Cat9k CPP grammar)
- **`cml_saumur_iosxe1712_pvrstp.txt`** — CML lab on IOS-XE 17.12
  exercising `spanning-tree pathcost method long` etc.
- **`cml_basic_forwarding_iosv_r1_ospf.txt`** — IOSv 15.x with OSPF
  + dot1Q sub-interfaces, published with every line at column 0: the
  parser refuses it (§ "A config without its indentation"), and it is
  kept under `tests/fixtures/refused/cisco_iosxe/`, in no coverage
  figure
- **`batfish_iosxe_basic_vrrp.txt`** — Batfish public corpus VRRP
  basic grammar (Apache-2.0).  Two-router HA pair with VRRP
  groups on GigabitEthernet — exercises the classic single-line
  VRRP form used by Wave-B VRRP wire-up
- **`ntc_carrier_interfaces.txt`** — Network To Code public corpus
  (Apache-2.0).  Carrier IOS grammar: VRFs, dot1Q Q-in-Q
  subinterfaces, QoS, ACL groups, uRPF.  Validates parse-tolerance
  for grammar outside the Cat9k campus surface

## A banner is text

The CLI codec reads a banner, and every other body of text a config
prints, as text the device shows or runs later, not as lines of the
config: each line of it is passed over by every reader of the parse
(the Tier-3 rows and the check for a JSON or XML paste included), and
nothing of it is translated.  Detection still reads the text as it
came.

- **Bodies written between two delimiters.**  In column 0: `banner`
  with a type (`exec`, `incoming`, `login`, `motd`, `prompt-timeout`,
  `slip-ppp`, `config-save`) or with none (a MOTD banner: the word
  after `banner` is no type), `aaa authentication banner` and `aaa
  authentication fail-message`, `menu <name> title` and `menu <name>
  prompt`, and `busy-message <host>`.  At any indentation, since
  neither is a command of the top level: a line's `vacant-message` and
  `refuse-message`, and a web authentication parameter map's `banner
  text` and `banner title` -- the device prints them indented, and in a
  text whose indentation was lost `text` and `title` after `banner` are
  still those words, never a delimiter.  A keyword with nothing after
  it (`banner motd`, a bare `vacant-message`) opens nothing, nor does a
  `no` form, nor `exec-banner` / `motd-banner`.  (Cisco's configuration
  guides for the syntax, the end and most types: "one or more blank
  spaces and a delimiting character", "terminating the message with the
  second occurrence of the delimiting character"; `prompt-timeout` from
  Cisco's IOS-XE YANG model, a bare `banner` from an IOS 11.0
  reference; `config-save` from a search excerpt of a Cisco Community
  answer and from Batfish; `busy-message` from O'Reilly's *Cisco IOS in
  a Nutshell*, a third-party book -- that IOS-XE takes the command is
  not established.)
- **The delimiter** is the first character after the keyword that is
  not white space, compared by its case (Cisco does not say; Batfish
  and ciscoconfparse2 compare it so).  `show running-config` prints
  every `banner` and `aaa authentication` text with the two characters
  `^C` as its delimiter, whatever was typed (no Cisco page says so:
  every committed and published printout shows it, and Ansible's
  `ios_banner` reads it so), and they are read as ONE delimiter: the
  body ends at the next `^C`, and a `^` alone in it is text.  That is
  what the device holds -- the printer writes `^C` round the stored
  text -- and it departs from Batfish and ciscoconfparse2, which end
  the body at a `^` alone: that is how the device would read the
  printout if it were loaded again (a Cisco community thread: a
  restored `^C` banner gains a `C` each time).  The choice is
  inferred, and the two readings differ only for a body that holds a
  `^` with no `C` after it.  A web authentication `banner text` /
  `banner title` is printed with a caret before the TYPED character
  (Cisco: "The caret symbol (^) displays in the configuration output
  before the delimiting character that you entered"), and ends at the
  next caret.  The byte 0x03 is a delimiter too.
- **Where the body ends**: at the next occurrence of the delimiter,
  ANYWHERE -- on the line that opens it (`banner motd ^CWelcome^C`,
  `aaa authentication banner *Unauthorized*`), in the middle of a later
  line, or at its start.  An IOSv printout puts the closing `^C` after
  the text of the body's last line, and the next banner straight after
  it, so a rule of "the delimiter alone on a line" would never end
  those banners.  What follows the delimiter on its line is discarded,
  neither text nor configuration (Cisco: "Characters after the ending
  delimiter are discarded").
- **`macro name <name>`** runs to a line that is `@` (Cisco: "Use the
  @ character to end the macro"; a published IOS printout shows the
  commands in column 0); an `@` inside a line of it is the macro's
  text.  Its commands run when the macro is applied, and are not
  configuration in force.  That IOS-XE prints a macro the same way is
  inferred.
- **Refused in words**, naming the line and quoting nothing (`parse
  failed: cisco_iosxe_cli: line <n> ...`):
  - a body with no end before the end of the text (`opens a block of
    text ...`).  A device's own printout always has the closer, and the
    device, loading a text whose banner never ends, takes every later
    line for the banner's text (a Cisco community report); read as it
    stands, nothing after it is configuration.  The text was cut
    short, or a delimiter was lost: paste the whole of `show
    running-config`;
  - a line of a body that ends in another character than a line feed
    -- a form feed, a vertical tab, a carriage return on its own, or
    another character Python ends a line at (`is a line of a banner,
    or of another block of text, and ends in a character ...`).  The
    device ends a line at a line feed, so where it ends the body, and
    so where the configuration goes on, is not where those lines say;
  - a line outside every body that holds `^C` (or the byte 0x03),
    after a body opened with it (`is outside every banner, and holds
    what ends one ...`).  A banner typed with another delimiter may
    hold the two characters `^C` (`Press ^C to abort`); printed between
    two `^C`, it ends at its own, and the `^C` the device printed after
    the text is left on a later line.  Read as it stands, the lines
    between were configuration: an account line in such a text was an
    account on the target.  Change the banner on the device so its text
    does not hold `^C`, or remove the banner's lines from the paste.
- **Not seen (a known limitation)**: a banner whose text holds `^C`
  and, after it, a line that opens another body (`banner exec ^C`,
  say).  That body takes the `^C` the device printed for its own end,
  nothing is left outside every body, and the lines between are read
  as configuration (measured: an account line there is an account on
  the target).
- **Not handled**: `crypto pki certificate chain` (its body is
  hexadecimal words and `quit`, indented, which no reader takes);
  `macro auto execute` (no printed form of it was found; Cisco shows
  it typed, ended by `}`); and an Easy VPN server group's `banner`,
  indented under `crypto isakmp client configuration group` (not
  established: no Cisco page that shows its form was found).  The
  bodies of the last two are read as configuration.

⚠️ Up to 0.7.7 a banner's lines were read as lines of the config: a
banner line `username <name> privilege 15 ...` became an account with
privilege 15 on the target, and its `vlan`, `interface`, `ip route`
and `ip access-list` lines became VLANs, interfaces, routes and a
Tier-3 row, in jobs that said `completed`.  If you translated an
IOS-XE config with a banner with 0.7.7 or earlier, translate it again,
and look in the old output for accounts, interfaces, VLANs and routes
the device does not have.

## A config without its indentation

The parser reads a stanza's lines by their indentation: `show running-config`
prints an interface's lines, a VLAN's, a VRF's, a DHCP pool's and a RADIUS
server's indented under it.  A text with NO indentation -- no
line but a comment begins with white space, and a stanza is followed
by a line at the left margin that is no other stanza, no `!` and no
`exit` or `end` -- is refused in words (`parse failed: cisco_iosxe_cli: this
text has no indentation. ...`), naming the line of the first such
stanza and quoting nothing of the text.  The parser cannot tell where
a stanza of such a text ends, and a guess would put a line where the
device does not; what the device itself makes of such a text is not
established here.  Any white space in front of a line is indentation,
a no-break space included, as the parser's readers take it: a config
copied out of a web page is read.  A text in which only SOME lines
lost their indentation is read by its indentation, each dedented line
as a line of the top level.

One committed capture is such a text: an IOSv config published in a
lab topology file with every line at column 0.  It is refused, and
kept under `tests/fixtures/refused/cisco_iosxe/` as the evidence for
the refusal, outside the corpus every other check reads; it had been
read as interfaces with no address, no `shutdown` and no dot1Q tag.

⚠️ Up to 0.7.7 such a text was read: every interface address, description and VLAN membership was lost,
and the VLAN names, in a job that did not say
so.  If you translated an IOS-XE config that had lost its indentation,
translate it again from `show running-config` as the device prints it.

## Common gotchas

- **A RADIUS `key 7` or `key 6` is carried to IOS-XE only** (CLI
  codec).  A key IOS-XE stored in its own form -- type 7, Cisco's
  reversible cipher, or type 6, AES under the router's master key --
  is written back as it was onto IOS-XE.  Onto any other target the
  server is written with no key, beside a review line that names the
  form: re-enter the secret there.  `key <secret>` and `key 0
  <secret>` are the secret as typed, and migrate everywhere.  Type 7
  is not decoded, and is not written into an EOS `key 7` (whether
  EOS's type 7 is Cisco's is not established).  ⚠️ With 0.7.7 or
  earlier, `key 7 <blob>` came out on AOS-S, FortiOS, OPNsense and
  RouterOS as the secret `7 <blob>`, and the one-line `radius-server
  host ... key 7 <blob>` came out on IOS-XE as `key <blob>`: a server
  that authenticates nobody.  Look for such a key in an old output.
- **A name that holds white space is written as one word as a
  target.**  A host name, VLAN name, VRF name or a static route's
  `name` is written with `_` for each run of white space and `'` for
  each `"`, the VRF at every place it is named, with a `review:` line.
  Up to 0.7.7 a route's name that held a space was dropped with
  nothing said.  An address that holds white space is left out and
  said.  See [`../CAPABILITIES.md`](../CAPABILITIES.md) § C.
- **A tag statement is read whole.**  `encapsulation dot1Q 2234
  second-dot1q 15` is a sub-interface of two tags, and reaches IOS-XE,
  IOS XR, EOS and Junos with both; onto another target the job is
  `partial`.  ⚠️ Up to 0.7.7 it was read as `dot1Q 2234` alone -- the
  six units of the carrier capture came out as six sub-interfaces of
  one tag, IOS-XE to IOS-XE included; translate such a config again.
  A statement that matches more than one inner tag (`second-dot1q
  any`, a range, a list) has no form in the tree: the sub-interface is
  left out, with a row of the Tier-3 banner (`... -- not one 802.1Q tag
  and at most one inner tag, so the sub-interface is not translated`).
  `encapsulation dot1Q N native` -- the sub-interface that takes the
  untagged frames of its port ("the default handler of untagged
  packets coming to the port", Cisco) -- is read and written, and
  reaches Junos as `native-vlan-id N` under `flexible-vlan-tagging`;
  onto every other target the job is `partial`
  (`/interfaces/interface/dot1q-native`).  What such a sub-interface
  sends untagged is not established on either platform.  ⚠️ Up to
  0.7.7 it was left out with a row; and a Junos router's
  `native-vlan-id` was written here as `switchport trunk native vlan`
  on a routed port.  The `encapsulation` of a `service instance`
  is the instance's, not the port's.  A port's own address beside
  tagged sub-interfaces (router-on-a-stick) reaches Junos with a
  `# review:` line: see [`juniper_junos.md`](juniper_junos.md).
- **A VLAN's address with no interface of its own gets one, once**
  (CLI codec).  A source can hold a VLAN's address on the VLAN
  itself: Junos folds the address of an `irb` unit that a VLAN binds
  with `l3-interface` onto the VLAN.  As a target, IOS-XE writes
  `interface Vlan<N>` for it.  An interface of the VLAN the source
  already has is found in any spelling, so an AOS-CX `interface vlan
  101` that reaches the renderer untranslated no longer gets an
  `interface Vlan101` beside it (the API and the demo translate the
  name, and were not affected).
- **Renaming or dropping `Vlan<N>` in the rename modal is not
  always shown by the output** (CLI codec).  A translation from
  IOS-XE to IOS-XE lists each VLAN interface under *Other names in
  the config*.  For some the output writes `interface Vlan<id>`
  from the VLAN itself: renamed, the interface is then written under
  the new name and the old one again; dropped, it comes back.  The
  job records the entry and says nothing.  Read the output after
  such an entry; renumbering or dropping the VLAN on the VLANs pane
  takes its interface with it.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § F.
- **A trunk's allowed list means what it says.**  A trunk with no
  `switchport trunk allowed vlan` line is read as a trunk of EVERY
  VLAN — the IOS-XE default — and reaches another vendor as that
  (`vlan members all`, `vlan trunk allowed all`).  `switchport trunk
  allowed vlan none`, and a list emptied by `remove` or `except`, is
  a trunk of NO VLAN.  `add` and `remove` on an interface's first
  allowed line start from every VLAN, as they do on the switch, and
  an interface whose stanza is met twice has ONE list: `add 30` in a
  second stanza is added to the list the first one stated, and a
  second stanza that says `switchport mode trunk` and states no list
  is a trunk of that same list.  As a target:
  every VLAN is written as a trunk with no allowed line, which is
  what the device prints for its default (never the ids, which are
  one line of some 19,000 characters); no VLAN is `switchport trunk
  allowed vlan none`; any other list is written as it stands.  A list
  kept on a port that is not a trunk comes back as it was, `all` for
  every id — but **`none` on such a port is dropped**: there an empty
  list and no list are one value, and no line is written.  A port in
  a dynamic mode that states `switchport trunk allowed vlan none`
  comes back with no allowed line, and carries every VLAN if it
  negotiates a trunk.  A port that says `switchport mode trunk` and
  takes its list from `source template`, which is not read, is a
  trunk of every VLAN.  Release 0.7.7 and earlier had one value, an
  empty list,
  for a trunk that allows no VLAN and for one that states no list: a
  `none` trunk came out here as a trunk of every VLAN, and a trunk
  with no list reached Junos, OS10 and AOS-S carrying none — check
  trunks translated that way.  Not established from Cisco's pages: what
  `show running-config` prints for `none`.  The vendors' own
  sentences are in the [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunk-that-states-no-allowed-list-platform-by-platform).
- **A trunk's native VLAN, and whether its allowed list names it**
  (CLI codec).  `switchport trunk native vlan <N>` is a line of its
  own, and the allowed line can name N or leave it out; either is
  read as it is written and comes back so.  In the canonical tree
  the list is what a trunk carries, so a native VLAN the list leaves
  out is stated and not carried: it reaches AOS-S with no `untagged`
  line, and a `; review:` line that says so, and OS10 as `no
  switchport access vlan` under a `! review:` line (release 0.7.7
  and earlier wrote the port untagged in that VLAN on both).  What
  Cisco says of it: the native VLAN is VLAN 1
  by default, and VLAN 1 can be taken off a trunk "so that no user
  traffic (including spanning-tree advertisements) is sent or
  received on VLAN 1."  For a native VLAN other than 1 there is no
  sentence of Cisco's: that it is not carried either follows from
  Cisco's rule that a trunk passes the VLANs its list allows, and is
  an inference — one that two phrases of Cisco's command reference
  read against.  As a target, an AOS-S port that is untagged in one
  VLAN and tagged in others, and an OS10 trunk with an access VLAN,
  are written with that VLAN on the allowed line beside the native
  line (`switchport trunk native vlan 10`, `switchport trunk allowed
  vlan 10,20,30`).  Release 0.7.7 and earlier left it off the
  allowed line, in jobs that said `completed`: check the allowed
  list of every trunk with a native line migrated then from AOS-S or
  OS10.  **A trunk that states no native VLAN has native VLAN 1**
  (Cisco: "The native VLAN is VLAN 1 by default.").  Where its
  allowed list holds VLAN 1 -- the list names it, or there is no
  allowed line -- a port that says `switchport mode trunk` is read
  as carrying VLAN 1 untagged, and Junos, OS10 and AOS-S are written
  so (`native-vlan-id 1`; `switchport access vlan 1`; `untagged`).
  Release 0.7.7 and earlier wrote VLAN 1 TAGGED on those three, in
  jobs that said nothing: check such trunks migrated then.  Where
  the list leaves VLAN 1 out nothing is filled in, and the trunk is
  read as having no untagged VLAN (Cisco, of taking VLAN 1 off a
  trunk: "so that no user traffic (including spanning-tree
  advertisements) is sent or received on VLAN 1.").  The default is
  a trunk's: a port in another mode -- `switchport mode dynamic
  auto`, `switchport mode access`, or no mode line -- keeps its
  trunk lines and is given no native VLAN.  As a target, no
  `switchport trunk native vlan 1` line is written for a trunk
  whose list holds VLAN 1: it is the default, and no real IOS-XE
  capture prints the line.  (A port that is not `switchport mode
  trunk` keeps a `native vlan 1` line it states.)  A `vlan 1` line
  IS written where a trunk of the source carries VLAN 1 untagged by
  its platform's default, though the source may have no word for
  VLAN 1 and no real IOS-XE capture prints the line: the tree has
  the VLAN, and every VLAN of the tree is declared.  So a config
  with such a trunk and no word for VLAN 1 comes back onto IOS-XE
  with a `vlan 1` line it did not have.  A port that carries NO
  VLAN untagged at its source and has VLAN 1 on its list (a Junos
  trunk of `vlan members all` with no `native-vlan-id`, say) would
  carry VLAN 1 untagged here by that default if it were written no
  native line.  The form Cisco documents for it on the Catalyst 9300
  and 9500 alike is `vlan dot1q tag native`, which tags the native
  VLAN of EVERY 802.1Q trunk of the switch (Cisco: "When enabled,
  native VLAN packets going out of all IEEE 802.1Q trunk ports are
  tagged.").  So it is written, once, before the interfaces, where
  no port the check reads blocks it: no port in trunk mode carries a
  VLAN untagged, and no port is in a mode no mode line is written
  for (dynamic, private-vlan, dot1q-tunnel, fex-fabric and the like)
  or holds trunk lines in no mode.  A port written with no mode and
  no trunk line is not counted: on a Catalyst such a port is in
  dynamic auto by default, and should it become a trunk the line
  tags its native VLAN as well.  Otherwise
  such a trunk is written no native line under a
  `! review:` line that says so
  ([`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A trunk's allowed
  list is not what I wrote").  Under the line, Cisco documents, dot1x
  reauthentication fails on trunk ports.  The per-port `switchport
  trunk native vlan tag` of the Catalyst 9500 High Performance
  models is not written.  As a source, `vlan dot1q tag native` (with
  `exclude control` or without) and `switchport trunk native vlan
  tag` are read: a trunk under either carries no VLAN untagged, and
  has no native VLAN in the tree, a stated one included; a trunk
  that states `no switchport trunk native vlan tag` leaves the line
  for every trunk, and has its default again.  Such a config comes
  back onto IOS-XE with the line where at least one trunk under the
  line holds VLAN 1 and no port the check reads blocks it.  Where a
  port blocks it -- a trunk that carries a VLAN untagged (one that
  leaves the line and holds VLAN 1 among them), a port in a mode no
  mode line is written for, trunk lines in no mode -- the trunks
  under the line that hold VLAN 1 come back with review lines; where
  no trunk under the line holds VLAN 1, it comes back without the
  line, and those trunks without a native line
  ([vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md)).  The VLAN pane's map
  keeps to that reading.  Where a map would bring a native VLAN
  that the list leaves out INTO the list, the native VLAN is
  cleared if the map has merged it with a VLAN of the config that
  the list names, and the new id is taken out of the list if the
  list only covered that number with a range
  (`switchport trunk native vlan 1000` beside `switchport trunk
  allowed vlan 2-999,1001-4094`, and 1000 renumbered to 900); the
  job says which, in a `vlan_rename:` warning
  ([`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A trunk's
  allowed list is not what I wrote").  It is done for a port
  in any mode -- `switchport mode dynamic desirable`, or no mode
  line -- since such a port can become a trunk and its trunk lines
  are written here.  The short allowed list of such a port names
  its VLANs as a trunk's does, declared or not: `native vlan 10`
  beside `allowed vlan 500`, with 10 given the id 500, is a merge
  in any mode.  The vendors' own
  sentences are in the [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunks-untagged-vlan-and-its-allowed-list-platform-by-platform).
- **A type and its number written apart** (CLI codec) —
  `interface ethernet 1/11`, and in a route `ip route 0.0.0.0
  0.0.0.0 loopback 66 100` — are one name, as IOS reads them, in
  the letters the config has (`ethernet1/11`, `loopback66`); the
  number after a route's interface is its distance, and an address
  after a type word (`Dialer 10.0.0.1`) is the route's gateway, not
  the type's number.  `show running-config` prints the two
  together, so this is about typed and documentation-shaped text.
  An `interface range ...` stanza names no interface, and neither
  does an `interface breakout <port> map <profile>` line (OS10's,
  in a text read as IOS-XE): it is not translated, and its header
  is on the migrate banner, counted as a section.  ⚠️ Up to 0.7.7
  the name was the first word alone: two `interface ethernet 1/N`
  stanzas were one interface called `ethernet`, the route went out
  `loopback` at distance 66, and a range or a breakout line was an
  interface called `range` or `breakout`.
- **`ip route <prefix> <mask> dhcp` keeps a word where a name
  goes** (CLI codec).  The keyword says the next hop is the default
  router a DHCP server hands out, and a translated route holds an
  address or an interface name and nothing else, so `dhcp` is kept
  as the route's interface.  From IOS-XE to IOS-XE the line is
  written back as it was.  Onto another platform it is a route out
  an interface called `dhcp` (`ip route 0.0.0.0/0 dhcp`, `set
  device "dhcp"`, `gateway=dhcp`), and onto Junos the validation
  report holds the job: write the target's own form for a
  DHCP-learned route by hand.  After an interface (`ip route ...
  GigabitEthernet1 dhcp`) the keyword is read past, and the route
  is an ordinary one out that port.
- **No `terminal length 0`.**  Netcanon uses `--More--`
  space-injection for paging.  This is a hard rule (see
  [`../../AGENTS.md`](../../AGENTS.md)) — don't try to bypass.
- **Mgmt-vrf interface** (`GigabitEthernet0/0` with
  `vrf forwarding Mgmt-vrf`) gets `kind=mgmt` override automatically
  by the parser, so cross-vendor rename can cascade to Aruba `oobm`
  / Junos management VRF.
- **Declaring a Catalyst as the source device** — IOS-XE lists the
  interfaces of every network module the chassis could take, whichever
  one is fitted, and an application-hosting port.  With both devices
  declared — in the Interface rename modal or on the API — those
  names come back as off-inventory (and
  some of them can be displaced), so the job is `partial` although the
  model is right.  Where the target model lists no management port, a
  management port is kept as the target's out-of-band form if it has
  one and still asks for your decision.  An `interface Null0` stanza
  is reported as off-inventory too, and a VRRP `track <object
  number>` is read as a port name.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § G.
- **Type-7 hashes** are Cisco-proprietary and **migration-blocked**
  when targeting non-Cisco vendors — Netcanon emits a review-comment
  in the rendered output rather than translating to plaintext.
  Type-9 hashes round-trip cleanly within Cisco; type-5/6 hashes
  translate via the cross-vendor crypt-form mapping.
- **Backup-side**: `cisco_more_paging: true` in the device-definition
  YAML — see [`../../netcanon/definitions/library/cisco/`](../../netcanon/definitions/library/cisco/)
  for the canonical examples.

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
