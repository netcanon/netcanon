# 30 — Adversarial GO/NO-GO Review: SOPS for netcanon

**Author:** V1 (review, read-only) · **Run:** 2026-06-17 SOPS evaluation · **Status:** adversarial review.
**Inputs read in full:** R1 census (`10-…`), R2 Kontroll precedent (`11-…`), R3 runtime/deploy (`12-…`),
D1 SOPS integration (`20-…`), D2 threat + alternatives (`21-…`). **Re-verified against source this run** (not
inherited): `credentials.py` (full), `device_profile_store.py` (full), `models/device_profile.py:1-70`,
`.gitignore:1-98`, `backup_runner.py:225-249`, `api/routes/backups.py:108-138`, `Dockerfile` (grep on
data-dir/volume/apt). Both load-bearing claims the seed asked me to fact-check are **CONFIRMED true**.

---

## 0. One-line verdict

**NO-GO on adopting SOPS as a netcanon feature.** The recommendation does **not** flip, because the two
load-bearing claims that drive it both check out against source. The honest right-sized answer is: **do nothing
new in app code; ship a small docs/posture hardening pass instead** — name the `configs/`-is-plaintext fact in
SECURITY.md, point operators at Tier-1 (`NETCANON_FERNET_KEY`) + an OS-encrypted volume, and (optionally) add a
one-paragraph "SOPS is an operator-side delivery option for Tier 1, not a netcanon feature" note so a future
contributor doesn't speculatively wire it in. **The lighter thing to do instead of SOPS is: (1) a SECURITY.md
honesty paragraph about `configs/` + encrypted-volume guidance, and (2) keep the existing 3-tier Fernet scheme.**

If the synthesis wants to leave a door open, the *only* non-rejected scope is D1's variant C (a docs-only
launch-wrapper recipe, server/Docker, zero code, zero packaging) — and even that is dominated by delivery options
netcanon already documents, so it is at most a `GO-WITH-NARROW-SCOPE` for a README paragraph, never a build.

---

## 1. Fact-check of the two load-bearing claims (I opened the files myself)

The seed (`00-blackboard.md:70`) tasks V1 with verifying the two facts the whole verdict hangs on, because "if
either claim is wrong, the recommendation flips." I did not trust R1/R3/D2; I re-read the source.

### 1.1 Claim (a) — R1's at-rest-format claim: is the device-credential store plaintext / encoded / encrypted?

**R1's claim (`10-…:52-75`):** device login credentials are **Fernet-encrypted** at rest inside an
otherwise-plaintext JSON file; `SecretStr` is in-memory masking only and contributes nothing at rest.

**VERDICT: CONFIRMED — genuinely encrypted at rest (not merely encoded/obfuscated), with one subtlety worth
stating precisely.**

| Sub-claim | Source I read | Finding |
|---|---|---|
| Persisted creds are plaintext `str` *in memory* | `models/device_profile.py:34,59-60` | TRUE. `password: str`, `enable_password: str \| None`; docstring line 34 reads literally "plaintext in memory; encrypted on disk". |
| Only the two password fields are encrypted on write | `device_profile_store.py:64-67` | TRUE. `data = json.loads(model_dump_json())`, then `data["password"] = encrypt(profile.password)` and (conditionally) `data["enable_password"] = encrypt(...)`. Everything else (`id`, `name`, `host`, `port`, `username`, `notes`, `detected_facts`, …) is written as **plaintext JSON**. |
| `encrypt()` is real Fernet, not base64/obfuscation | `credentials.py:227-233` | TRUE. `_get_fernet().encrypt(plaintext.encode()).decode()` — Fernet is AES-128-CBC + HMAC-SHA256 with a random IV, an authenticated token (`gAAAAA…`). This is **encryption**, not encoding. |
| Decrypt-on-load + legacy-plaintext migration | `device_profile_store.py:86-125`, `credentials.py:246-263` | TRUE. `migrate_credential_fields` → `decrypt_field`; a value that fails `InvalidToken` is treated as legacy plaintext and re-saved encrypted. |
| `SecretStr` is in-memory hygiene only | `device_profile.py:59-60` (plain `str`, NOT `SecretStr`); re-wrap at `backups.py:128-136` | TRUE. The persisted model uses plain `str`; the transport model re-wraps into `SecretStr` only on the way to the collector. `SecretStr` never reaches disk and adds **zero** at-rest protection. |

