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

1. **Sanitize your config.**  Use the Phase 4.5 sanitiser:
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
