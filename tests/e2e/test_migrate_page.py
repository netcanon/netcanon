"""
E2E tests for the ``/migrate`` translator workbench.

Covers the shipped form + result surfaces:

* Page loads, nav link works, adapter dropdowns populate from the API.
* Switching input mode hides/shows the right form field.
* Submit → result region reveals.
* iosxe → iosxe happy path produces ``mig-banner-ok``.
* Submitting malformed XML still renders a result (failed job, not a
  server error) so the user gets actionable feedback.
* Class-hint warning appears when source + target classes are disjoint.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import MigratePage, NavBar

pytestmark = pytest.mark.e2e


_IOSXE_MIN = """<?xml version="1.0"?>
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>Gi0/0/0</name>
    <config>
      <name>Gi0/0/0</name>
      <description>e2e test</description>
      <enabled>true</enabled>
    </config>
  </interface>
</interfaces>
"""


# ---------------------------------------------------------------------------
# Navigation + structure
# ---------------------------------------------------------------------------


class TestMigratePageStructure:
    def test_nav_link_visible(self, page: Page, base_url: str):
        page.goto("/")
        expect(page.locator('[data-testid="nav-migrate"]')).to_be_visible()

    def test_nav_link_navigates(self, page: Page, base_url: str):
        page.goto("/")
        page.locator('[data-testid="nav-migrate"]').click()
        expect(page).to_have_url(f"{base_url}/migrate")

    def test_page_title(self, page: Page, base_url: str):
        page.goto("/migrate")
        expect(page).to_have_title("Migrate — NetConfig")

    def test_form_renders(self, page: Page, base_url: str):
        page.goto("/migrate")
        mig = MigratePage(page)
        expect(mig.form).to_be_visible()
        expect(mig.source_select).to_be_visible()
        expect(mig.target_select).to_be_visible()
        expect(mig.raw_input).to_be_visible()
        expect(mig.submit_btn).to_be_visible()

    def test_result_region_hidden_on_load(self, page: Page, base_url: str):
        page.goto("/migrate")
        expect(MigratePage(page).result).to_be_hidden()


# ---------------------------------------------------------------------------
# Adapter dropdown — hydrated from the live API
# ---------------------------------------------------------------------------


class TestAdapterDropdownsPopulate:
    def test_source_select_lists_registered_adapters(
        self, page: Page, base_url: str
    ):
        """The adapter list is fetched via JS on page load."""
        page.goto("/migrate")
        mig = MigratePage(page)
        # Wait for JS to hydrate — after load the select has >0 options.
        page.wait_for_function(
            """() => {
                const sel = document.querySelector(
                  '[data-testid="migrate-source-select"]'
                );
                return sel && sel.options.length > 0;
            }""",
            timeout=5_000,
        )
        values = mig.source_select.evaluate(
            "sel => Array.from(sel.options).map(o => o.value)"
        )
        # At minimum the three registered adapters.
        assert "cisco_iosxe" in values
        assert "opnsense" in values
        assert "mock" in values

    def test_adapter_info_updates_on_change(self, page: Page, base_url: str):
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        expect(mig.adapter_info).to_be_visible()
        expect(mig.adapter_info).to_contain_text("Source")
        expect(mig.adapter_info).to_contain_text("Target")


# ---------------------------------------------------------------------------
# Input-mode toggle
# ---------------------------------------------------------------------------


class TestInputModeToggle:
    def test_raw_visible_by_default(self, page: Page, base_url: str):
        page.goto("/migrate")
        expect(
            page.locator('[data-testid="migrate-raw-wrap"]')
        ).to_be_visible()
        expect(
            page.locator('[data-testid="migrate-filename-wrap"]')
        ).to_be_hidden()

    def test_switching_to_filename_hides_textarea(
        self, page: Page, base_url: str
    ):
        page.goto("/migrate")
        page.locator('[data-testid="migrate-input-mode-filename"]').click()
        expect(
            page.locator('[data-testid="migrate-raw-wrap"]')
        ).to_be_hidden()
        expect(
            page.locator('[data-testid="migrate-filename-wrap"]')
        ).to_be_visible()


# ---------------------------------------------------------------------------
# Submit flow: end-to-end against the live API
# ---------------------------------------------------------------------------


class TestMigrateSubmitFlow:
    def test_iosxe_roundtrip_yields_ok_banner(
        self, page: Page, base_url: str
    ):
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        mig.fill_raw(_IOSXE_MIN)
        mig.submit_and_wait()
        expect(mig.result).to_be_visible()
        assert mig.banner_severity_class() == "ok"
        expect(mig.status_summary).to_contain_text("completed")

    def test_rendered_output_panel_appears(
        self, page: Page, base_url: str
    ):
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        mig.fill_raw(_IOSXE_MIN)
        mig.submit_and_wait()
        output_section = page.locator(
            '[data-testid="migrate-output-section"]'
        )
        expect(output_section).to_be_visible()
        expect(mig.output).to_contain_text("Gi0/0/0")

    def test_parse_failure_renders_failed_status_not_http_error(
        self, page: Page, base_url: str
    ):
        """Parse failures are JOB outcomes, not HTTP errors — the page
        must still render the result region with a failure status."""
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        mig.fill_raw("<not>real</xml")
        mig.submit_and_wait()
        expect(mig.result).to_be_visible()
        expect(mig.status_summary).to_contain_text("failed")
        # A block-severity banner isn't rendered on parse failure (no
        # validation ran); the error banner uses mig-banner-info colour
        # because we don't yet have a "job-failed" severity.  Accept
        # either info (Phase 1) or block (future).
        severity = mig.banner_severity_class()
        assert severity in ("info", "block")

    def test_validation_block_still_shows_result(
        self, page: Page, base_url: str
    ):
        """An unsupported path produces a ``partial`` job — result
        region must render with a block banner so the user sees the
        warning AND the rendered output for review."""
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        # mock → mock with an unsupported path path in the input.
        mig.pick_source("mock")
        mig.pick_target("mock")
        mig.fill_raw('{"/unsafe/kernel_module": "rootkit"}')
        mig.submit_and_wait()
        expect(mig.result).to_be_visible()
        assert mig.banner_severity_class() == "block"
        expect(mig.status_summary).to_contain_text("partial")


# ---------------------------------------------------------------------------
# Bug #10b regression: banner severity must match job outcome
# ---------------------------------------------------------------------------


class TestBannerSeverityMatchesJobOutcome:
    """Locks in the fix for the manual-QA finding that a ``render failed``
    job was rendering with a GREEN banner because validate ran OK before
    render blew up.  Rule: any job.error / failed / partial status forces
    the banner to block (red)."""

    def _setup(self, page):
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        return mig

    def test_failed_job_renders_block_banner_not_ok(
        self, page: Page, base_url: str
    ):
        """Parse failure ⇒ data-severity='block' (red) regardless of
        whether validation.severity could have been 'ok'."""
        mig = self._setup(page)
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        mig.fill_raw("<not>real</xml")
        mig.submit_and_wait()
        assert mig.banner_severity_attr() == "block"

    def test_partial_job_renders_block_banner(
        self, page: Page, base_url: str
    ):
        """partial ⇒ block banner — rendered output exists but unsafe
        to deploy as-is, so the banner must scream 'read me'."""
        mig = self._setup(page)
        mig.pick_source("mock")
        mig.pick_target("mock")
        mig.fill_raw('{"/unsafe/kernel_module": "x"}')
        mig.submit_and_wait()
        assert mig.banner_severity_attr() == "block"

    def test_happy_path_renders_ok_banner(
        self, page: Page, base_url: str
    ):
        """Sanity: when nothing is wrong, severity IS 'ok' (not just
        'never block')."""
        mig = self._setup(page)
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        mig.fill_raw(_IOSXE_MIN)
        mig.submit_and_wait()
        assert mig.banner_severity_attr() == "ok"


# ---------------------------------------------------------------------------
# Format hint + Load sample button
# ---------------------------------------------------------------------------


class TestFormatHint:
    """The hint banner tells the user WHAT to paste.  Critical because
    the paste box doesn't accept CLI text, a trap that cost ~30 min of
    QA confusion during the first manual pass."""

    def test_hint_shows_declared_format_for_source(
        self, page: Page, base_url: str
    ):
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        expect(mig.format_hint).to_be_visible()
        assert mig.format_hint_format() == "xml-netconf"
        expect(mig.format_hint).to_contain_text("OpenConfig NETCONF")

    def test_hint_updates_when_source_changes(
        self, page: Page, base_url: str
    ):
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        assert mig.format_hint_format() == "xml-netconf"
        mig.pick_source("opnsense")
        assert mig.format_hint_format() == "xml-opnsense"

    def test_load_sample_button_populates_textarea(
        self, page: Page, base_url: str
    ):
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        assert mig.raw_input.input_value() == ""
        mig.load_sample_btn.click()
        value = mig.raw_input.input_value()
        # The iosxe sample includes a GigabitEthernet interface.
        assert "<interfaces" in value
        assert "GigabitEthernet" in value

    def test_loaded_sample_successfully_translates(
        self, page: Page, base_url: str
    ):
        """End-to-end sanity — the shipped sample actually roundtrips."""
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("cisco_iosxe")
        mig.pick_target("cisco_iosxe")
        mig.load_sample_btn.click()
        mig.submit_and_wait()
        assert mig.banner_severity_attr() == "ok"


# ---------------------------------------------------------------------------
# Stored-config dropdown compatibility warning
# ---------------------------------------------------------------------------


class TestStoredConfigCompatWarn:
    """When a user picks a stored config whose extension doesn't match
    the source adapter's declared format, warn in-place BEFORE submit."""

    def _setup(self, page):
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        return mig

    def test_warn_hidden_on_load(self, page: Page, base_url: str):
        mig = self._setup(page)
        expect(mig.filename_compat_warn).to_be_hidden()

    def test_mock_adapter_shows_no_store_warning(
        self, page: Page, base_url: str
    ):
        """mock's input_format is json-flat with NO compatible file
        extensions — picking any stored config should warn."""
        mig = self._setup(page)
        # Switch to filename mode; only works if there's at least one config.
        page.locator('[data-testid="migrate-input-mode-filename"]').click()
        # mock has exts=[] so ANY selected stored file is incompatible.
        mig.pick_source("mock")
        sel = page.locator('[data-testid="migrate-filename-select"]')
        options = sel.evaluate(
            "s => Array.from(s.options).map(o => o.value)"
        )
        real = [v for v in options if v]
        if not real:
            pytest.skip("no stored configs in this session — can't exercise")
        sel.select_option(value=real[0])
        expect(mig.filename_compat_warn).to_be_visible()
        expect(mig.filename_compat_warn).to_contain_text(
            "does not read files from the backup store"
        )


