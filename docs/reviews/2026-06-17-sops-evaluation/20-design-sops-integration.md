# 20 — Design: IF netcanon adopts SOPS, what does the concrete integration look like?

**Author:** D1 (design) · **Run:** 2026-06-17 SOPS evaluation · **Status:** read-only design sketch, builds on R1/R2/R3.

> **Framing this report must state up front (so the synthesis isn't misread):** my brief is *"assume netcanon
> DOES adopt SOPS, design the concrete integration."* I do that. But the design honesty rule in the seed
> (`00-blackboard.md:28-32`) and R1/R2/R3's findings force me to flag, at every step, where the integration is
> either **redundant with the existing 3-tier Fernet scheme** or **structurally blocked** (the SOPS decryption
> key co-locates with the ciphertext in every netcanon run-mode — R1 §7, R2 §5.1, R3 §3). So this is a *buildable*
> design with the ugly parts called out, NOT an argument that it should be built. The GO/NO-GO call belongs to
> D2 + the synthesis; my job is to make the cost and shape concrete enough that the verdict is well-informed.
> **My own bottom line, stated honestly:** the only integration variant that buys anything real is the narrow
> one in §1.C (SOPS as an *operator-side, opt-in delivery mechanism for `NETCANON_FERNET_KEY` on the server/
> Docker mode only*) — and even that is dominated by the env-var tier netcanon already ships. Everything wider
> than that is `OVER-ENGINEERING`/`RUNTIME-BLOCKER`. I design all variants so the synthesis can pick.

---

## 0. Anchors I am building on (do not re-derive)

From the three research reports, treated as fixed:

- **R1 census (`10-…md`):** two secret classes — (a) device login creds in `devices/*.json` + legacy
  `schedules/*.json`, **already Fernet-encrypted at rest** (`device_profile_store.py:64-67`,
  test-guarded `tests/unit/test_device_profile_store.py:124-133`); (b) the fetched device configs in
  `configs/**`, **plaintext, the largest cleartext secret surface**, never encrypted/redacted on the write
  path (`backup_runner.py:233-241`, `file_store.py:1-3`). The Fernet key resolves through a 3-tier chain
  (env → keyring → file) and in Tier 3 **co-locates** with the ciphertext (`credentials.py:192-211`).
- **R2 Kontroll (`11-…md`):** SOPS+age works in Kontroll because the age key lives on a **separate control VM**
  from the consumers and the ciphertext is **committed to git**; decryption is **render-time** (Ansible →
  one `0600` `.env`), the app never holds the key. **None of {separate-machine custody, commit-ciphertext-to-git,
  render-time Ansible} transfers** to a single local-first app.
- **R3 runtime (`12-…md`):** four run-modes (desktop/server/docker/MSI) all funnel through the **same
  `create_app()`** (`main.py:69`). The key co-locates with the ciphertext in **every default zero-config mode**;
  the *only* decoupled posture is **Tier 1 env-var sourced off-host** — which already exists. SOPS adds binary
  deps to a pure-Python Docker image + an unsignable MSI for no new property.

I do **not** contradict any of these. Where SOPS is infeasible in a mode (per R3 §3), I say so and scope around it.

---

## 1. (Q1) WHAT gets SOPS-encrypted — the target set

R1 §8 gives three candidate buckets. I evaluate each as a SOPS target and design the *least-bad* mapping.
There are three coherent variants; I name them A/B/C and recommend C (narrowest).

### 1.A — Device-profile credentials at rest (REPLACE Fernet with SOPS)

**Shape:** stop Fernet-encrypting the two password fields inside each `devices/{id}.json`; instead keep one
SOPS-encrypted file per profile (or one aggregate file) whose `password`/`enable_password` values are
`ENC[AES256_GCM,…]`, decrypted via the `sops` library/binary on load.

```yaml
# data/devices/3f2a….sops.json  (SOPS-encrypted, encrypted_regex catches only cred fields)
{
  "id": "3f2a…", "name": "core-sw-1", "type_key": "Cisco", "host": "10.0.0.1",
  "username": "netadmin",
  "password": "ENC[AES256_GCM,data:…,iv:…,tag:…,type:str]",
  "enable_password": "ENC[AES256_GCM,data:…,iv:…,tag:…,type:str]",
  "sops": { "age": [ … ], "lastmodified": "…", "mac": "ENC[…]", "version": "3.x" }
}
```

```yaml
# .sops.yaml  (creation rule — basename-anchored, like Kontroll instance/.sops.yaml:26-32)
creation_rules:
  - path_regex: (^|/)devices/.*\.sops\.json$
    encrypted_regex: '^(password|enable_password)$'   # leave id/host/username plaintext
    age: 'age1operator…'                              # ← the load-bearing problem (see §2)
```

**VERDICT: `OVER-ENGINEERING` + `RUNTIME-BLOCKER`.** This is a pure **rip-and-replace of a working,
test-guarded scheme** (`credentials.py`, `migration.py`, `device_profile_store.py:64-67`) with one that has the
**identical at-rest threat ceiling** (R3 §4) and a strictly worse key story: Fernet's Tier 2 (OS keyring/DPAPI)
gives desktop/MSI an out-of-band key *for free* (R3 §3a/§3d); a SOPS age identity on desktop must live on the
same disk as the ciphertext → **co-located, no gain, and now the user owns an age key** (AGENTS.md:111-128
single-user-utility ethos). This variant should be **rejected outright** by the synthesis. I include it only to
make the rip-and-replace cost explicit: it touches `credentials.py`, both storage loaders, `migration.py`, and
every credential test, for zero new security property.

### 1.B — The backup artifacts (`configs/**`) at rest (NEW encryption surface)

**Shape:** SOPS-encrypt each fetched config as it is written in `backup_runner.py:233-241` /
`file_store.py:162-186`; decrypt on the view/migrate/sanitize read paths.

**VERDICT: `THREAT-MISMATCH` + wrong tool + real functional regression.** Three independent problems:

1. **SOPS is a structured-document tool** (YAML/JSON/ENV/INI/dotenv key-value). A Cisco `running-config` or a
   Junos `set`-form blob is **unstructured text**, so SOPS would fall back to whole-file binary mode
   (`sops -e --input-type binary`) — which gives you exactly what Fernet/`age -e` gives you with far less
   ceremony. There is no per-field selectivity to exploit (the value SOPS uniquely adds).
2. **Bulk volume.** R1 §8 calls this "bulk, high-volume, frequently-written content"; backups run on a schedule
   and can be 50 MB each (`file_store.py:100`). Wrapping every backup in a `sops`-binary subprocess per file is
   a throughput + CPU cost for the offline-disk-exfil threat only (R3 §4 — and the key co-locates anyway).
3. **Functional regression.** The configs tree is *meant to be readable* — operators `View`/`Open in editor`
   (`POST /api/v1/configs/{filename}/open`, AGENTS.md:85-89), diff, and `git`-track their backups externally.
   Encrypting them at rest breaks every out-of-band tool the operator already uses on that directory. The
   **correct** at-rest answer for `configs/` is R3 §5.6: **OS-level volume encryption** (BitLocker is on by
   default on the Win 11 desktop platform; LUKS/encrypted-EBS for server/Docker) — zero app code, covers the
   whole tree including the Fernet key, same ceiling. SOPS here is the wrong layer.

If the synthesis wants *any* at-rest story for `configs/`, route it to OS volume encryption + the existing
on-demand sanitizer for *sharing* — **not** SOPS.

### 1.C — A deploy/config secret file (NARROW, opt-in, server/Docker only) ✅ recommended-if-anything

**Shape:** netcanon stores **nothing new**. Instead, document + (optionally) ship a thin helper so an operator
who *already* uses SOPS in their estate can keep `NETCANON_FERNET_KEY` in a committed `*.sops.yaml` and have it
decrypted **at process launch, outside the app**, into the env var Tier 1 already consumes
(`credentials.py:163-167`). This is the **only** mapping that matches SOPS's actual shape (a small declarative
secret file, committed, decrypted out-of-band by an off-host key — R2 §4.1) **and** netcanon's actual gap (the
Tier-3 co-location, fixable by sourcing Tier 1 from off-host).

