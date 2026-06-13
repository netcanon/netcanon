# result-RA-06 — R-06 (FortiGate MTU `_CAPS` + docs) + R-08 (stale cross-mesh artifacts)

**Agent:** RA-06 (opus) · **Findings:** R-06 (fix), R-08 (analyze + regen spec)
**Verdict on the supported-vs-lossy call: `supported`** (full parse + render
wire-up — high confidence, grounded in the project's own MTU worked example).

---

## 0. TL;DR for the orchestrator

1. **R-06 core fix is tiny and additive:** add ONE xpath
   (`/interfaces/interface/config/mtu`) to FortiGate's `_CAPS.supported`
   list + two doc edits. FortiGate parses **and** renders MTU today
   (proven green by `test_mtu_wire_through.py::TestFortiGateMTUParseRender`);
   the missing `_CAPS` entry is a checklist-step-6 miss from the original
   MTU wire-through commit. The fix matches how `cisco_iosxe_cli`,
   `arista_eos`, `juniper_junos` treat MTU.
2. **NO matrix ripple from the `_CAPS` edit.** Confirmed three ways
   (see §3): `_walk_canonical` never emits the mtu xpath, the mesh audits
   `interfaces` as a whole (mtu is a sub-field, not a tracked top-level
   field), and the `_WIRED_UP_BY_CODEC` invariant only governs the 5 Wave
   A/B/C paths. Adding mtu to `supported` changes ZERO matrix cells and
   trips ZERO invariants. The expectation YAMLs key on `interfaces[].mtu`
   (a field-name, not the xpath) and are **not** asserted against codec
   behavior by any test (`test_cross_vendor_expectations.py` does not
   exist; the loader is schema-lint only).
3. **R-08 is independent and real:** corpus is **45** real fixtures, the
   artifacts are pinned to **39**. The two regen commands refresh them.
   The regen is needed for R-08 regardless of the R-06 `_CAPS` edit.
4. **Bonus finding (flagged, NOT in the apply-ready edits):** one
   expectation YAML, `fortigate_cli__cisco_iosxe.yaml`, contains a
   factually-wrong `reason` ("the fortigate_cli parser does not currently
   surface [mtu]… parse-side codec gap") that directly contradicts the
   code + the green test. It is stale documentation that passes the
   schema-lint. See §6 — recommend a follow-up, left out of the core PR to
   keep R-06 tight. Sibling YAMLs (`fortigate_cli__juniper_junos.yaml`,
   `fortigate_cli__opnsense.yaml`, `fortigate_cli__arista_eos.yaml`)
   already describe FortiGate-parses-mtu correctly, so this is an
   internal contradiction in the YAML corpus.

---

## 1. Finding + current state (with file:line)

**R-06.** FortiGate's codec wires per-interface MTU bidirectionally, but
the `_CAPS` matrix is silent on it and two docs are wrong:

- **Parse captures mtu:**
  `netcanon/migration/codecs/fortigate_cli/parse.py:325-330` —
  `mtu_tokens = edit.settings.get("mtu")` → `iface.mtu = int(mtu_tokens[0])`.
- **Render emits mtu:**
  `netcanon/migration/codecs/fortigate_cli/render.py:632-637` —
  `if iface.mtu is not None: set mtu-override enable / set mtu {N}`.
- **`_CAPS` omits the xpath:**
  `netcanon/migration/codecs/fortigate_cli/codec.py:114-154` — the
  `supported` list has no `/interfaces/interface/config/mtu` entry (and
  it is not in `lossy`/`unsupported` either → matrix-silent).
- **Proof it works today:**
  `tests/unit/migration/test_mtu_wire_through.py:139-174`
  (`TestFortiGateMTUParseRender`: parse, render-emits-both, round-trip) —
  **runs green** (I ran it: 3 passed).
- **Doc over-claim:** `docs/CAPABILITIES.md:52-61` — the Tier-1 blanket
  "Fully modelled; every shipped bidirectional codec parses and renders"
  is contradicted by FortiGate's own per-codec table, which lists
  `tunnel_type` as **lossy** (`fortigate_cli/codec.py:172-182`) and never
  mentions mtu.
- **Doc wrong:** `docs/vendors/fortigate.md:32-36` — claims MTU is "parsed
  when FortiGate is the *source* … **but not emitted when FortiGate is the
  *target***". The render path at `render.py:632-637` emits it; this is
  flatly false.

**The supported-vs-lossy call → `supported`.** Authoritative basis:
`docs/adding-a-canonical-field.md` is the project's MTU worked example. It
shows FortiGate parse (lines 121-131), FortiGate render incl. the
`mtu-override enable` quirk (lines 157-163), and **Step 6 (lines 225-237)
puts `/interfaces/interface/config/mtu` in `supported_paths`**. Lines
299-304 explicitly classify the `mtu-override enable` requirement as a
"per-vendor quirk … in the codec's render path, not a lossiness." So mtu
is a clean Tier-2 wire-through → `supported`, exactly like the peer CLI
codecs (which carry it implicitly; see §3). `cisco_iosxe` (NETCONF) is the
only codec that declares mtu **lossy** (`cisco_iosxe/codec.py:222-230`) —
that lossiness is OpenConfig-single-leaf-specific and does **not** apply to
the FortiGate CLI codec.

**R-08.** `tests/fixtures/real/CROSS_MESH_RESULTS.md:3` header says
"376 cells (39 real + 8 synthetic fixtures × 8 bidirectional targets)",
generated `2026-05-05`. Actual corpus today = **45 real fixtures**
(arista 5 + aruba 6 + cisco_iosxe 13 + fortigate 3 + junos 7 + mikrotik 4
+ opnsense 7 = 45; verified by directory listing). `PHASE4_RECONCILIATION.md`
shares the same stale snapshot. No staleness banner on either.

---

## 2. Proposed change — APPLY-READY

### Edit 1 of 3 — FortiGate `_CAPS` (the only code edit)

**File:** `netcanon/migration/codecs/fortigate_cli/codec.py`

Add the mtu xpath to the `supported` list. Insert it right after the
ipv6-prefix-length line (matching the position peers keep interface scalars
and grouping it with the other `/interfaces/interface/config/*` and
ipv4/ipv6 address paths). The DHCPv6 line follows it unchanged.

**OLD** (codec.py — current `supported` interface block, lines ~122-126):

```python
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            "/interfaces/interface/dhcp-client-v6",          # set ip6-mode dhcp
```

**NEW:**

```python
            "/interfaces/interface/ipv4/address/ip",
            "/interfaces/interface/ipv4/address/prefix-length",
            "/interfaces/interface/ipv6/address/ip",         # GAP-EVPN-3
            "/interfaces/interface/ipv6/address/prefix-length",  # GAP-EVPN-3
            # Per-interface MTU — parse (`set mtu N` →
            # CanonicalInterface.mtu) + render (`set mtu-override enable`
            # + `set mtu N`) both wired; see
            # tests/unit/migration/test_mtu_wire_through.py
            # ::TestFortiGateMTUParseRender and the MTU worked example in
            # docs/adding-a-canonical-field.md.  The `mtu-override enable`
            # gate is a FortiOS render-side quirk, not a lossiness — full
            # round-trip parity, so `supported` (matches cisco_iosxe_cli /
            # arista_eos / juniper_junos, which carry mtu implicitly).
            "/interfaces/interface/config/mtu",
            "/interfaces/interface/dhcp-client-v6",          # set ip6-mode dhcp
```

> Note for the orchestrator: the inserted `old_string` anchor above is
> unique within `codec.py`. If you prefer a leaner comment, the
> load-bearing line is just `"/interfaces/interface/config/mtu",` placed
> anywhere inside the `supported=[ ... ]` list.

### Edit 2 of 3 — `docs/CAPABILITIES.md` Tier-1 blanket (soften)

**File:** `docs/CAPABILITIES.md`

**OLD** (lines 52-61):

```markdown
### Tier 1 — auto-translatable (cross-vendor stable)

Fully modelled; every shipped bidirectional codec parses and renders:

* `hostname`, `domain`
* `interfaces` — `name`, `description`, `enabled`, IPv4 + IPv6
  addresses, `vrf` binding, `kind` (physical / mgmt / loopback /
  uplink), `mtu`, `lag_member_of`, `dhcp_client_v6` (IPv6 DHCPv6 /
  SLAAC mode discriminator), `tunnel_type` (GRE / EoIP / IPIP /
  IPSEC / VXLAN encap discriminator)
```

**NEW:**

```markdown
### Tier 1 — auto-translatable (cross-vendor stable)

Modelled and wired across the shipped bidirectional codecs.  Most leaves
round-trip cleanly on every codec; a few carry documented per-codec
exceptions (e.g. `tunnel_type` is **lossy** on FortiGate — FortiOS expresses
tunnels in separate top-level sections, not as an encap discriminator on a
tunnel interface; `mtu` is unsupported on Aruba AOS-S, which has no per-port
MTU concept).  The per-codec tables under
[§A](#a-capability-matrix-unsupported--lossy-panels) are the source of
truth for which leaves are lossy/unsupported on which codec; this list
names the canonical surface, not a blanket guarantee.

* `hostname`, `domain`
* `interfaces` — `name`, `description`, `enabled`, IPv4 + IPv6
  addresses, `vrf` binding, `kind` (physical / mgmt / loopback /
  uplink), `mtu`, `lag_member_of`, `dhcp_client_v6` (IPv6 DHCPv6 /
  SLAAC mode discriminator), `tunnel_type` (GRE / EoIP / IPIP /
  IPSEC / VXLAN encap discriminator)
```

> Rationale: removes the false "every … codec parses and renders" /
> "Fully modelled" absolute, points operators to the honest per-codec
> tables, and explicitly names the two known Tier-1 exceptions
> (FortiGate `tunnel_type` lossy per `fortigate_cli/codec.py:172-182`;
> Aruba `mtu` unsupported per `docs/adding-a-canonical-field.md:133-136`).
> Note: the FortiGate per-codec table at `CAPABILITIES.md:259-276` does
> NOT need an mtu row added — it lists only lossy/unsupported paths, and
> mtu is now `supported` (supported paths are not enumerated in those
> tables, consistent with how the other codecs' supported mtu is unlisted).

### Edit 3 of 3 — `docs/vendors/fortigate.md` MTU note (correct the lie)

**File:** `docs/vendors/fortigate.md`

**OLD** (lines 32-36, inside the "What translates well / Tier 1" bullet):

```markdown
  **Note:** per-interface MTU is parsed when FortiGate is the
  *source* (carried into the canonical model and rendered by other
  target codecs that emit MTU) but not emitted when FortiGate is the
  *target* — see codec capability matrix.  Per-interface VRF is
  routing-instance-scoped, not a Tier-1 binding.
```

**NEW:**

```markdown
  **Note:** per-interface MTU round-trips both directions — parsed from
  `set mtu N` into the canonical model, and emitted on render as
  `set mtu-override enable` + `set mtu N` (FortiOS requires the override
  flag before `set mtu` takes effect on physical ports).  `mtu` is declared
  `supported` in the codec capability matrix.  Per-interface VRF is
  routing-instance-scoped, not a Tier-1 binding.
```

> Source of the correction: `render.py:632-637` (emits both lines) +
> `test_mtu_wire_through.py:151-161` (asserts both lines appear).

---

## 3. Why there is NO matrix ripple from the `_CAPS` edit (critical)

The R-06 brief flagged a possible "matrix ripple" (expectation-YAML edits +
regen tied to the `_CAPS` change). After tracing the validation + mesh +
reconciliation machinery, **the `_CAPS` edit is matrix-inert**. Three
independent reasons:

**(a) The validation walker never emits the mtu xpath.**
`netcanon/migration/codecs/cisco_iosxe_cli/codec.py::_walk_canonical`
(lines 503-562, the shared walker every codec's `iter_xpaths` delegates to —
FortiGate included, via `codec.py:324-327`) has **no** `if iface.mtu:` branch.
It never yields `/interfaces/interface/config/mtu`. Therefore
`classify_tree` (`services/migration_validate.py:48-88`) never classifies an
mtu xpath against any codec's `_CAPS`. The xpath is matrix-invisible whether
declared or not. (This is also why `cisco_iosxe`'s *declared-lossy* mtu entry
never actually fires in validation — it's documentation-grade.)

**(b) `CapabilityMatrix.classify` defaults undeclared paths to `supported`.**
`netcanon/models/migration.py:196-220`: resolution is unsupported → lossy →
else **`supported` (implicit)**. So even if the walker emitted mtu, an
undeclared mtu on the peer CLI codecs already classifies as supported — which
is exactly the "declare only the exceptions" pattern those codecs use
(`cisco_iosxe_cli`, `arista_eos`, `juniper_junos` parse+render mtu and do
**not** list it). Adding FortiGate's explicit entry makes the honest state
**explicit** without changing any computed classification.

**(c) The cross-mesh audit tracks `interfaces` as a whole, not `mtu`.**
`tools/run_full_mesh.py::_AUDITED_FIELDS` (lines 137-164) is a tuple of
**top-level `CanonicalIntent` fields** — `interfaces`, `vlans`, … —
`mtu` is **not** in it (it is a sub-field of each interface record). The
`"mtu": null` strings in `CROSS_MESH_RESULTS.md` are just part of the
serialized interface JSON blob the mesh diffs, not a tracked cell. The
mesh already reflects FortiGate's real mtu behavior (mtu has been wired in
code for some time); changing `_CAPS` does not re-run or alter translations.

**(d) The `_WIRED_UP_BY_CODEC` invariant does not cover mtu.**
`tests/unit/migration/test_canonical_vrrp_anycast_schema.py:312-446`
(`TestShipBeforeWireUnsupportedDeclarations`) only governs the 5 Wave A/B/C
paths (`_NEW_PATHS`, lines 312-318): vrrp-groups, the two virtual-gateway-
address paths, anycast-gateway-mac, static-route/vrf. `mtu` is not among
them, so adding it to FortiGate's `supported` list trips nothing. The test
reads `supported = set(codec.capabilities.supported)` (line 410) but only
inspects the 5 paths — an extra mtu entry is ignored.

**(e) No test asserts FortiGate's `supported` list contents/length.**
Confirmed by grep: only `test_canonical_vrrp_anycast_schema.py:410` and
`test_cisco_iosxe.py:425` read a codec's `supported` list, neither pins
FortiGate's exact membership.

**Net: the expectation YAMLs need NO change for the `_CAPS` edit, and the
regen for R-08 is independent of it.** (One YAML is wrong on its own merits —
see §6 — but that is a stale-doc finding, not a ripple from this edit.)

---

## 4. R-08 regen spec (orchestrator runs these)

**Corpus confirmed: 45 real fixtures** (was 39 at snapshot time):

| vendor dir | count |
|---|---|
| `tests/fixtures/real/arista_eos` | 5 |
| `tests/fixtures/real/aruba_aoss` | 6 (excl. README.md) |
| `tests/fixtures/real/cisco_iosxe` | 13 |
| `tests/fixtures/real/fortigate` | 3 |
| `tests/fixtures/real/junos` | 7 |
| `tests/fixtures/real/mikrotik` | 4 (`.rsc`) |
| `tests/fixtures/real/opnsense` | 7 |
| **total** | **45** |

**Exact regen commands (from repo root, Windows → `py`):**

```
py tools/run_full_mesh.py --matrix
py tools/run_phase4_reconciliation.py
```

- `run_full_mesh.py --matrix` writes a fresh timestamped JSON under
  `tests/fixtures/real/_cross_mesh_runs/<ts>.json` (gitignored) AND
  regenerates `tests/fixtures/real/CROSS_MESH_RESULTS.md` from it
  (per the tool docstring, lines 24-31).
- `run_phase4_reconciliation.py` reads the most-recent mesh JSON, joins it
  to the per-pair expectation YAMLs, and regenerates
  `tests/fixtures/real/PHASE4_RECONCILIATION.md` (tool docstring lines 67-75;
  default reads latest `_cross_mesh_runs/` JSON, no flag needed). **Run it
  after** the mesh so it picks up the new JSON.

**Expected diff shape:**
- `CROSS_MESH_RESULTS.md`: header line 3 count changes from
  `376 cells (39 real + 8 synthetic …)` to the 45-fixture figure
  (`45 real + 8 synthetic = 53 source fixtures × 8 targets = 424 cells`,
  plus a refreshed generation timestamp), and **6 new source-fixture rows**
  appear (the fixtures absent from the 39-snapshot:
  `arista_eos/batfish_eos_evpn_vlan_based_leaf.txt`,
  `cisco_iosxe/batfish_iosxe_basic_vrrp.txt`,
  `junos/ksator_labmgmt_qfx10k2_junos173.set`,
  `junos/ksator_labmgmt_qfx5100_junos173.set`,
  `junos/ksator_labmgmt_qfx5110_junos173.set`, and one
  mikrotik/opnsense delta — confirm against the regenerated file).
  Existing cells may shift if any codec behavior changed since 2026-05-05.
- `PHASE4_RECONCILIATION.md`: refreshed counts + the same 6 fixtures'
  per-cell variance classes added; no schema change.
- **No `_CAPS`-driven cell change** (see §3). If the regen shows mtu-related
  cell movement, that is a pre-existing drift surfaced by the corpus
  refresh, not caused by this PR's `_CAPS` edit.

> Matrix-honesty caveat: the regenerated `.md` files are
> machine-generated; the orchestrator commits them verbatim (per the
> tool docstrings) — do not hand-edit. If `run_phase4_reconciliation.py`
> emits new `CODEC_BUG` cells, that is signal worth a glance but is out
> of scope for R-06/R-08 (those are corpus-refresh findings).

---

## 5. Test plan

**For the `_CAPS` + doc edits (R-06):**

```
py -m pytest tests/unit/migration/test_mtu_wire_through.py -q -p no:cacheprovider
py -m pytest tests/unit/migration/test_fortigate_cli.py -q -p no:cacheprovider
py -m pytest tests/unit/migration/test_canonical_vrrp_anycast_schema.py -q -p no:cacheprovider
py -m pytest tests/unit/migration/test_cross_codec_matrix.py -q -p no:cacheprovider
py -m pytest tests/unit/migration/test_validate.py tests/unit/migration/test_cross_codec_pipeline.py -q -p no:cacheprovider
```

Expectation: all green, **unchanged** — the `_CAPS` edit is additive and
matrix-inert (§3). `test_mtu_wire_through.py::TestFortiGateMTUParseRender`
already passes today (I verified: 3 passed) and continues to; it is the
behavioral guard that the `supported` declaration now matches.
`test_canonical_vrrp_anycast_schema.py` must stay green (proves the
`_WIRED_UP_BY_CODEC` invariant is untouched).

Optional broader safety net (matrix-honesty + audit tooling):

```
py -m pytest tests/unit/audit -q -p no:cacheprovider
py -m pytest tests/unit/migration/codecs/fortigate_cli -q -p no:cacheprovider
```

**No new test file is required.** The behavior is already covered by
`test_mtu_wire_through.py::TestFortiGateMTUParseRender`. If the orchestrator
wants belt-and-suspenders on the new declaration, a one-liner can be added
to `test_fortigate_cli.py` (optional, not required):

```python
def test_caps_declares_mtu_supported():
    """R-06: FortiGate parses+renders per-interface MTU
    (test_mtu_wire_through.py) — the capability matrix must declare it
    supported, matching the MTU worked example in
    docs/adding-a-canonical-field.md step 6."""
    from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
    caps = FortiGateCLICodec().capabilities
    assert "/interfaces/interface/config/mtu" in caps.supported
    # And it must not be double-declared lossy/unsupported.
    assert "/interfaces/interface/config/mtu" not in {p.path for p in caps.lossy}
    assert "/interfaces/interface/config/mtu" not in {
        p.path for p in caps.unsupported
    }
```

**For R-08:** after running the two regen commands, run the audit-tool
tests to confirm the generators still pass on the 45-corpus:

```
py -m pytest tests/unit/audit/test_run_full_mesh.py tests/unit/audit/test_run_phase4_reconciliation.py -q -p no:cacheprovider
```

These tests exercise `compute_field_disposition` / the reconciler logic, not
the committed `.md` content, so they should be green before and after.

---

## 6. Bonus finding — stale expectation YAML (RECOMMEND follow-up, NOT in core PR)

Independent of the `_CAPS`/doc edits, one expectation YAML carries a
factually-wrong rationale that contradicts the code and the green test:

- **`tests/fixtures/cross_vendor_expectations/fortigate_cli__cisco_iosxe.yaml:265-276`** —
  `interfaces[].mtu` `disposition: lossy`, reason says *"the fortigate_cli
  parser does not currently surface it onto canonical (parse-side codec gap;
  deferred). `intent.interfaces[].mtu` is None on parse"*. **False** —
  `parse.py:325-330` sets it and `test_mtu_wire_through.py:140-149` asserts
  `intent.interfaces[0].mtu == 1500`.
- Same file **line 621** (trailing comment): *"mtu — fortigate_cli
  parse-side gap (`set mtu <N>` not surfaced…)"*. Same falsehood.
- Sibling FortiGate-source YAMLs are already **correct** and contradict the
  above: `fortigate_cli__juniper_junos.yaml:335-342` ("mtu present implies
  override"), `fortigate_cli__opnsense.yaml:310-316`,
  `fortigate_cli__arista_eos.yaml:202,211` ("mtu (good — both store
  integer)"). So the corpus is internally inconsistent about FortiGate
  parsing mtu.

**Why this is NOT in the apply-ready edits above:**
1. R-06's stated scope is the `_CAPS` entry + the two named docs.
2. No test asserts YAML `disposition`/`reason` against behavior
   (`tests/unit/migration/test_cross_vendor_expectations.py` does not
   exist; `tools/load_cross_vendor_expectations.py` is schema-lint only —
   it validates the disposition enum + that lossy/unsupported carry a
   `reason`, but never compares to codec output). So the wrong reason
   passes CI today.
3. The **disposition** (`lossy`) for the `fortigate_cli → cisco_iosxe`
   direction is arguably still defensible (the cisco_iosxe NETCONF *target*
   is a stub that renders interfaces-only and declares mtu lossy), so the
   PHASE4 variance class may not change — but the **reason string is dead
   wrong** and should be rewritten to attribute the drift to the
   cisco_iosxe target-side stub, not a (nonexistent) FortiGate parse gap.

**Suggested follow-up reason (if the orchestrator chooses to fold it in):**

> OLD `fortigate_cli__cisco_iosxe.yaml:267-276` reason →
> NEW: "FortiGate parses `set mtu <N>` into `CanonicalInterface.mtu`
> (gated on `set mtu-override enable` on render). The `cisco_iosxe`
> NETCONF target is a Phase-0.5 stub whose `_render_canonical()` emits
> only `openconfig-interfaces` and does not emit `<config><mtu>`, so the
> MTU drops on this direction. Even with a full NETCONF render, the
> cisco_iosxe matrix declares `/interfaces/interface/config/mtu` lossy
> (OpenConfig's single mtu leaf can't distinguish link-MTU from `ip mtu`
> / `ipv6 mtu` / `mpls mtu`)."

I have left this as a recommendation rather than an apply-ready edit
because it widens R-06 beyond its charter and touches the YAML corpus the
DC-02 regen also reads. If folded in, run the schema-lint after:
`py tools/load_cross_vendor_expectations.py` (must exit 0 — the reason key
is still present, so the lint stays happy), then re-run the R-08 regen so
PHASE4 reflects any reclassification. **Could also be spun off as its own
small task.**

Also borderline (FYI, not recommended for edit): the *direction-specific*
"`set mtu` is not emitted" tails in `aruba_aoss__fortigate_cli.yaml:241-244`
and `:483-487` are technically correct in disposition (Aruba **source**
doesn't parse mtu, so canonical is empty → FortiGate emits nothing **in that
direction**) but read as if FortiGate can't emit mtu at all. These are
defensible as-is; leave them unless doing a full YAML sweep.

---

## 7. Risk + blast radius

- **`_CAPS` edit:** additive, matrix-inert (§3). Cannot break the
  `_WIRED_UP_BY_CODEC` two-sided invariant (mtu not in its scope). Cannot
  change cross-mesh cells (mtu not a tracked top-level field; walker never
  emits the xpath). Cannot create an `iter_xpaths`-vs-`supported` mismatch
  (the codecs/README.md:398-404 rule requires emitted⊆declared, not
  declared⊆emitted; walker emits no mtu, so adding a declared mtu is safe).
- **Doc edits:** prose-only, zero code impact. The CAPABILITIES.md change is
  a softening that brings the blanket in line with the already-honest
  per-codec tables (matrix-honesty discipline: docs must not over-claim).
- **R-08 regen:** regenerates two machine-generated `.md` artifacts. Risk is
  that the refresh surfaces *pre-existing* drift on the 6 new fixtures (new
  WARN/CODEC_BUG cells). That is honest signal, not a regression introduced
  here; the orchestrator should commit the regenerated files as-is and, if
  any `CODEC_BUG` cells appear, note them for a separate triage (out of
  R-06/R-08 scope).
- **Matrix-honesty:** the whole change *increases* honesty (declares a real
  capability that was silent; softens a doc over-claim; refreshes stale
  generated artifacts). No honesty regression.

---

## 8. Self-assessment

- **Confidence: HIGH** on the `supported` call. It is not a judgment call —
  `docs/adding-a-canonical-field.md` Step 6 is the project's own MTU worked
  example and literally places `/interfaces/interface/config/mtu` in
  `supported_paths`; `test_mtu_wire_through.py::TestFortiGateMTUParseRender`
  is green today; peer CLI codecs treat mtu as (implicitly) supported. The
  only codec with a *lossy* mtu is `cisco_iosxe` NETCONF, for an
  OpenConfig-leaf reason that does not apply to the FortiGate CLI codec.
- **Confidence: HIGH** that the `_CAPS` edit causes no matrix ripple
  (§3, four independent confirmations + grep of all `supported`-reading
  tests).
- **Confidence: HIGH** on the R-08 corpus count (45, directory-verified)
  and the regen commands (read straight from the two tools' docstrings).
- **Open questions for the orchestrator:**
  1. **Fold in the §6 YAML reason fix, or spin it off?** It is a genuine
     doc-honesty defect (contradicts code + a sibling YAML) but widens
     R-06's charter and touches the corpus the R-08 regen reads. My
     recommendation: spin it off as a tiny follow-up (or fold into the R-08
     PR since both touch the cross-mesh corpus), keeping the R-06 PR to the
     three clean edits in §2.
  2. **Exact CROSS_MESH header count after regen** — I projected
     `45 real + 8 synthetic`; the generator computes the precise cell count
     and the exact list of 6 added rows. Trust the regenerated file over my
     projection.
  3. The optional `test_caps_declares_mtu_supported` guard (§5) — add it or
     not? It is belt-and-suspenders; `test_mtu_wire_through.py` already
     guards behavior. I lean "add it" because it pins the *declaration*
     (which had silently drifted from behavior — that is the exact class of
     bug R-06 is), and it is 8 cheap lines with no runtime cost.
