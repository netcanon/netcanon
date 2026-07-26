"""In-process test harness for the demo warden.

The warden is Trusted Computing Base: its lifecycle guarantees (I3 hard TTL,
the caps, the route allowlist) are the whitepaper's load-bearing claims, so they
need tests that run on every PR — not only in the live-stack smoke.

Two problems make a naive test suite impossible, and this harness solves both:

1. **Wall-clock.** ``HARD_TTL`` is 900 s and ``IDLE_TTL`` 600 s. Asserting a
   real 15-minute destroy cannot live in PR CI, and the TTLs are deliberately
   hard-coded constants (``constants.py`` is the single source of truth the
   whitepaper cites — making them env-tunable in production would weaken the
   claim). So we swap the *warden module's* ``time`` reference for a fake clock
   we advance by hand. Patching the global ``time.monotonic`` instead would
   break asyncio's own scheduler, hence the module-attribute swap.
2. **Docker.** The warden talks to a real daemon. :class:`FakeDocker` records
   every call, so we can assert *what the warden asks Docker to do* — including
   that teardown uses ``remove(v=True, force=True)``.

**Honest scope.** These tests prove the warden's own logic and the spec it
*requests*. They cannot prove the daemon *applied* that spec, that the internal
network really has no egress, or that the socket-proxy denies `exec` — those
need a real daemon and stay in the live-stack smoke (module 08's `[O]` rows /
`deploy/VERIFY.md`). Each test that has a live-stack counterpart says so.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types

import pytest

# constants.py reads these at import time — they must be set first.
os.environ.setdefault("NETCANON_INSTANCE_IMAGE", "ghcr.io/netcanon/netcanon@sha256:test")
os.environ.setdefault("NETCANON_INSTANCE_NETWORK", "demo-int")

from demo.warden import constants as C


def _install_docker_sdk_stub() -> None:
    """Register a stub ``docker`` module so the warden imports without the SDK.

    The warden's own dependencies are containerized (``demo/warden/requirements.txt``)
    and the docker SDK is deliberately NOT a dependency of the netcanon package —
    adding one just to import the module under test would put ``requests``/
    ``urllib3`` into every CI job for no runtime benefit. Since these tests drive
    a :class:`FakeDocker` anyway, the only real SDK surface the warden needs is
    the exception classes it catches. Installed unconditionally so a machine that
    happens to have the SDK behaves identically to CI.
    """
    docker_mod = types.ModuleType("docker")
    errors_mod = types.ModuleType("docker.errors")

    class DockerException(Exception):
        pass

    class NotFound(DockerException):
        pass

    class ImageNotFound(NotFound):
        pass

    errors_mod.DockerException = DockerException
    errors_mod.NotFound = NotFound
    errors_mod.ImageNotFound = ImageNotFound

    class DockerClient:  # only referenced in a postponed annotation
        pass

    def from_env(*_args, **_kwargs):
        raise RuntimeError(
            "docker.from_env() is unavailable in the in-process suite; "
            "tests inject a FakeDocker via the `warden` fixture"
        )

    docker_mod.errors = errors_mod
    docker_mod.DockerClient = DockerClient
    docker_mod.from_env = from_env

    sys.modules["docker"] = docker_mod
    sys.modules["docker.errors"] = errors_mod


_install_docker_sdk_stub()


class FakeClock:
    """Stand-in for the ``time`` module, injected into the warden's namespace.

    Only ``monotonic`` and ``time`` are used by the warden. Advancing is
    explicit, so every TTL assertion is deterministic and instant.
    """

    def __init__(self, start: float = 10_000.0) -> None:
        self._now = start

    def monotonic(self) -> float:
        return self._now

    def time(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class FakeContainer:
    def __init__(self, cid: str, ip: str, kwargs: dict, registry: FakeDocker) -> None:
        self.id = cid
        self._ip = ip
        self.create_kwargs = kwargs
        self._registry = registry
        self.started = False
        self.removed = False
        self.remove_calls: list[dict] = []

    @property
    def labels(self) -> dict:
        return dict(self.create_kwargs.get("labels") or {})

    @property
    def attrs(self) -> dict:
        network = self.create_kwargs.get("network") or ""
        return {"NetworkSettings": {"Networks": {network: {"IPAddress": self._ip}}}}

    def start(self) -> None:
        self.started = True

    def reload(self) -> None:  # no-op; attrs are already populated
        pass

    def remove(self, v: bool = False, force: bool = False) -> None:
        self.remove_calls.append({"v": v, "force": force})
        self.removed = True
        self._registry.removed.append(self)


class _Containers:
    def __init__(self, registry: FakeDocker) -> None:
        self._r = registry

    def create(self, **kwargs):
        if self._r.create_fails:
            raise RuntimeError("simulated docker create failure")
        self._r.create_calls.append(kwargs)
        n = len(self._r.create_calls)
        c = FakeContainer(f"c{n:04d}deadbeef", f"172.31.0.{100 + n}", kwargs, self._r)
        self._r.containers_by_id[c.id] = c
        return c

    def get(self, container_id: str):
        import docker.errors

        c = self._r.containers_by_id.get(container_id)
        if c is None:
            raise docker.errors.NotFound(f"no such container {container_id}")
        return c

    def list(self, all: bool = False, filters: dict | None = None):
        # The warden only ever filters by the demo.instance label.
        return [c for c in self._r.containers_by_id.values() if not c.removed]


class _Images:
    def __init__(self, registry: FakeDocker) -> None:
        self._r = registry

    def get(self, name: str):
        import docker.errors

        if self._r.image_present:
            return object()
        raise docker.errors.ImageNotFound(f"no such image {name}")


class FakeDocker:
    """Minimal stand-in for ``docker.DockerClient`` recording every call."""

    def __init__(self) -> None:
        self.containers_by_id: dict[str, FakeContainer] = {}
        self.create_calls: list[dict] = []
        self.removed: list[FakeContainer] = []
        self.image_present = True
        self.create_fails = False
        self.containers = _Containers(self)
        self.images = _Images(self)

    @property
    def live(self) -> list[FakeContainer]:
        return [c for c in self.containers_by_id.values() if not c.removed]


class Warden:
    """Handle bundling the warden module with its fake clock + fake daemon."""

    def __init__(self, app_module, clock: FakeClock, docker_client: FakeDocker) -> None:
        self.app = app_module
        self.clock = clock
        self.docker = docker_client

    # ── convenience accessors (keep tests readable) ─────────────────────────
    @property
    def pool(self) -> list:
        return self.app._pool

    @property
    def active(self) -> dict:
        return self.app._active

    @property
    def per_ip(self) -> dict:
        return self.app._per_ip

    @property
    def counters(self) -> dict:
        return self.app._counters

    @property
    def idle_ttl(self) -> float:
        return self.app._idle_ttl

    async def drain_background(self) -> None:
        """Settle the warden's fire-and-forget tasks.

        ``session_new`` kicks off ``_refill_pool()`` via ``_spawn``. While that
        task is in flight it holds the single-flight ``_refilling`` flag, so an
        explicit ``fill_pool()`` would return immediately WITHOUT filling — and
        the next mint would then correctly 503 on an empty pool. That race is
        scheduling-dependent, i.e. an intermittent CI failure. Draining first
        makes the harness deterministic.
        """
        # Bounded, and yields explicitly: the done-callback that removes a task
        # from _bg_tasks runs via call_soon, so a completed-but-not-yet-discarded
        # task would make gather() return without ever yielding — an unbounded
        # `while _bg_tasks` spins forever on that.
        for _ in range(50):
            pending = [task for task in list(self.app._bg_tasks) if not task.done()]
            if not pending:
                self.app._bg_tasks.clear()
                return
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.sleep(0)

    async def fill_pool(self) -> None:
        """Bring the pool up to POOL_SIZE, deterministically."""
        await self.drain_background()
        for _ in range(5):
            await self.app._refill_pool()
            if len(self.app._pool) >= C.POOL_SIZE:
                return
            await self.drain_background()

    async def tick(self) -> None:
        """Run one reaper tick (the loop itself is never started in tests)."""
        await self.app._reaper_tick()

    def keep_healthy(self, token: str) -> None:
        """Mark a session as freshly heartbeaten *and* freshly active.

        Needed because three independent deadlines race: without a heartbeat the
        session dies at ``HB_STALE_VISIBLE`` (75 s) and without work it dies at
        ``IDLE_TTL`` (600 s) — both long before the 900 s ceiling. Isolating the
        hard-TTL path therefore requires simulating a perfectly-behaved visitor.
        """
        session = self.app._active.get(token)
        if session is not None:
            session.last_heartbeat = self.clock.monotonic()
            session.last_activity = self.clock.monotonic()

    async def run_healthy(self, token: str, seconds: float, step: float | None = None) -> None:
        """Advance *seconds* in heartbeat-sized steps, keeping the session healthy
        and running the reaper each step (the way a live session really ages)."""
        step = step or C.HB_INTERVAL
        remaining = seconds
        while remaining > 0:
            delta = min(step, remaining)
            self.clock.advance(delta)
            remaining -= delta
            self.keep_healthy(token)
            await self.tick()

    async def mint(self, ip: str = "203.0.113.10", cookie: str | None = None):
        """Mint a session the way the HTTP route does, without a real request."""
        request = FakeRequest(ip=ip, cookie=cookie)
        return await self.app.session_new(request)


class FakeRequest:
    """The subset of ``starlette.Request`` the warden's session routes touch."""

    def __init__(self, ip: str = "203.0.113.10", cookie: str | None = None,
                 body: dict | None = None, method: str = "GET",
                 accept: str | None = None) -> None:
        self.headers = {"x-forwarded-for": ip}
        if accept is not None:
            self.headers["accept"] = accept
        self.cookies = {}
        if cookie is not None:
            self.cookies[C.ROUTE_COOKIE] = cookie
        self.client = None
        self.method = method
        self._body = body or {}

    async def json(self) -> dict:
        return self._body


