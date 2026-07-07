# Fable multi-lens full-project review — netcanon @ v0.5.3

- **Target:** `main` @ `8598d74` (tag `v0.5.3`), 12-codec multi-vendor config translator + SSH backup.
- **Method:** Opus hub orchestrates; **all review work performed in Fable at max effort**. 12 read-only lens agents → 2 codec-fidelity-promotion agents → adversarial verification wave (each finder's output an independent Fable skeptic tries to refute) → 1 synthesis agent.
- **Stance:** READ-ONLY. Produces this artifact + ranked findings. No code changes until the user greenlights remediation.
- **Date:** 2026-07-06.

## Deliverables

- `99-synthesis.md` — the ranked verdict + severity-ordered bug findings (HIGH/MAJOR/MEDIUM/MINOR), each with file:line, failure scenario, fix, confirmed-vs-plausible tag, and a themes section.
- `98-promotion-candidates.md` — the **separate** ranked list of difficult-but-feasible lossy/unsupported → supported fidelity-promotion opportunities (exact xpath, current disposition, why improvable, wiring sketch, de-risking verification), excluding hard logistical blockers.
- `NN-<lens>.md` — per-lens evidence trail (one file per lens).

## Added emphasis this run

A dedicated codec-fidelity-improvement lens hunts lossy/unsupported canonical fields that are difficult-but-not-impossible to promote toward supported, where there is real translation-fidelity payoff and it is NOT a hard logistical blocker (vendor images / Cisco contract / donor-blocked grammar / absent corpus / genuine platform limit). Matrix pessimism is the safe bias; every candidate is adversarially verified.
