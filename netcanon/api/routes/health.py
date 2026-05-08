"""``/health`` — lightweight readiness probe.

Used by container orchestrators (Docker ``HEALTHCHECK``, Kubernetes
liveness / readiness probes, GHA / CI smoke-tests) to verify the
server is responsive.

The endpoint is deliberately cheap — no DB hits, no codec
instantiation, no disk I/O.  Returns immediately with a static
JSON payload + the running package version.

Exposed at ``/health`` (no ``/api/v1`` prefix) per convention —
container HEALTHCHECK directives, k8s probes, and CDN /
load-balancer health configurations all default to that path.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

router = APIRouter()

try:
    _VERSION = version("netcanon")
except PackageNotFoundError:
    # Editable install or non-installed source tree — fall back to
    # an obvious sentinel rather than crashing the probe.
    _VERSION = "unknown"


@router.get(
    "/health",
    summary="Readiness probe",
    description=(
        "Returns `{\"status\": \"ok\", \"version\": \"<package version>\"}`.  "
        "Used by Docker `HEALTHCHECK` and container orchestrators.  "
        "Cheap by design: no DB hits, no codec instantiation, no disk I/O."
    ),
    tags=["health"],
)
async def get_health() -> dict[str, str]:
    return {"status": "ok", "version": _VERSION}
