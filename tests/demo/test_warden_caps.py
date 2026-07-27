"""Caps, rate limits, and saturation behaviour (whitepaper claim 8).

Claim 8 is "the demo can't silently degrade isolation under load": at the cap it
must return 503 rather than share an instance, and it must never sacrifice a
session that could still be mid-paste. These are the rows a reviewer is most
likely to distrust, so they are asserted at the exact boundary rather than
approximately.

Live-stack counterpart: driving real load against a real daemon (module 08's
capacity SLO / `load_sanity.py`) stays out of PR CI.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from demo.warden import constants as C

pytestmark = pytest.mark.unit


def body_of(response) -> dict:
    return json.loads(response.body)


async def saturate(warden, count: int | None = None) -> list[str]:
    """Fill the warden to *count* (default MAX_ACTIVE) live sessions."""
    count = count or C.MAX_ACTIVE
    tokens = []
    for i in range(count):
        await warden.fill_pool()
        resp = await warden.mint(ip=f"198.51.100.{10 + i // 2}")
        assert resp.status_code == 200, body_of(resp)
        tokens.append(body_of(resp)["token"])
    return tokens


# ── Per-IP concurrency cap ──────────────────────────────────────────────────
async def test_third_concurrent_session_from_one_ip_is_refused(warden):
    """The visitor-visible half of claim 8 (VERIFY.md proof 6)."""
    await warden.fill_pool()
    ip = "198.51.100.7"

    first = await warden.mint(ip=ip)
    second = await warden.mint(ip=ip)
    third = await warden.mint(ip=ip)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert body_of(third) == {"reason": "rate_limited"}
    assert warden.per_ip[ip].active == C.PER_IP_MAX_CONCURRENT


async def test_ending_a_session_frees_the_per_ip_slot(warden):
    await warden.fill_pool()
    ip = "198.51.100.8"
    token = body_of(await warden.mint(ip=ip))["token"]
    await warden.mint(ip=ip)
    assert (await warden.mint(ip=ip)).status_code == 429

    await warden.app._destroy(token, "end")
    await warden.fill_pool()

    assert (await warden.mint(ip=ip)).status_code == 200


async def test_a_different_ip_is_unaffected_by_another_ips_cap(warden):
    await warden.fill_pool()
    await warden.mint(ip="198.51.100.20")
    await warden.mint(ip="198.51.100.20")
    assert (await warden.mint(ip="198.51.100.20")).status_code == 429

    await warden.fill_pool()
    assert (await warden.mint(ip="198.51.100.21")).status_code == 200


# ── Per-IP sliding-window mint rate limit ───────────────────────────────────
async def test_mint_rate_limit_trips_after_the_window_budget(warden):
    """<= PER_IP_MINT_MAX mints per window per IP, even if each is ended."""
    ip = "198.51.100.30"
    for _ in range(C.PER_IP_MINT_MAX):
        await warden.fill_pool()
        resp = await warden.mint(ip=ip)
        assert resp.status_code == 200, body_of(resp)
        await warden.app._destroy(body_of(resp)["token"], "end")

    await warden.fill_pool()
    refused = await warden.mint(ip=ip)
    assert refused.status_code == 429
    assert body_of(refused) == {"reason": "rate_limited"}


async def test_mint_budget_recovers_after_the_window_slides(warden):
    ip = "198.51.100.31"
    for _ in range(C.PER_IP_MINT_MAX):
        await warden.fill_pool()
        resp = await warden.mint(ip=ip)
        await warden.app._destroy(body_of(resp)["token"], "end")
    assert (await warden.mint(ip=ip)).status_code == 429

    warden.clock.advance(C.PER_IP_MINT_WINDOW + 1)
    await warden.fill_pool()

    assert (await warden.mint(ip=ip)).status_code == 200


# ── Global cap + reclaim floor ──────────────────────────────────────────────
async def test_empty_pool_below_the_cap_creates_inline_instead_of_refusing(warden):
    """An empty pool must NOT be read as saturation.

    Found by ``load_sanity.py``: a burst larger than POOL_SIZE drains the warm
    pool before the background refill catches up, and the mint path then went
    straight to reclaim — which correctly refuses when every session is young.
    Net effect was a 503 "capacity" while most of MAX_ACTIVE sat idle, i.e. the
    demo would have turned away a launch-day spike at a fraction of capacity.
    Free headroom must be spent before anyone is refused or reclaimed.
    """
    await warden.fill_pool()
    warden.pool.clear()  # simulate a burst having drained the pool
    assert len(warden.active) < C.MAX_ACTIVE, "precondition: headroom exists"

    resp = await warden.mint(ip="198.51.100.90")

    assert resp.status_code == 200, (
        f"refused with headroom free: {body_of(resp)} — an empty pool is not the cap"
    )
    assert warden.counters["destroys_by_reason"]["reclaim"] == 0, (
        "no live session may be sacrificed while slots are free"
    )
    assert sum(warden.counters["refusals_by_reason"].values()) == 0


async def test_a_burst_larger_than_the_pool_is_fully_served(warden):
    """The load-sanity scenario, in-process: POOL_SIZE=4 but a 12-session burst
    must all be granted while far below MAX_ACTIVE."""
    await warden.fill_pool()

    responses = await asyncio.gather(
        *[warden.mint(ip=f"198.51.100.{100 + i}") for i in range(12)]
    )

    statuses = [r.status_code for r in responses]
    assert statuses == [200] * 12, f"burst not fully served: {statuses}"
    assert len(warden.active) == 12
    assert len({s.instance.container_id for s in warden.active.values()}) == 12


async def test_saturation_with_only_young_sessions_returns_503(warden):
    """The 120 s floor protects a seconds-old paste: at true saturation the
    warden refuses rather than killing someone mid-translation."""
    await saturate(warden)
    assert len(warden.active) == C.MAX_ACTIVE

    refused = await warden.mint(ip="198.51.100.200")

    assert refused.status_code == 503
    assert body_of(refused) == {"reason": "capacity"}
    assert len(warden.active) == C.MAX_ACTIVE, "no session may be sacrificed"
    assert warden.counters["destroys_by_reason"]["reclaim"] == 0


async def test_saturation_reclaims_the_longest_idle_session_past_the_floor(warden):
    """Above the floor, the least-recently-active session is the victim."""
    tokens = await saturate(warden)
    # Age everything past the reclaim floor while keeping it all healthy.
    for _ in range(5):
        warden.clock.advance(C.HB_INTERVAL)
        for token in tokens:
            warden.keep_healthy(token)
        await warden.tick()

    victim, luckier = tokens[7], tokens[8]
    warden.active[victim].last_activity = warden.clock.monotonic() - 200
    warden.active[luckier].last_activity = warden.clock.monotonic() - 100

    resp = await warden.mint(ip="198.51.100.201")

    assert resp.status_code == 200, body_of(resp)
    assert victim not in warden.active, "the longest-idle session is reclaimed"
    assert luckier in warden.active
    assert warden.counters["destroys_by_reason"]["reclaim"] == 1
    assert len(warden.active) == C.MAX_ACTIVE, "reclaim-then-create-inline holds the cap"


async def test_a_session_under_the_min_age_floor_is_never_the_victim(warden):
    """Even with an idle old session present, a brand-new one must survive."""
    tokens = await saturate(warden)
    for _ in range(5):
        warden.clock.advance(C.HB_INTERVAL)
        for token in tokens:
            warden.keep_healthy(token)
        await warden.tick()

    # Free one slot, refill it with a fresh session, then saturate again.
    await warden.app._destroy(tokens[0], "end")
    await warden.fill_pool()
    newborn = body_of(await warden.mint(ip="198.51.100.210"))["token"]
    # Make the newborn look like the least-recently-active candidate.
    warden.active[newborn].last_activity = warden.clock.monotonic() - 10_000

    await warden.mint(ip="198.51.100.211")

    assert newborn in warden.active, (
        "a session younger than the 120 s floor must never be reclaimed, "
        "even when it is the least-recently-active"
    )


# ── Concurrency safety ──────────────────────────────────────────────────────
async def test_simultaneous_mints_never_share_an_instance(warden):
    """Reserve-then-fill must hold under a burst: no container may back two
    tokens, and MAX_ACTIVE may never be exceeded."""
    await warden.fill_pool()

    responses = await asyncio.gather(
        *[warden.mint(ip=f"198.51.100.{40 + i}") for i in range(12)]
    )

    granted = [body_of(r) for r in responses if r.status_code == 200]
    assert granted, "at least the warm pool should have been handed out"

    container_ids = [s.instance.container_id for s in warden.active.values()]
    assert len(container_ids) == len(set(container_ids)), "an instance was double-assigned"
    instance_ids = [g["instance_id"] for g in granted]
    assert len(instance_ids) == len(set(instance_ids))
    assert len(warden.active) <= C.MAX_ACTIVE
    assert warden.app._reserving == 0, "every reservation must be released"


async def test_pool_and_active_together_respect_the_global_cap(warden):
    await saturate(warden)
    await warden.fill_pool()

    assert len(warden.active) + len(warden.pool) <= C.MAX_ACTIVE
    assert len(warden.docker.live) <= C.MAX_ACTIVE


# ── Per-IP record hygiene (RAM-only, bounded) ───────────────────────────────
async def test_idle_per_ip_records_are_evicted_after_their_ttl(warden):
    """The whitepaper promises the record is held "up to 10 minutes after your
    last request" and never longer."""
    await warden.fill_pool()
    ip = "198.51.100.60"
    token = body_of(await warden.mint(ip=ip))["token"]
    await warden.app._destroy(token, "end")

    warden.clock.advance(C.PER_IP_TTL + 1)
    await warden.tick()

    assert ip not in warden.per_ip


