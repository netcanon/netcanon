# 2026-05-21 — initial security-scanner alert wave

First triage cycle after enabling CodeQL (default setup), zizmor,
Trivy, secret scanning, push protection, and private vulnerability
reporting on commits `04002cd` → `1f68713`.

## What was newly enabled

| Tool | Enabled at | First scan |
|---|---|---|
| Private vulnerability reporting | 2026-05-21 ~04:50 UTC | passive |
| Secret scanning | 2026-05-21 ~04:50 UTC | historical sweep, 0 alerts |
| Secret push protection | 2026-05-21 ~04:50 UTC | passive |
| CodeQL (default setup, 3 langs) | 2026-05-21 ~04:55 UTC | 35 alerts |
| zizmor v0.5.6 (.github/workflows/zizmor.yml) | 2026-05-21 ~04:59 UTC | 44 alerts |
| Trivy v0.36.0 (in docker-publish.yml) | 2026-05-21 ~05:02 UTC | *pending* — fires on next `v*.*.*` tag |
| Copilot Autofix | (already on by GitHub default) | passive per-alert |

## Alert inventory

**79 open code-scanning alerts.**  **1 Dependabot alert auto-resolved**
(CVE-2026-33634 trivy-action; bumped 0.24.0 → v0.36.0 in `1f68713`).
**0 secret-scanning alerts.**  **0 malware alerts.**

### CodeQL (35 alerts)

| Count | Rule | Severity | Initial cluster |
|---|---|---|---|
| 19 | `py/polynomial-redos` | high | B — pattern verify |
| 7 | `py/clear-text-logging-sensitive-data` | high | A — attack surface |
| 3 | `actions/missing-workflow-permissions` | medium | C — workflow security |
| 2 | `py/paramiko-missing-host-key-validation` | high | B — pattern verify |
| 2 | `py/xml-bomb` | high | A — attack surface |
| 1 | `js/xss-through-dom` | high | A — attack surface |
| 1 | `py/incomplete-url-substring-sanitization` | high | A — attack surface |

### zizmor (44 alerts)

| Count | Rule | Severity | Initial cluster |
|---|---|---|---|
| 26 | `zizmor/unpinned-uses` | error | B — pattern verify |
| 6 | `zizmor/artipacked` | note | C — workflow security |
| 4 | `zizmor/excessive-permissions` | warning | C — workflow security |
| 3 | `zizmor/dependabot-cooldown` | warning | C — workflow security |
| 2 | `zizmor/cache-poisoning` | error | A — attack surface |
| 2 | `zizmor/template-injection` | error | D — already identified |
| 1 | `zizmor/superfluous-actions` | note | C — workflow security |

## Cluster summary

| Cluster | Alert count | Investigation needed |
|---|---|---|
| A — real attack surface | 13 | YES — Stage 1 agent A |
| B — pattern verification | 47 | YES — Stage 1 agent B |
| C — workflow security | 17 | YES — Stage 1 agent C |
| D — already identified | 2 | NO — fix in Stage 2 |
| **Total** | **79** | |

Raw machine-readable inventory: `alerts-raw.json`.
Per-cluster inputs for Stage 1 agents: `cluster-*.json`.

## User-set policy for this run

* **Severity scope:** fix all REAL HIGH + MEDIUM; dismiss-with-reason
  for NOISE / BY-DESIGN
* **`zizmor/unpinned-uses` × 26:** hybrid policy — SHA-pin third
  parties (`zizmorcore/zizmor-action`, `aquasecurity/trivy-action`),
  allow tag-pin for `actions/*` and `github/*` via zizmor config.
  Means the 24 first-party findings dismiss as accepted-risk; the
  2 third-party ones become real SHA-pin fixes.
* **Dismissal execution:** orchestrator applies dismissals via
  `gh api` after Stage 1 verdicts land in this folder.

## Stage 1 dispatch

3 read-only `general-purpose` agents in parallel, no worktree
isolation.  Each receives its cluster's JSON and writes to
`01-investigation-{A,B,C}.md`.  Outputs feed `99-synthesis.md`
written by orchestrator post-merge.
