"""
Integration-test fixtures.

These fixtures build on the root ``tests/conftest.py`` fixtures to provide a
``TestClient`` connected to a fully initialised FastAPI application.  SSH
collection is mocked by patching ``get_collector`` before any request is made.

Because FastAPI's ``TestClient`` runs ``BackgroundTasks`` synchronously
(before returning the response), integration tests see a *completed* backup
job immediately after ``POST /api/v1/backups`` — no polling required.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CISCO_FAKE_OUTPUT, FakeCollector


@pytest.fixture()
def client(test_app) -> TestClient:
    """``TestClient`` with SSH collection replaced by ``FakeCollector``.

    The patch target is ``netcanon.api.routes.backups.get_collector`` — the
    exact location imported and called by the backup route.  The patch returns
    a ``FakeCollector`` for every ``get_collector(definition)`` call, regardless
    of the definition's strategy or type_key.

    The ``TestClient`` is used as a context manager so the app lifespan runs
    (loading definitions, creating the FileConfigStore) before the first
    request and tears down cleanly after the last.
    """
    fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
    with patch(
        "netcanon.api.routes.backups.get_collector",
        return_value=fake,
    ):
        with TestClient(test_app, raise_server_exceptions=True) as c:
            yield c
