# VERIFY.md — verifying the netcanon public demo's claims

This file is the runbook for verifying every claim made in the demo whitepaper
(live at `/whitepaper` on the demo host; source at `docs/DEMO_WHITEPAPER.md`).
Each proof below is a copy-paste command sequence, not a description. If a
command's output does not match the "expected" line, the claim is broken — file
an issue.

Proofs are tagged with one of two tiers:

- **[V] Visitor-verifiable** — runnable from your own browser or machine,
  trusting nothing served by us. These stand on their own.
- **[O] Operator-attested** — require SSH access to the demo host. Visitors
  cannot run them against production, but every [O] proof is **locally
  reproducible**: the demo stack is built from this repo and pinned by digest,
  so you can `docker run` the identical images on your own machine and execute
  every [O] row yourself.

One honest caveat up front: **no hosted demo can remotely prove its own
runtime**. A server can always lie about what it is running. The [V] proofs
narrow what a lying server could get away with; the [O] proofs plus digest
pinning let you reconstruct the exact stack independently. The ultimate proof
is running netcanon locally — it is a single container.

---

## Reproducibility & signatures

### `make verify` — pin comparison

From `deploy/` in this repo:

```bash
cd deploy/
make verify
```

This prints the pinned image digests (from `demo.env`) and the SHA-256 of the
compose file. Compare them, byte for byte, against the reproducibility block in
the whitepaper. If they match, the repo you are reading is the recipe for the
stack the whitepaper describes. (This attests the *recipe*; proof 7 below
covers what it does and does not say about the live host.)

### Cosign — netcanon instance image (works today)

The published netcanon image on GHCR is signed keyless via Sigstore, using
GitHub Actions OIDC. Resolve the digest, then verify against the digest — never
against a mutable tag:

```bash
# Resolve the immutable digest for the pinned release
DIGEST=$(docker buildx imagetools inspect ghcr.io/netcanon/netcanon:vX.Y.Z \
  --format '{{json .Manifest}}' | jq -r .digest)

cosign verify ghcr.io/netcanon/netcanon@sha256:${DIGEST#sha256:} \
    --certificate-identity 'https://github.com/netcanon/netcanon/.github/workflows/docker-publish.yml@refs/tags/vX.Y.Z' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Notes:

- Replace `vX.Y.Z` with the exact release tag pinned in `deploy/demo.env`
  (`NETCANON_INSTANCE_IMAGE`).
- Verify the **digest**, not the tag. Tags are mutable; digests are not.
- `--certificate-identity` is the **full pinned signer identity** — the exact
  workflow file at the exact tag ref — not a regexp. It must match
  byte-for-byte. A passing verification means: this exact image was built by
  that exact GitHub Actions workflow, at that exact tag, in the public
  `netcanon/netcanon` repo, and signed via Sigstore's transparency log.

### Cosign — demo stack images (live from the first `demo-v<semver>` tag)

The warden and the create-body authz shim are both Trusted Computing Base, and
both are built, signed, SBOM-attested and provenance-attested by
[`.github/workflows/demo-publish.yml`](../.github/workflows/demo-publish.yml).
The signer identity is the workflow file at the exact demo tag:

```bash
# Digests come from the bundle's demo.env; verify each against its tag identity.
cosign verify ghcr.io/netcanon/netcanon-demo-warden@sha256:<digest> \
    --certificate-identity 'https://github.com/netcanon/netcanon/.github/workflows/demo-publish.yml@refs/tags/demo-v0.1.0' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com

cosign verify ghcr.io/netcanon/netcanon-demo-warden-shim@sha256:<digest> \
    --certificate-identity 'https://github.com/netcanon/netcanon/.github/workflows/demo-publish.yml@refs/tags/demo-v0.1.0' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Notes:

- Replace `demo-v0.1.0` with the demo tag the running bundle came from, and each
  `<digest>` with the value in that bundle's `demo.env`.
- This is a **second, separate** signer identity from the product image's
  (`docker-publish.yml@refs/tags/vX.Y.Z`). Two artifacts, two identities, two
  verify commands. Never widen either regexp to cover both.
- Demo tags are `demo-v<major>.<minor>.<patch>`. The workflow's ref guard refuses
  anything else before it builds, because a tag like `demo-v1-rc1` would produce
  a signature no identity above can match.
