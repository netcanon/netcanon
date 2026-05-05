# Public Release Plan

**Status:** Future wave.  Not yet started.  Captured here so a
post-compaction context (or a contributor walking the docs cold) has
the strategic plan available without re-deriving it.

This is a forward-looking working document — when the release
actually happens, prune the "plan" sections and convert this file
into a `docs/RELEASE_NOTES.md` that records what was actually done.
Until then, it's the design + rationale for taking the project
public.

---

## Why this document exists

The project currently sits in private development with strong matrix-
honesty discipline (CODEC_BUG=0 across ~12,000 field-cells; cross-
mesh fidelity audit; explicit Tier-3 boundary; honest CapabilityMatrix
declarations).  At some point that discipline pays off only if the
tool gets in front of operators and starts catching the cells the
internal audit can't surface (the ones no fixture exercises).  This
document is the plan for crossing that boundary deliberately.

The plan is opinionated — it's not "here's an exhaustive menu" but
"here's the recommended path with rationale."  Adjust per-decision
when you start the wave.

---

## Pre-flight checklist (1-2 sessions of work)

The boring but essential part.  Most items have raw material in the
repo already; some are missing entirely.

| Item | Status | Notes |
|---|---|---|
| `LICENSE` | Verify present | If absent → MIT or Apache-2.0; vendor-tooling space is overwhelmingly permissive-licensed |
| `SECURITY.md` | Exists; gap noted | Doc audit flagged a possible gap (type_key constraint as security-adjacent); worth a follow-up paragraph |
| `CONTRIBUTING.md` | Missing | Critical for releases.  Walks: add a fixture, add a codec, add a canonical field.  Existing `docs/adding-a-canonical-field.md` and `docs/adding-a-target-profile.md` are perfect raw material |
| `CODE_OF_CONDUCT.md` | Probably missing | Adopt Contributor Covenant; copy-paste is fine |
| `.github/ISSUE_TEMPLATE/` | Missing | Critical for bug-report surface (see "Maximum bug-report surface area" below) |
| `.github/PULL_REQUEST_TEMPLATE.md` | Missing | Lightweight; references the doc-sync checklist from `CLAUDE.md` |
| Public CI (GitHub Actions) | Verify | Pre-commit hooks + suite need to run on PRs from external contributors |
| Real-IP / secret scrub audit | Hard rule already prevents | Run a final `git log --all -p \| grep` for IPs/hostnames before going public |
| Semver versioning + tag | Need to decide | Recommended: `v0.1.0` to signal pre-1.0 — sets honest expectations |
| Public-facing repo URL | Need to decide | GitHub is the obvious primary for this audience |

---

## Maximum bug-report surface area — the strategic question

Network engineers are a specific audience with specific habits.  The
launch strategy has to match.

### What this audience is like

1. **They work with real production configs they can't share publicly.**
   The whole tool is built around this — synthetic fixtures + sanitized
   real captures + cross-vendor expectation YAMLs.  The bug-report
   friction has to match: operators need a low-effort path to sanitize
   and submit.

2. **They're skeptical of automation that touches gear.**  They've
   seen too many "auto-config tools" produce garbage.  They will assume
   your tool is wrong until proven otherwise.  The matrix-honesty
   discipline (CODEC_BUG=0, CAPABILITIES.md, the Tier-3 honesty) is
   your trust-building asset — lead with it, don't bury it.

