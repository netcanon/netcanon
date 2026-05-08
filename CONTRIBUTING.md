# Contributing to Netcanon

Thanks for considering a contribution.  Netcanon has an opinionated
contribution shape — what gets accepted, what doesn't, and why — that's
worth reading before you write code.

## What this project values

Netcanon is a multi-vendor network config translator with a single
defining discipline: **matrix honesty**.  Every claim about what the tool
does has a verifiable test behind it.  Every codec capability is declared
explicitly — supported, lossy, or unsupported, with a cited reason.
Documentation matches in-app behaviour.  The cross-mesh audit catches
drift before it ships.

If your change preserves matrix honesty, it's likely welcome.  If it adds
a silent loss path, an aspirational claim, or an undocumented behaviour,
it's likely going to need rework.  This doc walks the three most common
contribution paths and points at the rulebook ([`CLAUDE.md`](CLAUDE.md))
that governs all of them.

## Three contribution paths

### 1. Add a fixture (the matrix-friendly path)

The fastest way to improve the project: hand us a real-world config that
exercises a translation we don't currently test.

1. Sanitize the config (the helper documented in `BUG_REPORTING.md`
   ships in Phase 4.5 of [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md);
   until then, hand-redact carefully).
2. Drop the sanitized capture under `tests/fixtures/real/<vendor>/`.
3. Add provenance to `tests/fixtures/real/NOTICE.md`.
4. Add a row to `tests/fixtures/real/RESULTS.md` describing what the
   fixture covers.
5. Wire it into the per-vendor parse test under
   `tests/unit/migration/`.
6. Run the cross-mesh audit
   (`python tools/run_full_mesh.py --matrix`) and commit the
   regenerated `tests/fixtures/real/PHASE4_RECONCILIATION.md`.

If the fixture surfaces a `CODEC_BUG` cell, that's the goal — we want
to know.  Open an issue with the bug report template and reference the
fixture.

### 2. Add a codec (the heavy path)

A new vendor codec is several waves of work; coordinate via an issue
first.  The shape:

1. Implement parse + render under `netconfig/migration/codecs/<vendor>/`.
   Read [`netconfig/migration/codecs/README.md`](netconfig/migration/codecs/README.md)
   first — the "Shape of a codec" section is mandatory reading.
2. Declare the capability matrix exhaustively.  Every supported xpath,
   every lossy xpath with a cited reason, every unsupported xpath with
   a "why not yet" comment.  No placeholders.
3. Add the round-trip suite under
   `tests/unit/migration/codecs/<vendor>/`.
4. Add cross-vendor expectation YAMLs for every pair the codec
   participates in (`tests/fixtures/cross_vendor_expectations/`).
5. Update `tests/fixtures/real/RESULTS.md` with the certification
   state (`alpha` / `beta` / `best_effort` / `certified`).
6. Update [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) with the new
   vendor row.

The matrix-honesty discipline is non-negotiable here.  An over-claiming
codec is worse than a missing codec.

### 3. Add a canonical field (the architectural path)

If the canonical model is missing a field your codec needs, see the
worked example: [`docs/adding-a-canonical-field.md`](docs/adding-a-canonical-field.md).
The MTU wire-through there is the reference pattern.

## Hard rules

The full rulebook is [`CLAUDE.md`](CLAUDE.md).  The most-broken rules:

- **Never** silent-drop content.  If a codec can't translate something,
  declare it `lossy` or `unsupported`, populate
  `dropped_tier3_sections` if it's Tier 3, and surface it in the UI.
- **Never** change the signatures of existing pipeline-stage functions
  in `netconfig/services/migration_pipeline.py` (frozen).
- **Never** skip `data-testid` on new HTML interactive elements.
- **Never** commit real credentials, device IPs, or hostnames.
- **Never** hard-code counts in prose docs without a CI/test guard.
- **Never** author a `type_key` containing `_` or `.` in a YAML.
- **Never** ship code without its docs.  See "Documentation Sync
  Checklist" in `CLAUDE.md` — the rows are concrete and
  rotation-resistant.

## Running tests

```bash
pip install -e .[dev]
pytest tests/unit          # ~30s; pure-function tests
pytest tests/integration   # ~60s; API-level via TestClient
pytest tests/e2e           # ~5min; full browser via Playwright
pytest tests/desktop       # ~30s; desktop shell with mocked PySide6
```

The unit + integration tiers run in CI on every PR.  Local pre-commit
hooks should catch most issues before push.

## Doc-sync discipline

If your change touches code that has documentation describing it,
update the docs in the same commit.  `CLAUDE.md`'s doc-sync table maps
"if you change X then touch Y" concretely; audit every applicable row
before you commit.  Stale docs are bugs.

## Code review

Maintainer review focuses on:

1. **Matrix integrity** — does this preserve the cross-mesh audit?
2. **Doc sync** — do the rows in the doc-sync checklist match this
   change?
3. **Test coverage** — unit + integration for new logic; e2e for new
   UI flows.
4. **Hard-rule compliance** — see [`CLAUDE.md`](CLAUDE.md).

Reviews are honest, not adversarial.  We point at the same rulebook
contributors do.

## Reporting bugs

Use the bug report issue template.  Include sanitized config snippets,
source/target vendors, and what you expected vs got.  Once the
sanitization helper ships (Phase 4.5), `BUG_REPORTING.md` will document
the canonical workflow.

## Reporting security issues

See [`SECURITY.md`](SECURITY.md).  Do not open public issues for
security vulnerabilities — use GitHub's private vulnerability reporting
flow.

## See also

- [`README.md`](README.md) — quickstart
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the four-layer design
- [`CLAUDE.md`](CLAUDE.md) — the full contributor rulebook
- [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) — operator-facing
  capabilities
- [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) — the matrix-honesty
  discipline as a portable methodology
- [`tests/README.md`](tests/README.md) — test-suite layout and mocking
  strategy
