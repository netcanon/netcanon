"""
Unit tests for the Phase 0 ``canonical.loader`` stub.

The module exists so future code has a stable import path; every
public surface must raise :class:`NotImplementedError` with a helpful
pointer to the roadmap.
"""

from __future__ import annotations

import pytest

from netconfig.migration.canonical import loader

pytestmark = pytest.mark.unit


class TestStubsRaise:
    def test_get_libyang_context_raises(self):
        with pytest.raises(NotImplementedError, match="Phase 0.5"):
            loader.get_libyang_context()

    def test_validate_against_canonical_raises(self):
        with pytest.raises(NotImplementedError, match="libyang"):
            loader.validate_against_canonical({})


class TestPlannedModulesInventory:
    def test_openconfig_modules_listed(self):
        """PLANNED_MODULES is documentation-as-code for roadmap tracking."""
        assert "openconfig-interfaces" in loader.PLANNED_MODULES
        assert "netconfig-ext" in loader.PLANNED_MODULES

    def test_planned_modules_is_immutable_tuple(self):
        """Guard against accidental mutation during test runs."""
        assert isinstance(loader.PLANNED_MODULES, tuple)
