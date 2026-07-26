# 03 — Warden Specification

The warden is the only stateful service. Its *live* state is a single in-memory
dict, but durable lifecycle enforcement does **not** depend on it (container
labels + a startup sweep + an independent host timer — see Lifecycle). FastAPI +
`docker` SDK + `httpx` (streaming proxy), run **single-process
(`uvicorn --workers 1`)** so the session dict is never sharded across workers;
synchronous `docker` SDK calls run via `asyncio.to_thread` and a single
`asyncio.Lock` guards the pool + active-map + caps (see Security posture).
Target: small enough to audit in one sitting (≤500 lines); the whitepaper links
to its source and counts it — together with the socket-proxy + small create-body
authz shim (see Security posture) — as the Trusted Computing Base.

## Responsibilities

1. Maintain the **warm pool** (default 4 unassigned instances), refilled
   **single-flight** — one refill task at a time, guarded by the pool lock — so a
   burst of assignments cannot thundering-herd N concurrent container-creates on
   the 2-vCPU box.
2. Mint sessions: assign instance, generate token, bind a routing cookie, track
   deadline/heartbeat.
3. Reverse-proxy to the assigned instance — streaming, never persisting bodies —
   fixing up framing headers and routing by session cookie (netcanon uses
   absolute URLs and has no root-path support; see Proxying).
4. Enforce lifecycle: heartbeat timeout, idle-TTL reclaim, hard TTL, explicit
   end — across **two independent enforcement domains (the warden and host
   systemd), three mechanisms**, with the in-memory dict as the warden's live
   reaper (see
   Lifecycle).
5. Enforce global + per-IP caps, occupancy-driven idle-TTL, and expose an
   operational `/healthz`.

## API

| Route | Method | Behavior |
|---|---|---|
| `/session/new` | POST | If the request carries a **valid `nc_route` cookie**, destroy that session first (reason `end`) and mint fresh — **one live session per browser** (the cookie is browser-global). Enforce the per-IP session cap, then pop pool → mint token (`secrets.token_urlsafe(16)`), set the routing cookie → `{token, ttl_seconds, expires_at, idle_ttl_seconds, instance_id}`. Pool empty at cap → reclaim the longest-idle session **older than the 120 s floor** and retry; if every active session is younger than 120 s, or still full → `503 {"reason":"capacity"}`. |
| `/session/{t}/hb` | POST | Body `{"hidden": <bool>}` (from `document.visibilityState`). Update `last_heartbeat` and the stored visibility (tab-liveness only — does **not** reset the idle timer; only an allowlisted proxied POST does). Returns `{"idle_remaining_seconds": <int>}`. 404 for unknown/dead tokens. |
| `/session/{t}/end` | POST | Immediate destroy. Idempotent 204. Must accept `sendBeacon` (no CORS preflight — same-origin, `text/plain`). |
| `/i/{t}/{path:path}` | ANY | Token valid **and `{path}` on the route allowlist** → set the routing cookie, streamed proxy to instance `:{INSTANCE_PORT}` (8000); off-allowlist `{path}` (incl. bare `/i/{t}/` → instance `/`, the blocked backup dashboard) or bad token → 404. Frontend targets `/i/{t}/migrate`. |
| allowlisted absolute paths (`/migrate`, `/api/v1/migration/*`, …) | ANY | Routed by **routing cookie** to the mapped instance; off-allowlist → 404. Any allowlisted **proxied POST** (`POST /api/v1/migration/plan` and all `/plan/*` sub-plans — `/ports`, `/vlans`, `/local_users`, `/snmp`, `/snmpv3` — plus `POST /api/v1/migration/detect` and `POST /api/v1/sanitize`) also refreshes the session's `last_activity` (resets the idle timer); GETs and `/hb` do not. Allowlist in [04](04-container-hardening.md). |
| `/healthz` | GET | Pool size, active count, uptime, aggregate counters (see Operational telemetry). **No tokens, no per-session detail.** |

## Lifecycle rules

