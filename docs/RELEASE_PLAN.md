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

The plan separates **structural** release work (license, CI,
packaging — items required to ship) from **qualitative** release
work (trust signals, identity, polish — items required to land
well).  Both classes matter; the structural items are necessary and
the qualitative items determine whether the matrix-honesty
discipline gets COMMUNICATED to a skeptical audience.

---

## Pre-flight checklist (1-2 sessions of work)

The boring but essential structural part.  Most items have raw
material in the repo already; some are missing entirely.

| Item | Status | Notes |
|---|---|---|
| `LICENSE` | Verify present | If absent → MIT or Apache-2.0; vendor-tooling space is overwhelmingly permissive-licensed |
| `SECURITY.md` | Exists; gap noted | Doc audit flagged a possible gap (type_key constraint as security-adjacent); worth a follow-up paragraph.  See "Operator-trust building" below for the substantive content this file needs |
| `CONTRIBUTING.md` | Missing | Critical for releases.  Walks: add a fixture, add a codec, add a canonical field.  Existing `docs/adding-a-canonical-field.md` and `docs/adding-a-target-profile.md` are perfect raw material |
| `CODE_OF_CONDUCT.md` | Probably missing | Adopt Contributor Covenant; copy-paste is fine |
| `.github/ISSUE_TEMPLATE/` | Missing | Critical for bug-report surface (see "Repo-level 'asking for help'" below) |
| `.github/PULL_REQUEST_TEMPLATE.md` | Missing | Lightweight; references the doc-sync checklist from `CLAUDE.md` |
| Public CI (GitHub Actions) | Verify | Pre-commit hooks + suite need to run on PRs from external contributors |
| Real-IP / secret scrub audit | Hard rule already prevents | Run a final `git log --all -p \| grep` for IPs/hostnames before going public |
| Semver versioning + tag | Need to decide | Recommended: `v0.1.0` to signal pre-1.0 — sets honest expectations |
| Public-facing repo URL | Need to decide | GitHub is the obvious primary for this audience |
| Project name conflict check | Not yet done | Verify `netconfig` (or alternate) is available on PyPI, GitHub, Docker Hub.  See "Project identity & discoverability" below |

---

## Project identity & discoverability

A tool without a clear public identity gets confused with adjacent
tools and skipped over in search results.  Items that need
deliberate work:

* **Name conflict check.**  `netconfig` on PyPI may be taken;
  `netconfig-translator` or similar may be necessary.  Same on
  GitHub.  Same on Docker Hub.  Verify before committing to a name
  — a mid-launch rename is significantly painful.
* **Logo or identity mark.**  Even a simple one.  Operators
  recognise tools by their badges in repos and conference slides;
  a project without a mark looks unfinished.  No need for a
  professional designer; a clean SVG mark is sufficient.
* **GitHub Topics.**  Add `network-automation`, `cisco`, `juniper`,
  `fortinet`, `aruba`, `mikrotik`, `opnsense`, `network-config`,
  `vendor-translation`.  Each topic increases the surface where
  operators stumble across the project organically.
* **A 1-2 sentence project description on GitHub** that's distinct
  from the README.  The description shows up in search results and
  GitHub's project lists; it deserves separate copy.
* **A 1-line tagline.**  Not "multi-vendor network device
  configuration translator" — too generic.  Something like
  "Translate live network configs across 8 vendor families with
  verifiable cross-vendor accuracy."  The "verifiable" word matters;
  it's the differentiator.
* **An honest comparison table** vs adjacent tools — not aggressive,
  just clarifying.  E.g. "vs Capirca/Aerleon: those are firewall-
  DSL forward emitters; we're a multi-vendor parse+render
  translator with explicit Tier-3 deferral on firewall/NAT."
  Operators arriving from "I'm looking for a Capirca alternative"
  need to know whether you're competing or complementary.

---

## Pre-launch quality hardening

Items in this section don't ship features; they ship POLISH.  An
operator's first 5 minutes after install determines whether they
bookmark the project or drift away.

### Failure-mode quality

The tool has good code quality, but qualitative trust often hinges
on failure modes.  Worth a deliberate audit:

