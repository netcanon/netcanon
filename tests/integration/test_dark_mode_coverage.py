"""
Regression guard for Phase-3 Round-7.1 dark-mode coverage sweep.

Visual verification on Round 7 surfaced ~6 pre-existing dark-mode
coverage gaps (vendor chips, compare-picker modal, migrate
textarea / form, sanitize undefined-var fallbacks, schedules
target panels, banner palettes).  This module pins those specific
surfaces against regression — each test asserts that the
problem-pattern (hardcoded ``#fff`` / undefined ``var(--bg-input)``
/ banner literal pairs) is replaced by a theme-token reference.

The discipline this enforces is: when a NEW page or partial is
added, the colour declarations either flow through ``var(--*)``
tokens defined in ``base.html`` or are inside an intentional
always-dark surface (the config-viewer header, the mig-chip
palette, syntax-highlight tok-* classes).  These tests don't catch
every gap — only the recurring patterns that produced visible
operator-facing regressions.  Visual verification remains the
primary discipline; this is just belt-and-braces.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


class TestUndefinedVarFallbacks:
    """``var(--bg-input)`` / ``var(--text)`` / ``var(--bg-card)`` are
    NOT declared in base.html — using them as the only declaration
    causes the fallback (typically ``#fff``) to render.  This was the
    sanitize.html textarea + result-card regression."""

    def test_sanitize_does_not_reference_undefined_bg_input(self, client):
        resp = client.get("/sanitize")
        # ``var(--bg-input`` (no trailing comma — looking for the token
        # name) is not in any defined token set.
        assert "var(--bg-input" not in resp.text, (
            "sanitize.html still references undefined --bg-input token"
        )

    def test_sanitize_does_not_reference_undefined_bg_card(self, client):
        resp = client.get("/sanitize")
        assert "var(--bg-card" not in resp.text

    def test_sanitize_does_not_reference_undefined_text_token(self, client):
        """``var(--text)`` (not ``--text-primary`` / ``--text-muted``) is
        also undefined.  Catch that specifically."""
        resp = client.get("/sanitize")
        # Look for the exact pattern ``var(--text,`` or ``var(--text)``
        # — the ``,`` form has a fallback (defined-token usage would be
        # without a fallback) and ``)`` form means it's standalone.
        assert "var(--text," not in resp.text
        assert "var(--text)" not in resp.text


class TestCardSurfaceTokens:
    """High-severity card surface fixes — devices/jobs cards, configs
    compare-picker box, migrate form + result section.  All should
    use ``var(--surface)`` so dark mode re-themes them."""

    def test_devices_card_uses_surface_token(self, client):
        resp = client.get("/devices")
        # The .device-card CSS rule should be tokenized.
        css_chunk = resp.text.split(".device-card {")[1].split("}")[0]
        assert "var(--surface)" in css_chunk
        # And NOT carry a literal #fff/#ffffff fallback.
        assert "#fff" not in css_chunk.lower()

    def test_jobs_card_uses_surface_token(self, client):
        resp = client.get("/jobs")
        css_chunk = resp.text.split(".job-card {")[1].split("}")[0]
        assert "var(--surface)" in css_chunk
        assert "#fff" not in css_chunk.lower()

    def test_compare_picker_box_uses_surface_token(self, client):
        """The operator-reported white compare-picker modal."""
        resp = client.get("/configs")
        css_chunk = resp.text.split("#compare-picker-box {")[1].split("}")[0]
        assert "var(--surface)" in css_chunk
        assert "#fff" not in css_chunk.lower()

    def test_migrate_form_uses_surface_token(self, client):
        resp = client.get("/migrate")
        css_chunk = resp.text.split(".mig-form {")[1].split("}")[0]
        assert "var(--surface)" in css_chunk
        assert "#fff" not in css_chunk.lower()


class TestBannerPaletteTokens:
    """The diff banner / migrate banner / sanitize info-banner
    triplet shared a hardcoded light-mode palette (``#d4edda/#155724``
    etc.).  Each should flow through ``--badge-*`` / ``--alert-info-*``
    tokens so dark mode re-themes them."""

    def test_diff_banner_ok_uses_badge_token(self, client):
        # Need a diff page that renders; using a forced no-records
        # request returns the error path but the <style> block is still
        # in the response.  Fall back to a direct template route check
        # if the diff endpoint requires real records.
        resp = client.get("/configs")  # configs.html doesn't have diff CSS
        # Instead, check the underlying diff.html template via a route
        # that triggers it.  The diff route is /configs/{left}/vs/{right}
        # which 404s without records — but the response body still
        # carries the CSS because the template still renders.
        # Simplest: read the template directly via Python.
        from pathlib import Path
        diff_html = (
            Path(__file__).resolve().parents[2]
            / "netcanon" / "templates" / "diff.html"
        ).read_text(encoding="utf-8")
        ok_chunk = diff_html.split(".diff-banner-ok")[1].split("}")[0]
        assert "var(--badge-completed-bg)" in ok_chunk
        assert "var(--badge-completed-fg)" in ok_chunk

    def test_migrate_banner_info_uses_alert_token(self, client):
        """The operator-reported 'Source expects:' alert callout."""
        resp = client.get("/migrate")
        info_chunk = resp.text.split(".mig-banner-info")[1].split("}")[0]
        assert "var(--alert-info-bg)" in info_chunk
        assert "var(--alert-info-fg)" in info_chunk

    def test_sanitize_banner_info_uses_alert_token(self, client):
        """The 'For sharing only' safety note callout."""
        resp = client.get("/sanitize")
        # The .san-banner-info rule should reference --alert-info-*.
        info_chunk = resp.text.split(".san-banner-info")[1].split("}")[0]
        assert "var(--alert-info-bg)" in info_chunk
        assert "var(--alert-info-fg)" in info_chunk


class TestChipTokens:
    """Vendor/device-type chip patterns — the operator-reported light
    chips on cards and inside the compare-picker modal."""

    def test_devices_type_chip_inline_style_uses_tokens(self, client):
        """The vendor chip on a device card uses an inline ``style="..."``
        attribute (not a class), so we have to render at least one
        profile to assert the tokens.  Seeds a minimal profile via
        the device-profile API + asserts the rendered chip's inline
        style references the surface-elev token rather than the
        pre-fix #e8e8f0 / #333 hex pair."""
        # Seed via the API so the dependency on persisted state is
        # explicit rather than poking the store directly.
        seed = client.post(
            "/api/v1/devices/",
            json={
                "name": "darkmode-seed",
                "type_key": "Cisco",
                "host": "10.0.0.99",
                "username": "admin",
                "password": "fake",
            },
        )
        assert seed.status_code in (200, 201), seed.text
        resp = client.get("/devices")
        device_chip_chunk = resp.text.split(
            'data-testid="device-type"'
        )[1].split(">")[0]
        assert "var(--surface-elev)" in device_chip_chunk
        assert "#e8e8f0" not in device_chip_chunk.lower()
        assert "#333" not in device_chip_chunk

    def test_compare_picker_type_chip_uses_tokens(self, client):
        resp = client.get("/configs")
        css_chunk = resp.text.split(
            ".compare-option .type-chip {"
        )[1].split("}")[0]
        assert "var(--surface-elev)" in css_chunk
        assert "#e8e8f0" not in css_chunk.lower()


class TestTextareaInheritsBaseRule:
    """The base.html ``input, select, textarea`` rule should include
    ``textarea`` so all textareas inherit theme-aware backgrounds
    (the migrate textarea + sanitize textarea both depend on this)."""

    def test_base_input_rule_includes_textarea(self, client):
        resp = client.get("/")
        # The selector list should be ``input, select, textarea``.
        # Look for the rule pattern.
        assert "input, select, textarea" in resp.text or "input,select,textarea" in resp.text


class TestSchedulesDisabledBadgeUsesTokens:
    """The schedule's Disabled badge variant should reuse the existing
    --badge-pending-* token pair (already defined for the same
    semantic state elsewhere in the app)."""

    def test_disabled_badge_uses_badge_pending_token(self, client):
        resp = client.get("/schedules")
        css_chunk = resp.text.split(".disabled-badge")[1].split("}")[0]
        assert "var(--badge-pending-bg)" in css_chunk
        assert "var(--badge-pending-fg)" in css_chunk


class TestSchedulesTargetPanelsUseTokens:
    """The two target panels ("Target by Device Type" /
    "Target Specific Devices") have inline ``style="background:#f8f8f8"``
    panels that need theme tokens."""

    def test_type_keys_section_uses_surface_alt(self, client):
        resp = client.get("/schedules")
        section_chunk = resp.text.split(
            'data-testid="sched-type-keys-section"'
        )[1].split(">")[0]
        assert "var(--surface-alt)" in section_chunk
        assert "#f8f8f8" not in section_chunk.lower()

    def test_devices_section_uses_surface_alt(self, client):
        resp = client.get("/schedules")
        section_chunk = resp.text.split(
            'data-testid="sched-devices-section"'
        )[1].split(">")[0]
        assert "var(--surface-alt)" in section_chunk
        assert "#f8f8f8" not in section_chunk.lower()
