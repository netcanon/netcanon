# Aruba AOS-S — What works for me?

If you operate Aruba AOS-S (formerly ProCurve) switches and want to
know what Netcanon does for you, this is the page.

## TL;DR

- **`aruba_aoss`** — AOS-S CLI parse + render.  **Certification:
  certified.**  Bidirectional.

The codec covers AOS-S WB / WC / KB software branches across the
major AOS-S generations represented in the corpus: 2920 / 2930F /
2930M stack / 5400R modular chassis.  The CLI grammar is stable
across the AOS-S product line, so other generations (2530, the YA
branch, etc.) parse and render through the same pipeline — they
just aren't pinned by a fixture yet (operator captures welcome —
see [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)).

## What translates well

[Tier 1](../CAPABILITIES.md#tier-1--auto-translatable-cross-vendor-stable):

- `hostname`, DNS / NTP servers (`domain`, `syslog_servers` and
  `timezone` + DST rule are declared **unsupported** on this codec —
  see the capability matrix; they do not round-trip)
- Interfaces — slot-port and letter-slot-port (`A1-A24`, `B1-B24`
  on modular 5400R) port-id ranges, descriptions, IPv4 SVI L3
- VLANs — ID, name, tagged/untagged port lists with comma-separated
  range expansion (`A2-A6,A8-A10,A12-A24`), `primary-vlan`
- Static routes (incl. `ip default-gateway` form)
- LAGs (`trk<N>` reconciled with cross-vendor `Port-channel<N>`).  The
  device writes a LAG `trk1` on its `trunk` line and `Trk1` everywhere
  else; it is one name here, `trk1`, as a key of a rename map (`Trk1`
  reaches it too) and as its one row in the rename modal.  A
  translation from AOS-S to AOS-S does not rename it; its row is
  then under *Other names in the config*.  A second `trunk` line for
  a LAG adds its ports to the first, and a second `interface` stanza
  for an interface goes on with the first (an address it states
  again is kept once)

[Tier 2](../CAPABILITIES.md#tier-2--translatable-with-caveats):

- SNMP v1/v2c/v3 — `snmpv3 user` + `snmpv3 group` mappings; engine
  ID; trap-host with `trap-level` filtering
- RADIUS — `radius-server host <ip> key <secret>`
- DHCP server pools (`dhcp-server pool` grammar with default-router
  + dns-server + network + range)
- Local users — `password manager sha1` hash (and other AOS-S hash
  forms) form-preserving migration

Parse-tolerant (parsed but not currently rendered cross-vendor —
intra-AOS-S round-trip preserves them; cross-vendor render path is
future work):

- `dhcp-snooping` — `authorized-server` lists, VLAN scope, trust-port
- `web-management ssl`, `ip authorized-managers` management-plane
  ACLs

## L3 redundancy: VRRP (no anycast)

**New in v0.2.0** (Wave B — classic VRRP wire-up).

AOS-S nests VRRP groups inside the per-VLAN stanza — the VLAN IS the
SVI on AOS-S, so the redundancy group lives next to the VLAN's IP
address rather than on a separate routed interface.  Canonical
attaches the group to the synthesised `Vlan<N>` interface (see the
codec's `_svi_absorption.py` pattern).

### Grammar

```text
router vrrp
;
vlan 100
   name "Mgmt"
   ip address 10.0.100.1/24
   ip vrrp vrid 10
      virtual-ip-address 10.0.100.254
      priority 110
      preempt
      enable
      authentication mode plaintext-password "SECRET"
      exit
   exit
```

Sub-commands handled: `virtual-ip-address`, `priority`, `preempt` (+
absence ⇒ `preempt=False`), `enable` (mandatory marker; consumed
without a canonical field — render re-emits it), `authentication mode
plaintext-password "<key>"` (→ `plain:<key>`).  The top-level `router
vrrp` enabler line is mandatory and gets re-emitted any time there
are groups in the canonical tree.

Multiple `ip vrrp vrid` blocks in the same `vlan N` stanza produce
multiple `CanonicalVRRPGroup` records on the SVI.

### Known limitations

- **Single virtual-ip-address per vrid.**  AOS-S `virtual-ip-address`
  accepts ONE address per group.  Cross-vendor migration from
  multi-VIP sources (Cisco IOS-XE `vrrp 10 ip X secondary`, Junos
  `virtual-address [ X Y Z ]`) emits the first VIP and drops the tail
  with a `; review:` comment — operator must split into multiple
  groups manually if redundancy is needed on every address.
- **No anycast-gateway grammar.**  AOS-S is a campus L2/L3 codec
  with no equivalent of Arista VARP / Junos virtual-gateway-address /
  Cisco SD-Access fabric forwarding.  All anycast canonical paths
  are declared `unsupported` and parse-and-ignore.
- **No CARP, no HSRP.**  Only IETF VRRP.
- **AOS-S vendor default is `preempt=False`**, opposite to most
  other vendors — the parser overrides the canonical default (True)
  when the `preempt` token is absent from the source.

### Cross-references

- [`../v0.2.0-planning/01-vrrp-canonical/`](../v0.2.0-planning/01-vrrp-canonical/)
  — VRRP canonical model design (`CanonicalVRRPGroup`); see
  `02-per-vendor-grammar.md` § "Aruba AOS-S" for the single-VIP
  constraint rationale.
- [`../v0.2.0-planning/02-anycast-gateway/`](../v0.2.0-planning/02-anycast-gateway/)
  — anycast-gateway design (no AOS-S participation; declared
  unsupported across all three anycast canonical paths).

## Lossy paths

See per-codec `CapabilityMatrix.lossy` declarations in the codec
source — most fields parse + render cleanly within the documented
surface.

## What we don't do

[Tier 3](../CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered):

- **Aruba-specific firewall** features (`access-list extended`
  beyond simple ACL parse-tolerance)
- **NAT**
- **IPsec VPN**
- **QoS** policies
- **Routing protocols** (OSPF / RIP / static routes parse, but
  protocol stanzas informational)
- **PoE policy detail** beyond per-port `power-over-ethernet enable`

## Real-world fixtures we've validated against

Provenance in
[`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md):

- **`aruba_central_5memberstack_rendered.cfg`** — rendered from
  Aruba Central's bulk-config 5-member-stack template (BSD-2-Clause
  upstream)
- **`hpe_community_2930f_wc1607_intervlan.cfg`** — 2930F on
  WC.16.07.0002 with 12 VLANs, inter-VLAN L3, `ip helper-address`
  on 10 VLANs (HPE Community forum-share)
- **`hpe_community_2920_wb1608_dhcp_snooping.cfg`** — 2920 on
  WB.16.08.0001 — different OS family (WB vs WC) and major version
  from the other captures.  `dhcp-snooping` with 13
  `authorized-server` entries, NTP iburst, ACLs
- **`hpe_community_2930f_wc1610_dhcp_server.cfg`** — 2930F on
  WC.16.10.0005 with `dhcp-server pool` grammar exercised across
  3 pools and 4 VLANs
- **`user_contrib_2930m_wc1611.cfg`** — 2930M stack on WC.16.11.0025
  (most-current WC LTS), JL323A chassis + JL083A flexible-module
  uplinks, `stacking` stanza, `oobm` per-member IP, SNMPv3 engineid,
  `password manager sha1` hash, slot-port + slot-letter-port range
  expansion
- **`hpe_community_5406rzl2_kb1515.cfg`** — 5406Rzl2 (J9850A)
  modular-chassis on KB.15.15.0008 (first KB-branch and first
  modular-chassis fixture); `module A type j9534a` + `module B
  type j9537a` line-card declarations

Spans WB / WC / KB software branches and 2920 / 2930F / 2930M /
5400R hardware classes (the body above hedges "other generations
including 2530 / YA branch parse + render through the same
pipeline — they just aren't pinned by a fixture yet").

The kb1515 capture is committed with every line at column 0, its
indentation lost between the switch and the repository (a forum or
paste step, inferred).  The 5-member-stack render has five body lines at
column 0 (`ip address` in each VLAN stanza, `no
power-over-ethernet` in two `interface` stanzas): an earlier version
of the in-tree render script put them there, and the file is kept
as it is, as an input whose stanza bodies are partly flat.

## Where a stanza ends, and a port's VLAN lines

**A stanza ends where the switch ends a context, not where the
indentation stops.**  HPE describes the CLI by commands: a command
that enters a context (`vlan 10`, `interface 3`, `oobm`) moves into
it; `exit` -- "Return to the previous context" (Basic Operation
Guide 16.10) -- leaves it, and `end` goes to the Manager level, out of
every context; and HPE's examples go from one context straight into
another with a command that enters it (`vlan-10` to `int-3`, `ospf`
to `vlan-8`).  No HPE switch guide says that indentation plays a
part, either way.  So Netcanon ends a `vlan`, `interface` or `vrrp
vrid` stanza at its `exit` or an `end` (in any letter case: `EXIT` is
the same command; an `end` in a `vrrp vrid` block ends its VLAN's
stanza too), or at a line in column 0 that enters another context or
that the top of the config reads (`ip route ...`, `trunk ...`,
`hostname ...`).  Any other line in column 0 is the stanza's.  A
config pasted with its indentation lost -- a forum post, a page
copied out of a browser -- is read as the one it was: `vlan 2` /
`name "VLAN2"` / `untagged A1` / `exit`, every line at column 0, is
VLAN 2 with its name and its port.  **Release 0.7.7 and earlier**
ended the stanza at the first line in column 0 and skipped every
indented line after it: such a config was read as VLANs with nothing
in them -- the committed KB.15.15 capture as three empty VLANs and no
port -- in jobs that said `completed` onto most targets (AOS-S itself
among them), and no job said a line was not read.  If you migrated a
config whose stanza bodies were not indented with one of those
releases, translate it again.

What is not established, and what Netcanon does there:

- **A line of the top inside a stanza that lost its indentation**
  (`ip route ...` between two of a VLAN's lines) is read as the line
  it is, and ends the stanza: the VLAN's lines after it are read at
  the top, where none of them is a line of its own.  For a port
  context HPE says the global commands are run there ("plus the
  global configuration, Manager, and Operator commands"); whether the
  switch then stays in the context is not established, and for a
  VLAN context whether it takes a global command at all is not.
  HPE's examples and every committed capture a switch printed indent
  their body lines and close each stanza with `exit`, and so do not
  have this shape; whether any release prints otherwise is not
  established.
- **An indented stanza header is no header.**  A line of the top is
  read only from column 0, so ` vlan 10` (a paste that put one space
  in front of every line) is read as nothing.
- **Detection needs the indentation, or the banner.**  An AOS-S
  config whose `;` banner was cut off and whose indentation was lost
  is detected as no codec; choose AOS-S as the source by hand.  With
  its banner it is detected whatever its indentation.

**`oobm` is a stanza, and nothing in it is read.**  Its lines
configure the out-of-band management port, and several are lines the
top of the config reads otherwise: HPE configures the OOBM interface's
address "within the OOBM context" (Management and Configuration Guide
16.09), the global forms being `oobm ip address` and `oobm ip
default-gateway`.  The open context decides what such a line means,
so an `ip default-gateway` in an `oobm` stanza is never the switch's
default route -- with its indentation or without -- and `interface
enable` there makes no interface.  The stanza ends at its `exit` (a
stack member's `member N` block in it has its own first) or an `end`,
or at a line in column 0 that enters another context or that the top
of the config reads and is no word of the context (`hostname ...`,
`ip route ...`): an `oobm` with no `exit` keeps its gateway and loses
no line of the switch's after it.  The management port's settings are
not carried into the output (below).

**A port's VLANs can be stated from the port's side.**  In an
`interface` stanza -- `tagged vlan 10,20`, `untagged vlan 5`, `no
tagged vlan 10`, `no untagged vlan 1` (HPE's examples print these in
`show running-config interface <port>`) -- and on one line at the
top, for a list of ports (`interface 1,6,7-10 tagged vlan 1,3,5-10`,
and its `no` form; HPE's syntax).  Netcanon reads each as the VLAN's
own line of the same meaning, where it stands in the text:
`interface 3` / `tagged vlan 20` is `vlan 20` / `tagged 3`.  The later
of two lines wins, whichever context it was typed in -- an inference:
HPE prints the one as the other, and says of the CLI, the menu and
the web interface that "the most recently configured version of a
parameter setting overrides any earlier settings for that parameter".
An `untagged vlan` line moves the port out of the VLAN it was untagged
in, as a later `vlan` stanza's `untagged` does.  HPE's own example
shows it for VLAN 1 (it prints `no untagged 1` under VLAN 1 for a port
made untagged in VLAN 10); for another VLAN it is an inference from
"A port can be an untagged member of only one port-based VLAN".
**Release 0.7.7 and earlier read none of these lines**, and a job
that had them said nothing.

- A port's line applies to a VLAN that a `vlan` stanza ABOVE it
  declares.  One that names another VLAN makes no VLAN: it is left
  out, and `dropped_tier3_sections` has a row for it --
  `interface 3 tagged vlan 30 (VLAN 30: declared by no vlan stanza
  above the line; not translated)`.  On the switch the one-line form
  is refused for a VLAN that does not exist ("If a VLAN or SVLAN does
  not exist, an error message displays"); what the switch does with
  the line in an `interface` stanza is not established.  A config
  that states memberships this way and declares its VLANs after its
  interfaces -- the order `show running-config` prints the two kinds
  of stanza in -- has every such line in that list: move the `vlan`
  stanzas above the `interface` stanzas, or state the memberships
  under `vlan N`.  The rows are bounded in number (lines that read
  alike share one, and past a limit one last row counts the rest),
  and a row quotes the first characters of its line and the first
  few ids it names, then counts the rest.
- A stanza for several ports -- `interface 1,3` or `interface 1-4`,
  HPE's `interface <port-list>` -- gives its VLAN lines to each port
  it names.  No interface is named after the list (release 0.7.7 and
  earlier made one called `1-4`, and read nothing of `interface 1,3`),
  and anything else the stanza sets (`disable`, `name ...`) is not
  translated; a row says so.
- A port tagged and untagged in one VLAN keeps both memberships,
  where HPE gives a port one participation in each VLAN: see the
  known limitations in the CHANGELOG.
- `forbid vlan <list>` (and `forbid <ports>` under `vlan N`) is not
  read in either context: it makes no membership ("Prevents the port
  from joining the VLAN, even if GVRP is enabled on the switch"), and
  GVRP is not modelled.
- As a target, AOS-S output states every membership under `vlan N`,
  as a full `show running-config` does: no HPE example of the full
  configuration prints a port's VLAN line in an `interface` stanza.

## A banner is text

The parser reads a `banner motd` (not the `;` Configuration Editor
lines at the top, which detection reads) as text the switch shows,
not as lines of the config: each line of it is passed over by every
reader of the parse -- the Tier-3 rows, the check for a JSON or XML
paste, the release on the config-editor line and the deployment
detector (which had taken a banner line `module 1 type <part>` for the
chassis) included -- and nothing of it is translated.  Detection still
reads the text as it came.

- **The printed form.**  `show running-config` prints `banner motd`
  in column 0 and the banner's text as a double-quoted string that
  starts on that line, right after the quote, and runs across lines,
  the text's own line breaks printed as line breaks; the delimiter the
  operator typed is not printed (HPE's K.11.00 figure; a published
  R.11.121 printout).  A one-line banner is one line (`banner motd
  "Authorized use only."`).  `\'`, `\n` and `\t` are printed as typed
  in HPE's 16.06 and 16.10 listing; `\"` and `\\` are in its table of
  escapes, and are read the same way (inferred).  `banner exec` is read
  the same way, though no HPE page shows that type (inferred).  `banner
  motd` with nothing after it opens nothing, nor does `no banner motd`.
- **Where it ends**: at the first double quote that no backslash
  escapes -- on the line that opens it, at the end of a line of its
  text, or alone on a line.  A backslash takes the next character with
  it, and a backslash at the end of a line takes the line end, nothing
  of the next line.  The lines between are text, whatever they hold
  (`!`, `exit`, words of commands).  A printed line of the text may be
  a longer line wrapped at column 80; inside the quotes that is
  harmless.
- **Refused in words**, naming the line and quoting nothing (`parse
  failed: aruba_aoss: line <n> ...`):
  - a banner with no end before the end of the text;
  - text after the quote that ends a printed banner.  The printer
    writes nothing there, so such text means a quote in the banner's
    text ended it early (how a switch prints a typed `"` is not
    established), or that the listing lost a line -- as one of HPE's own
    guides prints a `banner motd "good morning` whose next quote is in
    the line after it (inferred);
  - a line outside every banner, after a printed one, with an odd
    number of double quotes, counting none a backslash escapes (`is
    outside every banner, and holds an odd number of double quotes
    ...`): a text with a line that ends in a quote, or is one, ends
    there, and the quote the switch printed after the text is left on
    a later line.  Read as it stands, the lines between were
    configuration;
  - a line of a banner that ends in another character than a line feed
    -- a form feed, a vertical tab, a carriage return on its own (the
    switch ends a line at a line feed, so where it ends the banner is
    not where those lines say).

  A detection of the hardware then says the lines that state it could
  not be read.  Paste the whole of `show running-config`; if the
  banner's text holds a double quote, change the banner on the switch,
  or remove its lines from the paste.
- **Not seen (a known limitation)**: a text that holds a quote at the
  end of a line, and after it either a line that opens another banner
  (which takes the switch's quote for its own end) or a last line with
  an odd number of quotes (which the switch's quote makes even).
  Nothing is left with an odd number of quotes, and the lines between
  are read as configuration (measured: an account line there is an
  account on the target).
- **The typed form**, in a pasted script: `banner motd %`, the text,
  and `%` again -- any character but a quote.  It ends at the next
  occurrence of that character, anywhere (the line that opens it
  included), and what follows it on its line is discarded (HPE's
  typed example ends at `penalties!%`).

⚠️ Up to 0.7.7 a banner's lines were read as lines of the config: a
banner line `password manager user-name ...` became an account with
privilege 15 on the target, its `vlan` and `ip route` lines became a
VLAN with an address and a route, and a line `module 1 type <part>`
the chassis the deployment detector proposed, in jobs that said
`completed`.  If you translated an AOS-S config with a banner of
several lines with 0.7.7 or earlier, translate it again, and look in
the old output for accounts, VLANs and routes the switch does not
have.

## Common gotchas

- **A RADIUS `encrypted-key` is carried to AOS-S only.**  With
  `encrypt-credentials` on, AOS-S prints a RADIUS key as
  `encrypted-key "<blob>"`, on a host line or on the global
  `radius-server` line (the global form is inferred from the host
  form HPE documents).  It is written back as it was onto AOS-S; onto
  any other target the server is written with no key, beside a review
  line: re-enter the secret there.  `key "<secret>"` migrates
  everywhere.  ⚠️ With 0.7.7 or earlier, the blob came out as the
  secret itself on every target, AOS-S included (`key "<blob>"`).
  Look for such a key in an old output.
- **Renaming or dropping `Vlan<N>` in the rename modal changes
  nothing.**  A translation from AOS-S to AOS-S lists each VLAN's
  routed interface under *Other names in the config*.  AOS-S writes
  a VLAN's address in the `vlan` stanza, by the VLAN's id, so an
  entry on that row is recorded by the job (`port_renames`,
  `port_drops`) and the output is the same to the byte.  Renumber or
  drop the VLAN itself, on the VLANs pane.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § F.
- **AOS-S has no allowed list.**  A port carries the VLANs that name
  it (`tagged`, `untagged`), so there is no trunk that states none.
  As a target: a trunk of every VLAN from another vendor — a Cisco or
  Arista trunk that states no list, an AOS-CX `vlan trunk allowed
  all`, a Junos `vlan members all` — is tagged in each VLAN the
  output declares (AOS-S cannot say "and any VLAN made later", and
  nothing in the output marks that more was meant: tag the port in a
  VLAN you add afterwards), and a trunk of no VLAN is tagged in none.
  Release 0.7.7 and earlier
  tagged a Cisco trunk with no list, and an AOS-CX `all`, in nothing.
- **The VLAN a port is untagged in is on its allowed list on the
  target.**  AOS-S states a port's untagged VLAN apart from its
  tagged ones (`untagged 1` in one VLAN, `tagged 1` in others), and
  the port carries it.  Onto a platform that has an allowed list —
  IOS-XE, NX-OS, EOS, AOS-CX, Junos — such a port is a trunk whose
  native VLAN is ALSO on its allowed line (`switchport trunk native
  vlan 10` beside `switchport trunk allowed vlan 10,20,30`), as HPE's
  own side-by-side of the AOS-S and AOS-CX grammars writes it; onto
  OS10 it is `switchport access vlan 10` beside an allowed line of
  the tagged VLANs.  **Release 0.7.7 and earlier left the untagged
  VLAN off the allowed line** on the first five, in jobs that said
  `completed`: where the list decides what a trunk carries — on
  AOS-CX, by HPE's own page — that port passes no untagged traffic.
  Check the allowed list of every trunk with a native line migrated
  from AOS-S then, and add the native VLAN to it.  As a target: a
  trunk whose own list leaves its native VLAN out is written
  `untagged` in no VLAN (it was written `untagged` in that one), and
  a `; review:` line in that VLAN's stanza names the port and says
  so.  A port is in the default VLAN until a line takes it out of it
  -- HPE: "In the factory default configuration, all ports are
  assigned to the default VLAN (DEFAULT_VLAN; VID=1).", and "Any
  ports not specifically removed from the default VLAN remain in the
  DEFAULT_VLAN, regardless of other port assignments." -- so VLAN 1's
  stanza takes such a port out with `no untagged` where the output
  tags it in some VLAN (below), and the line says so: `; review: port
  5 -- native VLAN 10 is stated for this trunk and its allowed list
  leaves it out, so no untagged line is written for this port and it
  is taken out of the default VLAN -- check what this port is to
  carry untagged`.  Where no line takes it out -- a trunk that
  carries nothing, or one tagged in VLAN 1 -- the line for a port
  says what HPE says of one, and all it says: `; review: port 5 --
  native VLAN 10 is stated for this trunk and its allowed list
  leaves it out, so no untagged line is written for this port; in
  the factory default configuration an AOS-S port is in the default
  VLAN (VID 1), and it remains there until it is removed -- check
  what this port is to carry untagged`.  Neither of HPE's sentences
  says whether that membership is tagged or untagged, and the line
  does not either.  A LAG has its line under `Trk<n>`, and a member
  port that states the same lines under its own name.  For a
  `Trk<n>` name, and for a port the same output puts on a `trunk`
  line, the line gives HPE's sentences for a trunk group instead
  (2530, 2930F/M and 3810/5400R management guides: "Creating a new
  trunk automatically places the trunk in the DEFAULT_VLAN,
  regardless of whether the ports in the trunk were in another
  VLAN.", "You can configure a static trunk in the same way that you
  configure a port for membership in any VLAN.", and of the ports of
  a trunk, "configuration for all ports in a trunk is done at the
  trunk level"): `; review: port Trk1 -- native VLAN 10 is stated
  for this trunk and its allowed list leaves it out, so no untagged
  line is written for this port; a new AOS-S trunk group is placed in
  the default VLAN (VID 1), a static one is configured for VLAN
  membership as a port is, and the VLANs of a port that is in one are
  the group's -- check what this port is to carry untagged`.  The
  groups written are static (`trunk <ports> trk<n> lacp`; HPE's table
  has "TrkX (Static)" beside "DynX (Dynamic)"), so what HPE says of a
  dynamic LACP trunk -- that it "operates only in the default VLAN"
  -- does not bear on them.  Each line says what the text the trunk
  was read from states and no more: what the source switch did with
  that VLAN is each vendor's to say, and not every vendor says it.
  The VLAN in it is the output's: after a VLAN map, the new id.

  **A port or trunk group that carries no VLAN untagged is taken out
  of VLAN 1.**  VLAN 1's stanza is written `no untagged <names>` for
  every name the output tags in some VLAN, lists untagged in none,
  and names on no line of VLAN 1 -- after the `name` line and before
  `untagged` and `tagged`, the order of HPE's examples from 15.14 on
  (`name`, `no untagged`, `untagged`, `ip address`).  A trunk group is named
  `Trk<n>`, as the other lines name it.  A tree with no VLAN 1 record
  (a source that declares none) is written a `vlan 1` stanza for it,
  first among the VLANs and with no `name` line, and a trunk that
  carries VLAN 1 tagged -- a Junos trunk of `vlan members all` -- is
  written `tagged` there.  Such a port is a Junos trunk with no
  `native-vlan-id`, a Cisco or Arista trunk that states no native
  VLAN and whose list leaves VLAN 1 out, an OS10 trunk with no access
  VLAN, an AOS-CX trunk of `vlan trunk native <N> tag`, and a trunk
  whose native VLAN its list leaves out.  Release 0.7.7 and earlier
  wrote no such line, and such a port stayed in VLAN 1, in jobs that
  said nothing.  The AOS-S parser reads the line, above the lists,
  as removing nothing: on lists that share no name that is the tree
  the output was written from.  A trunk that carries nothing -- on no
  VLAN line at all -- has no AOS-S form (HPE: "a port must always be
  a tagged or untagged member of at least one port-based VLAN."), and
  stays in VLAN 1.  (A Cisco, Arista or AOS-CX trunk that states no
  native VLAN and has VLAN 1 on its list carries VLAN 1 untagged by
  its platform's default, and is written `untagged` in VLAN 1.
  Release 0.7.7 and earlier wrote it `tagged` there: check such
  ports migrated then.  And where the VLAN pane's map merges such a
  trunk's untagged VLAN with a VLAN it carries tagged -- VLAN 10
  given the id 1, say -- the merged VLAN's stanza lists the port
  on its `untagged` AND its `tagged` line, in a job that says only
  that port lists were merged: take the port off the one that is
  not meant.)  For a trunk of nothing, decide what the port is to
  carry, look at what the switch has it in, and write its lines.
  The VLAN pane's map keeps to the same reading: where it would
  bring a native VLAN that the list leaves out INTO the list, the
  native VLAN is cleared if the map has merged it with a VLAN of the
  config that the list names, and the new id is taken out of the
  list -- the review line then standing under that id -- if the
  list only covered that number with a range; the job says which
  ([`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) § "A trunk's
  allowed list is not what I wrote").  The vendors' own sentences are in the
  [vendor reference](../vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md#a-trunks-untagged-vlan-and-its-allowed-list-platform-by-platform).
- **A port with no `interface` stanza is a port all the same.**  An
  AOS-S switch prints an `interface` stanza only for a port with a
  setting of its own — a name, `disable`, an address.  Every other
  port is in the config through the `untagged` / `tagged` lists of
  its VLANs, or as a member on a `trunk` line; a switch's own config
  can have no `interface` stanza at all.  Netcanon reads each such
  port as a port: enabled, with the VLANs the lists give it and the
  LAG its `trunk` line gives it.  Onto another vendor it is written
  with its own stanza — `switchport access vlan`, `vlan trunk
  allowed`, `channel-group` — like a port that had one.

  **Release 0.7.7 and earlier wrote no line for such a port** on a
  target that writes a port from the port's own stanza: onto NX-OS,
  AOS-CX, OS10 and IOS-XR the output had none of those ports, and so
  none of their VLANs, in a job that could say `completed`; a `trunk`
  member with no stanza was no member of its LAG on those four and
  on EOS, IOS-XE CLI and Junos.  If you
  migrated an AOS-S switch with one of those releases, compare the
  output with the source's `vlan` and `trunk` lines port by port.

  As a target, AOS-S output follows the device: a port that has
  nothing to say in a stanza of its own — enabled, no name, no
  address — and that a VLAN's list or a `trunk` line names gets no
  `interface` stanza.  A port that is disabled, named or addressed
  has one, and so has a port no other line names.  So has a port
  under a name the switch does not use (`Ethernet1`), and a port
  whose line would not read back as it was written: Netcanon reads
  each `trunk` line and VLAN list back as it writes it, and a
  `trunk` line with a member whose name has a space in it, or a
  list that would write `01` as `1`, leaves its ports their
  stanzas.  The output is a
  whole configuration: read into a switch that already has one, a
  port left out here keeps whatever that switch had for it.
- **A port range that names ports the switch does not have is
  refused.**  `tagged 1-1001` is 1,001 ports to everything downstream.
  One range is read up to 1,025 ports; the DIFFERENT ports that ranges
  name, and the ports that only a VLAN's or a LAG's list names, are
  held to the server's config size limit (`ports`), and the job says
  `refused:` with the range that passed it.  Each of those ports is
  then an interface, and counts toward `interfaces` with the ports
  that have a stanza.  An AOS-S OUTPUT is held to the same count of
  the ports its ranges name, where it is written.  See
  [`../CAPABILITIES.md`](../CAPABILITIES.md) § H.
- **`include-credentials` mode** affects how hashes appear in
  running-config — Netcanon parses + preserves both forms.
- **Banner format + positional port lists** — the codec correctly
  parses the AOS-S banner / "Configuration Editor" prelude and the
  position-sensitive port-list forms (`untagged 1,3,5-10` etc.).
- **Stacking-aware port IDs** — 2930M stacks use `1/1-1/47`,
  `1/A1-1/A4` forms which expand correctly in cross-vendor port
  rename.

  ⚠️ **Uplink-module ports fuse onto access ports on most targets.**
  `1/A1` is a port on uplink module **A**; `1/1` is access port 1.
  They are physically different ports, and Netcanon's parser keeps
  them apart.  But no other vendor models a letter-slot module, so
  every target that formats a `stack/port` pair renders both as one
  name — `ge-1/0/1` on Junos, `Ethernet1/0/1` on NX-OS, `port1` on
  FortiGate, and so on for most targets.  The two ports end on one
  name: a target that writes a stanza for each port writes two under
  it, each with its own port's VLANs, and a device reads one port.

  Since #482 this is **reported** in the job's warnings; before that
  it was silent, and silent specifically on the captures most likely
  to hit it (an AOS-S config with no `interface` stanzas names its
  ports only inside the VLAN lists, which the old collision check
  never looked at).  Netcanon does not repair it automatically —
  there is no correct target port to invent.  Supply an explicit
  `port_rename_map` entry per uplink port, e.g.
  `{"1/A1": "xe-1/1/1"}`, to place them somewhere distinct.  Until
  you do, a job with no devices declared is `partial`, not
  `completed`, and lists each shared name with its two ports in
  `fused_ports` (see [CAPABILITIES.md](../CAPABILITIES.md) section
  D1); declaring both devices pairs each uplink with an uplink.
- **A VLAN's address onto another vendor** — AOS-S writes a VLAN's
  address in the `vlan` stanza, and the codec carries it on an
  interface it names `Vlan<id>`.  The port translator does not read
  that name, so it is left as it is on every target: `interface
  Vlan10`.  On EOS, IOS-XE and NX-OS that is what the interface is
  called, and the job is not held for it.  On Junos (`set
  interfaces Vlan10 ...`), AOS-CX, IOS-XR, VyOS, OPNsense, FortiOS
  and RouterOS it is not, and OS10 prints the name as `vlan10`:
  onto those, with no devices declared, the job is `partial` and
  lists each in `untranslated_ports` until you give it the
  target's own name (`{"Vlan10": "irb.10"}` for Junos), or — if
  you know the target takes it — keep it (`{"Vlan10": "Vlan10"}`,
  or *keep this name* on its row).  See
  [CAPABILITIES.md](../CAPABILITIES.md) section D1.
- **Moving between AOS-S models** — an AOS-S port's name depends on
  the model, its uplink module and whether stacking or VSF is on, and
  a same-vendor translation does not rename ports by itself.  Declare
  both switches — in the Interface rename modal (*Source device* and
  *Target device* on the Ports pane) or on the API — and the ports
  are paired by position: a standalone 2930F's `49`-`52` become a
  stacked 2930M's `1/A1`-`1/A4`.  A VSF fabric or a stack of several
  switches can be declared on either side, or on both: its members
  pair in the order you list them, not by member number (see
  [`CAPABILITIES.md`](../CAPABILITIES.md) section G).  The `vsf` or
  `stacking` stanza itself — which switches the stack is made of,
  their priorities, the ports a fabric uses as its links — and the
  `oobm` block, per-member addresses included, are not carried into
  the output; set the target stack up as its own.  The job has no
  warning for this: it is said here, and in the plan's `caveats`
  where the 2930F fabric or 2930M stack is declared from a model
  family.  The source switch is read from the config: an AOS-S
  config states its part number, the modules it is provisioned for
  and whether it is stacked.  The modal fills the source device in
  from those lines and shows them
  (`POST /api/v1/migration/detect-deployment` on the API).
  A stack's banner names no model, so a stack config pasted without
  its `stacking` or `vsf` stanza states no device; and a proposal
  lists a stack's members lowest number first.
  The 2930F and 2930M series are modelled; a 3810M can be declared
  through its target profile; a switch with neither cannot be declared
  yet.  Only the port names are translated: a config that removes
  ports from VLAN 1 with `no untagged` gets that line back for the
  ports the output tags in some VLAN and lists untagged in none; a
  port it lists untagged in another VLAN gets none, and leaves VLAN 1
  by that line (HPE: "You can remove all ports from the default VLAN
  by placing them in another port-based VLAN").  A port the source
  removes and puts in no other VLAN gets no line, and stays in VLAN 1
  on a factory-default target — check VLAN 1 on the result.
  See [`../CAPABILITIES.md`](../CAPABILITIES.md) § G.
- **Hash portability** — `sha1` hashes don't translate to all
  targets cleanly; review-comment surfaces in the rendered output
  when targeting incompatible vendors.
- **Backup-side**: definition YAML lives at
  [`../../netcanon/definitions/library/aruba/aos-s/16.x.yaml`](../../netcanon/definitions/library/aruba/aos-s/16.x.yaml).

## See also

- [`../CAPABILITIES.md`](../CAPABILITIES.md) — full capability matrix
- [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md)
  — live certification state
- [`../../tests/fixtures/real/NOTICE.md`](../../tests/fixtures/real/NOTICE.md)
  — fixture provenance
- [`../../BUG_REPORTING.md`](../../BUG_REPORTING.md)
- [`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md)
- [`../HOW_WE_TEST.md`](../HOW_WE_TEST.md)
