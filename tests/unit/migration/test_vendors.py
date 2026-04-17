"""
Unit tests for vendor YAML loading (``netconfig.migration.vendors``).

Covers:
    * Built-in vendors load cleanly from the package directory.
    * VendorInfo model shape and defaults.
    * Corrupt / missing YAML files are skipped without crashing.
    * Custom directory support for test isolation.
    * vendor_id linkage: every shipped codec's vendor_id matches a loaded vendor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.vendors import load_vendors
from netconfig.models.migration import DeviceClass, VendorInfo

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Built-in vendors
# ---------------------------------------------------------------------------


class TestBuiltInVendors:
    def test_loads_four_vendors(self):
        """Cisco IOS-XE, OPNsense, MikroTik RouterOS, plus the mock."""
        vendors = load_vendors()
        assert len(vendors) == 4

    def test_cisco_iosxe_present(self):
        v = load_vendors()
        assert "cisco_iosxe" in v
        assert v["cisco_iosxe"].display_name == "Cisco IOS-XE"

    def test_opnsense_present(self):
        v = load_vendors()
        assert "opnsense" in v
        assert v["opnsense"].display_name == "OPNsense"

    def test_mikrotik_routeros_present(self):
        v = load_vendors()
        assert "mikrotik_routeros" in v
        assert v["mikrotik_routeros"].display_name == "MikroTik RouterOS"

    def test_mock_present(self):
        v = load_vendors()
        assert "mock" in v

    def test_device_classes_populated(self):
        v = load_vendors()
        assert DeviceClass.router in v["cisco_iosxe"].device_classes
        assert DeviceClass.switch in v["cisco_iosxe"].device_classes
        assert DeviceClass.firewall in v["opnsense"].device_classes
        assert DeviceClass.router in v["mikrotik_routeros"].device_classes
        assert DeviceClass.firewall in v["mikrotik_routeros"].device_classes

    def test_default_timeout_is_int(self):
        for vendor in load_vendors().values():
            assert isinstance(vendor.default_timeout, int)
            assert vendor.default_timeout > 0


# ---------------------------------------------------------------------------
# VendorInfo model
# ---------------------------------------------------------------------------


class TestVendorInfoModel:
    def test_minimal(self):
        v = VendorInfo(id="test", display_name="Test")
        assert v.device_classes == []
        assert v.default_timeout == 30
        assert v.notes == ""

    def test_full(self):
        v = VendorInfo(
            id="x",
            display_name="X Corp",
            device_classes=[DeviceClass.router],
            default_timeout=60,
            notes="test vendor",
        )
        assert v.id == "x"
        assert v.display_name == "X Corp"
        assert v.default_timeout == 60


# ---------------------------------------------------------------------------
# Error resilience
# ---------------------------------------------------------------------------


class TestErrorResilience:
    def test_missing_directory_returns_empty(self, tmp_path):
        vendors = load_vendors(tmp_path / "nonexistent")
        assert vendors == {}

    def test_corrupt_yaml_skipped(self, tmp_path):
        (tmp_path / "bad.yaml").write_text("not: [valid: yaml: {{}", encoding="utf-8")
        (tmp_path / "good.yaml").write_text(
            "id: good\ndisplay_name: Good\n", encoding="utf-8"
        )
        vendors = load_vendors(tmp_path)
        assert "good" in vendors
        assert len(vendors) == 1

    def test_non_dict_yaml_skipped(self, tmp_path):
        (tmp_path / "list.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
        vendors = load_vendors(tmp_path)
        assert vendors == {}

    def test_missing_required_fields_skipped(self, tmp_path):
        # id present but no display_name
        (tmp_path / "incomplete.yaml").write_text(
            "id: nope\nnotes: missing display_name\n", encoding="utf-8"
        )
        vendors = load_vendors(tmp_path)
        assert vendors == {}

    def test_duplicate_vendor_id_last_wins(self, tmp_path):
        (tmp_path / "a_first.yaml").write_text(
            "id: dupe\ndisplay_name: First\n", encoding="utf-8"
        )
        (tmp_path / "b_second.yaml").write_text(
            "id: dupe\ndisplay_name: Second\n", encoding="utf-8"
        )
        vendors = load_vendors(tmp_path)
        assert vendors["dupe"].display_name == "Second"


# ---------------------------------------------------------------------------
# Codec ↔ vendor linkage
# ---------------------------------------------------------------------------


class TestCodecVendorLinkage:
    def test_every_codec_vendor_id_matches_a_loaded_vendor(self):
        """Each shipped codec's ``vendor_id`` must resolve to a loaded
        vendor — otherwise the API returns an empty display_name and
        the UI shows a blank."""
        import netconfig.migration  # side-effect: register codecs
        from netconfig.migration.codecs.registry import get_codec, list_codecs

        vendors = load_vendors()
        for name in list_codecs():
            codec = get_codec(name)
            vid = codec.capabilities.vendor_id
            assert vid in vendors, (
                f"Codec {name!r} declares vendor_id={vid!r} but no "
                f"vendor YAML with that id exists. Known vendors: "
                f"{sorted(vendors)}"
            )
