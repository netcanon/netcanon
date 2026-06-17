# 21 — Threat Model + Alternatives Bake-Off (SOPS for netcanon)

**Author:** D2 (design) · **Run:** 2026-06-17 SOPS evaluation · **Status:** design report, read-only.
**Inputs:** R1 census (`10-research-secret-census.md`), R2 Kontroll precedent (`11-research-kontroll-sops-precedent.md`),
R3 runtime/deploy (`12-research-runtime-deployment.md`). D1's SOPS integration design (`20-design-sops-integration.md`)
had not landed when this was written; I verified the load-bearing source facts myself (cites below) rather than rely on it.

---

## 0. Bottom line up front (the one thing synthesis needs)

**What threat are we actually buying down?** Exactly one: **T4 — an *offline* copy of the data directory (stolen
disk image, leaked Docker `data/` volume tarball, copied `%APPDATA%` folder) read on a *different* machine that
lacks the host's key material.** netcanon **already buys this down today** for device credentials via Fernet, and
buys it down again — for the whole data dir including the plaintext backup configs and the `.fernet_key` itself —
via the OS-level encrypted volume that ships on by default on the Windows desktop target (BitLocker on Win 11).

**Is SOPS the most cost-appropriate tool for it?** **No.** SOPS's entire security value is *decryptor ≠
ciphertext-host* (R2 §5.1). That property is **structurally unavailable in every netcanon run-mode** — the process
that decrypts, the key, and the ciphertext all sit on one machine under one OS user (R3 §3). So SOPS would re-buy
the *same* T4 mitigation Fernet already provides, while adding a `sops`+`age`/`gpg` binary to the pure-Python
Docker image and MSI, and a key-management burden onto a single-user desktop that will never own an `age` key.

**Recommendation: NO-GO on SOPS.** The single best-fit is **"do nothing new in the app code; harden the docs +
default posture"** — specifically (a) document/encourage Tier-1 (`NETCANON_FERNET_KEY`) + an encrypted volume for
server/Docker operators, and (b) optionally close the one genuine *residual* gap (the plaintext **backup
artifacts** in `configs/`, which Fernet does not reach) — but even that gap is best closed by the encrypted-volume
/ ops layer, **not** by SOPS. Full reasoning + matrices below. Severity tags for V1: **`THREAT-MISMATCH`** +
**`OVER-ENGINEERING`** on any SOPS adoption; **`RUNTIME-BLOCKER`** on the premise that SOPS protects a running
netcanon instance.

---

## 1. The threat model (explicit attacker × asset × run-mode)

### 1.1 Assets at risk (from R1's census)

| Asset | At-rest format today | Cite |
|---|---|---|
| A1 — Device SSH/enable credentials | **Fernet ciphertext** in `devices/*.json` (+ legacy `schedules/*.json`) | `device_profile_store.py:64-67`, `credentials.py:227-233` |
| A2 — The Fernet master key | **Plaintext** `.fernet_key` (Tier 3 only); off-disk in Tier 1/2 | `credentials.py:117-153,192-211` |
| A3 — Backup artifacts (fetched device configs) | **Plaintext, verbatim** in `configs/**` — contain device `$9$`/type-7/`$6$` hashes, SNMP/RADIUS/IKE keys | `backup_runner.py:233-241`, `file_store.py:1-3` |
| A4 — Job history / sidecars / known_hosts | Plaintext, **no confidential payload** (hosts/IPs + public keys only) | `models/backup.py:61-117`, `hostkey.py:41-90` |

A4 is out of scope for any confidentiality scheme (it holds no secret). The real candidates are **A1 (small,
already encrypted)** and **A3 (large, plaintext, the product stores it raw on purpose)**.

### 1.2 The candidate threats (the seed's T1–T6, made precise)

