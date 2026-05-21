# Cluster C — workflow security investigation

## Summary

All 17 alerts are REAL, fixable defence-in-depth gaps with the exception of one
DISMISS (`zizmor/superfluous-actions` on `softprops/action-gh-release`, which
provides materially more functionality than the runner-bundled `gh release`).
Headline finding: a single top-level `permissions: contents: read` block on
`.github/workflows/ci.yml` clears 7 of the 17 alerts (all 3 CodeQL
`actions/missing-workflow-permissions` + all 4 `zizmor/excessive-permissions`)
in one edit; the remaining 9 REAL alerts are 6 `persist-credentials: false`
additions on `actions/checkout` calls and 3 `cooldown:` blocks in
`.github/dependabot.yml`.

## Per-alert verdicts

| Alert # | Rule | File:Line | Verdict | Severity | Fix shape (REAL) or reason (DISMISS) |
|---|---|---|---|---|---|
| 1 | actions/missing-workflow-permissions | ci.yml:21 | REAL | medium | Cleared by adding top-level `permissions: contents: read` to ci.yml (Group 1). CodeQL anchors at job `name:` line; fix is at workflow scope. |
| 2 | actions/missing-workflow-permissions | ci.yml:55 | REAL | medium | Cleared by Group 1 (same workflow-level fix). |
| 3 | actions/missing-workflow-permissions | ci.yml:85 | REAL | medium | Cleared by Group 1 (same workflow-level fix). |
| 42 | zizmor/excessive-permissions | ci.yml:1 | REAL | warning | Cleared by Group 1 — workflow-level `permissions: contents: read`. |
| 43 | zizmor/excessive-permissions | ci.yml:20 (`test` job) | REAL | warning | Cleared by Group 1 — child jobs inherit workflow-level perms once declared. |
| 44 | zizmor/excessive-permissions | ci.yml:54 (`build-distribution` job) | REAL | warning | Cleared by Group 1. |
| 45 | zizmor/excessive-permissions | ci.yml:84 (`docker-build-smoke` job) | REAL | warning | Cleared by Group 1. |
| 39 | zizmor/artipacked | ci.yml:29 (`test` checkout) | REAL | note | Add `persist-credentials: false` to the existing `with:` block under `actions/checkout@v6`. Job is read-only (runs pytest); no subsequent step needs the token. |
| 40 | zizmor/artipacked | ci.yml:59 (`build-distribution` checkout) | REAL | note | Add `persist-credentials: false` to the existing `with:` block. Job builds sdist + wheel; no git push. |
| 41 | zizmor/artipacked | ci.yml:93 (`docker-build-smoke` checkout) | REAL | note | Add `persist-credentials: false` to the existing `with:` block. Job builds + smoke-tests the Docker image; no git push. |
| 60 | zizmor/artipacked | docker-publish.yml:36 | REAL | note | `actions/checkout@v6` currently has no `with:` block — add one with `persist-credentials: false`. Subsequent steps log into GHCR via `secrets.GITHUB_TOKEN` directly (not via persisted git creds); cosign + Trivy don't need the git credential helper. |
| 71 | zizmor/artipacked | pypi-publish.yml:26 | REAL | note | Add `persist-credentials: false` to the existing `with:` block under `actions/checkout@v6`. Build job only runs `python -m build` + `twine check`; publish-pypi job uses OIDC, not git push. |
| 51 | zizmor/artipacked | desktop-msi-publish.yml:63 | REAL | note | Add `persist-credentials: false` to the existing `with:` block under `actions/checkout@v6`. The `softprops/action-gh-release` step downstream uses the GITHUB_TOKEN from the env it sees, not from `.git/config`, so dropping persisted creds is safe. |
| 36 | zizmor/dependabot-cooldown | dependabot.yml:10 (pip ecosystem) | REAL | warning | Add `cooldown: { default-days: 7 }` under the pip entry. 7 days lets upstream yank cases / hotfixes settle (per cluster brief). |
| 37 | zizmor/dependabot-cooldown | dependabot.yml:24 (github-actions ecosystem) | REAL | warning | Add `cooldown: { default-days: 3 }` under the github-actions entry. Actions release less often; shorter cooldown is fine. |
| 38 | zizmor/dependabot-cooldown | dependabot.yml:38 (docker ecosystem) | REAL | warning | Add `cooldown: { default-days: 7 }` under the docker entry. Base-image stability. |
| 59 | zizmor/superfluous-actions | desktop-msi-publish.yml:139 | DISMISS | note | `softprops/action-gh-release@v3` is replaceable by `gh release create/upload` in principle, but the action provides four features the runner-bundled `gh` does not give for free: auto-create-if-missing release page, `generate_release_notes: true`, structured `prerelease:` flag computation, and `fail_on_unmatched_files: true`. Replacing with shell would require reimplementing all four with idempotent create-or-append edge-case handling. Net security gain is negligible (the action is third-party but widely-used, well-maintained, and SHA-pinnable independently); cost of swap is non-trivial. Won't fix. |

