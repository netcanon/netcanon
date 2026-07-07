# 18 — CI / Supply-chain / Packaging (merged lens)

Reviewer: Fable fresh-eyes pass, 2026-07-03. Scope: `.github/workflows/*.yml`,
`.github/{dependabot,zizmor}.yml`, `CODEOWNERS`, `Dockerfile`, `.dockerignore`,
`pyproject.toml`, `requirements.lock` + `tools/gen_requirements_lock.sh`,
`MANIFEST.in`, `setup_desktop.py`, `netcanon_desktop/`, version wiring,
`scripts/git-hooks/pre-push`, `.gitattributes`, `.gitignore`.

Verdict: **one confirmed major packaging defect** (Docker image ships without
the 12 `migration/vendors/*.yaml` files — reproduced with a build probe, all
CI gates blind to it), **one major guard gap** (the two PII dirs are NOT
gitignored despite the guard's comment claiming they are, and the guard is
content-pattern-only), plus a handful of minors. The workflow security posture
overall is unusually strong (see "Verified good" at the end).

---

## F1 — MAJOR (confirmed by probe): Docker images ship with ZERO `migration/vendors/*.yaml`; vendor registry silently empty in the Docker channel

**The gap.** `pyproject.toml:163-177` (`[tool.setuptools.package-data]`) lists
only `templates/*.html`, `templates/_partials/*.js`, and
`definitions/library/**/*.yaml`. The 12 vendor-declaration YAMLs under
`netcanon/migration/vendors/` (arista_eos, aruba_aoscx, aruba_aoss,
cisco_iosxe, cisco_iosxr, cisco_nxos, fortigate, juniper_junos,
mikrotik_routeros, mock, opnsense, vyos) are **not covered by any glob**.

**Why PyPI is fine but Docker is not.** Two different wheel-build paths:

* **PyPI** (`pypi-publish.yml:147` → `python -m build`): full git checkout →
  setuptools_scm's VCS file-finder puts the YAMLs in the **sdist** (with
  `SOURCES.txt`), and `build` then builds the wheel **from that sdist**, whose
  manifest carries them into the wheel. Complete.
* **Docker** (`Dockerfile:53` → `pip wheel --no-cache-dir --no-deps
  --wheel-dir /wheels .`): direct PEP 517 `build_wheel`, **no sdist
  round-trip**, and the build context has **no `.git`** (`.dockerignore:2`)
  and **no egg-info** (`.dockerignore:15` excludes `*.egg-info/`). The
  setuptools_scm file-finder is inert, so package data comes ONLY from the
  explicit `[tool.setuptools.package-data]` globs — which omit `vendors/`.

**Probe (reproducible).** Copied `pyproject.toml`/`README.md`/`LICENSE`/
`MANIFEST.in`/`netcanon/`/`netcanon_desktop/` to a scratch dir and ran
`setuptools.build_meta.build_wheel` two ways:

1. **Git-less** (exact Docker condition, `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NETCANON=0.4.15`):
   wheel contains `netcanon/migration/vendors/__init__.py` and **zero** YAMLs.
   (Templates: 24 entries OK; definitions/library: 66 YAMLs OK.)
2. **git init + tag + build_sdist → extract → build_wheel** (exact
   `python -m build` / PyPI condition): wheel contains **all 12 vendor
   YAMLs** (sdist also correctly contained 0 `tests/` entries — the T0-5
   prune holds).

Diff of the two wheels — files missing from the Docker-path wheel:
all 12 `netcanon/migration/vendors/*.yaml` plus 7 in-package `README.md`
docs (harmless). Nothing else differs.

**Runtime effect in the shipped image.** `netcanon/main.py:114` loads
`app.state.vendors = load_vendors()` at startup;
`netcanon/migration/vendors/__init__.py:51-56` degrades **silently** to an
empty registry (the dir exists — it holds `__init__.py` — so not even the
"Vendors directory not found" warning fires; it logs "Loaded 0 vendor(s)").
Consequences:

* `GET /api/v1/migration/adapters` (`netcanon/api/routes/migration.py:180-181`
  → `_migration_helpers.py:138-143`) returns `vendor_display_name: ""` for
  every codec — the UI's group-by-vendor metadata is empty.
* The definitions page's "Vendors + codec capabilities" section
  (`netcanon/api/routes/ui.py:449-452` iterates `vendors_dict`) renders
  **zero vendor rows** in the Docker channel.
* Translation itself still works (codecs are Python-registered), which is
  exactly why nobody noticed: this is a silent cross-channel divergence, and
  any future feature that actually gates on the vendor registry will break
  in Docker only.

