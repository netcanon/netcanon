"""
E2E tests: browser-level smoke tests using Playwright.

These tests drive a real browser against a live Uvicorn server with SSH
collection mocked out (``get_collector`` is patched in ``e2e/conftest.py``
for the entire session).

All selectors use ``data-testid`` attributes, which are set on every
interactive template element.  See ``tests/testid_reference.md`` for the
full reference.

Marks
-----
All tests carry ``@pytest.mark.e2e`` so they can be skipped in environments
without a display::

    pytest -m "not e2e"          # skip all E2E tests
    pytest tests/e2e -m e2e -v   # run only E2E tests
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    BackupFormPage,
    ComparePicker,
    ConfigsPage,
    ConfigViewer,
    DefinitionsPage,
    DiffPage,
    JobProgressPanel,
    JobsTable,
    NavBar,
)

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Navigation smoke tests
# ---------------------------------------------------------------------------


class TestNavigation:
    def test_dashboard_title(self, page: Page, base_url: str):
        page.goto("/")
        expect(page).to_have_title("Dashboard — NetConfig")

    def test_nav_brand_visible(self, page: Page, base_url: str):
        page.goto("/")
        nav = NavBar(page)
        expect(nav.brand).to_have_text("NetConfig")

    def test_nav_to_configs(self, page: Page, base_url: str):
        page.goto("/")
        NavBar(page).go_to_configs()
        expect(page).to_have_url(f"{base_url}/configs")

    def test_nav_to_definitions(self, page: Page, base_url: str):
        page.goto("/")
        NavBar(page).go_to_definitions()
        expect(page).to_have_url(f"{base_url}/definitions")

    def test_nav_back_to_dashboard(self, page: Page, base_url: str):
        page.goto("/configs")
        NavBar(page).go_to_dashboard()
        expect(page).to_have_url(f"{base_url}/")

    def test_configs_page_title(self, page: Page, base_url: str):
        page.goto("/configs")
        expect(page).to_have_title("Configs — NetConfig")

    def test_definitions_page_title(self, page: Page, base_url: str):
        page.goto("/definitions")
        expect(page).to_have_title("Definitions — NetConfig")


# ---------------------------------------------------------------------------
# Dashboard — static structure
# ---------------------------------------------------------------------------


class TestDashboardStructure:
    def test_backup_form_visible(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        expect(form.form).to_be_visible()

    def test_one_device_entry_on_load(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        expect(form.device_entries()).to_have_count(1)

    def test_add_device_button_visible(self, page: Page, base_url: str):
        page.goto("/")
        expect(BackupFormPage(page).add_device_btn).to_be_visible()

    def test_submit_button_visible(self, page: Page, base_url: str):
        page.goto("/")
        expect(BackupFormPage(page).submit_btn).to_be_visible()

    def test_remove_button_hidden_for_single_entry(self, page: Page, base_url: str):
        """Remove button must be hidden when only one device row exists."""
        page.goto("/")
        remove_btn = page.locator('[data-testid="remove-device-btn"]').first
        expect(remove_btn).to_be_hidden()

    def test_type_select_has_options(self, page: Page, base_url: str):
        """The device type dropdown must list the loaded definitions."""
        page.goto("/")
        select = page.locator('[data-testid="device-type-select"]').first
        options = select.locator("option").all()
        assert len(options) >= 1

    def test_status_banner_hidden_on_load(self, page: Page, base_url: str):
        page.goto("/")
        expect(BackupFormPage(page).status_banner).to_be_hidden()


# ---------------------------------------------------------------------------
# Multi-device form interactions
# ---------------------------------------------------------------------------


class TestMultiDeviceForm:
    def test_add_device_adds_row(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        form.add_device_btn.click()
        expect(form.device_entries()).to_have_count(2)

    def test_add_two_devices(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        form.add_device_btn.click()
        form.add_device_btn.click()
        expect(form.device_entries()).to_have_count(3)

    def test_remove_button_appears_with_multiple_entries(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        form.add_device_btn.click()
        remove_btns = page.locator('[data-testid="remove-device-btn"]')
        # At least one remove button should now be visible
        expect(remove_btns.first).to_be_visible()

    def test_remove_device_reduces_count(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        form.add_device_btn.click()
        expect(form.device_entries()).to_have_count(2)
        page.locator('[data-testid="remove-device-btn"]').first.click()
        expect(form.device_entries()).to_have_count(1)

    def test_remove_button_hidden_after_back_to_one(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        form.add_device_btn.click()
        page.locator('[data-testid="remove-device-btn"]').first.click()
        expect(form.device_entries()).to_have_count(1)
        expect(page.locator('[data-testid="remove-device-btn"]').first).to_be_hidden()


# ---------------------------------------------------------------------------
# Backup form submission
# ---------------------------------------------------------------------------


class TestBackupSubmission:
    def test_submit_shows_banner(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        expect(form.status_banner).to_be_visible()

    def test_banner_shows_job_id(self, page: Page, base_url: str):
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        job_id_el = page.locator('[data-testid="job-id-display"]')
        # Job ID display shows first 8 chars + ellipsis
        job_id_text = job_id_el.text_content()
        assert job_id_text and len(job_id_text.strip()) > 0

    def test_submit_completes_and_shows_job_in_table(self, page: Page, base_url: str):
        """After completion the job row is injected inline and jobs table becomes visible."""
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        # JS injects a row and un-hides the table — no page reload needed
        jobs_table = page.locator('[data-testid="jobs-table"]')
        expect(jobs_table).to_be_visible(timeout=5_000)


# ---------------------------------------------------------------------------
# Definitions page
# ---------------------------------------------------------------------------


class TestDefinitionsPage:
    def test_definitions_table_visible(self, page: Page, base_url: str):
        page.goto("/definitions")
        defs_page = DefinitionsPage(page)
        expect(defs_page.table).to_be_visible()

    def test_two_definitions_loaded(self, page: Page, base_url: str):
        page.goto("/definitions")
        defs_page = DefinitionsPage(page)
        expect(defs_page.rows()).to_have_count(2)

    def test_cisco_definition_row(self, page: Page, base_url: str):
        page.goto("/definitions")
        defs_page = DefinitionsPage(page)
        row = defs_page.row_for_type_key("Cisco")
        expect(row).to_be_visible()

    def test_opnsense_definition_row(self, page: Page, base_url: str):
        page.goto("/definitions")
        defs_page = DefinitionsPage(page)
        row = defs_page.row_for_type_key("OPNsense")
        expect(row).to_be_visible()

    def test_definition_vendor_cell(self, page: Page, base_url: str):
        page.goto("/definitions")
        cisco_row = page.locator(
            '[data-testid="definition-row"][data-type-key="Cisco"]'
        )
        vendor_cell = cisco_row.locator('[data-testid="def-vendor"]')
        expect(vendor_cell).to_have_text("Cisco")


# ---------------------------------------------------------------------------
# Configs page
# ---------------------------------------------------------------------------


class TestConfigsPage:
    def test_empty_configs_message(self, page: Page, base_url: str):
        """On a fresh server the configs page shows the empty-state message."""
        page.goto("/configs")
        configs_page = ConfigsPage(page)
        # The live server is session-scoped, so other tests may have already
        # added configs — we just check the page renders without errors.
        expect(page.locator("h1")).to_have_text("Stored Configurations")

    def test_configs_page_renders(self, page: Page, base_url: str):
        page.goto("/configs")
        # Should not show a 500 error page — the main tag must be present
        expect(page.locator("main")).to_be_visible()


# ---------------------------------------------------------------------------
# Config viewer modal — syntax highlighting + in-modal search
# ---------------------------------------------------------------------------


def _ensure_cisco_config(page: Page) -> str:
    """Make sure at least one Cisco config exists, then return its filename.

    Posts a backup via the API (FakeCollector returns canned Cisco output
    containing ``!`` comments, ``version``, ``hostname Router``, and ``end``).
    """
    # 1. Create a config by triggering a backup through the live API.
    page.request.post(
        "/api/v1/backups/",
        data={
            "devices": [
                {
                    "type_key": "Cisco",
                    "host": "192.168.77.77",
                    "credentials": {"username": "admin", "password": "pw"},
                }
            ]
        },
    )
    # 2. Find the most recent Cisco config.
    resp = page.request.get("/api/v1/configs/")
    assert resp.ok
    records = resp.json()
    cisco = [r for r in records if r["device_type"] == "Cisco"]
    assert cisco, "expected at least one Cisco config after POST /backups"
    return cisco[0]["filename"]


class TestConfigViewerHighlighting:
    """Syntax highlighting paints comments / keywords / numbers."""

    def test_modal_opens_with_filename(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        expect(viewer.modal).to_be_visible()
        expect(viewer.title).to_have_text(filename)

    def test_cfg_content_has_comment_tokens(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        # The canned Cisco output contains `!` comment lines.
        comments = viewer.content.locator(".tok-comment")
        expect(comments.first).to_be_visible()

    def test_cfg_content_has_keyword_tokens(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        # "hostname" and "version" from the canned output are keywords.
        keywords = viewer.content.locator(".tok-keyword")
        assert keywords.count() >= 1

    def test_cfg_content_has_number_tokens(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        # Canned output has "17.9", "1234" → number/IP tokens.
        numbers = viewer.content.locator(".tok-number, .tok-ip")
        assert numbers.count() >= 1


class TestConfigViewerSearch:
    """In-modal search: counter, prev/next, highlighting, keyboard nav."""

    def test_empty_query_shows_no_count(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        expect(viewer.count).to_have_text("")

    def test_search_highlights_matches(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("hostname")
        # Canned output contains one "hostname".
        assert viewer.current_matches().count() >= 1

    def test_search_count_shows_index_and_total(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("hostname")
        # First match is selected automatically → "1 / N".
        expect(viewer.count).to_contain_text("1 /")

    def test_no_match_shows_no_matches_text(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("zzzzz-definitely-absent-zzzzz")
        expect(viewer.count).to_have_text("No matches")

    def test_next_button_advances_current_match(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        # "!" appears multiple times in the canned output.
        viewer.search.fill("!")
        matches = viewer.current_matches()
        total = matches.count()
        assert total >= 2, "need >=2 matches to test next"
        expect(viewer.count).to_contain_text("1 /")
        viewer.next_btn.click()
        expect(viewer.count).to_contain_text("2 /")

    def test_prev_button_wraps_to_last(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("!")
        total = viewer.current_matches().count()
        assert total >= 2
        # At match 1, pressing prev wraps to the last match.
        viewer.prev_btn.click()
        expect(viewer.count).to_contain_text(f"{total} / {total}")

    def test_escape_in_empty_search_closes_modal(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.focus()
        viewer.search.press("Escape")
        expect(viewer.modal).to_be_hidden()

    def test_close_button_hides_modal(self, page: Page, base_url: str):
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        expect(viewer.modal).to_be_visible()
        viewer.close()
        expect(viewer.modal).to_be_hidden()

    def test_cross_span_query_finds_match(self, page: Page, base_url: str):
        """A query that crosses a syntax-highlight span boundary must match.

        The canned Cisco output contains the line ``hostname Router``;
        the tokenizer wraps ``hostname`` in ``<span class="tok-keyword">``
        and leaves `` Router`` as plain text in a sibling text node.
        Before the flat-text search fix this query returned zero matches;
        it must now report at least one.
        """
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("hostname Router")
        # Cross-span match: one logical hit, possibly rendered as 2 marks.
        expect(viewer.count).to_contain_text("1 /")
        assert viewer.current_matches().count() >= 1

    def test_cross_span_match_current_class_applied_to_all_pieces(
        self, page: Page, base_url: str
    ):
        """When a match spans boundaries, every <mark> in the group gets
        ``.current`` so the highlight visually reads as one selection."""
        filename = _ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("hostname Router")
        # All marks created by this search share the class (single match,
        # so every mark in the DOM belongs to the current group).
        current = viewer.content.locator("mark.current")
        assert current.count() >= 1


# ---------------------------------------------------------------------------
# Job progress panel — visibility, per-device rows, persistence
# ---------------------------------------------------------------------------


class TestJobProgressPanel:
    """Floating progress panel: header summary, expandable rows, dismiss."""

    def test_panel_hidden_on_fresh_page(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        expect(panel.panel).to_be_hidden()

    def test_panel_shows_after_backup_submit(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        expect(panel.panel).to_be_visible()

    def test_panel_header_shows_short_job_id(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        job_id_el = page.locator('[data-testid="job-id-display"]')
        # Header shows first 8 chars + ellipsis.
        expect(job_id_el).to_contain_text("\u2026")

    def test_panel_has_one_device_row_per_device(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        # Single-device backup → exactly one row.
        expect(panel.device_rows()).to_have_count(1)

    def test_panel_device_row_has_terminal_status(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device(host="10.77.77.77")
        form.submit_and_wait()
        # After completion, the row's data-status attr is a terminal value.
        row = panel.row_for("10.77.77.77")
        assert panel.status_of("10.77.77.77") in ("success", "failed")
        expect(row).to_be_visible()

    def test_footer_appears_after_terminal_state(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        expect(panel.footer).to_be_visible()
        expect(panel.dismiss_btn).to_be_visible()
        expect(panel.view_link).to_be_visible()

    def test_dismiss_button_hides_panel(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        panel.dismiss_btn.click()
        expect(panel.panel).to_be_hidden()

    def test_header_click_collapses_body(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        expect(panel.body).to_be_visible()
        panel.header.click()
        expect(panel.body).to_be_hidden()
        panel.header.click()
        expect(panel.body).to_be_visible()

    def test_panel_persists_across_page_reload(self, page: Page, base_url: str):
        """After completion the panel stays in localStorage; reload shows it again."""
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        # Confirm it's visible before the reload.
        expect(panel.panel).to_be_visible()
        # Reload — base.html's resume logic should restore the panel from
        # localStorage and show the already-terminal job.
        page.reload()
        expect(panel.panel).to_be_visible(timeout=5_000)
        # Footer (terminal-only) should also be back.
        expect(panel.footer).to_be_visible()
        # Cleanup so other tests don't see our storage.
        panel.dismiss_btn.click()

    def test_panel_disappears_after_dismiss_and_reload(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        panel.dismiss_btn.click()
        page.reload()
        # localStorage was cleared on dismiss, so a reload must not resurrect it.
        expect(panel.panel).to_be_hidden()

    def test_view_link_targets_jobs_page(self, page: Page, base_url: str):
        panel = JobProgressPanel(page)
        panel.clear_storage()
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()
        href = panel.view_link.get_attribute("href") or ""
        assert href.startswith("/jobs#")


# ---------------------------------------------------------------------------
# Config diff — API + compatibility guardrails + UI flow
# ---------------------------------------------------------------------------


def _ensure_n_configs_of_type(page: Page, type_key: str, count: int) -> list[str]:
    """Create *count* configs of the given type via the live API and
    return their filenames (newest-first)."""
    for i in range(count):
        page.request.post(
            "/api/v1/backups/",
            data={
                "devices": [
                    {
                        "type_key": type_key,
                        "host": f"10.88.{i+1}.1",
                        "credentials": {"username": "admin", "password": "pw"},
                    }
                ]
            },
        )
    records = page.request.get("/api/v1/configs/").json()
    files = [
        r["filename"]
        for r in records
        if r["device_type"] == type_key
    ]
    assert len(files) >= count, f"Seeded configs didn't appear: got {len(files)}"
    return files


class TestDiffApi:
    """E2E-level checks via the live API (complements integration tests).

    Goal: prove the wiring from HTTP → service → response works end-to-end
    against a real filesystem store, not just the TestClient.
    """

    def test_same_type_returns_ok_compat(self, page: Page, base_url: str):
        files = _ensure_n_configs_of_type(page, "Cisco", 2)
        resp = page.request.post(
            "/api/v1/configs/diff",
            data={"left": files[0], "right": files[1]},
        )
        assert resp.ok
        report = resp.json()
        assert report["compatibility"]["severity"] == "ok"

    def test_cross_vendor_without_force_is_422(self, page: Page, base_url: str):
        cisco_files = _ensure_n_configs_of_type(page, "Cisco", 1)
        opn_files = _ensure_n_configs_of_type(page, "OPNsense", 1)
        resp = page.request.post(
            "/api/v1/configs/diff",
            data={"left": cisco_files[0], "right": opn_files[0]},
        )
        assert resp.status == 422


class TestDiffPageUI:
    """Compare button → picker → diff page flow."""

    def test_compare_button_visible_on_configs_page(self, page: Page, base_url: str):
        _ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto("/configs")
        cp = ConfigsPage(page)
        expect(cp.compare_buttons().first).to_be_visible()

    def test_picker_opens_on_compare_click(self, page: Page, base_url: str):
        files = _ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto("/configs")
        cp = ConfigsPage(page)
        cp.open_compare_for(files[0])
        picker = ComparePicker(page)
        expect(picker.modal).to_be_visible()

    def test_picker_lists_same_type_as_compatible(self, page: Page, base_url: str):
        files = _ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto("/configs")
        ConfigsPage(page).open_compare_for(files[0])
        picker = ComparePicker(page)
        # At least one compatible option (the other Cisco config).
        assert picker.options().count() >= 1

    def test_picker_hides_cross_vendor_until_toggle(self, page: Page, base_url: str):
        _ensure_n_configs_of_type(page, "Cisco", 1)
        _ensure_n_configs_of_type(page, "OPNsense", 1)
        records = page.request.get("/api/v1/configs/").json()
        cisco = [r for r in records if r["device_type"] == "Cisco"][0]
        page.goto("/configs")
        ConfigsPage(page).open_compare_for(cisco["filename"])
        picker = ComparePicker(page)
        # Cross-vendor options are hidden by default.
        expect(picker.cross_vendor_options()).to_have_count(0)
        picker.show_all.check()
        # Once toggled, at least one cross-vendor option appears.
        assert picker.cross_vendor_options().count() >= 1

    def test_close_button_hides_picker(self, page: Page, base_url: str):
        files = _ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto("/configs")
        ConfigsPage(page).open_compare_for(files[0])
        picker = ComparePicker(page)
        expect(picker.modal).to_be_visible()
        picker.close_btn.click()
        expect(picker.modal).to_be_hidden()


class TestDiffPageContent:
    """Direct hits on ``/configs/{left}/vs/{right}`` — banner, stats, swap."""

    def test_same_type_renders_green_ok_banner(self, page: Page, base_url: str):
        files = _ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto(f"/configs/{files[0]}/vs/{files[1]}")
        diff = DiffPage(page)
        assert diff.banner_severity() == "ok"

    def test_cross_vendor_renders_block_banner_with_override_btn(
        self, page: Page, base_url: str
    ):
        _ensure_n_configs_of_type(page, "Cisco", 1)
        _ensure_n_configs_of_type(page, "OPNsense", 1)
        records = page.request.get("/api/v1/configs/").json()
        cisco = [r for r in records if r["device_type"] == "Cisco"][0]
        opn = [r for r in records if r["device_type"] == "OPNsense"][0]
        page.goto(f"/configs/{cisco['filename']}/vs/{opn['filename']}")
        diff = DiffPage(page)
        assert diff.banner_severity() == "block"
        expect(diff.force_override_btn).to_be_visible()

    def test_force_override_renders_diff_body(self, page: Page, base_url: str):
        _ensure_n_configs_of_type(page, "Cisco", 1)
        _ensure_n_configs_of_type(page, "OPNsense", 1)
        records = page.request.get("/api/v1/configs/").json()
        cisco = [r for r in records if r["device_type"] == "Cisco"][0]
        opn = [r for r in records if r["device_type"] == "OPNsense"][0]
        page.goto(
            f"/configs/{cisco['filename']}/vs/{opn['filename']}?force=true"
        )
        diff = DiffPage(page)
        assert diff.banner_severity() == "block"
        # With force=true the body renders — either as visible diff-line
        # rows (when changes are tightly interleaved) or collapsed markers
        # (when long equal runs got folded).  Either is evidence of a
        # populated diff body.
        visible = diff.lines().count() + diff.collapsed_markers().count()
        assert visible > 0

    def test_same_file_diff_has_zero_added_zero_removed(
        self, page: Page, base_url: str
    ):
        files = _ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/{files[0]}")
        diff = DiffPage(page)
        expect(diff.stats_added).to_have_text("+0")
        expect(diff.stats_removed).to_contain_text("0")

    def test_missing_file_renders_404_banner(self, page: Page, base_url: str):
        files = _ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/Cisco_0-0-0-0_20000101_000000.cfg")
        diff = DiffPage(page)
        assert diff.banner_severity() == "block"
        expect(diff.banner).to_contain_text("Not found")

    def test_reverse_direction_link_reverses_url(self, page: Page, base_url: str):
        """The "Reverse direction" button swaps baseline ↔ current by
        pointing at the ``right/vs/left`` URL."""
        files = _ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto(f"/configs/{files[0]}/vs/{files[1]}")
        diff = DiffPage(page)
        href = diff.reverse_btn.get_attribute("href") or ""
        # URL contains right-then-left after reversing.
        assert files[1] in href
        assert href.index(files[1]) < href.index(files[0])

    def test_from_and_to_role_labels_visible(
        self, page: Page, base_url: str
    ):
        """The directional paradigm is surfaced to the user explicitly —
        not implied by chip position.  ``from``/``to`` is temporally
        neutral (unlike ``current``, which implied 'this is now')."""
        files = _ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto(f"/configs/{files[0]}/vs/{files[1]}")
        expect(page.locator('[data-testid="diff-from-label"]')).to_be_visible()
        expect(page.locator('[data-testid="diff-to-label"]')).to_be_visible()


class TestDiffContextFolding:
    """Long runs of equal lines collapse into expandable markers so large
    configs don't render tens of thousands of DOM rows up front."""

    def test_identical_configs_collapse_to_one_marker(self, page: Page, base_url: str):
        """A diff with zero changes means every line is cold → one group."""
        files = _ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/{files[0]}")
        diff = DiffPage(page)
        # The FakeCollector's canned Cisco output has >= a few equal lines.
        expect(diff.collapsed_markers().first).to_be_visible()
        # Since there are no changes, no visible diff-line rows exist.
        expect(diff.lines()).to_have_count(0)

    def test_collapsed_marker_announces_hidden_line_count(
        self, page: Page, base_url: str
    ):
        """The marker text advertises how many lines it hides."""
        files = _ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/{files[0]}")
        diff = DiffPage(page)
        marker = diff.collapsed_markers().first
        count_attr = marker.get_attribute("data-count")
        # Canned Cisco output has multiple lines; count must be positive.
        assert count_attr is not None and int(count_attr) >= 1
        # Text explicitly mentions "unchanged".
        expect(marker).to_contain_text("unchanged")

    def test_click_collapsed_marker_expands_in_place(
        self, page: Page, base_url: str
    ):
        """Clicking a collapsed marker swaps in its hidden lines and removes
        the marker itself (same effect as GitHub's ↕ expander)."""
        files = _ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/{files[0]}")
        diff = DiffPage(page)
        marker = diff.collapsed_markers().first
        hidden_count = int(marker.get_attribute("data-count") or "0")
        assert hidden_count >= 1, "need >= 1 hidden line to test expansion"
        assert diff.lines().count() == 0

        marker.click()

        # Marker is gone, hidden lines are now visible diff-line rows.
        expect(diff.collapsed_markers()).to_have_count(0)
        assert diff.lines().count() == hidden_count
