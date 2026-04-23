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


# ---------------------------------------------------------------------------
# Request-ID filter (Phase 9 logging audit)
# ---------------------------------------------------------------------------


class TestRequestIdFilter:
    """Locks in the contextvar + LogFilter shape so future refactors
    of ``configure_logging`` don't silently lose the correlation
    column on log lines.
    """

    def test_filter_injects_default_sentinel_when_no_request(self):
        """Outside a request scope, REQUEST_ID_CTX returns '-'.  The
        filter must preserve the column alignment by injecting the
        sentinel rather than leaving the attribute missing."""
        from netconfig.logging_config import (
            REQUEST_ID_CTX,
            RequestIdFilter,
        )
        # Baseline: no request is in flight.
        assert REQUEST_ID_CTX.get() == "-"
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="",
            lineno=0, msg="hello", args=(), exc_info=None,
        )
        RequestIdFilter().filter(record)
        assert record.request_id == "-"

    def test_filter_uses_contextvar_value(self):
        from netconfig.logging_config import (
            REQUEST_ID_CTX,
            RequestIdFilter,
        )
        token = REQUEST_ID_CTX.set("abc12345")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="",
                lineno=0, msg="hello", args=(), exc_info=None,
            )
            RequestIdFilter().filter(record)
            assert record.request_id == "abc12345"
        finally:
            REQUEST_ID_CTX.reset(token)

    def test_filter_preserves_explicit_extra_request_id(self):
        """Explicit ``extra={'request_id': '...'}`` instrumentation
        wins over the contextvar — a deliberate override shouldn't
        get stomped by the filter."""
        from netconfig.logging_config import RequestIdFilter
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="",
            lineno=0, msg="hello", args=(), exc_info=None,
        )
        record.request_id = "custom-id"
        RequestIdFilter().filter(record)
        assert record.request_id == "custom-id"

    def test_configure_logging_installs_filter_on_console(self):
        configure_logging()
        from netconfig.logging_config import RequestIdFilter
        console_handlers = [
            h for h in logging.getLogger().handlers
            if type(h) is logging.StreamHandler
        ]
        assert console_handlers, "expected a StreamHandler"
        for h in console_handlers:
            assert any(
                isinstance(f, RequestIdFilter) for f in h.filters
            ), f"handler {h!r} missing RequestIdFilter"

    def test_configure_logging_installs_filter_on_file(self, tmp_path):
        configure_logging(log_file=tmp_path / "req.log")
        from netconfig.logging_config import RequestIdFilter
        file_handlers = [
            h for h in logging.getLogger().handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert file_handlers, "expected a RotatingFileHandler"
        for h in file_handlers:
            assert any(
                isinstance(f, RequestIdFilter) for f in h.filters
            )

    def test_formatted_output_contains_request_id_column(
        self, tmp_path,
    ):
        """End-to-end: set a request id, emit a log, read the file,
        assert the [req=...] column renders with the id."""
        from netconfig.logging_config import REQUEST_ID_CTX
        log_file = tmp_path / "netconfig.log"
        configure_logging(level="INFO", log_file=log_file)
        token = REQUEST_ID_CTX.set("e2e12345")
        try:
            logging.getLogger("test.fmt").info("correlated-probe")
            for h in logging.getLogger().handlers:
                h.flush()
        finally:
            REQUEST_ID_CTX.reset(token)
        text = log_file.read_text(encoding="utf-8")
        assert "[req=e2e12345]" in text, (
            f"expected [req=e2e12345] in formatted log; got: {text!r}"
        )
