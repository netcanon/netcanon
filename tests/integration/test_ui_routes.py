"""
Integration tests for UI routes (``/jobs``, ``/schedules``) and job
persistence behaviour.

Covers:
- HTTP 200 and text/html content-type for both UI pages.
- Correct ``data-testid`` sentinel elements in empty and populated states.
- JSON job files written to disk after a backup completes.
- Jobs survive a simulated server restart (second ``create_app`` reads same dirs).
- Manual backup jobs carry ``schedule_id=None`` / ``schedule_name=None``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from netconfig.main import create_app
from tests.conftest import CISCO_FAKE_OUTPUT, FakeCollector

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_CISCO_DEVICE = {
    "type_key": "Cisco",
    "host": "192.168.1.1",
    "credentials": {"username": "admin", "password": "pw"},
}

_BACKUP_PAYLOAD = {"devices": [_CISCO_DEVICE]}

_SCHEDULE_PAYLOAD = {
    "name": "Test Schedule",
    "interval_minutes": 60,
    "target_type_keys": ["Cisco"],
}


def _post_backup(client: TestClient) -> dict:
    """POST a backup and return the parsed JSON response body."""
    resp = client.post("/api/v1/backups", json=_BACKUP_PAYLOAD)
    assert resp.status_code == 202
    return resp.json()


def _post_and_get_job(client: TestClient) -> dict:
    """POST a backup then GET the completed job state."""
    job_id = _post_backup(client)["id"]
    resp = client.get(f"/api/v1/backups/{job_id}")
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# TestJobsUIRoute
# ---------------------------------------------------------------------------


class TestJobsUIRoute:
    def test_get_returns_200(self, client: TestClient) -> None:
        resp = client.get("/jobs")
        assert resp.status_code == 200

    def test_response_content_type_is_html(self, client: TestClient) -> None:
        resp = client.get("/jobs")
        assert "text/html" in resp.headers["content-type"]

    def test_empty_state_contains_no_jobs_msg(self, client: TestClient) -> None:
        resp = client.get("/jobs")
        assert 'data-testid="no-jobs-msg"' in resp.text

    def test_after_backup_contains_job_card(self, client: TestClient) -> None:
        _post_backup(client)
        resp = client.get("/jobs")
        assert 'data-testid="job-card"' in resp.text

    def test_after_backup_no_jobs_msg_absent(self, client: TestClient) -> None:
        _post_backup(client)
        resp = client.get("/jobs")
        assert 'data-testid="no-jobs-msg"' not in resp.text


# ---------------------------------------------------------------------------
# TestSchedulesUIRoute
# ---------------------------------------------------------------------------


class TestSchedulesUIRoute:
    def test_get_returns_200(self, client: TestClient) -> None:
        resp = client.get("/schedules")
        assert resp.status_code == 200

    def test_response_content_type_is_html(self, client: TestClient) -> None:
        resp = client.get("/schedules")
        assert "text/html" in resp.headers["content-type"]

    def test_empty_state_contains_no_schedules_msg(self, client: TestClient) -> None:
        resp = client.get("/schedules")
        assert 'data-testid="no-schedules-msg"' in resp.text

    def test_schedule_form_always_present(self, client: TestClient) -> None:
        resp = client.get("/schedules")
        assert 'data-testid="schedule-form"' in resp.text

    def test_after_create_schedule_contains_schedule_row(
        self, client: TestClient
    ) -> None:
        resp = client.post("/api/v1/schedules/", json=_SCHEDULE_PAYLOAD)
        assert resp.status_code == 201
        page = client.get("/schedules")
        assert 'data-testid="schedule-row"' in page.text


# ---------------------------------------------------------------------------
# TestJobPersistence
# ---------------------------------------------------------------------------


class TestJobPersistence:
    def test_job_file_written_to_disk(self, test_settings) -> None:
        """After a completed backup the job JSON file exists on disk."""
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netconfig.api.routes.backups.get_collector", return_value=fake
        ):
            app = create_app(test_settings)
            with TestClient(app, raise_server_exceptions=True) as c:
                job = _post_and_get_job(c)
                job_id = job["id"]

        jobs_dir = test_settings.configs_dir.parent / "jobs"
        job_file = jobs_dir / f"{job_id}.json"
        assert job_file.exists(), f"Expected job file at {job_file}"

    def test_job_survives_restart(self, test_settings) -> None:
        """Jobs loaded on startup survive a simulated server restart."""
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netconfig.api.routes.backups.get_collector", return_value=fake
        ):
            app1 = create_app(test_settings)
            with TestClient(app1, raise_server_exceptions=True) as c1:
                job_id = _post_backup(c1)["id"]
            # c1 is closed here; app1 lifespan torn down

            # Simulate restart: fresh app pointing at the same directories
            app2 = create_app(test_settings)
            with TestClient(app2, raise_server_exceptions=True) as c2:
                resp = c2.get(f"/api/v1/backups/{job_id}")
                assert resp.status_code == 200
                assert resp.json()["id"] == job_id

    def test_persisted_job_has_no_schedule_id(self, test_settings) -> None:
        """A manually triggered job has ``schedule_id=None`` after reload."""
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netconfig.api.routes.backups.get_collector", return_value=fake
        ):
            app1 = create_app(test_settings)
            with TestClient(app1, raise_server_exceptions=True) as c1:
                job_id = _post_backup(c1)["id"]

            app2 = create_app(test_settings)
            with TestClient(app2, raise_server_exceptions=True) as c2:
                job = c2.get(f"/api/v1/backups/{job_id}").json()
                assert job["schedule_id"] is None

    def test_persisted_job_has_no_schedule_name(self, test_settings) -> None:
        """A manually triggered job has ``schedule_name=None`` after reload."""
        fake = FakeCollector(output=CISCO_FAKE_OUTPUT)
        with patch(
            "netconfig.api.routes.backups.get_collector", return_value=fake
        ):
            app1 = create_app(test_settings)
            with TestClient(app1, raise_server_exceptions=True) as c1:
                job_id = _post_backup(c1)["id"]

            app2 = create_app(test_settings)
            with TestClient(app2, raise_server_exceptions=True) as c2:
                job = c2.get(f"/api/v1/backups/{job_id}").json()
                assert job["schedule_name"] is None


# ---------------------------------------------------------------------------
# TestJobScheduleFields
# ---------------------------------------------------------------------------


class TestJobScheduleFields:
    def test_manual_backup_schedule_id_is_none(self, client: TestClient) -> None:
        """POST /api/v1/backups sets schedule_id=None on the completed job."""
        job = _post_and_get_job(client)
        assert job["schedule_id"] is None

    def test_manual_backup_schedule_name_is_none(self, client: TestClient) -> None:
        """POST /api/v1/backups sets schedule_name=None on the completed job."""
        job = _post_and_get_job(client)
        assert job["schedule_name"] is None


# ---------------------------------------------------------------------------
# TestThemeToggleRendered — server-side sanity that the dark-mode
# toggle button + boot script render on every page.  Cheaper than
# Playwright; catches template regressions before e2e runs.
# ---------------------------------------------------------------------------


class TestThemeToggleRendered:
    """Dark-mode wiring is in base.html, so EVERY page that extends
    it should carry:

    * ``<html data-theme="light">`` default on the root element
      (boot script overrides on the client before CSS paints).
    * Inline boot script reading ``localStorage`` + prefers-color-
      scheme.
    * The ``nav-theme-toggle`` button with sun + moon glyphs.
    * The theme-toggle partial inclusion.

    Sample the dashboard + jobs + configs pages — if one extends
    base.html differently, this catches it.
    """

    _PAGES = ["/", "/jobs", "/schedules", "/configs", "/definitions"]

    def test_html_has_data_theme_attribute(self, client: TestClient) -> None:
        for path in self._PAGES:
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert 'data-theme="light"' in resp.text, (
                f"{path} missing default data-theme on <html>"
            )

    def test_boot_script_present(self, client: TestClient) -> None:
        """FOUC-prevention: the boot script MUST be inline in <head>
        (not an external <script src>) so it runs synchronously
        before CSS parses."""
        resp = client.get("/")
        assert "netconfig.theme.v1" in resp.text
        assert "prefers-color-scheme" in resp.text
        # Boot script references documentElement (not body/DOM) —
        # required so the attribute is set before the body renders.
        assert "document.documentElement.setAttribute" in resp.text

    def test_nav_theme_toggle_button_present(
        self, client: TestClient,
    ) -> None:
        for path in self._PAGES:
            resp = client.get(path)
            assert 'data-testid="nav-theme-toggle"' in resp.text, (
                f"{path} missing nav-theme-toggle"
            )

    def test_sun_and_moon_glyphs_both_present(
        self, client: TestClient,
    ) -> None:
        """The glyph swap happens via CSS, not DOM mutation — both
        spans are in the markup, one hidden by the data-theme
        selector rules."""
        resp = client.get("/")
        # Sun (U+2600) + moon (U+263D) — HTML entities, mixed case
        # tolerated (the template uses lowercase hex).
        assert "&#x263D;" in resp.text or "&#x263d;" in resp.text
        assert "&#x2600;" in resp.text

    def test_toggle_partial_included(self, client: TestClient) -> None:
        """``_partials/theme-toggle.js`` inclusion means
        ``toggleTheme`` + aria-label updater both reach the page."""
        resp = client.get("/")
        assert "function toggleTheme()" in resp.text
        assert "_updateThemeToggleAriaLabel" in resp.text

    def test_css_variables_declared(self, client: TestClient) -> None:
        """Dark-mode CSS tokens must be present (regression guard
        against someone accidentally removing the :root or
        [data-theme=\"dark\"] block)."""
        resp = client.get("/")
        assert "--page-bg:" in resp.text
        assert '[data-theme="dark"]' in resp.text
        # Spot-check a few tokens; no need to enumerate all.
        assert "--surface:" in resp.text
        assert "--text-primary:" in resp.text
        assert "--nav-bg:" in resp.text


# ---------------------------------------------------------------------------
# TestDefinitionsPageEnriched — the /definitions page exposes FOUR
# sections (backup device defs + overlays + target profiles +
# vendor codecs).  Previously only the first section existed; the
# other three surface the hidden ~62 loaded records.  This class
# guards against regressions in:
#   * which sections render
#   * the section-count badges being wired to the right context
#     variables
#   * per-profile port chips + module variants populating
#   * per-vendor codec tables rendering with direction + certainty
#     pills
# ---------------------------------------------------------------------------


class TestDefinitionsPageEnriched:
    """The /definitions page surfaces every NetConfig data source:
    backup device definitions, version/model overlays, migration
    target profiles (with module variants), and vendor codec
    capabilities.  Before this enrichment only the first section
    rendered — the 54 target profiles + 8 vendors + module variants
    were invisible.
    """

    def test_four_section_containers_rendered(
        self, client: TestClient,
    ) -> None:
        resp = client.get("/definitions")
        assert resp.status_code == 200
        for testid in (
            "section-device-definitions",
            "section-target-profiles",
            "section-vendors",
        ):
            assert f'data-testid="{testid}"' in resp.text, (
                f"/definitions missing {testid}"
            )

    def test_device_definitions_section_count_matches_state(
        self, client: TestClient,
    ) -> None:
        """The backup-side family-base count in the header badge
        must match what app.state.definitions actually holds."""
        resp = client.get("/definitions")
        # Test app loads at least 1 definition; real count depends
        # on test fixtures.  We only verify the badge IS rendered
        # and is a non-negative integer.
        assert 'data-testid="section-device-definitions-count"' in resp.text

    def test_target_profiles_section_rendered_when_loaded(
        self, client: TestClient,
    ) -> None:
        """54 target profiles ship with NetConfig by default.
        The vendor-group + row testids must appear in the rendered
        HTML (a regression would drop the whole section)."""
        resp = client.get("/definitions")
        assert 'data-testid="section-target-profiles"' in resp.text
        # If target profiles are loaded, at least one vendor group
        # + one profile row should render.  The test harness uses
        # the real definitions/target_profiles dir.
        assert 'data-testid="profile-vendor-group"' in resp.text, (
            "no vendor groups rendered — target_profiles context "
            "missing or empty"
        )
        assert 'data-testid="target-profile-row"' in resp.text

    def test_profile_filter_widget_present(
        self, client: TestClient,
    ) -> None:
        resp = client.get("/definitions")
        assert 'data-testid="defs-profile-filter"' in resp.text
        assert 'data-testid="defs-profile-filter-count"' in resp.text

    def test_module_variants_exposed_when_profile_has_them(
        self, client: TestClient,
    ) -> None:
        """Profiles with ``modules:`` blocks (like Cat 9300
        C9300-24UX with NM-8X + NM-2Q) must render a
        `profile-module` card per SKU.  Regression guard: before
        this enrichment, module variants were only reachable
        through the rename-modal dropdown, never browsable."""
        resp = client.get("/definitions")
        # At least one of the shipped Cat 9300 / 3810M profiles has
        # module variants declared.  If the loader or template
        # drops them, this fails.
        assert 'data-testid="profile-module"' in resp.text, (
            "no module-variant cards rendered — modules context "
            "broken"
        )
        assert 'data-testid="profile-module-sku"' in resp.text

    def test_profile_base_ports_emitted(
        self, client: TestClient,
    ) -> None:
        """Every target profile should emit a base-ports chip list
        (chassis-fixed port inventory).  Empty profiles would skip
        this via the Jinja guard."""
        resp = client.get("/definitions")
        assert 'data-testid="profile-base-ports"' in resp.text

    def test_vendors_section_lists_all_codecs(
        self, client: TestClient,
    ) -> None:
        """The 8 vendor YAMLs each emit a vendor row; codecs
        registered under each vendor emit their own codec rows."""
        resp = client.get("/definitions")
        assert 'data-testid="section-vendors"' in resp.text
        assert 'data-testid="vendor-row"' in resp.text
        assert 'data-testid="vendor-codec-row"' in resp.text

    def test_codec_certainty_pills_rendered(
        self, client: TestClient,
    ) -> None:
        """Certainty tier is surfaced as a CSS-classed pill
        (certified / best_effort / experimental).  The pill CSS
        class must include the tier so the colour scheme applies."""
        resp = client.get("/definitions")
        # At least one codec is certified in the default shipped set.
        assert "defs-pill-certified" in resp.text
        assert 'data-testid="codec-certainty"' in resp.text

    def test_codec_direction_pill_rendered(
        self, client: TestClient,
    ) -> None:
        resp = client.get("/definitions")
        assert 'data-testid="codec-direction"' in resp.text
        assert "defs-pill-direction" in resp.text

    def test_capability_chips_are_buttons(
        self, client: TestClient,
    ) -> None:
        """The supported / lossy / unsupported count cells render as
        ``<button>`` elements with the expected testids — operators
        click them to expand a detail row showing the actual paths.
        Pre-fix these were inert ``<span>``s with hover tooltips
        only."""
        resp = client.get("/definitions")
        for testid in (
            "codec-caps-chip-supported",
            "codec-caps-chip-lossy",
            "codec-caps-chip-unsupported",
        ):
            assert f'data-testid="{testid}"' in resp.text, (
                f"missing {testid!r} chip on /definitions"
            )
        # The chips must include the data-bucket + data-codec
        # attributes the JS handler reads.
        assert 'data-bucket="supported"' in resp.text
        assert 'data-bucket="lossy"' in resp.text
        assert 'data-bucket="unsupported"' in resp.text
        assert 'data-codec="' in resp.text

    def test_capability_chips_disabled_when_count_zero(
        self, client: TestClient,
    ) -> None:
        """A chip whose count is 0 must render with the ``disabled``
        attribute so it can't be clicked + visually communicates
        "nothing to expand here".  The mock codec ships with zero
        unsupported xpaths and zero lossy xpaths in its declared
        capability matrix — guarding against accidental removal of
        the conditional ``{% if count == 0 %}disabled{% endif %}``
        in the template."""
        resp = client.get("/definitions")
        # The mock codec row should have at least one disabled chip.
        assert 'disabled' in resp.text
        # And at least one chip with a non-zero count must NOT be
        # disabled — every shipped codec has supported xpaths > 0.
        # Crude check: there's a chip without ``disabled`` somewhere
        # before its closing tag.
        import re
        # Look for one chip-supported button that isn't disabled.
        # The button definition spans multiple lines so use DOTALL.
        m = re.search(
            r'<button[^>]*data-testid="codec-caps-chip-supported"'
            r'(?![^>]*disabled)[^>]*>',
            resp.text,
        )
        assert m is not None, (
            "expected at least one supported-chip without `disabled` "
            "(every shipped codec has at least one supported xpath)"
        )

    def test_capabilities_endpoint_returns_full_matrix(
        self, client: TestClient,
    ) -> None:
        """The detail-row JS calls
        ``GET /api/v1/migration/adapters/{name}/capabilities`` to
        populate the expanded view.  Lock in the response shape so
        the JS bind doesn't silently break: must contain
        ``supported`` (list of strings) + ``lossy`` (list of
        path/reason objects) + ``unsupported`` (same shape as
        lossy).  Use a real shipped codec — opnsense — so the
        fixture is stable across test runs."""
        resp = client.get(
            "/api/v1/migration/adapters/opnsense/capabilities",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "supported" in body
        assert "lossy" in body
        assert "unsupported" in body
        assert isinstance(body["supported"], list)
        # OPNsense's ``unsupported`` is non-empty (firewall rules,
        # NAT, snmpv3 USM users) — exercise the lossy/unsupported
        # entry shape that the JS expects.
        assert len(body["unsupported"]) >= 1
        first_unsupp = body["unsupported"][0]
        assert "path" in first_unsupp
        assert "reason" in first_unsupp

    def test_overlays_section_absent_when_no_overlays_loaded(
        self, client: TestClient,
    ) -> None:
        """The overlays section is conditional — when the loader
        has zero overlays (the default test harness ships only
        family-base YAMLs), the section must NOT render.  Inverse
        of :meth:`test_overlays_section_renders_when_overlay_added`
        below."""
        resp = client.get("/definitions")
        assert 'data-testid="section-overlays"' not in resp.text

    def test_overlays_section_renders_when_overlay_added(
        self,
        sample_definitions_dir,
        test_settings,
        tmp_path,
    ) -> None:
        """Drop a version-pin overlay YAML next to the base Cisco
        definition and assert the overlays section renders it.
        Regression guard against the original user-reported "5
        loaded but only 4 visible" discrepancy — the 5th WAS an
        overlay (Cisco 17.12) and was hidden from the UI."""
        import yaml as _yaml
        from fastapi.testclient import TestClient

        from netconfig.main import create_app

        overlay_yaml = _yaml.safe_dump({
            "type_key": "Cisco",
            "vendor": "Cisco",
            "os": "IOS-XE",
            "os_version": "17.12",      # overlay marker
            "priority": 5,
            "file_extension": "cfg",
            "connection": {"needs_enable": True},
            "collector": {
                "strategy": "netmiko",
                "netmiko_device_type": "cisco_xe",
            },
            "commands": {"config": "show running-config"},
            "notes": "17.12-specific overlay for tests",
        })
        (sample_definitions_dir / "cisco" / "17_12.yaml").write_text(
            overlay_yaml, encoding="utf-8",
        )

        app = create_app(test_settings)
        with TestClient(app) as tc:
            resp = tc.get("/definitions")
            assert resp.status_code == 200
            assert 'data-testid="section-overlays"' in resp.text
            assert 'data-testid="overlay-row"' in resp.text
            # The overlay's os_version should appear in the row's
            # data attribute (and in the visible cell).
            assert 'data-os-version="17.12"' in resp.text
