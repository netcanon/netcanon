# 06 — Privacy & Ephemerality Whitepaper (publishable draft)

This module is both the spec and ~90% of the final text. Publish at
`/whitepaper` on the demo site and as `docs/DEMO_WHITEPAPER.md` in the repo.
Fill `<>` placeholders at deploy time. The defining feature: **every claim has
a Control (a config line you can read) and a Proof (a procedure you can run)** —
procedures live in [08](08-testing-verification.md) and are excerpted here.

---

# The Netcanon Demo Never Keeps Your Config — Here's the Proof

Network configs are sensitive. A running-config can contain your addressing
plan, SNMP strings, usernames, and topology. So the netcanon demo runs your
session in a throwaway instance that **self-destructs within 15 minutes**, built
so that retaining your data is not just against policy — it is **architecturally
unavailable**. This page maps every claim to the exact control that enforces it
and a procedure anyone can use to verify it.

The entire deployment is open source: <REPO_DEPLOY_URL>. The running system is
reproducible from that repo, and its image digests, lockfile hash, and
compose-file hash are published below.

## Threat model

We defend the visitor's pasted data against: (a) operator retention (us, by
design), (b) cross-visitor leakage, (c) post-session forensic recovery from the
host, (d) log-based leakage at any layer, (e) a compromised or buggy demo
application instance. Out of scope: a fully compromised host kernel/hypervisor
(no hosted demo can defend that — if your config is that sensitive, run
netcanon locally: `docker run …`; we make that path one click away).

### Trusted Computing Base

Every claim below rests on a small set of components we ask you to trust: the
**warden** (session manager + reverse proxy), the **socket-proxy + create-body
authz shim** (the capability filter that fronts the Docker socket), **Caddy**
(TLS termination), **dockerd** (the container runtime), and the **host
kernel/OS**. These are the TCB. A compromise of any of them — most sharply the
warden, which reaches the Docker socket — is **host root**, and host root voids
**all ten claims** below.
We do not pretend otherwise; we make the TCB as small and as auditable as we can:

- **The warden is ≤ 500 lines** you can read end to end (source: <REPO_DEPLOY_URL>).
- It runs as a **non-root, read-only container** and reaches Docker only through
  a **socket-proxy / authz filter** that permits just **create, start, list
  (`GET /containers/json`, including label filters), inspect, and remove** —
  denying everything else (`exec`, `commit`, `build`, `images`, `networks`,
  `volumes`, …), not the arbitrary, root-equivalent Docker API. Because the
  socket proxy cannot inspect a create *body*, a **small (~50–80-line) create-body
  authz shim** in front of it enforces a **whole-body default-deny allowlist** on
  every `POST /containers/create`: the raw wire body may contain **only** the
  fields of the canonical create-body template (`INSTANCE_SPEC` serialized through
  the pinned Docker-SDK version), each equal to that template (image digest,
  read-only rootfs, the tmpfs set, no bind mount, network mode, memory/pids/cpu
  caps, `CapDrop: [ALL]` with `CapAdd: []`, security-opts) — **any other field is
  rejected**, so an
  added `Privileged`, `CapAdd`, bind mount, or `NetworkMode: host` cannot slip
  through. Only the `demo.*` labels and the two per-instance random env keys may
  differ. This shim is **counted in the Trusted Computing Base** alongside the
  ≤ 500-line warden.
- It **never `exec`s into an instance** and never reads instance memory or
  tmpfs; its only contact with your instance is proxying HTTP to it.
- Caddy and dockerd are stock, pinned by digest (below); the host is a single
  small VPS whose configuration lives in the same public repo.

If you cannot extend that trust, the honest answer is the one on the front page:
run netcanon locally with `docker run …` and trust nothing of ours.

## Claims, controls, proofs

