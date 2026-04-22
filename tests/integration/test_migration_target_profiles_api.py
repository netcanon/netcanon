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
        # Loopback0 should produce a warning.
        warnings_text = "\n".join(body["warnings"])
        assert "Loopback0" in warnings_text or "loopback" in warnings_text

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
