# Dell SmartFabric OS10 — What works for me?

If you operate Dell EMC PowerSwitch hardware running **SmartFabric
OS10** — the S-series leaf / ToR and Z-series spine class — and want to
know what Netcanon does for you, this is the page.

## TL;DR

- **`dell_os10`** — `show running-configuration` text **bidirectional**
  (parse AND render).  **Certification: best_effort.**

OS10 is Dell's modern Debian-based NOS.  It is **not** the older
Force10 **OS9 / FTOS** grammar (`interface TenGigabitEthernet 0/1`,
`ManagementEthernet`, VLAN-centric `tagged` / `untagged`) — that is a
different language, and this codec **refuses** it outright rather than
mis-parse it into a plausible-looking wrong answer.

> **Corrected 2026-09-23 (#482).**  This paragraph used to promise that
> "auto-detection returns no candidate" for an OS9 paste.  That was a
> whole-product claim, and it was **false**: the OS10 codec did refuse,
> but `cisco_iosxe_cli` then claimed the file at confidence **95**
> ("IOS-specific banner sequence detected"), because Force10 emits
> `service timestamps` and one such banner was enough.  Measured on four
> real S4810 captures, it parsed them into 90 interfaces collapsed onto
> 5 distinct names, 0 VLANs and 0 IP addresses.  The deferral now lives
> in `cisco_iosxe_cli.probe()`, so the claim above is true again — but
> if you migrated an OS9 config before this, re-check what source codec
> was used.

> **Why `best_effort` and not `certified`?**  Every other codec's
> `certified` rests on an **in-tree real capture corpus**.  The OS10
> development corpus — 40 real configs spanning five OS10 releases —
> is held out-of-tree: some captures carry live password hashes, and
> the best-structured material of all carries no redistribution
> licence.  The codec is validated against those 40 captures plus a
> committed synthetic kitchen-sink fixture and full cross-vendor mesh
> coverage, but the honest label for "no committed real corpus" is
> `best_effort`.  See
> [Real-world fixtures](#real-world-fixtures-weve-validated-against).

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable)
— auto-translatable:

- `hostname`
- Interfaces — name, description, admin state, MTU, IPv4 + IPv6
  addresses (CIDR), `ip vrf forwarding` binding
- L2 switchport — access / trunk mode, access VLAN, trunk allowed-VLAN
  list, trunk **native** VLAN, `channel-group` membership
- VLANs — ID, name, tagged / untagged port lists
- Static routes — including per-VRF (`ip route vrf <name> …`)
- VRFs — name (`ip vrf <name>`)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats) —
translatable with caveats:

- LAGs (`interface port-channel N`, reconciled with cross-vendor names
  like `Port-channel<N>` / `ae<N>` / `lag N`)
- SNMP v2c (community / location / contact / trap host) and v3 USM users
- Local users — name, role, `priv-lvl`, hashed password
- **VRRP** — group ID, priority, preempt, virtual addresses

## L3 redundancy: real VRRP

OS10 runs **real VRRP**, not a vendor FHRP dialect:

```text
interface vlan461
 ip address 192.168.46.3/26
 !
 vrrp-group 46
  priority 110
  preempt
  virtual-address 192.168.46.1
```

This matters in both directions:

- **OS10 as target.** A source carrying HSRP (Cisco) or CARP (OPNsense)
  is re-expressed as VRRP.  The operator's redundancy *intent* for the
  virtual IP survives, but **the wire protocol changes** — so
  `/interfaces/interface/vrrp-groups/group/mode` is declared `lossy`
  rather than quietly reported as a faithful translation.  Same-vendor
  VRRP round-trips losslessly.
- **OS10 as source.** `priority`, `preempt` and the virtual addresses
  round-trip to any target that models VRRP.

⚠️ **One parsing subtlety worth knowing if you read the configs
yourself:** OS10 device dumps separate an SVI's L3 block from its
nested VRRP block with a **one-space indented `!`**.  A parser that
treats any bare `!` as a stanza terminator drops the entire VRRP group.
This codec closes a stanza only on a column-0 line, which is why the
groups above survive.

## SNMPv3 keys — read this before migrating users

An SNMPv3 USM key is localised against **the agent's own engine ID**, and
Dell states such keys cannot be copied between switches.  So:

- A key that belongs to **another device** is **refused** — the codec
  emits a review comment instead of an `snmp-server user` line.  It is
  never re-emitted behind the `localized` keyword, which would claim the
  digest was already this switch's and make OS10 derive a key from a key.
