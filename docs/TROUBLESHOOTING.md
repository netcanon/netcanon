# Troubleshooting — When a translation doesn't go cleanly

Operator-facing diagnostic flowchart for "I tried to translate a
config and the result isn't what I expected."

The Netcanon discipline classifies every output condition into one
of three camps: **expected (Tier-3)**, **expected (Lossy)**, or
**actual bug (CODEC_BUG)**.  This page walks the diagnosis.

---

## Step 1: What does the migrate page say?

The migrate page surfaces three notification surfaces alongside
every translation:

### A. The Tier-3 banner

> "Detected but not translated: firewall rules (47 lines), NAT
> rules (12 lines), IPsec VPN (3 phase1 entries)..."

If your missing content is in this banner: **expected.**  The Tier-3
boundary is documented in
[`CAPABILITIES.md`](CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered)
— firewall, NAT, VPN, QoS, routing protocols, PKI.  These surfaces
deliberately don't translate cross-vendor.

**Action:** if you need them translated, plan to hand-translate or
pair with an adjacent tool — see
[`COMPARISON.md`](COMPARISON.md) for Capirca / Aerleon (firewall
DSL) and Batfish (network analysis).

A row that begins `inactive:` is different: it is a Junos statement
the source had deactivated (`deactivate interfaces ge-0/0/2`, or
`inactive: ge-0/0/2 {` in the hierarchical form).  The device was
not running it, so it is not translated, and the banner does not
count it among the sections to apply by hand.  (A row that begins
`delete:` is a statement a load file marks for deletion, and is
treated the same.)  **Action:** none, unless you meant to bring it
back into force on the target — then add it there by hand.  Two
things to look at when the row is an interface: whether a
`routing-instances` statement or a LAG member still names it — what
names a deactivated statement is still read, see
[`vendors/juniper_junos.md`](vendors/juniper_junos.md) — and
whether the output has what you expected of the group or the
interface-range that would have filled it: under a deactivated path
that is left out too.

A row that begins `preconfigure:` is an IOS XR `interface
preconfigure <name>` stanza: configuration the router holds for an
interface it does not have yet.  It was not in force there either,
and is left out for that reason.  **Action:** none, unless the
target is to hold configuration for the same hardware — then write
it there by hand.

