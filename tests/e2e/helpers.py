"""
Page-object helpers and test utilities for E2E tests.

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

    def go_to_jobs(self) -> None:
        self._page.locator('[data-testid="nav-jobs"]').click()
        self._page.wait_for_url("**/jobs")

    def go_to_schedules(self) -> None:
        self._page.locator('[data-testid="nav-schedules"]').click()
        self._page.wait_for_url("**/schedules")

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
        """Backward-compat alias — points at the new floating panel.

        Older tests call this ``status_banner``; the current implementation
        is the global ``job-progress-panel`` in base.html (the inline banner
        was removed when the panel was introduced).
        """
        return self._page.locator('[data-testid="job-progress-panel"]')

    @property
    def job_status_display(self):
        """Aggregated job status text embedded in the panel header.

        Still exposed under the legacy ``job-status-display`` testid so the
        existing ``submit_and_wait`` helper keeps working.
        """
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

    def compare_buttons(self):
        return self._page.locator('[data-testid="config-compare-btn"]')

    def open_compare_for(self, filename: str):
        """Click the Compare button on the row with *filename*."""
        self._page.locator(
            f'[data-testid="config-row"][data-filename="{filename}"] '
            f'[data-testid="config-compare-btn"]'
        ).click()


class ComparePicker:
    """Helpers for the Compare target-picker modal on the configs page."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def modal(self):
        return self._page.locator('[data-testid="compare-picker"]')

    @property
    def title(self):
        return self._page.locator('[data-testid="compare-picker-title"]')

    @property
    def body(self):
        return self._page.locator('[data-testid="compare-picker-body"]')

    @property
    def show_all(self):
        return self._page.locator('[data-testid="compare-picker-show-all"]')

    @property
    def close_btn(self):
        return self._page.locator('[data-testid="compare-picker-close"]')

    def options(self):
        """Compatible (same type_key + ext) options."""
        return self._page.locator('[data-testid="compare-option"]')

    def cross_vendor_options(self):
        return self._page.locator('[data-testid="compare-option-cross-vendor"]')


class DiffPage:
    """Helpers for the ``/configs/{left}/vs/{right}`` diff page."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def banner(self):
        return self._page.locator('[data-testid="diff-compatibility-banner"]')

    def banner_severity(self) -> str:
        """Return ``ok`` / ``warn`` / ``block`` from the banner's attr."""
        return self.banner.get_attribute("data-severity") or ""

    @property
    def left_chip(self):
        return self._page.locator('[data-testid="diff-left-filename"]')

    @property
    def right_chip(self):
        return self._page.locator('[data-testid="diff-right-filename"]')

    @property
    def stats_added(self):
        return self._page.locator('[data-testid="diff-stats-added"]')

    @property
    def stats_removed(self):
        return self._page.locator('[data-testid="diff-stats-removed"]')

    @property
    def force_override_btn(self):
        return self._page.locator('[data-testid="diff-force-override-btn"]')

    @property
    def reverse_btn(self):
        """The "Reverse direction" link — makes ``right`` the new baseline.

        (Previously named ``swap_sides_btn`` / ``diff-swap-sides-btn`` back
        when the button was framed as "Swap sides".  The unified-diff layout
        has directionality — baseline → current — not sides.)
        """
        return self._page.locator('[data-testid="diff-reverse-btn"]')

    def lines(self):
        return self._page.locator('[data-testid="diff-line"]')

    def collapsed_markers(self):
        return self._page.locator('[data-testid="diff-line-collapsed"]')


# ---------------------------------------------------------------------------
# Job progress panel (global — floating widget injected by base.html)
# ---------------------------------------------------------------------------