| ID | Attacker / scenario | What they get access to | Realistic for netcanon? |
|---|---|---|---|
| **T1** | A **non-root local user** on the same host reads the data dir | Filesystem read of `data_dir` *while the host is live*, but **without** the owning user's session/keyring/env | Server/Docker: plausible on a shared box. Desktop: only if OS file ACLs are wrong (they aren't — `%APPDATA%` is per-user). |
| **T2** | **Backup-artifact exfil** — someone copies `configs/**` off the box | The plaintext device configs (A3) | **The most realistic high-value leak.** A3 is plaintext and bulky; the device secrets inside are the payload. |
| **T3** | **Accidental `git commit` / `git add -A`** of the data dir or a secrets file | Whatever lands in the repo + is pushed | Low — `.gitignore` already excludes `devices/`,`schedules/`,`jobs/`,`configs/`,`.fernet_key`,`**/.fernet_key` (`.gitignore:18-28`). |
| **T4** | **Stolen disk image / offline backup** of the host, read on another machine | A cold copy of the whole data dir + `.fernet_key` *if Tier 3*; **no** live keyring/env | **The canonical at-rest threat.** Stolen laptop, leaked volume tarball, offsite backup tape. |
| **T5** | **Shared / multi-tenant host** — another tenant or admin reads the data | Filesystem read as a *different principal* on the same live host | Server/Docker only; the desktop/MSI is explicitly single-user loopback-only (`AGENTS.md:108-109`). |
| **T6** | **Secret in a process-memory dump** of the running app | Live RSS of the netcanon process (RCE, core dump, `/proc/<pid>/mem`, hibernation file) | Possible wherever the app runs; **inherent** to any decrypt-at-runtime design. |

Two extra scenarios worth naming because they reframe the verdict:

- **T2′ — exfil of `configs/` specifically** is a *subset of T2* but matters on its own because A3 is the **only**
  asset Fernet does **not** cover. Any "should we encrypt more at rest" conversation is really about A3.
- **T-net — a network attacker hitting the exposed `0.0.0.0:8000` API** is an **authn/authz** problem, not an
  encryption one (`SECURITY.md:499-500` concedes there is no API auth — operators add a reverse proxy). No at-rest
  scheme touches it; listed only to keep it out of scope cleanly.

### 1.3 The load-bearing fact: key co-location per run-mode (verified, not assumed)

R3 §3 establishes — and I re-confirmed against source — that in **every default zero-config run-mode the
decryption key is reachable on the same host the app runs on**, and the running app must hold the plaintext key in
memory regardless:

| Run-mode | Default winning key tier | Key on the data disk? | Key reachable by a live-host attacker who is the owning user? |
|---|---|---|---|
| (a) Desktop / (d) MSI | Tier 2 — OS keyring (DPAPI) | No (OS store, **user-scoped**) | Yes (DPAPI unseals for the owning account) |
| (b) Server | Tier 1 (env) **or** Tier 3 (file) | Tier 3 **YES** (`.fernet_key` beside `devices/`) ; Tier 1 No | Yes (env via `/proc/<pid>/environ`; file via FS read) |
| (c) Docker | Tier 1 (recommended) **or** Tier 3 | Tier 3 **YES** (in the bind-mounted volume) ; Tier 1 No | Yes |

Source: `credentials.py:70-79` (`_data_dir()` = `NETCANON_DATA_DIR`/`./data`), `:192-211` (Tier-3 writes
`.fernet_key` into that dir), `:163-167` (Tier-1 env), `:169-190` (Tier-2 keyring). Confirmed first-hand this run.

**The consequence (the spine of the whole verdict):** because the key is co-resident with the ciphertext on a live
host, **at-rest encryption can only ever defend a threat where the attacker has the *ciphertext on a different /
offline machine without the key* — i.e. T4 (and the T3 git-leak, since the committed bytes are ciphertext, and
the keyring/env/`.fernet_key` are gitignored or off-disk).** It can do **nothing** for an attacker who is on the
live host as the owning user (T1-as-owner, T5-as-same-principal, T6), because that attacker can read the key the
same way the app does. This is **equally true of Fernet and of SOPS** — SOPS does not change the ceiling.

---

## 2. Threat × SOPS, per run-mode (ruthless: does the key-colocation reality defeat it?)

For each threat I ask the seed's exact question: *given that the SOPS key would sit beside the ciphertext on a
running host (or in the keyring / env exactly where the Fernet key already sits), is the threat mitigated?*