- **Status:** live. Demo releases have been cut and published, so the signatures
  above are real and verifiable today — Gate 4 (verifying a published bundle with
  the operator's own cosign commands before deploying it) has been run. Use the
  tag the running bundle came from; `deploy/demo.env` on the host records the
  digests actually deployed, and `make verify` prints them.

### Verify the deploy bundle itself

`SHA256SUMS` in each demo release is signed with `cosign sign-blob`, so the
bundle is not a mutable, unsigned link in the chain:

```bash
cosign verify-blob SHA256SUMS \
    --bundle SHA256SUMS.cosign.bundle \
    --certificate-identity 'https://github.com/netcanon/netcanon/.github/workflows/demo-publish.yml@refs/tags/demo-v0.1.0' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com

sha256sum -c SHA256SUMS      # then confirm every asset matches
```

---

## Live proofs

### 1. Canary forensics — pasted configs leave no trace (claims 2, 3, 4) [O]

Start a session, paste a config containing a unique canary
(`CANARY-$(openssl rand -hex 8)`), translate it, end the session. Then sweep
the entire host:

```bash
CANARY="CANARY-$(openssl rand -hex 8)"
echo "$CANARY"   # paste a config containing this string into a session, translate, end session

docker ps -a | grep <instance-id>
# expected: no output — the container is gone, not stopped

grep -r CANARY- / --binary-files=text --exclude-dir={proc,sys,dev}
# expected: zero hits anywhere on the filesystem

journalctl | grep CANARY-
# expected: zero hits in any journal

# NOTE: naive grep is OOM-killed on a large device — it buffers unbounded on
# binary data with no newlines. Bound the line length first:
LC_ALL=C tr -c '[:print:]' '
' < /dev/sda | LC_ALL=C grep -c CANARY-
# expected: zero hits — raw block-device sweep, catches deleted-but-unallocated blocks too
#
# Run the canary through WITHOUT saving any response to host disk. A harness that
# writes the canary to /tmp will find its own files and read as a claim violation.
```

Also run the same sweep **before** the TTL expires, while the session is still
alive: the canary must appear nowhere on disk even for a live session (it lives
only in tmpfs and process memory).

Error-path variant: repeat the full sweep after each of (a) an oversized
request body, (b) a malformed body, (c) a mid-stream client kill, (d) a forced
500 — each with its own distinct `CANARY-` value. Error paths must be as clean
as the happy path.

- expected: every sweep, on every path, returns zero hits.

### 2. Mount proof — read-only rootfs, tmpfs-only writes (claim 2) [O]

During a live session:

```bash
docker inspect <id> | jq '.[0].HostConfig.ReadonlyRootfs, .[0].Mounts'
# expected: true, and every mount is tmpfs — no bind mounts, no volumes

docker diff <id>
# expected: only paths under the tmpfs mounts — nothing on the container's root layer changed
```

### 3. Swap proof — session data cannot be paged to disk (claim 5) [O]

```bash
swapon --show
# expected: empty — the host has no swap at all

docker inspect <id> | jq '.[0].HostConfig.Memory, .[0].HostConfig.MemorySwap'
# expected: two equal non-zero numbers — Memory == MemorySwap means zero swap allowance even if swap existed
```

### 4. Egress + segmentation — instances can reach nothing (claim 6) [O]

```bash
docker network inspect demo-int | jq '.[0].Internal'
# expected: true — the instance network has no route out
```

From inside an instance's network namespace (via `nsenter -t <pid> -n` or a
probe container attached to `demo-int`), attempt four connections:

```bash
# 1. the internet
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/1.1.1.1/443'; echo "exit=$?"
# 2. a sibling instance's IP
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/<sibling-ip>/8000'; echo "exit=$?"
# 3. the warden API port
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/<warden-ip>/<api-port>'; echo "exit=$?"
# 4. the socket-proxy
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/<socket-proxy-ip>/2375'; echo "exit=$?"
# expected: all four fail (non-zero exit / timeout)
```

The nftables policy is directional: warden→instance **ALLOW**,
instance→instance **DENY**, instance→warden **DENY**. The socket-proxy is
unreachable *by construction* — it sits only on the `warden-sock` network,
which no instance is ever attached to.

### 5. Isolation — sessions are distinct and unforgeable (claim 1) [V then O]

[V] part, from your own browser: open two browser profiles (or one normal + one
private window) and start a session in each. Each page header shows a
**distinct instance-id chip** — that is the `instance_id`, not the routing
token. End session A (or wait out its TTL). Session A's `nc_route` cookie is
now dead: every further request from profile A returns **404**, while profile B
continues working untouched.

[O] part, confirming the mechanism:

```bash
docker ps --filter label=demo.instance
# expected: one container per active session, each with its own id
```

Routing is by the `HttpOnly` `nc_route` cookie — page JavaScript cannot read or
forge it, so one session cannot craft its way into another's instance.

- expected: distinct chips; dead session → 404s; live session unaffected.

### 6. Capacity — global cap, per-IP cap, slot reclaim SLO (claim 8) [O, per-IP part V]

```bash
# script mints MAX_ACTIVE (32) sessions, then attempts one more
./scripts/mint_sessions.sh 33
# expected: sessions 1-32 succeed; mint 33 first reclaims the longest-idle
#           session that has never translated, else returns 503; UI shows the busy state
```

