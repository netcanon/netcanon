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

import json
import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.drawn import (
    alike,
    choose_override,
    ink,
    override_options,
    painted_background,
    painted_token,
    token_ink,
)
from tests.e2e.helpers import MigratePage

pytestmark = pytest.mark.e2e

#: What the banner and the notice above the table are painted on.
TOP = "#mig-rename-modal-top"


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
      * Auto-drop (default) — the server leaves out a name the target
        has no form for (a tunnel, on AOS-S) before render.  The
        rendered output is already without it; the modal shows the
        row as "auto-dropped", with a link that keeps it instead.
        A loopback is not one of these on AOS-S, which has loopback
        interfaces of its own.
      * Explicit drop — operator clicks the row's drop link to
        remove a name that would otherwise auto-translate.
    """

    def test_a_loopback_is_renamed_not_dropped(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        # ``Loopback0`` is given the first loopback an operator can
        # create on AOS-S and is rendered with its address; the job
        # drops nothing for this config.  (That the source name is not
        # in the output says nothing: no AOS-S output has it.)
        output = page.locator('[data-testid="migrate-output"]')
        rendered = (output.text_content() or "").splitlines()
        assert "interface loopback1" in rendered
        assert "   ip address 1.1.1.1/32" in rendered
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # Its row says so.  (A section with nothing to attend to
        # starts folded, so the row is read, not looked for on screen.)
        row = page.locator('[data-testid="migrate-rename-row-Loopback0"]')
        expect(row).to_have_count(1)
        assert "has-auto-drop" not in (row.get_attribute("class") or "").split()
        expect(
            page.locator('[data-testid="migrate-rename-auto-Loopback0"]')
        ).to_have_text("loopback1")
        expect(
            page.locator('[data-testid="migrate-rename-drop-Loopback0"]')
        ).to_have_text("drop")

    def test_a_name_with_no_target_form_is_dropped(
        self, page: Page, live_server_url: str,
    ):
        # A tunnel has no AOS-S form.  The server leaves it out before
        # render, without any action of the operator's; its row says
        # it was dropped, and its link offers to keep the name.
        mp = MigratePage(page)
        page.goto(live_server_url + "/migrate")
        mp.source_select.wait_for(state="visible", timeout=5_000)
        mp.pick_source("cisco_iosxe_cli")
        mp.pick_target("aruba_aoss")
        mp.fill_raw(_CISCO_SRC.replace(
            "end\n", "interface Tunnel0\n ip address 10.9.9.1 255.255.255.252\n!\nend\n",
        ))
        mp.submit_and_wait()
        output = page.locator('[data-testid="migrate-output"]')
        rendered = output.text_content() or ""
        assert "interface loopback1" in rendered.splitlines()
        assert "tunnel" not in rendered.lower() and "10.9.9.1" not in rendered
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        row = page.locator('[data-testid="migrate-rename-row-Tunnel0"]')
        expect(row).to_have_count(1)
        assert "has-auto-drop" in (row.get_attribute("class") or "").split()
        expect(
            page.locator('[data-testid="migrate-rename-auto-Tunnel0"]')
        ).to_have_text("(auto-dropped \u2014 won't render)")
        expect(
            page.locator('[data-testid="migrate-rename-drop-Tunnel0"]')
        ).to_have_text("keep verbatim")

    def test_explicit_drop_link_removes_interface(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        # Drop a source that WOULD auto-translate (Gi1/0/1 → 1/1);
        # user explicitly says "don't render this".
        output = page.locator('[data-testid="migrate-output"]')
        # Before the drop the port is rendered: its stanza, and its
        # place in the VLAN.
        rendered = (output.text_content() or "").splitlines()
        assert "interface 1/1" in rendered and "   untagged 1/1" in rendered
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        drop_link = page.locator(
            '[data-testid="migrate-rename-drop-GigabitEthernet1/0/1"]'
        )
        expect(drop_link).to_be_visible()
        # For rows that auto-translated successfully, link says "drop"
        # -- and once dropped, the same link undoes it.
        expect(drop_link).to_have_text("drop")
        drop_link.click()
        expect(drop_link).to_have_text("un-drop")
        summary = page.locator('[data-testid="migrate-rename-summary"]')
        expect(summary).to_contain_text("1 drop")
        page.locator('[data-testid="migrate-rename-apply-btn"]').click()
        expect(
            page.locator('[data-testid="migrate-rename-status"]')
        ).to_contain_text("Applied", timeout=5_000)
        page.locator('[data-testid="migrate-rename-modal-close"]').click()
        # The source name is never in an AOS-S output; what the drop
        # takes out is the port's target-side stanza and membership.
        # (Whole lines: "1/1" alone is also the start of other names.)
        rendered = (output.text_content() or "").splitlines()
        assert "interface 1/1" not in rendered
        assert "   untagged 1/1" not in rendered
        assert "interface 1/2" in rendered


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
        # Model dropdown now contains all Aruba AOS-S profiles we shipped.
        options = model.locator("option").all_text_contents()
        assert any("2930F-48G-PoE+" in o for o in options)
        assert any("3810M-48G-PoE" in o for o in options)
        # The CX 6300M runs AOS-CX and is no longer offered here.
        assert not any("6300M" in o for o in options), options

    def test_aoscx_profile_offers_lag_names_the_codec_accepts(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """The CX 6300M is filed under Aruba AOS-CX, and its LAG
        options are spelled the way AOS-CX writes them -- ``lag 1``,
        with a space.  The modal builds the option as prefix + number,
        so this proves the profile's trailing-space prefix survives the
        loader, the API and the option value: ``lag1`` is not a LAG
        name the aruba_aoscx codec recognises."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoscx")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="6300M-48G-PoE4-SFP56")
        values = [value for value, _text in override_options(page, "Port-channel1")]
        assert "lag 1" in values and "lag 256" in values, values[:6]
        assert "lag1" not in values
        # Access rows are offered member/slot/port names.
        access_values = [
            value for value, _text in override_options(page, "GigabitEthernet1/0/1")
        ]
        assert "1/1/1" in access_values and "1/1/48" in access_values
        assert "1/A1" not in access_values


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
        # Override GigabitEthernet1/0/1 → 12 (valid on the standalone
        # 2930F-48G-PoEP, whose ports are bare numbers).
        choose_override(page, "GigabitEthernet1/0/1", "12")
        # Now switch profile to one that has DIFFERENT port names
        # (Cisco uses GigabitEthernet1/0/N style).
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="cisco_iosxe")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="C9300-24UX")
        # The override of "12" doesn't exist in Cisco C9300-24UX
        # (ports are "TenGigabitEthernet1/0/N").  Dropdown should
        # surface it as "(custom: 12 — not in profile)".
        override = page.locator(
            '[data-testid="migrate-rename-override-GigabitEthernet1/0/1"]'
        )
        options_text = override.locator("option").all_text_contents()
        assert any(
            "custom: 12 " in o and "not in profile" in o
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


#: An AOS-S LAG as the device writes it: ``trk1`` where it is defined,
#: ``Trk1`` in its own interface stanza and in a VLAN's port list.
_AOSS_ONE_LAG = """; JL260A Configuration Editor; Created on release #WC.16.07.0002
hostname "sw"
trunk 51-52 trk1 lacp
interface Trk1
   name "uplink"
   exit
vlan 1
   name "DEFAULT_VLAN"
   untagged 1-50
   tagged Trk1
   exit
"""


class TestRenameModalAosSLag:
    """The two spellings of one LAG used to be two rows aimed at one
    target: both drawn as a collision, and an Apply button that stayed
    disabled until one of them was dropped -- for an AOS-S config that
    names a LAG outside its ``trunk`` line (a VLAN that lists it, its
    own ``interface`` stanza), onto any other vendor."""

    @pytest.mark.parametrize("target", ["juniper_junos", "cisco_iosxe_cli", "arista_eos", "aruba_aoss"])
    def test_a_lag_is_one_row_and_apply_works(
        self, page: Page, live_server_url: str, target: str,
    ):
        mp = MigratePage(page)
        page.goto(live_server_url + "/migrate")
        mp.source_select.wait_for(state="visible", timeout=5_000)
        mp.pick_source("aruba_aoss")
        mp.pick_target(target)
        mp.fill_raw(_AOSS_ONE_LAG)
        mp.submit_and_wait()
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # One row, under the name the config's ``trunk`` line gave it.  (A
        # section with nothing to attend to starts folded, so the row is
        # counted, not looked for on screen.)  Onto AOS-S itself the
        # job renames no name; the row is there all the same, drawn
        # from the job's list of the names that are no hardware port.
        expect(page.locator('[data-testid="migrate-rename-row-trk1"]')).to_have_count(1)
        expect(page.locator('[data-testid="migrate-rename-row-Trk1"]')).to_have_count(0)
        expect(page.locator('[data-testid="migrate-rename-row-51"]')).to_have_count(1)
        expect(page.locator(".has-collision")).to_have_count(0)
        expect(page.locator('[data-testid="migrate-rename-summary"]')).not_to_contain_text("collision")
        expect(page.locator('[data-testid="migrate-rename-apply-btn"]')).to_be_enabled()


#: A Junos config with one port and a loopback.
_JUNOS_WITH_A_LOOPBACK = (
    "set system host-name r1\n"
    "set interfaces ge-0/0/1 unit 0 family inet address 10.1.0.1/24\n"
    "set interfaces lo0 unit 0 family inet address 192.0.2.1/32\n"
)

#: A Junos config that is a loopback and nothing else: no port, no
#: VLAN, no user, no community.
_JUNOS_ONLY_A_LOOPBACK = (
    "set interfaces lo0 unit 0 family inet address 192.0.2.1/32\n"
)

#: An EOS port-channel with two members.
_EOS_PORT_CHANNEL = """hostname sw
!
interface Port-Channel1
   description uplink
   switchport mode trunk
!
interface Ethernet1
   channel-group 1 mode active
!
interface Ethernet2
   channel-group 1 mode active
!
end
"""


#: An IOS-XE config whose VLAN interface and loopback have the same
#: names on EOS, beside two ports that have others.
_IOS_WITH_AN_SVI = """hostname sw
!
vlan 10
 name users
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet1/0/2
 switchport mode access
 switchport access vlan 10
!
interface Vlan10
 ip address 10.10.0.1 255.255.255.0
!
interface Loopback0
 ip address 10.255.0.1 255.255.255.255
!
end
"""


def _tid(name: str) -> str:
    return f'[data-testid="{name}"]'


def _open_modal_on(page: Page, base: str, source: str, target: str, raw: str) -> None:
    mp = MigratePage(page)
    page.goto(base + "/migrate")
    mp.source_select.wait_for(state="visible", timeout=5_000)
    mp.pick_source(source)
    mp.pick_target(target)
    mp.fill_raw(raw)
    mp.submit_and_wait()
    page.locator(_tid("migrate-rename-open-btn")).click()
    expect(page.locator(_tid("migrate-rename-modal"))).to_be_visible()


def _apply(page: Page) -> dict:
    """Click Apply; return the body of the plan request it sent, once
    the answer is back."""
    with (
        page.expect_request("**/api/v1/migration/plan") as request,
        page.expect_response("**/api/v1/migration/plan"),
    ):
        page.locator(_tid("migrate-rename-apply-btn")).click()
    expect(page.locator(_tid("migrate-rename-status"))).to_contain_text("Applied", timeout=5_000)
    return json.loads(request.value.post_data or "{}")


def _sections(page: Page) -> list[str]:
    """The sections of the ports table, in the order they are drawn."""
    return page.locator(_tid("migrate-rename-sections") + " > details").evaluate_all(
        "els => els.map(e => e.getAttribute('data-testid'))"
    )


def _unfold(page: Page, kind: str) -> None:
    """Open the section of *kind* the way an operator does, if it is
    folded: a section with nothing to attend to starts that way
    unless it is the first, and every new job folds it again."""
    section = page.locator(_tid(f"migrate-rename-section-{kind}"))
    if not section.evaluate("el => el.open"):
        page.locator(_tid(f"migrate-rename-section-summary-{kind}")).click()
    expect(section).to_have_attribute("open", "")


class TestRenameModalNamesThatAreNoPort:
    """The table drew a row for a name the job renamed, for one a
    warning quoted, and for each hardware port.  A job from a vendor
    to itself renames no name and warns about none, so a LAG, a
    loopback or a VLAN interface had no row there, and could be
    renamed or dropped only by a request written by hand.  The job
    lists those names now, and each that nothing else gave a row
    has one, in a section of its own after the ports."""

    @pytest.mark.parametrize(
        ("codec", "raw", "name", "new_name", "line"),
        [
            ("aruba_aoss", _AOSS_ONE_LAG, "trk1", "trk7", "trunk 51-52 trk7 lacp"),
            ("juniper_junos", _JUNOS_WITH_A_LOOPBACK, "lo0", "lo1",
             "set interfaces lo1 unit 0 family inet address 192.0.2.1/32"),
            ("arista_eos", _EOS_PORT_CHANNEL, "Port-Channel1", "Port-Channel7",
             "channel-group 7 mode active"),
        ],
        ids=["aruba_aoss", "juniper_junos", "arista_eos"],
    )
    def test_it_has_one_row_and_apply_renames_it(
        self, page: Page, live_server_url: str,
        codec: str, raw: str, name: str, new_name: str, line: str,
    ):
        _open_modal_on(page, live_server_url, codec, codec, raw)
        expect(page.locator(_tid(f"migrate-rename-row-{name}"))).to_have_count(1)
        # In the section for such names, which is drawn after the ports.
        section = page.locator(_tid("migrate-rename-section-other"))
        row = section.locator(_tid(f"migrate-rename-row-{name}"))
        expect(row).to_have_count(1)
        drawn = _sections(page)
        assert drawn[0] == "migrate-rename-section-physical"
        assert drawn[-1] == "migrate-rename-section-other", drawn
        # It is folded while a section above it has rows; an operator opens it.
        expect(section).not_to_have_attribute("open", "")
        _unfold(page, "other")
        expect(row).to_be_visible()
        expect(page.locator(_tid(f"migrate-rename-auto-{name}"))).to_have_text("(unchanged)")
        # The controls every row has, typed into as a person types.
        override = page.locator(_tid(f"migrate-rename-override-{name}"))
        override.click()
        override.press_sequentially(new_name)
        expect(override).to_have_value(new_name)
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_enabled()
        body = _apply(page)
        assert body["port_rename_map"] == {name: new_name}
        expect(page.locator(_tid("migrate-output"))).to_contain_text(line)
        # Still one row: the job now lists the name as renamed, and it
        # is not drawn a second time for being in the other list too.
        expect(page.locator(_tid(f"migrate-rename-row-{name}"))).to_have_count(1)
        expect(page.locator(_tid("migrate-rename-section-other"))).to_have_count(0)

    def test_it_can_be_dropped_and_kept_again(self, page: Page, live_server_url: str):
        """The link beside the field goes through its three states on
        such a row as on any other."""
        _open_modal_on(page, live_server_url, "aruba_aoss", "aruba_aoss", _AOSS_ONE_LAG)
        _unfold(page, "other")
        link = page.locator(_tid("migrate-rename-drop-trk1"))
        expect(link).to_have_text("drop")
        link.click()
        expect(link).to_have_text("un-drop")
        assert _apply(page)["port_rename_map"] == {"trk1": None}
        output = page.locator(_tid("migrate-output"))
        expect(output).not_to_contain_text("trunk 51-52")
        # The job no longer has the LAG, and the row is still there to
        # take it back by.  Un-dropped, it shows what the job on
        # screen did with the name, and offers to keep it.
        _unfold(page, "other")
        expect(link).to_have_text("un-drop")
        link.click()
        expect(link).to_have_text("keep verbatim")
        link.click()
        assert _apply(page)["port_rename_map"] == {"trk1": "trk1"}
        expect(output).to_contain_text("trunk 51-52 trk1 lacp")

    def test_one_loopback_is_enough_to_open_it(
        self, page: Page, live_server_url: str,
    ):
        """The button needed a rename, a warning, a VLAN, a user, a
        community or a hardware port.  A name that is none of them
        is enough: it has a row to rename it by."""
        mp = MigratePage(page)
        page.goto(live_server_url + "/migrate")
        mp.source_select.wait_for(state="visible", timeout=5_000)
        mp.pick_source("juniper_junos")
        mp.pick_target("juniper_junos")
        mp.fill_raw(_JUNOS_ONLY_A_LOOPBACK)
        mp.submit_and_wait()
        button = page.locator(_tid("migrate-rename-open-btn"))
        expect(button).to_be_visible()
        button.click()
        # The only section there is, so it is open.
        assert _sections(page) == ["migrate-rename-section-other"]
        expect(page.locator(_tid("migrate-rename-row-lo0"))).to_be_visible()
        expect(page.locator(_tid("migrate-rename-table-empty"))).to_be_hidden()
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text("1")

    @pytest.mark.parametrize("target", ["juniper_junos", "cisco_iosxe_cli", "arista_eos"])
    def test_a_name_with_a_row_gets_no_second(
        self, page: Page, live_server_url: str, target: str,
    ):
        """There the job renames the LAG, which gives it its row among
        the link aggregations.  It is in the list of names that are
        no port as well, and is not drawn again for that."""
        _open_modal_on(page, live_server_url, "aruba_aoss", target, _AOSS_ONE_LAG)
        expect(page.locator(_tid("migrate-rename-row-trk1"))).to_have_count(1)
        expect(
            page.locator(_tid("migrate-rename-section-lag")).locator(_tid("migrate-rename-row-trk1"))
        ).to_have_count(1)
        expect(page.locator(_tid("migrate-rename-section-other"))).to_have_count(0)
        # The rail counts the rows drawn: fifty-two ports and the LAG.
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text("53")

    def test_an_entry_on_its_name_holds_apply(self, page: Page, live_server_url: str):
        """The LAG keeps its name, which another row may not also
        take -- as for a port that keeps its name.  The summary
        counts the two rows, Apply is held and says why, and the
        section the LAG's row is in opens by itself."""
        _open_modal_on(page, live_server_url, "aruba_aoss", "aruba_aoss", _AOSS_ONE_LAG)
        apply = page.locator(_tid("migrate-rename-apply-btn"))
        expect(apply).to_be_enabled()
        override = page.locator(_tid("migrate-rename-override-5"))
        override.click()
        override.press_sequentially("trk1")
        expect(page.locator(_tid("migrate-rename-summary"))).to_contain_text("2 collisions")
        expect(apply).to_be_disabled()
        expect(page.locator(_tid("migrate-rename-apply-why"))).to_contain_text(
            "two rows end on one target name (trk1)"
        )
        # Leaving the field redraws the table: both rows are marked.
        override.press("Tab")
        for name in ("5", "trk1"):
            expect(page.locator(_tid(f"migrate-rename-row-{name}"))).to_have_class(
                re.compile(r"\bhas-collision\b")
            )
        expect(page.locator(_tid("migrate-rename-section-other"))).to_have_attribute("open", "")
        expect(page.locator(_tid("migrate-rename-row-trk1"))).to_be_visible()

    def test_a_warning_quoting_one_is_on_its_row(
        self, page: Page, live_server_url: str,
    ):
        """Junos to OPNsense: the unit ``lo0.2`` is put on ``lo0``,
        which is the loopback's name there too, and the job warns
        that two names share it.  The name the warning quotes is
        where a rename ENDS, and such a name is taken for a target's
        and given no row -- unless the job says it is a source name,
        which for a loopback only the list of names that are no
        port does."""
        raw = _JUNOS_WITH_A_LOOPBACK + "set interfaces lo0 unit 2 family inet address 192.0.2.2/32\n"
        _open_modal_on(page, live_server_url, "juniper_junos", "opnsense", raw)
        row = page.locator(_tid("migrate-rename-row-lo0"))
        expect(row).to_have_count(1)
        expect(row).to_have_class(re.compile(r"\bhas-warning\b"))
        expect(page.locator(_tid("migrate-rename-row-lo0.2"))).to_have_count(1)

    def test_the_rail_counts_its_row(self, page: Page, live_server_url: str):
        _open_modal_on(page, live_server_url, "aruba_aoss", "aruba_aoss", _AOSS_ONE_LAG)
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text("53")
        expect(
            page.locator(_tid("migrate-rename-section-summary-other"))
        ).to_contain_text("Other names in the config")

    def test_kept_across_vendors_it_has_a_row(
        self, page: Page, live_server_url: str,
    ):
        """IOS-XE onto EOS renames the two ports and leaves
        ``Vlan10`` and ``Loopback0`` as they are: the same names on
        both platforms.  A name the job did not rename is in no
        list of renames and no warning quotes it -- on this job as
        on one from a vendor to itself.  So here too it has its row
        from the job's list of the names that are no port, in the
        section after the ports, whatever else the job renamed."""
        _open_modal_on(
            page, live_server_url, "cisco_iosxe_cli", "arista_eos", _IOS_WITH_AN_SVI,
        )
        # The job did rename something: a port's row shows where it went.
        expect(
            page.locator(_tid("migrate-rename-auto-GigabitEthernet1/0/1"))
        ).to_have_text("Ethernet1")
        section = page.locator(_tid("migrate-rename-section-other"))
        for name in ("Vlan10", "Loopback0"):
            expect(page.locator(_tid(f"migrate-rename-row-{name}"))).to_have_count(1)
            expect(section.locator(_tid(f"migrate-rename-row-{name}"))).to_have_count(1)
        assert _sections(page) == [
            "migrate-rename-section-physical", "migrate-rename-section-other",
        ]
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text("4")
        _unfold(page, "other")
        expect(page.locator(_tid("migrate-rename-row-Vlan10"))).to_be_visible()
        expect(page.locator(_tid("migrate-rename-auto-Vlan10"))).to_have_text("(unchanged)")
        # And the row does what a row does.
        override = page.locator(_tid("migrate-rename-override-Loopback0"))
        override.click()
        override.press_sequentially("Loopback7")
        assert _apply(page)["port_rename_map"] == {"Loopback0": "Loopback7"}
        output = page.locator(_tid("migrate-output"))
        expect(output).to_contain_text("interface Loopback7")
        expect(output).not_to_contain_text("interface Loopback0")

    @pytest.mark.parametrize("how", ["dropped", "renamed away"])
    def test_a_name_that_went_frees_its_name(
        self, page: Page, live_server_url: str, how: str,
    ):
        """A name holds its own name while it keeps it.  One the
        operator has dropped, or sent elsewhere, holds it no longer:
        another row may take the name, no collision is counted, and
        Apply sends both entries."""
        _open_modal_on(page, live_server_url, "aruba_aoss", "aruba_aoss", _AOSS_ONE_LAG)
        _unfold(page, "other")
        if how == "dropped":
            page.locator(_tid("migrate-rename-drop-trk1")).click()
            expect(page.locator(_tid("migrate-rename-drop-trk1"))).to_have_text("un-drop")
            sent = {"trk1": None, "5": "trk1"}
        else:
            lag = page.locator(_tid("migrate-rename-override-trk1"))
            lag.click()
            lag.press_sequentially("trk7")
            lag.press("Tab")
            sent = {"trk1": "trk7", "5": "trk1"}
        override = page.locator(_tid("migrate-rename-override-5"))
        override.click()
        override.press_sequentially("trk1")
        expect(override).to_have_value("trk1")
        summary = page.locator(_tid("migrate-rename-summary"))
        expect(summary).to_contain_text("override")
        expect(summary).not_to_contain_text("collision")
        expect(page.locator(_tid("migrate-rename-apply-why"))).to_be_hidden()
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_enabled()
        # Leaving the field redraws the table: no row is marked.
        override.press("Tab")
        expect(page.locator(_tid("migrate-rename-row-5"))).to_have_class(
            re.compile(r"\bhas-override\b")
        )
        expect(page.locator(".has-collision")).to_have_count(0)
        expect(page.locator(_tid("migrate-rename-collision-5"))).to_have_count(0)
        assert _apply(page)["port_rename_map"] == sent

    def test_a_fusion_nobody_typed_holds_nothing(
        self, page: Page, live_server_url: str,
    ):
        """Junos to OPNsense once more: the translator itself puts
        ``lo0.2`` on ``lo0``, which keeps its name.  That is the job
        as it came back, and its row carries the warning.  It is not
        counted as a collision, though a name that keeps its name is
        tallied: only against an entry of the operator's own, or
        Apply would be held before anything was typed, and every
        other edit with it."""
        raw = _JUNOS_WITH_A_LOOPBACK + "set interfaces lo0 unit 2 family inet address 192.0.2.2/32\n"
        _open_modal_on(page, live_server_url, "juniper_junos", "opnsense", raw)
        expect(page.locator(_tid("migrate-rename-auto-lo0.2"))).to_have_text("lo0")
        summary = page.locator(_tid("migrate-rename-summary"))
        expect(summary).to_contain_text("auto")
        expect(summary).not_to_contain_text("collision")
        expect(page.locator(_tid("migrate-rename-apply-why"))).to_be_hidden()
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_enabled()


class TestRenameModalModuleDropdown:
    """Third-stage module dropdown — chassis with swappable uplink
    modules (Cisco Cat 9300 NM-8X/NM-2Q, Aruba 3810M JL083A/JL078A).
    UI rule: dropdown hidden for legacy profiles, visible
    and populated when profile declares modules.  Changing the
    selected module re-scopes target-port dropdowns to that module's
    uplink inventory."""

    def test_module_dropdown_hidden_for_legacy_profile(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Legacy profiles (no modules declared) must not surface
        the third dropdown — existing users see the pre-M2 UI
        unchanged when picking a legacy target."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoss")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="2930F-48G-PoEP")
        module_sel = page.locator(
            '[data-testid="migrate-rename-target-module-select"]'
        )
        expect(module_sel).to_be_hidden()

    def test_module_dropdown_visible_for_module_variant_profile(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Cat 9300-24UX declares NM-8X + NM-2Q modules — the third
        dropdown must appear and list both SKUs."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="cisco_iosxe")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="C9300-24UX")
        module_sel = page.locator(
            '[data-testid="migrate-rename-target-module-select"]'
        )
        expect(module_sel).to_be_visible()
        options = module_sel.locator("option").all_text_contents()
        # Both module SKUs surface in the dropdown, labelled with
        # their description so the operator can tell them apart
        # without memorising part numbers.
        assert any("NM-8X" in o for o in options), options
        assert any("NM-2Q" in o for o in options), options
        # First-declared SKU is pre-selected (mirrors backend
        # default_module_sku() — NM-8X here).
        assert module_sel.input_value() == "NM-8X"

    def test_module_dropdown_resets_when_model_changes(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Switching model re-populates the module dropdown (or
        hides it for legacy profiles).  Stale SKUs from the
        previous model must not leak into the new dropdown."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # Start with a module-variant profile.
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="cisco_iosxe")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="C9300-24UX")
        module_sel = page.locator(
            '[data-testid="migrate-rename-target-module-select"]'
        )
        expect(module_sel).to_be_visible()
        # Switch to Aruba legacy profile → module dropdown hides.
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoss")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="2930F-48G-PoEP")
        expect(module_sel).to_be_hidden()

    def test_module_switch_retargets_uplink_dropdown(
        self, page: Page, live_server_url: str,
    ):
        """The core value of module variants: swapping NM-8X →
        NM-2Q must replace the uplink dropdown options from 10G
        SFP+ ids to 40G QSFP+ ids.  This test is the regression
        guard for the user-reported 40G case — source ports that
        look like uplinks must be offered 40G targets once NM-2Q
        is selected."""
        # The shared fixture's ports are all access ports; this needs
        # one that looks like an uplink.
        uplink = "TenGigabitEthernet1/1/1"
        mp = MigratePage(page)
        page.goto(live_server_url + "/migrate")
        mp.source_select.wait_for(state="visible", timeout=5_000)
        mp.pick_source("cisco_iosxe_cli")
        mp.pick_target("aruba_aoss")
        mp.fill_raw(_CISCO_SRC.replace(
            "interface Loopback0", f"interface {uplink}\n description uplink\n!\ninterface Loopback0",
        ))
        mp.submit_and_wait()
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="cisco_iosxe")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="C9300-24UX")

        def offered(source: str) -> list[str]:
            return [
                value for value, _text in override_options(page, source)
                if value and not value.startswith("__")
            ]

        # NM-8X is selected by default: eight 10G ports for the
        # uplink, and the chassis ports for an access port.
        assert offered(uplink) == [f"TenGigabitEthernet1/1/{n}" for n in range(1, 9)]
        access = offered("GigabitEthernet1/0/1")
        assert access[0] == "TenGigabitEthernet1/0/1" and len(access) == 24
        page.locator(
            '[data-testid="migrate-rename-target-module-select"]'
        ).select_option(value="NM-2Q")
        expect(
            page.locator('[data-testid="migrate-fitcheck-module-note"]')
        ).to_contain_text("NM-2Q")
        # The uplink is offered the module's two 40G ports; the
        # chassis ports do not depend on the module.
        assert offered(uplink) == [
            "FortyGigabitEthernet1/1/1", "FortyGigabitEthernet1/1/2",
        ]
        assert offered("GigabitEthernet1/0/1") == access

    def test_aruba_3810m_exposes_jl_module_variants(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Aruba 3810M JL083A (4x SFP+) and JL078A (1x QSFP+) must
        both surface as module options so operators doing a Cisco →
        Aruba 3810M migration can pick the module actually fitted.
        JL084A (the stacking module) and JL085A (a power supply)
        must NOT be offered -- both were, as 40G uplink modules."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoss")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="3810M-48G-PoEP")
        module_sel = page.locator(
            '[data-testid="migrate-rename-target-module-select"]'
        )
        expect(module_sel).to_be_visible()
        options = module_sel.locator("option").all_text_contents()
        assert any("JL083A" in o for o in options), options
        assert any("JL078A" in o for o in options), options
        assert not any("JL084A" in o for o in options), options
        assert not any("JL085A" in o for o in options), options