| Threat | (a)/(d) Desktop/MSI | (b) Server | (c) Docker | Net SOPS verdict |
|---|---|---|---|---|
| **T1** local non-root user, no owning session | Partial — but **only if** the SOPS `age` key is itself protected by OS ACL/keyring, which is exactly what DPAPI+Fernet already do. SOPS adds nothing. | **No** — Tier-3-equivalent: the `age` key would sit in `data_dir` (or be env-injected = Tier 1). A non-owning local user with FS read either can't read the key (then Fernet already stopped them) or can (then SOPS doesn't either). | **No** (same as server) | **No gain over Fernet** |
| **T2 / T2′** backup-artifact exfil (`configs/`) | **No** — A3 is plaintext; SOPS-on-`devices/*.json` never touches `configs/`. SOPS would have to *additionally* wrap every backup write (a bulk, high-volume re-encrypt on every collect) — and then the `age` key co-locates anyway on a live box. | **No** (same) | **No** (same) | **No** — wrong asset, and key co-locates even if extended |
| **T3** accidental `git commit` | Already mitigated by `.gitignore` (ciphertext + gitignore). SOPS-committed-to-git is the *Kontroll* model netcanon's posture explicitly forbids ("never commit secrets", `AGENTS.md:249`). | same | same | **No gain** — `.gitignore`+Fernet already cover it; SOPS-in-git is anti-pattern here |
| **T4** stolen disk / offline backup | **Yes** — but Fernet+keyring already gives this (DPAPI-sealed key isn't in the offline copy), and BitLocker gives it for the *whole* volume for free. | **Yes iff** the `age` key is off-host (env-injected) — which is **identical to Fernet Tier 1**. If the `age` key is in `data_dir` (the zero-config shape), **No** — it's in the stolen image. | **Yes iff** env-injected `age` key (= Tier 1); else **No** (key in the volume tarball) | **No gain over Fernet Tier 1 / encrypted volume** |
| **T5** shared / multi-tenant host | n/a (single-user platform) | **No** — a co-tenant reading the live FS gets whatever the FS ACL allows; if the `age` key is FS-readable they decrypt, if not Fernet already stopped them. Same-principal/admin defeats everything. | **No** (same) | **No** |
| **T6** process-memory dump | **No** — the decrypted creds + the `age`/Fernet key are in RSS by definition. | **No** | **No** | **No** — out of scope for any at-rest scheme |

**Reading the row that matters (T4):** SOPS *does* mitigate T4 — but **only in the exact configuration where the
key is off-host**, which is *byte-for-byte the posture netcanon's existing `NETCANON_FERNET_KEY` env tier already
delivers* (R3 §3(b)/(c)). In the zero-config configuration (Tier-3-equivalent: `age` key written into `data_dir`),
SOPS faces the **same co-location defeat** the seed warns about — the key is in the stolen image. So SOPS's only
"win" is a win Fernet already owns, and SOPS's only "loss" mode is the same loss Fernet's Tier 3 has. **SOPS is a
lateral move on the one threat at-rest encryption can address, with strictly higher operational cost.**

---

## 3. The alternatives bake-off (same threats, same modes)

R3 surveyed six options; three are **already shipped** in netcanon. I score each against T1–T6, then give the
per-mode fit. The baseline every option must *beat* is the existing Fernet 3-tier scheme — not a plaintext
strawman.

### 3.1 Option roster

| # | Option | Status in netcanon | Key lives where |
|---|---|---|---|
| O1 | **SOPS + age** (Kontroll model) | Not present | `age` identity file on host, OR env-injected (= Tier 1) |
| O2 | **OS keyring** (`keyring` lib, DPAPI/Keychain/SecretService) | ✅ shipped (Tier 2) | OS secret store, user-scoped, off the data disk |
| O3 | **App-level age/Fernet, key from OS keychain or operator passphrase** | ✅ Fernet shipped (Tier 1/2/3); passphrase-KDF not | 3-tier (env/keyring/file) today; KDF variant = nowhere-on-disk |
| O4 | **"Never persist device creds — resolve at backup-time from an operator-entered value"** | **Partially mischaracterised — see §3.3** | n/a (no stored secret) |
| O5 | **OS-level encrypted volume** (BitLocker / LUKS / FileVault) | Not app-managed (often already on, Win 11) | OS/TPM, block layer, below the app |
| O6 | **Document-only** (status quo + operator guidance) | The honest baseline | Whatever the operator already runs |

### 3.2 Threat × option matrix (mitigates / partial / no)

Scored for the **realistic default configuration** of each option, with the per-mode caveats in the footnotes.
"mitigates" = closes the threat in the common case; "partial" = closes it only under a specific config or only
for one asset class; "no" = does not address it.

| Option | T1 local user | T2/T2′ config exfil | T3 git commit | T4 stolen/offline | T5 multi-tenant | T6 memory dump |
|---|---|---|---|---|---|---|
| **O1 SOPS+age** | no¹ | no² | no³ | partial⁴ | no | no |
| **O2 OS keyring** ✅ | partial⁵ | no² | mitigates⁶ | mitigates⁷ | partial⁵ | no |
| **O3 Fernet 3-tier** ✅ | partial⁵ | no² | mitigates⁶ | mitigates⁷ | partial⁵ | no |
| **O3-KDF passphrase** | partial⁵ | no² | mitigates⁶ | **mitigates**⁸ | partial⁵ | no |
| **O4 never-persist creds** | mitigates⁹ | **no**² | mitigates⁹ | mitigates⁹ | mitigates⁹ | partial¹⁰ |
| **O5 encrypted volume** | no¹¹ | **mitigates**¹² | partial¹³ | **mitigates**¹² | no¹¹ | no |
| **O6 document-only** | = whatever O2/O3/O5 the operator runs | — | — | — | — | — |

**Footnotes (the load-bearing caveats):**

1. **O1/T1:** the `age` key sits on the same FS as the ciphertext (or in the keyring = O2, or env = O3-Tier1).
   A non-owning local user either can read the key (no mitigation) or can't (O2/O3 already stopped them). SOPS
   adds nothing.
2. **·/T2:** **no option in this column except O5 touches A3 (the plaintext `configs/` backups)**, because A1's
   credential encryption is a *different asset*. O1–O4 all leave `configs/**` in cleartext. This is the single
   most important cell in the matrix: **the biggest realistic leak (T2 backup-artifact exfil) is unaddressed by
   every secret-management option — only the volume-level O5 covers it.**
3. **O1/T3:** SOPS *committed to git* is the Kontroll pattern; netcanon's Hard Rule is "never commit secrets"
   (`AGENTS.md:249`) and `.gitignore` already excludes the data dir. SOPS-in-git would *introduce* a commit path,
   not close one.
4. **O1/T4:** mitigates **only** when the `age` key is off-host (env-injected) — which is identical to O3 Tier 1.
   In the zero-config (key-in-`data_dir`) shape it does **not** mitigate T4 (key is in the stolen image).
5. **O2/O3/T1,T5:** "partial" = mitigates against a **different** principal who can't unseal the keyring / read
   the env / read the user-scoped key file, but **not** against the owning user or a root/admin co-tenant.
   DPAPI binds the secret to the Windows account, so a non-owning local user can't decrypt — genuine partial win.
6. **·/T3:** the persisted creds are **ciphertext**, and `devices/`,`schedules/`,`.fernet_key` are all gitignored
   (`.gitignore:18-28`) — double-covered.
7. **O2/O3/T4:** mitigates because the offline copy lacks the keyring secret (DPAPI, host-bound) or the env value;
   the `.fernet_key` is in the image **only** in Tier 3 (then it's NOT mitigated — see O3 row reality).
8. **O3-KDF/T4:** **strongest** at-rest story — the key is never on disk in any tier; derived per-boot from a human
   passphrase. Defeats the offline copy even versus Tier-3 leakage. Cost: breaks unattended `docker run -d` /
   scheduler restart (R3 §5.5).
9. **O4/T1,T3,T4,T5:** if creds are **never persisted**, there is no stored A1 secret to leak in any of those
   scenarios — strictly dominant *for A1*. **But see §3.3 — this changes the product, and does nothing for A3.**
10. **O4/T6:** the cred is still in memory *during* the backup run; the window is narrower (only while a job runs)
    but non-zero.
11. **O5/T1,T5:** the volume is **unlocked while mounted** on the live host — a local user / co-tenant with FS
    access reads plaintext. Encrypted volume defends offline, not live.
12. **O5/T2,T4:** **covers the entire data dir including `configs/` and `.fernet_key`** at the block layer, with
    zero app code. This is the only option that mitigates T2 (config exfil) for an offline/stolen-disk attacker.
13. **O5/T3:** partial — a file copied *off* the encrypted volume into a git repo is plaintext again; but
    `.gitignore` + Fernet already cover the credential file specifically.

### 3.3 Special handling: O4 "never persist creds" vs the #53–#65 work (what already exists)

The seed asks how far the #53–#65 remediation already moved toward "never persist; resolve at backup-time." I
verified the actual code path:

- `DeviceProfilePublic` is **WRITE-ONLY** — creds are scrubbed from API *reads* (seed `00-blackboard.md:44-45`).
- Server-side resolution: `backups._resolve_credentials` takes the **already-persisted, already-decrypted**
  profile password and re-wraps it as `SecretStr` for transport to the collector
  (`backups.py:114-137`, esp. `:128-136`). Confirmed first-hand this run.

**So the #53–#65 work did NOT make creds ephemeral.** Creds are still **persisted** (Fernet-encrypted in
`devices/*.json`) so unattended/scheduled backups can run without a human. "Server-side resolution" means *the API
never echoes creds back to the client*, **not** *the server never stores them*. The move was a **read-path /
egress** hardening (no cred leakage through the public API), not an at-rest-persistence change.

Going **fully** O4 (never store; prompt the operator per backup) would:

- **Eliminate A1 at rest entirely** — the strongest possible answer for T1/T3/T4/T5 *on the credential asset*.
- **Break the core product** — netcanon's whole value is **unattended scheduled backups** (the scheduler,
  `main.py:163-204`; new-style schedules reference `device_profile_id`s precisely so they can run headless,
  `schedule_store.py:9-13`). A per-run human prompt is incompatible with `docker run -d`, systemd, k8s, and the
  desktop tray's background scheduling. This is a **product-shape change, not a security tweak.**
