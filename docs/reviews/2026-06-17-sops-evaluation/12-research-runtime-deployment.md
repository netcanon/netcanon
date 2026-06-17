# 12 — Runtime & Deployment: where could a decryption key live per run-mode? (R3)

**Author:** R3 (research) · **Run:** 2026-06-17 SOPS evaluation · **Status:** read-only research

> Mission slice: MAP how netcanon is actually run/deployed in each mode and WHERE a decryption key could
> live in each — the load-bearing constraint for any at-rest encryption scheme — then survey the Python
> alternatives, and answer per-mode: **does the decryption key co-locate with the ciphertext on the same
> disk/host the app runs on?** No recommendation (that's D2). This is the option matrix for the design phase.

---

## 0. TL;DR for the design phase (read this first)

1. **netcanon already ships at-rest credential encryption.** It is *not* a greenfield decision. Device-profile
   and legacy-schedule credentials are encrypted with **Fernet** (`cryptography`), and the key is resolved by a
   **mature 3-tier chain** that already implements three of the very alternatives the seed asks me to survey
   (env-var, OS keyring, file-fallback). See `netcanon/security/credentials.py:1-269`,
   `netcanon/storage/device_profile_store.py:5-16,61-77`, `SECURITY.md:80-161`. Whatever D1/D2 recommend must be
   weighed against *this existing system*, not against a hypothetical plaintext baseline.

2. **The key co-locates with the ciphertext in every default zero-config run-mode** (desktop keyring tier,
   container file-fallback tier, pip/dev file-fallback tier). The *only* tier that decouples key from data-dir
   is **Tier 1 (`NETCANON_FERNET_KEY` env var)** — and even that is only decoupled if the operator stores the
   value somewhere off the host (an orchestrator secret store), which is exactly the Kontroll-shaped pattern.

3. **Therefore at-rest encryption here only ever defends an offline-disk / exfil-copy threat** (a stolen laptop
   data dir, a leaked `data/` volume tarball, an accidentally-committed JSON). It does **not** defend against an
   attacker who can read the running host/process — because the running app must hold the plaintext key in
   memory and (in the default tiers) the key sits next to the data. SOPS would inherit exactly the same ceiling.

4. **SOPS adds nothing the env-var tier doesn't already give**, and it adds binary deps (`sops`+`age`/`gpg`) to
   Docker/MSI and key-management friction to a single-user desktop that will never own an age key. The runtime
   map below is the evidence for that.

---

## 1. The four run-modes — how each actually launches

| Mode | Entry point | `create_app` call site | Host binding | Who runs it |
|---|---|---|---|---|
| **(a) PySide6 desktop** | `python -m netcanon_desktop` → `DesktopApp.run()` | `netcanon_desktop/app.py:58` `create_app(settings)` | `127.0.0.1:8765` (loopback only) | Single local user, their own Windows session |
| **(b) FastAPI/uvicorn server** | `uvicorn netcanon.main:app` | module-level `app = create_app()` `netcanon/main.py:318` | `0.0.0.0:8000` default (`config.py:100-101`) | Operator on a host/VM |
| **(c) Docker** | image `ENTRYPOINT ["uvicorn","netcanon.main:app",…]` `Dockerfile:96` | same module-level `create_app()` | `0.0.0.0:8000` in-container | Operator via `docker run` / compose / k8s |
| **(d) Windows MSI** | `netcanon.exe` (cx_Freeze frozen `netcanon_desktop/__main__.py`) `setup_desktop.py:174-189` | same `create_app(settings)` as desktop | `127.0.0.1:8765` | Single local Windows user |

**Key structural fact:** all four modes funnel through the *same* `create_app()` factory
(`netcanon/main.py:69`) and the *same* lifespan, which constructs the *same* `FileDeviceProfileStore`
(`netcanon/main.py:159`). So the credential-encryption code path is **identical across every mode** — the only
thing that varies per mode is *which Fernet key tier wins* and *where the key physically sits*. That is the
entire crux of this report.

### Where each mode keeps its data (the ciphertext location)

Data root is resolved through `Settings.effective_data_dir` (`config.py:116-128`): explicit `data_dir` wins,
else `configs_dir.parent`. The four state stores hang off it in the lifespan:
`jobs/`, `schedules/`, `devices/` (`netcanon/main.py:147,155,159`). Device credentials live in
`{data_root}/devices/{id}.json`, Fernet-encrypted (`device_profile_store.py:61-77`).

| Mode | `configs_dir` | `effective_data_dir` (ciphertext lives here) |
|---|---|---|
| Desktop dev (source) | `<repo>/configs` (`settings.py:57`) | `<repo>/configs`.parent = `<repo>` |
| Desktop frozen (MSI) | `%APPDATA%\Netcanon\configs` (`settings.py:51`) | `prefs.data_dir` or `%APPDATA%\Netcanon\configs`.parent = `%APPDATA%\Netcanon` |
| Server (pip) | `./configs` (default, `config.py:98`) | `./` (cwd) unless `NETCANON_DATA_DIR`/`data_dir` set |
| Docker | `/app/configs` (`Dockerfile:79`) | `/app/data` (`NETCANON_DATA_DIR=/app/data`, `Dockerfile:80`), bind-mounted `VOLUME` `Dockerfile:94` |

---

## 2. The existing key-resolution chain (the option matrix is already half-built)

`netcanon/security/credentials.py::_resolve_key()` (`credentials.py:156-211`) — **first hit wins**:

| Tier | Source | Code | Key on disk? | Decoupled from data dir? |
|---|---|---|---|---|
| **1** | `NETCANON_FERNET_KEY` env var | `credentials.py:163-167` | **No** (in process env) | **Yes — iff** operator stores value off-host |
| **2** | OS keyring (Win Cred Mgr/DPAPI, macOS Keychain, libsecret) | `credentials.py:169-190` via `keyring` lib | **No** (in OS secret store) | Partially — same host, OS-scoped |
| **3** | File `$NETCANON_DATA_DIR/.fernet_key` (auto-gen) | `credentials.py:192-211`, `_data_dir()` `:70-79` | **Yes** | **No — sits next to ciphertext** |

Two subtleties the design phase must not miss:

- **`credentials._data_dir()` reads the `NETCANON_DATA_DIR` *env var* directly** (`credentials.py:79`,
  `os.environ.get("NETCANON_DATA_DIR", "data")`) — it does **NOT** go through `Settings.effective_data_dir`.
  So the file-fallback key location is governed by the env var (set in Docker `Dockerfile:80`) or defaults to
  `./data` relative to cwd. In the **desktop** modes nobody sets `NETCANON_DATA_DIR`, so if Tier 2 keyring ever
  failed, the Tier-3 key would land in `<cwd>/data/.fernet_key`, **not** `%APPDATA%\Netcanon` — a latent
  inconsistency, though in practice desktop always has a working keyring so Tier 3 never fires there. Flag for
  D2 as a `POLISH` note; not load-bearing for the SOPS verdict.
- **The in-memory model always holds plaintext** (`credentials.py` module docstring `:41-46`,
  `device_profile_store.py:10-12`). Encryption is a storage-layer concern only. This is the same property as
  pydantic `SecretStr` would give *plus* at-rest protection — see §5.

Operator-facing guidance already exists: `SECURITY.md:80-161` (full three-tier table + rekey procedure),
`.env.example:32-52`, `README.md:94-121` (Docker key-gen + `-e NETCANON_FERNET_KEY`).

---

## 3. Per-mode key-availability story + the co-location verdict

For each mode I answer the crux plainly: **does the decryption key co-locate with the ciphertext on the same
disk/host the app runs on?**

### (a) PySide6 desktop

- **Launch:** `DesktopApp.__init__` builds `desktop_settings()` then `create_app(settings)`
  (`app.py:55-58`); server bound to `127.0.0.1:8765` (`settings.py:32,72-79`). Never exposed on LAN
  (AGENTS.md "Web only" note, lines 108-109).
- **Data dir:** `%APPDATA%\Netcanon\` (frozen) or repo root (dev) — §1 table.
- **Winning key tier:** **Tier 2 — OS keyring** (Windows Credential Manager / DPAPI). `keyring` is a hard runtime
  dep (`pyproject.toml:74`) and is present in the `[desktop]`/MSI build. On a logged-in Windows session the
  keyring backend is alive, so Tier 2 always wins; Tier 3 file-fallback never fires.
- **Would a desktop user ever own an age or gpg key?** **Almost certainly not.** The desktop is explicitly a
  *single-user local utility* with no telemetry, no auto-update, no shell knob (AGENTS.md:111-128;
  preferences are a GUI dialog, not env vars). Expecting a network engineer running an MSI to generate, store,
  and rotate an `age` keypair — or to install `gpg` — is exactly the cargo-culted operational cost the seed
  warns against (`00-blackboard.md:28-32`). SOPS is a non-starter here.
- **Co-location verdict:** **YES, key co-locates with ciphertext on the same host.** The DPAPI-protected
  keyring entry and the `devices/*.json` ciphertext are both on the user's machine, both readable by the
  user's own account (DPAPI keys are scoped to the user profile). At-rest encryption here defends a **stolen
  laptop / copied `%APPDATA%` folder** where the attacker does *not* have the user's login session — DPAPI
  ties the keyring secret to the Windows account, so a raw copy of `%APPDATA%\Netcanon\devices\` off the disk
  is undecryptable without the account creds. It does **NOT** defend against malware running *as* that user.
  SOPS would give the *same* ceiling but require the user to manage a key the OS keyring manages for free.

### (b) FastAPI / uvicorn server (pip install / host-run)

- **Launch:** `uvicorn netcanon.main:app` → module-level `create_app()` (`main.py:316-323`). Binds `0.0.0.0:8000`
  by default (`config.py:100-101`), i.e. **network-exposed** — the one mode where a remote read-the-host threat
  is plausible.
- **Data dir:** `configs_dir.parent` = cwd by default, unless operator sets `NETCANON_DATA_DIR` /
  `NETCANON_CONFIGS_DIR` (`config.py:97-99`, env-prefix `NETCANON_` `config.py:111`).
- **Winning key tier:** depends on host. A headless Linux server typically has **no SecretService daemon**, so
  Tier 2 fails (`credentials.py:186-190` swallows it) and either Tier 1 (if operator set the env var) or Tier 3
  (auto-gen file) wins. SECURITY.md:92 marks Tier 1 as the recommended production tier here.
- **Co-location verdict:** **DEPENDS on operator choice.**
  - *Tier 3 (default zero-config):* **YES co-locates** — `.fernet_key` sits in the same dir as `devices/*.json`
    (`credentials.py:79,192-203`). Encryption protects only an offline copy of the data dir, NOT an attacker
    who can read the host filesystem (they grab both key and ciphertext in one `tar`).
  - *Tier 1 with env var sourced from a secret manager:* **NO co-location** — key is injected at process start
    and never written to the data disk. This is the only configuration that defends against data-dir exfil
    *and* keeps the key out of the at-rest footprint. **This is precisely what SOPS would also achieve** — and
    the env-var tier already achieves it with zero new tooling.
  - **But:** even Tier 1 does **not** defend against an attacker who can read the *running process* (env vars
    are readable via `/proc/<pid>/environ`, a memory dump, or the app's own logs if misconfigured). No at-rest
    scheme — SOPS included — closes that gap; that's an authn/authz + host-hardening problem, not an encryption
    one. SECURITY.md:499-500 already concedes "No API authentication … web operators must add auth via reverse
    proxy."

### (c) Docker

- **Launch:** `ENTRYPOINT ["uvicorn","netcanon.main:app","--host","0.0.0.0","--port","8000"]` (`Dockerfile:96`).
  No compose file in the repo (`Glob docker-compose*` → none); README shows raw `docker run` (`README.md:100-104`).
- **Volumes / data dir:** `VOLUME ["/app/configs","/app/data"]` (`Dockerfile:94`); `NETCANON_DATA_DIR=/app/data`
  (`Dockerfile:80`). Operator bind-mounts `-v $(pwd)/data:/app/data` (`README.md:102`). `definitions/` is **baked
  into the image**, not mounted (`Dockerfile:69`; README warns against mounting `README.md:110-114`).
- **Where would a key be mounted?** Two existing paths:
  - *Recommended:* `-e NETCANON_FERNET_KEY=<key>` (`README.md:100-104`, `Dockerfile` carries no key). Tier 1 wins;
    key lives in the container's process env, never on the mounted volume. The README key-gen one-liner and the
    `.env.example:41-44` already enumerate the orchestrator injection mechanisms (k8s Secret + envFrom, Compose
    `secrets:`, systemd EnvironmentFile).
  - *Zero-config fallback:* skip `-e`; Tier 3 auto-generates `/app/data/.fernet_key` (`README.md:118-121`) —
    which lands **inside the bind-mounted volume next to the ciphertext**.
- **Co-location verdict:** **DEPENDS, same shape as (b).**
  - *Tier 1 env-injected:* **NO co-location.** A leaked `data/` volume tarball is undecryptable. This is the
    Kontroll-equivalent posture, reachable today.
  - *Tier 3 default:* **YES co-locates** — `.fernet_key` and `devices/*.json` are both in `/app/data`; the
    volume is a single exfil unit. Encryption is then near-useless against anyone who gets the volume.
  - **SOPS in Docker would mean** baking `sops` + an `age`/`gpg` binary into the runtime image (it's currently a
    pure-Python slim image, `Dockerfile:48-63`, no extra binaries beyond `curl` for healthcheck), plus mounting
    an age private key into the container — which itself re-creates the co-location problem (the age key would
    sit on the same host/volume as the ciphertext unless *it* is env-injected, at which point you've reinvented
    Tier 1). Net: SOPS adds image weight and a key-mount problem to solve a problem `-e NETCANON_FERNET_KEY`
    already solves binary-free.

### (d) Windows MSI

- **Build:** `python setup_desktop.py bdist_msi` via cx_Freeze (`setup_desktop.py:1-8`, CI workflow
  `desktop-msi-publish.yml`). Bundles Python + deps + `definitions/` next to `netcanon.exe`
  (`setup_desktop.py:97-110`); installs to `C:\Program Files\Netcanon\` (`setup_desktop.py:130`). Entry point is
  the frozen desktop app (`setup_desktop.py:174-189`) — so **runtime behaviour ≡ mode (a)**.
- **Can the MSI even carry a key tool?** The `packages`/`include_files` lists (`setup_desktop.py:76-110`) bundle
  only Python libs + definitions + license notices. There is **no mechanism to ship a per-install secret** — and
  shipping one would be catastrophic (every install would share it). cx_Freeze could in principle bundle a
  `sops`/`age` *binary* via `include_files`, but it could not bundle a *key* (keys must be per-user, generated at
  runtime). And the MSI is **unsigned** today (`desktop-msi-publish.yml:20-22`) — adding a bundled crypto binary
  expands the SmartScreen/AV-flag surface for zero benefit.
- **Winning key tier:** **Tier 2 — OS keyring (Windows Credential Manager / DPAPI)**, same as (a). The MSI build
  pulls `keyring` transitively (it's a base dep, `pyproject.toml:74`, and `[desktop-build]` extends `[desktop]`
  which extends the base, `pyproject.toml:103-106`).
- **Co-location verdict:** **YES, key co-locates with ciphertext on the same host** — identical to (a). DPAPI
  keyring secret + `%APPDATA%\Netcanon\devices\*.json` ciphertext both on the user's machine. Defends a copied
  `%APPDATA%` folder lacking the Windows account; does not defend malware-as-user. SOPS/age key management has
  no realistic home in an MSI-delivered single-user app.

### Co-location summary table

| Mode | Default winning tier | Key on the data disk by default? | Decoupled posture reachable? | SOPS realistic? |
|---|---|---|---|---|
| (a) Desktop | Tier 2 keyring (DPAPI) | No (OS secret store, host-scoped) | n/a (already host-scoped) | No — user won't own an age key |
| (b) Server | Tier 1 or Tier 3 | Tier 3 **YES**; Tier 1 No | **Yes** via Tier 1 env-var | Possible but redundant w/ Tier 1 |
| (c) Docker | Tier 1 (recommended) or Tier 3 | Tier 3 **YES**; Tier 1 No | **Yes** via `-e` + orchestrator | Possible but adds binaries; redundant |
| (d) MSI | Tier 2 keyring (DPAPI) | No (OS secret store, host-scoped) | n/a | No — no per-install key home |

**Plain answer to the crux, per mode:** In **every default zero-config configuration**, the key is reachable on
the same host the app runs on (keyring on desktop/MSI; `.fernet_key` file on server/Docker Tier 3). At-rest
encryption therefore protects an **offline-disk / exfil-copy** threat only. The *single* exception is the
**env-var tier on server/Docker when the value is sourced from an off-host secret store** — and that exception
already exists in netcanon without SOPS.

---

## 4. Threat each scheme actually covers (framing for D2)

| Threat scenario | Defended by at-rest encryption? | Defended by SOPS specifically (beyond Tier 1)? |
|---|---|---|
| Stolen laptop / copied `%APPDATA%` or `data/` folder, attacker lacks the host's keyring/env | **Yes** (any of the tiers) | No extra benefit over keyring/Tier-1 |
| Leaked `data/` volume tarball from Docker (Tier 3 default) | **No** — key is in the tarball | Would require off-host age key — i.e. equals Tier 1 |
| Leaked `data/` volume, Tier 1 env-injected | **Yes** | Same as Tier 1 |
| Accidental `git commit` of `devices/*.json` | **Yes** (JSON is ciphertext) — but `.gitignore` already excludes `configs/`,`data/`,`devices/` | No extra benefit |
| Attacker can read the **running host/process** (RCE, memory dump, `/proc/<pid>/environ`) | **No** (plaintext key is in memory) | **No** — out of scope for any at-rest scheme |
| Network attacker hitting the exposed API | **No** — this is authn, not encryption (SECURITY.md:499-500) | No |

The honest conclusion this map supports: **the only threat at-rest encryption uniquely closes here is
offline-disk/exfil-copy, and netcanon already closes it.** SOPS would re-close the same threat with more moving
parts. (D2 owns the final head-to-head; this is the runtime evidence feeding it.)

---

## 5. Alternatives survey, mapped to the run-modes

The seed asks me to survey six options. **Three are already implemented** in netcanon (annotated ✅). I map each
to the modes and name the threat it covers and where its key would live.

### 5.1 OS keyring (`keyring` lib) — ✅ ALREADY USED (Tier 2)

- **What it is:** `keyring.get/set_password` against Windows Credential Manager (DPAPI), macOS Keychain, Linux
  SecretService/libsecret. Code: `credentials.py:82-114,169-190`. Hard dep `pyproject.toml:74`.
- **Key location:** OS-managed secret store, scoped to the user account; **not on the data disk**.
- **Threat covered:** offline copy of the data dir by an attacker lacking the user's OS account (DPAPI binds the
  secret to the Windows profile). Does not cover malware-as-user.
- **Fits modes:** **(a) desktop, (d) MSI** — perfect fit, zero operator action. **(b)/(c)** headless: no
  SecretService daemon → backend unavailable → falls through (the code already handles this gracefully,
  `credentials.py:186-190`). Containers can't realistically use it.

### 5.2 `age` / `pyrage` app-level encryption (the SOPS substrate)

- **What it is:** modern file encryption; `age` recipients are X25519 keypairs or SSH keys. `pyrage` is the Rust
  `age` lib's Python binding. SOPS uses `age` as one of its key backends (per R2's brief, Kontroll uses SOPS+age).
- **Key location:** an `age` *identity* (private key) file — which **must live somewhere the app can read at
  decrypt time**. On desktop/MSI that's the user's disk (co-locates with ciphertext → no gain over keyring). On
  server/Docker it's a mounted key file (co-locates unless env-injected → equals Tier 1).
- **Threat covered:** same offline-disk threat as Fernet. No additional threat over the existing scheme.
- **Fits modes:** technically all, **practically none better than what exists**. Adds a *new* dep (`pyrage` or a
  bundled `age` binary) to a tree that has zero such binaries today (`Dockerfile` is pure-Python-slim). For
  desktop/MSI it asks a single user to manage an age identity the OS keyring already manages.
- **Verdict feed:** this is the SOPS substrate; its key-location story is *identical* to Fernet's, so SOPS
  inherits the same co-location ceiling. `OVER-ENGINEERING` candidate for D2.

### 5.3 `cryptography` Fernet — ✅ ALREADY THE IMPLEMENTATION

- **What it is:** the at-rest scheme netcanon ships (`credentials.py:227-264`). AES-128-CBC + HMAC, symmetric.
- **Key from where?** the 3-tier chain (§2). "Key from where?" is *the entire question*, and netcanon answers it
  with env-var → keyring → file. This is already the strongest realistic answer for a local-first app.
- **Threat / modes:** see §3 — covers offline-disk exfil in all modes; decouples from the data dir only via
  Tier 1.
- **Verdict feed:** baseline. Any proposal must beat this, and SOPS doesn't (it's Fernet-with-extra-steps for
  the same threat).

### 5.4 pydantic `SecretStr` — in-memory ONLY, explicitly NOT at-rest

- **What it is:** a pydantic type that masks a secret in `repr()`/logs/`.model_dump()` and requires
  `.get_secret_value()` to read. **Purely an in-memory accidental-leak guard** (stops a secret printing into a
  log line or a JSON dump).
- **Key location:** n/a — there is no key; it does not encrypt anything on disk.
- **Threat covered:** accidental logging / serialization leaks of a live secret. **Does not touch the at-rest
  threat at all.** netcanon's existing analogue is the WRITE-ONLY `DeviceProfilePublic` scrub
  (seed `00-blackboard.md:44-45`) which already prevents creds leaking through API reads.
- **Fits modes:** all modes, but **orthogonal** to SOPS — it would complement, never replace, at-rest
  encryption. Worth noting to D2 only so the threat taxonomy stays clean: SecretStr ≠ at-rest, and the seed
  itself flags this.

### 5.5 Operator-supplied passphrase at startup (KDF → key, nothing persisted)

- **What it is:** prompt the operator for a passphrase at process start, run it through a KDF (PBKDF2/scrypt/
  Argon2 — `cryptography` provides these) to derive the Fernet key, hold it in memory only.
- **Key location:** **nowhere on disk** — derived fresh each boot from a human secret. This is the strongest
  off-host posture short of an external HSM.
- **Threat covered:** offline-disk exfil **and** keeps the key off the data disk entirely (better than Tier 3,
  comparable to Tier 1 without needing a secret store).
- **Fits modes:**
  - **(b) server / (c) Docker:** workable for *attended* starts, but **breaks unattended restart** — the
    scheduler (`main.py:163-204`) and container auto-restart need the app to boot without a human. A passphrase
    prompt is hostile to `docker run -d` / systemd / k8s. Could be supplied via stdin/env, but then it's just
    Tier 1 with a KDF.
  - **(a) desktop / (d) MSI:** plausible as a "master password" UX, but a regression vs the *zero-friction*
    DPAPI keyring users have today (they'd now type a password every launch). Most desktop password managers
    that do this also offer "remember on this device" — which re-introduces co-location.
- **Verdict feed:** strongest *threat* story, weakest *ergonomics* for netcanon's unattended/zero-friction
  modes. A `VIABLE`-but-narrow option for the server mode if an operator explicitly wants no key on disk and
  accepts attended restarts. Strictly better than SOPS on dependency cost (pure `cryptography`, no binaries).

### 5.6 OS-level encrypted volume (BitLocker / LUKS / FileVault)

- **What it is:** full-disk / volume encryption *underneath* the app. Zero application code. The whole data dir
  (configs, data, devices, the `.fernet_key` itself) is protected by the OS at the block layer.
- **Key location:** managed by the OS (TPM-sealed for BitLocker, LUKS keyslot, FileVault keychain) — never the
  app's concern.
- **Threat covered:** **offline-disk / stolen-hardware** — exactly netcanon's real threat — for *everything* on
  the volume, including configs/backups and the Fernet key, with **zero app complexity**. Does NOT defend a
  running host (volume is unlocked while mounted) — same ceiling as every other option.
- **Fits modes:**
  - **(a) desktop / (d) MSI:** BitLocker is on-by-default on modern Windows 11 (the platform per the env block).
    A stolen laptop is already covered at the block layer *for free*. This substantially undercuts the marginal
    value of app-level encryption on desktop.
  - **(b) server / (c) Docker:** LUKS on the host volume / encrypted EBS / encrypted PV covers the bind-mounted
    `data/` and the configs. Standard ops hygiene; orthogonal to the app.
- **Verdict feed:** the **lowest-complexity option that covers netcanon's actual threat**, and on Windows
  desktop it's often *already on*. Strong "do-nothing-in-the-app / push it to ops" candidate for D2's matrix.
  Its weakness vs app-level encryption: it doesn't protect an *accidental git commit* of a `devices/*.json`
  (the file is plaintext-on-an-encrypted-volume → plaintext once copied off) — but netcanon already mitigates
  that via Fernet *and* `.gitignore`.

### Alternatives × modes matrix

| Option | Key lives where | Threat covered | (a) Desktop | (b) Server | (c) Docker | (d) MSI | New deps? |
|---|---|---|---|---|---|---|---|
| OS keyring ✅ | OS secret store (host) | offline copy w/o OS account | **Best fit** | weak (no daemon) | n/a | **Best fit** | none (have it) |
| age/pyrage / **SOPS** | key file or env (host unless injected) | offline-disk (= Fernet) | poor (user owns key) | OK if env-injected | OK if env-injected | poor | **+binary/+pyrage** |
| Fernet ✅ | 3-tier (env/keyring/file) | offline-disk | shipped | shipped | shipped | shipped | none (have it) |
| SecretStr | nowhere (in-mem mask) | accidental log/serialize leak | orthogonal | orthogonal | orthogonal | orthogonal | none |
| Startup passphrase (KDF) | nowhere (memory) | offline-disk + off-disk key | friction | attended only | breaks `-d` | friction | none (`cryptography`) |
| Encrypted volume (BitLocker/LUKS) | OS/TPM | offline-disk / stolen HW (whole dir) | **often already on** | ops-layer | ops-layer | **often already on** | none (OS) |

---

## 6. What this means for the SOPS question (handoff to D1/D2 — no recommendation here)

- **The runtime map shows the decryption key co-locates with the ciphertext in every default mode**, so any
  at-rest scheme — Fernet *or* SOPS — protects only the offline-disk/exfil threat. `RUNTIME-BLOCKER` for the
  premise that SOPS adds protection against a host-read attacker.
- **netcanon already ships the env-var-injected posture that is SOPS's only real advantage**
  (`NETCANON_FERNET_KEY`, README.md:94-121, SECURITY.md:103-121). SOPS would be a *delivery mechanism* for that
  same env value — and the orchestrator-secret integrations the `.env.example:41-44` already names (k8s Secret,
  Compose `secrets:`, systemd EnvironmentFile) cover that delivery without SOPS.
- **SOPS imposes per-mode costs the runtime map makes concrete:** binary deps in the pure-Python Docker image
  (`Dockerfile:48-63`), an age-key-mount problem that re-creates co-location, and a key-management burden on a
  single-user desktop/MSI that will never own an age key (AGENTS.md:111-128). These are `OVER-ENGINEERING`
  signals for D2 to weigh.
- **Lighter alternatives that cover the same threat already exist or are nearly free:** the OS keyring (in use),
  encrypted volumes (often already on for the Windows desktop platform), and — if an operator wants zero key on
  disk for the server mode — a startup-passphrase KDF using the `cryptography` dep already present.

**Net (for the design phase, not a verdict):** the realistic key-availability story per mode strongly favors
"keep the existing 3-tier Fernet scheme; if anything, document/encourage Tier 1 + encrypted volumes" over
adopting SOPS. D1 should cost the SOPS integration against *this* baseline; D2 should run the head-to-head
threat matrix above and likely land NO-GO or GO-WITH-NARROW-SCOPE.

---

## 7. Citations index

- `netcanon/security/credentials.py:1-269` — Fernet scheme + 3-tier `_resolve_key` (env `:163-167`, keyring
  `:169-190`, file `:192-211`), `_data_dir()` reads `NETCANON_DATA_DIR` env directly `:70-79`.
- `netcanon/security/migration.py:18-35` — legacy plaintext → encrypted migration helper.
- `netcanon/storage/device_profile_store.py:5-16,61-77,86-125` — encrypt-on-save / decrypt-on-load, ciphertext
  at `{data_root}/devices/{id}.json`.
- `netcanon/storage/schedule_store.py:9-13,46-54,76-100` — legacy inline-device-list creds encrypted too.
- `netcanon/main.py:69,98-160,318` — `create_app` factory, lifespan store wiring off `effective_data_dir`,
  module-level production `app`.
- `netcanon/config.py:97-128` — `Settings`, `NETCANON_` env prefix, `effective_data_dir` derivation.
- `netcanon_desktop/app.py:36,55-58` — desktop launches `create_app(desktop_settings())`.
- `netcanon_desktop/settings.py:32,48-80,83-99` — loopback `:8765`, frozen vs dev paths, `%APPDATA%\Netcanon`.
- `Dockerfile:48-96` — pure-Python slim runtime, `NETCANON_DATA_DIR=/app/data`, `VOLUME`, uvicorn entrypoint.
- `setup_desktop.py:1-8,76-110,130,174-189` — cx_Freeze MSI bundle contents + frozen entry point.
- `.github/workflows/desktop-msi-publish.yml:20-22,57-135` — unsigned MSI build, no key shipped.
- `pyproject.toml:52-106` — `cryptography`+`keyring` base deps; `[desktop]`/`[desktop-build]` extras.
- `SECURITY.md:80-161,499-503` — three-tier table, rekey, key-loss/no-auth threat rows.
- `README.md:94-121` — Docker key-gen + `-e NETCANON_FERNET_KEY` + volume mounts.
- `.env.example:32-52` — operator key guidance + orchestrator injection mechanisms.
- `tests/unit/test_data_dir_resolution.py:34-103` — `effective_data_dir` resolution pins.
- `AGENTS.md:108-128` — desktop is loopback-only, single-user, no telemetry/auto-update (no age-key home).
