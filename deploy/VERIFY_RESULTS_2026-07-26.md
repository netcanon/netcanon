# VERIFY_RESULTS — 2026-07-26

Proofs 1–13 from [`VERIFY.md`](VERIFY.md), executed on the production host against
the deployed bundle. Required by the pre-launch gate, and re-required on every
image-digest bump.

| | |
|---|---|
| Host | Hetzner CPX32, Ubuntu 24.04.4, x86_64, 4 vCPU / 7745 MiB / 152.6 G |
| Bundle | `demo-v0.1.1` (superseding `demo-v0.1.0`, see note at the end) |
| Commit | `2fecfec` |
| Product pinned | `v0.6.1` |

Anything that did **not** pass cleanly, or that could not be run as written, is
recorded as such rather than omitted.

## Gate 4 — bundle verification

```
cd ./bundle && cosign verify-blob SHA256SUMS \
    --bundle SHA256SUMS.cosign.bundle \
    --certificate-identity "https://github.com/netcanon/netcanon/.github/workflows/demo-publish.yml@refs/tags/demo-v0.1.1" \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
Verified OK

cd ./bundle && sha256sum -c SHA256SUMS
demo.env: OK
whitepaper.html: OK
whitepaper-template.html: OK
whitepaper-values.json: OK
index.html: OK
docker-compose.yml: OK
Gate 4 OK — signature valid and every bundle file matches its published hash.
```

`make deploy` reaches `docker pull` only through `promote → verify-bundle`, so the
digests below are the ones that were verified, not merely the ones on disk.

## `make verify` — the deployed pins

```
compose sha256:     8ff351e167a4367532bbc75c4417230948ae5b78b74633e201e8ce0b5f1ef537
PINNED_PRODUCT_TAG: v0.6.1
NETCANON_INSTANCE_IMAGE=ghcr.io/netcanon/netcanon@sha256:0b2eab3b9cf6a3b59fdd0cd784acf73b275e4d6c80b7c54c97b1f12824bf98b6
WARDEN_IMAGE=ghcr.io/netcanon/netcanon-demo-warden@sha256:13feaa1edff24742e122234069759aa2b6afd8f780f159a4e43e31b33f212127
WARDEN_SHIM_IMAGE=ghcr.io/netcanon/netcanon-demo-warden-shim@sha256:016cf0fabd55e17a88263e2e526c8343d7433166209355997e7ec462a9a8abfb
SOCKET_PROXY_IMAGE=ghcr.io/tecnativa/docker-socket-proxy@sha256:1f3a6f303320723d199d2316a3e82b2e2685d86c275d5e3deeaf182573b47476
CADDY_IMAGE=docker.io/library/caddy@sha256:844f60b64e4724a5aa8245e019dace0d3f199f7433ce6c57676cb30a920dbad9
```

All six values appear verbatim in the live `/whitepaper` reproducibility block
(**6/6 MATCH**, 0 placeholders remaining). Under `demo-v0.1.0` this was 5/6 — the
authz-shim digest was published nowhere, which is why `demo-v0.1.1` exists.

I6 confirmed: `deploy/docker-compose.yml` and the published bundle copy are
byte-identical (`8ff351e1…`), so the in-repo hash really is the published hash.

## Proof 1 — canary forensics (claims 2, 3, 4) [O]

Two canaries, one per path.

**Error path** — `CANARY-68f22b92f8eb7fb2`, a parse that fails
(`cisco_iosxe` is the NETCONF/XML codec; the input was CLI, so the job returned
`status: failed` with `malformed XML`). VERIFY.md explicitly requires error paths
to be as clean as the happy path.

**Happy path** — `CANARY-53b4c11dd64b4e3d`, a real translation:

```
translate -> HTTP 200
job status      : completed
source_hostname : CANARY-53b4c11dd64b4e3d      <- the canary genuinely transited the instance
error           : none
```

Sweeps, both while the session was live and after it ended:

```
host filesystem : 0 demo-attributable hits   (both canaries, both phases)
journald        : 0
docker logs (all containers): 0
container after end: removed, not stopped
```