class JobProgressPanel:
    """Helpers for the persistent floating backup-progress panel.

    The panel is rendered in ``base.html`` so it's available from every page
    and survives both navigation and full page reloads (the active job ID
    is held in ``localStorage`` under ``netconfig.activeJob``).

    Per-device rows carry ``data-host`` and ``data-status`` attributes so
    tests can assert specific devices reach specific states without poking
    at the DOM structure.
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def panel(self):
        return self._page.locator('[data-testid="job-progress-panel"]')

    @property
    def header(self):
        return self._page.locator('[data-testid="job-progress-header"]')

    @property
    def summary(self):
        return self._page.locator('[data-testid="job-progress-summary"]')

    @property
    def body(self):
        return self._page.locator('[data-testid="job-progress-body"]')

    @property
    def footer(self):
        return self._page.locator('[data-testid="job-progress-footer"]')

    @property
    def dismiss_btn(self):
        return self._page.locator('[data-testid="job-progress-dismiss"]')

    @property
    def view_link(self):
        return self._page.locator('[data-testid="job-progress-view-link"]')

    def device_rows(self):
        return self._page.locator('[data-testid="job-progress-device-row"]')

    def row_for(self, host: str):
        return self._page.locator(
            f'[data-testid="job-progress-device-row"][data-host="{host}"]'
        )

    def status_of(self, host: str) -> str:
        """Return the current per-device status string (queued/running/success/failed)."""
        return self.row_for(host).get_attribute("data-status") or ""

    def clear_storage(self) -> None:
        """Remove any persisted active-job key from localStorage."""
        self._page.evaluate(
            "() => { try { localStorage.removeItem('netconfig.activeJob'); } catch(_) {} }"
        )


# ---------------------------------------------------------------------------
# Config viewer modal (global — available from any page)
# ---------------------------------------------------------------------------


class ConfigViewer:
    """Helpers for the config viewer modal injected by ``base.html``.

    The modal is rendered on every page and is opened by clicking any
    ``[data-testid="config-view-link"]`` / ``[data-testid="job-config-view-link"]``
    element (or by calling ``viewConfig(filename)`` directly in JS).

    Attributes:
        modal: The outer modal container.
        title: Displayed filename in the header.
        content: The ``<pre>`` holding the highlighted config text.
        search: The in-modal search input.
        count: "N / M" match counter (empty when no query).
        prev_btn / next_btn: Previous / next match buttons.
        close_btn: The ``×`` close button.
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def modal(self):
        return self._page.locator('[data-testid="config-viewer"]')

    @property
    def title(self):
        return self._page.locator('[data-testid="config-viewer-title"]')

    @property
    def content(self):
        return self._page.locator('[data-testid="config-viewer-content"]')

    @property
    def search(self):
        return self._page.locator('[data-testid="config-viewer-search"]')

    @property
    def count(self):
        return self._page.locator('[data-testid="config-viewer-search-count"]')

    @property
    def prev_btn(self):
        return self._page.locator('[data-testid="config-viewer-search-prev"]')

    @property
    def next_btn(self):
        return self._page.locator('[data-testid="config-viewer-search-next"]')

    @property
    def close_btn(self):
        return self._page.locator('[data-testid="config-viewer-close"]')

    def open_for(self, filename: str) -> None:
        """Programmatically open the viewer for *filename* via JS.

        Faster and more deterministic in tests than clicking the View link.
        """
        self._page.evaluate(f"viewConfig({filename!r})")

    def current_matches(self):
        """Return the live list of current/highlighted match elements."""
        return self.content.locator("mark")

    def close(self) -> None:
        self.close_btn.click()


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


# ---------------------------------------------------------------------------
# Jobs page
# ---------------------------------------------------------------------------


class JobsPage:
    """Helpers for the ``/jobs`` page."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def no_jobs_msg(self):
        return self._page.locator('[data-testid="no-jobs-msg"]')

    def cards(self):
        return self._page.locator('[data-testid="job-card"]')

    def first_card_header(self):
        return self._page.locator('[data-testid="job-card-header"]').first

    def toggle_first_card(self) -> None:
        """Click the first card header to expand or collapse it."""
        self.first_card_header().click()

    def card_body(self, n: int = 0):
        """Return the nth card body (``data-testid="job-card-body"``)."""
        return self._page.locator('[data-testid="job-card-body"]').nth(n)


# ---------------------------------------------------------------------------
# Schedules page
# ---------------------------------------------------------------------------


class SchedulesPage:
    """Helpers for the ``/schedules`` page."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def form(self):
        return self._page.locator('[data-testid="schedule-form"]')

    @property
    def no_schedules_msg(self):
        return self._page.locator('[data-testid="no-schedules-msg"]')

    def rows(self):
        return self._page.locator('[data-testid="schedule-row"]')

    def fill_form(
        self,
        name: str,
        interval_value: str = "1440",
        check_first_type_key: bool = True,
    ) -> None:
        """Fill the schedule form with a name, interval, and target.

        ``interval_value`` is the ``<option value>`` of the interval select.

        ``check_first_type_key`` (default ``True``) ticks the first
        type-key checkbox so the ``ScheduleCreate`` body passes
        validation (at least one target is required).  Set to ``False``
        if you want to test the validation error path.
        """
        self._page.locator('[data-testid="sched-name-input"]').fill(name)
        self._page.locator('[data-testid="sched-interval-select"]').select_option(
            value=interval_value
        )
        if check_first_type_key:
            checkbox = self._page.locator(
                '[data-testid="sched-type-key-checkbox"]'
            ).first
            if not checkbox.is_checked():
                checkbox.check()

    def submit_form(self) -> None:
        """Click the submit button and wait for the page to finish loading."""
        self._page.locator('[data-testid="sched-submit-btn"]').click()
        self._page.wait_for_url("**/schedules")
        self._page.wait_for_load_state("networkidle")

    def toggle_first(self) -> None:
        """Click the first schedule's toggle button and wait for reload."""
        self._page.locator('[data-testid="schedule-toggle-btn"]').first.click()
        self._page.wait_for_load_state("networkidle")

    def delete_first(self) -> None:
        """Click the delete button on the first schedule row.

        This only opens the inline confirm; the caller must click either
        ``schedule-delete-confirm-btn`` (Yes) or ``schedule-delete-cancel-btn``
        (No) to complete the interaction.
        """
        self._page.locator('[data-testid="schedule-delete-btn"]').first.click()


