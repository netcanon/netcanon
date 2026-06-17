# 99 — Synthesis: Should netcanon adopt SOPS? (2026-06-17)

**Author:** main thread (orchestrator). **Inputs:** R1 census (`10-`), R2 Kontroll precedent (`11-`),
R3 runtime/deploy (`12-`), D1 SOPS integration (`20-`), D2 threat+alternatives (`21-`), V1 adversarial
review (`30-`). This run was **read-only research/design** — no app code was written or proposed for build.

## Verdict: **NO-GO on adopting SOPS as a netcanon feature.**

Unanimous across all six agents; the adversarial reviewer re-opened the source itself and **both load-bearing
claims held**, so the recommendation does not flip. SOPS is `THREAT-MISMATCH` + `OVER-ENGINEERING` for netcanon
as it exists today.

## Why (the two facts the whole decision hangs on, verified against source)

1. **netcanon already encrypts device credentials at rest.** `devices/*.json` store the two password fields as
   real **Fernet** ciphertext (`device_profile_store.py:64-67` → `credentials.py:227-233`; AES-128-CBC + HMAC,
   not encoding), test-guarded (`tests/unit/test_device_profile_store.py:124-133`). The key resolves 3-tier:
   **Tier 1** `NETCANON_FERNET_KEY` env (off-host), **Tier 2** OS keyring / Windows DPAPI (off-disk, the desktop
   default), **Tier 3** file fallback `$NETCANON_DATA_DIR/.fernet_key` (plaintext, zero-config Docker). `SecretStr`
   is in-memory masking only — it never reaches disk. **The thing SOPS would "add" is already shipped.**

2. **SOPS's one value prop is structurally unavailable here.** SOPS exists to make *the decryptor ≠ the
   ciphertext host* (key on a control VM / committed-ciphertext GitOps). Every netcanon run-mode —
   desktop / server / docker / MSI — co-locates the process, the key, and the ciphertext on **one machine, one
   user** (`credentials.py:70-79,163-211`; `Dockerfile:80,94` puts `.fernet_key` in the same bind-mounted volume
   as `devices/`). So at-rest encryption can only ever defend the **offline/exfil** threat (stolen disk, leaked
   volume tarball) — and on *that* threat SOPS merely re-buys what Fernet Tier-1/keyring + an OS-encrypted volume
   already deliver, while adding `sops`+`age` binaries to a pure-Python-slim image, an unsigned-MSI AV surface
   **with no key home at all**, and a commit-secrets-to-git posture the project's Hard Rules forbid
   (`AGENTS.md:249`).

**Precedent against, by the same hand:** Kontroll's own `SECURITY.md:20-21` classifies a *"frozen, local"* repo
as **"plaintext accepted,"** reserving mandatory encryption for the *networked control plane*. netcanon's
gitignored single-host data dir is the former; Kontroll's multi-service, control-VM-custody, render-time-`.env`,
multi-principal SOPS model answers questions netcanon doesn't pose (R2 transferability verdict: does **not**
transfer).

## The run's real ROI (the finding worth more than the SOPS answer)

The largest **plaintext** secret surface isn't the credentials (those are encrypted) — it's the **backup
artifacts**: fetched device configs are written verbatim to `configs/**` (`backup_runner.py:233-241`) and
routinely contain `$9$`/type-7/`$6$` hashes + SNMP/RADIUS/IKE keys. Nothing encrypts or redacts them at rest, the
on-demand sanitiser is bug-reporting-only (never on the backup-write path), and **SECURITY.md does not state this
as a deliberate posture.** That silent gap — not SOPS — is the actionable output of this run.

## Resolution of the reviewer's must-answer questions

| Q | Resolution |
|---|---|
| **Q1** NO-GO vs narrow-scope? | **NO-GO** on SOPS-in-product. The only non-rejected sliver (an operator-side `sops -d → export NETCANON_FERNET_KEY → exec` launch recipe) is redundant with the k8s/Compose/systemd env delivery already documented → demote to **at most one README sentence**, not a feature. |
| **Q2** Ship the `configs/` honesty paragraph now? | **Recommend YES as a small follow-up PR** (docs-only) — it's the run's ROI. Proposed, not yet built; awaiting go-ahead (see Buildable-now). |
| **Q3** Does "encrypted volume covers `configs/`" over-claim? | Yes if stated flatly. O5 (BitLocker/LUKS) covers **offline** T2 only (stolen disk / leaked tarball). It does **not** defend a live-host read or a deliberate `scp`-out. The SECURITY.md prose must state that ceiling. |
| **Q4** Is the Tier-3 zero-config hole steered against? | `README.md:118-121` already warns; the docs pass should make it explicit that zero-config Docker leaves `.fernet_key` in the data volume → **set Tier-1 or use an encrypted volume.** Fix is operator config, not tooling (a SOPS `age` key would land in the same volume). |
| **Q5** Doc-sync fan-out for a SECURITY.md edit? | SECURITY.md is the primary surface; cross-check README install section + `.env.example` comments for a one-line pointer. No code/IDENTITY/packaging doc implicated. |
| **Q6** Test re-run warranted? | **No** — docs-only, touches no code/fixtures. |

## Buildable-now contract (if/when greenlit — all docs/posture, NO app code, NO new deps)

1. **SECURITY.md: name the plaintext-`configs/` posture** as a deliberate, documented decision, with the
   encrypted-volume recommendation and O5's honest ceiling (offline-only; sanitiser is for *sharing*).
2. **SECURITY.md / README: recommend Tier-1 + encrypted volume as the server/Docker confidential-at-rest default**,
   naming the offline-disk / volume-exfil threats in operator language; make the zero-config Tier-3 `.fernet_key`
   warning explicit.
3. **(Optional) Preventive non-fit note** (mirrors `AGENTS.md` "Deliberately omitted" pattern): "SOPS is an
   operator-side delivery option for Tier 1, not a netcanon feature; desktop/MSI use the OS keyring (DPAPI) and
   have no per-install key home" — stops the next contributor re-litigating.
4. **(Deferred POLISH, not this work)** align `credentials._data_dir()` with `Settings.effective_data_dir`
   (`credentials.py:79` vs `config.py:116-128`) so a desktop Tier-3 fallback lands in `%APPDATA%\Netcanon`, not
   `<cwd>/data`. Not security-load-bearing (desktop never hits Tier 3).

This dossier is the frozen evidence trail (EXPECTED-STALE; a future audit must not flag it as drift). The
SECURITY.md follow-up, if taken, is its own behaviour-preserving docs PR under the standing actuation rules.
