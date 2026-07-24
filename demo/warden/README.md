# demo/warden — ephemeral-demo session manager (Trusted Computing Base)

The **warden** is the one stateful service behind the netcanon public demo
(`demo.netcanon.net`). It owns the warm pool of hardened netcanon instances,
mints one per browser session, reverse-proxies to it, and enforces every
lifecycle/isolation invariant. Spec: [`docs/demo-plan/03-warden-spec.md`](../../docs/demo-plan/03-warden-spec.md)
+ [`04-container-hardening.md`](../../docs/demo-plan/04-container-hardening.md).

## Files

| File | Role |
|---|---|
| `constants.py` | **Single source of truth** — `INSTANCE_SPEC` (the hardened container create kwargs), all TTLs/caps, and the route allowlist the whitepaper cites. |
| `app.py` | The warden: warm pool, mint/heartbeat/end, reaper (hard-TTL / idle / heartbeat), per-IP caps, streaming proxy (strip `X-Frame-Options`, rewrite CSP `frame-ancestors`, route by `nc_route` cookie, default-deny allowlist). Single-process; one `asyncio.Lock`, reserve-then-fill (never held across a docker call). |
| `authz_shim.py` | The **create-body authz shim** — validates every `POST /containers/create` against `INSTANCE_SPEC` (whole-body default-deny) so an injected `Privileged` / `CapAdd` / bind-mount is impossible. |
| `Dockerfile` | Two targets: `warden` and `shim`. |

## Privilege chain

```
browser → Caddy(:443) → warden → authz-shim → docker-socket-proxy → docker.sock
                          │            │              │
                     (session mgmt) (create-body   (verb allowlist:
                                      default-deny)  create/start/list/inspect/remove)
```

`read_only` + non-root on the warden container does **not** constrain the Docker
socket (root-equivalent on the host); the socket-proxy (verbs) **and** the shim
(create bodies) are the real boundary. Both are counted in the TCB.

## Run locally (Gate 1)

Requires the full stack (warden + socket-proxy + `demo-int`/`warden-sock`
networks + a pinned instance image). The `deploy/` compose that wires this is
the next PR; until then the warden refuses to start unless
`NETCANON_INSTANCE_IMAGE=ghcr.io/netcanon/netcanon@sha256:<digest>` is set and
that image is present locally.

## Status

⚠️ **Warden core — not yet Gate-1 verified.** This PR is the authored
implementation. Before it is deploy-ready it needs: the local Gate-1 compose
stack + the CI test table ([`08-testing-verification.md`](../../docs/demo-plan/08-testing-verification.md)),
an adversarial security review of the TCB (socket-proxy verbs, the shim's
default-deny, the reaper/lock discipline), the `X-API-Key` header name confirmed
against netcanon's API auth, and a hash-locked `requirements.lock`.
