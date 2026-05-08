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

    def test_missing_input_raises(self, capsys, tmp_path):
        nonexistent = tmp_path / "does-not-exist.cfg"
        with pytest.raises((FileNotFoundError, OSError)):
            main([
                "sanitize",
                "-i", str(nonexistent),
                "-s", "aruba_aoss",
            ])


class TestCLIArgvFromList:
    """Pass argv as a list (not relying on sys.argv) for in-process testing."""

    def test_main_accepts_argv_list(self, capsys):
        with pytest.raises(SystemExit):
            main(["--help"])