**Why this matters for the verdict:** R1's framing — "device-credential *encryption* is already solved; the real
unencrypted surface is `configs/`" — is factually correct. If the store had been plaintext (the strawman the seed
warns against), the SOPS case would be far stronger. It is not. The credential asset is already encrypted with a
test-guarded scheme (`tests/unit/test_device_profile_store.py:124-133` per R1 — I did not re-open that test but
the code path is unambiguous). **Claim (a) holds → the verdict does not flip on it.**

One nuance the synthesis should keep crisp: "encrypted at rest" is only as strong as where the key lives — which
is exactly claim (b).

### 1.2 Claim (b) — R3/D2's key-colocation claim: does the decryption key co-locate with the ciphertext per run-mode?

**R3/D2's claim (`12-…:21-29`, `21-…:67-87`):** in **every default zero-config run-mode** the Fernet key is
reachable on the same host/disk as the ciphertext, so at-rest encryption only ever defends an *offline/exfil*
threat — and SOPS would inherit the identical ceiling.

**VERDICT: CONFIRMED, per tier, from source.**

| Tier | Source I read | Key location | Co-locates with ciphertext? |
|---|---|---|---|
| **1 — env var** `NETCANON_FERNET_KEY` | `credentials.py:163-167` | Process environment; "never touches disk inside the data directory" (docstring `:17-18`) | **NO** — *iff* the operator sources the value off-host. Decoupled posture, exists today. |
| **2 — OS keyring** (DPAPI/Keychain/SecretService) | `credentials.py:169-190` (`_read_keyring`/`_write_keyring` `:82-114`) | OS secret store, user-scoped | **NO** to the data disk; but **YES reachable** by the owning account on a live host (DPAPI unseals for that user). Defends an *offline copy* lacking the account, not malware-as-user. |
| **3 — file fallback** `$NETCANON_DATA_DIR/.fernet_key` | `credentials.py:70-79` (`_data_dir()`), `:117-153` (`_read/_write_key_file`), `:192-211` (Tier-3 resolve) | Plaintext 44-char base64 in the data dir | **YES** — explicitly. `_data_dir()` returns `Path(os.environ.get("NETCANON_DATA_DIR", "data"))`; `_write_key_file` writes `.fernet_key` *into that same dir*. The module's own docstring (`:25-34`) says the key is "persisted in the operator's bind-mounted data volume … plaintext on disk … the same volume the operator already chose to trust." |

**Docker confirmation (the worst case):** `Dockerfile:80` sets `NETCANON_DATA_DIR=/app/data` and `:94`
`VOLUME ["/app/configs","/app/data"]`. So in the zero-config container path (no `-e NETCANON_FERNET_KEY`), the
Tier-3 `.fernet_key` lands **inside the bind-mounted `/app/data` volume right next to `devices/*.json`** — a
single `tar` of the volume contains both ciphertext and key. The runtime image adds only `curl` (`Dockerfile:51-52`,
grep-confirmed), so it is genuinely pure-Python-slim; bundling `sops`+`age` would be a real new binary surface.

**The chmod-0600 caveat is real and in the source** (`credentials.py:147-152`): on Windows `os.chmod(0o600)` is a
no-op and the failure is *deliberately swallowed*; confidentiality there rests on the inherited NTFS user-profile
ACL. This is honestly documented in the docstring (`:130-141`) and does not change the verdict.

**Why this matters:** SOPS's entire security value (R2 §5.1) is *decryptor ≠ ciphertext-host*. Claim (b) proves
that property is **structurally unavailable** in every netcanon run-mode: the process that decrypts, the key, and
the ciphertext are one machine / one user. The *only* decoupled posture (Tier-1 env sourced off-host) is exactly
what netcanon already ships. **Claim (b) holds → the verdict does not flip on it.** The one place SOPS would help
(off-host key) is byte-for-byte the env-var tier; the one place SOPS would *not* help (zero-config) recreates the
same co-location with extra binaries. Both research conclusions are sound.

### 1.3 Two ancillary facts I spot-checked because the verdict leans on them

