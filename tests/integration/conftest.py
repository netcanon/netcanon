"""
Integration-test fixtures.

These fixtures build on the root ``tests/conftest.py`` fixtures to provide a
``TestClient`` connected to a fully initialised FastAPI application.  SSH
collection is mocked by patching ``get_collector`` before any request is made.

Backup dispatch runs on a dedicated background executor since #27 (no longer
FastAPI ``BackgroundTasks``), so a ``POST /api/v1/backups`` returns while the
job is still ``pending``.  The ``client`` fixture below wraps ``TestClient``
so it automatically polls each newly-created backup job to completion — this
restores the pre-#27 "the job has finished by the next request" behaviour the
existing tests were written against, without every test needing an explicit
``wait_for_job`` call.  Tests that build their own ``TestClient`` (custom
collector / settings) must call ``wait_for_job`` from ``tests/conftest.py``
themselves.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import CISCO_FAKE_OUTPUT, AutoWaitTestClient, FakeCollector


@pytest.fixture()
def client(test_app) -> TestClient:
    """``TestClient`` with SSH collection replaced by ``FakeCollector``.

    The patch target is ``netcanon.api.routes.backups.get_collector`` — the
    exact location imported and called by the backup route.  The patch returns
    a ``FakeCollector`` for every ``get_collector(definition)`` call, regardless
    of the definition's strategy or type_key.

    The client is an :class:`~tests.conftest.AutoWaitTestClient` so a
    ``POST /api/v1/backups`` blocks until the created job is terminal (see the
    module docstring) — the default ``FakeCollector`` finishes in
    milliseconds.  Used as a context manager so the app lifespan runs (loading
    definitions, creating the FileConfigStore) before the first request and
    tears down cleanly after.
    """
    fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
    with patch(
        "netcanon.api.routes.backups.get_collector",
        return_value=fake,
    ), AutoWaitTestClient(test_app, raise_server_exceptions=True) as c:
        yield c
