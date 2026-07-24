# 00 — Overview

## Purpose

Give any visitor a zero-install way to paste a network config and watch
netcanon translate + audit it, with **architectural confidence — isolation and
destruction at the container boundary, with every claim mapped to a verifiable
control**. The demo is a trust artifact as much as a product artifact: its
architecture *is* the marketing claim.

## Goals

1. **Instanced execution.** Each browser session gets its own netcanon
   container. No cross-session data visibility is possible even in the presence
   of an application-level bug, because isolation is at the container boundary.
2. **Provable ephemerality.** Instance lifetime is capped by a **15-min hard TTL**
   (`HARD_TTL=900 s`, ≤ ~20 min from creation even if the warden crashes) that
   nothing the browser does can extend, and is reclaimed sooner in the common
   cases: on browser close, and after **10 min** with no allowlisted proxied POST
   (translate, detect, or sanitize) (`IDLE_TTL=600 s`, tightened under load). All
   instance state lives on
   tmpfs (RAM). Teardown = memory freed = data gone. Nothing to delete because
   nothing was written.
3. **Zero retention.** No request bodies, no pasted configs, no translated
   output, no per-user identifiers in any log or store that survives the
   session. Host logs carry operational metadata only (see [04](04-container-hardening.md#logging)).
4. **Auditable.** Every claim in the whitepaper ([06](06-privacy-whitepaper.md))
   maps to a config line in the public repo and a verification procedure in
   [08](08-testing-verification.md).
5. **Cheap and boring.** Single small VPS, Docker, Caddy. Budget headline:
   **~$7.40/mo demo-attributable (the domain is shared with the main site)**
   ([07](07-budget.md)).

## Invariants

These override everything else in this plan.

- **I1 — No persistent writes from demo instances.** Demo containers run with
  read-only root filesystem, tmpfs for all writable paths, and **zero volumes**.
  The image declares `VOLUME ["/app/configs", "/app/data"]` (Dockerfile:113), so
  **both** must be tmpfs-backed — a missed one becomes a persistent anonymous
  host-disk volume that falsifies "zero volumes" — and instances are destroyed
  with `remove(v=True, force=True)` so no anonymous volume can survive (see
  [04](04-container-hardening.md#container-spec-per-instance)).
- **I2 — No demo payload ever reaches disk.** Not in proxy logs, not in warden
  logs, not in netcanon logs, not in swap (swap disabled or encrypted-ephemeral).
- **I3 — Hard TTL.** The warden destroys any instance **≤ 15 min after
  assignment** (`HARD_TTL=900 s`, in-RAM reaper, `deadline = assignment_time +
  HARD_TTL`) regardless of heartbeats or activity. Nothing the browser does can
  extend a session past it; the separate idle reclaim (`IDLE_TTL=600 s`) and
  heartbeat timeout only ever *shorten* life. The in-memory session dict alone
  would orphan live instances on a warden crash/restart, so the hard TTL is
  enforced across **two independent enforcement domains (the warden and host
  systemd), three mechanisms**: (1) the warden's in-RAM reaper at `deadline =
  assignment_time + HARD_TTL`; (2) the warden's **startup label-sweep**, which
  force-removes every `demo.*`-labeled container it did not itself just create
  (every instance is labeled at creation — `demo.created_at`, `demo.instance` —
  the immutable labels the sweep keys on; the token does not exist at create); and
  (3) an **independent host `systemd` timer** (swept every 60 s) that force-removes
  any `demo.*`-labeled container older than `HARD_TTL + POOL_MAX_AGE = 1200 s`.
  Because the reaper recycles any unassigned pool instance older than
  `POOL_MAX_AGE − reaper_period` (~290 s), no instance is ever *assigned* more than
  `POOL_MAX_AGE` (300 s) after creation, so a live session's creation-age deadline
  is ≤ 1200 s and the backstop — which removes only containers *older than* 1200 s
  — never fires before the in-RAM 900 s assignment-relative deadline (see
  [04](04-container-hardening.md#host-level-complements)).
- **I4 — Instances are not publicly routable.** Only the warden/proxy can reach
  them, on an internal Docker network with inter-container isolation.
- **I5 — Egress-locked instances.** Demo containers have no outbound internet
  access. (Translation is local computation; egress is pure risk.)
- **I6 — The deployment is reproducible from the public repo.** Anyone can
  diff the running system's compose file hash against the published one.
- **I7 — Resource-capped.** Per-instance CPU/RAM/pids limits and a global
  instance cap; when full, visitors get a friendly "demo at capacity" state,
  never a degraded-isolation fallback.

## Success criteria

- Visitor lands → instance ready in **< 3 s** (warm pool) → pastes config →
  sees translation + Tier-3/audit banners → closes tab → instance destroyed.
  The `pagehide` `sendBeacon` makes teardown near-immediate; absent a beacon,
  the session is reclaimed **≤ 2 min for a closed foreground tab, ≤ ~4 min for a
  throttled background tab** — 30 s heartbeat + a visibility-aware stale threshold
  (75 s visible, 180 s hidden) + ~10 s reaper — *not* 60 s, which the heartbeat
  math cannot deliver. An open-but-idle tab (heartbeating, but no
  translate/detect/sanitize activity) is reclaimed at the 10-min idle TTL (sooner
  under heavy load); at the 15-min hard TTL, every instance is destroyed
  unconditionally.
- Every whitepaper claim passes its [08](08-testing-verification.md) procedure
  on the live host.
- `docker diff` on a live demo instance shows changes only under tmpfs mounts.
- A full teardown leaves `docker ps -a`, `docker volume ls`, and the host
  filesystem with **zero** artifacts attributable to the session.

## Glossary

- **Warden** — the small session-manager service (FastAPI, ~300 lines) that
  owns the Docker socket, spawns/destroys instances, and proxies traffic to
  them. Spec: [03](03-warden-spec.md).
- **Instance** — one hardened netcanon container bound to one browser session.
- **Warm pool** — N pre-created, never-yet-assigned instances kept ready so
  session start is instant. An instance is assigned exactly once.
- **Session token** — random 128-bit URL-safe token minted by the warden;
  the only linkage between a browser and its instance; held in memory only.
