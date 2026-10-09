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