```yaml
# secrets.sops.yaml  — operator-owned, lives in THEIR ops repo, NOT netcanon's
NETCANON_FERNET_KEY: ENC[AES256_GCM,data:…,iv:…,tag:…,type:str]
sops:
  age: [ { recipient: age1operator…, enc: "-----BEGIN AGE ENCRYPTED FILE-----…" } ]
```

```bash
# launch wrapper (operator-side, NOT in the netcanon image): decrypt → export → exec
export NETCANON_FERNET_KEY="$(sops --decrypt --extract '["NETCANON_FERNET_KEY"]' secrets.sops.yaml)"
exec uvicorn netcanon.main:app --host 0.0.0.0 --port 8000
```

**VERDICT: `VIABLE` but `OVER-ENGINEERING` vs the baseline.** This works, requires **no netcanon code change at
all** (Tier 1 already reads the env var), keeps `sops`/`age` entirely **out of** netcanon's image/MSI (it runs in
the operator's deploy tooling, exactly like Kontroll runs it in Ansible — R2 §3), and the age key lives in the
operator's existing custody (their secret store / CI), never in netcanon's data-dir. **But** R3 §3b/§3c shows the
same `.env.example:41-44` already enumerates k8s Secret, Compose `secrets:`, systemd `EnvironmentFile` as
off-host delivery for that same env var — SOPS is just *one more* delivery option among those, valuable **only to
an operator whose estate is already SOPS-shaped**. So the honest "integration" is: **a 6-line README recipe, zero
code, zero packaging.** That is the entire defensible scope.

