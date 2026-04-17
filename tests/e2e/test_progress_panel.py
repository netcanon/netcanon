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