async def test_active_per_ip_records_survive_the_ttl_sweep(warden):
    await warden.fill_pool()
    ip = "198.51.100.61"
    token = body_of(await warden.mint(ip=ip))["token"]

    warden.clock.advance(C.PER_IP_TTL + 1)
    await warden.tick()

    if token in warden.active:  # still live -> record must be retained
        assert ip in warden.per_ip


async def test_per_ip_table_is_capped_under_a_unique_ip_flood(warden, monkeypatch):
    """Backstop against a memory-exhaustion flood from many distinct IPs."""
    monkeypatch.setattr(C, "MAX_IP_RECORDS", 10)
    for i in range(25):
        record = warden.app.IpRecord()
        record.last_seen = warden.clock.monotonic()
        record.active = 0
        warden.per_ip[f"192.0.2.{i}"] = record

    await warden.tick()

    assert len(warden.per_ip) <= 10


# ── Counters (the /healthz operational surface) ─────────────────────────────
async def test_refusals_are_counted(warden):
    await saturate(warden)
    before = sum(warden.counters["refusals_by_reason"].values())

    await warden.mint(ip="198.51.100.220")

    assert sum(warden.counters["refusals_by_reason"].values()) == before + 1


# The three refusals below mean completely different things to an operator:
# rate_limited is one visitor being greedy, capacity is the box being too small,
# create_failed is Docker or the image being broken. The old single `503_count`
# summed all three (and counted a 429 as a 503), so it could not answer the one
# question it existed for — it read 33 on a box that had never been near its
# cap. Each test asserts the OTHER buckets stay put; that isolation is the whole
# point of the split, and a shared counter would pass the increment half alone.
def _refusals(warden) -> dict:
    return dict(warden.counters["refusals_by_reason"])


