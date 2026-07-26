"""netcanon ephemeral-demo warden — session manager + hardened reverse proxy.

The only stateful service.  Live state is one in-memory dict, but durable
lifecycle enforcement does NOT depend on it (container labels + a startup sweep +
an independent host systemd timer — see the reaper).  Run single-process
(``uvicorn --workers 1``); one ``asyncio.Lock`` guards pool/active/caps, held only
for O(1) in-RAM mutations, never across an awaited docker call (reserve-then-fill).

Spec: ``docs/demo-plan/03-warden-spec.md`` + ``04-container-hardening.md``.
This is Trusted Computing Base — keep it small and auditable (<=500 lines).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import docker
import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from . import constants as C

log = logging.getLogger("warden")

# ── In-RAM state (never persisted; a crash is covered by the label sweep) ────
_pool: list[Instance] = []  # unassigned, ready instances
_active: dict[str, Session] = {}  # routing token -> Session
_per_ip: dict[str, IpRecord] = {}  # source IP -> rate/concurrency record
_lock = asyncio.Lock()  # guards _pool/_active/_per_ip — O(1) mutations only
_idle_ttl = C.IDLE_TTL  # current idle TTL (hysteresis, see _adjust_idle_ttl)
_refilling = False  # single-flight pool-refill guard
_reserving = 0  # instances popped/created for an in-flight mint, not yet in _active
_docker: docker.DockerClient | None = None
_http: httpx.AsyncClient | None = None
_counters = {
    "sessions_started": 0,
    "destroys_by_reason": dict.fromkeys(("hard-ttl", "idle", "hb", "end", "reclaim"), 0),
    "pool_recycled": 0,
    "503_count": 0,
    "pool_refill_failures": 0,
}
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    """Fire-and-forget, keeping a ref so it is not GC'd (RUF006) and surfacing
    exceptions (an unretrieved task exception is otherwise silent)."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_on_bg_done)


def _on_bg_done(task: asyncio.Task) -> None:
    _bg_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.error("background task failed", exc_info=task.exception())


@dataclass
class Instance:
    container_id: str
    instance_id: str  # the demo.instance label / display id (NOT the token)
    created_mono: float  # monotonic clock, for age/recycle
    ip: str  # the container's address on demo-int, for proxying


@dataclass
class Session:
    token: str
    instance: Instance
    deadline: float  # monotonic: assignment_time + HARD_TTL (immovable, I3)
    last_heartbeat: float
    last_activity: float
    hidden: bool = False
    src_ip: str = ""


@dataclass
class IpRecord:
    mints: list[float] = field(default_factory=list)  # monotonic mint timestamps
    active: int = 0
    last_seen: float = 0.0


# ── Docker helpers (synchronous SDK; always via asyncio.to_thread) ───────────
def _client() -> docker.DockerClient:
    assert _docker is not None
    return _docker


def _docker_create_and_start() -> Instance:
    """Create + start one hardened instance and return it (blocking)."""
    api_key = secrets.token_urlsafe(24)
    fernet_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()  # valid Fernet key
    created_wall = int(time.time())
    instance_id = secrets.token_hex(6)
    kwargs = C.build_instance_create_kwargs(api_key, fernet_key, created_wall, instance_id)
    container = _client().containers.create(**kwargs)
    container.start()
    container.reload()
    ip = ""
    nets = container.attrs.get("NetworkSettings", {}).get("Networks", {})
    if C.INSTANCE_NETWORK in nets:
        ip = nets[C.INSTANCE_NETWORK].get("IPAddress", "") or ""
    inst = Instance(
        container_id=container.id,
        instance_id=instance_id,
        created_mono=time.monotonic(),
        ip=ip,
    )
    inst._api_key = api_key  # type: ignore[attr-defined]  # injected into proxied /api/v1
    return inst


def _docker_remove(container_id: str) -> None:
    try:
        c = _client().containers.get(container_id)
        c.remove(v=True, force=True)  # v=True also sweeps anonymous volumes
    except docker.errors.NotFound:
        pass
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("remove failed id=%s err=%s", container_id[:12], exc)


def _docker_list_demo_ids() -> list[str]:
    """All demo-labelled container ids (for the startup orphan sweep)."""
    cs = _client().containers.list(all=True, filters={"label": C.LABEL_SELECTOR})
    return [c.id for c in cs]