* **What happens with a 50MB config file?**  The file_store has a
  50MB cap; what does the operator see when they hit it?  Stack
  trace or graceful error?
* **What happens if SSH disconnects mid-backup?**  Is the partial
  config persisted?  Is it cleaned up?  Is the operator told?
* **What happens if a probe regex doesn't match?**  Does the backup
  proceed without facts, or fail?
* **What happens if the operator pastes the wrong vendor's config
  in the migrate page?**  Auto-detection is a thing; what's the
  error message?
* **Memory under load** — 10 devices × 100KB configs × concurrent
  backups.  Does the tool sit at reasonable RSS or balloon?

These are the things that will surface in early bug reports.  A
pre-release "failure mode tour" pass to make every error path
produce an actionable message (not a stack trace) pays for itself
in reduced GitHub-issue noise.

### Browser / desktop polish

The web platform is the primary surface.  The desktop wrapper is a
Tier-3 audience.  Both deserve a polish pass:

* **Browser compat.**  Latest Chrome / Firefox / Safari / Edge.
  The dark-mode work helps, but unverified Safari is the typical
  gap.
* **Mobile / tablet view.**  Network engineers occasionally check
  tools on iPad in the field.  Doesn't have to be optimised, but
  shouldn't be broken.
* **Empty states.**  What does the migrate page look like before
  any device is added?  Before any config is saved?  With one
  device?  Operators land on an empty UI more often than you'd
  think.
* **Loading states.**  Long-running operations (backup, render,
  validation) need clear "working..." feedback.  Operators who
  don't see progress assume the tool hung.
* **Keyboard navigation / accessibility.**  Network engineers run
  multiple tabs / Vim-style workflows.  Keyboard shortcuts (already
  partially present) deserve documentation; tab order should be
  sensible.

The matrix-honesty discipline applied to UI: every interactive
element needs a `data-testid` (already enforced).  Every error
state needs an actionable message (less enforced).  Every empty
state needs context (mostly missing).

### Operator-facing copy quality

The text on every page is operator-facing copy.  The tone of that
copy signals what kind of project this is.

* **Error messages.**  "Validation failed" → tell them WHAT failed
  and HOW to fix it.  The validation pass aligned in-app limitation
  messages with `CAPABILITIES.md`; that discipline should extend to
  all operator-facing text.
* **Tooltips.**  Most fields don't have tooltips.  Tooltips with
  concrete examples ("e.g. `192.168.1.1`" / "e.g. `cisco_iosxe`")
  help operators who don't read docs.
* **Banner copy on the migrate page.**  The Tier-3 detection banner
  is well-worded.  Look at every other banner with that lens.
* **Form-field labels.**  "Device type" vs "Vendor" vs "Codec" —
  three concepts, three labels, sometimes used interchangeably.
  Pick one term per concept and use it consistently.

---

## Maximum bug-report surface area — the strategic question

Network engineers are a specific audience with specific habits.
The launch strategy has to match.

### What this audience is like

1. **They work with real production configs they can't share publicly.**
   The whole tool is built around this — synthetic fixtures + sanitized
   real captures + cross-vendor expectation YAMLs.  The bug-report
   friction has to match: operators need a low-effort path to sanitize
   and submit.

2. **They're skeptical of automation that touches gear.**  They've
   seen too many "auto-config tools" produce garbage.  They will
   assume your tool is wrong until proven otherwise.  The matrix-
   honesty discipline (CODEC_BUG=0, `CAPABILITIES.md`, the Tier-3
   honesty) is your trust-building asset — lead with it, don't bury
   it.

3. **They cluster on specific platforms.**  HN gets eyeballs but
   most are not your audience.  Real audiences:
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

### First-impression UX

The README is what 95% of visitors see.  The current README is
functionally complete but reads like internal documentation.  It's
missing the things that grab a network engineer in the first 30
seconds:

* **A 1-line tagline** above the fold (covered in "Project identity
  & discoverability" above).
* **A demo gif or asciinema recording** showing the migrate page
  in action.  30 seconds, no audio, autoplay.  Network engineers
  won't read 2000 words; they'll watch a 30-second clip.  asciinema
  specifically (vs YouTube) signals "this is a real tool, not a
  marketing site."
* **A "before/after" cross-vendor example** above the fold — paste
  in a Cisco snippet, get back the equivalent Junos / Arista /
  Aruba.  Concrete > abstract.
* **The matrix-honesty achievement, but as a trust signal.**  "Zero
  CODEC_BUG cells across ~12,000 cross-vendor field-cells" is
  meaningless without context.  "We test every cross-vendor field
  translation across 47 codec pairs against vendor-doc-grounded
  expectations, and as of this commit none of them silently
  translates incorrectly.  Here's the live audit matrix" — that's
  a trust signal a network engineer will read twice.

The tool already DOES all this — it just doesn't tell its own
story.

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

### Operator-trust building

Network engineers won't trust a tool that touches their gear without
doing diligence.  The matrix-honesty discipline gives you the
substrate for this trust, but it has to be *visible*.

* **Reproducible builds.**  The Docker image should be reproducible
  — same source → same digest.  Operators in regulated environments
  will verify.
* **Signed releases.**  Cosign + Sigstore (covered in detail under
  Packaging Tier 1).
* **A substantive `SECURITY.md`** — not a 5-line "report bugs to
  email."  A real threat model:
  * "What this tool can do to your devices" (answer: pull configs
    over SSH, deploy migrated configs)
  * "Where your credentials live during a session" (answer: in-
    memory only; never written to disk)
  * "What gets logged" (answer: this list, with redactions for
    these fields)
  * "Supply-chain integrity story" (Trusted Publishing, signed
    images, SBOM)
  * "What would happen if you compromised the running container?"
    (worst-case incident response)
* **A "How we test" page** narrating the cross-mesh audit.  Take a
  screenshot of `PHASE4_RECONCILIATION.md`'s matrix.  Explain it.
  Show the 8 variance classes.  Operators will read this if framed
  as "here's how we know we don't silently translate wrong."
* **A "What we won't do" page** lifted from CAPABILITIES.md's
  Tier-3 section but with operator-facing rationale.  Honesty about
  scope is rare in this space; operators reward it.

### Repo-level "asking for help"

Three core docs to write, plus several walkthrough/reference pages:

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

### Documentation that operators can actually use

`CAPABILITIES.md` is a reference document — it tells you what's true.
Operators need walkthroughs that show them how to USE what's true.

* **Per-vendor "What works for me?" pages** under `docs/vendors/`.
  A Cisco operator visiting the repo wants to know "for Cisco
  IOS-XE, what's my story?"  Today they have to cross-reference
  RESULTS.md + CAPABILITIES.md + the codec docstring.  Pre-compose
  8 vendor pages: target audience is "operator who knows their
  vendor and wants to know what this tool does for them."
* **A migration walkthrough** under `docs/walkthroughs/` — not the
  developer-facing migrate-page partial inventory, but a "you have
  50 Cisco switches and you're refreshing to Aruba; here's the
  path" narrative.  Real workflow, real steps, realistic friction
  points called out.
* **An "I have a config that doesn't translate cleanly" troubleshooting
  page** — diagnose:
  * Is it a Tier-3 surface? (firewall, NAT) → expected; here's why
  * Is it a Lossy field? → expected within bounds; here's how to
    verify
  * Is it a CODEC_BUG? → file an issue; here's the template
* **A "Configs we deliberately can't translate, and why" failure-
  mode showcase** — concrete examples of Tier-3 inputs (FortiGate
  UTM profiles, Junos firewall filters, Cisco zone-based firewall)
  showing the tool's output: the Tier-3 banner, the dropped-section
  list, the "review manually" review comments.  Operators reading
  this will see HONESTY where they expected to find OVER-CLAIMS,
  and the trust differential is meaningful.

---

## Demo & sample artifacts

The biggest gap to "show me what this does in 30 seconds" is that
there's no canonical low-friction path that doesn't involve setting
up devices, pasting configs, navigating the UI.

Worth investing in:

* **A `tools/demo.py` script** that loads pre-baked sample configs
  (synthetic, public-research-derived), runs the full pipeline, and
  prints the cross-vendor diff.  One command, no UI, no devices
  required.
* **A "kitchen sink" tour** under `docs/walkthroughs/` showing 3-5
  canonical migration scenarios:
  * "Cisco IOS-XE → Junos: VLAN + interface + static routes"
  * "FortiGate → MikroTik: DHCP pools + interfaces"
  * "Aruba → Arista: switch refresh with hash review"
  * "OPNsense → Junos: capability-matrix limitations on display"
* **A public-hosted "try it" instance** is what users will WANT but
  you should NOT build — too much credential-exposure risk.  The
  right answer is "run docker-compose up locally; here's a
  30-second loop."

The synthetic kitchen-sink fixtures already exist
(`tests/fixtures/synthetic/`); they just need a curated subset
surfaced as "here's what this looks like."

---

## Sanitization tooling

The bug-report-surface-area strategy assumes operators can sanitize
configs before submitting.  Without a sanitization helper, operators
either submit raw (security risk for them, leak risk for the project)
or skip submitting (signal loss for the project).  Build the helper
as a release-blocker (MUST tier).

**Status as of 2026-05-05:** The helper does NOT yet exist.  No
``tools/sanitize_config.py`` in the repo; no API endpoint; no UI
surface.  The existing ``netconfig.migration._naming.sanitise_hostname``
helper is for cross-vendor render-time normalisation (whitespace
collapse), NOT for redacting sensitive data.

### Architectural decision: integrated, multi-invocation, single source of truth

Build the helper as a **shared library accessible via three invocation
paths**, NOT three separate implementations.  This avoids the version-
skew + maintenance-fragmentation tax of an ad-hoc script that lives
alongside but evolves independently of the main app:

1. **`netconfig.tools.sanitize` Python module** — the actual
   sanitisation logic.  Vendor-aware via the existing codec parsers;
   operates on the canonical model rather than raw text.  Single
   source of truth.

2. **CLI subcommand `netconfig sanitize`** — exposed via the PyPI
   package's console-scripts entry point.  For operators NOT running
   the FastAPI server (one-shot pip install, CI / scripting).

3. **HTTP API endpoint `POST /api/v1/sanitize`** — exposed via the
   running FastAPI server.  For operators running Docker (or any
   deployed instance).

A fourth invocation path — a web UI page at `/sanitize` — is **deferred
to v0.2.0** contingent on operator-feedback signals showing the
friction is real.  Same shared library; thin presentation layer if
added.

### Why integrated, not ad-hoc

A separate ad-hoc script downloaded from the repo has version-skew
risk and gets stale relative to codec changes.  The shared-library
approach means:

* Sanitisation rules track codec evolution automatically — when a
  codec gains a new field, sanitisation rules for that field fall
  out of the canonical model walk.
* Single source of truth for "what gets redacted" — no parallel
  implementations to drift apart.
* Test surface shared with codec parsers — every fixture exercises
  both directions.
* Cross-vendor consistency: a Cisco config and a Junos config of the
  same network sanitise to byte-similar shapes because they pass
  through the same canonical model.

### Docker UX (the friction concern resolved)

The Docker user has the FastAPI server running already — that's the
point of the container.  They should NOT need to learn `docker exec`.
The HTTP API IS the answer for Docker users:

```
# Operator with NetConfig running on localhost:8765
curl -X POST http://localhost:8765/api/v1/sanitize \
  -F "source_vendor=cisco_iosxe_cli" \
  -F "config=@my-config.txt" \
  -o sanitized.txt
```

Two lines.  No `docker exec` gymnastics.  No mounting volumes for a
one-shot operation.  `curl` against the running container is
idiomatic for any server-in-container pattern operators are already
familiar with.

For PyPI / native users not running the server:

```
pip install netconfig
netconfig sanitize -i my-config.txt -o sanitized.txt \
  --source-vendor cisco_iosxe_cli
```

For Windows MSI users: the MSI ships the same Python entry point
under `<install>\netconfig.exe sanitize ...` — OR (better) they hit
the local FastAPI server's HTTP endpoint same as Docker users (the
MSI starts the server on `127.0.0.1:<port>` already).