3. **They cluster on specific platforms.**  HN gets eyeballs but most
   are not your audience.  Real audiences:
   * **r/networking** (~600k) — primary audience; mostly enterprise/SP
     engineers
   * **NANOG mailing list** — North American Network Operators Group;
     tooling-friendly if framed right
   * **r/sysadmin** — secondary, broader appeal
   * **PacketPushers community / Discord** — concentrated network-
     engineering audience
   * **Network To Code Slack** — the largest network-automation
     community; specifically interested in tools like this
   * **Vendor-specific subreddits**: r/Cisco, r/Juniper, r/fortinet,
     r/mikrotik — pull bug reports per-codec
   * **Twitter/Mastodon (#NetworkEngineering #NetOps)** — short-lived
     but high-visibility
   * **LinkedIn Network Operations groups** — older audience but
     high-quality reports
   * **dev.to, lobste.rs** — adjacent technical audiences for pattern
     interest
   * **HN Show HN** — broad reach but mostly drive-bys; useful for
     initial visibility, not for sustained bug reports
   * **Conference talks: NANOG, Cisco Live, Network Field Day** — if
     you're up for it, single-best lever for credibility

### Specific framing that works for this tool

The matrix-honesty discipline is **rare** in this space.  Most tools
in this category have one of two failure modes: either they over-claim
accuracy and silently drop content, or they under-claim and over-warn
until operators tune them out.  This project explicitly avoids both
via `CAPABILITIES.md` + the Tier-3 banner + the cross-mesh audit.

Lead with that:

> "Multi-vendor network config translator across 8 vendors.  The
> cross-mesh audit shows zero CODEC_BUG cells across ~12,000 field-
> cells of test coverage — but that just means we haven't found them.
> **Bring us configs we haven't tested yet.** Sanitized fixtures
> welcome; we publish a sanitization helper.  We're explicit about
> what we don't translate (firewall, NAT — see CAPABILITIES.md).
> We're looking for the cells the audit hasn't surfaced because no
> fixture exercised them."

This framing:
* Doesn't claim perfection
* Quantifies what you DO claim (12,000 cells, 0 bugs in the matrix)
* Names the limitation honestly (Tier 3)
* Asks for a specific kind of help (real-world fixtures)
* Shows you have a way to consume the help (the sanitization helper,
  the fixture-add workflow)

### Repo-level "asking for help"

Three docs to write:

1. **`BUG_REPORTING.md`** — concrete walkthrough:
   * "Sanitize your config" — point at a `tools/sanitize_config.py`
     (write this if it doesn't exist; should mask IPs, hostnames,
     hashes, secrets across all 8 vendors)
   * "What fields to include in the issue" — source vendor + version,
     target vendor + version, sanitized snippet, what you expected,
     what you got
   * "What we'll do with it" — turn into a fixture under
     `tests/fixtures/real/<vendor>/`, add cross-vendor expectation
     YAML row, run the matrix
   * SLA: "we triage within 48 hours; we respond honestly even if the
     answer is 'this is Tier 3 by design'"

2. **`CONTRIBUTING.md`** — the project already has the raw material in
   `CLAUDE.md`'s doc-sync checklist + `docs/adding-a-canonical-field.md`.
   Lift those into a public-facing CONTRIBUTING that:
   * Walks adding a fixture (the matrix-friendly path)
   * Walks adding a codec (the heavy path)
   * Walks adding a canonical field (the architectural path)
   * Calls out the matrix-honesty discipline (no silent drops, no
     stale docstrings, no hard-coded prose counts)

3. **`.github/ISSUE_TEMPLATE/`** — at least three templates:
   * `bug_report.yml` — pre-filled fields per `BUG_REPORTING.md`
   * `feature_request.yml` — guides operators away from out-of-scope
     (firewall translation) and toward in-scope (new fixtures, new
     vendor)
   * `fixture_submission.yml` — explicit "I have a config that breaks
     this; here's the sanitized version" — separate from bug reports
     because the fixture itself IS the contribution

The SECURITY-disclosure path needs its own contact — `SECURITY.md`
should specify where to send a vulnerability report (private email,
encrypted if available; never as a public issue).

---

## Packaging — tiered to match the tiered audience

The MSI installer isn't clunky in absolute terms — it's clunky **for
the audience this tool's primary feature serves**.  Network engineers
running a multi-vendor migration are overwhelmingly comfortable with
Linux + Docker; many run their tooling on a jumphost that doesn't
have a desktop session at all.

### Tier 1: Docker image — the primary

```
docker run -p 127.0.0.1:8765:8000 \
  -v $(pwd)/configs:/app/configs \
  -v $(pwd)/devices:/app/devices \
  ghcr.io/<owner>/netconfig:0.1.0
```

Build properties:
* **Multi-stage build**: builder stage with deps, runtime stage with
  just the runtime artefact
* **Distroless or `python:3.14-slim` base**: small surface, fewer CVEs
* **Non-root user**: critical for security-sensitive tooling
* **Pinned Python**: 3.14 in the Dockerfile so users don't have to
  install Python at all
* **Signed images** via `cosign` against Sigstore — operators in
  regulated environments will require this
* **SBOM** via `syft` published alongside each release — same
  audience requirement
* **Volume-mounted state**: `/app/configs` (backups), `/app/devices`
  (device list), `/app/jobs` (job state) all volume-mounted so
  container state isn't lost on restart
* **Health check** on `/health` endpoint
* **Versioned tags** (`0.1.0`, `0.1`, `latest`) plus a `:dev` tag
  built from main on each commit
* **Hosted on GHCR** primarily; mirrored to Docker Hub if you want
  broad discoverability

This becomes the README's quickstart.  One command, no Python install,
no .NET runtime, no PySide6 dance.

### Tier 2: PyPI package — for technical / library users

`pip install netconfig` (or whatever name's available; check PyPI
now).  Useful for:
* Operators integrating into existing tooling pipelines (Ansible,
  NetBox, Nautobot)
* Power users running the FastAPI server inside their existing
  infrastructure
* Contributors developing locally

Setup:
* `pyproject.toml` already exists; add `[project]` metadata for PyPI
* `python -m build` + `twine upload`
* GitHub Actions workflow on tag push for automated PyPI publication
* Trusted Publishing (no API token in repo) — a small but meaningful
  security improvement

### Tier 3: Windows MSI — for point-and-click operators

Don't drop the desktop wrapper just because Docker is the headline.
There IS a real audience for Windows-native: smaller-shop network
admins, junior engineers, operators in environments where Docker is
policy-blocked.  The MSI is right for them.

The clunky part isn't the MSI per se — it's that it gets equal-billing
in the README.  Move it to Tier 3 and document it as the "I don't
want to use Docker" path explicitly.  Operators who would have been
confused by Docker-first will see "click here for the Windows
installer."

### Tier 4 (optional): Native packages

| Package | Effort | Audience |
|---|---|---|
| Homebrew formula (macOS) | Medium | macOS network engineers |
| `.deb` / `.rpm` | Medium | Linux ops who avoid Docker for policy reasons |
| Nix flake | Low (if you're into Nix) | Nix users; small but vocal |
| Snap / Flatpak | Medium | Desktop Linux users |
| AUR package | Low | Arch users |

Skip these for v0.1.0; add based on demand.  PyPI + Docker cover 95%
of installs.

---

## Concrete release sequence

When this wave actually starts, work this order:

| Phase | Effort | Outcome |
|---|---|---|
| **1 — Pre-flight** | 1-2 sessions | LICENSE, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, issue templates, real-IP audit, semver tag |
| **2 — Packaging foundation** | 1 session | Dockerfile (multi-stage, distroless, non-root), GHCR publish workflow, PyPI publish workflow |
| **3 — Sanitization tooling** | 1 session | `tools/sanitize_config.py` covering all 8 vendors; documented in `BUG_REPORTING.md` |
| **4 — Public-facing docs** | 1 session | README rewrite leading with capabilities + limitations honesty; QUICKSTART; BUG_REPORTING; CONTRIBUTING |
| **5 — Tag v0.1.0, soft launch** | Same day | Push to GitHub public, push Docker image, publish PyPI |
| **6 — Hard launch** | Spread over a week | Show HN → r/networking → NANOG list → vendor subreddits → blog post → conference proposals |
| **7 — Triage cadence** | Ongoing | 48-hour SLA on bug reports; weekly fixture-import wave; quarterly versioned release |

The matrix-honesty discipline + `CAPABILITIES.md` + the cross-mesh
audit harness are the **distinctive features** of this tool.  Other
config-translator tools claim accuracy; this one can prove it.  That's
the lede.

---

## What to NOT do

* **Don't do a "v1.0" release.**  The codebase is mature in scope but
  ten thousand operators haven't beaten on it yet.  v0.1.0 → v0.2.0
  → ... → v1.0.0 after sustained external use.  Pre-1.0 sets honest
  expectations.

* **Don't ship with a public-facing demo instance.**  Either the tool
  runs on the operator's machine or in their network — public hosted
  instances create credential-exposure incentives you don't want.

* **Don't accept binary device-config submissions in issues.**  Force
  the sanitization step.  A leaked production config in a public issue
  is a much worse outcome than slightly-higher-friction bug reporting.

* **Don't promise auto-translation of firewall rules.**  The deferral
  is the right call; advertise it as a deliberate design choice, not
  a "we haven't gotten to it."  Firewall translation is a different
  product (see `CAPABILITIES.md` Tier-3 boundary).

* **Don't open Discussions until you have triage capacity.**  GitHub
  Discussions creates an expectation of response.  Better to ship
  with Issues only and add Discussions when you can sustain the
  cadence.

---

## When to start

Triggers that suggest "now" rather than "later":

* `CAPABILITIES.md` matches the implemented codecs without any active
  lies (✅ as of validation pass).
* CODEC_BUG count holds at 0 through 1-2 fresh waves of unrelated
  fixture work (signal that the audit has stable surface area).
* Pre-flight checklist items are addressed (LICENSE etc.).
* You have 48-hour-SLA capacity for the first 2-4 weeks post-launch
  (the highest-velocity bug-report period).

Triggers that suggest "wait":

* In-flight architectural change that may invalidate parts of
  `CAPABILITIES.md`.
* Active Wave that hasn't settled (matrix integrity in flux).
* Pre-flight items not yet shipped.

---

## See also

* [`README.md`](../README.md) — current quickstart (will be rewritten
  during Phase 4 of this plan)
* [`ARCHITECTURE.md`](../ARCHITECTURE.md) — internal design (the
  audience for the public release plan is operators, not architects;
  this doc is internal)
* [`CAPABILITIES.md`](CAPABILITIES.md) — the operator-facing source of
  truth this release plan promotes
* [`CLAUDE.md`](../CLAUDE.md) — contributor directives; the
  CONTRIBUTING.md authored during Phase 1 of this plan should lift
  much of the matrix-honesty discipline from CLAUDE.md
* [`CHANGELOG.md`](../CHANGELOG.md) — chronological shipped work; this
  plan is forward-looking, NOT shipped, hence not in CHANGELOG
* [`tests/fixtures/real/RESULTS.md`](../tests/fixtures/real/RESULTS.md)
  — live per-codec certification matrix
* [`tests/fixtures/real/PHASE4_RECONCILIATION.md`](../tests/fixtures/real/PHASE4_RECONCILIATION.md)
  — live cross-mesh audit
