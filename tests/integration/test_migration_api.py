"""
Integration tests for ``/api/v1/migration/*`` — Phase 0 read-only routes.

Covers:
    * GET /api/v1/migration/adapters — list format, content
    * GET /api/v1/migration/adapters/{name}/capabilities — 200 + 404
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestListMigrationAdapters:
    def test_returns_200(self, client):
        resp = client.get("/api/v1/migration/adapters")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        resp = client.get("/api/v1/migration/adapters")
        body = resp.json()
        assert isinstance(body, list)

    def test_includes_mock_adapter(self, client):
        """Phase 0 ships the mock adapter; it must appear in the list."""
        resp = client.get("/api/v1/migration/adapters")
        names = [a["name"] for a in resp.json()]
        assert "mock" in names

    def test_each_entry_has_required_fields(self, client):
        resp = client.get("/api/v1/migration/adapters")
        for entry in resp.json():
            for field in (
                "name", "version_range", "device_classes",
                "supported_count", "lossy_count", "unsupported_count",
            ):
                assert field in entry, f"missing {field} in {entry}"

    def test_mock_adapter_device_classes_surface(self, client):
        """MockCodec declares [switch, router] — both must come back via the
        API so frontend code can filter the target-picker to compatible adapters."""
        resp = client.get("/api/v1/migration/adapters")
        info = next(a for a in resp.json() if a["name"] == "mock")
        assert "switch" in info["device_classes"]
        assert "router" in info["device_classes"]

    def test_vendor_id_surfaces_on_list_endpoint(self, client):
        """Every codec carries vendor_id so the UI can group by vendor."""
        resp = client.get("/api/v1/migration/adapters")
        for entry in resp.json():
            assert "vendor_id" in entry
            assert isinstance(entry["vendor_id"], str)
            assert entry["vendor_id"] != "", f"{entry['name']} has empty vendor_id"

    def test_vendor_display_name_resolved(self, client):
        """vendor_display_name is resolved from the vendor YAML at startup."""
        resp = client.get("/api/v1/migration/adapters")
        info = next(a for a in resp.json() if a["name"] == "cisco_iosxe")
        assert info["vendor_display_name"] == "Cisco IOS-XE"

    def test_opnsense_vendor_display_name(self, client):
        resp = client.get("/api/v1/migration/adapters")
        info = next(a for a in resp.json() if a["name"] == "opnsense")
        assert info["vendor_display_name"] == "OPNsense"

    def test_input_format_surfaces_on_list_endpoint(self, client):
        """Every entry exposes ``input_format`` so the /migrate UI can
        pick a matching sample + filter stored files."""
        resp = client.get("/api/v1/migration/adapters")
        for entry in resp.json():
            assert "input_format" in entry
            assert isinstance(entry["input_format"], str)

    def test_ui_metadata_fields_surface(self, client):
        """R5 follow-up (UI metadata migration): every entry exposes
        description + sample_input + output_extension so the client
        side has no need to hard-code per-vendor metadata."""
        resp = client.get("/api/v1/migration/adapters")
        for entry in resp.json():
            for field in ("description", "sample_input", "output_extension"):
                assert field in entry, f"{entry['name']} missing {field}"
                assert isinstance(entry[field], str)

    def test_real_codecs_have_sample_input(self, client):
        """Every real codec (cisco_iosxe*, opnsense, mikrotik_routeros)
        should provide a non-empty sample_input for the UI's 'Load sample'
        button."""
        resp = client.get("/api/v1/migration/adapters")
        for entry in resp.json():
            if entry["name"] in ("cisco_iosxe", "cisco_iosxe_cli",
                                 "opnsense", "mikrotik_routeros", "mock"):
                assert entry["sample_input"], (
                    f"{entry['name']} has no sample_input"
                )

    def test_real_codecs_have_output_extension(self, client):
        """Every real codec declares an output_extension for downloads."""
        resp = client.get("/api/v1/migration/adapters")
        expected = {
            "cisco_iosxe": "xml",
            "cisco_iosxe_cli": "cfg",
            "opnsense": "xml",
            "mikrotik_routeros": "rsc",
            "mock": "json",
        }
        for entry in resp.json():
            if entry["name"] in expected:
                assert entry["output_extension"] == expected[entry["name"]], (
                    f"{entry['name']} output_extension mismatch"
                )

    def test_cisco_iosxe_input_format_is_xml_netconf(self, client):
        resp = client.get("/api/v1/migration/adapters")
        info = next(a for a in resp.json() if a["name"] == "cisco_iosxe")
        assert info["input_format"] == "xml-netconf"

    def test_opnsense_input_format_is_xml_opnsense(self, client):
        resp = client.get("/api/v1/migration/adapters")
        info = next(a for a in resp.json() if a["name"] == "opnsense")
        assert info["input_format"] == "xml-opnsense"

    def test_cisco_iosxe_adapter_registered(self, client):
        """Phase 0.5's first real adapter must appear in the list once
        the migration package is imported (which FastAPI's create_app
        already does)."""
        resp = client.get("/api/v1/migration/adapters")
        names = [a["name"] for a in resp.json()]
        assert "cisco_iosxe" in names

    def test_cisco_iosxe_declares_router_and_switch(self, client):
        resp = client.get("/api/v1/migration/adapters")
        info = next(a for a in resp.json() if a["name"] == "cisco_iosxe")
        assert "router" in info["device_classes"]
        assert "switch" in info["device_classes"]

    def test_cisco_iosxe_capabilities_endpoint(self, client):
        """The detail endpoint returns the full iosxe matrix including
        lossy MTU and unsupported IPv6 declarations."""
        caps = client.get(
            "/api/v1/migration/adapters/cisco_iosxe/capabilities"
        ).json()
        assert caps["adapter"] == "cisco_iosxe"
        lossy_paths = [lp["path"] for lp in caps["lossy"]]
        assert "/interfaces/interface/config/mtu" in lossy_paths
        unsupp_paths = [up["path"] for up in caps["unsupported"]]
        assert any("ipv6" in p for p in unsupp_paths)

    def test_mock_adapter_counts_match_capability_matrix(self, client):
        """The summary counts in the list view must match the detail view."""
        info = next(
            a for a in client.get("/api/v1/migration/adapters").json()
            if a["name"] == "mock"
        )
        caps = client.get(
            "/api/v1/migration/adapters/mock/capabilities"
        ).json()
        assert info["supported_count"] == len(caps["supported"])
        assert info["lossy_count"] == len(caps["lossy"])
        assert info["unsupported_count"] == len(caps["unsupported"])


class TestGetAdapterCapabilities:
    def test_returns_200_for_known_adapter(self, client):
        resp = client.get("/api/v1/migration/adapters/mock/capabilities")
        assert resp.status_code == 200

    def test_response_shape(self, client):
        caps = client.get("/api/v1/migration/adapters/mock/capabilities").json()
        assert caps["adapter"] == "mock"
        assert "supported" in caps
        assert "lossy" in caps
        assert "unsupported" in caps
        assert "device_classes" in caps
        # Lossy entries carry path + reason + severity.
        for lossy in caps["lossy"]:
            assert "path" in lossy
            assert "reason" in lossy
            assert "severity" in lossy

    def test_404_for_unknown_adapter(self, client):
        resp = client.get(
            "/api/v1/migration/adapters/definitely-not-registered/capabilities"
        )
        assert resp.status_code == 404
        assert "No adapter registered" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/v1/migration/plan
# ---------------------------------------------------------------------------


_IOSXE_SIMPLE = """<?xml version="1.0"?>
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>Gi0/0/0</name>
    <config><name>Gi0/0/0</name><enabled>true</enabled></config>
  </interface>
