"""OBS-01 regression: NETCANON_LOG_LEVEL must reach the stdlib root logger.

``netcanon/main.py`` previously called ``configure_logging(level="INFO")``
with a hardcoded level at import time, so ``Settings.log_level`` (env
``NETCANON_LOG_LEVEL``) never reached the stdlib root logger on the
server/Docker path — every ``logger.debug(...)`` site was silently dropped
under the bare ``uvicorn netcanon.main:app`` entry point.  ``main`` now
resolves ``Settings().log_level``.

These tests exercise the fix's mechanism directly (env -> Settings ->
configure_logging -> root level) rather than reloading ``netcanon.main``,
which instantiates the app + scheduler at module level.
"""

from __future__ import annotations

import logging

import pytest

from netcanon.config import Settings
from netcanon.logging_config import configure_logging

pytestmark = pytest.mark.unit


def _run_with_clean_root(fn):
    """Run *fn* with the root logger's non-pytest handlers stripped so
    ``configure_logging``'s idempotency guard lets it (re)configure, then
    restore the original handlers + level."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers[:] = [
        h for h in saved_handlers if type(h).__module__.startswith("_pytest")
    ]
    try:
        return fn(root)
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_settings_log_level_reads_env(monkeypatch):
    monkeypatch.setenv("NETCANON_LOG_LEVEL", "debug")
    assert Settings().log_level == "debug"


def test_settings_log_level_defaults_to_info(monkeypatch):
    monkeypatch.delenv("NETCANON_LOG_LEVEL", raising=False)
    assert Settings().log_level == "info"


def test_resolved_env_level_reaches_root_logger(monkeypatch):
    # Mirrors exactly what netcanon.main does at import time:
    #   configure_logging(level=Settings().log_level)
    monkeypatch.setenv("NETCANON_LOG_LEVEL", "debug")

    def check(root):
        configure_logging(level=Settings().log_level)
        assert root.level == logging.DEBUG

    _run_with_clean_root(check)


def test_default_resolves_to_info_root_level(monkeypatch):
    monkeypatch.delenv("NETCANON_LOG_LEVEL", raising=False)

    def check(root):
        configure_logging(level=Settings().log_level)
        assert root.level == logging.INFO

    _run_with_clean_root(check)