### Target-set summary

| Candidate | Maps to SOPS's shape? | New security property over status quo? | Verdict |
|---|---|---|---|
| **A** device creds (replace Fernet) | partial (small JSON) | **none** — same ceiling, worse desktop key story | **REJECT** (`OVER-ENGINEERING`) |
| **B** `configs/**` artifacts | **no** (unstructured, bulk → binary mode) | none + breaks View/diff/git | **REJECT** (`THREAT-MISMATCH`) — use OS volume encryption |
| **C** `NETCANON_FERNET_KEY` in a SOPS file, decrypted at launch | **yes** (the only true fit) | only on server/Docker, only if estate already SOPS | **NARROW GO** — docs-only, no code, no packaging |

**Only encrypt what is genuinely sensitive-at-rest (the seed's rule):** creds are already encrypted; configs are
better served by OS encryption; the one thing worth keeping off the data-dir is the *key*, and variant C does
exactly that without re-encrypting anything netcanon stores.

---

## 2. (Q2) WHERE the private key lives per run-mode — the hard part

This is the question R3 §3 surfaced as load-bearing. I answer it concretely per mode for the only buildable
variant (C), and note where it forces a compromise or has **no clean home**. (For A/B the answer is the same
co-location verdict, only worse, since the app itself would need the key.)

| Mode | Where the age private key would live | Co-located with ciphertext? | Clean home? |
|---|---|---|---|
| **(a) Desktop (PySide6)** | Would have to sit on the user's disk (`%APPDATA%` or `~/.config/sops/age/keys.txt`) so the app can read it at launch | **YES** — same machine/user as `devices/*.json` | **NO CLEAN HOME.** DPAPI keyring already gives an out-of-band key for free (R3 §3a). A user-owned age key is strictly worse + new burden. **Scope SOPS OUT of desktop entirely.** |
| **(b) Server (pip/uvicorn)** | In the **operator's deploy tooling / secret store**, used by the launch wrapper to decrypt → export `NETCANON_FERNET_KEY`, **never written to the data-dir** | **NO** (if wrapper runs on a trusted admin host / CI and only the *decrypted env var* reaches the server process) | **YES-ish** — but identical to "operator sets `NETCANON_FERNET_KEY` from their secret manager," which exists. |
| **(c) Docker** | **Must NOT be baked into the image** (every pull would share it — catastrophic, cf. R3 §3d on the MSI). Either (i) decrypt **outside** the container in the orchestrator and inject `-e NETCANON_FERNET_KEY` (recommended; key never enters container), or (ii) mount the age key into the container + run `sops` in an entrypoint — which **re-creates co-location** (R3 §3c: the age key now sits on the same host/volume as the ciphertext). | (i) **NO**; (ii) **YES** | (i) **YES** but ≡ Tier 1; (ii) **NO** — reinvents the Tier-3 problem with extra binaries. |
| **(d) MSI** | **No home exists.** R3 §3d: the MSI can bundle a *binary* via `include_files` (`setup_desktop.py:97-110`) but **cannot bundle a per-user key**; shipping one shared key is catastrophic; generating one at runtime puts it on the same disk as the ciphertext (≡ desktop co-location) and asks a network engineer to manage an age keypair. The MSI is also **unsigned today** (`desktop-msi-publish.yml:20-22`) so adding a crypto binary expands the SmartScreen/AV surface. | **YES** (if a key is generated) | **NO CLEAN HOME.** Same as desktop — **scope SOPS OUT.** |

**The honest per-mode answer:** SOPS has a *defensible* key home in **exactly one place — the operator's
off-host deploy tooling in server/Docker mode (variant C, path i)** — and that home is **not inside netcanon at
all**; it is the operator's existing secret custody, the same place Tier 1's env var already comes from. In
desktop and MSI there is **no clean key home** (DPAPI dominates; no per-install secret mechanism exists). In
Docker the "in-container" path reinvents co-location. So the design **must explicitly scope SOPS to server/Docker
operator-tooling and leave desktop/MSI on the existing keyring tier** — anything else is `RUNTIME-BLOCKER`.

---

## 3. (Q3) The decrypt flow — at-load vs at-use; where plaintext lives, for how long

Two candidate flows; the choice only matters for variants A/B (where the app decrypts). For variant C the app
never sees SOPS — it just reads `NETCANON_FERNET_KEY` from the env exactly as today, so §3 is moot for the
recommended scope. I document both so the synthesis can see why A/B are also worse here.

### 3.1 At-load (decrypt the whole store on startup → plaintext in memory)

This mirrors netcanon's **current** Fernet behaviour: `FileDeviceProfileStore.load_all()`
(`device_profile_store.py:86-125`) decrypts every credential field into the in-memory `DeviceProfile` registry
once at lifespan startup; the in-memory model holds **plaintext for the whole process lifetime** (the module
docstring is explicit: `credentials.py:41-46`, `device_profile_store.py:10-12`).

- **Plaintext residence:** process memory, for the life of the process (re-resolved each restart).
- **SOPS-at-load sketch (variant A):** in `load_all()`, replace the `migrate_credential_fields(...)` decrypt with
  a `sops --decrypt` (or `pysops`/`pyrage`) call per file → parse → hydrate. **Cost vs today:** N subprocess
  spawns at startup (one `sops` exec per profile) instead of N in-process Fernet decrypts — slower, and adds the
  binary dep. **Same plaintext-in-memory residence as today.** No improvement, measurable regression.

### 3.2 At-use (decrypt one credential when a backup runs)

Decrypt lazily only when `backups._resolve_credentials` needs the password for an actual SSH connect
(`backups.py:128-136` re-wraps into `SecretStr`; netmiko reads it at `netmiko_collector.py:88-94`).

- **Plaintext residence:** ideally only for the duration of the SSH session, then dropped. This is the
  *theoretically* better hygiene posture (shorter plaintext window) and mirrors Kontroll's lazy-deref-under-`no_log`
  discipline (R2 §3.1).
- **Reality check:** netcanon's current design materialises plaintext at load, not at use, and the backup worker
  thread already holds the plaintext profile (`device_profile_store.py:36-44` lock comment). Moving to at-use
  would be a **larger refactor than the SOPS adoption itself** (the registry currently *is* the plaintext store),
  and Python `str` immutability means you cannot reliably zero the plaintext anyway (it lingers until GC). So the
  shorter-window benefit is **mostly illusory in CPython** — `RUNTIME-BLOCKER`-adjacent.

**Recommendation for the flow question:** if (against my recommendation) A is ever built, use **at-load** to
match the existing architecture and avoid the registry refactor — but recognise it buys nothing over the Fernet
at-load it replaces. For variant C, **there is no in-app decrypt flow** — `sops` runs once in the launch wrapper,
emits the key to the env, the app's existing Tier-1 path takes over, and plaintext-key residence is identical to
today (process env + the in-memory Fernet instance, `credentials.py:214-224`).

---

## 4. (Q4) Key rotation + multi-recipient (operator + CI)

This section only has teeth for variant C (the others have no off-host key to rotate meaningfully). I borrow the
**discipline** from Kontroll (R2 §2.2) but flag that netcanon has **no second principal** to justify the full
key-group machinery (R2 §5.2: "Least-privilege across principals presupposes ≥2 principals").

### 4.1 Multi-recipient `.sops.yaml` (operator + CI)

```yaml
# operator's ops-repo .sops.yaml  (NOT netcanon's repo)
creation_rules:
  - path_regex: (^|/)secrets\.sops\.ya?ml$
    age: >-
      age1operator…,    # day-to-day operator decrypt (laptop / admin host)
      age1ci…,          # CI runner that deploys netcanon (decrypts at deploy)
      age1breakglass…   # offline recovery key (never on the deploy host)
```

- **Operator key:** the human who runs deploys; lives in their secret store, mirrors Kontroll's control-VM key
  (`SECURITY.md:52-54` in Kontroll).
- **CI key:** scoped to the deploy pipeline so CI can `sops --decrypt` → inject `NETCANON_FERNET_KEY`. This is the
  one place a *second principal* genuinely appears (operator vs CI) — but note it's the **operator's CI**, not
  netcanon's product, so this is operator-ops design, not netcanon-product design.
- **Break-glass:** offline recovery key per Kontroll R2 §2.2 — only meaningful if you accept that losing the
  `NETCANON_FERNET_KEY` means re-entering all device profiles (which netcanon *already* accepts as a tolerated
  risk — `SECURITY.md:502`, R1 §3). So break-glass is arguably **over-built for netcanon's stated risk posture**.

### 4.2 Rotation

- **`NETCANON_FERNET_KEY` rotation (the real one):** netcanon **already documents** a rekey procedure
  (`SECURITY.md:80-161`, R3 §2) — generate a new Fernet key, the stores re-encrypt on next save. SOPS is
  orthogonal: rotating the *Fernet* value inside the SOPS file is `sops --set` then redeploy; rotating the *age
  recipients* is `sops updatekeys` after editing `.sops.yaml` (Kontroll defers this as a manual operator step —
  R2 §2.4, `SECURITY.md:353-360`). **Two rotation surfaces instead of one** is a net complexity add.
- **Flag:** rotation here is a feature of the operator's SOPS workflow, not of netcanon. netcanon's own rotation
  story (rekey + re-save) is unchanged and already exists.

---

## 5. (Q5) Dev/test story — fixtures/tests must run with NO real key

This is mandatory regardless of variant: CI and contributors must never need a real age key, and AGENTS.md
Hard Rules forbid committing real secrets (AGENTS.md:249, 290-294).

### 5.1 The Kontroll precedent to copy

Kontroll's `instance.example/.sops.yaml` ships a **placeholder** recipient (`age1example…`,
R2 §2.4 / `instance.example/.sops.yaml:24`) that `--fresh` replaces. The transferable pattern is a **committed
test age identity** — a throwaway keypair whose *private* half is committed *on purpose* (it protects nothing
real), exactly the "DUMMY-domain" approach the seed references.