- **Do nothing for A3** — the backup *artifacts* still land in plaintext `configs/`. T2 is untouched.

Verdict on O4: **right idea, wrong product.** It's the cleanest theoretical answer for the credential asset but
collides head-on with the unattended-backup design that is netcanon's reason to exist. Worth noting in the
synthesis as the "if we were greenfield and didn't need scheduling" option — not actionable here.

### 3.4 Per-mode fit summary (which option wins where)

| Mode | Best-fit option(s) | Why | SOPS realistic? |
|---|---|---|---|
| (a) Desktop / (d) MSI | **O2 keyring (have it) + O5 BitLocker (often already on)** | DPAPI manages the key for free; BitLocker covers the whole `%APPDATA%` offline. Zero operator action. | **No** — a network engineer running an MSI will not generate/rotate an `age` key; no per-install key home (R3 §3(d)). |
| (b) Server | **O3 Tier-1 env (have it) + O5 LUKS** | Env-injected key = off-host (the only real T4 win); LUKS covers `configs/` + the rest. | Redundant with Tier 1; adds binary deps for no new threat coverage. |
| (c) Docker | **O3 Tier-1 `-e NETCANON_FERNET_KEY` (have it) + encrypted PV/EBS** | Orchestrator secret → env is the documented path (`README.md:100-104`, `.env.example:41-44`); encrypted volume covers the bind-mount. | **No** — re-introduces `sops`+`age`/`gpg` into a pure-Python slim image (`Dockerfile:48-63`) + an age-key-mount problem that recreates co-location. |

