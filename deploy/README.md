# deploy — netcanon ephemeral demo (demo.netcanon.net)

The production stack + host provisioning for the public demo. Spec:
[`docs/demo-plan/02-deployment.md`](../docs/demo-plan/02-deployment.md). The
warden/shim live in [`demo/warden/`](../demo/warden/).

## Files

| File | Role |
|---|---|
| `docker-compose.yml` | Production stack: caddy + warden + authz-shim + socket-proxy, 3 networks. Image refs are env-interpolated so the file stays digest-free — its in-repo hash **is** the published hash (**I6**). |
| `docker-compose.dev.yml` | Local Gate-1 override — builds warden+shim from source. |
| `Caddyfile` | TLS termination (Let's Encrypt; DNS-only Cloudflare → Caddy is the sole terminator), static landing/whitepaper, reverse-proxy to the warden, 2 MB body cap, no request logs on demo paths. |
| `cloud-init.yaml` | Hardened Ubuntu 24.04: docker, **swap-off + core-dumps-off + journald-volatile** (I2), **fail2ban (SSH)**, unattended-upgrades, host firewall (443/80 + admin-only SSH), chrony, OOM protection, the TTL-backstop timer. |
| `systemd/` | `demo-ttl-backstop.{sh,service,timer}` — the warden-independent hard-TTL backstop (removes any `demo.*` container older than 1200 s, every 60 s). |
| `nftables/demo-int.nft` | The demo-int isolation rules (warden→instance ALLOW, instance→instance DENY, instance→warden DENY). |
| `Makefile` | `verify` / `deploy` / `drain` / `down` + `dev-up` for local Gate-1. |
| `demo.env.example` | Env template (image digests + ACME email). Copy → `demo.env` (**gitignored**; real values never commit). |
| `PINNED_PRODUCT_TAG` | The netcanon version the demo pins (`v0.6.1`). Bumped by ordinary PR. |

## Local Gate-1 (needs Docker)

```bash
cd deploy
cp demo.env.example demo.env    # edit: CADDY_IMAGE=caddy:2, SOCKET_PROXY_IMAGE=tecnativa/docker-socket-proxy,
                                #       NETCANON_INSTANCE_IMAGE=ghcr.io/netcanon/netcanon:0.6.1, ACME_EMAIL=...
docker pull ghcr.io/netcanon/netcanon:0.6.1
make dev-up
```

## Deploy (human-pulled, on the host)

`make deploy` (verify signatures/SHA256SUMS — Gate-4 — then pull pinned images + `up -d`). No GitHub deploy secret exists; the operator SSHes in and runs it, then executes the Gate-4 live proofs.

## DDoS / abuse posture

- **L7 abuse:** warden per-IP concurrency cap (2) + mint rate limit (≤30/600 s), Caddy 2 MB body cap, fail-closed 503 at `MAX_ACTIVE`, per-instance cpu/mem/pids caps, no egress.
- **SSH:** fail2ban jail (above).
- **Volumetric L3/L4:** ⚠️ **not mitigated** — DNS-only Cloudflare exposes the origin IP and adds no scrubbing; only Hetzner's free network-edge protection applies. A conscious residual of the DNS-only trust-model choice (orange-cloud would fix it but adds Cloudflare to the TCB). The no-log privacy design also limits fail2ban-on-HTTP.

## Status — ⚠️ draft, not yet Gate-1/Gate-3 verified

Authored against the spec; needs a live Docker host to verify. Known verify points (flagged inline): the socket-proxy verb/DELETE behavior, the `DOCKER-USER` nftables ordering/idempotency + post-daemon-reload survival, `make deploy`'s signature/SHA256SUMS gate (Gate-4), and pinning the SSH source in `cloud-init.yaml`. Nothing is deployed.
