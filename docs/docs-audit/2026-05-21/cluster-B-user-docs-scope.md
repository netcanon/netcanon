# Cluster B — User-facing documentation accuracy

## Scope

Operator-readable documentation.  Verify claims against current
code, current fixture corpus, current capability matrix, current
CLI surface, current HTTP API surface.

### In scope (full audit)

* `README.md` — top-level, install + quickstart
* `docs/CAPABILITIES.md` — per-codec capability matrix narrative
* `docs/TROUBLESHOOTING.md` — operator failure-mode flowchart
* `BUG_REPORTING.md` — sanitiser workflow + submission flow
* `docs/HOW_WE_TEST.md` — operator-facing audit narrative + variance taxonomy
* `docs/COMPARISON.md` — positioning vs adjacent tools (Batfish / NAPALM / etc.)
* `docs/IDENTITY.md` — project identity surfaces
* `docs/walkthroughs/*.md` — narrative migration scenarios (paired 1:1 with `tools/demo.py` scenarios)
* `docs/vendors/*.md` — per-vendor "what works for me?" pages

### In scope (sampled)

* `docs/vendor-references/<pair>/*.md` (~600 files) — audit ONE
  representative pair in depth (suggest `cisco_iosxe_cli_to_juniper_junos/`);
  for the other ~41 pairs, verify the template shape is consistent
  (same file set, same heading structure)

### Out of scope

* Developer docs (handled by Cluster C)
* Codec docstrings (handled by Cluster D)
* Test docs (handled by Cluster F)
* Special folders (security-triage/per-date/, v0.2.0-planning/,
  fixture-research-2015/, templates/) — read for context only, do
  NOT flag content as stale

## What to verify

1. **Install / quickstart commands.**  Does `pip install netcanon==0.1.2`
   work?  Does the Docker pull command match the registry that exists?
   Does the MSI download path match the GitHub Release?

2. **Capability claims.**  `docs/CAPABILITIES.md` describes per-codec
   `supported` / `lossy` / `unsupported` paths.  Verify against the
   actual `_CAPS` declarations in each codec's `codec.py` AND the
   `_WIRED_UP_BY_CODEC` map in
   `tests/unit/migration/test_canonical_vrrp_anycast_schema.py`.
   Discrepancies = WRONG.

3. **Vendor page accuracy.**  Each `docs/vendors/<vendor>.md` claims
   what works for that vendor.  Verify against:
   * The codec's `_CAPS` matrix
   * `tests/fixtures/real/<vendor>/` actual fixture coverage
   * The vendor's `docs/vendor-references/` reference pairs
   Discrepancies = WRONG.

4. **Walkthrough fidelity.**  Each `docs/walkthroughs/<source>_to_<target>.md`
   pairs with a scenario in `tools/demo.py`.  Per AGENTS.md doc-sync
   row: "Re-run `python tools/demo.py --pair <affected>` to verify
   the embedded synthetic config still translates cleanly. If the
   rendered output's shape changed (added / dropped / reformatted
   lines that operators see), update the walkthrough's 'What
   Netcanon does for you', 'Tier-3 boundary', and 'Manual review
   checklist' sections."  Verify the walkthrough's described
   translation behaviour matches what `tools/demo.py` would
   actually produce TODAY (don't run it; verify by reading the
   embedded config in demo.py and tracing through the codec).

5. **Troubleshooting flowchart.**  Verify failure-mode classes
   (Tier-3 / Lossy / CODEC_BUG) referenced in `TROUBLESHOOTING.md`
   match what the running code actually emits.  Verify the "go to
   this URL / file" pointers all resolve.

6. **Sanitiser claims.**  `BUG_REPORTING.md` describes what gets
   sanitised + what doesn't.  Cross-check against the actual
   sanitiser implementation (likely under
   `netcanon/services/sanitiser.py` or `netcanon/services/redaction.py`
   — Grep to find).  Discrepancies between claimed redaction
   coverage and actual = WRONG.  Documented limitations (e.g.
   "banner text not sanitised") that match current behaviour = OK.

7. **COMPARISON.md positioning.**  Verify the comparison points
   against adjacent tools (Batfish, NAPALM, Capirca, ciscoconfparse,
   NetBox/Nautobot) still hold — focus on netcanon's claimed
   differentiator ("explicit lossy/unsupported declarations") still
   being unique-in-class.  Don't audit the OTHER tools' state.

8. **IDENTITY.md surfaces.**  Tagline, GitHub repo description,
   GitHub Topics list, logo design brief.  Verify the tagline /
   description matches what's actually in the GitHub repo settings
   (via `gh api repos/netcanon/netcanon`).

9. **Vendor-references template consistency.**  Sample ONE pair in
   depth.  For the other ~41, list which (if any) are outliers in
   file count / heading structure.

## Methodology

* `Read` each in-scope doc fully.
* `Grep` for the cited code patterns / file paths to verify they
  exist + the surrounding context matches the doc's claim.
* `Read` the cited codec's `_CAPS` matrix to verify capability
  claims.
* `Bash` (`gh api repos/netcanon/netcanon`) to verify GitHub-side
  metadata claims.
* Do NOT run `python tools/demo.py` (that's an action; trace
  through reading instead).

## Severity tagging

| Severity | Examples |
|---|---|
| **WRONG** | Install command targets a version that doesn't exist; capability matrix narrative contradicts `_CAPS`; walkthrough describes a translation that the current codec doesn't produce |
| **MISSING** | A codec has `supported` paths not documented in `docs/vendors/<vendor>.md`; a CLI subcommand exists but isn't in `README.md` quickstart |
| **INCOMPLETE** | Vendor page mentions some real-capture fixtures but not all; troubleshooting covers some failure classes but not all surfaced ones |
| **STYLE** | Formatting inconsistency; stale doc style not matching current convention |
| **EXPECTED-STALE** | Doc explicitly says "Phase X is planned" and Phase X hasn't shipped — that's forward-looking by design, not a finding |

## Output format

Write to: `docs/docs-audit/2026-05-21/01-investigation-B.md`

```markdown
# Cluster B — User-facing documentation accuracy

## Summary

(2-3 sentence verdict: total findings split by severity; headline
real concerns.)

## Per-doc audit results

(For each in-scope doc, a short verdict block:)

### `<doc path>`
* Verified claims: ...
* Findings: (severity-tagged table or "no findings")

## Vendor-references sampling result

(Sampled-pair audit + cross-pair template consistency report)

## Cross-cutting observations
```

## Constraints

* **READ-ONLY.**  Single output file.  No edits to repo .md or .py.
* Hard rules from `AGENTS.md`.
* Time budget: ~45-60 min.  This cluster has many small docs +
  semantic verification across surfaces.
* If a claim is ambiguous (e.g. "operator-friendly" subjective
  wording), flag as STYLE for orchestrator decision, don't make a
  judgement call.