---

## 4. The recommendation

### 4.1 Verdict: **NO-GO on SOPS.** Best-fit = **document-only (O6) + push T2 to the encrypted-volume / ops layer (O5)**

The deliverable the synthesis asked for — *what threat are we buying down, and is SOPS the most cost-appropriate
tool* — resolves cleanly:

1. **The only threat at-rest encryption can address here is T4 (offline-disk / exfil-copy).** Every live-host
   threat (T1-as-owner, T5-same-principal, T6) is defeated by key co-location, identically for Fernet and SOPS
   (R2 §5.1, R3 §3). This is a hard ceiling, not a tuning knob.

2. **netcanon already buys down T4** for the credential asset (Fernet + DPAPI keyring / env Tier 1, test-guarded
   at `tests/unit/test_device_profile_store.py:124-133`), and the Windows desktop target buys it down for the
   *entire* data dir for free via BitLocker.

3. **SOPS re-buys the *same* T4 mitigation** that `NETCANON_FERNET_KEY` already provides, while:
   - adding a `sops`+`age`/`gpg` binary to the pure-Python Docker image and the unsigned MSI (R3 §3(c)/(d)),
   - imposing an `age`-key-management burden on a single-user desktop that will never own one (R3 §3(a)),
   - recreating the **exact** co-location defeat in the zero-config mode (the `age` key lands in `data_dir`), and
   - pushing toward a *commit-secrets-to-git* posture that netcanon's Hard Rules forbid (`AGENTS.md:249`).
   The same operator's **own Kontroll SECURITY.md** classifies a *"frozen, local"* repo as **"plaintext
   accepted,"** reserving mandatory encryption for the *networked control plane* (R2 §1, `kontroll/SECURITY.md:20-21`)
   — precedent *against* porting SOPS here, written by the same hand.

