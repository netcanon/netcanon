# Cluster A — Interlinking & structural integrity

## Scope

Every `*.md` file in the repo EXCEPT those in `.claude/` (Claude
Code session data, not project content).  Total: ~778 files.

**Sampling strategy for `docs/vendor-references/<pair>/`** (~600
files):

* Audit one representative pair in full depth (suggest
  `docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/` since
  Junos↔Cisco is the project's most-cited pair).
* For the other ~41 pairs, verify the template SHAPE is consistent
  (same set of file names, same heading structure) rather than
  auditing each page individually.  Outlier pairs = report; matching
  pairs = note as conforming.

**Treatment of special folders** (per audit charter):

| Folder | Treatment |
|---|---|
| `docs/security-triage/2026-05-21/` | Read for interlinking only; do NOT flag content as "stale" |
| `docs/v0.2.0-planning/` | Read for interlinking only; gaps to current state are expected |
| `docs/fixture-research-2015/` | Read for interlinking only |
| `docs/templates/` | Read for interlinking only; netcanon-specific content gap is expected (it's a clone-to-other-projects template) |
| `docs/archive/` | Verify only that cross-refs INTO it from current docs still resolve |

## What to check

1. **Internal link resolution.**  For every `[text](path)` or
   `[text](#anchor)` link in any .md, verify the target exists.
   * For relative paths: walk up `../` correctly from the source
     file's directory.
   * For anchor links (`#section-name`): verify the heading exists
     in the target file (slugified per GitHub's anchor convention).
   * For inline code references like `` `file.py:line` ``: not
     links; skip unless the surrounding prose calls them references.

2. **"See also" reciprocity.**  Per `AGENTS.md` § "Cross-reference
   discipline":
   > Every doc in `tests/`, `docs/`, and top-level `*.md` should
   > open with (or end with) a "See also" line pointing to its two
   > or three closest peers. ... When you add a new sibling doc,
   > add the reciprocal link in the existing peers in the same
   > commit — one-way cross-references rot faster than numbers do.
   For each "See also" entry A → B, verify there's a B → A entry
   (in B's See also section).  Asymmetric pairs = WRONG.

3. **Orphan docs.**  A doc that no other doc references AT ALL.
   May indicate the doc is dead (delete) or that peer docs missed
   adding a reference (add).  Surface for review.

4. **Contents-map drift.**  Per AGENTS.md doc-sync rule:
   > A file-tree listing or "contents map" in any doc (ARCHITECTURE.md
   > partial inventories, migrate.html header comment, sub-README
   > directory trees) | Either update the listing in the same commit
   > as the new file, OR convert the listing to a pointer.
   For every .md that contains a directory listing, file enumeration,
   or "contents map" comment, verify the listing matches reality.

5. **External link sanity.**  For `http(s)://` links: verify they're
   well-formed URLs.  Do NOT fetch them (avoid rate limits / slowness);
   just check syntax + flag obvious dead patterns (e.g. links to
   removed PR numbers in github.com, deprecated domain names).

6. **`See also` section presence.**  Per the discipline rule:
   every contributor-facing doc in `docs/`, `tests/`, or top-level
   should HAVE a See also section.  Surface docs that lack one
   entirely.

## Methodology

* Use `Grep` for `\[.*\]\(.*\)` link extraction and `^## See also`
  section identification.  Bulk operations.
* Use `Read` selectively for verification of specific anchor
  targets or contents-map sections.
* `Bash` (`gh api`, `git log`) only for cross-checking commit refs
  cited in docs (e.g. "see commit abc1234" — verify abc1234 exists).

## Severity tagging

| Severity | Examples |
|---|---|
| **WRONG** | Broken link to non-existent file; "See also" pointer to a renamed/deleted doc; contents-map listing entries that don't exist |
| **MISSING** | A → B "See also" with no B → A back-link; doc with no "See also" section at all |
| **INCOMPLETE** | "See also" with only one peer when AGENTS.md says 2-3; contents-map missing entries that do exist |
| **STYLE** | Inconsistent link format; non-relative path where a relative would be clearer |
| **EXPECTED-STALE** | Link into security-triage/<old-date>/ that resolves but the target is intentionally frozen — note + skip |

## Output format

Write to: `docs/docs-audit/2026-05-21/01-investigation-A.md`

```markdown
# Cluster A — Interlinking & structural integrity

## Summary

(2-3 sentence verdict: how many WRONG / MISSING / INCOMPLETE / STYLE
findings across the ~778 .md surface.)

## Statistics

* Total .md files audited: X (Y in current-state, Z in special folders)
* Total internal links resolved: ...
* Broken internal links: ...
* "See also" asymmetric pairs: ...
* Orphan docs: ...
* Contents-map drift instances: ...

## WRONG findings

| # | Source path:line | Issue | Fix shape |
|---|---|---|---|

## MISSING findings

| # | Source path | Issue | Fix shape |
|---|---|---|---|

## INCOMPLETE findings

| # | Source path | Issue | Fix shape |
|---|---|---|---|

## STYLE findings (defer-eligible)

| # | Source path | Issue | Fix shape |
|---|---|---|---|

## Vendor-references sampling result

(Did the sampled pair audit cleanly?  Are the other ~41 pairs
template-shape-consistent?)

## Cross-cutting observations

(Anything worth noting that doesn't fit per-alert format.  E.g.
patterns observed across multiple findings, suggested process
improvements.)
```

## Constraints

* **READ-ONLY on repo code.**  You may use Read, Grep, Glob, Bash
  for non-destructive commands.  Do NOT edit any file except your
  single output file.
* Do not commit; do not modify any .md or .py.
* Hard rules inheritance: per `AGENTS.md` § "Hard Rules (Never
  Break)" — especially the "never include real password hashes"
  rule if you happen to read fixture files in the course of
  resolving citations.
* Time budget: this is the largest cluster by file count but most
  work is mechanical Grep / link-resolution.  Aim for ~45-60 min
  worth of investigation density.
* If anchor-slug verification gets ambiguous (GitHub's slug rules
  for non-ASCII / punctuation), flag rather than guess.
