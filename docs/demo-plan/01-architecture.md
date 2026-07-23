# 01 — Architecture

## Framework decision

**Chosen: single VPS + Docker Engine + a purpose-built "warden" session manager
+ Caddy.** Evaluated against alternatives:

| Option | Verdict | Why |
|---|---|---|
| **Docker + custom warden (chosen)** | ✅ | Full control over lifecycle/teardown proofs; one cheap host; no platform trust required — the whitepaper only has to trust *our* config, all of it public. |
| Fly.io Machines | Viable alt | Per-session VMs, per-second billing, auto-stop — genuinely good fit. Rejected as primary because retention proofs then depend on platform attestations you can't independently audit, and cost is less predictable under abuse. Documented as the fallback if the VPS pattern ever needs geographic scale. |
| Kubernetes (k3s) | ❌ | Operationally heavy for one node; adds attack/complexity surface with zero benefit at this scale. |
| Shared single stateless container (no instancing) | ❌ | Cheapest, but "no retention" then rests on application behavior instead of container-boundary destruction. Weaker whitepaper. |
| Serverless (Lambda/Cloud Run) | ❌ | Cold starts, request-scoped not session-scoped, log plumbing you don't control by default. |

## Components

```
                      ┌────────────────────────── VPS (Hetzner CX32) ──────────────────────────┐
                      │                                                                        │
  Browser ── HTTPS ──▶│  Caddy (:443)                                                          │
                      │   ├── /            → static demo frontend (05)                         │
                      │   ├── /session/*   → warden API (mint / heartbeat / end)               │
                      │   └── /i/{token}/* + cookie-routed absolute paths → warden             │
                      │                                                                        │
                      │  Warden (FastAPI, drives docker.sock via socket-proxy)                 │
                      │   ├── warm pool  [inst][inst][inst][inst]   (unassigned, N=4)          │
                      │   ├── active map {token → container, deadline, last_heartbeat, last_activity, hidden} │
                      │   ├── RESPONSE: strip X-Frame-Options, CSP frame-ancestors→'self'      │
                      │   └── REQUEST: route by HttpOnly session cookie, not path-prefix       │
                      │                                                                        │
                      │  netcanon instances  (serve :8000, one container per session)          │
                      │   ├── read-only rootfs, tmpfs, no volumes, no egress, cpu/mem cap      │
                      │   └── nftables: warden→inst ALLOW, inst→inst/inst→warden DENY (04)     │
                      └────────────────────────────────────────────────────────────────────────┘
```