# ---------------------------------------------------------------------------
# Path list de-duplication (bug #11)
# ---------------------------------------------------------------------------


class TestPathListDeduplication:
    """The top stats count reflects per-leaf impact (occurrences matter),
    but the path LIST de-duplicates with an ×N badge."""

    def test_duplicate_paths_coalesce_in_list(
        self, page: Page, base_url: str
    ):
        """Use the opnsense fixture (3 interfaces → same /if, /ipaddr,
        /enable, /zone paths repeat) routed through opnsense → opnsense."""
        page.goto("/migrate")
        mig = MigratePage(page)
        page.wait_for_function(
            """() => document.querySelector(
                '[data-testid="migrate-source-select"]'
            ).options.length > 0"""
        )
        mig.pick_source("opnsense")
        mig.pick_target("opnsense")
        mig.fill_raw(
            '<opnsense>'
            '<interfaces>'
            '<wan><if>em0</if><enable/></wan>'
            '<lan><if>em1</if><enable/></lan>'
            '<opt1><if>em2</if><enable/></opt1>'
            '</interfaces>'
            '</opnsense>'
        )
        mig.submit_and_wait()
        # Stats count is raw (3 * N leaves per interface).
        stat = page.locator('[data-testid="migrate-stat-supported"]').inner_text()
        assert int(stat) >= 3  # at least one repeated path

        # Path LIST entries are coalesced — fewer rows than raw count.
        # Reveal the <details> so playwright can locate-entries.
        page.locator('[data-testid="migrate-paths-section"] summary').click()
        entries = page.locator(
            '[data-testid="migrate-paths-supported"] '
            '[data-testid="migrate-path-entry"]'
        )
        assert entries.count() < int(stat), (
            "de-dup should collapse ≥2 entries for the 3-interface input"
        )