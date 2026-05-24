# 2026-05-21 — Documentation hygiene audit snapshot

First docs-audit cycle.  Triggered after a sustained run of
substantive change waves:

1. Phase 6 supply-chain integrity (signing, SBOM, Trusted Publishing)
2. v0.1.1 ship (VRRP/anycast schema + 7-codec wire-up + bug-fix pair)
3. Fixture-research-2015 catalogue (overlay-authoring backlog)
4. v0.1.2 security-hardening (defusedxml + workflow hardening +
   scanner enablement + new triage scaffolding)

Doc drift surface is at its widest.  Per the audit charter, this
cycle runs read-only Stage 1 agents in parallel + orchestrator-
synthesised Stage 2 fixes.

## Repo state at audit start

```
HEAD:           e1b9902 (release: v0.1.2)
Latest tag:     v0.1.2 (shipped to PyPI / GHCR / Docker Hub / GitHub Release)
Working tree:   clean (in sync with origin)
Test suite:     2685 passed, 56 skipped (last verified pre-v0.1.2)
Code Scanning:  0 open alerts (post 2026-05-21 security-triage cycle)
Dependabot:     0 open alerts
```

## Surface inventory

### .md files

```
Total .md files (excluding .claude/):   778
  docs/vendor-references/<pair>/:        ~600   ← per-vendor-pair pages, sampling-only
  docs/v0.2.0-planning/:                  31   ← forward-looking, EXPECTED-STALE
  docs/fixture-research-2015/:            17   ← historical research, EXPECTED-STALE
  tests/ (subtree):                       19
  docs/security-triage/<date>/:            6   ← frozen evidence trail, EXPECTED-STALE
  Top-level (README, AGENTS, etc.):        9
  docs/<top-level>:                       ~11
  docs/vendors/:                          ~10
  docs/walkthroughs/:                      5-6
  docs/templates/:                          1
  netcanon/.../README.md sub-READMEs:       5
  definitions/.../README.md:                1
```

### .py files

```
Total netcanon/ .py files:               112
  migration/codecs/ (8 codecs — note:      45
    cisco_iosxe NETCONF +
    cisco_iosxe_cli are distinct):
  migration/canonical/:                    9
  services/:                               5
  api/:                                   14
  collectors/:                             5
  storage/:                                7
  models/:                                 8
  (root + cli.py + other):                19

Total tests/ .py files:                  212
```

### Special-folder counts (EXPECTED-STALE per audit charter)

| Folder | Files | Why expected-stale |
|---|---|---|
| `docs/security-triage/2026-05-21/` | 7 .md + 6 JSON | Frozen evidence trail of prior triage cycle |
| `docs/v0.2.0-planning/` | 31 .md | Forward-looking design — gap between described future and present is expected |
| `docs/fixture-research-2015/` | 17 .md | Historical research snapshot |
| `docs/templates/` | 1 .md (+ subtree) | Aspirational starter scaffolding for cloning to other projects |
| `docs/archive/` | (subtree) | Retired docs preserved for citation |

## Cluster dispatch

| # | Cluster | Files | Scope file | Agent | Output |
|---|---|---|---|---|---|
| A | Interlinking & structural integrity | ALL .md (778) | `cluster-A-interlinking-scope.md` | Opus 1M, read-only | `01-investigation-A.md` |
| B | User-facing docs accuracy | ~30 hand-curated user docs | `cluster-B-user-docs-scope.md` | Opus 1M, read-only | `01-investigation-B.md` |
| C | Developer-facing docs accuracy | ~15 contributor docs | `cluster-C-developer-docs-scope.md` | Opus 1M, read-only | `01-investigation-C.md` |
| D | Codec docstrings + file headers | 45 .py files in codecs/ | `cluster-D-codec-docstrings-scope.md` | Opus 1M, read-only | `01-investigation-D.md` |
| E | Platform code docstrings | ~67 .py files outside codecs/ | `cluster-E-platform-docstrings-scope.md` | Opus 1M, read-only | `01-investigation-E.md` |
| F | Tests + CHANGELOG accuracy | 19 .md + key conftest + pyproject + CHANGELOG | `cluster-F-tests-changelog-scope.md` | Opus 1M, read-only | `01-investigation-F.md` |

All 6 agents dispatched in parallel; no worktree isolation
(read-only).  Synthesis follows the security-triage pattern.

## User-set policy for this run

* **Scope:** audit all docs, but treat special folders (security-triage/
  per-date, v0.2.0-planning/, fixture-research-2015/, templates/) as
  EXPECTED-STALE — surface findings only where they contradict
  patterns the special folder itself claims to maintain.
* **Posture:** verify existing claims AND surface missing doc
  coverage (both directions).
* **Stage 2 intent:** mirror security-triage — synthesise + plan +
  execute fixes commit-by-commit.
* **Model:** Opus 4.7 1M for every Stage 1 agent.
* **Severity threshold for Stage 2 fix execution:** to be decided
  post-synthesis based on actual finding volume (WRONG always
  fixes; MISSING + INCOMPLETE evaluated case-by-case; STYLE
  batched or deferred).

## See also

* [`README.md`](../README.md) — process doc + cluster taxonomy
* [`docs/security-triage/README.md`](../../security-triage/README.md) —
  sister process; same scaffolding pattern applied to security
  alerts