def _docker_image_present() -> bool:
    try:
        _client().images.get(C.INSTANCE_IMAGE)
        return True
    except docker.errors.ImageNotFound:
        return False


# ── Pool / lifecycle ────────────────────────────────────────────────────────
async def _refill_pool() -> None:
    """Bring the pool up to POOL_SIZE, single-flight (one refill at a time)."""
    global _refilling
    async with _lock:
        if _refilling:
            return
        need = C.POOL_SIZE - len(_pool)
        # respect the global cap: pool + active must stay <= MAX_ACTIVE
        room = C.MAX_ACTIVE - (len(_pool) + len(_active) + _reserving)
        need = max(0, min(need, room))
        if need <= 0:
            return
        _refilling = True
    try:
        for _ in range(need):
            try:
                inst = await asyncio.to_thread(_docker_create_and_start)
            except Exception as exc:
                _counters["pool_refill_failures"] += 1
                log.warning("pool refill failed: %s", exc)
                continue  # fill what we can; don't abandon the batch on one failure
            async with _lock:
                _pool.append(inst)
    finally:
        async with _lock:
            _refilling = False


def _occupancy() -> float:
    return len(_active) / float(C.MAX_ACTIVE) if C.MAX_ACTIVE else 0.0


def _adjust_idle_ttl() -> None:
    """Occupancy-driven hysteresis: tighten >80%, loosen <70%."""
    global _idle_ttl
    occ = _occupancy()
    if occ > C.OCCUPANCY_TIGHTEN:
        _idle_ttl = C.IDLE_TTL_TIGHT
    elif occ < C.OCCUPANCY_LOOSEN:
        _idle_ttl = C.IDLE_TTL


def _stale_threshold(hidden: bool) -> float:
    return C.HB_STALE_HIDDEN if hidden else C.HB_STALE_VISIBLE


async def _destroy(token: str, reason: str) -> None:
    """Remove a session's instance and drop it from the active map."""
    async with _lock:
        sess = _active.pop(token, None)
        if sess is None:
            return
        rec = _per_ip.get(sess.src_ip)
        if rec and rec.active > 0:
            rec.active -= 1
    await asyncio.to_thread(_docker_remove, sess.instance.container_id)
    _counters["destroys_by_reason"][reason] = (
        _counters["destroys_by_reason"].get(reason, 0) + 1
    )
    log.info("session_destroyed reason=%s", reason)


async def _reaper_tick() -> None:
    now = time.monotonic()
    expired: list[tuple[str, str]] = []
    recycle: list[Instance] = []
    async with _lock:
        _adjust_idle_ttl()
        for token, s in _active.items():
            if now > s.deadline:
                expired.append((token, "hard-ttl"))
            elif now - s.last_activity > _idle_ttl:
                expired.append((token, "idle"))
            elif now - s.last_heartbeat > _stale_threshold(s.hidden):
                expired.append((token, "hb"))
        # recycle unassigned pool instances older than POOL_RECYCLE_AGE
        keep: list[Instance] = []
        for inst in _pool:
            if now - inst.created_mono > C.POOL_RECYCLE_AGE:
                recycle.append(inst)
            else:
                keep.append(inst)
        _pool[:] = keep
        # evict stale per-IP records
        for ip in [ip for ip, r in _per_ip.items() if now - r.last_seen > C.PER_IP_TTL and r.active <= 0]:
            _per_ip.pop(ip, None)
        # hard cap: under a unique-IP flood, drop the least-recently-seen idle
        # records so _per_ip can't grow without bound between stale sweeps.
        if len(_per_ip) > C.MAX_IP_RECORDS:
            idle = sorted((r.last_seen, ip) for ip, r in _per_ip.items() if r.active <= 0)
            for _, ip in idle[: len(_per_ip) - C.MAX_IP_RECORDS]:
                _per_ip.pop(ip, None)
    for token, reason in expired:
        await _destroy(token, reason)
    for inst in recycle:
        await asyncio.to_thread(_docker_remove, inst.container_id)
        _counters["pool_recycled"] += 1
    await _refill_pool()


async def _reaper() -> None:
    """Every REAPER_PERIOD: expire sessions, recycle aged pool instances, refill.
    Exception-guarded: one failed tick must not kill TTL enforcement for good."""
    while True:
        await asyncio.sleep(C.REAPER_PERIOD)
        try:
            await _reaper_tick()
        except Exception:
            log.exception("reaper tick failed; continuing")