**Why every CI gate is blind to it.**

* `ci.yml` "Clean-room wheel install" (ci.yml:255-296) — checks
  `DefinitionLoader` + `/health` only; the wheel it tests is also built via
  `python -m build` (sdist path), so it wouldn't show the gap anyway.
* `ci.yml` docker-build-smoke (ci.yml:337-376) — curls `/health` and `/`
  only; both succeed with an empty vendor registry.
* No unit test asserts wheel contents for `vendors/` (checked
  `tests/unit/` — `test_vendors.py` runs from the source tree).

**The MSI channel is almost certainly affected too (unverified).**
`setup_desktop.py:101-114` hand-ships `include_files` for exactly the two
data trees cx_Freeze won't copy (templates, definitions/library) — proving
the author knew cx_Freeze doesn't bundle package data — but `vendors/` was
never added when the vendor registry landed. In the frozen layout,
`lib/netcanon/migration/vendors/` will hold only the compiled `__init__`,
so `_VENDORS_DIR.glob("*.yaml")` finds nothing → same silent empty registry
in the desktop app. Verify on the next MSI build.

**Fix (three lines + a guard).**

1. Add `"migration/vendors/*.yaml"` to `[tool.setuptools.package-data]`
   (pyproject.toml:163).
2. Add `(HERE / "netcanon" / "migration" / "vendors", "lib/netcanon/migration/vendors")`
   to `include_files` in setup_desktop.py — or better, move the desktop to
   loading vendors from the packaged data like everything else.
3. Extend the docker-build-smoke step (ci.yml:337) to assert
   `/api/v1/migration/adapters` returns a non-empty `vendor_display_name`
   for at least one codec (or `GET` whichever endpoint exposes vendor
   count) — that pins the whole class shut for the Docker channel the same
   way the `/` curl pinned the templates class.

Note: this is the **same bug class** the pyproject comment itself warns
about (pyproject.toml:152-162, the v0.1.0-rc1/rc2 `_partials/*.js`
regression) — third occurrence of the pattern (templates → definitions →
vendors). A generic guard (compare git-less-built wheel contents against a
manifest) would end the whack-a-mole.

---

## F2 — MAJOR (guard gap): the two PII dirs are not gitignored; pii-guard's design assumption is false in-tree

* `git check-ignore docs/codebase-review docs/reviews/2026-06-19-run3-verification`
  → exit 1 (**neither is ignored**); `git ls-files` → 0 (untracked only).
  They survive on disk purely as untracked files.
* `pii-guard.yml:30-33` states: "The review dossier under
  docs/codebase-review/ intentionally quotes these values **and is
  gitignored, so git grep never sees it**." That claim is **false** — there
  is no `.gitignore` entry for either dir (checked `.gitignore` end to end;
  only `local/`, runtime dirs, etc.).
* The guard itself (pii-guard.yml:50) is **content-pattern-only**
  (`samuelr[i]pp09|C:[\]Users`). A `git add docs/` / `git add -A` slip
  commits both dirs; the guard fires only if the file content happens to
  match those two patterns. `docs/codebase-review/` likely matches (it
  quotes the email), but `docs/reviews/2026-06-19-run3-verification/`
  (unlicensed third-party config content per the run seed) plausibly
  contains **neither** pattern → committed cleanly, CI green.
* Compounding: `MANIFEST.in:11` prunes only `tests/`; setuptools_scm ships
  **every tracked file** in the PyPI sdist — so an accidentally committed
  run3-verification dir would be **auto-redistributed to PyPI** at the next
  tag (the exact T0-5 failure mode the tests-prune was built to prevent).

**Fix.** (1) Add both paths to `.gitignore` (making the pii-guard comment
true). (2) Add a cheap path-based step to pii-guard.yml:
`git ls-files -- docs/codebase-review docs/reviews/2026-06-19-run3-verification`
must be empty — that blocks by path regardless of content. (3) Optional:
correct the comment.

Minor note while verifying: the `C:[\]Users` pattern misses the
forward-slash form (`C:/Users/...`). `git grep -E 'C:/Users'` over tracked
files is currently clean (verified), so this is a hardening nit, not a leak.

---

## F3 — MINOR (drift): `gen_requirements_lock.sh` base digest out of lock-step with the Dockerfile

* `tools/gen_requirements_lock.sh:24-25`:
  `BASE="python:3.14.5-slim-bookworm@sha256:a9bee155..."` with the comment
  "Keep this digest in lock-step with the FROM lines in Dockerfile."
* `Dockerfile:12` / `Dockerfile:60`:
  `python:3.14.6-slim-bookworm@sha256:4ff4b92a...`.

