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
