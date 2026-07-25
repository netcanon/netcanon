"""Live-stack smoke: the module-08 ``[O]`` rows that need a real Docker daemon.

The in-process suite (``test_warden_*.py``) proves the warden's logic and the
spec it *requests*. It cannot prove dockerd **applied** that spec, that
``demo-int`` really has no egress, or that the socket-proxy and authz shim
actually intercept on the wire. Those are the claims a skeptical reader cares
most about, and they are exactly what this file checks — by shelling out to the
same ``docker`` commands ``deploy/VERIFY.md`` documents, so the runbook and the
test cannot drift into different claims.

**Opt-in.** Skipped unless ``NETCANON_DEMO_SMOKE=1``, because PR CI has no demo
stack. Three commands from ``deploy/`` (see the Makefile)::

    cp demo.env.example demo.env        # plain tags are fine for local dev
    make smoke-up                       # dev stack + the warden port published
    make smoke                          # this suite
    make smoke-down                     # removes instances first, then the stack

``docker-compose.smoke.yml`` is what publishes the warden on 127.0.0.1:8098;
production publishes only Caddy. Instances must be removed before the stack
comes down or ``demo-int`` refuses to go (it still has endpoints attached) —
``make smoke-down`` does that in the right order.

Override the defaults with ``NETCANON_DEMO_BASE_URL`` (default
``http://127.0.0.1:8098``) and ``NETCANON_DEMO_NETWORK`` (default ``demo-int``).

**Not covered here — Gate 3, on the real Linux host.** The nftables isolation
rules (warden→instance ALLOW, instance→instance DENY, instance→warden DENY, I4)
live in the host's ``DOCKER-USER`` chain and cannot be exercised on Docker
Desktop, which runs dockerd inside a VM. Those tests are declared below and
skip explicitly rather than being silently omitted — an unlisted proof reads as
a passing one.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import httpx
import pytest

from demo.warden import constants as C

SMOKE_ENABLED = os.environ.get("NETCANON_DEMO_SMOKE") == "1"
BASE_URL = os.environ.get("NETCANON_DEMO_BASE_URL", "http://127.0.0.1:8098").rstrip("/")
INSTANCE_NETWORK = os.environ.get("NETCANON_DEMO_NETWORK", "demo-int")
# Docker Desktop cannot exercise host-level nftables (dockerd lives in a VM).
HOST_NFTABLES = os.environ.get("NETCANON_DEMO_HOST_NFTABLES") == "1"

pytestmark = [
    pytest.mark.demo_live,
    pytest.mark.skipif(
        not SMOKE_ENABLED,
        reason="needs a running demo stack; set NETCANON_DEMO_SMOKE=1 (see module docstring)",
    ),
]


# ── docker helpers (the CLI, so the test runs what VERIFY.md documents) ───────
def docker(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=120
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"docker {' '.join(args)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def inspect(target: str) -> dict:
    return json.loads(docker("inspect", target))[0]


def container_for_instance(instance_id: str) -> str:
    """Map the warden's public display id to a container via its label."""
    cid = docker("ps", "-q", "--filter", f"label={C.LABEL_INSTANCE}={instance_id}")
    assert cid, f"no running container labelled {C.LABEL_INSTANCE}={instance_id}"
    return cid.splitlines()[0]


def find_container(name_fragment: str) -> str:
    cid = docker("ps", "-q", "--filter", f"name={name_fragment}")
    assert cid, f"no running container matching name~{name_fragment!r}"
    return cid.splitlines()[0]


