# Phase 4b — `cisco_iosxe` (NETCONF / OpenConfig XML) source findings

Source codec: `cisco_iosxe` (Phase-0.5 NETCONF / OpenConfig stub —
`netconfig/migration/codecs/cisco_iosxe/codec.py`).  This codec's
`parse()` walks the `<interfaces>` subtree only; every other declared-
`supported` capability matrix path (system, vlans, network-instances,
snmp, routing) is aspirational wire-up that hasn't landed.  Most cells
in the cross-mesh therefore exhibit `METHODOLOGY_ISSUE_under` (parse
side never populates) rather than CODEC_BUG.

Inputs reconciled:

* `tests/fixtures/real/_phase4_runs/latest.json` (run
  `2026-05-02T06:54:10Z`, mesh run `20260501T141211Z.json`)
* `tests/fixtures/cross_vendor_expectations/cisco_iosxe__<target>.yaml`
  for the seven cross-vendor pairs (intra-vendor self-pair has no YAML
  by Phase-3 design)
* The lone fixture exercising this source codec is
  `tests/fixtures/synthetic/cisco_iosxe/kitchen_sink.xml` — a 10-
  interface OpenConfig snapshot covering ethernet, loopback, tunnel,
  l2vlan / SVI, ieee8023adLag, multi-IPv4, dual-stack, and
  enabled-false.  No real captures for this codec yet (Phase-0.5
  status; no published OpenConfig <get-config> dump in the corpus).

## CODEC_BUG counts per target

| Target              | CODEC_BUG | Notes                               |
|---------------------|----------:|-------------------------------------|
| arista_eos          |         0 | All drift covered by EXPECTED_LOSSY |
| aruba_aoss          |         4 | name / description / enabled / ipv4 |
| cisco_iosxe (self)  |         0 | Self round-trip, no YAML            |
| cisco_iosxe_cli     |         2 | interface_type / ipv4_addresses     |
| fortigate_cli       |         1 | description                         |
| juniper_junos       |         0 | All drift covered by EXPECTED_LOSSY |
| mikrotik_routeros   |         4 | name / description / enabled / ipv4 |
| opnsense            |         1 | ipv4_addresses                      |
| **Σ**               |    **12** |                                     |

The 12 high-severity CODEC_BUG findings reduce to **five distinct root
causes**, none of which are bugs in the cisco_iosxe (NETCONF) source
codec itself.  All actionable fixes live in target codecs or in the
expectation YAMLs.

---

## Finding 1 — aruba_aoss & mikrotik_routeros: count drift cascades

**Pairs affected:** `cisco_iosxe → aruba_aoss` (4 CODEC_BUGs),
`cisco_iosxe → mikrotik_routeros` (4 CODEC_BUGs).  `name`,
`description`, `enabled`, `ipv4_addresses` all flagged on the same
underlying drift.

**What drifted.**  Phase-1 `field_disposition.interfaces`:

* aruba_aoss: `source_count=10 → target_count=3` (only `Loopback0`,
  `Loopback1`, `Tunnel100` survive the round-trip).  All seven
  ethernet / Vlan10 / Port-channel1 records lost.
* mikrotik_routeros: `source_count=10 → target_count=8`.

The Phase-4 reconciliation script blames every per-iface field as
drifted because the records simply aren't present on the target side
to compare — the count drift swallows seven (or two) sub-fields each.
Same actual bug surfaces as four CODEC_BUGs in the field-variances
JSON because the Phase-3 YAML labels each of name / description /
enabled / ipv4_addresses as `good`.

**Codec responsible.**  Target codecs.  The cisco_iosxe NETCONF parser
emits all 10 interfaces correctly into the canonical tree; the loss
happens on render → re-parse.

**Likely fix locations:**

1. `netconfig/migration/codecs/aruba_aoss/parse.py:174-176` —
   `_IFACE_HEADER_RE = re.compile(r'^interface\s+("?[A-Za-z]*\d+(?:/\d+)?"?)\s*$')`.
   The regex accepts at most one `/` segment, so the AOS-S parser
   silently drops Cisco-shaped names like `GigabitEthernet0/0/0`,
   `GigabitEthernet0/0/1` etc. on re-parse.  The render side
   (`render.py:329`) emits `interface GigabitEthernet0/0/0` literally
   without applying any port-rename mesh, so the bytes the renderer
   writes don't match what the parser reads back.  This is the
   canonical "render-emits-but-parse-rejects" mismatch.  Two ways to
   fix:
   * widen the parse regex to accept multi-slash port names (cheap;
     keeps the asymmetric-rename tech debt deferred); OR
   * have the AOS-S render path apply the port-rename mesh on
     `iface.name` before emitting (architecturally cleaner; this is
     the same fix the cross-vendor expectation YAMLs anticipate when
     they say "via the port-rename mesh").