async def test_a_rate_limited_visitor_is_counted_apart(warden):
    """One IP over PER_IP_MAX_CONCURRENT. This is a 429, not a 503 at all."""
    await warden.fill_pool()
    for _ in range(C.PER_IP_MAX_CONCURRENT):
        assert (await warden.mint(ip="198.51.100.7")).status_code == 200
    before = _refusals(warden)

    resp = await warden.mint(ip="198.51.100.7")

    assert resp.status_code == 429, body_of(resp)
    after = _refusals(warden)
    assert after["rate_limited"] == before["rate_limited"] + 1
    assert after["capacity"] == before["capacity"]
    assert after["create_failed"] == before["create_failed"]


async def test_a_capacity_refusal_is_counted_apart(warden):
    """Genuine saturation: every slot taken and nothing reclaimable."""
    await saturate(warden)
    before = _refusals(warden)

    resp = await warden.mint(ip="198.51.100.221")

    assert resp.status_code == 503, body_of(resp)
    after = _refusals(warden)
    assert after["capacity"] == before["capacity"] + 1
    assert after["rate_limited"] == before["rate_limited"]
    assert after["create_failed"] == before["create_failed"]


async def test_a_broken_docker_is_not_counted_as_capacity(warden):
    """The refusal the old counter hid: plenty of headroom, but the create
    fails. Reported as `capacity` on the wire (the frontend keys its states on
    that, and "try again shortly" is right either way) while the counter says
    `create_failed` — otherwise a broken image reads as "buy a bigger box"."""
    warden.docker.create_fails = True
    assert not warden.pool, "the create path is only reached with an empty pool"
    before = _refusals(warden)

    resp = await warden.mint(ip="198.51.100.222")

    assert resp.status_code == 503, body_of(resp)
    assert body_of(resp)["reason"] == "capacity", "wire contract must not move"
    after = _refusals(warden)
    assert after["create_failed"] == before["create_failed"] + 1, (
        "a create failure must not be filed under capacity — that is the "
        "conflation the split exists to remove"
    )
    assert after["capacity"] == before["capacity"]
    assert after["rate_limited"] == before["rate_limited"]


