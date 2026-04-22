"""
Target-profile loader + model tests.

Covers:
  * YAML schema validation (required/optional fields)
  * Loader behaviour on malformed / duplicate / missing directories
  * Helper accessors (port_count, port_ids, lookup_port, key, display)
  * Real-profile integration: the two profiles shipped under
    ``definitions/target_profiles/`` load cleanly and expose the
    expected port inventories.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.target_profiles import (
    ProfileLoadError,
    TargetLAGCaps,
    TargetPort,
    TargetProfile,
    load_profile_file,
    load_profiles_dir,
)

pytestmark = pytest.mark.unit


class TestTargetProfileModel:
    def test_minimal_profile(self):
        p = TargetProfile(vendor="aruba_aoss", model="test")
        assert p.vendor == "aruba_aoss"
        assert p.model == "test"
        assert p.device_class.value == "switch"
        assert p.ports == []
        assert p.lags is None
        assert p.key == "aruba_aoss/test"
        assert p.display() == "aruba_aoss test"

    def test_full_profile(self):
        p = TargetProfile(
            vendor="aruba_aoss",
            model="2930F-48G",
            display_name="Aruba 2930F",
            stacking="vsf-capable",
            ports=[
                TargetPort(id="1", speed="gig", poe=True),
                TargetPort(id="2", speed="gig", poe=True),
                TargetPort(id="A1", kind="uplink", speed="10gig", sfp=True),
            ],
            lags=TargetLAGCaps(max=24, prefix="Trk"),
        )
        assert p.port_count == 3
        assert p.port_ids() == ["1", "2", "A1"]
        assert p.port_ids(kind="physical") == ["1", "2"]
        assert p.port_ids(kind="uplink") == ["A1"]
        assert p.lookup_port("1").poe is True
        assert p.lookup_port("A1").sfp is True
        assert p.lookup_port("missing") is None
        assert p.display() == "Aruba 2930F"

    def test_port_kind_enum(self):
        # Invalid kind rejected
        with pytest.raises(Exception):  # pydantic ValidationError
            TargetPort(id="1", kind="invalid-kind")

    def test_lag_capacity(self):
        caps = TargetLAGCaps(max=0, prefix="")
        assert caps.max == 0
        assert caps.prefix == ""
        with pytest.raises(Exception):  # negative max rejected
            TargetLAGCaps(max=-1)


class TestLoader:
    def test_load_missing_dir_returns_empty(self, tmp_path):
        profiles = load_profiles_dir(tmp_path / "does-not-exist")
        assert profiles == {}

    def test_load_empty_dir_returns_empty(self, tmp_path):
        profiles = load_profiles_dir(tmp_path)
        assert profiles == {}

    def test_load_single_file(self, tmp_path):
        (tmp_path / "test.yaml").write_text(
            "vendor: aruba_aoss\n"
            "model: test-24G\n"
            "ports:\n"
            "  - {id: '1', kind: physical, speed: gig}\n",
            encoding="utf-8",
        )
        profiles = load_profiles_dir(tmp_path)
        assert set(profiles) == {"aruba_aoss/test-24G"}
        assert profiles["aruba_aoss/test-24G"].port_count == 1

    def test_malformed_yaml_skipped_not_fatal(self, tmp_path, caplog):
        (tmp_path / "broken.yaml").write_text(
            "vendor: aruba_aoss\n"
            "ports:\n"
            "  - this is not valid YAML mapping:\n"
            "      -- bad\n",
            encoding="utf-8",
        )
        (tmp_path / "ok.yaml").write_text(
            "vendor: aruba_aoss\nmodel: ok\n",
            encoding="utf-8",
        )
        profiles = load_profiles_dir(tmp_path)
        # The one good file loaded.
        assert set(profiles) == {"aruba_aoss/ok"}

    def test_missing_required_field_rejected(self, tmp_path):
        # Missing ``model`` — required.
        (tmp_path / "no-model.yaml").write_text(
            "vendor: aruba_aoss\n", encoding="utf-8"
        )
        with pytest.raises(ProfileLoadError, match="schema validation"):
            load_profile_file(tmp_path / "no-model.yaml")

    def test_duplicate_key_logs_warning(self, tmp_path, caplog):
        (tmp_path / "a.yaml").write_text(
            "vendor: aruba_aoss\nmodel: test\n", encoding="utf-8"
        )
        (tmp_path / "b.yaml").write_text(
            "vendor: aruba_aoss\nmodel: test\n", encoding="utf-8"
        )
        import logging
        with caplog.at_level(logging.WARNING):
            profiles = load_profiles_dir(tmp_path)
        assert "duplicate" in caplog.text
        # Only one key, the second one wins.
        assert set(profiles) == {"aruba_aoss/test"}


class TestRangeSyntax:
    """Range shorthand in port entries.  Keeps profile YAMLs compact
    — the 48-port 2930F goes from 48 near-identical lines to one
    `{range: "1-48", ...}` entry."""

    def _write(self, tmp_path, body):
        fp = tmp_path / "p.yaml"
        fp.write_text(body, encoding="utf-8")
        return load_profile_file(fp)

    def test_bare_numeric_range(self, tmp_path):
        p = self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "1-48", kind: physical, speed: gig, poe: true}
""")
        assert p.port_count == 48
        assert p.ports[0].id == "1"
        assert p.ports[-1].id == "48"
        assert all(x.poe for x in p.ports)

    def test_prefixed_range_cisco_style(self, tmp_path):
        p = self._write(tmp_path, """
vendor: cisco_iosxe
model: t
ports:
  - {range: "GigabitEthernet1/0/1-24", kind: physical, speed: gig}
""")
        assert p.port_count == 24
        assert p.ports[0].id == "GigabitEthernet1/0/1"
        assert p.ports[-1].id == "GigabitEthernet1/0/24"

    def test_letter_prefix_range_aruba_uplink_style(self, tmp_path):
        p = self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "A1-A4", kind: uplink, speed: 10gig, sfp: true}