2. `netconfig/migration/codecs/mikrotik_routeros/render.py:85-110` —
   the mikrotik render only emits `/interface ethernet`,
   `/interface bridge`, `/interface bonding`, `/interface vlan`
   stanzas.  Loopback (`ianaift:softwareLoopback`) and Tunnel
   (`ianaift:tunnel`) interfaces from the source canonical have no
   corresponding RouterOS branch and never reach the wire — only
   their IPv4 addresses survive via `/ip address add` lines pointing
   at non-existent interfaces, which the re-parse can't reattach.
   Fix: add a Loopback / Tunnel emission branch (RouterOS uses
   `/interface ovpn-server`, `/interface gre`, `/interface bridge`
   for loopback emulation depending on platform; the canonical
   `interface_type` should drive the choice).

**Test that would catch the fix.**

* For aruba_aoss: a unit test in
  `tests/unit/migration/codecs/aruba_aoss/test_parse_iface_header.py`
  asserting that
  `_IFACE_HEADER_RE.match("interface GigabitEthernet0/0/0")` is
  non-None (currently None — silently dropped).  Equivalent via the
  full pipeline: a `tests/integration/migration/test_aruba_aoss_round_trip.py`
  fixture pasting Cisco-shaped names and asserting iface count
  preserves.
* For mikrotik_routeros: a unit test asserting that
  `render_intent(intent_with_loopback)` emits a `/interface bridge`
  (or platform-equivalent) entry for a `softwareLoopback` interface,
  and the round-trip preserves the iface count.

---

## Finding 2 — cisco_iosxe_cli & fortigate_cli & opnsense: secondary IPv4 addresses dropped on render / re-parse

**Pairs affected:** `cisco_iosxe → cisco_iosxe_cli` (1 CODEC_BUG on
`ipv4_addresses`), `cisco_iosxe → opnsense` (1 CODEC_BUG on
`ipv4_addresses`).  Same symptom on `cisco_iosxe → fortigate_cli`
(secondary addresses lost) but already absorbed into the description
finding because that pair's `ipv4_addresses` YAML disposition is
`lossy`.

**What drifted.**  The kitchen_sink fixture's `GigabitEthernet0/0/1`
carries three IPv4 addresses (10.0.10.1/24, 10.0.11.1/24,
10.0.12.1/24); `GigabitEthernet0/0/3` carries two
(172.16.0.1/30, 172.16.100.1/24 — the latter from a dot1q
sub-interface absorbed onto the parent).  After cisco_iosxe NETCONF
parse the canonical correctly carries all addresses; after rendering
into the CLI / OPNsense target and re-parsing, only the first
address survives.

**Codec responsible.**  Target codecs.  Two distinct mechanisms:

* `cisco_iosxe_cli`:
  * Render
    (`netconfig/migration/codecs/cisco_iosxe_cli/render.py:202-204`)
    emits every address as a bare `ip address X.X.X.X MASK` —
    Cisco IOS-XE rejects this on a real device (only the first is
    primary; the rest must be `ip address X.X.X.X MASK secondary`).
  * Parse
    (`netconfig/migration/codecs/cisco_iosxe_cli/parse.py:347-353`)
    has the inverse defect: an explicit `if not current["ipv4"]:
    # primary only` guard discards every line beyond the first.  So
    even if the renderer emitted the `secondary` keyword, the parser
    would still drop them today.  Both halves need fixing for
    multi-IPv4 to round-trip.
* `opnsense`
  (`netconfig/migration/codecs/opnsense/render.py:137-139`) emits
  only `iface.ipv4_addresses[0]` to `<ipaddr>` + `<subnet>`.  This
  is documented in the codec docstring and capability matrix as a
  one-IP-per-zone modelling limit; OPNsense has `<virtualip>` blocks
  but the canonical emitter doesn't bridge into them.

**Likely fix location.**

* CLI: parse and render both, with a coordinated change.  The cleanest
  fix is to extend the CLI render to emit `secondary` for index>=1 and
  the parser to accept `secondary` as a continuation (preserving
  primary-first ordering on the canonical list).
* OPNsense: render the secondary addresses into `<virtualip>` (or at
  minimum surface them as XML comments so the data isn't silently
  dropped — same pattern the codec already uses for unmodelled DHCP
  pools).

Honest skepticism: the OPNsense expectation YAML
(`cisco_iosxe__opnsense.yaml:252-260`) says `ipv4_addresses` is `good`
but the note explicitly says "Multiple IPv4 addresses per Cisco
interface degrade to the primary only on the canonical model (one
address per interface)."  The note contradicts the disposition — this
is a **YAML expectation bug**.  The disposition should be `lossy` with
that note.  Same critique applies to `cisco_iosxe__cisco_iosxe_cli.yaml`:
the YAML says `good` but a same-vendor round-trip that loses
secondaries is `lossy`, not `good`.

