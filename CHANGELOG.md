# Changelog

All notable changes to Netcanon are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Note on pre-launch commit SHAs.**  Older entries below cite
> commits by short SHA (`(commit X)`).  Pre-launch the project went
> through a `git filter-repo` history rewrite to scrub PII (see the
> Phase 1 entry).  That rewrite changed every commit's SHA, so most
> short-SHA citations in entries written before Phase 1 won't
> resolve via `git show <sha>` against current history.  The
> *narrative* around each SHA is the load-bearing context; the SHA
> is decorative.  Entries written after Phase 1 (the entries closest
> to the top of `[Unreleased]`) cite current SHAs that resolve.

See also: [`README.md`](README.md) for project orientation;
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the four-layer design that
much of the work below evolves.

---

## [Unreleased]

### Pre-launch sanitization pass (developer-facing docs)

Trims developer-facing docs of pre-launch strategy / planning content
that doesn't add operator value (and could read as either presumptuous
or amateurish to a public audience).  Substance preserved everywhere
it's load-bearing; only marketing-strategy / launch-venue / forward-
looking-strategy material trimmed.

#### `docs/RELEASE_PLAN.md` (821 → ~200 lines)

The doc itself anticipated this conversion: *"when the release
actually happens, prune the 'plan' sections and convert this file
into a `docs/RELEASE_NOTES.md` that records what was actually done."*
This is that conversion in place (filename kept to avoid breaking
~7 cross-references; content rewritten).

* **Kept:** as-shipped phase log (Phase 1 / 1.5 / 2 / 4 / 4.5 / 5 / 6
  / 7 narratives), post-launch roadmap notes (backup retention, lock
  manifest, Docker Hub README sync), the
  pre-launch quality hardening notes (Phase 3 — still pending), the
  universal "what we deliberately don't do" principles (no v1.0
  until external validation, no public demo instance, no binary
  config submissions, no firewall-translation promises, no
  Discussions until triage capacity, no silent-drop translations).
* **Trimmed:** the launch-strategy material ("Maximum bug-report
  surface area" with audience analysis + posting-venue list,
  "Specific framing that works for this tool" marketing copy,
  "Concrete release sequence" with phase 8-11 launch playbook,
  "Priority ranking" MUST/SHOULD/NICE breakdown, "When to start"
  triggers).  Project identity material (now in `IDENTITY.md`),
  sanitiser design rationale (now in `SECURITY.md` / `BUG_REPORTING.md`),
  and packaging-tier discussion (now in `SECURITY.md` Supply-Chain
  Integrity) all dropped from this file since they're authoritatively
  sourced elsewhere now.

#### `translator-plans.txt`

Conservative trim — preserved historical record, fixed obvious
staleness:

* **Removed:** stale `PHASE 1` / `PHASE 2` / `PHASE 3` design-target
  blocks at the bottom that duplicated the SHIPPED phases earlier in
  the file (with old terminology — "adapter" instead of "codec" —
  and design intents that all landed under different names).
* **Updated:** the "Quick-reference checklist when adding a new
  codec" — replaced obsolete file names (`parser.py` / `renderer.py`
  / `capabilities.yaml`) with current convention (`parse.py` /
  `render.py` / in-code `CapabilityMatrix`), removed the "entry
  point in pyproject.toml" step (codecs aren't registered that way),
  added the actual current required surfaces (cross-vendor
  expectation YAMLs, real-capture fixtures + NOTICE/RESULTS rows,
  `docs/CAPABILITIES.md` row, `docs/vendors/<vendor>.md` page).
* **Renamed:** "Honest limitations — DO NOT PROMISE IN MARKETING" →
  "Honest limitations" (the suffix read as internal marketing-team
  framing).

The `[SHIPPED]` historical record blocks (~600 lines documenting
each shipped feature with design-space rationale) are kept verbatim.
A future contributor genuinely benefits from seeing "we considered X
and rejected it for reason Y" — that's the project's design-history
record and removing it would be data loss.

#### `AGENTS.md` — corrected stale SHA references

Four pre-rewrite SHAs (`a93bee8`, `de8e0f3`, `01f394c`, `8c9e9d4`)
that survived the rename PR's sweep updated to their post-rewrite
equivalents (`ba72502` for the type_key validator commit; `7b3d7ed`
/ `271f196` / `a5441b9` for BD-Aruba / BD-Junos / BD-Arista
respectively).  These are load-bearing references in the hard-rule
rationale and the doc-sync table — operators who follow the citations
need them to resolve.

#### `CHANGELOG.md` header — disclaimer about pre-launch SHAs

Older `[Unreleased]` entries cite ~30 short SHAs that don't resolve
against current history (all filter-repo casualties from Phase 1's
PII scrub).  Stripping them all would be ~30 individual edits with
unclear value — the *narrative* around each SHA is the substance,
the SHA is decorative.  Added a one-paragraph disclaimer at the top
of the file explaining the situation honestly.

#### Personal-identifier sweep

Verified clean:

* No personal name / email leaks (`samuelripp` / `samuel.ripp` /
  `Samuel` etc. — zero hits across tracked tree)
