# 11 — Research: how SOPS works in Kontroll, and what transfers to netcanon

**Run:** 2026-06-17-sops-evaluation · netcanon ultracode blackboard · **Agent:** R2 (research, read-only)
**Scope:** study the sibling **Kontroll** project's SOPS usage (key backend, key location/provisioning,
decrypt timing, what it bought / cost) and judge what of that model transfers to netcanon — a single
local-first app (PySide6 desktop / FastAPI server / Docker / Windows MSI) — vs what is structurally
Kontroll-specific.

All Kontroll citations are `file:line` from `~/Desktop/kontroll` (read-only). I did **not**
read or reproduce any secret material — only the encrypted *shape* and the plumbing.

**Bottom line up front:** Kontroll's SOPS works because it is a **multi-node, multi-service, Ansible-deployed
control plane** with a clean *physical* separation between (a) the **control VM** that holds the age private
key and renders secrets and (b) the **fleet of containers/devices** that consume the rendered plaintext but
never hold the key. That separation — *the decryptor is not the ciphertext-host* — is the entire security
value, and it is **the one property netcanon's run-modes cannot replicate**: in every netcanon run-mode the
process that would decrypt and the data-dir that holds the ciphertext sit on the same machine, under the same
user, with the key necessarily reachable by the same process. The render-time-Ansible model, the control-VM
key custody, and the multi-service `.env` composition are **all Kontroll-specific and do NOT transfer**. What
*can* be borrowed is narrower: the *discipline* (one-file-per-domain, value-free generated manifests, never
log the plaintext, `0600` resting place) and the *break-glass / least-privilege key-group* idea — but those
are postures, not a reason to adopt SOPS itself. Full transferability matrix in §6.

---

## 1. What Kontroll *is* (the context SOPS lives in)

Kontroll is, per its own SECURITY.md, a **single-user homelab control plane running on a dedicated VM on the
Proxmox cluster, Management VLAN 11** (`SECURITY.md:18-21`). It **holds standing credentials to every managed
device** — FortiGate/Cisco/OPNsense/RouterOS API tokens + enable creds, Proxmox API tokens, SSH keys for
docker hosts, Grafana/Semaphore admin passwords, SNMPv3 creds, an ACME DNS token, etc. (`instance/secrets/README.md:10-19`).
Its trust model explicitly makes "encryption at rest **mandatory**" *because* it is a long-lived networked box
holding live device control credentials, in contrast to "the migration repo (frozen, local, plaintext
accepted)" (`SECURITY.md:20-21`). **That contrast is the headline finding for this evaluation: Kontroll's own
authors classify a "frozen, local, plaintext" repo — which is what netcanon's data-dir is — as a context
where plaintext is *accepted*.**

Architecturally it is a stack: Semaphore (CI/runner), Grafana, Prometheus, Loki+Vector (logging), Homepage,
an onboard-GUI, an API, optional Caddy ingress — orchestrated by **Ansible** (`deploy-stack.yml`, 721 lines)
and deployed as **Docker Compose** services on the VM. This is a fundamentally different shape from a single
app the operator double-clicks.

---

## 2. (1) Key backend, where the private key physically lives, and how it's provisioned

### 2.1 Backend: SOPS + **age** (not GPG)

