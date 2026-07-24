"""Create-body authz shim — the Trusted Computing Base gate on ``create``.

Sits between the warden and the docker-socket-proxy::

    warden --DOCKER_HOST--> authz-shim --> socket-proxy (verb allowlist) --> docker.sock

The socket-proxy allowlists *verbs*; this shim enforces a **whole-body
default-deny** on every ``POST .../containers/create``.

⚠️ Validation is a POSITIVE allowlist, case-folded. The Docker daemon decodes
the create body with Go's ``encoding/json``, which matches struct fields
**case-insensitively** — so a case-sensitive Python *denylist* (``hc.get("Binds")``)
let lowercase ``binds`` / ``privileged`` / ``capadd`` smuggle host root straight
past it while the daemon still honoured them. We instead fold every key to lower
case and reject any key not in the allowlist (in any case), pin the
security-critical HostConfig values, and drop top-level ``networkingconfig``
(an extra-network attach would breach isolation). We also deny every POST that is
not ``create``/``start`` (the warden never pulls images, exec's, or commits).

Counted in the TCB. Keep it tiny and auditable.
"""

from __future__ import annotations

import json
import os
import re

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import constants as C

# The socket-proxy that enforces the coarse verb allowlist.
UPSTREAM = os.environ.get("DOCKER_SOCKET_PROXY", "http://socket-proxy:2375").rstrip("/")

_CREATE_RE = re.compile(r"^/(v[0-9.]+/)?containers/create$")
_START_RE = re.compile(r"^/(v[0-9.]+/)?containers/[^/]+/start$")

# Top-level create-body keys docker-py legitimately sends. EXCLUDES
# networkingconfig on purpose (attaching an extra network = isolation breach).
# Any unlisted key (in any case) is rejected; a false-reject fails CLOSED (the
# demo won't launch) and is caught by the Gate-1 positive-path test.
_ALLOWED_TOP = frozenset(
    {
        "image", "labels", "env", "hostconfig", "hostname", "domainname", "user",
        "attachstdin", "attachstdout", "attachstderr", "tty", "openstdin",
        "stdinonce", "cmd", "entrypoint", "workingdir", "volumes", "exposedports",
        "stopsignal", "stoptimeout", "healthcheck", "networkdisabled",
        "macaddress", "onbuild", "shell", "argsescaped",
    }
)
_ALLOWED_HOSTCONFIG = frozenset(
    {
        "readonlyrootfs", "tmpfs", "networkmode", "memory", "memoryswap",
        "nanocpus", "pidslimit", "capdrop", "securityopt", "logconfig",
    }
)


def _fold(d: object) -> dict:
    """Lower-case one dict level. Last-wins on collision, matching Go's
    duplicate-key semantics, so our validated view and the daemon's decoded view
    resolve to the same object."""
    if not isinstance(d, dict):
        return {}
    out: dict = {}
    for k, v in d.items():
        out[k.lower() if isinstance(k, str) else k] = v
    return out


def validate_create_body(body: object) -> str | None:
    """Return ``None`` if *body* is exactly a hardened instance, else a reason."""
    if not isinstance(body, dict):
        return "create body is not a JSON object"
    top = _fold(body)
    extra = set(top) - _ALLOWED_TOP
    if extra:
        return f"unexpected top-level key(s): {sorted(extra)}"
    if top.get("image") != C.INSTANCE_IMAGE:
        return "Image is not the pinned digest"
    hc = _fold(top.get("hostconfig") or {})
    if not hc:
        return "missing HostConfig"
    extra_hc = set(hc) - _ALLOWED_HOSTCONFIG
    if extra_hc:
        return f"forbidden HostConfig key(s): {sorted(extra_hc)}"
    if hc.get("readonlyrootfs") is not True:
        return "HostConfig.ReadonlyRootfs must be true"
    if hc.get("networkmode") != C.INSTANCE_NETWORK:
        return "HostConfig.NetworkMode must be the internal demo network"
    mem, swap = hc.get("memory"), hc.get("memoryswap")
    if not mem or mem != swap:
        return "HostConfig.Memory must be set and equal MemorySwap (no swap)"
    if not hc.get("pidslimit"):
        return "HostConfig.PidsLimit must be set"
    if "ALL" not in [str(c).upper() for c in (hc.get("capdrop") or [])]:
        return "HostConfig.CapDrop must include ALL"
    if [str(s).lower() for s in (hc.get("securityopt") or [])] != ["no-new-privileges:true"]:
        return "HostConfig.SecurityOpt must be exactly [no-new-privileges:true]"
    if _fold(hc.get("logconfig") or {}).get("type") not in (None, "none"):
        return "HostConfig.LogConfig.Type must be none"
    return None


async def _forward(request: Request, body: bytes | None = None) -> Response:
    """Proxy the request through to the socket-proxy."""
    url = f"{UPSTREAM}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
        content = body if body is not None else await request.body()
        upstream = await client.request(request.method, url, headers=headers, content=content)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers={
                k: v for k, v in upstream.headers.items()
                if k.lower() not in ("transfer-encoding", "connection", "content-encoding")
            },
        )


async def _handle(request: Request) -> Response:
    method = request.method
    path = request.url.path
    if method == "POST":
        if _CREATE_RE.match(path):
            raw = await request.body()
            try:
                body = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return JSONResponse({"message": "authz-shim: create body is not JSON"}, status_code=400)
            reason = validate_create_body(body)
            if reason is not None:
                return JSONResponse({"message": f"authz-shim: create refused ({reason})"}, status_code=403)
            return await _forward(request, body=raw)
        if _START_RE.match(path):
            return await _forward(request)
        # Deny every other POST — image pull (/images/create), exec, commit, … —
        # which the warden never issues. Defense-in-depth beyond the socket-proxy.
        return JSONResponse({"message": "authz-shim: POST not allowed on this path"}, status_code=403)
    return await _forward(request)


app = Starlette(
    routes=[Route("/{path:path}", _handle, methods=["GET", "POST", "PUT", "DELETE", "HEAD"])]
)
