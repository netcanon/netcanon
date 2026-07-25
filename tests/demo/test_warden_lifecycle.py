"""Warden lifecycle: warm pool, assignment, and every destroy path (I3).

Covers the module-08 CI rows for claim 3 ("nothing survives the session") and
claim 1 ("your session runs in its own isolated instance") that can be proven
without a real daemon. The fake clock (see ``conftest.py``) makes the 900 s /
600 s deadlines instant and exact instead of untestable.

Live-stack counterparts (NOT covered here): that dockerd actually applied the
hardening spec, that ``demo-int`` really has no egress, and that the host systemd
backstop fires with the warden dead — see ``deploy/VERIFY.md`` proofs 2, 4, 11.
"""

from __future__ import annotations

import json

import pytest

from demo.warden import constants as C

pytestmark = pytest.mark.unit


def body_of(response) -> dict:
    return json.loads(response.body)


async def mint_many(warden, count: int) -> list[str]:
    """Mint *count* sessions across distinct IPs (the per-IP cap is 2).

    Refills the pool between mints because the live warden does that on a
    background task; without it the pool empties after ``POOL_SIZE`` mints and
    the warden correctly answers 503 (every session is under the 120 s
    reclaim floor). That saturation path is asserted on purpose in
    ``test_warden_caps.py`` — here we just want N healthy sessions.
    """
    tokens = []
    for i in range(count):
        await warden.fill_pool()
        resp = await warden.mint(ip=f"203.0.113.{10 + i // 2}")
        assert resp.status_code == 200, body_of(resp)
        tokens.append(body_of(resp)["token"])
    return tokens


# ── Warm pool ───────────────────────────────────────────────────────────────
async def test_pool_prewarms_to_pool_size(warden):
    await warden.fill_pool()
    assert len(warden.pool) == C.POOL_SIZE
    assert len(warden.docker.live) == C.POOL_SIZE


async def test_pool_refill_survives_a_failing_create(warden):
    """One create failure must not abandon the whole batch (fill what we can).

    Calls ``_refill_pool`` directly rather than the harness's ``fill_pool()``
    helper: the helper retries, which is right for tests that just need a warm
    pool but would multiply the failure count asserted here.
    """
    warden.docker.create_fails = True
    await warden.app._refill_pool()
    assert warden.pool == []
    assert warden.counters["pool_refill_failures"] == C.POOL_SIZE, (
        "each of the POOL_SIZE creates should be attempted and counted once"
    )

    warden.docker.create_fails = False
    await warden.app._refill_pool()
    assert len(warden.pool) == C.POOL_SIZE


# ── Mint contract ───────────────────────────────────────────────────────────
async def test_mint_response_contract(warden):
    """Locks the exact shape the frontend consumes.

    ``expires_at`` is deliberately absent — the frontend computes its countdown
    client-side as ``receipt_time + ttl_seconds`` (immune to clock skew). An
    earlier plan draft listed the field; the warden never emitted it. If this
    test ever fails, ``frontend/index.html`` must change in the same PR.
    """
    await warden.fill_pool()
    resp = await warden.mint()
    assert resp.status_code == 200
    payload = body_of(resp)

    assert set(payload) == {"token", "ttl_seconds", "idle_ttl_seconds", "instance_id"}
    assert payload["ttl_seconds"] == C.HARD_TTL
    assert payload["idle_ttl_seconds"] == C.IDLE_TTL
    assert isinstance(payload["token"], str) and payload["token"]
    # The chip shows the display id, never the routing token.
    assert payload["instance_id"] != payload["token"]


