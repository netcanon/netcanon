"""
Unit tests for the :attr:`AdapterBase.input_format` declaration.

Introduced after a round of manual GUI testing surfaced that the
/migrate paste box accepts MACHINE-READABLE input (XML/JSON), not
the CLI text operators usually have from a device.  Adapters now
declare their expected input format so the UI can:

    1. Show a hint banner explaining what to paste.
    2. Offer a "Load sample" button with a known-good payload.
    3. Warn when a stored-config file's extension is unlikely to be
       parseable by the selected source adapter.

This file covers the DECLARATIONS side of that contract — the UI
side is covered by the E2E tests.
"""

from __future__ import annotations

import pytest

from netconfig.migration.adapters._mock import MockAdapter
from netconfig.migration.adapters.base import INPUT_FORMATS, AdapterBase
from netconfig.migration.adapters.cisco_iosxe import CiscoIOSXEAdapter
from netconfig.migration.adapters.opnsense import OPNsenseAdapter
from netconfig.migration.adapters.registry import list_adapters, get_adapter
from netconfig.models.migration import CapabilityMatrix

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


class TestInputFormatCatalogue:
    def test_catalogue_is_frozenset(self):
        """Immutable so contributors can't mutate it at import time."""
        assert isinstance(INPUT_FORMATS, frozenset)

    def test_catalogue_contains_core_entries(self):
        for expected in (
            "xml-netconf", "xml-opnsense", "json-flat", "unknown",
        ):
            assert expected in INPUT_FORMATS

    def test_reserved_cli_formats_present(self):
        """Reserved tags for not-yet-shipped adapters — declaring them now
        keeps the UI catalogue in sync with the roadmap."""
        for reserved in ("cli-ios", "cli-fortigate", "cli-mikrotik", "xml-panos"):
            assert reserved in INPUT_FORMATS


# ---------------------------------------------------------------------------
# Default on the abstract base
# ---------------------------------------------------------------------------


class TestAdapterBaseDefault:
    def test_default_input_format_is_unknown(self):
        """Adapters under development inherit a safe default."""

        class _StubAdapter(AdapterBase):
            name = "_test_stub_default_fmt"

            @property
            def capabilities(self):
                return CapabilityMatrix(adapter=self.name)

            def parse(self, raw):
                return {}

            def render(self, tree):
                return ""

        assert _StubAdapter.input_format == "unknown"


# ---------------------------------------------------------------------------
# Concrete adapter declarations
# ---------------------------------------------------------------------------


class TestConcreteAdapterDeclarations:
    def test_cisco_iosxe_declares_xml_netconf(self):
        assert CiscoIOSXEAdapter.input_format == "xml-netconf"

    def test_opnsense_declares_xml_opnsense(self):
        assert OPNsenseAdapter.input_format == "xml-opnsense"

    def test_mock_declares_json_flat(self):
        assert MockAdapter.input_format == "json-flat"

    def test_every_registered_adapter_declares_a_known_format(self):
        """Every shipped adapter's declared format must be in the catalogue.

        Using 'unknown' is acceptable (and tested above) but a typo like
        'xml-netcon' would silently break the UI's format-hint lookup.
        This test catches the typo at CI time."""
        import netconfig.migration  # side-effect: register all built-ins

        for name in list_adapters():
            adapter = get_adapter(name)
            fmt = getattr(adapter, "input_format", "unknown")
            assert (
                fmt in INPUT_FORMATS
            ), f"{name} declares unknown input_format {fmt!r}"


# ---------------------------------------------------------------------------
# API surface — AdapterInfo exposes input_format
# ---------------------------------------------------------------------------


class TestAdapterInfoShape:
    def test_adapter_info_model_has_input_format_field(self):
        from netconfig.models.migration import AdapterInfo

        # The default is 'unknown' so a minimal AdapterInfo constructs cleanly
        # even if the caller forgets to pass it.
        info = AdapterInfo(
            name="t",
            version_range="*",
            supported_count=0,
            lossy_count=0,
            unsupported_count=0,
        )
        assert info.input_format == "unknown"

    def test_adapter_info_preserves_declared_format(self):
        from netconfig.models.migration import AdapterInfo

        info = AdapterInfo(
            name="cisco_iosxe",
            version_range="16.3+",
            input_format="xml-netconf",
            supported_count=9,
            lossy_count=1,
            unsupported_count=1,
        )
        assert info.input_format == "xml-netconf"