## Fix groupings (for Stage 2 dispatch)

### Group 1 — ci.yml workflow-wide permissions block (clears 7 alerts: #1, #2, #3, #42, #43, #44, #45)

**Single edit at `.github/workflows/ci.yml` between lines 17 and 19** — insert a
top-level `permissions:` block immediately after the `env:` block and before
`jobs:`:

```yaml
# (after env: ... FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true')

permissions:
  contents: read

jobs:
  test:
    ...
```

Rationale: all three ci.yml jobs (test, build-distribution, docker-build-smoke)
are read-only — they run pytest, build sdist/wheel artefacts that stay on the
runner, and build+boot a local Docker image. None push to a registry, write
to the repo, upload artifacts to a release, or call any API requiring
`packages: write` / `contents: write` / etc. `contents: read` is sufficient.

Once declared at workflow level, all child jobs inherit. zizmor's
`excessive-permissions` and CodeQL's `actions/missing-workflow-permissions` both
resolve from this single block (the job-level zizmor anchors at #43/#44/#45 fire
because the workflow itself has no permissions declaration; declaring it removes
the "default permissions used" framing for the inherited case). No per-job
`permissions:` overrides are needed.

### Group 2 — `persist-credentials: false` across all checkout calls (clears 6 alerts: #39, #40, #41, #51, #60, #71)

Add `persist-credentials: false` under the `with:` block of every
`actions/checkout@v6` call:

* **`.github/workflows/ci.yml:29-35`** — `test` job. Existing `with:` block has
  `fetch-depth: 0`; add `persist-credentials: false` as a sibling key.
* **`.github/workflows/ci.yml:59-65`** — `build-distribution` job. Same shape.
* **`.github/workflows/ci.yml:93-99`** — `docker-build-smoke` job. Same shape.
* **`.github/workflows/docker-publish.yml:36`** — Currently `- uses: actions/checkout@v6` with no `with:` block. Add a `with:` block containing just `persist-credentials: false`.
* **`.github/workflows/pypi-publish.yml:26-32`** — `build` job. Existing `with:` has `fetch-depth: 0`; add `persist-credentials: false`.
* **`.github/workflows/desktop-msi-publish.yml:63-71`** — `build-msi` job. Existing `with:` has `ref:` + `fetch-depth: 0`; add `persist-credentials: false`.

Rationale: zizmor.yml already sets this pattern at line 48 (model template).
Across all 6 remaining call sites, no subsequent step pushes to the repo via
git — registry logins use explicit token secrets, OIDC, or action-internal
auth; release uploads use the action's own GITHUB_TOKEN handling. Disabling
credential persistence is risk-free and recommended-default for repos with no
git-push steps.

### Group 3 — `cooldown:` blocks in dependabot.yml (clears 3 alerts: #36, #37, #38)

Single-file edit at `.github/dependabot.yml`. Insert a `cooldown:` block under
each of the three `updates:` entries. Recommended values per the cluster brief:

```yaml
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    cooldown:
      default-days: 7
    open-pull-requests-limit: 5
    ...

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    cooldown:
      default-days: 3
    open-pull-requests-limit: 3
    ...

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "monthly"
    cooldown:
      default-days: 7
    open-pull-requests-limit: 2
    ...
```

Position within each entry is flexible (Dependabot accepts the key anywhere
under the ecosystem block) but placing it after `schedule:` keeps the file
read-flow chronological (when → cooldown → how many PRs → grouping → labels).

`default-days: N` is the minimal valid shape per Dependabot's option reference;
expand to per-severity (`semver-major-days` / `semver-minor-days` / `semver-patch-days`)
only if a more nuanced policy is needed later. The brief specified 7 / 3 / 7;
those are used directly here.

### Group 4 — DISMISS the superfluous-actions alert (clears 1 alert: #59)

No file edit. Pass-through to the orchestrator's `gh api PATCH /code-scanning/alerts/59`
call with:

* `dismissed_reason`: `won't fix`
* `dismissed_comment`: `softprops/action-gh-release@v3 provides four features that gh release does not give for free: auto-create-if-missing release page (handles backfill via workflow_dispatch on tags pushed before this workflow existed), generate_release_notes: true (auto-population of release notes from PR/commit changelog), structured prerelease: detection (currently computed from -rc / -alpha / -beta substring match in the tag name), and fail_on_unmatched_files: true (hard error if dist/*.msi glob is empty). Replacing with bare gh release create + gh release upload in a script step would require reimplementing all four with idempotent create-or-append edge-case handling. The third-party-action risk is mitigated by SHA-pinning (handled in cluster B's unpinned-uses policy decisions, not here). Net security gain of swap is negligible; cost is non-trivial. Accepted-risk: keep the action.`

## Per-rule notes

### actions/missing-workflow-permissions × 3