### 5.2 Concrete test fixture

```
tests/fixtures/sops/
  age-test-key.txt          # PUBLICLY-COMMITTED throwaway age identity (AGE-SECRET-KEY-1TEST…)
  .sops.yaml                # creation rule → the test recipient only
  example.secrets.sops.yaml # NETCANON_FERNET_KEY encrypted to the test key
```

```python
# tests/conftest.py  (or a sops marker fixture)
@pytest.fixture
def sops_test_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SOPS_AGE_KEY_FILE", str(FIXTURES / "sops" / "age-test-key.txt"))
    # decrypt with the throwaway key, assert the round-trip; NEVER a real key
    ...
```

- **Critical:** the committed test private key must be **unmistakably fake** (mirror AGENTS.md:290-294's
  synthetic-hash rule), e.g. a comment header `# THROWAWAY TEST KEY — protects nothing — do NOT reuse`. The
  `gitleaks` custom rule Kontroll uses to *catch* `AGE-SECRET-KEY` (R2 §2.3) would **fire on this file** — so
  netcanon would need a `gitleaks` allowlist entry for exactly this path, which is itself a small ongoing tax.
- **The deeper flag:** netcanon today needs **zero** key material in its test tree — Fernet tests
  (`tests/unit/test_credentials.py:107-149`) generate an ephemeral key in-process via `reset_fernet()`
  (`credentials.py:266-269`) and `Fernet.generate_key()`. Adopting SOPS **introduces** a committed-key fixture +
  a `gitleaks` allowlist carve-out where none was needed. That is a new attack-surface-shaped maintenance item
  (a committed private key, even fake, that a future careless edit could swap for a real one) — `POLISH`-tagged
  cost but worth naming.