# ── Engagement: minted vs actually used ─────────────────────────────────────
# `sessions_started` alone cannot distinguish a visitor who translated a config
# from one who opened the page and left. That difference is the only product
# question the warden can answer without reading a body or keeping a per-visitor
# record — /api/v1/migration/plan ALWAYS returns HTTP 200 and carries the real
# outcome in the response body, which the proxy never buffers (I2), so "did it
# succeed" is deliberately out of reach. "Did they try" is not.
def _touch(warden, sess, path, method="POST"):
    warden.app._refresh_activity(sess, method, path)


async def test_a_session_that_translates_is_counted_once(warden):
    await warden.fill_pool()
    token = body_of(await warden.mint(ip="198.51.100.31"))["token"]
    sess = warden.active[token]
    assert warden.counters["sessions_that_translated"] == 0

    _touch(warden, sess, "/api/v1/migration/plan")
    assert warden.counters["sessions_that_translated"] == 1

    # A visitor tweaking panes POSTs repeatedly; that is still ONE session that
    # engaged, so the counter must stay a session count and not become a request
    # count that one power user can dominate.
    for path in ("/api/v1/migration/plan", "/api/v1/migration/plan/ports",
                 "/api/v1/migration/plan/vlans"):
        _touch(warden, sess, path)
    assert warden.counters["sessions_that_translated"] == 1


async def test_detect_and_sanitize_alone_do_not_count_as_translating(warden):
    """`IDLE_RESETTING` covers eight POST paths, not just the plan ones. A
    visitor who auto-detects a vendor or sanitises a config and then leaves has
    not translated anything, and counting them would quietly inflate the
    engagement rate the number exists to measure."""
    await warden.fill_pool()
    token = body_of(await warden.mint(ip="198.51.100.32"))["token"]
    sess = warden.active[token]

    for path in ("/api/v1/migration/detect", "/api/v1/sanitize"):
        _touch(warden, sess, path)
    assert warden.counters["sessions_that_translated"] == 0, (
        "detect/sanitize counted as a translation"
    )
    assert sess.last_activity > 0, "these paths must still reset the idle timer"


async def test_engagement_is_counted_per_session_not_per_visitor(warden):
    """Two sessions that each translate count twice — the counter tracks
    sessions, and the warden holds no cross-session visitor identity to dedupe
    against even if it wanted to."""
    await warden.fill_pool()
    for i, ip in enumerate(("198.51.100.41", "198.51.100.42")):
        token = body_of(await warden.mint(ip=ip))["token"]
        _touch(warden, warden.active[token], "/api/v1/migration/plan")
        assert warden.counters["sessions_that_translated"] == i + 1
