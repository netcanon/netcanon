# Remediation sweep — 2026-06-06 review tail

Closes out the remaining findings from
[`../findings-register.md`](../findings-register.md) after Batches 1–5
shipped (v0.1.3 + PRs #10/#12/#13/#14/#15).  Same two-stage technique
as the prior `security-triage/` and `docs-audit/` rounds:

1. **Stage 1 — parallel agents (read-only on repo code).**  Each agent
   owns one finding (or a small cluster), investigates against the
   current tree, and writes an **apply-ready result file** here
   (`result-<ID>.md`): exact edits, rationale, risk, and a test plan.
   Agents do **not** modify repo code — they write only their result
   file.
2. **Stage 2 — orchestrator validates + actuates.**  I review each
   result, then apply the change myself (Edit/Write), run the tests,
   and land it as a themed PR.  Untested agent specs are validated by
   me at actuation time.

Model tier per agent: **Opus** for multi-site / refactor / matrix /
security-adjacent work; **Sonnet** for well-scoped doc + small-code
fixes.  (Nothing below Sonnet.)

## Agent roster

| ID | Model | Findings | Scope | Result file |
|----|-------|----------|-------|-------------|
| RA-06 | opus | R-06, R-08 | FortiGate `_CAPS` MTU declaration + regen `CROSS_MESH_RESULTS.md` / `PHASE4_RECONCILIATION.md` | `result-RA-06.md` |
| RA-12 | opus | R-12 | Split the `/docs` Swagger reskin out of `api/routes/ui.py` → `api/routes/docs.py` | `result-RA-12.md` |
| RA-13 | opus | R-13 | `is_secondary` cross-vendor fidelity (cisco_iosxe_cli ↔ arista_eos) + round-trip tests | `result-RA-13.md` |
| RA-16 | opus | R-16 | Sanitiser PII/network tail (`snmp.contact`, VLAN-SVI IPv4, RADIUS/trap/DHCP hosts) | `result-RA-16.md` |
| RA-18 | opus | R-18 | Extract backup orchestration from `api/routes/backups.py` → `services/backup_runner.py` | `result-RA-18.md` |
| RA-2021 | sonnet | R-20, R-21 | `file_store` hostname decode bijection + NETCONF port-name "no rename" banner | `result-RA-2021.md` |
| RA-24 | sonnet | R-24 | Normalise the 8 codec `__init__.py` headers to one template | `result-RA-24.md` |
| RA-docs | sonnet | R-23, R-25, R-26, R-27 | Doc/interlink sweep (migrate.html map, tests/README See-also, nxos links, orphan READMEs) | `result-RA-docs.md` |
| RA-19 | sonnet | R-19 | Assess `models/migration.py` codec-contract placement (recommend KEEP-or-move) | `result-RA-19.md` |

## Deliberately NOT farmed (WATCH — verdict stands)

- **R-29** (`migrate.html` further `<script>` extraction) and **R-30**
  (`juniper_junos/render.py` `render_intent` decomposition) are CE
  **WATCH/KEEP** verdicts — earned-size files to split only if they
  become change-hotspots.  Forcing a large, risky refactor for a P3
  WATCH item is the wrong trade; left as-is with this rationale.

## Result-file template

Each `result-<ID>.md` must contain:

1. **Finding(s) + current state** — what's wrong now, with `file:line`.
2. **Proposed change** — apply-ready: for edits, literal
   `old → new` blocks with file paths + enough surrounding context to
   be unique; for new files, full content.
3. **Test plan** — exact tests to run, and the **full content** of any
   new test file.
4. **Risk + blast radius** — what could break; what's additive.
5. **Self-assessment** — confidence (high/med/low) + open questions for
   the orchestrator.

## Status

Stage 1 dispatched; results land as `result-*.md`.  Stage 2 actuation
tracked in the per-theme PRs + a closing note here.