---

## 6. (Q6) Packaging cost — shipping `sops` + `age` into Docker and (critically) the MSI

This is where the integration gets ugliest, and it only arises for variants where **netcanon itself** decrypts
(A/B, or variant C path-ii where `sops` runs in the container). Variant C path-i (decrypt in operator tooling)
ships **nothing** — which is the strongest argument for that scope.

### 6.1 Docker

- **Current image is pure-Python slim** with **only `curl`** added at runtime (`Dockerfile:48-56`); the builder
  stage has `build-essential`/`libffi-dev`/`libssl-dev` but the **runtime stage carries none of them**
  (`Dockerfile:48-63`). There are deliberately **no extra binaries** in the runtime layer.
- **To run `sops` in-container** you must either (a) `apt-get install` nothing-from-Debian (sops is not in
  bookworm's default repos) → download the `sops` + `age` release binaries (~20-40 MB combined) and `COPY` them
  into the runtime stage, **or** (b) add a pure-Python path: `pyrage` (Rust `age` binding via maturin wheel) +
  a SOPS-format reader. Either way the pure-Python-slim property R3 §3c calls out is **lost**, the image grows,
  and the SBOM/attestation surface (AGENTS.md:186 packaging row → SECURITY.md Dependency Supply Chain table)
  gains a new entry that must be documented in the same commit.
- **Multi-arch:** the publish workflow builds for amd64 (and likely arm64); the `sops`/`age` binary `COPY` must
  be arch-aware (`TARGETARCH` build-arg + per-arch download) — a real Dockerfile complication.

### 6.2 Windows MSI — the hard wall

- The MSI is a **cx_Freeze bundle** of Python libs + `definitions/` + license notices
  (`setup_desktop.py:76-110`); its `packages`/`include_files` lists are Python-import-driven. Adding `sops.exe`
  + `age.exe` means: download Windows release binaries, add them to `include_files`
  (`setup_desktop.py:97-110`), redistribute them under **their** licenses (sops = MPL-2.0, age = BSD-3) → a new
  `THIRD-PARTY-NOTICES.txt` obligation (the file already tracks PySide6/paramiko/pystray — `setup_desktop.py:103-109`).
- **The MSI is unsigned** (`desktop-msi-publish.yml:20-22`, R3 §3d). Bundling two unsigned native crypto
  executables **materially expands the SmartScreen / AV false-positive surface** — exactly the kind of friction
  AGENTS.md:120-122 cites as the reason auto-update was deliberately omitted.
- **And it buys nothing** (R3 §3d): the MSI's winning key tier is DPAPI keyring; there is **no per-install age
  key home** in an MSI. So the MSI would ship two crypto binaries to support a key-management flow that **has no
  valid key location in that mode**. This is the single clearest `RUNTIME-BLOCKER` in the whole packaging story:
  **the MSI cannot host SOPS meaningfully, so it should not carry the binaries at all.**

### 6.3 Packaging verdict

| Distribution | Binary cost | Buys what? | Recommendation |
|---|---|---|---|
| Docker (path-i: decrypt outside) | **none in image** | off-host key delivery ≡ Tier 1 | OK — docs only |
| Docker (path-ii: decrypt in entrypoint) | +`sops`+`age` (~20-40 MB, arch-aware), loses pure-Python-slim | re-creates co-location | **REJECT** |
| MSI | +`sops.exe`+`age.exe`, new license notices, bigger AV surface, **unsigned** | **nothing — no key home** | **REJECT** |

**Friction estimate:** Docker path-i = ~6 lines of README. Docker path-ii / MSI = a multi-arch binary-vendoring
exercise + license-notice updates + SECURITY.md supply-chain row + a bigger unsigned-MSI AV surface, for a key
flow that **doesn't have a home in the MSI mode**. The packaging math alone argues the scope must be **operator-
tooling only (C path-i)**, never bundled.

---

## 7. (Q7) Migration of any existing plaintext store

There are two distinct "existing store" migration questions, and netcanon already has machinery for the one that
matters.

### 7.1 The Fernet legacy-plaintext migration ALREADY EXISTS (do not rebuild)

`migrate_credential_fields` + `decrypt_field` (`migration.py:18-35`, `credentials.py:246-263`) already do
transparent one-shot migration: any credential field that fails Fernet decryption is treated as legacy plaintext,
returned as-is, and the file is immediately re-saved encrypted (`device_profile_store.py:104-118`,
`schedule_store.py:90-104`). This is the migration that already protects real operators upgrading from a
pre-encryption version. **Any SOPS adoption must NOT regress this** — it is test-and-doc-guarded
(`SECURITY.md:155-161`).

### 7.2 Migrating Fernet→SOPS (only relevant to the rejected variant A)

If variant A were built, you would need a **second** one-shot migration: on load, detect a Fernet token
(`gAAAAA…`) vs a SOPS-`ENC[…]` value, decrypt with Fernet, re-encrypt with SOPS, re-save. Sketch:

```python
def _migrate_fernet_to_sops(value: str) -> tuple[str, bool]:
    if value.startswith("ENC[AES256_GCM"):       # already SOPS
        return sops_decrypt_field(value), False
    plaintext, _ = decrypt_field(value)          # Fernet or legacy plaintext (existing path)
    return plaintext, True                        # caller re-encrypts via SOPS + re-saves
```

**Flag:** this is a *third* token format the loader must disambiguate (legacy-plaintext, Fernet, SOPS) — more
code, more edge cases, for variant A which §1.A already rejects. The migration cost is therefore an argument
**against** A, not a feature of it.

### 7.3 Variant C needs NO store migration

Because variant C re-encrypts nothing netcanon stores (it only changes how the *operator* delivers
`NETCANON_FERNET_KEY`), **there is zero data migration** — the existing Fernet-at-rest stores and their legacy
migration are untouched. This is another reason C is the only sane scope: it is **purely additive operator
documentation**.

---

## 8. The buildable-now scope (if the synthesis says GO)

Distilling §1-§7 into the *only* thing I'd actually build, and the things I'd explicitly refuse:

**BUILD (if anything):**

1. A **README/SECURITY.md recipe** (no code) under the existing key-management docs (`SECURITY.md:80-161`,
   `.env.example:32-52`) showing the variant-C launch-wrapper pattern (§1.C): "if your estate already uses SOPS,
   here's how to source `NETCANON_FERNET_KEY` from a `*.sops.yaml` at launch — server/Docker only." This slots
   in next to the k8s/Compose/systemd delivery options already documented (R3 §3b/§3c) as one more.
2. **Explicitly document the non-fit** for desktop/MSI (DPAPI dominates; no key home) so a future contributor
   doesn't speculatively add it — mirroring AGENTS.md:111-128's "Deliberately omitted (preventive)" pattern.

**REFUSE:**

- Replacing Fernet with SOPS for `devices/*.json` (§1.A — `OVER-ENGINEERING`/`RUNTIME-BLOCKER`).
- SOPS-encrypting `configs/**` (§1.B — `THREAT-MISMATCH`; use OS volume encryption instead).
- Bundling `sops`/`age` into the Docker image or the MSI (§6 — packaging tax, no key home in MSI).
- Adding a committed test age key + `gitleaks` allowlist (§5 — new key-shaped surface where none existed).

---

## 9. Where it gets ugly (consolidated flag list for V1 + synthesis)

| # | Ugly spot | Why | Tag |
|---|---|---|---|
| U1 | Desktop/MSI have **no clean key home** for an age identity; DPAPI already provides one for free | §2, R3 §3a/§3d | `RUNTIME-BLOCKER` |
| U2 | In-container `sops` (Docker path-ii) **re-creates** the Tier-3 co-location it was meant to fix | §2, R3 §3c | `RUNTIME-BLOCKER` |
| U3 | MSI would ship two unsigned crypto binaries to support a key flow with **no valid key location in that mode** | §6.2 | `RUNTIME-BLOCKER` + `OVER-ENGINEERING` |
| U4 | Variant A is a rip-and-replace of a working, test-guarded scheme for the **same threat ceiling** | §1.A, R3 §4 | `OVER-ENGINEERING` |
| U5 | Variant B uses SOPS as a whole-file binary blob on bulk text + **breaks View/diff/git** on `configs/` | §1.B | `THREAT-MISMATCH` |
| U6 | SOPS introduces a **committed (fake) age key + gitleaks carve-out** where netcanon needs zero key material in tests today | §5.2 | `POLISH` (but a real new surface) |
| U7 | Two rotation surfaces (Fernet value + age recipients) replace one (existing rekey) | §4.2 | `OVER-ENGINEERING` |
| U8 | A third loader token format (plaintext/Fernet/SOPS) to disambiguate, if A is built | §7.2 | `OVER-ENGINEERING` |
| U9 | Variant C's "integration" reduces to a README recipe that is **one of several already-documented** off-host delivery options for the env var | §1.C, R3 §3b | `OVER-ENGINEERING` (redundant) |

---

## 10. Synthesis hand-off (D1 → V1 / 99-synthesis)

- **The only buildable-and-defensible SOPS scope is variant C, server/Docker, docs-only, decrypt-in-operator-
  tooling.** It requires **no netcanon code change, no store migration, and no `sops`/`age` in any netcanon
  artifact** — because the work happens in the operator's deploy pipeline (exactly how Kontroll uses it — R2 §3),
  and the app's existing Tier-1 env-var path (`credentials.py:163-167`) consumes the result unchanged.
- **Every wider variant is blocked or redundant:** A replaces a working scheme for the same ceiling (and a worse
  desktop key story); B is the wrong tool for unstructured bulk artifacts and breaks operator workflows; the
  Docker-in-container and MSI packaging paths have no valid key home (U1-U3).
- **Therefore my design honestly supports a `GO-WITH-NARROW-SCOPE` at most, leaning `NO-GO`:** even variant C is
  dominated by the env-var tier netcanon already ships, so its marginal value is *only* "a recipe for operators
  whose estate is already SOPS." If D2's threat head-to-head confirms the co-location ceiling (it will — R3 §4),
  the right call is likely **NO-GO + a one-paragraph SECURITY.md note** that SOPS is an operator-side delivery
  option for Tier 1, not a netcanon feature.
- **Concrete artifacts I sketched for whoever builds C:** the `.sops.yaml` creation rule (§1.C), the launch
  wrapper one-liner (§1.C), the multi-recipient ruleset (§4.1), and the test-key fixture layout (§5.2) — all
  operator-side, none touching netcanon source.

*Verified against source this run: `netcanon/security/credentials.py` (full, 3-tier `_resolve_key` :156-211,
`encrypt`/`decrypt`/`decrypt_field` :227-263, `reset_fernet` :266-269); `netcanon/security/migration.py` (full);
`netcanon/storage/device_profile_store.py` (full, encrypt-on-save :64-67, load+migrate :86-125, lock :31-45);
`netcanon/storage/schedule_store.py` (full, legacy inline-cred encrypt :49-54 / migrate :90-104); `Dockerfile`
(full, pure-Python-slim runtime :48-63, only `curl` added, `NETCANON_DATA_DIR=/app/data` :80, VOLUME :94,
uvicorn entrypoint :96); `setup_desktop.py` :70-190 (cx_Freeze packages/include_files/excludes, executables);
`pyproject.toml` :52-106 (cryptography :73 + keyring :74 base deps, desktop-build extra :103); `AGENTS.md`
(Hard Rules :249/:290-294, deliberately-omitted :111-128, packaging doc-sync row :186). Peer reports
10/11/12 read in full.*