| # | Claim | Control | Proof (abridged; full: repo `VERIFY.md`) | Tier |
|---|---|---|---|---|
| 1 | Your session runs in its own isolated instance | Warden creates one container per session; routing is by the **HttpOnly `nc_route` cookie** — a bearer credential valid for the life of the session, not a single-use token; instances unreachable except via the warden | Two browser profiles: each header shows a **distinct instance-id chip** (`instance_id`, a display id — not the routing token); end session A → A's now-dead cookie 404s every request while B is unaffected | V·O |
| 2 | The instance cannot write to disk | `read_only: true` rootfs; **both** declared VOLUME paths (`/app/data` *and* `/app/configs`) backed by tmpfs (RAM), so no anonymous host-disk volume is ever created; **zero named or anonymous volumes** | `docker inspect` shows ReadonlyRootfs=true and Mounts = tmpfs only; `docker diff` clean outside tmpfs; `docker volume ls` empty after teardown | O |
| 3 | Nothing survives the session | Teardown = `container.remove(v=True, force=True)` (container **and** any anonymous volume); tmpfs freed by kernel; the hard TTL is enforced across **two independent enforcement domains (the warden and host systemd), three mechanisms** — (1) the warden's in-RAM reaper at `deadline = assignment_time + HARD_TTL` (900 s from assignment), (2) the warden's startup label-sweep, and (3) an independent host **systemd timer** (swept every 60 s) that force-removes any `demo.*`-labeled container older than `HARD_TTL + POOL_MAX_AGE + 120 s slack = 1320 s` even if the warden is dead; sooner in practice via the 10-min idle reclaim (sooner under heavy load), `pagehide` `sendBeacon`, and heartbeat timeout (**≤ 2 min for a closed foreground tab, ≤ ~4 min for a throttled background tab**) | Destroy → `docker ps -a` and `docker volume ls` empty of it; kill the warden mid-session → the systemd timer still removes it within ~23 min of creation; canary paste + host-wide grep finds nothing post-teardown | O |
| 4 | Your paste appears in no log, anywhere | Instance log driver `none`; warden logs metadata-only (schema enumerated) and **never interpolates a request body — including in exception handlers / error paths**; Caddy access logs disabled on the demo paths (`/i/*`, `/session/*`, and all allowlisted cookie-routed app paths → no access logs; everything else → status-only); journald volatile (RAM) | Canary-string grep across journald + filesystems; warden log-schema test in CI asserts no body field on any path, error paths included | O |
| 5 | RAM contents can't leak to disk (swap **or** core dump) | Swap disabled host-wide; `memswap_limit == mem_limit`; **core dumps disabled host-wide** — `kernel.core_pattern` set to discard, `systemd-coredump` `Storage=none` + `ProcessSizeMax=0`, apport neutered, `docker.service LimitCORE=0` | `swapon --show` empty; inspect shows limits equal; `cat /proc/sys/kernel/core_pattern` shows the discard sink; force a crash → no core file written | O |
| 6 | The instance can't phone anywhere | Instances on an `internal: true` network (no egress); ICC is all-or-nothing, so isolation is enforced by **explicit nftables rules**: warden→instance ALLOW, instance→instance DENY, instance→warden DENY | From inside an instance: every outbound connect fails; instance→instance fails; instance→warden fails | O |
| 7 | Even netcanon's encryption key is never written to disk | The warden injects a **per-instance random `NETCANON_FERNET_KEY`** (Tier-1 of netcanon's key resolution), so the file fallback at `data/.fernet_key` is never reached — **no Fernet key file is ever created**; the key lives only in the instance's RAM | **Proof 13**: from the host via the **raw host Docker socket** (not the warden's path — its allowlist forbids `exec`), `docker exec`/`docker inspect` shows the env key set and no `.fernet_key` on disk (`/app/data` is tmpfs regardless); gone with the instance | O |
| 8 | The demo can't silently degrade isolation under load | Hard instance cap (`MAX_ACTIVE` = 32); per-IP concurrent-session cap (`PER_IP_MAX_CONCURRENT` = 2); above 80% occupancy the **idle** TTL tightens (600 s → 300 s, applied retroactively within ~10–20 s of the crossing, loosening back below 70% — hysteresis), reclaiming untouched tabs faster while the 15-min hard ceiling is left intact; the longest-idle (never-translated) session is reclaimed before anyone is refused — but **never one younger than 120 s** (a mid-paste session is protected; if every session is under that floor the demo returns 503 rather than reclaiming one); at the cap the demo returns **503** rather than sharing an instance | Saturate the cap; observe 503 + busy UI, never a shared instance (**the third concurrent session from your IP is refused — that you can see**) | O |
| 9 | The published deployment is exactly reproducible (and the live host is operator-attested to match) | Images pinned by digest; `requirements.lock` hash-locked; compose SHA-256 published | Digests + hashes below; `make verify` reproduces them **from the repo** — it attests the published artifact, **not this live host** (no hosted demo can remotely prove its own runtime; that is what the local `docker run` path is for) | O |
| 10 | No tracking on the demo page | The **page** sets no cookies, no `localStorage`, no analytics, no third-party requests; the *only* cookie in play is the warden's **HttpOnly, SameSite=Strict, Secure** session-routing cookie — a bare instance binding, not an identifier (disclosed under "What we do see") | View source (self-contained, all CSS/JS inline); devtools **Network** shows no third-party requests and **Application → Cookies** shows only the routing cookie | V |