Dependabot bumped the Dockerfile digest but the regen script kept the old
one, violating the script's own stated invariant. Practical risk today is
low (same 3.14 ABI, and the lock is hash-verified either way), but the next
lock regen resolves in an environment that is not the deploy base, which is
precisely what the script's header says must not happen.
`tests/unit/test_requirements_lock.py:80-88` guards only "with Python 3.14"
in the lock header — it cannot see this digest drift. Cheap fix: a guard
test asserting the script's `BASE=` digest substring equals the Dockerfile
`FROM` digest, or have the script grep the digest out of the Dockerfile
instead of duplicating it.

Related comment rot (trivial, fix in passing): `Dockerfile:9` says "the
multi-arch index for **3.14.5**-slim-bookworm" above a 3.14.6 tag;
`Dockerfile:15-16` says "if the wheel index lacks a **Python 3.13** ...
prebuilt" in a 3.14 image.

---

## F4 — MINOR: MSI build supply chain is unpinned (contrast with the hash-locked Docker path)

`desktop-msi-publish.yml:191-202`: the release-time MSI build does
`pip install -e ".[desktop-build]"` — resolving PySide6/pystray/Pillow/
cx_Freeze **and the entire runtime dep tree from pyproject ranges at
whatever PyPI serves that day**, with no lock and no hashes; then
`setup_desktop.py bdist_msi`, where (per the workflow's own comment,
line 200-201) **cx_Freeze auto-downloads WiX on first use** — an unpinned
binary toolchain fetch executing inside a job holding `contents: write`.
The Docker image gets `--require-hashes` from `requirements.lock`; the MSI —
the artifact aimed at the least sophisticated operators, already unsigned
(documented at desktop-msi-publish.yml:20-23) — gets neither. A
`requirements-desktop.lock` (same gen pattern, Windows/3.13 environment)
would close most of this.

---

## F5 — MINOR (least privilege): workflow-level write permissions leak into the no-write test-gate jobs

* `desktop-msi-publish.yml:41-43`: `contents: write` is workflow-level, so
  the `test` job (pytest only, lines 71-91) runs with a release-asset-writing
  token it never needs.
* `docker-publish.yml:10-15`: `packages: write`, `id-token: write`,
  `security-events: write` are workflow-level; the `test` job (lines 49-68)
  gets all of them.

Both test jobs execute the full dependency tree + test suite — the largest
third-party-code surface in the pipeline — with publish-grade tokens.
`pypi-publish.yml` already does this correctly (workflow-level read-only,
`id-token: write` scoped to the `publish-pypi` job only,
pypi-publish.yml:10-12,170-171). Move the write grants down to the
build/publish jobs in the other two workflows.

---

## F6 — MINOR (footgun): `workflow_dispatch` on pypi-publish can publish an untagged `.devN` version

`pypi-publish.yml:8` allows `workflow_dispatch` with no inputs. Dispatched
on `main`, the checkout is branch HEAD; the ancestry check (line 89) passes
trivially, the CI-success check (line 107) passes (the merge push run), and
setuptools_scm derives e.g. `0.4.16.dev3` (`no-local-version` makes it
PyPI-acceptable, pyproject.toml:141). One accidental click publishes an
immutable dev release to PyPI. Maintainer-only surface (dispatch requires
write), so a footgun rather than a vulnerability — but a 3-line guard
(`[[ "$GITHUB_REF" == refs/tags/v* ]] || exit 1`, mirroring what
desktop-msi-publish achieves via its required `tag` input) removes it.
Same applies to docker-publish's dispatch (`docker-publish.yml:8`), where
the semver tag pattern would produce an odd image tag.

---

## F7 — NOTE (operational): ci.yml cancel-in-progress interacts with the release CI-success gate

`ci.yml:8-10` sets `cancel-in-progress: true` keyed on ref, so two quick
merges to `main` cancel the first commit's push-event run. If that first
commit is later tagged for release, the publish gates
(`pypi-publish.yml:107-131` etc.) find conclusion `cancelled` and refuse —
correctly fail-closed, but the error ("CI concluded 'cancelled'") will read
as a mystery at release time. Either exclude `refs/heads/main` from
cancellation or document "tag the latest main commit" in the release
procedure.

---

## F8 — NIT (comment integrity): self-contradictory Trivy pin rationale

`docker-publish.yml:236-243`: "Pinned at **v0.36.0 (latest stable)** ...
Vulnerable ranges were `< 0.35.0` and exact `= 0.69.4`. Do NOT bump to
0.69.x" — 0.69.4 cannot simultaneously be a historic vulnerable release and
above the "latest stable" 0.36.0. Whatever the real advisory said, this
comment will misdirect the next person bumping the pin (`GHSA-??`
placeholder included). Re-derive and fix the comment; the SHA pin itself is
fine and matches ci.yml:329.

