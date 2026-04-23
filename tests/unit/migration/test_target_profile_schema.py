"""
Target-profile schema tests.

Covers the pure-pydantic surface:
  * :class:`TargetProfile` / :class:`TargetPort` / :class:`TargetModule`
    / :class:`TargetLAGCaps` validation (required / optional fields).
  * Helper accessors on :class:`TargetProfile`
    (``port_count``, ``port_ids``, ``lookup_port``, ``key``,
    ``display``, ``has_modules``, ``effective_ports`` / …_port_count,
    ``default_module_sku``).

No YAML is loaded here — see ``test_target_profile_loader.py``
for loader + range-shorthand behaviour, and
``test_target_profile_shipped.py`` for per-YAML assertions on the
profiles that ship under ``definitions/target_profiles/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netconfig.migration.target_profiles import (
    ProfileLoadError,
    TargetLAGCaps,
    TargetModule,
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


class TestTargetModuleModel:
    """The :class:`TargetModule` shape on its own."""

    def test_minimal_module(self):
        m = TargetModule()
        assert m.sku == ""
        assert m.description == ""
        assert m.ports == []

    def test_full_module(self):
        m = TargetModule(
            sku="NM-8X",
            description="8x 10G SFP+ uplinks",
            ports=[
                TargetPort(
                    id="TenGigabitEthernet1/1/1",
                    kind="uplink",
                    speed="10gig",
                    sfp=True,
                )
            ],
        )
        assert m.sku == "NM-8X"
        assert m.description.startswith("8x 10G")
        assert len(m.ports) == 1
        assert m.ports[0].kind == "uplink"


class TestProfileWithModules:
    """Semantics of :class:`TargetProfile` when ``modules:`` is set."""

    def _build_dual_module_profile(self) -> TargetProfile:
        """Minimal chassis + two module variants.  Used by several
        tests to avoid repeating the fixture."""
        return TargetProfile(
            vendor="cisco_iosxe",
            model="C9300-24UX",
            ports=[
                TargetPort(id="GigabitEthernet1/0/1", kind="physical"),
                TargetPort(id="GigabitEthernet1/0/2", kind="physical"),
                TargetPort(id="GigabitEthernet0/0", kind="mgmt"),
            ],
            modules={
                "NM-8X": TargetModule(
                    sku="NM-8X",
                    description="8x 10G SFP+",
                    ports=[
                        TargetPort(
                            id=f"TenGigabitEthernet1/1/{n}",
                            kind="uplink",
                            speed="10gig",
                            sfp=True,
                        )
                        for n in range(1, 9)
                    ],
                ),
                "NM-2Q": TargetModule(
                    sku="NM-2Q",
                    description="2x 40G QSFP+",
                    ports=[
                        TargetPort(
                            id="FortyGigabitEthernet1/1/1",
                            kind="uplink",
                            speed="40gig",
                            sfp=True,
                        ),
                        TargetPort(
                            id="FortyGigabitEthernet1/1/2",
                            kind="uplink",
                            speed="40gig",
                            sfp=True,
                        ),
                    ],
                ),
            },
        )

    def test_has_modules(self):
        p = self._build_dual_module_profile()
        assert p.has_modules is True
        assert set(p.module_skus()) == {"NM-8X", "NM-2Q"}

    def test_default_module_sku_prefers_literal_default(self):
        p = TargetProfile(
            vendor="v", model="m",
            modules={
                "OTHER": TargetModule(sku="OTHER"),
                "default": TargetModule(sku="default"),
            },
        )
        # "default" wins even though inserted second.
        assert p.default_module_sku() == "default"

    def test_default_module_sku_falls_back_to_first_inserted(self):
        p = self._build_dual_module_profile()
        # NM-8X was inserted first.
        assert p.default_module_sku() == "NM-8X"

    def test_default_module_sku_none_when_no_modules(self):
        p = TargetProfile(vendor="v", model="m")
        assert p.default_module_sku() is None

    def test_effective_ports_merges_base_and_module(self):
        p = self._build_dual_module_profile()
        # Base has 3 (2 physical + 1 mgmt); NM-8X adds 8.
        eff = p.effective_ports("NM-8X")
        assert len(eff) == 11
        # NM-2Q adds 2 instead — chassis ports are identical.
        eff_q = p.effective_ports("NM-2Q")
        assert len(eff_q) == 5
        # First 3 of eff_q are the same chassis ports as eff.
        assert eff_q[:3] == eff[:3]

    def test_effective_ports_defaults_to_default_sku(self):
        p = self._build_dual_module_profile()
        # No arg → uses default_module_sku() ("NM-8X" here).
        assert p.effective_ports() == p.effective_ports("NM-8X")

    def test_effective_ports_unknown_sku_falls_back_to_base(self):
        p = self._build_dual_module_profile()
        eff = p.effective_ports("NM-DOES-NOT-EXIST")
        # Unknown SKU → base ports only (no crash, no module contrib).
        assert eff == list(p.ports)

    def test_effective_ports_legacy_profile_ignores_module_arg(self):
        p = TargetProfile(
            vendor="v", model="m",
            ports=[TargetPort(id="1"), TargetPort(id="2")],
        )
        # Legacy profile — any module arg just returns base ports.
        assert p.effective_ports("anything") == list(p.ports)

    def test_port_ids_accepts_module_sku(self):
        p = self._build_dual_module_profile()
        uplinks_8x = p.port_ids(kind="uplink", module_sku="NM-8X")
        uplinks_2q = p.port_ids(kind="uplink", module_sku="NM-2Q")
        assert len(uplinks_8x) == 8
        assert len(uplinks_2q) == 2
        assert uplinks_8x[0].startswith("TenGigabitEthernet")
        assert uplinks_2q[0].startswith("FortyGigabitEthernet")
        # Physical filter is module-independent — chassis-fixed.
        phys_8x = p.port_ids(kind="physical", module_sku="NM-8X")
        phys_2q = p.port_ids(kind="physical", module_sku="NM-2Q")
        assert phys_8x == phys_2q

    def test_lookup_port_crosses_base_and_module(self):
        p = self._build_dual_module_profile()
        # Chassis port resolvable regardless of module.
        assert p.lookup_port("GigabitEthernet1/0/1") is not None
        assert (
            p.lookup_port("GigabitEthernet1/0/1", module_sku="NM-2Q")
            is not None
        )
        # Module uplink resolvable only with that module selected.
        assert (
            p.lookup_port("FortyGigabitEthernet1/1/1", module_sku="NM-2Q")
            is not None
        )
        assert (
            p.lookup_port("FortyGigabitEthernet1/1/1", module_sku="NM-8X")
            is None
        )

    def test_port_count_excludes_modules(self):
        """``port_count`` is the base (chassis-fixed) count — use
        ``effective_port_count(sku)`` to include module uplinks.
        Kept separate so UI code that only wants chassis info
        (e.g. "this is a 48-port switch") doesn't accidentally
        double-count."""
        p = self._build_dual_module_profile()
        assert p.port_count == 3
        assert p.effective_port_count("NM-8X") == 11
        assert p.effective_port_count("NM-2Q") == 5

    def test_legacy_accessors_stay_backcompat(self):
        """Existing callers that pass only ``kind`` (no
        ``module_sku``) MUST keep getting the pre-modules
        behaviour.  This guards all pre-B call sites."""
        p = TargetProfile(
            vendor="v", model="m",
            ports=[
                TargetPort(id="1", kind="physical"),
                TargetPort(id="A1", kind="uplink"),
            ],
        )
        assert p.port_ids() == ["1", "A1"]
        assert p.port_ids(kind="physical") == ["1"]
        assert p.port_ids(kind="uplink") == ["A1"]
        assert p.lookup_port("1").kind == "physical"


