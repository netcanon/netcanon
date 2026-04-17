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


class TestConfigViewerHighlighting:
    """Syntax highlighting paints comments / keywords / numbers."""

    def test_modal_opens_with_filename(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        expect(viewer.modal).to_be_visible()
        expect(viewer.title).to_have_text(filename)

    def test_cfg_content_has_comment_tokens(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        # The canned Cisco output contains `!` comment lines.
        comments = viewer.content.locator(".tok-comment")
        expect(comments.first).to_be_visible()

    def test_cfg_content_has_keyword_tokens(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        # "hostname" and "version" from the canned output are keywords.
        keywords = viewer.content.locator(".tok-keyword")
        assert keywords.count() >= 1

    def test_cfg_content_has_number_tokens(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        # Canned output has "17.9", "1234" → number/IP tokens.
        numbers = viewer.content.locator(".tok-number, .tok-ip")
        assert numbers.count() >= 1

class TestConfigViewerSearch:
    """In-modal search: counter, prev/next, highlighting, keyboard nav."""

    def test_empty_query_shows_no_count(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        expect(viewer.count).to_have_text("")

    def test_search_highlights_matches(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("hostname")
        # Canned output contains one "hostname".
        assert viewer.current_matches().count() >= 1

    def test_search_count_shows_index_and_total(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("hostname")
        # First match is selected automatically → "1 / N".
        expect(viewer.count).to_contain_text("1 /")

    def test_no_match_shows_no_matches_text(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("zzzzz-definitely-absent-zzzzz")
        expect(viewer.count).to_have_text("No matches")

    def test_next_button_advances_current_match(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        # "!" appears multiple times in the canned output.
        viewer.search.fill("!")
        matches = viewer.current_matches()
        total = matches.count()
        assert total >= 2, "need >=2 matches to test next"
        expect(viewer.count).to_contain_text("1 /")
        viewer.next_btn.click()
        expect(viewer.count).to_contain_text("2 /")

    def test_prev_button_wraps_to_last(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("!")
        total = viewer.current_matches().count()
        assert total >= 2
        # At match 1, pressing prev wraps to the last match.
        viewer.prev_btn.click()
        expect(viewer.count).to_contain_text(f"{total} / {total}")

    def test_escape_in_empty_search_closes_modal(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.focus()
        viewer.search.press("Escape")
        expect(viewer.modal).to_be_hidden()

    def test_close_button_hides_modal(self, page: Page, base_url: str):
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        expect(viewer.modal).to_be_visible()
        viewer.close()
        expect(viewer.modal).to_be_hidden()

    def test_cross_span_query_finds_match(self, page: Page, base_url: str):
        """A query that crosses a syntax-highlight span boundary must match.

        The canned Cisco output contains the line ``hostname Router``;
        the tokenizer wraps ``hostname`` in ``<span class="tok-keyword">``
        and leaves `` Router`` as plain text in a sibling text node.
        Before the flat-text search fix this query returned zero matches;
        it must now report at least one.
        """
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("hostname Router")
        # Cross-span match: one logical hit, possibly rendered as 2 marks.
        expect(viewer.count).to_contain_text("1 /")
        assert viewer.current_matches().count() >= 1

    def test_cross_span_match_current_class_applied_to_all_pieces(
        self, page: Page, base_url: str
    ):
        """When a match spans boundaries, every <mark> in the group gets
        ``.current`` so the highlight visually reads as one selection."""
        filename = ensure_cisco_config(page)
        page.goto("/configs")
        viewer = ConfigViewer(page)
        viewer.open_for(filename)
        viewer.search.fill("hostname Router")
        # All marks created by this search share the class (single match,
        # so every mark in the DOM belongs to the current group).
        current = viewer.content.locator("mark.current")
        assert current.count() >= 1