> Every instance is destroyed **≤ 15 min after assignment** (the warden's in-RAM
> reaper, `deadline = assignment_time + HARD_TTL`) and **≤ ~23 min after creation
> even with the warden dead** (an independent host `systemd` timer that
> force-removes any `demo.*`-labeled container older than
> `HARD_TTL + POOL_MAX_AGE + 120 s slack = 1320 s`, swept every 60 s). Because the reaper
> recycles any unassigned pool instance whose age exceeds
> `POOL_MAX_AGE − reaper_period` (290 s), no instance is ever *assigned* more than
> `POOL_MAX_AGE` (300 s) after its creation; a live session's creation-age deadline
> is therefore ≤ `HARD_TTL + POOL_MAX_AGE` (1200 s), and the systemd backstop
> force-removes only containers *older than* 1200 s — strictly after the in-RAM
> deadline, never before.

- **Two independent TTLs — a session dies at whichever fires first:**
  - `HARD_TTL = 900 s` (15 min) **hard ceiling** — a monotonic-clock deadline
    (`deadline = assignment_time + HARD_TTL`, set when the instance is *assigned*
    out of the pool, not when it was created — see the epoch note under
    Enforcement); nothing the browser does moves it (**I3**). This is the
    advertised "self-destructs within 15 minutes"; the frontend countdown runs to
    it, so the ceiling reads as a feature, not a limitation.
  - `IDLE_TTL = 600 s` (10 min) **idle reclaim** — destroy a session whose last
    activity is older than `IDLE_TTL` (`now − last_activity > IDLE_TTL`) **even
    while it is still heartbeating**. This reclaims the open-but-unused tab — the
    dominant dwell driver — without touching the hard ceiling. `IDLE_TTL` is a
    **single global reaper parameter**, compared against every session's
    `last_activity` at each tick, so a change is **retroactive** (an already-idle
    session becomes eligible at the next tick). It has **hysteresis**: tighten
    `600 → 300 s` when occupancy **> 80 %**, loosen `300 → 600 s` when occupancy
    **< 70 %** (the 70–80 % dead-band prevents thrash). A tightening **takes effect
    at the next reaper tick, and a session already idle beyond the new threshold is
    reaped one tick later** (≈ 10–20 s after occupancy crosses 80 %) — at most one
    heartbeat, and possibly none, lands in that window to surface it (see
    [05](05-frontend.md)). The hard ceiling is **never** shortened
    (you reclaim idle
    sessions faster, you do not renege on the advertised 15 minutes).
- `last_activity` is updated by **any allowlisted POST proxied to the instance** —
  `POST /api/v1/migration/plan` and all `/plan/*` sub-plans (`/ports`, `/vlans`,
  `/local_users`, `/snmp`, `/snmpv3`), `POST /api/v1/migration/detect`, and
  `POST /api/v1/sanitize`. `last_heartbeat` tracks tab liveness and is updated by
  `/hb`; GETs and `/hb` do **not** refresh `last_activity`. The two clocks are
  deliberately separate: a heartbeat keeps a tab clear of the hb-timeout reaper
  but does **not** stave off the idle reclaim — only actually using netcanon does.
- Heartbeat interval 30 s; the stale threshold is **visibility-aware** — the
  `/hb` body carries `{"hidden": <bool>}` and the warden stores the last-reported
  visibility: **75 s** while visible (2 missed + margin), **180 s** while hidden
  (a throttled background tab beats at a slower cadence). This bounds no-beacon
  reclaim to **≤ 2 min for a closed foreground tab, ≤ ~4 min for a throttled
  background tab**.
- Reaper loop every 10 s: destroy `now > deadline` (hard-ttl) `|| now −
  last_activity > IDLE_TTL` (idle) `|| last_heartbeat-stale` (hb, threshold keyed
  to the reported visibility), and **recycle** any unassigned pool instance whose
  age exceeds `POOL_MAX_AGE − reaper_period` (290 s) (destroy + refill) — so no
  instance is ever *assigned* older than `POOL_MAX_AGE` (300 s) — then refill the
  pool to target. Refill is **single-flight** — one refill task at a time, guarded
  by the pool lock. The reaper also watches the drain sentinel (see Draining and shutdown)
  and, when it is set, stops minting and lets sessions lapse.
- Destroy = `container.remove(v=True, force=True)` — `v=True` also removes the
  container's anonymous volumes so nothing survives on the host disk. Verify
  gone; log `session_destroyed duration_s=… reason=hard-ttl|idle|hb|end|reclaim` —
  `reclaim` is the at-cap longest-idle victim (below); **metadata only**. Pool
  recycling destroys an *unassigned* instance (no session) and is counted
  separately as `pool_recycled`.
