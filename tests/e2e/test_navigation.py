"""
E2E tests — split from test_backup_flow.py for maintainability.

All selectors use data-testid attributes.  See tests/testid_reference.md.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import (
    NavBar,
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
    """Global light/dark toggle on the top nav (``data-testid``
    ``nav-theme-toggle``), rewired to the unified theme runtime
    (vendored ``_vendor/theme-picker.js``).  Covers:

    * Button is always visible on the nav across pages.
    * Click flips ``<html data-nc-mode>`` between ``light``/``dark``
      via ``NcTheme.set(null, mode)``.
    * Choice persists to ``localStorage["nc-mode"]`` and is mirrored
      one-way into the legacy ``netcanon.theme.v1`` key (the
      self-contained /docs page still reads it).
    * A pre-unification ``netcanon.theme.v1`` value migrates into
      ``nc-mode`` exactly once at boot.
    * Reload re-applies the persisted mode (no flash of wrong mode —
      ``NcTheme.boot()`` runs inline in ``<head>`` before CSS
      parses).
    * ``aria-label`` + ``aria-pressed`` reflect the next-action
      (not the current state) for screen-reader clarity.
    """

    def _mode_attr(self, page: Page) -> str:
        return page.locator("html").get_attribute("data-nc-mode") or ""

    def _stored_mode(self, page: Page) -> str:
        return page.evaluate(
            "() => localStorage.getItem('nc-mode') || ''"
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
        page.evaluate("() => NcTheme.set(null, 'light')")
        assert self._mode_attr(page) == "light"
        page.get_by_test_id("nav-theme-toggle").click()
        assert self._mode_attr(page) == "dark"
        assert self._stored_mode(page) == "dark"
        # One-way mirror keeps the self-contained /docs page in step.
        assert page.evaluate(
            "() => localStorage.getItem('netcanon.theme.v1')"
        ) == "dark"
        page.get_by_test_id("nav-theme-toggle").click()
        assert self._mode_attr(page) == "light"
        assert self._stored_mode(page) == "light"

    def test_choice_persists_across_reload(
        self, page: Page, base_url: str,
    ):
        page.goto("/")
        page.evaluate(
            "() => localStorage.setItem('nc-mode', 'dark')"
        )
        page.reload()
        assert self._mode_attr(page) == "dark"

    def test_legacy_key_migrates_once(
        self, page: Page, base_url: str,
    ):
        """A pre-unification user's persisted netcanon.theme.v1 value
        is copied into nc-mode at boot — only while nc-mode is unset,
        so the user's newer unified choice always wins."""
        page.goto("/")
        page.evaluate(
            "() => { localStorage.clear(); "
            "localStorage.setItem('netcanon.theme.v1', 'dark'); }"
        )
        page.reload()
        assert self._mode_attr(page) == "dark"
        assert self._stored_mode(page) == "dark"

    def test_aria_label_reflects_next_action(
        self, page: Page, base_url: str,
    ):
        """Screen-reader UX: the button labels describe the ACTION
        clicking performs, not the current state.  Mirrors common
        accessibility guidance."""
        page.goto("/")
        page.evaluate(
            "() => { NcTheme.set(null, 'light'); "
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
        CSS variable chain (nc tokens -> compat shim -> legacy var
        names).  Guards against regressions where data-nc-mode flips
        but var(--page-bg) doesn't resolve through the shim."""
        page.goto("/")
        # Force light for deterministic baseline.
        page.evaluate("() => NcTheme.set(null, 'light')")
        light_bg = page.evaluate(
            "() => getComputedStyle(document.body).backgroundColor"
        )
        page.get_by_test_id("nav-theme-toggle").click()
        # ``body`` animates ``background-color`` over a ~.15s CSS transition
        # (suppressed for ~80ms by the runtime's data-nc-switching guard),
        # so reading the computed value *immediately* after the click can
        # return the pre-/mid-transition (still-light) colour — a flaky
        # read.  Poll until the rendered background has actually moved off
        # the light token before asserting; if it genuinely never changes
        # this times out and the failure points at a real var(--page-bg)
        # regression, not timing.
        page.wait_for_function(
            "light => getComputedStyle(document.body).backgroundColor !== light",
            arg=light_bg,
            timeout=3000,
        )
        dark_bg = page.evaluate(
            "() => getComputedStyle(document.body).backgroundColor"
        )
        # Exact values are the theme tokens; we just assert they
        # differ — keeps the test resilient to colour-tuning.
        assert light_bg != dark_bg, (
            f"body background did not change when theme flipped: "
            f"still {light_bg}"
        )