# ── Proxy helpers ───────────────────────────────────────────────────────────
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


def _fix_response_headers(headers: httpx.Headers) -> list[tuple[str, str]]:
    """Strip XFO and rewrite CSP frame-ancestors 'none' -> 'self' so the demo
    origin may iframe the instance; drop hop-by-hop headers."""
    out: list[tuple[str, str]] = []
    for k, v in headers.multi_items():
        kl = k.lower()
        if kl in _HOP_BY_HOP or kl == "x-frame-options":
            continue
        if kl == "content-security-policy":
            v = re.sub(r"frame-ancestors\s+'none'", "frame-ancestors 'self'", v, flags=re.IGNORECASE)
        out.append((k, v))
    return out


async def _proxy(request: Request, inst: Instance, path: str, token: str) -> Response:
    """Stream a request to the instance; never buffer or log a body (I2)."""
    assert _http is not None
    url = f"http://{inst.ip}:{C.INSTANCE_PORT}{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() not in ("host", "authorization")
    }
    fwd_headers["X-Forwarded-For"] = request.client.host if request.client else ""
    # Inject the per-instance API key on /api/v1 calls (kept out of the browser).
    # netcanon gates /api/v1 on `Authorization: Bearer <key>` (netcanon/api/auth.py).
    if path.startswith("/api/v1"):
        fwd_headers["Authorization"] = f"Bearer {getattr(inst, '_api_key', '')}"
    req = _http.build_request(
        request.method, url, headers=fwd_headers, content=request.stream()
    )
    upstream = await _http.send(req, stream=True)
    resp_headers = _fix_response_headers(upstream.headers)

    async def _body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    resp = StreamingResponse(_body(), status_code=upstream.status_code)
    # Preserve duplicate headers (multiple Set-Cookie / CSP) — dict() would collapse them.
    resp.raw_headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in resp_headers]
    # (Re)stamp the routing cookie so absolute-path requests reach this instance.
    resp.set_cookie(
        C.ROUTE_COOKIE, token, max_age=C.HARD_TTL, path="/",
        httponly=True, secure=True, samesite="strict",
    )
    return resp


def _refresh_activity(sess: Session, method: str, path: str) -> None:
    now = time.monotonic()
    sess.last_heartbeat = now
    if method.upper() == "POST" and path in C.IDLE_RESETTING:
        sess.last_activity = now


# ── App ─────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    global _docker, _http
    _docker = docker.from_env()
    _http = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0),
        limits=httpx.Limits(max_connections=256, max_keepalive_connections=64),
    )
    if not C.INSTANCE_IMAGE:
        raise RuntimeError("NETCANON_INSTANCE_IMAGE is not set (must be digest-pinned)")
    if not await asyncio.to_thread(_docker_image_present):
        raise RuntimeError(f"pinned instance image absent locally: {C.INSTANCE_IMAGE}")
    # Adopt nothing: force-remove every demo-labelled container left by a prior run.
    for cid in await asyncio.to_thread(_docker_list_demo_ids):
        await asyncio.to_thread(_docker_remove, cid)
    await _refill_pool()
    _spawn(_reaper())
    yield
    if _http is not None:
        await _http.aclose()


app = FastAPI(
    title="netcanon-demo-warden", docs_url=None, redoc_url=None,
    openapi_url=None, lifespan=_lifespan,
)


def _client_ip(request: Request) -> str:
    # request.client.host is Caddy; the visitor is the first X-Forwarded-For hop.
    # Trusted because only Caddy can reach the warden (instances are denied it).
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


