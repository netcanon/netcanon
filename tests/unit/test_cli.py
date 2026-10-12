"""CLI tests — invocation contract for ``netcanon`` console script.

The CLI lives at :mod:`netcanon.cli` and is registered as the
``netcanon`` console-script entry point in ``pyproject.toml``.

Tests use ``main()`` directly rather than the installed entry point —
that keeps the test independent of PATH (the Windows pip-install
PATH issue documented in the Phase 1.5 wave) and runs in-process so
``capsys`` can capture stdout / stderr.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.cli import main

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[2]
ARUBA_FIXTURE = (
    REPO_ROOT / "tests" / "fixtures" / "real" / "aruba_aoss"
    / "hpe_community_2920_wb1608_dhcp_snooping.cfg"
)


class TestCLIHelp:
    def test_top_level_help_lists_sanitize(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "sanitize" in out

    def test_sanitize_help_lists_required_args(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["sanitize", "--help"])
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "--input" in out
        assert "--source-vendor" in out
        assert "--dry-run" in out


class TestCLISanitizeDryRun:
    def test_dry_run_prints_substitution_audit(self, capsys):
        rc = main([
            "sanitize",
            "-i", str(ARUBA_FIXTURE),
            "-s", "aruba_aoss",
            "--dry-run",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Substitution audit" in out
        assert "substitutions identified" in out

    def test_dry_run_does_not_write_output_file(self, capsys, tmp_path):
        target = tmp_path / "should-not-exist.cfg"
        rc = main([
            "sanitize",
            "-i", str(ARUBA_FIXTURE),
            "-s", "aruba_aoss",
            "-o", str(target),
            "--dry-run",
        ])
        assert rc == 0
        assert not target.exists()


class TestCLISanitizeWriteOutput:
    def test_writes_sanitized_file(self, capsys, tmp_path):
        target = tmp_path / "sanitized.cfg"
        rc = main([
            "sanitize",
            "-i", str(ARUBA_FIXTURE),
            "-s", "aruba_aoss",
            "-o", str(target),
        ])
        assert rc == 0
        assert target.exists()
        out = target.read_text(encoding="utf-8")
        assert out  # non-empty
        # Sanity: original SNMP community 'xxxx' (already obscured by
        # poster) was redacted to public_redacted_N or similar
        # placeholder pattern.  The original 'SW-1OG-01' hostname
        # should NOT appear in the sanitized output.
        assert "SW-1OG-01" not in out


class TestCLIErrorHandling:
    def test_unknown_source_vendor_returns_2(self, capsys, tmp_path):
        bogus = tmp_path / "x.cfg"
        bogus.write_text("hostname foo\n", encoding="utf-8")
        rc = main([
            "sanitize",
            "-i", str(bogus),
            "-s", "no_such_vendor",
        ])
        # Returns 2 on unknown vendor (or parse error)
        assert rc != 0

    def test_missing_input_reports_error(self, capsys, tmp_path):
        # A missing input file is reported with a clear `error: cannot
        # read ...` message + a non-zero exit code, NOT a raw traceback
        # (run3 sanitize-cli-read-outside-try).
        nonexistent = tmp_path / "does-not-exist.cfg"
        rc = main([
            "sanitize",
            "-i", str(nonexistent),
            "-s", "aruba_aoss",
        ])
        assert rc == 2
        assert "cannot read" in capsys.readouterr().err

    def test_unwritable_output_reports_error(self, capsys, tmp_path):
        # The write half is now guarded like the read half (review #46 — the
        # write half of API-3): a missing parent dir is a clean `error: cannot
        # write ...` + exit 2, not a raw traceback with the output lost.
        target = tmp_path / "no_such_dir" / "out.cfg"  # parent does not exist
        rc = main([
            "sanitize",
            "-i", str(ARUBA_FIXTURE),
            "-s", "aruba_aoss",
            "-o", str(target),
        ])
        assert rc == 2
        assert "cannot write" in capsys.readouterr().err
        assert not target.exists()


def _ranges(count: int) -> str:
    """An AOS-S stanza of *count* port ranges of 1,001 ports each."""
    ranges = ",".join(f"{n * 2000 + 1}-{n * 2000 + 1001}" for n in range(count))
    return f'hostname "T"\nvlan 10\n   name "V10"\n   tagged {ranges}\n   exit\n'


class TestCLISanitizeLimits:
    """A config that asks for more than the limits allow is refused
    in a sentence, with exit status 2 -- not reported as a config that
    failed to parse, and never a traceback."""

    def _run(self, tmp_path, capsys, count: int, *options: str):
        source = tmp_path / "wide.cfg"
        source.write_text(_ranges(count), encoding="utf-8")
        target = tmp_path / "out.cfg"
        rc = main(["sanitize", "-i", str(source), "-s", "aruba_aoss", "-o", str(target), *options])
        captured = capsys.readouterr()
        return rc, captured.out, captured.err, target

    def test_help_lists_the_option(self, capsys):
        with pytest.raises(SystemExit):
            main(["sanitize", "--help"])
        out = capsys.readouterr().out
        assert "--limits {small,standard,large,unlimited}" in out
        assert "NETCANON_CONFIG_LIMITS" in out

    def test_a_config_past_a_limit_is_refused_in_words(self, capsys, tmp_path, monkeypatch):
        monkeypatch.delenv("NETCANON_CONFIG_LIMITS", raising=False)
        rc, out, err, target = self._run(tmp_path, capsys, 40)
        assert rc == 2 and out == "" and not target.exists()
        assert err.startswith(
            "error: refused: reading the config as aruba_aoss would make 9,009 or more different ports "
            "named by port ranges; the limit is 8,192"
        )
        # What allows more, for someone at a command line.
        assert "This run used the 'standard' config size limit.  To allow more, pass --limits large" in err
        assert "failed to parse" not in err and "Traceback" not in err
        assert "restart" not in err and "Preferences" not in err

    def test_the_option_allows_more(self, capsys, tmp_path, monkeypatch):
        monkeypatch.delenv("NETCANON_CONFIG_LIMITS", raising=False)
        rc, _out, err, target = self._run(tmp_path, capsys, 40, "--limits", "unlimited")
        assert rc == 0, err
        assert "tagged" in target.read_text(encoding="utf-8")

    def test_the_option_wins_over_the_environment(self, capsys, tmp_path, monkeypatch):
        """Three ranges are 3,003 ports: more than ``small`` takes,
        and less than ``standard`` does."""
        monkeypatch.setenv("NETCANON_CONFIG_LIMITS", "small")
        rc, _out, err, _target = self._run(tmp_path, capsys, 3)
        assert rc == 2
        assert "would make 3,003 or more different ports named by port ranges; the limit is 2,048" in err
        # The command line's own words: there is no server here, and the
        # option that allows more is one this reader can pass.
        assert err.rstrip().endswith(
            "This run used the 'small' config size limit, the one the public demo uses.  The default, "
            "'standard', allows 8,192: pass --limits standard."
        )
        assert "server" not in err and "you run yourself" not in err
        rc, _out, err, _target = self._run(tmp_path, capsys, 3, "--limits", "standard")
        assert rc == 0, err

    def test_the_command_line_never_waits_its_turn(self, capsys, tmp_path, monkeypatch):
        """``small`` makes a SERVER work on one config at a time.  A
        run at the command line is not a request to one: with a
        server's place taken in this very process, it is not kept
        waiting and is not refused as busy."""
        import threading
        from dataclasses import replace

        from netcanon.migration import limits

        monkeypatch.delenv("NETCANON_CONFIG_LIMITS", raising=False)
        # If the run did wait, it would be refused in a third of a second.
        monkeypatch.setitem(limits.PROFILES, "small", replace(limits.SMALL, seconds=0.3))
        held, let_go = threading.Event(), threading.Event()

        def a_request_at_work() -> None:
            with limits.server_scope(limits.SMALL):
                held.set()
                let_go.wait(30)

        request = threading.Thread(target=a_request_at_work, daemon=True)
        request.start()
        assert held.wait(10)
        try:
            assert limits.in_flight() == (1, 0)
            rc, _out, err, target = self._run(tmp_path, capsys, 2, "--limits", "small")
            assert limits.in_flight() == (1, 0)
        finally:
            let_go.set()
            request.join(10)
        assert rc == 0, err
        assert "tagged" in target.read_text(encoding="utf-8") and "busy" not in err
        assert limits.in_flight() == (0, 0)

    def test_a_name_outside_the_four_is_not_taken(self, capsys, tmp_path, monkeypatch):
        with pytest.raises(SystemExit) as stopped:
            self._run(tmp_path, capsys, 1, "--limits", "none")
        assert stopped.value.code == 2
        capsys.readouterr()
        # From the environment it is not "no limit" either: it is said, and the standard limits apply.
        monkeypatch.setenv("NETCANON_CONFIG_LIMITS", "unlimitted")
        rc, _out, err, _target = self._run(tmp_path, capsys, 40)
        assert rc == 2
        assert err.startswith(
            "warning: NETCANON_CONFIG_LIMITS='unlimitted' is not one of small, standard, large, unlimited; "
            "using standard"
        )
        assert "the limit is 8,192" in err


class TestServe:
    """``netcanon serve`` starts the server as ``uvicorn.run`` would for
    one worker, on the socket the config limits ask for: under
    ``small`` one that it binds itself, on which the system ends a
    connection whose client takes nothing; under any other set, the
    server's own."""

    @pytest.fixture()
    def started(self, monkeypatch):
        """uvicorn replaced by a record of what it was asked."""
        import socket

        import uvicorn

        from netcanon.api.routes import _migration_helpers as helpers

        asked: dict = {"starts": True}

        class Bound:
            def __init__(self):
                self.set = []

            def setsockopt(self, *what):
                self.set.append(what)

        class Config:
            def __init__(self, app, **options):
                asked.update(app=app, options=options)

            def bind_socket(self):
                asked["bound"] = Bound()
                return asked["bound"]

        class Server:
            def __init__(self, config):
                self.started = False

            def run(self, sockets=None):
                asked["sockets"] = sockets
                self.started = asked["starts"]

        monkeypatch.setattr(uvicorn, "Config", Config)
        monkeypatch.setattr(uvicorn, "Server", Server)
        monkeypatch.setattr(helpers.socket, "TCP_USER_TIMEOUT", 18, raising=False)
        for name in ("NETCANON_HOST", "NETCANON_PORT", "NETCANON_API_KEY", "NETCANON_LOG_LEVEL",
                     "NETCANON_CONFIG_LIMITS"):
            monkeypatch.delenv(name, raising=False)
        asked["tcp"] = socket.IPPROTO_TCP
        return asked

    def test_by_default_the_server_binds_its_own_socket(self, started):
        assert main(["serve"]) == 0
        assert started["app"] == "netcanon.main:app"
        assert started["options"] == {"host": "127.0.0.1", "port": 8000, "log_level": "info"}
        assert started["sockets"] is None and "bound" not in started

    def test_under_small_it_is_started_on_a_socket_that_ends_unread_connections(self, started, monkeypatch):
        monkeypatch.setenv("NETCANON_CONFIG_LIMITS", "small")
        monkeypatch.setenv("NETCANON_PORT", "8123")
        assert main(["serve"]) == 0
        assert started["options"]["port"] == 8123
        assert started["sockets"] == [started["bound"]]
        assert started["bound"].set == [(started["tcp"], 18, 20_000)]

    def test_a_server_that_did_not_start_is_an_exit_status(self, started):
        started["starts"] = False
        assert main(["serve"]) == 3


class TestCLIArgvFromList:
    """Pass argv as a list (not relying on sys.argv) for in-process testing."""

    def test_main_accepts_argv_list(self, capsys):
        with pytest.raises(SystemExit):
            main(["--help"])