All three alerts (#1, #2, #3) are in **ci.yml only** — pypi-publish.yml,
docker-publish.yml, desktop-msi-publish.yml, and zizmor.yml all already have
top-level `permissions:` blocks (lines 41, 10, 41, 33 respectively).

The pattern to add to ci.yml is **default-deny via workflow-level declaration**:

```yaml
permissions:
  contents: read
```

Inserted after the `env:` block (line 17) and before `jobs:` (line 19).
No per-job override is needed — all three jobs are read-only.

This is the same shape pypi-publish.yml uses (line 10-11), modulo the absence
of any job that needs broader scope. (pypi-publish.yml's `publish-pypi` job
overrides to `id-token: write` for OIDC at line 68-69; ci.yml has no analog.)

### zizmor/excessive-permissions × 4

All four alerts (#42, #43, #44, #45) are in **ci.yml only**, anchored at:
* `#42` — workflow start (line 1)
* `#43` — `test` job (line 20)
* `#44` — `build-distribution` job (line 54)
* `#45` — `docker-build-smoke` job (line 84)

Same root cause as the CodeQL alerts above — no `permissions:` block anywhere
in the file. Cleared by the same Group 1 fix. zizmor reports per-job because
the rule walks every job and checks whether *effective* permissions are
restrictive; with no workflow-level declaration, every job inherits "default
write-all", so every job is individually flagged.

No per-job `permissions: {}` override is needed; workflow-level inheritance is
sufficient and is the pattern used by the other already-clean workflow files
in this repo (docker-publish.yml, pypi-publish.yml, zizmor.yml).

### zizmor/artipacked × 6

All six alerts are `actions/checkout@v6` calls that don't set
`persist-credentials: false`. The fix is mechanical: add the key to each
`with:` block. zizmor.yml already demonstrates the pattern at line 48
(orchestrator's pre-existing fix from the snapshot file).

| Alert | File:line | Existing `with:` | Edit |
|---|---|---|---|
| 39 | ci.yml:29 | has `fetch-depth: 0` | add sibling key |
| 40 | ci.yml:59 | has `fetch-depth: 0` | add sibling key |
| 41 | ci.yml:93 | has `fetch-depth: 0` | add sibling key |
| 60 | docker-publish.yml:36 | **no `with:` block** | create `with:` block with just the new key |
| 71 | pypi-publish.yml:26 | has `fetch-depth: 0` | add sibling key |
| 51 | desktop-msi-publish.yml:63 | has `ref:` + `fetch-depth: 0` | add sibling key |

Across all six call sites, **no downstream step performs a git push, git
fetch, git tag, or git config write that would need the persisted credential
helper.** Registry logins (GHCR, Docker Hub) use `secrets.GITHUB_TOKEN` or
explicit secrets passed directly to `docker/login-action`. cosign uses
keyless OIDC. PyPI uses Trusted Publishing OIDC. The MSI publish uses
`softprops/action-gh-release`'s internal GITHUB_TOKEN handling. None read
from `.git/config`.

### zizmor/dependabot-cooldown × 3

All three alerts in `.github/dependabot.yml`, one per ecosystem (pip:10,
github-actions:24, docker:38). Per Dependabot's options reference
(`cooldown` block), the minimal valid shape is:

```yaml
cooldown:
  default-days: N
```

For per-severity differentiation (optional, not required to clear the alerts):

```yaml
cooldown:
  default-days: 7
  semver-major-days: 14
  semver-minor-days: 7
  semver-patch-days: 3
```

The brief specified `default-days` of 7 / 3 / 7 for pip / github-actions /
docker respectively. Those are the values to use. No reason to expand to
per-severity for the first triage cycle; nuance can be tuned later if a CVE
slips through a 7-day window.

### zizmor/superfluous-actions × 1

DISMISS as **won't fix** (note severity, lowest tier). The flagged action
(`softprops/action-gh-release@v3` at desktop-msi-publish.yml:139) is being
used for four non-trivial features that `gh release create/upload` does not
provide for free:

1. **Auto-create-if-missing** release page — matters for `workflow_dispatch`
   backfill of tags pushed before this workflow existed (documented in the
   workflow header).
2. **`generate_release_notes: true`** — server-side population of release notes
   from PR / commit changelog. Bare `gh release create --generate-notes` exists
   but doesn't combine cleanly with "create-if-missing OR append-to-existing"
   idempotency.
3. **`prerelease:` flag** — driven by computed boolean from tag-name substring
   match. Bare `gh release` requires the flag as a CLI arg; computing in shell
   is fine but adds replicated logic.
4. **`fail_on_unmatched_files: true`** — fast-fail if `dist/*.msi` glob is
   empty. Bare `gh release upload` either silently succeeds with no files or
   errors with an unhelpful message; reimplementing the early-fail check in
   shell is doable but boilerplate.

Net: swap cost is non-trivial; security gain is negligible (third-party
action with active maintenance, SHA-pinnable independently if cluster B's
unpinned-uses policy applies). Dismiss with the comment in Group 4.
