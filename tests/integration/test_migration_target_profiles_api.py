"""
API integration tests for the Tier 3 port-rename backend.

Covers:
  * GET /api/v1/migration/target-profiles — lists loaded profiles
  * GET /api/v1/migration/target-profiles/{vendor}/{model} — by key
  * POST /api/v1/migration/plan with port_rename_map — routes to the
    rename-aware pipeline and surfaces port_renames + warnings on
    the response
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.module_variants import MODULE_VARIANT_PROFILES

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Target-profiles listing
# ---------------------------------------------------------------------------


class TestTargetProfilesList:
    def test_list_returns_shipped_profiles(self, client: TestClient):
        resp = client.get("/api/v1/migration/target-profiles")
        assert resp.status_code == 200
        data = resp.json()
        keys = {f"{p['vendor']}/{p['model']}" for p in data}
        assert "aruba_aoss/2930F-48G-PoEP" in keys
        assert "cisco_iosxe/C9300-24UX" in keys

    def test_get_by_key_returns_profile(self, client: TestClient):
        resp = client.get(
            "/api/v1/migration/target-profiles/aruba_aoss/2930F-48G-PoEP"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["vendor"] == "aruba_aoss"
        assert body["model"] == "2930F-48G-PoEP"
        # 48 + 2 uplinks.
        assert len(body["ports"]) == 50
        assert body["lags"]["max"] == 24
        assert body["lags"]["prefix"] == "Trk"

    def test_missing_profile_returns_404(self, client: TestClient):
        resp = client.get(
            "/api/v1/migration/target-profiles/aruba_aoss/NONEXISTENT"
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /plan with port_rename_map
# ---------------------------------------------------------------------------


# A minimal Cisco IOS-XE source config with enough structure to exercise
# the rename pipeline: hostname + VLAN stanzas + interface stanzas with
# physical + SVI + loopback + port-channel.
_CISCO_FIXTURE = """hostname test-sw
!
vlan 10
 name users
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet1/0/2
 channel-group 1 mode active
!
interface Port-channel1
 switchport mode trunk
 switchport trunk allowed vlan 10