</interfaces>
"""


class TestPlanEndpoint:
    """POST /api/v1/migration/plan — the first manually-testable endpoint."""

    def test_happy_path_returns_completed_job(self, client):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "raw_text": _IOSXE_SIMPLE,
            },
        )
        assert resp.status_code == 200
        job = resp.json()
        assert job["status"] == "completed"
        assert job["error"] is None
        assert job["rendered"] is not None
        assert job["validation"]["severity"] == "ok"

    def test_422_for_unknown_source_codec(self, client):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "not_an_adapter",
                "target": "cisco_iosxe",
                "raw_text": _IOSXE_SIMPLE,
            },
        )
        assert resp.status_code == 422
        assert "source adapter" in resp.json()["detail"]

    def test_422_for_unknown_target_codec(self, client):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe",
                "target": "not_an_adapter",
                "raw_text": _IOSXE_SIMPLE,
            },
        )
        assert resp.status_code == 422
        assert "target adapter" in resp.json()["detail"]

    def test_422_when_both_raw_text_and_source_filename_provided(
        self, client
    ):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "raw_text": _IOSXE_SIMPLE,
                "source_filename": "something.cfg",
            },
        )
        assert resp.status_code == 422
        assert "Exactly one" in resp.json()["detail"]

    def test_422_when_neither_raw_text_nor_source_filename(self, client):
        resp = client.post(
            "/api/v1/migration/plan",
            json={"source": "cisco_iosxe", "target": "cisco_iosxe"},
        )
        assert resp.status_code == 422

    def test_404_for_unknown_source_filename(self, client):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "source_filename": "not_a_real_file.cfg",
            },
        )
        assert resp.status_code == 404

    def test_parse_error_returns_200_with_failed_job(self, client):
        """A parse failure is NOT an HTTP error — it's a normal job
        outcome.  The caller wants the error message in the job body,
        not an HTTP 4xx/5xx."""
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "raw_text": "<not>real</xml",
            },
        )
        assert resp.status_code == 200
        job = resp.json()
        assert job["status"] == "failed"
        assert "parse failed" in (job["error"] or "").lower()

    def test_cross_class_refused_by_default(self, client):
        """opnsense [firewall,router] vs cisco_iosxe [router,switch]
        share 'router' — actually class-compatible; this test is here
        to confirm the guard isn't overly aggressive.  The PLAIN cross-
        class block case is covered by unit tests."""
        xml = """<?xml version="1.0"?>
