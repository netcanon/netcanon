# Stage 2 — Fix execution plan

33 REAL alerts to close.  Total scope: 7 workflow files + 2 codec
files + 1 dep change + 1 new config file.  All fixes are mechanical
(import swaps, YAML key additions, SHA pin substitutions).  **No
implementation agents needed** — orchestrator-direct execution is
faster than the dispatch overhead.

Detailed evidence and rationale live in
[`99-synthesis.md`](99-synthesis.md); this file is the execution
checklist.

## Commit sequence (7 commits, file-disjoint except where noted)

### ☐ Commit 1 — `fix(security): switch XML parsing to defusedxml`

Closes alerts: **#14, #15** (HIGH)

| File | Edit |
|---|---|
| `pyproject.toml` | Add `defusedxml>=0.7.1` to `[project] dependencies` list |
| `netcanon/migration/codecs/cisco_iosxe/codec.py:543` | `import xml.etree.ElementTree as ET` → `import defusedxml.ElementTree as ET` (verify exact import line; ET. references at call site remain) |
| `netcanon/migration/codecs/opnsense/parse.py:169` | Same import swap |

Verify: `py -m pytest tests/unit/migration --tb=no -p no:cacheprovider` — codec round-trip tests exercise both parsers.

Doc-sync: `SECURITY.md` Supply-Chain Integrity section — note operator-uploaded-XML threat-model now mitigated against entity-bomb DoS.

### ☐ Commit 2 — `ci(security): add workflow-level permissions to ci.yml`

Closes alerts: **#1, #2, #3, #42, #43, #44, #45** (3 medium + 4 warning)

| File | Edit |
|---|---|
| `.github/workflows/ci.yml` between line 17 (`env:` close) and line 19 (`jobs:`) | Insert `permissions:\n  contents: read\n\n` block |

Verify: `py -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`.

### ☐ Commit 3 — `ci(security): persist-credentials false on remaining checkouts`

Closes alerts: **#39, #40, #41, #51, #60, #71** (6 note)

| File:Line | Edit |
|---|---|
| `ci.yml:29` (test job) | Add `persist-credentials: false` to existing `with:` block |
| `ci.yml:59` (build-distribution) | Same |
| `ci.yml:93` (docker-build-smoke) | Same |
| `docker-publish.yml:36` | Create new `with:` block (currently bare `- uses:`) containing `persist-credentials: false` |
| `pypi-publish.yml:26` | Add to existing `with:` |
| `desktop-msi-publish.yml:63` | Add to existing `with:` |

Reference pattern: `zizmor.yml:48` already uses this.

### ☐ Commit 4 — `ci(security): SHA-pin third-party actions + zizmor first-party allowlist`

Closes alerts: **#57, #62, #63, #64, #65, #66, #69, #70, #76, #79, #80** (11 errors).
Plus enables clean re-scan for the 15 already-dismissed first-party uses.

Substitutions (preserve human-readable tag as trailing comment):

| File:Line | From | To |
|---|---|---|
| `desktop-msi-publish.yml:139` | `softprops/action-gh-release@v3` | `softprops/action-gh-release@b4309332981a82ec1c5618f44dd2e27cc8bfbfda  # v3` |
| `docker-publish.yml:39` | `docker/setup-buildx-action@v4` | `docker/setup-buildx-action@4d04d5d9486b7bd6fa91e7baf45bbb4f8b9deedd  # v4` |
| `docker-publish.yml:42` | `docker/login-action@v4` | `docker/login-action@4907a6ddec9925e35a0a9e82d7399ccc52663121  # v4` |
| `docker-publish.yml:49` | `docker/login-action@v4` | `docker/login-action@4907a6ddec9925e35a0a9e82d7399ccc52663121  # v4` |
| `docker-publish.yml:56` | `docker/metadata-action@v6` | `docker/metadata-action@030e881283bb7a6894de51c315a6bfe6a94e05cf  # v6` |
| `docker-publish.yml:86` | `docker/build-push-action@v7` | `docker/build-push-action@bcafcacb16a39f128d818304e6c9c0c18556b85f  # v7` |
| `docker-publish.yml:127` | `aquasecurity/trivy-action@v0.36.0` | `aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25  # v0.36.0` |
| `docker-publish.yml:144` | `sigstore/cosign-installer@v3` | `sigstore/cosign-installer@398d4b0eeef1380460a10c8013a76f728fb906ac  # v3` |
| `docker-publish.yml:169` | `anchore/sbom-action@v0` | `anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610  # v0` |
| `pypi-publish.yml:79` | `pypa/gh-action-pypi-publish@release/v1` | `pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b  # release/v1` |
| `zizmor.yml:55` | `zizmorcore/zizmor-action@v0.5.6` | `zizmorcore/zizmor-action@5f14fd08f7cf1cb1609c1e344975f152c7ee938d  # v0.5.6` |