* No operator-machine path leaks (`user12` / `C:\Users\` /
  `/home/<user>/` — zero hits)
* All sample IPs in tracked content are RFC1918 (`192.168.x` /
  `10.x.x.x` / `172.16.x.x`) or RFC5737 (`192.0.2.x` /
  `198.51.100.x` / `203.0.113.x`) docs ranges — no real WAN IPs
* All real-world FortiGate fixtures verified to contain no operator-
  identifying content beyond the public provenance noted in
  `tests/fixtures/real/NOTICE.md`

#### What this PR does NOT touch

Resisted the urge to over-sanitize.  The following are intentionally
kept visible:

* `AGENTS.md` engineering rules + doc-sync table (the project's
  craft signal — keep transparent)
* `docs/METHODOLOGY.md` (the matrix-honesty discipline distilled —
  this IS the differentiator)
* `docs/IDENTITY.md` (project identity reference — fine to expose)
* The `[SHIPPED]` design-space rationale in `translator-plans.txt`
  (historical record of decisions; future contributors benefit from
  seeing why one path was chosen over another)
* CHANGELOG narrative about the Phase 1 PII scrub, the rc1
  mislabel, the netcanonio detour — those read as iterative honesty
  in moderation; condensing them happens at v0.1.0 final tag time,
  not now

### Wire `setuptools_scm`: tag-driven package versioning

Eliminates the manual `pyproject.toml` version-bump-per-RC tax and
the entire class of PyPI filename-collision bugs.  Tag → version
becomes automatic.

#### Before (the manual cycle)

`pyproject.toml` had `version = "0.1.0"` (or `"0.1.0rc4"` after the
v0.1.0-rc4 fix) hardcoded.  Each release cycle required:

1. Open a PR bumping the pyproject version manually
2. Wait for CI green
3. Merge
4. Tag `v0.1.0-rcN`
5. Hope the rc number didn't collide with anything previously
   uploaded to PyPI (since PyPI permanently claims wheel filenames
   even after yanking)

The v0.1.0-rc1 / rc2 / rc3 / rc4 sequence each hit a variant of
this — version `0.1.0` permanently claimed by the broken rc1
publish; rc2 and rc3 inherited the same hardcoded `version = "0.1.0"`
and got rejected; rc4 manually bumped to `"0.1.0rc4"`.  Future
RCs (or v0.1.0 final, since `0.1.0` is permanently claimed) would
have continued requiring manual bump-PRs forever.

#### After (this PR)

Tag, push, done.  `setuptools_scm` derives the package version
from the git tag at build time:

* Tag `v0.1.0-rc5` → wheel `netcanon-0.1.0rc5-py3-none-any.whl`
* Tag `v0.1.1` → wheel `netcanon-0.1.1-py3-none-any.whl`
* Untagged commit (e.g. CI run on main between releases) → wheel
  `netcanon-0.1.0rc5.dev3-py3-none-any.whl` (PEP 440 dev version,
  guaranteed-distinct from any tagged release)

Every release tag produces a unique PyPI filename automatically.
No collisions possible.

#### Implementation

* **`pyproject.toml`**:
  - Added `setuptools_scm>=8` to `[build-system].requires`.
  - Replaced `version = "0.1.0rc4"` with `dynamic = ["version"]`.
  - Added `[tool.setuptools_scm]` block:
    - `version_file = "netcanon/_version.py"` — bakes the resolved
      version into the package so runtime can read it without
      needing git available (matters in containers).
    - `local_scheme = "no-local-version"` — strips PEP 440 local
      components (`+g<sha>`).  PyPI rejects local versions in
      releases; without this, untagged-commit builds would produce
      strings PyPI rejects.
    - `fallback_version = "0.0.0"` — backstop for source trees
      with no git history (extracted tarballs, etc).  Should never
      hit in CI or worktree work.

* **`.gitignore`**: exclude `netcanon/_version.py` (auto-generated;
  never committed).

* **`Dockerfile`**: builder stage gains an
  `ARG SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NETCANON` (defaults to
  empty).  `setuptools_scm` checks this env var first before
  trying git; lets the Docker builder skip needing `.git/` in its
  context (which is excluded per `.dockerignore`).

* **`.github/workflows/docker-publish.yml`**: passes
  `${{ steps.meta.outputs.version }}` (the semver-parsed tag) as
  the `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NETCANON` build-arg to
  the build-push-action.  Keeps the Docker build context clean
  while ensuring the resolved version matches the published tag.

* **`.github/workflows/ci.yml` + `.github/workflows/pypi-publish.yml`**:
  every `actions/checkout@v6` step now uses `fetch-depth: 0`.
  Default shallow checkouts have no tags; setuptools_scm would
  fall back to `0.0.0` and produce misleading "version 0.0.0"
  builds.  With full history, the tags are present and version
  resolves correctly.

* **`AGENTS.md`**: new doc-sync row covering the new release
  workflow ("Tag, push, done"), the build-arg flow for Docker, the
  fetch-depth requirement for any future CI step that runs
  `pip install -e .` or `python -m build`, and the gitignored
  `_version.py`.

#### Verification

Built locally on this branch (off main, post-rc4 tag):

```
$ git describe --tags --abbrev=7
v0.1.0-rc4

$ python -m setuptools_scm
0.1.0rc5.dev0

$ python -m build --wheel
Successfully built netcanon-0.1.0rc5.dev0-py3-none-any.whl
```

Untagged commit on this branch produced
`0.1.0rc5.dev0` — distinct from rc4 (the latest tag), PEP 440
clean, no local-version components, would be accepted by PyPI.
When this PR merges and you tag `v0.1.0-rc5`, the wheel will
build as `0.1.0rc5` (no `.dev0`) and publish cleanly to PyPI.

#### Carry-over: when v0.1.0 final ships

PyPI version `0.1.0` is permanently claimed by the broken rc1
publish (yanked, but yanking doesn't free filenames).  The
"final" v0.1.0 release will need to bump to `v0.1.1` (or any
unused PyPI version).  This is structural to PyPI, unrelated to
setuptools_scm, and can't be undone.  Future major / minor
releases (`v0.1.2`, `v0.2.0`, etc.) work fine.

### PyPI version bump + Docker tag-emission cleanup

Three publish-side fixes bundled.  The `v0.1.0-rc3` release exposed
two distinct issues at the registry / package-manager surface; this
PR fixes both plus removes a long-standing redundancy.

#### 1. PyPI: bump `pyproject.toml` `version` to `0.1.0rc4`

**Symptom:** the `v0.1.0-rc3` PyPI publish failed with:

```
400 File already exists ('netcanon-0.1.0-py3-none-any.whl', with
blake2_256 hash 'c61e26397f...').
See https://pypi.org/help/#file-name-reuse for more information.
```

**Cause:** `pyproject.toml` had `version = "0.1.0"` hardcoded.  Every
build produces files named `netcanon-0.1.0-*` regardless of the
git tag that triggered the publish.  v0.1.0-rc1 published with the
broken templates and permanently claimed that filename on PyPI;
yanking doesn't free the filename (PyPI's policy: filenames are
immutable once uploaded).  rc2 and rc3 inherited the same
`version="0.1.0"` and PyPI rejected each as a duplicate.

**Fix:** bump pyproject `version` to `"0.1.0rc4"` (PEP 440 form,
no dash).  Each RC bumps explicitly so each gets a unique PyPI
filename.  Inline comment in `pyproject.toml` documents the trap so
future maintainers don't re-introduce it.

The Docker side wasn't affected — Docker tags are unique per push
regardless of the package's internal version.  v0.1.0-rc3 published
to GHCR + Docker Hub successfully and the published image is
working (HTML pages render correctly; verified end-to-end).  Only
PyPI was blocked.

#### 2. Docker tag emission: drop redundant `v`-prefixed tag

**Symptom:** every Docker Hub release published two tags pointing
at the same image bytes — e.g. `v0.1.0-rc3` AND `0.1.0-rc3`.
Visible on the Docker Hub Tags page; same digest under both tags.

**Cause:** `docker-publish.yml`'s `metadata-action` config had:

```yaml
tags: |
  type=ref,event=tag                  # emits v0.1.0-rc3 (with `v`)
  type=semver,pattern={{version}}     # emits 0.1.0-rc3  (without `v`)
  ...
```

**Fix:** remove the `type=ref,event=tag` line.  Keep only the
semver-derived form, which matches the convention of official
Docker Hub images (`python:3.13-slim`, `node:20`, etc.), the PyPI
version string, and most operator muscle memory for `docker pull`
commands.

Note: existing dual-tagged releases (`v0.1.0-rc1`, `v0.1.0-rc2`,
`v0.1.0-rc3`) on Docker Hub stay as-is; this only affects future
publishes.  Operators with hardcoded `:v0.1.0-rc3` references in
their tooling will need to switch to `:0.1.0-rc3` for future
releases.  Cleanup of the lingering `v`-prefixed tags is manual
(via the Docker Hub UI Tag → Delete dropdown) — see the action-
items list in the previous CHANGELOG entry.

#### 3. Docker `:latest` emission on tag pushes

**Symptom:** the `:latest` tag on Docker Hub / GHCR was never
populated.  Every released RC pushed `vX.Y.Z-rcN` and `X.Y.Z-rcN`
tags but no `:latest`.  README + CHANGELOG both documented
`docker pull netcanon/netcanon:latest` as the recommended
quickstart, which would fail with "manifest unknown".

**Cause:** the `metadata-action` config had:

```yaml
type=raw,value=latest,enable={{is_default_branch}}
```

The `is_default_branch` template variable is only true when the
workflow's git ref IS the default branch (e.g. push to `main`).
For tag-triggered workflows (`push: tags: ['v*.*.*']`), the ref is
the tag, not the branch — so `is_default_branch` evaluates false,
and `:latest` never emits.

**Fix:** drop the `enable={{is_default_branch}}` condition.
`:latest` now updates on every release tag push.  This means RC
tags will set `:latest` to point at the current RC — appropriate
for a pre-launch project where there's no stable to anchor `:latest`
to.  Once v0.1.0 final ships, RC tags become rare; if/when stable +
RC release cadence overlaps and we want `:latest` to track stable
only, the condition can be re-added with a different gate (e.g.
`enable=${{ !contains(github.ref, '-') }}` to skip pre-release tags).

#### Action items for the operator (manual)

After this PR merges, tagging `v0.1.0-rc4` will publish:

* **PyPI:** `netcanon==0.1.0rc4` (working — the templates fix from
  the previous PR + the unique version string from this one combined
  unblock the publish)
* **Docker Hub + GHCR:** `:0.1.0-rc4` and `:latest` (no more
  `v`-prefix duplicate; `:latest` finally exists and points at the
  rc4 image)

The dangling `v0.1.0-rc1` / `v0.1.0-rc2` / `v0.1.0-rc3` tags from
earlier publishes can be deleted manually via the Docker Hub UI
once rc4 is up — they all point at broken or pre-fix images and
operators have no reason to pull them.  Same for GHCR via
https://github.com/netcanon/netcanon/pkgs/container/netcanon →
Manage versions.

#### Long-term fix (post-v0.1.0)

Tracked in `docs/RELEASE_PLAN.md` post-launch roadmap notes:
**wire `setuptools-scm`** so the package version is auto-derived
from the git tag.  No more manual pyproject bumps per RC; no more
opportunity for `v`-prefix-vs-not confusion.  Tag `v0.1.0-rc5` →
package builds as `0.1.0rc5` (PEP 440 normalized) automatically.
Tag `v0.1.0` → builds as `0.1.0`.  Removes a class of bugs
permanently.  ~10-line change to `pyproject.toml` + workflow; not
urgent but worth doing before v0.1.0 final.

### Fix: `templates/_partials/*.js` missing from built wheel (every HTML page 500'd)

**Severity: blocker.**  v0.1.0-rc1 and v0.1.0-rc2 published artefacts
(both PyPI wheels and Docker images on GHCR + Docker Hub) shipped
**without** the 12 Jinja partials under `netcanon/templates/_partials/`.
Every HTML page that extends `base.html` (which includes the dashboard,
migrate page, devices, configs, schedules — i.e. *every operator-
facing page*) raised `jinja2.exceptions.TemplateNotFound` and FastAPI
returned 500.  `/health` worked because it returns JSON, not a
template.

Discovered by pulling `netcanon/netcanon:v0.1.0-rc2` from Docker Hub
into a clean container, hitting `/`, getting `Internal Server Error`,
and checking `docker logs`:

```
jinja2.exceptions.TemplateNotFound: '_partials/config-viewer.js'
not found in search path:
'/usr/local/lib/python3.14/site-packages/netcanon/templates'
```

#### Root cause

`pyproject.toml` had:

```toml
[tool.setuptools.package-data]
netcanon = ["templates/*.html"]
```

That glob matches only `.html` files at the **top** of `templates/`.
It misses files with non-`.html` extensions (the `.js` partials) AND
files in subdirectories (the `_partials/` subdirectory).  When
setuptools builds the wheel, those 12 files are silently excluded.
When operators install the wheel — directly via `pip install netcanon`
or transitively via the Docker image's multi-stage build — the
package is missing the partials.

Editable installs (`pip install -e`) hide this because they import
files directly from the source tree on each load, bypassing the
wheel-packaging step.  This is why local Python development works
fine but every published artefact is broken.

#### Fix (3 changes in this PR)

1. **`pyproject.toml`** — expanded the package-data glob:
   ```toml
   netcanon = [
       "templates/*.html",
       "templates/_partials/*.js",
   ]
   ```
   Inline comment added explaining the trap so future contributors
   don't reintroduce it.  Verified locally: `python -m build --wheel`
   now produces a wheel containing all 9 HTML files + all 12 `_partials/*.js`
   files.

2. **`.github/workflows/ci.yml`** — extended the `docker-build-smoke`
   job to curl `GET /` (the dashboard) in addition to `/health`.
   The original smoke only verified `/health`, which doesn't render
   a template, which is why this regression slipped through CI.
   The expanded check is small (one extra `curl`) and catches the
   exact bug class that bit us — every operator-facing page renders
   `base.html`, which renders the partials, so a single dashboard
   request is sufficient signal.

3. **`AGENTS.md`** — new doc-sync row mapping "new template file
   with non-`.html` extension OR in a new subdirectory" → "update
   `pyproject.toml` `[tool.setuptools.package-data]`".  Cites the
   v0.1.0-rc1 / rc2 bug as the failure mode this rule prevents.

#### Aftermath / coordination required

Three operator-action items beyond merging this PR:

* **Yank `netcanon==0.1.0`, `netcanon==0.1.0rc1`, `netcanon==0.1.0rc2`
  from PyPI.**  All three are broken (every HTML page 500s).  Yank
  via https://pypi.org/manage/project/netcanon/ → click each version
  → Yank.  Yanking marks the version as "do not install for new
  users" (`pip install netcanon` skips it) but doesn't free the
  filename — that's PyPI's permanent policy.  Already-pinned
  installs continue to work; new installs skip the broken versions.
* **Mark broken Docker tags clearly.**  The `v0.1.0-rc1` and
  `v0.1.0-rc2` tags on `ghcr.io/netcanon/netcanon` and
  `docker.io/netcanon/netcanon` are also broken.  Either delete
  them via the registry UI or push a tag-level note in the Docker
  Hub repo description warning operators away.  Don't silently
  let `:latest` keep pointing at a broken image — repoint it to the
  next working release after the fix lands.
* **Tag `v0.1.0-rc3` once this PR merges.**  Verifies the fix
  end-to-end (the new docker-build-smoke step will fail-fast if
  the wheel is still broken; if green, both registries publish a
  working image and PyPI gets a working wheel).

After v0.1.0-rc3 verifies, the path forward is unchanged: tag
`v0.1.0` final when ready (note: PyPI version `0.1.0` is permanently
claimed by the broken rc1 publish; the actual final release will
need to be `v0.1.1` or higher per PyPI's filename-immutability
policy.  See the broader PyPI versioning issue tracked in
`docs/RELEASE_PLAN.md` post-launch roadmap notes — `setuptools-scm`
wiring would auto-derive package version from git tags and prevent
this class of issue recurring).

#### Why CI didn't catch this

The original `docker-build-smoke` job built the image and curled
`/health` — which doesn't render a template, so the missing
partials didn't surface.  Closed in this PR.

The release workflow (`docker-publish.yml`) doesn't smoke-test
either; it builds, signs, publishes, and runs `cosign verify` (which
verifies the *signature*, not the application's runtime behaviour).
That's appropriate for a publish workflow, but it means the
`docker-build-smoke` is the load-bearing pre-publish gate — and
it had a coverage gap.

### Correct Docker Hub namespace: `netcanonio` → `netcanon`

The `v0.1.0-rc2` Docker publish failed against `docker.io/netcanonio/netcanon`
with `unauthorized: incorrect username or password`.  Root cause was
not auth — it was that `netcanonio` was a wrong-turn namespace.  When
the Docker Hub mirror PR was authored, the operator believed the
`netcanon` namespace was already taken and picked `netcanonio` as a
fallback.  Verifying afterwards showed `netcanon` was actually
available and now belongs to the project's Docker Hub account.

This PR corrects every `netcanonio` reference to `netcanon`:

* `.github/workflows/docker-publish.yml` — `DOCKERHUB_IMAGE` env var
* `README.md` — `docker run` example
* `docs/IDENTITY.md` — Distribution surfaces table + drops the
  "namespace divergence" note (no longer divergent)
* `SECURITY.md` — Distribution channels table
* `AGENTS.md` — distribution-variants clarifying paragraph
* `CHANGELOG.md` — earlier `[Unreleased]` Docker Hub mirror entry
  rewritten to reflect the corrected namespace

After this PR merges, the operator should also:

* Update the `DOCKERHUB_USERNAME` repo secret to `netcanon`
* Re-run the failed `v0.1.0-rc2` Docker publish workflow from the
  Actions tab (no need to re-tag — same trigger ref)
* Optionally clean up the dormant `netcanonio` Docker Hub namespace
  (if it was registered as a placeholder) so it doesn't sit empty

The Docker Hub mirror has never successfully pushed any image, so
the correction is cleanly retroactive — no operators have been
told to pull from the wrong namespace.

### `AGENTS.md`: clarify Docker / pip / MSI as distribution variants

Closes a small ambiguity in the "Parallel Platform Development"
section.  Pre-edit, the section listed Web + Desktop as the two
platforms requiring feature parity, but didn't say where Docker /
pip / MSI fit.  A future contributor could reasonably wonder
whether Docker is a third parity-requiring target (it isn't —
`docker run ghcr.io/netcanon/netcanon` runs the same
`uvicorn netcanon.main:app` entrypoint as host-installed web; the
container is a packaging variant of the web platform, not a
separate code path).

Two small additions:

* **Clarifying paragraph after the platforms table.**  Names
  Docker (GHCR + Docker Hub mirror), `pip install netcanon`, and
  the Windows MSI as distribution variants of the two platforms —
  Docker + pip both produce a web-platform install; the MSI
  produces a desktop-platform install.  Explicit that none of
  them require their own parity test row.
* **New doc-sync table row for packaging / distribution workflow
  changes.**  Covers `Dockerfile`, `.dockerignore`, the publish
  workflows (`docker-publish.yml` / `pypi-publish.yml`), base-
  image bumps, action-version bumps, registry namespace changes,
  and signing / SBOM / attestation surface changes.  Required
  follow-ups when any of those change: `SECURITY.md` Supply-Chain
  Integrity table, `docs/IDENTITY.md` Distribution surfaces
  table, `README.md` Install section, and (for a new Python
  matrix entry) the matching classifier in `pyproject.toml`.

The Phase 6 (packaging foundation), Python 3.14 (CI matrix
expansion), and Docker Hub mirror waves all hit at least one of
these surfaces, so the row is anchored in real recent waves
rather than speculative.

### Rename `CLAUDE.md` → `AGENTS.md` (cross-tool convention name)

Renames the contributor-directives file from a vendor-named
(`CLAUDE.md`) to the emerging cross-tool convention
(`AGENTS.md`).  Substance unchanged — same hard rules, same
doc-sync table, same engineering discipline; just the filename and
its 197 cross-references across 56 files.

The rename also touches the starter template at
`docs/templates/CLAUDE.md.template` → `docs/templates/AGENTS.md.template`
and the four genuine `Claude`-named references that lived outside
the directive file itself:

* `docs/glossary.md` — "humans and Claude agents" → "human or
  AI-assisted"
* `translator-plans.txt` — "Written for Claude, not humans" →
  "Written for AI-assisted contributors and grep — not narrative
  reading"
* `.gitignore` — "Claude Code internal" → "AI-assistant tooling —
  local session state, never committed", and expanded to ignore
  `.cursor/` and `.aider*/` alongside `.claude/` so the gitignore
  treats AI tooling generically
* The directives file itself — content was already vendor-neutral
  (no "Claude" string anywhere in body text); only the filename +
  cross-refs changed

The rename is a pure structural change; no rules were dropped,
softened, or rewritten.

#### Why now

Pre-public-flip polish.  `AGENTS.md` is becoming the cross-tool
standard for "the rulebook the contributor reads first" — adopted
by OpenAI codex, several Cursor projects, and others.  The
generic name decouples the file from any particular AI tool's
conventions and reduces the perception that the project is tied
to one vendor's tooling.

#### What did NOT change

* **Git history.**  Past commits with `Co-Authored-By` trailers
  stay as they are — those are truthful attribution and rewriting
  them would require a destructive `git filter-repo` pass we're
  not doing again after the Phase 1 PII scrub.  Going forward,
  commits attribute to the project contributor identity only.
* **Real-world fixtures.**  Two FortiGate operator-contributed
  fixtures contain "Claude" in their unmodified config text
  (banner / comment / description); leaving them untouched
  preserves fixture provenance and authenticity.
* **The contributor directives content.**  Every hard rule, every
  doc-sync table row, every cross-reference target stays the same
  — only the filename changed.

#### Doc-sync follow-up

* `CONTRIBUTING.md` gained a small "A note on the development
  workflow" subsection inside "What this project values":
  acknowledges AI-assisted development as part of the workflow
  context, declares that matrix-honesty discipline applies to the
  AI workflow the same as the code, and points at `AGENTS.md` as
  the canonical (tooling-agnostic) directives file.

### Distribution: mirror published images to Docker Hub

`docker-publish.yml` now pushes each release to **two registries** in
the same `docker/build-push-action` step:

* **GHCR — `ghcr.io/netcanon/netcanon`** — primary, signed via
  cosign keyless (Sigstore + GitHub OIDC), SBOM attached as a cosign
  attestation (SPDX JSON via syft).  The "trust chain" image.
* **Docker Hub — `docker.io/netcanon/netcanon`** — convenience
  mirror.  Same image bytes (single build, dual push from one
  buildx step), same tag patterns.  No cosign signature, no SBOM
  attestation — Docker Hub is treated as a discoverability /
  corporate-egress-friendliness path; operators in regulated
  environments should continue pulling from GHCR for the attested
  provenance.

Why mirror to Docker Hub: network engineers in corporate environments
often have egress whitelists that allow `docker.io` but block GHCR;
`docker pull netcanon/netcanon` is also closer to muscle memory
than the GHCR equivalent, so tutorials and quick-start docs read
cleaner.

All distribution surfaces share the `netcanon` name (GHCR org,
Docker Hub user, GitHub org, PyPI project).

#### Auth surface

Two new repository secrets (configured manually in repo settings,
not in code):

* `DOCKERHUB_USERNAME` — the Docker Hub account username with push
  permission to the `netcanon` namespace
* `DOCKERHUB_TOKEN` — Docker Hub Personal Access Token with **Read
  & Write** scope (least privilege; never password)

The token is per-purpose ("Github Actions docker-publish" description)
and revocable via Docker Hub Account Settings → Security → Personal
Access Tokens if it ever leaks.

#### Cosign filtering

The cosign signing step now filters by registry prefix to sign only
the GHCR tags.  Without this filter, cosign would attempt to sign
the Docker Hub mirror too, which would either fail (if the workflow
lacks Docker Hub keyless signing setup) or attach a Docker Hub-
specific signature with weaker provenance.  The filter keeps the
trust chain unambiguous: cosign-verifiable signatures live on GHCR;
Docker Hub is the unsigned mirror.

#### Docs sync

* `README.md` — added the `docker run netcanon/netcanon:latest`
  example as an alternative install path under the existing
  Docker section, with a note that the mirror is unsigned.
* `docs/IDENTITY.md` — added a "Distribution surfaces" table
  enumerating GHCR / Docker Hub / PyPI with their provenance
  guarantees per channel.
* `SECURITY.md` — added a "Distribution channels and what each
  provides" sub-table to the Supply-Chain Integrity section,
  making the cosign / SBOM / attestation differences between the
  channels explicit.

### CI: Python 3.14 coverage + Docker build smoke test

Closes the verification gap that the Dependabot Dockerfile bump
(`python:3.13-slim-bookworm` → `python:3.14-slim-bookworm`,
PR #2) opened: previously the test matrix tested 3.11/3.12/3.13
only, so the bumped base image was effectively unverified by CI.

Two changes:

* **CI matrix expanded to include Python 3.14.**
  `.github/workflows/ci.yml` adds `"3.14"` to the test matrix and
  `pyproject.toml` adds the corresponding
  `Programming Language :: Python :: 3.14` classifier so the package
  metadata is consistent with what's tested.
* **New `docker-build-smoke` CI job.**  Builds the Dockerfile on
  every PR and `push` to main, runs the resulting image, and polls
  `GET /health` for up to 60 seconds.  Catches Dockerfile-side
  regressions (base bumps, COPY mistakes, entrypoint breakage) at
  PR-time rather than at tag-time when `docker-publish.yml` fires
  the GHCR push.

The smoke test exercises the full container lifecycle (build →
boot → ready → health-check responds) but doesn't run pytest
inside the container — that's still the matrix job's role on the
host runner.  The two layers complement: matrix verifies the
package code; smoke verifies the image-shipping path.

### Documentation audit pass (post-Phase-7)

Multi-agent review of every operator-facing doc against current state,
with prioritised fixes applied across BLOCKER + HIGH + MEDIUM tiers.
Five parallel review agents covered: top-level docs (README /
CHANGELOG / BUG_REPORTING / HUMAN_TESTING / CONTRIBUTING / SECURITY /
LICENSE); `docs/` root operator pages (CAPABILITIES / COMPARISON /
IDENTITY / HOW_WE_TEST / TROUBLESHOOTING / METHODOLOGY / RELEASE_PLAN
/ glossary); per-vendor pages (`docs/vendors/*.md`); walkthroughs
(`docs/walkthroughs/*.md`); architecture + contributor docs
(ARCHITECTURE / adding-a-canonical-field / adding-a-target-profile /
feature-parity-walkthrough / translator-plans).  Headline fixes:

#### BLOCKER (factually wrong / would break trust)

* **README Docker volume-mount bug.**  Removed `-v $(pwd)/definitions:
  /app/definitions` example — the in-image `definitions/` YAMLs are
  tracked content; mounting an empty host dir over them crashes
  startup with the same `FileNotFoundError` the Phase 6 wave caught.
  Replaced with `-v $(pwd)/data:/app/data` (the actual operator-
  state mount slot).
* **README sanitiser link target.**  Pointed at `BUG_REPORTING.md`
  (the workflow doc) instead of `CAPABILITIES.md` (the matrix).
* **HUMAN_TESTING.md hardcoded codec count.**  "all 7 codecs" →
  "the registered codecs" (AGENTS.md hard-rule violation).
* **`docs/IDENTITY.md` Topics ↔ pyproject.toml mirror claim.**
  Added `python` + `fastapi` to `pyproject.toml` `keywords` so the
  two surfaces actually match (doc claimed mirror; reality didn't).
* **Phantom CLI flag.**  `cisco_iosxe_to_junos.md` referenced a
  `--rename-interfaces` flag that doesn't exist; replaced with the
  actual mechanism (migrate-page rename modal / `rename_overrides`
  in the API payload).
* **Invalid git SHAs in contributor docs.**  `adding-a-canonical-
  field.md` referenced `e3b48b4` (MTU) and `e495a0b` (local_users);
  `feature-parity-walkthrough.md` referenced `145642e` (SNMPv3 USM).
  The first two were filter-repo casualties from the netconfig→
  netcanon rename and aren't recoverable; rewrote to remove SHA
  references and point at `git log --grep="wire-through"` for live
  tree examples.  The SNMPv3 SHA was wrong; corrected to `8c6e493`
  (the actual P2C6 commit).
* **`translator-plans.txt` stale `[ ]` marker.**  Module-variant
  target profiles marked unshipped despite Option B being fully
  shipped (allowlist + schema + reference YAML all live); replaced
  with `[SHIPPED]` block citing the current-tree artefacts and
  preserving the original design-space notes for historical record.

#### HIGH (cross-cutting purges)

* **Hardcoded `~12,000 cells` purge.**  Appeared in
  `docs/HOW_WE_TEST.md`, `docs/TROUBLESHOOTING.md`, and two places
  in `docs/RELEASE_PLAN.md`.  Replaced with pointers to the live
  source (`tests/fixtures/real/PHASE4_RECONCILIATION.md`, machine-
  generated, can't drift behind code).  Hard-rule violation.
* **Docker-tag policy.**  `:0.1.0` doesn't exist on GHCR yet
  (only `:0.1.0-rc1` from Phase 6).  Switched README + RELEASE_PLAN
  examples to `:latest` (always resolves; auto-tracks current
  build) so operators can copy-paste without 404'ing.
* **Stale forward-looking phase prose.**  `CONTRIBUTING.md` (Phase
  4.5 sanitiser as future work), `SECURITY.md` (Phase 6 Supply-
  Chain Integrity as future work), and `RELEASE_PLAN.md`'s body
  ("Status as of 2026-05-05: helper does NOT yet exist") all
  contradicted their own status blocks.  Rewrote to current-state.

#### Vendor-page capability drift (per-vendor codec investigation)

Every contested claim in the agent report was checked against the
codec implementation directly (parse.py + render.py grep of MTU /
VRF / RADIUS / DHCP / local_users):

* **`cisco_iosxe.md`** — TL;DR clarified that `cisco_iosxe_cli` is
  parse-only (Cisco-as-source); MTU claim retained (it IS parsed —
  carried into canonical for target codecs to render).
* **`fortigate.md`** — added explicit caveat that MTU + VRF binding
  are parsed-on-source-only (FortiGate-as-source carries them
  through; FortiGate-as-target doesn't emit them — codec gap, not
  doc gap).  Removed "35K-line" hardcoded count from the gotchas.
* **`mikrotik_routeros.md`** — moved DHCP server pools from Tier 1
  to Tier 2 (matches `CAPABILITIES.md` and the codec's own
  `# Tier 2 DHCP` source comment).  Renamed-port preservation
  reframed as intra-vendor round-trip preservation (not a cross-
  vendor translation surface).
* **`aruba_aoss.md`** — moved `dhcp-snooping` and `web-management
  ssl` / `ip authorized-managers` to a "parse-tolerant carry-
  through" subsection (parsed on source; cross-vendor render path
  not yet wired).
* **`arista_eos.md`** — corrected "EOS 4.21 through 4.30+" to "4.21
  through 4.26" (corpus-validated range).
* **`aruba_aoss.md`** — dropped `YA` software branch + 2530 chassis
  from the version-coverage list (no fixture); reframed as "CLI
  grammar parses + renders for these; not pinned by a fixture yet".
* **`juniper_junos.md`** — same treatment for SRX (no fixture;
  reframed).  "Five distinct Junos majors" corrected to "five
  captures across four majors" (two 25.4 captures = one major).

#### Walkthrough fidelity (paired-with-demo accuracy)

* **`aruba_to_arista.md`** — corrected the paradigm-flip block to
  match what the demo actually emits (bare `interface 1` not
  `interface Ethernet1`; both forms are valid Arista CLI).  Added
  a "Note on port naming" callout describing how to invoke the
  rename mesh for canonical `Ethernet<N>` form.  Manual-review
  checklist updated to match.
* **`cisco_iosxe_to_junos.md`** — added the missing third interface
  line (`GigabitEthernet0/0/2`) to the sample output block.
* **`fortigate_to_mikrotik.md`** + **`opnsense_to_junos.md`** —
  softened hardcoded "35K-line" / "2,000+ lines" / "~5-10% Tier-1/2"
  / "~90-95% Tier-3" prose to qualitative phrasing (hard-rule).

#### `BUG_REPORTING.md` SLA realism

Triage SLA changed from "48 hours" to "2 weeks", with explicit
context that this is a one-maintainer project worked on alongside
a full-time dayjob.  Critical reports (security, silent data loss
in `supported`-declared translations) escalate.

#### `tests/fixtures/real/RESULTS.md`: cisco_iosxe (NETCONF) section

Added a `## cisco_iosxe (NETCONF / OpenConfig)` section documenting
the codec's `best_effort` cert state, Phase 0.5 stub-render scope,
and the cert-decision rationale (stays `best_effort` until either
NETCONF render demand materialises or a multi-version operator-
contributed corpus lands).  This is the doc the per-vendor index
links to as cert source-of-truth.

#### `SECURITY.md` accuracy refresh

Beyond stale-Phase-6 Supply-Chain Integrity content (rewritten to
current state — multi-stage Docker, cosign keyless signing, syft
SBOM attestation, PyPI Trusted Publishing, non-root runtime), the
threat model was reframed to acknowledge the dual-deployment shape
(desktop on loopback vs. web/Docker with operator-supplied reverse
proxy + auth).  Added a new "Sanitiser (Bug-Reporting Workflow)"
section documenting Phase 4.5's redaction categories.  Known-risk
table grew rows for "banner / comment text not sanitised" and
"IPv6-public redaction not implemented" — both honest disclosure
of the v0.1.0 sanitiser's documented limitations.

#### `docs/RELEASE_PLAN.md` post-launch roadmap entry

Added a "Backup retention / rolling delete on scheduled jobs"
note: today every scheduled-job run lands a fresh
`configs/<host>_<ts>.<ext>` file with no automatic cleanup; long-
running schedules grow the backup directory unbounded.  Want a
per-schedule retention policy (keep N most recent, OR keep configs
newer than D days, OR both) configurable at schedule-creation.
Doesn't gate v0.1.0; tracked here so it survives the eventual
RELEASE_PLAN→RELEASE_NOTES conversion.

#### Cross-cutting smaller fixes

* **`docs/glossary.md` Tier-3 description** — corrected from
  "`raw_sections` passthrough" to "detected-but-deliberately-not-
  translated; surfaced via `CanonicalIntent.dropped_tier3_sections`"
  (matches actual model field name).
* **`docs/COMPARISON.md`** — "8 vendor families" → enumerated list
  of 7 (Cisco / Juniper / Fortinet / Aruba / Arista / MikroTik /
  OPNsense — the codec count is 8, vendor families are 7).
* **`docs/TROUBLESHOOTING.md`** — `alpha`/`beta` cert tiers (don't
  exist) replaced with `best_effort` (the actual non-`certified`
  tier in use); broken `#hash-portability-policy` anchor link
  replaced with prose pointer.
* **`ARCHITECTURE.md`** — Phase 1 evolution-roadmap bullet no
  longer mislabels `cisco_iosxe_cli` as bidirectional (it's
  parse-only).
* **`docs/IDENTITY.md`** — "we use 13" Topics count replaced with
  "the list below" (the count rots without a CI guard).

### Public release plan — Phase 7: README rewrite

Phase 7 from [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) — the
operator-facing front door.  The pre-rewrite README read like
internal documentation (architecture-first, contributor-table
above the fold).  The new README leads with operator value and
defers contributor scaffolding to a later section.

#### Reframed structure

* **Tagline above the fold** — the locked tagline from
  [`docs/IDENTITY.md`](docs/IDENTITY.md) ("Multi-vendor network
  config translator with a verifiable cross-vendor audit") is the
  first thing readers see.
* **Concrete before/after demo** — paste a Cisco IOS-XE snippet,
  see the rendered Junos output, both inline.  Static text
  equivalent of the asciinema the Phase 4 changelog flagged as
  Phase 7's deliverable.  Live demo is one `docker run` away.
* **Trust signal as invitation** — surfaces the zero-`CODEC_BUG`
  cross-mesh-audit claim (the headline number lives in
  [`docs/HOW_WE_TEST.md`](docs/HOW_WE_TEST.md), per the prose-
  count hard rule), then immediately points at
  [`BUG_REPORTING.md`](BUG_REPORTING.md): the audit only covers
  cells we have fixtures for; bring us configs we haven't tested
  yet.  Frames the matrix-honesty discipline as an invitation
  rather than a marketing claim.
* **Headline install: `docker run`** — the published GHCR image
  is the headline path (signed via Sigstore + SBOM via syft per
  Phase 6).  `pip install netcanon` is Tier-2; Windows MSI is
  Tier-3.  Each install path includes the actual command, not
  just a name.
* **Walkthroughs table promoted above the fold** — the four
  Phase-4 walkthroughs (Cisco→Junos / FortiGate→MikroTik /
  Aruba→Arista / OPNsense→Junos) are the answer to "is this the
  right tool for my migration?", and now sit prominently above
  the contributor table rather than buried in a "where to go
  next" multi-row.
* **Tier-1/2/3 summary inline** — operators learn what translates
  and what doesn't directly in the README, with a pointer to
  [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) for the full
  matrix.  The Tier-3 boundary's "we deliberately don't auto-
  render firewall / NAT / VPN" line is the load-bearing
  expectation-setter and now sits in front of every reader.
* **"Got a config that breaks it?" section** — second-from-bottom
  CTA pointing at [`BUG_REPORTING.md`](BUG_REPORTING.md) with the
  three-step workflow (sanitise → submit → fixture lands in test
  matrix).  Fixture submissions are the highest-impact
  contribution this project receives; the README now frames them
  that way.
* **Contributor scaffolding kept, demoted** — the developer-
  facing "Where to go next" table, test-suite invocation, and
  Layout block all moved under a "For contributors" heading
  below the operator content.  Nothing removed; reordered for
  audience.

#### What this wave does NOT do

* **No asciinema recording / animated GIF.**  The static
  before/after in the "See it in 10 seconds" section is the
  equivalent for a text README; the runnable `docker run ...
  python tools/demo.py` is the dynamic counterpart.  An
  asciinema upload is a follow-up if operators ask for it.
* **Per-vendor README sections.**  Per-vendor reference lives
  in [`docs/vendors/`](docs/vendors/) (Phase 5 deliverable);
  the README points there rather than duplicating.
* **Versioned `docker run` examples beyond `:0.1.0`.**  The
  README pins to `:0.1.0`, the same tag the Phase 9 soft-launch
  publishes.  Until that tag pushes, operators can substitute
  `:latest` or `:0.1.0-rc1` (already on GHCR from Phase 6).

### Public release plan — Phase 4: demo + walkthroughs

Phase 4 from [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) — the
30-second "show me what this does" path that operators see before
they read any docs.

#### `tools/demo.py`

One-command cross-vendor translation, no setup required (no devices,
no FastAPI server, no fixture files on disk — just `pip install
netcanon` and run).  Four scenarios baked in:

* `cisco__junos` — Cisco IOS-XE -> Juniper Junos (DC leaf:
  VLANs + interfaces + DNS / NTP + static route)
* `fortigate__mikrotik` — FortiGate -> MikroTik RouterOS
  (branch firewall: DNS + interfaces + DHCP pools)
* `aruba__arista` — Aruba AOS-S -> Arista EOS (switch refresh:
  VLAN-centric grammar -> per-port switchport)
* `opnsense__junos` — OPNsense -> Juniper Junos (edge migration
  with Tier-3 boundary on display: `<filter>` / `<nat>` /
  `<ipsec>` deliberately deferred)

Each scenario uses an embedded synthetic config (~10-25 lines).
Output shows source, rendered target, and the dropped-Tier-3
banner so operators see what didn't translate.

CLI:

```
python tools/demo.py                       # default: cisco__junos
python tools/demo.py --pair X__Y           # specific pair
python tools/demo.py --list                # show available scenarios
```

The demo calls `run_plan` directly through the same codec registry
the API uses — so when operators see the demo translate correctly,
the production path translates the same way.

#### `docs/walkthroughs/` (new directory)

Narrative walkthroughs paired 1:1 with the demo scenarios.  Where
[`docs/vendors/`](docs/vendors/) are reference docs ("what does
Netcanon do for vendor X?"), walkthroughs are workflow docs ("you
have a fleet of X and want to migrate to Y -- here's the path,
the friction points, and the manual review checklist").

* [`docs/walkthroughs/README.md`](docs/walkthroughs/README.md) —
  index + format spec
* `cisco_iosxe_to_junos.md` — DC leaf migration, paradigm flip
  notes, hash-portability caveat
* `fortigate_to_mikrotik.md` — branch firewall consolidation,
  honest about the ~90-95% Tier-3 split
* `aruba_to_arista.md` — VLAN-centric -> per-port grammar
  inversion (the canonical-intermediate-model headline
  transformation)
* `opnsense_to_junos.md` — edge migration with Tier-3 boundary
  showcase (the matrix-honesty discipline made visible)

Each walkthrough has a 6-section format: Scenario / What Netcanon
does / Run the demo / Tier-3 boundary / Manual review checklist /
See also.  Intentionally short — operators get a 30-second answer
to "should I be using Netcanon for this migration?" and a 5-minute
answer to "what's the actual workflow look like?".

#### Doc cross-references

* `AGENTS.md` "See also" footer extended with `docs/walkthroughs/`
* `docs/walkthroughs/` cross-links into `docs/vendors/`,
  `docs/CAPABILITIES.md`, `docs/COMPARISON.md`, `BUG_REPORTING.md`,
  and `docs/HOW_WE_TEST.md` — every walkthrough's "See also"
  closes the loop into the matrix-honesty discipline

#### What this wave does NOT do

* **Per-fixture demo recordings (asciinema).**  Phase 7's README
  rewrite will produce the headline asciinema; this wave's `tools/
  demo.py` is the underlying artefact the asciinema records.
* **HTML / web-UI demo page.**  CLI-only for v0.1.0; a web demo
  page is post-launch follow-up if operator-feedback signals
  demand it.
* **Bidirectional walkthroughs** (e.g. Junos -> Cisco).  Each pair
  has 2 directions; v0.1.0 ships one direction per scenario.  The
  reverse direction works (every codec is bidirectional and
  certified) but the walkthrough narrative for each direction
  belongs to its own page.

### Public release plan — Phase 6: packaging foundation

Phase 6 from [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) — the
Dockerfile + GHCR publish workflow + PyPI Trusted Publishing
workflow that turn a release tag into actual published artefacts.

#### Dockerfile (multi-stage, non-root, signed, healthcheck'd)

* **Multi-stage build.**  Stage 1 (`builder`) compiles wheels with
  `build-essential` + `libffi-dev` + `libssl-dev`; stage 2 installs
  prebuilt wheels with `pip install --no-index` (no compilers in
  runtime, no network during the runtime layer).
* **Base image** `python:3.13-slim-bookworm` — broad wheel support
  for paramiko / cryptography / pydantic-core; ~150MB before the
  netcanon install.
* **Non-root `app` user** (uid=1000, gid=1000) — file writes go
  through the bind-mounted volumes only.
* **Volume slots** `/app/configs` (backup output) + `/app/data`
  (jobs / devices / schedules root, mirrors `NETCANON_DATA_DIR`
  semantics).
* **`/app/definitions`** baked into the image (per-vendor
  device-definition YAMLs are tracked content, not operator state
  — they ship with the image rather than bind-mounted).
* **`HEALTHCHECK`** every 30s on `GET /health` via `curl -fsS`;
  start-period 10s; 3 retries before marking unhealthy.
* **OCI labels** for image discovery + provenance (title /
  description / source / documentation / licenses / vendor).

#### `.dockerignore`

Excludes tests, configs, devices, schedules, jobs, docs, .git,
build artefacts, .venv, the operator-local backup dir from the
Phase 1 history rewrite.  Whitelists `README.md` (the Dockerfile
COPYs it for `pyproject.toml`'s readme field).

#### `.github/workflows/docker-publish.yml`

Triggers on `v*.*.*` tag push (incl. `-rc`/`-alpha`/`-beta`
pre-releases).  Pipeline:

1. Build via buildx (cache via `type=gha`).
2. Push to GHCR (`ghcr.io/netcanon/netcanon`) with semver tags +
   `latest` on the default branch.
3. Cosign keyless sign every published tag via Sigstore + GitHub
   OIDC (no long-lived keys in the repo).
4. Generate SBOM (SPDX JSON) via syft; upload as workflow
   artefact.
5. Attach SBOM as a cosign attestation on the image digest.
6. Post-publish smoke test: `cosign verify` against the published
   digest with the GitHub Actions OIDC issuer + repository
   identity.

#### `.github/workflows/pypi-publish.yml`

Triggers on `v*.*.*` tag push.  Pipeline:

1. Build sdist + wheel via `python -m build`.
2. Validate metadata via `twine check`.
3. Upload distribution as a workflow artefact.
4. Publish to PyPI via Trusted Publishing (`pypa/gh-action-pypi-publish`)
   — no API token in the repo; OIDC-bound to the `pypi`
   environment + the repo identity declared on PyPI's side.

#### `/health` endpoint

[`netcanon/api/routes/health.py`](netcanon/api/routes/health.py) —
new lightweight readiness probe at `GET /health` (no `/api/v1`
prefix per orchestrator convention).  Returns
`{"status": "ok", "version": "<package version>"}` from
`importlib.metadata.version("netcanon")` with `"unknown"` fallback
for editable / source-only installs.

Tests: [`tests/integration/test_health_api.py`](tests/integration/test_health_api.py)
— 5 tests covering 200 status / response shape / Content-Type /
no-auth-required / version-is-string.  All pass; no regressions
in pre-existing test tiers.

#### Local build + smoke test (verified)

* `docker build -t netcanon:dev .` — built clean, 373MB image.
* `docker run -d -p 127.0.0.1:8765:8000 netcanon:dev` — startup
  in ~5s; loads 7 device definitions + 54 target profiles.
* `curl http://127.0.0.1:8765/health` →
  `{"status":"ok","version":"0.1.0"}`.
* `curl -X POST .../api/v1/sanitize -F source_vendor=aruba_aoss
  -F config=@... -F dry_run=true` → 10 substitutions, identical
  output to the CLI invocation (proves Phase 4.5 sanitiser
  pipeline works inside the container).
* `docker inspect` → `Health: healthy`, exit=0 from the probe.

#### Bug caught by local verification

The first build attempt crashed at startup with
`FileNotFoundError: Definitions directory not found: /app/definitions`.
The Dockerfile's `pip install` brings in the `netcanon` Python
package but the per-vendor `definitions/` directory at the repo
root isn't packaged with it (deliberately — those are
operational-grade YAMLs, not Python source).  Fix: explicit
`COPY definitions/ /app/definitions/` in the runtime stage.

This is the kind of bug that would have shipped to GHCR if we'd
trusted the CI build without local verification — operators
pulling the image would have hit immediate startup crashes.
Resolved before commit.

#### What you (operator) do for the first release

1. **Register PyPI Trusted Publisher** at
   https://pypi.org/manage/account/publishing/ — workflow file
   name `pypi-publish.yml`, environment name `pypi`.
2. **Create the `pypi` GitHub Actions environment** in repo
   settings (Settings → Environments → New environment → `pypi`).
3. **Push a release tag**: `git tag v0.1.0-rc1 && git push origin
   v0.1.0-rc1`.  Both workflows trigger automatically.
4. **Verify after publish** (~5 min later):
   * `docker pull ghcr.io/netcanon/netcanon:v0.1.0-rc1`
   * `docker run -p 8000:8000 ghcr.io/netcanon/netcanon:v0.1.0-rc1`
   * `curl http://localhost:8000/health`
   * `cosign verify ghcr.io/netcanon/netcanon:v0.1.0-rc1
     --certificate-identity-regexp "https://github.com/netcanon/netcanon"
     --certificate-oidc-issuer "https://token.actions.githubusercontent.com"`
   * `pip install netcanon==0.1.0rc1` (Trusted Publishing accepts
     pre-release tags).

#### What this wave does NOT do

* **Multi-arch builds** (`linux/arm64` for Apple Silicon / Pi
  hosts).  v0.1.0 ships `linux/amd64` only; multi-arch is a
  Phase 7 / post-launch follow-up.
* **Distroless base image.**  Distroless requires more careful
  dependency surgery (paramiko / cryptography pull in
  libffi / libssl + glibc); the size win (~50MB) isn't worth the
  fragility at v0.1.0.
* **Docker Hub mirror.**  GHCR only for v0.1.0; Docker Hub
  mirror is a follow-up if discovery becomes the bottleneck.
* **Reproducible build verification.**  The Dockerfile is
  reproducible-in-principle (pinned base image, pinned wheels);
  byte-identical-digest verification is a follow-up post-launch.

### AGENTS.md hard rule — review every push for PII

New hard rule codifying the discipline that surfaced from the Phase
1 PII scrub.  Applies to any push to an off-machine destination —
GitHub / GitLab / Bitbucket / GHCR / Docker Hub / PyPI, including
private repos that may later go public, including container images
and PyPI distributions.

The rule enumerates five review-scope categories:

* Operator personal data (emails, names, geographic identifiers in
  commit metadata + banner / comment text + operator-tied hostname
  patterns).
* Real-world network identifiers (public WAN IPs, real hostnames +
  MACs + serials, internal-domain references).
* Encrypted secrets + key material — explicitly noting these are
  **operator-traceable even when encrypted**; the Phase 1 scrub
  found 22 BEGIN PRIVATE KEY blocks + 14 cert chains + 48 ENC
  blobs in the leaked configs/ files.  Encrypted ≠ safe to publish.
* Accidentally-tracked operator backups under `configs/` /
  `devices/` / `schedules/` / `jobs/` (gitignore is not
  retroactive).
* Narrative-exposure — the meta-leak Phase 1 found in NOTICE.md /
  CHANGELOG.md prose: docs that "documented sanitisation" by
  literally naming the value being redacted ("real WAN IP `<X>`
  replaced with...").  The sanitisation narrative itself must not
  leak.

References the Phase 4.5 sanitiser as the canonical tool; flags
`git filter-repo` as the recovery tool when a secret has already
been committed (Phase 1 wave is the reference workflow).

Closes a discipline gap surfaced when the rebrand wave found 4
real backup files tracked at HEAD despite `.gitignore` covering
the directory — the rule prevents that recurring.

Includes judgment-based test-rerun guidance: sanitisation edits
can break tests in subtle ways (renamed fields, redacted-marker
introduction in narrative-asserting tests); the operator should
re-run the affected tier rather than assume sanitisation is
side-effect-free.

### Public release plan — Phase 5: operator-facing docs

Phase 5 from [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) — the
operator-facing doc surface that turns the matrix-honesty discipline
+ the Phase 4.5 sanitiser + the Tier-3 boundary into pages an
operator can actually read on landing.

#### Per-vendor "What works for me?" pages

Seven new operator pages under `docs/vendors/`, plus an index:

* [`docs/vendors/README.md`](docs/vendors/README.md) — index +
  certification table + page format definition.
* [`docs/vendors/cisco_iosxe.md`](docs/vendors/cisco_iosxe.md) —
  IOS-XE CLI (certified) + IOS-XE NETCONF (best_effort stub).
* [`docs/vendors/juniper_junos.md`](docs/vendors/juniper_junos.md) —
  Junos set-form, 5 distinct majors covered.
* [`docs/vendors/aruba_aoss.md`](docs/vendors/aruba_aoss.md) — AOS-S
  WB / WC / KB across 2530 / 2920 / 2930F / 2930M / 5400R.
* [`docs/vendors/arista_eos.md`](docs/vendors/arista_eos.md) — EOS
  4.21 through 4.30+ with MLAG / VXLAN / EVPN.
* [`docs/vendors/fortigate.md`](docs/vendors/fortigate.md) — FortiOS
  7.2.x / 7.6.x with explicit Tier-3 boundary call-out (firewall,
  NAT, VPN, UTM are deliberately deferred — Netcanon translates the
  shared-network-function subset).
* [`docs/vendors/mikrotik_routeros.md`](docs/vendors/mikrotik_routeros.md)
  — RouterOS 6.48.x and 7.18+ with renamed-port preservation.
* [`docs/vendors/opnsense.md`](docs/vendors/opnsense.md) — OPNsense
  25.x with paramiko-shell capture artifact handling.

Each page follows the same shape: TL;DR → translates well → lossy
paths → won't do → real-world fixtures → common gotchas → see-also.
LINKS rather than DUPLICATES the `CAPABILITIES.md` + `RESULTS.md`
sources of truth.

#### "How we test" page

[`docs/HOW_WE_TEST.md`](docs/HOW_WE_TEST.md) — operator-facing
narrative of the matrix-honesty discipline:

* The 4-tier test pyramid (unit / integration / e2e / desktop)
  + the 5th cross-mesh audit layer.
* The 8 variance classes (ALIGNED / CODEC_BUG / EXPECTED_LOSSY /
  EXPECTED_UNSUPPORTED / METHODOLOGY_ISSUE_under /
  METHODOLOGY_ISSUE_over / STRUCTURAL_ONLY / TRIVIAL_EMPTY).
* The trust claim, quantified ("zero CODEC_BUG cells across
  ~12,000 field-cells as of this commit").
* The honest follow-up: "the audit only covers cells we have
  fixtures for — submit a fixture that surfaces a path we don't
  yet test."

This is the page Phase 7's README rewrite will lean on for the
trust-signal lede.

#### Troubleshooting page

[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — diagnostic
flowchart for "I tried to translate a config and the result isn't
what I expected":

* Step 1: Read the migrate page banners (Tier-3 / unsupported-paths /
  lossy-paths) — most "missing content" questions answer here.
* Step 2: Is it actually a CODEC_BUG?  Symptoms that suggest yes
  vs no (the latter list is a feature: "this looks like a bug but
  isn't" patterns).
* Step 3: How to file a CODEC_BUG (delegates to BUG_REPORTING.md).
* Common error patterns + diagnoses (VLANs disappearing,
  hash-as-review-comment by design, LAG name reconciliation,
  paramiko-shell capture artifact, Tier-3 surface didn't translate).

#### `BUG_REPORTING.md` — the canonical fixture-submission workflow

[`BUG_REPORTING.md`](BUG_REPORTING.md) — top-level operator-facing
doc covering sanitise → verify → submit:

* Sanitise via the Phase 4.5 helper (CLI or HTTP API; both shown
  with concrete invocation snippets).
* Field-typed redaction table.
* Sanitiser limitations documented (sub-lossless round-trip;
  banner / comment text not redacted; IPv6-public deferred).
* Bug-report template requirements with sanitisation-check
  enforced via `bug_report.yml` checkboxes.
* Fixture-submission template requirements with provenance +
  licence confirmation enforced via `fixture_submission.yml`.
* SLA: 48hr triage, 7-day reproduction, fix wave, CHANGELOG
  credit.

This unblocks the bug-report friction collapse — operators go from
"hand-redact every line" to "30-second `curl -F` workflow."

#### AGENTS.md additions (operator-facing-doc discipline)

* New row in the Documentation Sync Checklist: "user-facing feature
  ships or changes" → update the relevant operator-facing docs
  (`docs/vendors/<vendor>.md`, `docs/CAPABILITIES.md`,
  `BUG_REPORTING.md`, `docs/TROUBLESHOOTING.md`,
  `docs/HOW_WE_TEST.md`).
* New hard rule: "Never ship a user-facing feature or capability
  change without updating the operator-facing docs that describe
  it."  Rationale: operator-facing prose drifts faster than code;
  "the docs lied to me" is the failure mode this rule prevents and
  the matrix-honesty discipline depends on.
* "See also" footer extended with the four new operator-facing
  docs (BUG_REPORTING + HOW_WE_TEST + TROUBLESHOOTING +
  vendors/).

#### What this wave does NOT do

* **Per-codec round-trip regression-guard suite for the
  sanitiser** — the plan mentioned running every real-capture
  fixture through `parse → sanitise → render → parse → assert no
  real-IPs/hashes/secrets remain`.  Phase 4.5 covered the Aruba
  pattern; expanding to all 9 codecs is a follow-up wave.
* **Walkthroughs** — `docs/walkthroughs/` (Cisco → Aruba migration,
  FortiGate → MikroTik, etc.) is Phase 4 / Phase 7 territory.
  Today's per-vendor pages are reference docs, not narrative
  walkthroughs.
* **Failure-mode showcase** — concrete examples of Tier-3 inputs
  with their banner output ("here's what FortiGate UTM looks like
  when you try to translate it; the operator sees this honest
  Tier-3 banner") is Phase 7 README content.

### Public release plan — Phase 4.5: sanitization tooling

Phase 4.5 from [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) — the
sanitization helper that gives operators a concrete invocation path
for the bug-report workflow (`BUG_REPORTING.md`, deferred to Phase 5,
depends on this existing).

The architecture is **integrated multi-invocation** (single source of
truth, three invocation paths) per the plan:

* **`netcanon.tools.sanitize` Python module** — the actual logic.
  Parses raw config via the registered codec, walks the canonical
  intent applying field-typed redactions, re-renders in the same
  vendor's format.  Counter-per-session stable: same input value
  always maps to the same redaction across the whole config (so
  cross-references survive — a hostname referenced 5 times gets the
  same redacted value 5 times).
* **CLI subcommand `netcanon sanitize`** (`netcanon/cli.py`) — for
  operators NOT running the FastAPI server (one-shot
  `pip install netcanon` users, CI / scripting).  Registered as
  `[project.scripts]` in `pyproject.toml`.
  ```
  netcanon sanitize -i my-config.txt -o sanitised.txt \
      --source-vendor cisco_iosxe_cli
  ```
* **HTTP API endpoint `POST /api/v1/sanitize`**
  (`netcanon/api/routes/sanitize.py`) — for operators running the
  server (Docker, embedded desktop, deployed instance).  Multipart
  form upload; returns text/plain sanitized config (default) or JSON
  audit (`dry_run=true`).
  ```
  curl -X POST http://localhost:8000/api/v1/sanitize \
      -F "source_vendor=cisco_iosxe_cli" \
      -F "config=@my-config.txt" \
      -o sanitised.txt
  ```

#### Field-typed redactions (counter-per-session stable)

| Canonical field | Replacement |
|---|---|
| `CanonicalIntent.hostname` | `device-N` |
| `CanonicalIntent.domain` | `example-N.test` |
| Public IPv4 anywhere | RFC 5737 docs ranges (192.0.2.x / 198.51.100.x / 203.0.113.x) |
| Private IPs (RFC 1918, ULA, link-local, loopback, multicast, CGNAT 100.64/10) | Preserved |
| `CanonicalLocalUser.hashed_password` | Format-preserving fake (Junos `$9$`, FortiGate `ENC`, crypt `$5$`/`$6$`, bcrypt `$2y$`, Cisco type-7 hex, Aruba SHA-1 hex) |
| `CanonicalSNMP.community` | `public_redacted_N` |
| `CanonicalSNMPv3User.auth_passphrase` | `REDACTED-AUTH-N` |
| `CanonicalSNMPv3User.priv_passphrase` | `REDACTED-PRIV-N` |
| `CanonicalRADIUSServer.key` | `REDACTED-RADIUS-N` |
| `CanonicalInterface.description` | `description redacted` |
| `CanonicalDHCPPool.dns_servers` (public entries) | docs range |
| `CanonicalStaticRoute.gateway` (public) | docs range |
| `CanonicalIntent.dropped_tier3_sections` | Stripped entirely |

#### `--dry-run` mode

Both CLI (`--dry-run` flag) and HTTP API (`dry_run=true` form field)
support audit-only mode: returns the full substitution table without
writing the rendered output.  Critical for trust — the operator
previews every replacement before committing.

#### Tests

* `tests/unit/tools/test_sanitize.py` (29 tests) — every redaction
  category (hostname / IPv4 public + private + docs + CGNAT /
  interface description / hash format-preserving for 5 prefix
  families / SNMP community + v3 / RADIUS / static routes / Tier-3 /
  counter stability / sanitize-purity / unknown-codec error path).
  Plus end-to-end against a real-capture Aruba fixture.
* `tests/unit/test_cli.py` (8 tests) — argparse + dry-run + write
  output + error handling + argv-list invocation.
* `tests/integration/test_sanitize_api.py` (7 tests) — HTTP endpoint
  contract (default text/plain / dry_run JSON / 400 unknown vendor /
  422 missing fields / X-Netcanon-Substitution-Count header /
  library-vs-HTTP consistency).

44 new tests; full unit + integration tiers pass clean (no
regressions in pre-existing 3,400+ tests).

#### Limitations (documented in module docstring)

* **Round-trip is sub-lossless.**  Parse drops Tier-3 content;
  render emits only what the codec models.  Sanitized output is the
  supported subset, not byte-identical with the original.
  Acceptable for bug reports — operators usually don't want to
  share Tier-3 content (firewall, NAT, VPN, QoS) anyway.
* **Banner text + raw comments not redacted.**  Not visible to the
  field-typed walk; most get parse-and-ignored.  Future enhancement
  could add a text-level post-render sweep for these surfaces.
* **One IPv6-public-redaction edge case** — current implementation
  redacts IPv4 only.  IPv6 addresses are preserved verbatim.
  IPv6-public detection + redaction is a follow-up (uses
  `ipaddress.IPv6Address` + RFC 3849 `2001:db8::/32` documentation
  range).

#### What this wave does NOT do

* **Web UI wrapper at `/sanitize`** — deferred to v0.2.0 contingent
  on operator-feedback signals showing the friction is real.  Same
  shared library; thin presentation layer if added.
* **Per-fixture round-trip regression-guard suite** — the plan
  mentioned running every real-capture fixture through
  `parse → sanitise → render → parse → assert no real-IPs/hashes/
  secrets remain`.  The end-to-end fixture test covers the Aruba
  pattern; expanding to all 9 codecs is a Phase 5 follow-up under
  the `BUG_REPORTING.md` workflow that depends on this.

### Public release plan — Phase 2: project identity foundation

Phase 2 from [`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) —
establish the project identity surfaces operators encounter before
they read any code.  All in-repo deliverables; the GitHub-side
surfaces (repo description, Topics) are documented for the operator
to apply when the repo goes public.

* **Tagline locked.**  *"Multi-vendor network config translator with
  a verifiable cross-vendor audit."*  Captures action, scope, and
  differentiator in 78 chars.  Applied to:
  * `pyproject.toml` `description` field (replaces the older
    "backup and translation engine" phrasing)
  * `README.md` header (replaces the equivalent line + adds a
    one-paragraph elevator pitch with the explicit vendor list,
    Tier-3 boundary link, and `docs/COMPARISON.md` pointer)
* **`docs/IDENTITY.md`** (new) — source-of-truth for tagline,
  GitHub repo description (extended 174-char form for the About
  section), GitHub Topics list (13 topics mirroring
  `pyproject.toml` keywords), and the logo design brief.  When
  the repo goes public, the operator copies the description +
  Topics from this doc to GitHub Settings.
* **`docs/COMPARISON.md`** (new) — positioning vs adjacent tools
  (Batfish, Capirca / Aerleon, NAPALM, Netmiko / Nornir, Ansible
  network modules, NetBox / Nautobot, ciscoconfparse).  Comparison
  table + "where we compete vs where we're complementary vs what
  we won't do" sections.  Surface area for operators arriving from
  "I'm looking for a Capirca alternative" — gives the
  matrix-honesty discipline a positioning frame.
* **Logo brief** (in `docs/IDENTITY.md`) — three concept directions
  (mosaic cell / N letterform / network constellation) with
  operator-tool visual constraints (deep slate primary + amber
  accent; geometric sans wordmark; 16×16 favicon legibility; no
  clichés).  Recommends Direction A (mosaic cell — ties to the
  matrix-honesty cell metaphor).  Logo not yet commissioned;
  brief is the spec when ready.  Includes a starter Midjourney
  prompt for AI-generated drafts.
* **`AGENTS.md` "See also" footer** updated with both new docs.

#### What this wave does NOT do

* **Set the GitHub repo description / Topics.**  Those are GitHub
  Settings actions; documented in `docs/IDENTITY.md` for the
  operator to apply when the repo goes public.
* **Commission a logo.**  Brief is the spec; actual logo
  generation is a separate workflow (designer / Midjourney /
  in-house).
* **Rewrite the README.**  Phase 7 of the release plan is the
  full README rewrite (asciinema, before/after example, full
  matrix-honesty trust signal).  This wave updates the tagline
  + elevator pitch only.

### Public release plan — Phase 1.5: package directory + import + env-var rename

The Phase 1 wave deliberately deferred the directory rename to keep
the diff scope-clean.  This wave executes it.  No code-behaviour
changes; pure structural rename + import path + env var prefix.

#### What renamed

* **Package directories** (via `git mv`):
  * `netconfig/` → `netcanon/`
  * `netconfig_desktop/` → `netcanon_desktop/`
* **Import paths** in 352 files (1,508 `netconfig` references at
  word boundaries → `netcanon`; 114 `netconfig_desktop` references
  → `netcanon_desktop`).  Word-boundary regex protected
  `docs/archive/netconfigreport.txt` references from accidental
  rewrite.
* **Env var prefix** (20 occurrences): `NETCONFIG_*` → `NETCANON_*`
  in `.env.example`, `netcanon/config.py`,
  `netcanon_desktop/preferences.py`, and operator-facing prose in
  `AGENTS.md` + CHANGELOG.  This IS a breaking change for any
  operator with shell scripts or `.env` files using `NETCONFIG_*`
  — it ships pre-public so no real users are affected.
* **`pyproject.toml`** structural fields: `[tool.setuptools.packages.find]
  include = ["netcanon*", "netcanon_desktop*"]`,
  `[tool.setuptools.package-data] netcanon = [...]`,
  `[tool.coverage.run] source = ["netcanon"]`.
* **`localStorage` keys** (web platform): `netconfig.theme.v1` →
  `netcanon.theme.v1` and `netconfig.activeJob` →
  `netcanon.activeJob`.  Pre-public; no real-user state migration
  required.  The `v1` suffix is preserved as the migration anchor
  for future schema changes.
* **Logger name**: `logging.getLogger("netconfig")` →
  `getLogger("netcanon")` (one occurrence, plus its assertion in
  `tests/unit/test_logging_config.py`).
* **Log filename**: `netconfig.log` → `netcanon.log` under
  `%APPDATA%\Netcanon\` on Windows desktop.

#### Deliberately preserved

* **`docs/archive/`** (5 files) — historical reports.  Their
  reference to "netconfig" reflects project state at archive time;
  rewriting would falsify the historical record.  Future
  contributors reading the archive understand the rename happened
  in this wave; no need to retroactively rewrite the archive.
* **`docs/archive/netconfigreport.txt`** filename — same rationale.
  The word-boundary regex `\bnetconfig\b` correctly skipped this
  filename during the substitution pass.

#### Test verification

Reinstalled editable package (`pip install -e .`) — `netcanon
0.1.0` builds + installs cleanly.  PEP 639 license-classifier
collision (the deprecated
`License :: OSI Approved :: MIT License` classifier alongside the
new `license = "MIT"` field) was caught at install time and
removed from `pyproject.toml`.  Unit + integration tiers pass
clean post-rename — every import resolved correctly under the new
package name.

#### Outstanding follow-ups for the public release

* Phase 1's "history rewrite" is **already complete** (separate
  wave; ran `git filter-repo` for blob + commit-message text +
  author-email scrub + `configs/` purge).  The Phase 1 entry's
  "Pending" wording is historically accurate — the rewrite landed
  shortly after.
* Local git config still holds the personal author identity for
  this clone; future commits in this repo will reintroduce it
  unless operator runs `git config user.email
  "noreply.netcanon@gmail.com"` + `git config user.name "Netcanon
  contributor"` (repo-local; doesn't touch global config).

### Public release plan — Phase 1 pre-flight + rebrand to Netcanon

First pass at the public-launch pre-flight checklist from
[`docs/RELEASE_PLAN.md`](docs/RELEASE_PLAN.md) Phase 1, plus the
project rebrand surfaced by the name-conflict check in the same
checklist.  No code-behaviour changes; brand + structural
artefacts + PII scrub.

#### Pre-flight artefacts authored

* **`LICENSE`** — MIT.  Vendor-tooling space is overwhelmingly
  permissive-licensed (Netmiko, NAPALM, Nornir all MIT).
* **`CODE_OF_CONDUCT.md`** — Contributor Covenant 2.1, fetched
  verbatim from `contributor-covenant.org` (CC BY 4.0; standard
  OSS template).  Enforcement contact uses an `OWNER/REPO`
  placeholder to swap before public launch.
* **`CONTRIBUTING.md`** — substantive contributor guide; lifts
  from `AGENTS.md`'s doc-sync checklist +
  `docs/adding-a-canonical-field.md`.  Walks the three
  contribution paths (fixture / codec / canonical field) and
  points at matrix-honesty as the project's North Star.
* **`SECURITY.md`** — extended with two new sections:
  * "Reporting a Vulnerability" — uses GitHub's private
    vulnerability reporting flow; no email contact required.
  * "Supply-Chain Integrity (forward-looking)" — documents
    cosign + SBOM + Trusted Publishing items planned for Phase 6.
* **`.github/PULL_REQUEST_TEMPLATE.md`** — references the
  doc-sync checklist + the matrix-honesty self-check.
* **`.github/ISSUE_TEMPLATE/`** — 4 forms: `config.yml` (blank
  issues disabled + Capabilities / Contributing / private
  security advisory routing), `bug_report.yml` (sanitization
  required), `feature_request.yml` (in-scope vs Tier-3-deferred
  guidance), `fixture_submission.yml` (separate from bug
  reports — the fixture IS the contribution).
* **`.github/workflows/ci.yml`** — minimal CI: pytest unit +
  integration tiers across Python 3.11 / 3.12 / 3.13, plus
  sdist + wheel build with `twine check`.  E2E + desktop tiers
  deferred to a follow-up CI wave.
* **`pyproject.toml`** — extended with PyPI-required metadata:
  dist name (`netcanon`), license (MIT), readme, authors,
  keywords, classifiers, `[project.urls]` block (all
  `OWNER/REPO`-templated).

#### Rebrand: NetConfig → Netcanon

The pre-flight name-conflict check found `netcanon` taken on
PyPI (squatter) and `github.com/netcanon` claimed.  After
scoring candidates against availability + collision +
on-brand-ness, **Netcanon** won: 8 letters, fully available
across PyPI / GitHub / Docker Hub / relevant TLDs, and the name
carries the project's defining discipline ("canon" =
canonical-intermediate model + authoritative matrix-honesty
reference).

* **181 substitutions** across 76 tracked files: `NetConfig` →
  `Netcanon` in prose, page titles, copyright lines, mutex
  names, installer scripts.
* **PyPI dist name** flipped: `name = "netcanon"` in
  `pyproject.toml`.
* **Self-reference** `desktop-build = ["netcanon[desktop]"]`
  updated.
* **`pip install netcanon`** → `pip install netcanon` in
  install instructions (2 occurrences).

Deliberately **not yet renamed** (deferred to Phase 1.5 to keep
this wave's diff scope-clean):

* Python package directories `netcanon/` and
  `netcanon_desktop/` (and all import paths).
* Env var prefix `NETCANON_*` (operator-facing; rename =
  breaking change for any existing shell scripts).

#### PII scrub

Pre-flight real-IP / personal-identifier audit surfaced multiple
narrative-exposure points + an incomplete sanitization in a
public fixture.  Scrubbed:

* **Public fixture leak fixed.**
  `tests/fixtures/real/fortigate/user_contrib_fg100e_fos7213.conf`
  was supposed to have all real-domain occurrences sanitized
  to `example.test` per `NOTICE.md`'s claim, but 6 occurrences
  remained (lines 3827 / 28216 / 28220 / 28236 / 28495 /
  28750).  An additional bare `*.lan` form was also
  undocumented.  Both now replaced with the claimed sanitized
  values.
* **Narrative-exposure scrub.**  `NOTICE.md`, `CHANGELOG.md`,
  `CROSS_MESH_RESULTS.md`, `RESULTS.md`,
  `phase4_findings_*.md`, `user_smoke_findings.md`, and
  `_phase4_runs/latest.json` all literally NAMED the real
  values they claimed to have sanitized ("real WAN IP `<IP>`
  replaced with...").  Replaced with redaction markers
  (`[redacted-email]`, `[redacted-domain]`,
  `[redacted-WAN-IP]`) in 42 narrative occurrences.

#### Live operator backups untracked

`git rm --cached` of 4 files in `configs/` that were tracked at
HEAD despite `.gitignore` covering the directory (gitignore is
not retroactive — files in the index stay tracked):

* Two empty Cisco backup placeholders.
* One 491-line Cisco config (2 type-8/9 password hashes).
* One 35,095-line FortiGate config (48 ENC encrypted secrets,
  22 BEGIN PRIVATE KEY blocks, 14 certificate blocks, 4 SSH
  public keys, 46 MAC addresses, 5 email addresses, the
  operator's real WAN IP).

Files remain in the working tree (operator's local backups);
they are no longer in the git index.  **History still contains
them** — the next wave (history rewrite via `git filter-repo`)
closes that gap.

#### Findings surfaced for follow-up

* **Author metadata leak.**  `git log --format='%ae'` shows 352
  of 353 historical commits authored by a personal `gmail.com`
  address.  History rewrite via `git filter-repo
  --email-callback` is the next wave's main task.
* **Real-IP audit otherwise clean.**  Outside the configs/
  files now untracked, every "looks-public" IP in the working
  tree is either RFC 5737 documentation range, well-known
  public DNS/NTP retained as fixture grammar, or sourced from
  public corpora (Batfish, HPE Community, etc.) with
  documented provenance in `tests/fixtures/real/NOTICE.md`.
* **Project-name conflicts.**  PyPI: `netcanon`,
  `netcanon-translator`, `net-config` all taken (squatters).
  GitHub `/netcanon` claimed.  Resolved by rebrand.
* **44 untracked phase4-run JSONs** in
  `tests/fixtures/real/_phase4_runs/` contain PII narrative
  refs.  Already gitignored (`.gitignore` line 68 carves out
  `latest.json`); local-only ephemera, no commit-leakage risk.
  Operator may delete locally as a separate cleanup.

#### What this wave does NOT do

* **Git history rewrite.**  Pending; needs `filter-repo`
  invocation to (a) scrub `configs/Fortigate` +
  `configs/Cisco` from all historical commits, (b) replace
  personal email in author/committer metadata across all 352
  commits, (c) replace `[redacted-domain]` /
  `[redacted-WAN-IP]` / `[redacted-email]` blob text in
  history.  Destructive but safe — no external clones exist.
* **Package directory rename.**  `netcanon/` → `netcanon/`
  (and `netcanon_desktop/` → `netcanon_desktop/`) is Phase
  1.5.

Test state post-rebrand: unit + integration tiers pass clean,
no regressions from the substitution pass.

### Added (Desktop Preferences mini-wave)

The desktop-parity audit identified 7 actionable items in the
"necessary differences" category — desktop-platform-specific surfaces
the web platform doesn't need.  This wave addresses them as a coherent
feature so operator workflow on the desktop matches the configurable
surface that the web platform exposes via `NETCANON_*` env vars.

* **Item 1 — `DesktopPreferences` model** (`netcanon_desktop/preferences.py`):
  Pydantic model with optional path overrides (`configs_dir`,
  `definitions_dir`, `data_dir`), `port` (1024–65535 spinbox range),
  `open_in_editor` toggle, and a forward-compatible
  `open_browser_on_start` field.  `load()` is corruption-tolerant —
  malformed JSON returns factory defaults so the desktop never refuses
  to start because of a botched preferences file.
* **Item 2 — Preferences dialog UI** (`netcanon_desktop/preferences_dialog.py`):
  PySide6 `QDialog` with browse buttons, port spinner, toggles, and an
  "Open Configs Folder" convenience button.  Each interactive widget
  carries `setObjectName()` per the `pref-dialog-<field>-<action>`
  convention (the desktop equivalent of `data-testid`).
* **Item 3 — `Settings.data_dir` field + `effective_data_dir` property**
  (`netcanon/config.py`): backward-compatible explicit override for
  the data-root directory holding `jobs/`, `schedules/`, `devices/`.
  When `None`, falls back to the historical `configs_dir.parent`
  derivation.  `netcanon/main.py` reads through `effective_data_dir`
  at all four lifespan call sites; an `inspect.getsource` regression
  guard catches future copy-pastes of the old derivation.
* **Item 4 — Tray menu surface** (`netcanon_desktop/tray.py` +
  `app.py`): four-item menu (Show / Preferences… / Open configs folder /
  Quit).  The two new callbacks are optional kwargs so existing tray
  construction stays backward-compatible.
* **Item 5 — Single-instance enforcement** (`netcanon_desktop/single_instance.py`):
  Windows named-mutex guard (`Global\NetcanonSingleInstance_v1`)
  prevents a second `netcanon_desktop` from launching and silently
  failing on the port-bind.  No-op on non-Windows so test suite runs
  on Linux / macOS.
* **Item 6 — Documentation** (`netcanon_desktop/README.md`): module
  layout updated to list all five new files; settings table extended
  with the data-root row; new Preferences and Uninstall behaviour
  sections.
* **Item 7 — Cross-cutting docs** (`AGENTS.md`): Platform-Specific
  Exceptions section gains the Preferences dialog + single-instance
  entries; new "Deliberately omitted (preventive)" subsection
  documents telemetry / auto-update / file associations / crash
  reporting as explicit OUT OF SCOPE so future contributors don't add
  them speculatively.

The audit found zero parity violations — these are necessary
desktop-only surfaces (the web platform's equivalents are the
`NETCANON_*` env vars and the inability to launch two web servers
without picking a different port).  The wave preserves that parity by
giving desktop operators an equivalent configuration surface to what
web operators already have.

New tests added: 47 in 4 new modules (`test_preferences.py` 16,
`test_preferences_dialog.py` 16, `test_single_instance.py` 9,
`test_data_dir_resolution.py` 6) plus 14 in 3 extended modules
(`test_settings.py` +5, `test_tray.py` +4, `test_app.py` +5).  Suite
state for the unit + integration + desktop tiers post-wave: 3403
passed, 57 skipped, 0 failed.  No matrix regen.  No codec touch.
Pipeline-stage signatures unchanged.

### Validation cleanup wave (post-`170a2c2` audit follow-ups)

After the comprehensive validation pass (commit `170a2c2`), the
matrix-honesty discipline applied to the validation findings
themselves surfaced a 21-item open-work inventory.  This batch
addresses the actionable subset:

* **Commit `07086b1`** — `cisco_iosxe_cli` `/routing-instances/instance`
  declaration moved from `UnsupportedPath` to `LossyPath`.  Old
  declaration claimed "wire-up deferred" but parse + render had been
  shipping; Wave 10β-B (commit `40de39c`) re-flipped the per-pair
  YAML disposition months prior.  Codec capability matrix was
  contradicting both the codec's own code AND the cross-vendor
  expectation YAML.  6 regression-guard tests pin the corrected
  declaration shape.
* **Commit `e7c5378`** — `docs/CAPABILITIES.md` table row for the
  same field aligned with the corrected matrix.
* **Commit `298e1ca`** — Four historical `*.txt` files (12-lens
  architectural analysis, companion review report, auto-actionable
  triage, vendor-config research notes) moved from top-level to
  `docs/archive/` with a `README.md` explaining provenance and the
  current-state authoritative-source pointers.
* **Commit `7ffa1c5`** + this commit — Two E2E tests (originally
  reported as "pre-existing flakes" by Wave 11-A and Wave 7c-G)
  diagnosed as deterministic dead-premise failures: both depend on
  Cisco `Loopback0` flowing through Aruba's auto-drop path, but
  commit `5f4855a` (May 2026) added Aruba loopback support so
  `Loopback0 → loopback1` translates cleanly with no warning and no
  auto-drop.  Skip-marked with rationale; Wave-12 follow-up to
  re-author against a target codec that genuinely cannot render
  loopbacks (or delete; the equivalent UI surfaces are exercised by
  sibling tests).
* **Commit `30beb92`** — Two new canonical `CanonicalInterface`
  fields (`dhcp_client_v6` for IPv6 DHCPv6 / SLAAC mode, and
  `tunnel_type` for GRE / EoIP / IPIP / IPSEC / VXLAN encap
  discriminator) closing two long-standing schema gaps.  Wired
  across 5 codecs each (parse + render) with `LossyPath`
  declarations on codecs without native grammar.  Junos
  switch-options sub-paths reframed from "deferred" to "documented
  architectural deferral" — same Tier-3-shape rationale (EVPN-VXLAN
  underlay primitives require deployment-topology context the
  canonical model deliberately doesn't carry).  46 new tests.

Cumulative validation cleanup: matrix integrity + capability-honesty
contracts now align across codec.py declarations, parse/render code,
cross-vendor expectation YAMLs, CAPABILITIES.md table rows, and
regression-guard tests.

Suite: 3229 → 3275 passed (+46 tests across the wave), 57 skipped
(2 newly skip-marked; pre-existing E2E that no longer have a real
target configuration), 0 failed.  Matrix delta: CODEC_BUG holds at
0; minor TRIVIAL_EMPTY shift (+41) and STRUCTURAL_ONLY shift (-56)
from the new fields routing through the trivial-empty classification
correctly on fixtures that don't exercise IPv6-DHCP or non-GRE
tunnels.

### Documented (forward-looking)

* **Commit `1fe1cfd`** — `docs/RELEASE_PLAN.md` captures the
  strategic plan for taking the project public.  Pre-flight
  checklist, maximum-bug-report-surface-area framing for the network-
  engineer audience, packaging tier strategy (Docker primary, PyPI
  secondary, MSI tertiary), concrete release sequence, what-not-to-do
  guidance, when-to-start triggers.  Forward-looking; not yet
  started.  Linked from `AGENTS.md` "See also" so post-compaction
  contexts find it cold.

### Added (Wave 11 — operator-visible notification when Tier-3 sections are dropped)

The canonical model classifies firewall_rules / nat_rules / vpn /
routing_protocols as **Tier 3 — "parse for display, never auto-render"**
(see `netcanon/migration/canonical/intent.py:39-41`).  Codec parsers
silently skipped these stanzas because there's no canonical surface
to populate.  Operators pasting a Cisco config containing
`ip access-list extended OUTSIDE_IN ... ip access-group OUTSIDE_IN in`
into the migrate page got a "successful migration" with zero
notification that ACL blocks had been dropped — exactly the silent
drop the project's matrix-honesty discipline calls out as drift.

This wave closes the notification gap from two angles:

* **W11-A — capability-matrix coverage** (commit `21a0f38`).  Three
  ACL-capable codecs that didn't declare ACL/firewall xpaths as
  unsupported now do:
  * `arista_eos`: `/access-list/extended`, `/access-list/standard`,
    `/access-list/ipv6`
  * `cisco_iosxe` (NETCONF): `/access-list`, `/firewall`
  * `cisco_iosxe_cli`: `/access-list/extended`, `/access-list/standard`,
    `/access-list/ipv6`, `/firewall`, `/nat`
  This makes the existing UI "Unsupported paths" panel surface the
  ACL/firewall/NAT gap on those codecs.  Parallel coverage with the
  5 codecs that already declared (`aruba_aoss`, `fortigate_cli`,
  `mikrotik_routeros`, `opnsense`, `juniper_junos`).  20 new
  capability-matrix regression-guard tests.

* **W11-B — parser-level Tier-3 stanza detection** (commit `c632bdc`).
  New shared helper `netcanon/migration/_tier3_detection.py` with
  per-vendor pattern sets (`_iosxe_cli`, `_fortios`, `_junos`,
  `_routeros`, `_opnsense`, plus a `_iosxe_xml` no-op stub for the
  NETCONF codec).  New `CanonicalIntent.dropped_tier3_sections:
  list[str]` field populated by every parser at entry.  Operator-
  visible UI banner in `migrate.html` ("⚠ Tier-3 sections detected
  in source") with `migrate-tier3-banner` testid.  Critical scope
  property: **the new field is OUTPUT-ONLY** — no render code path
  consumes it.  This is notification, not translation.  Firewall /
  NAT auto-translation remains explicitly out of scope (see the
  Cluster E.X / firewall-translation architectural decision in the
  Wave 9 / Cluster E.1 entries).  37 new tests.

Cumulative Wave 11 matrix delta: **zero**.  Notification-only
changes; no migration semantics altered.  Suite: 3186 → 3223 passed
(+37 tests across both sub-waves), 57 skipped, 0 failed.

Honest behaviour delta: operators pasting a Cisco/Arista config
with ACL blocks now see the dropped sections enumerated in the
migrate page UI.  Previous behavior silently dropped them with no
operator-visible signal.

### Fixed (Wave 10γ — three methodology gaps closed; matrix integrity at 91% noise reduction)

Wave 10β agents flagged three methodology gaps during their
disciplined per-source-vendor investigation.  Three Wave 10γ
agents closed all of them:

* **Sub-field cascade gap in TRIVIAL_EMPTY** (commit `2fe7902`).
  Wave 10α's TRIVIAL_EMPTY classification fired only at parent-list
  level; sub-fields of parents with rows but empty per-record data
  cascaded as `preserved` and generated false METHODOLOGY_under
  signals.  Phase 1 now records `subfields_with_data: list[str]`
  per list-parent (sorted union of sub-field names with non-empty
  data on at least one record across both sides); Phase 4's
  `actual_disposition` cascade consults it and returns
  `"trivially_preserved"` for sub-fields outside the set.  Cleared
  ~1014 false METHODOLOGY_under cells.
* **`_list_drift_summary` cap-of-5 truncation** (commit `2fe7902`).
  When 6+ records drifted in a list field, records 6+ were
  invisible to Phase 4's per-record drill-down so their sub-fields
  appeared preserved.  Cap removed entirely; display-side
  truncation in `_md_inline` (200 chars) keeps the matrix `.md`
  legible without losing data.  Surfaced 5 previously-hidden
  CODEC_BUG cells which γ-3 then resolved.
* **`cisco_iosxe` (NETCONF) target codec is a Phase 0.5 stub**
  (commit `f81f3a5`).  Render only emits openconfig-interfaces
  subtree; many fields preserve trivially because the target
  literally doesn't emit.  Capability matrix now declares 16
  top-level field xpaths + 11 granular xpaths as `unsupported`
  (the un-rendered subtrees: hostname, domain, dns_servers,
  ntp_servers, timezone, syslog_servers, vlans, static_routes,
  snmp/{community,location,contact,trap-host,v3-user}, lags,
  local_users, radius_servers, dhcp_servers, routing_instances,
  vxlan_vnis, evpn_type5_routes).  New regression-guard test
  asserts every un-rendered field is declared unsupported —
  prevents future drift between render expansion and matrix.
* **5 newly-surfaced CODEC_BUG cells** (commit `2863db8`):
  * `_canonical_lag_name` regex extended to recognise `agg<N>`
    (FortiGate aggregate) and `bond<N>` (RouterOS bonding) as
    LAG-name canonical equivalents to `ae<N>` / `Port-channel<N>`
    / `trk<N>` — Wave 9β coverage gap.
  * IPv6 link-local elision on opnsense render is intentional
    vendor schema policy (FreeBSD auto-derives `fe80::/64`
    from MAC per RFC 4862 SLAAC); 2 YAML dispositions flipped
    `good → lossy` with vendor-doc rationale.
  * cisco_iosxe_cli IPv6 scope classifier now recognises
    `fe80::/10` prefix per RFC 4291 §2.4 (case-insensitive;
    tolerant of malformed double-`::` fixtures).

### Cumulative Wave 10 (α + β + γ) matrix arc

The Phase 4 matrix-honesty audit, completed across three sub-waves:

  ALIGNED                    2298 → 1210 (-1088 — false-positive
                                          ALIGNED reclassified to
                                          TRIVIAL_EMPTY)
  CODEC_BUG                  0    → 0    (preserved through wave;
                                          γ-1 surfaced 5 hidden
                                          drifts which γ-3 closed)
  EXPECTED_LOSSY             940  → 949  (+9; small wave-9β/10γ
                                          reclassifications)
  EXPECTED_UNSUPPORTED       512  → 532  (+20; cisco_iosxe NETCONF
                                          honesty correction)
  METHODOLOGY_ISSUE_under    7382 → 705  (-6677, 91% reduction)
  METHODOLOGY_ISSUE_over     23   → 23
  STRUCTURAL_ONLY            810  → 810
  TRIVIAL_EMPTY              0    → 7736 (new class, severity ok)

Honest cell breakdown:
  Real verified preservation:          1210 cells
  Real over-claims (Wave 10β residual): 705 cells
  Test-data gaps (no fixture data):    7736 cells
  Documented lossy/unsupported:        1481 cells
  Structural / methodology delta:       833 cells
  Codec bugs:                             0 cells

Total: 11965 field-cells classified across 376 cross-mesh cells.

### Added (Wave 10α — TRIVIAL_EMPTY variance class for matrix-honesty restoration)

The Phase 4 reconciliation classifier grows from 7 to 8 variance
classes with the addition of `TRIVIAL_EMPTY` (severity `ok`).
Definition: "field is empty on both source AND target sides; no
data to validate the YAML's disposition claim against; cell is
benignly aligned by absence of data".

The class addresses a methodology-noise problem that surfaced
when Wave 9γ-A flagged ~200 candidate METHODOLOGY_ISSUE_under
cells.  Audit before Wave 10β dispatch revealed the actual
candidate count was 7382 (post-Wave-7c) — and 4169 of those were
trivially-empty cells where neither source nor target had any
data for the field, so the cell aligned by absence rather than
by real cross-vendor preservation.  These cells were generating
false "YAML over-claim" signals.

The classifier now distinguishes three actual states
(`preserved` / `drifted` / `trivially_preserved`).  When both
sides have zero data (lists with `source_count == 0 AND
target_count == 0`, dicts similarly, scalars matching `_is_empty
_zero_state`), the actual state is `trivially_preserved` and
the variance is `TRIVIAL_EMPTY` regardless of YAML disposition.

ARCHITECTURE.md "Cross-mesh fidelity audit harness" subsection
gains the 8th variance-class bullet documenting the new class.

Tooling-only change.  No codec / canonical / YAML touches.

### Fixed (Wave 10β — selective YAML re-flips on residual real over-claims)

Four parallel per-source-vendor agents walked the post-Wave-10α
residual of 1769 METHODOLOGY_ISSUE_under cells (real over-claims:
populated source data preserves through round-trip, YAML claims
lossy/unsupported).  Three findings landed:

* **`cisco_iosxe_cli → opnsense / dns_servers`** (commit `40de39c`).
  YAML claimed OPNsense codec didn't parse/emit `<dnsserver>`;
  capability stale (both directions wired in earlier wave).
  Re-flip `lossy → good`.
* **`cisco_iosxe_cli → juniper_junos / routing_instances`** plus
  7 sub-fields (commit `40de39c`).  YAML cited stale capability-
  matrix entry claiming `/routing-instances/instance` parse-and-
  ignore; cisco_iosxe_cli parse populates from `vrf definition`
  blocks (rd, RT import/export, description, l3_vni); Junos
  render wires through to `set routing-instances <name>
  instance-type vrf`.  Re-flip `unsupported → good`.
* **`opnsense → {arista, aruba, cisco_iosxe_cli, fortigate} /
  snmp`** plus mikrotik_routeros source ntp_servers / opnsense
  source dns_servers across multiple targets (commit `ab4d321`).
  Multiple SNMP sub-surface preservation paths the codec wired in
  Wave 7c hadn't propagated to expectation YAMLs.  Re-flips on 16
  trios across opnsense + mikrotik sources.
* **`fortigate_cli → {arista, cisco_iosxe_cli, opnsense} / vlans`**
  (commit `888ca19`).  Top-level `vlans` list round-trips at list+id
  level across all populated fixtures; existing reasons cited
  sub-field caveats already captured at sub-field disposition
  level.  Re-flip `lossy → good`.

Wave 10β-A (arista + aruba sources) returned no-op after
disciplined cross-fixture verification — every candidate was
justified by a real vendor wire-format constraint not exercised
by current fixtures.  Same pattern as Wave 9γ-A/B.

Cumulative Wave 10 matrix delta:

  ALIGNED                    2298 → 1479 (-819, real-truth restoration)
  CODEC_BUG                  0    → 0 (preserved through wave)
  EXPECTED_LOSSY             940  → 940
  EXPECTED_UNSUPPORTED       512  → 512
  METHODOLOGY_ISSUE_under    7382 → 1716 (-5666, 77% reduction)
  METHODOLOGY_ISSUE_over     23   → 23
  STRUCTURAL_ONLY            810  → 810
  TRIVIAL_EMPTY              0    → 6485 (new)

The ALIGNED drop reflects 819 cells correctly reclassified from
false-positive ALIGNED (trivial-empty alignment) to TRIVIAL_EMPTY.
The 5666-cell METHODOLOGY_under reduction is the matrix-honesty
win the wave was scoped to deliver.

### Methodology follow-ups identified during Wave 10β (deferred)

Three comparator/codec gaps surfaced by per-source-agent
investigation, queued as Wave 10γ candidates if pursued:

* **Sub-field cascade gap in Wave 10α** — TRIVIAL_EMPTY fires
  at parent list level only; sub-fields with empty data on
  fixtures with non-empty parent lists cascade as preserved
  (e.g. `interfaces[].switchport_mode` when interfaces list has
  rows but no row populates the switchport surface).
* **`_list_drift_summary` cap-of-5 truncation** in
  `tools/run_full_mesh.py:438-443` — when 6+ records drift, the
  6+ are invisible to the per-record drift drill-down so their
  sub-fields appear preserved.
* **`cisco_iosxe` (NETCONF) target codec is a Phase 0.5 stub** —
  render only emits openconfig-interfaces subtree; many fields
  preserve trivially because the target literally doesn't emit.
  Either complete the render wire-up (substantial) or
  reclassify the codec's CapabilityMatrix more aggressively.

### Added (Cluster E.1 — DHCP-server parse + render for arista_eos and juniper_junos)

The canonical model carries `intent.dhcp_servers: list[CanonicalDHCPPool]`
(Tier 2) and four codecs (`cisco_iosxe_cli`, `fortigate_cli`,
`mikrotik_routeros`, `opnsense`) round-tripped DHCP pools before this
wave.  Two more codecs join: `arista_eos` and `juniper_junos`.

* **arista_eos** (commit `90c093c`) — `ip dhcp pool` grammar parse +
  render.  Cisco-derived syntax with one EOS-specific addition:
  inline `range <start> <end>` (Cisco relies on `ip dhcp excluded-
  address` instead).  Parse tolerates both dotted-mask
  (`network 10.0.0.0 255.255.255.0`) and CIDR (`network 10.0.0.0/24`)
  forms; render emits dotted-mask to mirror the cisco_iosxe_cli
  convention.  Lease-time emitted as full d/h/m triple
  (`lease 0 12 0`); `lease infinite` round-trips via the DHCP
  `0xFFFFFFFF` sentinel.  Cited against Arista EOS User Manual,
  "DHCP and DHCP Relay".

* **juniper_junos** (commit `5bcc89c`) — modern `set access
  address-assignment pool` + `set system services dhcp-local-server
  group` two-stage form for render; parser also accepts the legacy
  `set system services dhcp` form (deprecated on M/MX/SRX since
  ~2010 but still valid on EX 4.x trains) so old captures still
  produce `CanonicalDHCPPool` records.  Stable pool/group names
  derived from `pool.interface` (sanitising `/` and `.` to `_`)
  with `pool<idx>` fallback by list position.  The runtime's
  network-prefix matching between groups and pools is approximated
  with an equal-name link plus a 1-to-1 fallback for hand-authored
  cross-vendor inputs with mismatched names.  Multi-`range` Junos
  pools (which the canonical single `start_ip`/`end_ip` slot
  cannot fully represent) collapse to the first range on parse;
  surplus ranges drop with a comment.  Cited against Junos OS
  Network Management — "Configuring Address-Assignment Pools".

Cumulative DHCP coverage post-Cluster-E.1:

  parse  render
  ✓      ✓      cisco_iosxe_cli   (pre-existing)
  ✓      ✓      fortigate_cli     (pre-existing)
  ✓      ✓      mikrotik_routeros (pre-existing)
  ✓      ✓      opnsense          (pre-existing)
  ✓      ✓      arista_eos        (Cluster E.1)
  ✓      ✓      juniper_junos     (Cluster E.1)
  ✗      stub   aruba_aoss        (intentional — AOS-S is a relay
                                    platform per the codec's
                                    architectural decision; render
                                    emits comment block, no native
                                    server stanza)
  ✗      ✗      cisco_iosxe       (NETCONF; OpenConfig DHCP YANG
                                    is sparse; deferred)

Matrix delta from regen (commit `5fbb106`): no CODEC_BUG
regression; ALIGNED unchanged at 2298; some EXPECTED_LOSSY /
EXPECTED_UNSUPPORTED cells shifted to METHODOLOGY_under as the
new DHCP round-trips begin exercising actual translation where
they previously trivially aligned (both sides empty
`dhcp_servers`).  Suite 3091 → 3116 passed (+25 new tests).

### Architectural decision (Cluster E.X deferred — Tier 3 → Tier 2 promotion required)

The original Cluster E plan called for adding render paths for
firewall rules, NAT rules, DHCP pools, and DNS static-host
entries across six codecs.  Audit before dispatch revealed:

1. Three of the four surfaces (`firewall_rules`, `nat_rules`,
   DNS-static) do not exist on the canonical model — only DHCP
   pools have a `Canonical*` class today.
2. `firewall_rules` and `nat_rules` are explicitly classified as
   Tier 3 — "parse for display, never auto-render" — in the
   canonical model docstring
   (`netcanon/migration/canonical/intent.py:39-40`).  The
   docstring's rationale: auto-rendering firewall semantics
   across vendor-specific zone-pair vs interface-attached vs
   stateful-vs-stateless models risks shipping configs with
   unintended security holes.

Cluster E.1 (this commit) addresses only the DHCP slice — the
single surface that is both Tier 2 and canonically modelled.
Cluster E.X (firewall, NAT, DNS-static) is deferred pending a
deliberate architectural conversation about Tier 3 → Tier 2
promotion, which would require:

* New canonical classes (`CanonicalFirewallRule`,
  `CanonicalNATRule`, `CanonicalDNSStaticHost`).
* Updates to the canonical-model docstring's tiering paragraph.
* Per-codec `CapabilityMatrix.unsupported` listings flipped
  (probably to `partial` with review-banner UI flagging).
* Render-path agents only after the schema and capability-matrix
  groundwork lands.

### Fixed (Wave 7c — long-tail cross-mesh codec bugs cleared from 42 to 0)

Seven parallel agents (one per source-vendor) walked the post-
Wave-9 reconciliation matrix and resolved every remaining
`CODEC_BUG` cell.  Cumulative matrix delta:

  ALIGNED                    2242 → 2298 (+56)
  CODEC_BUG                  42   → 0    (-42, FULL CLEAR)
  EXPECTED_LOSSY             942  → 944  (+2)
  EXPECTED_UNSUPPORTED       493  → 514  (+21)
  METHODOLOGY_ISSUE_under    7350 → 7378 (+28)
  STRUCTURAL_ONLY            876  → 810  (-66)

Notable codec fixes during the wave:

* **Cisco IOS-XE CLI: `secondary` IPv4 keyword** (commit `87b2248`,
  Agent C).  Coordinated render+parse fix at
  `cisco_iosxe_cli/render.py:259-262` and `parse.py:576-585`.
  Render now emits `ip address X.X.X.X MASK secondary` for index>=1;
  parser drops the prior primary-only guard.
* **Arista EOS: phantom-VLAN guard + `switchport trunk native vlan`
  parse symmetry** (commit `87b2248`, Agent C).  Cross-vendor trunk
  configs were re-inflating canonical VLAN records on parse round-
  trip; snapshot-and-prune now mirrors the cisco_iosxe_cli pattern.
* **Cisco IOS-XE NETCONF: SVI-to-VLAN synthesis** (commit `1b1b865`,
  Agent D).  `Vlan<N>` SVI interfaces now synthesise
  `CanonicalVlan` records via the new shared
  `transforms.project_svi_to_vlan` helper.
* **Aruba AOS-S: foreign-port-name preservation + RADIUS port grammar**
  (commits `ce9725d` Agent A, `c344200` Agent G).  Junos-shape ports
  (`xe-0/0/N`, `et-0/0/N`) now survive round-trip without range-
  shredding; `radius-server host <ip> auth-port N acct-port N`
  cumulative-update grammar accepted on parse + emitted on render
  when ports differ from AOS-S defaults.
* **Aruba AOS-S: SVI absorption ignored VRF binding on `irb.<vid>`
  interfaces** (commit `7fd8b14`, Agent B).  Render now skips
  `iface.vrf`-set entries in `iface_by_vlan_id`.
* **Juniper Junos: phantom `ae<N>` interface elision** (commit
  `2d7a7f2`, Agent E).  Junos parse materialisation loop now skips
  empty iface_state entries whose names appear in lag_state — the
  CanonicalLAG record alone carries LAG identity.  This correction
  also debunked a stale Phase 4b "interface-range collapse"
  hypothesis that had been the assumed root cause for ~3 cells.
* **Arista EOS: RADIUS render + parse path** (commit `ce9725d`,
  Agent A).  Closes a count-regression on aruba→arista where source
  RADIUS servers were being silently dropped by the Arista codec.
* **Cross-vendor list-order parity** (commit `87b2248`, Agent C).
  New `transforms._natural_port_sort_key` resolves lexical-order
  drift on `vlan.tagged_ports` / `vlan.untagged_ports` across all
  codecs that produce port-list outputs (`1/1, 1/2, 1/10` rather
  than lex `1/1, 1/10, 1/2`).
* **Arista EOS: cross-vendor LAG-name normalisation** (commit
  `ce9725d`, Agent A).  Render now accepts ae/Port-channel/Trk/
  bond/lagg shapes via shared `_normalise_lag_name_to_arista`,
  emitting them as the EOS-canonical `Port-Channel<N>` form.
* **FortiGate CLI: static-route `set comment` parser-side gap**
  (commit `1b1b865`, Agent F).  `_apply_router_static` now reads
  `set comment "<text>"` back into `CanonicalStaticRoute.description`
  (the render side was already emitting; the gap was pinned by a
  test in commit `60b6199` from an earlier wave).
* **MikroTik RouterOS: hostname whitespace policy** (commit
  `1b1b865`, Agent F).  Multi-token RouterOS identity values
  reclassified `good → lossy` for arista_eos and cisco_iosxe_cli
  targets — Arista's parser regex `\s*$` rejects multi-token names,
  Cisco IOS-XE captures only the first `\S+` token; the
  `sanitise_hostname` substitution is wire-format-correct and
  documented per HPE Aruba 2930F config guide etc.

The final 3 cells were all `interfaces[].name` count drifts on the
`cisco_iosxe → {aruba, junos, mikrotik} / kitchen_sink.xml` fixture
and reflect documented vendor-wire constraints (foreign-name stub
elision on aruba/junos; phantom `bridge1` synthesised by RouterOS
to host source-side VLAN sub-interfaces).  Reclassified `good →
lossy` with explanatory rationale (commit `ec607d8`).

### Added (Wave 7c shared utilities)

Three new helpers in `netcanon/migration/canonical/transforms.py`
landed during Wave 7c, consolidating patterns that codecs had
started growing independently:

* **`project_svi_to_vlan(intent)`** — synthesise `CanonicalVlan`
  records from L3 SVI interfaces (`Vlan100`, `irb.100`, etc.).
  Codecs whose source-format carries SVIs but not their backing
  VLAN call this as a parse post-pass.
* **`_natural_port_sort_key(name)`** — natural-sort key for
  port-name strings.  Used by `project_switchport_to_vlan` and
  the Junos parser's port-list materialisation to guarantee
  cross-vendor list-order parity.
* **`_normalise_lag_name_to_arista(name)`** in
  `netcanon/migration/codecs/arista_eos/render.py` — accepts
  ae / Port-channel / Trk / bond / lagg shapes and emits as the
  EOS-canonical `Port-Channel<N>` form.

`netcanon/migration/codecs/README.md` "Cross-codec shared utilities"
section gains entries for the two `transforms.py` helpers.

### Added (Phase 1 backup-definition expansion: Arista EOS / Aruba AOS-S / Juniper Junos)

Three new device-definition YAMLs land alongside the existing
Cisco / Fortigate / MikroTik / OPNsense backup definitions, closing
the gap between migration-codec coverage (8 vendors) and backup-
collector coverage (was 4, now 7).  Each ships with a netmiko-strategy
collector wired to the appropriate driver — `arista_eos`,
`aruba_osswitch`, `juniper_junos` — so users with real hardware in
those families can now point the backup pipeline at devices and pull
their `running-config` (or `show configuration | display set | no-more`
for Junos, where the `set`-form output maps directly onto what
`juniper_junos.parse_intent` consumes).

* **`definitions/arista/eos/4.32.yaml`** — netmiko `arista_eos` with
  the standard Cisco-style `cisco_more_paging: true` (per the hard
  rule against `terminal length 0`).  Probe regexes pinned against
  DCS / vEOS / CCS chassis families.
* **`definitions/aruba/aos-s/16.x.yaml`** — netmiko `aruba_osswitch`
  (the modern AOS-S 16.x driver; `hp_procurve` documented as the
  legacy alternate for 15.x firmware).  Manager-mode escalation via
  netmiko's `secret` credential.
* **`definitions/juniper/junos/22.x.yaml`** — netmiko `juniper_junos`
  with `cisco_more_paging: false` (Junos uses `| no-more` in the
  command itself rather than space-injection).  Probe regexes pinned
  for SRX / EX / MX / QFX `show version` shapes.

Per-vendor unit tests pin the schema, probe regexes, and codec round-
trip; per-vendor integration tests cover the POST/GET happy path with
mocked `get_collector` (per the hard rule against patching
`ConnectHandler` directly); per-vendor desktop tests confirm the
embedded uvicorn serves the new definitions.

### Added (`type_key` filename-safety constraint)

Authoring a `DeviceDefinition` with `type_key` containing `_` or `.`
now raises `ValidationError` at load time (validator
`type_key_filename_safe` on `DeviceDefinition`).  These characters are
the separators the file-store filename grammar uses
(`{type_key}_{safe_host}_{ts}.{ext}`), so a `type_key` containing
either makes the parse mathematically ambiguous — `resolve_path()`
would mis-route the file because the lazy `.+?` in the device-type
group absorbs only the leading non-underscore token.

The constraint pins the established convention (single-token
CamelCase: `Cisco`, `Fortigate`, `MikroTik`, `OPNsense`, `Aruba`,
`Juniper`, `Arista`).  BD-Aruba's initial `aruba_aoss_16.x` outlier
(commit `de8e0f3`) and BD-Arista's independent rediscovery of the
trap (commit `8c9e9d4`) confirmed the rule was load-bearing.  Both
the schema-level validator and the file-store regex (now using
`[^_.]+` for the `device_type` group instead of `.+?`) enforce the
invariant from two angles.  AGENTS.md "Hard Rules" gains a new
bullet citing the rule.

### Fixed (Wave 9 cross-mesh comparator: dict-drift false-positive + LAG-rename equivalence)

Two surgical fixes to the Phase 4 reconciliation tooling at
`tools/run_phase4_reconciliation.py` that tighten matrix integrity
without touching any codec render or parse code:

* **Wave 9α — `_subfield_drift_in_dict` audit-tooling false positive.**
  Phase 1 (`tools/run_full_mesh.py::process_cell`) was storing only
  the top-level keys of dict-typed canonical fields (`snmp`, etc.)
  as `record["source"]` / `record["target"]`, which left
  `_subfield_drift_in_dict` unable to determine whether a specific
  attribute (e.g. `snmp.community`) drifted.  It conservatively
  fell through to "drifted", inflating the CODEC_BUG count by ~11
  cells across SNMP attributes for cross-vendor pairs that were
  actually translating cleanly.  Fix: store the full source/target
  dicts so the reconciler can walk per-attribute.
* **Wave 9β — Vendor-correct LAG-rename equivalence.**  Junos
  `ae<N>`, Cisco `Port-channel<N>` (and `Po<N>`), and Aruba
  `trk<N>` are the same LAG bundle in different vendor-native
  spellings.  The comparator now treats these as equivalent for
  the field-keys in `_LAG_NAME_FIELDS = {"lags[].name",
  "interfaces[].lag_member_of"}` via a `_lag_name_equivalence`
  callable plugged into `_subfield_drift_in_list` /
  `_slice_list_subfield`.  Names not matching a documented LAG
  shape fall through to raw equality, so non-LAG drift on the
  same fields still surfaces.  Defensive on current matrix state
  (no immediate cell drops) but prevents regression as future
  YAML refreshes tighten `lags` dispositions from `lossy` back
  to `good`.

### Fixed (Wave 9γ — selective re-flip of Wave 8 over-eager `lossy` reclassifications)

After Wave 8 reclassified ~120 fields from `good → lossy` based on
per-source-vendor findings reports, three per-source agents (γ-A,
γ-B, γ-C) walked their assigned scopes to verify each flip was
justified by genuine drift in at least one fixture for the pair.
γ-A (arista + aruba) and γ-B (cisco) confirmed every Wave 8 flip
was correct.  γ-C identified six over-eager flips on
`juniper_junos -> cisco_iosxe_cli / vlans[].id`: the Wave 8
hypothesis that Junos `vlan members all` would expand to
`range(1, 4095)` on the canonical `vlans[].id` projection was
incorrect — the expansion lands on `interfaces[].trunk_allowed_vlans`
instead.  Six fixtures (5 real + 1 synthetic) confirm `vlans[].id`
preserves cleanly across this pair; YAML re-flipped to `good`.

Cumulative Wave 9 matrix delta: ALIGNED 2225 → 2242 (+17), CODEC_BUG
53 → 42 (-11), METHODOLOGY_ISSUE_under 7370 → 7350 (-20).

### Refactored (extract `_migration_helpers.py` from `migration.py`)

Final cleanup pass on the `refactor/god-file-cleanup` branch.  The
god-file audit had flagged `netcanon/api/routes/migration.py` as the
remaining oversized route file (~750 LOC mixing route dispatch with
adapter resolution, input-text resolution, capability-matrix shaping,
target-profile lookup, and override-routing predicates).  Extracted
the helpers into a sibling `_migration_helpers.py` so the route
module is closer to "thin glue" and the helpers acquire focussed
unit-test coverage without spinning up a TestClient.

* **Helpers lifted verbatim** — `resolve_adapter_or_422`,
  `resolve_input_text`, `get_target_profiles`, `build_codec_info_list`,
  `request_has_overrides_or_profile`.  Names lost the leading
  underscore on the move because they're now first-class symbols of
  the helper module's public surface.  Behaviour unchanged — call
  sites updated, no signature edits, no logic rewrites.

* **Frozen pipeline signatures untouched** — `run_plan`,
  `run_plan_with_rename`, `run_plan_with_overrides` (the trio in
  `netcanon/services/migration_pipeline.py`) stay frozen per the
  hard-rule freeze-and-extend contract.  Extraction was purely on
  the request-shaping / response-shaping side, one layer above the
  pipeline.

* **Tests** — new `tests/unit/api/test_migration_helpers.py`
  covers every helper directly (23 unit tests, one class per
  helper).  `tests/integration/test_migration_api.py` zero
  deltas — proves the API boundary (URLs, request/response shapes,
  status codes) is unchanged.

* **Docs** — `netcanon/api/routes/README.md` gains a brief
  "Helper modules" section establishing the
  `_<router>_helpers.py` sibling pattern as a worked example for
  future contributors.  Module docstring on the new helper file
  enumerates its public functions.

* **Why not refactor the per-pane handlers in the same commit?** —
  The five `/plan/<category>` route bodies are nearly identical
  (5 × ~20 LOC of "resolve adapters → resolve input → call
  `run_plan_with_overrides` with one category map populated → log").
  A `dispatch_pane_plan(category, ...)` helper would shrink the
  route file substantially.  Deferred deliberately: lifting AND
  refactoring in the same commit is the wrong shape of risk.  The
  per-pane consolidation is a candidate for a follow-up commit.

### Added (EOS 4.26 EVPN/VXLAN gaps — item 3 of 5: IPv6 addresses)

Third of the five deferred translator-plans EVPN/VXLAN gaps closed.
The karneliuk EOS 4.26 fixture's
`ipv6 address fc00:192:168:100::62/64` on Management1 was silently
dropped on parse before this change; the same was true for every
real-capture fixture carrying static IPv6 (Junos `family inet6
address`, Cisco `ipv6 address X/Y`, etc.) — IPv6 addresses are
stable syntax across vendor versions in the corpus, so the wire-up
is version-agnostic.

* **Schema** — new `CanonicalIPv6Address` (ip + prefix_length +
  scope) sibling to `CanonicalIPv4Address`; new
  `CanonicalInterface.ipv6_addresses` list.  Scope discriminator
  (`"global"` / `"link-local"`) normalises the keyword form on
  Cisco / Arista against prefix-inferred form on Junos / MikroTik /
  OPNsense / FortiGate.

* **Wire-through** — parse + render landed on all 8 codecs:
  arista_eos, cisco_iosxe (NETCONF/OpenConfig), cisco_iosxe_cli,
  aruba_aoss, juniper_junos, fortigate_cli, mikrotik_routeros,
  opnsense.  Capability matrix entries added on every codec.
  Vendor-specific placeholders filtered on parse: FortiGate `::/0`
  (no-v6 default), OPNsense `dhcp6` / `idassoc6` (keyword markers),
  Aruba AOS-S `dhcp full` (stateless DHCPv6).

* **Tests** — 36 new per-codec unit tests
  (`test_ipv6_wire_through.py`); 72 new cross-mesh smoke tests
  (every bidirectional pair preserves an IPv6 address through the
  round-trip + every target codec emits canonical IPv6 input);
  real-capture regression assertion exercising karneliuk EOS 4.26
  + ntc carrier IOS-XE + buraglio Junos + batfish EVPN-Type5 Junos.

### Added (EOS 4.26 EVPN/VXLAN gaps — items 1 + 2 of 5)

Two of the five deferred translator-plans EVPN/VXLAN gaps closed.
Surfaced when an Arista EOS 4.26 → Juniper translation lost semantic
surface; both items had stable syntax across versions (EOS 4.13+ /
Junos 15.1+) so the wire-up regresses across the full fixture corpus,
not just the EOS 4.26 trigger fixture.

* **VXLAN source-interface + UDP port** (`CanonicalVxlan` schema +
  Arista + Junos parse/render).  Arista's
  `interface Vxlan1 / vxlan source-interface <name>` and
  `vxlan udp-port <N>` now populate onto every CanonicalVxlan record
  emitted from the stanza; Junos's
  `set switch-options vtep-source-interface <name>` and
  `set switch-options vxlan-port <N>` mirror the same wire-up.
  Capability-matrix entries added across all 8 codecs.

* **Arista BGP / VLAN / RD / RT EVPN MAC-VRF**
  (CanonicalRoutingInstance with `instance_type="mac-vrf"`).  The
  per-VLAN EVPN binding form (`router bgp / vlan N / rd ... /
  route-target both ...`) now populates a CanonicalRoutingInstance
  keyed by the VLAN name — previously parse-and-ignore.  The new
  `vlan <N>` recognition is depth-restricted (3-space top-level
  router-bgp sub) so nested `vlan-aware-bundle ... / vlan <N>` lines
  don't spuriously spawn MAC-VRF entries.

### Fixed (OPNsense paramiko-shell backups breaking the migrate parser)

User report: picking a stored OPNsense config in the Migrate UI
returned ``parse failed: opnsense: malformed XML: syntax error:
line 1, column 0`` even though the detection probe reported 98%
confidence the file was OPNsense XML.  Detection tolerated leading
noise (substring search for ``<opnsense>``); parse called
``ET.fromstring`` which refused anything not starting with a valid
XML prolog.

**Root cause** — the paramiko-shell collector writes the raw PTY
dump to disk without stripping BOTH:

* The echoed command at the HEAD of the buffer (``cat /conf/
  config.xml\r\r\n`` before the ``<?xml`` prolog).
* The returning shell prompt at the TAIL of the buffer
  (``root@supergate:~ # `` after ``</opnsense>``).

Detection probe (tolerant substring search for ``<opnsense>``)
happily reported 98% confidence, but ``ET.fromstring`` refused
both shapes — first failing at line 1 column 0 (leading echo), and
once the leading strip was added, failing again at line 4603
column 4 (trailing prompt residue after the close tag).
``NetmikoCollector`` never had either issue — Netmiko's
``strip_command=True`` + ``strip_prompt=True`` handle both ends
internally.  The raw paramiko path has to do them explicitly and
didn't.

**Fix** in two layers, both now trimming head + tail:

1. **Collector side** (prevents new bad backups):
   `netcanon/collectors/paramiko_collector.py::_collect_output`
   now accepts an optional ``command`` kwarg and calls the new
   module-level helper ``_strip_command_echo(buf, command)`` before
   returning.  The helper:
   - **Head**: locates the command string in the first 512 bytes
     and drops everything up to and including the echo plus
     trailing ``\r``/``\n``/tab/space.
   - **Tail**: scans the last 512 bytes for a shell-prompt shape
     (``user@host:cwd [#$>]``) via bounded regex, slices before
     the prompt if found.
   Call site in ``collect()`` now passes
   ``definition.commands.config``.  Matches Netmiko's
   ``strip_command=True`` + ``strip_prompt=True`` behaviour.
2. **Parser side** (rescues legacy backups already on disk):
   `netcanon/migration/codecs/opnsense/codec.py::_trim_xml_envelope`
   (renamed from the original ``_trim_xml_prologue``; the old name
   is kept as a backwards-compat alias).  Called at the top of
   ``parse()``:
   - **Head**: searches the first 2 KiB for the earliest ``<?xml``
     or ``<opnsense`` marker; slices from there.
   - **Tail**: locates the last ``</opnsense>`` and slices
     everything after it.
   If no markers are present, the input passes through unchanged
   so truly malformed XML still raises the expected ``ParseError``
   — the trim is bounded so operator visibility of genuine
   failures is preserved.

### Tests (OPNsense rescue)

- `tests/unit/test_paramiko_collector.py` — 10 tests for
  ``_strip_command_echo`` covering the bug-reproducing CRLF+CR
  preamble, LF-only variant, tab+space+CR mix, no-whitespace-after-
  echo edge case, command-not-in-head tolerance (preserves output
  that mentions the command deeper in the file), empty/None inputs,
  and embedded-spaces commands (``show configuration | display set``).
- `tests/unit/migration/test_opnsense.py::TestParseTolerancePreamble`
  (6 tests) + `::TestTrimXmlPrologue` (7 tests) — covers the
  canonical ``cat /conf/config.xml\r\r\n`` shape, banner/MOTD
  preamble, prolog-less input where only ``<opnsense`` marker is
  present, bounded head-scan (markers past 2 KiB are NOT stripped),
  and a regression check against the new real fixture.
- `tests/integration/test_migration_api.py::TestOpnsenseParamikoShellEchoRescue`
  — 2 end-to-end tests joining the two halves the investigation
  agent flagged as a test-coverage gap: drops a corrupt-preamble
  file directly into `test_settings.configs_dir`, hits
  `POST /api/v1/migration/plan`, asserts ``status=completed``.
  Inverse test confirms truly malformed files still return
  ``failed`` with a clear error.
- New fixture:
  `tests/fixtures/real/opnsense/opnsense_paramiko_shell_capture.xml`
  — `opnsense_core_default.xml`'s body with a
  ``cat /conf/config.xml\r\r\n`` prefix prepended, reproducing the
  exact byte shape the user reported.  Documented in NOTICE.md and
  RESULTS.md as a regression fixture; derived from a BSD-2-Clause
  upstream file.

### Docs (OPNsense rescue)

- `netcanon/collectors/README.md` — `paramiko_shell` section now
  notes the command-echo stripping behaviour and points at the
  Netmiko `strip_command=True` parallel.
- `tests/fixtures/real/NOTICE.md` — provenance row for the new
  paramiko-shell-capture fixture.
- `tests/fixtures/real/RESULTS.md` — OPNsense section gains a
  Findings paragraph for the user-reported bug; matrix row added
  for the new fixture; summary-table row updated 4→5 fixtures and
  1→2 bugs surfaced.  TOTAL row updated 38→39 fixtures and 16→17
  bugs.

### Changed (Definitions page enriched with 4 browsing sections)

The `/definitions` page was showing only 4 backup-side device
definitions, hiding the richer data Netcanon actually has loaded:
1 version overlay + 54 migration target profiles (with module
variants) + 8 vendor codec records.  The page now surfaces ALL of
it as a browsable reference — the Tier-3 rename-modal dropdowns
are no longer the only way to discover what hardware/capabilities
the app supports.

- `netcanon/api/routes/ui.py::definitions_page` — extended to
  pass four context variables instead of one: `definitions`
  (unchanged family-base backup list), `overlays` (version /
  model-pinned variants from the loader's `_variants` registry),
  `profiles_by_vendor` (54 target profiles grouped by vendor),
  `vendor_rows` (8 vendors with their registered codecs +
  certainty tier + direction + capability-matrix counts).
- `netcanon/templates/definitions.html` — rewrote with four
  `<section>` blocks, each with a `section-*` testid.  Native
  `<details>`/`<summary>` disclosure for per-vendor and per-
  profile expansion — zero custom JS for the collapsible
  behaviour.  Port chips render per-port with kind-specific
  border colours (uplink / mgmt / console) + tooltip with
  speed / PoE / SFP / notes.  Module-variant cards expose SKU
  + description + uplink port list, so the Cat 9300 NM-8X vs
  NM-2Q choice (and similar across Aruba 3810M / FortiGate
  SFP-cage variants) is finally visible outside the migrate
  modal.
- **Live filter over target profiles**: a search input at the
  top of section 3 does DOM hide/show against a pre-lowercased
  `data-haystack` attribute (`vendor + model + display_name`)
  set server-side.  Vendor groups auto-collapse when all their
  profiles are filtered out.  Live counter shows "N matches"
  as the user types.
- **Codec certainty / direction pills**: each codec row in the
  vendors section renders its certainty tier as a colour-coded
  pill (`certified` → green, `best_effort` → amber,
  `experimental` → yellow — driven by the existing badge
  theme tokens so dark mode just works) + a direction pill
  (`parse_only` / `bidirectional` / `render_only`).  Side-by-
  side summary of each vendor's codec portfolio without
  needing to hit the API.
- All new styles use the dark-mode theme tokens from `base.html`'s
  `:root` / `[data-theme="dark"]` blocks — page renders correctly
  in both themes.

### Tests (Definitions page)

- `tests/integration/test_ui_routes.py::TestDefinitionsPageEnriched`
  — 11 server-side assertion tests covering:
  - The four section containers all render
  - Device definitions section count badge present
  - Target-profiles section + vendor groups + profile rows all
    populate from the real `definitions/target_profiles/`
  - Filter input + live count elements present
  - Module-variant cards emit when profiles have modules
  - Base-ports chip list emits
  - Vendors section lists all codecs with certainty + direction
    pills using theme-token-driven CSS classes
  - Overlays section ABSENT when loader has no overlays (the
    default test harness)
  - Overlays section RENDERS when an overlay YAML is dropped
    in at runtime (regression guard against the original
    "5 loaded / 4 displayed" user report)
- `tests/testid_reference.md` — Definitions section rewritten
  into four subsections (one per page section) with 30+ new
  testid entries covering sections, filter, vendor groups,
  profile rows, module cards, port-chip containers, vendor
  rows, codec rows, direction/certainty pills.

### Added (Global dark mode with sun/moon toggle on top nav)

- `netcanon/templates/base.html` — light + dark themes via CSS
  custom properties toggled on `<html data-theme>`.  Single source
  of truth: `:root` block declares light-mode tokens; a mirrored
  `[data-theme="dark"]` block overrides for dark mode.  Tokens
  cover page background, surfaces (base + alt + elevated +
  hover), text (primary + muted + faint), borders, accent +
  focus-ring, button variants (primary + secondary + danger),
  status-badge colour pairs (failed / running / pending /
  completed / partial), alerts, shadows, `<pre>` chrome, and
  the nav bar itself.  CSS declarations across the base template
  now reference `var(--token)` rather than raw hex for the
  high-visibility surfaces.
- **FOUC-prevention boot script** inlined in `<head>` *before*
  the `<style>` block — a tiny IIFE reads
  `localStorage["netcanon.theme.v1"]` (user override), falls
  back to `window.matchMedia('(prefers-color-scheme: dark)')`,
  and sets `data-theme` on `documentElement` synchronously.
  Blocks CSS parse, no flash of wrong theme on reload.
- **Sun/moon toggle button** (`data-testid="nav-theme-toggle"`)
  right-aligned on the nav via a flex spacer.  Always visible
  on every page (lives in `base.html`).  CSS attribute-selector
  swap between `&#x263D;` (moon glyph, shown in light mode →
  click to go dark) and `&#x2600;` (sun glyph, shown in dark
  mode → click to go light).  No DOM mutation on toggle —
  glyphs flip via CSS alone.
- **Accessibility**: `<button>` (not `<input type="checkbox">`)
  with live-updating `aria-label` ("Switch to dark theme" /
  "Switch to light theme") and `aria-pressed` (`true`/`false`)
  describing the ACTION not the current state — clearer for
  screen readers than a static "dark mode on/off" label.
- **localStorage persistence** under `netcanon.theme.v1`
  (matches the existing `netcanon.X.v1` key convention used by
  the rename-ack and active-job state).
- `netcanon/templates/_partials/theme-toggle.js` — new partial
  containing the `toggleTheme()` function +
  `_updateThemeToggleAriaLabel()` + DOMContentLoaded aria
  initialiser.  Included from `base.html` alongside the
  existing `config-viewer.js` + `job-progress.js` partials.
- **Cross-cutting cleanups**:
  - `showToast()` now applies CSS classes (`.toast-info` /
    `.toast-error` / `.toast-success`) driven by theme tokens
    instead of writing inline `element.style.background` hex —
    dark mode inherits the semantic colour pair automatically.
  - Job-progress panel + toast + config-viewer-modal outer
    chrome migrated to theme tokens.
  - 150ms transition scoped to colour properties (background /
    color / border-color) so theme flip is smooth without
    juddering unrelated animations.

### Docs (dark mode)

- `tests/testid_reference.md` — added `nav-theme-toggle` to the
  Navigation section with full semantic description (aria
  semantics + localStorage key).
- `ARCHITECTURE.md` — new "Theming (dark mode)" subsection under
  Template organisation documenting the three load-bearing
  rules: inline-blocking boot script, JS-driven theme apply
  (not `@media` CSS-only), theme-aware toast/alert colour pairs
  via CSS class (never inline style).  `_partials/` inventory
  extends with `theme-toggle.js`.
- `AGENTS.md` Documentation Sync Checklist gains a new row: "A
  new CSS colour added to `base.html`" → use `var(--token)`
  from the theme set; add to BOTH `:root` and
  `[data-theme="dark"]` if no existing token fits.  Points at
  ARCHITECTURE "Theming (dark mode)" section for full rationale.

### Tests (dark mode)

- `tests/integration/test_ui_routes.py::TestThemeToggleRendered`
  — 6 server-side sanity tests: `<html data-theme="light">`
  default on 5 pages, boot script inlined in `<head>`,
  `nav-theme-toggle` button renders on every page, sun + moon
  glyphs both in markup, theme-toggle partial included,
  `:root`/`[data-theme="dark"]` CSS tokens present.  Cheaper
  than Playwright; catches template regressions early.
- `tests/e2e/test_navigation.py::TestThemeToggle` — 6
  Playwright tests: button visible on dashboard + jobs, click
  flips both `data-theme` attr + localStorage, reload persists
  the stored theme, `aria-label`/`aria-pressed` update to
  reflect next-action, body background colour actually changes
  on click (guards against the `var(--)` resolution regression
  class).

### Added (Arista EOS 4.26 real fixture — 4th EOS major)

- `tests/fixtures/real/arista_eos/karneliuk_a_eos1_eos4260.txt` —
  real **A-EOS1** vEOS fixture on **EOS-4.26.0.1F** from Anton
  Karneliuk's Batfish MVP demo (BSD-3-Clause, karneliuk-com/
  batfish-mvp @ `62e8ce7`).  82 lines covering the post-GAP-6
  canonical surface: `service routing protocols model multi-agent`,
  VLAN 100 + `Vxlan1 vni 100`, Management1 with IPv4+IPv6, router
  bgp 65033 with two eBGP neighbours + `address-family evpn` +
  `evpn redistribute-learned`, route-maps permit+deny, ip prefix-
  list.  Fourth distinct EOS major in the Arista corpus
  (4.21 + 4.22 + 4.23 + 4.26).
- `tests/fixtures/real/RESULTS.md`: Arista section gains the new
  matrix row; certification-decision paragraph updated to reflect
  the 4.26 fixture; summary-table row updated 3→4 fixtures / 3→4
  versions.  TOTAL row 37→38 fixtures.  Promotion-path paragraph
  replaced with "even-newer EOS LTS 4.28+/4.30+ fixture" as
  remaining nice-to-have.
- `tests/fixtures/real/NOTICE.md`: provenance row added for the
  new fixture with repo + commit SHA + license + grammar
  summary.  Also documents the fixture-hunt dead-ends: batfish/
  lab-validation caps out at 4.23; ksator/arista_eos_audit at
  4.22.4M; aristanetworks/avd lacks `! device:` version banners;
  newer 4.28+/4.30+ configs require authenticated GitHub search
  or lab-owned containerlab captures.

### Added (Structural apply-groups collapse — Junos interface-range)

- `netcanon/migration/codecs/juniper_junos/codec.py` — parse now
  handles ``set interfaces interface-range <rname> ...`` grammar.
  Supported sub-paths: ``member <iface>``, ``description``,
  ``mtu``, ``disable``, ``unit 0 family inet address``.  Shared
  attrs apply to each member interface at materialisation time so
  the canonical tree looks identical whether the operator wrote
  interface-range blocks or flat per-interface lines.  Per-member
  config overrides range-level defaults (member wins on conflict).
- Top-level ``set interfaces <X> mtu <N>`` also now parses and
  populates :attr:`CanonicalInterface.mtu` (previously the MTU
  field existed on the model but Junos parse didn't populate it).
- Render-side structural collapse: auto-detects ≥3 interfaces
  sharing identical ``(mtu, description, enabled)`` tuples with
  at least one non-default value and emits
  ``set interfaces interface-range AUTO-RANGE-<N>`` blocks.
  Per-interface emission of the shared attrs gets suppressed; per-
  interface specifics (IPv4 addresses, etc.) still emit normally.
- Collapse heuristics deliberately skip VRF-bound interfaces,
  switchport / trunk interfaces, access-VLAN-carrying interfaces,
  and sub-interfaces — their richer semantics warrant per-
  interface emission.  Default-everything interfaces also skip
  (nothing to hoist to the range).
- Render MTU emission newly added: ``set interfaces <X> mtu <N>``
  emits when `iface.mtu` is set and the interface isn't a range
  member (suppression via the collapse-detection pass).
- Structural collapse is COMPLEMENTARY to GAP 9b's apply-groups
  preservation: operator-authored group structure (via
  ``set groups G`` + ``set apply-groups G``) round-trips verbatim;
  auto-synthesis kicks in only for raw per-interface sharing the
  operator didn't themselves collapse.

### Tests (structural collapse)

- ``tests/unit/migration/test_junos_interface_range.py`` — 15 tests:
  - ``TestInterfaceRangeParse`` (5 tests): member collection +
    shared mtu/description/disable application + per-interface
    override wins + unknown sub-paths tolerated.
  - ``TestInterfaceRangeRender`` (7 tests): ≥3-member collapse
    happy path, 2-member no-collapse (threshold), multiple
    collapse groups with distinct tuples, per-interface
    specifics still emit, VRF-bound skipped, all-default
    skipped, sub-interfaces skipped.
  - ``TestInterfaceRangeRoundTrip`` (3 tests): flat→collapsed→
    reparse stability, range-form input survives the render
    round-trip, top-level mtu parse.

### Changed (EVPN Type-5 per-prefix path: Unsupported → Lossy)

- Moved `/evpn-type5-routes/route` from ``Unsupported`` to ``Lossy``
  on all three DC codecs (Arista EOS, Juniper Junos, Cisco IOS-XE
  CLI).  The `CanonicalEvpnType5Route` per-prefix schema is a
  lossy-by-default extension point: no codec populates it today,
  and the canonical semantic for Type-5 IP-prefix advertisements
  lives on :attr:`CanonicalRoutingInstance.l3_vni` (populated via
  GAP 6 — Arista ``vxlan vrf X vni N`` + Junos ``protocols evpn
  ip-prefix-routes vni N``).
- Reason strings across all three codecs now explicitly call out
  the VRF-property canonical model as the supported alternative
  and note that per-prefix enumeration would require route-map /
  policy-statement parsing as a future dependency.
- Consumers needing explicit per-prefix semantics should infer
  from VRF membership (`CanonicalInterface.vrf`) + l3_vni rather
  than relying on the per-prefix list.
- Also updated the obsolete GAP 4-era Junos LossyPath note for
  `/groups` — the "Apply-groups inheritance is wired only for
  host-name" text was stale post-GAP-8 (two-pass parse wires the
  full dispatch surface); reason rewritten.

### Tests (Type-5 demotion)

- ``tests/unit/migration/test_vxlan_evpn_schema.py`` —
  ``TestDCCodecsDeclareEvpnType5Unsupported`` renamed to
  ``TestDCCodecsDeclareEvpnType5Lossy``, assertions updated to
  verify ``lossy`` classification + non-empty reason mentioning
  `l3_vni` as the supported alternative.  New regression guard
  confirms the path is NOT in the Unsupported list post-demotion.
  Parametrised across Arista + Junos + Cisco IOS-XE CLI.

### Added (GAP 9b — Junos apply-groups statement + body preservation on render)

- Two new fields on :class:`CanonicalIntent`:
  - ``apply_groups: list[str]`` — operator-declared apply-groups
    statements (e.g. ``set apply-groups POC_Lab``).
  - ``group_content: dict[str, list[list[str]]]`` — per-group
    bucket of tokenised set-line tails, preserving operator-
    authored group bodies verbatim.  Only groups that appear in
    ``apply_groups`` (i.e. actually composed into the candidate
    config) get persisted; orphan groups drop.
- `netcanon/migration/codecs/juniper_junos/codec.py` — parse
  populates both fields from the GAP 8 two-pass buckets.  Render
  emits `set groups <G> <body>` lines FIRST (using
  `_quote_if_needed` per token so multi-word quoted values like
  banner messages round-trip exactly), followed by
  `set apply-groups <G>` statements.
- Operator-facing benefit: paste a Junos config with
  ``set groups POC ...`` + ``set apply-groups POC``, render it
  back out, and the output looks like hand-written Junos again
  (group-structure preserved) — previously v2a flattened
  everything into top-level lines.
- De-dup guards added alongside:
  - `_apply_routing_options` — static routes de-dup on
    ``(destination, gateway)`` pair.
  - `_apply_interfaces` unit-N IPv4 address handler — de-dup on
    ``(ip, prefix_length)`` pair.  Both prevent duplicate
    accumulation when GAP 9b's group-content + top-level emission
    would otherwise double-add on re-parse.
- Scope-cap: GAP 9b preserves what the operator wrote.  It does
  NOT synthesise groups from shared sub-configs (auto-detecting
  that N interfaces share an MTU value and collapsing them to a
  group) — that's a larger refactor requiring per-entity
  source-provenance metadata; deferred.

### Tests (GAP 9b)

- ``tests/unit/migration/test_junos_apply_groups_rich.py::TestApplyGroupsRenderPreservation``
  — 8 tests covering:
  - Parse populates `apply_groups` + `group_content`
  - Orphan group (no apply-groups) drops from persistence
  - Group body tokens preserve exactly
  - Render emits `set groups <G>` BEFORE `set apply-groups <G>`
  - Full round-trip stability (parse → render → parse produces
    identical canonical tree)
  - Multi-word quoted body (banner message) re-quotes correctly
    on render so tokeniser round-trips
  - Real-fixture regression: ksator EX4550 has 22 group-body
    lines including a banner — round-trip preserves every line
  - Fresh `CanonicalIntent` has empty `apply_groups` + `group_content`

### Added (GAP 9a — Junos block-form (curly-brace hierarchical) parse)

- `netcanon/migration/codecs/juniper_junos/codec.py` — parse now
  auto-detects block-form (hierarchical curly-brace) input and
  converts it to set-form internally via a grammar-agnostic
  walker.  The same `_dispatch_set` pipeline then applies the
  resulting set-lines to the canonical tree — no duplicated
  parse logic.
- New helpers at module scope:
  - ``_looks_like_blockform(raw)`` — heuristic detection: first
    meaningful line ends with ``{`` AND has content before it,
    lines containing ``"key":`` patterns get rejected as likely
    JSON.
  - ``_tokenise_blockform(raw)`` — tokeniser with ``{``/``}``/
    ``;`` as standalone tokens; strips ``/* ... */`` comments
    (multiline tolerated); preserves quoted strings including
    escaped inner quotes.
  - ``_blockform_to_setform(raw)`` — recursive-descent walker
    that maintains a path stack, emits ``set <path...> <value>``
    for each ``;``-terminated leaf statement, raises
    ``ParseError`` on unbalanced braces.
- JSON and malformed `{`-leading input still raise ``ParseError``
  with a helpful hint pointing at ``| display set`` for real
  Junos operators.
- Previously, the codec rejected block-form with a helpful error
  message (v1 behaviour — GAP 4 commit); GAP 9a removes that
  rejection and ships the conversion.  Operators no longer need
  to run ``| display set`` on their device to feed block-form
  output into Netcanon.

### Tests (GAP 9a)

- ``tests/unit/migration/test_juniper_junos.py::TestBlockFormParse``
  — 10 tests:
  - ``test_system_host_name``: simplest case.
  - ``test_nested_blocks``: ``system / login / user / class /
    authentication / encrypted-password`` nested 5 deep.
  - ``test_interface_with_ip``: ``interfaces / ge-0/0/0 /
    description`` + ``unit 0 / family inet / address``.
  - ``test_vlan_with_vxlan_vni``: block-form VLAN + nested
    ``vxlan / vni``.
  - ``test_routing_instance_vrf``: full VRF declaration in
    block-form.
  - ``test_apply_groups_inheritance_in_blockform``: `set
    groups G { ... }` + `set apply-groups G;` wiring through
    the GAP 8 two-pass machinery.
  - ``test_quoted_strings_preserved``: descriptions with spaces
    and `$`-special chars.
  - ``test_comments_stripped``: ``/* ... */`` both multi-line
    and inline.
  - ``test_mixed_input_still_rejected_if_not_blockform``: JSON
    input (``{"hostname": ...}``) still raises ``ParseError``.
  - ``test_unbalanced_braces_raises``: missing ``}`` raises
    with helpful message.