4. **The biggest *real* exposure is T2 — the plaintext backup artifacts in `configs/`** (A3), which no
   secret-management option (O1–O4) touches, because they encrypt a *different* asset (A1). The cost-appropriate
   mitigation for T2 is the **encrypted volume (O5)** + the existing on-demand sanitiser for *sharing* — not SOPS.

### 4.2 Concrete buildable-now actions (all docs / posture, **no app code, no new deps**)

These are the right-sized actions the synthesis can green-light. None require SOPS.

1. **Doc the Tier-1 + encrypted-volume posture as the recommended server/Docker default.** Most of this prose
   already exists (`SECURITY.md:80-161`, `README.md:94-121`, `.env.example:32-52`); the gap is an explicit
   "for confidential-at-rest, set `NETCANON_FERNET_KEY` from an orchestrator secret **and** run on an encrypted
   volume — that covers your `configs/` too" paragraph that names T2/T4 in operator language.
2. **Name the `configs/`-is-plaintext fact in SECURITY.md as a known, deliberate posture** with the encrypted-volume
   recommendation, so it's an honest documented decision, not a silent gap (matrix-honesty discipline,
   `AGENTS.md`). R1 §5 establishes the fact; SECURITY.md should state it.
3. *(Optional, lowest priority)* **`POLISH`:** the Tier-3 `.fernet_key` path uses `NETCANON_DATA_DIR` directly,
   not `Settings.effective_data_dir` (`credentials.py:79` vs `config.py:116-128`) — a latent desktop inconsistency
   R3 §2 flagged. Not security-load-bearing (desktop never hits Tier 3); note for a future cleanup, not this run.

### 4.3 What would change the verdict (the honest "GO" preconditions)

For completeness, SOPS would become the right tool **iff** netcanon grew a property it does not have:

- a **second machine** that holds the key but not the ciphertext (a control-plane / render-node split), **or**
- a requirement to **commit encrypted secrets to a repo** (GitOps), **or**
- **multiple distinct principals** at different trust levels needing scoped decrypt (Kontroll's Semaphore-runner case).

None of these exist in a local-first single app. Until one does, SOPS is `THREAT-MISMATCH` + `OVER-ENGINEERING`.

---

## 5. Hand-off notes for V1 (review) and the synthesis

- **Fact-check anchors I re-verified this run** (not just inherited from R1/R3): Tier-3 key co-location
  (`credentials.py:70-79,192-211`); `.gitignore` already excludes the data dir + both `.fernet_key` forms
  (`.gitignore:18-28`) → T3 is *already* closed, which weakens any "SOPS prevents accidental commits" argument;
  server-side cred resolution re-wraps **persisted** plaintext, so the #53–#65 work is **not** a "never-persist"
  move (`backups.py:114-137`).
- **The one cell V1 should pressure-test:** O5/T2 ("encrypted volume covers `configs/`"). It's the strongest claim
  in the matrix and the basis for not doing anything app-side about A3. It holds for *offline* T2 (stolen disk),
  but **not** for a live-host copy or an operator who deliberately `scp`s a config out — that's the on-demand
  sanitiser's job, and it's bug-reporting-only, not a general redaction. V1 should confirm the synthesis doesn't
  over-claim O5 as covering *all* of T2.
- **Steelman of the GO side, for honesty:** the genuine sliver is that **Tier 3** (zero-config Docker) *does* leave
  the key in the volume, so a leaked tarball is fully decryptable — a real T4 hole. But the fix is "tell operators
  to set Tier 1 / use an encrypted volume" (already documented, `README.md:118-121` even warns about it), not
  "adopt SOPS" — because a SOPS `age` key in the same zero-config container lands in the same volume. The hole is
  *operator config*, not *missing tooling*.
- **Severity tags:** `THREAT-MISMATCH` + `OVER-ENGINEERING` for SOPS adoption; `RUNTIME-BLOCKER` for "SOPS protects
  a running instance"; `VIABLE` for the document-only + encrypted-volume recommendation; `POLISH` for the
  `_data_dir()` vs `effective_data_dir` inconsistency.

---

*Verified against source this run: `netcanon/security/credentials.py:60-219` (3-tier resolve, `_data_dir`,
Windows-chmod-no-op caveat), `.gitignore:1-98` (data-dir + `.fernet_key` exclusions), `netcanon/api/routes/backups.py:110-154`
(server-side cred resolution re-wrapping persisted plaintext). All other cites inherited from R1/R2/R3 reports,
which themselves cite `file:line`.*