Plus new file `.github/zizmor.yml` (suppression config for first-party-action accepted-risk):

```yaml
# Site-wide zizmor config — netcanon hybrid action-pinning policy.
# See docs/security-triage/2026-05-21/99-synthesis.md for the
# decision context.  This file is read by zizmor before scanning.

rules:
  unpinned-uses:
    config:
      policies:
        "actions/*": ref-pin     # GitHub-owned, force-push protected
        "github/*": ref-pin      # GitHub-owned
        "*": hash-pin            # third-party publishers: SHA required
```

Note: depends on commit 3 (also touches workflow files); execute serial 3 → 4 to avoid line-number drift mid-edit.

Awareness flag: `pypa/gh-action-pypi-publish@release/v1` was a branch ref before pinning.  Dependabot's tag-tracking will not propose bumps for branch-pinned actions; manual SHA refresh required in the future.

### ☐ Commit 5 — `fix(security): template-injection in desktop-msi-publish.yml via env-var`

Closes alerts: **#52, #53** (2 errors)

Replace the inline `${{ inputs.tag || github.ref_name }}` expansion in `run:` with an `env:`-mediated assignment:

```yaml
# desktop-msi-publish.yml around line 79-91
- name: Compute MSI version from tag
  shell: bash
  env:
    TAG_RAW: ${{ inputs.tag || github.ref_name }}
  run: |
    # On workflow_dispatch the tag is inputs.tag.  On tag-push it's
    # github.ref_name (the tag name without the refs/tags/ prefix).
    # TAG_RAW carries the value into shell context as a literal
    # env-var, eliminating template-expansion injection class via
    # tag-name metacharacters (zizmor template-injection #52, #53).
    tag="${TAG_RAW#v}"          # e.g. 0.1.0-rc7
    msi_version="${tag%%-*}"    # e.g. 0.1.0
    echo "NETCANON_MSI_VERSION=$msi_version" >> "$GITHUB_ENV"
    echo "Building MSI with ProductVersion: $msi_version (source tag: $tag)"
```

### ☐ Commit 6 — `ci(security): drop pip cache from single-shot publish workflows`

Closes alerts: **#58, #77** (2 low)

| File:Line | Edit |
|---|---|
| `pypi-publish.yml:35` | Delete the `cache: "pip"` line under `actions/setup-python@v6` |
| `desktop-msi-publish.yml:74` | Same — delete `cache: "pip"` |

Rationale: both jobs run once per release with a cold dep tree; cache buys nothing.  Removing also removes a real attack surface independent of severity grade.

### ☐ Commit 7 — `ci(security): add Dependabot cooldown blocks`

Closes alerts: **#36, #37, #38** (3 warning)

Single file: `.github/dependabot.yml`.  Add `cooldown: { default-days: N }` after each ecosystem's `schedule:` block:

| Ecosystem | Cooldown |
|---|---|
| `pip` | `default-days: 7` |
| `github-actions` | `default-days: 3` |
| `docker` | `default-days: 7` |

## Total alert closure

```
33 REAL closed across 7 commits:
  Commit 1  →  2 closed  (HIGH)
  Commit 2  →  7 closed  (medium + warning)
  Commit 3  →  6 closed  (note)
  Commit 4  → 11 closed  (error)
  Commit 5  →  2 closed  (error)
  Commit 6  →  2 closed  (low)
  Commit 7  →  3 closed  (warning)
            ----
              33 closed  ✓
```

Already dismissed (in Task 6): **46**.

After Stage 2: expected open-alert count = **0** (pending re-scan latency).

## Post-execution

After commit 7 lands:
* `py -m pytest tests/unit/migration --tb=no -p no:cacheprovider` (already done after commit 1; confirm still green)
* Push all commits
* Watch Actions tab for CodeQL + zizmor re-scans
* Re-query: `gh api "repos/netcanon/netcanon/code-scanning/alerts?per_page=100&state=open" --jq 'length'` should report 0 (modulo scanner-cooldown latency)
* Commit the `docs/security-triage/2026-05-21/` evidence folder in a final commit (`docs(security): 2026-05-21 triage evidence trail`)

## Awareness items captured for next triage

* **`dismissed_comment` 280-char limit** — recorded in [`README.md`](../README.md) Stage 2 section.
* **`MigrationPlanRequest.raw_text` has no Pydantic `max_length`** — defence-in-depth hardening item (not a Stage 1 blocker, would belong in a future Cluster A scan).
* **Branch-ref pin on `pypa/gh-action-pypi-publish`** — Dependabot won't auto-bump; manual SHA refresh required.
* **`MAX_CONFIG_SIZE` is the canonical upload-size cap** at `netcanon/storage/file_store.py:133`; useful boundedness anchor for future regex-DoS dismissals.
