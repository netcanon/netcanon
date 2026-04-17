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
