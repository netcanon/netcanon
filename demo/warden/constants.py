"""Single source of truth for the netcanon ephemeral-demo warden.

Every hardening flag and lifecycle constant the demo whitepaper cites lives
here, so the claim table in ``docs/demo-plan/06-privacy-whitepaper.md`` maps to
ONE file.  The warden applies :data:`INSTANCE_SPEC` verbatim; the create-body
authz shim (``authz_shim.py``) validates every ``POST /containers/create``
against the SAME spec, so "create-with-fixed-spec" is *enforced*, not hoped.

Spec references: ``docs/demo-plan/03-warden-spec.md`` (lifecycle, caps, API) and
``docs/demo-plan/04-container-hardening.md`` (the container spec + route
allowlist).
"""

from __future__ import annotations

import os

# ── Ports ──────────────────────────────────────────────────────────────────
INSTANCE_PORT = 8000  # netcanon's listen port (Dockerfile ``EXPOSE 8000``)

# ── Lifecycle TTLs (seconds) ────────────────────────────────────────────────
HARD_TTL = 900  # 15-min hard ceiling, measured from ASSIGNMENT (I3)
IDLE_TTL = 600  # 10-min idle reclaim (no allowlisted proxied POST)
IDLE_TTL_TIGHT = 300  # idle TTL under load (occupancy > OCCUPANCY_TIGHTEN)
POOL_MAX_AGE = 300  # an instance is never ASSIGNED more than this after creation
REAPER_PERIOD = 10  # reaper loop tick
# Recycle an unassigned pool instance older than this (destroy + refill), so no
# instance is ever assigned older than POOL_MAX_AGE.
POOL_RECYCLE_AGE = POOL_MAX_AGE - REAPER_PERIOD  # 290
# Creation-age ceiling for the warden-startup sweep + the independent host
# systemd backstop.  Provably looser than any live session's 900s
# assignment-relative deadline, so it can never fire early.
HARD_TTL_BACKSTOP = HARD_TTL + POOL_MAX_AGE  # 1200

# ── Heartbeat / no-beacon reclaim ───────────────────────────────────────────
HB_INTERVAL = 30  # frontend heartbeat cadence
HB_STALE_VISIBLE = 75  # stale threshold while the tab reports visible
HB_STALE_HIDDEN = 180  # ...while hidden (tolerate background-timer throttling)

# ── Caps ────────────────────────────────────────────────────────────────────
MAX_ACTIVE = 32  # global instance cap (CX32; docs/demo-plan/07-budget.md)
POOL_SIZE = 4  # warm-pool target (counts toward MAX_ACTIVE)
PER_IP_MAX_CONCURRENT = 2  # concurrent sessions per source IP
PER_IP_MINT_WINDOW = 600  # sliding window for the per-IP mint rate limit
PER_IP_MINT_MAX = 30  # <= 30 mints / window / IP
PER_IP_TTL = 600  # evict a per-IP record this long after its last request
RECLAIM_MIN_AGE = 120  # never reclaim a session younger than this at cap

# ── Occupancy-driven idle-TTL hysteresis ────────────────────────────────────
OCCUPANCY_TIGHTEN = 0.80  # occupancy > this -> IDLE_TTL_TIGHT
OCCUPANCY_LOOSEN = 0.70  # occupancy < this -> IDLE_TTL (the 70-80% dead-band)

# ── Session token / routing cookie ──────────────────────────────────────────
TOKEN_NBYTES = 16  # secrets.token_urlsafe(16) -> 128-bit token
ROUTE_COOKIE = "nc_route"  # warden-set HttpOnly routing cookie (see 03 Proxying)

# ── Container labels (the hard-TTL backstop keys; NOT the token) ─────────────
LABEL_CREATED_AT = "demo.created_at"
LABEL_INSTANCE = "demo.instance"
# ``docker ... --filter label=demo.instance`` selects only demo instances.
LABEL_SELECTOR = LABEL_INSTANCE

# ── Instance image + network (I1/I4/I5) ─────────────────────────────────────
# Digest-pinned in deploy (``NETCANON_INSTANCE_IMAGE=ghcr.io/netcanon/netcanon@sha256:...``).
# The warden refuses to start if this is unset or the image is absent locally.
INSTANCE_IMAGE = os.environ.get("NETCANON_INSTANCE_IMAGE", "")
INSTANCE_NETWORK = os.environ.get("NETCANON_INSTANCE_NETWORK", "demo-int")

