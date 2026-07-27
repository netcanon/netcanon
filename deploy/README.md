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
| `cloud-init.yaml` | Hardened Ubuntu 24.04: docker, **key-only SSH**, **swap-off + core-dumps-off + journald-volatile** (I2), **fail2ban (SSH)**, unattended-upgrades, host firewall (443/80 + admin-only SSH, ICMPv6 allowed), chrony, `make` + `jq` for the deploy runbook, OOM protection. Clones this repo to `/opt/demo` and installs the TTL-backstop + demo-firewall units from it. |
| `systemd/` | `demo-ttl-backstop.{sh,service,timer}` — the warden-independent hard-TTL backstop (removes any `demo.*` container older than **1320 s** = `HARD_TTL + POOL_MAX_AGE + 120 s slack`, swept every 60 s). |
| `nftables/demo-int.nft` | The demo-int isolation rules (warden→instance ALLOW, instance→instance DENY, instance→warden DENY). |
| `Makefile` | `verify` / `verify-bundle` (Gate 4) / `whitepaper` / `deploy` / `down` + `dev-up` / `dev-down` / `smoke-*`. ⚠️ `drain` is **not implemented** and exits non-zero — the warden has no drain sentinel. |
| `demo.env.example` | Env template (image digests + ACME email). Copy → `demo.env` (**gitignored**; real values never commit). |
| `PINNED_PRODUCT_TAG` | The netcanon version the demo pins (`v0.6.1`). Bumped by ordinary PR. |

## Local Gate-1 (needs Docker)

```bash
cd deploy
cp demo.env.example demo.env    # edit: CADDY_IMAGE=caddy:2, ACME_EMAIL=...
                                #       SOCKET_PROXY_IMAGE=ghcr.io/tecnativa/docker-socket-proxy:v0.4.2
                                #       NETCANON_INSTANCE_IMAGE=ghcr.io/netcanon/netcanon:0.6.1
                                # socket-proxy must be v0.4.0+ — older tags render
                                # haproxy.cfg outside the tmpfs and crash-loop
                                # against the service's read-only rootfs.
docker pull ghcr.io/netcanon/netcanon:0.6.1
make dev-up
```

## Provisioning the host (Hetzner console)

