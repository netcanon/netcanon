#!/usr/bin/env python3
"""Capacity / load-sanity probe for the ephemeral demo (Gate 5).

Answers the one sizing question the plan cannot answer on paper: **what does a
real held session actually cost?** ``INSTANCE_MEM_LIMIT`` (256 MB) is a
fail-closed guardrail, NOT the sizing basis — sizing ``MAX_ACTIVE`` off the cap
would over-provision by ~2x. So this drives N concurrent sessions through real
translations and reports measured RSS, then projects the full-cap footprint.

It also asserts the capacity invariants that must hold under pressure:

* every session gets its **own** container — never a shared instance;
* ``MAX_ACTIVE`` is never exceeded;
* at saturation the demo **fails closed** (503 / 429) rather than sharing;
* no OOM-kill of the warden, shim, socket-proxy or Caddy — the instance cap is
  supposed to bound instances, not starve the control plane;
* a closed tab's slot frees within the SLO.

Usage (needs a running stack — see test_live_stack_smoke.py for `make smoke-up`)::

    python tests/demo/load_sanity.py                    # MAX_ACTIVE sessions
    python tests/demo/load_sanity.py --sessions 8       # smaller smoke run
    python tests/demo/load_sanity.py --json report.json # machine-readable

Exits non-zero if any invariant fails, so it can gate Gate 5. The measured
numbers are printed either way — a run that fails an invariant still tells you
what the box needs.

⚠️ Measure on the REAL target box. Docker Desktop numbers are indicative only:
its VM accounting, page-cache behaviour and CPU quota differ from a bare Hetzner
CX32, and 32 instances will contend very differently there.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from demo.warden import constants as C

# A representative payload: the same sample the demo's own "try this sample"
# button pastes, so measured RSS reflects the real visitor path.
SAMPLE_CONFIG = """hostname edge-sw1
!
vlan 10
 name USERS
vlan 20
 name VOICE
!
interface GigabitEthernet1/0/1
 description uplink-to-core
 switchport mode trunk
 switchport trunk allowed vlan 10,20
!
interface GigabitEthernet1/0/2
 description user-access
 switchport mode access
 switchport access vlan 10
!
interface Vlan10
 ip address 10.10.10.1 255.255.255.0
