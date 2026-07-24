# 07 — Budget & Sizing

## Monthly costs

| Item | Cost | Notes |
|---|---|---|
| Hetzner CX32, Falkenstein (4 vCPU / 8 GB / 40 GB / 20 TB) | ~€6.80 (~$7.4) | Launch default; the entire runtime |
| — US alternative: Hetzner CPX32, Ashburn/Hillsboro | re-price + re-verify traffic | Shared-vCPU AMD line; CX is EU-only and CPX included traffic is much lower ([02](02-deployment.md#host)) |
| Domain (.dev or similar) | ~$12/yr ≈ $1/mo | Shared with the main site — **not demo-attributable** |
| TLS | $0 | Let's Encrypt via Caddy |
| Container registry | $0 | GHCR public |
| **Total** | **~$7.40/mo demo-attributable** | The CX32 box is the only demo-attributable runtime cost (~€6.80 ≈ $7.40); the ~$1/mo domain is shared with the main site, so it is **not** demo-attributable |

Budget headline: **~$7.40/mo demo-attributable (the domain is shared with the
main site)**.

Explicit non-costs: no managed k8s, no load balancer, no log/analytics SaaS
(prohibited by design anyway), no CDN (page is ~50 KB).

## <a name="sizing"></a>Sizing math

Size `MAX_ACTIVE` off the **real held-session RSS**, not the 256 MB hard cap.
The 256 MB `mem_limit` is a fail-closed OOM guardrail — a runaway instance is
killed and destroyed, the correct failure mode — **not** the sizing basis. A
held netcanon session actually resides at **~90–140 MB RSS** (parsing and
translation are short bursts; between requests the instance is near-idle) plus a
few MB of container/exec-shim overhead.

- **CX32 (8 GB):** 8192 MB − (OS+Docker ~400) − (caddy+warden ~200) ≈ **7.4 GB
  usable**. At ~150 MB effective per held session that is ~49 theoretical; set
  `MAX_ACTIVE = 32` (warm pool 4 counts toward it), leaving headroom so that even
  a cluster of simultaneous translation bursts stays under RAM and under the
  per-instance caps.
- **Deliberate >100 % cap-sum.** The per-instance 256 MB is an OOM guardrail,
  not a reservation; the cap-sum (`32 × 256 MB = 8 GB`) deliberately exceeds the
  7.4 GB usable — sizing is off the real ~90–140 MB held RSS, and an instance
  that tries to reach its cap is OOM-killed (destroyed), the correct failure
  mode (swap-off + `memswap_limit == mem_limit` means reaching the cap can only
  end in a kill, never in swap thrash).

Per-box defaults:

| Box | vCPU / RAM | `MAX_ACTIVE` | warm pool | idle / hard TTL |
|---|---|---|---|---|
| CX22 | 2 / 4 GB | 14–16 | 3 | 600 / 900 s |
| **CX32 / CPX32** (launch default) | 4 / 8 GB | **32** | **4** | **600 / 900 s** |
| CX42 / CPX41 | 8 / 16 GB | 60–80 | 6 | 600 / 900 s |

The fail-closed story (**I7**) still holds: at cap the pool drains and
`/session/new` returns `503 {"reason":"capacity"}` with client auto-retry — the
demo refuses rather than degrades isolation. A front-page spike (HN/Reddit) can
push the arrival rate several-fold above sustained usage; the answer is that 503
+ auto-retry + longest-idle reclaim, not over-provisioning.

### Why not a smaller (Alpine) base image

Shrinking the instance image with Alpine is tempting for RSS, but **rejected**:
it invalidates the hash-locked, glibc-built `requirements.lock` (forcing
musllinux/source builds) for a ~10 % RSS win that does **not** change the sizing
tier above and does **not** speed warm-pool refill (the image is already cached;
container start is dominated by Python import, and refill is async). The base
stays **`python:3.14-slim-bookworm`**; its digest + hash-lock chain is a
whitepaper reproducibility asset (**I6**, pinned in
[02](02-deployment.md#image-supply-chain)).

## Scale levers (in order, if ever needed)

Concurrent occupancy follows **Little's Law, `L = λ · W`**: the number of live
instances `L` is the arrival rate `λ` times the mean dwell `W` (session
lifetime). `W`, not the box, is the highest-leverage term — so tune it first;
upsize the box last.

1. **Shorten `W` (idle TTL + reliable teardown) — the primary lever, zero cost.**
   The dwell that binds capacity is set by the **idle TTL**, not the hard
   ceiling: an open-but-untouched tab lingers at most `IDLE_TTL = 600 s` (10 min),
   and only a user *actively translating* rides the full `HARD_TTL = 900 s`
   (15 min) ceiling — rare, and exactly the visitor you want to serve. Take the
   idle case `W = 10 min`: at `λ = 4` sessions/min that is `L = 4 × 10 = 40`
   concurrent, over CX32's 32. But real `W` is far below that: most sessions end
   on `pagehide`, the no-beacon reclaim is **≤ 2 min for a closed foreground tab**
   (30 s heartbeat + 75 s visible stale + 10 s reaper) and **≤ ~4 min for a
   throttled background tab** (30 s + 180 s hidden stale + 10 s reaper), and idle
   tabs are reaped at 600 s regardless of heartbeats. Drop the effective `W` to
   ~2 min and the same `λ` gives `L = 4 × 2 = 8` concurrent. Reliable teardown
   plus the idle TTL are what keep `L` small.
2. **Occupancy-driven tightening (automatic, with hysteresis).** Above **80 %**
   occupancy, tighten the **idle TTL** (`600 s → 300 s`) so untouched tabs are
   reclaimed twice as fast; below **70 %** it **loosens back** (`300 s → 600 s`)
   — the gap between the two thresholds prevents thrash between 70–80 %. The idle
   TTL is a single global reaper parameter compared at reap time, so a tightening
   applies **retroactively** to already-idle sessions (~10–20 s: it takes effect at
   the next reaper tick, and a session already beyond the new threshold is reaped
   one tick later). The 15-min hard ceiling is left intact (you don't
   renege on the advertised number); keep the per-IP concurrent-session cap
   (`PER_IP_MAX_CONCURRENT = 2`); and reclaim the longest-idle (never-translated)
   session — never one younger than the 120 s min-age floor — before ever
   returning a 503.
3. **Warm-pool tuning** — raise the pool only if mint latency (not RAM) is the
   constraint. Note the recycle floor: pooled instances are recycled at
   `POOL_MAX_AGE − reaper_period` (~290 s, ≈ every 5 min), so at zero traffic a pool of 4 turns over
   ~1,150 create/destroy cycles/day — negligible CPU (async, single-flight
   refill) but real, and a burst landing in a refill gap degrades to a sub-3 s
   synchronous create, not a failure. A pooled instance's pre-warmed life is thus
   ≤ `POOL_MAX_AGE`, so the pool is sized for mint latency, not warmth duration.
4. **Box upsize — last, and reversible.** Rescale CX32 → CX42 (8/16,
   `MAX_ACTIVE` 60–80, pool 6) same-day; Hetzner bills hourly and a CPU/RAM-only
   rescale that keeps the 40 GB disk is fully reversible.
5. **Fly.io Machines port** ([01](01-architecture.md#framework-decision)) for
   burst/geo scale — only if the demo outgrows a single node, which likely means
   the project has bigger problems to enjoy.

## Cost-abuse guards

- **Warden-enforced** per-IP concurrent-session cap (`PER_IP_MAX_CONCURRENT = 2`,
  held in RAM only) plus request rate limiting — the warden already holds the
  per-IP state, and stock Caddy has no native rate-limit directive
  ([02](02-deployment.md#caddy-configuration-requirements)). The 2 MB
  request-body cap *does* stay in Caddy (native `request_body`). These are two
  distinct guardrails: a single **browser** holds exactly **one** live session
  (the `nc_route` cookie is browser-global, so a second `POST /session/new` from
  it destroys-and-replaces the first), while the per-**IP** cap of 2 bounds
  distinct browsers/devices behind one NAT — a single browser can never
  self-collide with the cap.
- Occupancy-driven TTL tightening and longest-idle reclaim (above) keep a burst
  from turning into runaway spend; the demo returns 503 before it degrades.
- `pids_limit`, CPU and memory caps make a hostile instance self-limiting;
  no egress (**I5**) makes it useless as an attack platform.
- Hetzner's 20 TB EU egress allowance is ~3 orders of magnitude above plausible
  demo traffic (the US CPX allowance is much lower — re-verify per
  [02](02-deployment.md#host)).

## Deliverables

- `MAX_ACTIVE` (32), warm-pool size (4), `HARD_TTL` (900 s), `IDLE_TTL` (600 s,
  tightening to 300 s above 80 % occupancy and loosening back below 70 %), the
  per-IP concurrent-session cap (`PER_IP_MAX_CONCURRENT = 2`), and the occupancy
  tighten/loosen thresholds (80 % / 70 %) as env-configurable warden settings
  with the above defaults committed
- A one-paragraph "capacity philosophy" note in the whitepaper (fail closed,
  never degrade isolation)