# Every writable path in RAM (I1/I2).  BOTH declared VOLUME paths
# (/app/data AND /app/configs) must be tmpfs or Docker creates a persistent
# anonymous host-disk volume that falsifies "zero volumes".
INSTANCE_TMPFS = {
    "/tmp": "rw,noexec,nosuid,size=64m",  # Starlette spools >~1MB multipart here
    "/app/data": "rw,noexec,nosuid,size=32m",
    "/app/configs": "rw,noexec,nosuid,size=8m",
}
INSTANCE_MEM_LIMIT = "256m"  # fail-closed OOM guardrail, NOT the sizing basis
INSTANCE_NANO_CPUS = 500_000_000  # 0.5 CPU
INSTANCE_PIDS_LIMIT = 128


def build_instance_create_kwargs(
    api_key: str, fernet_key: str, created_at: int, instance_id: str
) -> dict:
    """docker-py ``containers.create(**kwargs)`` for one hardened instance.

    Only the two ``demo.*`` labels and the two per-instance random env keys
    (``api_key``, ``fernet_key``) vary between instances; every other field is
    the canonical spec the authz shim pins.  No ``user`` override — the image
    already runs non-root as uid 1000 via ``USER app``; forcing a different uid
    breaks tmpfs ownership.
    """
    return {
        "image": INSTANCE_IMAGE,
        "read_only": True,  # I1: read-only rootfs
        "tmpfs": {**INSTANCE_TMPFS},  # I1/I2: every writable path in RAM
        "network": INSTANCE_NETWORK,  # I4: internal-only network
        "mem_limit": INSTANCE_MEM_LIMIT,
        "memswap_limit": INSTANCE_MEM_LIMIT,  # == mem_limit: no swap headroom (I2)
        "nano_cpus": INSTANCE_NANO_CPUS,
        "pids_limit": INSTANCE_PIDS_LIMIT,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "log_config": {"type": "none"},  # I2: daemon keeps no container output
        "labels": {
            LABEL_CREATED_AT: str(created_at),
            LABEL_INSTANCE: instance_id,
        },
        "environment": {
            "NETCANON_API_KEY": api_key,  # gates the non-loopback bind; per-instance
            "NETCANON_HOST": "0.0.0.0",  # reachable only on the internal net
            "NETCANON_PORT": str(INSTANCE_PORT),
            "NETCANON_LOG_LEVEL": "warning",  # bodies never logged at any level
            "NETCANON_FERNET_KEY": fernet_key,  # RAM-only; no key file is written
        },
    }


# ── Feature-surface reduction: the warden route allowlist (04) ──────────────
# Anything not matched here -> 404 at the warden.  netcanon has NO static
# assets (all CSS/JS inline) and NO /api/v1/translate route; translation runs
# through POST /api/v1/migration/plan and its typed sub-plans.
ALLOW_GET_EXACT = frozenset(
    {
        "/migrate",
        "/sanitize",
        "/health",
        "/api/v1/migration/adapters",
        "/api/v1/migration/target-profiles",
    }
)
ALLOW_GET_PREFIX = (
    "/api/v1/migration/adapters/",  # /{name}/capabilities
    "/api/v1/migration/target-profiles/",  # /{vendor}/{model}
)
ALLOW_POST_EXACT = frozenset(
    {
        "/api/v1/migration/plan",
        "/api/v1/migration/plan/ports",
        "/api/v1/migration/plan/vlans",
        "/api/v1/migration/plan/local_users",
        "/api/v1/migration/plan/snmp",
        "/api/v1/migration/plan/snmpv3",
        "/api/v1/migration/detect",
        "/api/v1/sanitize",
    }
)
# Any allowlisted proxied POST refreshes last_activity (resets the idle timer);
# GETs and /hb do not.  POST /api/v1/migration/render is deliberately NOT here.
IDLE_RESETTING = ALLOW_POST_EXACT


def route_allowed(method: str, path: str) -> bool:
    """Whole-path default-deny allowlist check for a proxied instance request."""
    method = method.upper()
    if method == "GET":
        if path in ALLOW_GET_EXACT:
            return True
        return any(path.startswith(p) for p in ALLOW_GET_PREFIX)
    if method == "POST":
        return path in ALLOW_POST_EXACT
    return False
