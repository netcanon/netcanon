# Lens 07 — Build / Release / CI supply chain

**Summary:** The release pipeline is in strong shape overall (tag-only publish guards, on-main ancestry + CI-success re-verification, OIDC trusted publishing, SHA-pinned third-party actions, hash-locked Docker deps, publish-time test gates). Six real findings survive scrutiny: one MAJOR release-integrity bug (`:latest` moves onto pre-release Docker tags — historically demonstrated), one MEDIUM gate-bypass class in the PII guard's pattern, and four MINORs (publish gate omits the PII workflow; MSI dispatch lacks the PKG-5 non-tag guard its siblings have; MSI rc/final ProductVersion collision; MSI dependency closure unpinned). No workflow injection, no untrusted-event publish, no permissions over-grant found.

Target: main @ 8598d74 (v0.5.3). All paths repo-relative.

---

### F1. `:latest` moves onto pre-release tags on both registries (MAJOR, confirmed)

- **File:** `.github/workflows/docker-publish.yml:224` (the `type=raw,value=latest` line in the `docker/metadata-action` tags block, lines 206–224)
- **Failure scenario:** The workflow triggers on `v*.*.*-*` pre-release tags (line 7). In metadata-action, `type=raw,value=latest` has `enable` defaulting to `true` — it is emitted unconditionally, on every trigger. The two `type=semver` lines correctly suppress `{{major}}.{{minor}}` for prereleases, but raw entries have no prerelease awareness. So pushing e.g. `v0.6.0-rc1` publishes `0.6.0-rc1` **and moves `:latest`** — on GHCR *and* the Docker Hub mirror — onto the RC. `:latest` is the documented quickstart pull in README.md (lines 38, 177, 219) and SECURITY.md (line 126), so default consumers get pre-release code.
- **Evidence this is live, not theoretical:** commit `e809839` (2026-05-09) deliberately removed the old `enable={{is_default_branch}}` gate to make `:latest` exist at all (it never fired on tag refs), replacing it with the unconditional raw form — but overshot. Tags `v0.1.0-rc5`…`v0.1.0-rc9` (2026-05-09 → 2026-05-13) were pushed *after* that commit, so `:latest` demonstrably pointed at RCs for the tail of the 0.1.0 cycle. The workflow's own comment (lines 218–224) documents only the "must exist on release pushes" motivation, not the prerelease side-effect.
- **Fix:** gate the raw entry on a stable tag: `type=raw,value=latest,enable=${{ !contains(github.ref_name, '-') }}`. (Equivalently, drop the raw line and use `flavor: latest=auto` with the semver entries, which is prerelease-aware by design.)
- **Confidence:** confirmed (exact code + documented metadata-action semantics + git history showing the exposure window was actually exercised).

### F2. PII guard misses common encodings of the operator-path leak it exists to block (MEDIUM, confirmed)

- **File:** `.github/workflows/pii-guard.yml:52`
- **Failure scenario:** The recurrence guard greps tracked files with `git grep -nI -E '<email-pattern>|C:[\]Users'`. That matches only the single-backslash, exact-case form of the Windows user-profile path. The forms the original leak class actually shows up in are broader, and all of them pass the guard today:
  - forward-slash form — `C:[/]Users[/]<user>...` (pytest output, URLs, tool logs, many editors normalize to this),
  - doubled-backslash form — `C:` + `\\` + `Users` (JSON-encoded job records, Python `repr()`/tracebacks — verified the current pattern does **not** match it: the class consumes the first backslash, then requires `U` but finds the second backslash),
  - MSYS/Git-Bash form — `[/]c[/]Users[/]<user>...` (exactly what Bash-on-Windows tooling prints),
  - any case variant (`git grep -E` is case-sensitive; the email pattern likewise).
  A committed doc or fixture that pastes a traceback or JSON blob in one of these forms re-leaks the operator username publicly while the guard stays green — the precise incident class that forced the 2026-06 PII history rewrite and the (still-pending) GH-Support cache purge.
- **Precondition verified:** the tracked tree currently has **zero** occurrences of any variant (checked all four forms case-insensitively), so strengthening the pattern cannot break the build.
- **Fix:** make the grep case-insensitive and widen the path pattern, keeping the self-masking character-class trick, e.g. `git grep -nIi -E '<email-pattern>|c:[\/][\/]?users|[/]c[/]users'` (the `[\/][\/]?` class-pair covers backslash, forward-slash, and doubled-backslash forms in one branch). Keep the fail-closed exit-code handling as is.
- **Confidence:** confirmed (reproduced the non-match of each variant against the live pattern with `git grep` locally).

