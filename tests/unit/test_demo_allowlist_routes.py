"""The demo proxy's allowlist names paths the application answers on.

The demo's warden passes only the paths listed in
``demo/warden/constants.py`` through to an instance.  Nothing tied
those lists to the application: an entry for a path the application
does not serve is inert, and a call the migrate page starts making
without an entry is refused at the warden -- in the demo only, where no
test of the application looks.  ``docs/demo-plan/04-container-hardening.md``
said its copy of the list was "verified against the image route table";
this is that verification, run where a pull request runs.

It ASKS the application rather than reading its route table: how a
framework holds its routes is its own business and changes between its
releases (a first version of this test read ``app.routes`` and saw one
route on the version CI installs).  A path the application does not
serve answers 404, and one it serves by another method answers 405.

It lives in the unit tier because ``tests/demo`` is not part of pull
request CI.  It reads the warden's constants only -- a module with no
dependency of its own -- and never starts the warden.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from demo.warden import constants as warden
from netcanon.config import Settings
from netcanon.main import create_app

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
HARDENING_DOC = REPO_ROOT / "docs" / "demo-plan" / "04-container-hardening.md"

#: Not a route: no such path, or not by that method.
NOT_SERVED = (404, 405)

#: One real path under each allowlisted prefix.  A prefix added to the
#: warden fails here until it is given one.
EXAMPLE_UNDER = {
    "/api/v1/migration/adapters/": "/api/v1/migration/adapters/aruba_aoss/capabilities",
    "/api/v1/migration/target-profiles/": "/api/v1/migration/target-profiles/aruba_aoss/2930F-48G",
}


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """The application with its shipped definitions and an empty store,
    on directories of its own."""
    root = tmp_path_factory.mktemp("allowlist")
    (root / "configs").mkdir()
    settings = Settings(configs_dir=root / "configs", data_dir=root)
    with TestClient(create_app(settings)) as running:
        yield running


@pytest.mark.parametrize("path", sorted(warden.ALLOW_GET_EXACT))
def test_an_allowlisted_get_is_served(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", sorted(warden.ALLOW_POST_EXACT))
def test_an_allowlisted_post_is_served(client: TestClient, path: str) -> None:
    """An empty body is refused as a body (422), which is the route
    answering; what matters is that it is not "no such route"."""
    assert client.post(path, json={}).status_code not in NOT_SERVED


def test_every_allowlisted_prefix_has_an_example() -> None:
    assert set(EXAMPLE_UNDER) == set(warden.ALLOW_GET_PREFIX)
    for prefix, path in EXAMPLE_UNDER.items():
        assert path.startswith(prefix) and warden.route_allowed("GET", path)


@pytest.mark.parametrize("prefix", sorted(EXAMPLE_UNDER))
def test_an_allowlisted_prefix_has_a_route_under_it(client: TestClient, prefix: str) -> None:
    assert client.get(EXAMPLE_UNDER[prefix]).status_code == 200


def test_the_check_can_fail(client: TestClient) -> None:
    """A path that is no route is not served, and neither is a route
    asked for by the other method."""
    assert client.get("/api/v1/migration/no-such-route").status_code == 404
    assert client.post("/api/v1/migration/no-such-route", json={}).status_code in NOT_SERVED
    assert client.get("/api/v1/migration/inventory").status_code == 405
    assert client.post("/api/v1/migration/model-families", json={}).status_code == 405


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