### What gets sanitised (vendor-aware via canonical model)

Operating on the canonical model, the rules are field-typed.  This
gets you AST-level precision without the per-vendor regex
fragility:

| Canonical field | Replacement |
|---|---|
| `CanonicalIntent.hostname` | `device-N` (counter per session — same value always maps to same replacement so cross-references survive) |
| Public IPs in any field | RFC 5737 docs ranges (`192.0.2.x`, `198.51.100.x`, `203.0.113.x`) |
| Private IPs (RFC 1918, ULA, link-local) | Preserve — operators can keep these; not PII |
| `CanonicalLocalUser.hashed_password` | Obvious-fake hashes (`$5$REDACTED$REDACTED01`, `ENC fakeEncodedHash01==`, etc. matching the source format) |
| `CanonicalSNMP.community` | `public_redacted_N` |
| `CanonicalSNMPv3User.auth_passphrase` / `priv_passphrase` | `REDACTED-AUTH-N` / `REDACTED-PRIV-N` |
| `CanonicalRADIUSServer.shared_secret` | `REDACTED-SECRET-N` |
| `CanonicalInterface.description` | `description redacted` (preserve presence; redact content) |
| `CanonicalDHCPPool.dns_servers` (if public) | RFC 5737 docs ranges; preserve private resolvers |
| `CanonicalIntent.dropped_tier3_sections` | Strip entirely (Tier-3 carry-through may contain anything) |
| Comments / banners | Strip entirely |