The encryption backend is **[age](https://age-encryption.org)** — X25519 recipients written as `age1…`
public keys — wrapping SOPS's native AES256-GCM data encryption. Confirmed in three independent places:

- The creation-rule recipients are all `age:` key-groups with `age1…` public keys, e.g.
  `instance/.sops.yaml:26-32` lists three `age1…` recipients for the operational domains.
- The encrypted files carry `sops: age:` blocks with `-----BEGIN AGE ENCRYPTED FILE-----` per-recipient
  envelopes and `recipient: age1…` — e.g. `instance/secrets/network.sops.yml:5-32` (the data fields above are
  `ENC[AES256_GCM,data:…,iv:…,tag:…,type:str]`, the SOPS standard).
- SECURITY.md names it outright: **"Secrets encrypted at rest (SOPS + age)"** (`SECURITY.md:34`), age key on
  the control VM (`SECURITY.md:36-37`).

The SOPS version is pinned in the file MAC block: `version: 3.13.1` (`instance/secrets/network.sops.yml:36`).

### 2.2 Three recipients per domain — least-privilege key-groups

`instance/.sops.yaml` is the creation-rule ruleset. Its design (`instance/.sops.yaml:7-20`) is explicitly
least-privilege per secret domain, with up to **three** age recipients (any one private key decrypts — OR
semantics within a key-group, `:18`):

1. **Control VM operational key** — `~/.config/sops/age/keys.txt` on the control VM, the day-to-day
   decryptor, never committed. On **every** domain.
2. **Offline break-glass recovery key** — private half stored **offline** on a trusted machine, never on the
   VM / repo / `local/`. Recovery only. On **every** domain.
3. **Scoped Semaphore runner key** — `~/.config/semaphore/age.key` on the control VM and inside Semaphore's
   encrypted store so the runner can decrypt at job time. Present **only** on the operational domains
   (`network`, `proxmox`) — `instance/.sops.yaml:24-35` — so a Semaphore breach cannot decrypt the service
   secrets (`compute`/`dashboards`/`semaphore`/`acme`/`snmp_observability`/`logging_file_tail`), which use
   only control + break-glass (`*base_recipients`, `:39-66`).

The path-regex is **basename-anchored** (`(^|/)<domain>\.sops\.ya?ml$`) and the template warns that a path
prefix would fall through to the catch-all and silently drop the scoped key (`instance.example/.sops.yaml:14-16`).

### 2.3 Physical location of the private key: **the control VM, on disk, mode 0600**

`SECURITY.md:52-54`: *"the age private key lives only at `~/.config/sops/age/keys.txt` (mode 600) on the
control VM, is never committed."* This is the canonical operational decryptor.

- The **operator workstation** is **not** the resting place of the day-to-day key — the key lives on the
  control VM, which is itself the long-lived networked box. (The *break-glass* key lives offline on a trusted
  machine, but that's recovery-only, never the active decryptor.)
- `.gitignore` blocks the key; `gitleaks` (pre-commit + CI) has a custom rule that always catches an
  `AGE-SECRET-KEY` (`SECURITY.md:40,108-109,368`).

### 2.4 Provisioning: `kontroll-init.py` mints it locally with `age-keygen`

A brand-new node runs `scripts/kontroll-init.py` (the CLI half of a keygen split):

- `ensure_control_key()` runs `age-keygen -o ~/.config/sops/age/keys.txt` then `chmod 0o600`
  (`scripts/kontroll-init.py:71-78`; const `AGE_KEY_FILE` at `:41`).
- `--fresh` scaffolds a private `instance/` overlay from the shipped `instance.example/` skeleton and writes a
  `.sops.yaml` naming **only the freshly-minted control key** (never inheriting another instance's recipient)
  — `scripts/kontroll-init.py:20-26,170-194`. The example ruleset (`instance.example/.sops.yaml:3-5`) is a
  template whose placeholder `age1example…` recipient (`:24`) is replaced by `--fresh`.
- The init prints the public key + a reminder that *"the private … decrypts every secret"* and to keep a copy
  in a password manager (`scripts/kontroll-init.py:194-195`). kontroll-init runs **locally as the trusted
  operator** (no network surface), which is the deliberate exception to Kontroll's otherwise never-persist
  rule (`SECURITY.md:376-380`).
- A separate **GUI keygen** surface (`/keygen/{role}`) mints break-glass / Semaphore keys **show-once** — the
  private half is returned in exactly one response and **never** written to the box/repo/audit/log
  (`SECURITY.md:334,348-353`). New recipients are added to `.sops.yaml` as *public* recipients via
  anchor-preserving, idempotent, parse-verified text insertion, with the decrypt-needing `sops updatekeys`
  re-wrap left as a **deferred operator step, never auto-run** (`SECURITY.md:353-360`).

**Key custody summary:** age private key generated *on the control VM* by `age-keygen`, persisted 0600 at
`~/.config/sops/age/keys.txt`, gitignored, never leaves the VM; a scoped Semaphore key on the same VM +
Semaphore store; an offline break-glass key on a separate trusted machine. The custody story is rich because
there are **multiple distinct principals** (operator, Semaphore runner, recovery) on **multiple machines**.

---

## 3. (2) Decryption is RENDER-TIME (Ansible builds a plaintext `.env` once at deploy)

**Render-time, decisively.** Decryption happens **once per deploy**, inside Ansible, and produces a plaintext
`docker/.env` that the containers then read. The app/containers **never decrypt SOPS themselves** — they have
no age key (the deliberate "no-key posture"). Evidence:

### 3.1 The decrypt + render task

The play *"Render docker/.env from SOPS and bring up the stack"* (`deploy-stack.yml:111-115`,
`connection: local`, runs on the control node) does the decrypt:

- **Platform-core domains** are decrypted by `community.sops.sops` lookups in the play `vars:`, fail-CLOSED
  (no `errors='ignore'`): `_sem` / `_dash` (`deploy-stack.yml:139-140`).
- **Device/consumer domains** are decrypted **by name** as the *union* of domains the generated manifest
  references, fail-SOFT per domain via the `kontroll_sops_domain` filter
  (`deploy-stack.yml:148-159`). The decrypt is a **lazy** Jinja expression dereferenced **only inside the
  one `no_log: true` render task** — never `set_fact`'d — so no decrypted value persists outside that boundary
  (the M3 constraint, `deploy-stack.yml:152-159`).
- The render task *"Render docker/.env (secrets — never logged)"* writes the file with `mode: "0600"`,
  operator-owned, gitignored, `no_log: true` (`deploy-stack.yml:246-300`). It emits hardcoded platform-core
  lines (`SEMAPHORE_*`, `GRAFANA_ADMIN_PASSWORD`, …, `deploy-stack.yml:256-267`) plus a single generic loop
  composing each device env var from its domain + template via `kontroll_render_token`
  (`deploy-stack.yml:292-293`).
- The **snmp** secret is a *third* injection shape: decrypted task-local and rendered into a config FILE
  (`prometheus/exporters/snmp/snmp.yml`, `0600`, gitignored), not the `.env` (`deploy-stack.yml:367-385`).
  The `logging_file_tail` SSH private key is rendered into a file the same way (`deploy-stack.yml:401-417`).

### 3.2 The decrypt-by-name mechanism (`kontroll_sops_domain`)

`ansible/filter_plugins/kontroll_sops.py` is a ~25-line filter: given a domain name (= the SOPS file stem)
and the secrets dir, it shells out to the **`sops` binary** (`subprocess.run(["sops", "--decrypt", path]…)`,
`:34`), `yaml.safe_load`s stdout, and returns the dict — or `{}` if the file is absent, sops is missing, or
decrypt fails (fail-soft, never raises, never logs the plaintext) (`kontroll_sops.py:25-43`). It exists so a
new credentialed device is **zero spine edit**: the domain name IS the file stem, so deploy-stack decrypts the
*union* of manifest-referenced domains without a hand-maintained `domain→dict` map.

### 3.3 The N-field token composition (`kontroll_render_token`)

`ansible/filter_plugins/kontroll_token.py` composes a `.env` value from a decrypted domain dict + a
`str.format` template over that domain's **field NAMES** (`:20-38`). A 1-field exporter env (`"{proxmox_api_user}"`)
and an N-field composed token (`"{user}!{id}={secret}"`) render through the **identical** call — a 1-field map
is the degenerate template. Fail-soft: if the template is empty or any referenced field is missing/blank, the
whole token renders `''` (`:25-34`) — the source then auths with an empty header and ships nothing, rather
than a half-formed token. Never raises (`:27,30,38`).

### 3.4 The manifest is value-free; secrets exist plaintext only in the rendered `.env`

`config/secret-env.manifest.generated.yml` (generated by `scripts/gen-secret-env.py`) holds **ZERO secret
values** — only env-var NAMES, domain NAMES, and field-NAME templates (`secret-env.manifest.generated.yml:1-19`;
generator contract `gen-secret-env.py:21-26`). It fail-CLOSES at *generate* time on a malformed descriptor
(non-UPPER_SNAKE env name, collision with a platform-core var, unsafe template field) — `gen-secret-env.py:52-122`.
The plaintext secret lives in exactly one place: the gitignored `0600` `docker/.env`, written under `no_log`
(`.env.example:1-4` confirms the example is value-free and the real values get decrypted in by a deploy step).

**So the model is:** ciphertext at rest in `instance/secrets/*.sops.yml` (committed) → Ansible decrypts the
union once at deploy under `no_log` → plaintext `docker/.env` (0600, gitignored, never committed) → Docker
Compose `--env-file` feeds the containers (`deploy-stack.yml:710,715`). **The runtime app never touches SOPS
or holds the age key.**

---

## 4. (3) What SOPS bought Kontroll, and what it cost

### 4.1 What it bought

| Benefit | Why it's real *for Kontroll* | Cite |
|---|---|---|
| **Encrypted secrets safely committed to git** | Kontroll's secret files ARE committed (`*.sops.yml` tracked); the canonical repo + offsite backups can hold them because the age key is not in any of those artifacts. This is the whole "GitOps for a control plane" payoff. | `SECURITY.md:37-38,150-152`; `network.sops.yml` is a committed ciphertext file |
| **Decryptor ≠ ciphertext-host (the load-bearing property)** | The age key lives on the control VM; the *containers* and *managed devices* that consume the rendered `.env` never hold it. A stolen container image, a compromised exporter, or a read of the git repo yields no plaintext. | no-key posture `SECURITY.md:280-282,301-313`; key only on VM `SECURITY.md:52-54` |
| **Multi-principal least-privilege** | Three recipients let a Semaphore-runner breach be scoped to 2 of 8 domains, and break-glass survive VM loss — meaningful *because there are genuinely separate principals on separate machines*. | `instance/.sops.yaml:7-66` |
| **Break-glass against key loss** | Two recipients per domain → losing the VM key is recoverable, not catastrophic. | `SECURITY.md:41-44` |
| **Backup-artifact safety** | Encrypted secrets are safe to host offsite (`scripts/backup.sh`); the age keys never leave. | `SECURITY.md:140,150-152` |

### 4.2 What it cost

| Cost | Detail | Cite |
|---|---|---|
| **Rich key-management ceremony** | A keygen split (CLI `kontroll-init` + GUI `/keygen/{role}` show-once), an offline break-glass custody process, a scoped Semaphore key, `sops updatekeys` re-wrap as a deferred operator step, anchor-preserving `.sops.yaml` edits, parse-verify gates. | `SECURITY.md:334-368`, `kontroll-init.py` |
| **`age` can't encrypt-without-decrypt** | A standing decrypt key in any always-on service would be a liability, so Kontroll deliberately keeps the API/Semaphore **no-key** and defers cred-encryption to an out-of-band trusted runner. This is an architectural constraint SOPS *imposed*. | `SECURITY.md:280-282` |
| **A binary dependency** | `sops` + `age` binaries must be present on the control node (a deploy prereq), and the Semaphore runner image is built *"stock + sops/age + baked collections"* (`deploy-stack.yml:446`). The decrypt filter shells out to the `sops` binary (`kontroll_sops.py:34`). | `kontroll_sops.py:16`, `deploy-stack.yml:446` |
| **A config-injection sink + validation tax** | Turning "which env var gets which value" into generated data created a fail-closed-at-generate-time validation surface (`_SAFE_ENV`, field-name allow-list, platform-core-collision gate) that the secret-injection review made a **blocker** (M2, the run's highest-severity finding). | `gen-secret-env.py:79-122`; `40-adversary.md:169-204` |
| **A no_log laziness invariant** | The decrypted union must stay a lazy var dereferenced only inside `no_log` tasks; a play-level `set_fact` of a decrypted dict leaks under `-v`/`debug` (M3, a blocker). | `40-adversary.md:102-119` |
| **Path-coupling / overlay-seam fragility** | The deploy READ path and the GUI onboarding WRITE path must resolve `.sops.yml` through the same seam or a future relocation silently splits them — a fail-soft-hidden ghost (M4). | `30-security-blindjoe.md:51-58`; `40-adversary.md:357` |
| **Fail-soft hides typos** | A typo'd `secret_domain`/field renders an empty token with no error — the review wanted a value-free "declared-but-absent domains" diagnostic to convert the silent cliff into a hint (D1). | `40-adversary.md:360` |

### 4.3 The adversary's own framing of the threat

Critically, the secret-injection review's threat model is **not a remote attacker** — *"the stack is
mgmt-VLAN-only, single-operator; [the adversary] is drift and a future contributor"* (`30-security-blindjoe.md:29-32`).
The legitimate resting place of a plaintext secret at deploy is the `0600` gitignored `docker/.env`
(`30-security-blindjoe.md:23-26`). So even in Kontroll — a networked box holding live device creds — the SOPS
machinery's day-to-day adversary is *config drift*, not an attacker reading the disk. The encryption-at-rest
benefit (§4.1 row 1) is real but is fundamentally about **what's safe to commit/back-up**, not about
defending a running box whose operator-trusted process can already reach the key.

---

## 5. (4) The Kontroll model, decomposed: what *could* map vs what is structurally Kontroll-specific

The seed asks to itemize Kontroll's model against a single local-first app. Here is the decomposition,
mechanism by mechanism.

### 5.1 The structural mismatch in one sentence

Kontroll has a **physical custody boundary** — the age key lives on the control VM; the *consumers* (Docker
containers, managed devices, the offsite backup, the git remote) are **different artifacts that never hold the
key**. netcanon has **no such boundary in any run-mode**: the process that would decrypt and the data-dir
holding the ciphertext are the same machine, same OS user, and any key the app can use at startup is a key an
attacker who already has that data-dir/process can also use. **SOPS's central value (decryptor ≠
ciphertext-host) evaporates when they co-locate.**

### 5.2 Mechanism-by-mechanism transfer matrix

| Kontroll mechanism | Cite | Transfers to netcanon? | Why / why not |
|---|---|---|---|
| **age key on a separate long-lived control VM, never on the consumer** | `SECURITY.md:52-54` | **NO** | netcanon's desktop/server/docker/MSI all run the decryptor on the same box as the data-dir + key. There is no second machine to be the custody boundary. The single most load-bearing property does not exist. |
| **Render-time Ansible decrypt → one plaintext `.env`** | `deploy-stack.yml:111-300` | **NO** | netcanon has no Ansible deploy step and no orchestrator that runs once on a trusted node distinct from the app. The closest analog (an entrypoint that decrypts on container start) would itself need the key *in the container*, recreating the co-location problem. |
| **Multi-service `.env` composition (manifest + generic loop + N-field token)** | `gen-secret-env.py`, `kontroll_render_token` | **NO** | This solves "compose creds for *many* containers/exporters from *many* domains with zero spine edit." netcanon is ONE process; there is no fleet of consumers to compose for. The whole modularity machinery is answering a question netcanon doesn't have. |
| **Multi-principal key-groups (control + break-glass + scoped Semaphore)** | `instance/.sops.yaml:7-66` | **NO (no second principal)** | Least-privilege across principals presupposes ≥2 principals on ≥2 trust levels. netcanon is single-user, single-process; there is no Semaphore-runner equivalent to scope away from, and no separate machine for break-glass to be meaningfully *offline* relative to. |
| **Committing encrypted secrets to git (the GitOps payoff)** | `network.sops.yml` (tracked) | **NO — and netcanon's posture is the opposite** | netcanon must **never** commit secrets at all (AGENTS.md Hard Rule "Never commit real credentials"); its data-dir (`configs/`, device-profile store) is **gitignored, not committed-encrypted**. Kontroll commits ciphertext *on purpose*; netcanon's design is "secrets never enter the repo," which removes the very problem SOPS-in-git solves. |
| **The `sops` + `age` binary dependency** | `kontroll_sops.py:34`, `deploy-stack.yml:446` | **NO (and it's a real cost)** | netcanon ships as a pip wheel / Docker image / **Windows MSI**. Bundling a `sops` + `age` binary into the MSI and the Docker image, on every platform, for a benefit that §5.1 already nullified, is pure packaging tax. (A pure-Python `age`/`Fernet` path avoids the binary but doesn't restore the custody boundary.) |
| **`no_log` discipline on secret-handling tasks** | `deploy-stack.yml:300,385,417` | **PARTIAL (as posture, not via SOPS)** | "Never log the decrypted value" is good hygiene netcanon already practices (the `DeviceProfilePublic` WRITE-ONLY scrub, per MEMORY). It's a logging discipline, not a reason to adopt SOPS. |
| **One-file-per-domain, value-free generated manifests, `0600` resting place** | `instance/secrets/README.md`, `.env.example:1-4` | **PARTIAL (as discipline)** | These are sound *patterns* portable to any secret store (including netcanon's existing OS-keyring / Fernet options the runtime-deployment agent is surveying). They argue for *care*, not for *SOPS specifically*. |
| **The "frozen, local, plaintext accepted" classification** | `SECURITY.md:20-21` | **DIRECTLY APPLICABLE — to netcanon** | Kontroll's authors explicitly put a *local, frozen* repo in the "plaintext accepted" bucket and reserved mandatory-encryption for the *networked control plane*. netcanon's data-dir is the former. This is precedent **against** adopting SOPS, written by the same operator. |

### 5.3 The one genuine half-overlap: backup *artifacts*

netcanon's backup artifacts (the fetched device configs in `configs/<host>.<ext>`) *do* routinely contain
device secrets (hashed/encrypted passwords, SNMP/RADIUS keys) — analogous to Kontroll's device creds. But the
parallel breaks on custody: Kontroll's encrypted device creds are safe to host *because the age key is on a
different box*. A netcanon operator's `configs/` dir sits next to whatever key the netcanon process uses; an
attacker with the data-dir has both. The honest transfer here is "treat `configs/` as sensitive-at-rest"
(OS-level disk encryption / restrictive perms / the existing sanitiser for *sharing*), not "SOPS-encrypt
`configs/` with a key the same machine holds."

---

## 6. Synthesis for this run (hand-off to D1/D2/V1 and the main thread)

1. **Key backend / location / provisioning (Q1):** SOPS + **age**; private key on the **control VM** at
   `~/.config/sops/age/keys.txt` (0600), minted locally by `age-keygen` via `kontroll-init.py`; plus an
   **offline break-glass** key and a **scoped Semaphore-runner** key. Three-recipient least-privilege
   key-groups, basename-anchored creation rules.

2. **Decrypt timing (Q2):** **RENDER-TIME.** Ansible's `deploy-stack.yml` decrypts the union of SOPS domains
   once per deploy (via `community.sops.sops` lookups + the `kontroll_sops_domain` filter), under `no_log`,
   into a gitignored `0600` `docker/.env`. The app/containers **never decrypt SOPS at runtime** and hold no
   age key (the deliberate no-key posture).

3. **Bought vs cost (Q3):** Bought = encrypted secrets safe to **commit/back-up** + a real **decryptor ≠
   ciphertext-host** boundary + multi-principal least-privilege + break-glass. Cost = a binary dependency,
   rich key-management ceremony, an `age`-can't-encrypt-without-decrypt architectural constraint forcing the
   no-key posture, a config-injection-sink validation tax, a `no_log`-laziness invariant, and overlay-seam
   path-coupling fragility — and even then the day-to-day adversary the review modeled is *drift*, not a disk
   reader.

4. **Transferability verdict (Q4):** **The Kontroll SOPS model is structurally Kontroll-specific and does NOT
   transfer to netcanon.** The load-bearing property (key on a separate box from the consumers + committing
   ciphertext to git) has no analog in any netcanon run-mode — desktop/server/docker/MSI all co-locate the
   decryptor, the key, and the ciphertext on one machine under one user. The render-time Ansible decrypt, the
   multi-service `.env` composition, the control-VM key custody, and the multi-principal key-groups are all
   answers to multi-node/multi-service/GitOps questions netcanon does not pose. The same operator's own
   SECURITY.md classifies a *"frozen, local"* repo as **"plaintext accepted,"** explicitly reserving
   mandatory encryption for the *networked* control plane — which is precedent *against* porting SOPS here.

   **What transfers is discipline, not the mechanism:** one-file-per-domain organization, value-free generated
   artifacts, never-log-the-plaintext, `0600`/gitignored resting places, and a break-glass mindset for
   whatever lighter mechanism netcanon already has (OS keyring / Fernet — see the runtime-deployment agent).
   These are reasons to be *careful*, not reasons to adopt SOPS.

   **Severity tag for V1:** this report lands on **`THREAT-MISMATCH` + `OVER-ENGINEERING`** for any proposal
   to port Kontroll's SOPS model wholesale, and **`RUNTIME-BLOCKER`** for the specific claim that SOPS would
   protect a running netcanon instance (the decryption key co-locates with the ciphertext in every run-mode,
   so there is no real protection against the local-disk-read / running-process adversary). I flag the one
   *non*-mismatched sliver — backup-artifact-at-rest sensitivity (§5.3) — to D2 to test against the lighter
   alternatives, since that's the only place a netcanon "encrypt-at-rest" story has any teeth, and even there
   OS-level disk encryption likely dominates SOPS.

---

*Verified against source this run: `kontroll/instance/.sops.yaml` (full), `kontroll/instance.example/.sops.yaml`
(full), `kontroll/instance/secrets/network.sops.yml` (shape only) + `instance/secrets/README.md` (full),
`kontroll/ansible/filter_plugins/kontroll_sops.py` + `kontroll_token.py` (full),
`kontroll/scripts/gen-secret-env.py` (full) + `config/secret-env.manifest.generated.yml` (full),
`kontroll/ansible/playbooks/deploy-stack.yml` L108-300 + L367-417 + L446 + L710-715 (the decrypt + render +
runner-image + bring-up), `kontroll/docker/.env.example` L1-55, `kontroll/SECURITY.md` L1-70 + the
grepped C1/C10/keygen sections (L52-54, 280-313, 334-380), `kontroll/scripts/kontroll-init.py` (grepped
key-provisioning L6-26,41-78,170-195,237-241), and the secret-injection review
`docs/reviews/2026-06-17-secret-injection/{00,40,99}.md` (full) + `30-security-blindjoe.md` L1-120.*