*Box = CX32-class launch default (4 vCPU / 8 GB, EU Falkenstein — EU hosting is
itself on-message for a privacy demo); the location fork (EU CX32 vs US CPX32),
MAX_ACTIVE sizing, and the same-day rescale to CX42 live in
[07](07-budget.md#sizing).*

Caddy never talks to instances directly; the warden is the only path, so token
checks and lifecycle state live in exactly one place. Because netcanon stamps
`X-Frame-Options: DENY` and CSP `frame-ancestors 'none'` on every response
(`main.py:366-374`), a plain iframe would render blank — and Caddy *cannot* relax
that by **adding** a `frame-ancestors 'self'` header (multiple CSP headers
intersect to the most restrictive). So the **warden** rewrites each proxied
instance *response*: it strips `X-Frame-Options` and turns `frame-ancestors
'none'` into `frame-ancestors 'self'`. And because the netcanon UI uses
**absolute** URLs (`fetch('/api/v1/migration/plan')`, `href="/migrate"`) with
**no root-path support**, naive `/i/{t}/` path-prefixing breaks; the warden
instead routes **by session** — it sets the routing cookie on the `/session/new`
mint response and re-stamps it on `/i/{t}/…` responses, bound to that instance
(`Set-Cookie: nc_route=<token>; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=900`
— defined in [03](03-warden-spec.md#proxying); `Path=/` is load-bearing so the
cookie rides **every** allowlisted absolute path, and `Max-Age=900` matches
`HARD_TTL`), and any allowlisted absolute path carrying that cookie is routed to
the mapped container (one active session per browser is already the model). The
routing cookie is warden-set (the frontend page itself sets none) and is
disclosed in the whitepaper's *What we do see* ([06](06-privacy-whitepaper.md)).

## Data flow (happy path)

1. Browser loads static page → `POST /session/new`.
2. Warden pops a warm-pool instance, mints token `t`, records
   `deadline = assignment_time + HARD_TTL` (900 s — `now` is the assignment
   moment) and seeds `last_activity = now`, returns
   `{token, ttl_seconds, expires_at, idle_ttl_seconds, instance_id}` (`ttl_seconds`
   = the 900 s hard ceiling the countdown runs to, computed client-side as
   `receipt_time + ttl_seconds`; `expires_at` is informational only;
   `idle_ttl_seconds` drives the idle indicator; `instance_id` is a display id,
   **not** the routing token). Refills pool async.
3. Browser **iframes** `/i/{t}/migrate` — the netcanon migrate UI, served by
   *that visitor's* instance on `:8000` (bare `/i/{t}/` maps to the instance's
   `/`, the default-denied backup dashboard, and is never the iframe target). On
   that first response the warden strips
   `X-Frame-Options`, relaxes the instance CSP so the frame renders, and re-stamps
   the routing cookie (first set on the `/session/new` mint response); the UI's
   absolute paths (`/migrate`,
   `/api/v1/migration/plan`) then carry that cookie back through the warden to
   the same instance. Pasted config → instance → translation + audit banners
   rendered. **The warden streams bodies; it never logs or buffers them to disk**
   ([03](03-warden-spec.md#proxying)).
4. Browser heartbeats `POST /session/{t}/hb` every 30 s.
5. End of life, whichever comes first:
   - `POST /session/{t}/end` (sent via `navigator.sendBeacon` on `pagehide`
     **only** — not `visibilitychange`→hidden, which fires on a tab-switch and
     would kill the demo's own copy-config-from-another-tab flow) → immediate
     destroy;
   - missed heartbeats → reclaimed **≤ 2 min for a closed foreground tab, ≤ ~4
     min for a throttled background tab** — the warden applies a visibility-aware
     stale threshold keyed to the `{"hidden": <bool>}` each heartbeat reports:
     **75 s** while visible (30 s heartbeat + 75 s + ~10 s reaper ≈ 115 s) and
     **180 s** while hidden to absorb background-timer throttling (30 + 180 + 10 ≈
     220 s) ([05](05-frontend.md));
   - **idle TTL** (10 min / 600 s) → an open tab that keeps heartbeating but sends
     no **allowlisted proxied POST** for `IDLE_TTL` is reclaimed anyway (heartbeats
     don't reset it — only an allowlisted POST does: `plan`, its sub-plans,
     `detect`, `sanitize`); tightened to 300 s above 80 % occupancy, loosens back
     to 600 s below 70 % (hysteresis)
     ([03](03-warden-spec.md#lifecycle-rules));
   - **hard TTL** → destroy unconditionally, enforced independently of the
     in-memory dict: **≤ 15 min after assignment** while the warden is live, and
     **≤ ~20 min after creation** via the startup sweep + host systemd backstop if
     the warden is dead (**I3**).
6. Destroy = `container.remove(v=True, force=True)` (`docker rm -fv`) → container
   + its tmpfs + any anonymous volume freed. Nothing to scrub because nothing
   persisted (**I1/I2**).

## Session lifecycle state machine

```
 POOLED ──assign──▶ ACTIVE ──(end│hb-timeout│idle│hard-ttl│reclaim)──▶ DESTROYED
   ▲  │                                                                │
   │  └──── pool-max-age recycle (unassigned > ~290 s) ────────────────┤
   └───────────────── pool refill (new container) ◀──────────────────────┘
```

The only exit from `POOLED` other than `assign` is **pool-max-age recycle** — the
reaper destroys an *unassigned* instance older than ~290 s (`POOL_MAX_AGE − reaper
tick`) and the pool refills, so no instance is ever assigned older than 300 s
(`POOLED→DESTROYED`, never through `ACTIVE`). On the `ACTIVE→DESTROYED` edge,
`reclaim` is the at-cap longest-idle victim (see the `/session/new` row in
[03](03-warden-spec.md)). `DESTROYED` is terminal; tokens are
never reused; a returning browser gets a fresh instance via a fresh
`POST /session/new`.

## Why instancing at the container boundary

netcanon's translate path is stateless per request, so a shared instance would
*function*. Instancing is chosen because it converts the retention claim from
"the app behaves well" into "the kernel freed the memory": even an application
bug that cached a pasted config could only ever leak it into a container that
is destroyed minutes later and was never reachable by another visitor (**I4**).
That is what makes [06](06-privacy-whitepaper.md) provable rather than
promissory.

## Deliverables

- Architecture section of the site (one diagram, links to whitepaper).
- `docker-compose.yml` expressing: caddy, warden, socket-proxy, and three
  networks — `demo-int` (`internal: true` for no egress; instances **and** warden),
  `warden-sock` (warden **and** socket-proxy only — the socket-proxy is on no other
  network), and the caddy-facing net (warden + caddy). Peer/warden-ward isolation
  is **not** `enable_icc: false` — that is all-or-nothing and would also block
  warden→instance; it is explicit **nftables on the `demo-int` bridge** implementing
  warden→instance ALLOW, instance→instance DENY, instance→warden DENY (see
  [04](04-container-hardening.md)).
- This document's diagram reproduced in the repo (`docs/demo-architecture.md`).

