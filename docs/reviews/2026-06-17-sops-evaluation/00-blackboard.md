# Blackboard — Should netcanon adopt SOPS secret management? (2026-06-17)

**Process:** netcanon file-per-agent blackboard. Read-only agents each write EXACTLY ONE report in this dir;
the main thread seeds this file + writes `99-synthesis.md` + is the sole actor that verifies/commits. Agents
must never read or write under `docs/codebase-review/` (the uncommitted PII dossier).

## Mission

Decide **whether and how** netcanon should add [SOPS](https://github.com/getsops/sops)-based secret management,
mirroring the sibling **Kontroll** project (which uses SOPS for its deploy-stack secrets). Specifically:

- **Is there a *practical* use case for SOPS in netcanon** — a real threat it uniquely mitigates given how
  netcanon actually stores secrets and is actually run? Or is it Kontroll-shaped tooling that doesn't fit a
  local-first single application?
- **If yes**, what does adoption concretely look like (what gets encrypted, where the key lives per run-mode,
  the decrypt-at-load flow, packaging/ops cost)?
- Return a clear **GO / NO-GO / GO-WITH-NARROW-SCOPE** verdict the main thread can act on — including the
  honest "do nothing / use a lighter alternative" outcome if that's correct.

This is a **design/research run only** — no code changes this run. The deliverable is this dossier + a
synthesis recommendation.

## Hard constraints (apply to every report)

- **Verify-first, cite `file:line`.** Every claim about how netcanon stores/handles a secret MUST be grounded in
  the actual code (e.g. the device-profile store's on-disk format) — do NOT assume "it's plaintext" or "it's
  encrypted"; open the file and confirm. Same for Kontroll's SOPS mechanics.
- **Right-size / anti-over-engineering is a first-class outcome.** netcanon is a *local-first single app*
  (PySide6 desktop + FastAPI server + Docker + Windows MSI), NOT a multi-service Ansible-deployed stack like
  Kontroll. Weigh SOPS's real operational cost (age/gpg key mgmt, binary deps in Docker/MSI, dev/test friction)
  against the actual threat. "This is security theater here / NO-GO" is a fully valid, even expected, verdict if
  the runtime decryption key co-locates with the ciphertext in every real run-mode.
- **netcanon ≠ Kontroll.** Explicitly separate what transfers from Kontroll's SOPS usage vs what is
  Kontroll-specific (Ansible render-time decrypt, multi-service `.env` composition, a control-VM with the age
  key). Don't cargo-cult.
- **Threat model must be explicit.** Name the attacker/scenario SOPS would defend against (data-dir read access?
  backup-artifact exfil? an accidental `git commit` of secrets? a stolen disk image?) and test each alternative
  against *that same* scenario per run-mode.
- **Standing actuation rules** (context, not this run): pseudonym commits + `Co-Authored-By` trailer; explicit
  staging (the PII dossier stays uncommitted); no agent actuates — the main thread alone verifies/commits.

## Decisions already locked (context the agents treat as fixed)

- netcanon handles **device credentials** (SSH passwords + enable/`secret`) and a prior remediation already
  landed: `DeviceProfilePublic` is WRITE-ONLY (creds scrubbed from API reads) + server-side backup-credential
  resolution (the #53–#65 review era). Backup **artifacts themselves** (the fetched device configs) routinely
  contain secrets (hashed/encrypted passwords, SNMP/RADIUS keys).
- Run modes that all must keep working: **PySide6 desktop shell**, **FastAPI/uvicorn server**, **Docker image**,
  **Windows MSI**. The decryption-key-availability story differs per mode and is the load-bearing design
  constraint.
- **Kontroll** (`~/Desktop/kontroll`) uses SOPS: encrypted
  `instance/secrets/*.sops.yml`, a `.sops.yaml` ruleset, decrypt-by-name via `ansible/filter_plugins/
  kontroll_sops.py` + `kontroll_token.py`, render-time `.env` composition (`scripts/gen-secret-env.py`,
  `ansible/playbooks/deploy-stack.yml`), and a recent `docs/reviews/2026-06-17-secret-injection/` design review.
  This whole evaluation was triggered while wiring a PVE/scratch-VM workflow into netcanon the way Kontroll does
  it — Kontroll keeps its PVE token in SOPS; the question is whether netcanon should follow suit for its secrets.
- This is **independent of** the scratch-VM/PVE-token handling for the dogfood lab (that token lives in a
  gitignored `local/` regardless); this run is about netcanon's *own product* secret handling.

## File roster

| File | Phase | Author | Covers |
|---|---|---|---|
| 00-blackboard.md | seed | main thread | this protocol + mission + constraints |
| 10-research-secret-census.md | research | R1 | every secret/credential netcanon handles + how it's stored at rest TODAY (device-profile store format, backup artifacts, egress allow-list, host-key TOFU, config/env) — `file:line` |
| 11-research-kontroll-sops-precedent.md | research | R2 | how SOPS works in Kontroll (key backend, decrypt-by-name, render-time injection, ops cost from its secret-injection review); what transfers vs is Kontroll-specific |
| 12-research-runtime-deployment.md | research | R3 | how netcanon is run/deployed per mode (desktop/server/docker/MSI) + where a decryption key could live in each; Python secret-mgmt alternatives (OS keyring, age/pyage, cryptography/Fernet, pydantic SecretStr, encrypted volume) |
| 20-design-sops-integration.md | design | D1 | IF adopted: concrete SOPS integration — what's encrypted, key location per run-mode, decrypt-at-load flow, rotation, dev/test story, Docker/MSI packaging of sops+age |
| 21-design-threat-and-alternatives.md | design | D2 | explicit threat model + head-to-head of SOPS vs the lighter alternatives against that threat per run-mode; recommended best-fit |
| 30-review-adversarial.md | review | V1 | GO/NO-GO/GO-WITH-SCOPE + must-answers; steelman both sides; fact-check the census + the runtime key-colocation claim |
| 99-synthesis.md | synthesis | main thread | reconciled verdict + (if GO) buildable-now scope, or the honest NO-GO + the lighter recommendation |

## Severity tags for the reviewer

`OVER-ENGINEERING` · `THREAT-MISMATCH` · `RUNTIME-BLOCKER` (key co-locates → no real protection in that mode) ·
`VIABLE` (a use case that genuinely holds) · `POLISH`.
