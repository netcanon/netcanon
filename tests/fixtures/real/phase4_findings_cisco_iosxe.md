# Phase 4b findings — source vendor: cisco_iosxe (NETCONF)

Generated against `_phase4_runs/latest.json`.  7 CODEC_BUG
entries across 6 target codecs.  Distribution: aruba_aoss (1),
cisco_iosxe_cli (2), fortigate_cli (1), juniper_junos (1),
mikrotik_routeros (1), opnsense (1).

Source codec: `cisco_iosxe` (Phase-0.5 NETCONF / OpenConfig stub —
`netcanon/migration/codecs/cisco_iosxe/codec.py`).  Its `parse()` walks
the `<interfaces>` subtree only; every other declared-`supported`
matrix path (system, vlans, network-instances, snmp, routing) is
aspirational wire-up that hasn't landed.  All seven CODEC_BUGs surface
on the interface subtree (the only subtree this source codec
populates), and all seven point at target-codec or expectation-YAML
defects rather than at the cisco_iosxe NETCONF parser itself.

Sole fixture exercising this source codec: a synthetic 10-interface
kitchen-sink (`tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml`)
covering ethernet, loopback, tunnel, l2vlan / SVI, ieee8023adLag,
multi-IPv4, dual-stack, and enabled-false.  No real captures yet
(Phase-0.5 status; no published OpenConfig `<get-config>` dump in the
corpus).  Narrow-fixture caveat: the seven CODEC_BUGs may be a
floor, not a ceiling, on what real captures would surface.

## Triage classification (3 buckets: A real-bug / B stale-YAML / C acceptable-lossy)

* **Bucket A — real codec bug:** the target codec drops or mangles
  data the canonical model carries; expectation YAML is honestly
  optimistic; fix is a code change in the target codec.
* **Bucket B — stale / wrong YAML expectation:** the codec already
  declares a `LossyPath` or has documented modelling limits that the
  pair YAML's `disposition: good` contradicts; the YAML's own `note`
  often spells out the loss.  Fix is a YAML correction (`good` →
  `lossy`).
* **Bucket C — acceptable lossy / not a bug:** behaviour is
  documented, expected, and the YAML correctly anticipates it; the
  reconciliation flag is a comparator artefact (typically a count-
  drift cascade where structural collapse is doing its job but a
  per-field diff still surfaces).  No fix needed; resolved by
  upstream comparator hygiene or by a sibling fix in another bucket.

## Bucket totals

| Bucket | Count | Action |
|---|---:|---|
| A | 4 | Code fix in target codec (aoss parse regex, mikrotik render branch, cisco_iosxe_cli ipv4 secondary, opnsense secondary IP modelling) |
| B | 3 | Flip pair-YAML disposition `good` → `lossy` (cisco_iosxe_cli ipv4 + interface_type; opnsense ipv4) |
| C | 0 | none — every flagged cell here is a real defect or stale doc |
| **Σ** | **7** | |

The seven findings reduce to **four distinct codec defects** and
**three YAML hygiene corrections**.  Some defects manifest in more
than one cell (the count-drift cascades especially); the bucket totals
above count cells, not root causes.

## Per-cell findings

### Target: aruba_aoss

**1 entry.  Bucket A.**

* **Field:** `interfaces[].name`
* **Drift detail:** count drift `10 → 8 (interfaces)`.  Source emits
  10 interfaces; target re-parse produces 8.  Reconciler reports the
  cascade on `name` because `interfaces` itself is `lossy` in the
  pair YAML, so `interfaces[].name` is the highest-severity child
  field that flips to `CODEC_BUG` (pair YAML labels it `good`).
* **Likely missing records:** seven of the ten source interfaces are
  Cisco-shaped multi-slash names (`GigabitEthernet0/0/0` …
  `0/0/4`, `Port-channel1`, `Vlan10`).  AOS-S parser regex
  `_IFACE_HEADER_RE` (`netcanon/migration/codecs/aruba_aoss/parse.py:207`)
  accepts at most one `/` segment.  When the AOS-S render emits
  `interface GigabitEthernet0/0/0` (no port-rename mesh applied), the
  re-parse drops every multi-slash name.  Loopback / Tunnel / Vlan
  names also miss the regex.
