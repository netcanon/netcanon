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


class TestDiffApi:
    """E2E-level checks via the live API (complements integration tests).

    Goal: prove the wiring from HTTP → service → response works end-to-end
    against a real filesystem store, not just the TestClient.
    """

    def test_same_type_returns_ok_compat(self, page: Page, base_url: str):
        files = ensure_n_configs_of_type(page, "Cisco", 2)
        resp = page.request.post(
            "/api/v1/configs/diff",
            data={"left": files[0], "right": files[1]},
        )
        assert resp.ok
        report = resp.json()
        assert report["compatibility"]["severity"] == "ok"

    def test_cross_vendor_without_force_is_422(self, page: Page, base_url: str):
        cisco_files = ensure_n_configs_of_type(page, "Cisco", 1)
        opn_files = ensure_n_configs_of_type(page, "OPNsense", 1)
        resp = page.request.post(
            "/api/v1/configs/diff",
            data={"left": cisco_files[0], "right": opn_files[0]},
        )
        assert resp.status == 422

class TestDiffPageUI:
    """Compare button → picker → diff page flow."""

    def test_compare_button_visible_on_configs_page(self, page: Page, base_url: str):
        ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto("/configs")
        cp = ConfigsPage(page)
        expect(cp.compare_buttons().first).to_be_visible()

    def test_picker_opens_on_compare_click(self, page: Page, base_url: str):
        files = ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto("/configs")
        cp = ConfigsPage(page)
        cp.open_compare_for(files[0])
        picker = ComparePicker(page)
        expect(picker.modal).to_be_visible()

    def test_picker_lists_same_type_as_compatible(self, page: Page, base_url: str):
        files = ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto("/configs")
        ConfigsPage(page).open_compare_for(files[0])
        picker = ComparePicker(page)
        # At least one compatible option (the other Cisco config).
        assert picker.options().count() >= 1

    def test_picker_hides_cross_vendor_until_toggle(self, page: Page, base_url: str):
        ensure_n_configs_of_type(page, "Cisco", 1)
        ensure_n_configs_of_type(page, "OPNsense", 1)
        records = page.request.get("/api/v1/configs/").json()
        cisco = [r for r in records if r["device_type"] == "Cisco"][0]
        page.goto("/configs")
        ConfigsPage(page).open_compare_for(cisco["filename"])
        picker = ComparePicker(page)
        # Cross-vendor options are hidden by default.
        expect(picker.cross_vendor_options()).to_have_count(0)
        picker.show_all.check()
        # Once toggled, at least one cross-vendor option appears.
        assert picker.cross_vendor_options().count() >= 1

    def test_close_button_hides_picker(self, page: Page, base_url: str):
        files = ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto("/configs")
        ConfigsPage(page).open_compare_for(files[0])
        picker = ComparePicker(page)
        expect(picker.modal).to_be_visible()
        picker.close_btn.click()
        expect(picker.modal).to_be_hidden()