**Clean-room run** — `CANARY-f19e8e412d846b16`. The two runs above were
contaminated: the harness saved the curl response to `/tmp/plan2.json` and the
canary to `/tmp/canary.txt`, so the sweeps found the harness's own files (1
filesystem hit) and a later raw block-device sweep found 2 hits — the live file
plus the deleted one's still-unallocated blocks. Both were mine, neither was the
demo's, but the only way to *prove* that is a canary the harness never writes to
host disk at all:

```
canary held only in shell variables; no file created by the script
job status        : completed
canary transited? : YES   (round-tripped through the instance)
container removed?: yes
filesystem hits   : 0
journald hits     : 0
```

Recorded at length because anyone re-running proof 1 will hit the same false
positive, and a naive reading of it looks exactly like a claim-4 violation.

**Raw block-device sweep — COMPLETE, 0 hits** over the full 152.6 G `/dev/sda`
for the clean-room canary. This is the strongest form of the proof: it catches
deleted-but-unallocated blocks, not just live files. It also settles the earlier
2 hits definitively as the harness's own files.

Note the naive `grep -a /dev/sda` in VERIFY.md is **OOM-killed** on this host —
grep buffers unbounded on binary data with no newlines. What works:

```bash
LC_ALL=C tr -c '[:print:]' '\n' < /dev/sda | LC_ALL=C grep -c "$CANARY"
```

VERIFY.md has been corrected with this command and a warning about the harness
false positive.

## Proof 2 — read-only rootfs, tmpfs-only writes (claim 2) [O]

```
ReadonlyRootfs : true
mounts         : none (tmpfs declared via HostConfig, so no bind mounts, no volumes)
tmpfs paths    : /app/configs  /app/data  /tmp
docker diff    : 0 changed paths outside tmpfs
```

## Proof 3 — swap (claim 5) [O]

```
host swapon --show : 0 entries
Memory vs MemorySwap : 268435456 vs 268435456   (equal, non-zero -> zero swap allowance)
```

## Proof 4 — egress + segmentation (claim 6) [O]

```
demo-int Internal : true

from inside a live instance:
  internet          (1.1.1.1:443)   -> BLOCKED OSError
  sibling instance  (:8000)         -> BLOCKED TimeoutError
  warden API        (172.31.0.2:8080) -> BLOCKED TimeoutError
  socket-proxy      (:2375)         -> BLOCKED gaierror
```

The three failure *modes* differ meaningfully and corroborate three distinct
mechanisms: `OSError` = no route (`internal: true`), `TimeoutError` = silent
nftables `drop` (I4), `gaierror` = the name does not resolve, because the
socket-proxy sits only on `warden-sock` and no instance ever joins it.

Directionality confirmed separately — warden→instance **REACHED**, so the ALLOW
rule is not over-broad.

## Proof 5 — isolation (claim 1) [V then O]

```
one container per session, distinct ids : 5 running / 5 distinct
dead session cookie -> HTTP 404
```

[V] portion confirmed in a browser earlier the same day: the `nc_route` cookie is
`HttpOnly` and invisible to page JavaScript (`document.cookie` empty).

## Proof 6 — capacity (claim 8) [O, per-IP part V]

Split across two paths, because the two halves are not measurable from the same
place.

**Saturation** — requires presenting distinct source addresses, which only works
against the directly-published warden (`make smoke-up`), as
`load_sanity.visitor_ip` documents. Measured on this host:

```
granted=32 refused=0   active=32 <= MAX_ACTIVE=32
worked-instance RSS median 72.0 MiB (28% of the 256 MiB guardrail)
PROJECTED at MAX_ACTIVE=32: 2420 MiB (2.36 GiB) vs 7745 MiB total
no OOM-kill of warden / shim / socket-proxy / caddy
failed closed at saturation (503 capacity)
slot freed in 0s (SLO 90s)
swap still empty
```

One blemish: at full saturation `31/32` sessions rendered output — a ~3%
shortfall at the cap, not reproduced below it.

**Public path** — through Caddy, on the deployed signed stack:

```
PROJECTED at MAX_ACTIVE=32: 2468 MiB (2.41 GiB)
slot freed in 0s (SLO 90s)
no OOM-kill
note: ran 2 < MAX_ACTIVE=32; the saturation invariant was NOT exercised here
```

The two projections agree within 2%.

**Per-IP cap cannot be bypassed by header spoofing** — four mints with four
distinct client-supplied `X-Forwarded-For` values:

