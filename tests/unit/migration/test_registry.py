"""
Unit tests for ``netcanon.migration.codecs.registry``.

The registry is a process-global singleton populated at import time,
so these tests use a throwaway subclass registered under a unique
name that won't collide with the built-ins.
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.base import CodecBase
from netcanon.migration.codecs.registry import (
    _REGISTRY,
    get_codec,
    list_codecs,
    register,
)
from netcanon.models.migration import CapabilityMatrix

pytestmark = pytest.mark.unit


class _DummyAdapter(CodecBase):
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
            assert "_test_register_put" in list_codecs()
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
            assert list_codecs().count("_test_idempotent") == 1
        finally:
            _cleanup(A.name)


class TestGetAdapter:
    def test_returns_instance_not_class(self):
        class A(_DummyAdapter):
            name = "_test_get_instance"
        register(A)
        try:
            result = get_codec("_test_get_instance")
            assert isinstance(result, A)
        finally:
            _cleanup(A.name)

    def test_unknown_name_raises_lookuperror_not_keyerror(self):
        with pytest.raises(LookupError, match="No adapter registered"):
            get_codec("_definitely_not_registered")

    def test_lookup_message_lists_known_adapters(self):
        """Error message must help the caller discover valid names."""
        with pytest.raises(LookupError) as excinfo:
            get_codec("_nope")
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
            result = list_codecs()
            # Both registered names are in alphabetical order relative
            # to each other.
            assert result.index("_test_list_aaa") < result.index("_test_list_zzz")
        finally:
            _cleanup(Z.name)
            _cleanup(A.name)

    def test_mock_adapter_is_always_registered(self):
        """The package __init__ pre-registers the reference mock adapter."""
        import netcanon.migration  # noqa: F401 — ensure import
        assert "mock" in list_codecs()


class TestAutoDiscovery:
    """The migration package auto-discovers codec sub-packages; adding
    a new codec should require no edit to netcanon/migration/__init__.py."""

    def test_all_built_in_codecs_discovered(self):
        """Every sub-package under netcanon/migration/codecs/ registers
        via auto-discovery at package import time."""
        import netcanon.migration  # noqa: F401 — ensure discovery ran
        registered = set(list_codecs())
        expected = {
            "mock",
            "cisco_iosxe",
            "cisco_iosxe_cli",
            "opnsense",
            "mikrotik_routeros",
        }
        assert expected.issubset(registered), (
            f"missing: {expected - registered}"
        )

    def test_discovery_is_idempotent(self):
        """Re-importing the package must not duplicate or reject registrations."""
        import importlib
        import netcanon.migration
        before = set(list_codecs())
        importlib.reload(netcanon.migration)
        after = set(list_codecs())
        assert before == after, (
            f"registry drifted across reload: "
            f"lost={before - after} gained={after - before}"
        )