Some rows are sections the parser itself took out, and are in no
output: an `interface range ...` header in a text read as IOS-XE or
IOS XR (configure the ports it covers by hand), an `interface
breakout <port> map <profile>` line in the same (split the port on
the target by hand, if it is to be split there), and
`<dhcpd><zone>: no <zone> in <interfaces>, so its DHCP pool has no
interface` for an OPNsense DHCP pool whose zone is assigned to no
device (bind the pool to a zone that has one, or write it on the
target by hand).  See
[`CAPABILITIES.md`](CAPABILITIES.md#b-tier-3-sections-detected-banner).

A job that is `partial` with "No source constructs were recognized"
and rows that all begin `inactive:`, `delete:` or `preconfigure:`
read nothing else: every statement it understood was one the
source held and did not run, or the text is not a config of the
vendor chosen.

**A pasted Junos `show configuration` came out empty or was
refused.**  Read are the hierarchical form as a device prints it and
the lines of the session around it (the prompt, `{master:0}`,
`[edit]`, a pager's prompt).  Refused, with the reason in the
error: a `}` that closes nothing, a block that is never closed, a
`/*` comment opened after the first block and never closed — a
capture that was cut off.  If
the text begins with anything else that is not configuration, take
it off, or use `show configuration | display set`.

### B. The unsupported-paths panel

> "Field /routing-instances/instance is declared `unsupported` for
> this codec pair.  Reason: schema shipped, codec wire-up pending
> (ship-before-wire path)."

If your missing field is in this panel: **expected, with a cited
reason.**  The codec's `CapabilityMatrix` declares it explicitly.

**Action:** check the cited reason.  If it says "wire-up pending"
or "ship-before-wire," the codec author is working on it.  If it
says "different vendor semantics" or similar architectural reason,
this is by design.  File a feature request with `feature_request.yml`
if you have a strong use case.

### C. The lossy-paths panel

> "Field interfaces[].mtu translates with sub-field drift —
> source vendor encodes per-interface MTU, target vendor uses
> per-VLAN MTU; some MTU values may not survive round-trip."

If your output diff matches a path in this panel: **expected within
the documented boundary.**  The codec declared this lossy and cited
why.

**Action:** review the cited reason.  Lossy paths usually have a
review-comment in the rendered output describing the drift; verify
that against your operational expectations.

---

## Step 2: Is it actually a CODEC_BUG?

A `CODEC_BUG` is when the translation produced output that
**contradicts the vendor docs** — parse misread the source, or
render emitted wrong target-vendor syntax.

The cross-mesh audit
([`HOW_WE_TEST.md`](HOW_WE_TEST.md)) targets zero CODEC_BUGs across
the full audit matrix.  Live count lives in
[`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
(machine-generated; can't drift behind code).  But the fixtures
don't exercise every real-world config — operator-submitted
fixtures regularly find new CODEC_BUGs.

### Symptoms that suggest CODEC_BUG

- Output is **silently** missing content that's NOT in the Tier-3
  banner or the unsupported-paths panel
- Output has **invalid syntax** the target device rejects on
  config-load
- Output has the **wrong semantic** (e.g. trunk port came out as
  access port; VRF binding lost; VLAN ID flipped)
- Round-trip through the same vendor is **non-idempotent** (parse
  → render → parse produces a different intent than the first
  parse)

### Symptoms that are NOT CODEC_BUG

- Output is missing Tier-3 content (firewall, NAT, VPN, QoS) →
  expected; see Step 1.A
- Output has review-comments saying "this didn't translate
  cleanly; review manually" → expected; that's the lossy-path
  surface working
- Output is shorter than the input → expected; Tier-3 deliberately
  drops, lossy fields collapse
- Hash-form passwords appear as `# REVIEW: ...` (or `! REVIEW: ...` /
  `; REVIEW: ...` — comment delimiter varies per target vendor) →
  expected; the hash didn't translate to the target vendor's hash
  form, and Netcanon **never** falls back to plaintext (see
  [`CAPABILITIES.md`](CAPABILITIES.md) "Hash-portability policy")

---

## Step 3: How to file a CODEC_BUG

If you've worked through Step 1 and Step 2 and concluded it's a
real bug:

1. **Sanitize your config.**  Use `netcanon sanitize`:
   ```
   netcanon sanitize -i my-config.txt -o sanitised.txt \
       --source-vendor cisco_iosxe_cli --dry-run
   ```
   Review the substitution table; then run again without
   `--dry-run` to write the output.

2. **Open a `bug_report.yml` issue.**  Required fields:
   - Source vendor + OS version
   - Target vendor + OS version
   - Sanitized input snippet (the smallest reproducer)
   - Expected output (what the vendor docs say should happen)
   - Actual output (what Netcanon produced — sanitized)
   - Netcanon version / commit SHA

3. See [`../BUG_REPORTING.md`](../BUG_REPORTING.md) for the full
   workflow including SLA and what we'll do with your submission.

---

## Common error patterns + diagnoses

### "My VLANs disappeared"

Most likely: VLAN-centric vs interface-centric paradigm mismatch.
Some vendors carry VLAN membership on the VLAN
(`tagged_ports` / `untagged_ports` lists), others on the interface
(`switchport access vlan <id>`).  Netcanon normalises to
VLAN-centric on parse via the
[`project_switchport_to_vlan`](../netcanon/migration/canonical/transforms.py)
transform.

If VLANs are missing on the target, check:
- The codec's `CapabilityMatrix` for `/vlans/vlan` declarations
- The migrate page's Tier-3 banner (VLAN-via-firewall-zone is
  Tier-3)
- The dropped_tier3_sections list
- Whether the source config was pasted without its indentation.  An
  AOS-S config is read as the indented one: a stanza ends at its
  `exit` or an `end` (see [`vendors/aruba_aoss.md`](vendors/aruba_aoss.md)
  § "Where a stanza ends").  Release 0.7.7 and earlier read such an
  AOS-S config as VLANs with no port and no address, in a job that
  said `completed`: translate it again.  An IOS XR, EOS, AOS-CX,
  IOS-XE CLI, NX-OS or OS10 config with no indentation is refused, not
  read (see [The job says `parse failed:` for an IOS XR
  config](#the-job-says-parse-failed-for-an-ios-xr-config), [for an
  EOS config](#the-job-says-parse-failed-for-an-eos-config) and [for
  an AOS-CX, IOS-XE CLI, NX-OS or OS10
  config](#the-job-says-parse-failed-for-an-aos-cx-ios-xe-cli-nx-os-or-os10-config)).
  Release 0.7.7 and earlier read such an AOS-CX, IOS-XE CLI, NX-OS or
  OS10 config as stanzas with almost nothing in them, in a job that
  did not say so: translate it again, from the config as the device
  prints it.
- On AOS-S, a row `interface <port> tagged vlan <ids> (VLAN <ids>:
  declared by no vlan stanza above the line; not translated)`: a
  port's VLAN line names a VLAN that no `vlan` stanza above it
  declares, and was left out.  Move the `vlan` stanzas above the
  `interface` stanzas, or state the membership under `vlan N`.
- On AOS-S, a row `interface <port-list> (a context for several
  ports: what it sets other than their VLANs is not translated)`: an
  `interface 1,3` or `interface 1-4` stanza set something other than
  its ports' VLANs (`disable`, `name ...`).  Its VLAN lines were read
  for each port; for the rest, write one `interface` stanza a port.

**One case is by design: a VLAN carried only by an
"allow-everything" trunk.**  Netcanon synthesises a VLAN record for
every VID your switchport lines mention, then prunes the ones no
config actually declares.  A VID is kept if it has a `vlan <N>`
stanza or an SVI, if a port uses it as an access or native VLAN, or
if it appears in a *specific* `switchport trunk allowed vlan` list.
It is dropped only when its sole mention is a wide range such as
`1-4094`, `2-4094` or `100-3000` — those say "carry whatever
exists", not "these VLANs exist", and expanding them would invent
thousands of VLANs you never wrote.

So `switchport trunk allowed vlan 701-710` gives you ten VLANs on
the target; `switchport trunk allowed vlan 1-4094` gives you none
from that line alone.  If your VLAN database genuinely lives behind
a wide trunk and nowhere else, declare the VLANs explicitly in the
source config before translating.

⚠️ Releases up to and including **v0.7.5** did not limit this
pruning to wide ranges — *any* VLAN appearing solely in a trunk-allowed
list was dropped, however short the list.  If you translated a trunked
config on one of those releases, re-check the target's VLAN
database: the trunk lines were
emitted correctly but the matching `vlan <N>` declarations could be
missing, which silently stops those VLANs forwarding.

### "A trunk's allowed list is not what I wrote"

A trunk's list is carried as what it MEANS, and each target writes
its own form for it.  What you may see:

* **No `switchport trunk allowed vlan` line at all** (IOS-XE, NX-OS,
  EOS).  The source trunk carried every VLAN — it said `all`, or
  `vlan members all`, or stated no list on a platform where that is
  every VLAN — and a trunk with no allowed line is how these
  platforms say so.  Nothing to do.
* **`switchport trunk allowed vlan none`**, or a Junos trunk with no
  `vlan members`.  The source trunk allowed no VLAN: it said `none`,
  its list was emptied by `remove` or `except`, it is a Junos trunk
  with no members or a Dell OS10 trunk with no allowed line and no
  access VLAN, or you dropped every VLAN it carried (next item).  (A
  Dell OS10 trunk with an access VLAN and no allowed line is not one
  of these: it carries that VLAN, and is written with it as its
  native VLAN and as its whole allowed list.  Release 0.7.7 and
  earlier wrote it `none`.)
* **The native VLAN is on the allowed line as well**
  (`switchport trunk native vlan 10` beside `switchport trunk allowed
  vlan 10,20,30`; `vlan trunk native 10` beside `vlan trunk allowed
  10,20,30`; `native-vlan-id 10` and `vlan members` that include
  it).  The source was an AOS-S port untagged in one VLAN and tagged
  in others, or an OS10 trunk with an access VLAN: both carry that
  VLAN, and a trunk's list is what it carries.  Nothing to do.
  **If the port was migrated with release 0.7.7 or earlier, the VLAN
  is NOT on the allowed line: add it**, or the port may carry no
  untagged traffic (on AOS-CX it does not, by HPE's own page).
* **A native line whose VLAN the allowed line leaves out.**  The
  source trunk said so itself -- only a source with a native line of
  its own can -- and it is written as it stood.  If that was not
  meant on the source either, add the VLAN to the list on both.
* **`vlan dot1q tag native`**, one line before the interfaces, on
  IOS-XE or NX-OS; **`switchport trunk native vlan tag`** on an EOS
  trunk; **`vlan trunk native 1 tag`** on an AOS-CX trunk.  The
  source trunk carries no VLAN untagged -- a Junos trunk with no
  `native-vlan-id`, an AOS-S port only `tagged` in VLAN 1, a Cisco
  or AOS-CX trunk whose native VLAN is sent tagged, a trunk whose
  native VLAN you dropped or merged in the VLAN pane -- and its
  list holds VLAN 1, which a trunk with no native line has for its
  native VLAN on these four.  Each line is that platform's form for
  a trunk that carries none.  On IOS-XE and NX-OS it is a line for
  EVERY trunk of the switch, written only where no port the check
  reads blocks it: no trunk carries a VLAN untagged, and no port is
  in a mode no mode line is written for (dynamic, private-vlan,
  dot1q-tunnel, fex-fabric and the like) or holds trunk lines in no
  mode.  A port written with no mode and no trunk line is not
  counted: on a Catalyst such a port is in dynamic auto by default,
  and should it become a trunk the line tags its native VLAN as
  well.
  **Action:** on NX-OS, Cisco recommends leaving the line off where
  the connected switch does not have it; on IOS-XE, Cisco documents
  that dot1x reauthentication fails on trunk ports under it; on
  EOS, what the port sends for VLAN 1 is not on Arista's page.
  Check the neighbour, and those, before deploying.
* **`! review: this trunk carries no VLAN untagged in the
  translated config; ...`** where the native line would be, on an
  IOS-XE or NX-OS trunk.  The same trunk, in an output where
  another trunk carries a VLAN untagged (or a port is in a mode no
  mode line is written for -- dynamic, private-vlan, dot1q-tunnel,
  fex-fabric and the like -- or holds trunk lines in no mode): the
  line for every trunk would tag that port too, and is not
  written.  As written,
  the port has native VLAN 1, and its list holds VLAN 1, so it
  carries VLAN 1 UNTAGGED, which the source did not.  The line says
  so, and that the line for every trunk would tag it.
  **Action:** decide what the port is to carry untagged on the
  switch, and state it: a native VLAN its allowed list leaves out
  (Cisco's sentences say a trunk whose list leaves VLAN 1 out
  carries no user traffic on VLAN 1 -- its tagged traffic in VLAN 1
  included), or the line for every trunk where every trunk can take
  it.  On a Catalyst 9500 High Performance switch Cisco documents a
  per-port `switchport trunk native vlan tag`, under the line for
  every trunk.  The job does not count this line.
* **`! review: native VLAN <N> is stated for this trunk and its
  allowed list leaves it out ...`** above `no switchport access
  vlan`, on OS10.  The source trunk states a native VLAN its own
  list leaves out (N is the id the OUTPUT has for it: the new one,
  if you renumbered the VLAN), so no untagged VLAN is written for
  the port: an OS10 trunk carries its access VLAN untagged whatever
  its allowed line says.  The line goes on to say that Dell's pages
  disagree on what `no switchport access vlan` then leaves the
  trunk with -- no untagged VLAN, or VLAN 1.  **Action:** check
  what the port carries untagged on the switch; if untagged traffic
  was meant to pass on the source, write `switchport access vlan
  <N>` instead.
* **`! review: no untagged VLAN is stated for this trunk ...`** above
  `no switchport access vlan`, on OS10.  The trunk has no native
  VLAN in the tree: it carries no VLAN untagged (a Junos trunk with
  no `native-vlan-id`, a Cisco or Arista trunk whose list leaves
  VLAN 1 out, an AOS-S port only `tagged`, an OS10 trunk with no
  access line, a trunk whose native VLAN is sent tagged).  With
  neither an access line nor `no switchport access vlan` an OS10
  trunk is an untagged member of the switch's default VLAN, so the
  line is written; the review line says that Dell's pages disagree
  on whether it then leaves the trunk with no untagged VLAN or with
  VLAN 1, and -- where the allowed line holds VLAN 1 -- that no Dell
  page shows VLAN 1 on an OS10 trunk's allowed line.  **Action:**
  check what the port carries untagged on the switch, and whether
  it takes the allowed line.
* **`; review: port <P> -- native VLAN <N> is stated for this trunk
  and its allowed list leaves it out ...`** in the `vlan <N>`
  stanza, on AOS-S.  The same case: the source trunk states a
  native VLAN its own list leaves out.  The port is tagged in the
  VLANs the list names, and no `untagged` line is written for it.
  Where it is tagged in some VLAN and not in VLAN 1, VLAN 1's stanza
  takes it out of the default VLAN with `no untagged`, and the line
  ends `... and
  it is taken out of the default VLAN`.  Otherwise the rest of the
  line says what is known.  For a port: `in the factory default
  configuration an AOS-S port is in the default VLAN (VID 1), and it
  remains there until it is removed` -- what HPE's guide says of a
  port, and all it says: not whether that membership is tagged or
  untagged.  For a trunk group (`Trk<n>`), and for a port that the
  same output puts on a `trunk` line: `a new AOS-S trunk group is
  placed in the default VLAN (VID 1), a static one is configured for
  VLAN membership as a port is, and the VLANs of a port that is in
  one are the group's` -- HPE's sentences for a trunk group.
  **Action:** decide what the port is to carry untagged, look at
  what the switch has it in, and write `untagged` or `no untagged`
  for it.
* **`no untagged <ports>` in `vlan 1`, on AOS-S, that the source did
  not have.**  Each port on it is tagged in some VLAN of the output
  and untagged in none: it carries no VLAN untagged, and an AOS-S
  port stays in the default VLAN until a line takes it out.  A
  source with no VLAN 1 gets a `vlan 1` stanza for it, with no
  `name` line, and a trunk of every VLAN is `tagged` there.
  **Action:** none, unless the port is meant to carry VLAN 1
  untagged; then write `untagged` for it in VLAN 1.  A trunk that
  carries nothing is on no VLAN line and stays in VLAN 1: AOS-S has
  no form for a port in no VLAN (see the limits in
  [`CAPABILITIES.md`](CAPABILITIES.md)).
* **`! review: the source trunk allows no VLAN ...`** in an AOS-CX
  interface stanza, and no `vlan trunk` line.  AOS-CX has no form
  for a trunk that carries nothing: a trunk left with no allowed
  VLAN carries every VLAN.  **Action:** add `vlan trunk allowed
  <list>` (and `vlan trunk native <N>`) for what the port is to
  carry, or `shutdown` it.  The job does not count this line.  As
  written, the stanza is a switched port with no `vlan` line — taken
  here to be an access port in VLAN 1 by the switch's default, which
  is not established here from an HPE page — so do not leave it as
  it is.
* **`vlan members all`, `vlan trunk allowed all`, or OS10's `1-4094`,
  on a port whose own stanza has no allowed line.**  A Cisco, Arista
  or AOS-CX port that states the trunk mode and no list is a trunk
  of every VLAN.  If its list is stated somewhere that is not read —
  on the port-channel it is a member of, in an `inherit
  port-profile` or a `source template` — the output is every VLAN
  where the switch has that list.  **Action:** write the list on the
  port.
* **`switchport trunk allowed vlan none` (or a Junos trunk with no
  members) for a port that had `switchport trunk native vlan <N>`
  and no `switchport mode trunk`** (NX-OS, EOS sources).  The port
  was read as a trunk from its trunk line, and a trunk read that way
  is given no VLAN the config does not name.  On the switch it is an
  access port.  **Action:** state the port's mode in the source, or
  correct the stanza in the output.
* **`! review: the source trunk allows every VLAN ...`** above
  `switchport trunk allowed vlan 1-4094` on OS10.  OS10 has no word
  for every VLAN, its ids end at 4093, and it lists only VLANs that
  exist.  **Action:** replace `1-4094` with the VLANs the switch
  has.  The port's own access VLAN is not in the range (a trunk
  carries it untagged, and OS10 does not take one VLAN on both
  lines): `1-9,11-4094` beside `switchport access vlan 10`.

And the warnings of the rename modal's VLAN pane that are about a
trunk.  When you drop VLANs:

```
vlan_rename: interface 'GigabitEthernet1/0/1' is a trunk that allowed only VLAN 100 which was dropped — the trunk now allows no VLAN
```

Every VLAN that trunk carried was dropped, so it is written as a
trunk of no VLAN (it is not removed, and the job is not failed by
it).  If that is not what you meant, keep one of its VLANs, or drop
the port as well.  A trunk of every VLAN is not touched by a drop or
a renumber: it is still every VLAN.

When you drop the VLAN a trunk carries untagged:

```
vlan_rename: interface 'GigabitEthernet1/0/1' had native VLAN 1 which was dropped — native VLAN cleared; the port allows every VLAN, and an output that writes it as a trunk of every VLAN still allows VLAN 1
```

The trunk's native VLAN was dropped, so it has none and is written
no native line.  (A Cisco, Arista or AOS-CX trunk that states no
native VLAN has VLAN 1 for one where its list holds VLAN 1, so
dropping VLAN 1 gives this warning for each such trunk.)  The
words after the semicolon are
there when the trunk's allowed list is every VLAN -- it stated no
allowed line, or `all`.  Such a list is left as it stands, so an
output that writes the port as a trunk of every VLAN still
allows the VLAN you dropped.  On IOS-XE, NX-OS, EOS and AOS-CX
such a trunk, with no native VLAN and VLAN 1 on its list, is written
that target's form for a trunk that carries no VLAN untagged (the
list above): where the VLAN you dropped is VLAN 1, the trunk still
carries it, TAGGED -- or, on IOS-XE and NX-OS where another port
blocks the line for every trunk (the list above), untagged by the
target's default, under a `! review:` line.  **Action:** if the trunk is
not to carry that VLAN, give it an allowed list on the target that
leaves the VLAN out (for IOS-XE, NX-OS and AOS-CX the vendors' own
sentences say such a trunk carries no user traffic on that VLAN;
for EOS what a trunk does with a native VLAN its list leaves out
is not established, so check it on the switch).  Beside a list that names its VLANs the
warning ends at `native VLAN cleared`: the VLAN is taken out of the
list as well.

When you give one VLAN the id of another:

```
vlan_rename: interface 'GigabitEthernet1/0/1' had native VLAN 10 outside its allowed list, and the map merges it into VLAN 20, which the trunk carries tagged — native VLAN cleared
```

The trunk stated native VLAN 10 beside an allowed list that left 10
out, and carried VLAN 20 tagged.  With the two made one VLAN, its
native line would name a VLAN that is on its list, and the trunk
would carry UNTAGGED what it carried tagged.  So its native VLAN is
cleared and the VLAN stays tagged (the job is not failed by it).
The same is done when the map gives VLAN 20 the id 10, and said as
`the map merges VLAN 20, which the trunk carries tagged, into it`.
The trunk then has no native VLAN, and is written as a trunk that
carries none untagged: where its list holds VLAN 1, on IOS-XE,
NX-OS, EOS and AOS-CX, by that target's form for it (the list
above), so that the target's own default does not make VLAN 1 its
untagged VLAN.  Before this
the merged VLAN was written as the trunk's native VLAN, and the job
said only that two VLANs were merged.

And when you renumber a VLAN onto an id that a trunk's list only
covers:

```
vlan_rename: interface 'Ethernet1' had native VLAN 1000 outside its allowed list, and the map gives it the id 900, which the list named only as a number no VLAN of the config had — 900 is taken out of the list, and the trunk does not carry native VLAN 900
```

The trunk stated native VLAN 1000 beside a list written around it
-- `switchport trunk allowed vlan 2-999,1001-4094`; `allowed vlan
except 1000` is such a list too -- so that VLAN was stated and not
carried.  You gave VLAN 1000 the id 900.  The config has no VLAN
900: the list names that number only because its range covers it,
and nothing was merged.  Left as it stood, the list would hold the
trunk's native VLAN, and the trunk would carry UNTAGGED a VLAN it
did not carry at all.  So 900 is taken out of the list and the
native VLAN is kept: `native vlan 900` beside
`2-899,901-999,1001-4094`, and on AOS-S and OS10 the review line
above, with 900 as its VLAN.  If you meant the trunk to carry the VLAN,
add it to the allowed list on the target.  The middle of the
warning has two more forms: `the map gives its id to 500` when it
is a number of the list that you renumbered onto the native VLAN's
id, and `the map gives it the id 900 and gives the same id to 500`
when you renumbered both.

Which of the two warnings you get turns on that id of the list.  A
VLAN the config has -- one it declares, an access port's VLAN, one
that a trunk names as its native VLAN or in a short allowed list
(see "My VLANs disappeared") -- is a VLAN the trunk carried tagged,
and giving the native VLAN its id is a merge.  So is any id of a
short allowed list, whether or not the config declares it.  A
number that only a longer list covers with a range is no VLAN, and
is taken out.  Both are done for any port that states a native
line and an allowed line, whatever its mode: a port in a dynamic
mode, or one with no mode line, can become a trunk.  (No VLAN is
made from the allowed list of such a port, and its short list is
read as a trunk's is all the same.)  Before this, either way, the
VLAN was written as the trunk's native VLAN with the VLAN on its
list.

### "My hashed password came out as a review comment"

By design.  Netcanon's hash-portability policy (see
[`CAPABILITIES.md`](CAPABILITIES.md))
**never** falls back to plaintext.  If the source vendor's hash
form (e.g. Cisco type-7) doesn't have a target equivalent, the
rendered output gets a `# REVIEW: <hash> from <source vendor>`
comment instead of a plaintext password.

The account itself is left out with it, on every target: an account
written without the password it had would be an account with none.

**Action:** re-create the user on the target device and set its
password with the target's native CLI (`username ... secret`, `set
system login user ... authentication plain-text-password`, etc.).

### "A user with a typed password came out as a review comment on Junos or OPNsense"

By design.  The source held the password as it was typed (IOS-XE
`password 0`, AOS-CX `password plaintext`, and the like), and the
config of Junos and OPNsense holds a password only as a hash:
Junos's `encrypted-password` and OPNsense's `<password>`.  Written
there, the typed string would be the hash itself, and no password
would open the account.  The review line names the account and says
why; it never quotes the password.

**Action:** add the user on the device and set its password there
(Junos `set system login user <name> authentication
plain-text-password`, which asks for it; the OPNsense user manager).

### "My LAG/Port-Channel name changed"

By design.  Cross-vendor LAG names get reconciled via the LAG
name-equivalence helper:
- Cisco: `Port-channel<N>`
- Arista: `Port-Channel<N>`
- Junos: `ae<N>`
- Aruba: `trk<N>`
- MikroTik: `bond<N>`

If you see `Po1` on Cisco become `ae1` on Junos, that's the
correct mapping.

### "My job is `partial` and the validation report is clean"

The validation report is one reason for `partial`; the port names
are another.  `job.error` (the status banner on the migrate page)
says which.  If it begins **"Port mapping is incomplete"** you
declared both devices: see that section below.  If it says **"Port
names are not settled"** you declared none, every port name was
translated by the shape of the name, and the job found one or more
of three things in its own output.

**1. Two source names ended on one name.**  The config of two
interfaces is written as one.  `fused_ports` on the job lists each
such name with the source names on it, for example
`{"Ethernet1": ["1/1", "1/A1"]}`, and the job's warnings have a
`port_rename: multiple source ports map to ...` line for each.  It
happens where the target's names cannot tell the two apart: an
AOS-S uplink-module port beside the access port of the same number,
ports numbered from 0 onto a platform that numbers from 1, two
aggregates numbered from 0, a Junos per-instance loopback (`lo0.2`)
onto a platform with one `Loopback0`.

*To settle it:* give all but one of the names a target of its own,
or drop it.  In the rename modal the rows carry the collision mark
and Apply is held until one of them is changed; type a target in one
row's field, or use its **drop** link.  Through the API:
`"port_rename_map": {"1/A1": "Ethernet49"}`, or `{"1/A1": null}`.

**2. A name was dropped because the target has no name for it.**
`unresolved_ports` lists them, they are in `port_drops`, and each has
a warning.  A hardware port — a management port onto a platform
with no form for one (NX-OS `mgmt0` onto IOS-XE), a breakout lane, a
port whose name shape the target cannot take — and a logical name
just the same: a loopback or a tunnel the target has no form for, a
FortiGate hardware switch (`internal`) with the LAN address on it.
What was configured on the name is not in the output.  A
sub-interface that went with its port is listed with it.

*To settle it:* say what is to happen to the name.  In the rename
modal the row is marked with a `?`: **keep verbatim** opens its
field for a target name, **drop** records that it is to go, and
**Accept the drops** above the table records that for every such
row at once.  Through the API: `{"mgmt0": "GigabitEthernet0/0"}`,
or `{"mgmt0": null}`.  Dropping a port settles its sub-interfaces
too.

**3. A name was left as the source config has it.**
`untranslated_ports` lists them, and each has a `could not classify
port name ...; left verbatim` warning.  The translator reads a name
through the source vendor's own classifier, and where that does not
know the name it leaves it: an IOS `GigabitEthernet1` (the
one-number ports of a virtual router), an OPNsense `igc0`, a
RouterOS interface with a name of your own, the `VlanN` interface an
AOS-S VLAN's address is carried on.  Whatever the output has of that
interface is under the source vendor's name — `set interfaces igc0
...` in a Junos config.

Not every name with that warning is listed.  One that is no foreign
name where it lands holds nothing: any name between the two IOS-XE
codecs, and a logical name the target itself writes exactly so for
the same kind of thing — that AOS-S `Vlan10` is `interface Vlan10`
on EOS, IOS-XE and NX-OS, and is listed on Junos, AOS-CX, OS10 and
the rest.  If a job is `completed` and its warnings have a `could
not classify` line for an interface, that is why; a hardware port
is always listed.

*To settle it:* give the name the name it is to have.  In the rename
modal the row says "(left under its source name)" and is marked with
a `?`: type a target in its field, use **drop**, or — where the name
is right on the target as it stands, as a RouterOS interface you
named `WAN` is on FortiOS — **keep this name**.  Through the API:
`{"igc0": "ge-0/0/0"}`, `{"igc0": null}`, or the name itself,
`{"WAN": "WAN"}`, which is how you say it is right as it is.  There
is no button that keeps several at once.

A value is a name or `null`.  `{"mgmt0": ""}` is refused with a 422:
a blank target is not a way to drop.  So is a target that draws
nothing — only white space, or only control or format characters
such as a zero-width space pasted in with a name: if the 422 says
"must not be blank" of an entry that looks filled in, retype it.

Apply (or post again), and the job is `completed` once none of the
three lists has an entry — unless the validation report holds it
for a reason of its own.  Every plan endpoint applies
`port_rename_map`, so the same entries settle the job whichever one
you post to.

**Should I declare both devices instead?**  For the hardware ports
among these names, yes: ports are then paired by position, each with
a port of its own (see [`CAPABILITIES.md`](CAPABILITIES.md) section
G).  For anything else, no.  A pair of devices decides nothing about
two loopbacks on one loopback, a tunnel that was dropped or a VLAN
interface left under its source name: with both devices declared the
output has them the same and the job is not held for them, so you
would get `completed` for the output you were warned about.  The
job's sentence offers the devices only where a hardware port is
among what it lists; where it does not offer them, an entry is what
settles the name.  The strip in the rename modal follows the same
rule with one device already chosen: where no hardware port is
among the names it says that choosing the other device "pairs
hardware ports by position: that settles none of the names above".
And for a vendor nobody has described a device of (NX-OS, IOS-XR,
OS10 and VyOS as shipped) there is no device to choose: the strip
does not offer one, though the job's sentence may.

Such a job said `completed` before this was part of the status, with
the same output and the same warnings.  If you applied a config
translated from another vendor without reading its warnings, look in
the output for two stanzas of one interface, for a management port
or a tunnel that is not there, and for an interface under the old
vendor's name.

Still only a warning: a name the config has only in a static route,
a DHCP pool, a tracking entry or a VXLAN source, and that the
translator cannot read — a route to `Null0`, say.  It is left as it
is and holds no job, since what those places hold is not always an
interface.  Read a finished job's warnings for `could not classify
port name`.

### "Two of my ports became one port"

Check the job warnings for `port_rename: multiple source ports map
to ...` (the line goes on `the target will render duplicate/fused
interface stanzas`, or, for names a config holds only in a VLAN's
list, `these are distinct ports on the source device and their VLAN
membership will be merged`).  Where the
sources are two ports this is a **real loss**, not cosmetic: two
physically distinct source ports resolved to a single name on the
target.  A target that writes a stanza for each port writes two
under that name, and a device reads one port.  The job is `partial`
for it, and lists the names in `fused_ports` (with both devices
declared, in `port_mapping_plan.fused`).  (One exception: a Junos
interface named with and without its unit, `sources: lo0, lo0.0`, is
one interface, and is not in `fused_ports`.  A unit other than 0 is
not: `sources: lo0, lo0.2` says a Junos per-instance loopback was put
on the target's one loopback — give it a loopback of its own in
`port_rename_map`.)
Where the line reads `map to 'Trk1' (also written
'trk1': one port on <platform>)`, the two were sent to names that
differ only in letter case, which on that platform is one port.

If the line is instead `... are one name on <platform>, written in
more than one letter case, and do not end together`, nothing was
merged: one port is in the config under two spellings, and they were
sent to two places.  Give both spellings the same entry.

The common case is Aruba AOS-S uplink-module ports.  `1/A1` (module
**A**, port 1) and `1/1` (access port 1) are different ports, but no
other vendor models a letter slot, so both become `ge-1/0/1` /
`Ethernet1/0/1` / `port1` depending on target.

Netcanon will not guess a target port for you — inventing an offset
would fabricate topology you never wrote.  Fix it by mapping each
colliding port explicitly in the ports pane (or `port_rename_map` on
the API), e.g. `1/A1` -> `xe-1/1/1`.  The warning clears once the
mapping is distinct.

⚠️ If you migrated from AOS-S before #482, this was **silent** —
re-run the translation and check for these warnings.

### "A same-vendor translation renamed or dropped my ports" / "My sub-interface is on its parent port"

Both were defects, up to 0.7.7, in jobs that said `completed`.

* **Same vendor on both sides.**  Every name you had not mapped was
  read by the source codec and written again by the target codec,
  and on several platforms that is not the name it had (AOS-S,
  IOS-XE, OS10, FortiOS, Junos and VyOS, on the configs we test
  with): Junos `fxp0` and
  `me0` came back `em0`, FortiOS `dmz` came back `dmz1`, IOS
  `Ethernet0/0` came back `FastEthernet0/0`, a Catalyst's `Mgmt-vrf`
  port and Dell OS10 breakout lanes (`ethernet1/1/1:1`) were dropped,
  a Junos unit (`ge-0/0/1.54`, `lo0.2`) and a VyOS `vif` were written
  onto their parent.  A name you did not map now stays as written.
* **A sub-interface onto another vendor.**  A Junos or VyOS one was
  written under its PORT's name — two stanzas of one interface, the
  802.1Q tag on the second — and an IOS-XE, EOS, NX-OS or IOS-XR one
  stayed in the output under its source name.  It now goes where its
  port goes, with its unit (`Ethernet1.54`, `unit 54` of
  `ge-0/0/1`).

Translate the config again.  To check an output you already have:
compare its interface names with the input's (same vendor), or look
for a repeated interface stanza, a missing `encapsulation dot1q` /
`vlan-id`, and an interface under the other vendor's name.  The job
said what it had done in `port_renames` and `port_drops`, and
nowhere in its status.

If a sub-interface is still not where you expect: a unit of a
loopback or of a management port is not followed across vendors, nor
is one whose port the source codec does not recognise (a channelized
Junos port), nor an interface numbered 0 (`.0`, `.00`), nor a name
that ends in more than ten digits; and a
target with no
routed sub-interface gets an interface named `<port>.<unit>` without
its tag, in a job that is `partial` where the source had a tag.
See [`CAPABILITIES.md`](CAPABILITIES.md) § F and § G.

### "... went with its port to ... with no 802.1Q tag"

A sub-interface was moved with its port, and no VLAN tag was read
for it from the source config, so the output has an interface of
that name with no `encapsulation dot1q` / `vlan-id` — or, on VyOS
and FortiOS, with the unit's NUMBER as its VLAN id.  The causes:

* the source platform's parser reads no tag for a sub-interface.
  That is every sub-interface of an AOS-CX or Dell OS10 config,
  whatever its `encapsulation dot1q` line says;
* the stanza states none.

Look the tag up in the source and set it on the target by hand.
With both devices declared the same units are listed in
`port_mapping_plan.untagged_units` ("N sub-interface name(s) moved
with their port, but no 802.1Q tag was read ...") and the job is
`partial` until `port_rename_map` has an entry for each — its own
name on the target to keep it, `null` to drop it.  A unit of a
port the target lists is not then reported as a name the device does
not list.

Between two configs of one vendor nothing is said — which is not a
promise about the tag.  A tag the source platform's parser does not
read (AOS-CX, OS10) is lost on every path, a job from that vendor to
itself included, and there no warning, no validation line and no
status reports it.  Compare the sub-interfaces of such an output with
the source by hand.

### "... moved with their port (...), but the plan does not vouch for where they went"

With both devices declared, a sub-interface went where its port went
— tag and all — and the plan still asks you to decide it.  The plan
takes a name for a unit of a port only where the name spells the port
as the config does.  Two kinds of name are outside that: a unit typed
in another letter case than its port (`interface
gigabitethernet1/0/1.54` under `interface GigabitEthernet1/0/1`, on a
platform whose names have no letter case), and a unit of a unit
(`ge-0/0/1.54.2`).  Each is listed in
`port_mapping_plan.unvouched_units` with the name it has in the
output, and its row in the rename modal says the same.  Check where
it went.  Then give `port_rename_map` an entry for it — that name to
keep it, `null` to drop it — or, in the modal, press **Accept as
shown** and Apply.

### "The Auto target says `1/1` but my switch's ports are `1`"

You picked a target model in the rename modal, its dropdown lists the
names your device really uses, and the *Auto target* column shows
something else — marked amber, "not on profile".

Both are behaving as designed, and the profile is the one to trust.
The translator derives each target name from the **shape** of the
source name (Cisco `GigabitEthernet1/0/1` becomes Aruba `1/1`); it is
not told which model you chose, so it cannot know that a standalone
2930F numbers that port `1`.  Until it is, set the names yourself:
pick each port from the row's dropdown, or pass a `port_rename_map`
to the API.  See [`CAPABILITIES.md`](CAPABILITIES.md) § F for what
the line under the fit-check banner tells you about the profile's
names.

There is now a way to tell it: choose the *Source device* as well as
the target in the modal (or declare both through the API), and the
ports are paired by position between the two.  See
[`CAPABILITIES.md`](CAPABILITIES.md) § G.

### Apply is greyed out in the rename modal

It says why, beside the button.  Two rows end on one target name: give
one of them another target, or drop it.  With no devices declared
that is either two rows the job itself wrote as one interface (they
carry the mark, and the strip above the table counts them), or two
rows you gave one name in the fields.  Two rows that merely show the
same auto name are not held where the job counts them as one
interface: a Junos `lo0.0` is the unit-0 name of `lo0`, both read
`Loopback0`, and neither needs changing.  If the two are ports the
translator itself put on one name (two Catalyst ports that both read
as `1/1` on an Aruba switch), declare the *Source device* and the
*Target device*: with both declared, Apply is available and pairs
the ports the source device has, each with a port of its own.  A
name the declared source device does not have (a Catalyst's
`AppGigabitEthernet1/0/1`) is listed as not on the source device and
waits for your decision.

### Apply said "Applied" and the port names did not change

Ports are paired by position only when **both** devices are declared.
With a target device and no source device, every port keeps its
name (same vendor) or is translated by the shape of its name (another
vendor).  The strip above the table says so -- in amber, with the
count of names the target does not have -- and the footer says
"Ports were NOT paired by position".  The source device is filled in
by itself only where the config states its hardware and a model
family describes it (an AOS-S 2930F or 2930M today); otherwise the
line under *Source device* says why not.  Choose the source device,
then Apply.

### The strip says "No port was paired by position"

Both devices are declared, and no port the config uses is a port of
the source device: the device chosen as the source is not the one
the config came from (a stack's `1/1` names against a config of `1`,
`2`, `3`; a 25G model against `GigabitEthernet` names).  Every name
was translated by its shape instead.  Choose the right source model,
mode and member numbers; *Accept as shown* records the names as they
are and pairs nothing.

### The strip above the rename table is red

The job is held.  With both devices declared, either a target port
was given more than one source port — open "What the mapping
reported" under the strip for which, and change one of the entries
that point there — or, on a RouterOS target, a port's name reads as
a VLAN, a bridge or a LAG and no line of the output finds its
hardware: give that port another name.  With no source device
declared it is headed "Port names are not settled": two source names
ended on one name of the output.  Give one of the marked rows a
target of its own, or drop it — see "My job is `partial` and the
validation report is clean" above.  (Amber under that heading is a
name waiting for your decision: one that was dropped, or one left
under its source name.)

### The line under *Source device* says the device could not be read

"Reading the source device from the config …" is the question being
put; it should be gone in a moment.  If it turns into "Could not read
the device from the config (…)", the words in brackets are why: the
server's status, a network failure, or "no answer from the server in
20 seconds".  Nothing is wrong with the config.  Choose the source
device yourself, or close the modal and open it again: the config is
asked about again every time the modal opens until it has been
answered for.

### The footer says overrides "were left out"

"Restored prior overrides (…)" means the browser had entries of yours
for this source codec, target codec and host name, and put them
back.  Two configs can share a host name.  "N kept for this host
name are for a name this config does not have, and were left out"
counts the entries that belong to the other config: a port, a VLAN
or a user this one has no row for.  They are not sent, and they
stay kept: back on the other config they are put back.  **Reset
all** forgets what this config has rows for, and leaves the
other config's entries as they are.

### A VLAN override was typed and that VLAN did not change

A number that is no VLAN id (1 to 4094) is not an entry: nothing is
sent for that VLAN while the field holds it, and an earlier entry
for it is gone too.  The field looks like any other; its title says
"Not a VLAN id (1-4094): nothing is sent for VLAN N".  Type an id in
range.

### Detection proposes a device, and says ports are missing

In the rename modal the line under *Source device* is amber and says
"N port names the config uses are not on this device", with the first
few.  On the API, `POST /api/v1/migration/detect-deployment` returned a
`deployment` with `consistent: false`.  Either way the config says it
is that device, and uses port names that device does not have
(`missing_ports`; `missing_port_count` is how many).  Possible causes:

* **A module the config does not state.**  The config uses `A1`-`A4`
  and has no `flexible-module` line, so the proposal has an empty bay.
  Set the bay's module in the *Source device* row (or add it to the
  deployment's `modules` before you send it).
* **Only part of the config was pasted**, or two were pasted together:
  a standalone banner over stacked port names (`1/24`).
* **A name that is not a hardware port.**  The check counts any name
  the config has where a port name goes, unless the config or the codec
  marks it as a LAG or a VLAN interface.
* **The model data is wrong.**  If none of the above fits, the family
  file may list the wrong ports for that part number — that is worth a
  bug report: sanitise the config first (`netcanon sanitize`; see
  [`../BUG_REPORTING.md`](../BUG_REPORTING.md)) and include its banner,
  its `module` or `stacking` lines and its VLAN port lists.

`consistent: null` is not a pass: nothing was checked, because nothing
was proposed, the text could not be parsed, or it names no port.  The
modal shows that line in amber too.

A `deployment` of `null` is not an error.  The first of `notes` says
why: the config
does not state its device (a stack's banner names no model, so a stack
config with its `stacking` or `vsf` stanza cut off states none); no
model family describes a part number in `unknown_parts`; the members
belong to different families; what the config states does not compile
(a module the bay does not take, a member number outside the mode's
range, more members than the mode allows); the lines that state the
hardware could not be read -- on AOS-S, a banner the parser cannot
tell from the configuration (a `banner motd` with no end, with text
after its closing quote, or whose text holds a quote; see [The job
says `parse failed:` for a
banner](#the-job-says-parse-failed-for-a-banner)); or the vendor has
no detector yet.  A stack that comes back short of a member, or with a
bay empty that the config provisions, has a note that counts the
member lines, member blocks or module lines that could not be read;
so has a `module 1` line that could not be read, where the banner was
used in its place.

### "Port mapping is incomplete" — the job is `partial`

You declared both devices (`source_deployment` / `target_deployment`)
and some ports the config uses could not be settled.
`port_mapping_plan.unresolved_ports` on the job lists them; the lists
below say why each is there:

* **`unplaced`** — the source has more ports of a kind than the
  target.  A 48-port config onto a 24-port switch leaves ports 25-48
  with nowhere to go; uplinks onto a switch whose module bay you
  declared empty have no uplink ports at all.  These ports were
  **dropped from the output** (they are in `port_drops`).  Decide each
  one: give it a target in `port_rename_map`, or map it to `null` to
  confirm the drop.  Either way the job stops being `partial` on that
  port's account — on `/plan` and on every per-pane endpoint.

  With a stack as the source an entry can say `reason: "no-member"`:
  the port belongs to a source member with no target member in the
  same position.  Members pair in the order the two declarations list
  them, so check how many members you declared on each side, and in
  what order.  A port is never moved to another member to find it a
  place; do that yourself in `port_rename_map` if it is what you
  want.

  A management port is treated differently.  With no management port
  in the target model it is handed to the ordinary port translation
  (the name-shape translator) rather than dropped.  Where the target
  has a form for out-of-band management it is kept — on AOS-S it
  becomes the `oobm` block — and the entry shows `dropped: false`
  and where it `landed`; where the target has no such form the
  translator drops it and the entry shows `dropped: true`.  Either
  way the port is in `unresolved_ports`: netcanon does not know
  whether the target device has a management interface.  Name the
  port in `port_rename_map` — the same target to confirm it, or
  `null` to drop it.
* **`off_inventory`** — the config names ports the source device you
  declared does not have.  Those names were handed to the name-shape
  translator, the old way — which may rename one, or drop it when
  the target has no name for it (check `port_drops`).  Almost always
  the declaration is wrong: the wrong model (a 24-port model for a
  48-port
  config), the wrong mode (bare `24` against a stacked declaration
  whose ports are `1/24`), a module you did not declare (`A1` with
  an empty bay), or — for a stack — a member you did not declare, or
  one whose number is not the config's (`3/1` against members
  numbered 1 and 2: a member with no `id` is numbered from 1).
  `POST /api/v1/migration/inventory` with
  `{"codec": "<source codec>", "deployment": {...}}` shows the names
  your declaration produces — compare them with the config.  A few
  causes leave the declaration right: the config
  spells a port another way than the device prints it
  (`gigabitethernet1/0/1`, `Gi1/0/1`); it has an `interface Null0`
  stanza; or it is a Catalyst or a FortiGate, whose configs list
  interfaces their profile does not.  Map or drop such a name by
  hand in `port_rename_map`.

  On RouterOS the key of an entry is the name the CONFIG uses for a
  port.  A port you named `core-a` is `core-a` in the plan and in
  your map (`labelled_ports` says which port of the model it is).
  With both devices declared an entry keyed by its factory name is
  taken for that port; without, it matches nothing and is ignored
  with a warning.
* **`displaced`** — a name nobody decided that the name-shape
  translator would have put on a name another interface ends on, or
  on a port of the target: a name from either list above, or a
  logical interface such as a firewall's aggregate.  Two interfaces
  on one name is one's config merged into the other's, so the name
  was **dropped** instead.  Give it a target of its own in
  `port_rename_map`, or map it to `null`.
* **`landed_off_target`** — a logical name nobody decided (a VLAN
  interface or an aggregate, on a FortiGate usually) that the
  name-shape translator gave a port-shaped name the target device
  does not have.  Nothing shares that name, so it was **kept** — with
  its config on a port that does not exist.  Give it a target in
  `port_rename_map`, or map it to `null`.

The message can also say **"N static route(s) still name, as next
hop, an interface that has another name in the output, or is not in
it"**.
`port_mapping_plan.stale_next_hops` lists their destinations.  A next
hop that is exactly an interface's name follows the interface; a
RouterOS list of gateways (`gateway=ether1,ether2`), a routing-table
suffix (`ether3@main`) and, across vendors, a Junos unit
(`next-hop et-0/0/24.0`) are left as written.  The job is `partial`
while a route names an interface that has another name in the output.
No entry rewrites the route: correct it in the output, or keep the
names it uses — on a RouterOS target an entry that gives each such
port its old name (`{"ether3": "ether3"}`) leaves the route right,
since a name does not decide a port's hardware there.

The message can also say **"N port(s) are not looked up by their
hardware in the output"** — on a RouterOS target only.
`port_mapping_plan.unbound_ports` lists them, each with the factory
name it should be looked up by.  RouterOS finds a port by its factory
name, and there are three ways to end without a line that does:

* The port's name reads as a VLAN, a bridge, a LAG or a loopback
  (`bond1`, `bridge-uplink`, `vlan-trunk`, `uplink.10`, `lo0`).  The
  output has no Ethernet line for such a name, so the address and
  every other reference are on a name nothing defines — or, for a
  name like `vlan10`, on a VLAN interface the renderer creates on
  another port.  Give the port another name in `port_rename_map`, or
  a port of the target.
* The config has no interface for the port — it names it only as a
  LAG member or in a route — and an entry gave it a name.  No line
  can carry its factory name, so the name is written where the port
  is referenced (`slaves=`, `gateway=`) and defined nowhere.  Use a
  port of the target as the entry's target, or remove the entry: the
  name the mapping gives the port needs no line.
* Two ports of another vendor were given one name.  The output finds
  the first by it, and the second is listed.  Give each a name of its
  own.

If the job also says **"the output could not be read back with the
target codec"**, no port could be checked at all: every port that
could have been checked is listed for that reason, whatever its name,
and the three causes above do not apply.  That is a fault in netcanon
— report it with the config.

If the plan lists `emptied_lags`, `shrunk_lags`, `lost_routes`,
`lost_dhcp_pools`, `lost_tracking` or `lost_vtep_sources`, a dropped
port took something with it: a LAG loses a dropped member (and may be
left with none), a static route or a DHCP pool that names a dropped
port is removed whole, an interface that stays loses the VRRP track
entry that named it, and a VTEP loses the source interface it was
bound to.

If the plan lists `off_target`, one of your targets is not a name the
target model lists.  That is allowed — but check it is not another
spelling of a port that is already taken.  Only letter case and
surrounding space are understood; `Gi1/0/1` is not recognised as
`GigabitEthernet1/0/1`, and the device would put both source ports on
that one interface.  On a RouterOS target a target that is not a port
of the declared device is a NAME for the port, not a place: the
port's hardware stays where the mapping put it
(`port_mapping_plan.target_hardware`), the name is not listed here,
and a line of the plan says the entry was taken as a name.  If
nobody placed the port, the name is listed here — unless the target
happens to have a port with the factory name the port had, in which
case `target_hardware` shows it on that port, which the mapping did
not choose for it.  Between two RouterOS configs `source_hardware`
then names a factory name the target lacks; from another vendor the
output finds the port by the name you typed, which no port has, or
only refers to it, and a line of the plan says so.  Where the name
reads as another kind of interface (`bridge-x`, `bond7`) no Ethernet
line is written at all: between two RouterOS configs the port is then
in `unbound_ports` and the name is not listed here; from another
vendor the name is listed here and the address is on a name nothing
defines.

The message can also say **"N target port(s) received more than one
source port"**.  `port_mapping_plan.fused` names them.  Only your own
`port_rename_map` can cause this — two entries pointing at one name,
or an entry pointing at a name the pairing already used (on a
same-vendor pair, keeping an unplaced port under its old name can do
exactly that).  A target is read as the target device spells it, so
on a platform without case `1/a1` is the port `1/A1` — and on Junos
or OPNsense, which name every interface themselves in lower
case, `GE-0/0/2` is the port `ge-0/0/2`.  On RouterOS two ports can
also be fused without sharing a name: a port that keeps a name of its
own is on the hardware it was paired with, and another port sent to
that hardware is on it too.  Naming the ports again does not clear
it; give each a target of its own.

**"Port mapping was not made"** means no pairing was possible at all —
one side is a profile that lists no ports, or lists a port name
twice; or a RouterOS config gives a port the name another port of the
source device still has, or looks two interfaces up by one factory
name (a renamed port beside a line that still uses its old name), so
its ports cannot be told apart.  Every port name was then translated
by name shape.

A job that is `partial` for another reason as well (the usual state
of a cross-vendor run) carries both messages in `error`.

A Catalyst source is a special case: IOS-XE prints the interfaces of
every network module the chassis could take, so the modules you did
not declare show up as off-inventory even when the declaration is
right.  A sub-interface (`GigabitEthernet1/0/1.100`) follows its
parent port, between two configs of the same codec and across
vendors: it is listed in `sub_interfaces` with the name it was
given, and is not off-inventory.  One that followed and took no
802.1Q tag with it is the exception: it is listed in
`untagged_units`, stays off-inventory and asks for a decision (see
"... with no 802.1Q tag" above).  So is one the plan does not vouch
for — typed in another letter case than its port, or a unit of a
unit: it is listed in `unvouched_units` (see "... but the plan does
not vouch for where they went" above).

### "A stack member's config came out on another member"

Two stacks are paired member by member in the ORDER the two
declarations list them — the first member of `source_deployment` with
the first of `target_deployment` — and not by member number.  A
fabric numbered 1 and 3 onto a stack numbered 1 and 2 puts `3/5` on
`2/5`; list the source as 3 then 1 and member 3 lands on member 1.
The job says so in a line (`stack members pair in the order they are
declared, not by member number: source member 3 with target member
2`), and `port_mapping_plan.source.members` / `.target.members` give
each member's place (`rank`) and number.  To pair them another way,
change the order of one list.

Where a member is put beside a member of its own number instead of
on it — for instance the same members listed 2, 1 on one side and
1, 2 on the other — the line is another one: `N stack member(s) are
paired with a member of ANOTHER number while one of the two numbers
is declared on both sides`.  That is a **crossing**: every port of
those members is on another switch.  The job is still `completed`,
since the order of a list is yours to choose; if you did not mean it,
give the members of one number the same place in both lists.

A member states its number with `id` in the request
(`{"model": "JL260A", "id": 3}`); one that leaves it out is numbered
from the lowest number no other member states.  See
[`CAPABILITIES.md`](CAPABILITIES.md) § G.

### "On RouterOS my port was renamed, not moved"

An entry of `port_rename_map` such as `{"ether1": "ether5"}` came out
as `set [ find default-name=ether1 ] name=ether5`: the port is still
`ether1`, now CALLED `ether5`.  That is what an entry means on
RouterOS when no devices are declared — it names a port, and nothing
in a name says whether hardware was meant (`sfp1` is a port of one
model and a short name for a port of another).  To move a port's
config onto other hardware, declare both device models (API:
`source_profile` / `target_profile`); an entry whose target is a port
of the declared target then moves the port there.  See
[`CAPABILITIES.md`](CAPABILITIES.md) § G.

### The job says `parse failed:` for an IOS XR config

Two sentences say that the text is not in the form `show
running-config` prints, and nothing of it was read.  Both name a line
number and quote nothing of the text.

- **`cisco_iosxr: this text has no indentation. ...`** -- no line of
  the text but a comment is indented, and the line it names opens a
  stanza with the line after it at the left margin.  IOS XR places
  each line of a configuration by its indentation when it loads a file
  (what that rests on is on the vendor page), so neither the router
  loading it nor Netcanon can tell where such a stanza ends, and
  loaded onto the router the text would put its lines in the wrong
  submode too.  The indentation was lost on the way: a paste through
  a tool that trims lines, a file joined from its lines, a config
  embedded in another document.  Indentation is a space or a tab: a
  text copied out of a web page can be indented with no-break spaces,
  which are none -- replace them with spaces.  Paste the output of
  `show running-config` as the router prints it.  A whole config is still detected as IOS XR, so the
  migrate page offers no other vendor for it; a short text with no
  interface of an IOS XR name (a user and a VRF, say) is detected as
  IOS-XE CLI, printed or not, and the page offers IOS-XE beside the
  sentence -- keep IOS XR as the source and paste the text with its
  indentation.
- **`cisco_iosxr: line <n> states an interface's setting ...`** --
  the line is `interface <name> <setting> ...` in column 0, the form
  `show running-config formal` prints, or a one-line command typed
  into a printed config.  Paste
  `show running-config` without `formal`; if the line was typed in,
  write the setting on a line of its own, indented under its
  `interface` line.

See [`vendors/cisco_iosxr.md`](vendors/cisco_iosxr.md) § "Common
gotchas".

### The job says `parse failed:` for an EOS config

Two sentences say that the text is not in the form `show
running-config` prints, and nothing of it was read.  Both name a line
number and quote nothing of the text.

- **`arista_eos: this text has no indentation. ...`** -- no line of
  the text but a comment is indented, and the line it names opens a
  stanza with the line after it at the left margin.  The parser tells
  which lines belong to a stanza by their indentation, and without it
  cannot tell where a stanza ends.  (What the switch makes of such a
  text Arista does not say; the vendor page says what it is inferred
  to do.)  The indentation was lost on the way: a paste through a
  tool that trims lines, a file joined from its lines, a config
  embedded in another document or a forum post.  Indentation is a
  space or a tab: a text copied out of a web page can be indented
  with no-break spaces, which are none -- replace them with spaces.
  Paste the output of `show running-config` as the switch prints it.
  A whole config is still detected as EOS, so the migrate page offers
  no other vendor for it; a short text may be detected as no codec --
  keep EOS as the source.
- **`arista_eos: line <n> opens a block of text ...`** -- the line
  opens a banner (`banner login`, `banner motd`), a `comment`, RCF
  `code unit`, a multi-line `action bash` or `protocol https
  certificate` (which opens two, a certificate and then its key, each
  ended by its own `EOF`): bodies that Arista's tools end at a line
  that is `EOF` -- for a banner, `EOF` in column 0 -- and the last one
  opened has none.  The text was cut short, or its `EOF` line was
  lost: paste the whole of `show running-config`.

See [`vendors/arista_eos.md`](vendors/arista_eos.md) § "Common
gotchas".

### The job says `parse failed:` for an AOS-CX, IOS-XE CLI, NX-OS or OS10 config

- **`<codec>: this text has no indentation. ...`** (`aruba_aoscx`,
  `cisco_iosxe_cli`, `cisco_nxos`, `dell_os10`) -- no line of the text
  but a comment begins with white space, and the line it names opens a
  stanza with a line after it at the left margin.  The parser tells
  which lines belong to a stanza by their indentation, and without it
  cannot tell where a stanza ends: an `ip route` after an empty NX-OS
  `vrf context` may be the VRF's.  (What the device itself makes of
  such a text is not established here.)  The indentation was lost on
  the way: a paste through a tool that trims lines, a file joined from
  its lines, a config embedded in another document -- a lab topology
  file is one.  Any white space in front of a line is indentation, a
  no-break space included, so a text copied out of a web page is read.
  Paste the output of `show running-config` (OS10: `show
  running-configuration`) as the device prints it.  A whole config is
  still detected as its own vendor's, so the migrate page offers no
  other vendor for it.  Release 0.7.7 and earlier read such a text as
  stanzas with almost nothing in them -- no interface address, no
  VLAN membership -- in a job that did not say so: translate it again.

