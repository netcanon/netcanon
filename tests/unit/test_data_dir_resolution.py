"""
Unit tests for ``Settings.data_dir`` and the ``effective_data_dir`` property.

The desktop application needs to relocate the data root (jobs / schedules /
device profiles) independently of ``configs_dir`` — the operator may keep
configs on a fast SSD while the small JSON state files sit under
``%APPDATA%\\NetConfig\\``.  ``Settings.data_dir`` is the explicit knob that
makes that possible without breaking the historical ``configs_dir.parent``
default.

This module pins the resolution algorithm:

* ``data_dir is None`` → ``effective_data_dir == configs_dir.parent``
  (backward compatible — no env var, no preferences file behaves
  identically to the pre-change codebase).
* ``data_dir = Path("/explicit")`` → ``effective_data_dir == /explicit``
  (explicit override wins; this is the desktop-preferences path).

The four lifespan call sites in ``netconfig/main.py`` (data_root probe,
job_store, schedule_store, device_profile_store) all read through
``effective_data_dir`` so they share a single resolution point.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.config import Settings

pytestmark = pytest.mark.unit


class TestEffectiveDataDirDefault:
    """When ``data_dir`` is unset, fall back to ``configs_dir.parent``."""

    def test_default_data_dir_is_none(self):
        s = Settings()
        assert s.data_dir is None

    def test_falls_back_to_configs_parent(self, tmp_path):
        s = Settings(configs_dir=tmp_path / "configs")
        assert s.effective_data_dir == tmp_path

    def test_fallback_with_relative_configs_dir(self):
        # Even with a relative path, the property derives the parent
        # without performing any filesystem touch.
        s = Settings(configs_dir=Path("configs"))
        assert s.effective_data_dir == Path("configs").parent


class TestEffectiveDataDirExplicit:
    """An explicit ``data_dir`` overrides the parent-derivation."""

    def test_explicit_path_overrides_default(self, tmp_path):
        custom = tmp_path / "custom_data"
        s = Settings(
            configs_dir=tmp_path / "configs",
            data_dir=custom,
        )
        assert s.effective_data_dir == custom

    def test_explicit_path_outside_configs_tree(self, tmp_path):
        # data_dir need not be a sibling/parent of configs_dir
        configs = tmp_path / "fast_ssd" / "configs"
        data = tmp_path / "appdata" / "state"
        s = Settings(configs_dir=configs, data_dir=data)
        assert s.effective_data_dir == data
        # configs_dir.parent should not leak through
        assert s.effective_data_dir != configs.parent


class TestMainLifespanCallSites:
    """Smoke-test that the four call sites in ``netconfig/main.py`` use
    ``effective_data_dir`` rather than ``configs_dir.parent`` directly.

    Failure mode this guards against: a future contributor adds another
    store (e.g. ``credentials/``) and copy-pastes the old derivation,
    silently bypassing the operator's data_dir override.  We grep the
    file for the literal ``configs_dir.parent`` token to catch that.
    """

    def test_main_uses_effective_data_dir(self):
        from netconfig import main as main_module
        from inspect import getsource

        src = getsource(main_module)
        # The lifespan should refer to effective_data_dir at least once
        assert "effective_data_dir" in src
        # And must NOT use the old configs_dir.parent derivation in code
        # (only in comments / docstrings, which is fine).  Strip comments
        # before checking so the explanatory note above the assignment
        # doesn't trigger a false positive.
        code_lines = [
            ln.split("#", 1)[0] for ln in src.splitlines()
        ]
        joined = "\n".join(code_lines)
        assert "configs_dir.parent" not in joined, (
            "main.py still references configs_dir.parent in code; "
            "use settings.effective_data_dir instead."
        )