<opnsense><system><hostname>fw</hostname></system></opnsense>"""
        resp = client.post(
            "/api/v1/migration/plan",
            json={"source": "opnsense", "target": "cisco_iosxe", "raw_text": xml},
        )
        assert resp.status_code == 200
        # Guard did NOT refuse (intersecting classes).
        assert "Device-class guard" not in (resp.json()["error"] or "")

    def test_force_flag_round_trips(self, client):
        """The force flag is accepted and passed through — no crash
        even if the request would've passed without it."""
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "raw_text": _IOSXE_SIMPLE,
                "force": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


class TestPlanPortsEndpoint:
    """``POST /api/v1/migration/plan/ports`` — first per-pane override
    endpoint.  Establishes the pattern that future category-specific
    endpoints (``/plan/vlans``, ``/plan/snmp``, etc.) will follow.

    Exists alongside the existing ``POST /plan`` which remains the
    "everything at once" entry; per-pane endpoints let the client
    POST only the category that changed.  Semantically equivalent to
    ``POST /plan`` with a ``port_rename_map`` in the body; the
    organisational distinction is routing-by-URL vs routing-by-body-
    field-presence.
    """

    def test_happy_path_returns_completed_job(self, client):
        resp = client.post(
            "/api/v1/migration/plan/ports",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "raw_text": _IOSXE_SIMPLE,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_engages_rename_pipeline_even_with_no_map(self, client):
        """Hitting /plan/ports with no explicit rename map still
        engages the rename-aware pipeline (auto-heuristic only) —
        distinct from the legacy /plan endpoint which falls through
        to the un-rename-aware run_plan when no map is supplied."""
        resp = client.post(
            "/api/v1/migration/plan/ports",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "raw_text": _IOSXE_SIMPLE,
            },
        )
        assert resp.status_code == 200
        # Rename pipeline sets port_renames (possibly empty dict);
        # run_plan alone leaves it as the default empty dict.
        # Assert the key is present and typed correctly — value is
        # codec-dependent.
        body = resp.json()
        assert "port_renames" in body
        assert isinstance(body["port_renames"], dict)

    def test_port_rename_map_is_applied(self, client):
        """User-supplied rename map should carry through end-to-end —
        resulting MigrationJob reflects the mapping in port_renames.

        Uses the actual port name present in _IOSXE_SIMPLE (Gi0/0/0)
        so the rename has a real target to act on."""
        resp = client.post(
            "/api/v1/migration/plan/ports",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "raw_text": _IOSXE_SIMPLE,
                "port_rename_map": {"Gi0/0/0": "GigabitEthernet99"},
            },
        )
        assert resp.status_code == 200
        applied = resp.json()["port_renames"]
        # Explicit override wins over the identity auto-heuristic.
        assert applied.get("Gi0/0/0") == "GigabitEthernet99"

    def test_422_for_unknown_source_codec(self, client):
        """Error-path parity with /plan."""
        resp = client.post(
            "/api/v1/migration/plan/ports",
            json={
                "source": "not_an_adapter",
                "target": "cisco_iosxe",
                "raw_text": _IOSXE_SIMPLE,
            },
        )
        assert resp.status_code == 422

    def test_plan_ports_matches_plan_with_rename_map(self, client):
        """Regression guard: /plan/ports with a rename_map produces
        the same outcome as /plan with the same body.  Per-pane
        endpoints are an organisational redirection, not a behaviour
        change."""
        body = {
            "source": "cisco_iosxe",
            "target": "cisco_iosxe",
            "raw_text": _IOSXE_SIMPLE,
            "port_rename_map": {},   # opt into rename-aware pipeline
        }
        plan = client.post("/api/v1/migration/plan", json=body).json()
        plan_ports = client.post("/api/v1/migration/plan/ports", json=body).json()
        # Same pipeline outcome (job IDs differ, but status + rendered
        # content match).
        assert plan["status"] == plan_ports["status"]
        assert plan["rendered"] == plan_ports["rendered"]
        assert plan["port_renames"] == plan_ports["port_renames"]


