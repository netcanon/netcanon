"""
Integration tests for the Swagger UI ``/docs`` page wrapping.

Phase-3 Round-7.2 deliverable.  The page is built from
``fastapi.openapi.docs.get_swagger_ui_html()`` then post-processed
in ``netcanon.api.routes.ui:swagger_ui`` to inject:

1. A theme-detect boot script (reads localStorage + sets
   ``<html data-theme>``).
2. Token definitions (``:root`` + ``[data-theme="dark"]`` blocks)
   — duplicated from base.html because the docs page doesn't
   extend base.html.
3. The Netcanon nav bar with right-rail `?` cheatsheet trigger
   + theme toggle.
4. A local ``toggleTheme()`` JS function.
5. ``[data-theme="dark"] .swagger-ui ...`` CSS overrides for the
   Swagger UI internals.

These tests pin the structural contract — every piece must be
present.  They don't assert visual fidelity (that's the user
visual loop) or that the Swagger UI bundle itself initializes
correctly (that requires Playwright + the CDN fetch).

Also covers the ``?show-shortcuts=1`` URL-param hook in
``_partials/kbd-cheatsheet.js`` — the docs page's `?` button
navigates to ``/?show-shortcuts=1`` and base.html auto-opens the
modal there.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


class TestDocsPageBoot:
    """Boot-script must run before any CSS applies (so the page paints
    in the right theme without FOUC).  Tokens must be defined for the
    nav and Swagger overrides to resolve."""

    def test_boot_script_sets_data_theme(self, client):
        resp = client.get("/docs")
        assert resp.status_code == 200
        # The boot script reads localStorage + sets data-theme on
        # <html>.  Look for the canonical pattern.
        assert "netcanon.theme.v1" in resp.text
        assert "document.documentElement.setAttribute('data-theme'" in resp.text

    def test_root_tokens_defined(self, client):
        resp = client.get("/docs")
        # Spot-check the tokens the nav + Swagger overrides reference.
        for token in (
            "--page-bg",
            "--surface",
            "--surface-alt",
            "--text-primary",
            "--text-muted",
            "--nav-bg",
            "--nav-fg",
            "--accent",
        ):
            assert token in resp.text, "missing token: {}".format(token)

    def test_dark_theme_overrides_defined(self, client):
        resp = client.get("/docs")
        # The dark-mode override block must be present.
        assert '[data-theme="dark"]' in resp.text


class TestDocsNavBar:
    """The nav bar must mirror base.html's structure: page-nav links
    cluster on the left, spacer, then right-rail `?` cheatsheet
    trigger + theme toggle."""

    def test_brand_link_present(self, client):
        resp = client.get("/docs")
        assert 'data-testid="nav-brand"' in resp.text
        assert 'class="brand"' in resp.text

    @pytest.mark.parametrize("testid,href", [
        ("nav-home", "/"),
        ("nav-devices", "/devices"),
        ("nav-jobs", "/jobs"),
        ("nav-schedules", "/schedules"),
        ("nav-configs", "/configs"),
        ("nav-definitions", "/definitions"),
        ("nav-migrate", "/migrate"),
        ("nav-sanitize", "/sanitize"),
        ("nav-api-docs", "/docs"),
    ])
    def test_page_nav_links(self, client, testid, href):
        resp = client.get("/docs")
        assert 'data-testid="{}"'.format(testid) in resp.text
        assert 'href="{}"'.format(href) in resp.text

    def test_api_docs_link_marked_active(self, client):
        """The nav-api-docs link should carry class="active" since
        the operator is on /docs.  Slice the whole <a> element and
        assert ``class="active"`` is on it."""
        resp = client.get("/docs")
        # Find the start of the <a> tag carrying the testid by
        # rewinding from the testid attribute to the preceding `<a`.
        idx = resp.text.find('data-testid="nav-api-docs"')
        assert idx > 0
        anchor_start = resp.text.rfind("<a", 0, idx)
        anchor_end = resp.text.find(">", idx)
        anchor_tag = resp.text[anchor_start:anchor_end + 1]
        assert 'class="active"' in anchor_tag, (
            "nav-api-docs link missing active class: " + anchor_tag
        )

    def test_cheatsheet_button_links_to_show_shortcuts(self, client):
        """The right-rail `?` button on /docs is a regular <a> link
        (not a JS-driven button) because the docs page has no modal
        markup of its own.  It navigates to /?show-shortcuts=1 which
        auto-opens the cheatsheet on the home page."""
        resp = client.get("/docs")
        assert 'data-testid="kbd-cheatsheet-open-btn"' in resp.text
        assert 'href="/?show-shortcuts=1"' in resp.text

    def test_theme_toggle_present(self, client):
        resp = client.get("/docs")
        assert 'data-testid="nav-theme-toggle"' in resp.text
        # The button calls toggleTheme(); the JS function must also
        # be inlined on the page (Swagger UI doesn't load base.html's
        # partial).
        assert 'onclick="toggleTheme()"' in resp.text
        assert "function toggleTheme(" in resp.text

    def test_spacer_between_page_nav_and_right_rail(self, client):
        """The nc-spacer element pushes the right-rail buttons to
        the far right.  Mirror base.html's nav structure."""
        resp = client.get("/docs")
        assert 'class="nc-spacer"' in resp.text
        # nc-spacer should appear AFTER the page-nav links but BEFORE
        # the cheatsheet/theme-toggle buttons.
        spacer_pos = resp.text.find('class="nc-spacer"')
        api_docs_pos = resp.text.find('data-testid="nav-api-docs"')
        cheatsheet_pos = resp.text.find(
            'data-testid="kbd-cheatsheet-open-btn"'
        )
        toggle_pos = resp.text.find('data-testid="nav-theme-toggle"')
        assert api_docs_pos < spacer_pos < cheatsheet_pos < toggle_pos