### F3. Publish-time gates re-verify `ci.yml` only — the PII guard has no publish-time equivalent (MINOR, confirmed)

- **Files:** `.github/workflows/pypi-publish.yml:127–151`, `.github/workflows/docker-publish.yml:129–153`, `.github/workflows/desktop-msi-publish.yml:140–164`
- **Failure scenario:** The T0-4 closure's stated property is that the publish gate "holds even if the merge gate was bypassed" (pypi-publish.yml lines 30–43), and its own comment lists PII among the ruleset-required checks. But the "Require CI success" step queries only `repos/$REPO/actions/workflows/ci.yml/runs` — `pii-guard.yml` is a separate workflow and is never checked, and the in-run `test` gate (unit+integration) doesn't include the grep either. An admin-bypassed merge (or a variant-encoded leak per F2) with a red/never-green PII guard on main still publishes to PyPI (effectively immutable — yanked files remain fetchable by hash), GHCR, Docker Hub, and the MSI release. Given this project already paid the full PII-remediation cost once, the one required check with no publish-time backstop is the PII one.
- **Fix:** cheapest: add a second `gh api` query in the same step asserting the latest `pii-guard.yml` push run for `$head_sha` concluded `success` (same poll loop, same fail-closed shape). Cleaner: move the two grep steps into `ci.yml` as a job — then the existing ci.yml-conclusion check covers it with zero extra code in the three publish workflows.
- **Confidence:** confirmed (exact code: the API path names `ci.yml` only, in all three workflows).

### F4. MSI workflow lacks the PKG-5 refuse-non-tag guard its two siblings have (MINOR, confirmed)