Counter-per-session means the same value gets the same replacement
across the whole config — so operators can verify the sanitised
output's structure matches their original mental model without their
real device names appearing.

### `--dry-run` mode (critical for trust)

```
netconfig sanitize --dry-run -i my-config.txt --source-vendor cisco_iosxe_cli
```

Prints the substitution table:
```
hostname production-edge-01      → hostname device-1
ip address 198.51.100.5/24       → ip address 198.51.100.5/24  (already in docs range)
ip address 4.4.4.4               → ip address 192.0.2.42       (public→docs)
snmp-server community SuperSecret → snmp-server community public_redacted_1
description Uplink to ISP-PRD     → description redacted
... (full table) ...
```

Operator reviews before committing.  The framing matters:
**"Don't trust me; here's exactly what I'll change. Now run it for
real."**  Critical for the audience's skepticism.

### Testing surface

For each codec, every existing real-capture fixture round-trips
through sanitisation as a regression-guard:

```
parse → sanitise → render → parse → assert(no real-IPs / hashes / secrets remain)
```

This pattern means sanitisation rules can't silently leak through —
the same property the codec round-trip discipline already enforces
extends to the sanitiser.

### What this enables

Once the sanitiser ships, `BUG_REPORTING.md` documents a concrete
fixture-submission path:

```
1. Sanitise:  curl -X POST http://localhost:8765/api/v1/sanitize ...
2. Verify:    diff <original> <sanitised>  (or use --dry-run first)
3. Submit:    attach sanitised file to issue using fixture_submission.yml template
```

