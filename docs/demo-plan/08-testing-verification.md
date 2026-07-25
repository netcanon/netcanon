# 08 — Testing & Verification

Two tiers: **CI tests** (run on every deploy-repo commit) and **live proofs**
(runnable on the production host; these are the whitepaper's `VERIFY.md`).
Each maps to a claim number in [06](06-privacy-whitepaper.md#claims-controls-proofs).

## CI tests (pytest, against a compose stack in CI)

| Test | Claim |
|---|---|
| Mint two sessions → containers differ; routing cookie for A + absolute path → served by A only; A's cookie against B's instance → 404 | 1 |
| `docker inspect`: ReadonlyRootfs, **tmpfs on both `/app/configs` and `/app/data`** (the image declares `VOLUME` for both), no named/anonymous volumes, non-root uid 1000 (native `USER app`, no `user` override), cap_drop ALL, no-new-privileges, pids/mem/cpu limits, log driver `none`, memswap==mem | 2, 4, 5 |
| Header rewrite: proxied instance response has **no `X-Frame-Options`** and CSP `frame-ancestors 'self'` (netcanon stamps XFO:DENY + `frame-ancestors 'none'`; the warden must strip/rewrite them) | 2 |
| Volume reap: after a full session + destroy, `docker volume ls` shows **zero** anonymous volumes (destroy uses `remove(v=True, force=True)`) | 2 |
| Hard-TTL immovable: heartbeat **and** translate continuously; assert destroy at the 900 s (`HARD_TTL`) deadline (`deadline = assignment_time + HARD_TTL`) ±10 s — nothing the session does extends it | 3 |
| Pool epoch (assignment-relative TTL): age a pooled instance to ~289 s (just under the `POOL_MAX_AGE − reaper_period` ~290 s recycle threshold), **then** assign it; assert it survives a full 900 s from **assignment** (creation-age deadline ≈ 1189 s) and that the creation-relative systemd backstop (`HARD_TTL + POOL_MAX_AGE + 120 s slack = 1320 s`, fires only *older than* 1320 s) does not kill it early — the 120 s slack is exactly what makes this safe. Companion: a pooled instance aged past ~290 s is **recycled** (destroyed + refilled), so it is never assigned older than `POOL_MAX_AGE` (300 s) | 3 |
| Idle reclaim: heartbeat continuously but **never** send an allowlisted POST; assert destroy at ~600 s (`IDLE_TTL`), i.e. a heartbeat alone must not keep a session alive | 3, 8 |
| Idle hysteresis (retroactive, no thrash): occupancy crosses **> 80 %** → sessions idle > 300 s are reaped **one reaper tick after the tightening takes effect (~10–20 s after the crossing)**; occupancy drops **< 70 %** → threshold returns to 600 s; assert no thrash while occupancy sits between 70–80 % | 3, 8 |
| Idle activity set (`last_activity`): a session driving only `POST /api/v1/migration/detect` + `POST /api/v1/migration/plan/ports` (never the bare `plan`) survives **past** `IDLE_TTL` — sub-plan and detect calls refresh `last_activity`; GETs and `/hb` do not | 3, 8 |
| No-beacon reclaim, **visible** tab: `/hb` reports `{"hidden": false}` then stops; assert destroy **≤ 2 min for a closed foreground tab** (30 s hb interval + 75 s visible stale threshold + 10 s reaper ≈ 115 s) | 3 |
| No-beacon reclaim, **hidden** tab: `/hb` reports `{"hidden": true}` then stops; assert destroy **≤ ~4 min for a throttled background tab** (30 s + 180 s hidden stale threshold + 10 s reaper ≈ 220 s) | 3 |
| TTL independence: create a `demo`-labeled instance, kill+restart the warden; assert it is force-removed within one startup label-sweep; assert the host systemd timer (sweep cadence 60 s) force-removes a `demo.*`-labeled container older than `HARD_TTL + POOL_MAX_AGE + 120 s slack = 1320 s` on **creation** age | 3 |
| `end` idempotency + sendBeacon content-type accepted | 3 |
| Warden log schema: run a full session with payload "CANARY-<rand>"; assert canary absent from captured warden/caddy stdout at `NETCANON_LOG_LEVEL=warning` | 4 |
| Error-path canary: oversized body, malformed body, mid-stream client kill, and a forced 500 — each carrying `CANARY-<rand>`; assert canary absent from all logs (the interesting leaks are on the error paths, not the happy path) | 4 |
| Egress + isolation: outbound connect from instance netns fails (spawn a probe container on `demo-int`); **instance→warden API port fails**; **instance→instance fails**; **instance→socket-proxy fails** (socket-proxy is on `warden-sock` only, which instances never join) | 6 |
| Per-IP session cap: one IP opening more than `PER_IP_MAX_CONCURRENT = 2` concurrent sessions is refused past the cap (RAM-only record, evicted 600 s after that IP's last request) | 8 |
| Cap behavior: fill to `MAX_ACTIVE` (32); next mint reclaims the longest-idle no-translate session **older than the 120 s min-age floor**, else → 503; assert a session younger than 120 s is **never** the reclaim victim; no instance sharing | 8 |
| Capacity SLO: a closed tab (beacon path) frees its slot ≤ **90 s** | 8 |
| Proxy allowlist: an allowlisted route (`POST /api/v1/migration/plan`, `POST /api/v1/sanitize`, `GET /migrate`) is proxied; a blocked route (`/api/v1/backups`, `/api/v1/devices`, `/api/v1/configs`, `/docs`, `/jobs`) → 404 at warden | (04) |
| Proxy allowlist (iframe `{path}` form): the allowlist covers the `{path}` component of `/i/{t}/{path}` exactly as for absolute cookie-routed paths — `/i/{t}/migrate` → 200; `/i/{t}/api/v1/backups` → 404; bare `/i/{t}/` (instance `/`, the backup dashboard) → 404 | 2, (04) |
| Socket-proxy verb allowlist: probe `exec`, `commit`, `build`, `images`, `networks`, `volumes` through the proxy → each **rejected**; only `create`, `start`, `list`, `inspect`, `remove` pass (the TCB verb boundary Gate 1 asserts) | 3, 9 |
| Create-body authz shim (whole-body default-deny): a `POST /containers/create` body that deviates from `INSTANCE_SPEC` is **rejected** — an extra bind mount, a changed image digest, a dropped `read_only`, **and** an added `Privileged` / `CapAdd` / `Devices` / `PidMode` / `HostConfig.Mounts` / `VolumesFrom` / `NetworkMode: host` key or a changed `LogConfig`; only the two `demo.*` labels + two per-instance random env keys may vary. This is the CI that makes "create-with-fixed-spec" real | 3, 9 |
| Create-body authz shim (positive path): the warden's **real canonical create body** (the wire body = `INSTANCE_SPEC` serialized through the pinned SDK, structural defaults included) is **accepted** — proves the template isn't over-strict and the demo can actually launch instances | 3, 9 |
| Two-tab replacement (one live session per browser): open tab 1 (cookie → instance A); `POST /session/new` bearing A's `nc_route` cookie → A destroyed (reason `end`), instance B minted, cookie now routes to B; a request replaying A's identity → 404; no request ever silently lands on the wrong container | 1 |
| Concurrency safety: fire N simultaneous `POST /session/new` at a near-empty pool; assert no container is assigned to two tokens and `MAX_ACTIVE` is never exceeded. Separately, run a **reaper recycle of an aging pool instance concurrently with a mint** and assert the mint never lands on a container being destroyed — the reserve-then-fill discipline (mark `RESERVING`/`DESTROYING` and remove from the pool under the lock, do docker I/O outside it) holds, and the lock is **never** held across an `asyncio.to_thread` call | 1, 8 |
| Fernet key in RAM (claim 7): `docker inspect` shows `NETCANON_FERNET_KEY` present in the instance env (per-instance random); no `.fernet_key` file is created | 7 |
| Token entropy: mint 10k, assert length/charset/uniqueness | 1 |

## Live proofs (`VERIFY.md` — anyone with host access; several visitor-runnable)

1. **Canary forensics (claims 2, 3, 4).** Start session; paste config containing
   `CANARY-$(openssl rand -hex 8)`; translate; end session. Then:
   `docker ps -a | grep <id>` → gone; whole-filesystem sweep
   `grep -r CANARY- / --binary-files=text` (excluding `/proc /sys /dev`) +
   `journalctl | grep CANARY-` → zero hits; **raw block-device sweep**
   `grep -a CANARY- /dev/sda` (catches anything that hit the disk under a
   filesystem we didn't walk) → zero hits. (Run before TTL too: canary must
   appear **nowhere on disk even while the session lives**.)
   - **Error-path canaries (claim 4).** Repeat the sweep after each abnormal
     path — an oversized body, a malformed body, a mid-stream client kill, and a
     forced 500 — each carrying a distinct `CANARY-`. The interesting leaks
     (stack traces, buffered request echoes) live on the error paths, not the
     happy path; `NETCANON_LOG_LEVEL=warning` keeps parsed fragments out of logs.
2. **Mount proof (claim 2).** During a live session: `docker inspect <id> |
   jq '.[0].HostConfig.ReadonlyRootfs, .[0].Mounts'` → `true`, tmpfs-only.
   `docker diff <id>` → changes confined to tmpfs paths.
3. **Swap proof (claim 5).** `swapon --show` → empty. `docker inspect | jq
   .HostConfig.Memory,.HostConfig.MemorySwap` → equal.
4. **Egress + segmentation proof (claim 6).** `docker network inspect demo-int |
   jq '.[0].Internal'` → true. From instance netns (`nsenter`): connect to
   1.1.1.1:443, to a **sibling instance**, to the **warden API port**, and to the
   **socket-proxy** → all four fail. (The nftables policy on the single `demo-int`
   bridge is warden→instance ALLOW, instance→instance DENY, instance→warden DENY;
   the socket-proxy is unreachable by construction — it sits on the `warden-sock`
   network only, which instances never join. `enable_icc=false` is **not** used —
   it is all-or-nothing and would also break warden→instance.)
5. **Proof 5 (isolation, claim 1).** Two browser profiles each start a session;
   each header shows a **distinct instance-id chip** (`instance_id`, a short
   warden-assigned id — not the routing token). End (or wait out) session A; A's
   `nc_route` cookie is now dead, so every subsequent request from A returns
   **404** (the destroyed state) while B is unaffected. Routing is by the
   **HttpOnly** `nc_route` cookie, so a visitor cannot forge another session's
   routing from JS. (A live routing token is a bearer credential for the life of
   the session — not single-use — which is why the cookie is HttpOnly, Secure, and
   SameSite=Strict.)
6. **Capacity proof (claim 8).** Script mints MAX_ACTIVE sessions → next mint
   first reclaims the longest-idle no-translate session, then (if none) → 503;
   UI shows busy state. **Per-IP cap:** one IP opening more than the per-IP
   concurrent-session cap is refused past the cap. **Capacity SLO:** a closed
   tab (beacon path) frees its slot within ≤ 90 s.
7. **Reproducibility (claim 9) — visitor-runnable.** `make verify` prints image
   digests + compose SHA-256; visitor compares against whitepaper block. (This
   attests the **repo**, not the live host — no hosted demo can remotely prove
   its own runtime; that is why the local `docker run` path exists.)
8. **Page cleanliness (claim 10) — visitor-runnable.** Devtools: the page itself
   sets no cookies/localStorage and makes no third-party requests; source is
   self-contained. (The warden-set HttpOnly routing cookie is out of page reach
   and is disclosed in the whitepaper's "What we do see".)
9. **Framing proof (Gate 2, claim 2).** With a live session in the parent page's
   iframe: the instance renders (not blank); response headers show no
   `X-Frame-Options` and CSP `frame-ancestors 'self'` after the warden's
   header rewrite. Confirms the XFO/CSP neutralization actually works end-to-end.
10. **Volume-reap proof (claim 2).** After a full session + destroy:
    `docker volume ls` → no anonymous volume attributable to the instance
    (destroy uses `remove(v=True, force=True)`; both declared `VOLUME` paths were
    tmpfs, so none should have been created in the first place).
11. **TTL-independence proof (claim 3).** Create a `demo`-labeled instance; kill
    and restart the warden → the startup label-sweep force-removes it (it adopts
    nothing). Separately, let a `demo.*`-labeled container exceed
    `HARD_TTL + POOL_MAX_AGE + 120 s slack = 1320 s` on creation age with the warden stopped →
    the host systemd timer (sweep cadence 60 s, `OnUnitActiveSec=60s`) force-removes
    it. Neither relies on the in-memory dict.
12. **Core-dump proof (claim 5).** Crash a process inside a live instance (e.g.
    `kill -SIGSEGV` a worker) → nothing appears under `/var/crash`,
    `/var/lib/systemd/coredump`, or apport spool (`kernel.core_pattern` discards,
    `systemd-coredump Storage=none`/`ProcessSizeMax=0`, apport neutered).
13. **Proof 13 (Fernet key never on disk, claim 7).** From the host, using the
    **raw host Docker socket** (not the warden's path — its allowlist forbids
    `exec`): `docker exec <id> sh -c 'ls -la /app/data/.fernet_key'` → no such
    file; `docker exec <id> printenv NETCANON_FERNET_KEY` → set. `/app/data` is
    tmpfs regardless, so even had the file existed it never touched disk.

## Pre-launch gate

All CI tests green **and** live proofs 1–13 executed on the production host with
output pasted into `VERIFY_RESULTS_<date>.md` (committed). The whitepaper links
to that file. Re-run on every image-digest bump.

## Deliverables

- `tests/` implementing the CI table
- `VERIFY.md` with copy-paste commands for proofs 1–13
- `VERIFY_RESULTS_<date>.md` from the real host, committed pre-launch