- ``test_block_form_rejected_with_helpful_hint`` (v1 path) has
  been swapped to ``test_block_form_now_accepted_via_gap_9a_conversion``
  to lock in the new behaviour.

### Added (GAP 8 — richer Junos apply-groups inheritance)

- `netcanon/migration/codecs/juniper_junos/codec.py` — full
  two-pass parse refactor.  Every `set groups <g> <path>` line is
  now bucketed during a first pass; the dispatcher then replays
  group content (in REVERSE apply-groups order so the first-
  declared group wins for scalars — matches Junos's first-match
  composition) followed by top-level content (so direct-intent
  overwrites group inheritance).  List-shaped fields
  (`static_routes`, `local_users`, `dns_servers`, `ntp_servers`,
  `syslog_servers`, interface `ipv4_addresses`) accumulate from
  both sources with de-dup.
- Before GAP 8, only `set groups <g> system host-name X` was
  inherited (GAP 4 narrow path).  After GAP 8 the full dispatch
  surface flows through: `set groups <g> system login user ...`,
  `set groups <g> system ntp server ...`, `set groups <g> system
  name-server ...`, `set groups <g> system syslog host ...`,
  `set groups <g> interfaces <iface> ...`, `set groups <g> snmp
  community ...`, `set groups <g> routing-options static route
  ...`, `set groups <g> routing-instances ...`, `set groups <g>
  vlans ...` — all populate canonical tree via apply-groups.