[V] per-IP part, from your own machine: open 3 concurrent sessions from one IP.

- expected: the 3rd is refused (per-IP cap is 2) — you can watch the refusal
  yourself in the browser.

Capacity SLO: close a tab (the beacon path fires on unload) and watch the slot.

- expected: the closed tab's slot is freed within **≤ 90 s**.

### 7. Reproducibility — the repo is the recipe (claim 9) [V]

```bash
cd deploy/
make verify
# expected: printed image digests + compose sha256 match the whitepaper's reproducibility block exactly
```

Honest scope note: this attests **the repo**, not the live host. It proves the
published recipe matches the published claims; it cannot remotely prove the
host is running that recipe (see the caveat in the intro).

### 8. Page cleanliness — the page itself stores and leaks nothing (claim 10) [V]

In your browser's devtools on the demo page:

```text
Application tab -> Cookies / Local Storage / Session Storage
# expected: the page sets no cookies and no localStorage/sessionStorage

Network tab (reload the page)
# expected: no third-party requests — every request goes to the demo origin

View source
# expected: self-contained — no external script/style/font origins
```

The only cookie present is the warden's `HttpOnly` routing cookie (`nc_route`),
which is set by the server, unreadable by page JS, and disclosed in the
whitepaper's "What we do see" section.

### 9. Framing — the instance is embeddable only by us (claim 2) [O]

With a live session rendered in the demo page's iframe: the instance renders
(not a blank frame), and the proxied response carries the rewritten headers.
Check via curl through the warden, or in devtools → Network → the iframe
document's response headers:

```bash
# a cookie-routed instance page (the warden proxies /migrate to your instance)
curl -sD - -o /dev/null --cookie 'nc_route=<token>' https://<demo-host>/migrate
# expected: NO X-Frame-Options header, and CSP contains: frame-ancestors 'self'
```

The warden strips `X-Frame-Options` and rewrites `Content-Security-Policy`
`frame-ancestors` to `'self'` — so the instance frames on the demo page but
nowhere else.

### 10. Volume reap — no orphaned storage (claim 2) [O]

After a full session lifecycle (create → use → destroy):

```bash
docker volume ls
# expected: no anonymous volume attributable to the instance — nothing to reap because nothing was created
```

### 11. TTL independence — cleanup survives warden death (claim 3) [O]

Two independent mechanisms, neither relying on the warden's in-memory session
dict:

```bash
# (a) startup label-sweep: create a demo-labeled instance, then kill and restart the warden
docker kill demo-warden && docker start demo-warden
docker ps -a --filter label=demo.instance
# expected: the pre-restart instance is force-removed on warden startup — the warden adopts nothing

# (b) host systemd timer: stop the warden entirely, let a demo.*-labeled container
#     exceed the backstop ceiling (HARD_TTL + POOL_MAX_AGE + 120s slack = 1320s).
#     The slack guarantees this creation-age sweep can never fire inside a live
#     session's assignment-relative 900s window.
systemctl list-timers | grep demo-ttl-backstop     # sweep cadence: 60s
docker ps -a --filter label=demo.instance
# expected: once creation age exceeds 1320s, the timer force-removes it (within one
#           60s sweep) with the warden still stopped
```

### 12. Core-dump proof — crashes leave no memory image on disk (claim 5) [O]

Crash a process inside a live instance:

```bash
docker exec <id> sh -c 'kill -SIGSEGV <worker-pid>'

ls -la /var/crash /var/lib/systemd/coredump /var/lib/apport/coredump 2>/dev/null
# expected: nothing new appears in any of them
```

Why: `kernel.core_pattern` discards cores, `systemd-coredump` is configured
`Storage=none` / `ProcessSizeMax=0`, and apport is neutered. A crashing worker
whose memory contains a pasted config cannot write that memory to disk.

### 13. Fernet key never on disk (claim 7) [O]

Run this from the host using the **raw host docker socket** — not the warden's
proxied path, whose allowlist forbids `exec` by design:

```bash
docker exec <id> sh -c 'ls -la /app/data/.fernet_key'
# expected: "No such file or directory" — the key file does not exist

docker exec <id> printenv NETCANON_FERNET_KEY
# expected: set — a per-instance random key, injected as env at create time
```

Belt and braces: `/app/data` is tmpfs regardless (proof 2), so even if the
file had existed, it would never have touched disk.

---

## Pre-launch gate

The demo does not go (or stay) live on faith:

- **All CI tests green**, and
- **Proofs 1–13 executed on the production host**, with their raw output
  committed to `VERIFY_RESULTS_<date>.md`,
- **re-run on every image-digest bump** — a new pin means a fresh full pass.

Freshness note: this file describes the verification **mechanism**; the live
`/whitepaper` reproducibility block describes the **exact bundle currently
running**. When they disagree, the live block is the fresher of the two —
and `make verify` is how you check it.