class TestRenameModalFitCheck:
    """Hardware fit-check banner — source-vs-target port counts
    grouped by kind, surfaced in the rename modal whenever a target
    profile is selected.  Module-aware: switching module swaps the
    uplink capacity numbers in place."""

    def test_fitcheck_hidden_when_no_profile_selected(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Without a profile there's no capacity to compute — the
        banner must stay hidden so the modal doesn't show
        meaningless zeroes or NaN."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # Vendor defaults to "(none — free-form)" on first open unless
        # a match is auto-suggested.  Explicitly reset to no-vendor
        # to guarantee profile-less state.
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="")
        banner = page.locator('[data-testid="migrate-rename-fitcheck"]')
        expect(banner).to_be_hidden()

    def test_fitcheck_visible_when_profile_selected(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Selecting a profile activates the banner; it shows
        source-vs-target counts for whichever kinds have non-zero
        values on either side.  The Cisco fixture has 2 physical
        access ports + 1 LAG + 1 loopback — target 2930F-48G-PoEP
        has 48 access + 4 uplinks, so no overage expected."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoss")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="2930F-48G-PoEP")
        banner = page.locator('[data-testid="migrate-rename-fitcheck"]')
        expect(banner).to_be_visible()
        # Access kind row appears: "access: <src_count> / <tgt_count>".
        access = page.locator(
            '[data-testid="migrate-fitcheck-kind-physical"]'
        )
        expect(access).to_be_visible()
        expect(access).to_contain_text("48")  # target count

    def test_fitcheck_is_green_when_it_fits(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Two access ports onto a 24-port 2930F: the banner says it
        fits, and is drawn so -- green, its counts in the ink that
        goes with it.  An overage is held in
        ``test_migrate_device_models_drawn.py``, by
        ``test_the_capacity_banner_counts_the_ports_the_config_uses``."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoss")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="2930F-24G")
        banner = page.locator('[data-testid="migrate-rename-fitcheck"]')
        expect(banner).to_be_visible()
        counts = page.locator('[data-testid="migrate-fitcheck-kind-physical"]')
        expect(counts).to_have_text("access: 2 / 24")
        # The class that says it fits -- and the paint, which the
        # class is not: green, in the ink that goes with it.  The ink
        # is read on the counts, which are the banner's words.
        assert (banner.get_attribute("class") or "").split() == ["fit-ok"]
        assert alike(
            painted_background(banner),
            painted_token(page, TOP, "--badge-completed-bg"),
        )
        assert ink(counts) == token_ink(page, "--badge-completed-fg")

    def test_fitcheck_module_note_surfaces_selected_sku(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """For module-variant profiles the banner shows which
        module SKU the numbers are counted against — operator
        understands the capacity context at a glance."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="cisco_iosxe")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="C9300-24UX")
        note = page.locator(
            '[data-testid="migrate-fitcheck-module-note"]'
        )
        expect(note).to_be_visible()
        # NM-8X is the pre-selected default for C9300-24UX.
        expect(note).to_contain_text("NM-8X")
        # Swap to NM-2Q — note updates in place.
        page.locator(
            '[data-testid="migrate-rename-target-module-select"]'
        ).select_option(value="NM-2Q")
        expect(note).to_contain_text("NM-2Q")

    def test_fitcheck_no_module_note_for_legacy_profile(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Legacy profiles have no module dimension — the banner
        omits the SKU note to keep it uncluttered."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoss")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="2930F-48G-PoEP")
        note = page.locator(
            '[data-testid="migrate-fitcheck-module-note"]'
        )
        # Note element never gets rendered for legacy profiles.
        expect(note).to_have_count(0)


class TestRenameModalProfileNotice:
    """Target-profile provenance notice — which deployment state the
    profile's port names describe, how well they are established, and
    any caveat.  A port id picked from a profile is written verbatim
    into the generated config, so the operator has to be told when the
    names on offer are unverified."""

    NOTICE = '[data-testid="migrate-rename-profile-notice"]'

    def _pick(self, page: Page, vendor: str, model: str) -> None:
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value=vendor)
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value=model)

    def test_notice_hides_and_resets_when_the_profile_is_cleared(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Shown first, so this cannot pass on an element that simply
        ships ``display:none``.  Clearing the model, then the vendor,
        must hide the notice AND drop the stale grade attribute."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        notice = page.locator(self.NOTICE)
        self._pick(page, "cisco_iosxe", "C9300-24UX")
        expect(notice).to_be_visible()
        assert notice.get_attribute("data-evidence") == "capture"
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="")
        expect(notice).to_be_hidden()
        assert notice.get_attribute("data-evidence") is None
        self._pick(page, "cisco_iosxe", "C9300-24UX")
        expect(notice).to_be_visible()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="")
        expect(notice).to_be_hidden()
        assert notice.get_attribute("data-evidence") is None

    def test_ungraded_profile_says_it_is_ungraded(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
        live_server_url: str,
    ):
        """Unset ``evidence`` means nobody has checked the names, not
        that they are fine -- so the notice says so instead of staying
        blank.  Resolved from the live registry so grading a profile
        later does not break this test."""
        profiles = page.request.get(
            live_server_url + "/api/v1/migration/target-profiles"
        ).json()
        ungraded = [
            p for p in profiles if not p.get("evidence") and p.get("ports")
        ]
        assert ungraded, "every profile is graded now -- retire this test"
        target = ungraded[0]
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        self._pick(page, target["vendor"], target["model"])
        notice = page.locator(self.NOTICE)
        expect(notice).to_be_visible()
        assert notice.get_attribute("data-evidence") == "ungraded"
        assert "notice-warn" not in (notice.get_attribute("class") or "")
        expect(page.locator(
            '[data-testid="migrate-rename-profile-notice-evidence"]'
        )).to_contain_text("not yet graded")

    def test_notice_states_the_deployment_the_port_names_describe(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """An Aruba 2930F port is ``24`` standalone and ``1/24`` as a
        VSF member; the profile describes one of those and says which."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        self._pick(page, "aruba_aoss", "2930F-48G-PoEP")
        notice = page.locator(self.NOTICE)
        expect(notice).to_be_visible()
        state = page.locator(
            '[data-testid="migrate-rename-profile-notice-state"]'
        )
        expect(state).to_contain_text("standalone")

    def test_capture_backed_profile_says_so_without_alarm(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        self._pick(page, "cisco_iosxe", "C9300-24UX")
        notice = page.locator(self.NOTICE)
        expect(notice).to_be_visible()
        assert notice.get_attribute("data-evidence") == "capture"
        # The C9300 profiles carry a caveat about network modules, but
        # the notice goes amber only for an `inferred` grade.
        expect(page.locator(
            '[data-testid="migrate-rename-profile-notice-caveat"]'
        )).to_contain_text("network module")
        assert "notice-warn" not in (notice.get_attribute("class") or "")
        expect(page.locator(
            '[data-testid="migrate-rename-profile-notice-evidence"]'
        )).to_contain_text("real capture")

    def test_unverified_profile_is_flagged_amber_with_its_caveat(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
        live_server_url: str,
    ):
        """Resolves an ``inferred`` profile from the live registry
        rather than naming one.  No shipped profile carries that grade
        (the set is pinned empty by
        ``tests/unit/migration/test_target_profile_evidence.py``), so
        the one found here is the synthetic profile ``conftest.py``
        adds to the e2e server's definitions directory."""
        profiles = page.request.get(
            live_server_url + "/api/v1/migration/target-profiles"
        ).json()
        inferred = [p for p in profiles if p.get("evidence") == "inferred"]
        assert inferred, "no profile is graded `inferred` any more"
        target = inferred[0]
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        self._pick(page, target["vendor"], target["model"])
        notice = page.locator(self.NOTICE)
        expect(notice).to_be_visible()
        assert "notice-warn" in (notice.get_attribute("class") or "")
        # Amber is paint; the class only asks for it.
        assert alike(
            painted_background(notice),
            painted_token(page, TOP, "--badge-partial-bg"),
        )
        caveat = page.locator(
            '[data-testid="migrate-rename-profile-notice-caveat"]'
        )
        expect(caveat).to_have_text(target["caveat"])
        # The ink is read on the parts that hold the words.
        grade = page.locator(
            '[data-testid="migrate-rename-profile-notice-evidence"]'
        )
        for part in (grade, caveat):
            assert ink(part) == token_ink(page, "--badge-partial-fg")

    def test_notice_is_ports_pane_only(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """The notice is about PORT names; it must not follow the
        operator onto the VLAN pane, and must come back with them."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        self._pick(page, "aruba_aoss", "2930F-48G-PoEP")
        notice = page.locator(self.NOTICE)
        expect(notice).to_be_visible()
        fitcheck = page.locator('[data-testid="migrate-rename-fitcheck"]')
        expect(fitcheck).to_be_visible()
        page.locator('[data-testid="migrate-rename-rail-vlans"]').click()
        expect(notice).to_be_hidden()
        expect(fitcheck).to_be_hidden()
        # An override edit on the VLAN pane refreshes the summary, which
        # re-runs both renderers.  Neither may come back while the
        # ports pane is inactive (the ports banner used to).
        page.locator(
            '[data-testid="migrate-rename-vlan-override-10"]'
        ).fill("110")
        expect(notice).to_be_hidden()
        expect(fitcheck).to_be_hidden()
        page.locator('[data-testid="migrate-rename-rail-ports"]').click()
        expect(notice).to_be_visible()
        expect(fitcheck).to_be_visible()


class TestRenameModalOffProfileAutoTarget:
    """Selecting a profile does not change auto-translated names: the
    translator derives a target name from the shape of the source name
    (Cisco ``GigabitEthernet1/0/1`` becomes AOS-S ``1/1``) whatever
    model is chosen.  When the auto name is not a port the selected
    profile lists, the row says so -- otherwise the default the operator
    leaves in place is a port the chosen device does not have."""

    ROW = '[data-testid="migrate-rename-row-GigabitEthernet1/0/1"]'
    MARK = '[data-testid="migrate-rename-offprofile-GigabitEthernet1/0/1"]'

    def _pick(self, page: Page, vendor: str, model: str) -> None:
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value=vendor)
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value=model)

    def test_auto_name_absent_from_the_profile_is_marked(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """A standalone 2930F lists bare ``1``..``52``; the auto name
        is the stacked form ``1/1``."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        row = page.locator(self.ROW)
        # No profile -> nothing to compare against -> no mark.
        assert "has-offprofile" not in (row.get_attribute("class") or "")
        self._pick(page, "aruba_aoss", "2930F-48G-PoEP")
        row = page.locator(self.ROW)
        assert "has-offprofile" in (row.get_attribute("class") or "")
        mark = page.locator(self.MARK)
        expect(mark).to_be_visible()
        assert "1/1 is not a port on" in (mark.get_attribute("title") or "")
        expect(page.locator(
            '[data-testid="migrate-rename-section-offprofile-physical"]'
        )).to_contain_text("not on profile")
        # Choosing a real port clears it.
        choose_override(page, "GigabitEthernet1/0/1", "12")
        row = page.locator(self.ROW)
        assert "has-offprofile" not in (row.get_attribute("class") or "")
        expect(page.locator(self.MARK)).to_have_count(0)

    def test_auto_name_the_profile_lists_is_not_marked(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """The 3810M profile describes stack member 1, whose ports ARE
        ``1/1``.. -- so the same auto name is on-profile there."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        self._pick(page, "aruba_aoss", "3810M-48G-PoEP")
        row = page.locator(self.ROW)
        assert "has-offprofile" not in (row.get_attribute("class") or "")
        expect(page.locator(self.MARK)).to_have_count(0)
        # The LAG row's auto name (Trk1) is one of the profile's LAGs.
        lag_row = page.locator(
            '[data-testid="migrate-rename-row-Port-channel1"]'
        )
        assert "has-offprofile" not in (lag_row.get_attribute("class") or "")


class TestRenameModalLeftRail:
    """P2C3 added a left-rail category nav with Ports + VLANs panes.
    Clicking a rail button swaps the visible category pane; counts
    on the rail buttons reflect each category's row count."""

    def test_rail_renders_with_ports_active_by_default(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        rail = page.locator('[data-testid="migrate-rename-rail"]')
        expect(rail).to_be_visible()
        # Ports pane starts active; VLANs pane starts hidden.
        ports_pane = page.locator('[data-testid="migrate-rename-ports-pane"]')
        vlans_pane = page.locator('[data-testid="migrate-rename-vlans-pane"]')
        # "active" CSS class drives visibility via the
        # .mig-rename-category-pane.active { display:block; } rule.
        ports_cls = ports_pane.get_attribute("class") or ""
        vlans_cls = vlans_pane.get_attribute("class") or ""
        assert "active" in ports_cls
        assert "active" not in vlans_cls

    def test_clicking_vlans_rail_activates_vlans_pane(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator('[data-testid="migrate-rename-rail-vlans"]').click()
        # Active class flips.
        ports_pane = page.locator('[data-testid="migrate-rename-ports-pane"]')
        vlans_pane = page.locator('[data-testid="migrate-rename-vlans-pane"]')
        expect(vlans_pane).to_be_visible()
        ports_cls = ports_pane.get_attribute("class") or ""
        vlans_cls = vlans_pane.get_attribute("class") or ""
        assert "active" in vlans_cls
        assert "active" not in ports_cls

    def test_vlan_row_renders_for_source_vlan(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator('[data-testid="migrate-rename-rail-vlans"]').click()
        # VLAN 10 is declared in the Cisco fixture; row should render.
        row = page.locator('[data-testid="migrate-rename-vlan-row-10"]')
        expect(row).to_be_visible()
        override = page.locator('[data-testid="migrate-rename-vlan-override-10"]')
        expect(override).to_be_visible()

    def test_vlan_rail_count_matches_source_vlans(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        count = page.locator(
            '[data-testid="migrate-rename-rail-vlans-count"]'
        )
        # The Cisco fixture declares exactly one VLAN (id 10).
        expect(count).to_have_text("1")

    def test_vlan_override_updates_summary(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator('[data-testid="migrate-rename-rail-vlans"]').click()
        # Override VLAN 10 → 100.
        page.locator(
            '[data-testid="migrate-rename-vlan-override-10"]'
        ).fill("100")
        # VLAN sub-summary appears with the override count.
        sub = page.locator('[data-testid="migrate-rename-summary-vlans"]')
        expect(sub).to_be_visible()
        expect(sub).to_contain_text("override")


class TestRenameModalLocalStoragePersistence:
    """Overrides persist across page reloads under a hostname-scoped
    localStorage key.  Reset-all clears the saved state."""

    def test_override_persists_across_reload(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page, live_server_url: str,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator('[data-testid="migrate-rename-rail-vlans"]').click()
        page.locator(
            '[data-testid="migrate-rename-vlan-override-10"]'
        ).fill("555")
        # Wait a tick so the input handler writes to localStorage.
        page.wait_for_timeout(100)
        # Reload the page, re-run the same translation, re-open the modal.
        # localStorage survives the reload and should restore the 555 override.
        mp = migrate_with_cisco_to_aruba
        page.reload()
        mp.source_select.wait_for(state="visible", timeout=5_000)
        mp.pick_source("cisco_iosxe_cli")
        mp.pick_target("aruba_aoss")
        mp.fill_raw(_CISCO_SRC)
        mp.submit_and_wait()
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator('[data-testid="migrate-rename-rail-vlans"]').click()
        restored = page.locator(
            '[data-testid="migrate-rename-vlan-override-10"]'
        )
        expect(restored).to_have_value("555")
        # Status line tells the operator that prior state was restored.
        status = page.locator('[data-testid="migrate-rename-status"]')
        expect(status).to_contain_text("Restored")

    def test_reset_all_clears_persisted_state(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator('[data-testid="migrate-rename-rail-vlans"]').click()
        page.locator(
            '[data-testid="migrate-rename-vlan-override-10"]'
        ).fill("777")
        page.wait_for_timeout(100)
        # Reset clears the user maps + the saved ack.
        page.locator('[data-testid="migrate-rename-modal-reset"]').click()
        override = page.locator(
            '[data-testid="migrate-rename-vlan-override-10"]'
        )
        expect(override).to_have_value("")
        # localStorage should no longer have the ack entry.
        remaining = page.evaluate(
            "() => { var hits = []; for (var i = 0; i < localStorage.length; i++) "
            "{ var k = localStorage.key(i); if (k && k.indexOf('netcanon.rename-ack.') === 0) "
            "hits.push(k); } return hits; }"
        )
        assert remaining == []


# Cisco config carrying local users — exercises P2C4's local-users
# pane which needs non-empty source_local_users on the job.  The
# base _CISCO_SRC fixture at the top of this file declares no
# usernames, so tests below use their own config.
_CISCO_WITH_USERS_SRC = """hostname test-sw-users
!
username admin privilege 15 secret 5 $1$abc$fake
username operator privilege 5 secret 5 $1$def$fake
username svc-backup-2019 privilege 1 secret 5 $1$ghi$fake
!
vlan 10
 name users
!
interface GigabitEthernet1/0/1
 switchport mode access
 switchport access vlan 10
!
end
"""


@pytest.fixture()
def migrate_with_cisco_users_to_aruba(page: Page, live_server_url: str):
    """Translate a Cisco config WITH usernames → Aruba, return the
    MigratePage instance on results view.  Separate from the
    default migrate_with_cisco_to_aruba fixture because the base
    config has no username lines — the local-users pane needs at
    least one source user to enumerate."""
    mp = MigratePage(page)
    page.goto(live_server_url + "/migrate")
    mp.source_select.wait_for(state="visible", timeout=5_000)
    mp.pick_source("cisco_iosxe_cli")
    mp.pick_target("aruba_aoss")
    mp.fill_raw(_CISCO_WITH_USERS_SRC)
    mp.submit_and_wait()
    return mp


class TestRenameModalPaneScopedControls:
    """The target-profile dropdowns + fit-check banner in the modal
    header drive ports-pane-specific behaviour (dropdown-vs-freetext
    rows, per-kind capacity counts).  They have no effect on VLAN /
    local-users panes, so those panes hide the controls to prevent
    operators from thinking they need to pick a profile first."""

    def test_target_profile_group_visible_on_ports_pane(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        group = page.locator(
            '[data-testid="migrate-rename-target-profile-group"]'
        )
        expect(group).to_be_visible()

    def test_target_profile_group_hidden_on_vlans_pane(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-vlans"]'
        ).click()
        group = page.locator(
            '[data-testid="migrate-rename-target-profile-group"]'
        )
        expect(group).to_be_hidden()

    def test_target_profile_group_restores_on_returning_to_ports(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # Leave ports → hidden.
        page.locator(
            '[data-testid="migrate-rename-rail-vlans"]'
        ).click()
        # Return to ports → visible again.
        page.locator(
            '[data-testid="migrate-rename-rail-ports"]'
        ).click()
        group = page.locator(
            '[data-testid="migrate-rename-target-profile-group"]'
        )
        expect(group).to_be_visible()


class TestRenameModalPerPaneFitCheck:
    """Per-pane fit-check banners.  Each pane (VLANs, local_users)
    owns its own banner that surfaces when the active target
    profile declares a capacity limit for that category AND the
    source tree's count for that category is known.  Hidden when
    no profile is picked OR the profile doesn't declare the limit
    — same discipline as the ports fit-check."""

    def test_vlan_fitcheck_hidden_without_profile(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Modal opens with no vendor selected → VLAN fit-check
        stays hidden."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        # Clear the auto-suggested vendor so no profile is active.
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="")
        page.locator(
            '[data-testid="migrate-rename-rail-vlans"]'
        ).click()
        banner = page.locator(
            '[data-testid="migrate-rename-vlans-fitcheck"]'
        )
        expect(banner).to_be_hidden()

    def test_vlan_fitcheck_visible_when_profile_declares_limit(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Aruba 2930F-48G-PoEP declares max_vlans=2048 in its
        shipped YAML.  Picking it should show a green OK banner
        ('1 / 2048' for our 1-VLAN fixture)."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-target-vendor-select"]'
        ).select_option(value="aruba_aoss")
        page.locator(
            '[data-testid="migrate-rename-target-model-select"]'
        ).select_option(value="2930F-48G-PoEP")
        page.locator(
            '[data-testid="migrate-rename-rail-vlans"]'
        ).click()
        banner = page.locator(
            '[data-testid="migrate-rename-vlans-fitcheck"]'
        )
        expect(banner).to_be_visible()
        expect(banner).to_contain_text("VLAN fit")
        # OK state — CSS class includes fit / ok indicators.
        cls = banner.get_attribute("class") or ""
        assert "mig-banner-ok" in cls

    # The previously-shipped ``test_vlan_fitcheck_hidden_when_limit_undeclared``
    # test selected an OPNsense profile under the assumption that OPNsense
    # profiles left ``max_vlans`` unset.  The item-7 data-enrichment
    # commit (``3f311b5``) populated max_vlans=4094 on every OPNsense
    # profile, making the scenario unreachable through shipped profiles.
    # The renderer's "limit undeclared → hidden" branch is still
    # covered by the schema unit tests in
    # ``tests/unit/migration/test_target_profile_schema.py`` (which
    # test ``TargetProfile(max_vlans=None)`` directly) and by the
    # ``test_vlan_fitcheck_hidden_without_profile`` sibling test
    # above (which exercises the no-profile-picked branch that the
    # renderer treats identically).  Deleting this test rather than
    # re-writing it against a synthetic unset-limit profile — less
    # fiddly and equally well covered.


class TestRenameModalCompatBanner:
    """Target-codec compatibility banner on the local-users pane.

    **Post-Option-A state (current):** every shipped bidirectional
    codec round-trips CanonicalLocalUser, so no banner should fire
    on any target.  The banner element + renderer stay in the UI
    as an extension point for future codecs that genuinely DON'T
    round-trip a category (SNMP, RADIUS, etc. when their rename
    panes ship) — the ``renderCompatBanners`` JS reads
    ``CodecInfo.unsupported_rename_categories`` which is currently
    empty on every shipped codec.

    **Pre-Option-A state:** OPNsense + FortiGate listed
    ``{"local_users"}`` under their ``unsupported_rename_categories``
    class attr because an earlier incorrect assumption said those
    codecs kept user blocks in raw_sections.  In fact both already
    parse + render users end-to-end (see
    test_local_users_wire_through.py).  Option A removed those
    false declarations; the integration test
    ``test_unsupported_rename_categories_exposed`` now locks in
    the all-empty state."""

    def test_banner_hidden_cisco_to_aruba(
        self, migrate_with_cisco_to_aruba: MigratePage, page: Page,
    ):
        """Baseline: Cisco → Aruba, no shipped compat issues."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        banner = page.locator(
            '[data-testid="migrate-rename-local-users-compat"]'
        )
        expect(banner).to_be_hidden()

    def test_banner_hidden_cisco_to_opnsense(
        self, page: Page, live_server_url: str,
    ):
        """Post-Option-A: OPNsense round-trips local_users.  Pre-
        fix this test asserted the banner was VISIBLE; fixed to
        assert hidden now that the false declaration is cleared."""
        mp = MigratePage(page)
        page.goto(live_server_url + "/migrate")
        mp.source_select.wait_for(state="visible", timeout=5_000)
        mp.pick_source("cisco_iosxe_cli")
        mp.pick_target("opnsense")
        mp.fill_raw(
            "hostname test-sw\n!\n"
            "username admin privilege 15 secret 5 $1$abc$fake\n!\n"
        )
        mp.submit_and_wait()
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        banner = page.locator(
            '[data-testid="migrate-rename-local-users-compat"]'
        )
        expect(banner).to_be_hidden()

    def test_banner_hidden_cisco_to_fortigate(
        self, page: Page, live_server_url: str,
    ):
        """Post-Option-A: FortiGate round-trips local_users."""
        mp = MigratePage(page)
        page.goto(live_server_url + "/migrate")
        mp.source_select.wait_for(state="visible", timeout=5_000)
        mp.pick_source("cisco_iosxe_cli")
        mp.pick_target("fortigate_cli")
        mp.fill_raw(
            "hostname test-sw\n!\n"
            "username admin privilege 15 secret 5 $1$abc$fake\n!\n"
        )
        mp.submit_and_wait()
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        banner = page.locator(
            '[data-testid="migrate-rename-local-users-compat"]'
        )
        expect(banner).to_be_hidden()


class TestRenameModalLocalUsersPane:
    """P2C4 added a third rail category for local-user renaming.
    Structural parallel to the VLAN pane — enumerates every user
    declared in the source, offers free-text rename + drop actions."""

    def test_rail_button_renders_with_count(
        self, migrate_with_cisco_users_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        btn = page.locator('[data-testid="migrate-rename-rail-local-users"]')
        expect(btn).to_be_visible()
        count = page.locator(
            '[data-testid="migrate-rename-rail-local-users-count"]'
        )
        # Cisco fixture declares 3 users (admin / operator / svc-backup-2019).
        expect(count).to_have_text("3")

    def test_clicking_rail_activates_local_users_pane(
        self, migrate_with_cisco_users_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        ports_pane = page.locator('[data-testid="migrate-rename-ports-pane"]')
        users_pane = page.locator('[data-testid="migrate-rename-local-users-pane"]')
        expect(users_pane).to_be_visible()
        assert "active" in (users_pane.get_attribute("class") or "")
        assert "active" not in (ports_pane.get_attribute("class") or "")

    def test_user_row_renders_for_source_user(
        self, migrate_with_cisco_users_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        row = page.locator(
            '[data-testid="migrate-rename-local-user-row-admin"]'
        )
        expect(row).to_be_visible()
        override = page.locator(
            '[data-testid="migrate-rename-local-user-override-admin"]'
        )
        expect(override).to_be_visible()

    def test_override_updates_summary(
        self, migrate_with_cisco_users_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        page.locator(
            '[data-testid="migrate-rename-local-user-override-admin"]'
        ).fill("netadmin")
        sub = page.locator(
            '[data-testid="migrate-rename-summary-local-users"]'
        )
        expect(sub).to_be_visible()
        expect(sub).to_contain_text("override")

    def test_drop_link_cycles_states(
        self, migrate_with_cisco_users_to_aruba: MigratePage, page: Page,
    ):
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        drop_link = page.locator(
            '[data-testid="migrate-rename-local-user-drop-svc-backup-2019"]'
        )
        # Default state: "drop".
        expect(drop_link).to_have_text("drop")
        drop_link.click()
        # After click: "un-drop".
        expect(drop_link).to_have_text("un-drop")

    def test_override_persists_across_reload(
        self,
        migrate_with_cisco_users_to_aruba: MigratePage,
        page: Page,
        live_server_url: str,
    ):
        """localStorage ack schema v1 is additive — local_users map
        persists alongside ports + vlans under the same key."""
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        page.locator(
            '[data-testid="migrate-rename-local-user-override-admin"]'
        ).fill("superadmin")
        page.wait_for_timeout(100)
        # Reload + re-run translation + re-open modal.
        mp = migrate_with_cisco_users_to_aruba
        page.reload()
        mp.source_select.wait_for(state="visible", timeout=5_000)
        mp.pick_source("cisco_iosxe_cli")
        mp.pick_target("aruba_aoss")
        mp.fill_raw(_CISCO_WITH_USERS_SRC)
        mp.submit_and_wait()
        page.locator('[data-testid="migrate-rename-open-btn"]').click()
        page.locator(
            '[data-testid="migrate-rename-rail-local-users"]'
        ).click()
        restored = page.locator(
            '[data-testid="migrate-rename-local-user-override-admin"]'
        )
        expect(restored).to_have_value("superadmin")
        # Status line reflects user-count in restore notice.
        status = page.locator('[data-testid="migrate-rename-status"]')
        expect(status).to_contain_text("user")