!
ip route 0.0.0.0 0.0.0.0 10.10.10.254
!
snmp-server community public RO
!
"""

INFRA_CONTAINERS = ("warden", "authz-shim", "socket-proxy", "caddy")


# ── docker helpers ──────────────────────────────────────────────────────────
def docker(*args: str, check: bool = True) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=120)
    if check and result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def mib(value: str) -> float:
    """Parse a `docker stats` size ('123.4MiB', '1.2GiB') into MiB."""
    value = value.strip()
    for suffix, factor in (("GiB", 1024.0), ("MiB", 1.0), ("KiB", 1 / 1024.0), ("B", 1 / 1048576.0)):
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * factor
    return 0.0


def instance_rss() -> dict[str, float]:
    """MiB of RSS per live demo instance, keyed by SHORT CONTAINER ID.

    Keyed by id, not name: ``docker stats`` prints docker's random names
    (``elastic_volhard``), which cannot be matched back to the ids that
    ``docker ps -q`` gives for a session's container. Both sides use the 12-char
    short id so assigned instances can be separated from the idle warm pool.
    """
    ids = docker("ps", "-q", "--filter", f"label={C.LABEL_INSTANCE}").splitlines()
    if not ids:
        return {}
    raw = docker("stats", "--no-stream", "--format", "{{.ID}}\t{{.MemUsage}}", *ids)
    out: dict[str, float] = {}
    for line in raw.splitlines():
        if "\t" not in line:
            continue
        cid, usage = line.split("\t", 1)
        out[cid.strip()] = mib(usage.split("/")[0])
    return out


def infra_rss() -> dict[str, float]:
    out: dict[str, float] = {}
    for fragment in INFRA_CONTAINERS:
        ids = docker("ps", "-q", "--filter", f"name={fragment}").splitlines()
        if not ids:
            continue
        raw = docker("stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}", ids[0])
        if "\t" in raw:
            name, usage = raw.split("\t", 1)
            out[name] = mib(usage.split("/")[0])
    return out


def oom_killed() -> list[str]:
    """Any infra container the kernel OOM-killed. The instance cap exists to
    bound instances, not to starve the control plane."""
    killed = []
    for fragment in INFRA_CONTAINERS:
        for cid in docker("ps", "-aq", "--filter", f"name={fragment}").splitlines():
            state = json.loads(docker("inspect", cid))[0]["State"]
            if state.get("OOMKilled"):
                killed.append(f"{fragment} ({cid[:12]})")
    return killed


def container_for(instance_id: str) -> str:
    cid = docker("ps", "-q", "--filter", f"label={C.LABEL_INSTANCE}={instance_id}")
    return cid.splitlines()[0] if cid else ""


# ── the probe ───────────────────────────────────────────────────────────────
def visitor_ip(index: int) -> str:
    """A distinct source IP per simulated visitor (RFC 5737 documentation range).

    Reaching ``MAX_ACTIVE`` requires distinct source IPs: ``PER_IP_MAX_CONCURRENT``
    is 2, so a probe hammering from one address gets 2 sessions and 30 refusals —
    it would measure the per-IP cap, not capacity.

    The warden reads the first ``X-Forwarded-For`` hop and trusts it *because in
    production only Caddy can reach it* (instances on demo-int are denied the
    warden's port). The smoke override publishes the warden directly, so this
    probe can present per-visitor addresses. That is **simulating N visitors, not
    defeating a control** — and ``check_per_ip_cap`` below proves the cap still
    works, so the shortcut cannot mask a broken guardrail.
    """
    return f"198.51.100.{1 + index % 250}"


def mint(base_url: str, index: int, source_ip: str | None = None) -> dict:
    started = time.monotonic()
    headers = {"X-Forwarded-For": source_ip or visitor_ip(index)}
    try:
        response = httpx.post(f"{base_url}/session/new", headers=headers, timeout=120.0)
    except httpx.HTTPError as exc:
        return {"index": index, "error": str(exc), "status": 0}
    record = {
        "index": index,
        "status": response.status_code,
        "mint_seconds": round(time.monotonic() - started, 3),
    }
    if response.status_code == 200:
        record.update(response.json())
    else:
        record["reason"] = (response.json() or {}).get("reason", "")
    return record


def translate(base_url: str, token: str) -> dict:
    """Drive a real translation so RSS reflects a working session."""
    started = time.monotonic()
    try:
        response = httpx.post(
            f"{base_url}/i/{token}/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "juniper_junos",
                "raw_text": SAMPLE_CONFIG,
            },
            timeout=180.0,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": str(exc)}
    payload = response.json() if response.status_code == 200 else {}
    return {
        "ok": response.status_code == 200,
        "status": response.status_code,
        "job_status": payload.get("status"),
        "renders": bool(payload.get("rendered")),
        "seconds": round(time.monotonic() - started, 3),
    }


def check_per_ip_cap(base_url: str, fail) -> dict:
    """Prove the per-IP cap still bites, BEFORE the load phase spreads across
    simulated IPs. Without this, presenting per-visitor addresses could hide a
    broken guardrail behind a green capacity report."""
    ip = "203.0.113.253"
    opened = []
    try:
        for _ in range(C.PER_IP_MAX_CONCURRENT):
            record = mint(base_url, 0, source_ip=ip)
            if record["status"] != 200:
                fail(f"per-IP probe could not open {C.PER_IP_MAX_CONCURRENT} sessions "
                     f"(got {record['status']}) — capacity too low to test the cap")
                return {"verified": False}
            opened.append(record)
        extra = mint(base_url, 0, source_ip=ip)
        if extra["status"] == 429:
            print(f"  OK    per-IP cap holds: session "
                  f"{C.PER_IP_MAX_CONCURRENT + 1} from one IP refused (429)")
            return {"verified": True, "status": 429}
        if extra["status"] == 200:
            opened.append(extra)
        fail(f"per-IP cap did NOT bite: session {C.PER_IP_MAX_CONCURRENT + 1} "
             f"from one IP returned {extra['status']}")
        return {"verified": False, "status": extra["status"]}
    finally:
        for record in opened:
            try:
                httpx.post(f"{base_url}/session/{record['token']}/end", timeout=30.0)
            except httpx.HTTPError:
                pass


def report_memory(report: dict, session_containers: set[str]) -> dict[str, float]:
    """Measure and print RSS, then project the full-cap footprint.

    Split out of ``run()`` to keep that function within the project's complexity
    limit; it is also the one phase worth reading on its own, since its output is
    the number the box gets sized from.
    """
    per_instance = instance_rss()
    control_plane = infra_rss()
    report["instance_rss_mib"] = per_instance
    report["infra_rss_mib"] = control_plane

    print("\nmeasured RSS (MiB):")
    if per_instance:
        # Partition assigned (worked) vs warm-pool (idle). Mixing them skews the
        # median toward idle and would UNDER-size the box; the sizing basis has
        # to be a session that actually translated.
        # Both sides are 12-char short ids (see instance_rss).
        session_ids = {cid[:12] for cid in session_containers}
        assigned = {k: v for k, v in per_instance.items() if k[:12] in session_ids}
        idle_pool = {k: v for k, v in per_instance.items() if k[:12] not in session_ids}

        def summarise(values: list[float]) -> dict:
            ordered = sorted(values)
            return {
                "count": len(ordered),
                "min": round(ordered[0], 1),
                "median": round(statistics.median(ordered), 1),
                "max": round(ordered[-1], 1),
                "total": round(sum(ordered), 1),
            }

        report["instance_rss_all"] = summarise(list(per_instance.values()))
        print(f"  all live instances: {report['instance_rss_all']}")
        if idle_pool:
            report["instance_rss_pool"] = summarise(list(idle_pool.values()))
            print(f"  warm pool (idle):  {report['instance_rss_pool']}")

        # Prefer the worked sessions; fall back to all with a loud caveat.
        if assigned:
            basis = summarise(list(assigned.values()))
            report["instance_rss_assigned"] = basis
            print(f"  ASSIGNED (worked): {basis}   <- sizing basis")
        else:
            basis = report["instance_rss_all"]
            print("  note  could not isolate assigned instances; using ALL live "
                  "instances as the basis (includes idle pool -> may under-size)")

        cap = float(C.INSTANCE_MEM_LIMIT.rstrip("m"))
        print(f"  per-instance cap is {cap:.0f} MiB — the worked median is "
              f"{basis['median'] / cap * 100:.0f}% of it "
              f"(the cap is a fail-closed guardrail, not the sizing basis)")
        projected = basis["median"] * C.MAX_ACTIVE + sum(control_plane.values())
        report["projected_full_cap_mib"] = round(projected, 1)
        print(f"  PROJECTED at MAX_ACTIVE={C.MAX_ACTIVE}: "
              f"{projected:.0f} MiB instances+control-plane "
              f"({projected / 1024:.2f} GiB)")
    else:
        print("  (no live instances to measure)")
    for name, value in sorted(control_plane.items()):
        note = "  (NOT RUNNING — 0 is not a measurement)" if value == 0.0 else ""
        print(f"  {name}: {value:.1f}{note}")

    return control_plane


def run(base_url: str, sessions: int, slo_seconds: int) -> dict:
    report: dict = {"requested_sessions": sessions, "failures": []}

    def fail(message: str) -> None:
        report["failures"].append(message)
        print(f"  FAIL  {message}")

    baseline = httpx.get(f"{base_url}/healthz", timeout=15.0).json()
    print(f"baseline: pool={baseline['pool']} active={baseline['active']}")

    print("\nverifying the per-IP cap before spreading load across IPs...")
    report["per_ip_cap"] = check_per_ip_cap(base_url, fail)

    # ── mint concurrently ───────────────────────────────────────────────────
    print(f"\nminting {sessions} concurrent sessions...")
    with ThreadPoolExecutor(max_workers=min(sessions, 16)) as pool:
        minted = list(pool.map(lambda i: mint(base_url, i), range(sessions)))

    granted = [m for m in minted if m["status"] == 200]
    refused = [m for m in minted if m["status"] in (429, 503)]
    broken = [m for m in minted if m["status"] not in (200, 429, 503)]
    print(f"  granted={len(granted)} refused={len(refused)} unexpected={len(broken)}")
    if broken:
        fail(f"{len(broken)} mint(s) returned an unexpected status: "
             f"{sorted({m['status'] for m in broken})}")

    latencies = sorted(m["mint_seconds"] for m in granted)
    if latencies:
        report["mint_seconds"] = {
            "p50": latencies[len(latencies) // 2],
            "max": latencies[-1],
        }
        print(f"  mint latency p50={report['mint_seconds']['p50']}s "
              f"max={report['mint_seconds']['max']}s")

    # ── invariant: never a shared instance ──────────────────────────────────
    instance_ids = [m["instance_id"] for m in granted]
    containers = {i: container_for(i) for i in instance_ids}
    missing = [i for i, c in containers.items() if not c]
    if missing:
        fail(f"{len(missing)} granted session(s) have no live container")
    distinct = {c for c in containers.values() if c}
    if len(distinct) != len([c for c in containers.values() if c]):
        fail("a container backs more than one session — instances are being SHARED")
    else:
        print(f"  OK    {len(distinct)} distinct containers, none shared")

    live = httpx.get(f"{base_url}/healthz", timeout=15.0).json()
    report["active_after_mint"] = live["active"]
    if live["active"] > C.MAX_ACTIVE:
        fail(f"active={live['active']} exceeds MAX_ACTIVE={C.MAX_ACTIVE}")
    else:
        print(f"  OK    active={live['active']} <= MAX_ACTIVE={C.MAX_ACTIVE}")

    # A refusal is only legitimate at genuine saturation. Refusing while slots
    # are free is the failure mode that matters on launch day: the box sits idle
    # while visitors are told the demo is full.
    capacity_refusals = [m for m in refused if m.get("reason") == "capacity"]
    report["spurious_refusals"] = 0
    if capacity_refusals and live["active"] < C.MAX_ACTIVE:
        report["spurious_refusals"] = len(capacity_refusals)
        fail(
            f"{len(capacity_refusals)} mint(s) refused with reason='capacity' while "
            f"only {live['active']}/{C.MAX_ACTIVE} slots were in use — the warden "
            "must use free headroom before refusing (a burst larger than "
            f"POOL_SIZE={C.POOL_SIZE} must not read as saturation)"
        )
    elif capacity_refusals:
        print(f"  OK    {len(capacity_refusals)} capacity refusal(s), at genuine saturation")

    # ── drive real work, then measure ───────────────────────────────────────
    print(f"\ntranslating in {len(granted)} session(s)...")
    with ThreadPoolExecutor(max_workers=min(len(granted) or 1, 16)) as pool:
        results = list(pool.map(lambda m: translate(base_url, m["token"]), granted))
    ok = [r for r in results if r.get("ok")]
    rendered = [r for r in ok if r.get("renders")]
    print(f"  translated={len(ok)}/{len(granted)} rendered_output={len(rendered)}")
    report["translations_ok"] = len(ok)
    report["translations_rendered"] = len(rendered)
    if granted and not ok:
        fail("no translation succeeded — RSS below reflects IDLE instances, "
             "so it is NOT a valid sizing basis")
    if ok:
        durations = sorted(r["seconds"] for r in ok)
        report["translate_seconds"] = {"p50": durations[len(durations) // 2], "max": durations[-1]}
        print(f"  translate p50={report['translate_seconds']['p50']}s "
              f"max={report['translate_seconds']['max']}s")

    time.sleep(3)  # let RSS settle after the burst
    report_memory(report, distinct)

    # ── invariant: the control plane survives ───────────────────────────────
    killed = oom_killed()
    report["oom_killed"] = killed
    if killed:
        fail(f"OOM-killed control-plane container(s): {killed}")
    else:
        print("\n  OK    no OOM-kill of warden / shim / socket-proxy / caddy")

    # ── invariant: saturation fails closed ─────────────────────────────────
    if len(granted) >= C.MAX_ACTIVE:
        extra = mint(base_url, -1)
        report["saturation_status"] = extra["status"]
        if extra["status"] in (429, 503):
            print(f"  OK    at saturation the demo failed closed "
                  f"({extra['status']} {extra.get('reason')})")
        elif extra["status"] == 200:
            # Legitimate: the warden may reclaim a session older than the 120s
            # floor. It must still not exceed the cap or share an instance.
            after = httpx.get(f"{base_url}/healthz", timeout=15.0).json()
            if after["active"] > C.MAX_ACTIVE:
                fail("a mint past saturation pushed active over MAX_ACTIVE")
            else:
                print("  OK    mint past saturation reclaimed rather than shared")
            granted.append(extra)
        else:
            fail(f"unexpected saturation status {extra['status']}")
    else:
        print(f"\n  note  ran {len(granted)} < MAX_ACTIVE={C.MAX_ACTIVE}; "
              "the saturation invariant was NOT exercised")
        report["saturation_status"] = None

    # ── invariant: a closed tab frees its slot within the SLO ───────────────
    if granted:
        victim = granted[0]
        before = httpx.get(f"{base_url}/healthz", timeout=15.0).json()["active"]
        httpx.post(f"{base_url}/session/{victim['token']}/end", timeout=30.0)
        freed_at = None
        for elapsed in range(slo_seconds + 1):
            if httpx.get(f"{base_url}/healthz", timeout=15.0).json()["active"] < before:
                freed_at = elapsed
                break
            time.sleep(1)
        report["slot_freed_seconds"] = freed_at
        if freed_at is None:
            fail(f"slot not freed within the {slo_seconds}s SLO")
        else:
            print(f"  OK    slot freed in {freed_at}s (SLO {slo_seconds}s)")

    # ── clean up every session we opened ───────────────────────────────────
    print("\nreleasing sessions...")
    for record in granted:
        try:
            httpx.post(f"{base_url}/session/{record['token']}/end", timeout=30.0)
        except httpx.HTTPError:
            pass
    final = httpx.get(f"{base_url}/healthz", timeout=15.0).json()
    report["active_after_cleanup"] = final["active"]
    print(f"  active={final['active']} (pool={final['pool']})")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8098",
                        help="warden base URL (default: %(default)s)")
    parser.add_argument("--sessions", type=int, default=C.MAX_ACTIVE,
                        help="concurrent sessions to open (default: MAX_ACTIVE=%(default)s)")
    parser.add_argument("--slo-seconds", type=int, default=90,
                        help="capacity SLO for freeing a closed tab's slot (default: %(default)s)")
    parser.add_argument("--json", type=str, default=None,
                        help="also write the report as JSON to this path")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    print(f"load-sanity against {base_url}\n" + "=" * 60)
    try:
        report = run(base_url, args.sessions, args.slo_seconds)
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"\nABORTED: {exc}")
        print("Is the stack up with the warden published? See `make smoke-up`.")
        return 2

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        print(f"\nwrote {args.json}")

    print("\n" + "=" * 60)
    if report["failures"]:
        print(f"LOAD SANITY FAILED — {len(report['failures'])} invariant(s):")
        for message in report["failures"]:
            print(f"  - {message}")
        return 1
    print("LOAD SANITY OK — every capacity invariant held.")
    if report.get("projected_full_cap_mib"):
        print(f"Size the box off {report['projected_full_cap_mib']:.0f} MiB projected at "
              f"MAX_ACTIVE={C.MAX_ACTIVE}, plus host overhead — not off the "
              f"{C.INSTANCE_MEM_LIMIT} per-instance guardrail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