**Tier — how far you have to trust us.** **V** = *visitor-verifiable now*: you
can confirm it from your own browser, on the live site, trusting nothing of
ours. **O** = *operator-attested + locally reproducible*: confirming it needs
host access, so we commit the exact command output in `VERIFY.md` — and, because
no hosted demo can remotely prove its own runtime, you can reproduce every **O**
row yourself by running the identical stack locally with `docker run …`.
`make verify` attests the **published repo/artifact, not this live host**. A row
marked **V·O** carries both components: claim 1 is the case — you can watch the
instance-id chip differ and the dead-cookie 404 from your own browser (**V**),
while "never a *shared* instance" is attested at the container boundary (**O**).

## What we do see

Honesty section — required. We (the operator) can observe: standard host
operational metadata (session count, lifecycle timestamps, destroy reasons,
status codes), Hetzner's infrastructure-level traffic metadata, and whatever a
TLS-terminating proxy inherently sees **in memory while streaming** your
request. Two more things, stated outright:

- **A warden-set routing cookie.** netcanon's UI uses absolute URLs
  (`fetch('/api/v1/migration/plan')`, `href="/migrate"`) and has no root-path
  support, so the warden routes you to your one instance **by session, not by
  path**. To do that it sets a single cookie —
  `Set-Cookie: nc_route=<token>; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=900`
  — carrying only the opaque session token. That token is a **bearer credential
  valid for the life of the session** (not single-use), which is exactly why the
  cookie is HttpOnly, Secure, and SameSite=Strict — JS cannot read or forge it.
  It is not an analytics identifier and it dies with your session. Because the
  cookie is browser-global, a browser holds **exactly one live session** (a fresh
  mint replaces the previous one); the **≤ 2-concurrent-sessions-per-IP** cap is a
  separate guardrail bounding distinct devices behind one IP. The demo page itself
  still sets nothing (claim 10).
- **Per-IP session state, in RAM only.** To enforce the per-IP concurrent-session
  cap (**≤ 2 concurrent sessions per IP**) and a sliding-window mint rate limit
  (**≤ 30 mints / 600 s per IP**), the warden keeps a small per-IP record **in
  memory only** — never logged, **held in memory for up to 10 minutes after your
  last request, never written to disk, gone on warden restart**. A rate limiter
  must outlive any single session, so the record is evicted 10 min after your last
  request rather than on session end.

We keep none of the in-memory transit category — the controls above are what
make that checkable rather than a promise. If you cannot accept in-memory
transit through our proxy, run netcanon locally; that path is on the demo's
front page.