!
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
!
end
"""


class TestPlanWithRenameMap:
    def test_plan_without_rename_map_is_legacy_shape(
        self, client: TestClient,
    ):
        """Legacy callers that don't send port_rename_map or
        target_profile get the original run_plan behaviour — no
        port_renames in response."""
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": _CISCO_FIXTURE,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # port_renames and warnings exist in the model but are empty
        # for legacy callers.
        assert body["port_renames"] == {}
        assert body["warnings"] == []

    def test_plan_with_target_profile_runs_auto_rename(
        self, client: TestClient,
    ):
        """target_profile alone (no explicit map) triggers the
        rename-aware pipeline; UI gets the auto-translations +
        warnings."""
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": _CISCO_FIXTURE,
                "target_profile": "aruba_aoss/2930F-48G-PoEP",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Auto-heuristic rewrote Cisco names to Aruba.
        assert "GigabitEthernet1/0/1" in body["port_renames"]
        assert body["port_renames"]["GigabitEthernet1/0/1"] == "1/1"
        assert body["port_renames"]["Port-channel1"] == "Trk1"
        # Loopback0 maps cleanly to AOS-S `loopback1` (16.04+
        # supports `interface loopback <N>`); auto-heuristic produces
        # the rewrite, no warning needed.
        assert body["port_renames"]["Loopback0"] == "loopback1"

    def test_plan_with_explicit_rename_map_wins_over_auto(
        self, client: TestClient,
    ):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": _CISCO_FIXTURE,
                "port_rename_map": {
                    "GigabitEthernet1/0/1": "1/A1",
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # User override wins.
        assert body["port_renames"]["GigabitEthernet1/0/1"] == "1/A1"
        # Other ports auto-translated.
        assert body["port_renames"]["GigabitEthernet1/0/2"] == "1/2"

    def test_rendered_output_reflects_renamed_ports(
        self, client: TestClient,
    ):
        """End-to-end proof: the rename actually hits the rendered
        output, not just the diagnostics."""
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": _CISCO_FIXTURE,
                "target_profile": "aruba_aoss/2930F-48G-PoEP",
            },
        )
        body = resp.json()
        rendered = body["rendered"] or ""
        # Aruba-style port references appear.
        assert "1/1" in rendered
        assert "Trk1" in rendered or "trunk" in rendered.lower()
        # Cisco-style names do NOT leak through.
        assert "GigabitEthernet" not in rendered
        assert "Port-channel" not in rendered


# ---------------------------------------------------------------------------
# Module-variant API surface (schema-first Option B, milestone-2a)
# ---------------------------------------------------------------------------


class TestModulesFieldSerialization:
    """GET /target-profiles must serialize the ``modules`` dict so
    the frontend can drive the third-stage module dropdown.  Legacy
    profiles expose an empty dict (UI hides the dropdown)."""

    def test_list_response_includes_modules_field(
        self, client: TestClient,
    ):
        resp = client.get("/api/v1/migration/target-profiles")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        # Every profile in the response carries the modules key —
        # even if empty — so frontend code can rely on its presence.
        for p in data:
            assert "modules" in p, (
                f"profile {p['vendor']}/{p['model']} missing 'modules' key"
            )
            assert isinstance(p["modules"], dict)

    #: Canonical allowlist imported from
    #: :mod:`tests.fixtures.module_variants` — single source of
    #: truth shared with the unit-tier shipped-profile tests.
    MODULE_VARIANT_PROFILES = MODULE_VARIANT_PROFILES

    def test_legacy_profiles_serialize_empty_modules(
        self, client: TestClient,
    ):
        """Profiles not opted-in to the module-variant schema
        must still serialize with an empty dict so pre-milestone-2
        clients keep working."""
        resp = client.get("/api/v1/migration/target-profiles")
        data = resp.json()
        for p in data:
            key = f"{p['vendor']}/{p['model']}"
            if key in self.MODULE_VARIANT_PROFILES:
                continue
            assert p["modules"] == {}, (
                f"{key} should have empty modules until it opts in "
                f"to the module-variant schema"
            )

    def test_module_variant_profile_serializes_modules_dict(
        self, client: TestClient,
    ):
        """The migrated C9300-24UX profile surfaces its NM-8X +
        NM-2Q modules as serialized dict entries so the third-stage
        UI dropdown can iterate them."""
        resp = client.get(
            "/api/v1/migration/target-profiles/cisco_iosxe/C9300-24UX"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["modules"].keys()) == {"NM-8X", "NM-2Q"}
        nm2q = body["modules"]["NM-2Q"]
        assert nm2q["sku"] == "NM-2Q"
        # 2x 40G QSFP+ uplinks.
        uplinks = [pt for pt in nm2q["ports"] if pt["kind"] == "uplink"]
        assert len(uplinks) == 2
        assert all("FortyGigabitEthernet" in pt["id"] for pt in uplinks)
        assert all(pt["speed"] == "40gig" for pt in uplinks)

    def test_get_by_key_includes_modules(self, client: TestClient):
        """Single-profile fetch must also include the modules key
        (not just the list endpoint)."""
        resp = client.get(
            "/api/v1/migration/target-profiles/aruba_aoss/2930F-48G-PoEP"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "modules" in body
        assert body["modules"] == {}


class TestMaxVlansSourceSerialization:
    """Per-vendor version-tuning provenance (``max_vlans_source``)
    ships through the API so the UI's VLAN-pane fit-check banner can
    surface a tooltip naming the FortiOS version the cap was sourced
    from.  Optional field — empty string on profiles that haven't
    been through a version-tuning pass yet."""

    def test_fortigate_profiles_surface_version_pinned_source(
        self, client: TestClient,
    ):
        """All shipped FortiGate profiles pin a specific FortiOS
        minor (e.g. ``FortiOS 7.2``) in the source string so the UI
        tooltip can explain which firmware the cap was validated
        against.  Regression guard — if a future YAML edit forgets
        the provenance, the fit-check tooltip would read "no source
        provided" which defeats the feature."""
        resp = client.get("/api/v1/migration/target-profiles")
        assert resp.status_code == 200
        data = resp.json()
        fortigate = [p for p in data if p["vendor"] == "fortigate"]
        assert len(fortigate) >= 3
        for p in fortigate:
            assert "max_vlans_source" in p, (
                f"fortigate/{p['model']}: max_vlans_source missing "
                f"from API response"
            )
            assert p["max_vlans_source"], (
                f"fortigate/{p['model']}: max_vlans_source empty "
                f"— YAML must populate it"
            )
            assert "FortiOS 7." in p["max_vlans_source"], (
                f"fortigate/{p['model']}: source should pin a "
                f"specific FortiOS minor; got "
                f"{p['max_vlans_source']!r}"
            )

    def test_unset_source_serializes_as_empty_string(
        self, client: TestClient,
    ):
        """Profiles that haven't been through a version-tuning pass
        yet (most vendors) serialize ``max_vlans_source`` as the
        empty string — NOT ``null`` / missing key.  The UI tooltip
        hides itself on empty-string, and the wire contract stays
        stable for clients that don't branch on null."""
        resp = client.get(
            "/api/v1/migration/target-profiles/aruba_aoss/2930F-48G-PoEP"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("max_vlans_source") == ""


class TestPlanAcceptsTargetModule:
    """POST /plan accepts the new ``target_module`` field without
    422-ing, even though the pipeline treats it as advisory (like
    ``target_profile``).  Once module-variant profiles ship, the
    rename modal uses ``target_module`` to filter the target-name
    dropdown to only that module's uplinks."""

    def test_target_module_accepted(self, client: TestClient):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": _CISCO_FIXTURE,
                "target_profile": "aruba_aoss/2930F-48G-PoEP",
                "target_module": "NM-8X",
            },
        )
        # Legacy profile has no NM-8X module, but the field is
        # advisory only — pipeline accepts any value without
        # complaining.
        assert resp.status_code == 200
        body = resp.json()
        # Still runs the rename-aware pipeline.
        assert body["port_renames"]  # non-empty

    def test_target_module_defaults_to_null(self, client: TestClient):
        """Unset target_module should behave identically to
        pre-milestone-2a callers — ensures we haven't introduced a
        required field."""
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": _CISCO_FIXTURE,
                "target_profile": "aruba_aoss/2930F-48G-PoEP",
            },
        )
        assert resp.status_code == 200