* **Codec locus:** `aruba_aoss/parse.py:_IFACE_HEADER_RE`
  (regex too narrow) **and/or** `aruba_aoss/render.py` (render path
  fails to apply the port-rename mesh that the YAML's note explicitly
  promises is in place — "AOS-S target render emits via the
  port-rename mesh").  The render-says-A / parse-rejects-A asymmetry
  is the canonical "render-emits-but-parse-rejects" mismatch.
* **Fix options:**
  1. Widen the AOS-S parse regex to accept multi-slash port names
     (cheap; defers the asymmetric-rename tech debt).
  2. Apply the port-rename mesh on the AOS-S render side so emitted
     bytes use AOS-S-shape names that the parser does match.  This
     matches what the pair YAML claims is happening today.

### Target: cisco_iosxe_cli

**2 entries.  Bucket A (1) + Bucket B (1, but with a coordinated A
half).**

#### Cell 2a — `interfaces[].ipv4_addresses` — Bucket A (code) + B (YAML)

* **Drift detail:** `GigabitEthernet0/0/1` source carries three IPv4
  addresses (10.0.10.1/24, 10.0.11.1/24, 10.0.12.1/24); target after
  CLI render + re-parse carries only the first.
  `GigabitEthernet0/0/3` source carries two (172.16.0.1/30,
  172.16.100.1/24 — the latter from a dot1q sub-interface absorbed
  onto the parent); target carries only the first.
* **Codec locus — render side:**
  `netcanon/migration/codecs/cisco_iosxe_cli/render.py:253-255`
  emits every address as a bare `ip address X.X.X.X MASK` — Cisco
  IOS-XE rejects this on a real device (only the first is primary;
  the rest must be `ip address X.X.X.X MASK secondary`).
* **Codec locus — parse side:**
  `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:560-561`
  has the inverse defect: an explicit `if not current["ipv4"]:
  # primary only` guard discards every line beyond the first.  Even
  if the renderer emitted the `secondary` keyword the parser would
  drop them today.  Both halves must change for multi-IPv4 to
  round-trip.
* **YAML status:**
  `cross_vendor_expectations/cisco_iosxe__cisco_iosxe_cli.yaml:263`
  labels `interfaces[].ipv4_addresses` as `good`.  Even after the
  code fix above, the pair YAML's `note` still applies — but the
  current state is that this is a real codec defect AND the YAML is
  optimistic.  Bucket A primary; Bucket B until the fix lands (then
  Bucket A clears the defect and the YAML stays correct as-is).
* **Recommended action:** coordinated render + parse change to emit
  / accept `secondary` for index>=1.  Don't flip the YAML — fix the
  code instead, since this is the same-vendor cross-format pair
  where `good` is genuinely the right disposition once `secondary`
  round-trips.

#### Cell 2b — `interfaces[].interface_type` — Bucket B

* **Drift detail:** source `Vlan10` carries
  `interface_type="ianaift:l2vlan"` (from the OpenConfig
  `<type>ianaift:l2vlan</type>`); target after CLI re-parse carries
  `ianaift:l3ipvlan`.
* **Codec locus:**
  `netcanon/migration/codecs/cisco_iosxe_cli/parse.py:91` hard-codes
  `"vlan": "ianaift:l3ipvlan"` in the name-prefix → IANA-ifType
  lookup.  IANA distinguishes `l2vlan` (135 — bridge / 802.1Q
  sub-interface) from `l3ipvlan` (136 — routed VLAN / SVI carrying
  L3).  OpenConfig models a Catalyst SVI as `l2vlan` (the underlying
  hardware port is L2-VLAN-tagged); IOS-XE's CLI behaviour
  (`interface Vlan10` always implies a routed SVI) fits `l3ipvlan`.
  Both choices are defensible; neither codec is "wrong".
* **YAML status:**
  `cross_vendor_expectations/cisco_iosxe__cisco_iosxe_cli.yaml:242-249`
  labels `interfaces[].interface_type` as `good` with a note
  claiming "byte-perfect" round-trip.  The same-vendor cross-format
  round-trip is **not** byte-perfect for SVIs — the IANA ident flips.
  The YAML is wrong.  Pure Bucket B.
* **Recommended action:** flip the pair YAML disposition to `lossy`
  with a reason citing the inferred-type asymmetry.  No code change
  needed unless the team wants to enforce one canonical choice
  across the codebase (currently not justified for one fixture
  cell).

### Target: fortigate_cli

**1 entry.  Bucket B.**

* **Field:** `interfaces[].description`
* **Drift detail:** five interface descriptions exceed 25 characters
  (`WAN uplink to upstream carrier` 30, `LAN downlink (campus
  distribution)` 34, `Reserved for future expansion (shutdown)` 40,
  `L3 routed port with dot1q subinterface trunk` 44, `Router ID /
  iBGP peering loopback` 33).  All five truncated at byte 25 by the
  FortiGate render.
* **Codec locus:**
  `netcanon/migration/codecs/fortigate_cli/render.py:545-548` emits
  `iface.description[:25]` with the comment "FortiOS alias caps at
  25 chars per spec".  This is documented, not a bug.
  `fortigate_cli/codec.py` declares
  `LossyPath(path="/interfaces/interface/config/description",
  reason="FortiOS limits alias to 25 characters; longer
  descriptions from other vendors will be truncated.")`.
* **YAML status:**
  `cross_vendor_expectations/cisco_iosxe__fortigate_cli.yaml:212-221`
  labels the field `good` but its own `note` says "FortiOS caps
  alias at 25 characters — longer Cisco descriptions truncate on
  FortiGate render".  The note contradicts the disposition.  Pure
  Bucket B.
* **Recommended action:** flip the pair YAML disposition `good` →
  `lossy` and use the existing `note` text verbatim as the `reason`.
  No code change — the codec already declares the loss correctly via
  `LossyPath`.

### Target: juniper_junos

**1 entry.  Bucket A.**

* **Field:** `interfaces[].name`
* **Drift detail:** count drift `10 → 9 (interfaces)`.  One interface
  drops on the round-trip into Junos.
* **YAML status:**
  `cross_vendor_expectations/cisco_iosxe__juniper_junos.yaml:241-253`
  labels `interfaces[].name` as `good`, claiming "Loopback / SVI /
  Port-channel sources route through the rename mesh too" (Cisco
  `Vlan100` → Junos `irb.100`; `Port-channel1` → `ae1`; `Loopback0`
  → `lo0`).  If the rename mesh handles all 10 source names the
  count should be preserved; that one interface is dropping
  indicates a name the mesh fails to translate or a Junos render
  branch missing for one canonical interface_type.