---

## F9 — NIT: `scripts/git-hooks/pre-push` not covered by `.gitattributes`

`.gitattributes:6-7` forces LF for `requirements.lock` and the lock-gen
script, explicitly because "shell scripts must not carry CRLF" — but the
bash pre-push PII hook (`scripts/git-hooks/pre-push`, activated via
`core.hooksPath`) is not listed. On a Windows clone with `autocrlf=true` it
materializes with CRLF and bash fails on `set -euo pipefail\r` — with
`set -e` semantics that blocks every push (fail-closed, so no PII slips,
but the local half of the PII guard becomes "mysteriously broken push" on
the primary dev platform, inviting `core.hooksPath` removal). Add
`/scripts/git-hooks/* text eol=lf`.

---

## F10 — OBSERVATION (within adjudicated policy): floating first-party action majors in the OIDC publish job

Pin state is: all third-party actions SHA-pinned (docker/*, aquasecurity,
sigstore, anchore, softprops, zizmorcore, pypa — verified every `uses:`);
first-party at tags per the documented hybrid policy (`.github/zizmor.yml:19-21`).
Within that policy, note that `actions/upload-artifact@v7`
(pypi-publish.yml:154) and `actions/download-artifact@v8`
(pypi-publish.yml:175) are **floating major** refs, and download-artifact
executes inside the job holding `id-token: write` for PyPI Trusted
Publishing — the single highest-value token in the pipeline. A retagged v8
that tampers `dist/` between download and publish is inside GitHub's trust
boundary per the policy, but hash-pinning just these two costs nothing.
Not re-litigating the policy; flagging the one place where its marginal
cost is lowest and stakes highest.

---

## Verified good (no findings — checked, not assumed)

* **sdist licensing gate (T0-5)**: probe sdist contained 0 `tests/` entries;
  `MANIFEST.in prune tests` + ci.yml:234-253 assertion both hold.
* **PyPI wheel completeness**: probe wheel-from-sdist carries templates
  (24), definitions/library (67), vendors (12) — the pip channel is whole.
* **No committed absolute local paths**: repo-wide grep for `basetemp`,
  `D:/`, `D:\`, `E:/` → only RANCID-regex false positives; pytest `addopts`
  (pyproject.toml:190) is clean. The D:-basetemp workflow from the memory
  file never leaked into tracked config.
* **No `pull_request_target`, no `workflow_run` triggers, no script
  injection**: the one attacker-influencable value (`inputs.tag`) is passed
  via `env` into `run:` (desktop-msi-publish.yml:167-189, with correct
  rationale comment) and as action inputs elsewhere; no `${{ github.event.* }}`
  in any run block. Fork PRs get read-only tokens (plain `pull_request`).
* **Publish gating**: tag-push only + on-main ancestry check + in-run CI
  success poll (fail-closed on timeout/cancel) + in-run unit+integration
  gate + `concurrency: cancel-in-progress: false` on all three publish
  workflows; PyPI via OIDC Trusted Publishing in a dedicated `pypi`
  environment; cosign identity regexp anchored + dot-escaped
  (docker-publish.yml:316-318). Non-maintainers cannot reach any publish
  path.
* **Docker runtime hygiene**: digest-pinned base, multi-stage,
  `--require-hashes` wheels-only install with `--no-index`, non-root
  uid/gid 1000, HEALTHCHECK, VOLUMEs, no secrets in layers; gating
  pre-merge Trivy CRITICAL scan (ci.yml:328-335) plus informational
  post-push scan + SBOM attestation.
* **checkout hygiene**: every checkout sets `persist-credentials: false`;
  `fetch-depth: 0` only where setuptools_scm needs it.
* **Dependabot**: pip + github-actions + docker ecosystems, 7-day cooldown
  each (`.github/dependabot.yml`), matching the zizmor rule minimum.
* **Version derivation**: `netcanon` reads its version via
  `importlib.metadata` with a `0.0.0+unknown` fallback (netcanon/main.py:233-235);
  `fallback_version = "0.0.0"` covers git-less trees; `no-local-version`
  keeps untagged CI builds PyPI-legal. Console script
  `netcanon = "netcanon.cli:main"` resolves (netcanon/cli.py:32).
* **pii-guard pattern efficacy**: the `[\]`-class backslash form is real
  (`git grep -E 'C:[\]Users'` matches backslash paths); exit-code handling
  fails closed on grep error (pii-guard.yml:56-58).
