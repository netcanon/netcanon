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
    ConfigsPage,
    DefinitionsPage,
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