See the vendor pages ([AOS-CX](vendors/aruba_aoscx.md),
[IOS-XE](vendors/cisco_iosxe.md), [NX-OS](vendors/cisco_nxos.md),
[OS10](vendors/dell_os10.md)) § "A config without its indentation".

### The job says `parse failed:` for a banner

The IOS-XE CLI, NX-OS, AOS-CX, OS10, AOS-S and IOS XR parsers read a
banner as text, ended where the vendor ends it, and refuse a text in
which the banner cannot be told from the configuration: read as it stands,
the lines after it would be the banner's text, or where it ends is
not in the text.  Each sentence names a line and quotes nothing of
the text, nor the delimiter (which is yours).

- **`<codec>: line <n> opens a banner ...` / `opens a block of text
  ...`, "that runs to the end of this text"** -- the banner (or, on
  IOS-XE, a `menu` title or prompt, a `busy-message`, a line's
  `vacant-message` or `refuse-message`, a web authentication banner or
  a `macro name`; on NX-OS, a `scheduler job name`) never ends.
  IOS-XE and NX-OS end a banner at the next occurrence of the
  delimiter after its keyword, anywhere (IOS prints it as `^C`); a
  macro ends at a line that is `@`, a scheduler job at a line that is
  `end-job`.  AOS-CX ends it at the next line that ENDS with the one
  character after `banner motd` / `banner exec` (the character with
  text after it is the banner's text).  OS10 ends it at a line that
  holds the delimiter and nothing else, in column 0 -- the delimiter
  inside a line, or after a space, does not end it.  AOS-S ends a
  printed banner at the next double quote that no backslash escapes.
  IOS XR ends it at the next occurrence of the one character after
  its type, anywhere; a banner set through NETCONF can be printed with
  none (see the IOS XR vendor page).  The text was cut short, or the
  line that ends the banner was lost: paste the whole of `show
  running-config` (on OS10, `show running-configuration`).
- **`aruba_aoscx: line <n> opens a banner with more than one
  character ...`** and **`dell_os10: line <n> opens a banner with more
  than its delimiter ...`** -- the banner's line has text after its
  delimiter, which no printout of `show running-config` (on OS10,
  `show running-configuration`) has there, so where the banner's text
  ends cannot be told.  The text was typed or edited by hand: paste
  the device's own printout.
- **`aruba_aoss: line <n> ends a banner, and has text after the
  double quote that ends it`** -- a double quote inside the banner's
  text ended it early, or the listing lost a line and the next quote is
  another command's.  Check the banner's lines in the paste; remove
  them if the device's printout cannot be had.  `detect-deployment`
  then answers "The lines that state the hardware could not be read;
  declare the device yourself."
- **`<codec>: line <n> is outside every banner, and holds ...`**
  (IOS-XE, AOS-S, OS10) -- the line holds what the device prints to
  end a banner: on IOS-XE `^C` (or the byte 0x03), on AOS-S an odd
  number of double quotes, on OS10 the delimiter alone.  The banner
  the sentence names held the same in its own text, and so ended
  early: the device printed its real end later, on this line, and the
  lines between, read as they stand, would be configuration.  A
  device's printout cannot say where such a banner ends.  Change the
  banner on the device so that its text does not hold its end, or
  remove the banner's lines from the text you paste.
- **`cisco_iosxr: line <n> names a banner that IOS XR does not
  print`** -- a line in column 0 begins `banner` (or `aaa banner`) and
  is not `banner` with one of its six types and a delimiter, or `aaa
  banner login` and a delimiter: `banner` and a delimiter with no type
  and `banner config-save` are IOS's, and a type with nothing after it
  has no text.  Where its text would end cannot be told.  The line came
  from another platform's config or was typed by hand: paste the
  router's own printout, or remove the line.
- **`cisco_iosxr: line <n> is a line of a banner whose delimiter is
  printed as a caret and a letter C, and holds a caret with no C after
  it`** -- the banner was opened with `^C`.  IOS XR takes a delimiter
  to be one character, which would end the banner at that caret, and
  whether it takes `^C` for one is not established, which would not:
  the lines after it would be configuration under one reading and
  banner under the other.  Change the banner on the router so that its
  text holds no caret, or remove the banner's lines from the paste.
- **`<codec>: line <n> is a line of a banner, or of another block of
  text, and ends in a character ...`** (the six above, and
  `arista_eos`) -- a line of the banner ends in a form feed, a
  vertical tab, a carriage return on its own, or another character
  that ends a line for the parser and not for the device, which ends
  a line at a line feed: where the device ends the banner, and so
  where the configuration goes on, is not where those lines say.  The
  character came with the banner's text (a banner set through an API
  or a file can hold one), or the text was changed on the way.  Paste
  the device's own printout; if it holds the character, change the
  banner on the device, or remove its lines from the paste.

