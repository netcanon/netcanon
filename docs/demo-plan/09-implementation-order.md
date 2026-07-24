# 09 — Implementation Order

Build sequence for the implementing agent. Each phase ends in an acceptance
gate; do not proceed past a failing gate. Estimated total: one focused
build session for phases 1–5, plus deploy.

## Phase 0 — Reconnaissance (read-only)

Pull `ghcr.io/netcanon/netcanon:latest` and record the facts the plan
parameterizes. These have been verified against the netcanon source; the
implementing agent confirms them against the pinned digest and writes them into
the warden constants block. **Where a value below corrects an earlier draft
assumption, the corrected value is authoritative** (Standing rule 2).

- [x] **Listen port = `8000`** (not 8080) — `config.py` `port: int = 8000`,
      `Dockerfile` `EXPOSE 8000`. `NETCANON_PORT=8000` in the instance spec.
- [x] **Data dir = `/app/data`** — confirmed. But the image also declares
      `VOLUME ["/app/configs", "/app/data"]` (Dockerfile:113), so **`/app/configs`
      needs a tmpfs too** (`rw,noexec,nosuid,size=8m`); a missed one becomes a
      persistent anonymous host-disk volume that falsifies "zero volumes"
      ([04](04-container-hardening.md#container-spec-per-instance)).
- [x] **Route table → allowlist.** There are **no static assets** (all CSS/JS is
      inline) and **no `/api/v1/translate` route**. Allow only the migrate/
      sanitize UI + migration-plan/detect/sanitize APIs; block backups, devices,
      schedules, configs, definitions, `/docs`, and UI pages. Exact list in
      [04](04-container-hardening.md#feature-surface-reduction) /
      [03](03-warden-spec.md#proxying). Note `/` is the backup **dashboard**, not
      migrate.
- [x] **Log level = `warning`.** Request bodies are never logged at any level;
      only parsed fragments at `debug`. `NETCANON_LOG_LEVEL=warning` provably
      excludes them (defense in depth behind driver `none`).
- [x] **No WebSockets.** The UI polls via `fetch`; the WS-fallback contingency is
      deleted ([03](03-warden-spec.md#proxying) / [05](05-frontend.md)).
- [x] **No root-path/base-URL support; the UI uses absolute URLs**
      (`fetch('/api/v1/migration/plan')`, `href="/migrate"`). The warden
      therefore **routes by session cookie, not path prefix** — a warden-set
      HttpOnly + SameSite=Strict + Secure routing cookie is **required**
      ([03](03-warden-spec.md#proxying) / [05](05-frontend.md)).
- [x] **The app stamps `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'`**
      on every response (`main.py` security-headers middleware). The warden
      **must strip XFO and rewrite `frame-ancestors 'none'` → `'self'`** on every
      proxied response or the iframe renders blank
      ([03](03-warden-spec.md#proxying)).
- [x] **Non-root uid = 1000, native.** The image runs `USER app` (uid 1000);
      **no `user` override** — a mismatched uid breaks tmpfs ownership.
      `ALLOW_INSECURE_BIND` is unnecessary: setting `NETCANON_API_KEY` alone
      satisfies the non-loopback bind gate.
- [x] Record the image digest to pin (part of the I6 hash-lock chain).

**Gate 0:** all facts recorded and written into the warden constants block; any
that contradict a module have been reconciled into that module (Standing rule 2).

## Phase 1 — Warden

Implement per [03](03-warden-spec.md) with [04](04-container-hardening.md)'s
constants. Local compose: warden + `demo-int` + `warden-sock` (socket-proxy) +
caddy-facing net. Interpose the docker-socket proxy (verb allowlist: **create,
start, list, inspect, remove** — deny everything else) plus a **small
(~50–80-line) create-body authz shim** that **whole-body default-deny**-validates
every `POST /containers/create` body against the canonical `INSTANCE_SPEC` —
rejecting any field not in the spec (an added `Privileged`/`CapAdd`/bind mount) as
well as any changed field (the verb filter cannot inspect a create body) — since
the read-only non-root warden container does **not** by itself constrain the
socket API, which is root-equivalent on the host.

**Gate 1:** CI test table from [08](08-testing-verification.md#ci-tests) green
locally, including: egress + segmentation (instance→instance, instance→warden,
**and instance→socket-proxy** all DENY), per-IP + global cap, **volume-reap clean**
(`docker volume ls` empty after destroy), **TTL-independence** (warden restart →
labeled orphan swept; systemd backstop present), **socket-proxy** rejecting any
verb outside create/start/list/inspect/remove, and the **create-body authz shim**
(whole-body default-deny) rejecting a create body with an extra bind mount, a
changed image digest, a dropped `read_only`, **or an added `Privileged` /
`CapAdd` / `Devices` / `NetworkMode: host`** — the two rows now defined in
[08](08-testing-verification.md#ci-tests).

## Phase 2 — Proxy & frontend

Caddyfile per [02](02-deployment.md#caddy-configuration-requirements); frontend
per [05](05-frontend.md). Caddy has no native rate-limit, so either commit an
xcaddy build with a pinned self-built digest (to keep I6/`make verify` honest)
or fold rate-limiting into the warden (which already holds per-IP session
state). `Referrer-Policy: same-origin` on all demo paths (path tokens must not
leak via `Referer`).

**Gate 2:** Full happy path locally: land → start → the instance **renders
inside the iframe** (verifying the warden stripped `X-Frame-Options` and
rewrote CSP `frame-ancestors` → `'self'`; a plain iframe would be blank) →
sample-config translate with Tier-3 banner visible → countdown → tab close
(`pagehide` beacon) frees the slot ≤ 90 s, no-beacon reclaim ≤ 2 min for a closed
foreground tab (≤ ~4 min for a throttled background tab); hard-TTL (900 s) and
idle-reclaim (600 s) destroys each verified once end-to-end.

## Phase 3 — Host

Cloud-init per [02](02-deployment.md): Hetzner **CX32** (4 vCPU / 8 GB, EU
Falkenstein — the CX line is EU-only, so "CX22 + Ashburn" is impossible; the US
alternative is CPX32, re-priced with its lower included traffic). Swap off,
journald volatile, firewall, DNS, TLS. Also disable **core dumps** host-wide
(swap-off is not the only RAM→disk path): `kernel.core_pattern` → discard,
`systemd-coredump` `Storage=none` + `ProcessSizeMax=0`, apport removed/neutered,
`docker.service LimitCORE=0`.

**Gate 3:** `swapon --show` empty; core dumps disabled (crash a throwaway
process → nothing under `/var/crash` or `/var/lib/systemd/coredump`); 443 only;
HTTPS green; `make deploy` from a clean clone converges.

## Phase 4 — Proofs & whitepaper

Run live proofs 1–13 ([08](08-testing-verification.md#live-proofs)) on prod;
commit `VERIFY_RESULTS_<date>.md`. Fill the whitepaper's reproducibility block
([06](06-privacy-whitepaper.md#reproducibility-block-fill-at-deploy)); publish
at `/whitepaper`.

**Gate 4:** every whitepaper claim's proof has real output committed (**live
proofs 1–13**); `make verify` output matches the published block.

## Phase 5 — Launch wiring

- [ ] Demo URL into the launch assets (`[DEMO LINK]` placeholders in the
      launch playbook: HI pitch, Show HN, README badges).
- [ ] Front-page `docker run` one-liner + sanitize-page pointer (ties into
      BUG_REPORTING flow).
- [ ] Load sanity: script `MAX_ACTIVE` (32 on CX32) concurrent sessions with
      translations; confirm no OOM-kill of warden/caddy (size the cap off real
      held-session RSS ~90–140 MB + shim, not the 256 MB cap), busy-state renders
      for #33. Idle TTL + reliable teardown is the primary capacity lever
      (Little's Law `L = λ·W`; idle dwell 600 s, hard ceiling 900 s); box upsize
      is last. If the launch lands, rescale
      CX32 → CX42 (8/16, `MAX_ACTIVE` 60–80, pool 6) same-day (Hetzner hourly
      billing; rescale CPU/RAM only, keep the 40 GB disk so it stays reversible).

**Gate 5 (launch-ready):** capacity behavior observed under synthetic load;
all links resolve; whitepaper live; VERIFY_RESULTS committed.

## Standing rules for the agent

1. Invariants in [00](00-overview.md#invariants) override any convenience.
2. Any Phase-0 fact that contradicts a module → update the module, don't
   silently diverge; the whitepaper must describe reality.
3. Never introduce a persistence mechanism "temporarily for debugging" on the
   prod host. Debug in dev compose.
4. Keep the warden small; if it exceeds ~500 lines, you are building the wrong
   thing — simplify.