## Reproducibility block (fill at deploy)

```
netcanon image    : ghcr.io/netcanon/netcanon@sha256:<...>   (base python:3.14-slim-bookworm)
requirements.lock : sha256:<...>   (hash-locked; glibc/manylinux wheels — not Alpine/musl)
warden image      : <registry>@sha256:<...>
socket-proxy image: <registry>@sha256:<...>   (TCB component — the capability filter fronting docker.sock)
caddy image       : <registry>@sha256:<...>   (self-built via xcaddy if rate-limiting lives in Caddy)
compose sha256    : <...>
deployed          : <date>   hard TTL: 900s (15 min)   idle TTL: 600s (10 min)   instance cap (MAX_ACTIVE): 32
```

## Residual risks, stated plainly

### Trusted Computing Base — the honest worst case

The sharpest residual risk is not exotic: it is us. The warden, the socket-proxy
+ authz shim, Caddy, dockerd, and the host are **trusted** (see the threat model's
TCB subsection). A
compromise of the warden — which holds the Docker socket — is **host root**, and
host root **voids all ten claims** above: it could snapshot RAM, disable the
reaper, or read into any instance. We *bound* (not eliminate) this by keeping the
warden tiny (≤ 500 auditable lines), non-root, read-only, reachable to Docker
only through a capability-filtered socket proxy **plus a small create-body authz
shim that whole-body default-deny-validates every `POST /containers/create`
against the canonical `INSTANCE_SPEC` (both counted in the TCB), so create is not
the arbitrary, root-equivalent Docker API** — and never `exec`ing into
instances — all of it in the public repo. If that residual is unacceptable for
your data, run netcanon locally and trust none of it.

- A kernel- or hypervisor-level compromise of the host likewise defeats all
  guarantees (out of scope in the threat model).
- `sendBeacon` on `pagehide` is best-effort; when it doesn't fire, the
  heartbeat-timeout path reclaims your instance in **≤ 2 min for a closed
  foreground tab, ≤ ~4 min for a throttled background tab**, and a tab left open
  but untouched is reclaimed at the **10-minute idle TTL** (sooner under heavy
  load). Both of those only ever *shorten* the session. The guarantee that
  requires **nothing** from your browser — no beacon, no heartbeat, no activity —
  is the hard TTL, enforced across **two independent enforcement domains (the
  warden and host systemd), three mechanisms**, with two honest bounds: while the
  warden is live it destroys your instance **≤ 15 minutes after it was assigned to
  you**; and **even if the warden crashes**, an independent host systemd timer
  (swept every 60 s) force-removes any `demo.*`-labeled container **≤ ~23 minutes
  after it was created** (older than `HARD_TTL + POOL_MAX_AGE + 120 s slack = 1320 s`). A crash
  can therefore widen the ceiling from 15 to at most ~23 minutes — it can never
  *lift* it; nothing keeps your instance alive indefinitely.
- We can change this deployment. That's why the digests and hash are published:
  trust the artifact you can verify today, not us.

---

## Deliverables

- **This module is the whitepaper _template_.** It lives in-repo as
  `docs/DEMO_WHITEPAPER.md` with its `<>` placeholders **unfilled**. The
  **filled** copy is rendered at deploy time (`tools/render_whitepaper.py`),
  served at `/whitepaper`, and shipped in the signed Release bundle — it is never
  committed with real digests.
- **Freshness note** (carried in `/whitepaper` and `VERIFY.md`): the live site
  may lawfully run an **older published bundle** than the newest Release; the
  live whitepaper reproducibility block always describes the **currently running**
  system, and a synthetic probe alerts on live-vs-latest drift (detection, not
  closure).
- `VERIFY.md` in the deploy repo = full procedures from [08](08-testing-verification.md)
- Reproducibility block wired to `make verify` output (filled at deploy time, not
  in the in-repo template)
