"""
E2E tests: Jobs page and Schedules page.

These tests drive a real browser against a live Uvicorn server with SSH
collection mocked out (``get_collector`` is patched in ``e2e/conftest.py``
for the entire session).

All selectors use ``data-testid`` attributes exclusively.
See ``tests/testid_reference.md`` for the full reference.

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
    JobsPage,
    NavBar,
    SchedulesPage,
)

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Jobs page — navigation
# ---------------------------------------------------------------------------


class TestJobsPageNavigation:
    def test_jobs_page_title(self, page: Page, base_url: str):
        page.goto("/jobs")
        expect(page).to_have_title("Jobs — NetConfig")

    def test_nav_jobs_link_visible_from_dashboard(self, page: Page, base_url: str):
        page.goto("/")
        nav_jobs = page.locator('[data-testid="nav-jobs"]')
        expect(nav_jobs).to_be_visible()

    def test_nav_to_jobs(self, page: Page, base_url: str):
        page.goto("/")
        NavBar(page).go_to_jobs()
        expect(page).to_have_url(f"{base_url}/jobs")

    def test_jobs_page_has_active_nav_state(self, page: Page, base_url: str):
        page.goto("/jobs")
        nav_jobs = page.locator('[data-testid="nav-jobs"]')
        expect(nav_jobs).to_have_class("active")


# ---------------------------------------------------------------------------
# Jobs page — renders without error
# ---------------------------------------------------------------------------


class TestJobsPageEmpty:
    def test_jobs_page_renders(self, page: Page, base_url: str):
        """The /jobs page should render without a 500 error — main is visible."""
        page.goto("/jobs")
        expect(page.locator("main")).to_be_visible()

    def test_jobs_page_h1_visible(self, page: Page, base_url: str):
        page.goto("/jobs")
        expect(page.locator("h1")).to_be_visible()


# ---------------------------------------------------------------------------
# Jobs page — with a real (mocked) backup job
# ---------------------------------------------------------------------------


class TestJobsPageWithJob:
    def test_job_card_visible_after_backup(self, page: Page, base_url: str):
        """After submitting a backup from the dashboard, /jobs shows a job card."""
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()

        page.goto("/jobs")
        jobs = JobsPage(page)
        expect(jobs.cards().first).to_be_visible(timeout=5_000)

    def test_first_job_card_header_has_status_badge(self, page: Page, base_url: str):
        """The first job card header contains a status badge."""
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()

        page.goto("/jobs")
        jobs = JobsPage(page)
        status_badge = jobs.first_card_header().locator('[data-testid="job-status"]')
        expect(status_badge).to_be_visible(timeout=5_000)

    def test_clicking_job_card_header_expands_body(self, page: Page, base_url: str):
        """Clicking the card header toggles the card body into view."""
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()

        page.goto("/jobs")
        jobs = JobsPage(page)
        # Body should be hidden initially
        expect(jobs.card_body(0)).to_be_hidden()
        # Click header to expand
        jobs.toggle_first_card()
        expect(jobs.card_body(0)).to_be_visible(timeout=5_000)

    def test_expanded_card_body_contains_result_rows(self, page: Page, base_url: str):
        """An expanded job card body contains at least one job-result-row."""
        page.goto("/")
        form = BackupFormPage(page)
        form.fill_first_device()
        form.submit_and_wait()

        page.goto("/jobs")
        jobs = JobsPage(page)
        jobs.toggle_first_card()
        result_rows = jobs.card_body(0).locator('[data-testid="job-result-row"]')
        expect(result_rows.first).to_be_visible(timeout=5_000)


# ---------------------------------------------------------------------------
# Schedules page — navigation
# ---------------------------------------------------------------------------


class TestSchedulesPageNavigation:
    def test_schedules_page_title(self, page: Page, base_url: str):
        page.goto("/schedules")
        expect(page).to_have_title("Schedules — NetConfig")

    def test_nav_to_schedules(self, page: Page, base_url: str):
        page.goto("/")
        NavBar(page).go_to_schedules()
        expect(page).to_have_url(f"{base_url}/schedules")

    def test_schedules_page_has_active_nav_state(self, page: Page, base_url: str):
        page.goto("/schedules")
        nav_schedules = page.locator('[data-testid="nav-schedules"]')
        expect(nav_schedules).to_have_class("active")


# ---------------------------------------------------------------------------
# Schedules page — static structure
# ---------------------------------------------------------------------------


class TestSchedulesPageStructure:
    def test_schedule_form_visible(self, page: Page, base_url: str):
        page.goto("/schedules")
        expect(SchedulesPage(page).form).to_be_visible()

    def test_sched_name_input_visible(self, page: Page, base_url: str):
        page.goto("/schedules")
        expect(page.locator('[data-testid="sched-name-input"]')).to_be_visible()

    def test_sched_interval_select_visible(self, page: Page, base_url: str):
        page.goto("/schedules")
        expect(page.locator('[data-testid="sched-interval-select"]')).to_be_visible()

    def test_sched_type_keys_section_visible(self, page: Page, base_url: str):
        """The 'Target by Device Type' checkbox section must be visible."""
        page.goto("/schedules")
        expect(page.locator('[data-testid="sched-type-keys-section"]')).to_be_visible()

    def test_sched_submit_btn_visible(self, page: Page, base_url: str):
        page.goto("/schedules")
        expect(page.locator('[data-testid="sched-submit-btn"]')).to_be_visible()

    def test_sched_type_key_checkboxes_match_definitions(self, page: Page, base_url: str):
        """One checkbox per loaded definition type_key."""
        page.goto("/schedules")
        checkboxes = page.locator('[data-testid="sched-type-key-checkbox"]')
        # The E2E conftest loads Cisco + OPNsense definitions.
        assert checkboxes.count() >= 2

    def test_custom_interval_input_hidden_by_default(self, page: Page, base_url: str):
        page.goto("/schedules")
        custom_input = page.locator('[data-testid="sched-custom-interval-input"]')
        expect(custom_input).to_be_hidden()

    def test_selecting_custom_shows_custom_interval_input(
        self, page: Page, base_url: str
    ):
        page.goto("/schedules")
        interval_select = page.locator('[data-testid="sched-interval-select"]')
        # Select the "Custom…" option — its value is "custom" per the template
        interval_select.select_option(value="custom")
        custom_input = page.locator('[data-testid="sched-custom-interval-input"]')
        expect(custom_input).to_be_visible()


# ---------------------------------------------------------------------------
# Schedules page — create and delete flow
# ---------------------------------------------------------------------------


class TestScheduleCreateAndDelete:
    def test_create_schedule_appears_in_table(self, page: Page, base_url: str):
        """Creating a schedule causes a new row to appear in the schedules table."""
        page.goto("/schedules")
        sched = SchedulesPage(page)
        sched.fill_form(name="Test E2E Schedule", interval_value="1440")
        sched.submit_form()
        expect(sched.rows().first).to_be_visible(timeout=5_000)

    def test_created_schedule_name_cell(self, page: Page, base_url: str):
        """The schedule-name cell of the created row contains the schedule name."""
        page.goto("/schedules")
        sched = SchedulesPage(page)
        sched.fill_form(name="Test E2E Schedule", interval_value="1440")
        sched.submit_form()
        name_cell = sched.rows().first.locator('[data-testid="schedule-name"]')
        expect(name_cell).to_contain_text("Test E2E Schedule")

    def test_created_schedule_toggle_shows_enabled(self, page: Page, base_url: str):
        """The toggle button on a freshly created schedule reads "Enabled"."""
        page.goto("/schedules")
        sched = SchedulesPage(page)
        sched.fill_form(name="Test E2E Schedule", interval_value="1440")
        sched.submit_form()
        toggle_btn = sched.rows().first.locator('[data-testid="schedule-toggle-btn"]')
        expect(toggle_btn).to_contain_text("Enabled")

    def test_delete_cancel_restores_delete_button(self, page: Page, base_url: str):
        """Clicking No on the confirm dialog hides confirm and restores the delete button."""
        page.goto("/schedules")
        sched = SchedulesPage(page)
        sched.fill_form(name="Test E2E Schedule", interval_value="1440")
        sched.submit_form()

        # Click delete — inline confirm should appear
        first_row = sched.rows().first
        first_row.locator('[data-testid="schedule-delete-btn"]').click()
        confirm_btn = first_row.locator('[data-testid="schedule-delete-confirm-btn"]')
        cancel_btn = first_row.locator('[data-testid="schedule-delete-cancel-btn"]')
        expect(confirm_btn).to_be_visible()

        # Click No — confirm disappears, delete button reappears
        cancel_btn.click()
        expect(confirm_btn).to_be_hidden()
        expect(first_row.locator('[data-testid="schedule-delete-btn"]')).to_be_visible()

    def test_delete_confirm_removes_row(self, page: Page, base_url: str):
        """Clicking Yes on the confirm dialog removes the schedule row."""
        page.goto("/schedules")
        sched = SchedulesPage(page)
        sched.fill_form(name="Test E2E Schedule", interval_value="1440")
        sched.submit_form()

        rows_before = sched.rows().count()
        assert rows_before >= 1, "Expected at least one schedule row before delete"

        # Click delete then confirm with Yes
        first_row = sched.rows().first
        # Capture the schedule-id before the row disappears
        schedule_id = first_row.get_attribute("data-schedule-id")
        first_row.locator('[data-testid="schedule-delete-btn"]').click()
        first_row.locator('[data-testid="schedule-delete-confirm-btn"]').click()

        # The row for this specific schedule should disappear
        deleted_row = page.locator(
            f'[data-testid="schedule-row"][data-schedule-id="{schedule_id}"]'
        )
        expect(deleted_row).to_be_hidden(timeout=5_000)
