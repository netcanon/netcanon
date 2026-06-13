# 99 — Code & architecture fleet synthesis

Consolidates the six Fleet-C investigations (CA–CF) plus the
adversarial-verification pass.  Authored by the orchestrator.
Per-finding detail lives in the `01-investigation-C*.md` chapters.

## Headline verdict

**This is a healthy, deliberately-disciplined codebase.** Across six
independent review lenses the findings are notable for what they are
*not*: **zero P0, zero crash-class P1, no god-files, no import cycles,
no layering inversions, no happy-path correctness bugs in 78 platform
files.** CA confirmed code and `ARCHITECTURE.md` substantially agree;
CD confirmed the dependency graph is strictly downward and acyclic
(the one back-edge, `canonical/port_names.py → codecs.base`, is
correctly quarantined under `TYPE_CHECKING`); CE confirmed every large
file is earned-size, not a god-file.

The two **P1**s are not architectural — they are a **security gap in
the sanitiser** and a **packaging gap in what we ship**. Both are
narrow, both are fixable in a few lines, and both were independently
corroborated (one by deterministic config inspection, one by an
adversarial refuter that tried and failed to refute it).

## The two P1s (both verified)

### P1-A — sanitiser leaks VRRP/CARP authentication secrets (CF-01, verified)
`netcanon sanitize` — the command operators are explicitly told to run
before pasting configs into public bug reports (`BUG_REPORTING.md:19-24`)
— never redacts `CanonicalInterface.vrrp_groups[].authentication`. The
sanitiser walk touches only `description` + `ipv4_addresses`
(`sanitize.py:215-236`); the field holds cleartext by design
(`intent.py:563-566`, `plain:`/`carp-key:` schemes); and three
renderers emit it verbatim (`aruba_aoss/render.py:673-677`
`plaintext-password "..."`; `opnsense/render.py:470-473` CARP
`<password>`; `cisco_iosxe_cli/render.py:472-476` `authentication text`).
Round-trip tests prove it survives the exact parse→render path the
sanitiser uses, and `--dry-run` shows no substitution → **false
assurance**. SECURITY.md's redaction table (`:305-315`) omits it
entirely. **Adversarial verdict: CONFIRMED-REAL, P1** (security /
secret-disclosure; not P0 only because it requires the config to carry
VRRP/CARP auth AND the operator to publish).

### P1-B — `tools/` absent from every shipped artifact (CF-02 / DA-01, verified)
The README's hero "See it in 10 seconds" command runs `tools/demo.py`,
but `tools/` is excluded from the wheel (`pyproject.toml:124`
`include = ["netcanon*","netcanon_desktop*"]`) **and** the Docker image
(`Dockerfile:36` copies only `netcanon/`; runtime installs the wheel +
`definitions/`). So the flagship onboarding command, and the
`tools/demo.py:14-15` pip-install instruction, are **broken in every
distributed artifact** — works only from a source checkout. The
`docker-build-smoke` CI job curls `/health` + `/` but never runs the
demo, so nothing catches it. **Deterministically confirmed** from
packaging config. P1 (first-impression onboarding).

## Cross-cluster themes

### Theme C-1 — error-taxonomy has one outlier (the Junos `TypeError`)
Triple-confirmed (DD-01, CC-01, CF-03): `juniper_junos/render.py:105`
raises `TypeError` on its wrong-input-type guard where all 7 other
codecs and the `CodecBase.render` contract raise `RenderError`. **Blast
radius is contained** (CF verdict): the pipeline's broad
`except Exception` (`migration_pipeline.py:255`) catches it → clean
`failed` job, **no 500** — only the `job.error` prefix is wrong
("unexpected error in stage rendering" vs "render failed"). The second
call site (`tools/sanitize.py:159`) has no try/except, but
`sanitized_intent` is always a `CanonicalIntent` there, so the guard is
structurally unreachable today. A real contract divergence and a latent
trap; **P2**, not a live crash. One-line fix.

### Theme C-2 — async/sync boundary: one event-loop-blocking route
`POST /api/v1/sanitize` is declared `async def` but calls the heavy,
synchronous parse→redact→render directly on the event loop
(`sanitize.py:42`), while every other pipeline endpoint is sync `def`
(auto-threadpooled by FastAPI) and the scheduler uses
`asyncio.to_thread` (CA-01, P2). Under concurrency this blocks all
requests for the duration of a sanitise. Fix: `run_in_threadpool`.

### Theme C-3 — invariants enforced socially, not mechanically
The frozen pipeline signatures (`run_plan` / `run_plan_with_rename` /
`run_plan_with_overrides`) are documented in three places and honored
in code, but there is **no `inspect.signature` guard test** (CD-03,
P2) — a reordered positional param or changed default could pass the
suite while breaking positional callers. The same shape recurs in DE-01
(no header-vs-`certainty`-ClassVar test). Both point at the same cheap
hardening: turn a documented invariant into a ~20-line guard test.