- **T3 "accidental git commit" is already closed.** `.gitignore:18-28` excludes `devices/`, `schedules/`,
  `jobs/`, `configs/`, **and** `.fernet_key` + `**/.fernet_key`. D2's claim that SOPS-prevents-accidental-commits
  is a non-benefit here is correct — and SOPS-in-git would *introduce* a commit path (the Kontroll model), which
  `AGENTS.md:249` ("Never commit real credentials") forbids. CONFIRMED.
- **The #53–#65 work is NOT "never-persist".** `backups.py:128-136` builds `DeviceCredentials` from
  `profile.username` / `SecretStr(profile.password)` — i.e. it re-wraps the **already-persisted, already-decrypted**
  profile password for transport. D2 §3.3's correction (server-side resolution = read-path hardening, not
  ephemerality) is CONFIRMED. This matters because it rules out O4 ("never persist creds") as a free win — creds
  must persist for unattended scheduled backups, which is netcanon's reason to exist.

**Net on fact-checking:** both load-bearing claims are true; both ancillary facts are true. There is no factual
escape hatch that flips the recommendation toward GO. The peer reports are unusually well-grounded (every cite I
re-checked landed exactly where claimed).

---

## 2. Steelman of BOTH positions (the seed's explicit ask)

I owe the synthesis the strongest honest version of each side, not a strawman of the loser.

### 2.1 Strongest case FOR adopting SOPS

