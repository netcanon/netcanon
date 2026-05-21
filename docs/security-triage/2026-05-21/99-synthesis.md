# 2026-05-21 — Synthesis

Consolidated verdict across the 79 open code-scanning alerts plus the
2 cluster-D template-injection alerts already-identified by the
orchestrator pre-Stage-1.  Reconciled from
[`01-investigation-A.md`](01-investigation-A.md),
[`01-investigation-B.md`](01-investigation-B.md), and
[`01-investigation-C.md`](01-investigation-C.md).

## Tally

```
                       REAL   DISMISS    notes
Cluster A (13)            4         9    2 HIGH (XXE) + 2 LOW (cache); 7 false-positive logging + 1 test assertion + 1 escaped innerHTML
Cluster B (47)           11        36    All 11 REAL are third-party SHA pins; 19 redos + 2 paramiko + 15 first-party all by-design
Cluster C (17)           16         1    1 ci.yml block clears 7; remaining 9 surgical; 1 DISMISS (action-gh-release worth keeping)
Cluster D ( 2)            2         0    Both template-injection findings real (desktop-msi-publish.yml:84 dual)
                       ----     ----
                         33        46    Total 79 = matches snapshot count
```

## REAL findings — grouped for Stage 2 fix dispatch

### Group I — `defusedxml` swap (closes 2 alerts, HIGH)

| Alert | File | Fix |
|---|---|---|
| #14 | `netcanon/migration/codecs/cisco_iosxe/codec.py:543` | `import xml.etree.ElementTree as ET` → `import defusedxml.ElementTree as ET` (single-line import swap; call-site shape preserved) |
| #15 | `netcanon/migration/codecs/opnsense/parse.py:169` | Same import swap |

Plus: add `defusedxml>=0.7.1` to `pyproject.toml` `[project] dependencies`.

Verified upstream:
* Only 3 stdlib-ET import sites in `netcanon/` (Grep across the tree)
* The 3rd site is `opnsense/render.py` — only *generates* XML output, never parses input. Out of scope (render is safe by definition).
* `defusedxml.ElementTree.fromstring` is an exact API drop-in for these 2 call sites — no signature change.
* Doc-sync row applies: `SECURITY.md` Supply-Chain Integrity section references the codec parsing surface; threat-model line for operator-uploaded XML needs to surface the entity-bomb mitigation.

### Group II — `ci.yml` workflow-level permissions (closes 7 alerts, MEDIUM × 3 + WARNING × 4)

| Alert | Rule | Notes |
|---|---|---|
| #1, #2, #3 | `actions/missing-workflow-permissions` (MEDIUM) | All 3 anchor in ci.yml (test, build-distribution, docker-build-smoke jobs) |
| #42, #43, #44, #45 | `zizmor/excessive-permissions` (WARNING) | Same root cause; job-level reports because the workflow itself has no permissions declaration |

**Single edit** — insert between `env:` (line 17) and `jobs:` (line 19):

```yaml
permissions:
  contents: read
```

All 3 jobs in ci.yml are read-only (pytest, build-sdist+wheel, docker-build-smoke).  No per-job override needed; child jobs inherit.

### Group III — `persist-credentials: false` on remaining checkouts (closes 6 alerts, NOTE)

| Alert | File:Line | `with:` block status |
|---|---|---|
| #39 | `ci.yml:29` (test) | Has `fetch-depth: 0` — add sibling key |
| #40 | `ci.yml:59` (build-distribution) | Has `fetch-depth: 0` — add sibling key |
| #41 | `ci.yml:93` (docker-build-smoke) | Has `fetch-depth: 0` — add sibling key |
| #60 | `docker-publish.yml:36` | No `with:` block — create one |
| #71 | `pypi-publish.yml:26` | Has `fetch-depth: 0` — add sibling key |
| #51 | `desktop-msi-publish.yml:63` | Has `ref:` + `fetch-depth: 0` — add sibling key |