- **File:** `.github/workflows/desktop-msi-publish.yml` — `build-msi` job (checkout lines 107–118; release step lines 241–257). Compare `pypi-publish.yml:84–91` and `docker-publish.yml:93–100`, which both gained the guard in PR #288 (PKG-5).
- **Failure scenario:** On `workflow_dispatch`, `inputs.tag` is checked out and released without any verification that it names a *tag*. `actions/checkout` accepts a branch name. A maintainer who types a branch that (a) sits on main history (passes the ancestry + CI gates, which check the resolved commit) and (b) looks version-ish (e.g. a `v0.6.0-fix` branch — needed to survive the version computation at lines 192–196; a plain `main` dies later with a confusing cx_Freeze invalid-version error) gets: an MSI built from a mutable branch tip, then `softprops/action-gh-release` with `tag_name: v0.6.0-fix` **creates that tag at the repository default-branch HEAD** (documented `target_commitish` default — *not* the commit the MSI was built from) plus a release page. Result: a spurious `v*.*.*-*`-shaped tag, and a published artifact whose tag points at a different commit than its contents. (The new tag does not cascade into the other publish workflows — GITHUB_TOKEN-created refs don't trigger workflows — which caps the blast radius.)
- **Fix:** add a guard step after checkout, e.g. `git show-ref --verify --quiet "refs/tags/${TAG_RAW}" || { echo "::error::'${TAG_RAW}' is not a tag"; exit 1; }` with `TAG_RAW: ${{ inputs.tag || github.ref_name }}` passed via env (the `$GITHUB_REF`-prefix check used by the siblings doesn't transfer here, since checkout uses `inputs.tag`, not the dispatch ref).
- **Confidence:** confirmed (code read; action-gh-release `target_commitish` default is documented behavior).

### F5. MSI ProductVersion collision between rc and final of the same release (MINOR, plausible)

- **Files:** `.github/workflows/desktop-msi-publish.yml:195` (`msi_version="${tag%%-*}"`), `setup_desktop.py:47–48, 67` (constant `UPGRADE_CODE`)
- **Failure scenario:** Every pre-release of a version and its final collapse to the same MSI `ProductVersion` (e.g. `v0.6.0-rc1` and `v0.6.0` → `0.6.0`), under one constant UpgradeCode. Windows Installer's `FindRelatedProducts` excludes equal versions by default (and MSI ignores a 4th version field for upgrade detection, so the usual "encode the rc ordinal in field 4" trick does not help). A user who installed the rc MSI gets no clean upgrade path to the final: same-version install is either refused by the downgrade-prevention row or produces a second ARP entry writing into the same `[ProgramFilesFolder]\Netcanon` directory. This surface was actually shipped: rc1–rc9 MSIs and the 0.1.0 final all carried ProductVersion `0.1.0`.
- **Fix (pick one):** skip the MSI attach for prerelease tags (mirrors the F1 fix; RC testers can use the 30-day workflow artifact instead), or document uninstall-before-upgrading for rc users in the release notes template.
- **Confidence:** plausible (MSI same-version semantics reasoned, not reproduced — building an MSI in-review was out of scope; the version collapse itself is confirmed from code).

### F6. MSI dependency closure is unpinned — the audit-#5 lock covers Docker only (MINOR, confirmed as a design gap)

- **Files:** `.github/workflows/desktop-msi-publish.yml:199–210`, `pyproject.toml:109–117`, contrast `tools/gen_requirements_lock.sh` + `Dockerfile:51–53`
- **Failure scenario:** Audit e5b77d7 #5 ("no pinned/hash-locked dependency manifest for shipped artifacts") was closed with `requirements.lock` + `--require-hashes` — but only for the container. The MSI build runs `pip install -e ".[desktop-build]"` against live PyPI at release time, resolving pyproject *ranges* with no hashes, and cx_Freeze additionally auto-downloads the WiX toolset at build time (workflow comment, lines 208–209). The lock's own header states the rationale: "the lock constrains the *application* (the container), which is the thing finding #5 is about" — the MSI is equally an application artifact that freezes its entire dependency closure into a shipped binary. A malicious or broken dep release published inside the Dependabot 7-day cooldown window (which gates PRs, not live pip resolution) lands directly in the installer, and unlike the Docker image there is no Trivy scan of the result.
- **Fix:** generate a second, Windows/CPython-3.13-resolved constraints file for the `[desktop-build]` extra (the Linux lock can't be reused — PySide6/Pillow wheels differ per platform) and install with `-c`; pre-install a pinned WiX release on the runner instead of letting cx_Freeze fetch it.
- **Confidence:** confirmed (design gap read directly from the lock header's rationale vs. the MSI job; no reproduction needed).

---

## NITs (not counted as findings)

- **Release-train friction, fail-closed:** `ci.yml` uses `cancel-in-progress: true` keyed on `github.ref`, so a second merge to main cancels the release commit's CI run; the publish gates then (correctly) refuse, and the poll ceiling is 10 min (30×20s) which a cold full matrix can exceed. Consider `cancel-in-progress: ${{ github.event_name == 'pull_request' }}` and a slightly larger poll budget. Safe today — every failure mode is a refusal, not a bad publish.
- **Write-only buildx cache:** `docker-publish.yml:242–243` writes `type=gha,mode=max` cache on tag refs, but tag runs can only restore same-ref or default-branch caches and nothing on main writes buildx cache — so publish builds are always cold while the mode=max write burns repo cache quota (can evict CI pip caches). Either seed the cache from a main-push job or drop both lines.
- **Scope inconsistency (benign):** `pypi-publish.yml:12` grants `actions: read` at workflow level (its `test` job inherits it); docker/msi scope it per-job per the PKG-4 pattern. Read-only, no risk — parity cleanup only.
- **Prerelease detection by substring:** `desktop-msi-publish.yml:257` marks prerelease only for `-rc`/`-alpha`/`-beta`; a tag like `v0.6.0-1` (matches the `v*.*.*-*` trigger) would publish as a non-prerelease Release. `contains(github.ref_name, '-')` would be exact.

## Verified non-findings (do not re-hunt)

- **No untrusted-event publish:** no `pull_request_target`, `workflow_run`, or `issue_comment` triggers anywhere; publishes fire only on tag push / workflow_dispatch (both require write).
- **No template injection:** the only `${{ }}` inside any `run:` block is `github.repository` in the cosign-verify regexp (docker-publish.yml:343) — owner/repo charset cannot carry shell or regex metacharacters of consequence; every attacker-influenceable value (tag names) enters via `env:`.
- **Action pinning is policy-consistent:** all third-party actions SHA-pinned; `actions/*` + `github/*` ref-pinned per the documented hybrid policy in `.github/zizmor.yml`.
- **Gates fail closed:** the `gh api` CI-success poll treats API errors/empty responses as retry-then-refuse; the ancestry check and non-tag guards refuse on mismatch; pii-guard fails closed on `git grep` exit ≥ 2.
- **CHANGELOG guard genuinely gates at publish:** `tests/unit/test_changelog.py` runs inside every publish `test` job with `fetch-depth: 0` (tags present), so a tag without its `## [X.Y.Z]` header blocks all three publishes.
- **requirements.lock has a real drift guard:** `tests/unit/test_requirements_lock.py` fails CI when pyproject deps and the lock diverge; a stale lock also reddens `docker-build-smoke` at PR time. PyPI wheel/sdist staying range-based is deliberate (library vs application) per the lock generator's header.
- **sdist T0-5 gate and the wheel/vendor-registry smoke checks are sound** (`ci.yml:234–296, 377–400`): the `/tests/` tar assertion and the non-empty `vendor_display_name` adapters probe both target the real regression classes they cite.