- **Enforcement is not the in-memory dict alone** — a warden crash/restart would
  otherwise orphan live instances. The hard TTL is enforced across **two
  independent enforcement domains (the warden and host systemd), three
  mechanisms**: (1) the warden's in-RAM reaper at `deadline = assignment_time +
  HARD_TTL`; (2) the warden's **startup label-sweep**, which force-removes every
  `demo.*`-labeled container it did not itself just create (it adopts nothing);
  and (3) an **independent host `systemd` timer** (sweep cadence 60 s,
  `OnUnitActiveSec=60s`/`OnBootSec=60s`) that force-removes any `demo.*`-labeled
  container older than `HARD_TTL + POOL_MAX_AGE` (1200 s), so the creation-age
  ceiling holds even while the warden is down (a crash can widen the effective
  ceiling from 15 min-after-assignment to ≤ ~23 min-after-creation, never lift
  it). Idle and heartbeat reclaim are warden-live-only; the systemd backstop is
  what covers a wedged/dead warden.
  - **Epoch note.** Every instance is created with labels
    `demo.created_at=<unix-ts>` and `demo.instance=<create-time random id>` —
    **not** the token (it does not exist at create, and labels are immutable). The
    warden's in-RAM deadline is assignment-relative (900 s from assignment); the
    warden-dead backstop can only read the create-time label, so it uses the
    looser creation-relative 1200 s ceiling that provably cannot fire before a
    live session's 900 s (see the guarantee blockquote above).
  - Pool recycling (at `POOL_MAX_AGE − reaper_period`, ~290 s) is a **warden**
    action, which also closes the old "a host timer force-removes the whole idle
    pool / races a fresh assignment" hazard — recycling is never a systemd race at
    1200 s.
- Global cap: `MAX_ACTIVE = 32` (tunable per [07](07-budget.md#sizing); sized off
  real held-session RSS ≈ 90–140 MB + shim, **not** the 256 MB cap). Plus a
  warden-enforced **per-IP concurrent-session cap (`PER_IP_MAX_CONCURRENT = 2`)**
  and a **sliding-window per-IP mint rate limit (≤ 30 mints / 600 s per IP)**.
  Both share one per-IP record, held in **warden RAM only** and **evicted 600 s
  (10 min) after that IP's last request** (a rate limiter must outlive a single
  session), disclosed under
  [06 "What we do see"](06-privacy-whitepaper.md#what-we-do-see).
- At cap, `/session/new` reclaims the **longest-idle session older than the 120 s
  min-age floor** (a session younger than 120 s is never the victim — it protects
  a seconds-old mid-paste session); if every active session is under the floor, or
  the pool is drained, `/session/new` → 503 and the frontend shows the busy state.
  Under heavy load an untouched session may thus be reclaimed early to make room.

## Instance creation parameters

Exact hardening flags in [04](04-container-hardening.md); the warden creates
containers with those parameters verbatim — they are defined in one constants
block so the whitepaper can cite a single source location.

The instance image is pinned by digest and is **not** in the compose file (the
warden creates instances directly), so the warden asserts the pinned digest is
present locally at startup (`docker image inspect <pinned digest>`) and **refuses
to start** if it is absent — no silent pull-on-demand. The host deploy flow
therefore `docker pull`s the pinned instance digest explicitly (see
[02](02-deployment.md#image-supply-chain)).

Instances start with a per-instance throwaway `NETCANON_API_KEY` that the warden
generates at create time and injects into proxied `/api/v1` requests. The image
gates a non-loopback bind on that key **alone** — a key *or*
`NETCANON_ALLOW_INSECURE_BIND=1` (config.py); we set the key and never set the
insecure-bind opt-out — so "unauthenticated netcanon API" is kept out of
existence entirely, which reads better in the whitepaper. `NETCANON_PORT=8000`,
the RAM-only per-instance `NETCANON_FERNET_KEY` (no key file is ever written),
and the rest of the env + hardening flags live in the one constants block in
[04](04-container-hardening.md).

## Proxying

- Stream request and response bodies (`httpx` streaming); **no body ever
  touches a buffer that outlives the request, no body is ever logged** (**I2**).
- Strip hop-by-hop headers; add `X-Forwarded-*`.
- **Fix framing on every instance response.** netcanon stamps
  `X-Frame-Options: DENY` and a CSP with `frame-ancestors 'none'` on every
  response (main.py:366-374), so a plain iframe renders blank and a CSP header
  *added* downstream can't relax it (multiple CSP headers intersect). The warden
  therefore **strips `X-Frame-Options`** and **rewrites the instance CSP
  directive `frame-ancestors 'none'` → `frame-ancestors 'self'`** so the demo
  origin may frame it; the page stays in an iframe (frontend detail:
  [05](05-frontend.md)).
- **Route by session cookie, not path prefix.** netcanon's UI uses absolute URLs
  (`fetch('/api/v1/migration/plan')`, `href="/migrate"`) and has no root-path
  support, so a `/i/{t}/`-mounted prefix would break every asset and API call.
  Instead, serving `/i/{t}/…` sets the routing cookie bound to that instance — the
  exact line is:
  ```
  Set-Cookie: nc_route=<token>; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=900
  ```
  `Path=/` is mandatory: without it RFC-6265 default-path scoping would restrict
  the cookie to `/i/…` and the absolute-path routing would never carry it, so the
  whole cookie-routing scheme would fail at Gate 2. `Max-Age=900` matches
  `HARD_TTL` (the cookie is dead-on-arrival once the session ends — the warden
  404s the token regardless). The warden routes any allowlisted absolute path
  carrying that cookie to the mapped instance (one active session per browser is
  already the model). The **frontend page itself sets no cookies or localStorage**;
  this cookie is warden-set and is disclosed under
  [06 "What we do see"](06-privacy-whitepaper.md#what-we-do-see).
- **The route allowlist applies to the `{path}` component of `/i/{t}/{path}`
  exactly as it does to absolute cookie-routed paths.** So `/i/{t}/api/v1/backups`
  is default-denied just like `/api/v1/backups`, and bare `/i/{t}/` (→ instance
  `/`, the blocked backup dashboard) is **not** on the allowlist and 404s; the
  frontend therefore targets `/i/{t}/migrate`, which is allowlisted.
- netcanon has **no WebSockets** — the UI polls via `fetch`. There is no WS path
  to proxy, so no WS fallback is carried; the warden stays the only path to
  instances.

## Security posture of the warden itself

- <a name="socket"></a>Reaches the Docker API through a **socket-proxy / authz
  filter**, never the raw socket. Running the warden `read_only: true` and
  non-root does **not** constrain what the socket API can do — a mounted
  `docker.sock` is root-equivalent on the host — so a minimal path/method filter
  (e.g. `docker-socket-proxy`) allows **only create, start, list
  (`GET /containers/json`, including label filters), inspect, and remove**, and
  denies everything else (`exec`, `commit`, `build`, `images`, `networks`,
  `volumes`, …). `list` is needed by the startup label-sweep to discover orphaned
  `demo.*` containers after a crash (no IDs to inspect otherwise); `start` because
  Docker separates create from start and pool instances must be **running** to
  serve `:8000`.
- <a name="shim"></a>The path/method filter cannot inspect a create **body**, so
  a **small (~50–80-line) create-body authz shim** (an authz plugin in front of
  the socket proxy) enforces a **whole-body default-deny allowlist** on every
  `POST /containers/create`. It validates the **raw wire body** (whose keys are
  `HostConfig`-nested — `ReadonlyRootfs`, `Tmpfs`, `Memory`, `NanoCpus`, `CapDrop`,
  `NetworkMode`, `LogConfig`, … — not the Python-SDK kwargs) against the
  **canonical create-body template = `INSTANCE_SPEC` serialized through the pinned
  Docker-SDK version**, structural defaults included: the body may contain **only**
  the template's keys — **any other key is rejected outright** — and each must
  equal the template (image digest, `ReadonlyRootfs: true`, the tmpfs set,
  `NetworkMode`, `Memory == MemorySwap`, `PidsLimit`, `NanoCpus`,
  `CapDrop: [ALL]` **with `CapAdd: []`**, `SecurityOpt`). Only the
  deliberately-variable fields — the `demo.created_at`/`demo.instance` labels and
  the two per-instance random env keys (`NETCANON_API_KEY`, `NETCANON_FERNET_KEY`)
  — may differ. **Default-deny is load-bearing:** a positive check of only the
  fields the shim *knows about* would pass a body that keeps every listed field
  canonical yet **adds** a root-equivalent one, so the shim explicitly rejects any
  of `Privileged`, `CapAdd`, `Devices`, `PidMode`/`IpcMode`/`UTSMode`,
  `NetworkMode: host`, `UsernsMode`, `VolumesFrom`, `HostConfig.Binds` /
  `HostConfig.Mounts` (bind), `CgroupParent`, `Sysctls`, `Runtime`, or a changed
  `LogConfig`. That is what makes "create-with-fixed-spec" genuinely enforceable —
  `Binds:["/:/host"]`, `Privileged:true`, and `CapAdd:[SYS_ADMIN]` are all
  impossible. The shim is **counted in the Trusted Computing Base** alongside the
  ≤500-line warden and the socket-proxy; together the socket-proxy + shim are the
  crown jewel and the main reason the warden stays small and auditable.
- The **socket-proxy attaches to the dedicated `warden-sock` network only**
  (warden + socket-proxy, no other network), so instances — on `demo-int` only —
  cannot reach it by construction, in addition to the nftables instance→warden
  DENY (see [Network isolation](#network)).
- The warden container still runs `read_only: true`, non-root where the SDK
  allows, and `no-new-privileges`. It bridges **three networks** — `demo-int`
  (`internal: true`, to proxy instances; the warden holds the static address
  `172.31.0.2`), `warden-sock` (to reach the socket-proxy), and the caddy-facing
  net — and is **not** on the instance-to-instance path.
- **Single process, `uvicorn --workers 1`** (multiple workers would shard the
  session dict). A **single `asyncio.Lock`** guards the pool + active-map + caps,
  but is held **only for O(1) in-RAM mutations, never across an awaited `docker`
  SDK call** (holding it across create/remove would block `/hb` and proxied reads
  — the very heartbeat freeze it must avoid). The two guarantees — never freeze
  heartbeats **and** never double-assign — coexist only via **reserve-then-fill**:
  under the lock, mark the chosen instance `RESERVING` (a mint) or `DESTROYING` (a
  reaper recycle / at-cap reclaim) and remove it from the assignable pool; release
  the lock; do the container I/O via `asyncio.to_thread` (or `aiodocker`);
  re-acquire only to commit the O(1) state change. A mint therefore can never pop
  an instance the reaper is concurrently destroying, and no `docker` call ever runs
  under the lock.
- Never executes anything inside instances (`exec` is denied); the socket-proxy
  verb allowlist is **create, start, list, inspect, remove** only.
- Token comparison in constant time (`secrets.compare_digest`).
- All warden logs to stdout → journald (volatile). Log schema is enumerated in
  the whitepaper; grep-able proof that no payload fields exist
  ([08](08-testing-verification.md#log-audit)).

## <a name="network"></a>Network isolation

Instances attach to the `demo-int` bridge (`internal: true`, no egress — **I5**);
instances receive addresses in `172.31.0.0/24` and the **warden holds the static
address `172.31.0.2`**. The bridge's forward path is **default-drop**, with these
rules evaluated in order, implementing the three-way policy so instances are never
publicly routable (**I4**):

```
1) ct state established,related                      accept   # return path for warden→instance
2) ip saddr 172.31.0.2  tcp dport 8000               accept   # warden → instance ALLOW
3) ip daddr 172.31.0.2                               drop     # instance → warden DENY
4) ip saddr 172.31.0.0/24 ip daddr 172.31.0.0/24     drop     # instance → instance DENY
5) (default)                                         drop
```

- **warden → instance: ALLOW** (rules 1–2) — the proxy path.
- **instance → warden: DENY** (rule 3) — a compromised instance cannot reach the
  control plane / socket-proxy; it can only answer proxied requests.
- **instance → instance: DENY** (rule 4) — a compromised instance cannot reach a
  peer.

`enable_icc=false` is **not** used (it is all-or-nothing and would also cut
warden→instance). The socket-proxy is unreachable from instances by construction
— it is on the `warden-sock` network only, which instances never join.

**Interface vs subnet matching, and anti-spoofing.** Rule 4 matches by **subnet**
(`172.31.0.0/24`), not `iifname "demo-int"`: a Docker-created bridge is named
`br-<hash>` unless pinned with
`driver_opts { com.docker.network.bridge.name: demo-int }`, so subnet matching is
robust regardless of the interface name. The ruleset lives in the `DOCKER-USER`
chain scoped to the demo bridge, so it never touches the `warden-sock` / caddy
nets. Rule 2 trusts the source IP `172.31.0.2`; that is safe **because** instances
run `cap_drop: [ALL]` (no `CAP_NET_RAW`, so a compromised instance cannot
source-spoof the warden's address) — where the deployment can pin the warden's
veth name, add an `iifname` match to rule 2 as a second layer rather than relying
on `cap_drop` alone.

Instances need no outbound egress (netcanon plans offline); host-level egress
rules are in [04](04-container-hardening.md).

## Draining and shutdown

- The **sole drain trigger** is a **loopback-only control endpoint (bound to
  `127.0.0.1`)** or a **sentinel file the reaper watches** — not a routable HTTP
  path. When set, the warden stops minting new sessions and lets existing sessions
  lapse naturally.
- **SIGTERM is fast shutdown, not drain.** `docker compose up -d` sends SIGTERM
  and **kills live sessions by design** — no session-state migration exists. A
  graceful window, if wanted, comes from raising the container's
  `stop_grace_period`, not from treating SIGTERM as a drain.
- This is consistent with **adopt-nothing**: after a redeploy the fresh warden's
  startup label-sweep force-removes any leftover `demo.*` containers, so a
  redeploy without draining first is safe (it just kills those live sessions).

## Operational telemetry (`/healthz`)

Metadata-only — "no visitor tracking" is not "no operator telemetry". Beyond
pool size / active count / uptime, `/healthz` exposes aggregate counters with no
per-session or per-visitor detail:

- `sessions_started`
- `destroys_by_reason` (`hard-ttl` / `idle` / `hb` / `end` / `reclaim`)
- `pool_recycled` (unassigned instances recycled at ~290 s, `POOL_MAX_AGE − reaper_period`)
- `503_count`
- `pool_refill_failures`

These back an external uptime monitor and a synthetic
mint→translate-sample→end probe (a few times/hr, exempt from the per-IP cap);
verification detail in [08](08-testing-verification.md).

## Deliverables

- `warden/app.py` (+ `warden/Dockerfile`, pinned base image) and the
  socket-proxy / authz-filter config
- Constants block, single source of truth: `INSTANCE_PORT = 8000`,
  `HARD_TTL = 900 s`, `IDLE_TTL = 600 s`, `POOL_MAX_AGE = 300 s`, `HB = 30 s`,
  `MAX_ACTIVE = 32`, warm-pool size 4, `PER_IP_MAX_CONCURRENT = 2`, per-IP mint
  rate limit, the 120 s at-cap reclaim floor, container spec / `INSTANCE_SPEC`
- Host `systemd` timer unit (independent hard-ceiling backstop; force-removes any
  `demo.*`-labeled container older than `HARD_TTL + POOL_MAX_AGE + 120 s slack = 1320 s`, swept
  `every 60 s` via `OnUnitActiveSec=60s`/`OnBootSec=60s`) + startup-sweep hook +
  the loopback/sentinel `drain` trigger (SIGTERM = fast shutdown, not drain)
- Unit tests: lifecycle transitions, **hard-TTL immovability** (an instance aged
  in the pool to ~250 s then assigned still survives a full 900 s **from
  assignment**, and the creation+1200 s backstop does not kill it early), **idle
  reclaim** (heartbeating — including `detect`/sub-plan calls that refresh
  `last_activity` — but no activity for `IDLE_TTL` → destroyed), startup sweep of
  orphaned `demo.*`-labeled containers, token unguessability, framing-header
  rewrite, cookie routing (incl. the `/i/{t}/{path}` allowlist: bare `/i/{t}/` and
  `/i/{t}/api/v1/backups` → 404, `/i/{t}/migrate` → 200), proxy streams without
  buffering to disk (tmpdir watch), longest-idle reclaim (never a <120 s session),
  per-IP cap, 503-at-cap, and concurrent-mint safety under the lock