**Test that would catch the fix.**

* Unit test in `tests/unit/migration/codecs/cisco_iosxe_cli/test_render_ipv4_secondary.py`
  asserting `render(intent_with_3_v4_addrs)` emits `ip address X
  MASK secondary` for the second and third addresses.
* Round-trip integration test asserting
  `len(parse(render(intent_with_3_v4_addrs)).interfaces[0].ipv4_addresses) == 3`.
* OPNsense: unit test on the render asserting that
  `iface.ipv4_addresses[1:]` either become `<virtualip>` entries OR
  are surfaced as a comment (the test should encode whichever
  decision the team makes).

---

## Finding 3 — cisco_iosxe_cli: SVI interface_type drift (l2vlan → l3ipvlan)

**Pair affected:** `cisco_iosxe → cisco_iosxe_cli` (1 CODEC_BUG on
`interfaces[].interface_type`).

**What drifted.**  Source `Vlan10` carries
`interface_type="ianaift:l2vlan"` from the OpenConfig
`<type>ianaift:l2vlan</type>` element.  Round-trip target carries
`ianaift:l3ipvlan`.

**Codec responsible.**  Target codec, but it's a vendor-modelling
ambiguity rather than a clean bug.
`netconfig/migration/codecs/cisco_iosxe_cli/parse.py:90` hard-codes
`"vlan": "ianaift:l3ipvlan"` in the name-prefix → IANA-ifType lookup.
The IANA registry distinguishes:

* `l2vlan` (135) — bridge / IEEE 802.1Q VLAN sub-interface
* `l3ipvlan` (136) — routed VLAN / SVI carrying L3