Without the helper, that workflow has implicit "operator
hand-redacts everything" friction that most operators won't do.
With it, the bug-report path is a 30-second loop.

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
* **Reproducible builds**: same source → same digest.  Operators
  in regulated environments will verify.
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
now — see "Project identity & discoverability" above for the
collision-check discipline).  Useful for:
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
| **1 — Pre-flight** | 1-2 sessions | LICENSE, SECURITY (substantive content per "Operator-trust building"), CONTRIBUTING, CODE_OF_CONDUCT, issue templates, real-IP audit, semver tag, name-conflict check |
| **2 — Project identity foundation** | 1 session | Logo, GitHub Topics, project description, tagline.  Comparison table vs adjacent tools |
| **3 — Pre-launch quality hardening** | 2-3 sessions | Failure-mode tour (every error path produces actionable message); browser-compat sweep; empty-state + loading-state pass; copy-quality pass; tooltip layer |
| **4 — Demo + sample artifacts** | 1 session | `tools/demo.py`; per-scenario walkthroughs under `docs/walkthroughs/` |
| **4.5 — Sanitization tooling** | 1-2 sessions | `netconfig.tools.sanitize` shared library + CLI subcommand `netconfig sanitize` + HTTP API endpoint `POST /api/v1/sanitize`.  Vendor-aware via canonical-model walk; `--dry-run` mode; round-trip regression-guards on every real-capture fixture.  Three invocation paths, single source of truth.  Blocks Phase 5 because `BUG_REPORTING.md` documents this as the canonical fixture-submission path |
| **5 — Operator-facing docs** | 2 sessions | Per-vendor "what works for me?" pages; "How we test" page narrating the cross-mesh audit; "What we won't do" Tier-3 page; troubleshooting page; failure-mode showcase; `BUG_REPORTING.md` referencing the Phase 4.5 sanitiser invocation paths |
| **6 — Packaging foundation** | 1 session | Dockerfile (multi-stage, distroless, non-root, reproducible), GHCR publish workflow, PyPI publish workflow with Trusted Publishing.  Verifies the sanitiser's three invocation paths all land in their respective artefacts |
| **7 — README rewrite** | 1 session | Lead with tagline + asciinema + before/after example + matrix-honesty trust signal |
| **8 — Private beta** | 3 weeks (calendar) | Five trusted network engineers, each in a different vendor environment, given the Docker image with "find me bugs" mandate.  Saves the embarrassing-on-HN fire drill of "everyone hits the same bug in week one."  Cheap to set up; high return |
| **9 — Tag v0.1.0, soft launch** | Same day | Push to GitHub public, push Docker image, publish PyPI |
| **10 — Hard launch** | Spread over a week | Show HN → r/networking → NANOG list → vendor subreddits → blog post → conference proposals |
| **11 — Triage cadence** | Ongoing | 48-hour SLA on bug reports; weekly fixture-import wave; quarterly versioned release |

The matrix-honesty discipline + `CAPABILITIES.md` + the cross-mesh
audit harness are the **distinctive features** of this tool.  Other
config-translator tools claim accuracy; this one can prove it.  That's
the lede; everything in phases 1-7 (incl. 4.5) is the work of
communicating that lede to a skeptical audience.

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

* **Don't skip the private beta phase.**  Three weeks of trusted-
  network-engineer testing before the public launch is the
  difference between "everyone hits the same bug in week one" and
  "the tool already had three rounds of feedback baked in."

---

## Priority ranking

If forced to rank for a v0.1.0 release:

| Tier | Items | Why |
|---|---|---|
| **MUST (release-blocker quality)** | Pre-flight checklist (LICENSE, SECURITY substantive, CONTRIBUTING, issue templates), 1-line tagline + 30s asciinema + before/after example, substantive `SECURITY.md`, "How we test" page, per-vendor "what works for me?" pages, failure-mode actionable error messages, name-conflict check, **sanitization helper (CLI + HTTP API + shared library — Phase 4.5)** | The trust-signal substrate.  If these are weak, the matrix-honesty discipline doesn't get communicated and the tool gets dismissed alongside the over-claiming alternatives.  The sanitiser specifically is MUST-tier because BUG_REPORTING.md is meaningless without a concrete invocation path. |
| **SHOULD (quality differentiator)** | `tools/demo.py` + walkthroughs, GitHub Topics + comparison table, browser compat + empty states + loading states, operator-facing copy pass, private beta phase, in-app sanitiser web UI wrapper (defer to v0.2.0 contingent on demand) | Substantially raises the quality bar; operators who would have given the tool a shrug will give it a bookmark. |
| **NICE (post-1.0)** | Mobile / tablet view, multi-language docs, conference talk submissions, public landing page (separate from GitHub), Tier-4 native packages | Real value but lower per-hour return at v0.1.0.  Defer. |

The matrix-honesty discipline is the differentiator.  Everything in
tier MUST is communication of that discipline to a skeptical
audience.  The structural items in the pre-flight checklist are
necessary; the qualitative items above are what determines whether
the release lands well.

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
* You have private-beta capacity (5 testers × 3 weeks = ~15 person-
  weeks of feedback).

Triggers that suggest "wait":

* In-flight architectural change that may invalidate parts of
  `CAPABILITIES.md`.
* Active Wave that hasn't settled (matrix integrity in flux).
* Pre-flight items not yet shipped.
* No bandwidth for the 48-hour-SLA discipline post-launch.

---

## See also

* [`README.md`](../README.md) — current quickstart (will be rewritten
  during Phase 7 of this plan)
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
