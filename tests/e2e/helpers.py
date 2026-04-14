"""
Page-object helpers for E2E tests.

Each helper wraps a group of related Playwright ``Locator`` calls behind a
semantic API.  Using ``data-testid`` attributes (set on every interactive
element in the templates) makes selectors immune to CSS refactoring.

Usage::

    from tests.e2e.helpers import NavBar, BackupFormPage, JobsTable

    def test_navigation(page):
        nav = NavBar(page)
        nav.go_to_configs()
        assert "/configs" in page.url
"""
from __future__ import annotations

from playwright.sync_api import Page


# ---------------------------------------------------------------------------
# Navigation bar
# ---------------------------------------------------------------------------


class NavBar:
    """Helpers for the top navigation bar (``data-testid="nav"``)."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def brand(self):
        return self._page.locator('[data-testid="nav-brand"]')

    def go_to_dashboard(self) -> None:
        self._page.locator('[data-testid="nav-home"]').click()
        self._page.wait_for_url("**/")

    def go_to_configs(self) -> None:
        self._page.locator('[data-testid="nav-configs"]').click()
        self._page.wait_for_url("**/configs")

    def go_to_definitions(self) -> None:
        self._page.locator('[data-testid="nav-definitions"]').click()
        self._page.wait_for_url("**/definitions")

    def go_to_api_docs(self) -> None:
        self._page.locator('[data-testid="nav-api-docs"]').click()


# ---------------------------------------------------------------------------
# Dashboard — backup form
# ---------------------------------------------------------------------------


class BackupFormPage:
    """Helpers for the ``/`` dashboard backup form."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def form(self):
        return self._page.locator('[data-testid="backup-form"]')

    @property
    def add_device_btn(self):
        return self._page.locator('[data-testid="add-device-btn"]')

    @property
    def submit_btn(self):
        return self._page.locator('[data-testid="submit-backup-btn"]')

    @property
    def status_banner(self):
        return self._page.locator('[data-testid="job-status-banner"]')

    @property
    def job_status_display(self):
        return self._page.locator('[data-testid="job-status-display"]')

    def device_entries(self):
        return self._page.locator('[data-testid="device-entry"]')

    def fill_first_device(
        self,
        host: str = "192.168.1.1",
        username: str = "admin",
        password: str = "testpass",
    ) -> None:
        """Fill the first (or only) device row with test credentials."""
        entry = self._page.locator('[data-testid="device-entry"]').first
        entry.locator('[data-testid="device-host-input"]').fill(host)
        entry.locator('[data-testid="device-username-input"]').fill(username)
        entry.locator('[data-testid="device-password-input"]').fill(password)

    def submit(self) -> None:
        self.submit_btn.click()

    def submit_and_wait(self, timeout: float = 10_000) -> None:
        """Submit the form and wait for the job to reach a terminal state."""
        self.submit()
        self.status_banner.wait_for(state="visible", timeout=timeout)
        # Poll until status is no longer 'pending' or 'running'
        self._page.wait_for_function(
            """() => {
                const el = document.querySelector('[data-testid="job-status-display"]');
                return el && !['pending', 'running'].includes(el.textContent.trim());
            }""",
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# Dashboard — recent jobs table
# ---------------------------------------------------------------------------


class JobsTable:
    """Helpers for the recent jobs table on the dashboard."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def table(self):
        return self._page.locator('[data-testid="jobs-table"]')

    def rows(self):
        return self._page.locator('[data-testid="job-row"]')

    def no_jobs_msg(self):
        return self._page.locator('[data-testid="no-jobs-msg"]')


# ---------------------------------------------------------------------------
# Configs page
# ---------------------------------------------------------------------------


class ConfigsPage:
    """Helpers for the ``/configs`` page."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def table(self):
        return self._page.locator('[data-testid="configs-table"]')

    def rows(self):
        return self._page.locator('[data-testid="config-row"]')

    def no_configs_msg(self):
        return self._page.locator('[data-testid="no-configs-msg"]')

    def delete_buttons(self):
        return self._page.locator('[data-testid="config-delete-btn"]')


# ---------------------------------------------------------------------------
# Definitions page
# ---------------------------------------------------------------------------


class DefinitionsPage:
    """Helpers for the ``/definitions`` page."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def table(self):
        return self._page.locator('[data-testid="definitions-table"]')

    def rows(self):
        return self._page.locator('[data-testid="definition-row"]')

    def no_definitions_msg(self):
        return self._page.locator('[data-testid="no-definitions-msg"]')

    def row_for_type_key(self, type_key: str):
        return self._page.locator(f'[data-testid="definition-row"][data-type-key="{type_key}"]')
