"""
E2E tests — split from test_backup_flow.py for maintainability.

All selectors use data-testid attributes.  See tests/testid_reference.md.
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
    MigratePage,
    NavBar,
    ensure_cisco_config,
    ensure_n_configs_of_type,
)

pytestmark = pytest.mark.e2e


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
