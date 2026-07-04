"""Unit tests for the ``netcanon demo`` CLI and the ``netcanon.tools.demo`` module.

Regression guard for finding R-02 / CF-02 (2026-06-06 review): the demo
must ship inside the package so ``netcanon demo`` works from a bare
``pip install`` / the Docker image (the README hero command) — not only
``python tools/demo.py`` from a source checkout.  The repo-root
``tools/demo.py`` is retained as a thin shim and must keep re-exporting
the package entry point.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from netcanon.cli import main as cli_main
from netcanon.tools.demo import SCENARIOS
from netcanon.tools.demo import main as demo_main

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestDemoModule:
    def test_list_returns_zero_and_shows_every_pair(self, capsys):
        assert demo_main(["--list"]) == 0
        out = capsys.readouterr().out
        for key in SCENARIOS:
            assert f"--pair {key}" in out

    def test_default_pair_translates_to_junos(self, capsys):
        # No args → default cisco__junos scenario.  Proves the
        # rename-aware pipeline ran end-to-end: the Cisco hostname becomes
        # Junos set-form AND the Cisco port name is translated to native
        # Junos form (ge-1/0/1), not left verbatim.
        assert demo_main([]) == 0
        out = capsys.readouterr().out
        assert "set system host-name access-sw-01" in out
        assert "set interfaces ge-1/0/1" in out

    @pytest.mark.parametrize("pair", sorted(SCENARIOS))
    def test_every_scenario_runs_clean(self, pair, capsys):
        assert demo_main(["--pair", pair]) == 0
        out = capsys.readouterr().out
        assert "OUTPUT" in out
        assert "FAILED" not in out

    def test_partial_job_exits_nonzero(self, capsys, monkeypatch):
        """API-5 (2026-07-03 review): the demo keyed success off the enum's
        repr suffix (``endswith('failed')``), so a *partial* job printed the
        full success flow and exited 0. It must now treat only ``completed``
        as success — a partial job prints a PARTIAL section and returns
        non-zero."""
        from types import SimpleNamespace

        import netcanon.tools.demo as demo_mod
        from netcanon.models.migration import MigrationJobStatus

        monkeypatch.setattr(
            demo_mod, "run_plan_with_rename",
            lambda *a, **k: SimpleNamespace(
                status=MigrationJobStatus.partial, error=None,
            ),
        )
        rc = demo_main(["--pair", "cisco__junos"])
        out = capsys.readouterr().out
        assert rc == 1
        assert "PARTIAL" in out
        assert "OUTPUT" not in out


class TestDemoViaCLI:
    """``netcanon demo …`` must delegate to the same module (the shipped path)."""

    def test_cli_demo_list(self, capsys):
        assert cli_main(["demo", "--list"]) == 0
        assert "Available demo scenarios" in capsys.readouterr().out

    def test_cli_demo_pair(self, capsys):
        assert cli_main(["demo", "--pair", "aruba__arista"]) == 0
        assert "Aruba AOS-S -> Arista EOS" in capsys.readouterr().out


class TestRootShim:
    """The repo-root ``tools/demo.py`` shim stays valid and re-exports ``main``."""

    def test_shim_reexports_package_main(self):
        shim_path = REPO_ROOT / "tools" / "demo.py"
        assert shim_path.is_file()
        spec = importlib.util.spec_from_file_location("_demo_shim_under_test", shim_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # The shim must expose the *same* callable the package ships.
        assert module.main is demo_main
