"""The demo proxy's allowlist names routes the application serves.

The demo's warden passes only the paths listed in
``demo/warden/constants.py`` through to an instance.  Nothing tied
those lists to the application: an entry for a path that is no route
is inert, and a call the migrate page starts making without an entry
is refused at the warden -- in the demo only, where no test of the
application looks.  ``docs/demo-plan/04-container-hardening.md`` said
its copy of the list was "verified against the image route table";
this is that verification, run where a pull request runs.

It lives in the unit tier because ``tests/demo`` is not part of pull
request CI.  It reads the warden's constants only -- a module with no
dependency of its own -- and never starts the warden.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from demo.warden import constants as warden
from netcanon.main import create_app

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
HARDENING_DOC = REPO_ROOT / "docs" / "demo-plan" / "04-container-hardening.md"


@pytest.fixture(scope="module")
def routes() -> set[tuple[str, str]]:
    """``(method, path)`` of every route of the application."""
    return {
        (method, route.path)
        for route in create_app().routes
        for method in (getattr(route, "methods", None) or ())
    }


@pytest.mark.parametrize("path", sorted(warden.ALLOW_GET_EXACT))
def test_an_allowlisted_get_is_a_route(routes: set[tuple[str, str]], path: str) -> None:
    assert ("GET", path) in routes


@pytest.mark.parametrize("path", sorted(warden.ALLOW_POST_EXACT))
def test_an_allowlisted_post_is_a_route(routes: set[tuple[str, str]], path: str) -> None:
    assert ("POST", path) in routes


@pytest.mark.parametrize("prefix", warden.ALLOW_GET_PREFIX)
def test_an_allowlisted_prefix_has_a_route_under_it(
    routes: set[tuple[str, str]], prefix: str,
) -> None:
    assert any(method == "GET" and path.startswith(prefix) for method, path in routes)


def test_the_check_can_fail(routes: set[tuple[str, str]]) -> None:
    """A path that is no route is not found, and neither is a route
    asked for by the other method."""
    assert ("GET", "/api/v1/migration/no-such-route") not in routes
    assert ("GET", "/api/v1/migration/inventory") not in routes
    assert ("POST", "/api/v1/migration/model-families") not in routes


@pytest.mark.parametrize(
    "path", sorted(warden.ALLOW_GET_EXACT | warden.ALLOW_POST_EXACT),
)
def test_the_hardening_document_lists_it(path: str) -> None:
    """The document's ALLOW list is a second copy of the constants.
    Sub-plans are written there as a suffix of the plan route
    (``+ /plan/ports``), so the last two segments are what is looked
    for."""
    text = HARDENING_DOC.read_text(encoding="utf-8")
    tail = "/" + "/".join(path.strip("/").split("/")[-2:])
    assert path in text or tail in text, f"{path} is allowlisted and not in the document"