class TestSwaggerDarkOverrides:
    """The CSS that themes Swagger UI's internal class selectors
    (.opblock, .scheme-container, etc.).  These must be wrapped in
    [data-theme="dark"] so they only apply in dark mode + must use
    !important to beat the CDN stylesheet's specificity."""

    def test_opblock_dark_override_present(self, client):
        resp = client.get("/docs")
        # The .opblock background override is the highest-visibility
        # surface (endpoint cards).
        assert '[data-theme="dark"] .swagger-ui .opblock' in resp.text

    def test_scheme_container_dark_override(self, client):
        resp = client.get("/docs")
        # Auth scheme container at the top of the page.
        assert "scheme-container" in resp.text

    def test_uses_important_for_specificity(self, client):
        """Swagger UI's CDN stylesheet wins specificity battles with
        regular [data-theme="dark"] .swagger-ui ... rules unless we
        use !important.  Confirm the override block uses it."""
        resp = client.get("/docs")
        # Find the dark-override CSS block (between the dark token
        # block and </body>) and assert !important is used heavily.
        # Cheap regex-y check: count !important inside <style> blocks.
        important_count = resp.text.count("!important")
        # The nav alone uses ~15 !important declarations; the Swagger
        # overrides add another ~20.  Pin a conservative floor.
        assert important_count >= 20, (
            "expected !important throughout Swagger overrides; "
            "found only {}".format(important_count)
        )

    def test_inputs_themed(self, client):
        """Try-it-out inputs (text/textarea/select) should re-theme."""
        resp = client.get("/docs")
        assert 'input[type="text"]' in resp.text
        assert "textarea" in resp.text


class TestShowShortcutsUrlParam:
    """The home page's URL-param handler auto-opens the cheatsheet
    when the operator navigates from /docs's `?` button."""

    def test_handler_registered_in_partial(self, client):
        """The kbd-cheatsheet.js partial registers a DOMContentLoaded
        handler that reads URLSearchParams."""
        resp = client.get("/")
        # The handler should fire on every base-inheriting page.
        assert "URLSearchParams" in resp.text
        assert "show-shortcuts" in resp.text

    def test_handler_strips_query_param_after_open(self, client):
        """After auto-opening, the URL is rewritten via
        history.replaceState so refreshing doesn't re-open."""
        resp = client.get("/")
        assert "history.replaceState" in resp.text


class TestDocsResponseIntegrity:
    """The post-processing must not break the underlying Swagger UI
    bundle initialization — the SwaggerUIBundle script tag + the
    #swagger-ui div must survive intact."""

    def test_swagger_ui_div_present(self, client):
        resp = client.get("/docs")
        assert 'id="swagger-ui"' in resp.text

    def test_swagger_ui_bundle_script_present(self, client):
        resp = client.get("/docs")
        # The CDN script that boots Swagger UI.
        assert "swagger-ui-bundle.js" in resp.text

    def test_openapi_url_referenced(self, client):
        resp = client.get("/docs")
        assert "/api/v1/openapi.json" in resp.text
