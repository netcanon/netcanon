# Netcanon Ephemeral Demo — Implementation Plan

One-shot plan for a public-facing, **provably ephemeral** live demo of
[netcanon](https://github.com/netcanon/netcanon). Per-visitor instanced
execution; no demo persists past the **15-minute hard TTL** (`HARD_TTL = 900 s`;
≤ ~23 min from creation even if the session manager crashes) or browser close; no
demo data is ever retained; architecture claims are backed by a verifiable
whitepaper.

## For the implementation agent

Read the modules **in numeric order**. Each module is self-contained but
cross-linked. Modules declare their deliverables in a `## Deliverables` section
— treat those as your task list. `09-implementation-order.md` is the build
sequence with acceptance gates; do not skip gates.

Global invariants (violating any of these is a build failure) are defined in
[`00-overview.md`](00-overview.md#invariants). When any module conflicts with an
invariant, the invariant wins.

## Module map

| # | File | Purpose |
|---|------|---------|
| 00 | [`00-overview.md`](00-overview.md) | Goals, invariants, success criteria, glossary |
| 01 | [`01-architecture.md`](01-architecture.md) | Component design, data flow, session lifecycle |
| 02 | [`02-deployment.md`](02-deployment.md) | Host, DNS, TLS, cloud-init, reverse proxy |
| 03 | [`03-warden-spec.md`](03-warden-spec.md) | Session-manager service: API, lifecycle, limits |
| 04 | [`04-container-hardening.md`](04-container-hardening.md) | Per-instance no-retention controls |
| 05 | [`05-frontend.md`](05-frontend.md) | Demo page, heartbeat, browser-close teardown |
| 06 | [`06-privacy-whitepaper.md`](06-privacy-whitepaper.md) | The provable no-retention whitepaper (publishable) |
| 07 | [`07-budget.md`](07-budget.md) | Costs, sizing, scale ceiling |
| 08 | [`08-testing-verification.md`](08-testing-verification.md) | Proof procedures mapped to whitepaper claims |
| 09 | [`09-implementation-order.md`](09-implementation-order.md) | Build sequence + acceptance gates |

## Upstream facts this plan relies on

- netcanon ships on GHCR: `ghcr.io/netcanon/netcanon:latest`; default
  entrypoint `netcanon serve` binds `0.0.0.0:8000` (`config.py` `port = 8000`,
  `Dockerfile` `EXPOSE 8000` — **not** 8080).
- **As of 0.4.0 the container fails closed on a public bind**: it refuses to
  start unless `NETCANON_API_KEY` is set (gates `/api/v1`) or
  `NETCANON_ALLOW_INSECURE_BIND=1` is set. Setting `NETCANON_API_KEY` alone
  satisfies the non-loopback bind gate, so `NETCANON_ALLOW_INSECURE_BIND` is
  **unnecessary** for the demo; the proxy layer provides the public gate.
- Netcanon otherwise auto-generates a Fernet key file at `data/.fernet_key` on
  first run (to encrypt stored device data). Demo instances set a per-instance
  random `NETCANON_FERNET_KEY` env instead, so **no key file is ever created**
  and the key stays RAM-only.
- The UI uses **absolute URLs** (`fetch('/api/v1/migration/plan')`,
  `href="/migrate"`) and has **no root-path/base-URL support**, so the warden
  routes by a warden-set session cookie, not a path prefix. Netcanon also stamps
  `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'` on every response, so
  the warden must strip XFO and rewrite `frame-ancestors` → `'self'` or the
  demo iframe renders blank (see [03](03-warden-spec.md#proxying)).
- Relevant endpoints for the demo: the migrate page, the sanitize page
  (`/sanitize`), the migration-plan APIs (`POST /api/v1/migration/plan` + its
  `/ports`, `/vlans`, … variants, `POST /api/v1/migration/detect`), and
  `POST /api/v1/sanitize`. There is **no `/api/v1/translate` route**, and `/` is
  the backup **dashboard** (out of scope). Device-backup/devices/schedules/
  configs features are **out of scope** and must be unreachable (see 04).

## Plan currency — reviewed 2026-07-22 (netcanon v0.6.1)

Last reconciled against `main` at **v0.6.1**. The design is unchanged; findings:

- **Upstream facts re-verified, still valid.** `X-Frame-Options: DENY` + CSP
  `frame-ancestors 'none'` are still stamped on every response (now
  `main.py:366-374`; the two `_CSP_*` constants at `:97`/`:116`), and the
  Dockerfile still declares `EXPOSE 8000`,
  `VOLUME ["/app/configs", "/app/data"]`, `USER app`,
  `ENTRYPOINT ["netcanon", "serve"]`. The warden strip-XFO / rewrite-CSP design
  and the tmpfs-**both**-volumes invariant (I1) hold verbatim.
- **UI is now the unified design language** (ui-design-spec v0.2.1, shipped in
  v0.6.1) but is **still fully inline** — the vendored CSS/JS are
  Jinja-`{% include %}`d into `base.html`; there is still **no StaticFiles mount
  and no static assets**, so the "all-inline, cookie-route, no `/static`
  allowlist" reconnaissance in [09](09-implementation-order.md#phase-0) holds
  unchanged. Cosmetic bonus: the demo iframe inherits the visitor's OS
  light/dark via `prefers-color-scheme`. `/docs` stays self-themed / out of scope.
- **`deploy/PINNED_PRODUCT_TAG` target = `v0.6.1`** (the current demo-worthy
  release).
- **Instancing substrate = self-contained VPS (decision recorded).** An
  alternative lease-based VM instancing platform was evaluated and set aside for
  this demo: a low-concurrency private-lab lease pool cannot serve a public,
  scalable ephemeral demo (VM-granularity, slow cold-start, a small concurrent
  cap, and private ingress), so the self-contained VPS + container-per-visitor
  design in [01](01-architecture.md) stays. Revisit only if a separate,
  low-concurrency "lease a full netcanon VM" demo ever becomes the explicit goal.