The best pro-SOPS argument is **not** "encrypt the creds better" (they're already encrypted) — it's a combination
of three genuinely-true sub-points that, stacked, look compelling until you test them against co-location:

1. **The zero-config Tier-3 hole is real and embarrassing.** In the most common headless Docker path, a leaked
   `/app/data` tarball is *fully decryptable* because `.fernet_key` rides along in the same volume
   (`credentials.py:192-211` + `Dockerfile:80,94`). That is a true at-rest weakness, and "the key sits next to the
   ciphertext" is exactly the smell SOPS exists to fix. A reviewer who stopped here would say GO.
2. **Operator-estate consistency / least-astonishment.** The sibling Kontroll already standardizes on SOPS+age
   (R2 §2). An operator running both would reasonably want one secret-management idiom across their estate. SOPS
   is a real, audited, widely-deployed tool; "use the thing the org already uses" is a legitimate ops argument.
3. **`configs/` is the biggest unencrypted secret surface and nothing covers it.** R1 §5 / D2 A3 establish that the
   fetched device configs are plaintext and contain `$9$`/type-7/`$6$` hashes, SNMP/RADIUS/IKE keys. A SOPS-shaped
   "encrypt the sensitive files at rest" reflex points right at it. The honest pro side says: *netcanon stores a
   lot of secret material in cleartext on purpose, and a file-encryption tool is the obvious lever.*

**The strongest single sentence for GO:** *"There is a true zero-config at-rest hole (Tier-3 key co-location) and a
true large plaintext surface (`configs/`), the org already runs SOPS, so adopt SOPS to close both with one
familiar tool."*

### 2.2 Strongest case AGAINST (the steelman the data actually supports)

1. **SOPS's load-bearing property does not exist here, in any run-mode.** *Decryptor ≠ ciphertext-host* (R2 §5.1)
   requires a second machine or a commit-to-git GitOps split. netcanon has neither — desktop/server/docker/MSI all
   co-locate process+key+ciphertext (claim (b), confirmed). So SOPS cannot deliver the one thing it is *for*.
2. **Every "win" SOPS offers, netcanon already has cheaper.** The off-host-key posture = Tier-1 env var
   (`credentials.py:163-167`), already documented with k8s Secret / Compose `secrets:` / systemd EnvironmentFile
   delivery (`.env.example`, per R3 §3). SOPS becomes "one more delivery mechanism for an env var we already read."
3. **The Tier-3 hole is fixed by operator config, not tooling.** A SOPS `age` key in the same zero-config
   container lands in the same `/app/data` volume — recreating the identical hole (D1 U2, D2 §5 steelman). The fix
   is "set Tier 1 / use an encrypted volume," which the README *already warns about* (`README.md:118-121` per R3).
4. **`configs/` is the wrong asset for SOPS specifically** (D1 §1.B): it's unstructured bulk text → SOPS degrades
   to whole-file binary mode (no per-field selectivity, its only differentiator), it breaks the operator's
   View/diff/git workflows on a directory meant to be readable (`AGENTS.md:85-89`), and the right layer is OS
   volume encryption (BitLocker on by default on the Win 11 target). CONFIRMED reasoning.
5. **Packaging cost is real and one-sided.** Pure-Python-slim Docker image gains `sops`+`age` (~20-40 MB, arch-aware
   `COPY`); the **unsigned** MSI (D1 §6.2) gains two unsigned native crypto binaries (bigger SmartScreen/AV
   surface) — to support a key flow that **has no valid key home in the MSI/desktop mode** (DPAPI dominates; no
   per-install secret mechanism). Pure tax.
6. **The same operator's own doctrine argues against it.** Kontroll's SECURITY.md (R2 §1, `kontroll/SECURITY.md:20-21`)
   explicitly classifies a *"frozen, local"* repo as **"plaintext accepted,"** reserving mandatory encryption for
   the *networked control plane*. netcanon's data-dir is the former. This is precedent against, written by the same
   hand — the strongest anti-cargo-cult point.

**The strongest single sentence for NO-GO:** *"SOPS's only value is key-on-a-different-box, which no netcanon
run-mode can offer; the one posture it would give (off-host key) is the env-var tier we already ship, and the one
hole worth caring about (`configs/` + Tier-3 leak) is closed by an encrypted volume, not by adding two crypto
binaries to a pure-Python image and an unsigned MSI."*

### 2.3 Adjudication: the against-case wins decisively, and here's the pro-case's fatal flaw

The pro-case (§2.1) is real right up to the moment you ask *where does the SOPS key live*. All three pro-points
collapse on that question:

- Pro-point 1 (Tier-3 hole): a SOPS age key in the zero-config container lands in the **same volume** → hole not
  closed. To close it you must put the key off-host = Tier 1 = no SOPS needed.
- Pro-point 2 (estate consistency): legitimate, but it argues for an **operator-side launch wrapper** (D1 variant
  C, docs-only), **not** for SOPS *inside the netcanon product*. The operator can already `sops -d → export
  NETCANON_FERNET_KEY → exec uvicorn` today with zero netcanon changes.
- Pro-point 3 (`configs/`): the obvious lever is the wrong lever — SOPS on unstructured bulk text is binary-mode
  encryption that breaks readable-directory workflows; OS volume encryption is strictly better and free on the
  primary target.

So the pro-case, fully steelmanned, resolves to "write a README paragraph for SOPS-shaped operators" — which is
exactly the narrowest non-rejected scope, not a product feature. **The against-case is correct.**

---

## 3. Reviewer verdict table (severity-tagged, per claim/option)

| # | Item under review | Reviewer finding | Tag |
|---|---|---|---|
| V1 | **Replace Fernet with SOPS for `devices/*.json`** (D1 §1.A / variant A) | Rip-and-replace of a working, test-guarded scheme for the identical at-rest ceiling; worse desktop key story (loses free DPAPI). Same threat, more code, new burden. | `OVER-ENGINEERING` + `RUNTIME-BLOCKER` |
| V2 | **SOPS-encrypt `configs/**`** (D1 §1.B / variant B) | Unstructured bulk → SOPS binary mode (no differentiator); breaks View/diff/git; key co-locates anyway. Wrong tool, wrong layer. Use OS volume encryption. | `THREAT-MISMATCH` |
| V3 | **SOPS protects a *running* netcanon instance** (the premise) | False in every run-mode: key, decryptor, ciphertext are one host/user (claim (b), confirmed). At-rest encryption only ever defends offline/exfil. | `RUNTIME-BLOCKER` |
| V4 | **Bundle `sops`+`age` into Docker image / MSI** (D1 §6) | Pure-Python-slim image gains arch-aware binaries; **unsigned** MSI gains AV-flag surface; MSI has **no key home** at all. Tax for negative value. | `RUNTIME-BLOCKER` + `OVER-ENGINEERING` |
| V5 | **Variant C: operator-side launch-wrapper recipe, docs-only** (D1 §1.C) | Genuinely works, zero code, zero packaging — but redundant with k8s/Compose/systemd delivery already documented for the same env var. Defensible *only* as one README line for SOPS-shaped estates. | `VIABLE`-but-redundant → at most `POLISH` |
| V6 | **Existing 3-tier Fernet scheme as the baseline** | Correctly identified as the thing to beat; SOPS does not beat it. Tier-3 zero-config co-location is a real (already-documented) operator-config hole. | baseline / `VIABLE` |
| V7 | **`configs/` plaintext is an undocumented honesty gap** | R1 §5 + D2 §4.2 correct: the largest cleartext secret surface is unstated in SECURITY.md as a deliberate posture. This is the **real** finding of the whole run. | `POLISH` (docs) — the lighter thing to fix |
| V8 | **`_data_dir()` reads `NETCANON_DATA_DIR` directly, not `effective_data_dir`** (R3 §2, D2 §4.2.3) | Latent desktop inconsistency; desktop never reaches Tier 3 so not security-load-bearing. Note for a future cleanup. | `POLISH` |
| V9 | **D2's strongest claim: "encrypted volume (O5) covers `configs/` (T2)"** | Holds for *offline* T2 (stolen disk). Does **NOT** cover a live-host copy or a deliberate `scp`-out (that's the on-demand sanitiser's job, bug-reporting-only). Synthesis must not over-claim O5 as covering *all* of T2. | `POLISH` (pressure-test) |

**No `VIABLE` row supports building SOPS into the product.** The only `VIABLE` items are the existing scheme (V6)
and a docs paragraph (V5/V7).

---

## 4. Where I push back on the peer reports (adversarial, not rubber-stamp)

The peer reports are strong and converge — which is itself a mild risk (groupthink). I tested for it. Two
push-backs and one caution:

1. **D1 variant C is over-credited even as "narrow GO."** D1 calls it "NARROW GO — docs-only" (`20-…:142`). I'd
   downgrade further: the `.env.example` *already* enumerates k8s Secret / Compose `secrets:` / systemd
   EnvironmentFile as off-host delivery (R3 §3b). A SOPS launch-wrapper is just a fourth example of "decrypt
   something → export the env var." It does not deserve its own integration section; at most one sentence
   ("operators whose estate uses SOPS can source `NETCANON_FERNET_KEY` from a `*.sops.yaml` the same way"). Calling
   it a "GO" of any kind risks the synthesis greenlighting a build. It is a **footnote**, not a scope.

2. **The reports under-emphasize that the real deliverable is the `configs/` honesty gap, not SOPS at all.** R1
   §5 and D2 §4.2 both surface it, but it's framed as "the thing SOPS *doesn't* fix." Re-frame it as the *positive*
   outcome of this run: the most valuable thing the team learned is that the largest secret surface
   (`configs/**`) is deliberately plaintext and **unstated in SECURITY.md**. That's a matrix-honesty gap of the
   exact kind `AGENTS.md` exists to prevent. Fixing *that* (a SECURITY.md paragraph) is the run's actual ROI.

3. **Caution on D2's O5/T2 cell (V9 above).** "Encrypted volume covers `configs/`" is the linchpin for *not* doing
   anything app-side about A3 — but it only covers the **offline** threat. A live-host attacker or an operator who
   `scp`s a config out gets plaintext. The synthesis should state O5's ceiling honestly rather than imply
   `configs/` is "handled." This does not change the NO-GO (SOPS is still the wrong tool for A3), but it keeps the
   recommendation honest.

None of these flip the verdict; they tighten it.

---

## 5. The lighter thing to do instead of SOPS (named plainly, as the seed demands)

**Do NOT add SOPS. Instead, ship a docs/posture pass — no app code, no new dependency:**

1. **SECURITY.md honesty paragraph for `configs/`** (the run's real finding): state plainly that fetched device
   configs are stored verbatim in plaintext, that they contain device-side secrets, and that the recommended
   at-rest control is an **OS-encrypted volume** (BitLocker on by default on the Win 11 desktop target; LUKS /
   encrypted EBS/PV for server/Docker), with the on-demand sanitiser reserved for *sharing*. This converts a
   silent gap into a documented, deliberate posture (matrix-honesty discipline). Cite the exact fact at
   `backup_runner.py:233-241` + `file_store.py` plaintext docstring.
2. **Recommend Tier-1 + encrypted volume as the server/Docker default**, naming the threats (offline-disk / volume
   exfil) in operator language. Most of this prose exists (`SECURITY.md:80-161`, `README.md:94-121`,
   `.env.example`); the gap is one explicit "for confidential-at-rest, set `NETCANON_FERNET_KEY` from an
   orchestrator secret AND run on an encrypted volume — that covers `configs/` too" paragraph.
3. **(Optional) Preventive non-fit note**, mirroring `AGENTS.md:111-128`'s "Deliberately omitted (preventive)"
   pattern: "SOPS is an operator-side delivery option for Tier 1, not a netcanon feature; desktop/MSI use the OS
   keyring (DPAPI) and have no per-install key home." This stops the next contributor from re-litigating.
4. **(Optional `POLISH`, future cleanup, not this run)** align `credentials._data_dir()` with
   `Settings.effective_data_dir` (V8) so a desktop Tier-3 fallback would land in `%APPDATA%\Netcanon`, not `<cwd>/data`.

Items 1–2 are the meat; 3–4 are nice-to-have. None require SOPS, `age`, `gpg`, a binary in Docker/MSI, a committed
test key, or a `gitleaks` allowlist carve-out.

---

## 6. Must-answer questions the synthesis must resolve before any build

Even though the verdict is NO-GO, the synthesis should explicitly resolve these so the decision is auditable and
the door is closed cleanly:

| # | Must-answer question | Why it must be answered before acting |
|---|---|---|
| Q1 | **Is the verdict NO-GO (no SOPS, docs-only) or GO-WITH-NARROW-SCOPE (a single README sentence for variant C)?** | These are the only two live options. The synthesis must pick one and say so; "we'll think about SOPS later" is not a resolution — write the preventive non-fit note instead. |
| Q2 | **Does the synthesis ship the `configs/`-plaintext honesty paragraph in SECURITY.md this run, or defer it?** | This is the run's actual ROI (V7). If deferred, it must be logged so the gap isn't silently dropped — `AGENTS.md` doc-sync discipline applies. |
| Q3 | **Does the O5/encrypted-volume recommendation over-claim coverage of `configs/`?** | D2's O5/T2 cell only covers *offline* exfil (V9). The SECURITY.md prose must state O5's ceiling (does not defend a live-host read or a deliberate config copy-out) or it lies by omission. |
| Q4 | **Is the zero-config Tier-3 `.fernet_key`-in-the-volume hole adequately steered against?** | `README.md:118-121` already warns; confirm that warning is loud enough, or strengthen it. This is the one *real* at-rest hole, and the fix is operator config (Tier 1 / encrypted volume), not SOPS. |
| Q5 | **Does any AGENTS.md doc-sync row fire for a SECURITY.md-only change?** | A SECURITY.md edit touching the secret-handling posture should round-trip its own "Updating This Document" trigger list (AGENTS.md packaging row references this). Confirm no other doc (README install, IDENTITY) needs a same-commit touch. |
| Q6 | **Confirm no test re-run is warranted.** | A docs-only change touches no code/fixtures, so per AGENTS.md's "judge whether a test re-run is warranted" rule, the answer is "no" — but the synthesis should state it rather than assume. |

---

## 7. Bottom line for the synthesis

- **Both load-bearing claims are TRUE** (verified against source this run): credentials are genuinely
  Fernet-encrypted at rest (claim a); the decryption key co-locates with the ciphertext in every default
  zero-config run-mode, and the only decoupled posture is the env-var tier netcanon already ships (claim b).
- **The recommendation does not flip.** SOPS's defining property (decryptor ≠ ciphertext-host) is structurally
  unavailable in a local-first single app; it would re-buy the one threat (offline-disk/exfil) the existing scheme
  already buys, at the cost of binaries in a pure-Python image, an unsigned-MSI AV surface with no key home, and a
  git-commit-secrets posture the project's Hard Rules forbid.
- **Verdict: NO-GO on SOPS** (with at most a one-sentence variant-C footnote for SOPS-shaped operator estates).
- **Lighter thing to do instead:** a SECURITY.md honesty paragraph about plaintext `configs/` + Tier-1 +
  OS-encrypted-volume guidance, and a preventive "SOPS-is-not-a-netcanon-feature" note. No code, no deps.

*Verified against source this run: `netcanon/security/credentials.py` (full), `netcanon/storage/device_profile_store.py`
(full), `netcanon/models/device_profile.py:1-70`, `.gitignore:1-98`, `netcanon/services/backup_runner.py:225-249`,
`netcanon/api/routes/backups.py:108-138`, `Dockerfile` (data-dir/volume/apt grep). Peer reports 10/11/12/20/21 read in full.*