- A source **passphrase** is portable and renders *without* `localized`,
  so OS10 localises it itself on commit.

⚠️ OS10's per-codec default is **`plaintext`** — the **opposite** of
NX-OS.  An OS10 value with no trailing `localized` marker is a
passphrase.

Practical consequence: **plan to re-key SNMPv3 users** when migrating
between vendors.  Auth algorithms also downgrade — OS10 offers only
`md5` / `sha`, so any SHA-2 variant collapses to `sha`, and privacy
offers only `des` / `aes`, so AES-192/256 collapse to `aes`.  Both are
declared `lossy`; neither is silent.

## Port naming

OS10 uses three-segment lower-case names, `ethernet<stack>/<module>/<port>`:

```text
ethernet1/1/30      ->  stack 1, module 1, port 30
ethernet1/1/10:1    ->  breakout subport (lane 1 of port 10)
mgmt1/1/1           ->  management port
```

Breakout subports (the `:lane` suffix) are unambiguous and classify
properly rather than falling through to `unknown`.  The chassis-level
`interface breakout 1/1/1 map 100g-1x` lines that *declare* the split
are not ports and do not become interfaces.

## What we don't do

Declared `unsupported` — the loss is reported, never silent:

- **VXLAN / EVPN.**  OS10 reaches an overlay through a
  `virtual-network <vnid>` indirection that is deferred past v1.
- **BGP / OSPF / IS-IS**, ACLs, QoS/DCB, NAT and firewall surfaces —
  [Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered),
  captured for the dropped-Tier-3 banner and never auto-rendered.
