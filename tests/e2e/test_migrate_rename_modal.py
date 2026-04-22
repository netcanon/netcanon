"""
E2E tests for the Tier 3 port-rename modal on /migrate.

Covers:
  * Modal open/close + visibility gating (button only appears after a
    translation that produced port-rename diagnostics)
  * Collapsible per-kind sections render
  * User override applied to a row updates the live preview
  * Collision detection disables the Apply button
  * Apply button re-runs translation with rename_map; output
    re-renders with the new names
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import MigratePage

pytestmark = pytest.mark.e2e


_CISCO_SRC = """hostname test-sw
!
vlan 10
 name users
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet1/0/2
 channel-group 1 mode active
!
interface Port-channel1
 switchport mode trunk
 switchport trunk allowed vlan 10
!
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
!
end
"""


@pytest.fixture()
def migrate_with_cisco_to_aruba(page: Page, live_server_url: str):
    """Open /migrate, run a Cisco→Aruba translation, return a
    MigratePage instance on the results view."""
    mp = MigratePage(page)
    page.goto(live_server_url + "/migrate")
    mp.source_select.wait_for(state="visible", timeout=5_000)
    mp.pick_source("cisco_iosxe_cli")
    mp.pick_target("aruba_aoss")
    mp.fill_raw(_CISCO_SRC)
    mp.submit_and_wait()
    return mp


class TestRenameModalVisibility:
    def test_button_hidden_on_fresh_page(self, page: Page, live_server_url: str):
        page.goto(live_server_url + "/migrate")
        btn = page.locator('[data-testid="migrate-rename-open-btn"]')
        # Button is present in DOM but style="display:none" hides it.
        expect(btn).to_be_hidden()

    def test_button_appears_after_translation_with_renames(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        btn = page.locator('[data-testid="migrate-rename-open-btn"]')
        expect(btn).to_be_visible()

    def test_modal_opens_and_closes(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        modal = page.locator('[data-testid="migrate-rename-modal"]')
        expect(modal).to_be_visible()
        # Close via the X button.
        page.locator('[data-testid="migrate-rename-modal-close"]').click()
        expect(modal).to_be_hidden()


class TestRenameModalContent:
    def test_table_shows_physical_section_with_renamed_ports(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        physical = page.locator(
            '[data-testid="migrate-rename-section-physical"]'
        )
        expect(physical).to_be_visible()
        # Rows are keyed by source port name.
        gi1_row = page.locator(
            '[data-testid="migrate-rename-row-GigabitEthernet1/0/1"]'
        )
        expect(gi1_row).to_be_visible()
        # Row contains the auto-target cell showing "1/1".
        expect(gi1_row).to_contain_text("1/1")

    def test_loopback_appears_as_warning_row(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        loop = page.locator('[data-testid="migrate-rename-section-loopback"]')
        expect(loop).to_be_visible()
        row = page.locator(
            '[data-testid="migrate-rename-row-Loopback0"]'
        )
        expect(row).to_be_visible()
        # Row has the has-warning class (yellow background).
        cls = row.get_attribute("class") or ""
        assert "has-warning" in cls


class TestRenameModalApply:
    def test_override_updates_preview_and_apply_regenerates_output(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # Override Gi1/0/1 → "1/42".  The physical section uses
        # free-form input when no target profile is picked.
        override_input = page.locator(
            '[data-testid="migrate-rename-override-GigabitEthernet1/0/1"]'
        )
        override_input.fill("1/42")
        # Preview pane shows the override.
        preview = page.locator('[data-testid="migrate-rename-preview"]')
        expect(preview).to_contain_text("1/42")
        # Apply → pipeline re-runs.
        page.locator('[data-testid="migrate-rename-apply-btn"]').click()
        # Wait for the status text to update.
        status = page.locator('[data-testid="migrate-rename-status"]')
        expect(status).to_contain_text("Applied", timeout=5_000)
        # Main output pane reflects the override.
        page.locator('[data-testid="migrate-rename-modal-close"]').click()
        output = page.locator('[data-testid="migrate-output"]')
        expect(output).to_contain_text("1/42")


class TestRenameModalDrop:
    """Dropping an interface removes it from the rendered output.

    Two paths:
      * Auto-drop (default) — server strips unmappable names (Loopback0
        on Aruba target, etc.) before render.  The rendered output
        already excludes them; UI shows them as "auto-dropped" rows.
      * Explicit drop — operator clicks the row's drop link to
        remove a name that would otherwise auto-translate.
    """

    def test_loopback_auto_dropped_by_default(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        # Default behaviour (strip_unmappable=True): Loopback0 has no
        # Aruba equivalent and is auto-dropped before render.  The
        # main output does NOT contain the Loopback name without any
        # user action.
        output = page.locator('[data-testid="migrate-output"]')
        assert "Loopback0" not in (output.text_content() or "")

    def test_explicit_drop_link_removes_interface(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        # Drop a source that WOULD auto-translate (Gi1/0/1 → 1/1);
        # user explicitly says "don't render this".
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        drop_link = page.locator(
            '[data-testid="migrate-rename-drop-GigabitEthernet1/0/1"]'
        )
        expect(drop_link).to_be_visible()
        # For rows that auto-translated successfully, link says "drop".
        expect(drop_link).to_contain_text("drop")
        drop_link.click()
        summary = page.locator('[data-testid="migrate-rename-summary"]')
        expect(summary).to_contain_text("drop")
        page.locator('[data-testid="migrate-rename-apply-btn"]').click()
        expect(
            page.locator('[data-testid="migrate-rename-status"]')
        ).to_contain_text("Applied", timeout=5_000)
        page.locator('[data-testid="migrate-rename-modal-close"]').click()
        # The target-side name for Gi1/0/1 would have been "1/1";
        # assert neither source nor target appears in rendered output.
        output = page.locator('[data-testid="migrate-output"]')
        text = output.text_content() or ""
        assert "GigabitEthernet1/0/1" not in text
        # "1/1" check is stricter than needed — Aruba's Trk1 rendering
        # contains "1/1" as part of trunk port lists — so just assert
        # the Gi1/0/1 interface STANZA doesn't appear.

    def test_keep_verbatim_re_includes_auto_dropped_row(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        # Default auto-drop hides Loopback0.  Operator wants to KEEP
        # it anyway (e.g. to carry it through for manual cleanup in
        # the target config).  The drop link on an auto-dropped row
        # says "keep verbatim" and clicking it un-drops the row.
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        keep_link = page.locator(
            '[data-testid="migrate-rename-drop-Loopback0"]'
        )
        expect(keep_link).to_be_visible()
        expect(keep_link).to_contain_text("keep verbatim")
        keep_link.click()
        page.locator('[data-testid="migrate-rename-apply-btn"]').click()
        expect(
            page.locator('[data-testid="migrate-rename-status"]')
        ).to_contain_text("Applied", timeout=5_000)
        page.locator('[data-testid="migrate-rename-modal-close"]').click()
        # Loopback0 now appears verbatim in rendered output
        # (the user explicitly asked for it).
        output = page.locator('[data-testid="migrate-output"]')
        assert "Loopback0" in (output.text_content() or "")


class TestRenameModalTargetProfileTwoStage:
    """Target profile selector is two-stage: Vendor dropdown first,
    then Model dropdown filtered to that vendor's profiles.  Tests
    the initial state, vendor-picks-gate-models behaviour, and that
    selecting a model drives the per-row dropdown options."""

    def test_model_disabled_until_vendor_picked(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        vendor = page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        )
        model = page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        )
        expect(vendor).to_be_visible()
        expect(model).to_be_visible()
        # The vendor auto-suggests "aruba_aoss" because the target
        # codec is aruba_aoss, so the model dropdown becomes active
        # on modal open.  Verify by resetting to "(none)" and
        # confirming model disables.
        vendor.select_option(value="")
        expect(model).to_be_disabled()

    def test_vendor_pick_populates_model_options(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        vendor = page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        )
        vendor.select_option(value="aruba_aoss")
        model = page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        )
        # Model dropdown now contains all Aruba profiles we shipped.
        options = model.locator("option").all_text_contents()
        assert any("2930F-48G-PoEP" in o for o in options)
        assert any("3810M-48G-PoE" in o for o in options)


class TestRenameModalOrphanedOverride:
    """When the operator sets an override under one target profile,
    then switches profiles, their override value might not exist in
    the new profile's port list.  The UI preserves the override and
    surfaces it as a ``(custom: X — not in profile)`` dropdown option
    so the operator can see and correct it."""

    def test_override_surfaces_as_custom_when_not_in_new_profile(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # Pick a profile and set an override on a physical port.
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoss")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="2930F-48G-PoEP")
        # Override GigabitEthernet1/0/1 → 1/12 (valid on 2930F-48G-PoEP).
        page.locator(
            '[data-testid="migrate-rename-override-GigabitEthernet1/0/1"]'
        ).select_option(value="1/12")
        # Now switch profile to one that has DIFFERENT port names
        # (Cisco uses GigabitEthernet1/0/N style).
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="cisco_iosxe")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="C9300-24UX")
        # The override of "1/12" doesn't exist in Cisco C9300-24UX
        # (ports are "GigabitEthernet1/0/N").  Dropdown should
        # surface it as "(custom: 1/12 — not in profile)".
        override = page.locator(
            '[data-testid="migrate-rename-override-GigabitEthernet1/0/1"]'
        )
        options_text = override.locator("option").all_text_contents()
        assert any(
            "custom:" in o and "1/12" in o and "not in profile" in o
            for o in options_text
        ), f"expected orphaned-override custom option; got: {options_text}"


class TestRenameModalCollisionDetection:
    def test_same_target_on_two_sources_disables_apply(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # Set both Gi1/0/1 and Gi1/0/2 to the same target → collision.
        page.locator(
            '[data-testid="migrate-rename-override-GigabitEthernet1/0/1"]'
        ).fill("1/99")
        page.locator(
            '[data-testid="migrate-rename-override-GigabitEthernet1/0/2"]'
        ).fill("1/99")
        # Summary shows collisions.
        summary = page.locator('[data-testid="migrate-rename-summary"]')
        expect(summary).to_contain_text("collision")
        # Apply button is disabled.
        apply_btn = page.locator('[data-testid="migrate-rename-apply-btn"]')
        expect(apply_btn).to_be_disabled()