@app.post("/session/new")
async def session_new(request: Request) -> Response:
    global _reserving
    ip = _client_ip(request)
    now = time.monotonic()
    # If this browser already has a live session, destroy-and-replace it.
    existing = request.cookies.get(C.ROUTE_COOKIE)
    if existing and existing in _active:
        await _destroy(existing, "end")
    async with _lock:
        rec = _per_ip.setdefault(ip, IpRecord())
        rec.last_seen = now
        rec.mints = [t for t in rec.mints if now - t < C.PER_IP_MINT_WINDOW]
        if len(rec.mints) >= C.PER_IP_MINT_MAX or rec.active >= C.PER_IP_MAX_CONCURRENT:
            _counters["503_count"] += 1
            return JSONResponse({"reason": "rate_limited"}, status_code=429)
        # Cap-check the POOL-HIT path too: a refill can land between another
        # mint's room check and this pop, so a warm instance != a free slot.
        # At cap `inst` stays None and the block below reclaims instead.
        at_cap = len(_active) + _reserving >= C.MAX_ACTIVE
        inst = None if at_cap else (_pool.pop(0) if _pool else None)
        if inst is not None:
            _reserving += 1  # hold it against the cap until it lands in _active
    if inst is None:
        # An empty pool is NOT the cap: a burst drains it before the background
        # refill catches up. Spend free headroom before reclaiming or refusing.
        async with _lock:
            headroom = C.MAX_ACTIVE - (len(_pool) + len(_active) + _reserving) > 0
            if headroom:
                _reserving += 1
        if not headroom:  # true saturation: reclaim the longest-idle session
            if await _reclaim_one(now) is None:
                _counters["503_count"] += 1
                return JSONResponse({"reason": "capacity"}, status_code=503)
            async with _lock:
                _reserving += 1
        try:
            inst = await asyncio.to_thread(_docker_create_and_start)
        except Exception as exc:
            async with _lock:
                _reserving -= 1
            log.warning("inline instance create failed: %s", exc)
            _counters["503_count"] += 1
            return JSONResponse({"reason": "capacity"}, status_code=503)
    token = secrets.token_urlsafe(C.TOKEN_NBYTES)
    async with _lock:
        _reserving -= 1
        rec = _per_ip.setdefault(ip, IpRecord())
        rec.mints.append(now)
        rec.active += 1
        rec.last_seen = now
        _active[token] = Session(
            token=token, instance=inst, deadline=now + C.HARD_TTL,
            last_heartbeat=now, last_activity=now, src_ip=ip,
        )
        _counters["sessions_started"] += 1
    _spawn(_refill_pool())
    resp = JSONResponse({
        "token": token,
        "ttl_seconds": C.HARD_TTL,
        "idle_ttl_seconds": _idle_ttl,
        "instance_id": inst.instance_id,
    })
    resp.set_cookie(
        C.ROUTE_COOKIE, token, max_age=C.HARD_TTL, path="/",
        httponly=True, secure=True, samesite="strict",
    )
    return resp


async def _reclaim_one(now: float) -> str | None:
    """Reclaim the longest-idle session older than the min-age floor; None if all young."""
    async with _lock:
        candidates = [
            (s.last_activity, tok) for tok, s in _active.items()
            if now - s.deadline + C.HARD_TTL > C.RECLAIM_MIN_AGE  # session age > floor
        ]
        if not candidates:
            return None
        candidates.sort()
        victim = candidates[0][1]
    await _destroy(victim, "reclaim")
    return victim


@app.post("/session/{token}/hb")
async def session_hb(token: str, request: Request) -> Response:
    sess = _active.get(token)
    if sess is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    sess.hidden = bool(body.get("hidden", False))
    sess.last_heartbeat = time.monotonic()
    remaining = int(_idle_ttl - (time.monotonic() - sess.last_activity))
    return JSONResponse({"idle_remaining_seconds": max(0, remaining)})


@app.post("/session/{token}/end")
async def session_end(token: str) -> Response:
    if token in _active:
        await _destroy(token, "end")
    return Response(status_code=204)


@app.get("/healthz")
async def healthz() -> Response:
    return JSONResponse({
        "pool": len(_pool),
        "active": len(_active),
        "idle_ttl": _idle_ttl,
        **_counters,
    })


@app.api_route("/i/{token}/{path:path}", methods=["GET", "POST"])
async def iframe_route(token: str, path: str, request: Request) -> Response:
    sess = _active.get(token)
    full = "/" + path
    if sess is None or time.monotonic() > sess.deadline or not C.route_allowed(request.method, full):
        return Response(status_code=404)
    _refresh_activity(sess, request.method, full)
    return await _proxy(request, sess.instance, full, token)


@app.api_route("/{full_path:path}", methods=["GET", "POST"])
async def cookie_route(full_path: str, request: Request) -> Response:
    token = request.cookies.get(C.ROUTE_COOKIE)
    sess = _active.get(token) if token else None
    full = "/" + full_path
    if sess is None or time.monotonic() > sess.deadline or not C.route_allowed(request.method, full):
        return Response(status_code=404)
    _refresh_activity(sess, request.method, full)
    return await _proxy(request, sess.instance, full, token)