OpenConfig models a Catalyst SVI as `l2vlan` because the underlying
hardware port is L2-VLAN-tagged; IOS-XE's CLI behavior (`interface
Vlan10` always implies a routed SVI) is closer to `l3ipvlan`.  Both
choices are defensible.

**Likely fix location.**  Pick one and align both codecs:

* If we say "Cisco SVI is always l3ipvlan", change the cisco_iosxe
  NETCONF parser to map the source `<type>` to `l3ipvlan` when the
  iface name starts with `Vlan` (override the wire value).  Keeps
  the CLI parser as-is.  This is a parse-side wire-up choice on the
  NETCONF codec.
* If we say "preserve what the wire said", change the CLI parser
  to map name-prefix `Vlan` to `l2vlan` when the source IANA ident
  was l2vlan, OR widen the canonical model so `interface_type`
  carries an alternation (`l2vlan|l3ipvlan` set).

The honest framing: this is an inferred-type asymmetry already
flagged in the cross-vendor YAMLs (e.g.
`cisco_iosxe__cisco_iosxe_cli.yaml:242-249` calls `interface_type`
`good`, but the same-vendor cross-format round-trip clearly isn't
byte-perfect for SVIs).  The cisco_iosxe_cli pair YAML's `good`
disposition for `interface_type` is **another YAML expectation bug**
— it should be `lossy` with the inferred-type note.

**Test that would catch the fix.**  Unit test asserting that
`parse_cli("interface Vlan10\n ip address 10.10.10.1 255.255.255.0\n")
.interfaces[0].interface_type` matches whatever the chosen-canonical
form says (currently `l3ipvlan`; would need to flip if we adopt
"preserve l2vlan" semantics).

---

## Finding 4 — fortigate_cli: description truncated to 25 chars

**Pair affected:** `cisco_iosxe → fortigate_cli` (1 CODEC_BUG on
`interfaces[].description`).

**What drifted.**  Six interfaces with descriptions longer than 25
characters (e.g. `WAN uplink to upstream carrier` — 30 chars) are
truncated at byte 25 by the FortiGate render.

**Codec responsible.**  This is **not** a bug — it's an intentional,
well-documented capability-matrix limit.

* `netconfig/migration/codecs/fortigate_cli/render.py:117-120` emits
  `iface.description[:25]` with the comment "FortiOS alias caps at
  25 chars per spec."
* `netconfig/migration/codecs/fortigate_cli/codec.py:144-150`
  declares `LossyPath(path="/interfaces/interface/config/description",
  reason="FortiOS limits alias to 25 characters; longer descriptions
  from other vendors will be truncated.")`.

**Likely fix location.**  YAML expectation, not codec.  The pair YAML
`tests/fixtures/cross_vendor_expectations/cisco_iosxe__fortigate_cli.yaml:212-221`
correctly explains the truncation in the note ("FortiOS caps alias at
25 characters — longer Cisco descriptions truncate on FortiGate
render") but contradicts itself by labelling the disposition `good`.
Should be `lossy` with that exact note as the reason.

**Test that would catch the fix.**  None code-side — this is a
documentation correctness issue.  The Phase-4 reconciliation already
catches it; the fix is to align the YAML disposition with the codec's
declared `LossyPath`.

---

## Finding 5 — Mikrotik description drift (sub-finding of count drift)

The mikrotik_routeros CODEC_BUG on `description` is the same count-
drift cascade as Finding 1; once two interfaces are silently dropped
on render (Loopback / Tunnel emission gap), every per-iface field on
those records reads as drifted.  No separate fix needed beyond
Finding 1.

---

## Skepticism on METHODOLOGY_ISSUE_under findings

Per Phase-4 brief: when source emits zero records for a field
(`source_count=0`), Phase-1 trivial preservation can produce
`METHODOLOGY_ISSUE_under` flags that look like drift.  Spot-checking
a handful of these on the cisco_iosxe → arista_eos cell (35 such
findings) confirms they are honestly described by the YAML's
`not_applicable` dispositions (parser doesn't populate `<system>`,
`<vlans>`, `<network-instances>`, etc., so every system / vlan /
routing / snmp / lag / aaa field is `(not_populated, not_applicable)`
which the reconciliation labels `METHODOLOGY_ISSUE_under, severity=low`).
None of these warrant promotion to a CODEC_BUG; they are
fixture-coverage gaps masquerading as variances and the YAMLs already
classify them correctly.

When the cisco_iosxe codec graduates from Phase-0.5 stub to wired
parse (`<system>`, `<vlans>`, etc.), a substantial Phase-3 YAML
revision will be needed: most `not_applicable` dispositions will flip
to `good` or `lossy`.  The pair YAMLs flag this explicitly in their
"Notes on confidence" sections.

---

## Top 3 actionable fix locations

1. **`netconfig/migration/codecs/aruba_aoss/parse.py:174-176`** —
   widen `_IFACE_HEADER_RE` to accept multi-slash Cisco-shaped port
   names (or fix the render to apply port-rename mesh).  Single-line
   regex change unblocks 4 of the 12 CODEC_BUGs and the comparable
   render-emits-but-parse-rejects issue is likely to recur for any
   non-AOS-S source codec.
2. **`netconfig/migration/codecs/cisco_iosxe_cli/parse.py:347-353`
   + `render.py:202-204`** — coordinated change to emit / accept
   `secondary` keyword for IPv4 addresses index >= 1.  Unblocks 1
   CODEC_BUG on the same-vendor cross-format pair AND makes the
   codec emit syntactically valid Cisco config (currently a real
   IOS-XE device would reject the second `ip address` without
   `secondary`).
3. **`netconfig/migration/codecs/mikrotik_routeros/render.py:85-110`**
   — add a Loopback / Tunnel emission branch driven by canonical
   `interface_type`.  Unblocks 4 CODEC_BUGs on the cisco_iosxe →
   mikrotik pair and removes a class of count-drift cascades for
   any source codec carrying loopback or tunnel interfaces.

YAML hygiene fixes (no code change, single-commit corrections):

* `tests/fixtures/cross_vendor_expectations/cisco_iosxe__fortigate_cli.yaml:212-221`
  — flip `interfaces[].description` from `good` to `lossy` (note
  already explains the 25-char truncation).
* `tests/fixtures/cross_vendor_expectations/cisco_iosxe__opnsense.yaml:252-260`
  — flip `interfaces[].ipv4_addresses` from `good` to `lossy` (note
  already explains "degrade to the primary only").
* `tests/fixtures/cross_vendor_expectations/cisco_iosxe__cisco_iosxe_cli.yaml:263-280`
  — flip `interfaces[].ipv4_addresses` from `good` to `lossy`
  (multi-address loss); flip `interfaces[].interface_type` from
  `good` to `lossy` (l2vlan/l3ipvlan inference asymmetry).

## See also

* `tests/fixtures/real/PHASE4_RECONCILIATION.md` — top-level summary
  matrix this report drills into for cisco_iosxe-as-source.
* `tests/fixtures/real/_phase4_runs/latest.json` — raw per-cell
  CODEC_BUG records this report classifies.
* `tests/fixtures/cross_vendor_expectations/README.md` — schema
  spec the YAML expectations this report critiques are written
  against.
* `netconfig/migration/codecs/cisco_iosxe/codec.py` — the
  Phase-0.5 stub source codec; the parse-side wire-up gap that
  dominates METHODOLOGY_ISSUE_under counts is documented in its
  module docstring and capability-matrix notes.
