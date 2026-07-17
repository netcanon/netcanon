"""Guard: every error status a route hand-raises is declared in OpenAPI (API-C4).

FastAPI auto-declares only the success code(s) plus ``422`` (when a route has
params).  Any ``raise HTTPException(status_code=N)`` a handler makes for a
``400``/``403``/``404``/``409``/``500``/``501`` is invisible to ``/docs`` and
generated clients unless the route decorator lists it in ``responses={}`` —
exactly the drift prior-#51 / HEAD-review API-C4 flagged across the CRUD
routers.

This pins the contract *structurally* rather than with a hand-maintained table:
it AST-parses each route's handler, collects every inline ``HTTPException``
status code, and asserts it appears in the generated schema's declared
responses.  A new handler that raises an undeclared code turns this red, so the
``responses={}`` map must be updated in the same change.  (Codes raised only in
a shared helper the handler *calls* are out of scope — declare those by hand.)
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap

import pytest
from starlette.routing import Route

from netcanon.main import create_app

pytestmark = pytest.mark.integration

# Success codes FastAPI declares from status_code=/response_model; a handler
# that also raises one of these (it doesn't, but be defensive) isn't an error
# gap.  422 is auto-declared for any route with params, so a hand-raised 422
# (e.g. an unknown type_key) is always already present.
_AUTO_CODES = frozenset({200, 201, 202, 204, 301, 302, 304, 307, 308, 422})


def _raised_status_codes(fn) -> set[int]:
    """Return every integer status code the function's source hand-raises via
    ``HTTPException(status_code=...)`` — literal ``404`` or ``status.HTTP_404_*``."""
    try:
        src = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return set()
    tree = ast.parse(src)
    codes: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "HTTPException":
            continue
        for kw in node.keywords:
            if kw.arg != "status_code":
                continue
            val = kw.value
            if isinstance(val, ast.Constant) and isinstance(val.value, int):
                codes.add(val.value)
            elif isinstance(val, ast.Attribute):  # status.HTTP_404_NOT_FOUND
                m = re.search(r"HTTP_(\d{3})", val.attr)
                if m:
                    codes.add(int(m.group(1)))
    return codes


def test_every_raised_status_is_declared_in_openapi():
    app = create_app()
    schema = app.openapi()
    gaps: list[str] = []
    for route in app.routes:
        if not isinstance(route, Route):
            continue
        for method in sorted(route.methods or set()):
            if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                continue
            op = schema["paths"].get(route.path, {}).get(method.lower(), {})
            declared = {
                int(c) for c in op.get("responses", {}) if str(c).isdigit()
            }
            raised = _raised_status_codes(route.endpoint)
            missing = {c for c in raised if c not in declared and c not in _AUTO_CODES}
            if missing:
                gaps.append(
                    f"{method} {route.path}: raises {sorted(missing)} but OpenAPI "
                    f"declares {sorted(declared)} — add them to the route's "
                    f"responses={{}} map (mirror _JOB_STATUS_RESPONSES)."
                )
    assert not gaps, "Undeclared error responses:\n" + "\n".join(gaps)
