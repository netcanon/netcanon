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


class TestNavigation:
    def test_dashboard_title(self, page: Page, base_url: str):
        page.goto("/")
        expect(page).to_have_title("Dashboard — Netcanon")

    def test_nav_brand_visible(self, page: Page, base_url: str):
        page.goto("/")
        nav = NavBar(page)
        expect(nav.brand).to_have_text("Netcanon")

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
        expect(page).to_have_title("Configs — Netcanon")

    def test_definitions_page_title(self, page: Page, base_url: str):
        page.goto("/definitions")
        expect(page).to_have_title("Definitions — Netcanon")


class TestThemeToggle:
    """Global dark-mode toggle on the top nav (``data-testid``
    ``nav-theme-toggle``).  Covers:

    * Button is always visible on the nav across pages.
    * Click flips `<html data-theme>` between ``light``/``dark``.
    * Choice persists to ``localStorage["netconfig.theme.v1"]``.
    * Reload re-applies the persisted theme (no flash of wrong
      theme — the inline boot script in ``<head>`` runs before
      CSS parses).
    * ``aria-label`` + ``aria-pressed`` reflect the next-action
      (not the current state) for screen-reader clarity.
    """

    def _theme_attr(self, page: Page) -> str:
        return page.locator("html").get_attribute("data-theme") or ""

    def _stored_theme(self, page: Page) -> str:
        return page.evaluate(
            "() => localStorage.getItem('netconfig.theme.v1') || ''"
        )

    def test_toggle_button_visible_on_dashboard(
        self, page: Page, base_url: str,
    ):
        page.goto("/")
        btn = page.get_by_test_id("nav-theme-toggle")
        expect(btn).to_be_visible()

    def test_toggle_button_visible_on_jobs(
        self, page: Page, base_url: str,
    ):
        """Regression guard: the toggle lives in base.html, so every
        page that extends it should expose the button."""
        page.goto("/jobs")
        btn = page.get_by_test_id("nav-theme-toggle")
        expect(btn).to_be_visible()

    def test_click_flips_theme(self, page: Page, base_url: str):
        page.goto("/")
        # Reset local state so the test is deterministic regardless
        # of OS prefers-color-scheme.
        page.evaluate(
            "() => { localStorage.setItem('netconfig.theme.v1', 'light'); "
            "document.documentElement.setAttribute('data-theme', 'light'); }"
        )
        assert self._theme_attr(page) == "light"
        page.get_by_test_id("nav-theme-toggle").click()
        assert self._theme_attr(page) == "dark"
        assert self._stored_theme(page) == "dark"
        page.get_by_test_id("nav-theme-toggle").click()
        assert self._theme_attr(page) == "light"
        assert self._stored_theme(page) == "light"

    def test_choice_persists_across_reload(
        self, page: Page, base_url: str,
    ):
        page.goto("/")
        page.evaluate(
            "() => localStorage.setItem('netconfig.theme.v1', 'dark')"
        )
        page.reload()
        assert self._theme_attr(page) == "dark"

    def test_aria_label_reflects_next_action(
        self, page: Page, base_url: str,
    ):
        """Screen-reader UX: the button labels describe the ACTION
        clicking performs, not the current state.  Mirrors common
        accessibility guidance."""
        page.goto("/")
        page.evaluate(
            "() => { localStorage.setItem('netconfig.theme.v1', 'light'); "
            "document.documentElement.setAttribute('data-theme', 'light'); "
            "_updateThemeToggleAriaLabel('light'); }"
        )
        btn = page.get_by_test_id("nav-theme-toggle")
        expect(btn).to_have_attribute("aria-label", "Switch to dark theme")
        expect(btn).to_have_attribute("aria-pressed", "false")
        btn.click()
        expect(btn).to_have_attribute("aria-label", "Switch to light theme")
        expect(btn).to_have_attribute("aria-pressed", "true")

    def test_body_background_reflects_theme(
        self, page: Page, base_url: str,
    ):
        """End-to-end visual check: clicking the toggle actually
        changes the page's rendered background colour via the
        CSS variable chain.  Guards against regressions where the
        data-theme attribute flips but the var(--page-bg)
        reference doesn't resolve."""
        page.goto("/")
        # Force light for deterministic baseline.
        page.evaluate(
            "() => { localStorage.setItem('netconfig.theme.v1', 'light'); "
            "document.documentElement.setAttribute('data-theme', 'light'); }"
        )
        light_bg = page.evaluate(
            "() => getComputedStyle(document.body).backgroundColor"
        )
        page.get_by_test_id("nav-theme-toggle").click()
        dark_bg = page.evaluate(
            "() => getComputedStyle(document.body).backgroundColor"
        )
        # Exact values are the theme tokens; we just assert they
        # differ — keeps the test resilient to colour-tuning.
        assert light_bg != dark_bg, (
            f"body background did not change when theme flipped: "
            f"still {light_bg}"
        )
