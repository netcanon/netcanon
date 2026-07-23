# 02 — Deployment

## Host

**Launch default: a CX32-class box** (4 vCPU, 8 GB RAM, 40 GB NVMe) running
Ubuntu 24.04 LTS. Location is an explicit fork — and because the CX line is
**EU-only**, the originally-drafted "CX22 + Ashburn" is not a real SKU:

- **EU — Hetzner CX32, Falkenstein** (4 vCPU / 8 GB / 40 GB / 20 TB traffic,
  ~€6.80/mo). Preferred: EU hosting is itself on-message for a privacy demo, and
  the 20 TB traffic allowance is generous.
- **US — Hetzner CPX32, Ashburn or Hillsboro** (4 vCPU / 8 GB, shared-vCPU AMD
  line, US latency for the primary audience). Must be **re-priced** and its
  much-lower included-traffic allowance **re-verified** before committing — the
  CX line does not exist in the US regions.

Rationale: fits the operator's existing Hetzner + hardened cloud-init workflow;
8 GB comfortably holds warden + Caddy + a warm pool + ~32 capped instances, sized
off *real* held-session RSS rather than the 256 MB hard cap
([07](07-budget.md#sizing)). Hetzner bills hourly, so the box can be **rescaled
up same-day** (CX32 → CX42) if the launch lands — a CPU/RAM-only rescale that
keeps the 40 GB disk, so it stays fully reversible ([07](07-budget.md#sizing)).

## Provisioning (cloud-init)

Reuse the existing hardened Ubuntu 24.04 cloud-init baseline, plus demo-specific
items:

- Docker Engine (official repo), compose plugin.
- **Disable swap** (`swapoff -a`, remove from fstab) — closes the "pasted
  config swapped to disk" hole. With hard per-instance memory caps this is safe;
  document it as a whitepaper control (**I2**).
- **Disable core dumps host-wide** — swap-off is not the only RAM→disk path; a
  crashing process can also spill a pasted config to a core file. In cloud-init
  set `kernel.core_pattern` to discard, `systemd-coredump` `Storage=none` +
  `ProcessSizeMax=0`, remove/neuter `apport`, and set `docker.service`
  `LimitCORE=0`. Documented alongside swap-off as a whitepaper control (**I2**).
- UFW / nftables: inbound 443 (and 80 for ACME redirect only), SSH restricted
  to admin IPs or an admin VPN, default-deny otherwise.
- Unattended-upgrades (security), fail2ban for SSH.
- `journald` config: `Storage=volatile`, `RuntimeMaxUse=64M` — host logs live
  in RAM and rotate aggressively; nothing session-derived is in them anyway
  ([04](04-container-hardening.md#logging)), this is defense in depth.
- Non-root deploy user in `docker` group; warden is the only Docker-socket
  consumer ([03](03-warden-spec.md#socket)).
- Time sync (chrony) — TTL enforcement and audit timestamps depend on it.
- **`OOMScoreAdjust=-500`** on `docker.service`, the warden, and Caddy (systemd
  drop-ins) — under host memory pressure the OOM killer then targets an
  **instance**, never a core service, so a runaway paste is killed in its own
  container instead of taking down the warden or Caddy
  ([07](07-budget.md#sizing)).
- **Host hard-TTL backstop timer** — a `systemd` timer + oneshot service that
  runs `every 60 s` (`OnUnitActiveSec=60s`, `OnBootSec=60s`) and force-removes
  any `demo.*`-labeled container whose `demo.created_at` is older than
  `HARD_TTL + POOL_MAX_AGE = 1200 s` (20 min). This is the warden-independent
  enforcement domain: it holds the creation-age ceiling even while the warden is
  dead ([03](03-warden-spec.md#lifecycle-rules),
  [04](04-container-hardening.md)).

## DNS + TLS

- `demo.netcanon.dev` (or subdomain of whatever the main site domain becomes)
  → A/AAAA to the VPS.
- Caddy with automatic Let's Encrypt. HSTS on. TLS ≥ 1.2.
- Main site (static) can live on the same Caddy or on GitHub Pages; only the
  demo requires this host.

## Caddy configuration requirements

- Serve static frontend at `/`.
- Reverse-proxy the warden's surface — `/session/*`, `/i/*`, and the allowlisted
  netcanon app paths the warden re-routes **by session cookie** (netcanon's UI
  uses absolute URLs and has no root-path support, so the warden routes by
  session, not path-prefix; allowlist in [04](04-container-hardening.md),
  warden detail in [03](03-warden-spec.md#socket)) — **with access-log body
  capture disabled and URI logging truncated**. Access logs, if enabled at all,
  log method + status + latency only; simplest compliant setting is access logs
  **off** for `/i/*`, `/session/*`, **and every allowlisted cookie-routed app
  path** — everything else stays status-only (**I2**).
- Request body limit: **2 MB** (largest reasonable running-config; blocks abuse).
  This one Caddy does natively (`request_body max_size`).
- **Rate limiting is not at the Caddy layer.** Stock Caddy has *no* native
  rate-limit directive. Rather than run an unpinned plugin, rate limiting moves
  **into the warden**, which already holds per-IP state for its concurrent-
  session cap ([07](07-budget.md#cost-abuse-guards)). If a Caddy-layer limit is
  ever wanted it must be an `xcaddy` build with the **self-built binary pinned
  by digest** so `make verify` stays honest (**I6**) — otherwise keep it in the
  warden.
- Security headers on the **static page**: HSTS, X-Content-Type-Options, a CSP
  for the page itself, and **`Referrer-Policy: same-origin` on all demo paths**
  (session tokens ride in the URL path, so a permissive referrer would leak them
  on outbound clicks).
- **Framing is fixed in the warden, not here.** netcanon stamps
  `X-Frame-Options: DENY` and CSP `frame-ancestors 'none'` on every response
  (`main.py:366-374`), so a plain iframe renders blank and a Caddy-*added*
  `frame-ancestors 'self'` cannot relax it (multiple CSP headers intersect). The
  warden therefore **strips `X-Frame-Options` and rewrites the instance CSP
  `frame-ancestors 'none'` → `'self'` on every proxied response**
  ([03](03-warden-spec.md#proxying)).

## Image supply chain

- Pin the netcanon image **by digest** in the warden's config
  (`ghcr.io/netcanon/netcanon@sha256:…`), not `:latest`. The digest is printed
  in the whitepaper's reproducibility section and bumped deliberately (**I6**).
- Base image stays **`python:3.14-slim-bookworm`** with a hash-locked
  `requirements.lock`; that digest + hash-lock chain is itself a whitepaper
  reproducibility asset (**I6**). Alpine is deliberately **rejected** — rationale
  in [07](07-budget.md#sizing).
- Warden, Caddy, and **socket-proxy** images likewise pinned by digest (the
  socket-proxy is a TCB component; the authz shim ships as repo source, covered by
  the compose/repo hash).
- **The instance image is pulled explicitly.** `docker compose pull` refreshes
  only the warden + Caddy images (the only ones the compose file references); the
  netcanon instance image is created **directly by the warden** and is not in the
  compose file, so the deploy flow adds an explicit
  `docker pull ghcr.io/netcanon/netcanon@sha256:<PINNED_DIGEST>`, and the warden
  **refuses to start if that pinned digest is absent locally**
  ([03](03-warden-spec.md)) — no silent pull-on-demand at the first pool-refill,
  on a fresh host or after any digest bump.
- A `make verify` target re-computes and prints all pinned digests + the
  compose file SHA-256 so any visitor can compare against the published values
  ([08](08-testing-verification.md)).

## Monitoring

Metadata-only, and consistent with the whitepaper ("no visitor tracking" is not
"no operator telemetry"):

- An **external uptime monitor** hitting `/` and `/healthz` from off-host, so an
  outage is visible even if the box wedges.
- `/healthz` exposes only aggregate counters (sessions started, destroys by
  reason, 503 count, pool-refill failures) — no tokens, no per-session detail
  ([03](03-warden-spec.md#socket)).
- A synthetic **mint → translate-sample → end** probe a few times an hour,
  exempt from the per-IP session cap, to catch a silently-broken pool.

## Update/redeploy flow

`git pull && docker compose pull && docker pull ghcr.io/netcanon/netcanon@sha256:<PINNED_DIGEST> && docker compose up -d`
— the explicit instance-image pull is required because the compose file
references only warden + Caddy (see Image supply chain above).

**Drain and `SIGTERM` are distinct.** **Drain** is a **non-public** operation —
triggered by a **loopback-only (`127.0.0.1`) control endpoint or a sentinel file
the reaper watches**, never a routable HTTP path — that stops minting new
sessions and lets in-flight ones lapse (idle reclaim ~10 min, hard TTL
≤ 15 min) before recreate; expect a short **capacity dip** (existing sessions
finish, no new ones start). **`SIGTERM` is fast shutdown, not drain:**
`docker compose up -d` sends `SIGTERM`, so a redeploy without draining first
**kills live sessions by design** — no state migration exists, and that is an
acceptable choice for a demo. For a graceful window, drain first or raise the
warden container's `stop_grace_period`. Either way, after the redeploy the fresh
warden's startup label-sweep force-removes any leftover `demo.*` containers (it
adopts nothing).

## Deliverables

- `deploy/cloud-init.yaml` (hardened baseline + swap-off + core-dump disable +
  `OOMScoreAdjust=-500` drop-ins + the host hard-TTL backstop `systemd`
  timer/oneshot: sweep `every 60 s`, creation-age ceiling `1200 s`)
- `deploy/Caddyfile`
- `deploy/docker-compose.yml` (caddy + warden + socket-proxy, and three
  networks: `demo-int` `internal: true` (subnet `172.31.0.0/24`, plus
  `driver_opts { com.docker.network.bridge.name: demo-int }` for a stable bridge
  name the `DOCKER-USER` nftables rules can rely on) for instances + warden,
  `warden-sock` for warden + socket-proxy only, and the caddy-facing net for
  warden + caddy)
- `Makefile` with `deploy` (full flow incl. the explicit instance-image
  `docker pull …@sha256:<PINNED_DIGEST>`), `verify`, and a **host-local**
  `drain` target — the drain trigger is the loopback-only (`127.0.0.1`) control
  endpoint / sentinel file (stop minting, let sessions lapse), **not** `SIGTERM`
  (which is fast shutdown) and not a public route
- External uptime monitor configured against `/` and `/healthz`
- DNS + TLS live on the chosen subdomain
