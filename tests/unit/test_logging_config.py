"""
Unit tests for ``netconfig.logging_config.configure_logging``.

Each test runs against a clean root logger state; the ``reset_root_logger``
fixture restores the original handlers and level after every test so tests
do not bleed into each other.
"""
from __future__ import annotations

import logging
import logging.handlers

import pytest

from netconfig.logging_config import configure_logging

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_root_logger():
    """Isolate root logger state before AND after each test.

    Clearing non-pytest handlers at entry is what lets these tests
    exercise :func:`configure_logging`'s "first call" code path — the
    function short-circuits when the root already has application
    handlers, so if an earlier module import (e.g. ``netconfig.main``)
    installed a console handler, the tests would otherwise see a
    no-op and assert against stale state.  The fixture restores the
    original handler set afterwards so other test modules are
    unaffected.
    """
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    level_before = root.level
    # Clear non-_pytest handlers so configure_logging's guard is satisfied.
    for h in list(root.handlers):
        if not type(h).__module__.startswith("_pytest"):
            root.removeHandler(h)
    yield
    # Remove anything this test added.
    for h in list(root.handlers):
        if h not in handlers_before:
            h.close()
            root.removeHandler(h)
    # Re-attach anything we stripped at entry.
    for h in handlers_before:
        if h not in root.handlers:
            root.addHandler(h)
    root.setLevel(level_before)
    # Reset noisy-logger overrides so other tests see NOTSET.
    for name in ("paramiko", "uvicorn.access", "multipart", "asyncio"):
        logging.getLogger(name).setLevel(logging.NOTSET)


# ---------------------------------------------------------------------------
# Basic handler / level configuration
# ---------------------------------------------------------------------------


class TestConfigureLoggingBasic:
    def test_adds_stream_handler(self):
        configure_logging()
        types = [type(h) for h in logging.getLogger().handlers]
        assert logging.StreamHandler in types

    def test_default_level_is_info(self):
        configure_logging()
        assert logging.getLogger().level == logging.INFO

    def test_explicit_warning_level(self):
        configure_logging(level="WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_explicit_debug_level(self):
        configure_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_level_is_case_insensitive(self):
        configure_logging(level="warning")
        assert logging.getLogger().level == logging.WARNING

    def test_idempotent_no_duplicate_handlers(self):
        configure_logging()
        count_first = len(logging.getLogger().handlers)
        configure_logging()
        assert len(logging.getLogger().handlers) == count_first

    def test_idempotent_when_handler_pre_exists(self):
        """If a handler was added before configure_logging, it must not add more."""
        logging.getLogger().addHandler(logging.StreamHandler())
        count_before = len(logging.getLogger().handlers)
        configure_logging()
        assert len(logging.getLogger().handlers) == count_before


# ---------------------------------------------------------------------------
# Rotating file handler
# ---------------------------------------------------------------------------


class TestFileHandler:
    def test_no_file_handler_without_log_file(self):
        configure_logging()
        handlers = logging.getLogger().handlers
        assert not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)

    def test_adds_rotating_file_handler(self, tmp_path):
        configure_logging(log_file=tmp_path / "test.log")
        handlers = logging.getLogger().handlers
        assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)

    def test_creates_parent_directories(self, tmp_path):
        log_file = tmp_path / "a" / "b" / "c" / "netconfig.log"
        configure_logging(log_file=log_file)
        assert log_file.parent.exists()

    def test_log_file_receives_messages(self, tmp_path):
        log_file = tmp_path / "netconfig.log"
        configure_logging(level="DEBUG", log_file=log_file)
        logging.getLogger("test.write").info("probe-message-xyz")
        for h in logging.getLogger().handlers:
            h.flush()
        assert log_file.exists()
        assert "probe-message-xyz" in log_file.read_text(encoding="utf-8")

    def test_console_and_file_both_added(self, tmp_path):
        configure_logging(log_file=tmp_path / "test.log")
        handlers = logging.getLogger().handlers
        has_stream = any(
            type(h) is logging.StreamHandler for h in handlers
        )
        has_file = any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
        assert has_stream and has_file


# ---------------------------------------------------------------------------
# Third-party logger suppression
# ---------------------------------------------------------------------------


class TestNoisyLoggerSuppression:
    def test_paramiko_suppressed_to_warning(self):
        configure_logging(level="DEBUG")
        assert logging.getLogger("paramiko").level == logging.WARNING

    def test_uvicorn_access_suppressed(self):
        configure_logging(level="DEBUG")
        assert logging.getLogger("uvicorn.access").level == logging.WARNING

    def test_multipart_suppressed(self):
        configure_logging(level="DEBUG")
        assert logging.getLogger("multipart").level == logging.WARNING

    def test_asyncio_suppressed(self):
        configure_logging(level="DEBUG")
        assert logging.getLogger("asyncio").level == logging.WARNING

    def test_application_loggers_not_suppressed(self):
        """netconfig.* loggers must NOT be individually suppressed."""
        configure_logging(level="DEBUG")
        # NOTSET means "inherit from parent / root" — correct behaviour.
        assert logging.getLogger("netconfig").level == logging.NOTSET
        assert logging.getLogger("netconfig.api.routes.backups").level == logging.NOTSET