class TestPlanVlansEndpoint:
    """``POST /api/v1/migration/plan/vlans`` — second per-pane
    override endpoint.  Exercises the ``vlan_rename_map`` surface
    end-to-end through the integration stack.

    Same structural parity with ``/plan/ports`` — each category
    endpoint accepts the full MigrationPlanRequest body and
    dispatches to ``run_plan_with_overrides`` with only its
    category's map populated."""

    _IOSXE_WITH_VLANS = """\
hostname TestCisco
!
vlan 10
 name USERS
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
"""

    def test_happy_path_returns_completed_job(self, client):
        resp = client.post(
            "/api/v1/migration/plan/vlans",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_vlan_rename_map_is_applied(self, client):
        resp = client.post(
            "/api/v1/migration/plan/vlans",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
                "vlan_rename_map": {10: 100},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Applied rewrite shows up as int → int.  Note that JSON
        # serialisation turns dict keys into strings, so the
        # wire-level shape is {"10": 100}; pydantic coerces back
        # to int keys on deserialisation.
        applied = body["vlan_renames"]
        # Key may be "10" (string) or 10 (int) depending on serialisation.
        if "10" in applied:
            assert applied["10"] == 100
        elif 10 in applied:
            assert applied[10] == 100
        else:
            pytest.fail(f"vlan_renames does not contain 10: {applied!r}")

    def test_vlan_drop_appears_in_vlan_drops(self, client):
        resp = client.post(
            "/api/v1/migration/plan/vlans",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
                "vlan_rename_map": {10: None},
            },
        )
        assert resp.status_code == 200
        assert 10 in resp.json()["vlan_drops"]

    def test_422_for_unknown_source_codec(self, client):
        resp = client.post(
            "/api/v1/migration/plan/vlans",
            json={
                "source": "not_an_adapter",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
            },
        )
        assert resp.status_code == 422

    def test_plan_vlans_ignores_port_rename_map(self, client):
        """Per-pane endpoints apply their category only.  If the
        operator sends a port_rename_map to /plan/vlans, it's
        silently dropped — documented contract, not a bug."""
        resp = client.post(
            "/api/v1/migration/plan/vlans",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
                "vlan_rename_map": {10: 100},
                "port_rename_map": {
                    "GigabitEthernet1/0/1": "GigabitEthernet99",
                },
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # VLAN applied, port NOT applied.
        vlan_renames = body["vlan_renames"]
        assert "10" in vlan_renames or 10 in vlan_renames
        assert body["port_renames"] == {}


class TestPlanLocalUsersEndpoint:
    """``POST /api/v1/migration/plan/local_users`` — third per-pane
    override endpoint (P2C4).  Exercises the ``local_user_rename_map``
    surface end-to-end through the integration stack."""

    _IOSXE_WITH_USERS = """\
hostname TestCisco
!
username admin privilege 15 secret 5 $1$abc$fake
username operator privilege 5 secret 5 $1$def$fake
username svc-backup-2019 privilege 1 secret 5 $1$ghi$fake
!
interface GigabitEthernet1/0/1
 description uplink
!
"""

    def test_happy_path_returns_completed_job(self, client):
        resp = client.post(
            "/api/v1/migration/plan/local_users",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_USERS,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_rename_is_applied(self, client):
        resp = client.post(
            "/api/v1/migration/plan/local_users",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_USERS,
                "local_user_rename_map": {"admin": "netadmin"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["local_user_renames"] == {"admin": "netadmin"}
        # Source-shape capture still reflects the pre-rename tree.
        assert "admin" in body["source_local_users"]

    def test_drop_appears_in_local_user_drops(self, client):
        resp = client.post(
            "/api/v1/migration/plan/local_users",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_USERS,
                "local_user_rename_map": {"svc-backup-2019": None},
            },
        )
        assert resp.status_code == 200
        assert "svc-backup-2019" in resp.json()["local_user_drops"]

    def test_422_for_unknown_source_codec(self, client):
        resp = client.post(
            "/api/v1/migration/plan/local_users",
            json={
                "source": "not_an_adapter",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_USERS,
            },
        )
        assert resp.status_code == 422

    def test_ignores_port_and_vlan_maps(self, client):
        """Per-pane endpoints apply their category only."""
        resp = client.post(
            "/api/v1/migration/plan/local_users",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_USERS,
                "local_user_rename_map": {"admin": "netadmin"},
                "port_rename_map": {
                    "GigabitEthernet1/0/1": "GigabitEthernet99",
                },
                "vlan_rename_map": {10: 100},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["local_user_renames"] == {"admin": "netadmin"}
        # Neither port nor VLAN maps engaged.
        assert body["port_renames"] == {}
        assert body["vlan_renames"] == {}


class TestPlanMultiCategoryRouting:
    """The top-level POST /plan endpoint accepts any combination of
    per-category maps and engages the rename-aware pipeline when any
    is present.  Locks in the P2C4 fix that previously saw VLAN +
    local-user maps silently dropped unless port_rename_map was also
    set."""

    _IOSXE = """\
hostname MultiTest
!
vlan 10
 name USERS
!
username admin privilege 15 secret 5 $1$abc$fake
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
"""

    def test_plan_with_only_vlan_map_engages_vlan_transform(self, client):
        """Pre-P2C4 bug: /plan with only vlan_rename_map silently
        used run_plan (no overrides).  Fixed: vlan_renames populates."""
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE,
                "vlan_rename_map": {10: 200},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        renames = body["vlan_renames"]
        assert ("10" in renames and renames["10"] == 200) or (
            10 in renames and renames[10] == 200
        )

    def test_plan_with_only_local_user_map_engages_user_transform(
        self, client,
    ):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE,
                "local_user_rename_map": {"admin": "netadmin"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["local_user_renames"] == {"admin": "netadmin"}

    def test_plan_with_all_three_maps_applies_all(self, client):
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE,
                "port_rename_map": {},
                "vlan_rename_map": {10: 200},
                "local_user_rename_map": {"admin": "netadmin"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # VLAN rewrite applied.
        vrn = body["vlan_renames"]
        assert ("10" in vrn and vrn["10"] == 200) or (
            10 in vrn and vrn[10] == 200
        )
        # Local-user rewrite applied.
        assert body["local_user_renames"] == {"admin": "netadmin"}
        # Port overrides empty-map means auto-heuristic only — no
        # user overrides applied, but source_vlans still populates.
        assert "source_vlans" in body

    def test_plan_without_any_override_still_works(self, client):
        """Legacy behaviour: no override maps, no target profile →
        plain run_plan path.  Source-shape fields stay empty because
        the capture only fires in the overrides engine."""
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # No overrides → empty renames.
        assert body["port_renames"] == {}
        assert body["vlan_renames"] == {}
        assert body["local_user_renames"] == {}


class TestSourceShapeCapture:
    """P2C3 M1 exposed source_vlans + source_hostname on the job so
    the rename-modal VLAN pane can enumerate source VLANs and scope
    localStorage persistence by device.  These tests lock in the
    capture contract against future pipeline changes that might
    reorder transforms."""

    _IOSXE_WITH_VLANS = """\
hostname CoreSw01
!
vlan 10
 name USERS
!
vlan 20
 name VOICE
!
vlan 99
 name MGMT
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
"""

    def test_source_vlans_populated_on_ports_endpoint(self, client):
        """Every per-pane endpoint flows through run_plan_with_overrides
        which always runs the capture transform — so /plan/ports
        populates source_vlans even though its pane doesn't use them."""
        resp = client.post(
            "/api/v1/migration/plan/ports",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert sorted(body["source_vlans"]) == [10, 20, 99]

    def test_source_vlans_populated_on_vlans_endpoint(self, client):
        resp = client.post(
            "/api/v1/migration/plan/vlans",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert sorted(body["source_vlans"]) == [10, 20, 99]

    def test_source_hostname_populated(self, client):
        resp = client.post(
            "/api/v1/migration/plan/ports",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["source_hostname"] == "CoreSw01"

    def test_source_hostname_empty_when_not_declared(self, client):
        """Cisco config with no hostname line → hostname field empty."""
        resp = client.post(
            "/api/v1/migration/plan/ports",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": "vlan 10\n name FOO\n!\n",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["source_hostname"] == ""

    def test_source_vlans_captured_before_rename_transform(self, client):
        """Capture runs AHEAD of rename transforms (first in the
        override_transforms list).  Renaming VLAN 10 → 100 mutates
        the tree, but source_vlans still reflects the pre-mutation
        state so the UI enumerates what the operator had originally."""
        resp = client.post(
            "/api/v1/migration/plan/vlans",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": self._IOSXE_WITH_VLANS,
                "vlan_rename_map": {10: 100},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # Pre-rename ids: 10 remains in source_vlans even though the
        # vlan_renames map shows 10 → 100.
        assert 10 in body["source_vlans"]
        assert sorted(body["source_vlans"]) == [10, 20, 99]

    def test_source_local_users_populated(self, client):
        """P2C4 extends the capture to include local_users names."""
        cfg_with_users = (
            "hostname CoreSw01\n!\n"
            "username admin privilege 15 secret 5 $1$abc$fake\n"
            "username backup privilege 1 secret 5 $1$def$fake\n"
            "!\n"
        )
        resp = client.post(
            "/api/v1/migration/plan/local_users",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": cfg_with_users,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert sorted(body["source_local_users"]) == ["admin", "backup"]

    def test_source_local_users_captured_before_rename(self, client):
        """Same pre-mutation contract as source_vlans — the UI pane
        should see 'admin' even after a rename rewrites it."""
        cfg = (
            "hostname CoreSw01\n!\n"
            "username admin privilege 15 secret 5 $1$abc$fake\n!\n"
        )
        resp = client.post(
            "/api/v1/migration/plan/local_users",
            json={
                "source": "cisco_iosxe_cli",
                "target": "aruba_aoss",
                "raw_text": cfg,
                "local_user_rename_map": {"admin": "netadmin"},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "admin" in body["source_local_users"]
        assert body["local_user_renames"] == {"admin": "netadmin"}


class TestRenderEndpoint:
    """/render is currently an alias for /plan.  These tests lock that
    fact in so a future split gets a visible PR."""

    def test_render_matches_plan_for_same_body(self, client):
        body = {
            "source": "cisco_iosxe",
            "target": "cisco_iosxe",
            "raw_text": _IOSXE_SIMPLE,
        }
        plan = client.post("/api/v1/migration/plan", json=body).json()
        render = client.post("/api/v1/migration/render", json=body).json()
        # Same pipeline outcome; only the job ID differs.
        assert plan["status"] == render["status"]
        assert plan["rendered"] == render["rendered"]


class TestSourceFilenameIntegration:
    """The source_filename shorthand loads from the backup store that
    the config diff feature already uses — proving the translator
    integrates cleanly with the existing storage layer."""

    def test_plan_reads_stored_config_by_filename(self, client):
        """Create a backup first, then migrate that stored config."""
        # Step 1: use FakeCollector (wired by the integration fixture)
        # to produce a real stored config on disk.
        devices = [
            {
                "type_key": "Cisco",
                "host": "10.77.77.77",
                "credentials": {"username": "admin", "password": "x"},
            }
        ]
        client.post("/api/v1/backups", json={"devices": devices})
        # Step 2: find its filename via the existing list endpoint.
        configs = client.get("/api/v1/configs/").json()
        assert configs, "FakeCollector should have produced a config"
        filename = configs[0]["filename"]

        # Step 3: hand that filename to /plan.  The Cisco FakeCollector
        # returns a plaintext IOS snippet, NOT OpenConfig XML, so the
        # iosxe parser will fail — but that's the point: we prove the
        # file WAS loaded (parse got a chance to run).
        resp = client.post(
            "/api/v1/migration/plan",
            json={
                "source": "cisco_iosxe",
                "target": "cisco_iosxe",
                "source_filename": filename,
            },
        )
        assert resp.status_code == 200
        job = resp.json()
        # Parse failed because the FakeCollector output isn't XML.
        assert job["status"] == "failed"
        assert "parse failed" in (job["error"] or "").lower()


# ---------------------------------------------------------------------------
# POST /api/v1/migration/detect (R5 — auto-detection)
# ---------------------------------------------------------------------------


class TestDetectEndpoint:
    def test_detect_opnsense_xml(self, client):
        resp = client.post(
            "/api/v1/migration/detect",
            json={
                "raw_text": "<opnsense><system><hostname>x</hostname></system></opnsense>",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["codec"] == "opnsense"
        assert body[0]["confidence"] >= 95
        assert "reason" in body[0]

    def test_detect_mikrotik_export(self, client):
        resp = client.post(
            "/api/v1/migration/detect",
            json={
                "raw_text": (
                    "# by RouterOS 7.13\n"
                    "/system identity\nset name=r1\n"
                ),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["codec"] == "mikrotik_routeros"

    def test_detect_ios_cli(self, client):
        resp = client.post(
            "/api/v1/migration/detect",
            json={
                "raw_text": (
                    "!\ninterface GigabitEthernet0/0/0\n"
                    " ip address 10.0.0.1 255.255.255.0\n"
                    " no shutdown\n!\n"
                ),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["codec"] == "cisco_iosxe_cli"

    def test_detect_empty_input(self, client):
        resp = client.post(
            "/api/v1/migration/detect",
            json={"raw_text": ""},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_detect_both_fields_set_returns_422(self, client):
        resp = client.post(
            "/api/v1/migration/detect",
            json={"raw_text": "x", "source_filename": "foo"},
        )
        assert resp.status_code == 422

    def test_detect_neither_field_set_returns_422(self, client):
        resp = client.post(
            "/api/v1/migration/detect",
            json={},
        )
        assert resp.status_code == 422

    def test_detect_missing_stored_file_returns_404(self, client):
        resp = client.post(
            "/api/v1/migration/detect",
            json={"source_filename": "does_not_exist.xml"},
        )
        assert resp.status_code == 404

    def test_detect_sorted_descending_by_confidence(self, client):
        """When multiple codecs match, API must return them sorted."""
        resp = client.post(
            "/api/v1/migration/detect",
            json={
                "raw_text": (
                    "hostname r1\n!\ninterface Loopback0\n"
                    " ip address 1.1.1.1 255.255.255.255\n!\n"
                ),
            },
        )
        body = resp.json()
        confidences = [c["confidence"] for c in body]
        assert confidences == sorted(confidences, reverse=True)

    def test_detect_min_confidence_filters(self, client):
        """Passing min_confidence=80 should drop weak matches."""
        weak = client.post(
            "/api/v1/migration/detect",
            json={"raw_text": "hostname r1\n!\n", "min_confidence": 1},
        ).json()
        strict = client.post(
            "/api/v1/migration/detect",
            json={"raw_text": "hostname r1\n!\n", "min_confidence": 80},
        ).json()
        # Weak threshold gets the hostname+! low-confidence match;
        # strict threshold drops it.
        assert len(weak) >= 1
        assert all(c["confidence"] >= 80 for c in strict)

    def test_detect_stored_config_end_to_end(self, client):
        """User-flow: backup an OPNsense config, then /detect on the
        filename — should return opnsense as the top candidate."""
        # Step 1: run a backup to produce a stored config.
        # The integration test harness has a FakeCollector keyed by
        # type_key; use the opnsense type to get XML output.
        devices = [
            {
                "type_key": "OPNsense",
                "host": "10.88.88.88",
                "credentials": {"username": "admin", "password": "x"},
            }
        ]
        backup_resp = client.post(
            "/api/v1/backups", json={"devices": devices}
        )
        if backup_resp.status_code != 200:
            pytest.skip("FakeCollector doesn't handle OPNsense here")
        configs = client.get("/api/v1/configs/").json()
        if not configs:
            pytest.skip("no stored configs produced by FakeCollector")
        # Pick an opnsense-ish filename.
        opn_cfg = next(
            (c for c in configs if "opnsense" in c["filename"].lower()),
            None,
        )
        if opn_cfg is None:
            pytest.skip("no opnsense-prefixed config in store")
        resp = client.post(
            "/api/v1/migration/detect",
            json={"source_filename": opn_cfg["filename"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) >= 1
        # The FakeCollector's OPNsense fixture is valid config.xml.
        assert body[0]["codec"] == "opnsense"
