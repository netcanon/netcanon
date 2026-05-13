"""
Integration tests for the keyboard-shortcut cheatsheet modal.

Phase-3 Round-7 deliverable.  The cheatsheet is global chrome rendered
by ``base.html``, so its surface tests live alongside the other base-
level UI surfaces.  Validates that:

* every testid the partial declares is present on every page that
  extends ``base.html`` (we sample a handful — dashboard, sanitize,
  migrate, configs, jobs, schedules, devices, definitions);
* the nav-bar trigger button is present and accessible-labelled;
* the modal is hidden by default (display:none) and only opens via
  the `?` keypress or the trigger button (JS-driven; not asserted
  at the integration layer — covered separately if/when we wire
  Playwright);
* all four shortcut sections are rendered (global, config viewer,
  diff, configs);
* the JS partial is wired into base.html and references the open
  function the nav button calls.

Submit-flow / open-flow tests are out of scope here — the modal is
static markup; behavioural verification is the user-visual loop +
future Playwright coverage.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


# Every testid the cheatsheet template renders synchronously.
SYNC_TESTIDS = [
    "kbd-cheatsheet-open-btn",
    "kbd-cheatsheet",
    "kbd-cheatsheet-title",
    "kbd-cheatsheet-close",
    "kbd-cheatsheet-body",
    "kbd-cheatsheet-section-global",
    "kbd-cheatsheet-section-config-viewer",
    "kbd-cheatsheet-section-diff",
    "kbd-cheatsheet-section-configs",
]


# Sample of routes that extend base.html.  If a future page adds
# `extends "base.html"` it inherits the cheatsheet for free; we
# don't need to backfill this list every time.
BASE_INHERITING_ROUTES = [
    "/",
    "/devices",
    "/jobs",
    "/schedules",
    "/configs",
    "/definitions",
    "/migrate",
    "/sanitize",
]


class TestCheatsheetTestids:
    """Every testid the cheatsheet declares must appear on every base-
    inheriting page.  This catches regressions where a template edit
    drops a testid + breaks downstream automation."""

    @pytest.mark.parametrize("route", BASE_INHERITING_ROUTES)
    def test_all_testids_present(self, client, route):
        resp = client.get(route)
        assert resp.status_code == 200, (
            "{} returned {}".format(route, resp.status_code)
        )
        missing = [
            tid for tid in SYNC_TESTIDS
            if 'data-testid="{}"'.format(tid) not in resp.text
        ]
        assert not missing, (
            "missing cheatsheet testids on {}: {}".format(
                route, ", ".join(missing)
            )
        )


class TestCheatsheetTriggerButton:
    """Nav-bar `?` button — discoverability lever for operators who
    don't know about the `?` keypress."""

    def test_trigger_button_calls_open_function(self, client):
        resp = client.get("/")
        # Locate the trigger button + assert its onclick wires to the
        # JS open function.
        btn_chunk = (
            resp.text.split('data-testid="kbd-cheatsheet-open-btn"')[1]
            .split("</button>")[0]
        )
        assert "openKbdCheatsheet()" in btn_chunk

    def test_trigger_button_has_accessible_label(self, client):
        resp = client.get("/")
        btn_chunk = (
            resp.text.split('data-testid="kbd-cheatsheet-open-btn"')[1]
            .split(">")[0]
        )
        assert 'aria-label="Show keyboard shortcuts"' in btn_chunk

    def test_trigger_button_has_tooltip_referencing_key(self, client):
        """Tooltip should mention the keyboard activation so operators
        learn the shortcut from hovering the button."""
        resp = client.get("/")
        btn_chunk = (
            resp.text.split('data-testid="kbd-cheatsheet-open-btn"')[1]
            .split(">")[0]
        )
        assert 'title="Keyboard shortcuts (?)"' in btn_chunk

    def test_trigger_button_appears_before_theme_toggle(self, client):
        """The cheatsheet button sits between the nav spacer and the
        theme toggle — verify its position so we catch accidental
        reordering."""
        resp = client.get("/")
        cheatsheet_pos = resp.text.find(
            'data-testid="kbd-cheatsheet-open-btn"'
        )
        theme_pos = resp.text.find('data-testid="nav-theme-toggle"')
        assert 0 < cheatsheet_pos < theme_pos


