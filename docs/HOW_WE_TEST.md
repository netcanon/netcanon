# How We Test — The matrix-honesty discipline

If you're a network engineer evaluating Netcanon, this page is the
substrate for the trust claim.  Every assertion the project makes
about translation accuracy has a verifiable test backing it.  The
table below describes how, layer by layer.

This is the operator-facing version of the discipline that
[`docs/METHODOLOGY.md`](METHODOLOGY.md) documents at the
contributor / methodology level.

---

## TL;DR

Netcanon ships with **four independent test layers** that gate every
release:

| Layer | What it tests | Speed |
|---|---|---|
| **Unit** | Every codec parser + renderer in isolation against synthetic and real-capture inputs | ~30s for the full tier |
| **Integration** | The HTTP API + migration pipeline end-to-end via FastAPI TestClient | ~60s |
| **E2E** | The browser UI via Playwright against a live Uvicorn server | ~5min |
| **Desktop** | The PySide6 + pystray desktop shell with mocked Qt | ~30s |

Plus a **fifth layer that's the differentiator**:

| Layer | What it tests |
|---|---|
| **Cross-mesh audit** | Every supported vendor pair's translation through the canonical intermediate, parsed against vendor-doc-grounded expectations |

The cross-mesh audit is what catches **silent** translation errors —
the kind where the codec produces output that *looks* valid but
quietly drops or transforms a field in a way the operator wouldn't
spot until the device behaves wrong in production.

---

## The matrix

The cross-mesh audit runs on every PR and on every fixture import.
Its results live in
[`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
(machine-generated; not hand-edited).

Each cell of the matrix is one (source vendor × target vendor ×
field) translation, classified into one of **8 variance classes**:

| Class | Meaning |
|---|---|
| **ALIGNED** | Source field translates to target field exactly as the vendor docs predict.  Boring; we want most cells in this class. |
| **CODEC_BUG** *(high severity)* | The translation produced a result that contradicts the vendor docs.  Either parse misread the source or render emitted wrong syntax.  **Goal: zero.**  Live count lives in [`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md) — that file is machine-generated, so it can't drift behind code. |
| **EXPECTED_LOSSY** | The capability matrix declares this field path as `lossy` for this pair, with a cited reason (e.g. per-VRF static-route VRF discriminator drops on round-trip).  Verified against the declaration. |
| **EXPECTED_UNSUPPORTED** | The capability matrix declares this field path as `unsupported` for this pair.  No render attempted; the migrate page surfaces it via the Tier-3 banner or the unsupported-paths panel. |
| **METHODOLOGY_ISSUE_under** | The expectation under-claims — the codec actually translates correctly, but the cross-vendor expectation YAML doesn't account for it.  Methodology bug; fixed by updating the expectation. |
| **METHODOLOGY_ISSUE_over** | The expectation over-claims — declares a field "should translate" when vendor docs disagree.  Methodology bug; fixed by softening the expectation. |
| **STRUCTURAL_ONLY** | Translation produced output but the comparison fails on structural details (dict ordering, list reordering) that don't carry semantic meaning.  Comparator bug; fixed by adding a normalization rule. |
| **TRIVIAL_EMPTY** | Both source and target are empty for this field.  Not a translation; a coverage gap to fill. |

The variance-class taxonomy is **complete** — every cell falls into
one of these eight.  Drift between "expected" and "actual" gets
classified honestly rather than smoothed over.

---

## The trust claim, quantified

> Across every supported vendor pair × every field declared as
> `supported`, the cross-mesh audit holds **zero CODEC_BUG cells**
> as of the current commit.

That's not "we think it works"; that's "every cell that should
translate, does, by automated test against vendor-doc-grounded
expectations."

The honest follow-up: **the audit only covers cells we have
fixtures for.**  Real-world configs exercise paths the synthetic
fixtures haven't reached.  See
[`../BUG_REPORTING.md`](../BUG_REPORTING.md) for how to submit a
fixture that surfaces a path we don't yet test — that's the
highest-impact contribution to the project.

---

## What the layers actually run

### Layer 1: Unit tests

`pytest tests/unit` — pure-function tests, no I/O.

Every codec parser is exercised against:
- **Synthetic kitchen-sink fixtures** — hand-crafted to exercise
  every grammar form the codec models
- **Real-capture fixtures** — sanitized configs from public
  sources (Batfish, ntc-templates, vendor docs, community forum
  shares) and operator contributions, listed in
  [`tests/fixtures/real/NOTICE.md`](../tests/fixtures/real/NOTICE.md)

Every renderer is exercised against the symmetric round-trip:
parse → render → parse → assert structural equality.

Per-codec round-trip suites live under
`tests/unit/migration/codecs/<vendor>/`.

### Layer 2: Integration tests

`pytest tests/integration` — HTTP API surface via FastAPI
`TestClient`, no real device interaction.  The backup collector
is mocked at a single entry point (`get_collector`) so tests
exercise the full migration pipeline without touching real SSH /
NETCONF.

### Layer 3: E2E tests

`pytest -m e2e` — Playwright against a live Uvicorn server.
Exercises the migrate-page flows: paste source, pick target, run
plan, view diff, accept/decline review comments.

### Layer 4: Desktop tests

`pytest tests/desktop` — PySide6 + pystray mocked at a shared
conftest so the desktop shell logic gets exercised without a real
display.

### Layer 5: Cross-mesh audit

`python tools/run_full_mesh.py --matrix` — generates
`tests/fixtures/real/CROSS_MESH_RESULTS.md` (mechanical
parse-render drift across every (source × target × fixture)
permutation).

`python tools/run_phase4_reconciliation.py` — applies the 8-class
variance taxonomy and generates
`tests/fixtures/real/PHASE4_RECONCILIATION.md` (the matrix).

Both run in CI on every PR; the matrix gets regenerated on every
codec change per the
[doc-sync checklist](../AGENTS.md#documentation-sync-checklist).

---

## Why this matters

Most config-translator tools in this space have one of two failure
modes:

1. **Over-claim accuracy + silently drop content.**  Operator runs
   the tool, gets output that looks right, deploys to a device,
   and discovers a missing field two weeks later in a production
   incident.
2. **Under-claim accuracy + over-warn.**  Operator runs the tool,
   gets warnings on every line, tunes them out, and back to (1).

The matrix-honesty discipline avoids both.  Every field is one of:

- **Supported** — translates correctly, audit-verified.
- **Lossy** — translates with a cited boundary; the boundary is
  visible to the operator via review comments.
- **Unsupported** — explicitly out of scope (Tier 3); the migrate
  page surfaces it via the dropped-Tier-3-sections banner.

There's no fourth state.  No "we think it might work."  No
"deprecated, but kept around."

---

## See also

- [`CAPABILITIES.md`](CAPABILITIES.md) — operator-facing capability
  matrix (the source of truth this page narrates)
- [`METHODOLOGY.md`](METHODOLOGY.md) — the contributor / engineering
  version of the same discipline (with worked-example citations
  into the live tree)
- [`vendors/README.md`](vendors/README.md) — per-vendor "what works
  for me?" pages
- [`../tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md)
  — live per-codec certification state
- [`../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  — live cross-mesh audit
- [`../tests/README.md`](../tests/README.md) — test-suite layout
  for contributors
- [`../BUG_REPORTING.md`](../BUG_REPORTING.md) — how to submit a
  fixture that surfaces a path we don't yet test