See the vendor pages, § "A banner is text":
[`cisco_iosxe.md`](vendors/cisco_iosxe.md#a-banner-is-text),
[`cisco_nxos.md`](vendors/cisco_nxos.md#a-banner-is-text),
[`aruba_aoscx.md`](vendors/aruba_aoscx.md#a-banner-is-text),
[`dell_os10.md`](vendors/dell_os10.md#a-banner-is-text),
[`aruba_aoss.md`](vendors/aruba_aoss.md#a-banner-is-text),
[`cisco_iosxr.md`](vendors/cisco_iosxr.md#a-banner-is-text).  On AOS-S,
a banner the parser refuses is not read by `detect-deployment` either
(see [Detection proposes a device, and says ports are
missing](#detection-proposes-a-device-and-says-ports-are-missing)).

### The job says `refused:` — "my config was refused"

Not a parse failure and not a bug: the config was read, and it asks
for more than this server is set to take, or the request ran out of
time.  The sentence says which limit, how many were asked for ("or
more" means the count stopped there) and the limit.  What each one
means, and what to do:

| The sentence names | What it is | What to do |
|---|---|---|
| VLAN ids that the config's lists and ranges name / VLAN ids in the allowed lists of ports | The ids on ports: every `switchport trunk allowed vlan 2-4000`, every `all`, every `vlan members` range, added up — and, on IOS-XE, NX-OS, EOS and AOS-CX, every trunk with NO allowed line, which carries every VLAN there and counts as `all` does ("the last one read: a trunk with no allowed list, which is every VLAN: ...") | A real chassis written `all` on thousands of ports, or with thousands of trunks that state no list: allow more (below).  Otherwise look at the list the sentence quotes |
| port memberships | (port, VLAN) pairs: each trunk that allows every VLAN is on every VLAN the config declares, so two ordinary counts multiply — the sentence gives both | Allow more, or translate the trunks and the VLANs you need |
| different ports named by port ranges / ports that a VLAN's or a LAG's port list names and no interface stanza declares | Ports that exist only as names in a list (AOS-S `tagged 1-1001,...`) | Almost always a range that names ports the device does not have: check the range the sentence quotes |
| interfaces | Interface records | A router with that many sub-interfaces is real: allow more |
| entries copied from an interface-range onto its members | A Junos `interface-range` with addresses on it: every address goes onto every member | Rarely meant; check the range the sentence names |
| words of set commands written out from block-form text | Block-form Junos is converted to set commands, and the whole path is written again for each statement | Paste `show configuration \| display set` instead: it is not converted, and not counted in words |
| characters of rendered config / characters of nested blocks written out from set lines | The output would be longer than the limit; or VyOS set lines, each written out as nested blocks | A wide VLAN list written to IOS-XE or EOS is a line of every id: allow more, or translate to a target that writes ranges |
| the request passed the N seconds it may take | The time limit | Allow more.  If the config is small, that is a slow path: please [report it](../BUG_REPORTING.md).  When the sentence goes on "while its body was still arriving" (HTTP 408) it was the REQUEST that was slow to arrive, which only a server set to `small` times: send it again |
| the server works on one config at a time, and was busy with another ... / ... more were already waiting their turn / ... this request waited N seconds for its turn | **Busy, not too large.**  A server set to `small` (the public demo) works on one request that reads config text at a time.  This one waited its whole time behind another; or arrived when as many were in flight as may work and wait, and its body was not read; or got its turn after a wait, too late to finish.  Nothing is wrong with the config | Send it again.  The sanitiser and `detect` answer this as HTTP 503 with `Retry-After`, where a config that is too large is 413; a request that arrives with every place taken is answered 503 by every endpoint that reads config text, the ones that return a job too.  If it happens with nothing else running, something is holding the server: on the demo, start a new session |

**To allow more**, where the server is yours: set
`NETCANON_CONFIG_LIMITS=large` (or `unlimited`) in its environment and
restart it; in the desktop application, **Preferences... -> Config
size limit**; on the command line, `--limits large`.  The numbers are
in [`CAPABILITIES.md`](CAPABILITIES.md#h-config-size-limits-a-job-that-says-refused)
§ H.  On the public demo the limit is not yours to change, and the
sentence says what a Netcanon you run yourself allows by default.
Only `small` makes requests take turns: a server of your own that
answers "busy" was set to it.

**An answer that stopped part-way** -- the connection closed before the
length the answer declared -- on a server set to `small`: an answer
has the request's 20 seconds to be read in, counted from when the
request arrived, and one that has not gone out by then is abandoned.
That is for a client that does not read; a slow line and the largest
answer `small` admits can meet it too.  The server's log has a line
for each ("an answer from ... was abandoned").  Send the request
again, or run a Netcanon of your own, which sets no such time.

If you believe a limit refused a config of a real device that it
should admit, that is worth a [bug report](../BUG_REPORTING.md): say
which limit and what the device is.  (The sanitiser is under the same
limits, so say what it answered if it refused the config too.)

### "The migrate page reports 'paramiko-shell capture artifact'"

Specific to OPNsense backups via SSH + `cat /conf/config.xml`.
The `_trim_xml_prologue` codec helper rescues legacy backups that
have a stray `cat /conf/config.xml\r\r\n` prefix before the
`<?xml` prolog.  Fixed in the collector for new backups; legacy
ones rescue automatically.

### "My Tier-3 surface didn't translate"

Expected.  The Tier-3 banner is the right place to read what was
detected-but-deliberately-not-translated.  See
[`CAPABILITIES.md`](CAPABILITIES.md#tier-3--opaque-carry--not-auto-rendered)
for the full list.

---

## Where to look for help, in order

1. **The migrate page banners** — Step 1 above.  Reading the
   banners answers most "why didn't X translate" questions.
2. **`docs/CAPABILITIES.md`** — the per-codec capability matrix.
3. **Per-vendor pages**
   ([`docs/vendors/`](vendors/)) — operator-facing summary of
   what your vendor's codec does.
4. **`tests/fixtures/real/RESULTS.md`** — live certification
   state per codec.  Codecs ship as `certified` (full bidirectional
   parity verified against real captures) or `best_effort` (under
   active development, gaps expected — currently the NETCONF stub
   only).
5. **`tests/fixtures/real/PHASE4_RECONCILIATION.md`** — the live
   cross-mesh audit if you want to see exactly which cells pass.
6. **`BUG_REPORTING.md`** — when nothing else helps.

---

## See also

- [`CAPABILITIES.md`](CAPABILITIES.md) — the capability matrix
- [`HOW_WE_TEST.md`](HOW_WE_TEST.md) — the discipline behind the
  capability declarations
- [`vendors/README.md`](vendors/README.md) — per-vendor pages
- [`COMPARISON.md`](COMPARISON.md) — when an adjacent tool is the
  right answer
- [`../BUG_REPORTING.md`](../BUG_REPORTING.md) — submitting a bug
  / fixture
