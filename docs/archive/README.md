# Historical analysis archive

This directory preserves analysis artifacts from earlier project phases.
None of these files are authoritative for the current state — they're
kept for historical reference (where the project came from, what
research informed early codec decisions).

For current-state authoritative sources, see:

* [`../../CHANGELOG.md`](../../CHANGELOG.md) — what's shipped
* [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) — current four-layer design
* [`../CAPABILITIES.md`](../CAPABILITIES.md) — operator-facing capabilities + limitations
* [`../../tests/fixtures/real/RESULTS.md`](../../tests/fixtures/real/RESULTS.md) — live per-codec certification
* [`../../tests/fixtures/real/PHASE4_RECONCILIATION.md`](../../tests/fixtures/real/PHASE4_RECONCILIATION.md) — live cross-mesh audit

## Files

* `analysis results.txt` (2026-04-15) — 12-lens architectural analysis pass
  results.  Mostly addressed by subsequent waves; preserved for the
  reasoning narrative.
* `netconfigreport.txt` (2026-04-14) — companion architectural review report
  to the 12-lens analysis above.  Same vintage.
* `triage.txt` (2026-04-15) — auto-actionable triage extracted from the
  analysis pass — items that didn't require design decisions.  Most have
  shipped via subsequent waves.
* `vendor-config-research.txt` — cross-vendor feature matrix research notes
  used during initial codec development.  Vendor syntax has evolved since;
  consult vendor documentation for current grammar (the in-tree codec
  parsers under `netconfig/migration/codecs/<vendor>/parse.py` are the
  authoritative reference for what each codec actually accepts).

## When to add new files here

If a new analysis / research / triage artifact is produced and won't be
maintained as living documentation, drop it here with a date prefix
(e.g. `2026-05-00-foo-analysis.txt`) so it's filed alongside the
existing artifacts.  Living documentation goes under `docs/` proper.