class TestCheatsheetContent:
    """The shortcut sections must be present + contain expected key
    references.  These are tight assertions because the cheatsheet
    IS the documentation source — drift between actual shortcuts and
    cheatsheet copy would mislead operators."""

    def test_global_section_documents_question_mark(self, client):
        resp = client.get("/")
        # Locate the global section + assert ``?`` and ``Esc`` are
        # documented within its <dl>.
        body = resp.text.split(
            'data-testid="kbd-cheatsheet-body"'
        )[1].split("</div>")[0]
        global_chunk = body.split(
            'data-testid="kbd-cheatsheet-section-global"'
        )[1].split("</dl>")[0]
        assert '<span class="kbd">?</span>' in global_chunk
        assert '<span class="kbd">Esc</span>' in global_chunk

    def test_config_viewer_section_documents_enter_and_shift_enter(self, client):
        resp = client.get("/")
        body = resp.text.split(
            'data-testid="kbd-cheatsheet-body"'
        )[1].split("</div>")[0]
        cv_chunk = body.split(
            'data-testid="kbd-cheatsheet-section-config-viewer"'
        )[1].split("</dl>")[0]
        assert '<span class="kbd">Enter</span>' in cv_chunk
        assert '<span class="kbd">Shift</span>' in cv_chunk

    def test_diff_section_documents_enter_and_space(self, client):
        resp = client.get("/")
        body = resp.text.split(
            'data-testid="kbd-cheatsheet-body"'
        )[1].split("</div>")[0]
        diff_chunk = body.split(
            'data-testid="kbd-cheatsheet-section-diff"'
        )[1].split("</dl>")[0]
        assert '<span class="kbd">Enter</span>' in diff_chunk
        assert '<span class="kbd">Space</span>' in diff_chunk

    def test_configs_section_documents_escape(self, client):
        resp = client.get("/")
        body = resp.text.split(
            'data-testid="kbd-cheatsheet-body"'
        )[1].split("</div>")[0]
        configs_chunk = body.split(
            'data-testid="kbd-cheatsheet-section-configs"'
        )[1].split("</dl>")[0]
        assert '<span class="kbd">Esc</span>' in configs_chunk


class TestCheatsheetWiring:
    """The cheatsheet JS partial must be included + the open/close
    functions must be referenced by the trigger button and close
    button respectively."""

    def test_partial_js_is_included(self, client):
        """The JS that defines ``openKbdCheatsheet`` / ``closeKbdCheatsheet``
        must be present in the rendered HTML so the trigger button's
        onclick handler resolves."""
        resp = client.get("/")
        assert "function openKbdCheatsheet" in resp.text
        assert "function closeKbdCheatsheet" in resp.text

    def test_question_mark_keypress_handler_registered(self, client):
        """The global ``?`` listener is what makes the cheatsheet
        discoverable without finding the nav button.  Assert the
        partial registers it."""
        resp = client.get("/")
        assert "e.key !== '?'" in resp.text

    def test_modal_hidden_by_default(self, client):
        """The outer modal div carries inline `display:none` via CSS;
        opening is JS-driven.  Verify the CSS rule is shipped."""
        resp = client.get("/")
        # The CSS rule should set the outer modal to display:none.
        assert "#_kbd-cheatsheet { display:none" in resp.text

    def test_input_focus_guard_present(self, client):
        """The ``?`` handler must bail out when a text-editable field
        is focused — otherwise operators typing ``?`` into the search
        input or a host field would trigger the modal."""
        resp = client.get("/")
        assert "_kbdIsTextEditableTarget" in resp.text
