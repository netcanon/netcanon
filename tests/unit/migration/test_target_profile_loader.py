"""
Target-profile loader tests.

Covers YAML-reading behaviour:
  * :func:`load_profile_file` / :func:`load_profiles_dir` —
    malformed / duplicate / missing-directory semantics.
  * Range-shorthand expansion in the ``ports:`` list (bare numeric,
    letter-prefix uplink, Cisco-style prefix, inconsistent-prefix
    rejection, start>end rejection, mixed range + literal).
  * Module-variant YAML loader — range expansion inside
    ``modules[sku].ports`` and automatic ``sku`` backfill from the
    dict key.

Pure model validation (no YAML) lives in
``test_target_profile_schema.py``; per-YAML assertions on the
profiles shipped under ``definitions/target_profiles/`` live in
``test_target_profile_shipped.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.target_profiles import (
    ProfileLoadError,
    TargetLAGCaps,
    TargetModule,
    TargetPort,
    TargetProfile,
    load_profile_file,
    load_profiles_dir,
)

pytestmark = pytest.mark.unit


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


class TestProfileWithModulesLoader:
    """YAML loader support for the ``modules:`` key."""

    def _write(self, tmp_path: Path, body: str) -> TargetProfile:
        fp = tmp_path / "p.yaml"
        fp.write_text(body, encoding="utf-8")
        return load_profile_file(fp)

    def test_module_ports_with_range_shorthand(self, tmp_path):
        p = self._write(tmp_path, """
vendor: cisco_iosxe
model: C9300-24UX
ports:
  - {range: "GigabitEthernet1/0/1-24", kind: physical, speed: 10gig}
modules:
  NM-8X:
    description: "8x 10G SFP+"
    ports:
      - {range: "TenGigabitEthernet1/1/1-8", kind: uplink, speed: 10gig, sfp: true}
  NM-2Q:
    description: "2x 40G QSFP+"
    ports:
      - {range: "FortyGigabitEthernet1/1/1-2", kind: uplink, speed: 40gig, sfp: true}
""")
        assert p.port_count == 24
        assert p.has_modules
        assert set(p.module_skus()) == {"NM-8X", "NM-2Q"}
        nm8x = p.modules["NM-8X"]
        assert len(nm8x.ports) == 8
        assert nm8x.ports[0].id == "TenGigabitEthernet1/1/1"
        assert nm8x.ports[-1].id == "TenGigabitEthernet1/1/8"
        nm2q = p.modules["NM-2Q"]
        assert len(nm2q.ports) == 2
        assert nm2q.ports[0].id == "FortyGigabitEthernet1/1/1"

    def test_module_sku_backfilled_from_dict_key(self, tmp_path):
        """Authors can omit the ``sku:`` field under each module —
        the dict key is the source of truth."""
        p = self._write(tmp_path, """
vendor: v
model: m
modules:
  NM-8X:
    description: "8x 10G"
    ports: []
""")
        assert p.modules["NM-8X"].sku == "NM-8X"

    def test_explicit_module_sku_wins_over_dict_key(self, tmp_path):
        """If the author set ``sku:`` explicitly we respect it, so
        authors can use alias keys (e.g. friendly URL slug) while
        keeping the part-number SKU."""
        p = self._write(tmp_path, """
vendor: v
model: m
modules:
  nm8x:
    sku: "NM-8X"
    description: "8x 10G"
    ports: []
""")
        assert p.modules["nm8x"].sku == "NM-8X"

    def test_module_not_mapping_rejected(self, tmp_path):
        with pytest.raises(ProfileLoadError, match="must be a mapping"):
            self._write(tmp_path, """
vendor: v
model: m
modules:
  NM-8X: "this should be a mapping not a string"
""")

    def test_module_range_error_identifies_module(self, tmp_path):
        with pytest.raises(ProfileLoadError, match=r"module 'NM-8X'"):
            self._write(tmp_path, """
vendor: v
model: m
modules:
  NM-8X:
    ports:
      - {range: "TenGig1/1/10-1", kind: uplink}
""")

    def test_no_modules_key_stays_legacy(self, tmp_path):
        p = self._write(tmp_path, """
vendor: aruba_aoss
model: 2930F
ports:
  - {range: "1-48", kind: physical, speed: gig}
""")
        assert p.modules == {}
        assert p.has_modules is False
        # effective_ports with no arg returns base ports only.
        assert len(p.effective_ports()) == 48

    def test_empty_modules_dict_stays_legacy(self, tmp_path):
        p = self._write(tmp_path, """
vendor: v
model: m
ports: []
modules: {}
""")
        assert p.has_modules is False
        assert p.default_module_sku() is None

    def test_module_round_trips_through_api_serialization(self, tmp_path):
        """The serialized JSON shape must preserve the ``modules:``
        dict — that's what the GET /target-profiles response
        depends on.  This smoke-tests the pydantic round-trip."""
        p = self._write(tmp_path, """
vendor: cisco_iosxe
model: C9300-24UX
ports:
  - {range: "GigabitEthernet1/0/1-2", kind: physical}
modules:
  NM-2Q:
    description: "2x 40G QSFP+"
    ports:
      - {id: "FortyGigabitEthernet1/1/1", kind: uplink, speed: 40gig}
""")
        dumped = p.model_dump()
        assert "modules" in dumped
        assert "NM-2Q" in dumped["modules"]
        assert dumped["modules"]["NM-2Q"]["ports"][0]["id"] == (
            "FortyGigabitEthernet1/1/1"
        )
        # Legacy field remains populated and distinct from module ports.
        assert len(dumped["ports"]) == 2
        # Rehydrate and verify behaviour survives.
        p2 = TargetProfile.model_validate(dumped)
        assert p2.default_module_sku() == "NM-2Q"
        assert len(p2.effective_ports("NM-2Q")) == 3
