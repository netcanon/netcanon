# 07 — Budget & Sizing

## Monthly costs

| Item | Cost | Notes |
|---|---|---|
| **Hetzner CPX32** (4 shared AMD EPYC vCPU / 8 GB / 160 GB NVMe) | ~€35/mo (confirm in console) | **Launch default.** Chosen because the CX line was out of stock at provisioning time; same 4 vCPU / 8 GB as CX32, so `MAX_ACTIVE = 32` is unchanged |
| — cheaper swap once CX is back in stock: Hetzner CX32 (4 / 8 GB / 80 GB) | ~€6.80 | Same CPU/RAM class. Confirm the included-traffic allowance for your location when switching |
| Domain (netcanon.net) | ~$12/yr ≈ $1/mo | Shared with the main site — **not demo-attributable** |
| TLS | $0 | Let's Encrypt via Caddy |
| Container registry | $0 | GHCR public |
| **Total** | **~€35/mo demo-attributable** | The box is the only demo-attributable runtime cost; the ~$1/mo domain is shared with the main site |

Budget headline: **~€35/mo demo-attributable on CPX32** (the domain is shared
with the main site). That is a deliberate, accepted premium over the ~€6.80 CX32
while the CX line is out of stock — the operator is carrying it for a few months
to see whether the demo draws traffic. If it does not, the honest move is to
take the demo down or move it to CX32, not to shrink the guarantees.

⚠️ **x86 only.** The warden and authz-shim images are built by
`demo-publish.yml` on `ubuntu-latest` with no `platforms:` set, so they are
**amd64-only**. CX and CPX are x86; the **CAX line is ARM** and would fail to
run them. Do not pick a CAX box without adding multi-arch builds first.

Explicit non-costs: no managed k8s, no load balancer, no log/analytics SaaS
(prohibited by design anyway), no CDN (page is ~50 KB).

## <a name="sizing"></a>Sizing math

Size `MAX_ACTIVE` off the **real held-session RSS**, not the 256 MB hard cap.
The 256 MB `mem_limit` is a fail-closed OOM guardrail — a runaway instance is
killed and destroyed, the correct failure mode — **not** the sizing basis.

**These numbers are now measured, not estimated.** `tests/demo/load_sanity.py`
drives N concurrent sessions through real translations and reports RSS; a
32-session run against the full stack gave:

| | measured |
|---|---|
| assigned (worked) instance RSS | **median 72.5 MiB** (min 71.9 / max 73.6) |
| warm-pool (idle) instance RSS | median ~71 MiB |
| control plane | warden ~55 + authz-shim ~73 + socket-proxy ~23 MiB |
| **projected at `MAX_ACTIVE = 32`** | **2471 MiB ≈ 2.41 GiB** |

The worked median is **28 % of the 256 MB per-instance cap**, which is exactly
why the cap is not the sizing basis: sizing off it would imply 8 GB and make an
8 GB box look exactly full.

- **CPX32 / CX32 (8 GB):** measured demand is ~2.4 GiB at the full cap, against
  ~7.4 GB usable after OS + Docker. `MAX_ACTIVE = 32` (warm pool 4 counts toward
  it) therefore leaves roughly 5 GB of headroom — comfortable even when a
  cluster of translation bursts lands at once.
- ⚠️ **Re-measure on the real box before trusting these.** The run above was on
  Docker Desktop, whose VM accounting, page-cache behaviour and CPU quota all
  differ from a bare Hetzner host. Run `python tests/demo/load_sanity.py` there
  as part of Gate 5 and size from *those* numbers.
- **Swap is off (I2), so RAM is a hard wall.** There is no graceful degradation:
  exceeding it means an OOM-kill, and the process most worth protecting is the
  control plane. That is why the headroom above is deliberately generous.
- **Deliberate >100 % cap-sum.** The per-instance 256 MB is an OOM guardrail,
  not a reservation; the cap-sum (`32 × 256 MB = 8 GB`) deliberately exceeds the
  7.4 GB usable — sizing is off the measured ~72 MiB held RSS, and an instance
  that tries to reach its cap is OOM-killed (destroyed), the correct failure
  mode (swap-off + `memswap_limit == mem_limit` means reaching the cap can only
  end in a kill, never in swap thrash).

Per-box defaults:

| Box | vCPU / RAM | `MAX_ACTIVE` | warm pool | idle / hard TTL |
|---|---|---|---|---|
| CX22 | 2 / 4 GB | 14–16 | 3 | 600 / 900 s |
| **CX32 / CPX32** (launch default) | 4 / 8 GB | **32** | **4** | **600 / 900 s** |
| next tier up (~2x) | 8 / 16 GB | 60–80 | 6 | 600 / 900 s |

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
   concurrent, over the box's 32. But real `W` is far below that: most sessions end
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
4. **Box upsize — last, and reversible.** Rescale to the next CPX tier (~2x
   CPU/RAM; confirm the current SKU and price at rescale time —
   `MAX_ACTIVE` 60–80, pool 6) same-day; Hetzner bills hourly and a CPU/RAM-only
   rescale that leaves the disk untouched is fully reversible.
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