- New top-level parse surface added alongside the refactor (these
  also appear at top level in some configs, not just under
  groups): `set system domain-name`, `set system name-server`,
  `set system ntp server [prefer ...]`, `set system syslog host
  <ip> [any ...]`.
- Render extended: `set system domain-name / name-server / ntp
  server / syslog host` emitted when canonical tree has the
  corresponding data.

### Tests (GAP 8)

- ``tests/unit/migration/test_junos_apply_groups_rich.py`` —
  16 tests:
  - ``TestSyntheticGroupInheritance`` (7 tests): user, static
    route, SNMP community, NTP server, DNS name-server, syslog
    host, interface — each declared only inside a group and
    surfaced via apply-groups.
  - ``TestCompositionSemantics`` (4 tests): direct-intent
    overrides group for scalars, first-apply-group wins among
    groups for scalars, lists accumulate from both sources,
    unapplied group silently drops.
  - ``TestKsatorFixturesRichInheritance`` (5 tests): real-
    fixture regression guards asserting that QFX5100 + EX4550
    now surface hostname, user, SNMP, static routes, NTP, DNS,
    syslog, and the `vme` management interface — all previously
    empty because everything lived under `set groups POC_Lab`.

### Added (GAP 6 — Arista EOS + Juniper Junos VXLAN + VRF / EVPN codec wire-up)

- `netcanon/migration/codecs/arista_eos/codec.py` — parse + render
  now populate `CanonicalVxlan` from ``interface Vxlan1 / vxlan
  vlan <vid> vni <vni>`` lines, and `CanonicalRoutingInstance` from
  top-level ``vrf instance <name>`` + ``router bgp <asn> / vrf
  <name> / rd / route-target import|export|both`` stanzas.  L3 VNI
  (``vxlan vrf <name> vni <N>``) populates
  :attr:`CanonicalRoutingInstance.l3_vni` for EVPN Type-5 symmetric
  IRB routing.  Per-interface VRF membership (``vrf <name>`` on
  Ethernet / Port-Channel / Loopback / Vlan interfaces) populates
  :attr:`CanonicalInterface.vrf`.
- `netcanon/migration/codecs/juniper_junos/codec.py` — parse +
  render now populate the same canonical shapes from Junos's
  equivalents: ``set vlans <name> vxlan vni <vni>``, ``set
  routing-instances <name> instance-type vrf`` + ``route-distinguisher``
  + ``vrf-target target:<rt>`` (shared or split import/export) +
  ``interface <iface>`` + ``protocols evpn ip-prefix-routes vni
  <N>`` (populates l3_vni).  Junos's ``set routing-instances <name>
  interface <iface>.0`` round-trips through the codec's canonical
  naming convention (unit-0 compound names collapse to parent in
  CanonicalInterface.name; render re-adds ``.0`` to preserve valid
  Junos grammar).
- New helper `CanonicalRoutingInstance.l3_vni` field added to the
  GAP 5 schema — matches how both vendors express Type-5
  announcements (VRF property, not per-prefix record).  Schema
  commit is the same as GAP 6 since it's hidden behind the codec
  implementations; no separate ship-before-wire step needed.
- `/vxlan-vnis/vni` and `/routing-instances/instance` demoted from
  ``Unsupported`` to ``Supported`` on both Arista EOS and Juniper
  Junos capability matrices.  `/evpn-type5-routes/route` remains
  Unsupported on both with updated reason: Type-5 per-prefix
  records aren't populated by any codec; the VRF-property
  modelling via ``l3_vni`` is the supported path today.
- Arista: Vxlan interface stanzas are NOT materialised as
  CanonicalInterface records (they're VXLAN config containers, not
  real interfaces).  Sub-commands dispatch through a sentinel
  interface during parse; render reconstructs the whole ``interface
  Vxlan1`` stanza from ``tree.vxlan_vnis`` +
  ``tree.routing_instances[].l3_vni``.
- Arista: router-bgp stanza scanner correctly handles ``!``
  sub-stanza separators (previously would reset ``in_bgp`` mid-
  stanza and drop subsequent ``vrf`` blocks — bug caught during
  wire-up, regression-guard included).
- Arista: ``route-target import evpn <rt>`` / ``export evpn <rt>``
  inside router-bgp / vrf stanzas strip the ``evpn`` prefix to
  extract the actual RT value.
- Arista: the render path emits
  ``router bgp 65000`` with a placeholder ASN when any VRF carries
  RD / RTs — `CanonicalIntent` doesn't model BGP config beyond what
  VRFs need, so operators re-emit the ASN as appropriate.

### Tests (GAP 6)

- ``tests/unit/migration/test_vxlan_evpn_wire_through.py`` — 35
  tests covering Arista + Junos parse + render + round-trip for
  VXLAN/VRF/L3-VNI/RD/RT, plus real-fixture regression guards
  (batfish DC1-LEAF2A Arista, batfish EVPN-Type5 + L3VPN Junos).
- Schema tests (``test_vxlan_evpn_schema.py``,
  ``test_routing_instance_schema.py``) updated: the wired codecs
  (Arista + Junos) are removed from the "must declare
  Unsupported" parametrised list; two new test classes lock in
  the supported classification.

### Added (Certification promotion — Arista + Junos to `certified` ✅)

- `tests/fixtures/real/arista_eos/batfish_duplicateprivate_eos4211.txt`
  — real **EOS-4.21.1.1F** DuplicatePrivate vEOS (Apache-2.0, via
  batfish/lab-validation @ `d40faf6`).  64 lines.  Third Arista
  fixture from a third EOS major (4.21 + 4.22 + 4.23) closing the
  `≥3 fixtures from ≥2 versions` certified bar.
- `tests/fixtures/real/junos/batfish_evpntype5_router1_junos2541.set`
  — real **Junos 25.4R1.12** EVPN-VXLAN leaf grammar (Apache-2.0,
  batfish/lab-validation).  151 lines.  VXLAN VNI mappings, IRB
  sub-interfaces with VRRP, routing-instances with RD + vrf-target,
  `protocols evpn encapsulation vxlan`, BGP EVPN signaling.  Fourth
  Junos major in the corpus (biggest version jump: 15.1 → 17.3 →
  18.4 → 25.4).
- `tests/fixtures/real/junos/batfish_l3vpn_pe1_junos2541.set` —
  real **Junos 25.4R1.12** MPLS L3VPN PE grammar (Apache-2.0).
  34 lines.  CUSTOMERS VRF, iBGP PE mesh with
  `family inet-vpn unicast`, LDP + MPLS.  Fifth Junos fixture —
  classic (pre-EVPN) VRF-over-MPLS complements the EVPN fixture.

### Changed (Certification promotion)

- `arista_eos` codec certainty promoted from `best_effort` to
  **`certified` ✅** — three real captures across three EOS majors
  (4.21 + 4.22 + 4.23), all round-trip stable after the three bugs
  fixed on the promotion path.
- `juniper_junos` codec certainty promoted from `best_effort` to
  **`certified` ✅** — five real captures across four Junos majors
  (15.1 + 17.3 + 18.4 + 25.4), all round-trip stable.  The two 25.4
  batfish captures (EVPN leaf + L3VPN PE) close the `≥3 fixtures
  from ≥2 versions` bar with a current-LTS major on both surfaces.
- `tests/fixtures/real/RESULTS.md` — Arista + Junos sections now
  carry `certified` banners with matrix rows for the 3 new fixtures
  + updated post-cert items (no longer gating, listed as follow-on
  enrichment via GAP 6/8/9).  Summary table reflects 3→3 / 5→5
  fixture counts, version jumps 2→3 for Arista and 3→4 for Junos;
  TOTAL row updated 34→37.
- `tests/fixtures/real/NOTICE.md` — provenance rows for the 3 new
  fixtures with repo + commit SHA + license + grammar summary.

### Added (GAP 7 — per-unit 802.1Q VLAN tagging on Junos sub-interfaces)

- `netcanon/migration/codecs/juniper_junos/codec.py` — parse now
  handles `set interfaces <parent> unit <N> vlan-id <tag>`,
  populating :attr:`CanonicalInterface.access_vlan` on the
  sub-interface.  Semantically equivalent to Cisco's
  ``encapsulation dot1Q <N>`` — stores on the existing
  ``access_vlan`` field without setting ``switchport_mode``
  (Junos sub-interfaces are L3 on a tagged VLAN, not L2 access
  ports).  Malformed ``vlan-id <garbage>`` silently no-ops
  rather than crashing parse.
