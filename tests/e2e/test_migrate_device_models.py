"""
E2E tests for the device pickers in the rename modal.

The operator says which device a config came from and which device it
is going to; Apply then pairs the two port lists by position, and the
table shows the pairing and every name it could not place.

The headline case is the one the feature was built for: a real
standalone Aruba 2930F-48G config moved onto a 2930M-48G with an SFP+
module, deployed as a one-member stack.  Same vendor on both sides, so
the name-shape translation renames nothing at all -- before this the
modal's ports pane was empty for it.

Everything here runs the committed real captures through the real
server; nothing is mocked.  The pairing itself is pinned in
``tests/unit/migration/test_run_plan_with_models.py`` and the API in
``tests/integration/test_migration_models_api.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.helpers import MigratePage

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]

#: A real standalone 2930F-48G-4SFP (JL260A): ports 1-52.
CAPTURE_2930F = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/hpe_community_2930f_wc1607_intervlan.cfg"
).read_text(encoding="utf-8")

#: A real one-member 2930M stack: JL323A with a JL083A in bay A.
CAPTURE_2930M = (
    REPO_ROOT / "tests/fixtures/real/aruba_aoss/user_contrib_2930m_wc1611.cfg"
).read_text(encoding="utf-8")

_CISCO_SRC = """hostname test-sw
!
interface GigabitEthernet1/0/1
 description user
 switchport mode access
 switchport access vlan 10
!
interface GigabitEthernet1/0/2
 description user
 switchport mode access
 switchport access vlan 10
