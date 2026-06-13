# 99 — Documentation fleet synthesis

Consolidates the six Fleet-D investigations (DA–DF).  Authored by the
orchestrator after all six landed.  Per-finding detail lives in the
`01-investigation-D*.md` chapters; this file is the cross-cluster view.

## Headline verdict

**The documentation surface is in strong shape and the discipline is
real** — 100% module-docstring coverage (179/179, per DC), an honest
and complete 56-pair vendor-reference mesh, zero dead links across 190
files / 1161 internal links (DB), and the 2026-05-21 docs-audit's
commits verifiably landed (DD/DE/DF all independently confirmed their
respective audit fixes stuck).  This is not a codebase whose docs are
rotting.

What the review found is a **thin layer of post-v0.1.2 drift** plus a
**handful of items the prior audit didn't reach** — almost all
low-to-medium severity, none catastrophic, and several clustering into
three recurring themes worth fixing as batches rather than one-offs.

## Cross-cluster themes

### Theme D-1 — `best_effort` → `certified` claim drift (the audit's near-miss)
The 2026-05-21 audit fixed the MikroTik `best_effort`→`certified`
header (Commit 8) but **missed the identical defect on Aruba**:
`aruba_aoss/__init__.py:52` still says `best_effort — validated against
synthetic fixtures` while `codec.py:70` declares `certainty="certified"`
(DE-01, HIGH). This is a doc-vs-code contradiction in an operator-facing
certainty claim — the single highest-value doc finding. Suggests a
**header-vs-ClassVar invariant test** would close the whole class.

### Theme D-2 — generated test-state artifacts pinned to a stale corpus
`RESULTS.md` internally contradicts itself (Summary table says 17 bugs
at `:623`, prose says "10 total … five codecs" at `:639` — stale
v0.1.1 vocabulary; it's now 7 codecs / 17 bugs, DC-01). `CROSS_MESH_RESULTS.md`
+ `PHASE4_RECONCILIATION.md` are pinned to a **39-fixture** snapshot
while the corpus is now **45** (DC-02). These are *generated* files —
the right fix is to re-run `tools/run_full_mesh.py --matrix` +
`tools/run_phase4_reconciliation.py` and recommit, not hand-edit.

### Theme D-3 — stale "Phase N / ship-before-wire" futures that already shipped
`migration/__init__.py:13-15` + `canonical/__init__.py:5-7` still frame
transforms as "out of scope (Phase 2+)" and the canonical tree as "an
opaque `dict[str,str]`" (DD-02); `intent.py` VRRP/anycast docstrings
still say "ship-before-wire … unsupported until wire-up" though Wave
B/C wired them (DD-03 / CB-01, **adversarially confirmed docstring-only
— the `_CAPS` are honest**). `METHODOLOGY.md` itself names this exact
anti-pattern ("Phase 2 will add a resolver" docstrings). Low blast
radius, but it's a *named* discipline violation, so worth a sweep.

### Theme D-4 — operator-facing capability over-claims (matrix-honesty at the prose layer)
`CAPABILITIES.md:54-61` Tier-1 blanket "every bidirectional codec
parses and renders these fully" over-claims (`tunnel_type` is lossy on
FortiGate `codec.py:172-182`; `mtu` is matrix-silent there), and
`docs/vendors/fortigate.md:33-36` says MTU isn't emitted when the
renderer in fact emits it (`render.py:632-637`) — DA-02/DA-03. The
per-codec tables below the summary are honest; the *summary sentences*
drift. This is the matrix-honesty discipline leaking at the prose tier.

### Theme D-5 — interlinking is healthy; a few reciprocity + index gaps remain
DB found **0 dead links** but: `tests/README.md:129-139` See-also
points only down to its children, never back up to README/AGENTS
(breaks one of AGENTS.md's three named reciprocity exemplars, DB-01);
`docs/v0.2.0-planning/03-nxos-codec/README.md:518-531` lists sub-pages
as bare backticks, orphaning three of them (DB-02); four sub-READMEs
have zero inbound links (DB-03). All P3.

### Theme D-6 — meta-doc currency: two real gaps in the contributor docs
`AGENTS.md:186` hard-codes "SECURITY.md … (line 385)" but the trigger
list is now at `SECURITY.md:492` — the *sole* surviving drifted
line-ref, ironically in the row warning about SECURITY.md drift (DF-01).
`ARCHITECTURE.md` never inventories `netcanon/security/` (Fernet
credential encryption + 3-tier key resolution — a cross-cutting,
partly-v0.1.2 package, DF-02), and `AGENTS.md:192` falsely claims
`_tier3_detection.py` is documented in ARCHITECTURE.md when it isn't
(DF-03).

## Severity rollup (Fleet D)

| Sev | Count | Items |
|-----|------:|-------|
| HIGH/P-high | 2 | DE-01 (Aruba cert header) · DD-01 (Junos `TypeError` — **a code bug**, surfaced via docstring lens; owned by Fleet C) |
| MED/P2 | ~9 | DA-02, DA-03, DC-01, DC-02, DE-02, DE-03/04, DF-01, DF-02, DF-03 |
| LOW/P3 | ~14 | DB-01/02/03(+), DC-04(+), DD-02, DD-03, DE-05…, DF-04/05/06 |
| OBSERVATION | many | see chapters |

(DD-01 is a genuine code defect that the docstring lens surfaced; it is
carried in the **code** synthesis, not double-counted here.)

## What's GOOD (propagate these)
- **100% module-docstring coverage** (179/179) and all 4 conftests
  document *why*, not just *what* (DC).
- **`NOTICE.md` provenance is impeccable** — 45 rows, 1:1 with the
  filesystem (DC); the licensing discipline is exemplary.
- **The em-dash anchor handling is correct** — all 23 em-dash-targeting
  anchors use GitHub's doubled-hyphen slug (DB). Someone understood the
  slug algorithm.
- **The 2026-05-21 anchor migration landed cleanly** — METHODOLOGY.md
  has *zero* surviving hard-coded line-refs (DF); the drift hypothesis
  was a negative result there.
- **Header convention is strong and intentional** — 100% coverage, no
  copy-paste vendor bleed, deliberate no-SPDX/root-LICENSE choice (DE).

## Hand-offs to other artifacts
- DD-01 (Junos `TypeError`) → tracked in `../code-review/99-code-synthesis.md`
  (triple-confirmed code defect).
- DD-03 / CB-01 (VRRP docstring drift) → adversarially settled as
  docstring-only (P3); see top-level synthesis.
- All findings flow into `../findings-register.md` (deduped) and
  `../recommended-remediation-plan.md` (sequenced).
