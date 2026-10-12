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

**What one paste can do to an instance** (measured 2026-10-12, Docker
Desktop: a container with this instance's limits — 256 MiB and no swap, half
a CPU, 128 pids, read-only root — started by the image's own entry point,
`netcanon serve`, with `NETCANON_CONFIG_LIMITS=small`; memory is the cgroup's
own `memory.peak`, of 268.4 MB).  An instance idles at 84 MB after two small
translations.  Every row is a fresh container and one round of requests sent
again and again: until the peak had not risen by half a megabyte in twelve
rounds (and at least fifteen had been run), or for sixty rounds, whichever
came first.  The arrow is the peak after the first round and after the
last; the last column is how many rounds, and whether the peak had stopped
rising.  The first seven rows were sent five or six times each.  Up to four
such containers ran at a time, on a machine that was running this project's
tests besides: that does not move the memory, and it does move the seconds.

| The request | The visitor gets | Most memory | Rounds |
|---|---|---|---|
| A real 48-port switch whose trunks state `1-99,101-4094` (5 KB) | translated in 0.04–0.07 s | 87 → 89 MB | 5 |
| One AOS-S line of 800 port ranges (11 KB) | `refused` in 0.00–0.01 s | 86 → 87 MB | 5 |
| 1,000 Arista trunks that allow 2-4000 (91 KB) | `refused` in 0.02–0.04 s | 91 → 93 MB | 5 |
| 1,000 trunks that allow every VLAN x 1,000 VLANs (118 KB) | `refused` in 0.03–0.05 s | 92 → 94 MB | 5 |
| 32,000 addresses on one Junos unit (2.0 MB) | translated in 1.6–1.6 s | 141 → 143 MB | 5 |
| The largest committed capture (1.1 MB), sanitised as the page does it: the audit, then the output | sanitised, 0.26–0.43 s a request | 95 → 102 MB | 6 |
| the same two requests at once | both sanitised, in turn; 0.6–0.7 s in all | 98 → 104 MB | 6 |
| **Every limit at once** in a 1.98 MB body — 256 trunks that allow every VLAN, 195 VLANs, 2,244 one-line interfaces, static routes to fill — translated to OPNsense | translated in 1.6–2.0 s, a 38 MB answer | 169 → 215 MB | 34; stopped rising (last rise in round 22) |
| the same text, translated to Junos | translated in 1.5–2.1 s, a 7 MB answer | 169 → 175 MB | 27; stopped rising (last rise in round 15) |
| the same text, sanitised: the audit | 1.5–1.8 s | 164 → 170 MB | 33; stopped rising (last rise in round 21) |
| the same text, sanitised: the text itself (7 MB) | 1.9–2.2 s | 182 → 188 MB | 30; stopped rising (last rise in round 18) |
| the same text, sanitised as the page does it: the audit, then the output | 4.2–6.2 s in all | 180 → 188 MB | 23; stopped rising (last rise in round 11) |
| **two translations of it at once** | both translated; the second waits for the first, 3.3–5.2 s in all | 173 → 225 MB | 32; stopped rising (last rise in round 20) |
| **three at once** | all translated, in turn; 6.2–8.4 s in all | 189 → 233 MB | 30; stopped rising (last rise in round 18) |
| the sanitise page's two requests **at once** (as the page used to send them) | both sanitised, in turn; 4.6–7.4 s in all | 183 → 194 MB | 32; stopped rising (last rise in round 20) |
| a translation and the sanitise pair at once | all answered, in turn; 6.0–9.8 s in all | 185 → 224 MB | 24; stopped rising (last rise in round 12) |
| three sanitise requests at once | all sanitised, in turn; 6.1–10.1 s in all | 186 → 198 MB | 16; stopped rising (last rise in round 4) |
| 1.98 MB of static routes: two translations at once | both translated, 2.6–5.7 s in all | 165 → 198 MB | 18; stopped rising (last rise in round 6) |
| 1.98 MB of static routes: the sanitise pair at once | both sanitised, 3.7–5.0 s in all | 156 MB | 15; stopped rising (last rise in round 1) |
| **twelve translations at once** | three translated in turn (1.7–7.8 s); nine answered 503 in words, in 0.00–1.01 s | 186 → 232 MB | 35; stopped rising (last rise in round 23) |
| sixteen at once | three translated; thirteen answered 503, in 0.00–1.15 s | 183 → 233 MB | 23; stopped rising (last rise in round 11) |
| twenty at once | three translated; seventeen answered 503, in 0.00–2.15 s | 185 → 237 MB | 44; stopped rising (last rise in round 32) |
| thirty at once | three translated; twenty-seven answered 503, in 0.00–2.57 s | 184 → 236 MB | 43; stopped rising (last rise in round 31) |
| three sanitise requests at once, then ten translations at once, alternating | every sanitise request answered; of each ten translations three translated and seven answered 503 | 187 → 230 MB | 28; stopped rising (last rise in round 16) |
| an honest heavy visitor: reading the vendor and the device out of the paste and translating it, at once; then the sanitise pair in turn; sixty times over | every request answered, none refused | 185 → 222 MB | 60; stopped rising (last rise in round 11) |

