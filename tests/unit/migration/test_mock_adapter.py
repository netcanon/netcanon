"""
Round-trip + contract tests for the reference ``MockAdapter``.

The round-trip invariant is THE most valuable test per
``translator-plans.txt`` §10 — every real adapter must satisfy it for
its supported subset, and this file is the reference pattern new
adapter contributors can copy.
"""

from __future__ import annotations

import json

import pytest

from netconfig.migration.adapters._mock import MockAdapter
from netconfig.migration.adapters.base import ParseError

pytestmark = pytest.mark.unit


SAMPLE_TREES: list[dict[str, str]] = [
    # Empty tree — trivial identity.
    {},
    # Single field.
    {"/interfaces/eth0/ip": "192.168.1.1"},
    # Multiple fields.
    {
        "/interfaces/eth0/ip": "10.0.0.1",
        "/interfaces/eth0/description": "uplink",
        "/vlans/10/name": "office",
    },
    # Values containing special characters.
    {"/interfaces/eth0/description": 'quote " and backslash \\'},
    # Keys with unicode (must survive JSON roundtrip).
    {"/labels/site": "Zürich office"},
]


class TestMockAdapterRoundtrip:
    @pytest.mark.parametrize("tree", SAMPLE_TREES)
    def test_parse_render_roundtrip(self, tree):
        """parse(render(tree)) == tree for every tree in the supported subset."""
        adapter = MockAdapter()
        rendered = adapter.render(tree)
        reparsed = adapter.parse(rendered)
        assert reparsed == tree

    def test_render_output_is_deterministic(self):
        """Same tree → same rendered text byte-for-byte.

        Required because the textual diff stage (Phase 1) compares
        rendered output to detect change.  Non-deterministic output
        would produce spurious diffs.
        """
        tree = {"/b": "2", "/a": "1"}
        a = MockAdapter().render(tree)
        b = MockAdapter().render(tree)
        assert a == b

    def test_render_output_is_sorted(self):
        """Keys appear in sorted order so human reviewers and textual
        diffs see a stable layout regardless of dict insertion order."""
        tree = {"/z": "1", "/a": "2", "/m": "3"}
        rendered = MockAdapter().render(tree)
        a_idx = rendered.index("/a")
        m_idx = rendered.index("/m")
        z_idx = rendered.index("/z")
        assert a_idx < m_idx < z_idx


class TestMockAdapterParseErrors:
    def test_non_json_raises_parseerror(self):
        with pytest.raises(ParseError):
            MockAdapter().parse("not json at all")

    def test_json_list_rejected(self):
        with pytest.raises(ParseError, match="object at top level"):
            MockAdapter().parse(json.dumps([1, 2, 3]))

    def test_non_string_value_rejected(self):
        with pytest.raises(ParseError, match="string keys and string values"):
            MockAdapter().parse(json.dumps({"/a": 42}))

    def test_parseerror_carries_snippet_for_ui(self):
        """The ParseError must include a snippet so the UI can surface
        a useful error banner."""
        raw = "this is not json"
        with pytest.raises(ParseError) as excinfo:
            MockAdapter().parse(raw)
        assert excinfo.value.snippet is not None
        assert raw in excinfo.value.snippet


class TestMockAdapterCapabilities:
    def test_capabilities_adapter_name_matches(self):
        assert MockAdapter().capabilities.adapter == "mock"

    def test_capabilities_has_each_classification(self):
        """The mock is deliberately set up to exercise every classify
        branch so pipeline tests can use it."""
        caps = MockAdapter().capabilities
        assert len(caps.supported) >= 1
        assert len(caps.lossy) >= 1
        assert len(caps.unsupported) >= 1

    def test_capabilities_is_class_level_constant(self):
        """Two instances yield the same matrix object (cached on the class)."""
        a = MockAdapter().capabilities
        b = MockAdapter().capabilities
        assert a is b