`zizmor.yml:48` already uses this pattern (orchestrator's pre-existing model).  No workflow has a downstream git-push step that needs persisted creds.

### Group IV — `dependabot.yml` cooldown blocks (closes 3 alerts, WARNING)

| Alert | Ecosystem | Cooldown value |
|---|---|---|
| #36 | pip | `default-days: 7` |
| #37 | github-actions | `default-days: 3` |
| #38 | docker | `default-days: 7` |

Position: after `schedule:` block, before `open-pull-requests-limit:` for natural read-order.

### Group V — `desktop-msi-publish.yml:84` template-injection (closes 2 alerts, ERROR — cluster D)

Replace the inline template expansion with an env-var assignment.

Current (vulnerable):

```yaml
- name: Compute MSI version from tag
  shell: bash
  run: |
    tag="${{ inputs.tag || github.ref_name }}"
    ...
```

Replacement:

```yaml
- name: Compute MSI version from tag
  shell: bash
  env:
    TAG_RAW: ${{ inputs.tag || github.ref_name }}
  run: |
    tag="${TAG_RAW#v}"
    msi_version="${tag%%-*}"
    echo "NETCANON_MSI_VERSION=$msi_version" >> "$GITHUB_ENV"
    echo "Building MSI with ProductVersion: $msi_version (source tag: $tag)"
```

The env-var carries the value into shell context as a literal — no template expansion in the shell phase, so injection via tag-name metacharacters is impossible.  Both flagged columns (`:20` and `:34`) clear from this single block.

### Group VI — Drop `cache: "pip"` from single-shot publish workflows (closes 2 alerts, LOW)

| Alert | File:Line | Edit |
|---|---|---|
| #77 | `pypi-publish.yml:35` (`cache: "pip"`) | Delete line |
| #58 | `desktop-msi-publish.yml:74` (`cache: "pip"`) | Delete line |

Both jobs run once per release with a cold dep tree.  Cache buys nothing; deleting is strictly cheaper than dismissal-with-justification.  Compensating-control note (OIDC TP + Trivy) recorded in commit message rather than as a dismissal comment.

### Group VII — SHA-pin third-party actions (closes 11 alerts, ERROR)

Mechanical swap; convention is to keep the human-readable tag as a trailing comment so Dependabot can still propose bumps:

```yaml
- uses: <publisher>/<action>@<full-sha>  # <original-tag>
```

| Alert | File:Line | Replacement |
|---|---|---|
| #57 | `desktop-msi-publish.yml:139` | `softprops/action-gh-release@b4309332981a82ec1c5618f44dd2e27cc8bfbfda  # v3` |
| #62 | `docker-publish.yml:39` | `docker/setup-buildx-action@4d04d5d9486b7bd6fa91e7baf45bbb4f8b9deedd  # v4` |
| #63 | `docker-publish.yml:42` | `docker/login-action@4907a6ddec9925e35a0a9e82d7399ccc52663121  # v4` |
| #64 | `docker-publish.yml:49` | `docker/login-action@4907a6ddec9925e35a0a9e82d7399ccc52663121  # v4` |
| #65 | `docker-publish.yml:56` | `docker/metadata-action@030e881283bb7a6894de51c315a6bfe6a94e05cf  # v6` |
| #66 | `docker-publish.yml:86` | `docker/build-push-action@bcafcacb16a39f128d818304e6c9c0c18556b85f  # v7` |
| #80 | `docker-publish.yml:127` | `aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25  # v0.36.0` |
| #69 | `docker-publish.yml:144` | `sigstore/cosign-installer@398d4b0eeef1380460a10c8013a76f728fb906ac  # v3` |
| #70 | `docker-publish.yml:169` | `anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610  # v0` |
| #76 | `pypi-publish.yml:79` | `pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b  # release/v1` |
| #79 | `zizmor.yml:55` | `zizmorcore/zizmor-action@5f14fd08f7cf1cb1609c1e344975f152c7ee938d  # v0.5.6` |

Note: `pypa/gh-action-pypi-publish@release/v1` was a *branch* ref before pinning.  Stage 2 awareness: Dependabot's tag-tracking won't propose bumps automatically for branch-pinned actions; future updates may need manual SHA refresh.

### Group VIII — `.github/zizmor.yml` config (no alerts directly; enables clean dismissals)

The 15 first-party `unpinned-uses` alerts dismiss as accepted-risk per hybrid policy.  Without a config change, zizmor will re-fire all 15 on the next scan.  Add a config file that suppresses the rule on `actions/*` + `github/*` publishers:

```yaml
# .github/zizmor.yml
rules:
  unpinned-uses:
    config:
      policies:
        "actions/*": ref-pin
        "github/*": ref-pin
        "*": hash-pin
```

`ref-pin` permits tag pins (`@v6`); `hash-pin` requires full SHAs.  Documents the policy in version control + prevents alert re-noise.

## DISMISS findings — bulk dismissal taxonomy

46 dismissals across 5 dismissal-comment classes.  Full payload in `dismissals.json`.

### Class 1: parse/render closing-summary logger.debug (7 alerts, `false positive`)

Alerts #5, #6, #7, #8, #9, #10, #11.  All variants of the same idiom — `logger.debug("<codec> parsed: hostname=%r ifaces=%d ... (input=%d chars)", intent.hostname, len(...), ...)`.  CodeQL flow-tracker sees the `intent` container being passed to a logger and flags because the container also holds password fields elsewhere, but the formatter only consumes `.hostname` and `len(...)` counts.

Comment template:

> Closing-summary log statement at end of codec parse/render.  Formatter only consumes `.hostname` (a single string) and `len(...)` counts of canonical-list fields.  No credential value reaches the logger; CodeQL flow-tracker flags because the `intent` container also holds password fields, but the dataflow at this call site only reads `.hostname` and `len()`.

### Class 2: pytest assertion misread as URL routing (1 alert, `used in tests`)

Alert #16.  Line is `assert "pool.ntp.org" in intent.ntp_servers` — list-membership check in a unit test, not a URL trust gate.

Comment:

> pytest assertion verifying parsed canonical NTP-server list membership; not a URL trust check.  The `in` operator is list-membership semantics, not URL substring sanitisation.

### Class 3: escaped innerHTML with server-trusted data source (1 alert, `false positive`)

Alert #4.  Every interpolation in `renderBucket()` goes through `escapeHtml()`; data source is compiled-in `CapabilityMatrix`, not operator input.

Comment:

> Every interpolation in renderBucket() (lines 815, 824, 832, 834-836) goes through the local escapeHtml() helper (lines 843-848) which HTML-encodes <>&"'.  Data source is the server-side compiled CapabilityMatrix, not operator-supplied input.

### Class 4: codec grammar regex with bounded input (19 alerts, `won't fix`)

Alerts #17 through #35 (full list in dismissals.json).  All in codec `parse.py` files; polynomial-not-exponential regex shapes; per-line input boundedness via `splitlines()`; 50 MB cap on file uploads via `MAX_CONFIG_SIZE`.

Comment template:

> Codec grammar regex in `<file>:<line>`.  Polynomial-not-exponential pattern shape (no nested quantifiers compounding) applied per-line via `splitlines()`.  File-upload path bounded at 50 MB by `MAX_CONFIG_SIZE` in `netcanon/storage/file_store.py:133`.  Polynomial backtracking is theoretical but not exploitable — no unbounded input path reaches this regex.

### Class 5: operator-driven SSH AutoAddPolicy (2 alerts, `won't fix`)

Alerts #12, #13.  Both in `paramiko_collector.py` — operator types device IP, netcanon SSHes there; operator is trust anchor.

Comment:

> Operator-initiated SSH to ad-hoc network device IPs from `DeviceTarget.host`.  AutoAddPolicy is the documented netmiko/paramiko default for operator tooling.  Threat model: the human operator is the trust anchor (same posture as `ssh root@10.0.0.1` from terminal), not a service identity with a pre-known fingerprint.

### Class 6: first-party action tag pin (15 alerts, `won't fix`)

Alerts #46, #47, #48, #49, #50, #54, #55, #56, #61, #68, #72, #73, #74, #75, #78.  `actions/*` and `github/*` publishers per hybrid policy.

Comment template:

> Accepted-risk per netcanon's hybrid action-pinning policy (2026-05-21 triage): tag-pin allowed for `actions/*` and `github/*` first-party publishers because GitHub controls the repos and force-push protections apply.  SHA pinning reserved for third-party publishers where compromise risk is materially higher.  Suppression configured in `.github/zizmor.yml` to prevent re-noise on subsequent scans.

### Class 7: superfluous-actions worth keeping (1 alert, `won't fix`)

Alert #59.  `softprops/action-gh-release@v3` provides 4 features `gh release` doesn't (auto-create-if-missing, generate_release_notes, structured prerelease, fail_on_unmatched_files).

Comment:

> softprops/action-gh-release@v3 provides four features that `gh release` does not give for free: auto-create-if-missing release page (handles backfill via workflow_dispatch on tags pushed before this workflow existed), generate_release_notes: true (auto-population from PR/commit changelog), structured prerelease: detection (computed from -rc/-alpha/-beta substring match), fail_on_unmatched_files: true (hard error if dist/*.msi glob is empty).  Replacing with bare gh release commands requires reimplementing all four with idempotent create-or-append edge-case handling; net security gain is negligible.

## Stage 2 dispatch shape

All Stage 2 work is mechanical (one-line edits / SHA swaps / config additions across 7 files + 2 codec files + 1 new file).  Orchestrator-direct execution is appropriate; no implementation agents needed.  Test-suite verification after the defusedxml swap warrants a single `py -m pytest` run.

**Proposed commit cadence (7 commits):**

1. `fix(security): switch XML parsing to defusedxml (XXE bomb mitigation)` — Group I.  2 codecs + dep add.  Closes #14, #15.
2. `ci(security): add workflow-level permissions block to ci.yml` — Group II.  Single edit.  Closes #1, #2, #3, #42, #43, #44, #45.
3. `ci(security): set persist-credentials: false on actions/checkout` — Group III.  Touches 4 workflow files.  Closes #39, #40, #41, #51, #60, #71.
4. `ci(security): SHA-pin third-party actions (hybrid policy)` — Group VII + Group VIII config.  Touches 4 workflow files + new `.github/zizmor.yml`.  Closes #57, #62, #63, #64, #65, #66, #69, #70, #76, #79, #80 (11 alerts) + enables clean dismissals on the 15 first-party DISMISS class.
5. `fix(security): template-injection in desktop-msi-publish.yml via env-var` — Group V.  Closes #52, #53 (both columns of the cluster-D template-injection finding on line 84).
6. `ci(security): drop cache: pip from single-shot publish workflows` — Group VI.  Closes #58, #77.
7. `ci(security): add Dependabot cooldown blocks` — Group IV.  Closes #36, #37, #38.

Sequencing: commits 1-3 + 5-7 can land in any order (file-disjoint).  Commit 4 depends on commit 3 (also touches workflow files); recommend serial 3 → 4 to avoid merge conflicts.

## Verification post-fixes

* `py -m pytest tests/unit/migration --tb=no -p no:cacheprovider` after the defusedxml swap (commit 1).  Codec round-trip tests for OPNsense + Cisco IOS-XE will exercise the new parser; failure here would mean defusedxml rejects valid input.
* CI passes on push.
* Re-scan after push: zizmor + CodeQL re-fire on workflow file changes; expect open-alert count to drop from 79 → 79 − 33 (REAL fixed) − 46 (dismissed) = 0.  Some lag for the re-scan to complete + dismissals to propagate to the UI.

## See also

* [`README.md`](../README.md) — the triage process
* [`00-snapshot.md`](00-snapshot.md) — initial alert inventory + cluster mapping
* [`dismissals.json`](dismissals.json) — batch payload for `gh api`
* [`fix-plan.md`](fix-plan.md) — Stage 2 work breakdown (groups → commits → verification)