`oom_kill` was 0 in every row.  `/health` was answered all the while: its
slowest answer was 433 ms in the rows above "twelve translations at
once", and 1022 to 1956 ms in the bursts and the alternating
row.  Most of the 503s of a burst came back in under 0.05 seconds; the
slowest of each row is in the table.

So with `small`, one request does not end an instance, and the three texts
that used to take hundreds of megabytes or gigabytes are refused in
milliseconds.  **Requests at once do not end it either**, and that is four
things, each found by measuring a container like this one:

* An instance works on one request that reads config text at a time; a
  second waits its turn inside its own 20 seconds, at most 2 wait, and one
  more is refused in words that say the server was busy and to send it
  again.
* A request is counted when its headers arrive; there are 3 places, and a
  request that finds them taken is answered 503 before its body is read.
  A body used to be read before its request could ask for a turn, so a
  burst cost what all its bodies cost, however few were let work.
* At its request's deadline an answer nobody has read is abandoned, so
  an answer has the request's 20 seconds to be read in; and the system
  ends the connection of a client that has taken nothing for that long
  (`netcanon serve` asks it to, on the socket it listens on).
* The sanitiser redacts the tree it parsed, where it used to copy it:
  the heaviest request an instance takes went from
  231 MB to 188.

**Clients that do not behave**, in the same container:

| What the clients do | What happens | Most memory |
|---|---|---|
| Thirty send a translation with a two-megabyte body and leave; a small translation is sent a second later (36 rounds) | three of the thirty are worked on, for nobody; the small translation is translated after 0.0–3.8 s in 18 rounds and answered 503 at once in 18 | 187 → 232 MB; stopped rising |
| Eight of the largest translations, one about every twenty seconds (19.5 s after the instance's counters were read for the last), whose answers are never read | each answer is abandoned at its request's 20 seconds, with 0.4–3.8 of its 38 MB taken; a small translation sent meanwhile is translated at once | 168 → 186 MB; socket buffers 4.2 MB at most |
| Forty of them, twice (two fresh containers) | the same: 40 abandoned each time, the instance alive after all 40 | 169 → 198 MB and 173 → 206 MB; socket buffers 4.3 MB at most |
| One largest translation read at a megabyte a second; a small one sent 3 s after it (3 rounds) | the reader gets 24–28 of its 38 MB, and the connection is closed on it at its request's 20 seconds; the small one waits 17.0 s for the turn and is translated | 170 → 178 MB |
| Three send their headers and one byte of body, and no more | each is answered 408 at 20.0 s; another request sent meanwhile is answered 503 at once | 86 MB |
| 400 ask for the migrate page and read nothing | every one is served; a translation sent meanwhile is translated at once | 96 → 103 MB |

**What the same requests did before**, measured the same day with the image
of each stage:

| The request | Before | Now |
|---|---|---|
| three translations at once | the release before the limits, and the limits without turns: killed in the first round, both | 189 → 233 MB |
| twelve at once | with turns, a body read before its request was counted: 214 → 267 MB in 30 rounds, and still rising | 186 → 232 MB |
| twenty at once | the same image: 266 MB after the first burst, at its limit after the second, killed in the fourth | 185 → 237 MB |
| three sanitise requests at once, then ten translations, alternating | the same image: killed in the sixth round | 187 → 230 MB |
| thirty clients that send and leave | the same image: killed in the second round | 187 → 232 MB |
| answers nobody reads, one about every twenty seconds | the same image: 172, 215 and 254 MB after the first three, killed at the fourth | 169 → 198 MB and 173 → 206 MB after 40 |
| three sanitise requests at once | the same image: 251 → 264 MB in 20 rounds, and still rising | 186 → 198 MB |

Three things remain.  **The peaks are high.**  One translation of the
largest text takes an instance to 215 MB of its 268, three at once to
233, and a burst to 232–237: that is the size of one request, most of
it nothing a limit counts (two megabytes of static routes), and what the
process keeps.  **An instance does not come back down**: after ten or more
rounds of the largest requests it holds 148 to 190 MB at rest, where it
idled at 84.  The next request uses the memory again, so the peaks stop
rising -- every row was sent until its peak had, or says that it had not
-- but they stop high.  **Nothing limits connections.**  What one
connection can make an instance hold is small now, and not nothing: the
table above is what was tried.  A visitor with connections enough can
still end their own sandbox, and nobody else's; past this the levers are
a limit on connections to an instance and the size of an answer, not the
counts.

The limits themselves are what was left after lowering them until the
counted part was small beside the rest.  With everything above in, the
numbers they were lowered from were measured again: with `vlan_ids` at
four times its number and `interfaces` and `memberships` at twice theirs,
the request built for those limits, translated 37 times, took an
instance to 238 MB, and sanitised as the page does it 34 times, to
202 MB; both had stopped rising.  The numbers were not changed.
Re-measure on the real host with the release's own image, as for the
numbers above.

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