def exec_python(container: str, code: str) -> tuple[int, str]:
    """Run python inside a container via the RAW host socket.

    The warden's own allowlist forbids ``exec`` by design; this is the operator
    path VERIFY.md proof 13 uses. Both the instance and the warden images are
    python-based, so no extra image has to be pulled.
    """
    result = subprocess.run(
        ["docker", "exec", container, "python", "-c", code],
        capture_output=True, text=True, timeout=60,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


# ── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def stack() -> dict:
    """Confirm the stack is reachable before any assertion runs."""
    try:
        health = httpx.get(f"{BASE_URL}/healthz", timeout=10.0)
    except httpx.HTTPError as exc:  # pragma: no cover - environment problem
        pytest.fail(
            f"cannot reach the warden at {BASE_URL} ({exc}). Is the stack up and the "
            "warden port published? See the module docstring."
        )
    assert health.status_code == 200, health.text
    return health.json()


@pytest.fixture(scope="module")
def session(stack) -> dict:
    """Mint one real session; destroy it on teardown."""
    response = httpx.post(f"{BASE_URL}/session/new", timeout=60.0)
    assert response.status_code == 200, f"mint failed: {response.status_code} {response.text}"
    payload = response.json()
    payload["container"] = container_for_instance(payload["instance_id"])
    yield payload
    httpx.post(f"{BASE_URL}/session/{payload['token']}/end", timeout=30.0)


# ── Claim 2: the instance cannot write to disk (VERIFY.md proof 2) ───────────
def test_rootfs_is_read_only_as_applied(session):
    assert inspect(session["container"])["HostConfig"]["ReadonlyRootfs"] is True


def test_every_mount_is_tmpfs(session):
    """Not "the warden asked for tmpfs" — what dockerd actually mounted."""
    mounts = inspect(session["container"])["Mounts"]
    non_tmpfs = [m for m in mounts if m.get("Type") != "tmpfs"]
    assert not non_tmpfs, f"instance has non-tmpfs mounts: {non_tmpfs}"


def test_both_declared_volume_paths_are_tmpfs_as_applied(session):
    """The anonymous-volume trap: the image declares VOLUME for /app/data AND
    /app/configs, so a missed tmpfs becomes a persistent host-disk volume."""
    tmpfs = inspect(session["container"])["HostConfig"]["Tmpfs"] or {}
    for path in ("/app/data", "/app/configs", "/tmp"):
        assert path in tmpfs, f"{path} is not tmpfs in the RUNNING container"


def test_container_filesystem_diff_is_confined_to_tmpfs(session):
    """`docker diff` shows nothing written to the container's own layer."""
    diff = docker("diff", session["container"])
    stray = [
        line for line in diff.splitlines()
        if line and not any(
            line[2:].startswith(p) for p in ("/tmp", "/app/data", "/app/configs", "/run", "/var")
        )
    ]
    assert not stray, f"writes outside tmpfs paths: {stray}"


def test_instance_runs_as_non_root_uid_1000(session):
    code, out = exec_python(session["container"], "import os; print(os.getuid())")
    assert code == 0, out
    assert out.strip() == "1000", f"expected uid 1000 (USER app), got {out!r}"


# ── Claim 5: RAM contents cannot reach disk ─────────────────────────────────
def test_memory_and_swap_limits_are_equal_as_applied(session):
    host_config = inspect(session["container"])["HostConfig"]
    assert host_config["Memory"] > 0
    assert host_config["Memory"] == host_config["MemorySwap"], (
        "MemorySwap must equal Memory — otherwise the instance may swap to disk"
    )


# ── Privilege (the flags the authz shim pins) ────────────────────────────────
def test_all_capabilities_dropped_as_applied(session):
    host_config = inspect(session["container"])["HostConfig"]
    assert host_config["CapDrop"] == ["ALL"]
    assert not host_config.get("CapAdd")
    assert host_config["Privileged"] is False


def test_no_new_privileges_as_applied(session):
    security_opt = inspect(session["container"])["HostConfig"]["SecurityOpt"] or []
    assert "no-new-privileges:true" in security_opt


def test_cpu_and_pid_limits_as_applied(session):
    host_config = inspect(session["container"])["HostConfig"]
    assert host_config["NanoCpus"] == C.INSTANCE_NANO_CPUS
    assert host_config["PidsLimit"] == C.INSTANCE_PIDS_LIMIT


# ── Claim 4: the paste appears in no log ────────────────────────────────────
def test_instance_log_driver_is_none_as_applied(session):
    assert inspect(session["container"])["HostConfig"]["LogConfig"]["Type"] == "none"


def test_instance_produces_no_captured_logs(session):
    """With driver `none` the daemon keeps nothing, so `docker logs` must fail
    or be empty — there is no buffer for a pasted config to sit in."""
    result = subprocess.run(
        ["docker", "logs", session["container"]],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0 or not result.stdout.strip(), (
        f"log driver 'none' should retain nothing, got: {result.stdout[:200]!r}"
    )


# ── Claim 6: the instance can't phone anywhere (VERIFY.md proof 4) ───────────
def test_instance_network_is_internal(session):
    """`internal: true` is what removes the default gateway from the bridge."""
    network = json.loads(docker("network", "inspect", INSTANCE_NETWORK))[0]
    assert network["Internal"] is True, f"{INSTANCE_NETWORK} is not an internal network"


def test_instance_has_no_egress(session):
    """The strongest single claim: from inside the instance, the internet is
    unreachable at the network layer."""
    code, out = exec_python(
        session["container"],
        "import socket;\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 443), timeout=4); print('REACHED')\n"
        "except OSError as e:\n"
        "    print('BLOCKED', e)\n",
    )
    assert code == 0, out
    assert "REACHED" not in out, f"instance reached the internet: {out}"
    assert "BLOCKED" in out, out


def test_instance_cannot_resolve_dns(session):
    code, out = exec_python(
        session["container"],
        "import socket;\n"
        "try:\n"
        "    print('RESOLVED', socket.gethostbyname('example.com'))\n"
        "except OSError as e:\n"
        "    print('BLOCKED', e)\n",
    )
    assert code == 0, out
    assert "RESOLVED" not in out, f"instance resolved a public name: {out}"


# ── The warden proxy: header rewrite + route allowlist ───────────────────────
def test_proxied_response_has_xfo_stripped_and_csp_rewritten(session):
    """VERIFY.md proof 9. netcanon stamps XFO:DENY + frame-ancestors 'none' on
    every response; without this rewrite the demo iframe renders blank."""
    response = httpx.get(f"{BASE_URL}/i/{session['token']}/migrate", timeout=60.0)
    assert response.status_code == 200, response.text
    assert "x-frame-options" not in {k.lower() for k in response.headers}
    csp = response.headers.get("content-security-policy", "")
    assert "frame-ancestors 'self'" in csp, f"CSP not rewritten: {csp!r}"
    assert "frame-ancestors 'none'" not in csp


@pytest.mark.parametrize(
    "path",
    ["api/v1/backups", "api/v1/devices", "api/v1/configs", "docs", "jobs", ""],
    ids=["backups", "devices", "configs", "docs", "jobs", "bare-instance-root"],
)
def test_blocked_routes_404_at_the_warden(session, path):
    """The instance still serves these; the warden must not proxy them. The bare
    root is the backup DASHBOARD — the most important one to keep unreachable."""
    response = httpx.get(f"{BASE_URL}/i/{session['token']}/{path}", timeout=30.0)
    assert response.status_code == 404, f"/{path} returned {response.status_code}"


def test_cookie_routing_reaches_the_instance(session):
    """Absolute app paths route by the nc_route cookie (netcanon's UI uses
    absolute URLs). Set the header directly: the cookie is Secure, so a client
    jar would refuse to send it over plain http to a local port."""
    response = httpx.get(
        f"{BASE_URL}/migrate",
        headers={"Cookie": f"{C.ROUTE_COOKIE}={session['token']}"},
        timeout=60.0,
    )
    assert response.status_code == 200, response.text


def test_a_dead_token_404s_everywhere(stack):
    """VERIFY.md proof 5: end a session, and its token is inert."""
    minted = httpx.post(f"{BASE_URL}/session/new", timeout=60.0)
    assert minted.status_code == 200, minted.text
    token = minted.json()["token"]
    assert httpx.get(f"{BASE_URL}/i/{token}/migrate", timeout=60.0).status_code == 200

    assert httpx.post(f"{BASE_URL}/session/{token}/end", timeout=30.0).status_code == 204

    assert httpx.get(f"{BASE_URL}/i/{token}/migrate", timeout=30.0).status_code == 404
    assert httpx.post(f"{BASE_URL}/session/{token}/hb", json={"hidden": False},
                      timeout=30.0).status_code == 404


# ── Claim 1/3: teardown really removes the container + any volume ────────────
def test_destroy_removes_the_container_and_leaves_no_volume(stack):
    """VERIFY.md proofs 1 and 10."""
    volumes_before = set(docker("volume", "ls", "-q").splitlines())

    minted = httpx.post(f"{BASE_URL}/session/new", timeout=60.0).json()
    container = container_for_instance(minted["instance_id"])
    httpx.post(f"{BASE_URL}/session/{minted['token']}/end", timeout=30.0)

    for _ in range(30):
        if not docker("ps", "-aq", "--filter", f"id={container}"):
            break
        time.sleep(1)
    assert not docker("ps", "-aq", "--filter", f"id={container}"), (
        "container still present after end — teardown must remove(force=True)"
    )
    assert set(docker("volume", "ls", "-q").splitlines()) <= volumes_before, (
        "an anonymous volume outlived the instance"
    )


# ── The TCB gates, live on the wire ─────────────────────────────────────────
def test_authz_shim_rejects_a_tampered_create_body():
    """The highest-value live assertion: the shim intercepts on the WIRE, not
    just in unit tests. Sent from inside the warden container, which is the only
    thing that can reach the shim (warden-sock is internal)."""
    warden = find_container("warden")
    code, out = exec_python(
        warden,
        "import httpx, json;\n"
        "body = {'Image': 'alpine', 'HostConfig': {'Binds': ['/:/hostfs'], 'Privileged': True}};\n"
        "r = httpx.post('http://authz-shim:2375/v1.43/containers/create',\n"
        "               json=body, timeout=20.0);\n"
        "print(r.status_code, r.text[:200])\n",
    )
    assert code == 0, out
    assert out.startswith("403"), f"shim did not refuse a host-mount create: {out}"


def test_socket_proxy_denies_verbs_outside_the_allowlist():
    """NETWORKS/VOLUMES/EXEC are 0 in the compose env; prove the proxy enforces
    it rather than merely declaring it."""
    warden = find_container("warden")
    code, out = exec_python(
        warden,
        "import httpx;\n"
        "for path in ('/v1.43/networks', '/v1.43/volumes', '/v1.43/info'):\n"
        "    try:\n"
        "        r = httpx.get('http://socket-proxy:2375' + path, timeout=20.0)\n"
        "        print(path, r.status_code)\n"
        "    except Exception as e:\n"
        "        print(path, 'ERR', type(e).__name__)\n",
    )
    assert code == 0, out
    for line in out.splitlines():
        assert " 200" not in line, f"socket-proxy allowed a denied section: {line}"


def test_instances_cannot_reach_the_socket_proxy(session):
    """Unreachable by construction: the socket-proxy sits on warden-sock only,
    a network no instance ever joins."""
    code, out = exec_python(
        session["container"],
        "import socket;\n"
        "try:\n"
        "    socket.create_connection(('socket-proxy', 2375), timeout=4); print('REACHED')\n"
        "except OSError as e:\n"
        "    print('BLOCKED', e)\n",
    )
    assert code == 0, out
    assert "REACHED" not in out, f"an instance reached the Docker control plane: {out}"


# ── Claim 7: the Fernet key lives only in RAM (VERIFY.md proof 13) ───────────
def test_fernet_key_is_in_env_and_no_key_file_exists(session):
    env = inspect(session["container"])["Config"]["Env"]
    fernet = [e for e in env if e.startswith("NETCANON_FERNET_KEY=")]
    assert fernet, "no NETCANON_FERNET_KEY injected — netcanon would fall back to a key FILE"
    assert len(fernet[0].split("=", 1)[1]) >= 43, "injected key is not a 256-bit Fernet key"

    code, out = exec_python(
        session["container"],
        "import os; print('EXISTS' if os.path.exists('/app/data/.fernet_key') else 'ABSENT')",
    )
    assert code == 0, out
    assert "ABSENT" in out, "a Fernet key file was written to disk"


# ── Gate 3: host nftables — declared, and skipped honestly ──────────────────
@pytest.mark.skipif(
    not HOST_NFTABLES,
    reason=(
        "I4 nftables isolation lives in the host DOCKER-USER chain and cannot be "
        "exercised on Docker Desktop (dockerd runs in a VM). Run on the real Linux "
        "host with NETCANON_DEMO_HOST_NFTABLES=1 — Gate 3."
    ),
)
def test_instance_cannot_reach_a_sibling_instance(stack):
    """warden→instance ALLOW, instance→instance DENY (I4)."""
    first = httpx.post(f"{BASE_URL}/session/new", timeout=60.0).json()
    second = httpx.post(f"{BASE_URL}/session/new", timeout=60.0).json()
    try:
        sibling_ip = inspect(container_for_instance(second["instance_id"]))[
            "NetworkSettings"]["Networks"][INSTANCE_NETWORK]["IPAddress"]
        code, out = exec_python(
            container_for_instance(first["instance_id"]),
            "import socket;\n"
            f"try:\n"
            f"    socket.create_connection(('{sibling_ip}', {C.INSTANCE_PORT}), timeout=4)\n"
            f"    print('REACHED')\n"
            "except OSError as e:\n"
            "    print('BLOCKED', e)\n",
        )
        assert code == 0, out
        assert "REACHED" not in out, f"instance-to-instance traffic is not blocked: {out}"
    finally:
        for minted in (first, second):
            httpx.post(f"{BASE_URL}/session/{minted['token']}/end", timeout=30.0)


@pytest.mark.skipif(
    not HOST_NFTABLES,
    reason="instance→warden DENY is a host-nftables rule — Gate 3 on the Linux host",
)
def test_instance_cannot_reach_the_warden_api(session):
    """instance→warden DENY: a compromised instance must not mint or end sessions."""
    code, out = exec_python(
        session["container"],
        "import socket;\n"
        "try:\n"
        "    socket.create_connection(('172.31.0.2', 8080), timeout=4); print('REACHED')\n"
        "except OSError as e:\n"
        "    print('BLOCKED', e)\n",
    )
    assert code == 0, out
    assert "REACHED" not in out, f"an instance reached the warden API: {out}"