- Render-side: sub-interface emit path now includes
  ``set interfaces <parent> unit <N> vlan-id <tag>`` when
  ``access_vlan`` is populated.  A sub-interface carrying only
  ``access_vlan`` (no IP, no description) is now considered
  "renderable" — the vlan-id line IS the content; the bare
  placeholder line is suppressed to avoid redundancy.
- ``unit 0 vlan-id <N>`` (uncommon but legal) stores on the
  PARENT interface's ``access_vlan`` — consistent with the v1
  unit-0-collapses-into-parent convention.

### Tests (GAP 7)

- ``tests/unit/migration/test_juniper_junos.py::TestPerUnitVlanTagging``
  — 7 tests covering vlan-id parse, vlan-id-alone sub-interface
  materialisation, malformed tag silent no-op, render emits
  native ``<parent> unit <N> vlan-id <tag>`` grammar,
  vlan-id-alone sub-interface emits content line (not placeholder),
  parse → render → parse round-trip stability, and unit-0 vlan-id
  collapses into parent.

### Added (GAP 5 — canonical VRF / routing-instance schema [ship-before-wire])

- `CanonicalRoutingInstance` model in
  `netcanon/migration/canonical/intent.py`.  Cross-vendor VRF
  primitive modelling Cisco `vrf definition`, Arista `vrf instance`,
  and Juniper `routing-instances`.  Fields: `name`,
  `instance_type` (defaults to ``"vrf"``; Junos variants
  ``virtual-router`` / ``l2vpn`` / ``mac-vrf`` also accepted),
  `route_distinguisher`, `rt_imports`, `rt_exports`, `description`.
- `CanonicalInterface.vrf` field — per-interface VRF membership
  (back-pointer pattern, matches `lag_member_of`).  Empty string
  = global / default VRF.  Source of truth for membership;
  `CanonicalRoutingInstance` carries metadata only.
- `CanonicalIntent.routing_instances` top-level Tier-2 list.
- Ship-before-wire: Arista EOS, Juniper Junos, and Cisco IOS-XE CLI
  capability matrices gain ``UnsupportedPath`` entries for
  ``/routing-instances/instance`` so the pipeline's validate stage
  surfaces "VRF detected but not translated" in the UI banner.
- Documentation: ``ARCHITECTURE.md`` Layer-3 CIM table's "Tier 2
  (ship-before-wire)" row extends to include VRF schema.
  ``translator-plans.txt`` DEFERRED ROADMAP gains a ``[SHIPPED]``
  entry for GAP 5.
- Tests: ``tests/unit/migration/test_routing_instance_schema.py``
  — 20 tests covering model construction, defaults, full-field
  construct, Junos `instance_type` variants, name-required
  validation, `<ip>:<nn>` RD form, per-interface `vrf` defaults +
  serialisation, intent-level `routing_instances` round-trip,
  and the ship-before-wire contract (parametrised check that
  every DC codec declares the new path as ``unsupported``).

### Added (GAP 4 — Junos apply-groups host-name inheritance + per-unit sub-interfaces)

- `netcanon/migration/codecs/juniper_junos/codec.py` — parse now
  handles `set groups <gname> system host-name <X>` + `set apply-
  groups <gname>` pairs, populating `intent.hostname` from the
  first applied group that declared a host-name (mirrors Junos's
  own first-match composition order).  Direct `set system
  host-name X` still wins over group-scoped fallback when both
  are present.  Bracketed `set apply-groups [ g1 g2 ]` form
  tolerated: the bracket tokens are filtered out of the
  applied-groups list.
- `netcanon/migration/codecs/juniper_junos/codec.py` — parse now
  materialises per-unit sub-interfaces (unit 1+) as distinct
  `CanonicalInterface` entries named `<parent>.<unit>` (e.g.
  `ge-0/0/0.100`), matching Cisco's dot1Q convention so canonical
  consumers see the same shape across vendors.  IPv4 address +
  description + disable on the sub-interface all populate on the
  child entry; unit 0 still collapses into the parent.  Render
  splits the compound name back into native Junos grammar
  (`set interfaces <parent> unit <N> ...`) — the compound name
  never appears in emitted set-lines.
- Helper `_split_subiface_name(name)` distinguishes Junos physical
  sub-interfaces (parent contains `<media>-<fpc>/<pic>/<port>`
  slashes, e.g. `ge-0/0/0.100`) from SVI-like interfaces whose
  dot is part of the base name (`irb.10`, `vlan.100`).  The
  slash requirement prevents mis-splitting irb/vlan identities.

### Changed (GAP 4 — ksator fixture hostnames now populate)

- `tests/fixtures/real/RESULTS.md`: Junos ksator QFX5100 + EX4550
  coverage-matrix rows updated from `hostname=0` to `hostname=1`
  each; explanatory note replaced with "**populates intent.hostname
  as of GAP 4**" marker.
- `tests/fixtures/real/RESULTS.md`: Junos promotion-path paragraph
  updated — apply-groups host-name and sub-interface materialisation
  are no longer pending; richer apply-groups inheritance (interface
  config, protocols, SNMP) + routing-instances + block-form + per-
  unit VLAN tagging remain the outstanding work before `certified`.

### Tests (GAP 4)

- `tests/unit/migration/test_juniper_junos.py::TestApplyGroupsHostname`
  — 7 tests covering the happy path, top-level-wins-over-group,
  unapplied group ignored, first-applied-group-wins ordering,
  bracketed `[ g1 g2 ]` syntax, and two real-fixture regression
  guards (ksator QFX5100 + EX4550) asserting the specific
  hostname string.
- `tests/unit/migration/test_juniper_junos.py::TestSubInterfaces`
  — 7 tests covering unit-N materialisation with IP + description
  + disable, multi-subiface on same parent, `irb.N` preservation
  (not mis-split as `irb`+unit), render emits native
  `<parent> unit <N>` grammar (never the compound-name form), and
  round-trip stability through parse → render → parse.

### Added (GAP 3 — real-capture fixtures promoting Arista + Junos to best_effort)

- `tests/fixtures/real/arista_eos/batfish_labval_dc1_leaf2a_eos4230.txt`
  — real **EOS-4.23.0.1F** vEOS EVPN leaf from Arista's EVPN L3
  Design Guide lab validation (Apache-2.0, via batfish/lab-validation
  @ `d40faf6`).  429 lines, 40 interfaces, 15 VLANs, MLAG peer-link
  + 5 Port-Channels, VXLAN1 overlay, router bgp 65102, VRF
  definitions, VARP virtual-router MAC.  Second Arista fixture from
  a different EOS major (4.22 + 4.23).
- `tests/fixtures/real/junos/ksator_labmgmt_qfx5100_junos173.set` —
  real **Junos 17.3R1.10** set-form config from a QFX5100 DC
  access/leaf switch (MIT, (c) Juniper Networks 2018).  106 lines,
  11 interfaces (including `ae0`/`ae1` LAGs), 16 VLAN declarations,
  apply-groups inheritance pattern.
- `tests/fixtures/real/junos/ksator_labmgmt_ex4550_junos151.set` —
  real **Junos 15.1R6.7** set-form from an EX4550 campus/DC access
  switch (same MIT source).  52 lines, 3 interfaces, 6 VLANs,
  `chassis aggregated-devices ethernet device-count 2`.  Oldest
  Junos major in the corpus — closes ≥3-version gap for promotion.

### Changed (GAP 3 — codec certification promotions + bug fixes surfaced by real captures)

- `arista_eos` codec certainty promoted from `experimental` to
  `best_effort` — 2 real captures across EOS 4.22 + 4.23 both
  round-trip stable.
- `juniper_junos` codec certainty promoted from `experimental` to
  `best_effort` — 3 real captures across Junos 15.1 + 17.3 + 18.4
  all round-trip stable.
- `netcanon/migration/codecs/arista_eos/codec.py` — render-side
  LAG bug fixed.  The render loop emitted `interface Port-ChannelN`
  stubs but did NOT emit the matching `channel-group N mode <mode>`
  on member Ethernet interfaces.  Arista LAGs (like Cisco IOS)
  are synthesised at parse time from `channel-group` lines on the
  child side; with nothing on that side in the rendered output,
  re-parse produced zero LAGs even when the canonical tree carried
  them.  Round-trip lost all 5 MLAG Port-Channels on the batfish
  EVPN capture.  Fixed by building a `lag_mode_by_name` lookup at
  render top + emitting `channel-group N mode <mode>` on
  interfaces whose `lag_member_of` is populated, with canonical-
  to-EOS mode normalisation (`static` → `on`, `passive` →
  `passive`, else `active`).
- `netcanon/migration/codecs/juniper_junos/codec.py` — render-side
  bare-interface bug fixed.  The v2a render loop emitted interface
  set-lines only when the canonical interface carried a
  description / disable flag / IPv4 address.  The Junos parse side
  creates an interface entry for every `set interfaces <name> ...`
  line seen — including lines whose trailing tokens are all Tier-3
  grammar (e.g. `unit 0 family ethernet-switching ...`).  Those
  interfaces landed in the canonical tree with no renderable
  attributes, render dropped them silently, and round-trip showed
  the interface count shrinking on the ksator EX4550 fixture.
  Fixed by emitting `set interfaces <name>` as a placeholder line
  when no other attributes are present.

### Tests (GAP 3)

- `tests/unit/migration/test_arista_eos.py::TestRender` — two new
  regression tests:
  - `test_render_lag_member_emits_channel_group` — parse a LAG
    config, render, re-parse, assert identical LAG recovered.
  - `test_render_lag_member_mode_normalised` — canonical mode
    `static` must render as EOS `on`.
- `tests/unit/migration/test_juniper_junos.py::TestRenderInterfaces::
  test_render_bare_interface_emits_placeholder` — parse an
  attribute-less interface, render, re-parse, assert the interface
  survives.
- 9 real-capture tests newly active across the 3 new fixtures
  (parse / round-trip / canonical representation stability).

- `tests/fixtures/real/RESULTS.md` — Arista + Junos sections
  updated with new coverage matrix rows, findings (the two bugs
  above), certification-decision paragraphs promoted to
  `best_effort`, and revised promotion-path notes.  Summary table
  updated: Arista 1→2 real / 1→2 versions / 2→3 bugs surfaced;
  Junos 1→3 real / 1→3 versions / 0→1 bug; TOTAL 31→34 fixtures,
  12→16 bugs surfaced.
- `tests/fixtures/real/NOTICE.md` — provenance rows added for
  each new fixture: source repo + commit SHA + license + line
  count + grammar summary.

### Changed (GAP 2 — Juniper Junos render-side v2a [flat set-form, no apply-groups])

- `netcanon/migration/codecs/juniper_junos/codec.py` — render
  implementation replaces the previous ``NotImplementedError`` stub.
  Direction promoted from ``parse_only`` to ``bidirectional``.
  Codec remains ``experimental`` tier pending additional real
  captures (see RESULTS.md for promotion bar).
- Render emits flat set-form commands in a deterministic order —
  system / login / interfaces / vlans / routing-options / snmp —
  so repeated renders of the same tree produce byte-identical
  output (load-bearing for diff-based deploy + snapshot compare).
- Quoting strategy mirrors what Junos's ``| display set`` emits
  natively: bare tokens for simple strings, double-quoted wrappers
  for strings containing whitespace or shell-special characters,
  backslash-escaping for embedded quotes.  Two internal helpers
  (``_quote_if_needed`` for identifiers, ``_quote_always`` for
  free-text fields) split the two conventions.
- Hash round-trip: passwords stored under the ``junos:<hash>``
  vendor tag (added by parse) get the prefix stripped on render,
  producing the operator-facing ``encrypted-password "<hash>"``
  form.  Cross-vendor hashes (no ``junos:`` prefix) emit verbatim.
- Role inference for rendered ``class``: explicit ``role`` field
  wins; otherwise privilege-level ≥15 → ``super-user``, ≥5 →
  ``operator``, else ``read-only``.  Preserves cross-vendor
  round-trips that drop role during codec-to-codec translation.
- Connected/blackhole static routes (empty gateway) are skipped on
  render — Junos flat set-form requires a ``next-hop``; we'd rather
  drop them than emit invalid input.  Logged as a future
  enrichment if demand arrives.
- Apply-groups inheritance (``set groups <name> ... / set
  apply-groups <name>``) is NOT emitted in v2a.  Output is verbose
  but syntactically complete.  v2b (deferred, bundleable with
  GAP 4) will detect repeated sub-trees and collapse them for
  operator readability.

### Tests (GAP 2)

- ``tests/unit/migration/test_juniper_junos.py`` — render test
  classes added alongside existing parse tests:
  ``TestRenderBasic`` (empty tree, hostname-only, determinism),
  ``TestRenderInterfaces`` (description quoting incl. embedded
  quotes, disabled flag, multi-IP, loopback), ``TestRenderVlans``
  (named, synthetic ``VLAN-<id>`` fallback, space-quoted name),
  ``TestRenderUsers`` (super-user/read-only from privilege,
  role-wins-over-privilege, hash vendor-tag stripping, cross-
  vendor hash preservation), ``TestRenderRouting`` (static route
  + connected-route skip), ``TestRenderSnmp`` (community,
  location, contact, trap-hosts), ``TestRenderRoundTrip``
  (hostname, sample-input round-trip, user-with-hash round-trip,
  special-char description round-trip), ``TestRenderCodecMetadata``
  (direction-promoted-to-bidirectional, render idempotence).
- Previously-skipped real-capture round-trip tests for Junos
  (``test_real_captures.py``) now run and pass against the
  buraglio fixture — Junos is no longer a parse_only skip case.
- Previously-skipped ``cross_mesh`` cases that filtered on
  ``direction == "bidirectional"`` now include Junos, expanding
  the per-pane rename-overrides smoke surface.

### Added (GAP 1 — EVPN-VXLAN canonical schema [ship-before-wire])

- `CanonicalVxlan` + `CanonicalEvpnType5Route` models in
  `netcanon/migration/canonical/intent.py`.  ``CanonicalVxlan``
  carries ``vlan_id``, ``vni`` (24-bit, validated 1..16777215),
  optional ``mcast_group``, and ``flood_list`` for head-end
  replication.  ``CanonicalEvpnType5Route`` carries ``vrf``,
  ``prefix`` (CIDR, IPv4 or IPv6), and ``rt_imports`` / ``rt_exports``
  for BGP-EVPN IP-prefix advertisements.
- Two new top-level Tier-2 lists on ``CanonicalIntent``:
  ``vxlan_vnis: list[CanonicalVxlan]`` and
  ``evpn_type5_routes: list[CanonicalEvpnType5Route]``.
- Ship-before-wire contract: no codec populates the new fields in
  this commit.  Arista EOS, Juniper Junos, and Cisco IOS-XE CLI
  capability matrices gain ``UnsupportedPath`` entries for
  ``/vxlan-vnis/vni`` and ``/evpn-type5-routes/route`` so the
  pipeline validate stage surfaces "VXLAN / EVPN detected but not
  translated" in the UI banner instead of silently dropping the
  payload.  Access-switch and firewall codecs (Aruba AOS-S,
  OPNsense, MikroTik, FortiGate) don't declare — the feature is
  architecturally inapplicable to their deployment class.
- Documentation: ``ARCHITECTURE.md`` Layer-3 (CIM) section gains
  a "Tier 2 (ship-before-wire)" row in the field-tier table and a
  paragraph describing the pattern, with EVPN-VXLAN as the
  reference case.  ``docs/adding-a-canonical-field.md`` gains a
  "Two shapes of this commit" header distinguishing the MTU-style
  wire-through from the ship-before-wire shape.  ``translator-plans.txt``
  DEFERRED ROADMAP gains a ``[SHIPPED]`` entry for GAP 1.
- Tests: ``tests/unit/migration/test_vxlan_evpn_schema.py`` covers
  model construction, VNI range validation, flood-list semantics,
  IPv6 prefix acceptance, round-trip through pydantic dump/load,
  and the ship-before-wire contract (parametrised check that every
  DC codec declares the two new paths as ``unsupported``).

### Added (Phase 13 — Juniper Junos codec v1 [parse-only] + 7 switching target profiles)

- `netcanon/migration/codecs/juniper_junos/` package — first
  hierarchical-grammar vendor in the portfolio.  v1 parses
  ``set``-form configuration text (output of
  ``show configuration | display set`` on Junos EX/QFX/MX/SRX).
  Direction: parse_only — render-side Junos requires commit /
  apply-groups / candidate-config handling that warrants a
  dedicated follow-up commit.  Strategic use case: migration
  FROM Junos TO Cisco / Arista / Aruba (DC refreshes, SP-to-
  enterprise moves).
- Supported grammar:
  - ``set system host-name``
  - ``set system login user <name> class <class>`` (super-user →
    privilege 15; read-only → privilege 1)
  - ``set system login user <name> authentication
    encrypted-password "<hash>"`` (hash preserved under
    ``junos:<hash>`` vendor tag)
  - ``set interfaces <iface> unit <N> family inet address
    <ip>/<prefix>`` (unit 0 collapsed into parent in v1;
    unit 1+ deferred)
  - ``set interfaces <iface> description "<desc>"`` (top-level
    or unit-scoped)
  - ``set interfaces <iface> disable``
  - ``set vlans <NAME> vlan-id <N>``
  - ``set routing-options static route <dest> next-hop <gw>``
  - ``set snmp community <name> authorization read-only``
  - ``set snmp location "<loc>"`` / ``set snmp contact "<c>"``
  - ``set snmp trap-group <name> targets <ip>``
- Parse-tolerance (silently ignored Tier-3 stanzas):
  ``set protocols bgp`` / ``isis`` / ``ospf`` / ``mpls``,
  ``set routing-instances``, ``set groups`` + apply-groups,
  ``set firewall``, ``set policy-options``, block-form
  (curly-brace) input rejected with a helpful error hinting at
  ``| display set``.
- Port-name identity bridge: Junos media prefixes
  (``ge-`` / ``xe-`` / ``et-`` / ``fe-`` / ``mge-`` / ``xle-``)
  encode speed hints; FPC/PIC/port 3-part naming maps to
  stack/module/port; management (``em0`` / ``me0`` / ``fxp0``)
  → kind=mgmt; ``ae<N>`` → kind=lag; ``irb.<N>`` → kind=svi.
  Cross-vendor: Cisco ``GigabitEthernet1/0/24`` →
  ``ge-1/0/24``; Cisco ``TenGigabitEthernet1/0/48`` →
  ``xe-1/0/48``.
- Real-capture fixture
  `tests/fixtures/real/junos/buraglio_netlab_junos184.set` —
  Junos 18.4R1-S1.1 set-form from ES.net netlab-ns demo.  28
  lines, exercises `em0` + `lo0` with IPv4 + IPv6/ISO/MPLS
  families + root-authentication + BGP + IS-IS + MPLS + LLDP.
- 7 new switching target profiles (feature parity with other
  shipped codecs):
  - Arista: DCS-7050SX-64 (10G TOR, matches the real fixture
    class), DCS-7050CX3-32S (100G leaf), DCS-7280CR3-32P4
    (100G + 400G spine), DCS-7060CX-32S (Tomahawk 100G TOR).
  - Juniper: EX4300-48T (1G campus access + VC stacking),
    EX4600-40F (10G/40G campus aggregation), QFX5120-48Y
    (25G/100G DC leaf).
- Tests (+61 new):
  - 40 unit tests in `tests/unit/migration/test_juniper_junos.py`
    covering parse scalars / interfaces / VLANs / users / routes
    / SNMP / validation / tolerance / probe / port-names.
  - 7 per-profile shipped-profile lock-in tests in
    `test_target_profile_shipped.py`.
  - Cross-vendor port-name-translation tests: Cisco → Junos for
    ``ge-`` and ``xe-`` media prefixes via speed-hint routing.
  - Real-captures harness extended: new `junos` dispatch entry;
    `.set` extension allowlist added.
  - `max_vlans` lock-in extended for the Arista + Junos
    families (all 7 new profiles declare 4094).
- Docs synced per AGENTS.md Documentation Sync Checklist:
  - `CHANGELOG` — this entry
  - `ARCHITECTURE.md` — codec count 6 → 7
  - `netcanon/migration/codecs/README.md` — wire-format table
    gains "Flat set-form command text (Junos)" row
  - `codecs/base.py` INPUT_FORMATS — new `cli-junos-set` entry
  - `vendors/juniper_junos.yaml` — vendor declaration
  - `migrate.html` _VENDOR_LABELS — `juniper_junos: 'Juniper Junos'`
  - `tests/fixtures/real/NOTICE.md` — fixture provenance
  - `tests/fixtures/real/RESULTS.md` — new juniper_junos section
    + summary table (30 → 31 fixtures)