!
end
"""

#: Nothing here for any pane but one hardware port: no VLAN, no user,
#: no SNMP, no rename (same vendor) and no warning.
_AOSS_ONE_PORT = (
    "; JL260A Configuration Editor; Created on release #WC.16.07.0002\n"
    'hostname "sw"\n'
    "interface 7\n"
    '   name "printer"\n'
    "   exit\n"
)

SOURCE_2930F_48G = "fam:2930F:2930F-48G-4SFP"
TARGET_2930M_48G = "fam:2930M:2930M-48G-PoEP"
TARGET_2930M_24G = "fam:2930M:2930M-24G"


def _tid(name: str) -> str:
    return f'[data-testid="{name}"]'


def _translate(page: Page, base: str, source: str, target: str, raw: str) -> MigratePage:
    mp = MigratePage(page)
    page.goto(base + "/migrate")
    mp.source_select.wait_for(state="visible", timeout=5_000)
    mp.pick_source(source)
    mp.pick_target(target)
    mp.fill_raw(raw)
    mp.submit_and_wait()
    return mp


@pytest.fixture()
def aoss_2930f(page: Page, live_server_url: str) -> MigratePage:
    """A 2930F config translated AOS-S to AOS-S, modal open."""
    mp = _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
    page.locator(_tid("migrate-rename-open-btn")).click()
    expect(page.locator(_tid("migrate-rename-modal"))).to_be_visible()
    return mp


def _source_note(page: Page):
    return page.locator(_tid("migrate-device-source-note"))


def _target_note(page: Page):
    return page.locator(_tid("migrate-device-target-note"))


def _plan(page: Page):
    return page.locator(_tid("migrate-rename-plan"))


def _pick_target(page: Page, value: str, bay_a: str | None = None) -> None:
    page.locator(_tid("migrate-rename-target-model-select")).select_option(value=value)
    expect(_target_note(page)).to_be_visible()
    if bay_a is not None:
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value=bay_a)


def _apply(page: Page) -> dict:
    """Click Apply; return the body of the plan request it sent."""
    with (
        page.expect_request("**/api/v1/migration/plan") as request,
        page.expect_response("**/api/v1/migration/plan"),
    ):
        page.locator(_tid("migrate-rename-apply-btn")).click()
    return json.loads(request.value.post_data or "{}")


# ---------------------------------------------------------------------------
# Without any device: a same-vendor translation is no longer a dead end
# ---------------------------------------------------------------------------


class TestSameVendorTranslationHasRows:
    def test_the_modal_opens_and_lists_the_ports_the_config_uses(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """AOS-S to AOS-S renames no port, and the table used to say
        "No port names recognised".  Every port the config uses now has
        a row, shown as unchanged."""
        expect(page.locator(_tid("migrate-rename-table-empty"))).to_be_hidden()
        row = page.locator(_tid("migrate-rename-row-49"))
        expect(row).to_be_visible()
        expect(row).to_contain_text("(unchanged)")
        expect(page.locator(_tid("migrate-rename-row-1"))).to_be_visible()


    def test_a_config_with_nothing_but_a_port_still_opens_the_modal(
        self, page: Page, live_server_url: str,
    ) -> None:
        """The button used to need a rename, a warning, a VLAN, a
        user or a community.  A port the config uses is enough: it
        is exactly the config whose devices are worth declaring."""
        _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", _AOSS_ONE_PORT)
        button = page.locator(_tid("migrate-rename-open-btn"))
        expect(button).to_be_visible()
        button.click()
        expect(page.locator(_tid("migrate-rename-row-7"))).to_contain_text("(unchanged)")
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text("1")
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value(
            SOURCE_2930F_48G
        )


# ---------------------------------------------------------------------------
# The source device is read from the config
# ---------------------------------------------------------------------------


class TestSourceDeviceIsReadFromTheConfig:
    def test_the_picker_is_filled_and_says_where_from(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        select = page.locator(_tid("migrate-device-source-model-select"))
        expect(select).to_have_value(SOURCE_2930F_48G)
        expect(page.locator(_tid("migrate-device-source-mode-select"))).to_have_value("standalone")
        note = _source_note(page)
        expect(note).to_be_visible()
        expect(note).to_contain_text("JL260A")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_have_text(
            re.compile(r"^52 ports: 1 . 52$")
        )
        # The committed capture IS this model: its names are proven.
        expect(note).to_have_attribute("data-evidence", "capture")
        lines = page.locator(_tid("migrate-device-source-note-read-from"))
        expect(lines).to_contain_text("Read from the config")
        lines.locator("summary").click()
        expect(lines).to_contain_text("; JL260A Configuration Editor")

    def test_a_standalone_device_has_no_member_number(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        expect(page.locator(_tid("migrate-device-source-member-0-id"))).to_have_count(0)
        expect(page.locator(_tid("migrate-device-source-add-member"))).to_be_hidden()

    def test_with_no_target_the_strip_asks_for_one(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_contain_text(
            "Choose the target device"
        )

    def test_a_stack_capture_is_read_with_its_member_and_module(
        self, page: Page, live_server_url: str,
    ) -> None:
        """``member 1 type "JL323A"`` and ``member 1 flexible-module A
        type JL083A`` are lines of the config, and are quoted."""
        _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930M)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(_source_note(page)).to_be_visible()
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value(
            "fam:2930M:2930M-40G-8SR-PoEP"
        )
        expect(page.locator(_tid("migrate-device-source-mode-select"))).to_have_value("stacked")
        expect(page.locator(_tid("migrate-device-source-member-0-id"))).to_have_value("1")
        expect(page.locator(_tid("migrate-device-source-member-0-bay-A"))).to_have_value("JL083A")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("1/A4")
        # What a provisioning line does and does not prove is said.
        expect(_source_note(page)).to_contain_text("does not show that a module is fitted")

    def test_choosing_another_model_offers_the_detected_one_back(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        select = page.locator(_tid("migrate-device-source-model-select"))
        select.select_option(value="fam:2930F:2930F-24G-4SFP")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("28 ports")
        expect(page.locator(_tid("migrate-device-source-note-config-says"))).to_contain_text("JL260A")
        page.locator(_tid("migrate-device-source-use-detected")).click()
        expect(select).to_have_value(SOURCE_2930F_48G)
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("52 ports")

    def test_a_vendor_with_no_detector_says_so(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Nothing reads the hardware lines of a Cisco config yet: the
        picker stays empty, lists that vendor's profiles, and says why."""
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_SRC)
        page.locator(_tid("migrate-rename-open-btn")).click()
        select = page.locator(_tid("migrate-device-source-model-select"))
        expect(select).to_have_value("")
        expect(select).to_be_enabled()
        expect(_source_note(page)).to_contain_text("declare the device yourself")
        values = select.locator("option").evaluate_all("els => els.map(e => e.value)")
        assert "profile:C9300-48P" in values
        assert not [v for v in values if v.startswith("fam:")]


# ---------------------------------------------------------------------------
# The corridor the feature was built for
# ---------------------------------------------------------------------------