- **VLT** (Dell's MLAG) — detected for the Tier-3 banner, not modelled.
  Both halves are reported: the column-0 `vlt-domain` block *and* the
  per-bundle `vlt-port-channel <N>` marker, the latter carrying its
  bundle id so you can see which Port-Channels changed meaning.  That
  second half was missed until 2026-09-24 (it is indented inside the
  interface stanza, and every other Dell pattern is anchored at column
  0), so a **dual-homed** bundle rendered as an ordinary
  **single-chassis** port-channel with no marker and no banner line —
  present in 6 of the 9 committed captures.  Note what "modelled" would
  buy on a Cisco IOS-XE target: very little.  VLT is a two-peer
  construct and IOS-XE has no peer MLAG (StackWise Virtual fuses two
  chassis into one logical switch), so there is no faithful target form
  — the honest ceiling is a comment block carrying the parameters.  The
  isomorphic target is NX-OS `vpc`, which netcanon does not model
  either.  Arista's MLAG is the same story — see
  [`arista_eos.md`](arista_eos.md).
- Management-plane scalars: `ip domain-name`, `ip name-server`,
  `ntp server`, `logging server`, DHCP pools and `radius-server`.

## Lossy paths

Declared `lossy` means: translated, but something measurable is left
behind.  Never silent — each one is reported in the migration diff.

**VRRP sub-fields** — the group itself round-trips; these do not:

- **`…/vrrp-groups/group/mode`** — a cross-family source (HSRP, CARP)
  is re-expressed as real VRRP.  The virtual-IP intent survives; the
  wire protocol changes.
- **`…/advertisement-interval`**, **`…/authentication`**,
  **`…/virtual-mac`**, **`…/description`** — not modelled in v1; the
  group renders without them and the target applies its defaults.
- **`…/virtual-ipv6s`** — OS10 expresses IPv6 VRRP through a separate
  `vrrp-ipv6-group` stanza that v1 does not render, so IPv6 virtual
  addresses drop while the IPv4 group survives.
- **`…/track-interfaces`** — OS10 tracks a track-*object* id, not an
  interface name, so a canonical track list has no faithful OS10 form.

**Anycast / virtual gateway** — OS10 has no VARP or
distributed-anycast-gateway concept at all:

- **`/interfaces/…/ipv4|ipv6/address/virtual-gateway-address`** and
  **`…/virtual-gateway-mac`**, plus the `/vlans/vlan/…` companions —
  the address renders, the virtual gateway does not.  Migrating from
  Arista VARP or NX-OS anycast gateway means re-authoring as VRRP.

**SNMPv3 USM** — see the section above before migrating users:

- **`auth-passphrase`** / **`priv-passphrase`** — a key localised to
  the source agent's engine ID is refused with its user.
- **`auth-protocol`** — OS10 offers only `md5` / `sha`, so every SHA-2
  variant collapses to `sha`.  A real cryptographic downgrade.
- **`priv-protocol`** — AES-192/256 collapse to `aes`, 3DES to `des`.
- **`engine-id`** — OS10 states it on its own `snmp-server engineID
  local` line, so a per-user engine ID has nowhere to go.

**VRF sub-details** — `ip vrf <name>` carries the name alone:

- **`instance-type`** (mac-vrf downgrades to `vrf`),
  **`description`**, **`route-distinguisher`**, **`rt-imports`**,
  **`rt-exports`**, **`l3-vni`** — the RD and route-targets live under
  Tier-3 `router bgp`; the L3VNI needs the deferred `virtual-network`
  indirection.

**Interface + misc:**

- **`/interfaces/interface/config/type`** — inferred from the name
  prefix on render rather than carried explicitly.
- **`/interfaces/interface/tunnel-type`** — the port survives as an
  `interface <name>` stanza; its encapsulation does not.
- **`dhcp-client`** / **`dhcp-client-v6`** — OS10 spells these
  `ip address dhcp` / `ipv6 address autoconfig`; v1 models no value.
- **`/interfaces/…/ipv6/address/secondary-ip`** — the IPv4 render
  re-emits `secondary`, the IPv6 form does not.
- **`/vlans/vlan/description`** — OS10 carries exactly one human label
  per VLAN (the SVI's `description`) and the render spends it on the
  VLAN **name**.  A VLAN whose name is only an interface's, or
  empty (an OPNsense or RouterOS VLAN), has its description written
  as its name instead.
- **`/vlans/vlan/name`** — written as the description of the VLAN's
  SVI: the one the config has, where it states no description, or
  one made for the VLAN.  An SVI with a description of its own keeps
  it, and the name is written in a `! review:` line of the stanza:

  ```
  interface vlan20
   description voice gateway
   ! review: VLAN 20 is named VOICE in the source; OS10 has one label for a VLAN, this interface's description, which holds the description the source gives the interface -- choose which to keep
  ```
- **`/routing/static-route/description`** — destination, next-hop and
  administrative distance only.

## Real-world fixtures we've validated against

**Nine are now in-tree** (2026-09-23), the codec's first committed corpus —
all MIT-licensed, verified against each upstream repository's licence metadata,
all nine parsing and round-tripping canonical-stable.  They are listed in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md).

⚠️ **This does not promote the codec to `certified`, and the reason is worth
stating plainly.**  The codified bar is "≥3 real captures round-trip cleanly"
and nine do.  But **none of the nine states its OS10 release** — every MIT
source ships its configs with the `! Version` banner stripped, while every
source that *does* pin a release carries no licence file at all.  Every other
certified codec names the versions behind its claim, so promoting on an
unversioned corpus would make the word mean something weaker here.  One
licence-clean capture with its banner intact closes it.

Development also used a **40-capture out-of-tree corpus** covering
five OS10 releases — **10.4.3.1, 10.4.3.4, 10.5.1.0, 10.5.1.4,
10.5.4.4** — across S3048, S4112F-ON, S5212F-ON, S5232F, S5248F-ON and
Z-series platforms, plus four **OS9 / FTOS S4810** captures kept as
negative controls.  Measured over that corpus:

- **40/40 parse** without exception
- **38/40 round-trip canonical-stable.**  The two exceptions are not
  defects: both are Microsoft reference configs scrubbed to a literal
  `$CREDENTIAL_PLACEHOLDER$` token, which the credential gate
  correctly refuses to re-emit — see
  `tests/unit/migration/codecs/dell_os10/test_render_refuses_unmodelled_credential.py`
- **4/4 OS9 captures refused**, as intended

Why it cannot simply be committed: the captures divide almost exactly
along the wrong axis.  The permissively-licensed material (MIT) carries
**no `! Version` banner**, while every capture that pins an OS10
release is **unlicensed**.  So committing the licensed half would not
satisfy the `certified` bar of ≥3 captures across ≥2 OS versions
anyway.  **One permissively-licensed OS10 `show running-configuration`
with its version banner intact remains the single highest-value
contribution to this codec** — see
[`WANTED.md`](../../tests/fixtures/real/WANTED.md).

## A banner is text

The parser reads a banner as text the switch shows, not as lines of
the config: each line of it is passed over by every reader of the
parse (the Tier-3 rows and the check for a JSON or XML paste
included), and nothing of it is translated.  Detection still reads
the text as it came.

- **`banner motd` and `banner login`** in column 0, then the
  delimiter and nothing else: the two characters `^C` as Dell prints
  them whatever was typed (a Dell knowledge-base listing, 10.5.1.0),
  or one other character (a generated config, the committed CANU one,
  has `^`).  `banner motd disable` and `banner login disable` are
  commands of one line and open nothing, nor does `banner motd` with
  nothing after it, nor `no banner ...`.
- **Where it ends**: at a line that is the delimiter and nothing else,
  in column 0 (Dell: "a line that contains only the delimiter
  character").  White space after it is allowed (inferred).  The
  delimiter in the middle of a line, or after white space, does not
  end it -- inferred from Dell's wording, and the safe side: the
  banner runs on to a later line, or is refused.  The last line of the
  text may have no line end.  A `!` in the text is the text's.
- **Refused in words**, naming the line and quoting nothing (`parse
  failed: dell_os10: line <n> ...`):
  - a banner with no end before the end of the text;
  - a banner line with more than its delimiter after the type (`banner
    motd ^CWelcome^C` -- no Dell page shows it; inferred);
  - a line outside every banner that is the delimiter alone of a banner
    opened before it (`is outside every banner, and holds nothing but
    the delimiter ...`): a banner typed with another delimiter may hold
    a line `^C`; printed with `^C`, it ends there, and the `^C` line
    Dell printed after the text is left behind.  Read as it stands, the
    lines between were configuration.  A `!` line is not refused so:
    `!` is OS10's comment mark, and a line of it after a banner
    delimited by `!` is as likely a comment;
  - a line of a banner that ends in another character than a line feed
    -- a form feed, a vertical tab, a carriage return on its own (the
    switch ends a line at a line feed, so where it ends the banner is
    not where those lines say).

  Paste the whole of `show running-configuration`; if a line of the
  banner's text is its delimiter alone, change the banner on the
  switch, or remove its lines from the paste.
- **Not seen (a known limitation)**: a text with a line that is the
  delimiter alone and, after it, a line that opens another banner
  (which takes the line Dell printed for its own end), or one whose
  delimiter is `!`.  The lines between are read as configuration
  (measured: an account line there is an account on the target).

⚠️ Up to 0.7.7 a banner's lines were read as lines of the config: a
banner line `username <name> password ... role sysadmin` became an
account with privilege 15 on the target, and its `interface vlan`,
`ip route` and `ip access-list` lines became VLANs, interfaces, routes
and a Tier-3 row, in jobs that said `completed`.  If you translated an
OS10 config with a banner with 0.7.7 or earlier, translate it again,
and look in the old output for accounts, interfaces, VLANs and routes
the switch does not have.

## A config without its indentation

The parser reads a stanza's lines by their indentation: `show running-configuration`
prints an interface's lines (a VLAN's and a port channel's among them) indented under it.  A text with NO indentation -- no
line but a comment begins with white space, and a stanza is followed
by a line at the left margin that is no other stanza, no `!` and no
`exit` or `end` -- is refused in words (`parse failed: dell_os10: this
text has no indentation. ...`), naming the line of the first such
stanza and quoting nothing of the text.  The parser cannot tell where
a stanza of such a text ends, and a guess would put a line where the
switch does not; what the switch itself makes of such a text is not
established here.  Any white space in front of a line is indentation,
a no-break space included, as the parser's readers take it: a config
copied out of a web page is read.  A text in which only SOME lines
lost their indentation is read by its indentation, each dedented line
as a line of the top level.

⚠️ Up to 0.7.7 such a text was read: every interface address, description, VLAN membership and LAG
member was lost, in a job that did not say
so.  If you translated an OS10 config that had lost its indentation,
translate it again from `show running-configuration` as the switch prints it.

## Common gotchas

⚠️ **Auto-detection finds about three OS10 configs in four.**
OS10 and IOS-XE share the `!`-delimited Cisco shape, so a capture that
spends its opening bytes on a template header, a console login banner or
a block of QoS can reach an IOS-XE marker before an OS10-exclusive one.

Measured across the 40-capture corpus, at the widened window shipped in
#483 (`DEFAULT_PROBE_BYTES = 65536`): **29 detect correctly, 7 return no
candidate, and 4 are still claimed by `cisco_iosxe_cli`.**  Before the
widening it was 19 / 11 / 10 — so most, but not all, of this gap was the
window rather than the markers.  The four that remain are config
*fragments* (a VLAN-only or interface-only excerpt) which carry no OS10
token at all.

If auto-detection picks the wrong vendor, or none, **select `dell_os10`
explicitly** — parsing is unaffected, since only the probe is at issue.  Pinned in
`tests/unit/migration/codecs/dell_os10/test_probe_window_limits.py`
and tracked in
[`../vendor-research/dell_os10/30-codec-plan.md`](../vendor-research/dell_os10/30-codec-plan.md)
§9.

⚠️ **A routed sub-interface loses its tag.**  A stanza named
`interface ethernet1/1/1.54` is read as an interface of that name; its
`encapsulation dot1q` line is not read (OS10 routed sub-interfaces are
not modelled).  Onto another vendor it goes where its port goes
(`Ethernet1.54`) with no VLAN — or, on VyOS and FortiOS, with 54 as
its VLAN id, whatever the line said.  The job warns for each such
unit, and with both devices declared lists it in `untagged_units` and
stays `partial` until you name it.  Set the tag on the target by hand.
**Onto OS10 itself the tag is lost the same way and nothing says so**:
the output has `interface ethernet1/1/1.54` with its address and no
`encapsulation dot1q`, in a job that is `completed` with no warning.
Compare the sub-interfaces of an OS10 to OS10 output with the source.

⚠️ **Renaming or dropping `vlan<N>` in the rename modal is not shown
by the output.**  A translation from OS10 to OS10 lists each VLAN
interface under *Other names in the config*.  OS10 output writes
`interface vlan<id>` from the VLAN itself: renamed, the interface is
written under the new name and the old one again; dropped, it is
written all the same.  The job records the entry and says nothing.
Edit the output.  See
[`../CAPABILITIES.md`](../CAPABILITIES.md) § F.

⚠️ **A user whose password hash we can't model is dropped, loudly.**
The renderer refuses to re-emit a credential it cannot prove is safe to
reuse, leaving a `review:` comment naming the user instead of a
`username` line.  A config whose secrets were scrubbed by some other
tool will therefore render with no users at all — that is the gate
working, not a parser fault.

⚠️ **OS10 cannot be told "every VLAN".**  An OS10 trunk with no
`switchport trunk allowed vlan` line carries untagged traffic on its
access VLAN and no tagged VLAN, and is read so: a trunk of that one
VLAN, or of NO VLAN where it states no access VLAN either.
As a target that is written the same way, with no allowed line.  But
OS10 has no word for every VLAN, its VLAN ids end at 4093, and a VLAN
must exist before a port is put in it.  A trunk of EVERY VLAN — a
Cisco or Arista trunk that states no list, an AOS-CX `vlan trunk
allowed all`, a Junos `vlan members all` — is written `switchport
trunk allowed vlan 1-4094`, as it always was, under a `! review:`
line that says so: replace the range with the VLANs the switch has.
A list that is NOT every VLAN is written as it stands, with no such
line, though it can have the same faults: `2-4094` names an id OS10
does not have, and any list can name a VLAN the output does not
declare, which OS10 wants made before a port is put in it.
Release 0.7.7 and earlier had one value, an empty list, for a trunk
that allows no VLAN and for one that states no list: an OS10 trunk
with no tagged VLAN came out as a trunk of every VLAN on IOS-XE,
NX-OS, EOS and AOS-CX, and a Cisco trunk with no list reached OS10
with no allowed line — check trunks translated that way.  The
vendors' own sentences are in the [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunk-that-states-no-allowed-list-platform-by-platform).

⚠️ **A trunk's access VLAN is carried, and is never on its allowed
line.**  `switchport access vlan <N>` on a trunk is the VLAN it
carries untagged, and `switchport trunk allowed vlan` names tagged
VLANs only — Dell: "An interface cannot be an access and trunk member
of the same VLAN."  In the canonical tree a trunk's list is
everything it carries, so the access VLAN is read INTO the list
(`access vlan 1` beside `allowed vlan 32,34` is native 1 and the list
`1,32,34`) and written back out of it: an OS10 config comes back with
the lines it had.  Onto IOS-XE, NX-OS, EOS, AOS-CX and Junos the
trunk is written with that VLAN on the allowed line beside the native
line.  **Release 0.7.7 and earlier left it off that line** — a port
with no untagged VLAN, where the allowed list decides what a trunk
carries — for every OS10 trunk that has an access VLAN, in jobs that
said `completed`: check the allowed list of every trunk with a native
line migrated from OS10 then, and add the native VLAN to it.  A trunk
with an access VLAN and no tagged one was written there as a trunk
that allows NONE; it is a trunk of that one VLAN.  As a target: the
allowed line is the source's list without its native VLAN (those
releases wrote the VLAN on both lines when the source list named
it).  A native VLAN the source list does NOT hold is one the source
trunk does not carry, as the tree reads it.  It is not written as an
access VLAN; `no switchport access vlan` stands in its place under a
`! review:` line: `! review: native VLAN 10 is stated for this trunk
and its allowed list leaves it out, so no untagged VLAN is written
for this port; Dell's pages disagree on whether the next line leaves
an OS10 trunk with no untagged VLAN or with VLAN 1 -- check what this
port is to carry untagged`.  (The VLAN in it is the output's: after a
VLAN map, the new id.  And where a map would bring such a native VLAN
INTO the source list, it is cleared if the map has merged it with a
VLAN of the config that the list names, and the new id is taken out
of the list -- the trunk then written as above -- if the list only
covered that number with a range; the job says which, see
[`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A trunk's allowed
list is not what I wrote".)  Dell's page for that command says it resets the
access VLAN membership, and gives VLAN 1 ("The no version of this
command resets access VLAN membership on a L2 access or trunk port
to VLAN 1."); Dell's VLAN-stacking configuration notes (10.5.5 to
10.6.1) describe the trunk the same chapter's procedure makes with it
as "pure trunk ports without any access VLAN membership", which "drop
any untagged or tagged (with other than configured TPID) traffic on
those ports"; which a switch does is not established, so check what
the port carries untagged.  As a source,
that line is read on any switched port: a trunk is left with no
native VLAN, and an access port with no access VLAN stated.  A trunk
that states no access VLAN is read the same way, as carrying no VLAN
untagged -- the reading that carries fewer.  Dell: "By default,
native VLAN of a port is the default VLAN ID of the switch."  Which id
that is is a setting of the switch (`default vlan-id`) that no trunk
states, and that no Dell example and no capture prints as
configuration, so nothing is filled in for it (no committed capture
has such a trunk).  As a target, a trunk with NO native VLAN in the
tree -- one that carries no VLAN untagged, whatever its list, the
empty one included -- is written `no switchport access vlan` after
`switchport mode trunk`, under its own review line: `! review: no
untagged VLAN is stated for this trunk; an OS10 trunk with neither an
access line nor the next line is an untagged member of the switch's
default VLAN, and Dell's pages disagree on whether the next line
leaves it with no untagged VLAN or with VLAN 1 -- check what this
port is to carry untagged`.  Where the allowed line written below it
holds VLAN 1 the line adds `; no Dell page shows VLAN 1 on an OS10
trunk's allowed line` before the dash.  An interface another record
of which states its untagged VLAN -- a native VLAN, or an access VLAN
-- is not written the line: OS10 applies an interface's stanzas in
turn, and the line would take that VLAN back.  Release 0.7.7 and earlier
wrote such a trunk with no access line, which the switch makes an
untagged member of its default VLAN.  The tree
cannot tell "no untagged VLAN, stated" from "not stated", so an OS10
trunk with neither line comes back onto OS10 with the line, and one
that has it keeps it.  As a
target, a Cisco, Arista or AOS-CX trunk that states no native VLAN and
has VLAN 1 on its list -- its platform's default native VLAN -- is
written `switchport access vlan 1` with VLAN 1 off the allowed line;
release 0.7.7 and earlier wrote VLAN 1 ON the allowed line, tagged,
and no access line: check such trunks migrated then.  `interface range` is
not read, so a trunk stated that way has no VLANs in any output.  The
vendors' own sentences are in the
[vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunks-untagged-vlan-and-its-allowed-list-platform-by-platform).

## Two things that would have been silent bugs

Recorded here because they change how you should read a migration report:

1. **`switchport access vlan` on a trunk port is the NATIVE VLAN.**
   OS10 emits no `switchport trunk native vlan` line at all.  Reading it
   as the access VLAN inverts the port's L2 semantics.
2. **`management route` is not `ip route`.**  It installs into the
   management VRF only.  In the reference corpus it outnumbers `ip
   route` 8:2, so treating it as a normal static route would put a
   management-only default into the global RIB.

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — the full per-codec
  capability matrix (§A lists every lossy / unsupported path with its
  reason).
- [`../vendor-research/dell_os10/`](../vendor-research/dell_os10/) — the
  grammar dossier this codec was built from, including the measured
  counts behind each trap above.
