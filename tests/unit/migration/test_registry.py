"""
Unit tests for ``netconfig.migration.adapters.registry``.

The registry is a process-global singleton populated at import time,
so these tests use a throwaway subclass registered under a unique
name that won't collide with the built-ins.
"""

from __future__ import annotations

import pytest

from netconfig.migration.adapters.base import AdapterBase
from netconfig.migration.adapters.registry import (
    _REGISTRY,
    get_adapter,
    list_adapters,
    register,
)
from netconfig.models.migration import CapabilityMatrix

pytestmark = pytest.mark.unit


class _DummyAdapter(AdapterBase):
    """Adapter subclass used only in these tests — name set per-test."""

    @property
    def capabilities(self) -> CapabilityMatrix:
        return CapabilityMatrix(adapter=self.name)

    def parse(self, raw: str):  # noqa: D401
        return {}

    def render(self, tree) -> str:  # noqa: D401
        return ""


def _cleanup(name: str) -> None:
    """Helper: remove *name* from the global registry if present."""
    _REGISTRY.pop(name, None)


class TestRegister:
    def test_register_returns_class(self):
        """@register is a decorator — must return the class unchanged."""
        class A(_DummyAdapter):
            name = "_test_register_returns_class"
        try:
            result = register(A)
            assert result is A
        finally:
            _cleanup(A.name)

    def test_register_puts_class_in_registry(self):
        class A(_DummyAdapter):
            name = "_test_register_put"
        register(A)
        try:
            assert "_test_register_put" in list_adapters()
        finally:
            _cleanup(A.name)

    def test_register_rejects_missing_name(self):
        class NoName(_DummyAdapter):
            pass
        # ClassVar on the parent still exists; need to null it out so
        # the registry sees it as missing.
        NoName.name = ""  # type: ignore[assignment]
        with pytest.raises(ValueError, match="missing a non-empty `name`"):
            register(NoName)

    def test_register_rejects_name_collision(self):
        class First(_DummyAdapter):
            name = "_test_collision"

        class Second(_DummyAdapter):
            name = "_test_collision"

        register(First)
        try:
            with pytest.raises(ValueError, match="name collision"):
                register(Second)
        finally:
            _cleanup(First.name)

    def test_register_same_class_twice_is_idempotent(self):
        """Useful during test re-imports via importlib.reload."""
        class A(_DummyAdapter):
            name = "_test_idempotent"
        register(A)
        register(A)  # must not raise
        try:
            assert list_adapters().count("_test_idempotent") == 1
        finally:
            _cleanup(A.name)


class TestGetAdapter:
    def test_returns_instance_not_class(self):
        class A(_DummyAdapter):
            name = "_test_get_instance"
        register(A)
        try:
            result = get_adapter("_test_get_instance")
            assert isinstance(result, A)
        finally:
            _cleanup(A.name)

    def test_unknown_name_raises_lookuperror_not_keyerror(self):
        with pytest.raises(LookupError, match="No adapter registered"):
            get_adapter("_definitely_not_registered")

    def test_lookup_message_lists_known_adapters(self):
        """Error message must help the caller discover valid names."""
        with pytest.raises(LookupError) as excinfo:
            get_adapter("_nope")
        assert "Known adapters" in str(excinfo.value)


class TestListAdapters:
    def test_result_is_sorted(self):
        class Z(_DummyAdapter):
            name = "_test_list_zzz"

        class A(_DummyAdapter):
            name = "_test_list_aaa"

        register(Z)
        register(A)
        try:
            result = list_adapters()
            # Both registered names are in alphabetical order relative
            # to each other.
            assert result.index("_test_list_aaa") < result.index("_test_list_zzz")
        finally:
            _cleanup(Z.name)
            _cleanup(A.name)

    def test_mock_adapter_is_always_registered(self):
        """The package __init__ pre-registers the reference mock adapter."""
        import netconfig.migration  # noqa: F401 — ensure import
        assert "mock" in list_adapters()