### Theme C-4 — cross-vendor fidelity: `is_secondary` is wired asymmetrically
Adversarially settled: `is_secondary` is **READ only on Arista's VARP
path** (`arista_eos/render.py:584/594/612`) and **SET only by Arista's
VARP parser** (`parse.py:960/1003`); `cisco_iosxe_cli` round-trips the
`secondary` keyword purely positionally (`render.py:287`, `idx>0`) and
never sets the flag. Consequence: `cisco_iosxe_cli → arista_eos` for a
classic `ip address X secondary` **loses the secondary designation**
(arista's plain-address parser also discards the trailer, so even
arista→arista loses it). Plus a captured-but-unused `(?P<secondary>…)`
regex group at `cisco_iosxe_cli/parse.py:127`. Real but narrow (classic
secondaries only; VARP anycast secondaries survive). **CC-02, P3.**

### Theme C-5 — `intent.py` VRRP/anycast docstrings are stale (NOT half-wired)
CB-01 flagged that `intent.py` calls VRRP/anycast fields "ship-before-
wire / unsupported" though Wave B/C wired them. The adversarial pass
built the full 8-codec table and proved **the two-sided invariant
holds**: every codec that populates/emits VRRP/anycast declares the
xpath `supported`/`lossy`; every codec whose `_CAPS` says `unsupported`
does not populate/emit. **No half-wired codec; this is docstring-only
drift → P3.** (Bonus nit: OPNsense lists the VRRP group path in *both*
`supported[]` `codec.py:165` and `lossy[]` `:188` — redundant, worth
de-duping.) This is exactly the over-claim the adversarial pass exists
to catch.

### Theme C-6 — one earned-size SPLIT worth doing, the rest are fine
CE's verdict: **no true god-files.** The big parsers are irreducible
vendor grammar (KEEP). The one genuine SPLIT is `api/routes/ui.py`
(894): ~48% (lines 447-884) is the `/docs` Swagger-UI dark-mode reskin
(`_DOCS_*` CSS/JS constants) interleaved with 8 unrelated thin page
handlers — clean seam at line 447 → `api/routes/docs.py`, zero behaviour
change (CE-01, P2). `migrate.html` (2477) and `juniper_junos/render.py`
(1503, a single ~1130-line `render_intent`) are WATCH→SPLIT (P3), both
with ready-made extraction maps (the latter has 14 section banners).

## Severity rollup (Fleet C, post-verification)

| Sev | Count | Items |
|-----|------:|-------|
| P0 | 0 | — |
| P1 | 2 | CF-01 (sanitiser secret leak, verified ↑ from P2) · CF-02/DA-01 (packaging) |
| P2 | ~5 | CC-01/CF-03 (Junos `TypeError`) · CA-01 (sanitize blocks loop) · CD-03 (no freeze-guard) · CE-01 (ui.py split) |
| P3 | ~12 | CC-02 (is_secondary) · CC-03 (PortIdentity.original) · CB-01 (vrrp docstring, ↓ from P2) · CB-02/03 · CA-02/03 · CD-06 · CD-doc · CE-02/03 · CF-04 |
| OBSERVATION | many | incl. CD-01/02 (positive), CB-O1–O5, CC-05/06/07 |

## What's GOOD (the codebase's strengths, for balance)
- **Exception-taxonomy translator** `api/_errors.py` — CB's "best file
  in the partition"; clean ParseError/RenderError/ValidationError →
  HTTP mapping.
- **End-to-end credential hygiene** — `SecretStr` + Fernet-at-rest +
  3-tier key resolution (CB, CF); `security/credentials.py` is solid.
- **All XML input parse sites are on defusedxml** (CF verified YES) —
  the v0.1.2 triage swap stuck; the 3 remaining stdlib `xml.etree` refs
  are render-only.
- **Atomic storage writes** (temp+rename) everywhere (CB).
- **The codec layer is the strongest area reviewed** (CC) — tight
  `CodecBase` contract, justified split-vs-single-file divergence,
  exemplary `_CAPS` matrix-honesty (the two-sided invariant genuinely
  holds), vendor-agnostic port-name mesh, uniform shared-helper use.
- **Clean acyclic dependency graph** (CD) — `models/` + `intent.py` are
  true leaves; the `canonical → codecs` back-edge is `TYPE_CHECKING`-
  quarantined.
- **The five per-pane rename orchestrators** are exemplary disciplined
  replication (CB, CD).

## Adversarial-pass outcomes (what verification changed)
1. **CF-01 upgraded P2 → P1** — refuter tried 4 refutation angles, all
   failed; the leak is real and reaches sanitised output.
2. **CB-01 downgraded (potential P2 methodology-violation) → P3
   docstring-only** — the 8-codec table proved no half-wiring.
3. **`is_secondary` "already wired" claim (Fleet D DD-03) refuted** —
   replaced by the accurate CC-02 (positional vs flag asymmetry).
4. **Packaging gap confirmed deterministically** from `pyproject.toml`
   + `Dockerfile` (no runtime build needed).

All findings flow into `../findings-register.md` and
`../recommended-remediation-plan.md`.