```
203.0.113.1 -> token issued
203.0.113.2 -> token issued
203.0.113.3 -> {"reason":"rate_limited"}
203.0.113.4 -> {"reason":"rate_limited"}
```

Caddy overwrites `X-Forwarded-For` for untrusted clients, so all four counted
against the real source address. This is what makes the warden's "trusted because
only Caddy can reach it" comment true in practice.

## Proof 7 — reproducibility (claim 9) [V]

`make verify` output above matches the live `/whitepaper` block 6/6. 0 unfilled
placeholders, 0 occurrences of the superseded `1200 s` / `~20 min` figures.

## Proof 8 — page cleanliness (claim 10) [V]

Measured in a real browser against the live site:

```
localStorage_keys      : 0
sessionStorage_keys    : 0
cookies visible to JS  : none (HttpOnly)
off-origin subresources: none
```

## Proof 9 — framing (claim 2) [O]

```
x-frame-options : stripped (the instance itself sends DENY)
CSP             : frame-ancestors 'self'
```

`'self'` is correct rather than permissive: the warden serves the instance under
the *same origin*, so same-origin framing works while cross-origin framing is
refused.

## Proof 10 — volume reap (claim 2) [O]

```
volumes before session end : 2
volumes after session end  : 2
```

Both are the stack's own `caddy-data` / `caddy-config`. No per-instance volume is
created or left behind — instances declare `v=True` on removal and their writable
paths are tmpfs.

## Proof 11 — TTL independence (claim 3) [O]

The real claim is that cleanup survives warden death, so the warden was stopped
first:

```
timer armed        : active   ceiling=1320
instances before   : 4
warden state       : exited
instances orphaned : 4
-- backstop run with the ceiling forced to 0 (same logic, no 22-minute wait) --
instances after    : 0
-- restore --
warden: running restarts=0    pool refilled: 4    site: HTTP 200
```

⚠️ Method note: the script's `CEILING=1320` is hardcoded, so a copy with
`CEILING=0` was used to exercise the removal path without waiting out a real
session. The age comparison itself was therefore not exercised against a genuinely
aged container — only the label-matching and removal logic, with the warden dead.

## Proof 12 — core dumps (claim 5) [O]

```
kernel.core_pattern              : |/bin/false
systemd-coredump Storage         : Storage=none
docker.service LimitCORE         : LimitCORE=0
core files after forcing SIGSEGV : 0
```

## Proof 13 — Fernet key never on disk (claim 7) [O]

```
NETCANON_FERNET_KEY in container env : 1
/app/data/.fernet_key on disk        : absent
```

## Summary

| Proof | Result |
|---|---|
| Gate 4 bundle signature + checksums | PASS |
| 1 canary forensics (fs + journald + logs + raw block device) | PASS (clean-room, 0/0/0/0) |
| 2 read-only rootfs / tmpfs | PASS |
| 3 swap | PASS |
| 4 egress + segmentation | PASS |
| 5 isolation | PASS |
| 6 capacity | PASS — saturation via smoke path; 31/32 rendered at the cap |
| 7 reproducibility | PASS 6/6 |
| 8 page cleanliness | PASS |
| 9 framing | PASS |
| 10 volume reap | PASS |
| 11 TTL independence | PASS — via forced-ceiling run, see method note |
| 12 core dumps | PASS |
| 13 Fernet key | PASS |

One item is **not** closed and should not be read as passing: the age
comparison in proof 11 — the removal logic was exercised with a forced ceiling,
not against a genuinely aged container. Everything else passed on the production
host against the deployed `demo-v0.1.1` bundle.

## Why `demo-v0.1.1` and not `demo-v0.1.0`

`demo-v0.1.0` deployed cleanly and then failed proof 7 against itself: the
authz-shim — a Trusted Computing Base component that `VERIFY.md` tells readers to
`cosign verify` — had no digest anywhere in the published reproducibility block.
The workflow computed it, wrote it into `demo.env`, and never emitted it into
`whitepaper-values.json`. Five of six digests were verifiable.

Because the bundle is signed and immutable, its values file can never carry the
missing keys; the fix necessarily shipped as a new tag. That is what a patch tag
is for, and the reason the first tag was `demo-v0.1.0` rather than `demo-v1`.