* **Codec locus:** Junos render path; specifically a missing emission
  branch for one of {Tunnel100 (`ianaift:tunnel`), Loopback1 (v6-
  only software loopback), or one of the multi-IP ethernets where
  the v4 list-len breaks Junos's per-unit address modelling}.  Not
  fully diagnosable from the comparator dump alone (truncated source
  list — see narrow-fixture caveat).
* **Recommended action:** drill into the Junos render with the
  kitchen_sink fixture in a unit test asserting `len(parse(render
  (intent)).interfaces) == 10`.  The diff will name the dropped
  interface and point at the missing branch.  Likely candidates,
  ranked by prior art across vendors:
  1. `Tunnel100` (GRE) — Junos uses `gr-0/0/0.<unit>`; if the
     port-rename mesh has no entry for ianaift:tunnel sources the
     interface won't reach the renderer.
  2. `Loopback1` (IPv6-only) — Junos `lo0` typically allows
     multiple units; if the renderer keys off `iface.ipv4_addresses`
     to decide whether to emit, an IPv6-only loopback drops.

### Target: mikrotik_routeros

**1 entry.  Bucket A.**

* **Field:** `interfaces[].name`
* **Drift detail:** count drift `10 → 11 (interfaces)`.  Net
  growth — target re-parse produces *more* interfaces than source.
  Target sample names: `bridge1`, `Vlan10`, `GigabitEthernet0/0/0`
  (the rest truncated by comparator dump).  RouterOS's
  `/ip address add interface=...` lines synthesise a stub interface
  on re-parse if the named interface wasn't declared via
  `/interface ethernet|bridge|...`.
* **Codec locus:**
  `netcanon/migration/codecs/mikrotik_routeros/render.py` emits
  `/interface ethernet`, `/interface bridge`, `/interface bonding`,
  `/interface vlan` stanzas.  Loopback (`ianaift:softwareLoopback`)
  and Tunnel (`ianaift:tunnel`) interfaces from the source canonical
  have no corresponding RouterOS branch and never reach the wire as
  `/interface` records — only their IPv4 addresses survive via
  `/ip address add interface=Loopback0` lines pointing at non-
  existent interfaces.  On re-parse, the RouterOS parser inflates
  every distinct `interface=` value into a stub canonical interface,
  producing the count overshoot rather than undershoot.
* **YAML status:**
  `cross_vendor_expectations/cisco_iosxe__mikrotik_routeros.yaml:202-211`
  labels `interfaces[].name` as `good` with a note about the
  rename-mesh translating Cisco speed-encoded names to RouterOS
  flat etherN form.  The `good` disposition is wrong for source
  fixtures carrying Loopback / Tunnel — but flipping the YAML
  doesn't fix the drift, since real users will hit this on captures
  that include loopbacks.  Real Bucket A.
* **Recommended action:** add a Loopback / Tunnel emission branch
  in `mikrotik_routeros/render.py` driven by canonical
  `interface_type` (RouterOS uses `/interface bridge` for loopback
  emulation, `/interface gre` / `/interface ovpn` for tunnels,
  depending on platform).  Same fix removes a class of count-drift
  cascades for any source codec carrying loopback or tunnel
  interfaces.

### Target: opnsense

**1 entry.  Bucket B.**

* **Field:** `interfaces[].ipv4_addresses`
* **Drift detail:** identical to the cisco_iosxe_cli case —
  `GigabitEthernet0/0/1` 3 addrs → 1, `GigabitEthernet0/0/3` 2
  addrs → 1.  Only the primary survives.
* **Codec locus:**
  `netcanon/migration/codecs/opnsense/render.py:252-254` emits only
  `iface.ipv4_addresses[0]` to `<ipaddr>` + `<subnet>`.  This is
  declared in the codec docstring and capability matrix as a
  one-IP-per-zone modelling limit; OPNsense has `<virtualip>` blocks
  but the canonical emitter doesn't bridge into them.
* **YAML status:**
  `cross_vendor_expectations/cisco_iosxe__opnsense.yaml:252-260`
  labels the field `good` but its own `note` says "Multiple IPv4
  addresses per Cisco interface degrade to the primary only on the
  canonical model (one address per interface)".  The note
  contradicts the disposition.  Pure Bucket B.
* **Recommended action:** flip the pair YAML disposition `good` →
  `lossy` and use the existing `note` text verbatim as the `reason`.
  Code change to render into `<virtualip>` is a feature ask, not a
  bug fix — defer until a real capture asks for it.

## Recommended fix work

Ordered by severity × leverage (a single fix that clears multiple
cells across the cross-mesh ranks above one-cell fixes):

1. **`netcanon/migration/codecs/aruba_aoss/parse.py:207`** — widen
   `_IFACE_HEADER_RE` to accept multi-slash Cisco-shaped port names
   (or fix the AOS-S render to apply the port-rename mesh, which
   the YAML claims is already happening).  Single-line regex change
   unblocks 1 CODEC_BUG on this source vendor and the underlying
   render-emits-but-parse-rejects asymmetry recurs for any non-AOS-S
   source codec — high cross-vendor leverage.  Add a unit test in
   `tests/unit/migration/codecs/aruba_aoss/test_parse_iface_header.py`
   asserting `_IFACE_HEADER_RE.match("interface GigabitEthernet0/0/0")`
   is non-`None`.
2. **`netcanon/migration/codecs/cisco_iosxe_cli/parse.py:560-561`
   + `render.py:253-255`** — coordinated change to emit / accept
   `secondary` keyword for IPv4 addresses index >= 1.  Unblocks 1
   CODEC_BUG on this same-vendor cross-format pair AND makes the
   codec emit syntactically valid Cisco config (currently a real
   IOS-XE device would reject the second `ip address` without
   `secondary`).  Add unit test on render
   (`test_render_ipv4_secondary`) and round-trip test
   (`len(parse(render(intent_with_3_v4)).interfaces[0].ipv4_addresses)
   == 3`).
3. **`netcanon/migration/codecs/mikrotik_routeros/render.py`** —
   add Loopback / Tunnel emission branches driven by canonical
   `interface_type`.  Unblocks 1 CODEC_BUG here and eliminates the
   count-drift overshoot for any source codec that carries
   non-ethernet / non-VLAN canonical interfaces (every CLI source
   codec eventually).

YAML hygiene fixes (no code change; single-commit corrections that
clear three of the seven cells immediately):

* `cross_vendor_expectations/cisco_iosxe__fortigate_cli.yaml:212-221`
  — flip `interfaces[].description` from `good` to `lossy` (note
  already explains the 25-char truncation).
* `cross_vendor_expectations/cisco_iosxe__opnsense.yaml:252-260` —
  flip `interfaces[].ipv4_addresses` from `good` to `lossy` (note
  already explains "degrade to the primary only").
* `cross_vendor_expectations/cisco_iosxe__cisco_iosxe_cli.yaml:242-249`
  — flip `interfaces[].interface_type` from `good` to `lossy` with
  a reason citing the l2vlan/l3ipvlan SVI inference asymmetry.
  (The same file's `interfaces[].ipv4_addresses` at line 263 stays
  `good` — that one is Bucket A waiting on the code fix above.)

A separate task to investigate but not fix here:

* **Junos render-side missing branch** (Bucket A entry on the
  juniper_junos cell).  Comparator dump truncates the target list
  so the dropped interface isn't directly visible from
  `latest.json`.  Add a focused round-trip unit test under
  `tests/unit/migration/codecs/juniper_junos/` against the
  kitchen_sink intent and inspect which canonical interface_type the
  Junos render skips; fix that branch.

## See also

* `tests/fixtures/real/PHASE4_RECONCILIATION.md` — top-level summary
  matrix that this report drills into for cisco_iosxe-as-source.
* `tests/fixtures/real/_phase4_runs/latest.json` — raw per-cell
  CODEC_BUG records this report classifies.
* `tests/fixtures/cross_vendor_expectations/cisco_iosxe__<target>.yaml`
  — pair-specific expectation YAMLs cited in each Bucket B finding.
* Sibling Phase-4b reports under
  `tests/fixtures/real/phase4_findings_<vendor>.md` — the
  cisco_iosxe_cli, juniper_junos, mikrotik_routeros, fortigate_cli,
  opnsense, and aruba_aoss reports cover the reverse direction of
  every cell touched here.
* `netcanon/migration/codecs/cisco_iosxe/codec.py` — the
  Phase-0.5 stub source codec; the parse-side wire-up gap that
  dominates `METHODOLOGY_ISSUE_under` counts (and which is *not*
  driving any of the 7 CODEC_BUGs above) is documented in its
  module docstring and capability-matrix notes.