class TestStandalone2930FOntoStacked2930M:
    def test_a_family_model_brings_its_mode_and_bay(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        _pick_target(page, TARGET_2930M_48G)
        expect(page.locator(_tid("migrate-device-target-mode-select"))).to_have_value("stacked")
        expect(page.locator(_tid("migrate-device-target-member-0-id"))).to_have_value("1")
        # The profile module select belongs to flat profiles.
        expect(page.locator(_tid("migrate-rename-target-module-select"))).to_be_hidden()
        # A bay nobody stated is said, in amber: it is counted as empty.
        note = _target_note(page)
        expect(page.locator(_tid("migrate-device-target-note-unstated"))).to_contain_text("bay A")
        expect(note).to_have_class(re.compile(r"\bnotice-warn\b"))
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("48 ports")
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_have_text(
            re.compile(r"^52 ports: 1/1 . 1/A4$")
        )
        expect(note).not_to_have_class(re.compile(r"\bnotice-warn\b"))
        expect(note).to_have_attribute("data-evidence", "vendor-doc")
        expect(_plan(page)).to_have_attribute("data-state", "ready")

    def test_a_port_paired_with_a_port_of_the_same_name_is_shown_as_paired(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """The same model on both sides: every port is paired with its
        namesake.  A row shows that name as its target -- not a note
        that nothing was mapped."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, SOURCE_2930F_48G)
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("52 paired")
        row = page.locator(_tid("migrate-rename-row-49"))
        expect(row).to_have_attribute("data-plan-state", "paired")
        expect(row.locator("td").nth(1)).to_have_text("49")
        expect(page.locator(_tid("migrate-rename-row-1")).locator("td").nth(1)).to_have_text("1")
        # No paired row says nothing was mapped.  (A row for a name the
        # translator left as it was -- a VLAN interface, a LAG -- still
        # may: that is what the note is for.)
        expect(
            page.locator('tr[data-plan-state="paired"]').get_by_text("needs override")
        ).to_have_count(0)

    def test_apply_pairs_every_port_by_position(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        body = _apply(page)
        assert body["source_deployment"] == {
            "mode": "standalone",
            "members": [{"model": "2930F-48G-4SFP", "modules": {}}],
        }
        assert body["target_deployment"] == {
            "mode": "stacked",
            "members": [{"model": "2930M-48G-PoEP", "id": 1, "modules": {"A": "JL083A"}}],
        }
        assert "target_profile" not in body and "source_profile" not in body

        expect(_plan(page)).to_have_attribute("data-state", "ok")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("52 paired")
        # The built-in uplinks land on the module's ports, by position.
        row = page.locator(_tid("migrate-rename-row-49"))
        expect(row).to_have_attribute("data-plan-state", "paired")
        expect(row.locator("td").nth(1)).to_have_text("1/A1")
        expect(page.locator(_tid("migrate-rename-why-49"))).to_have_text("uplink 1")
        expect(page.locator(_tid("migrate-rename-why-1"))).to_have_text("access 1")
        expect(aoss_2930f.output).to_contain_text("untagged 1/48,1/A1,1/A2,1/A3,1/A4")
        expect(aoss_2930f.status_summary).to_contain_text("completed")
        # The per-kind count banner gives way to the plan, which names
        # the ports instead of counting them by the shape of a name.
        expect(page.locator(_tid("migrate-rename-fitcheck"))).to_be_hidden()

    def test_an_override_picks_among_the_targets_ports_of_the_same_role(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        override = page.locator(_tid("migrate-rename-override-49"))
        values = override.locator("option").evaluate_all("els => els.map(e => e.value)")
        assert [v for v in values if "/" in v] == ["1/A1", "1/A2", "1/A3", "1/A4"]
        access = page.locator(_tid("migrate-rename-override-1"))
        access_values = access.locator("option").evaluate_all("els => els.map(e => e.value)")
        assert "1/48" in access_values and "1/A1" not in access_values


# ---------------------------------------------------------------------------
# Ports with no place on the target
# ---------------------------------------------------------------------------


class TestPortsWithNoPlace:
    def test_they_are_listed_and_need_a_decision(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """The module bay left empty: the four uplinks have nowhere to
        go.  They are dropped, each has a row that says so, and the job
        is not a clean success until the operator has decided."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G)
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("48 paired")
        expect(page.locator(_tid("migrate-rename-plan-unplaced"))).to_contain_text("4 with no place")
        expect(page.locator(_tid("migrate-rename-plan-pending"))).to_contain_text("4 need your decision")
        row = page.locator(_tid("migrate-rename-row-49"))
        expect(row).to_have_class(re.compile(r"\bneeds-decision\b"))
        expect(page.locator(_tid("migrate-rename-plan-state-49"))).to_have_text(
            re.compile(r"^no uplink port left on the target . dropped$")
        )
        expect(page.locator(_tid("migrate-rename-decision-49"))).to_be_visible()
        expect(page.locator(_tid("migrate-rename-decision-count-physical"))).to_contain_text(
            "4 need a decision"
        )
        expect(page.locator(_tid("migrate-rename-status"))).to_contain_text(
            "4 port names still need your decision"
        )
        expect(aoss_2930f.status_summary).to_contain_text("partial")
        # What the mapping reported is listed, in the server's words.
        expect(page.locator(_tid("migrate-rename-plan-report"))).to_contain_text(
            "4 source uplink port(s) have no uplink port left on the target"
        )

    def test_accepting_what_is_shown_settles_the_job(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G)
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        page.locator(_tid("migrate-rename-plan-accept")).click()
        expect(page.locator(_tid("migrate-rename-status"))).to_contain_text("4 decisions recorded")
        expect(page.locator(_tid("migrate-rename-row-49"))).not_to_have_class(
            re.compile(r"\bneeds-decision\b")
        )
        body = _apply(page)
        assert body["port_rename_map"] == {
            "49": None, "50": None, "51": None, "52": None,
        }
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        expect(page.locator(_tid("migrate-rename-plan-accept"))).to_have_count(0)
        expect(aoss_2930f.status_summary).to_contain_text("completed")

    def test_an_unplaced_port_can_be_given_any_port_of_the_target(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """A port with no place among its own kind is offered the
        target's other ports too.  Giving it one another port holds is
        caught before Apply, as any collision is."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G)
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        override = page.locator(_tid("migrate-rename-override-49"))
        values = override.locator("option").evaluate_all("els => els.map(e => e.value)")
        assert "1/48" in values and "__DROP__" in values
        override.select_option(value="1/48")
        expect(page.locator(_tid("migrate-rename-row-49"))).to_have_class(
            re.compile(r"\bhas-collision\b")
        )
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_disabled()

    def test_a_dropped_port_does_not_hold_its_old_name(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """48 ports onto a 24-port switch of the same series, both
        standalone, so both number their ports alike: the uplinks
        ``49``-``52`` land on ``25``-``28``, the names of four access
        ports that were dropped.  A dropped port reaches no target,
        so that is no collision and Apply stays available."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, "fam:2930F:2930F-24G-4SFP")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_have_text(
            re.compile(r"^28 ports: 1 . 28$")
        )
        _apply(page)
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("28 paired")
        row = page.locator(_tid("migrate-rename-row-49"))
        expect(row.locator("td").nth(1)).to_have_text("25")
        expect(row).not_to_have_class(re.compile(r"\bhas-collision\b"))
        expect(page.locator(_tid("migrate-rename-row-25"))).to_have_class(
            re.compile(r"\bhas-drop\b")
        )
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_enabled()

    def test_a_smaller_switch_leaves_access_ports_behind_too(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_24G, bay_a="JL083A")
        _apply(page)
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("28 paired")
        expect(page.locator(_tid("migrate-rename-plan-unplaced"))).to_contain_text("24 with no place")
        expect(page.locator(_tid("migrate-rename-plan-state-25"))).to_contain_text(
            "no access port left on the target"
        )
        # The uplinks still found their place, on the module.
        expect(page.locator(_tid("migrate-rename-row-49")).locator("td").nth(1)).to_have_text("1/A1")


# ---------------------------------------------------------------------------
# Stack members
# ---------------------------------------------------------------------------


class TestStackMembers:
    def test_a_member_is_added_and_removed(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        page.locator(_tid("migrate-device-target-add-member")).click()
        # A copy of the first member, with the next free member number.
        expect(page.locator(_tid("migrate-device-target-member-1-id"))).to_have_value("2")
        expect(page.locator(_tid("migrate-device-target-member-1-model"))).to_have_value(
            "2930M-48G-PoEP"
        )
        expect(page.locator(_tid("migrate-device-target-member-1-bay-A"))).to_have_value("JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_have_text(
            re.compile(r"^104 ports: 1/1 . 2/A4$")
        )
        page.locator(_tid("migrate-device-target-member-1-remove")).click()
        expect(page.locator(_tid("migrate-device-target-member-1"))).to_have_count(0)
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")

    def test_a_free_port_of_the_second_member_is_offered_and_marked(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        page.locator(_tid("migrate-device-target-add-member")).click()
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("104 ports")
        body = _apply(page)
        assert [m["id"] for m in body["target_deployment"]["members"]] == [1, 2]
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        override = page.locator(_tid("migrate-rename-override-52"))
        texts = override.locator("option").all_text_contents()
        assert any(t.startswith("2/A1") and "(free)" in t for t in texts), texts
        assert not any(t.startswith("1/A1") and "(free)" in t for t in texts), texts
        override.select_option(value="2/A1")
        _apply(page)
        expect(aoss_2930f.output).to_contain_text("2/A1")
        expect(_plan(page)).to_have_attribute("data-state", "ok")

    def test_a_member_number_outside_the_stack_is_refused_in_words(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        member = page.locator(_tid("migrate-device-target-member-0-id"))
        member.fill("11")
        member.dispatch_event("change")
        error = page.locator(_tid("migrate-device-target-note-error"))
        expect(error).to_be_visible()
        expect(_target_note(page)).to_have_class(re.compile(r"\bnotice-block\b"))
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_contain_text("not valid yet")
        # A declaration that does not compile is not sent.
        body = _apply(page)
        assert "target_deployment" not in body and "source_deployment" not in body

    def test_standing_alone_takes_the_member_number_away(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        page.locator(_tid("migrate-device-target-mode-select")).select_option(value="standalone")
        expect(page.locator(_tid("migrate-device-target-member-0-id"))).to_have_count(0)
        expect(page.locator(_tid("migrate-device-target-add-member"))).to_be_hidden()
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_have_text(
            re.compile(r"^52 ports: 1 . A4$")
        )


# ---------------------------------------------------------------------------
# A stack on both sides
# ---------------------------------------------------------------------------

#: Two 2930F-48G-4SFP as one VSF fabric; ``{m}`` is the number of the
#: second member.  Not a capture: no committed capture names a port of
#: a second member.  The port names are the ones the family's VSF mode
#: gives, the ``vsf`` stanza is the nested form of HPE's guide with
#: placeholder addresses, and ports 51-52 of each member are the
#: fabric's own links.  The two members carry different VLANs.
_VSF_FABRIC_OF = """; hpStack_WC Configuration Editor; Created on release #WC.16.07.0002
hostname "fabric"
vsf
   enable domain 1
   member 1
      type "JL260A" mac-address aabbcc-000001
      priority 200
      link 1 1/51-1/52
      exit
   member {m}
      type "JL260A" mac-address aabbcc-00000{m}
      link 1 {m}/51-{m}/52
      exit
   port-speed 1g
   exit
trunk 1/49,{m}/49 trk1 lacp
interface 1/1
   name "desk-a"
   exit
interface {m}/1
   name "desk-b"
   exit
vlan 1
   name "DEFAULT_VLAN"
   no untagged 1/1-1/10,{m}/1-{m}/30
   untagged 1/11-1/48,1/50,{m}/31-{m}/48,{m}/50
   tagged Trk1
   exit
vlan 10
   name "users"
   untagged 1/1-1/10,{m}/1-{m}/4
   tagged Trk1,{m}/50
   exit
vlan 20
   name "voice"
   untagged {m}/5-{m}/30
   tagged Trk1,1/50
   exit
"""


def _open_fabric(page: Page, base: str, second: int = 2) -> MigratePage:
    """The fabric translated AOS-S to AOS-S, modal open, source read."""
    mp = _translate(page, base, "aruba_aoss", "aruba_aoss", _VSF_FABRIC_OF.format(m=second))
    page.locator(_tid("migrate-rename-open-btn")).click()
    expect(_source_note(page)).to_be_visible()
    return mp


def _pick_a_two_member_stack(page: Page) -> None:
    _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
    page.locator(_tid("migrate-device-target-add-member")).click()
    expect(page.locator(_tid("migrate-device-target-note-ports"))).to_have_text(
        re.compile(r"^104 ports: 1/1 . 2/A4$")
    )


class TestAStackOnBothSides:
    """A two-member VSF fabric as the source and a two-member 2930M
    stack as the target.  The members pair row by row, in the order
    the two pickers list them."""

    def test_the_fabric_is_read_from_the_config_member_by_member(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Each ``member N`` block of the ``vsf`` stanza is a row of
        the source picker, with the number the config gives it."""
        _open_fabric(page, live_server_url, second=3)
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value(
            SOURCE_2930F_48G
        )
        expect(page.locator(_tid("migrate-device-source-mode-select"))).to_have_value("vsf")
        expect(page.locator(_tid("migrate-device-source-member-0-id"))).to_have_value("1")
        expect(page.locator(_tid("migrate-device-source-member-1-id"))).to_have_value("3")
        expect(page.locator(_tid("migrate-device-source-member-1-model"))).to_have_value(
            "2930F-48G-4SFP"
        )
        expect(page.locator(_tid("migrate-device-source-member-2"))).to_have_count(0)
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_have_text(
            re.compile(r"^104 ports: 1/1 . 3/52$")
        )

    def test_two_stacks_pair_member_by_member(
        self, page: Page, live_server_url: str,
    ) -> None:
        mp = _open_fabric(page, live_server_url)
        _pick_a_two_member_stack(page)
        body = _apply(page)
        assert body["source_deployment"]["mode"] == "vsf"
        assert [(m["model"], m["id"]) for m in body["source_deployment"]["members"]] == [
            ("2930F-48G-4SFP", 1), ("2930F-48G-4SFP", 2),
        ]
        assert [(m["id"], m["modules"]) for m in body["target_deployment"]["members"]] == [
            (1, {"A": "JL083A"}), (2, {"A": "JL083A"}),
        ]
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        # 104 ports, less the four the fabric uses as its own links.
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("100 paired")
        # The member numbers agree, so there is nothing to say of them.
        expect(page.locator(_tid("migrate-rename-plan-members"))).to_have_count(0)
        # An uplink of the SECOND member lands on the second member's module.
        row = page.locator(_tid("migrate-rename-row-2/49"))
        expect(row).to_have_attribute("data-plan-state", "paired")
        expect(row.locator("td").nth(1)).to_have_text("2/A1")
        expect(page.locator(_tid("migrate-rename-why-2/49"))).to_have_text("uplink 1 · member 2")
        expect(page.locator(_tid("migrate-rename-why-1/50"))).to_have_text("uplink 2 · member 1")
        expect(page.locator(_tid("migrate-rename-why-2/30"))).to_have_text("access 30 · member 2")
        # An access port keeps its name between the two stacks.  That is
        # a pairing like any other, and the row shows it as one.
        expect(page.locator(_tid("migrate-rename-row-2/30")).locator("td").nth(1)).to_have_text("2/30")
        expect(page.locator(_tid("migrate-rename-row-1/1")).locator("td").nth(1)).to_have_text("1/1")
        # No paired row says nothing was mapped.  (A row for a name the
        # translator left as it was -- a VLAN interface, a LAG -- still
        # may: that is what the note is for.)
        expect(
            page.locator('tr[data-plan-state="paired"]').get_by_text("needs override")
        ).to_have_count(0)
        # A LAG with a port on each member keeps one on each.
        expect(mp.output).to_contain_text("trunk 1/A1,2/A1 trk1 lacp")
        expect(mp.output).to_contain_text("tagged 1/A2,Trk1")

    def test_a_member_that_lands_on_another_number_is_said(
        self, page: Page, live_server_url: str,
    ) -> None:
        """The fabric's second member is number 3; the stack's is 2.
        Rows pair in order, so every port of member 3 is renamed --
        and the strip and each row say why."""
        mp = _open_fabric(page, live_server_url, second=3)
        _pick_a_two_member_stack(page)
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("100 paired")
        expect(page.locator(_tid("migrate-rename-plan-members"))).to_have_text(
            "member 3 → member 2"
        )
        row = page.locator(_tid("migrate-rename-row-3/49"))
        expect(row.locator("td").nth(1)).to_have_text("2/A1")
        expect(page.locator(_tid("migrate-rename-why-3/49"))).to_have_text(
            "uplink 1 · member 3 → member 2"
        )
        expect(page.locator(_tid("migrate-rename-row-3/7")).locator("td").nth(1)).to_have_text("2/7")
        expect(page.locator(_tid("migrate-rename-why-1/1"))).to_have_text("access 1 · member 1")
        expect(page.locator(_tid("migrate-rename-plan-report"))).to_contain_text(
            "stack members pair in the order they are declared, not by member number: "
            "source member 3 with target member 2"
        )
        expect(mp.output).to_contain_text("trunk 1/A1,2/A1 trk1 lacp")
        expect(mp.output).not_to_contain_text("3/")

    def test_a_member_the_target_has_no_member_for(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Two members onto one switch: the second member's ports have
        no member to go to.  They are dropped, each row says so, and
        the plan waits for a decision."""
        mp = _open_fabric(page, live_server_url)
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("50 paired")
        expect(page.locator(_tid("migrate-rename-plan-unplaced"))).to_have_text(
            "50 with no place on the target"
        )
        row = page.locator(_tid("migrate-rename-row-2/1"))
        expect(row).to_have_attribute("data-plan-state", "unplaced")
        expect(page.locator(_tid("migrate-rename-plan-state-2/1"))).to_contain_text(
            "the target has no stack member in this position"
        )
        expect(page.locator(_tid("migrate-rename-why-2/1"))).to_have_text(
            "access 1 · member 2 → no member"
        )
        expect(page.locator(_tid("migrate-rename-why-1/1"))).to_have_text("access 1 · member 1")
        # The LAG keeps its port on the member that is there.
        expect(mp.output).to_contain_text("trunk 1/A1 trk1 lacp")


# ---------------------------------------------------------------------------
# What is sent, and what is not
# ---------------------------------------------------------------------------


class TestWhatApplySends:
    def test_a_target_alone_is_advice_and_declares_nothing(
        self, page: Page, live_server_url: str,
    ) -> None:
        """A family model on the target with no source device: the
        server would refuse half a declaration, so none is sent.  The
        target's port list still fills the choices."""
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_SRC)
        page.locator(_tid("migrate-rename-open-btn")).click()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_contain_text(
            "Choose the source device as well"
        )
        override = page.locator(_tid("migrate-rename-override-GigabitEthernet1/0/1"))
        values = override.locator("option").evaluate_all("els => els.map(e => e.value)")
        assert "1/1" in values and "1/48" in values
        body = _apply(page)
        assert not [k for k in body if "deployment" in k or "profile" in k]
        expect(_plan(page)).not_to_have_attribute("data-state", "ok")

    def test_a_profile_can_be_the_source(
        self, page: Page, live_server_url: str,
    ) -> None:
        """No family describes a Catalyst yet; its profile declares it.
        The note says its port order is the profile's list order."""
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_SRC)
        page.locator(_tid("migrate-rename-open-btn")).click()
        page.locator(_tid("migrate-device-source-model-select")).select_option(
            value="profile:C9300-48P"
        )
        expect(page.locator(_tid("migrate-device-source-note-order"))).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        body = _apply(page)
        assert body["source_profile"] == "cisco_iosxe/C9300-48P"
        assert "source_deployment" not in body
        assert body["target_deployment"]["members"][0]["model"] == "2930M-48G-PoEP"
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("2 paired")
        expect(page.locator(_tid("migrate-rename-row-GigabitEthernet1/0/2")).locator("td").nth(1)).to_have_text("1/2")

    def test_clearing_a_device_takes_it_out_of_the_next_request(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """The request body is a copy of the last one.  A device that
        was declared and then cleared must not ride along."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        first = _apply(page)
        assert "source_deployment" in first and "target_deployment" in first
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        page.locator(_tid("migrate-device-source-model-select")).select_option(value="")
        expect(_plan(page)).to_have_attribute("data-state", "stale")
        second = _apply(page)
        assert "source_deployment" not in second and "target_deployment" not in second
        expect(_plan(page)).not_to_have_attribute("data-state", "ok")
        expect(aoss_2930f.output).not_to_contain_text("1/A1")

    def test_clearing_a_target_profile_takes_it_out_too(
        self, page: Page, live_server_url: str,
    ) -> None:
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_SRC)
        page.locator(_tid("migrate-rename-open-btn")).click()
        model = page.locator(_tid("migrate-rename-target-model-select"))
        model.select_option(value="2930F-48G")
        assert _apply(page)["target_profile"] == "aruba_aoss/2930F-48G"
        model.select_option(value="")
        assert "target_profile" not in _apply(page)

    def test_reset_all_reaches_the_server(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """A VLAN override that was applied and then reset must not
        be applied again: the next request carries no VLAN map."""
        page.locator(_tid("migrate-rename-rail-vlans")).click()
        page.locator(_tid("migrate-rename-vlan-override-2")).fill("200")
        assert _apply(page)["vlan_rename_map"] == {"2": 200}
        expect(aoss_2930f.output).to_contain_text("vlan 200")
        page.locator(_tid("migrate-rename-modal-reset")).click()
        assert "vlan_rename_map" not in _apply(page)
        expect(aoss_2930f.output).not_to_contain_text("vlan 200")

    def test_the_target_pick_survives_closing_the_modal(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-rename-target-model-select"))).to_have_value(
            TARGET_2930M_48G
        )
        expect(page.locator(_tid("migrate-device-target-member-0-bay-A"))).to_have_value("JL083A")
        expect(_plan(page)).to_have_attribute("data-state", "ok")


# ---------------------------------------------------------------------------
# Ports pane only
# ---------------------------------------------------------------------------


class TestDevicePickersBelongToThePortsPane:
    def test_they_hide_on_another_pane_and_come_back(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        _apply(page)
        expect(_plan(page)).to_be_visible()
        page.locator(_tid("migrate-rename-rail-vlans")).click()
        for name in (
            "migrate-device-source", "migrate-device-source-note",
            "migrate-device-target-note", "migrate-rename-plan",
            "migrate-rename-target-profile-group",
        ):
            expect(page.locator(_tid(name))).to_be_hidden()
        page.locator(_tid("migrate-rename-rail-ports")).click()
        for name in (
            "migrate-device-source", "migrate-device-source-note",
            "migrate-device-target-note", "migrate-rename-plan",
        ):
            expect(page.locator(_tid(name))).to_be_visible()


# ---------------------------------------------------------------------------
# What the plan says beyond pairs: two names for one port, a stray landing,
# a route left behind
# ---------------------------------------------------------------------------

_ROUTEROS_NAMED = """/interface ethernet
set [ find default-name=ether1 ] comment="wan"
set [ find default-name=ether2 ] name=core-a comment="core A"
/ip address
add address=192.0.2.2/30 interface=ether1
add address=10.0.0.1/24 interface=core-a
"""

_ROUTEROS_GATEWAY_LIST = """/interface ethernet
set [ find default-name=ether1 ] comment="a"
set [ find default-name=ether2 ] comment="b"
/ip address
add address=192.0.2.2/30 interface=ether1
add address=192.0.2.6/30 interface=ether2
/ip route
add dst-address=0.0.0.0/0 gateway=ether1,ether2
"""

_FORTIGATE_WITH_AN_AGGREGATE = """config system interface
    edit "port1"
        set ip 10.1.1.1 255.255.255.0
        set type physical
    next
    edit "port2"
        set ip 10.2.2.1 255.255.255.0
        set type physical
    next
    edit "fortilink"
        set ip 10.255.1.1 255.255.255.0
        set type aggregate
    next
end
"""


def _declare(page: Page, source_model: str, target_model: str) -> None:
    page.locator(_tid("migrate-rename-open-btn")).click()
    expect(page.locator(_tid("migrate-rename-modal"))).to_be_visible()
    page.locator(_tid("migrate-device-source-model-select")).select_option(
        value="profile:" + source_model
    )
    # A profile, not a family model: it has no deployment to resolve,
    # so there is no target note to wait for.
    page.locator(_tid("migrate-rename-target-model-select")).select_option(value=target_model)


class TestWhatThePlanSaysBeyondPairs:
    def test_a_port_the_operator_named_keeps_the_name_and_says_where_it_is(
        self, page: Page, live_server_url: str,
    ) -> None:
        """RouterOS keeps a port's factory name beside the name an
        operator gave it.  The row goes by the operator's name, says
        which port of the model it is, and says where its hardware
        went -- the output keeps the name."""
        mp = _translate(
            page, live_server_url, "mikrotik_routeros", "mikrotik_routeros", _ROUTEROS_NAMED,
        )
        _declare(page, "CRS310-8G+2S+", "CCR2004-1G-12S+2XS")
        body = _apply(page)
        assert body["source_profile"] == "mikrotik_routeros/CRS310-8G+2S+"
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        row = page.locator(_tid("migrate-rename-row-core-a"))
        expect(row).to_contain_text("ether2 in the device model")
        expect(row).to_contain_text("a name, not a place")
        expect(row).to_contain_text("the port is on sfp-sfpplus2")
        expect(mp.status_summary).to_contain_text("completed")

    def test_a_port_no_line_of_the_output_finds_is_said(
        self, page: Page, live_server_url: str,
    ) -> None:
        """RouterOS output has no Ethernet line for a port whose name
        reads as a LAG.  The strip says so in a blocking chip, the row
        says what to do, and the job is not a success."""
        mp = _translate(
            page, live_server_url, "mikrotik_routeros", "mikrotik_routeros",
            _ROUTEROS_NAMED.replace("core-a", "bond1"),
        )
        _declare(page, "CRS310-8G+2S+", "CCR2004-1G-12S+2XS")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "block")
        expect(page.locator(_tid("migrate-rename-plan-unbound"))).to_contain_text(
            "1 not found by its hardware in the output"
        )
        row = page.locator(_tid("migrate-rename-row-bond1"))
        expect(row).to_contain_text("no line of the output finds this port (sfp-sfpplus2)")
        expect(page.locator(_tid("migrate-rename-plan-report"))).to_contain_text(
            "bond1 on sfp-sfpplus2"
        )
        expect(mp.status_summary).to_contain_text("partial")

    def test_a_route_left_naming_a_port_that_moved_is_said(
        self, page: Page, live_server_url: str,
    ) -> None:
        """A list of gateways is not followed when its ports move.
        Nothing in the port map clears that, so the strip says it and
        the job is not a clean success."""
        mp = _translate(
            page, live_server_url, "mikrotik_routeros", "mikrotik_routeros",
            _ROUTEROS_GATEWAY_LIST,
        )
        _declare(page, "CRS310-8G+2S+", "CCR2004-1G-12S+2XS")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        expect(page.locator(_tid("migrate-rename-plan-stale-routes"))).to_contain_text(
            "1 route still names a port that moved"
        )
        expect(page.locator(_tid("migrate-rename-plan-report"))).to_contain_text("0.0.0.0/0")
        expect(mp.status_summary).to_contain_text("partial")

    def test_a_logical_name_on_a_port_the_target_lacks_needs_a_decision(
        self, page: Page, live_server_url: str,
    ) -> None:
        """A FortiGate's stock aggregate is given a port-shaped name
        (``fortilink1``) the declared FortiGate does not have.  It is
        kept, said, and asks for a decision."""
        mp = _translate(
            page, live_server_url, "fortigate_cli", "fortigate_cli",
            _FORTIGATE_WITH_AN_AGGREGATE,
        )
        _declare(page, "100E", "100E")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        expect(page.locator(_tid("migrate-rename-plan-landed"))).to_contain_text(
            "1 on a port the target does not have"
        )
        expect(page.locator(_tid("migrate-rename-plan-state-fortilink"))).to_contain_text(
            "given the port name fortilink1, which the target device does not have"
        )
        expect(page.locator(_tid("migrate-rename-row-fortilink"))).to_have_class(
            re.compile(r"\bneeds-decision\b")
        )
        expect(mp.status_summary).to_contain_text("partial")