@pytest.fixture
def make_request():
    """Factory for the minimal request object the warden's routes touch.

    Exposed as a fixture rather than imported directly: ``tests/demo`` is not a
    package (PEP-420 namespace layout), so a relative import of conftest fails.
    """
    return FakeRequest


@pytest.fixture
def warden(monkeypatch) -> Warden:
    """A warden module with pristine state, a fake clock, and a fake daemon.

    The warden keeps live state in module globals, so every test gets them reset.
    ``_lock`` is re-created because pytest-asyncio hands each test a fresh event
    loop and an ``asyncio.Lock`` binds to the first loop that acquires it.
    """
    from demo.warden import app as app_module

    clock = FakeClock()
    docker_client = FakeDocker()

    monkeypatch.setattr(app_module, "time", clock)
    monkeypatch.setattr(app_module, "_docker", docker_client)
    monkeypatch.setattr(app_module, "_lock", asyncio.Lock())
    monkeypatch.setattr(app_module, "_pool", [])
    monkeypatch.setattr(app_module, "_active", {})
    monkeypatch.setattr(app_module, "_per_ip", {})
    monkeypatch.setattr(app_module, "_bg_tasks", set())
    monkeypatch.setattr(app_module, "_idle_ttl", app_module.C.IDLE_TTL)
    monkeypatch.setattr(app_module, "_refilling", False)
    monkeypatch.setattr(app_module, "_reserving", 0)
    monkeypatch.setattr(app_module, "_counters", {
        "sessions_started": 0,
        "destroys_by_reason": dict.fromkeys(
            ("hard-ttl", "idle", "hb", "end", "reclaim"), 0
        ),
        "pool_recycled": 0,
        "503_count": 0,
        "pool_refill_failures": 0,
    })

    return Warden(app_module, clock, docker_client)