# ---------------------------------------------------------------------------
# Migrate page
# ---------------------------------------------------------------------------


class MigratePage:
    """Helpers for the ``/migrate`` translator workbench.

    The page is a thin form over ``POST /api/v1/migration/plan``; every
    interactive element has a stable ``migrate-*`` testid.  See
    ``tests/testid_reference.md`` for the full inventory.
    """

    def __init__(self, page: Page) -> None:
        self._page = page

    # ---- Form ----

    @property
    def form(self):
        return self._page.locator('[data-testid="migrate-form"]')

    @property
    def source_select(self):
        return self._page.locator('[data-testid="migrate-source-select"]')

    @property
    def target_select(self):
        return self._page.locator('[data-testid="migrate-target-select"]')

    @property
    def adapter_info(self):
        return self._page.locator('[data-testid="migrate-adapter-info"]')

    @property
    def raw_input(self):
        return self._page.locator('[data-testid="migrate-raw-input"]')

    @property
    def submit_btn(self):
        return self._page.locator('[data-testid="migrate-submit-btn"]')

    @property
    def force_checkbox(self):
        return self._page.locator('[data-testid="migrate-force-checkbox"]')

    def pick_source(self, name: str) -> None:
        self.source_select.select_option(value=name)

    def pick_target(self, name: str) -> None:
        self.target_select.select_option(value=name)

    def fill_raw(self, text: str) -> None:
        self.raw_input.fill(text)

    # ---- Results ----

    @property
    def result(self):
        return self._page.locator('[data-testid="migrate-result"]')

    @property
    def banner(self):
        return self._page.locator(
            '[data-testid="migrate-compatibility-banner"]'
        )

    @property
    def output(self):
        return self._page.locator('[data-testid="migrate-output"]')

    @property
    def status_summary(self):
        return self._page.locator('[data-testid="migrate-status-summary"]')

    def banner_severity_class(self) -> str:
        """Return the ``mig-banner-*`` modifier class on the banner.

        Parses the class attribute rather than a dedicated data-severity
        attr — the template applies ``mig-banner-<severity>`` directly.
        """
        classes = (self.banner.get_attribute("class") or "").split()
        for c in classes:
            if c.startswith("mig-banner-"):
                return c.replace("mig-banner-", "")
        return ""

    def submit_and_wait(self) -> None:
        """Submit the form and wait for the results region to render."""
        self.submit_btn.click()
        self.result.wait_for(state="visible", timeout=5_000)

    # ---- Format-hint + sample-loader (Phase 2 polish) ----

    @property
    def format_hint(self):
        return self._page.locator('[data-testid="migrate-format-hint"]')

    @property
    def load_sample_btn(self):
        return self._page.locator('[data-testid="migrate-load-sample-btn"]')

    @property
    def filename_compat_warn(self):
        return self._page.locator(
            '[data-testid="migrate-filename-compat-warn"]'
        )

    def format_hint_format(self) -> str:
        """Return the adapter's declared input_format via the hint banner's
        ``data-input-format`` attribute."""
        return self.format_hint.get_attribute("data-input-format") or ""

    def banner_severity_attr(self) -> str:
        """Read the banner's ``data-severity`` attribute (the authoritative
        source — set by the severity-rules logic, not derivable from
        class strings alone after the #10b fix)."""
        return self.banner.get_attribute("data-severity") or ""


# ---------------------------------------------------------------------------
# Shared test utilities — seed configs via the live API
# ---------------------------------------------------------------------------


def ensure_cisco_config(page: Page) -> str:
    """Make sure at least one Cisco config exists, then return its filename.

    Posts a backup via the API (FakeCollector returns canned Cisco output).
    """
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
    resp = page.request.get("/api/v1/configs/")
    assert resp.ok
    records = resp.json()
    cisco = [r for r in records if r["device_type"] == "Cisco"]
    assert cisco, "expected at least one Cisco config after POST /backups"
    return cisco[0]["filename"]


def ensure_n_configs_of_type(
    page: Page, type_key: str, count: int
) -> list[str]:
    """Create *count* configs of the given type via the live API and
    return their filenames (newest-first)."""
    for i in range(count):
        page.request.post(
            "/api/v1/backups/",
            data={
                "devices": [
                    {
                        "type_key": type_key,
                        "host": f"10.88.{i + 1}.1",
                        "credentials": {"username": "admin", "password": "pw"},
                    }
                ]
            },
        )
    records = page.request.get("/api/v1/configs/").json()
    files = [
        r["filename"] for r in records if r["device_type"] == type_key
    ]
    assert len(files) >= count, f"Seeded configs didn't appear: got {len(files)}"
    return files
