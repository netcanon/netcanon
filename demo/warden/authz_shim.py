"""Create-body authz shim — the Trusted Computing Base gate on ``create``.

Sits between the warden and the docker-socket-proxy::

    warden --DOCKER_HOST--> authz-shim --> socket-proxy (verb allowlist) --> docker.sock

The socket-proxy allowlists *verbs* (create / start / list / inspect / remove)
but cannot inspect a create *body*.  This shim enforces a **whole-body
default-deny** on every ``POST .../containers/create``: the body may only be the
canonical hardened-instance spec (``constants.build_instance_create_kwargs``).
Any privilege-escalation field is rejected outright, so ``Binds:["/:/host"]``,
``Privileged:true`` and ``CapAdd:["SYS_ADMIN"]`` are impossible even though the
verb filter alone would pass them.  Everything else is streamed through
unmodified.

Counted in the TCB (``docs/demo-plan/03-warden-spec.md`` — Security posture).
Keep it tiny and auditable.
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

# The socket-proxy that enforces the verb allowlist (create/start/list/inspect/remove).
UPSTREAM = os.environ.get("DOCKER_SOCKET_PROXY", "http://socket-proxy:2375").rstrip("/")

_CREATE_RE = re.compile(r"^/(v[0-9.]+/)?containers/create$")

# HostConfig keys that grant host access / privilege escalation — a create body
# carrying ANY of them (truthy) is refused.  Default-deny is load-bearing: pinning
# only the fields we know about would still pass a body that keeps them canonical
# yet ADDS one of these.
_FORBIDDEN_HOSTCONFIG = (
    "Privileged", "CapAdd", "Devices", "DeviceCgroupRules", "DeviceRequests",
    "Binds", "Mounts", "VolumesFrom", "PidMode", "IpcMode", "UTSMode",
    "UsernsMode", "CgroupParent", "Sysctls", "Runtime", "Capabilities",
)


def validate_create_body(body: object) -> str | None:
    """Return ``None`` if *body* is an allowed hardened instance, else a reason."""
    if not isinstance(body, dict):
        return "create body is not a JSON object"
    if body.get("Image") != C.INSTANCE_IMAGE:
        return "Image is not the pinned digest"
    if body.get("Privileged"):
        return "Privileged (top-level)"
    hc = body.get("HostConfig")
    if not isinstance(hc, dict):
        return "missing HostConfig"
    for k in _FORBIDDEN_HOSTCONFIG:
        if hc.get(k):
            return f"forbidden HostConfig.{k}"
    if hc.get("ReadonlyRootfs") is not True:
        return "HostConfig.ReadonlyRootfs must be true"
    if hc.get("NetworkMode") != C.INSTANCE_NETWORK:
        return "HostConfig.NetworkMode must be the internal demo network"
    mem, swap = hc.get("Memory"), hc.get("MemorySwap")
    if not mem or mem != swap:
        return "HostConfig.Memory must be set and equal MemorySwap (no swap)"
    if not hc.get("PidsLimit"):
        return "HostConfig.PidsLimit must be set"
    caps = [str(c).upper() for c in (hc.get("CapDrop") or [])]
    if "ALL" not in caps:
        return "HostConfig.CapDrop must include ALL"
    if not any("no-new-privileges" in str(s) for s in (hc.get("SecurityOpt") or [])):
        return "HostConfig.SecurityOpt must include no-new-privileges"
    if (hc.get("LogConfig") or {}).get("Type") not in (None, "none"):
        return "HostConfig.LogConfig.Type must be none"
    binds = hc.get("Binds")
    if binds:
        return "HostConfig.Binds is forbidden"
    return None


async def _forward(request: Request, body: bytes | None = None) -> Response:
    """Stream the request through to the socket-proxy (bodyless GET/streamed)."""
    url = f"{UPSTREAM}{request.url.path}"
    if request.url.query:
        url += f"?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
        content = body if body is not None else await request.body()
        upstream = await client.request(
            request.method, url, headers=headers, content=content
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers={
                k: v for k, v in upstream.headers.items()
                if k.lower() not in ("transfer-encoding", "connection")
            },
        )


async def _handle(request: Request) -> Response:
    path = request.url.path
    if request.method == "POST" and _CREATE_RE.match(path):
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return JSONResponse({"message": "authz-shim: create body is not JSON"}, status_code=400)
        reason = validate_create_body(body)
        if reason is not None:
            # Do NOT echo the body (could carry a pasted secret in a future misuse).
            return JSONResponse(
                {"message": f"authz-shim: create refused ({reason})"}, status_code=403
            )
        return await _forward(request, body=raw)
    return await _forward(request)


app = Starlette(
    routes=[Route("/{path:path}", _handle, methods=["GET", "POST", "PUT", "DELETE", "HEAD"])]
)
