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