""")
        assert [x.id for x in p.ports] == ["A1", "A2", "A3", "A4"]
        assert all(x.kind == "uplink" for x in p.ports)

    def test_mixed_range_and_literal(self, tmp_path):
        p = self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "1-4", kind: physical, speed: gig}
  - {id: "A1", kind: uplink, speed: 10gig, sfp: true}
""")
        assert [x.id for x in p.ports] == ["1", "2", "3", "4", "A1"]
        assert p.ports[-1].kind == "uplink"

    def test_inconsistent_prefix_rejected(self, tmp_path):
        with pytest.raises(ProfileLoadError, match="inconsistent prefix"):
            self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "A1-B4", kind: uplink, speed: 10gig}
""")

    def test_start_greater_than_end_rejected(self, tmp_path):
        with pytest.raises(ProfileLoadError, match="start.* > end"):
            self._write(tmp_path, """
vendor: aruba_aoss
model: t
ports:
  - {range: "10-1", kind: physical}
""")


class TestRealProfilesShipped:
    """The YAML files under ``definitions/target_profiles/`` load
    cleanly and expose the documented port inventories.  Any breakage
    here means a published profile file was malformed."""

    REPO_PROFILES_DIR = (
        Path(__file__).resolve().parents[3]
        / "definitions" / "target_profiles"
    )

    def test_all_profiles_load(self):
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        # At least two ship with this commit.
        assert len(profiles) >= 2

    def test_aruba_2930f_48g_poep(self):
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["aruba_aoss/2930F-48G-PoEP"]
        assert p.port_count == 50  # 48 RJ45 + 2 SFP+ uplinks
        assert len(p.port_ids(kind="physical")) == 48
        assert len(p.port_ids(kind="uplink")) == 2
        assert p.lags.max == 24
        assert p.lags.prefix == "Trk"
        # Every physical port has PoE.
        for port in p.ports:
            if port.kind == "physical":
                assert port.poe is True

    def test_cisco_c9300_24ux(self):
        profiles = load_profiles_dir(self.REPO_PROFILES_DIR)
        p = profiles["cisco_iosxe/C9300-24UX"]
        assert p.port_count == 33  # 24 mGig + 8 NM + 1 mgmt
        assert len(p.port_ids(kind="physical")) == 24
        assert len(p.port_ids(kind="uplink")) == 8
        assert len(p.port_ids(kind="mgmt")) == 1
        assert p.lags.max == 48
        assert p.lags.prefix == "Port-channel"
        # First port is a mGig multigig interface.
        first = p.lookup_port("GigabitEthernet1/0/1")
        assert first is not None
        assert first.speed == "10gig"  # max negotiated speed
        assert first.poe is True