async def test_mint_sets_hardened_routing_cookie(warden):
    await warden.fill_pool()
    resp = await warden.mint()
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(f"{C.ROUTE_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=strict" in cookie.replace("samesite", "SameSite")
    assert "Path=/" in cookie
    assert f"Max-Age={C.HARD_TTL}" in cookie


async def test_two_sessions_get_distinct_instances(warden):
    """Claim 1: never a shared instance."""
    await warden.fill_pool()
    a = body_of(await warden.mint(ip="203.0.113.1"))
    b = body_of(await warden.mint(ip="203.0.113.2"))

    assert a["instance_id"] != b["instance_id"]
    assert a["token"] != b["token"]
    containers = {s.instance.container_id for s in warden.active.values()}
    assert len(containers) == 2


async def test_second_mint_from_same_browser_replaces_the_first(warden):
    """One live session per browser: a mint bearing a live cookie destroys it."""
    await warden.fill_pool()
    first = body_of(await warden.mint(ip="203.0.113.5"))["token"]

    second = body_of(await warden.mint(ip="203.0.113.5", cookie=first))["token"]

    assert first not in warden.active
    assert second in warden.active
    assert warden.counters["destroys_by_reason"]["end"] == 1


# ── I3: the hard TTL is immovable ───────────────────────────────────────────
async def test_hard_ttl_destroys_at_900s(warden):
    """A perfectly-behaved session (beats + translates throughout) still dies at
    the ceiling. Note the session must be kept healthy: without a heartbeat it
    would be reclaimed at 75 s and without work at 600 s, so a bare clock jump
    would prove nothing about the hard TTL."""
    await warden.fill_pool()
    token = body_of(await warden.mint())["token"]

    await warden.run_healthy(token, C.HARD_TTL - 1)
    assert token in warden.active, "must survive right up to the deadline"

    warden.clock.advance(2)
    await warden.tick()
    assert token not in warden.active
    assert warden.counters["destroys_by_reason"]["hard-ttl"] == 1


async def test_hard_ttl_is_not_extended_by_heartbeat_or_activity(warden):
    """Nothing the session does may push the ceiling out (the I3 claim).

    Drives the *real* activity path — ``_refresh_activity`` with an allowlisted
    translate POST — rather than poking fields, and asserts *when* the destroy
    landed, so a regression that silently extended the deadline would fail here.
    """
    await warden.fill_pool()
    token = body_of(await warden.mint())["token"]
    start = warden.clock.monotonic()

    for _ in range(60):  # bounded at twice the ceiling so a bug can't hang CI
        warden.clock.advance(C.HB_INTERVAL)
        session = warden.active.get(token)
        if session is not None:
            warden.app._refresh_activity(session, "POST", "/api/v1/migration/plan")
        await warden.tick()
        if token not in warden.active:
            break

    assert token not in warden.active, "a busy session must still hit the ceiling"
    elapsed = warden.clock.monotonic() - start
    assert C.HARD_TTL < elapsed <= C.HARD_TTL + C.HB_INTERVAL, (
        f"destroyed at {elapsed}s; must be within one beat of {C.HARD_TTL}s"
    )
    assert warden.counters["destroys_by_reason"]["hard-ttl"] == 1
    assert warden.counters["destroys_by_reason"]["idle"] == 0


async def test_ttl_is_assignment_relative_not_creation_relative(warden):
    """A pool instance aged just under the recycle threshold still gets a full
    900 s from *assignment* — the pool must not silently shorten a session."""
    await warden.fill_pool()
    warden.clock.advance(C.POOL_RECYCLE_AGE - 1)  # 289 s: aged but not recycled

    token = body_of(await warden.mint())["token"]

    await warden.run_healthy(token, C.HARD_TTL - 1)
    assert token in warden.active, "deadline must run from assignment, not creation"

    warden.clock.advance(2)
    await warden.tick()
    assert token not in warden.active
    assert warden.counters["destroys_by_reason"]["hard-ttl"] == 1


async def test_aged_pool_instance_is_recycled_not_assigned(warden):
    """No instance is ever assigned older than POOL_MAX_AGE."""
    await warden.fill_pool()
    original = {i.container_id for i in warden.pool}

    warden.clock.advance(C.POOL_RECYCLE_AGE + 1)
    await warden.tick()

    assert warden.counters["pool_recycled"] == C.POOL_SIZE
    assert {i.container_id for i in warden.pool}.isdisjoint(original)
    assert len(warden.pool) == C.POOL_SIZE, "recycled instances are refilled"


# ── Idle reclaim ────────────────────────────────────────────────────────────
async def test_idle_reclaim_fires_despite_a_perfect_heartbeat(warden):
    """A heartbeat alone must NOT keep a session alive — only real work does."""
    await warden.fill_pool()
    token = body_of(await warden.mint())["token"]
    session = warden.active[token]

    for _ in range(C.IDLE_TTL // C.HB_INTERVAL + 2):
        warden.clock.advance(C.HB_INTERVAL)
        session.last_heartbeat = warden.clock.monotonic()  # beating, never working
        await warden.tick()
        if token not in warden.active:
            break

    assert token not in warden.active
    assert warden.counters["destroys_by_reason"]["idle"] == 1


async def test_translating_holds_a_session_past_the_idle_ttl(warden):
    await warden.fill_pool()
    token = body_of(await warden.mint())["token"]
    session = warden.active[token]

    # Work every 5 minutes for longer than the idle TTL.
    for _ in range(3):
        warden.clock.advance(300)
        session.last_heartbeat = warden.clock.monotonic()
        warden.app._refresh_activity(session, "POST", "/api/v1/migration/detect")
        await warden.tick()

    assert token in warden.active, "an active translator must ride to the hard TTL"


# ── No-beacon reclaim (heartbeat timeout) ───────────────────────────────────
@pytest.mark.parametrize(
    "hidden,threshold",
    [(False, C.HB_STALE_VISIBLE), (True, C.HB_STALE_HIDDEN)],
    ids=["visible-tab", "hidden-tab"],
)
async def test_no_beacon_reclaim_uses_the_reported_visibility(warden, hidden, threshold):
    """A closed tab whose beacon never fired is reclaimed on heartbeat staleness;
    a backgrounded tab gets the longer window (browser timer throttling)."""
    await warden.fill_pool()
    token = body_of(await warden.mint())["token"]
    warden.active[token].hidden = hidden

    warden.clock.advance(threshold - 1)
    await warden.tick()
    assert token in warden.active

    warden.clock.advance(2)
    await warden.tick()
    assert token not in warden.active
    assert warden.counters["destroys_by_reason"]["hb"] == 1


# ── Idle-TTL hysteresis under load ──────────────────────────────────────────
async def test_idle_ttl_tightens_above_80pc_and_loosens_below_70pc(warden):
    await warden.fill_pool()
    tokens = await mint_many(warden, 26)  # 26/32 = 81% > 80%
    await warden.tick()
    assert warden.idle_ttl == C.IDLE_TTL_TIGHT

    # Drop to 22/32 = 69% < 70% -> loosen back.
    for token in tokens[:4]:
        await warden.app._destroy(token, "end")
    await warden.tick()
    assert warden.idle_ttl == C.IDLE_TTL


async def test_idle_ttl_does_not_thrash_in_the_dead_band(warden):
    """70–80% occupancy must leave the current threshold untouched."""
    await warden.fill_pool()
    await mint_many(warden, 24)  # 24/32 = 75%, inside the dead band
    await warden.tick()
    assert warden.idle_ttl == C.IDLE_TTL, "must not tighten inside the band"

    warden.app._idle_ttl = C.IDLE_TTL_TIGHT  # arrive from above
    await warden.tick()
    assert warden.idle_ttl == C.IDLE_TTL_TIGHT, "must not loosen inside the band"


# ── Teardown mechanics ──────────────────────────────────────────────────────
async def test_teardown_removes_container_and_anonymous_volumes(warden):
    """Claim 2/3: destroy must be remove(v=True, force=True) — the ``v`` is what
    sweeps any anonymous volume, so ``docker volume ls`` stays clean."""
    await warden.fill_pool()
    token = body_of(await warden.mint())["token"]
    container_id = warden.active[token].instance.container_id

    await warden.app._destroy(token, "end")

    container = warden.docker.containers_by_id[container_id]
    assert container.removed
    assert container.remove_calls == [{"v": True, "force": True}]


async def test_destroy_is_idempotent(warden):
    await warden.fill_pool()
    token = body_of(await warden.mint())["token"]

    await warden.app._destroy(token, "end")
    await warden.app._destroy(token, "end")  # must not raise or double-count

    assert warden.counters["destroys_by_reason"]["end"] == 1


async def test_destroy_releases_the_per_ip_slot(warden):
    await warden.fill_pool()
    token = body_of(await warden.mint(ip="203.0.113.77"))["token"]
    assert warden.per_ip["203.0.113.77"].active == 1

    await warden.app._destroy(token, "end")
    assert warden.per_ip["203.0.113.77"].active == 0


async def test_removal_failure_never_propagates(warden):
    """A daemon error during teardown must not escape ``_destroy``.

    The whole live side of I3 rides on the reaper loop staying alive, so removal
    is best-effort: the session leaves the active map regardless, and the
    creation-age systemd backstop is what still collects the container
    (``deploy/VERIFY.md`` proof 11).
    """
    await warden.fill_pool()
    token = body_of(await warden.mint())["token"]
    container = warden.docker.containers_by_id[warden.active[token].instance.container_id]

    def explode(*_args, **_kwargs):
        raise RuntimeError("daemon is unwell")

    container.remove = explode

    await warden.app._destroy(token, "hard-ttl")  # must not raise

    assert token not in warden.active, "session is dropped even if removal failed"
    assert warden.counters["destroys_by_reason"]["hard-ttl"] == 1
