# 04 — Instance Hardening (No-Retention Controls)

Every flag here is a whitepaper claim. The warden applies them verbatim from
one constants block; [08](08-testing-verification.md) proves each on the live
system.

## Container spec (per instance)

```python
# warden constants — the single source of truth cited by the whitepaper
INSTANCE_PORT = 8000  # netcanon's listen port (config.py:266; Dockerfile EXPOSE 8000)

INSTANCE_SPEC = dict(
    image        = "ghcr.io/netcanon/netcanon@sha256:<PINNED_DIGEST>",
    #              I6: digest-pinned. Base stays python:3.14-slim-bookworm —
    #              Alpine is REJECTED (it invalidates the hash-locked
    #              requirements.lock → musllinux/source builds, for a ~10% RSS
    #              win that changes no sizing tier). The digest + hash-lock
    #              chain is itself a whitepaper asset (I6).
    read_only    = True,                          # I1: read-only rootfs
    tmpfs        = {                              # every writable path in RAM
        "/tmp":         "rw,noexec,nosuid,size=64m",  # PASTE path — see note
        "/app/data":    "rw,noexec,nosuid,size=32m",  # jobs/devices/schedules root
        "/app/configs": "rw,noexec,nosuid,size=8m",   # image VOLUME — MUST be tmpfs
    },
    volumes      = None,                          # I1: zero volumes, ever
    network      = "demo-int",                    # I4: internal-only network
    mem_limit    = "256m",
    memswap_limit= "256m",                        # no swap headroom (I2)
    nano_cpus    = 500_000_000,                   # 0.5 CPU
    pids_limit   = 128,
    cap_drop     = ["ALL"],
    security_opt = ["no-new-privileges:true"],
    # No `user` override: the image already runs non-root as uid 1000 via
    # `USER app` (Dockerfile:96). Forcing a different uid breaks tmpfs
    # ownership on the mounts above.
    labels       = {                              # hard-TTL backstop keys
        "demo.created_at": "<unix-ts>",           # swept on warden startup +
        "demo.instance":   "<create-time random id>",  # host systemd timer — see 03
        #              NOT the token: it does not exist at create time and labels
        #              are immutable. The assignment→token binding + the live
        #              deadline = assignment_time + HARD_TTL live in warden RAM.
    },
    environment  = {
        "NETCANON_API_KEY":    "<per-instance random>",  # see 03
        "NETCANON_HOST":       "0.0.0.0",                # internal net only
        "NETCANON_PORT":       str(INSTANCE_PORT),       # = 8000
        "NETCANON_LOG_LEVEL":  "warning",               # bodies never logged — see note
        "NETCANON_FERNET_KEY": "<per-instance random>",  # RAM-only; no key file
    },
    log_config   = {"type": "none"},              # I2: Docker captures no stdout
)

# Teardown: container.remove(v=True, force=True). v=True guarantees no
# anonymous volume can outlive the instance — the belt to the tmpfs
# suspenders above.
```

Notes:

- **`/app/configs` MUST be tmpfs.** The image declares
  `VOLUME ["/app/configs", "/app/data"]` (Dockerfile:113). Mounting a tmpfs
  over `/app/data` alone leaves `/app/configs` to Docker's default handling —
  an **anonymous host-disk volume** that survives the container and falsifies
  the "zero volumes" claim (**I1**). Both declared VOLUME paths get an explicit
  in-RAM tmpfs; `remove(v=True, …)` sweeps any anonymous volume regardless.
- **`/tmp` is on the paste path, not hygiene.** Starlette spools multipart
  uploads larger than ~1 MB to `/tmp`; a pasted config large enough to spool
  lands there. Keeping `/tmp` in RAM (`noexec,nosuid`) is therefore a
  **deliberate no-retention control** for submitted payloads, not incidental
  cleanliness.
- **No Fernet key file is ever created (claim 7).** Passing
  `NETCANON_FERNET_KEY` is Tier 1 of netcanon's key resolution
  (`security/credentials.py`), so the Tier-3 file fallback at
  `$NETCANON_DATA_DIR/.fernet_key` is **never written**. The key lives only in
  the instance's RAM and dies with it — the claim is "no key file is created,"
  not merely "the file is in tmpfs."