class TestDiffPageContent:
    """Direct hits on ``/configs/{left}/vs/{right}`` — banner, stats, swap."""

    def test_same_type_renders_green_ok_banner(self, page: Page, base_url: str):
        files = ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto(f"/configs/{files[0]}/vs/{files[1]}")
        diff = DiffPage(page)
        assert diff.banner_severity() == "ok"

    def test_cross_vendor_renders_block_banner_with_override_btn(
        self, page: Page, base_url: str
    ):
        ensure_n_configs_of_type(page, "Cisco", 1)
        ensure_n_configs_of_type(page, "OPNsense", 1)
        records = page.request.get("/api/v1/configs/").json()
        cisco = [r for r in records if r["device_type"] == "Cisco"][0]
        opn = [r for r in records if r["device_type"] == "OPNsense"][0]
        page.goto(f"/configs/{cisco['filename']}/vs/{opn['filename']}")
        diff = DiffPage(page)
        assert diff.banner_severity() == "block"
        expect(diff.force_override_btn).to_be_visible()

    def test_force_override_renders_diff_body(self, page: Page, base_url: str):
        ensure_n_configs_of_type(page, "Cisco", 1)
        ensure_n_configs_of_type(page, "OPNsense", 1)
        records = page.request.get("/api/v1/configs/").json()
        cisco = [r for r in records if r["device_type"] == "Cisco"][0]
        opn = [r for r in records if r["device_type"] == "OPNsense"][0]
        page.goto(
            f"/configs/{cisco['filename']}/vs/{opn['filename']}?force=true"
        )
        diff = DiffPage(page)
        assert diff.banner_severity() == "block"
        # With force=true the body renders — either as visible diff-line
        # rows (when changes are tightly interleaved) or collapsed markers
        # (when long equal runs got folded).  Either is evidence of a
        # populated diff body.
        visible = diff.lines().count() + diff.collapsed_markers().count()
        assert visible > 0

    def test_same_file_diff_has_zero_added_zero_removed(
        self, page: Page, base_url: str
    ):
        files = ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/{files[0]}")
        diff = DiffPage(page)
        expect(diff.stats_added).to_have_text("+0")
        expect(diff.stats_removed).to_contain_text("0")

    def test_missing_file_renders_404_banner(self, page: Page, base_url: str):
        files = ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/Cisco_0-0-0-0_20000101_000000.cfg")
        diff = DiffPage(page)
        assert diff.banner_severity() == "block"
        expect(diff.banner).to_contain_text("Not found")

    def test_reverse_direction_link_reverses_url(self, page: Page, base_url: str):
        """The "Reverse direction" button swaps baseline ↔ current by
        pointing at the ``right/vs/left`` URL."""
        files = ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto(f"/configs/{files[0]}/vs/{files[1]}")
        diff = DiffPage(page)
        href = diff.reverse_btn.get_attribute("href") or ""
        # URL contains right-then-left after reversing.
        assert files[1] in href
        assert href.index(files[1]) < href.index(files[0])

    def test_from_and_to_role_labels_visible(
        self, page: Page, base_url: str
    ):
        """The directional paradigm is surfaced to the user explicitly —
        not implied by chip position.  ``from``/``to`` is temporally
        neutral (unlike ``current``, which implied 'this is now')."""
        files = ensure_n_configs_of_type(page, "Cisco", 2)
        page.goto(f"/configs/{files[0]}/vs/{files[1]}")
        expect(page.locator('[data-testid="diff-from-label"]')).to_be_visible()
        expect(page.locator('[data-testid="diff-to-label"]')).to_be_visible()

class TestDiffContextFolding:
    """Long runs of equal lines collapse into expandable markers so large
    configs don't render tens of thousands of DOM rows up front."""

    def test_identical_configs_collapse_to_one_marker(self, page: Page, base_url: str):
        """A diff with zero changes means every line is cold → one group."""
        files = ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/{files[0]}")
        diff = DiffPage(page)
        # The FakeCollector's canned Cisco output has >= a few equal lines.
        expect(diff.collapsed_markers().first).to_be_visible()
        # Since there are no changes, no visible diff-line rows exist.
        expect(diff.lines()).to_have_count(0)

    def test_collapsed_marker_announces_hidden_line_count(
        self, page: Page, base_url: str
    ):
        """The marker text advertises how many lines it hides."""
        files = ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/{files[0]}")
        diff = DiffPage(page)
        marker = diff.collapsed_markers().first
        count_attr = marker.get_attribute("data-count")
        # Canned Cisco output has multiple lines; count must be positive.
        assert count_attr is not None and int(count_attr) >= 1
        # Text explicitly mentions "unchanged".
        expect(marker).to_contain_text("unchanged")

    def test_click_collapsed_marker_expands_in_place(
        self, page: Page, base_url: str
    ):
        """Clicking a collapsed marker swaps in its hidden lines and removes
        the marker itself (same effect as GitHub's ↕ expander)."""
        files = ensure_n_configs_of_type(page, "Cisco", 1)
        page.goto(f"/configs/{files[0]}/vs/{files[0]}")
        diff = DiffPage(page)
        marker = diff.collapsed_markers().first
        hidden_count = int(marker.get_attribute("data-count") or "0")
        assert hidden_count >= 1, "need >= 1 hidden line to test expansion"
        assert diff.lines().count() == 0

        marker.click()

        # Marker is gone, hidden lines are now visible diff-line rows.
        expect(diff.collapsed_markers()).to_have_count(0)
        assert diff.lines().count() == hidden_count