Strategic note on canonical-model extensibility: the Junos port-
name bridge illustrates the ``stack+module+port`` mapping
working for a non-Cisco hierarchical naming scheme — useful
precedent when NX-OS / IOS-XR get added later.  Canonical gaps
exposed that warrant follow-up: ``routing-instances`` (Junos's
VRF equivalent with richer semantics than Cisco's ``ip vrf``),
``groups`` / ``apply-groups`` inheritance, firewall filters,
and per-unit sub-interface modelling.

### Added (Phase 12 — Arista EOS codec v1: 6th shipped vendor, first DC-switching-native)

- `netcanon/migration/codecs/arista_eos/` package — bidirectional
  codec for Arista EOS ``show running-config`` text.  Closes the
  biggest cross-vendor DC migration corridor in enterprise networks
  (Cisco Catalyst 9K / Nexus → Arista 7050 / 7280 / 7500).
- New vendor YAML `netcanon/migration/vendors/arista_eos.yaml`.
- New INPUT_FORMATS entry `cli-arista` in `codecs/base.py`.
- UI vendor-labels dropdown gains `arista_eos: 'Arista EOS'` so the
  rename-modal vendor picker surfaces Arista as a target.
- Codec scope:
  - Parses hostname / dns / ntp / snmp community+location+contact+host
    / interfaces (Ethernet<N>, Ethernet<N>/<M> QSFP breakout,
    Management<N>, Loopback<N>, Vlan<N>, Port-Channel<N>) with
    CIDR `ip address 10.0.0.1/31`, quoted descriptions, shutdown,
    no switchport, switchport access/trunk allowed, channel-group
    membership / vlans / static routes / local users with
    `role <name>` and `secret <alg> <hash>` algorithms.
  - Renders all the above bidirectionally; round-trips the first
    real capture cleanly.
  - BGP / OSPF / MLAG / VXLAN / eAPI-over-HTTP / spanning-tree /
    aaa / daemon parse-and-ignore (Tier-3 grammar).
- Real-capture fixture
  `tests/fixtures/real/arista_eos/ksator_dcs_7150s64_eos4224.txt` —
  real DCS-7150S-64-CL on EOS 4.22.4M-2GB (256 lines, 66 ifaces,
  5 admins across 3 password-mode variants, QSFP breakouts, BGP
  + MLAG stanzas exercised as parse-ignore).  Certainty ships at
  `experimental` — promotion to `best_effort` after ≥1 additional
  capture from a different EOS version.
- Bugs surfaced + fixed during codec v1 development:
  1. Username regex `\s+` bled across newlines, causing users
     disappearing from finditer on multi-user blocks following a
     `secret sha512 $6$...` line.  Fixed via `[^\S\n]+`
     non-newline whitespace matcher.
  2. Render emitted `secret sha512:$6$...` (colon-separated
     canonical form) instead of `secret sha512 $6$...` (wire
     format).  Re-parse then missed the hash.  Fixed to split
     canonical tail into `alg` + `hash` on `:` and emit
     space-separated.
  Both caught by round-tripping the real fixture — textbook
  real-capture-harness validation.
- Port-name identity bridge (`arista_eos/port_names.py`) translates
  cross-vendor: Cisco `GigabitEthernet1/0/24` → Arista `Ethernet24`
  (drops stack+module indices, documented collision trade-off).
  `Port-Channel` canonical capitalisation (distinct from Cisco's
  `Port-channel`).
- Tests (+76 new):
  - 45 unit tests in `tests/unit/migration/test_arista_eos.py`
    covering parse scalars / SNMP / users / interfaces+VLANs /
    input-validation / render / round-trip / port-names / probe.
  - Real-captures harness extended with `arista_eos` in the
    `_VENDOR_TO_CODEC` dispatch map; 3 auto-discovered tests for
    the ksator fixture.
- Docs synced per AGENTS.md Documentation Sync Checklist:
  - `tests/fixtures/real/NOTICE.md` — fixture provenance row
  - `tests/fixtures/real/RESULTS.md` — new arista_eos section
    with coverage matrix + findings + cert decision;
    summary table updated (28 → 30 fixtures total, 10 → 12
    bugs surfaced)
  - Vendor-count test loosened to `>= 7` rather than `== 6`
    so adding a future codec doesn't force a mechanical edit
    (individual per-vendor presence tests lock in identity)
- Strategic note: adding Arista exposes canonical gaps in EVPN
  type-2/type-5 routes and VXLAN VNI-to-VLAN mapping — both are
  first-class in EOS and currently unmodelled in CanonicalIntent.
  Parse-and-ignore for v1; schema extension deferred to a follow-
  up commit (unblocks Arista ↔ NX-OS ↔ Junos EVPN-fabric
  migrations).

### Added (Phase 11 — 2 real-capture fixtures for grammar diversity)

- `tests/fixtures/real/aruba_aoss/hpe_community_5406rzl2_kb1515.cfg`
  — first fixture on the KB software branch + first fixture on
  the 5400R modular-chassis class.  Exercises `module A type j9534a`
  line-card declarations + letter-slot port ranges + multi-VLAN
  `ip helper-address` grammar.  Source: HPE Community forum thread
  6935784.
- `tests/fixtures/real/cisco_iosxe/cml_basic_forwarding_iosv_r1_ospf.txt`
  — first OSPFv2 multi-feature-grammar fixture in the corpus.
  `router ospf 1` + `router-id` + `passive-interface` + 5 `network`
  statements + per-interface `ip ospf cost` tuning + dot1Q
  subinterfaces.  Source: CiscoDevNet/cml-community under BSD-3-Clause.

### Changed (god-file cleanup — fortigate_cli codec split into parse.py + render.py)

- `netcanon/migration/codecs/fortigate_cli/codec.py` was the 4th-
  largest codec file at ~1068 LOC carrying both parse dispatchers
  (`_apply_<path>` functions) and render logic inline on the
  `FortiGateCLICodec` class.  Split into:
    - `parse.py` — block-model (`_ConfigBlock` / `_EditBlock`),
      tokeniser (`_parse_blocks`), per-stanza dispatchers
      (`_apply_system_global`, `_apply_system_interface`, …), IP
      mask utilities shared with render, LACP-mode maps.  Public
      entry `parse_intent(raw) -> CanonicalIntent` replaces the
      previously-inline parse method body.
    - `render.py` — canonical tree → FortiOS CLI text.  Public
      entry `render_intent(tree) -> str`.  Imports IP utilities +
      canonical-to-FortiGate LACP map from `parse.py` (one-
      directional edge, no circular risk).
    - `codec.py` — thin orchestrator retaining the
      `FortiGateCLICodec` class with metadata, probe, capability
      matrix, port-name delegates.  `parse()` and `render()` are
      one-line delegators to the sibling modules.  Re-exports
      `_parse_blocks`, `_prefix_to_mask`, `_mask_to_prefix` via
      `__all__` so `tests/unit/migration/test_fortigate_cli.py`
      (which pins internal symbols as test contracts) doesn't
      need to change.
- `vlan_heuristics.py` already existed as an earlier partial
  extraction; untouched by this commit.
- **Line counts post-split:** codec.py 246 (was 1068, −77%),
  parse.py 675, render.py 290.  Total is up slightly because
  each new module carries its own docstring + imports — the win
  is focus, not line reduction.
- `netcanon/migration/codecs/fortigate_cli/__init__.py` docstring
  refreshed: stale `certainty: best_effort` claim corrected to
  `certified` (matches RESULTS.md post-promotion), module-layout
  section added describing the new parse/render split, Tier-2
  coverage (SNMP / admin / RADIUS / DHCP) enumerated, structural
  quirks updated with the `set radius-port 0` canonicalisation.
- `netcanon/migration/codecs/README.md` Module layout section
  extended with the `parse.py` / `render.py` split pattern.
  Lists remaining split candidates (mikrotik_routeros,
  cisco_iosxe_cli, aruba_aoss, opnsense) and the re-export
  discipline that keeps tests unchanged across a split.
- **No behaviour change**: 1526 passed, 60 skipped (identical
  to pre-split).  All 26 `test_fortigate_cli.py` wire-through
  tests + real-capture harness + cross-mesh mesh still green.

### Added (P2C5 — per-pane SNMP community rename: fourth per-pane override category)

- New canonical orchestrator
  `netcanon/migration/canonical/snmp_names.py` — community-string
  rename via the same `build_X_rename_transform(rename_map) →
  (transform, result)` shape as ports / VLANs / local_users.
  Scope is scalar (`CanonicalIntent.snmp` holds a single
  `CanonicalSNMP` object) so the rename map is effectively single-
  entry but keeps the `dict[str, str | None]` shape for API
  symmetry with the list-oriented panes.
- Pipeline extension:
  `run_plan_with_overrides` grows a new optional
  `snmp_community_rename_map` parameter.  Runs last in the override
  chain (independent of ports / VLANs / users so ordering is free).
  Capture-first transform extended to populate
  `source_snmp_community` alongside `source_vlans` / `source_local_users`.
- Model fields on `MigrationJob`:
  `snmp_community_renames`, `snmp_community_drops`,
  `source_snmp_community`.  New field on `MigrationPlanRequest`:
  `snmp_community_rename_map`.
- New endpoint `POST /api/v1/migration/plan/snmp` — fourth
  concrete per-pane override endpoint.  Follows the `/plan/ports`
  pattern established in P2C1; ignores other category maps posted
  in the same body.  Main `POST /plan` routing predicate updated
  to detect `snmp_community_rename_map` (closes the same silent-
  drop class of bug the P2C4 fix caught for VLAN + user maps).
- UI:
  - New SNMP rail button in the rename modal (4th category).
  - New SNMP pane with single-row community-rewrite table.
    Structurally a table for visual parity with the list-oriented
    panes; always exactly one row.
  - New `_partials/snmp-rename-table.js` partial (~170 LOC)
    rendering the row with input + clear/un-clear/keep-verbatim
    three-state link.  The "drop" link is labelled **clear** on
    this pane because clearing the community omits the entire
    SNMP block rather than removing an identity.
  - `_renameSnmpCommunityMap` module-scope state; wired into
    localStorage ack persistence (schema-v1 additive — missing
    keys load as empty dict), reset-all, capture-for-rename gate,
    open-modal render, showRenameCategory pane switch,
    renderRenameRailCounts.
  - `rename-panel.js` preview substitution extended for SNMP
    community rename (whole-word match, same technique as VLANs
    + users).  Clear semantics still require server re-render
    (the SNMP stanza itself disappears, not a substitution).
  - `rename-panel.js` summary adds an SNMP sub-summary that
    surfaces only when SNMP activity exists (0-state gate parity
    with VLAN + user sub-summaries).
  - `rename-apply.js` POST body augmented with
    `snmp_community_rename_map` when the map is non-empty
    (same gate-on-non-empty pattern as the other categories).
- Tests:
  - 20 new unit tests in
    `tests/unit/migration/test_snmp_names.py` covering identity,
    rename, clear, no-SNMP-block warning, non-matching-source
    warning, input validation, transform builder.
  - 8 new integration tests in
    `tests/integration/test_migration_api.py` — new
    `TestPlanSnmpEndpoint` class + extensions to
    `TestSourceShapeCapture` (source_snmp_community
    populate/empty/pre-mutation contracts) +
    `TestPlanMultiCategoryRoutingSnmp` (routing + four-way
    composition).
  - Cross-mesh extension in
    `tests/unit/migration/test_cross_mesh_overrides.py`: new
    parametrized `test_snmp_community_rename_smoke_cross_codec`
    across cisco_iosxe_cli + aruba_aoss + mikrotik_routeros as
    sources, aruba_aoss + mikrotik_routeros as targets
    (cisco_iosxe_cli is parse_only, excluded from target set).
    New `test_four_category_overrides_in_one_call` locks in
    the full port+vlan+user+snmp composition contract.
- Docs synced per AGENTS.md Documentation Sync Checklist:
  - `tests/testid_reference.md` — 11 new testid rows documented
    for the SNMP pane (verified via grep self-check: reference
    count matches template/partial count).
  - `netcanon/templates/migrate.html` Contents map comment —
    adds the new partial entry.
  - Route docstring in `netcanon/api/routes/migration.py`
    (top-of-file endpoint enumeration) — lists `/plan/snmp`.
  - Pipeline docstring in
    `netcanon/services/migration_pipeline.py` — category
    support list updated; new capture-only field documented.
  - Model docstrings on `MigrationJob` + `MigrationPlanRequest`.
  - `HUMAN_TESTING.md` — new SNMP-pane manual-test scenarios.
  - `ARCHITECTURE.md` — queued "per-pane SNMP / RADIUS overrides"
    item updated to reflect SNMP is no longer queued.
- **Deferred** (explicitly NOT in this commit; reserved in
  pipeline param docstring): SNMPv3 user rename (requires
  canonical-schema extension; CanonicalSNMP models v1/v2c only),
  SNMP trap-host rename (list surface parallel to this commit's
  scalar community surface — same recipe applied again,
  reserved parameter name `snmp_trap_host_rename_map`).

### Fixed (stale cert-promotion drift in RESULTS.md / ARCHITECTURE.md / translator-plans.txt)

- `tests/fixtures/real/RESULTS.md` closing paragraph said
  "No codec is `certified` yet.  The threshold is ≥3 captures from
  ≥2 OS versions with round-trip stability — each vendor is ~2
  captures short of that bar".  Factually wrong — every shipped
  codec has since been promoted to `certified` (cisco_iosxe_cli,
  opnsense, mikrotik_routeros, fortigate_cli, aruba_aoss).  The
  Summary table above the paragraph already showed all five as
  certified ✅; the prose hadn't been updated to match.  Replaced
  with a "Certification state (April 2026)" block explaining the
  corpus purpose has shifted from promotion-driving to
  hardening-driving, with concrete grammar-diversity gaps listed
  (FortiGate multi-VDOM, FortiOS 7.4, RouterOS 7.19+, OPNsense
  25.x, AOS-S 16.11 late patches) — all opportunistic, none
  blocking.
- `ARCHITECTURE.md` "Real-capture validation" paragraph said the
  harness "is what gates codec promotion to `certified`".  Past
  tense now: all five are already at `certified`; the harness
  drives hardening rather than promotion.
- `ARCHITECTURE.md` Evolution roadmap "What's queued" listed
  "Fixture hunting to promote more codecs toward `certified`" as
  a top queue item.  Replaced with the accurate grammar-diversity
  gap list (pointers to RESULTS.md for the live version) + added
  per-pane SNMP / RADIUS override work to the queue (already
  slated via the established three-step recipe but previously
  undocumented in ARCHITECTURE).
- `translator-plans.txt` R6/7 "REAL-CAPTURE VALIDATION" block
  contained a snapshot of bug-fix session state that predates
  the cert-promotion wave — results table showed mikrotik as
  "CERTIFIED" and others as "best_effort", plus a "Still to do
  — to graduate any codec to `certified`" subsection listing
  fixture-count shortfalls.  Marked the whole block as
  SUPERSEDED with a pointer to RESULTS.md as the single source
  of truth.  Block preserved as a historical journal entry
  (per the CHANGELOG-archival-records Hard Rule exception) —
  its value now is showing which bugs each promotion surfaced,
  not current state.

This is a pure-docs fix — no code changes, no test count delta.
The drift slipped through earlier promotion commits because the
CHANGELOG + RESULTS.md tier-table got updated in each promotion
but the paragraph-form prose below the tables (and the
ARCHITECTURE queued-work + translator-plans historical block)
were left behind.  A useful illustration of why the Doc Sync
Checklist Hard Rule exists: numbers in tables fail loudly when
wrong, prose rots silently.

### Added (deferred item — FortiGate `max_vlans` version-tuning + `max_vlans_source` provenance field)

- New optional `TargetProfile.max_vlans_source: str` field carrying a
  free-text provenance string for `max_vlans` — pins which firmware
  release / datasheet the cap was validated against (e.g.
  `"FortiOS 7.2 Maximum Values Table, per-VDOM system.interface type
  vlan"`).  Makes version-tuning passes mechanically auditable via
  `grep` and lets the UI surface the source in a fit-check banner
  tooltip.
- All 3 shipped FortiGate profiles (40F / 60F / 100E) populated with
  `max_vlans_source` pinning FortiOS 7.2 as the Max Values Table
  reference.  FG-100E additionally calls out the
  `user_contrib_fg100e_fos7213.conf` real capture as the grounding
  datapoint — same capture that certifies the `fortigate_cli` codec.
- YAML comment sweep on the 3 FortiGate profiles: expanded the
  provenance block to name a specific FortiOS minor version, cite
  the Max Values Table URL, and explain that values can drift ±1
  between 7.0 / 7.2 / 7.4 / 7.6 so operators should re-verify on
  firmware upgrades.
- **Factual fix:** earlier comments said "up to N VLANs across all
  VDOMs".  Fortinet's Max Values Table publishes rows *per-VDOM*,
  not VDOM-aggregate — corrected across all three FortiGate
  profiles.  No numeric change, just clarified scoping.
- New unit test `test_fortigate_profiles_declare_max_vlans_source`
  enforces every shipped FortiGate profile declares the field and
  pins a specific FortiOS minor (rejects `"FortiOS 7.x"`-style
  vague strings).
- New integration test class `TestMaxVlansSourceSerialization`
  proves API serialization: FortiGate profiles surface
  `max_vlans_source` with a FortiOS version pin; profiles that
  haven't opted in serialize the field as `""` (not `null`).
- Other vendors (Aruba / Cisco / MikroTik / OPNsense) intentionally
  leave `max_vlans_source` empty for now — populate opportunistically
  when each vendor's caps get revisited.  The field is optional +
  defaulted so no mass-backfill is required.
- Numbers themselves unchanged: 40F / 60F still 512, 100E still 1024.
  This commit is a provenance tune, not a value tune — the existing
  values were the correct conservative floor for FortiOS 7.x; the
  improvement is that future value changes will now carry an
  audit-trail.

### Changed (kill module-variant allowlist manual-sync tax)

- The `MODULE_VARIANT_PROFILES` set was duplicated as two identical
  literals — one in `tests/unit/migration/test_target_profile_shipped.py`
  and one in `tests/integration/test_migration_target_profiles_api.py`
  — with a "kept in sync manually" comment on each and a matching
  Documentation Sync Checklist row in AGENTS.md.
- Extracted to a canonical shared module at
  `tests/fixtures/module_variants.py` (following the existing
  `tests/fixtures/` convention for test-input data).  Both test
  classes now import from there via `MODULE_VARIANT_PROFILES = MODULE_VARIANT_PROFILES`
  (class-body re-bind of the module-level constant — standard
  Python idiom).
- New CI-guard test
  `test_module_variant_allowlist_shared_with_integration_tier`
  asserts both class attributes are IDENTITY-equal (`is`) to the
  canonical set — catches accidental shadowing with a literal even
  if the content would otherwise match.
- AGENTS.md Documentation Sync Checklist row updated: single-file
  edit + CI-guard replaces the two-file manual-sync discipline.

### Added (deferred item 3 — more target profiles: Netgate ARM + Deciso DEC600)

- `opnsense_netgate_sg1100.yaml` — 3-port ARM desktop firewall,
  Marvell Armada 3720 + MV88E6141 switch chip.  Interface layout
  follows pfSense's published DSA + VLAN-tag convention
  (`mvneta0.4090` WAN, `mvneta0.4091` LAN, `mvneta0.4092` OPT).
- `opnsense_netgate_sg3100.yaml` — 5-port ARM desktop firewall
  (1 direct WAN + 4 switch LAN), Marvell Armada 38x.  Uses the
  VLAN-tag convention for the 4 LAN ports on `mvneta2`.
- `opnsense_deciso_dec600_igc.yaml` — 5-port 2.5GbE desktop
  appliance, Intel i226-V via `igc(4)`.  Complements the
  existing Netboard A-series (embedded PCB form-factor) with
  Deciso's current desktop-chassis line.
- **Caveat:** both Netgate profiles are tagged LOWER-CONFIDENCE.
  The SG-1100 and SG-3100 are primarily pfSense platforms; OPNsense
  on ARM is community-grade and interface naming may vary on stock
  FreeBSD arm64 OPNsense.  Operators running a non-Netgate-branded
  build should file an override profile if their `ifconfig`
  output disagrees.
- 3 new shipped-profile lock-in tests cover port-id list,
  kind-classification, max_vlans/max_local_users values.

### Changed (stale-comment sweep on existing OPNsense + FortiGate profiles)

- All 24 existing OPNsense profile YAMLs had a comment claiming
  "the OPNsense codec doesn't yet round-trip `<system><user>`
  blocks, so the local-users pane surfaces a compat banner".
  Option A cleared the false declaration and verified the round-
  trip works; the comment was stale.  Replaced with an accurate
  post-Option-A rationale (unbounded-limit, not codec gap).
- FortiGate 40F profile comment analogously refreshed; 60F and
  100E cross-reference 40F so they inherit the update via the
  existing `see fortigate_40f.yaml for rationale` pointers.

### Fixed (Option A — strip false `unsupported_rename_categories` on OPNsense + FortiGate)

- Both codecs already round-trip `CanonicalLocalUser` end-to-end
  (OPNsense parses + renders `<system><user>` blocks; FortiGate
  parses + renders `config system admin` blocks — 26 wire-through
  tests cover both in `test_local_users_wire_through.py`).  The
  earlier `unsupported_rename_categories = {"local_users"}`
  declarations were based on an incorrect session-compact-prompt
  assumption that users kept landing in `raw_sections`.  Cleared.
- Integration test `test_unsupported_rename_categories_exposed`
  rewritten to lock in the post-Option-A invariant — no shipped
  bidirectional codec lists any category as unsupported.  The
  attribute stays wired as an extension point for future codecs
  with genuine Tier-3-only surfaces (RADIUS, SNMP panes when
  those ship).
- Both codec capability matrices gain three supported xpaths for
  `/aaa/authentication/users/user/config/{username,password,role}`
  so the validate-stage classifier correctly reports users as
  supported rather than implicit-default.
- E2E test restructure: `TestRenameModalCompatBanner` now covers
  Cisco → {Aruba, OPNsense, FortiGate} all asserting the banner
  stays hidden; pre-fix it asserted the OPNsense banner was
  visible (now wrong post-Option-A).  The renderer's
  limit-undeclared branch for the fit-check banner is instead
  covered by the schema unit tests — dropped the stale e2e case
  that assumed OPNsense profiles omit `max_vlans` (item-7
  enrichment populated every OPNsense profile's `max_vlans=4094`).

### Added (ship `probe:` block for Cisco IOS-XE family-base + overlay inheritance note)

- `definitions/cisco/ios-xe/17.x.yaml` now declares a `probe:` block
  — the first shipped definition to opt into the P1C3 probe-phase
  machinery.  Command is `show version`; two regex patterns feed
  `DefinitionLoader.resolve()` and `DeviceProfile.detected_facts`:
    - `detected_os_version: "Version\\s+(\\d+\\.\\d+)"` — captures
      major.minor (e.g. `17.12`) from `Version 17.12.03, RELEASE …`.
      Major.minor is deliberate: the 17.12 overlay pins
      `os_version: "17.12"` and the resolver's match is exact-string,
      so capturing the full patch level (`17.12.03`) would MISS
      the overlay.
    - `detected_model: "Model Number\\s+:\\s+(\\S+)"` — captures
      hardware model (e.g. `C9300-48P`) from the `Model Number` line
      of Catalyst 9000 `show version` output.
- `definitions/cisco/ios-xe/17.12.yaml` intentionally does NOT
  declare its own `probe:` block.  The backup pipeline runs probe()
  on the family-base collector BEFORE resolving overlays, so the
  overlay inherits the family-base probe behaviour without
  duplication.  Inline comment in the overlay YAML documents this
  so a future contributor doesn't "helpfully" copy the block down.
- New integration tests in `tests/integration/test_backup_probe_wiring.py`
  (`TestShippedCiscoIOSXEProbeBlock`) lock in that the shipped
  family-base carries a non-empty `probe.command` with both
  `detected_os_version` + `detected_model` patterns, and that the
  17.12 overlay ships with NO probe block of its own.

### Changed (data enrichment — soft-limit `max_vlans` populated across MikroTik / OPNsense / FortiGate)

- Every shipped target profile now declares `max_vlans` so the
  VLAN-pane fit-check banner renders something for every
  selectable target.  New per-vendor distribution:
    - MikroTik RouterOS (2 profiles): 4094 — 802.1Q protocol
      ceiling supported universally on modern RouterOS.
    - OPNsense (24 profiles): 4094 — FreeBSD netgraph VLANs,
      protocol ceiling is the only hard limit.
    - FortiGate: 40F = 512, 60F = 512, 100E = 1024 (from
      Fortinet's FortiOS 7.x "Maximum Values Table").
  Aruba + Cisco values from prior commit unchanged.
- `max_local_users` intentionally STAYS unset on MikroTik /
  OPNsense / FortiGate profiles:
    - MikroTik: software-unbounded, no meaningful fit-check.
    - OPNsense / FortiGate: codecs don't yet round-trip
      CanonicalLocalUser, so the local-users pane surfaces a
      compat banner (see Item 1B) instead — setting the fit-check
      limit would visually overlap with that banner and confuse
      operators.
- New shipped-profile lock-in tests (3 cases) guard against
  silent drift: every profile declares `max_vlans`, distinct
  values match the documented per-vendor rationale, and
  `max_local_users` stays unset on the three soft-limit vendor
  families.

### Added (per-pane capacity fit-check banners — `TargetProfile.max_vlans` + `max_local_users`)

- Two new optional fields on `TargetProfile`:
    - `max_vlans: int | None` — active-VLAN limit for the device.
    - `max_local_users: int | None` — local-account limit.
- Each rename-modal pane (VLANs, local_users) renders its own
  fit-check banner sourced from these fields.  Three states:
  hidden (no profile picked OR limit undeclared) / green OK
  ("VLAN fit: N / limit") / red block ("VLAN OVER capacity — K
  over, pick a larger model").
- Pane-scoped: the ports fit-check banner (driven by per-kind
  capacity counts) stays in its own element; each new category's
  banner is a sibling, not an overload.  Adding a future SNMP /
  RADIUS fit-check banner follows the same pattern.
- Shipped profiles populated where datasheet numbers are
  reliable:
    - Aruba 2930F family (4 profiles): max_vlans=2048, max_local_users=16
    - Aruba 3810M (2): max_vlans=4094, max_local_users=16
    - Aruba 6300M (1): max_vlans=4094, max_local_users=64
    - Cisco C9300 family (6) + C9500 (2): max_vlans=4094
  Softer-limit vendors (MikroTik / OPNsense / FortiGate) left
  unset — populating them with best-guess values would mislead
  operators more than helping.
- 5 new unit tests (TargetProfile schema) + 3 new e2e tests
  (TestRenameModalPerPaneFitCheck).

### Added (Item 1 Option B — target-codec compatibility banners on rename panes)

- `CodecBase.unsupported_rename_categories: frozenset[str]`
  declares per-pane categories the codec doesn't round-trip.
  OPNsense + FortiGate both declare `{"local_users"}` because
  their parse+render path currently leaves user blocks in
  `raw_sections` as Tier-3 passthrough.
- `CodecInfo.unsupported_rename_categories` exposes the list via
  `GET /api/v1/migration/adapters`; UI caches it alongside the
  existing adapter metadata.
- Rename modal's local-users pane now shows an amber banner
  up-front when the active target is in the declaring set.
  Warns operators that rename overrides apply to the canonical
  tree but won't reach rendered output.  Kills the
  ghost-success bug where `job.local_user_renames` populates but
  the rendered config has no user stanzas.
- Rename-open button gate broadened (was ports-only): now shows
  when ANY pane has content (port renames/warnings, source_vlans,
  source_local_users).  Pre-P2C4 gap — becomes visible once the
  VLAN/users panes started carrying non-port-dependent content.
- Deferred: **Option A** — full parser+render wiring for
  local_users on OPNsense + FortiGate.  Tracked for the
  "certified-tier Tier-2 parity" sweep; remove the codec
  declarations when it ships.
- 2 new integration tests + 2 new e2e tests.

### Fixed (post-P2C4 rename-modal UX polish + OPNsense probe support)

- **Target-profile dropdowns scoped to ports pane.**  The vendor /
  model / module selects in the modal toolbar + the fit-check
  banner drive ports-pane-specific behaviour only.  Previously
  visible on all panes, misleading operators into thinking they
  needed to pick a profile before renaming VLANs or users.  Now
  hidden when the active rail category isn't `ports`.  New
  testid: `migrate-rename-target-profile-group`.
- **Collision blocks Apply across all panes.**  Pre-fix, ports-
  pane collisions disabled Apply but VLAN + local-user collisions
  only showed the ⛔ icon while letting Apply proceed (server
  would auto-merge).  Fixed for feature parity — any-pane
  collision now disables Apply so operators must explicitly
  resolve rather than silently ship a merged output.
- **Preview pane extended to VLAN + user renames.**  The client-
  side approximation (whole-word substitution) now covers all
  three categories' rename operations.  Drops still rely on the
  server-side re-render (Apply) since multi-line stanza removal
  isn't safe client-side.
- **ParamikoShellCollector.probe() implementation.**  OPNsense
  backups can now populate `detected_facts` — the paramiko_shell
  strategy finally has a probe override.  Handles the console
  menu opt-in; short-lived separate session with tighter idle +
  timeout bounds (~1.6s idle, 30s absolute).  Failure modes still
  never-fatal; family-base fallback unchanged.

### Added (P2C4 — local-users rename pane + three-category composition fix)

- Third per-pane override category after ports + VLANs.  New
  orchestrator `netcanon/migration/canonical/local_user_names.py`
  walks `CanonicalIntent.local_users` and applies a string → string
  (or string → None for drop) rewrite map.  Collision merge:
  highest `privilege_level` wins, first non-empty `role` wins,
  first `hashed_password` wins (hashes aren't composable).
- `run_plan_with_overrides` gains `local_user_rename_map`
  parameter.  `MigrationJob` gains `local_user_renames` +
  `local_user_drops` + `source_local_users` fields.  Capture
  transform now snapshots user names alongside VLAN IDs + hostname.
- New endpoint `POST /api/v1/migration/plan/local_users` follows
  the per-pane pattern — delegates to `run_plan_with_overrides`
  with only its category's map populated.
- **Latent /plan routing fix:** `/plan` previously only engaged
  the rename-aware pipeline when `port_rename_map` or
  `target_profile` was set.  A client posting `vlan_rename_map`
  (shipped P2C2) or `local_user_rename_map` WITHOUT also setting
  `port_rename_map` silently dropped the override.  Fixed:
  `/plan` now dispatches directly to `run_plan_with_overrides`
  whenever ANY override map is present and threads every category
  through.
- UI: left rail gains a "Local users" button + category pane
  rendered by new `_partials/local-user-rename-table.js`
  (structural copy of vlan-rename-table.js, string keys, free-text
  rewrite).  Every operator override is persisted to localStorage
  under the same `netcanon.rename-ack.v1:…` key as the other
  categories — additive schema, old payloads load unchanged.
- Apply flow: `local_user_rename_map` included in the POST body
  only when the operator actually touched a user row (gate-on-
  non-empty — same pattern as VLANs).
- 10 new testids under
  `tests/testid_reference.md` → "Left-rail category nav + VLAN pane"
  section now also covers local-users rows, override inputs, drop
  links, and the summary chip.
- 16 new unit tests (`tests/unit/migration/test_local_user_names.py`)
  + 16 new integration tests (`TestPlanLocalUsersEndpoint`,
  `TestPlanMultiCategoryRouting`, source-shape capture) + 9 new
  cross-mesh smoke cases + 6 new e2e tests
  (`TestRenameModalLocalUsersPane`).

### Added (P1C3 — pre-backup probe phase + layered-definition resolver wiring)

- New `ProbeConfig` block on `DeviceDefinition` (optional `command:` +
  `patterns:` regex map).  Empty defaults keep existing definitions
  working unchanged; only definitions that opt in by declaring a
  probe command participate.
- New pure-function parser at `netcanon/collectors/probe.py` with
  11 unit tests (`tests/unit/test_probe_parser.py`).  Handles
  multi-line output, missing captures, malformed regexes, auto-
  timestamps successful results.
- New `probe()` method on `BaseCollector` (no-op default) + concrete
  Netmiko implementation.  Short-lived separate session (30s probe
  timeout, 4x tighter than the main 120s config timeout).  Failures
  are non-fatal — log WARNING, return `{}`, proceed with family-base.
- Backup pipeline (`_process_one_device`) now threads a
  `DefinitionLoader` + device-profile store through the execution
  path: probe → resolve overlay (operator pins win over detected
  facts) → persist `detected_facts` on the linked profile → collect
  against the resolved definition.  Both interactive and scheduled
  backups get the same treatment.
- `app.state.definition_loader` exposed on the FastAPI app alongside
  the existing `app.state.definitions` dict (kept for endpoints that
  iterate type_keys).  New `get_definition_loader` dependency.

### Added (P2C3 — rename-modal left-rail category nav + VLAN pane + localStorage persistence)

- Rename modal body refactored from `table | preview` into
  `rail | table | preview`.  Left rail is a vertical category
  navigation with Ports and VLANs today; the rail is the extension
  point for future categories (local_users / SNMP / RADIUS under
  P2C4+).  Counts + badges on rail buttons show per-category row
  totals at a glance.
- New `_partials/vlan-rename-table.js` renders the VLAN pane —
  structural parallel to the existing ports table but simpler
  (integer IDs, no per-kind sections, no target-profile dropdown).
  Rows enumerate every VLAN declared in the source config; each row
  has an integer override input + drop/un-drop link.
- `MigrationJob` exposes `source_vlans: list[int]` and
  `source_hostname: str` populated by a capture transform that
  runs ahead of every user-override transform in
  `run_plan_with_overrides`.  The UI needs both — source_vlans
  drives the VLAN pane's row enumeration, source_hostname keys
  the localStorage persistence entry.
- localStorage ack persistence: overrides survive page reloads
  keyed on `(source_codec, target_codec, hostname)` under
  `netcanon.rename-ack.v1:…`.  Load on modal-open, save on every
  render-summary (universal choke point), clear on Reset-all.
  Surfaces an age hint on restore ("Restored prior overrides
  (N port, M VLAN) from 3m ago").
- ARCHITECTURE.md gains a "Per-pane overrides (Tier-3 rename
  modal)" section documenting the three-step recipe for adding a
  new category (orchestrator → pipeline wiring → UI rail + pane),
  the sentinel semantics, and the localStorage schema.
- 14 new testids documented in `tests/testid_reference.md` under
  a new "Left-rail category nav + VLAN pane" subsection.
- 7 new e2e tests (`TestRenameModalLeftRail`,
  `TestRenameModalLocalStoragePersistence`) + 5 new integration
  tests (`TestSourceShapeCapture`).

### Added (P2C2 — canonical VLAN-rename orchestrator + /plan/vlans endpoint)

- Cross-vendor VLAN-ID rewrite transform
  (`netcanon/migration/canonical/vlan_names.py`) — walks the
  canonical tree and rewrites every VLAN-referring field
  (`CanonicalVlan.id`, `access_vlan`, `trunk_allowed_vlans`,
  `trunk_native_vlan`, `voice_vlan`).  Drop semantics via `None`
  values; collision merge (union of port lists, concat of SVI
  addresses) when multiple source IDs map to the same target.
- `POST /api/v1/migration/plan/vlans` per-pane endpoint accepts
  only the VLAN override map; delegates to `run_plan_with_overrides`
  with `port_rename_map=None`.
- `run_plan_with_overrides` extended with `vlan_rename_map`
  parameter.  VLAN transform runs AFTER port rename so port-name
  rewrites don't race with VLAN-ID changes.
- Cross-mesh smoke tests
  (`tests/unit/migration/test_cross_mesh_overrides.py`) parametrised
  over every `(source, target)` capable pair; new `cross_mesh`
  pytest marker with documented 30s aggregate-runtime budget.

### Added (P2C1 — run_plan_with_overrides engine + /plan/ports per-pane endpoint)

- New `run_plan_with_overrides` in `migration_pipeline.py` — the
  shared engine for every per-pane override surface.  Grows via
  optional category-map parameters; existing `run_plan` +
  `run_plan_with_rename` signatures stay frozen per AGENTS.md's
  pipeline-signatures invariant.
- Sentinel semantics standardised across categories:
  `None` → don't engage, `{}` → engage with auto-heuristic only,
  `{src: tgt}` → engage with explicit overrides.
- `POST /api/v1/migration/plan/ports` per-pane endpoint — first
  instance of the per-pane pattern; dispatches to
  `run_plan_with_overrides` with only `port_rename_map`
  populated.

### Added (Tier 3 port-rename modal — interactive cross-vendor interface-name mapping in the /migrate UI)

- Draggable, non-blocking modal on the Migrate results view that
  exposes the Tiers 1+2 port-name translator to the operator.  The
  cross-vendor rename that used to happen silently (or fail to
  happen at all — the original complaint was Cisco ``GigabitEthernet1/0/24``
  leaking into Aruba output) is now:
    * **Auditable** — a mapping table shows every source name, the
      codec's auto-computed target, and warnings for untranslatable
      cases (breakout ports, loopbacks without target equivalents,
      uplink modules without operator input, etc.)
    * **Editable** — per-row override dropdown (profile-driven when
      a target profile is selected) or free-form input; user's
      choice wins over the auto-heuristic.
    * **Validated** — collision detection disables the Apply button
      when two sources map to the same target; warnings count shown
      in the header badge.

- Modal features:
    * Draggable (grab the ⋮⋮ grip header); non-blocking — user
      can drag aside to consult the rendered output behind it.
    * 2-pane layout: mapping table on the left (grouped by kind —
      physical / lag / svi / loopback / tunnel / breakout /
      hw_aggregate / virtual / unknown), client-side live preview
      on the right.
    * Sections collapsible; first-non-empty + any section with
      warnings/collisions auto-opens.
    * Target-profile selector in the toolbar: picking a profile
      swaps free-form inputs for dropdowns listing only ports the
      target hardware actually has; falls back to free-form when
      none selected.
    * Collision icons (⛔) with tooltips naming the colliding
      sources; warning icons (⚠) with the orchestrator's advisory
      text as tooltips.
    * "Reset all" clears user overrides; Apply POSTs to ``/plan``
      with the updated rename_map and refreshes the main output
      pane.

- The ``/migrate`` form now always sends ``port_rename_map: {}`` to
  opt into the rename-aware pipeline.  This means cross-vendor
  translations no longer leak source-vendor port names into the
  target output by default — the original Tier 3 complaint is fixed
  end-to-end.

- New e2e tests (7):
  ``tests/e2e/test_migrate_rename_modal.py`` — visibility gating,
  modal open/close, section rendering, override apply end-to-end,
  collision detection disables Apply, loopback warning row styling.

- Docs: ``translator-plans.txt`` gains a "PORT-NAME TRANSLATION
  (Tiers 1+2+3) — SHIPPED + DEFERRED WORK" section tracking the
  deferred save-as-profile, 3-pane layout, hardware fit-check,
  rename-operation diff, and target-profile expansion.
  ``HUMAN_TESTING.md`` gains a per-feature manual-verification
  checklist for the modal.

### Added (Tier 3 port-rename backend: target profiles + rename-aware /plan)

See commit ``b5cb5ca`` for the backend foundation that the frontend
consumes.

### Added (FortiGate CLI promoted to `certified` — 5th codec to reach the bar + real RADIUS round-trip bug fixed)

- User-contributed real ``show full-configuration`` from a physical
  **FortiGate 100E** running **FortiOS 7.2.13** (build 1762),
  captured via Netcanon's backup layer and sanitised per AGENTS.md
  hard rule.  ~35K lines — 34 interfaces, 5 VLANs, 2 LAGs, 6 DHCP
  servers, 3 admins, 1 RADIUS server, 1 SNMP community, full
  firewall policy table + VIPs + SDWAN + SSL-VPN.  First physical-
  appliance FortiGate capture in the corpus (existing 2 from
  KevinGuenay were a VM hub + 70G branch, both on 7.6.6); first
  FortiOS 7.2.x capture.
- ``user_contrib_fg100e_fos7213.conf`` — sanitisation inventory
  (per AGENTS.md "never commit real credential hashes" rule):
  - 48 ``ENC <base64>`` encrypted FortiGate secrets (admin
    passwords, RADIUS secret, FortiGuard proxy password, NTP
    key, DHCP option passwords, TACACS passwd1/2/3, etc.)
    replaced with ``ENC fakeEncodedSecret...`` markers
  - 14 ``-----BEGIN (ENCRYPTED) PRIVATE KEY-----`` /
    ``-----END`` blocks stripped with ``REMOVED_FIXTURE_SANITISATION``
    placeholder (public certificate chains retained for grammar)
  - 5 SSH public keys (``ssh-rsa AAAA...``) replaced with
    ``AAAAfakeSSHPublicKey...`` markers
  - 1 Firebase/APNs registration ID (``set reg-id "dxurAYJ..."``)
    sanitised
  - Real WAN IP ``[redacted-WAN-IP]`` (6 occurrences in address
    objects + VIP ``set extip`` entries) replaced with RFC 5737
    TEST-NET-3 ``203.0.113.217``
  - Real email ``[redacted-email]`` (2 occurrences in admin
    contact fields) replaced with ``netadmin@example.test``
  - All other real data retained — RFC1918 addressing, hostname
    ``fortihome``, alias ``FortiGate-100E``, interface descriptions,
    firewall policies with internal IPs, DHCP reservations,
    SD-WAN SLAs, SSL-VPN portal config.
- **Real codec bug surfaced + fixed in the same commit:** FortiOS
  uses ``set radius-port 0`` as the idiom for "use the default port
  1812" — real FortiOS exports (including the FG100E capture)
  emit this literally.  Our parser stored the 0 faithfully in
  ``CanonicalRADIUSServer.auth_port``, but the renderer had an
  early-out that omitted ``radius-port`` when ``auth_port == 1812``
  (mirroring FortiOS's own default-omission pattern).  Round-trip
  drift: first parse gave auth_port=0, render emitted nothing,
  re-parse defaulted to 1812.  Fix canonicalises ``radius-port 0``
  to 1812 at parse time in ``_apply_user_radius`` — canonical
  stores the *effective* value, not the literal 0.  Regression
  test
  ``TestRoundTrip::test_radius_port_zero_canonicalised_to_default``
  in ``tests/unit/migration/test_fortigate_cli.py`` pins the fix.
- ``certainty`` ClassVar bumped from ``best_effort`` to
  ``certified`` in
  ``netcanon/migration/codecs/fortigate_cli/codec.py``; matching
  test updated in
  ``tests/unit/migration/test_fortigate_cli.py::TestR3Fields::test_certainty``
  with comment citing the promotion evidence.
- ``fortigate_cli`` is the **5th codec to reach ``certified``**
  (after ``mikrotik_routeros``, ``aruba_aoss``,
  ``cisco_iosxe_cli``, ``opnsense``).  Only ``cisco_iosxe``
  (NETCONF OpenConfig) remains at ``best_effort``.
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance +
  sanitisation inventory), ``tests/fixtures/real/RESULTS.md``
  (per-codec section + summary total from 25 → 26 fixtures),
  ``README.md`` cert table.
- **677 migration tests passing** (+4 from the OPNsense commit),
  zero regressions.

### Added (OPNsense promoted to `certified` — 4th codec to reach the bar + real render bug fixed)

- User-contributed real ``config.xml`` from a deployed OPNsense
  instance ("supergate"), captured via Netcanon's own backup layer
  (SSH + ``cat /conf/config.xml``).  Sanitised per AGENTS.md hard
  rule — 2 bcrypt ``<password>`` hashes replaced with
  ``$2y$11$fakeBcrypt...`` markers; API keys and the QFeeds
  ``tip_...`` token replaced with synthetic placeholders; 2
  self-signed-cert private-key ``<prv>`` blobs stripped (public
  ``<crt>`` retained for grammar coverage); the real domain
  (``[redacted-domain]``) replaced with ``example.test`` across 22
  occurrences; 13 real MAC addresses sanitised with OUI-preserving
  last-3-octet anonymisation; SSH-capture artifacts (``cat
  /conf/config.xml`` prefix and trailing shell prompt) stripped.
- ``user_contrib_supergate_opn25.xml`` — 2,302 lines, 8 interfaces
  (wan/lan/opt1-5/loopback with USERVLAN/MGMTVLAN/SERVERVLAN/
  CLUSTERVLAN/IOTVLAN descriptions), 5 VLANs with ``<tag>`` +
  ``<descr>``, 2 local users w/ bcrypt hashes, extensive per-zone
  DHCP static MAC reservations (~20/zone with operational
  commentary), Unbound DNS with local overrides, IPsec, WireGuard,
  SNMP, NTP.  The first genuinely-real-deployment OPNsense fixture
  (previous 3 were all from ``opnsense/core`` upstream).
- **Real codec bug surfaced + fixed in the same commit:** the
  render path silently dropped every ``CanonicalVlan`` entry.  The
  parser correctly read ``<vlans><vlan><tag/>`` + ``<descr/>`` into
  ``intent.vlans``, but ``_render_canonical`` had no inverse block
  — so a ``parse → render → parse`` cycle on the supergate capture
  collapsed 5 VLANs down to 0.  The three upstream
  ``opnsense/core`` fixtures didn't exercise the ``<vlans>`` block
  at all, so this bug slept until real-deployment contact.  Fix:
  added a ``<vlans>`` render block in
  ``netcanon/migration/codecs/opnsense/codec.py`` that emits
  ``<tag>`` + ``<descr>`` per VLAN (round-trip-symmetric with what
  the parser reads).  Regression test
  ``TestRoundTrip::test_roundtrip_preserves_vlans`` in
  ``tests/unit/migration/test_opnsense.py`` pins the fix — the
  test constructs a 3-VLAN input, parses/renders/re-parses, and
  asserts the VLAN ids and names survive.
- ``certainty`` ClassVar bumped from ``best_effort`` to
  ``certified`` in
  ``netcanon/migration/codecs/opnsense/codec.py``; matching
  ``test_certainty_is_certified`` added in
  ``tests/unit/migration/test_opnsense.py`` with comment citing the
  promotion evidence.
- ``opnsense`` is the **4th codec to reach ``certified``** (after
  ``mikrotik_routeros``, ``aruba_aoss``, ``cisco_iosxe_cli``).
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance for the new
  file + sanitisation inventory), ``tests/fixtures/real/RESULTS.md``
  (per-codec table + summary total from 24 → 25 fixtures),
  ``README.md`` cert table.
- **673 migration tests passing** (+7 from the last cert commit),
  zero regressions.

### Added (Cisco IOS-XE CLI cert strengthened with physical Cat 9300-24UX real capture)

- User-contributed real ``show running-config`` from a physical
  **Cisco Catalyst 9300-24UX** running **IOS-XE 17.12**, captured via
  Netcanon's own backup layer against the contributor's live home-
  lab switch and sanitised per AGENTS.md hard rules.  Fills the
  physical-switch coverage gap that the earlier 3 BSD-3 racc
  captures didn't address — they were all **virtual routers**
  (CSR1000v / Cat8000V) and validated IOS-XE routing grammar but not
  physical-switch switching grammar.
- ``user_contrib_cat9300_iosxe1712.txt`` — 491 lines, 47 interfaces,
  6 VLANs, 3 LACP EtherChannels (the Fortigate uplink, NAS LAG, and
  Proxmox-blade LAG), 2 local users, 1 default-gateway static route.
  Exercises the whole physical-switch grammar surface: ``switch 1
  provision c9300-24ux``, ``TenGigabitEthernet1/0/N`` /
  ``FortyGigabitEthernet1/1/N`` / ``TwentyFiveGigE1/1/N`` /
  ``AppGigabitEthernet1/0/1`` port families, ``switchport mode
  trunk/access`` + ``switchport trunk allowed vlan <list>`` +
  ``switchport trunk native vlan``, ``channel-group N mode active``
  binding into ``interface Port-channel N``, ``interface Vlan N``
  SVIs, ``vrf forwarding Mgmt-vrf`` on the management port, the
  full Cat9k ``class-map system-cpp-police-*`` + ``policy-map
  system-cpp-policy`` CPP (control-plane policer) grammar,
  ``spanning-tree mode rapid-pvst``, 28 × ``privilege exec level 5
  show X`` delegation entries, multiple ``line vty`` ranges
  (``0 4`` / ``5 29`` / ``30 31``).
- Sanitisation: the two ``username X secret 9 $9$...`` hashes were
  replaced with synthetic-marked ``$9$fakeSalt...$fakeHash...`` per
  AGENTS.md "never commit real hashes from non-public devices" rule;
  the ``by <windows-username>`` annotation in the
  ``Last configuration change`` timestamp was updated to
  ``by netadmin``.  All other real data retained — RFC1918
  addressing, VLAN IDs, infrastructure-describing interface
  descriptions (``TRUNK - FORTIGATE`` / ``pvenas 2x 10gbe trunk`` /
  ``pveblade lacp``), and the self-signed device certificate chain.
  Same convention as the MikroTik ``user_contrib_crs310_ros7.rsc``
  precedent.
- Secondary fixture added: ``cml_saumur_iosxe1712_pvrstp.txt`` —
  BSD-3-Clause capture extracted from
  [CiscoDevNet/cml-community](https://github.com/CiscoDevNet/cml-community)
  `lab-topologies/ccna/Domain_2/2.5-interpret_stp/saumur_PVRSTP_solution.yaml`
  (the ``saumur`` node's ``configuration:`` block).  147 lines, IOS-
  XE 17.12 on a virtual ``ioll2-xe`` image (IOU port notation
  ``Ethernet0/N`` rather than physical ``Gi1/0/N``).  Complements
  the Cat 9300 capture with PVRST+ cost-tuning grammar the Cat 9300
  doesn't exercise: ``spanning-tree pathcost method long``,
  ``spanning-tree vlan 1-4094 priority 4096``, ``spanning-tree
  link-type point-to-point``, ``spanning-tree cost 2000000``,
  ``vtp version 1``, ``vlan internal allocation policy ascending``.
- **Zero codec bugs surfaced.**  Both fixtures parse cleanly on
  first contact and produce populated canonical trees.
- The cert promotion from the previous commit is now justified on
  **both** router grammar (racc corpus) and physical-switch grammar
  (Cat 9300 capture) rather than router grammar alone.  Test
  assertion comment updated in
  ``tests/unit/migration/test_cisco_iosxe_cli.py`` to reflect
  strengthened coverage.
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance for both new
  files), ``tests/fixtures/real/RESULTS.md`` (per-codec table +
  summary total from 22 → 24 fixtures; cisco_iosxe_cli row now
  shows 4 LTS OS versions and 11 fixtures), ``README.md`` cert
  table.
- **666 migration tests passing**, zero regressions.

### Added (Cisco IOS-XE CLI promoted to `certified` — 3rd codec to reach the bar)

- Three BSD-3-Clause real captures ingested from
  [nickrusso42518/racc](https://github.com/nickrusso42518/racc) —
  authored by a Cisco DevNet trainer, checked in as the playbook's
  own sample output directory, so provenance is unambiguous:
  - ``racc_csr1000v_iosxe169_bgp_ospf.txt`` — CSR1000v on
    **IOS-XE 16.9 LTS**, 280 lines.  BGP AS 65001 with ``vpnv4`` +
    ``rtfilter`` address-families, OSPF, QoS ``class-map`` +
    ``policy-map``, ``logging host``, RESTCONF + NETCONF-YANG.
  - ``racc_csr1_iosxe173_umbrella_sig.txt`` — CSR1000v on
    **IOS-XE 17.3 LTS**, 398 lines.  Cisco Umbrella SIG tunnel
    deployment: IKEv2 proposal/policy/profile + IPsec profile +
    ``tunnel protection ipsec profile`` on Tunnel100, 22 static
    routes (anycast SIG targets), EIGRP CITYNET, OSPF, SSH
    ``pubkey-chain``, guestshell app-hosting, NETCONF-YANG
    ``candidate-datastore``.
  - ``racc_cat8000v_iosxe179_netconf.txt`` — Cat8000V on
    **IOS-XE 17.9 LTS**, 343 lines.  ``ip nat inside source list
    ... overload`` (PAT), ``telemetry ietf subscription`` (YANG-
    push periodic update-policy over grpc-tcp), type-9 ``$9$...``
    hash, RESTCONF + NETCONF-YANG, app-hosting guestshell.
- **Zero codec bugs surfaced.**  All three fixtures parse cleanly
  on first contact and produce populated canonical trees —
  evidence the grammar coverage from the Batfish / NTC corpus
  already generalised to real deployed CSR1000v / Cat8000V
  configs.  Large cert chains, IKEv2 profiles, guestshell stanzas,
  telemetry subscriptions, PKI trustpoints all fell through to
  "parse-and-ignore" without tripping the parser — exactly as
  designed.
- Cert-bar for ``parse_only`` codecs: ≥3 real captures from ≥2 OS
  versions that parse cleanly and produce populated canonical
  trees (round-trip is N/A for parse-only).  The three racc
  fixtures give us 3 distinct LTS OS versions — meets the bar
  decisively.
- ``certainty`` ClassVar bumped from ``best_effort`` to
  ``certified`` in
  ``netcanon/migration/codecs/cisco_iosxe_cli/codec.py``;
  matching test renamed/updated in
  ``tests/unit/migration/test_cisco_iosxe_cli.py``
  (``test_certainty_is_certified``).
- ``cisco_iosxe_cli`` is the **3rd codec to reach ``certified``**
  (after ``mikrotik_routeros`` and ``aruba_aoss``).
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance for 3 new
  files), ``tests/fixtures/real/RESULTS.md`` (per-codec table +
  summary total from 19 → 22 fixtures), ``README.md`` cert table.
- **664 migration tests passing**, zero regressions.

### Added (Aruba AOS-S promoted to `certified` — 2nd codec to reach the bar)

- Three sanitised real captures ingested from HPE Community forum
  threads, collectively spanning **3 distinct OS versions** and
  **2 switch families**:
  - ``hpe_community_2930f_wc1607_intervlan.cfg`` — 2930F JL260A on
    **WC.16.07.0002**.  12 VLANs with per-VLAN SVIs, ``ip
    helper-address`` (DHCP relay) at scale, ``ip forward-protocol udp``
    for DNS/NTP helper forwarding, ``primary-vlan``, 4 static routes
    including ``ip default-gateway``.
  - ``hpe_community_2920_wb1608_dhcp_snooping.cfg`` — 2920 J9729A on
    **WB.16.08.0001** (different WB branch + different switch family
    to the other two).  Exercises ``dhcp-snooping`` with 13
    authorized-servers + VLAN scope + trust ports, ``ntp unicast``
    with ``iburst``, ``web-management ssl``, ``ip authorized-managers``,
    ``snmp-server host ... trap-level critical``.
  - ``hpe_community_2930f_wc1610_dhcp_server.cfg`` — 2930F JL258A on
    **WC.16.10.0005**.  Real AOS-S built-in ``dhcp-server pool``
    grammar (3 pools × ``default-router``/``dns-server``/``network``/
    ``range``), per-VLAN ``dhcp-server`` enable flag,
    ``allow-unsupported-transceiver``.
- **Zero codec bugs surfaced.**  All four fixtures (3 new + 1
  pre-existing rendered template) round-trip clean on first pass,
  parse deterministically, produce matching canonical trees — the
  harness invariants held without a single fix.
- ``certainty`` ClassVar bumped from ``best_effort`` to ``certified``
  in ``netcanon/migration/codecs/aruba_aoss/codec.py``; matching
  test updated in ``tests/unit/migration/test_aruba_aoss.py`` with
  a comment citing the promotion evidence (pattern mirrors the
  MikroTik certification commit).
- ``aruba_aoss`` is the **2nd codec to reach ``certified``** (after
  ``mikrotik_routeros``).  Cert bar: ≥3 real captures from ≥2 OS
  versions, all round-tripping clean.
- Docs: ``tests/fixtures/real/NOTICE.md`` (provenance for all 3 new
  files), ``tests/fixtures/real/RESULTS.md`` (per-codec table + summary
  total from 16 → 19 fixtures), ``README.md`` cert table.
- **658 migration tests passing**, zero regressions.

### Fixed (Bug 1: Cisco IOS-XE SVI dropped silently into Aruba render)

- **Symptom** (found via real-config dogfooding): feeding a Cisco
  9300 config containing ``interface Vlan11 / ip address
  192.168.11.252 255.255.255.0`` through the
  ``cisco_iosxe_cli -> aruba_aoss`` pipeline produced an Aruba render
  with **no ``vlan 11`` stanza at all** — the SVI's IP address
  silently vanished.
- **Root cause**: the IOS-XE CLI parser only created ``CanonicalVlan``
  records from explicit top-level ``vlan N / name X`` stanzas, not
  from ``interface Vlan<N>`` SVIs.  Aruba's renderer unconditionally
  skips interfaces named ``Vlan*`` (expecting the VLAN stanza to
  absorb the SVI's IP), so with no VLAN record the SVI + its L3
  data fell through the gap.
- **Fix**: new ``_synthesize_vlans_from_svis()`` post-pass in the
  Cisco IOS-XE CLI parser derives a ``CanonicalVlan(id=N)`` from
  each ``interface Vlan<N>`` stanza, attaches the SVI's IPv4
  addresses, and merges with any existing top-level ``vlan N``
  record (explicit ``name`` stays authoritative; SVI description
  falls back as the name when no stanza is present).
- **New cross-codec invariant** in the full-mesh matrix:
  ``test_every_source_ip_appears_in_rendered_output`` — every IP
  in the parsed-source tree MUST appear as a literal substring in
  the target codec's rendered output.  Substring-based so it
  doesn't depend on target parsers accepting foreign interface
  names (AOS-S can't re-parse ``GigabitEthernet0/0/0`` but the IP
  still reaches the rendered text, which is what matters for
  silent-drop detection).  This guard would have caught Bug 1 on
  day one.
- **8 new unit tests** (``TestSVIVlanSynthesis``) + 25 parametrized
  invariant runs.  **885 passing**, zero regressions.

### Added (Tier 2 — SNMP parse/render across all 5 real codecs)

- First Tier 2 feature wired end-to-end through every real codec:
  **SNMP** (community, location, contact, trap_hosts).  Previously
  the ``CanonicalSNMP`` model existed but no codec consumed or
  produced it.
- **Per-codec grammar coverage:**
  - ``cisco_iosxe_cli``: ``snmp-server community/location/contact/host``
  - ``opnsense``: ``<snmpd>`` plugin element (``<rocommunity>``,
    ``<syslocation>``, ``<syscontact>``, ``<traphost>``)
  - ``mikrotik_routeros``: ``/snmp set`` (sysinfo) + ``/snmp community
    set`` (community strings)
  - ``aruba_aoss``: ``snmp-server community/location/contact/host``
  - ``fortigate_cli``: ``config system snmp sysinfo`` + ``config
    system snmp community`` with nested ``config hosts`` sub-table
- Each codec's capability matrix now declares ``/snmp/community``,
  ``/snmp/location``, ``/snmp/contact``, ``/snmp/trap-host``.
- ``_walk_canonical`` emits SNMP xpaths only when populated, so
  codecs that don't carry SNMP produce no false xpath occurrences.
- 24 new unit tests in ``tests/unit/migration/test_tier2_snmp.py``:
  per-codec parse/render/round-trip + parametrized universal-render
  + universal-roundtrip across every real codec.  **852 passing.**
- Paves the way for the remaining Tier 2 features (local_users,
  LAGs, RADIUS servers, DHCP server pools) — identical shape of
  work, just different grammars.

### Added (FortiGate CLI codec — 5th real vendor, recursive grammar)

- **``FortiGateCLICodec``** in
  ``netcanon/migration/codecs/fortigate_cli/`` — parses and renders
  FortiOS 7.x CLI (``config/edit/set/next/end`` 5-keyword grammar).
  Recursive block model handles arbitrary nesting including nested
  ``config`` inside ``config`` (NTP ntpserver sub-table).
- **Parser scope:** ``system global`` (hostname), ``system dns``
  (primary/secondary), ``system ntp`` (ntpserver sub-table),
  ``system interface`` (physical + VLAN sub-interfaces via ``set
  type vlan`` + ``set vlanid`` + parent ``set interface``),
  ``router static`` (dst + gateway + device).
- **Structural handling:** quoted values with spaces, multi-token
  set values (``set allowaccess ping https ssh``), integer ``edit``
  IDs for routes + quoted ``edit`` IDs for interfaces, dotted-
  decimal mask form for IPs.
- **Capability matrix:** firewall policies + NAT rules marked
  unsupported (Tier 3); alias 25-char truncation marked lossy.
- **Auto-detection probe:** ``#config-version=`` banner (98%),
  5-keyword grammar markers (75-92%).
- **Vendor YAML** at ``netcanon/migration/vendors/fortigate.yaml``
  declaring ``[firewall, router]``.

### Added (full-mesh cross-codec matrix test)

- **``tests/unit/migration/test_cross_codec_matrix.py``** — parametrized
  pytest that auto-enumerates every ``(source, target)`` codec pair,
  filters to those sharing a ``DeviceClass``, runs each source's
  ``sample_input`` through ``run_plan``, and asserts the job
  completes.  Answers the user's question: yes, we now have
  full-mesh cross-vendor testing built into every codec addition.
  26 real pairs covered today; grows automatically with each new
  codec.
- **Latent bugs exposed + fixed on first matrix run:**
  - ``MockCodec.render()`` couldn't JSON-serialise ``CanonicalIntent``
    — now detects the type and uses pydantic's ``model_dump()``.
  - ``CiscoIOSXECodec.parse()`` still returned the legacy nested
    dict shape (never migrated during the canonical bridge work).
    Now returns ``CanonicalIntent`` like every other codec; 8 test
    assertions updated to use the canonical attribute access.
    Capability matrix updated to declare canonical xpaths.

### Added (Aruba AOS-S codec — 4th real vendor, VLAN-centric)

- **``ArubaAOSSCodec``** in ``netcanon/migration/codecs/aruba_aoss/``
  — parses and renders Aruba AOS-S (ProCurve / ArubaOS-Switch 16.x)
  ``show running-config`` text.  Architecturally the first codec
  where VLAN port membership lives naturally on the VLAN object
  (``vlan 10`` → ``untagged 1-24`` / ``tagged 25-26``), validating
  the canonical VLAN-centric design decision.
- **Parser scope (Tier 1):** hostname, VLANs (id, name, untagged/
  tagged port lists, SVI IPs), interfaces (name, enable/disable,
  routing keyword, per-port IP), static routes (``ip route`` +
  ``ip default-gateway``), SNMP community, DNS / NTP servers.
- **Structural quirks handled:**
  - ``;`` as comment character (not ``!``)
  - Stanza delimiter is ``exit`` or an un-indented line
  - Port names: bare numerics + alpha-numeric (``1``, ``A1``, ``Trk1``)
  - Port-range expansion (``1-24``) + compression on render
  - IP accepts both ``A.B.C.D/N`` and ``A.B.C.D M.M.M.M``
  - Default gateway ↔ ``0.0.0.0/0`` static route round-trip
  - ``no untagged 1-24`` port-list subtraction
- **Vendor YAML** at ``netcanon/migration/vendors/aruba_aoss.yaml``
  declaring ``[switch, router]``.
- **OPNsense renderer hardened**: bare-numeric interface names
  (legal on Aruba, invalid as XML element tags) now sanitise via
  ``_zone_tag_for()`` — ``1`` becomes ``if_1``, etc.  Closes a
  cross-vendor regression exposed by the Aruba→OPNsense pipeline.
- **Auto-detection probe** with three confidence tiers: ProCurve
  banner (98%), combined structural markers + ``;`` comment (95%),
  individual structural hits (70-88%).
- 49 new unit tests.  **760 passing, zero regressions.**

### Changed (auto-discover codec packages — zero-bookkeeping vendor add)

- **``netcanon/migration/__init__.py``** now auto-discovers every
  codec sub-package under ``netcanon/migration/codecs/`` using
  ``pkgutil.iter_modules``.  Each package's module-level
  ``@register`` decorator fires on import, populating the registry.
- Adding a new vendor is now a true drop-in: create the codec
  package directory + drop a vendor YAML — the translator picks
  both up at next import with **zero edits to any shared file**.
  (The ``INPUT_FORMATS`` frozenset and per-codec probe signatures
  remain in the codec's own module, so they're also vendor-local.)
- Broken codec packages log the failure and are skipped —
  robustness test pins that behaviour.
- 2 new unit tests: auto-discovery finds every expected codec;
  importing the package is idempotent across reloads.  **710 passing.**

### Changed (UI metadata migration — close the R5 client-side leak)

- **CodecBase gains three UI-metadata ClassVars**: ``description``,
  ``sample_input``, ``output_extension``.  Each codec class is now
  the single source of truth for its own presentation strings.
- **``CodecInfo`` pydantic model grew three fields** (same names)
  and ``GET /api/v1/migration/adapters`` surfaces them so the client
  can render format hints / load samples / pick download extensions
  without any vendor-specific JS.
- **`migrate.html` lost its 130-line ``FORMAT_CATALOGUE`` dict** and
  all six call sites that read from it.  New ``adapterEntry()`` and
  ``compatibleExtensions()`` helpers read server-provided metadata
  off the ``adapters`` array.  ``guessExtension`` and
  ``downloadMigrateOutput`` likewise delegate to
  ``target.output_extension``.
- **Adding a new codec no longer requires editing the template** —
  the codec class ships its own description + sample + download
  extension, which the UI picks up automatically.
- Every real codec (cisco_iosxe, cisco_iosxe_cli, opnsense,
  mikrotik_routeros, mock) now declares all three metadata fields.
- 3 new integration-test assertions confirm the surface
  (``test_ui_metadata_fields_surface``,
  ``test_real_codecs_have_sample_input``,
  ``test_real_codecs_have_output_extension``).  **708 passing.**

### Added (R5 — auto-detection of source codec from raw bytes)

- **`CodecBase.probe(raw_prefix)`** classmethod — new auto-detection
  hook.  Each codec overrides it to return a ``(confidence, reason)``
  tuple if the first ~500 bytes match its format, or ``None`` if it
  has no opinion.  Default base implementation returns ``None`` so
  codecs without a probe still load cleanly.
- **Per-codec probe signatures** on all four real codecs:
  - ``opnsense`` — matches ``<opnsense>`` root (98% confidence)
  - ``cisco_iosxe`` — matches OpenConfig YANG namespace (95%),
    ``<rpc-reply>`` envelope (70%), OpenConfig-shaped XML (75%)
  - ``cisco_iosxe_cli`` — matches ``Building configuration…`` banner
    (98%), strong CLI markers like ``interface Giga`` + ``ip address
    X.X.X.X Y.Y.Y.Y`` + ``no shutdown`` (90% for ≥2 hits), weaker
    fallbacks
  - ``mikrotik_routeros`` — matches ``# ... by RouterOS`` banner
    (98%), multiple ``/section`` headers + find-default-name idiom
    (97%), individual sections / idioms (80-95%)
  - ``mock`` — weak JSON-shape detection (40-55%)
- **`netcanon/services/migration_detect.py`** — pure-function
  detection service.  ``detect_codec(raw)`` walks every registered
  codec's ``.probe()``, filters by ``min_confidence``, and returns a
  ranked list.  ``best_codec(raw)`` is a convenience wrapper that
  returns only the top candidate (default strict threshold 50).
- **`POST /api/v1/migration/detect`** — new API endpoint.  Body
  accepts ``raw_text`` OR ``source_filename`` (same contract as
  ``/plan``) plus optional ``min_confidence``.  Returns
  ``list[DetectCandidate]`` sorted by descending confidence.
- **/migrate UI auto-detection** — debounced 350ms on textarea
  input, fires on stored-config selection, and on source-codec
  change.  Banner shows "Detected: \<vendor\> (\<confidence\>%)"
  with a "Use this source" button.  When the user has already
  picked the detected codec the banner goes green (confirmation).
- **MikroTik sample + format hint** — client-side
  ``FORMAT_CATALOGUE`` now has a ``cli-mikrotik`` entry (label,
  desc, sample, ``exts=['rsc']``) so the "Load sample" button and
  stored-config compatibility warning work for MikroTik too.  The
  ``guessExtension`` function was refactored to read
  ``adapter.input_format`` from the /adapters response instead of
  hard-coding vendor names — partial closure of a known client-side
  vendor-metadata leak.  Full structural fix (moving all codec
  metadata out of JS and onto the codec class) is queued as a
  standalone UI-metadata-migration session.
- **46 new tests**: 37 unit tests (per-codec probe signatures +
  detection service + robustness) + 9 integration tests (endpoint
  contract, sorting, min-confidence filtering, both-fields 422,
  missing-file 404).  Total suite: 705 passing.
- **Testid additions**: ``migrate-detect-banner`` (with
  ``data-detected-codec`` and ``data-detected-confidence`` attrs),
  ``migrate-detect-use-btn``.

### Added (MikroTik RouterOS codec — third canonical-bridged vendor)

- **``MikroTikRouterOSCodec``** in
  ``netcanon/migration/codecs/mikrotik_routeros/`` — parses and renders
  RouterOS ``/export verbose`` text through ``CanonicalIntent``.  First
  third-party validation that the canonical dict is portable across
  structurally different formats (XML / indented IOS CLI / section-
  oriented RouterOS script).
- **Parser scope (Tier 1):** system identity (hostname), DNS + NTP
  servers, ethernet-port tweaks (``set [ find default-name=ether1 ]``),
  VLAN interfaces (``add name=vlanN vlan-id=N``), bridge interfaces,
  IPv4 addresses bound to interfaces (``/ip address add``), and static
  routes (``/ip route add``).  Handles RouterOS quirks: quoted
  values with spaces, ``\`` line continuation, ``#`` banner comments.
- **Renderer scope:** emits deterministic, section-ordered output.
  Ethernet ports render as default-name tweaks; VLANs, bridges, and
  other interfaces render as `add` lines.  Round-trip invariant holds
  for the canonical subset.
- **Vendor YAML** added at
  ``netcanon/migration/vendors/mikrotik_routeros.yaml`` declaring
  device classes ``[router, firewall]``.
- **Capability matrix** marks firewall/filter rules and NAT as
  unsupported (Tier 3 — informational only), interface type as lossy
  (inferred from name prefix).
- **Cross-vendor translation proven for 3 new pairs:** Cisco IOS-XE
  CLI → MikroTik; MikroTik → OpenConfig NETCONF XML; MikroTik →
  OPNsense config.xml.  Ecosystem now supports 4! = 24 vendor-pair
  combinations (up from 6 before this codec).
- **38 new unit tests** covering R3 fields, parse, parse-errors,
  render, round-trip, iter_xpaths, capabilities, cross-adapter
  pipeline integration, and registry.  Total suite: 659 tests passing.

### Added (canonical intent dict — cross-vendor translation bridge)

- **``CanonicalIntent``** pydantic model in
  ``netcanon/migration/canonical/intent.py`` — the shared tree shape
  every codec's ``parse()`` emits and ``render()`` consumes.  Defines
  Tier 1 (auto-translatable: hostname, interfaces, VLANs, static
  routes), Tier 2 (review-required: DHCP, SNMP, LAGs, users, RADIUS),
  and Tier 3 (informational-only: firewall, NAT, VPN stored as
  raw_sections for display, never auto-rendered).
- **VLAN-centric membership model**: VLANs carry their port lists
  (tagged/untagged), not the reverse — Aruba AOS-S and OPNsense work
  this way natively; Cisco's per-interface switchport is transposed
  on parse.
- **Cisco IOS-XE CLI codec refactored** to emit ``CanonicalIntent``:
  now parses hostname, VLANs (``vlan <id>`` / ``name`` stanzas),
  static routes (``ip route``), and switchport config
  (``switchport mode``, ``access vlan``, ``trunk allowed vlan``,
  ``trunk native vlan``) in addition to interfaces.
- **OPNsense codec refactored** to emit/consume ``CanonicalIntent``:
  new ``_render_canonical()`` method renders OPNsense config.xml from
  any canonical intent (including those parsed from Cisco CLI).
- **Cisco IOS-XE NETCONF codec** gains ``_render_canonical()`` to
  produce OpenConfig XML from any ``CanonicalIntent``.
- **Cross-vendor translation proven**: ``cisco_iosxe_cli`` (source) →
  ``opnsense`` (target) completes successfully through the pipeline.
  First time in the project's history that a stored backup config
  from one vendor renders as another vendor's config format.
- **740 tests pass** — zero regressions.  All existing tests updated
  to assert against canonical model attributes instead of raw dicts.

### Added (R3+R4: codec direction/certainty fields + first CLI codec)

- **R3: three new fields on ``CodecBase``:**
  - ``direction`` — ``"bidirectional"`` (default), ``"parse_only"``, or
    ``"render_only"``.  Parse-only codecs can only be SOURCE; the
    ``/migrate`` UI now filters them out of the target dropdown.
  - ``certainty`` — ``"certified"`` / ``"best_effort"`` /
    ``"experimental"``.  Surfaced on the API and in the source
    dropdown label so users know the trust level.
  - ``canonical_model`` — which CIM the tree targets (default
    ``"openconfig-lite"``).  Informational for now; becomes load-
    bearing when cross-CIM translation lands.
  All three fields exposed on ``CodecInfo`` via
  ``GET /api/v1/migration/adapters``.

- **R4: ``CiscoIOSXECLICodec``** — first ``parse_only`` codec, first
  multi-codec-per-vendor instance.  Parses ``show running-config``
  text — the format Netcanon's existing Netmiko backup collectors
  already capture.  Shares ``vendor_id=cisco_iosxe`` with the
  NETCONF codec; both produce the same tree shape so they're
  interchangeable as pipeline SOURCEs.
  - Direction: ``parse_only`` (render raises ``RenderError``).
  - Certainty: ``experimental`` (synthetic samples only).
  - Scope: interface stanzas — name, description, ``shutdown`` /
    ``no shutdown``, ``ip address <ip> <mask>`` with mask→prefix-
    length conversion.  Infers IANA ifType from the interface name
    prefix (``GigabitEthernet`` → ``ethernetCsmacd``, ``Loopback`` →
    ``softwareLoopback``, etc.).
  - Rejects XML/JSON input with a clear error pointing at the
    NETCONF codec.  Rejects non-contiguous subnet masks.
  - ``/migrate`` page: CLI codec appears in the SOURCE dropdown
    (with ``[experimental]`` badge) but NOT in the TARGET dropdown.
    Format hint says "Paste the output of show running-config."
    The "Load sample" button provides a working IOS CLI snippet.

- **Pipeline proof:** ``cisco_iosxe_cli`` (source) → ``cisco_iosxe``
  (target) completes successfully — the first time a stored backup
  config can be translated to OpenConfig XML through the UI.

- **Tests (+23):** ``tests/unit/migration/test_cisco_iosxe_cli.py``
  covers R3 field declarations, parse (minimal, fixture, shutdown,
  loopback /32, type inference), parse errors (empty, XML, JSON,
  non-contiguous mask), render-raises, tree-shape compatibility with
  the NETCONF codec's capability matrix, pipeline integration
  (CLI→NETCONF succeeds, CLI-as-target fails with parse-only error),
  and registry (two codecs for one vendor).

- Full suite: **740 passing** (was 717).

### Added (R2: declarative vendor YAML)

- **Vendor declarations** extracted to YAML files under
  ``netcanon/migration/vendors/``.  Three shipped: ``mock.yaml``,
  ``cisco_iosxe.yaml``, ``opnsense.yaml``.  Each declares ``id``,
  ``display_name``, ``device_classes``, ``default_timeout``, ``notes``.
  No Python code — adding a new vendor is a 30-second YAML-copy
  operation.
- **``VendorInfo``** pydantic model in ``netcanon.models.migration``.
- **``load_vendors()``** function in ``netcanon.migration.vendors``
  scans the directory at startup, validates against the model, skips
  corrupt files with a log.  Loaded into ``app.state.vendors``.
- **``CodecInfo``** now carries ``vendor_id`` and
  ``vendor_display_name`` so the UI can group codecs by vendor without
  a second request.  ``vendor_display_name`` is resolved from the
  loaded YAML at response time.
- **Codec ↔ vendor linkage test:** a dedicated unit test asserts that
  every shipped codec's ``vendor_id`` resolves to a loaded vendor — a
  build-time guard against orphaned references.
- **Tests (+17):** ``test_vendors.py`` (14 unit — built-in loading,
  model shape, error resilience, corrupt/missing/duplicate YAML,
  codec linkage guard) + 3 integration (API surfaces ``vendor_id``
  and ``vendor_display_name`` for each codec).
- Full suite: **717 passing** (was 700).

### Refactored (R1: rename adapter → codec + add vendor_id)

- **`AdapterBase` → `CodecBase`** — "codec" accurately describes the
  class's job: translate between a wire format and the canonical tree.
  All related types renamed: `AdapterInfo` → `CodecInfo`,
  `AdapterError` → `CodecError`, `MockAdapter` → `MockCodec`,
  `CiscoIOSXEAdapter` → `CiscoIOSXECodec`, `OPNsenseAdapter` →
  `OPNsenseCodec`, `get_adapter` → `get_codec`, `list_adapters` →
  `list_codecs`.
- **Directory:** `netcanon/migration/adapters/` →
  `netcanon/migration/codecs/`.  `adapter.py` → `codec.py`.
- **Test files:** `test_mock_adapter.py` → `test_mock_codec.py`,
  `test_cross_adapter_pipeline.py` → `test_cross_codec_pipeline.py`.
- **`CapabilityMatrix.vendor_id: str`** — new field, links the codec
  to a vendor YAML (R2).  Set on all 3 codecs.
- **JSON back-compat:** `CapabilityMatrix.adapter` stays as the JSON
  field name so API consumers don't break.
- 700 tests pass — zero regressions.

### Refactored (god-file cleanup — zero behaviour change)

Three files identified as god-files during a structural audit;
all three refactored with zero behaviour change (674 tests pass
before and after, same count).

- **`netcanon/main.py` (539 → 208 lines).**  All 12 UI route
  handlers (``/``, ``/jobs``, ``/schedules``, ``/configs``,
  ``/configs/{L}/vs/{R}``, ``/devices``, ``/definitions``,
  ``/migrate``, ``/docs``, ``/health``) extracted to a new
  ``netcanon/api/routes/ui.py`` (406 lines).  ``_format_interval``
  and the Jinja2 ``templates`` instance moved with them.
  ``create_app`` now only wires routers and configures the lifespan.

- **`netcanon/templates/base.html` (834 → 262 lines).**  Two
  self-contained JS widgets extracted to Jinja ``{% include %}``
  partials (no ``StaticFiles`` mount needed):
  - ``_partials/config-viewer.js`` (346 lines) — syntax highlighter,
    tokenizer, cross-span search.
  - ``_partials/job-progress.js`` (231 lines) — floating progress
    panel, localStorage persistence, CustomEvent dispatch.
  Toast + timestamp localiser + config downloader remain inline
  (~80 lines; not worth a separate file at that size).

- **``tests/e2e/test_backup_flow.py`` (805 lines, 13 classes)
  split into 6 focused files:**
  - ``test_navigation.py`` (60 lines) — nav smoke tests.
  - ``test_backup_form.py`` (129 lines) — dashboard structure +
    multi-device form + backup submission.
  - ``test_pages.py`` (72 lines) — definitions + configs pages.
  - ``test_config_viewer.py`` (178 lines) — syntax highlighting +
    cross-span search.
  - ``test_progress_panel.py`` (153 lines) — floating panel
    visibility, persistence, dismiss.
  - ``test_diff.py`` (226 lines) — diff API, UI, content, context
    folding.
  Shared helpers ``ensure_cisco_config`` and
  ``ensure_n_configs_of_type`` promoted from private functions in
  the old monolith to public utilities in ``tests/e2e/helpers.py``.
  Old ``test_backup_flow.py`` deleted.

- **Import fix:** ``tests/unit/test_schedule_models.py`` updated to
  import ``_format_interval`` from its new home in
  ``netcanon.api.routes.ui`` instead of ``netcanon.main``.

### Fixed + Added (translator `/migrate` UX after manual QA pass)

Five findings from a hands-on walk-through of the page — one real UX
bug, three workflow gaps, one display issue.

- **Fixed: banner severity out-of-sync with job outcome** (manual
  QA #10b).  Previously a parse-OK / render-failed job rendered the
  GREEN "validation OK" banner because validation ran fine before
  render blew up.  Now the banner's severity follows a strict
  priority: `job.error` present → block, `failed`/`partial` status →
  block, else `validation.severity`, else `info`.  Colour can no
  longer contradict the message.  Banner also carries a
  `data-severity` attribute now so tests can assert on it
  unambiguously.
- **Added: `AdapterBase.input_format`** (str, defaults to
  `"unknown"`).  Each adapter declares what its `parse()` accepts:
  - `cisco_iosxe` → `xml-netconf` (OpenConfig NETCONF payload)
  - `opnsense` → `xml-opnsense` (`config.xml`)
  - `mock` → `json-flat`
  - reserved: `xml-panos`, `cli-ios`, `cli-fortigate`, `cli-mikrotik`
  Catalogued in `netcanon.migration.adapters.base.INPUT_FORMATS`
  (frozenset).  `AdapterInfo` now exposes the field so the UI can
  read it from `GET /api/v1/migration/adapters`.
- **Added: format-hint banner on `/migrate`** — explains in-line
  what the source adapter expects (e.g. "OpenConfig NETCONF —
  machine-readable payload from `netconf get-config`, NOT `show
  running-config`").  Addresses manual QA #4 (user confusion about
  paste-box contents).
- **Added: "Load sample for source adapter" button** with a
  working minimal payload per format.  The iosxe sample round-trips
  cleanly; the opnsense sample is a minimal `<opnsense>` tree.
- **Added: stored-config compatibility warning** — when the picked
  stored config's extension doesn't match the source adapter's
  declared `input_format`, a red in-place warn appears BEFORE submit
  ("`Fortigate_*.cfg` has extension `.cfg` but `cisco_iosxe`
  expects OpenConfig NETCONF XML — translate will almost certainly
  fail").  Addresses manual QA #12, #13.
- **Fixed: path-list de-duplication** (manual QA #11).  Three
  interfaces each with a description used to produce three visually-
  identical rows in the Supported list.  Now collapses to one row
  with an `×3` count badge.  Top stats count still reflects per-leaf
  impact (unchanged).

**Tests (+23):**

- `tests/unit/migration/test_input_format.py` (13) — catalogue
  immutability, base-class default, concrete adapter declarations,
  "every registered adapter declares a KNOWN format" guard.
- `tests/integration/test_migration_api.py` (+3) — `input_format`
  surfaces on the list endpoint for every adapter.
- `tests/e2e/test_migrate_page.py` (+10) — banner severity
  regression for failed/partial/ok jobs, format-hint visibility +
  auto-update, Load-sample button, stored-config compat warn,
  path-list coalescing.

Full project suite: **674 passing** (was 651).  Pre-existing
unrelated failure in `test_jobs_schedules.py` schedule form — same
drift flagged in earlier sessions, untouched here.

### Added (translator Phase 2, part 1 — `/migrate` workbench UI)

- **New HTML page at `/migrate`** — translator workbench.  Pick source
  + target adapter, paste raw text OR pick a stored config, optionally
  tick "Force cross-class", hit Translate.  Backed entirely by the
  already-shipped `POST /api/v1/migration/plan` endpoint.
- **Nav link:** "Migrate" after "Definitions".  Active highlighting
  via the same `active_page` convention as every other page.
- **Client-side adapter hydration**: the two dropdowns fetch
  `GET /api/v1/migration/adapters` on page load, so newly-registered
  adapters appear without a template redeploy.  Each option carries
  the adapter's device classes; the info strip below shows chip
  badges (colour-coded per class) plus supported/lossy/unsupported
  counts.  A class-guard hint renders in red BEFORE submit when the
  picked pair has no common class — user knows it'll be blocked.
- **Result surface** reuses existing components so visual language
  stays consistent across the app:
  - Banner palette mirrors the diff page (`mig-banner-ok` / `warn`
    / `block` / `info`) — user's eye already knows what those mean.
  - Rendered-output pane uses the config viewer's
    `_cvRenderHighlighted(text, ext)` helper for syntax highlighting
    — same `.tok-*` colours as every other code surface.
  - Toast notifications via `window.showToast`.
- **Paths drill-down** (collapsed by default): three buckets
  (supported / lossy / unsupported) with counts, full xpath lists,
  adapter-provided reasons, and severity chips.  Users can see every
  finding the ValidationReport carries without another request.
- **Copy button** for the rendered output — one-click clipboard
  without leaving the page.
- **Parse failures are surfaced as results, not errors.** The
  pipeline returns HTTP 200 with a `failed` job on adapter errors;
  the page renders the failure banner + status summary instead of a
  toast.  Genuine 4xx responses (unknown adapter, missing filename)
  DO toast.

- **Testids:** 29 new `migrate-*` testids promoted from reserved
  status in `tests/testid_reference.md` (nav, form, dropdowns, input
  mode toggle, result region, banner, stats, output, paths buckets).
  The reserved list for Phase 2 "transforms + deploy" remains
  (`migrate-transforms-list`, `migrate-deploy-btn`, etc.).

- **E2E tests (+13):** `tests/e2e/test_migrate_page.py` covers nav
  link, page structure, result-region hidden-on-load, adapter
  dropdown hydration, adapter-info update on change, input-mode
  toggle, iosxe round-trip happy path (ok banner), rendered-output
  panel appearance, parse-failure rendering, validation-block
  rendering (partial status).  `MigratePage` helper added to
  `tests/e2e/helpers.py` following the existing page-object pattern.

- **Total suite: 651 passing** (was 567 immediately after Phase 1
  backend).  Zero regressions; no new runtime dependencies.

### Added (translator Phase 1 — OPNsense adapter + write endpoints)

- **Second real adapter: `OPNsenseAdapter`** under
  `netcanon/migration/adapters/opnsense/`.  Parses/renders OPNsense
  `config.xml`.  Scope: system hostname/domain and interfaces
  (zone, `if`, descr, enable-flag, ipaddr, subnet).  Declares
  `device_classes=[firewall, router]`.
- **OPNsense zone-keyed interface idiom flattened** at parse time:
  native `<wan>…</wan><lan>…</lan>` children become a list of dicts
  with a synthetic `zone` key, so `iter_xpaths` can emit OpenConfig-
  style schema paths (no list keys).  The render step reverses the
  transformation.  Round-trip invariant `parse(render(tree)) == tree`
  is tested with sanitised 3-interface fixture.
- **Cross-vendor guardrail shown working:** OPNsense ∩ IOS-XE =
  `{router}`, so the class guard permits the migration; the per-
  xpath capability matrices then honestly flag firewall rules
  (`/filter/rule`, `/nat/outbound`) as unsupported by IOS-XE.
  The intended layering — class guard for coarse "is this meaningful
  at all?", capability matrix for fine "which features translate?".

- **New write endpoints:**
  - `POST /api/v1/migration/plan` — runs the full pipeline
    (class-guard → parse → transforms → validate → render) on a
    raw config payload.  Returns the `MigrationJob` as JSON, even
    on parse failure (the error is in `job.error`, not an HTTP
    status).  Callers inspect `job.status` for the outcome.
  - `POST /api/v1/migration/render` — currently an alias for
    `/plan`; kept as a separate route so Phase 2 can split plan
    (no side effects) from render (pre-deploy snapshot + diff URL)
    without another API rev.
  - Input mode toggle: request body supplies EITHER `raw_text` OR
    `source_filename` (which loads from the existing backup store).
    Exactly one MUST be set — otherwise 422.  Source-filename
    shorthand means you can migrate any stored config without
    shipping the bytes through HTTP.
  - `force=true` in the body skips the device-class guard.
- **New model:** `MigrationPlanRequest` in
  `netcanon.models.migration` — documented, tested, ready for a
  Phase 2 UI to reuse.

- **Manual testing now possible** end-to-end via curl:

      curl -X POST http://127.0.0.1:8000/api/v1/migration/plan \
           -H 'Content-Type: application/json' \
           -d '{"source":"cisco_iosxe","target":"cisco_iosxe",
                "raw_text":"<interfaces xmlns=\"http://openconfig.net/yang/interfaces\">…"}'

- **Tests (+32):**
  - `tests/unit/migration/test_opnsense.py` (21): parse, errors,
    render determinism, round-trip invariant (inline + fixture),
    iter_xpaths coverage, capability declarations, cross-adapter
    class-intersection, registry.
  - `tests/integration/test_migration_api.py` (+11): plan endpoint
    happy path, 422 variants (unknown source, unknown target,
    neither/both input modes), 404 for missing filename, parse
    failure returns 200 with failed job, force flag round-trip,
    render is alias, end-to-end integration with backup store.
  - `tests/fixtures/opnsense/config_simple.xml` — sanitised sample.

- **Total suite:** 567 passing (was 535, +32).  Migration suite
  alone: 184 tests (was 140, +44 across OPNsense + API integration).

### Added (translator: adversarial-input hardening + cross-adapter tests)

- **Strict YANG boolean parsing.** `CiscoIOSXEAdapter` used to silently
  coerce any `<enabled>` text other than literal `true` to `False` —
  meaning `<enabled>yes</enabled>` would ship a DISABLED interface.
  The parser now rejects every non-RFC-7950 spelling (`yes`, `no`,
  `1`, `0`, `on`, `off`, empty string, …) with a `ParseError` that
  names the exact xpath.
- **IPv4 prefix-length range check.** Previously values like `99`
  or `-1` were accepted silently and round-tripped into the rendered
  NETCONF payload, where the device would reject the edit at deploy
  time.  The parser now enforces the YANG `inet:ipv4-prefix` range
  (`0..32`).
- **Interface-index error paths.** Empty or missing `<name>` elements
  now raise a `ParseError` whose `path` includes the zero-based
  `interface[N]` index and whose `snippet` contains the offending
  element serialised to XML (capped at 200 chars).  A device
  returning ten interfaces with one malformed entry is now locatable
  in ~5 seconds instead of "open the XML and scroll".
- **UTF-8 BOM tolerance.** Some devices (and some editors) prepend a
  BOM to their XML declaration.  Test lock-in so this stays working.
- **Cross-adapter pipeline tests** (`tests/unit/migration/
  test_cross_adapter_pipeline.py`): prove stage transitions, error
  routing, and type boundaries that no single-adapter test touches:
  - IOS-XE → mock: class guard permits, nested walker reaches leaves,
    render produces JSON despite type-shape mismatch.
  - Mock → IOS-XE: render mismatch caught as `failed` with useful
    error; validation still ran first; `completed_at` is always set.
  - Partial-status routing: a validation `block` with a successful
    render correctly lands in `partial`, not `completed` or `failed`.
  - Stage ordering: class guard runs at stage 0, before parse — a
    disjoint-class pair with broken XML fails with the class-guard
    error, not a parser error.
- **Tests (+22)**:
  - `test_cisco_iosxe.py`: 10 new adversarial-input tests covering
    the four hardening items above.
  - `test_cross_adapter_pipeline.py`: 11 new pipeline scenarios.
  - Full migration suite now 140 tests (was 97 before this hardening
    pass, 77 before Phase 0.5's round-trip work, 30 at end of Phase 0).
- Full project suite: **535 passing** (was 513).  Zero regressions.

### Added (translator Phase 0.5 — Cisco IOS-XE adapter)

- **First real adapter: `CiscoIOSXEAdapter`** under
  `netcanon/migration/adapters/cisco_iosxe/`.  Scope:
  `openconfig-interfaces` + `openconfig-if-ip` subset (name,
  description, enabled, type, IPv4 address + prefix-length on
  subinterfaces).  Enough to prove the adapter contract against
  real OpenConfig NETCONF payloads.
- **Internal tree shape:** nested dict mirroring the OpenConfig XML
  structure, namespace-stripped for readability.  Canonical namespaces
  are re-attached on render.  Operates against captured NETCONF
  `<get-config>` responses today; live `ncclient` transport is
  Phase 1's responsibility (same split as the existing
  collectors-vs-collector-consumers layout).
- **Stdlib only** — `xml.etree.ElementTree` for parse/render.  No new
  runtime dependencies; libyang canonical validation is deferred to
  Phase 0.7 behind a "validates if installed" seam.
- **Round-trip invariant enforced:** `parse(render(tree)) == tree`
  for every supported tree.  Tested over inline samples and a real
  sanitised 3-interface fixture under `tests/fixtures/iosxe/`.
- **Capability matrix declares:**
  - 9 supported paths (name, config.name, config.description,
    config.enabled, config.type, subinterface.index, address.ip,
    address.config.ip, address.config.prefix-length).
  - Lossy: `/interfaces/interface/config/mtu` — YANG model doesn't
    round-trip every platform-specific MTU tweak.
  - Unsupported: IPv6 subtree (Phase 1 work).
  - `device_classes=[router, switch]` — IOS-XE platforms routinely
    fulfil both roles.

### Changed (translator: adapter-driven tree walker)

- **`AdapterBase` gets `iter_xpaths(tree)`** — non-abstract, defaults
  to the flat `dict[str, str]` walker so the mock adapter and any
  existing callers keep working.  Adapters with nested tree shapes
  (the new `CiscoIOSXEAdapter`) override to yield schema xpaths
  (no list-key predicates) that match their declared capability
  matrix.
- **`validate_against(tree, target)` gains an optional
  `source` adapter parameter.**  When supplied, the validator uses
  `source.iter_xpaths` to walk the tree — required for adapters
  whose internal tree shape isn't a flat dict.  Backward-compatible:
  omitting `source` keeps the Phase 0 behaviour.
- **`run_plan` threads `source` through to `validate_against`**
  automatically, so all pipeline callers get adapter-aware walking
  for free.

### Tests (+41 over Phase 0 baseline)

- `tests/unit/migration/test_cisco_iosxe.py` (30): parse (bare +
  envelope), parse errors (malformed XML, missing interfaces,
  non-integer prefix-length, interface without name), render
  determinism, round-trip invariant (inline + fixture), iter_xpaths
  predicate-freedom + matrix alignment, capability declarations,
  pipeline integration, registry.
- `tests/integration/test_migration_api.py`: new assertions that
  `cisco_iosxe` appears in the list endpoint, declares the expected
  device_classes, and exposes its full capability matrix (lossy
  MTU + unsupported IPv6) via the detail endpoint.
- `tests/fixtures/iosxe/get_config_simple.xml` — sanitised 3-interface
  NETCONF `<get-config>` response (RFC 5737 documentation IPs).

### Added (translator: cross-device-class guardrail)

- **Coarse-grained device-class compatibility check** prevents
  nonsensical migrations (e.g. trying to render a Layer-2 switch
  config through a firewall adapter).  Adapters declare one or more
  ``DeviceClass`` values on their ``CapabilityMatrix``; the pipeline
  refuses a pair with no class in common unless ``force=True``.
- **New `DeviceClass` enum** in `netcanon.models.migration`:
  ``switch``, ``router``, ``firewall``, ``load_balancer``,
  ``wireless_controller``, ``access_point``, ``waf``.  Taxonomy is
  flat and additive; multi-class devices (L3 switches, UTM
  appliances) declare multiple values.
- **`CapabilityMatrix.device_classes: list[DeviceClass]`** — empty
  default is "uncommitted" and produces a ``warn`` (not block) so
  adapters can be developed before their class declarations are
  finalised.
- **`check_class_compat(source, target) -> CompatibilityReport`** in
  `netcanon.services.migration_validate`.  Reuses the
  `CompatibilityReport` shape from the diff models so UIs can render
  both class-mismatch and xpath-mismatch banners with the same
  component.  Severity branches: same/overlapping class → `ok`;
  either side undeclared → `warn`; both declared but disjoint → `block`.
- **`run_plan` stage-0 guard**: the class check runs BEFORE parse,
  so mismatched adapters fail instantly with a clear
  ``"Device-class guard refused migration: …"`` error.  A new
  ``force: bool = False`` parameter on `run_plan` skips the guard
  for deliberate cross-class experiments (same idiom as the diff
  page's `?force=true` override).
- **API surface**: `AdapterInfo.device_classes` is now returned on
  ``GET /api/v1/migration/adapters`` so UIs can filter the target
  picker to compatible adapters before the user commits.  The
  detailed ``CapabilityMatrix`` response also surfaces the field.
- **Tests (+20)**: `tests/unit/migration/test_device_class.py`
  covers the enum shape, pydantic coercion of string values (for
  capabilities.yaml loading in Phase 1), every `check_class_compat`
  severity branch, and the `run_plan` stage-0 guard (default
  behaviour + `force=True` override + no-op when already
  compatible).  Integration test added for the new
  `device_classes` field on the list endpoint.

### Added (translator Phase 0 — adapter contract + pipeline skeleton)

- **Phase 0 of the translator / migration engine landed.**  Scope per
  `translator-plans.txt` §12: prove the shape end-to-end with a
  reference adapter, no real YANG tooling required yet.
- **New pydantic models** in `netcanon.models.migration`:
  `CapabilityMatrix` (with a `classify()` resolver using
  "strictest-wins" semantics — unsupported > lossy > supported),
  `LossyPath`, `UnsupportedPath`, `ValidationReport`, `XPathDelta`,
  `TransformSpec`, `MigrationJob`, `MigrationJobStatus`, `AdapterInfo`.
  Shape deliberately mirrors `CompatibilityReport` + `BackupJob` so UI
  banners and lifecycle conventions stay consistent.
- **`netcanon.migration` package**:
  - `adapters/base.py` — `AdapterBase` ABC + `ParseError` / `RenderError`.
  - `adapters/registry.py` — in-memory `register` / `get_adapter` /
    `list_adapters` with name-collision and missing-name guards.
  - `adapters/_mock/` — reference adapter that round-trips a flat
    `dict[str, str]` via JSON; exercises every `classify()` branch
    (supported, lossy, unsupported).
  - `canonical/loader.py` — Phase 0.5 stub; `NotImplementedError`
    with clear roadmap pointer.  `PLANNED_MODULES` tuple documents
    the OpenConfig + `netcanon-ext` modules that will be pinned
    once libyang lands.
- **New services**:
  - `services/migration_validate.py` — walks a tree's xpaths,
    classifies each against the target's `CapabilityMatrix`, returns
    a `ValidationReport` with `ok` / `warn` / `block` severity.
  - `services/migration_pipeline.py` — `run_plan(source, target,
    raw_text, transforms)` orchestrator covering stages
    parse → transform → validate → render.  Each failure class
    (`ParseError`, `RenderError`, generic `Exception`) yields a
    terminal `failed` job with a `.error` summary.  A successful
    render against a `block`-severity validation yields `partial`
    (output available for review, not safe to auto-deploy).
- **New API endpoints** (read-only Phase 0):
  - `GET /api/v1/migration/adapters` — list registered adapters
    with summary counts.
  - `GET /api/v1/migration/adapters/{name}/capabilities` — full
    `CapabilityMatrix`; 404 for unknown adapters.
- **Tests (+77)**:
  - `tests/unit/migration/test_models.py` (20) — every pydantic
    type + `classify` resolution rules.
  - `tests/unit/migration/test_registry.py` (10) — decorator
    contract, collision detection, idempotent re-registration,
    LookupError on unknown names, mock always registered.
  - `tests/unit/migration/test_mock_adapter.py` (14) — round-trip
    invariant over 5 sample trees, deterministic output, parse
    error paths, capability-matrix shape.
  - `tests/unit/migration/test_validate.py` (11) — every severity
    branch including `error`-level lossy escalation, mixed
    unsupported+lossy, empty tree, non-dict tree.
  - `tests/unit/migration/test_pipeline.py` (9) — happy path,
    transform ordering + failure, parse failure, validation
    block → partial status, failed-job timing.
  - `tests/unit/migration/test_canonical_loader.py` (4) — stubs
    raise `NotImplementedError` with roadmap pointer.
  - `tests/integration/test_migration_api.py` (9) — list + detail
    endpoints, 404 for unknown adapter, summary/detail consistency.
- **No UI in this phase.**  testids for the migration UI are
  queued for Phase 2 (`migrate-source-select`, etc. — see
  `translator-plans.txt` §11); the config diff page already
  handles rendered-output review so no second viewer is needed.

### Changed (diff page: directional paradigm — `FROM → TO`)

- **"Sides" paradigm replaced with a temporally-neutral direction.**
  The unified diff layout has directionality (`+N` added / `-M`
  removed going from one file to another), not sides.  The UI now
  surfaces that explicitly with `FROM` and `TO` role labels:
  - Each filename chip is preceded by a role badge: `FROM` (dark)
    next to the left chip, `TO` (green) next to the right chip.
  - A directional arrow (`→`) replaces the neutral "vs".
  - The stats strip is prefixed `from → to:` so `+12 / −3` reads
    naturally ("12 added, 3 removed going from the left file to the
    right file").
  - The `⇄ Swap sides` button becomes `⇋ Reverse direction`; its
    tooltip explains that the click swaps FROM/TO.
- **Why `from`/`to` instead of `baseline`/`current`?**  `current`
  implied one of the configs was from "now", which is wrong when you
  diff two old configs against each other.  `from`/`to` encodes only
  direction, not time — perfect for any pairwise comparison whether
  both configs are historical, both are fresh, or mixed.
- **Testid renames:**
  - `diff-swap-sides-btn` → `diff-reverse-btn`
  - New testids: `diff-from-label`, `diff-to-label`
- **Helper / test updates:** `DiffPage.swap_sides_btn` →
  `DiffPage.reverse_btn`; `test_swap_sides_link_reverses_url` →
  `test_reverse_direction_link_reverses_url`; new assertion
  `test_from_and_to_role_labels_visible`.

### Added (diff: collapsed-context folding for large configs)

- **Context folding** on `/configs/{left}/vs/{right}`.  Long runs of
  equal lines far from any change are squashed into a single expandable
  "… N unchanged lines …" marker, matching the convention used by git,
  GitHub, GitLab and VS Code.  Drops a real-world FortiGate vs
  FortiGate comparison from **35,422 rendered `<div>`s** to **~900** —
  a ~32× reduction in browser layout cost.
- **Zero-round-trip expansion.**  Every collapsed marker ships a
  sibling `<template>` element carrying the hidden lines as
  pre-rendered markup.  Clicking the marker clones the fragment into
  the DOM in place of the marker, applies syntax highlighting to the
  new lines, and removes the marker + template.  No network call, no
  flash of unstyled content.
- Keyboard-accessible: markers are `<button>`s so Tab / Enter / Space
  all work.
- **New model:** `netcanon.models.diff.DiffGroup` — `{kind, lines}`
  where ``kind`` is the per-line classification or the new
  ``"collapsed"`` group.
- **New service:** `netcanon.services.diff.fold_context(lines,
  context=3)` — pure, two-sweep Manhattan-style distance-to-change
  computation.  Default context (`3` lines) matches unified-diff
  convention.
- **New testids:** `diff-line-collapsed`, `diff-collapsed-template`.
- **Tests:** 9 new unit tests in `tests/unit/test_diff_service.py`
  exercising the folding algorithm (boundaries, adjacent changes,
  context=0, default=3, negative rejected, order preservation).
  3 new E2E tests in `TestDiffContextFolding` covering marker
  visibility, count attribute, and click-to-expand behaviour.

### Added (config diff — Tier 1 textual line diff with compatibility guardrails)

- **`POST /api/v1/configs/diff`** — line-level unified diff between two
  stored configurations.  Body: `{left, right, force?}`.  Returns a
  `DiffReport` containing the per-line breakdown, aggregate stats
  (`{added, removed, equal}`), and a compatibility report.  Uses
  stdlib `difflib.SequenceMatcher`; no new runtime dependencies.
- **Compatibility guardrails (defence in depth).**  Two configs are
  considered diff-compatible when `type_key` (`device_type`) AND
  `file_extension` match on both records.  Mismatches:
  - API refuses with **HTTP 422** unless the caller explicitly passes
    `force=true` in the body.
  - UI: the "Compare" button on `/configs` opens a target picker that
    lists only matching configs by default; cross-vendor options are
    hidden behind a "Show cross-vendor" toggle and dimmed.
  - `/configs/{left}/vs/{right}` page always renders, but an
    incompatible pair without `?force=true` gets a red block banner
    and a "Compare anyway" override button in place of the diff body.
  - With `force=true` the diff is computed anyway; a red banner warns
    semantic equivalence is not guaranteed.
- **Deep-linkable diff URL** at `/configs/{left}/vs/{right}` (with
  optional `?force=true`).  Reuses the config viewer's syntax
  highlighter client-side — each diff line's `<span>` goes through
  `_cvRenderHighlighted(text, ext)` post-render so cfg/xml colouring
  stays consistent between the viewer and the diff view.
- **Compare button** on every row of `/configs`; lightweight modal
  picker keyed on `type_key` + `file_extension`.
- **New models:** `netcanon.models.diff.{DiffLine, CompatibilityReport,
  DiffRequest, DiffReport}`.  **New service:**
  `netcanon.services.diff.{check_compatibility, compute_diff}` — pure,
  no I/O, easily testable.
- **New tests:**
  - `tests/unit/test_diff_service.py` (12 tests): pure-function tests
    for compat logic, add/remove/replace, force annotation, empty input,
    trailing-newline handling.
  - `tests/integration/test_configs_api.py::TestDiffCompatibility` +
    `::TestDiffOutput` (8 tests): same-type OK, cross-vendor 422,
    force override, 404 on missing filename, line-number monotonicity.
  - `tests/e2e/test_backup_flow.py::TestDiffApi` +
    `::TestDiffPageUI` + `::TestDiffPageContent` (13 tests): live-API
    wiring, Compare button and picker, cross-vendor hide/show, banner
    severity, force override, swap-sides link.
- **New testids** for Compare picker and the diff page; see
  `tests/testid_reference.md`.

### Fixed (config viewer search misses queries that cross syntax-highlight spans)

- **Cross-span search now works.** The syntax highlighter splits the
  config text into many text nodes interleaved with ``<span class="tok-*">``
  elements.  The previous per-text-node ``indexOf`` loop couldn't see a
  match that straddled a span boundary, so queries like ``64:ff9b``
  (FortiGate IPv6 NAT prefix — ``64`` is a ``tok-number`` span, ``:ff9b``
  is plain text in the next node) or ``hostname Router`` (keyword span
  followed by plain text) silently returned zero matches even when the
  substring was clearly present.
- **Fix:** ``_cvSearch`` in ``base.html`` now flattens the ``<pre>`` into
  a single string while building a ``(node, absolute_offset)`` segment
  map, finds matches in the flat text, and wraps each match across
  whatever boundaries it crosses.  Matches are processed in reverse
  document order so earlier offsets stay valid as later ones mutate
  the DOM.  A single logical match becomes a *group* of ``<mark>``
  elements; ``configViewerNav`` toggles the ``.current`` class on every
  element in the group and scrolls to the first.
- **New E2E tests** in ``tests/e2e/test_backup_flow.py``:
  - ``test_cross_span_query_finds_match`` — asserts ``"hostname Router"``
    (straddles the ``tok-keyword`` span) now matches.
  - ``test_cross_span_match_current_class_applied_to_all_pieces`` —
    asserts every ``<mark>`` in the group gets ``.current``.

### Added (parallel backup execution within a job)

- **Per-job parallelism** — `_run_backup_job` now dispatches device work
  to a bounded `ThreadPoolExecutor`.  Up to `backup_concurrency` devices
  run simultaneously; additional devices wait in the executor's FIFO
  queue and start as slots free up.  A 30-device job with 30 s per
  device now completes in ~3 × the per-device latency instead of 30 ×.
- **`Settings.backup_concurrency`** — new configurable, range `[1, 10]`,
  default `10`.  Hard-capped at `MAX_BACKUP_CONCURRENCY = 10` in
  `netcanon/config.py` to protect target SSH servers (most vendor caps
  are 5–16) and bound server thread count.  Override via
  `NETCANON_BACKUP_CONCURRENCY`; see `.env.example`.
- **Serial fast-path** — jobs with a single device (or deployments
  pinned to `backup_concurrency=1`) skip the thread pool entirely;
  traces and error paths stay unchanged for those callers.
- **Thread-safety contract** documented in the `_run_backup_job`
  docstring: results list is pre-populated and never resized, each
  worker mutates exactly one index, and `FileConfigStore` atomic writes
  handle storage concurrency.
- Tests default to serial execution (`test_settings` sets
  `backup_concurrency=1`) so the existing observation test and all
  ordering-sensitive assertions remain deterministic.  Explicit parallel
  tests in `TestBackupConcurrency` exercise the pool via `Barrier(n)`.

### Added (persistent backup-progress panel + per-device lifecycle states)

- **`BackupResult.status` lifecycle** — new intermediate values `queued`
  and `running` alongside the existing terminal `success` / `failed`.
  `_run_backup_job` now pre-populates one `BackupResult` per device in
  `queued` state, flips each to `running` when its collector is invoked,
  and sets the terminal state on completion.  Polling clients can snapshot
  the results list at any point and see exactly which device the engine is
  working on.
- **Floating job-progress panel** (`base.html` — global):
  - Bottom-right floating widget, present on every page.
  - Collapsible header showing aggregated job status + live summary
    (`2/5 complete — running: 1 — queued: 2` or `5/5 succeeded`).
  - One row per device with status icon (`○` queued, `⟳` running, `✓`
    success, `✗` failed), host label, per-device duration, and truncated
    error on failure.
  - **Persists across full page reloads** — the active job ID is stored
    in `localStorage["netcanon.activeJob"]`; on `DOMContentLoaded` the
    panel resumes polling if the stored job is still non-terminal, and
    renders the final state otherwise.
  - Explicit `Dismiss` button (no auto-dismiss) clears the panel AND the
    localStorage key.  A "View full job details" deep link jumps to the
    corresponding card on `/jobs`.
  - Dispatches `netcanon:job-started`, `netcanon:job-progress`,
    `netcanon:job-complete`, and `netcanon:job-dismissed` `CustomEvent`s
    on `document` so page-level code (e.g. the dashboard row injector)
    can react without re-polling.
- **New `data-testid`s:** `job-progress-panel`, `job-progress-header`,
  `job-progress-summary`, `job-progress-toggle`, `job-progress-body`,
  `job-progress-device-row`, `job-progress-device-status`,
  `job-progress-device-host`, `job-progress-device-duration`,
  `job-progress-device-error`, `job-progress-footer`,
  `job-progress-view-link`, `job-progress-dismiss`.  The legacy
  `job-status-banner`, `job-id-display`, and `job-status-display` testids
  are aliased onto the new panel for backward compatibility.

### Removed

- **Inline job status banner** on `index.html` — replaced by the global
  floating progress panel (above).  The dashboard's submit handler now
  delegates to `startJobProgress(jobId)` and listens for the
  `netcanon:job-complete` event for the "inject a row into the recent
  jobs table" step.

### Added (config viewer: syntax highlighting + in-modal search)

- **Syntax highlighting** in the shared config viewer modal (`viewConfig()`):
  comments, keywords, strings, IP addresses, and numbers for Cisco / Fortigate /
  Mikrotik `.cfg` output, plus tags and attributes for OPNsense XML.  Unknown
  extensions fall back to escaped plain text.  Palette is VS Code "Dark+"
  inspired; all tokens are rendered as `<span class="tok-*">` so E2E tests and
  custom themes can target them.
- **In-modal search** with live match counter, previous / next navigation
  (▲ / ▼ buttons), keyboard shortcuts (Enter = next, Shift+Enter = previous,
  Escape = clear or close), and wrap-around.  Matches are wrapped in `<mark>`
  elements; the currently-selected match gets `mark.current` for a distinct
  highlight colour and is auto-scrolled into view.
- **New `data-testid`s** for the viewer: `config-viewer`, `config-viewer-title`,
  `config-viewer-content`, `config-viewer-search`, `config-viewer-search-count`,
  `config-viewer-search-prev`, `config-viewer-search-next`, `config-viewer-close`.
  Full reference in `tests/testid_reference.md`.

### Changed (job status reflects per-device outcomes)

- **`JobStatus.partial`** — new terminal state for backup jobs where at least
  one device succeeded AND at least one failed.  Terminal-state semantics are
  now:
  - `completed` — every device succeeded.
  - `partial`   — mixed result (≥1 success, ≥1 failure).
  - `failed`    — zero successes (every device failed).

  Previously a job was marked `completed` regardless of per-device outcomes;
  users had to look at the success/total column to notice failures.  The UI
  now shows an amber `badge-partial` and a ⚠ indicator for mixed runs.

### Added (backup jobs page + recurring schedules)

- **Job persistence** — `FileJobStore` writes one JSON file per completed backup
  job to `{data_root}/jobs/`.  All jobs are reloaded into `app.state.jobs` at
  startup, so job history survives server restarts.
- **`BackupJob.schedule_id` / `schedule_name`** — new optional fields track
  which schedule triggered a job (snapshot of name at run time).  `None` for
  manually triggered runs.
- **`GET /jobs`** — dedicated Jobs page listing all backup jobs newest-first.
  Each job is a collapsible card showing: short ID, status badge, success/total
  count, timestamp, duration, and trigger (schedule name or "Manual").  Expanded
  body shows a per-device results table with View / Download / (Open) links and
  the config filename.  URL hash navigation: `/jobs#a1b2c3d4` auto-expands and
  scrolls to the matching job card.
- **`/schedules`** — Schedule management page and backing API:
  - **`GET /api/v1/schedules/`** — list all schedules
  - **`POST /api/v1/schedules/`** — create a recurring backup schedule
    (name, interval\_minutes, devices list)
  - **`DELETE /api/v1/schedules/{id}`** — delete a schedule
  - **`POST /api/v1/schedules/{id}/toggle`** — enable / disable a schedule
- **`BackupSchedule` model** (`netcanon/models/schedule.py`) — stores schedule
  metadata: id, name, enabled, interval\_minutes, devices, created\_at,
  last\_run\_at, next\_run\_at, last\_job\_id.
- **`FileScheduleStore`** (`netcanon/storage/schedule_store.py`) — persists
  schedule definitions as JSON under `{data_root}/schedules/`.
- **APScheduler integration** — `AsyncIOScheduler` (timezone=UTC) is started in
  the app lifespan.  Each enabled schedule registers an `IntervalTrigger` job.
  Blocking SSH runs via `asyncio.to_thread` so it never blocks the event loop.
  Scheduler state is purely in-memory; schedule definitions are re-loaded from
  disk and re-registered on every startup.
- **`next_run_at` tracking** — captured from APScheduler after registration and
  after each run; persisted to disk so the Schedules page always shows an
  accurate value even before the first tick.
- **Nav updated** — "Jobs" and "Schedules" links added between Dashboard and
  Configs in the nav bar (order: Dashboard | Jobs | Schedules | Configs |
  Definitions | API Docs).  Swagger nav updated to match.
- **`apscheduler>=3.10.4`** added to `requirements.txt` and `pyproject.toml`.

### Added (nav bar on API Docs page)

- **`GET /docs`** — FastAPI's built-in Swagger UI is now replaced by a
  custom route that injects the Netcanon nav bar (sticky, same style as
  all other pages) so users can always navigate back from the API explorer.
  The raw `/openapi.json` schema endpoint is unchanged.  `/redoc` is
  disabled (it was unreachable from the UI anyway).

### Changed (vendor-specific field naming)

- **`ConnectionConfig.handle_paging` → `cisco_more_paging`** — renamed to make
  clear this flag controls Cisco `--More--` space-injection specifically.
  `terminal length 0` remains deliberately avoided on all Cisco definitions.
- **`ConnectionConfig.needs_shell_menu` → `opnsense_shell_menu`** — renamed to
  make clear this flag detects and dismisses the OPNsense numbered console menu
  (sends `"8"` to enter the shell).  Not applicable to any other current vendor.
- **`ConnectionConfig.needs_enable`** — unchanged.  Enable/privileged-mode
  escalation is a cross-vendor concept in Netmiko (Cisco IOS, HP ProCurve,
  Aruba OS-CX, and others).
- Updated all four YAML definition files, both collectors, all test YAML strings,
  `tests/fixtures/definitions.py`, `Get-NetworkConfigs.ps1`,
  `Test-NetworkConfigs.ps1`, and all README/doc files to match.

### Added (config storage & open-in-editor)

- **Subdirectory storage layout** — config files are now saved under
  `{device_type}/{safe_host}/` inside `configs_dir` instead of a flat root.
  Example: `configs/Cisco/192-168-1-1/Cisco_192-168-1-1_20260414_120000.cfg`.
  The self-describing filename format is unchanged.
- **Startup migration** — `FileConfigStore.__init__` automatically moves any
  flat files left by older versions into the correct subdirectory.  Non-config
  files (log files, README) are left untouched.
- **Collision safety** — if two backups of the same device complete within the
  same second, a numeric suffix is appended (`…_1.cfg`, `…_2.cfg`, …) so no
  file is ever silently overwritten.
- **`resolve_path(filename)`** — new public method on `BaseConfigStore` and
  `FileConfigStore`.  Returns the absolute filesystem path for a given filename,
  checking the subdirectory location first then falling back to the root for
  files that pre-date migration.
- **`Settings.open_in_editor: bool = False`** — new flag.  When `True`, enables
  the `POST /api/v1/configs/{filename}/open` endpoint.  Set to `True` in
  `netcanon_desktop/settings.py`.  Can also be enabled for local web
  deployments via `NETCANON_OPEN_IN_EDITOR=true`.
- **`POST /api/v1/configs/{filename}/open`** — opens the named config file in
  the OS default text editor (`os.startfile` on Windows, `open` on macOS,
  `xdg-open` on Linux).  Returns 204 on success; 403 if disabled; 404 if not
  found; 500 if the OS refuses to open the file.  Documented as desktop-only
  in `AGENTS.md`; the web equivalent is the existing View button.
- **"Open" button** (`data-testid="config-open-btn"`) — appears in the Actions
  column of the Configs page only when `open_in_editor=True`.  Calls the open
  endpoint; shows a success or error toast via `showToast()`.

### Tests (config storage & open-in-editor)

- `tests/unit/test_storage.py` — 19 new/updated tests: subdirectory save,
  collision safety (triple-collision), `resolve_path` (subdir + flat fallback +
  missing), startup migration (multiple files, non-config left in place,
  idempotent), and `rglob`-based listing.  Existing tests updated to use
  `store.resolve_path()` instead of manually constructing paths.
- `tests/integration/test_configs_api.py` — `TestOpenConfig` (5 tests): 403
  when disabled, 404 for missing file, 204 on success, correct path passed to
  `os.startfile`, 500 when OS refuses.
- `tests/testid_reference.md` — `config-open-btn` added with conditional
  visibility note.

---

### Added (logging)

- **`netcanon/logging_config.py`** — New `configure_logging(level, log_file)` function.
  Sets up a `StreamHandler` (stderr) plus an optional `RotatingFileHandler` (5 MB, 3
  backups) on the root logger.  Idempotent: skips when real (non-pytest) handlers are
  already present.  Suppresses `paramiko`, `uvicorn.access`, `multipart`, and `asyncio`
  to `WARNING` regardless of root level to reduce noise in INFO/DEBUG runs.
- **`netcanon_desktop/__main__.py`** — `_configure_logging()` called before
  `DesktopApp()`.  In frozen (installed) mode writes to
  `%APPDATA%\Netcanon\netcanon.log`; in dev mode uses console only.  Fatal startup
  exceptions now go through `logger.critical(..., exc_info=True)` before the message
  box so the stack trace is captured in the log file.
- **`netcanon_desktop/server.py`** — `log_config=None` added to `uvicorn.Config` so
  uvicorn's startup does not call `logging.config.dictConfig()` and overwrite the root
  logger configuration set by `configure_logging()`.
- **`netcanon_desktop/settings.py`** — `log_level` default raised from `"warning"` to
  `"info"` so desktop INFO logs reach the file handler.

### Changed (logging)

- **`netcanon/api/routes/backups.py`** — Device backup failures upgraded from
  `WARNING` to `ERROR` and now include `exc_info=True` for full traceback capture.
- **`netcanon/api/routes/configs.py`** — Added module logger; all three endpoints now
  emit structured log records (`DEBUG` for list/get, `INFO` for delete success,
  `WARNING` for 404 paths).
- **`netcanon/api/routes/definitions.py`** — Added module logger; reload endpoint
  logs loaded count and source directory at `INFO`.
- **`netcanon/storage/file_store.py`** — Added module logger; `save()` logs filename
  and byte count at `INFO`, `list_configs()` at `DEBUG`, `delete()` at `INFO`.
- **`netcanon_desktop/app.py`** — Lifecycle events (start, server ready, quit, window
  closed) logged at `INFO`.
- **`netcanon_desktop/tray.py`** — Added module logger; `run_detached()` at `DEBUG`,
  Show/Quit callbacks at `DEBUG`/`INFO`, `stop()` exception swallowed at `DEBUG`
  (was silent).
- **`netcanon_desktop/window.py`** — Added module logger; `create()` and `start()` at
  `INFO`, show/hide/destroy at `DEBUG`, `on_closed` callback exception at `DEBUG`
  (was silent).

### Tests (logging)

- `tests/unit/test_logging_config.py` — 17 new unit tests across three classes:
  `TestConfigureLoggingBasic` (handler type, levels, idempotency),
  `TestFileHandler` (rotating handler, directory creation, write-through),
  `TestNoisyLoggerSuppression` (third-party loggers capped at WARNING, netcanon.*
  left at NOTSET).  `reset_root_logger` autouse fixture restores root logger state
  after each test.

---

### Security

- **Credential encryption at rest** (`netcanon/security/credentials.py`) —
  Device passwords and enable passwords are now encrypted with Fernet
  symmetric encryption before being written to disk.  The key is stored in
  the OS secure credential store (Windows Credential Manager / macOS Keychain
  / Linux SecretService) via the `keyring` library.  Existing plaintext
  profiles and schedule device lists are automatically migrated to encrypted
  storage on first load.  In-memory model objects always hold plaintext;
  encryption is a storage-layer concern only.
- **Path traversal protection** (`netcanon/storage/file_store.py`) —
  `resolve_path()` now rejects any filename that does not match the expected
  naming convention regex before touching the filesystem.  Both the
  subdirectory and flat-fallback paths are verified to lie inside the storage
  root via `Path.resolve().is_relative_to()`.
- **Open-in-editor extension whitelist** (`netcanon/api/routes/configs.py`) —
  `POST /api/v1/configs/{filename}/open` now checks the file extension against
  an explicit allowlist (`{.cfg, .conf, .txt, .xml, .log}`) and returns 400
  for any other type, preventing the OS handler from being invoked on
  executables or other unintended file types.
- **Host field validation** (`netcanon/models/device.py`,
  `netcanon/models/device_profile.py`) — `DeviceTarget.host`,
  `DeviceProfileCreate.host`, and `DeviceProfileUpdate.host` now validate
  against `ipaddress.ip_address()` or an RFC-1123 hostname regex.  Shell
  metacharacters, path separators, and other invalid values are rejected
  with HTTP 422.
- **Passwords removed from HTML DOM** — `data-password` /
  `data-enable-password` attributes removed from the Dashboard
  `<option>` elements (`index.html`).  Credentials are fetched via
  `GET /api/v1/devices/{id}` when a saved device is selected.  The
  `data-profile` attribute on Devices page cards (`devices.html`) no
  longer includes credential fields; `runDeviceBackup()` fetches the full
  profile from the API on demand.
- **Data directories added to `.gitignore`** — `devices/`, `schedules/`,
  `jobs/`, and `configs/` are now excluded from version control to prevent
  credential-bearing files from being committed.
- **`cryptography>=41.0.0` and `keyring>=24.0.0`** added to
  `requirements.txt` and `pyproject.toml` dependencies.
- **`SECURITY.md`** — new document describing the security architecture,
  threat model, implemented controls, and known limitations.  Must be kept
  up-to-date with any security-relevant change.

### Tests (security)

- `tests/unit/test_credentials.py` — 18 tests covering key initialisation
  (first run, cached reload, idempotent), `encrypt`/`decrypt` round-trip
  (empty string, unicode, uniqueness per call), `InvalidToken` on garbage
  input, and `decrypt_field()` migration helper (encrypted→True,
  plaintext→False, empty→False).
- `tests/unit/test_storage.py` → `TestResolvePathSecurity` — 7 tests
  covering `../` traversal, `.cfg`-suffixed traversal, absolute paths,
  subdir-relative paths, empty string, and a positive case asserting the
  resolved path stays inside the storage root.
- `tests/unit/test_models.py` → `TestDeviceTarget` — 7 host validation tests:
  IPv4, IPv6, hostname accepted; `../`, `/`, space, semicolon rejected.
- `tests/integration/test_configs_api.py` → `TestOpenConfig` — 2 new tests
  for extension whitelist (`.exe`, `.zip` → 400).
- `tests/integration/test_configs_api.py` → `TestPathTraversal` — 4 new
  tests: `../../etc/passwd` GET/DELETE → 404, `.cfg`-suffixed traversal →
  404, absolute path → 404.

### Added (device profiles)

- **`DeviceProfile` model** (`netcanon/models/device_profile.py`) — stores
  profile metadata: `id` (UUID), `name`, `type_key`, `host`, `port`, `username`,
  `password`, `enable_password` (optional), `notes` (optional), `created_at`.
  `DeviceProfileCreate` and `DeviceProfileUpdate` companion models.
- **`FileDeviceProfileStore`** (`netcanon/storage/device_profile_store.py`) —
  persists profiles as JSON under `{data_root}/devices/{id}.json`.
- **`GET/POST /api/v1/devices/`** and **`GET/PUT/DELETE /api/v1/devices/{id}`** —
  full CRUD for device profiles.
- **`GET /devices`** — Devices page listing all profiles as collapsible cards.
  Each card shows name, type badge, host, backup count, and actions (▶ Backup /
  Edit / Delete).  Expanding the card reveals a per-config history table.
  Inline edit panel (`device-edit-panel`) allows credential updates without
  leaving the page.
- **Dashboard — saved device select** (`data-testid="device-profile-select"`) —
  selecting a saved profile pre-fills all form fields.  Optional "Save as Profile"
  name input (`data-testid="device-profile-name-input"`) creates or links a profile
  when the backup form is submitted.
- **`ConfigRecord.device_profile_id`** — new optional field linking a stored
  config to the device profile that produced it.  Persisted as a sidecar
  `{filename}.meta.json` alongside each config file; sidecar is cleaned up on
  delete.  `list_configs()` reads sidecars to populate the field.
- **`BackupSchedule` — two-pronged targeting** — `target_type_keys: list[str]`
  (back up all profiles of matching types) and `target_device_ids: list[str]`
  (back up specific profile UUIDs); mix is permitted.  Inline `devices` list
  retained for backward compatibility.  `ScheduleCreate` validates that at least
  one target field is non-empty.
- **`GET /devices` nav link** added between Dashboard and Jobs.
  Order: Dashboard | Devices | Jobs | Schedules | Configs | Definitions | API Docs.

### Fixed (View / Download buttons — WebView compatibility)

- **`base.html`** — Added shared `viewConfig(filename)` function (fetches config
  and displays it in a new inline modal), `downloadConfig(filename)` function
  (blob-based download, works in Qt WebEngine where `<a download>` is unreliable),
  and `closeConfigViewer()`.  New config viewer modal (`#_config-viewer`) added to
  the base layout; closes on backdrop click or Escape key.
- **`configs.html`** — View (`config-view-link`) and Download (`config-download-btn`)
  changed from `<a target="_blank">` / `<a download>` to `<button>` elements
  calling `viewConfig()` / `downloadConfig()`.  Added `DOMContentLoaded` hash
  handler: navigating to `/configs#{filename}` scrolls to the matching row,
  briefly highlights it, and auto-opens the viewer modal.
- **`jobs.html`** — View (`job-config-view-link`) changed from
  `<a href="/api/v1/configs/…" target="_blank">` to `<a href="/configs#{filename}">`
  so clicking View on a job result navigates to the Configs tab with the file
  pre-selected.  Download (`job-config-download-btn`) changed from `<a download>`
  to `<button onclick="downloadConfig(…)">`.
- **`devices.html`** — Same View / Download fix as `configs.html` applied to the
  per-device config history table.

### Fixed

- **`configs.html`** — Post-delete empty-check used CSS selector `.config-row`
  (no such class) instead of `[data-testid="config-row"]`, causing the page to
  reload after *every* deletion rather than only when the last config was removed.
- **`base.html`** — Removed orphaned `.badge-success` CSS rule that duplicated
  `.badge-completed` and leaked device-result vocabulary into the job-level badge
  namespace.

### Added

- **`POST /api/v1/definitions/reload`** — New API endpoint that re-reads all YAML
  files from `definitions_dir` and replaces the in-memory registry without a server
  restart.  Returns `{ "loaded": N, "type_keys": [...] }`.
- **Definitions page** — "↻ Reload" button (`data-testid="def-reload-btn"`) that
  calls the new reload endpoint and refreshes the page on success.
- **Configs page** — "View" link (`data-testid="config-view-link"`) and download
  button (`data-testid="config-download-btn"`) are now separate explicit actions in
  the Actions column.  The filename cell is now plain text.
- **Toast notifications** (`data-testid="toast"`) — Global `showToast(msg, type)`
  function in `base.html` replaces all `alert()` calls with a non-blocking,
  auto-dismissing notification (4 s timeout).  Types: `info`, `success`, `error`.
- **Inline job results** — After a backup job completes, per-device results
  (host, type, success/failure, error message) are rendered directly in the status
  banner.  The recent-jobs table row is injected by JS; no full-page reload occurs.
- **Active nav state** — Current page is highlighted in the navbar
  (`class="active"`, `aria-current="page"`).  `active_page` context variable added
  to all three UI route responses in `main.py`.
- **UTC timestamp localisation** — All `[data-utc]` elements are converted to
  browser-local time on `DOMContentLoaded` via a global script in `base.html`.
  Server-rendered fallback (UTC string) is preserved for non-JS contexts.
- **Enable Password conditional visibility** — The Enable Password field is shown
  only for device types where `connection.needs_enable` is `true`.  Driven by
  `data-needs-enable` attributes on `<option>` elements; toggled on type change.
- **Port collapsed to Advanced** — The SSH port field (default 22, rarely changed)
  is now inside a `<details>` summary labelled "⚙ Port", reducing visual noise in
  the backup form.
- **Inline delete confirmation** — The Delete button on the Configs page now shows
  an in-row "Delete? Yes / No" prompt instead of the browser's native `confirm()`
  dialog (which can be suppressed in embedded WebView contexts).
- **Empty-state guidance** — All three pages now include actionable text in their
  empty states rather than bare declarative messages.

### Changed

- **Nav brand** (`data-testid="nav-brand"`) changed from `<span>` to `<a href="/">`
  so clicking the product name navigates home, per standard convention.
- **Submit button** (`data-testid="submit-backup-btn"`) is now disabled and labelled
  "Running…" while a backup job is in flight, preventing double-submission.
- **Polling error handling** — The job-status polling `setInterval` now counts
  consecutive fetch failures and stops after 3, showing a toast instead of silently
  looping forever.
- **Jobs table** — "Devices" column removed (redundant with "Success / Total"
  denominator).  "Job ID" column is now plain text (`data-testid="job-id-text"`)
  rather than a link to the raw JSON API response.  "Created (UTC)" header
  simplified to "Created" (timestamps are localised by JS).
- **Configs table** — "Captured (UTC)" column header simplified to "Captured".
  Filename column is now plain text; view/download actions moved to the Actions
  column.
- **Definitions table** — "Strategy" column renamed to "Collection"; strategy
  values are now human-readable ("SSH (Netmiko)", "SSH (Shell)") rather than
  internal Python identifiers.  "Ext" column header renamed to "File Ext".
  Notes cell gains a `title` tooltip showing the full (untruncated) text.
- **`button:disabled`** CSS rule added to `base.html` — disabled buttons now show
  `opacity: 0.6` and `cursor: not-allowed` globally.
- **E2E test** `test_submit_completes_and_page_reloads` renamed to
  `test_submit_completes_and_shows_job_in_table` and updated to assert that the
  jobs table becomes visible via JS injection (no `wait_for_load_state` needed).
- **Remove device button** gains `aria-label="Remove this device"` for
  accessibility.

### Tests

- `tests/integration/test_definitions_api.py` — Added `TestReloadDefinitions`
  (5 tests): 200 response, loaded count, type_keys list, post-reload registry
  accessibility, idempotency.
- `tests/testid_reference.md` — Updated for all new/changed testids: `toast`,
  `job-id-text` (replaces `job-link`), `config-view-link` (moved to Actions),
  `config-download-btn`, `config-delete-confirm-btn`, `config-delete-cancel-btn`,
  `def-reload-btn`.  Notes added for conditional visibility and `data-utc`.

---

## [0.1.0] — initial release

- Multi-vendor SSH configuration backup via Netmiko and Paramiko Shell strategies
- FastAPI + Jinja2 web UI: Dashboard, Configs browser, Definitions viewer
- Windows desktop shell: PySide6/QtWebEngine window, pystray system-tray icon,
  embedded Uvicorn server (`netcanon_desktop`)
- cx_Freeze MSI installer (`setup_desktop.py`)
- Four-layer test suite: unit, integration, E2E (Playwright), desktop