- **`NETCANON_LOG_LEVEL=warning` is safe.** netcanon never logs request bodies
  at **any** level; only parsed config *fragments* appear at `debug`. `warning`
  excludes even those, so no payload can reach a log line regardless of driver.
- `log_config type=none` is the bluntest correct tool: the daemon keeps **no**
  container output at all. Operational visibility comes from warden metadata
  logs, which contain no payloads. If instance stderr is ever needed for
  debugging, flip to `local` with `max-size=1m` **in a dev environment only** —
  never in prod; the whitepaper states `none`.
- **Labels drive the hard-TTL backstop.** `demo.created_at` / `demo.instance`
  are what the warden's startup sweep and the independent host systemd timer
  match on to force-remove orphaned instances (see
  [03](03-warden-spec.md#lifecycle-rules)); without them a warden crash would orphan
  live containers that the in-memory dict no longer tracks. Neither label is the
  session token — the token does not exist at create time and labels are
  immutable, so the live per-instance deadline (`deadline = assignment_time +
  HARD_TTL`, 900 s) lives only in warden RAM, never in a label. The reaper
  **recycles any unassigned pool instance older than `POOL_MAX_AGE − reaper_period`
  (~290 s)** (destroy + refill), so no instance is ever *assigned* more than
  `POOL_MAX_AGE` (300 s) after creation. The independent host
  `systemd` timer (sweep cadence `every 60 s`) therefore only needs a
  creation-age ceiling of `HARD_TTL + POOL_MAX_AGE + 120 s slack = 1320 s` (22 min) on
  `demo.created_at` — provably looser than any live session's 900 s
  assignment-relative deadline, so it can never fire early. Idle and heartbeat
  reclaim are **warden-live-only**; this systemd backstop is what bounds the
  warden-dead path (≤ ~23 min after creation).
- **Network egress + segmentation:** `demo-int` is created with
  `internal: true` → no outbound internet (**I5**); instances receive addresses
  in `172.31.0.0/24` and the **warden holds the static address `172.31.0.2`**.
  Do **not** reach for `enable_icc=false`: it is all-or-nothing on the bridge and
  would also cut **warden→instance**, breaking the proxy. Implement the matrix
  with explicit nftables rules on the bridge's **default-drop** forward path,
  evaluated in order:

  ```
  1) ct state established,related                      accept   # return path for warden→instance
  2) ip saddr 172.31.0.2  tcp dport 8000               accept   # warden → instance ALLOW
  3) ip daddr 172.31.0.2                               drop     # instance → warden DENY
  4) ip saddr 172.31.0.0/24 ip daddr 172.31.0.0/24     drop     # instance → instance DENY
  5) (default)                                         drop
  ```

  Rule 4 matches by **subnet** (`172.31.0.0/24`), not `iifname "demo-int"`: a
  Docker-created bridge is named `br-<hash>` unless pinned with
  `driver_opts { com.docker.network.bridge.name: demo-int }`, so subnet matching is
  robust regardless of the interface name. The ruleset lives in the `DOCKER-USER`
  chain scoped to the demo bridge. Rule 2 trusts the source IP; `cap_drop: [ALL]`
  (no `CAP_NET_RAW`) is what stops a compromised instance source-spoofing
  `172.31.0.2` — bind the warden's veth with `iifname` as a second layer where the
  interface name can be pinned.

  The socket-proxy is unreachable from instances **by construction** — it sits on
  the dedicated `warden-sock` network (warden + socket-proxy only), which
  instances never join, on top of the instance→warden DENY above (**I4**). See
  [03](03-warden-spec.md#socket) for the docker-socket proxy that is the true privilege
  boundary — `read_only` + non-root on the warden container do **not**
  constrain the socket API, which is root-equivalent on the host.

## <a name="route-allowlist"></a>Feature surface reduction

The demo needs exactly two flows — **migrate/translate** and **sanitize** —
plus the read-only capability and target-profile lookups their UIs call. It
must NOT expose netcanon's device-backup, inventory, schedule, saved-config, or
definition-management surfaces. No-egress makes those inert, but the warden
also enforces a **default-deny route allowlist** (anything not listed → 404 at
the warden). netcanon has **no root-path support** and its UI uses absolute
URLs, so the warden routes allowlisted absolute paths **by session cookie**
(see [03](03-warden-spec.md)), not by path-prefix. There are **no static assets** to
allow — all CSS/JS is inlined into the pages — and there is **no
`/api/v1/translate` route**; translation runs through `POST
/api/v1/migration/plan` and its typed sub-plans.

**ALLOW** (verified against the image route table):

- `GET  /migrate`
- `GET  /sanitize`
- `GET  /health`
- `GET  /api/v1/migration/adapters`
- `GET  /api/v1/migration/adapters/{name}/capabilities`
- `GET  /api/v1/migration/target-profiles` (+ `/{vendor}/{model}`)
- `POST /api/v1/migration/plan` (+ `/plan/ports`, `/plan/vlans`,
  `/plan/local_users`, `/plan/snmp`, `/plan/snmpv3`)
- `POST /api/v1/migration/detect`
- `POST /api/v1/sanitize`

**BLOCK** (default-deny; called out because a visitor might probe them):

- `/api/v1/backups*`
- `/api/v1/devices*`
- `/api/v1/schedules*` — note it exposes `/{id}/toggle` (enable/disable), which
  is **not** a run-now trigger, but it stays blocked regardless.
- `/api/v1/configs*`
- `/api/v1/definitions*`
- `/api/v1/openapi.json`, `/docs`
- UI pages: `/` (the **backup dashboard**, *not* migrate), `/jobs`,
  `/schedules`, `/configs`, `/devices`, `/definitions`

`POST /api/v1/migration/render` is also **not** on the allowlist — the demo's
translate flow reaches its result through `/plan` and the typed sub-plans, so
`/render` stays default-denied like everything else unlisted.

## Host-level complements

- Swap disabled host-wide ([02](02-deployment.md#provisioning-cloud-init)) — a
  tmpfs page can never be written to disk under memory pressure; with
  `memswap_limit == mem_limit`, an instance hitting its cap is OOM-killed
  (destroyed), which is the correct failure mode for this design.
- **Core dumps disabled host-wide** ([02](02-deployment.md#provisioning-cloud-init))
  — swap-off is not the only RAM→disk path. cloud-init sets
  `kernel.core_pattern` to discard, `systemd-coredump` `Storage=none` +
  `ProcessSizeMax=0`, removes/neuters apport, and sets `LimitCORE=0` on
  `docker.service`, so a crashing instance cannot spill submitted-config bytes
  into a dump file.
- journald volatile ([02](02-deployment.md)).
- Docker daemon: `"log-driver": "none"` as the *default* would be too blunt for
  caddy/warden; instead set `none` per-instance (above) and `local,max 10m` for
  the two service containers.

## <a name="logging"></a>Logging policy (system-wide, one table)

| Layer | What is logged | Where | Payload possible? |
|---|---|---|---|
| netcanon instance | nothing (driver `none`; `NETCANON_LOG_LEVEL=warning`) | — | No |
| Warden | session lifecycle metadata: token-hash prefix, timestamps, destroy reason, status codes | stdout → journald (RAM) | No — schema enumerated & tested |
| Caddy | `/i/*`, `/session/*`, and all allowlisted cookie-routed app paths: **no access logs**; everything else: **status-only** | stdout → journald (RAM) | No |
| Host | auth/system logs | journald volatile | No |

The whitepaper reproduces this table; [08](08-testing-verification.md#log-audit)
proves it empirically (paste a canary string through the demo, grep the entire
host — including any core-dump path — for it).

## Deliverables

- Constants block implemented exactly as above (with verified digest and the
  final route allowlist filled in); no `user` override; both declared VOLUME
  paths mounted as tmpfs
- `demo-int` network definition with `internal: true` + explicit
  warden→instance-only nftables segmentation (static warden IP `172.31.0.2`,
  `ct state established,related` accept, instance→instance and instance→warden
  drop), plus the dedicated `warden-sock` network carrying only the warden and
  the socket-proxy
- Daemon/service log-driver configuration; host core-dump + swap disable
  (cross-check [02](02-deployment.md#provisioning-cloud-init))
- Route allowlist derived from the actual image and recorded in the repo;
  instance labels wired to the [03](03-warden-spec.md#lifecycle-rules) hard-TTL sweep
