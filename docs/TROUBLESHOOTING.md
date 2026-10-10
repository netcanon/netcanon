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

### "My hashed password came out as a review comment"

By design.  Netcanon's hash-portability policy (see
[`CAPABILITIES.md`](CAPABILITIES.md))
**never** falls back to plaintext.  If the source vendor's hash
form (e.g. Cisco type-7) doesn't have a target equivalent, the
rendered output gets a `# REVIEW: <hash> from <source vendor>`
comment instead of a plaintext password.

**Action:** re-issue the hash on the target device using the
target's native CLI (`enable secret`, `set system root-authentication
plain-text-password`, etc.).

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

### "Two of my ports became one port"

Check the job warnings for `port_rename: multiple source ports map
to ...; these are distinct ports on the source device`.  Where the
sources are two ports this is a **real loss**, not cosmetic: two
physically distinct source ports resolved to a single name on the
target, and their VLAN memberships merged.  (One exception: a Junos
interface named with and without its unit, `sources: lo0, lo0.0`, is
one interface.)

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

Through the API there is now a way to tell it: declare the source
device as well as the target, and the ports are paired by position
between the two.  See [`CAPABILITIES.md`](CAPABILITIES.md) § G.

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
parent port only between two configs of the same codec; across
vendors it is reported separately and does not move with its port.

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
