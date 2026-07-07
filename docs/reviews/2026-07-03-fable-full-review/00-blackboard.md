# 2026-07-03 — Full-project review (Fable fresh-eyes pass)

## Mission

Full review of netcanon at `v0.4.15` (main @ `79c29a0`) across every lens we can think of.
The repo has already been reviewed comprehensively by earlier passes (see "Prior coverage"
below) — your job is a **fresh-eyes pass with a different model family**: find what those
passes missed, what has **regressed or drifted since** they ran, and what is newly risky in
code added in the v0.3.x–v0.4.x arcs (12th codec, IPv6 static-route sweep, mikrotik fixes,
version extraction, dep bumps, release pipeline changes).

Verdict discipline: report only findings you can cite to `file:line` (or reproduce with a
probe). Rank severity honestly (blocker / major / minor). "No findings in my lens" is a
valid and welcome result — do NOT pad.

## What netcanon is

12-codec multi-vendor network-config translator + SSH backup tool.
- Translator: `netcanon/migration/` — canonical schema (`schema.py`), per-codec
  `codecs/<name>/{parse,render}.py`, support matrices, orchestrator (port-name translation
  layer), fidelity/round-trip machinery.
- Web app: FastAPI under `netcanon/api/` + `netcanon/templates/` (Jinja), services under
  `netcanon/services/`, storage under `netcanon/storage/`, security helpers under
  `netcanon/security/`.
- Backup: SSH collectors under `netcanon/collectors/`, device definitions under
  `netcanon/definitions/` + `definitions/` data, TOFU host keys, opt-in egress allow-list,
  Fernet-encrypted credentials.
- CLI `netcanon/cli.py`; desktop MSI wrapper `netcanon_desktop/` + `setup_desktop.py`.
- Distribution: PyPI + Docker (GHCR/DockerHub) + Windows MSI. Version via setuptools_scm
  from git tag. CI: `.github/workflows/{ci,pypi-publish,docker-publish,desktop-msi-publish,pii-guard,zizmor}.yml`.
- Tests: `tests/{unit,integration,e2e,desktop}` + guard tests (cross-mesh CI guard,
  changelog guard, complexity ratchet, ship-before-wire invariants).

## HARD CONSTRAINTS (all agents)

1. **READ-ONLY** except your one report file (the runner's contract). You MAY run
   read-only probes: `py -c "..."` one-offs that import the local `netcanon` package and
   call parse/render/etc. Use `py` (never bare `python` — Windows Store shim).
2. Do NOT run: pytest suites, pip installs, git commands that mutate, servers, docker,
   network calls, regen tools (`tools/run_full_mesh.py`, `tools/run_phase4_reconciliation.py`).
3. **NEVER read** these paths (PII / unlicensed content):
   - `docs/codebase-review/`
   - `docs/reviews/2026-06-19-run3-verification/`
   - `local/` (entire dir — gitignored dogfood corpus + lab creds)
   - runtime state dirs at repo root: `data/`, `devices/`, `configs/`, `jobs/`, `schedules/`
4. Cite everything as `path:line`. Concrete > abstract.

## Prior coverage — do NOT re-litigate / re-hunt

Adjudicated decisions (raising these again is noise unless you have NEW evidence):
- SOPS/encrypted-config = evaluated, NO-GO; creds are Fernet 3-tier by design.
- Backup artifacts legitimately contain device `$6$` password hashes (documented, SECURITY.md).
- Bind 127.0.0.1 default, fail-closed serve, TOFU host-key DEFAULT (breaking change, intended).
- Port-name translation is an ORCHESTRATOR layer; bare `run_plan` renders verbatim names by
  design. junos `trunk_allowed_vlans`/`vlans[]`/`interfaces[].vrf` mesh drops = this
  architecture, parked.
- Declared-lossy surfaces are honest: opnsense 1-IP-per-iface, iosxe-xml/opnsense static
  routes, vyos VLAN↔VNI, HSRP→vrrp-groups, etc. The support-matrix + walker honesty
  system exists and is tested — check for *regressions/drift*, not the concept.
- Verified non-bugs from the 2026-07 dogfood arc: hostname space→underscore sanitization;
  Jinja `{{ }}` template-token rejection on reparse; `vlans[].id` set-GROWS materialization;
  junos dedup of genuine source duplicates; aoss empty-stub module-slot elision.
- IPv6 static routes were just fixed across all 12 codecs (#251–#260) and verified —
  don't re-audit that exact surface unless you find a NEW defect in the new code itself.

Prior passes (2026-06): 34-agent swarm review (90 findings, remediated #53–#65), 5 blind
adversarial audits (remediated v0.4.0–v0.4.5), UX review (20 must-fixes, all shipped).
So the cheap findings are gone. Look deeper, look at NEW code, look at interactions.

## Roster

Phase 1 — Review (16 lens agents, each writes `NN-<lens>.md` here):
- 10-security-web, 11-security-secrets, 12-security-ssh, 13-codec-parse-robustness,
  14-codec-render-injection, 15-schema-matrix-honesty, 16-concurrency-state,
  17-error-handling, 18-test-quality, 19-ci-supply-chain, 20-web-ui-ux, 21-docs-honesty,
  22-performance, 23-packaging-platform, 24-architecture-maintainability, 25-cli-api-contract

Phase 2 — Verify (4 adversarial verifiers, read all phase-1 reports):
- 40-verify-security (covers 10/11/12), 41-verify-codecs (covers 13/14/15),
  42-verify-platform (covers 16/17/19/22/23), 43-verify-product (covers 18/20/21/24/25)

Main thread synthesizes to `99-synthesis.md` afterwards.
