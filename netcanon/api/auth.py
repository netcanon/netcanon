"""Optional API authentication + bind-safety guard (audit finding SEC-01).

Netcanon ships with **no** authentication by default: the desktop shell
binds ``127.0.0.1`` and web/Docker operators are told to front the app
with a reverse proxy.  That posture is documented in ``SECURITY.md``, but
the insecure ``0.0.0.0`` default makes accidental public exposure one
``docker run -p`` away.  This module adds two opt-in, fail-closed controls:

1. :func:`require_api_key` — when ``Settings.api_key`` (env
   ``NETCANON_API_KEY``) is set, every ``/api/v1`` route requires a
   matching ``Authorization: Bearer <key>`` header.  Empty key (the
   default) makes the dependency a no-op, so the zero-config loopback /
   desktop experience is unchanged.  Credentials stay write-only over the
   API (``DeviceProfilePublic``); this is an orthogonal front door, not a
   replacement for the reverse proxy.

2. :func:`bind_refusal_reason` — used by ``netcanon serve`` to refuse to
   start when binding a non-loopback interface with no API key and no
   explicit ``NETCANON_ALLOW_INSECURE_BIND`` opt-out, so the insecure path
   is a conscious choice rather than the default.
"""

from __future__ import annotations

import hmac
import ipaddress

from fastapi import HTTPException, Request, status

_LOOPBACK_NAMES = {"localhost"}


def require_api_key(request: Request) -> None:
    """FastAPI dependency: enforce the optional static bearer token.

    No-op when no key is configured.  Uses a constant-time compare so the
    response timing does not leak the key's length or prefix.
    """
    # Fail open when no settings/key is configured: auth is opt-in, and
    # minimal app fixtures (e.g. the sanitize-only test app) may not attach
    # ``state.settings`` at all — that means "no key", not a 500.
    settings = getattr(request.app.state, "settings", None)
    expected = (getattr(settings, "api_key", "") or "").strip()
    if not expected:
        return  # auth disabled — zero-config local UX preserved
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token.strip(), expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def is_loopback_host(host: str) -> bool:
    """True if *host* binds only the loopback interface.

    ``localhost`` and any loopback IP (``127.0.0.0/8``, ``::1``) are
    loopback; ``0.0.0.0`` / ``::`` (all interfaces) and real hostnames are
    not (a non-``localhost`` hostname can't be proven loopback, so it is
    treated as exposed — the safe default).
    """
    h = host.strip().lower()
    if h in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def bind_refusal_reason(
    host: str, api_key: str, allow_insecure_bind: bool
) -> str | None:
    """Return a refusal message if binding *host* is unsafe, else ``None``.

    Unsafe = a non-loopback bind with no API key and no explicit opt-out.
    """
    if is_loopback_host(host):
        return None
    if (api_key or "").strip():
        return None
    if allow_insecure_bind:
        return None
    return (
        f"Refusing to start: binding {host!r} exposes the API on a "
        "non-loopback interface with no authentication. Set "
        "NETCANON_API_KEY=<token> to require a bearer token on /api/v1, or "
        "set NETCANON_ALLOW_INSECURE_BIND=1 to acknowledge an "
        "unauthenticated bind (e.g. behind a reverse proxy that terminates "
        "auth). See SECURITY.md."
    )