Launch box: **CPX32** (4 shared AMD EPYC vCPU / 8 GB / 160 GB NVMe), **Ubuntu
24.04**, EU region. CPX rather than the originally-planned CX32 only because the
CX line was out of stock — identical CPU/RAM class, so `MAX_ACTIVE = 32` is
unchanged ([07](../docs/demo-plan/07-budget.md#sizing)).

⚠️ **x86 only.** `demo-publish.yml` builds the warden and shim amd64-only, so a
**CAX (ARM) box will not run them.**

### Create-server wizard

| Section | Setting | Why |
|---|---|---|
| Type | **CPX32** | 4 vCPU / 8 GB; measured demand is ~2.4 GiB at the full cap |
| Location | **EU** (Falkenstein / Nuremberg / Helsinki) | EU hosting is itself on-message for a privacy demo |
| Image | **Ubuntu 24.04** | What `cloud-init.yaml` targets |
| Networking | **IPv4 + IPv6** | See the AAAA caveat below |
| SSH keys | **Add your key** | `ssh_pwauth: false` — key-only; you log in as `root` |
| Volumes | **none** | Claim 2 is *zero persistent volumes*; the local disk is already ~100x what is needed |
| Firewalls | **create one** (rules below) | Free, and filters *before* the host — it survives an nftables mistake |
| Backups | **off** | See below |
| Placement groups | **none** | Anti-affinity for multi-server fleets; this is one box |
| Labels | optional | e.g. `project=netcanon-demo`, `env=prod` |
| Cloud config | paste `cloud-init.yaml` **after editing the SSH source** | See below |

**Cloud firewall rules** — inbound only; leave outbound unrestricted (the host
pulls from GHCR and talks to Let's Encrypt):

- TCP **80, 443** from `0.0.0.0/0` + `::/0`
- TCP **22** from **your admin IP only**

**Backups: off — and not only for the ~20 % surcharge.** The host is reproducible
from this repo by design (`make deploy` from a clean clone converging *is* Gate
3's acceptance test), so a snapshot restores nothing the repo does not. It would
also put a provider-held copy of Caddy's TLS private key and `demo.env` at rest.
That is not a claims violation — session data is tmpfs-only and never touches
disk — but it is an extra copy of secrets with no upside. If you ever do enable
it, disclose it in the whitepaper's *What we do see* section.

**Before pasting `cloud-init.yaml`:** replace `203.0.113.0/24` in the
`/etc/nftables.conf` block with your real admin source. That rule is **IPv4-only**
— if you SSH over IPv6 you will be locked out until you uncomment the `ip6 saddr`
line beside it. Hetzner's web console is the way back in either way.

**IPv6 caveat — publish an `A` record only.** Docker's IPv6 is off by default, so
Caddy's published ports bind IPv4. Keep IPv6 on the server (free, useful
outbound), but do **not** add an `AAAA` record yet — it would advertise an
address that never answers.

### First boot — verify before deploying

cloud-init failures do not stop the boot, so check rather than assume:

```bash
ssh root@<ip>
grep -i fatal /var/log/cloud-init-output.log        # expect no output
systemctl is-active demo-ttl-backstop.timer demo-firewall.service
swapon --show                                        # expect empty (I2)
cat /proc/sys/kernel/core_pattern                    # expect |/bin/false
nft list table inet host_fw                          # 80/443 open, SSH pinned
docker --version && docker compose version
```

If the backstop timer or demo-firewall unit is inactive, **stop** — the host is
missing hard-TTL enforcement (I3) or network isolation (I4), both of which the
whitepaper claims.

### DNS

Add **`demo.netcanon.net` → A → `<your IPv4>`, DNS-only (grey cloud)** *before*
`make deploy`. Caddy terminates TLS itself; with the record missing or proxied,
the ACME HTTP-01 challenge fails and Caddy will not serve.

## Deploy (human-pulled, on the host)

No GitHub deploy secret exists; the operator SSHes in and runs this by hand.

**`cosign` is required** — `make deploy` fails closed without it:

```bash
curl -sSLo /usr/local/bin/cosign https://github.com/sigstore/cosign/releases/latest/download/cosign-linux-amd64
chmod +x /usr/local/bin/cosign && cosign version
```

Unpack the release bundle, then:

```bash
make deploy DEMO_TAG=demo-v0.1.0 BUNDLE=./bundle
```

`deploy` depends on `promote`, which depends on `verify-bundle`, so neither the
Gate-4 check nor the promotion can be skipped. Verification first: it
`cosign verify-blob`s `SHA256SUMS` against the **exact** signer identity
(`demo-publish.yml@refs/tags/<DEMO_TAG>` — which is why the tag has to be passed
in; it is not recoverable from the bundle), then `sha256sum -c` makes that one
signed manifest vouch for every other asset. Only then does it pull the
digest-pinned images and `up -d`.

`promote` is the step that makes the verification mean something: it copies the
**verified** bundle's digests into `deploy/demo.env`, preserving your
`ACME_EMAIL` (the one value the bundle deliberately omits, since it is operator
data rather than a build output). Without it, `deploy` would verify a signed
bundle and then bring up whatever image refs happened to be sitting in
`demo.env` — which is exactly what the first real Gate-4 run caught.

Then `make whitepaper DEMO_TAG=demo-v0.1.0 BUNDLE=./bundle` to stamp the deploy date and
render the copy Caddy serves at `/whitepaper` (CI deliberately leaves that one
value blank — it cannot know when you deploy). Until you run it, `/whitepaper`
serves the committed template, banner and all.

## Traffic stats

The demo keeps no access log (claim 4) and the warden's counters are in-RAM, so
without sampling there is no answer to "how much traffic did this get". A
`demo-stats.timer` writes aggregate totals to `/var/log/demo-stats.jsonl` every
5 minutes — **totals only, no visitor dimension**, disclosed in the whitepaper's
*What we do see*.

```bash
# last sample
tail -1 /var/log/demo-stats.jsonl | jq .

# sessions and refusals over the file
jq -r '[.ts, (.warden.sessions_started//0), (.warden."503_count"//0)] | @tsv' /var/log/demo-stats.jsonl

# requests by status code
jq -r '[.ts, .http_requests_total, (.http_by_code|tostring)] | @tsv' /var/log/demo-stats.jsonl
```

Two things to know when reading it:

- **Counters reset.** They are cumulative-since-process-start, so a restart
  zeroes them. `warden_uptime_s` drops at the same moment — treat that as the
  reset marker, exactly like a Prometheus counter.
- **`warden: null` means the demo was unreachable** at that timestamp. That is a
  recorded outage, deliberately distinct from a missing sample (timer not run).

⚠️ **`503_count` is not a capacity signal.** It increments for per-IP rate limits
(429), true saturation (503), *and* instance-create failures. Only the second
means "the box is too small". Splitting it is open work.

## DDoS / abuse posture

- **L7 abuse:** warden per-IP concurrency cap (2) + mint rate limit (≤30/600 s), Caddy 2 MB body cap, fail-closed 503 at `MAX_ACTIVE`, per-instance cpu/mem/pids caps, no egress.
- **SSH:** fail2ban jail (above).
- **Volumetric L3/L4:** ⚠️ **not mitigated** — DNS-only Cloudflare exposes the origin IP and adds no scrubbing; only Hetzner's free network-edge protection applies. A conscious residual of the DNS-only trust-model choice (orange-cloud would fix it but adds Cloudflare to the TCB). The no-log privacy design also limits fail2ban-on-HTTP.

## Status — Gate 1 ✅, Gate 3 ✅ (real host), Gate 4 pending a release

**Gate 1 passed** on Docker Desktop: the stack runs end to end (mint → iframed
`/migrate` with XFO stripped and CSP `frame-ancestors` rewritten → allowlist 404s
→ destroy), instance hardening is verified *as applied by dockerd*, and the
instance network has no egress. `tests/demo/test_live_stack_smoke.py` scripts
those proofs; `tests/demo/load_sanity.py` measures capacity.

**Gate 3 passed** on the CPX32 (Ubuntu 24.04, bare dockerd), 2026-07-26 — the
proofs Docker Desktop structurally cannot run:

- **I4 host nftables** — instance→instance and instance→warden both blocked, and
  warden→instance still reachable, so the ALLOW rule is not over-broad. The two
  denials surface as connect *timeouts* (a silent nftables `drop`), whereas I5
  egress fails immediately with no-route — different signatures for the two
  different mechanisms, which is itself corroboration.
- **I5 no egress** — instances cannot reach `1.1.1.1:443` or `8.8.8.8:53`.
- **`DOCKER-USER` idempotency and survival** — exactly one jump and four rules
  after a `demo-firewall` restart *and* after a full `dockerd` restart. The
  latter matters in production: `unattended-upgrades` bumping `docker.io` would
  otherwise be able to drop I4 silently.
- **Capacity re-measured on the box** — 2420 MiB projected at `MAX_ACTIVE = 32`
  against 7745 MiB total; worked-instance RSS median 72.0 MiB, 28% of the 256 MiB
  per-instance guardrail; fails closed at saturation; swap still empty. Within 2%
  of the Docker Desktop estimate in [07](../docs/demo-plan/07-budget.md#sizing).
  One caveat worth recording: at full saturation `31/32` sessions rendered output
  — a ~3% shortfall at the cap, not reproduced below it.

Gate 3 also caught a release blocker: `demo-publish.yml` pinned a socket-proxy
version that crash-loops under the service's read-only rootfs. Gate 1 had passed
only because it ran an untagged image. See `SOCKET_PROXY_TMPFS_SAFE` in
`tests/demo/test_demo_docs_truth.py`.

**Still unverified — needs a published release (Gate 4):**

- `make deploy`'s signature / `SHA256SUMS` gate.
- The digest-pinned production stack end to end. Gate 3 exercised the
  source-built dev stack, which is the same compose file with `build:` overlaid.

Nothing is deployed. Nothing auto-deploys.
