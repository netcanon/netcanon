"""
E2E tests for the device pickers: what is DRAWN and what is SENT.

``test_migrate_device_models.py`` walks the flows.  This module holds
the pickers to what an operator can see and reach, and the server to
what the screen said:

* at a laptop's size, with a stack of ten on each side, the table and
  the Apply button are still inside the modal and under the mouse;
* a colour is read as the pixel that was painted, not as the name of a
  class or the value of a custom property;
* a decision recorded by "Accept as shown" belongs to the pairing it
  was shown for;
* a count on the strip is of what happened, not of what was planned;
* the request Apply sends is read off the wire, for every field Apply
  owns;
* why an Apply did not happen is still in the modal when the toast
  that said it is gone, and that toast takes no click.

The stack, Catalyst, Junos and detection cases run small configs
written here or beside the flows; the corridor cases run the two
committed real captures.  Nothing is mocked.
"""

from __future__ import annotations

import json
import re

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.drawn import (
    alike,
    choose_override,
    contrast,
    ink,
    override_options,
    painted_background,
    painted_token,
    token_ink,
)
from tests.e2e.helpers import MigratePage
from tests.e2e.test_migrate_device_models import (
    _CISCO_SRC,
    _FORTIGATE_WITH_AN_AGGREGATE,
    _ROUTEROS_NAMED,
    CAPTURE_2930F,
    CAPTURE_2930M,
    REPO_ROOT,
    SOURCE_2930F_48G,
    TARGET_2930M_24G,
    TARGET_2930M_48G,
    _apply,
    _declare,
    _open,
    _open_fabric,
    _pick_a_two_member_stack,
    _pick_target,
    _plan,
    _source_note,
    _target_note,
    _tid,
    _translate,
)
from tests.fixtures.model_families import MARKUP_FAMILY_MODEL_OPTION, MARKUP_RAN

pytestmark = pytest.mark.e2e

_STACK_BANNER = "; hpStack_WC Configuration Editor; Created on release #WC.16.07.0003\n"


@pytest.fixture()
def aoss_2930f(page: Page, live_server_url: str) -> MigratePage:
    """A 2930F config translated AOS-S to AOS-S, modal open."""
    mp = _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
    page.locator(_tid("migrate-rename-open-btn")).click()
    expect(page.locator(_tid("migrate-rename-modal"))).to_be_visible()
    return mp


def _stack_of(count: int, part: str = "JL322A", hostname: str = "stack") -> str:
    """A 2930M backplane stack of *count* members that uses a few
    ports of each."""
    members = "".join(f'   member {n} type "{part}"\n' for n in range(1, count + 1))
    used = ",".join(f"{n}/1-{n}/4" for n in range(1, count + 1))
    return (
        _STACK_BANNER
        + f'hostname "{hostname}"\n'
        + "stacking\n" + members + "   exit\n"
        + f"vlan 1\n   untagged {used}\n   exit\n"
    )


def _add_target_members(page: Page, upto: int) -> None:
    add = page.locator(_tid("migrate-device-target-add-member"))
    for rank in range(1, upto):
        add.click()
        expect(page.locator(_tid(f"migrate-device-target-member-{rank}"))).to_be_attached()


def _box(page: Page, selector: str) -> dict:
    return page.evaluate(
        """(selector) => {
            const r = document.querySelector(selector).getBoundingClientRect();
            return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,
                    height: r.height, width: r.width};
        }""",
        selector,
    )


# ---------------------------------------------------------------------------
# Layout: the pickers do not push the table or Apply out of the modal
# ---------------------------------------------------------------------------


class TestTheTableAndApplyStayInTheModal:
    """The device rows, both notes and the strip sit above the table.
    They used to be fixed-height items in a box that clipped: a stack
    of four pushed the table to nothing and the footer out of the
    modal, where a mouse cannot follow (Playwright's ``click`` scrolls
    a clipped element into view, so no test that only clicked could
    see it).  These read where things ARE."""

    @pytest.mark.parametrize(
        "width,height", [(1366, 768), (1280, 720), (1920, 1080), (1024, 600)],
    )
    def test_ten_members_a_side_leave_rows_and_a_reachable_apply(
        self, page: Page, live_server_url: str, width: int, height: int,
    ) -> None:
        page.set_viewport_size({"width": width, "height": height})
        _open(page, live_server_url, _stack_of(10))
        # The source: ten members, read from the config.
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("480 ports")
        _pick_target(page, TARGET_2930M_48G)
        _add_target_members(page, 10)
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("480 ports")
        _apply(page)
        expect(_plan(page)).to_contain_text("Ports paired by position")
        # The target's member list is open (the operator built it), so
        # the strip that says what happened is far down the region that
        # scrolls.  Apply brings it into view.
        seen = page.evaluate(
            """() => {
                const top = document.getElementById('mig-rename-modal-top').getBoundingClientRect();
                const strip = document.querySelector('[data-testid="migrate-rename-plan-paired"]')
                    .getBoundingClientRect();
                return strip.top >= top.top - 0.5 && strip.bottom <= top.bottom + 0.5;
            }"""
        )
        assert seen, "the strip is not in view after Apply"

        modal = _box(page, "#mig-rename-modal")
        apply_box = _box(page, "#mig-rename-apply-btn")
        assert page.evaluate("document.getElementById('mig-rename-modal').scrollTop") == 0
        # The button is inside the modal's box and it is what a click
        # at its centre lands on.
        assert apply_box["bottom"] <= modal["bottom"] + 0.5
        assert apply_box["bottom"] <= height
        hit = page.evaluate(
            """() => {
                const b = document.getElementById('mig-rename-apply-btn').getBoundingClientRect();
                const el = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
                return el && el.id;
            }"""
        )
        assert hit == "mig-rename-apply-btn"
        # The table keeps its floor -- thirteen rem, whatever is above
        # it -- and whole rows lie inside its pane.  How many rows that
        # is depends on the machine's fonts (three here, two on the CI
        # runner's, at eleven rem); the floor does not.
        table = page.evaluate(
            """() => {
                const pane = document.getElementById('mig-rename-table-pane').getBoundingClientRect();
                const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
                const rows = [...document.querySelectorAll('#mig-rename-sections tbody tr')].filter((tr) => {
                    const r = tr.getBoundingClientRect();
                    return r.height > 0 && r.top >= pane.top && r.bottom <= pane.bottom;
                }).length;
                return {rows: rows, height: pane.height, floor: 13 * rem};
            }"""
        )
        assert table["height"] >= table["floor"] - 1, table
        assert table["rows"] >= 2, table
        # And what is above the table can be scrolled, by itself.
        top = page.evaluate(
            """() => {
                const el = document.getElementById('mig-rename-modal-top');
                return {scroll: el.scrollHeight, client: el.clientHeight,
                        overflow: getComputedStyle(el).overflowY};
            }"""
        )
        assert top["overflow"] == "auto"
        assert top["scroll"] > top["client"]
        # Neither region is squeezed for the other.  The table gives
        # way first, down to its floor; the pickers are not crushed to
        # a sliver because the preview beside the table is long (they
        # were, where both shrank in proportion to what they hold).
        if height >= 720:
            assert top["client"] >= 0.35 * height, top

    def test_a_long_stack_read_from_the_config_folds_under_its_count(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Ten members read from a config are ten lines of controls
        nobody asked for.  They fold under a count that says which
        members they are, and open when asked."""
        _open(page, live_server_url, _stack_of(10))
        fold = page.locator(_tid("migrate-device-source-members-fold"))
        summary = page.locator(_tid("migrate-device-source-members-fold-summary"))
        expect(summary).to_have_text("10 stack members (1\u201310)")
        expect(page.locator(_tid("migrate-device-source-member-9-id"))).to_be_hidden()
        summary.click()
        expect(page.locator(_tid("migrate-device-source-member-9-id"))).to_be_visible()
        expect(page.locator(_tid("migrate-device-source-member-9-id"))).to_have_value("10")
        # An edit redraws the controls; the list the operator opened stays open.
        page.locator(_tid("migrate-device-source-member-9-bay-A")).select_option(value="JL083A")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("484 ports")
        expect(fold).to_have_attribute("open", "")
        expect(page.locator(_tid("migrate-device-source-member-9-id"))).to_be_visible()

    def test_a_list_the_operator_is_adding_to_does_not_fold_under_them(
        self, page: Page, live_server_url: str,
    ) -> None:
        _open(page, live_server_url, CAPTURE_2930F)
        _pick_target(page, TARGET_2930M_48G)
        _add_target_members(page, 6)
        expect(page.locator(_tid("migrate-device-target-members-fold"))).to_have_attribute("open", "")
        expect(page.locator(_tid("migrate-device-target-member-5-id"))).to_be_visible()

    def test_a_stack_is_said_by_runs_of_like_members(
        self, page: Page, live_server_url: str,
    ) -> None:
        """The note names a stack once per run of like members, not
        once per member."""
        _open(page, live_server_url, _stack_of(6))
        said = page.locator(_tid("migrate-device-source-note-device"))
        expect(said).to_have_text(
            re.compile(r"^Source: 6 \u00d7 Aruba 2930M-48G-PoE\+ \(JL322A\) as members 1\u20136 — ")
        )
        # A member of another model breaks the run.
        page.locator(_tid("migrate-device-source-members-fold-summary")).click()
        page.locator(_tid("migrate-device-source-member-5-model")).select_option(value="2930M-24G")
        expect(said).to_have_text(
            re.compile(
                r"^Source: 5 \u00d7 Aruba 2930M-48G-PoE\+ \(JL322A\) as members 1\u20135; "
                r"Aruba 2930M-24G \(JL319A\) as member 6 — "
            )
        )


TOP = "#mig-rename-modal-top"


def _saved_overrides(page: Page) -> dict:
    """Every rename-override record the page keeps across a reload."""
    return page.evaluate(
        """() => {
            const out = {};
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key.startsWith('netcanon.rename-ack.')) out[key] = JSON.parse(localStorage.getItem(key));
            }
            return out;
        }"""
    )


# ---------------------------------------------------------------------------
# "Accept as shown" is a verdict on one pairing
# ---------------------------------------------------------------------------


class TestAcceptedDecisionsAreForOnePairing:
    """The button records what is on screen as the operator's decision
    for every name still undecided.  It used to write that into the
    operator's own override map, which is sent with every Apply and
    kept across page loads: accept four dropped uplinks, then give the
    target the module that has their ports, and Apply dropped them
    still -- job ``completed``, strip green, "52 paired"."""

    def _accept_four_dropped_uplinks(self, page: Page) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G)
        _apply(page)
        expect(page.locator(_tid("migrate-rename-plan-unplaced"))).to_have_text(
            "4 with no place on the target"
        )
        page.locator(_tid("migrate-rename-plan-accept")).click()
        body = _apply(page)
        assert body["port_rename_map"] == {"49": None, "50": None, "51": None, "52": None}
        expect(_plan(page)).to_have_attribute("data-state", "ok")

    def test_they_are_not_sent_once_the_devices_are_others(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        self._accept_four_dropped_uplinks(page)
        expect(aoss_2930f.output).not_to_contain_text("1/A1")
        # The operator sees the target lacks uplinks and fits the module.
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        expect(_plan(page)).to_have_attribute("data-state", "ready")
        expect(_plan(page)).to_have_attribute("data-stale", "true")
        body = _apply(page)
        # The four drops were a verdict on a target with no uplink port.
        assert body["port_rename_map"] == {}
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("52 paired")
        expect(page.locator(_tid("migrate-rename-plan-your-drops"))).to_have_count(0)
        expect(page.locator(_tid("migrate-rename-auto-49"))).to_have_text("1/A1")
        expect(page.locator(_tid("migrate-rename-row-49"))).not_to_have_class(
            re.compile(r"\bhas-drop\b")
        )
        expect(aoss_2930f.output).to_contain_text("untagged 1/48,1/A1,1/A2,1/A3,1/A4")

    def test_they_are_sent_again_while_the_devices_are_the_same(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """Forgetting is for other devices.  With the same two, a
        second Apply -- after a VLAN edit, say -- still carries them,
        and closing and reopening the modal does not lose them."""
        self._accept_four_dropped_uplinks(page)
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-rename-row-49"))).to_have_class(
            re.compile(r"\bhas-drop\b")
        )
        body = _apply(page)
        assert body["port_rename_map"] == {"49": None, "50": None, "51": None, "52": None}
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        # With an override of the operator's own beside them, the page
        # has something to remember -- and what it remembers is put
        # back when the modal opens.  The four are not in it, and are
        # not lost to it.
        choose_override(page, "3", "__DROP__")
        assert [record["ports"] for record in _saved_overrides(page).values()] == [{"3": None}]
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-rename-status"))).to_contain_text(
            "Restored prior overrides"
        )
        body = _apply(page)
        assert body["port_rename_map"] == {
            "3": None, "49": None, "50": None, "51": None, "52": None,
        }

    def test_they_are_not_remembered_across_a_page_load(
        self, aoss_2930f: MigratePage, page: Page, live_server_url: str,
    ) -> None:
        """The devices are not remembered across a reload, so a verdict
        on their pairing is not either: it came back as four drops for
        a job with no device declared at all."""
        self._accept_four_dropped_uplinks(page)
        assert [record["ports"] for record in _saved_overrides(page).values()] in ([], [{}])
        _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(_source_note(page)).to_be_visible()
        expect(page.locator(_tid("migrate-rename-status"))).not_to_contain_text("Restored")
        expect(page.locator(_tid("migrate-rename-row-49"))).not_to_have_class(
            re.compile(r"\bhas-drop\b")
        )
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        assert _apply(page)["port_rename_map"] == {}
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("52 paired")

    def test_a_row_changed_by_hand_since_is_the_operators_own(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """Accepted, then one of the four set by hand: that one is the
        operator's standing decision.  It is sent with other devices,
        and it is what the page remembers."""
        self._accept_four_dropped_uplinks(page)
        choose_override(page, "50", "")
        choose_override(page, "50", "__DROP__")
        saved = [record["ports"] for record in _saved_overrides(page).values()]
        assert saved == [{"50": None}]
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        body = _apply(page)
        assert body["port_rename_map"] == {"50": None}
        # The strip says what happened: three uplinks on the module, and
        # one paired port that the operator's own entry dropped.
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("51 paired")
        drops = page.locator(_tid("migrate-rename-plan-your-drops"))
        expect(drops).to_be_visible()
        expect(drops).to_have_text("1 paired port dropped by your own entries")
        expect(page.locator(_tid("migrate-rename-why-50"))).to_contain_text(
            "dropped by your own entry"
        )

    def test_a_new_translation_starts_without_them(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """Translated again on the same page, the record of what was
        accepted is gone with the job it was about.  Left behind, it
        would take the next drop of the same port for one of its own:
        not remembered, and forgotten with the devices."""
        self._accept_four_dropped_uplinks(page)
        page.locator(_tid("migrate-rename-modal-close")).click()
        _translate_behind_the_modal(page, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-rename-row-49"))).not_to_have_class(
            re.compile(r"\bhas-drop\b")
        )
        # One override of the operator's own, so that the page has
        # something to remember and to put back when the modal opens:
        # the record of the last job's four must not come back with it.
        choose_override(page, "3", "__DROP__")
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-rename-row-3"))).to_have_class(
            re.compile(r"\bhas-drop\b")
        )
        expect(page.locator(_tid("migrate-rename-row-49"))).not_to_have_class(
            re.compile(r"\bhas-drop\b")
        )
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        assert _apply(page)["port_rename_map"] == {"3": None}

    def test_reset_all_forgets_them(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        self._accept_four_dropped_uplinks(page)
        page.locator(_tid("migrate-rename-modal-reset")).click()
        # The job on the page was made with entries that are gone: the
        # strip is the job's, and it says the entries changed.
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        unsent = page.locator(_tid("migrate-rename-plan-unsent"))
        expect(unsent).to_be_visible()
        expect(unsent).to_contain_text("your entries changed since this mapping was made")
        assert _apply(page)["port_rename_map"] == {}
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        expect(page.locator(_tid("migrate-rename-plan-pending"))).to_have_text(
            "4 need your decision"
        )
        # The record went with the entries.  Left behind, it would be
        # put back beside the next thing the page remembers: one
        # override of the operator's own, the modal closed and opened,
        # and the four drops that were reset are back.
        choose_override(page, "3", "__DROP__")
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-rename-row-3"))).to_have_class(
            re.compile(r"\bhas-drop\b")
        )
        # Port 49 is dropped by the mapping, not by an entry.
        expect(page.locator(_tid("migrate-rename-row-49"))).to_have_class(
            re.compile(r"\bhas-auto-drop\b")
        )
        assert _apply(page)["port_rename_map"] == {"3": None}

    def test_a_name_that_was_kept_is_recorded_as_kept(
        self, page: Page, live_server_url: str,
    ) -> None:
        """A dropped name stays dropped and a KEPT one stays where it
        landed: the stock FortiGate aggregate, given a port-shaped
        name the target lacks, is recorded under that name -- not as
        a drop."""
        _translate(
            page, live_server_url, "fortigate_cli", "fortigate_cli",
            _FORTIGATE_WITH_AN_AGGREGATE,
        )
        _declare(page, "100E", "100E")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        expect(page.locator(_tid("migrate-rename-plan-pending"))).to_have_text(
            "1 needs your decision"
        )
        # The row that needs the decision is on screen, not folded away.
        expect(page.locator(_tid("migrate-rename-row-fortilink"))).to_be_visible()
        page.locator(_tid("migrate-rename-plan-accept")).click()
        expect(page.locator(_tid("migrate-rename-plan-pending"))).to_have_text(
            "1 decision recorded — Apply to confirm"
        )
        body = _apply(page)
        assert body["port_rename_map"] == {"fortilink": "fortilink1"}
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        # Accepted is not the same as fine: it is on a name the target
        # does not list, and the strip and the row go on saying so.
        off = page.locator(_tid("migrate-rename-plan-off-target"))
        expect(off).to_be_visible()
        expect(off).to_have_text("1 on a name the target does not list, by your own entries")
        expect(page.locator(_tid("migrate-rename-row-fortilink"))).to_have_class(
            re.compile(r"\bhas-offtarget\b")
        )
        expect(page.locator(_tid("migrate-rename-offtarget-fortilink"))).to_have_attribute(
            "title", "fortilink1 is not a port the declared target device lists"
        )
        expect(page.locator(_tid("migrate-rename-status"))).to_have_text(
            "Applied. Rendered output refreshed."
        )


# ---------------------------------------------------------------------------
# The strip counts what happened
# ---------------------------------------------------------------------------


class TestTheStripCountsWhatHappened:
    """``pairings`` is the pairing as it was MADE, before the
    operator's own entries.  The strip read it as the outcome: "10
    paired" over an output with seven."""

    def test_a_paired_port_the_operator_dropped_is_not_counted_as_paired(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, SOURCE_2930F_48G)
        choose_override(page, "3", "__DROP__")
        choose_override(page, "4", "__DROP__")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("50 paired")
        expect(page.locator(_tid("migrate-rename-plan-your-drops"))).to_have_text(
            "2 paired ports dropped by your own entries"
        )
        # No entry any more: 52 again, and the chip is gone.
        page.locator(_tid("migrate-rename-modal-reset")).click()
        _apply(page)
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("52 paired")
        expect(page.locator(_tid("migrate-rename-plan-your-drops"))).to_have_count(0)

    def test_an_unplaced_port_the_operator_placed_has_a_place(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """Twenty-four access ports have no place on the member they
        were paired with.  One is given a free port of the second
        member: it is not "with no place" any more, and its row shows
        where it is."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_24G, bay_a="JL083A")
        page.locator(_tid("migrate-device-target-add-member")).click()
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("56 ports")
        _apply(page)
        expect(page.locator(_tid("migrate-rename-plan-unplaced"))).to_have_text(
            "24 with no place on the target"
        )
        choose_override(page, "25", "2/1")
        _apply(page)
        expect(page.locator(_tid("migrate-rename-plan-unplaced"))).to_have_text(
            "23 with no place on the target"
        )
        placed = page.locator(_tid("migrate-rename-plan-your-places"))
        expect(placed).to_be_visible()
        expect(placed).to_have_text("1 given a place by your own entries")
        expect(page.locator(_tid("migrate-rename-auto-25"))).to_have_text("2/1")
        expect(page.locator(_tid("migrate-rename-plan-pending"))).to_have_text(
            "23 need your decision"
        )
        expect(page.locator(_tid("migrate-rename-status"))).to_have_text(
            "Applied. 23 port names still need your decision."
        )
        expect(aoss_2930f.output).to_contain_text("2/1")

    def test_what_a_pairing_costs_is_said_on_the_strip_and_the_row(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """A PoE+ switch with SFP+ uplinks onto one with neither.  The
        job is clean, so the strip is green -- and says in amber what
        the ports lose.  A port the operator dropped has lost nothing."""
        expect(_source_note(page)).to_be_visible()
        page.locator(_tid("migrate-device-source-model-select")).select_option(
            value="fam:2930F:2930F-48G-PoEP-4SFPP"
        )
        _pick_target(page, SOURCE_2930F_48G)
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        poe = page.locator(_tid("migrate-rename-plan-poe-lost"))
        expect(poe).to_be_visible()
        expect(poe).to_have_text("48 PoE ports on a port without PoE")
        slower = page.locator(_tid("migrate-rename-plan-slower"))
        expect(slower).to_be_visible()
        expect(slower).to_have_text("4 on a slower port")
        flag = page.locator(_tid("migrate-rename-flag-1-0"))
        expect(flag).to_be_visible()
        expect(flag).to_have_text("no PoE on the target port")
        expect(flag).to_have_attribute("data-level", "warn")
        assert ink(flag) == token_ink(page, "--badge-partial-fg")
        expect(page.locator(_tid("migrate-rename-why-49"))).to_contain_text("slower: 10gig")
        choose_override(page, "1", "__DROP__")
        _apply(page)
        expect(poe).to_have_text("47 PoE ports on a port without PoE")
        expect(page.locator(_tid("migrate-rename-why-1"))).not_to_contain_text("no PoE")
        expect(page.locator(_tid("migrate-rename-why-1"))).to_contain_text(
            "dropped by your own entry"
        )

    def test_a_crossing_the_operator_undid_port_by_port_is_not_said(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Members listed 2, 1 against 1, 2 cross.  With every used
        port put back on its own member by the operator's own entries,
        no port is on the other switch: the server drops its line, and
        the chip and the rows must drop theirs.  (The browser works
        the crossing out for itself from the plan; it was one
        condition short of the server's rule.)"""
        _open(page, live_server_url, _SMALL_FABRIC)
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("104 ports")
        _pick_a_two_member_stack(page)
        first = page.locator(_tid("migrate-device-target-member-0-id"))
        second = page.locator(_tid("migrate-device-target-member-1-id"))
        for control, number in ((first, "3"), (second, "1"), (first, "2")):
            control.fill(number)
            control.dispatch_event("change")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_have_text(
            re.compile(r"^104 ports: 2/1 . 1/A4$")
        )
        plan = _apply_and_read(page)["port_mapping_plan"]
        assert any("ANOTHER number" in line for line in plan["warnings"])
        crossed = page.locator(_tid("migrate-rename-plan-crossed"))
        expect(crossed).to_have_text("crossed: member 1 → member 2; member 2 → member 1")
        expect(page.locator(_tid("migrate-rename-why-1/1"))).to_have_text(
            "access 1 · member 1 → member 2"
        )
        expect(page.locator(_tid("migrate-rename-auto-1/1"))).to_have_text("2/1")
        # One member put back: the other still crosses.
        choose_override(page, "1/1", "1/1")
        choose_override(page, "2/1", "2/1")
        after = _apply_and_read(page)
        assert not any("ANOTHER number" in line for line in after["port_mapping_plan"]["warnings"])
        expect(crossed).to_have_count(0)
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("0 paired")
        expect(page.locator(_tid("migrate-rename-plan-your-moves"))).to_have_text(
            "2 paired ports sent elsewhere by your own entries"
        )
        why = page.locator(_tid("migrate-rename-why-1/1"))
        expect(why).not_to_contain_text("→")
        expect(why).to_contain_text("access 1 · member 1")
        expect(why).to_contain_text("sent to 1/1 by your own entry")
        flag = page.locator(_tid("migrate-rename-flag-1/1-0"))
        expect(flag).to_have_attribute("data-level", "info")


#: A two-member VSF fabric that uses one port of each member: small
#: enough to decide every port by hand.
_SMALL_FABRIC = """; hpStack_WC Configuration Editor; Created on release #WC.16.07.0002
hostname "small"
vsf
   enable domain 1
   member 1
      type "JL260A"
      exit
   member 2
      type "JL260A"
      exit
   exit
interface 1/1
   name "desk-a"
   exit
interface 2/1
   name "desk-b"
   exit
vlan 10
   name "users"
   untagged 1/1,2/1
   exit
"""


def _apply_and_read(page: Page) -> dict:
    """Click Apply; return the job the server answered with."""
    with page.expect_response("**/api/v1/migration/plan") as answer:
        page.locator(_tid("migrate-rename-apply-btn")).click()
    job = answer.value.json()
    expect(page.locator(_tid("migrate-rename-status"))).to_contain_text("Applied")
    return job


# ---------------------------------------------------------------------------
# What is painted
# ---------------------------------------------------------------------------


class TestWhatIsPainted:
    """A state is an attribute; what the operator sees is paint.  With
    the strip's class fixed at ``plan-ok`` and its ``data-state``
    right, every test passed and the strip was green while it blocked
    the job.  Each state is read here as the colour that was drawn."""

    def test_the_strip_is_the_colour_of_its_state(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        # No pair yet: a hint, in the information colours.
        _pick_target(page, TARGET_2930M_48G)
        expect(_plan(page)).to_have_attribute("data-state", "ready")
        info = painted_token(page, TOP, "--alert-info-bg")
        green = painted_token(page, TOP, "--badge-completed-bg")
        amber = painted_token(page, TOP, "--badge-partial-bg")
        red = painted_token(page, TOP, "--badge-failed-bg")
        assert len({info, green, amber, red}) == 4
        assert alike(painted_background(_plan(page)), info)
        # Four ports need a decision: amber.
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        assert alike(painted_background(_plan(page)), amber)
        assert ink(_plan(page)) == token_ink(page, "--badge-partial-fg")
        # Every port has a place: green.
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("52 ports")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        assert alike(painted_background(_plan(page)), green)
        assert ink(_plan(page)) == token_ink(page, "--badge-completed-fg")

    def test_a_strip_that_blocks_is_red_and_so_is_its_chip_and_its_row(
        self, page: Page, live_server_url: str,
    ) -> None:
        _translate(
            page, live_server_url, "mikrotik_routeros", "mikrotik_routeros",
            _ROUTEROS_NAMED.replace("core-a", "bond1"),
        )
        _declare(page, "CRS310-8G+2S+", "CCR2004-1G-12S+2XS")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "block")
        assert alike(painted_background(_plan(page)), painted_token(page, TOP, "--badge-failed-bg"))
        chip = page.locator(_tid("migrate-rename-plan-unbound"))
        expect(chip).to_be_visible()
        red = token_ink(page, "--badge-failed-fg")
        assert ink(chip) == red
        ground = painted_background(chip)
        assert alike(ground, painted_token(page, TOP, "--surface"))
        assert contrast(ink(chip), ground) >= 4.5
        # The row: the flag that holds the job is red, the remark about
        # the port is not, and the row carries a mark of its own.
        row = page.locator(_tid("migrate-rename-row-bond1"))
        expect(row).to_have_class(re.compile(r"\bhas-block\b"))
        flags = page.locator('[data-testid^="migrate-rename-flag-bond1-"]')
        blocking = flags.filter(has_text="no line of the output finds this port")
        expect(blocking).to_be_visible()
        expect(blocking).to_have_attribute("data-level", "block")
        assert ink(blocking) == red
        remark = flags.filter(has_text="in the device model")
        expect(remark).to_be_visible()
        expect(remark).to_have_attribute("data-level", "info")
        assert ink(remark) == token_ink(page, "--text-muted")
        mark = page.locator(_tid("migrate-rename-block-bond1"))
        expect(mark).to_be_visible()
        expect(mark).to_have_attribute("title", re.compile(r"^no line of the output finds this port"))
        # The report under a strip that needs the operator is open.
        expect(page.locator(_tid("migrate-rename-plan-report")).locator("li").first).to_be_visible()

    def test_a_note_is_the_colour_of_what_it_says(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        # A bay that was not stated: amber.
        _pick_target(page, TARGET_2930M_48G)
        note = _target_note(page)
        expect(page.locator(_tid("migrate-device-target-note-unstated"))).to_be_visible()
        assert alike(painted_background(note), painted_token(page, TOP, "--badge-partial-bg"))
        assert ink(note) == token_ink(page, "--badge-partial-fg")
        # Stated: no colour of its own.
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="JL083A")
        expect(page.locator(_tid("migrate-device-target-note-unstated"))).to_have_count(0)
        expect(page.locator(_tid("migrate-device-target-note-evidence"))).to_have_text(
            "Port names from published vendor sources (no capture of this deployment here)"
        )
        plain = painted_background(note)
        assert not alike(plain, painted_token(page, TOP, "--badge-partial-bg"))
        # Refused by the server: red.
        member = page.locator(_tid("migrate-device-target-member-0-id"))
        member.fill("11")
        member.dispatch_event("change")
        expect(page.locator(_tid("migrate-device-target-note-error"))).to_be_visible()
        assert alike(painted_background(note), painted_token(page, TOP, "--badge-failed-bg"))
        assert ink(note) == token_ink(page, "--badge-failed-fg")
        # The field itself is marked: the browser knows 11 is out of range.
        assert member.evaluate("el => el.matches(':invalid')")
        # And the source, which a real capture proves, says so.
        expect(page.locator(_tid("migrate-device-source-note-evidence"))).to_have_text(
            "Port names checked against a real capture of this deployment"
        )

    @pytest.mark.parametrize("mode", ["light", "dark"])
    def test_a_warning_chip_is_legible_in_any_strip(
        self, aoss_2930f: MigratePage, page: Page, mode: str,
    ) -> None:
        """A chip sits in a strip of any colour.  Laid on the strip as
        a tint of its own it was darker than either and read 2.7:1;
        on the opaque surface it reads the same wherever it is."""
        page.evaluate("(mode) => NcTheme.set(null, mode)", mode)
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G)
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        for name in ("migrate-rename-plan-unplaced", "migrate-rename-plan-pending"):
            chip = page.locator(_tid(name))
            expect(chip).to_be_visible()
            ground = painted_background(chip)
            assert alike(ground, painted_token(page, TOP, "--surface")), name
            assert not alike(ground, painted_background(_plan(page))), name
            assert ink(chip) == token_ink(page, "--badge-partial-fg"), name
            assert contrast(ink(chip), ground) >= 4.5, (name, mode)
        paired = page.locator(_tid("migrate-rename-plan-paired"))
        expect(paired).to_be_visible()
        expect(paired).to_have_text("48 paired")

    def test_a_section_with_a_row_that_needs_a_decision_does_not_stay_closed(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """A section stays as the operator left it -- except that one
        they closed comes back at the next redraw while a row in it
        still needs them.  A decision nobody can see is not made."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G)
        _apply(page)
        section = page.locator(_tid("migrate-rename-section-physical"))
        expect(page.locator(_tid("migrate-rename-decision-count-physical"))).to_have_text(
            "4 need a decision"
        )
        page.locator(_tid("migrate-rename-section-summary-physical")).click()
        expect(section).not_to_have_attribute("open", "")
        # Reset all redraws the table.
        page.locator(_tid("migrate-rename-modal-reset")).click()
        expect(section).to_have_attribute("open", "")
        expect(page.locator(_tid("migrate-rename-row-49"))).to_be_visible()
        # Decided, nothing in it needs the operator: it is closed
        # again, as they left it.
        page.locator(_tid("migrate-rename-plan-accept")).click()
        expect(section).not_to_have_attribute("open", "")
        # Going to another pane and back redraws the table.
        page.locator(_tid("migrate-rename-rail-vlans")).click()
        page.locator(_tid("migrate-rename-rail-ports")).click()
        expect(section).not_to_have_attribute("open", "")

    def test_a_row_that_needs_a_decision_is_marked_on_its_edge(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G)
        _apply(page)
        needs = page.locator(_tid("migrate-rename-source-49"))
        plain = page.locator(_tid("migrate-rename-source-1"))
        assert needs.evaluate("el => getComputedStyle(el).boxShadow") != "none"
        assert plain.evaluate("el => getComputedStyle(el).boxShadow") == "none"
        expect(page.locator(_tid("migrate-rename-decision-49"))).to_be_visible()
        # The table reads in the order of the device, under its headers.
        rows = page.locator('[data-testid^="migrate-rename-row-"][data-plan-state]')
        expect(rows.first).to_have_attribute("data-testid", "migrate-rename-row-1")
        counts = page.locator(_tid("migrate-rename-section-physical")).evaluate(
            """(section) => ({
                heads: section.querySelectorAll('thead th').length,
                cells: section.querySelector('tbody tr').children.length,
                third: section.querySelectorAll('thead th')[3].textContent,
            })"""
        )
        assert counts == {"heads": 5, "cells": 5, "third": "Position"}


# ---------------------------------------------------------------------------
# Apply is never held without a reason, and never by what a pairing would mend
# ---------------------------------------------------------------------------

#: Two ports the name-shape translation puts on one AOS-S name.
_CISCO_TWO_ON_ONE_NAME = """hostname cat
!
interface GigabitEthernet1/0/1
 description desk
 switchport mode access
!
interface AppGigabitEthernet1/0/1
 description app
!
interface TenGigabitEthernet1/1/1
 description uplink
!
end
"""

#: An access port and a LAG: two sections of the table, no collision.
_CISCO_WITH_A_LAG = """hostname cat
!
interface GigabitEthernet1/0/1
 description desk
 switchport mode access
!
interface GigabitEthernet1/0/2
 channel-group 1 mode active
!
interface Port-channel1
 switchport mode trunk
!
end
"""

#: A port with one tagged unit: the translator puts the unit on the port.
_JUNOS_WITH_A_UNIT = """set system host-name j1
set interfaces ge-0/0/1 vlan-tagging
set interfaces ge-0/0/1 unit 54 vlan-id 54
set interfaces ge-0/0/1 unit 54 family inet address 10.0.54.1/24
set interfaces ge-0/0/2 unit 0 family inet address 10.0.2.1/24
set vlans v54 vlan-id 54
"""


class TestApplyIsHeldOnlyForAReasonItStates:
    def test_two_of_the_servers_own_renames_on_one_name_do_not_hold_a_pairing(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Name-shape translation puts two Catalyst ports on ``1/1``,
        and Apply is held for it -- saying why.  Declaring the two
        devices is the remedy the documents give; the pairing is only
        made by Apply, which was held by the collision the pairing
        removes.  With both devices declared it is not held."""
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_TWO_ON_ONE_NAME)
        page.locator(_tid("migrate-rename-open-btn")).click()
        button = page.locator(_tid("migrate-rename-apply-btn"))
        why = page.locator(_tid("migrate-rename-apply-why"))
        expect(page.locator(_tid("migrate-rename-summary"))).to_contain_text("2 collisions")
        expect(button).to_be_disabled()
        expect(why).to_be_visible()
        # The warning quotes the name both ended on.  It is a name of
        # the target, not a third source port: it has no row, and the
        # section's count is the summary's.
        expect(page.locator(_tid("migrate-rename-row-1/1"))).to_have_count(0)
        expect(page.locator(_tid("migrate-rename-section-summary-physical"))).to_contain_text(
            "2 collisions"
        )
        rows = page.locator('[data-testid^="migrate-rename-row-"]').count()
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text(str(rows))
        expect(why).to_have_text(
            "Apply is held: two rows end on one target name (1/1) — "
            "give one another target, or drop it."
        )
        assert ink(why) == token_ink(page, "--badge-failed-fg")
        # Declare both devices: the next Apply asks for a pairing.
        page.locator(_tid("migrate-device-source-model-select")).select_option(
            value="profile:C9300-48P"
        )
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        expect(_plan(page)).to_have_attribute("data-state", "ready")
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_have_text(
            "Both devices are declared — Apply to pair their ports by position."
        )
        expect(button).to_be_enabled()
        expect(why).to_be_hidden()
        job = _apply_and_read(page)
        plan = job["port_mapping_plan"]
        assert plan["applied"] and plan["fused"] == {}
        assert not any("multiple source ports" in line for line in job["warnings"])
        expect(_plan(page)).not_to_have_attribute("data-state", "block")
        expect(page.locator(_tid("migrate-rename-auto-GigabitEthernet1/0/1"))).to_have_text("1/1")

    def test_a_collision_the_operator_made_holds_it_even_then(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Only the server's own renames are the pairing's to mend.  An
        entry of the operator's that takes a name another row has holds
        Apply whatever is declared, and the strip says which."""
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_TWO_ON_ONE_NAME)
        page.locator(_tid("migrate-rename-open-btn")).click()
        page.locator(_tid("migrate-device-source-model-select")).select_option(
            value="profile:C9300-48P"
        )
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        button = page.locator(_tid("migrate-rename-apply-btn"))
        expect(button).to_be_enabled()
        choose_override(page, "GigabitEthernet1/0/1", "1/7")
        expect(button).to_be_enabled()
        choose_override(page, "AppGigabitEthernet1/0/1", "1/7")
        expect(button).to_be_disabled()
        expect(page.locator(_tid("migrate-rename-apply-why"))).to_have_text(
            "Apply is held: two of your own entries end on one target name (1/7)."
        )
        expect(_plan(page)).to_have_attribute("data-state", "held")
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_have_text(
            "Both devices are declared, but two of your own entries end on one "
            "target name (1/7). Change one of them, then Apply."
        )
        assert alike(painted_background(_plan(page)), painted_token(page, TOP, "--badge-partial-bg"))
        choose_override(page, "AppGigabitEthernet1/0/1", "")
        expect(button).to_be_enabled()
        expect(_plan(page)).to_have_attribute("data-state", "ready")

    def test_apply_comes_back_held_if_something_holds_it_by_then(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Apply used to enable its button when it came back, whatever
        the summary had decided meanwhile: a collision made while it
        was out was then one click from being applied."""
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_WITH_A_LAG)
        page.locator(_tid("migrate-rename-open-btn")).click()
        held: list = []
        page.route("**/api/v1/migration/plan", lambda route: held.append(route))
        button = page.locator(_tid("migrate-rename-apply-btn"))
        page.locator(_tid("migrate-rename-override-GigabitEthernet1/0/1")).fill("1/9")
        with page.expect_request("**/api/v1/migration/plan"):
            button.click()
        # While it is out: an entry that takes the name the first has.
        page.locator(_tid("migrate-rename-override-GigabitEthernet1/0/2")).fill("1/9")
        expect(page.locator(_tid("migrate-rename-summary"))).to_contain_text("2 collisions")
        with page.expect_response("**/api/v1/migration/plan"):
            held[0].continue_()
        expect(page.locator(_tid("migrate-rename-status"))).to_contain_text("Applied")
        _settle(page)
        expect(button).to_have_text(re.compile(r"^Apply"))
        expect(button).to_be_disabled()
        expect(page.locator(_tid("migrate-rename-apply-why"))).to_contain_text(
            "two rows end on one target name (1/9)"
        )
        page.unroute("**/api/v1/migration/plan")

    def test_a_job_nobody_touched_opens_with_apply_available(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Junos to Junos, nothing declared.  The translator puts a
        tagged unit on its port.  The port keeps its own name, and that
        was counted as a collision with the translator's rename: Apply
        was disabled on opening, for a VLAN rename or anything else."""
        _translate(page, live_server_url, "juniper_junos", "juniper_junos", _JUNOS_WITH_A_UNIT)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-rename-row-ge-0/0/2"))).to_be_visible()
        expect(page.locator(_tid("migrate-rename-summary"))).not_to_contain_text("collision")
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_enabled()
        expect(page.locator(_tid("migrate-rename-apply-why"))).to_be_hidden()

    def test_an_entry_that_takes_the_name_of_an_unchanged_port_holds_it(
        self, page: Page, live_server_url: str,
    ) -> None:
        """What the count is for: a port the config uses under an
        unchanged name holds that name against an entry of the
        operator's."""
        _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(_source_note(page)).to_be_visible()
        field = page.locator(_tid("migrate-rename-override-1"))
        field.fill("2")
        expect(page.locator(_tid("migrate-rename-summary"))).to_contain_text("2 collisions")
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_disabled()
        expect(page.locator(_tid("migrate-rename-apply-why"))).to_contain_text(
            "two rows end on one target name (2)"
        )
        field.fill("")
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_enabled()

    def test_a_section_stays_as_the_operator_left_it(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Every redraw of the table put its sections back as it
        would open them itself: one the operator had opened closed
        under them, and one they had closed came back."""
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_WITH_A_LAG)
        page.locator(_tid("migrate-rename-open-btn")).click()
        ports = page.locator(_tid("migrate-rename-section-physical"))
        lags = page.locator(_tid("migrate-rename-section-lag"))
        expect(ports).to_have_attribute("open", "")
        expect(lags).not_to_have_attribute("open", "")
        page.locator(_tid("migrate-rename-section-summary-lag")).click()
        expect(lags).to_have_attribute("open", "")
        page.locator(_tid("migrate-rename-section-summary-physical")).click()
        expect(ports).not_to_have_attribute("open", "")
        # An edit in the section that is open redraws the table.
        field = page.locator(_tid("migrate-rename-override-Port-channel1"))
        field.fill("Trk9")
        field.press("Enter")
        expect(page.locator(_tid("migrate-rename-row-Port-channel1"))).to_have_class(
            re.compile(r"\bhas-override\b")
        )
        expect(lags).to_have_attribute("open", "")
        expect(ports).not_to_have_attribute("open", "")
        # Enter redrew the table; the field that was being typed in
        # has the focus still, and what was typed.
        expect(field).to_be_focused()
        expect(field).to_have_value("Trk9")

    def test_a_free_text_target_is_typed_key_by_key(
        self, page: Page, live_server_url: str,
    ) -> None:
        """The table was rebuilt on every key, the field with it: typed
        ``17``, the field held ``1`` and the focus was gone.  Every test
        used ``fill``, which sets a value in one step."""
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_TWO_ON_ONE_NAME)
        page.locator(_tid("migrate-rename-open-btn")).click()
        field = page.locator(_tid("migrate-rename-override-GigabitEthernet1/0/1"))
        field.click()
        typed_into = field.element_handle()
        field.press_sequentially("1/17")
        expect(field).to_have_value("1/17")
        expect(field).to_be_focused()
        # It is the field that was clicked, not a copy made for each
        # key: the table is not rebuilt while a name is being typed.
        assert typed_into.evaluate("el => el.isConnected")
        # Leaving the field for another row's field keeps what was
        # typed and lets the next one be typed into.
        other = page.locator(_tid("migrate-rename-override-AppGigabitEthernet1/0/1"))
        other.click()
        other.press_sequentially("1/9")
        expect(other).to_have_value("1/9")
        expect(other).to_be_focused()
        expect(field).to_have_value("1/17")
        expect(page.locator(_tid("migrate-rename-row-GigabitEthernet1/0/1"))).to_have_class(
            re.compile(r"\bhas-override\b")
        )
        # A click on another row's link straight out of a field is not
        # lost to the redraw that leaving the field causes.  (The
        # uplink was dropped by the server; the link keeps it.)  A
        # click is a press and a release on ONE element, and a hand
        # takes a moment between the two: the press is held here while
        # the page runs everything it has queued.
        link = page.locator(_tid("migrate-rename-drop-TenGigabitEthernet1/1/1"))
        box = link.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        _settle(page)
        page.mouse.up()
        expect(page.locator(_tid("migrate-rename-row-TenGigabitEthernet1/1/1"))).to_have_class(
            re.compile(r"\bhas-override\b")
        )
        expect(other).to_have_value("1/9")
        body = _apply(page)
        assert body["port_rename_map"] == {
            "GigabitEthernet1/0/1": "1/17",
            "AppGigabitEthernet1/0/1": "1/9",
            "TenGigabitEthernet1/1/1": "TenGigabitEthernet1/1/1",
        }


# ---------------------------------------------------------------------------
# A job replaced under the modal, a text that changed, a codec that changed
# ---------------------------------------------------------------------------


def _translate_behind_the_modal(page: Page, source: str, target: str, raw: str) -> None:
    """Submit the form while the modal is open.  The modal does not
    block the page; it does cover the form, so the form is filled and
    submitted without a click."""
    mp = MigratePage(page)
    mp.pick_source(source)
    mp.pick_target(target)
    mp.fill_raw(raw)
    with page.expect_response("**/api/v1/migration/plan"):
        page.locator(_tid("migrate-form")).evaluate("form => form.requestSubmit()")


def _two_member_stack(second: str, hostname: str = "s") -> str:
    """A two-member 2930M stack whose second member is *second*; long
    enough before the ``stacking`` stanza that two of them agree in
    their first 256 characters and their length."""
    return (
        "; hpStack_WC Configuration Editor; Created on release #WC.16.07.0003\n"
        f'hostname "{hostname}"\n'
        + "".join(f'snmp-server contact "line {n:02d} of filler before the stanza"\n' for n in range(8))
        + f'stacking\n   member 1 type "JL322A"\n   member 2 type "{second}"\n   exit\n'
        + "vlan 1\n   untagged 1/1-1/4,2/1-2/4\n   exit\n"
    )


class TestTheModalDescribesTheJobOnThePage:
    def test_a_translation_submitted_behind_the_open_modal_redraws_it(
        self, page: Page, live_server_url: str,
    ) -> None:
        """The modal stays open over the page.  Translate another
        config behind it and it showed the first one's device, its
        "Read from the config" lines, its strip and its table -- for a
        job that was no longer on the page."""
        mp = _open(page, live_server_url, CAPTURE_2930M)
        source = page.locator(_tid("migrate-device-source-model-select"))
        expect(source).to_have_value("fam:2930M:2930M-40G-8SR-PoEP")
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        _apply(page)
        expect(_plan(page)).to_contain_text("Ports paired by position")
        with page.expect_request("**/api/v1/migration/detect-deployment") as asked:
            _translate_behind_the_modal(page, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
        assert json.loads(asked.value.post_data)["raw_text"] == CAPTURE_2930F
        # The new config's own device, read from the new text.
        expect(source).to_have_value(SOURCE_2930F_48G)
        expect(page.locator(_tid("migrate-device-source-note-device"))).to_contain_text("JL260A")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("52 ports")
        lines = page.locator(_tid("migrate-device-source-note-read-from"))
        expect(lines).to_contain_text("JL260A")
        expect(lines).not_to_contain_text("JL323A")
        # No plan was made for this job, and the strip does not say one was.
        expect(_plan(page)).to_have_attribute("data-state", "ready")
        expect(_plan(page)).not_to_have_attribute("data-stale", "true")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_count(0)
        expect(page.locator('[data-testid^="migrate-rename-row-"][data-plan-state]')).to_have_count(0)
        expect(page.locator(_tid("migrate-rename-auto-49"))).to_have_text("(unchanged)")
        # The target is the same codec's: it is kept, and Apply pairs
        # the NEW source with it.
        body = _apply(page)
        assert body["raw_text"] == CAPTURE_2930F
        assert body["source_deployment"]["members"][0]["model"] == "2930F-48G-4SFP"
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("52 paired")
        expect(mp.output).to_contain_text("1/A1")

    def test_a_text_edited_in_place_is_another_text(
        self, page: Page, live_server_url: str,
    ) -> None:
        """A part number corrected in the pasted config: the same
        length, the same first lines.  The page took it for the text it
        already knew and went on showing the old device, with a "Read
        from the config" line the config no longer held."""
        first, second = _two_member_stack("JL322A"), _two_member_stack("JL320A")
        assert len(first) == len(second) and first[:256] == second[:256] and first != second
        asked: list[str] = []
        page.on(
            "request",
            lambda request: asked.append(request.post_data or "")
            if request.url.endswith("/detect-deployment") else None,
        )
        _open(page, live_server_url, first)
        member = page.locator(_tid("migrate-device-source-member-1-model"))
        expect(member).to_have_value("2930M-48G-PoEP")
        page.locator(_tid("migrate-rename-modal-close")).click()
        _translate_behind_the_modal(page, "aruba_aoss", "aruba_aoss", second)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(member).to_have_value("2930M-24G-PoEP")
        lines = page.locator(_tid("migrate-device-source-note-read-from"))
        expect(lines).to_contain_text("JL320A")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("72 ports")
        assert len(asked) == 2 and "JL320A" in asked[1]
        # Opening it again for the same text asks nothing.
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(member).to_have_value("2930M-24G-PoEP")
        assert len(asked) == 2

    def test_a_target_device_is_not_carried_to_another_target_codec(
        self, page: Page, live_server_url: str,
    ) -> None:
        """An Aruba profile chosen for a Cisco-to-Aruba job came back
        on the next job, to Junos: Aruba port numbers as the only
        choices, and the right Junos names flagged as not on it."""
        cisco = _CISCO_SRC
        _translate(page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", cisco)
        page.locator(_tid("migrate-rename-open-btn")).click()
        vendor = page.locator(_tid("migrate-rename-target-vendor-select"))
        model = page.locator(_tid("migrate-rename-target-model-select"))
        expect(vendor).to_have_value("aruba_aoss")
        model.select_option(value="2930F-48G")
        assert _apply(page)["target_profile"] == "aruba_aoss/2930F-48G"
        # The same job again: the pick is put back, as before.
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(model).to_have_value("2930F-48G")
        page.locator(_tid("migrate-rename-modal-close")).click()
        # Another target codec.
        _translate_behind_the_modal(page, "cisco_iosxe_cli", "juniper_junos", cisco)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(vendor).to_have_value("juniper_junos")
        expect(model).to_have_value("")
        expect(page.locator(_tid("migrate-rename-profile-notice"))).to_be_hidden()
        expect(page.locator('[data-testid^="migrate-rename-offprofile-"]')).to_have_count(0)
        body = _apply(page)
        assert body["target"] == "juniper_junos"
        assert not [key for key in body if "profile" in key or "deployment" in key]

    def test_a_target_of_another_vendor_is_said_first(
        self, page: Page, live_server_url: str,
    ) -> None:
        """The operator can still choose another vendor's device by
        hand.  Then the strip says THAT -- not "choose the source
        device as well", which would not help."""
        _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(_source_note(page)).to_be_visible()
        page.locator(_tid("migrate-device-source-model-select")).select_option(value="")
        page.locator(_tid("migrate-rename-target-vendor-select")).select_option(value="cisco_iosxe")
        page.locator(_tid("migrate-rename-target-model-select")).select_option(value="C9300-48P")
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_have_text(
            "The target device is not of the target codec\u2019s vendor, so ports are not "
            "paired by position."
        )
        expect(_plan(page)).to_have_attribute("data-state", "incomplete")

    def test_the_capacity_banner_counts_the_ports_the_config_uses(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """Same vendor, nothing renamed: the banner counted renames,
        drops and warnings, and said "access: 0 / 24" in green over a
        table of 52 ports."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, "fam:2930F:2930F-24G-4SFP")
        banner = page.locator(_tid("migrate-rename-fitcheck"))
        expect(banner).to_be_visible()
        expect(page.locator(_tid("migrate-fitcheck-kind-physical"))).to_have_text(
            "access: 48 / 24 (+24 over capacity)"
        )
        expect(page.locator(_tid("migrate-fitcheck-kind-uplink"))).to_have_text("uplink: 4 / 4")
        expect(banner).to_have_class(re.compile(r"\bfit-warn\b"))
        assert alike(painted_background(banner), painted_token(page, TOP, "--badge-partial-bg"))
        # And the rail counts the rows that are drawn.
        rows = page.locator('[data-testid^="migrate-rename-row-"]').count()
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text(str(rows))


# ---------------------------------------------------------------------------
# What Apply sends, for every field it owns
# ---------------------------------------------------------------------------

_CISCO_WITH_EVERYTHING = """hostname cat
!
username netops privilege 15 secret 0 fakeSecretForTests
!
vlan 10
 name users
!
interface GigabitEthernet1/0/1
 description desk
 switchport mode access
 switchport access vlan 10
!
snmp-server community fakeCommunity RO
snmp-server group opsgroup v3 priv
snmp-server user opsuser opsgroup v3 auth sha fakeAuthPass priv aes 128 fakePrivPass
!
end
"""


class TestWhatApplySendsForEveryFieldItOwns:
    """The request is a copy of the last one with the fields Apply owns
    taken out and put back.  Four of the ten had a test that failed
    when the taking-out was removed."""

    def test_a_source_profile_and_both_modules_are_sent_and_taken_out(
        self, page: Page, live_server_url: str,
    ) -> None:
        _translate(page, live_server_url, "cisco_iosxe_cli", "cisco_iosxe_cli", _CISCO_WITH_EVERYTHING)
        page.locator(_tid("migrate-rename-open-btn")).click()
        source = page.locator(_tid("migrate-device-source-model-select"))
        source.select_option(value="profile:C9300-24UX")
        source_module = page.locator(_tid("migrate-device-source-module-select"))
        expect(source_module).to_be_visible()
        source_module.select_option(value="NM-2Q")
        expect(page.locator(_tid("migrate-device-source-note-device"))).to_be_visible()
        model = page.locator(_tid("migrate-rename-target-model-select"))
        model.select_option(value="C9300-24UX")
        target_module = page.locator(_tid("migrate-rename-target-module-select"))
        expect(target_module).to_be_visible()
        target_module.select_option(value="NM-2Q")
        body = _apply(page)
        assert body["source_profile"] == "cisco_iosxe/C9300-24UX"
        assert body["source_module"] == "NM-2Q"
        assert body["target_profile"] == "cisco_iosxe/C9300-24UX"
        assert body["target_module"] == "NM-2Q"
        # A module is part of what the devices ARE: changing one makes
        # the mapping on screen a mapping of other devices.
        expect(_plan(page)).not_to_have_attribute("data-stale", "true")
        target_module.select_option(value="NM-8X")
        expect(_plan(page)).to_have_attribute("data-stale", "true")
        assert _apply(page)["target_module"] == "NM-8X"
        # A target profile with no modules: the module is not sent on.
        model.select_option(value="C9500-24Y4C")
        expect(target_module).to_be_hidden()
        body = _apply(page)
        assert body["target_profile"] == "cisco_iosxe/C9500-24Y4C"
        assert "target_module" not in body
        # The source cleared: neither it nor its module rides along.
        source.select_option(value="")
        expect(source_module).to_be_hidden()
        body = _apply(page)
        assert "source_profile" not in body and "source_module" not in body
        assert body["target_profile"] == "cisco_iosxe/C9500-24Y4C"

    def test_a_family_target_left_for_no_model_is_not_sent(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        assert "target_deployment" in _apply(page)
        page.locator(_tid("migrate-rename-target-model-select")).select_option(value="")
        expect(_target_note(page)).to_be_hidden()
        expect(page.locator(_tid("migrate-device-target-mode-select"))).to_be_hidden()
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_contain_text(
            "Choose the target device to pair ports by position."
        )
        body = _apply(page)
        assert "target_deployment" not in body and "source_deployment" not in body
        # The vendor select reaches the device code too.
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        page.locator(_tid("migrate-rename-target-vendor-select")).select_option(value="")
        expect(_target_note(page)).to_be_hidden()
        assert "target_deployment" not in _apply(page)

    @pytest.mark.parametrize(
        "rail,field,value,key,sent",
        [
            ("local-users", "migrate-rename-local-user-override-netops", "netadmin",
             "local_user_rename_map", {"netops": "netadmin"}),
            ("snmp", "migrate-rename-snmp-community-override", "fakeOtherCommunity",
             "snmp_community_rename_map", {"fakeCommunity": "fakeOtherCommunity"}),
            ("snmpv3", "migrate-rename-snmpv3-user-override-opsuser", "opsuser2",
             "snmpv3_user_rename_map", {"opsuser": "opsuser2"}),
        ],
    )
    def test_reset_all_takes_each_panes_map_out_of_the_next_request(
        self, page: Page, live_server_url: str,
        rail: str, field: str, value: str, key: str, sent: dict,
    ) -> None:
        _translate(page, live_server_url, "cisco_iosxe_cli", "cisco_iosxe_cli", _CISCO_WITH_EVERYTHING)
        page.locator(_tid("migrate-rename-open-btn")).click()
        page.locator(_tid(f"migrate-rename-rail-{rail}")).click()
        page.locator(_tid(field)).fill(value)
        assert _apply(page)[key] == sent
        # The pane is redrawn from the job that came back.
        expect(page.locator(_tid(field))).to_have_value(value)
        page.locator(_tid("migrate-rename-modal-reset")).click()
        assert key not in _apply(page)


# ---------------------------------------------------------------------------
# Member numbers and member lists
# ---------------------------------------------------------------------------


def _set_member(page: Page, side: str, rank: int, value: str) -> None:
    box = page.locator(_tid(f"migrate-device-{side}-member-{rank}-id"))
    box.fill(value)
    box.dispatch_event("change")


class TestMemberNumbersAndMemberLists:
    def test_what_the_number_field_holds_is_what_is_sent(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """The browser has no rule for a member number.  ``1e1`` is ten
        and was sent as one; ``2.9`` was sent as two; a field left
        blank stayed blank over a device compiled "as member 1"."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        ports = page.locator(_tid("migrate-device-target-note-ports"))
        _set_member(page, "target", 0, "1e1")
        expect(ports).to_have_text(re.compile(r"^52 ports: 10/1 . 10/A4$"))
        assert _apply(page)["target_deployment"]["members"][0]["id"] == 10
        # Not a whole number: the server says so, in its own words.
        _set_member(page, "target", 0, "2.9")
        error = page.locator(_tid("migrate-device-target-note-error"))
        expect(error).to_contain_text("Input should be a valid integer")
        expect(_plan(page)).to_have_attribute("data-state", "invalid")
        # Left blank: the server picks, and the field shows what it picked.
        _set_member(page, "target", 0, "")
        expect(ports).to_have_text(re.compile(r"^52 ports: 1/1 . 1/A4$"))
        expect(page.locator(_tid("migrate-device-target-member-0-id"))).to_have_value("1")
        expect(error).to_have_count(0)
        assert _apply(page)["target_deployment"]["members"][0]["id"] == 1

    def test_an_unstated_bay_is_named_by_its_members_number(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G)
        _set_member(page, "target", 0, "3")
        page.locator(_tid("migrate-device-target-add-member")).click()
        _set_member(page, "target", 1, "5")
        expect(page.locator(_tid("migrate-device-target-note-device"))).to_have_text(
            re.compile(r"^Target: 2 \u00d7 Aruba 2930M-48G-PoE\+ \(JL322A\) as members 3, 5 — ")
        )
        unstated = page.locator(_tid("migrate-device-target-note-unstated"))
        expect(unstated).to_have_text("Not stated, counted as empty: bay A of members 3, 5")
        # One of them stated: the other is still named by its number.
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="JL083A")
        expect(unstated).to_have_text("Not stated, counted as empty: bay A of member 5")

    def test_a_stack_set_aside_by_standing_alone_comes_back(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """Switching a stack to a mode in which a device stands alone
        kept member 1 and threw the others away without a word; so
        did choosing another model for the first member."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        page.locator(_tid("migrate-device-target-add-member")).click()
        _set_member(page, "target", 1, "4")
        ports = page.locator(_tid("migrate-device-target-note-ports"))
        expect(ports).to_have_text(re.compile(r"^104 ports: 1/1 . 4/A4$"))
        mode = page.locator(_tid("migrate-device-target-mode-select"))
        mode.focus()
        mode.select_option(value="standalone")
        expect(ports).to_have_text(re.compile(r"^52 ports: 1 . A4$"))
        expect(page.locator(_tid("migrate-device-target-member-1"))).to_have_count(0)
        expect(mode).to_be_focused()
        mode.select_option(value="stacked")
        expect(ports).to_have_text(re.compile(r"^104 ports: 1/1 . 4/A4$"))
        expect(page.locator(_tid("migrate-device-target-member-1-id"))).to_have_value("4")
        expect(page.locator(_tid("migrate-device-target-member-1-bay-A"))).to_have_value("JL083A")
        # Another model for the first member: the stack stays, and so
        # does the module the new model takes too.
        page.locator(_tid("migrate-rename-target-model-select")).select_option(
            value="fam:2930M:2930M-24G-PoEP"
        )
        expect(ports).to_have_text(re.compile(r"^80 ports: 1/1 . 4/A4$"))
        expect(page.locator(_tid("migrate-device-target-member-0-bay-A"))).to_have_value("JL083A")
        expect(page.locator(_tid("migrate-device-target-member-1-model"))).to_have_value(
            "2930M-48G-PoEP"
        )
        body = _apply(page)
        assert [
            (m["model"], m["id"]) for m in body["target_deployment"]["members"]
        ] == [("2930M-24G-PoEP", 1), ("2930M-48G-PoEP", 4)]

    def test_the_focus_stays_with_the_control_that_was_used(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """A control that redraws the row took the focus with it: it
        fell to the page, and the next Tab started from the top."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        add = page.locator(_tid("migrate-device-target-add-member"))
        add.focus()
        page.keyboard.press("Enter")
        expect(page.locator(_tid("migrate-device-target-member-1"))).to_be_attached()
        expect(add).to_be_focused()
        model = page.locator(_tid("migrate-device-target-member-1-model"))
        model.focus()
        model.select_option(value="2930M-24G")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("76 ports")
        expect(model).to_be_focused()
        # Each control says which device and which member it is of.
        expect(model).to_have_attribute("aria-label", "Target device, member 2: model")
        expect(page.locator(_tid("migrate-device-target-member-1-bay-A"))).to_have_attribute(
            "aria-label", "Target device, member 2: module in bay A"
        )
        expect(page.locator(_tid("migrate-rename-target-model-select"))).to_have_attribute(
            "aria-label", "Target device model"
        )
        remove = page.locator(_tid("migrate-device-target-member-1-remove"))
        expect(remove).to_have_attribute("aria-label", "Remove Target device, member 2")
        remove.focus()
        page.keyboard.press("Enter")
        expect(page.locator(_tid("migrate-device-target-member-1"))).to_have_count(0)
        expect(add).to_be_focused()


# ---------------------------------------------------------------------------
# A server that does not answer, or answers late
# ---------------------------------------------------------------------------


def _settle(page: Page) -> None:
    """Let the page finish what an answer started: two frames and a turn
    of the event loop."""
    page.evaluate(
        """() => new Promise((done) => requestAnimationFrame(
            () => requestAnimationFrame(() => setTimeout(done, 0))))"""
    )


class TestAServerThatDoesNotAnswer:
    def test_a_detection_that_failed_is_said_and_asked_again(
        self, page: Page, live_server_url: str,
    ) -> None:
        """It failed in silence, and was never asked again for that
        text: the source stayed "(not declared)" with no word why."""
        page.route("**/api/v1/migration/detect-deployment", lambda route: route.abort())
        _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
        page.locator(_tid("migrate-rename-open-btn")).click()
        said = page.locator(_tid("migrate-device-source-note-detect-failed"))
        expect(said).to_be_visible()
        expect(said).to_have_text(
            re.compile(r"^Could not read the device from the config \(.+\) — declare it yourself")
        )
        expect(_source_note(page)).to_have_class(re.compile(r"\bnotice-warn\b"))
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value("")
        page.unroute("**/api/v1/migration/detect-deployment")
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value(
            SOURCE_2930F_48G
        )
        expect(said).to_have_count(0)

    def test_a_preview_that_did_not_arrive_is_not_called_invalid(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """A preview that could not be fetched said "not valid yet",
        and Apply left both devices out and reported success.  It is
        no verdict: the note says it could not be checked, and Apply
        sends the devices for the server to compile itself."""
        expect(_source_note(page)).to_be_visible()
        page.route(
            "**/api/v1/migration/inventory",
            lambda route: route.fulfill(status=502, body="bad gateway"),
        )
        _pick_target(page, TARGET_2930M_48G)
        note = page.locator(_tid("migrate-device-target-note-unchecked"))
        expect(note).to_be_visible()
        expect(note).to_have_text(
            "Target device could not be checked here: The server answered 502 Bad Gateway. "
            "Apply sends it as declared, and the server decides."
        )
        expect(_target_note(page)).to_have_attribute("data-state", "unchecked")
        expect(_target_note(page)).not_to_have_class(re.compile(r"\bnotice-block\b"))
        assert alike(painted_background(_target_note(page)), painted_token(page, TOP, "--badge-partial-bg"))
        expect(_plan(page)).to_have_attribute("data-state", "unchecked")
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_have_text(
            "A device could not be checked here — see the note above. "
            "Apply sends both devices, and the server decides."
        )
        body = _apply(page)
        assert "source_deployment" in body and "target_deployment" in body
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("48 paired")
        expect(page.locator(_tid("migrate-rename-auto-1"))).to_have_text("1/1")
        page.unroute("**/api/v1/migration/inventory")

    def test_a_preview_that_never_answers_is_given_up_on(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """Apply waits for a preview in flight.  One that never
        answered held it for ever, and fired it minutes later."""
        expect(_source_note(page)).to_be_visible()
        page.clock.install()
        held: list = []
        page.route("**/api/v1/migration/inventory", lambda route: held.append(route))
        page.locator(_tid("migrate-rename-target-model-select")).select_option(
            value=TARGET_2930M_48G
        )
        # While it waits, the screen says it is waiting.
        expect(page.locator(_tid("migrate-device-target-note-checking"))).to_have_text(
            "Target device: checking …"
        )
        expect(_plan(page)).to_have_attribute("data-state", "checking")
        page.clock.fast_forward(21_000)
        expect(page.locator(_tid("migrate-device-target-note-unchecked"))).to_contain_text(
            "No answer from the server in 20 seconds."
        )
        expect(_plan(page)).to_have_attribute("data-state", "unchecked")
        assert len(held) == 1
        page.unroute("**/api/v1/migration/inventory")

    def test_model_families_that_did_not_load_are_said_and_asked_for_again(
        self, page: Page, live_server_url: str,
    ) -> None:
        """Without them no family is offered.  The note said "The
        config states: JL260A [use it]" and the button did nothing."""
        page.route("**/api/v1/migration/model-families", lambda route: route.abort())
        _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-device-source-note-config-says"))).to_have_text(
            "The config states: JL260A"
        )
        missing = page.locator(_tid("migrate-device-source-note-families-missing"))
        expect(missing).to_be_visible()
        expect(missing).to_contain_text("The model families could not be loaded")
        expect(page.locator(_tid("migrate-device-source-use-detected"))).to_have_count(0)
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value("")
        # Opening the modal again asks for them again, and they reach
        # both lists.
        page.unroute("**/api/v1/migration/model-families")
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value(
            SOURCE_2930F_48G
        )
        expect(missing).to_have_count(0)
        _pick_target(page, TARGET_2930M_48G)

    def test_an_older_preview_does_not_replace_a_newer_one(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        expect(_source_note(page)).to_be_visible()
        held: list = []

        def hold_the_first(route) -> None:
            if held:
                route.continue_()
            else:
                held.append(route)

        page.route("**/api/v1/migration/inventory", hold_the_first)
        page.locator(_tid("migrate-rename-target-model-select")).select_option(
            value=TARGET_2930M_48G
        )
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="JL083A")
        ports = page.locator(_tid("migrate-device-target-note-ports"))
        expect(ports).to_contain_text("52 ports")
        # The first request -- the device with its bay unstated, 48
        # ports -- answers now.
        with page.expect_response("**/api/v1/migration/inventory"):
            held[0].continue_()
        _settle(page)
        expect(ports).to_contain_text("52 ports")
        expect(page.locator(_tid("migrate-device-target-note-unstated"))).to_have_count(0)
        page.unroute("**/api/v1/migration/inventory")

    def test_a_preview_for_a_job_that_is_gone_is_not_drawn(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """A source preview in flight, another config translated, the
        old answer arrives: the note described the old device under a
        select that said "(not declared)"."""
        expect(_source_note(page)).to_be_visible()
        held: list = []
        page.route("**/api/v1/migration/inventory", lambda route: held.append(route))
        page.locator(_tid("migrate-device-source-model-select")).select_option(
            value="fam:2930F:2930F-24G-4SFP"
        )
        expect(page.locator(_tid("migrate-device-source-note-checking"))).to_be_visible()
        # A config that states no device, so nothing is declared for it.
        _translate_behind_the_modal(page, "aruba_aoss", "aruba_aoss", _NO_DEVICE_STATED)
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value("")
        assert len(held) == 1
        with page.expect_response("**/api/v1/migration/inventory"):
            held[0].continue_()
        _settle(page)
        expect(page.locator(_tid("migrate-device-source-note-device"))).to_have_count(0)
        expect(page.locator(_tid("migrate-device-source-note-checking"))).to_have_count(0)
        page.unroute("**/api/v1/migration/inventory")

    def test_apply_stays_held_while_it_is_out_and_a_late_answer_is_dropped(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """The summary re-enabled the button on every redraw, so a row
        edit while Apply was out allowed a second one; and an answer
        that came back after a newer translation replaced its output."""
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        held: list = []

        def hold_the_first(route) -> None:
            if held:
                route.continue_()
            else:
                held.append(route)

        page.route("**/api/v1/migration/plan", hold_the_first)
        button = page.locator(_tid("migrate-rename-apply-btn"))
        with page.expect_request("**/api/v1/migration/plan"):
            button.click()
        expect(button).to_have_text("Applying…")
        expect(button).to_be_disabled()
        # A row edit redraws the summary.  The button stays held.
        choose_override(page, "7", "__DROP__")
        expect(page.locator(_tid("migrate-rename-row-7"))).to_have_class(re.compile(r"\bhas-drop\b"))
        expect(button).to_be_disabled()
        # And Apply asked for by any other road does not go out twice.
        sent: list[str] = []
        page.on(
            "request",
            lambda request: sent.append(request.url)
            if request.url.endswith("/api/v1/migration/plan") else None,
        )
        page.evaluate("renameModalApply()")
        _settle(page)
        assert sent == []
        # A newer translation, behind the modal, while Apply is out.
        _translate_behind_the_modal(page, "aruba_aoss", "aruba_aoss", _NO_DEVICE_STATED)
        expect(aoss_2930f.output).to_contain_text("printer")
        with page.expect_response("**/api/v1/migration/plan"):
            held[0].continue_()
        _settle(page)
        # The old answer was for a job that is no longer on the page.
        expect(aoss_2930f.output).to_contain_text("printer")
        expect(aoss_2930f.output).not_to_contain_text("1/A1")
        expect(page.locator(_tid("migrate-rename-status"))).not_to_contain_text("Applied")
        expect(button).to_have_text(re.compile(r"^Apply"))
        expect(button).to_be_enabled()
        page.unroute("**/api/v1/migration/plan")


#: A VLAN and a port, and nothing that says what the device is.
_NO_DEVICE_STATED = (
    'hostname "plain"\n'
    "interface 7\n"
    '   name "printer"\n'
    "   exit\n"
    'vlan 10\n   name "users"\n   untagged 7\n   exit\n'
)


# ---------------------------------------------------------------------------
# What the operator declared, and what the config said
# ---------------------------------------------------------------------------


class TestWhatWasReadAndWhatWasChosen:
    def test_an_edited_source_no_longer_says_it_was_read_from_the_config(
        self, page: Page, live_server_url: str,
    ) -> None:
        requests: list[str] = []
        page.on(
            "request",
            lambda request: requests.append(request.url)
            if request.url.endswith("/detect-deployment") else None,
        )
        _open(page, live_server_url, CAPTURE_2930M)
        read = page.locator(_tid("migrate-device-source-note-read-from"))
        expect(read).to_be_visible()
        expect(page.locator(_tid("migrate-device-source-note-not-checked"))).to_have_count(0)
        page.locator(_tid("migrate-device-source-member-0-bay-A")).select_option(value="__empty__")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("48 ports")
        expect(read).to_have_count(0)
        # Edited by hand, it has not been checked against the config:
        # saying nothing would read as a check that passed.
        expect(page.locator(_tid("migrate-device-source-note-not-checked"))).to_have_text(
            "Not checked against the port names the config uses — Apply lists any the "
            "device does not have"
        )
        expect(page.locator(_tid("migrate-device-source-note-config-says"))).to_have_text(
            "The config states: JL323A"
        )
        # Taking the config's word again puts the focus on the device.
        page.locator(_tid("migrate-device-source-use-detected")).click()
        expect(read).to_be_visible()
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("52 ports")
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_be_focused()
        # "(not declared)" is a choice.  It sticks, and the config is
        # not asked again for a text it has answered for.
        page.locator(_tid("migrate-device-source-model-select")).select_option(value="")
        page.locator(_tid("migrate-rename-modal-close")).click()
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-device-source-note-config-says"))).to_be_visible()
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_have_value("")
        assert len(requests) == 1

    def test_a_vendor_with_no_device_to_choose_is_not_told_to_choose_one(
        self, page: Page, live_server_url: str,
    ) -> None:
        _translate(page, live_server_url, "vyos", "aruba_aoss", _VYOS)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-device-source-model-select"))).to_be_disabled()
        expect(page.locator(_tid("migrate-device-source-note-no-models"))).to_have_text(
            "No device model is known for this source vendor yet; its ports are "
            "translated by the shape of their names"
        )
        expect(_source_note(page)).not_to_contain_text("declare the device yourself")
        _pick_target(page, TARGET_2930M_48G)
        expect(page.locator(_tid("migrate-rename-plan-hint"))).to_have_text(
            "No device model is known for the source vendor yet, so ports cannot be "
            "paired by position. The target\u2019s port list only fills the choices below."
        )
        expect(_plan(page)).to_have_attribute("data-state", "incomplete")
        # By name both ports end on one name, and no pairing is on
        # offer to mend it: Apply is held, and says why.
        expect(page.locator(_tid("migrate-rename-apply-btn"))).to_be_disabled()
        expect(page.locator(_tid("migrate-rename-apply-why"))).to_have_text(
            re.compile(r"^Apply is held: two rows end on one target name \(.+\) — ")
        )


_VYOS = """interfaces {
    ethernet eth0 {
        address 192.0.2.1/24
    }
    ethernet eth1 {
        address 198.51.100.1/24
    }
}
system {
    host-name v1
}
"""


# ---------------------------------------------------------------------------
# Every state a row can be in
# ---------------------------------------------------------------------------

_CISCO_WITH_A_MANAGEMENT_PORT = """hostname cat
!
interface GigabitEthernet0/0
 description oob
 ip address 192.0.2.10 255.255.255.0
!
interface GigabitEthernet1/0/1
 description desk
 switchport mode access
!
end
"""

#: A whole OPNsense config from the committed captures.
_OPNSENSE = (
    REPO_ROOT / "tests/fixtures/real/opnsense/opnsense_core_default.xml"
).read_text(encoding="utf-8")


class TestEveryRowStateIsDrawn:
    """States the change draws that no browser test reached.  With the
    code for any of them inverted or removed, the tier passed."""

    def test_names_that_are_not_ports_of_the_source_and_names_displaced(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """A 28-port model declared for a config that uses 52 names.
        Twenty of the others are left as they are; four would have
        taken the names the four uplinks were paired onto, and were
        dropped instead."""
        expect(_source_note(page)).to_be_visible()
        page.locator(_tid("migrate-device-source-model-select")).select_option(
            value="fam:2930F:2930F-24G-4SFP"
        )
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("28 ports")
        _pick_target(page, SOURCE_2930F_48G)
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("28 paired")
        off = page.locator(_tid("migrate-rename-plan-off-inventory"))
        expect(off).to_be_visible()
        expect(off).to_have_text("24 not on the source device")
        displaced = page.locator(_tid("migrate-rename-plan-displaced"))
        expect(displaced).to_be_visible()
        expect(displaced).to_have_text("4 displaced")
        row = page.locator(_tid("migrate-rename-row-29"))
        expect(row).to_have_attribute("data-plan-state", "off-inventory")
        expect(page.locator(_tid("migrate-rename-plan-state-29"))).to_have_text(
            "not a port of the declared source device — left as it is"
        )
        expect(page.locator(_tid("migrate-rename-row-49"))).to_have_attribute(
            "data-plan-state", "displaced"
        )
        expect(page.locator(_tid("migrate-rename-plan-state-49"))).to_have_text(
            "dropped — by name it would have taken a name another interface holds"
        )
        # The uplink of the declared device took the name.
        expect(page.locator(_tid("migrate-rename-auto-25"))).to_have_text("49")
        expect(page.locator(_tid("migrate-rename-why-25"))).to_have_text("uplink 1")
        # The rail counts the rows that are drawn, whatever their state.
        rows = page.locator('[data-testid^="migrate-rename-row-"]').count()
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text(str(rows))

    def test_a_unit_follows_its_port(self, page: Page, live_server_url: str) -> None:
        """Between two configs of one codec a unit goes where its port
        goes.  Before the pairing could be asked for with a collision
        on screen, this state could not be reached from the modal."""
        _translate(page, live_server_url, "juniper_junos", "juniper_junos", _JUNOS_WITH_A_UNIT)
        _declare(page, "EX4300-48T", "EX4300-48T")
        job = _apply_and_read(page)
        assert job["port_mapping_plan"]["sub_interfaces"] == {"ge-0/0/1.54": "ge-0/0/1.54"}
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("2 paired")
        row = page.locator(_tid("migrate-rename-row-ge-0/0/1.54"))
        expect(row).to_have_attribute("data-plan-state", "follows")
        expect(page.locator(_tid("migrate-rename-why-ge-0/0/1.54"))).to_have_text("follows its port")

    def test_a_management_port_kept_by_name_asks_for_a_decision(
        self, page: Page, live_server_url: str,
    ) -> None:
        _translate(
            page, live_server_url, "cisco_iosxe_cli", "aruba_aoss", _CISCO_WITH_A_MANAGEMENT_PORT,
        )
        page.locator(_tid("migrate-rename-open-btn")).click()
        page.locator(_tid("migrate-device-source-model-select")).select_option(
            value="profile:C9300-48P"
        )
        _pick_target(page, TARGET_2930M_48G)
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "warn")
        row = page.locator(_tid("migrate-rename-row-GigabitEthernet0/0"))
        expect(row).to_be_visible()
        expect(row).to_have_attribute("data-plan-state", "unplaced")
        expect(row).to_have_class(re.compile(r"\bneeds-decision\b"))
        expect(page.locator(_tid("migrate-rename-plan-state-GigabitEthernet0/0"))).to_have_text(
            "kept as 1 — confirm the target has a management port"
        )
        expect(page.locator(_tid("migrate-rename-why-GigabitEthernet0/0"))).to_have_text("mgmt 1")
        # Kept is not "with no place — dropped": it is not counted as one.
        expect(page.locator(_tid("migrate-rename-plan-unplaced"))).to_have_count(0)
        expect(page.locator(_tid("migrate-rename-plan-pending"))).to_have_text(
            "1 needs your decision"
        )

    def test_ports_the_config_does_not_use_get_no_row(
        self, page: Page, live_server_url: str,
    ) -> None:
        _open(page, live_server_url, _SMALL_FABRIC)
        _pick_a_two_member_stack(page)
        _apply(page)
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_text("2 paired")
        expect(page.locator(_tid("migrate-rename-row-1/1"))).to_be_visible()
        expect(page.locator(_tid("migrate-rename-row-1/2"))).to_have_count(0)
        expect(page.locator(_tid("migrate-rename-row-2/52"))).to_have_count(0)
        expect(page.locator('[data-testid^="migrate-rename-row-"][data-plan-state]')).to_have_count(2)

    def test_two_ports_on_one_target_port_block_and_draw_no_row_for_the_target(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """An entry typed before a target was chosen puts port 50
        where port 49 is paired.  The strip blocks and says which.  A
        warning that quotes the TARGET port used to become a table row
        for it, reading "(no mapping -- needs override)"."""
        expect(_source_note(page)).to_be_visible()
        page.locator(_tid("migrate-rename-override-50")).fill("1/a1")
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        # The entry is not a port of the target, and the list says so.
        texts = [text for _value, text in override_options(page, "50")]
        assert "(custom: 1/a1 — not a port of the target)" in texts
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "block")
        fused = page.locator(_tid("migrate-rename-plan-fused"))
        expect(fused).to_be_visible()
        expect(fused).to_have_text("1 target port given more than one source")
        assert ink(fused) == token_ink(page, "--badge-failed-fg")
        expect(page.locator(_tid("migrate-rename-plan-report"))).to_contain_text("1/A1 <- 49, 50")
        expect(page.locator(_tid("migrate-rename-row-1/A1"))).to_have_count(0)
        rows = page.locator('[data-testid^="migrate-rename-row-"]').count()
        expect(page.locator(_tid("migrate-rename-rail-ports-count"))).to_have_text(str(rows))
        expect(aoss_2930f.status_summary).to_contain_text("partial")

    def test_a_plan_that_was_not_applied_is_not_drawn_as_one(
        self, page: Page, live_server_url: str,
    ) -> None:
        """A generic profile lists no ports, so nothing can be paired
        by position.  The strip says so, in red, once -- and the
        status line beside it does not say the opposite."""
        _translate(page, live_server_url, "opnsense", "opnsense", _OPNSENSE)
        _declare(page, "Generic", "Generic")
        expect(_plan(page)).to_have_attribute("data-state", "ready")
        job = _apply_and_read(page)
        assert job["port_mapping_plan"]["applied"] is False
        expect(_plan(page)).to_have_attribute("data-state", "unapplied")
        said = page.locator(_tid("migrate-rename-plan-unapplied"))
        expect(said).to_have_text(re.compile(r"^Ports were NOT paired by position: "))
        assert said.inner_text().count("translated by") == 1
        assert alike(painted_background(_plan(page)), painted_token(page, TOP, "--badge-failed-bg"))
        expect(page.locator(_tid("migrate-rename-plan-paired"))).to_have_count(0)
        expect(page.locator(_tid("migrate-rename-status"))).to_have_text(
            "Applied. Ports were NOT paired by position — see above."
        )

    def test_a_member_beside_its_namesake_crosses_and_an_unused_member_is_not_named(
        self, page: Page, live_server_url: str,
    ) -> None:
        """The fabric's ports are of members 1 and 3.  Declared as
        members 2 and 3 onto a stack numbered 1 and 2: member 3 lands
        on member 2, a number the SOURCE also declares -- a crossing,
        though only one of the two numbers is on the other side.
        Member 2 has no port the config uses, and is not named."""
        _open_fabric(page, live_server_url, second=3)
        _set_member(page, "source", 0, "2")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_have_text(
            re.compile(r"^104 ports: 2/1 . 3/52$")
        )
        _pick_a_two_member_stack(page)
        job = _apply_and_read(page)
        lines = " ".join(job["port_mapping_plan"]["warnings"])
        assert "source member 3 with target member 2" in lines
        assert "source member 2 with target member 1" not in lines
        expect(page.locator(_tid("migrate-rename-plan-crossed"))).to_have_text(
            "crossed: member 3 → member 2"
        )
        expect(page.locator(_tid("migrate-rename-plan-members"))).to_have_count(0)


# ---------------------------------------------------------------------------
# Strings an operator can author, and names of any length
# ---------------------------------------------------------------------------


class TestStringsThatAreMarkupAreDrawnAsText:
    """The static guard is a search of two files for the ways markup
    gets written, by name.  This holds the same thing from the other
    side: a model family in which every string a person can author is
    markup is chosen, drawn, compiled and paired, and nothing in the
    page came of it but text."""

    def test_a_family_whose_every_string_is_markup(
        self, page: Page, live_server_url: str,
    ) -> None:
        page.add_init_script(f"window.{MARKUP_RAN} = [];")
        _translate(page, live_server_url, "aruba_aoss", "aruba_aoss", CAPTURE_2930F)
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(_source_note(page)).to_be_visible()
        _pick_target(page, MARKUP_FAMILY_MODEL_OPTION)
        note = _target_note(page)
        # Its panel is graded `inferred`: the note says so, in amber.
        expect(page.locator(_tid("migrate-device-target-note-evidence"))).to_have_text(
            "Port names NOT verified for this device"
        )
        expect(note).to_have_attribute("data-evidence", "inferred")
        assert alike(painted_background(note), painted_token(page, TOP, "--badge-partial-bg"))
        expect(page.locator(_tid("migrate-device-target-note-device"))).to_contain_text(
            "<img src=x onerror="
        )
        page.locator(_tid("migrate-device-target-note-caveats-summary")).click()
        expect(page.locator(_tid("migrate-device-target-note-caveats"))).to_contain_text(
            "</li></ul></details><script>"
        )
        # Its module, its fabric mode, a second member, and a pairing.
        page.locator(_tid("migrate-device-target-member-0-bay-A")).select_option(value="MARKUPMOD")
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("10 ports")
        # With the bay stated, the grade alone keeps the note amber.
        expect(page.locator(_tid("migrate-device-target-note-unstated"))).to_have_count(0)
        expect(note).to_have_class(re.compile(r"\bnotice-warn\b"))
        assert alike(painted_background(note), painted_token(page, TOP, "--badge-partial-bg"))
        page.locator(_tid("migrate-device-target-mode-select")).select_option(value="vsf")
        page.locator(_tid("migrate-device-target-add-member")).click()
        expect(page.locator(_tid("migrate-device-target-note-ports"))).to_contain_text("20 ports")
        _apply(page)
        expect(_plan(page)).to_contain_text("Ports paired by position")
        page.locator(_tid("migrate-rename-plan-report-summary")).click()
        override_options(page, "1")
        made = page.evaluate(
            """() => ({
                ran: window.__markup_ran,
                elements: document.querySelectorAll(
                    '#mig-rename-modal img, #mig-rename-modal svg, #mig-rename-modal script, '
                    + '#mig-rename-modal a, #mig-rename-modal iframe').length,
                handlers: [...document.querySelectorAll('#mig-rename-modal *')].filter(
                    (el) => [...el.attributes].some((a) => a.name.startsWith('on')
                        && a.name !== 'onclick')).length,
            })"""
        )
        assert made == {"ran": [], "elements": 0, "handlers": 0}

    def test_a_port_name_that_is_markup(self, page: Page, live_server_url: str) -> None:
        """RouterOS lets an operator name a port anything.  The name
        is the row's test id, its first cell, a key of the override
        map and part of the preview."""
        page.add_init_script(f"window.{MARKUP_RAN} = [];")
        name = "<img/src=x/onerror=window.__markup_ran.push(99)>"
        config = _ROUTEROS_NAMED.replace("name=core-a", f'name="{name}"').replace(
            "interface=core-a", f'interface="{name}"'
        )
        assert config.count(name) == 2
        _translate(page, live_server_url, "mikrotik_routeros", "mikrotik_routeros", config)
        _declare(page, "CRS310-8G+2S+", "CCR2004-1G-12S+2XS")
        _apply(page)
        expect(page.locator(_tid("migrate-rename-source-" + name))).to_have_text(name)
        expect(page.locator(_tid("migrate-rename-flag-" + name + "-0"))).to_have_text(
            "ether2 in the device model"
        )
        made = page.evaluate(
            """() => ({
                ran: window.__markup_ran,
                images: document.querySelectorAll('#mig-rename-modal img').length,
            })"""
        )
        assert made == {"ran": [], "images": 0}

    def test_a_name_of_any_length_does_not_widen_the_table(
        self, page: Page, live_server_url: str,
    ) -> None:
        """One unbroken name of thousands of characters made the table
        that wide, and put every override control out of reach."""
        name = "x" * 3000
        _translate(
            page, live_server_url, "mikrotik_routeros", "mikrotik_routeros",
            _ROUTEROS_NAMED.replace("core-a", name),
        )
        page.locator(_tid("migrate-rename-open-btn")).click()
        expect(page.locator(_tid("migrate-rename-row-" + name))).to_be_visible()
        widths = page.evaluate(
            """() => {
                const pane = document.getElementById('mig-rename-table-pane');
                return [pane.scrollWidth, pane.clientWidth];
            }"""
        )
        assert widths[0] <= widths[1] + 1, widths
        field = page.locator(_tid("migrate-rename-override-" + name))
        box = field.bounding_box()
        pane = page.locator(_tid("migrate-rename-table-pane")).bounding_box()
        assert pane["x"] <= box["x"] and box["x"] + box["width"] <= pane["x"] + pane["width"] + 1


# ---------------------------------------------------------------------------
# An Apply that did not happen: why stays in the modal
# ---------------------------------------------------------------------------

_LONG_ANSWER = "a long answer from the server " * 40

#: Show a toast tall enough to lie over the modal's footer whatever the
#: fonts, and say for each button whether the toast is over its middle
#: and what a click there would land on.
_UNDER_A_TOAST = """([words, ids]) => {
    showToast(words, 'error');
    const toast = document.getElementById('_toast').getBoundingClientRect();
    return ids.map((id) => {
        const box = document.querySelector('[data-testid="' + id + '"]').getBoundingClientRect();
        const x = box.left + box.width / 2, y = box.top + box.height / 2;
        const hit = document.elementFromPoint(x, y);
        return {
            covered: toast.left <= x && x <= toast.right && toast.top <= y && y <= toast.bottom,
            hit: hit ? hit.getAttribute('data-testid') || hit.id || hit.tagName : null,
        };
    });
}"""

_REFUSED = "Not applied — the server refused the request: "


def _refuse(page: Page) -> None:
    """Send a pairing the server refuses: a member number the stack
    does not have."""
    _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
    member = page.locator(_tid("migrate-device-target-member-0-id"))
    member.fill("11")
    member.dispatch_event("change")
    expect(page.locator(_tid("migrate-device-target-note-error"))).to_be_visible()
    with page.expect_response("**/api/v1/migration/plan") as answer:
        page.locator(_tid("migrate-rename-apply-btn")).click()
    assert answer.value.status == 422


class TestWhyAnApplyDidNotHappenStays:
    """The server's reason for refusing an Apply was said in a toast
    and nowhere else: gone in four seconds, and for those four seconds
    lying over the modal's Cancel and Apply at a laptop's height, where
    it took their clicks -- its tint lets the buttons show through, so
    they looked pressable.  The reason is now the footer's status line,
    and a toast takes no click."""

    @pytest.mark.parametrize("width,height", [(1280, 720), (1024, 600)])
    def test_a_toast_takes_no_click_meant_for_what_is_under_it(
        self, page: Page, live_server_url: str, width: int, height: int,
    ) -> None:
        page.set_viewport_size({"width": width, "height": height})
        _open(page, live_server_url, CAPTURE_2930F)
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        buttons = ["migrate-rename-apply-btn", "migrate-rename-cancel-btn"]
        expect(page.locator(_tid(buttons[0]))).to_be_enabled()
        under = page.evaluate(_UNDER_A_TOAST, [_LONG_ANSWER, buttons])
        # The toast IS over both buttons, or what follows proves nothing.
        assert [each["covered"] for each in under] == [True, True], under
        assert [each["hit"] for each in under] == buttons, under
        # And a click lands where it was aimed while the toast shows: a
        # click that is intercepted is retried until the time allowed
        # runs out, which is shorter than the toast lasts.
        with (
            page.expect_request("**/api/v1/migration/plan"),
            page.expect_response("**/api/v1/migration/plan"),
        ):
            page.locator(_tid(buttons[0])).click(timeout=2_000)
        expect(page.locator(_tid("migrate-rename-status"))).to_contain_text("Applied")
        page.evaluate("(words) => showToast(words, 'error')", _LONG_ANSWER)
        expect(page.locator(_tid("toast"))).to_be_visible()
        page.locator(_tid(buttons[1])).click(timeout=2_000)
        expect(page.locator(_tid("migrate-rename-modal"))).to_be_hidden()

    def test_the_reason_for_a_refusal_stays_in_the_footer(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        status = page.locator(_tid("migrate-rename-status"))
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        width = _box(page, "#mig-rename-apply-btn")["width"]
        before = aoss_2930f.output.inner_text()
        _refuse(page)
        expect(status).to_have_text(
            re.compile("^" + re.escape(_REFUSED) + ".*member id 11 is outside 1-10")
        )
        expect(status).to_have_attribute("data-state", "failed")
        assert alike(ink(status), token_ink(page, "--badge-failed-fg"))
        # The toast goes.  The reason does not.
        expect(page.locator(_tid("toast"))).to_be_hidden(timeout=8_000)
        expect(status).to_contain_text("member id 11 is outside 1-10")
        expect(status).to_be_visible()
        assert aoss_2930f.output.inner_text() == before
        # A long reason wraps beside the buttons: they keep their size
        # and stay in the footer, the footer in the modal, and the table
        # keeps its floor.
        button = _box(page, "#mig-rename-apply-btn")
        footer = _box(page, "#mig-rename-modal-footer")
        modal = _box(page, "#mig-rename-modal")
        assert button["width"] == pytest.approx(width, abs=0.5)
        assert footer["top"] <= button["top"] and button["bottom"] <= footer["bottom"]
        assert footer["bottom"] <= modal["bottom"] + 0.5
        rem = page.evaluate("parseFloat(getComputedStyle(document.documentElement).fontSize)")
        assert _box(page, "#mig-rename-modal-body")["height"] >= 13 * rem - 1
        # Put right and applied, the footer reports -- and not in the
        # ink of the error that was there.
        member = page.locator(_tid("migrate-device-target-member-0-id"))
        member.fill("2")
        member.dispatch_event("change")
        expect(page.locator(_tid("migrate-device-target-note-error"))).to_have_count(0)
        _apply(page)
        expect(status).to_have_text("Applied. Rendered output refreshed.")
        assert status.get_attribute("data-state") is None
        assert alike(ink(status), token_ink(page, "--text-faint"))

    def test_a_report_after_a_refusal_is_not_drawn_as_the_error(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """The footer's line has more than one writer.  Each clears
        what marked the line before it."""
        status = page.locator(_tid("migrate-rename-status"))
        _refuse(page)
        expect(status).to_have_attribute("data-state", "failed")
        page.locator(_tid("migrate-rename-modal-reset")).click()
        expect(status).to_have_text("All overrides cleared.")
        assert status.get_attribute("data-state") is None
        assert alike(ink(status), token_ink(page, "--text-faint"))

    def test_an_apply_the_server_never_answered_says_so_and_stays(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        status = page.locator(_tid("migrate-rename-status"))
        apply_button = page.locator(_tid("migrate-rename-apply-btn"))
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        expect(apply_button).to_be_enabled()
        before = aoss_2930f.output.inner_text()
        page.route("**/api/v1/migration/plan", lambda route: route.abort())
        apply_button.click()
        expect(status).to_have_text(
            re.compile(r"^Not applied — the server did not answer \(.+\)\.$")
        )
        expect(status).to_have_attribute("data-state", "failed")
        assert alike(ink(status), token_ink(page, "--badge-failed-fg"))
        expect(page.locator(_tid("toast"))).to_contain_text("Network error")
        # Nothing was applied, and Apply can be pressed again.
        assert aoss_2930f.output.inner_text() == before
        expect(apply_button).to_be_enabled()
        expect(apply_button).to_have_text("Apply & regenerate")
        page.unroute("**/api/v1/migration/plan")
        _apply(page)
        expect(status).to_have_text("Applied. Rendered output refreshed.")
        assert status.get_attribute("data-state") is None
    @pytest.mark.parametrize(
        "reason", ["x" * 3000, "a reason " * 600], ids=["one-word", "many-lines"],
    )
    def test_a_reason_of_any_length_leaves_the_buttons_and_the_table(
        self, aoss_2930f: MigratePage, page: Page, reason: str,
    ) -> None:
        """A refusal can quote what it refuses, at any length.  The
        line breaks anywhere and scrolls in a few lines of its own."""
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        width = _box(page, "#mig-rename-apply-btn")["width"]
        # Written on the element: this is about how the line is drawn.
        page.evaluate(
            """(reason) => {
                const line = document.getElementById('mig-rename-status');
                line.textContent = reason;
                line.setAttribute('data-state', 'failed');
            }""",
            reason,
        )
        rem = page.evaluate("parseFloat(getComputedStyle(document.documentElement).fontSize)")
        button = _box(page, "#mig-rename-apply-btn")
        cancel = _box(page, _tid("migrate-rename-cancel-btn"))
        footer = _box(page, "#mig-rename-modal-footer")
        modal = _box(page, "#mig-rename-modal")
        assert button["width"] == pytest.approx(width, abs=0.5)
        for each in (button, cancel):
            assert modal["left"] <= each["left"] and each["right"] <= modal["right"], (each, modal)
            assert footer["top"] <= each["top"] and each["bottom"] <= footer["bottom"]
        assert footer["height"] <= 6 * rem, footer
        # It breaks where it has to; it is not read by scrolling sideways.
        wide = page.evaluate(
            """() => {
                const line = document.getElementById('mig-rename-status');
                return [line.scrollWidth, line.clientWidth];
            }"""
        )
        assert wide[0] <= wide[1] + 1, wide
        assert footer["bottom"] <= modal["bottom"] + 0.5
        assert _box(page, "#mig-rename-modal-body")["height"] >= 13 * rem - 1
        # Apply is still under the mouse.
        hit = page.evaluate(
            """() => {
                const box = document.getElementById('mig-rename-apply-btn').getBoundingClientRect();
                const at = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
                return at && at.id;
            }"""
        )
        assert hit == "mig-rename-apply-btn"


# ---------------------------------------------------------------------------
# Before Apply: the rows are in the source device's port order
# ---------------------------------------------------------------------------

_PORT_ROWS = """() => Array.from(
    document.querySelectorAll('[data-testid^="migrate-rename-source-"]')
).map((cell) => cell.textContent.trim()).filter((name) => /^[0-9]+$/.test(name))"""


def _port_rows(page: Page, first: list[str]) -> list[str]:
    """The numbered ports in the order the table lists them, once the
    list begins with *first* (the table is redrawn a moment after a
    device changes)."""
    page.wait_for_function(
        "(first) => JSON.stringify(("
        + _PORT_ROWS
        + ")().slice(0, first.length)) === JSON.stringify(first)",
        arg=first,
    )
    return page.evaluate(_PORT_ROWS)


class TestTheTableBeforeApplyIsInPortOrder:
    """An AOS-S config names its ports VLAN by VLAN, and the job lists
    them as the config first mentions them: 1, 48-52, 35-47, 2...  That
    was the table's order until Apply, for fifty-two ports.  Where the
    source device is declared the rows are in its port order."""

    def test_a_declared_source_puts_the_rows_in_its_port_order(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        # The source device is read from the config: 52 ports, 1 to 52.
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("52 ports")
        numbered = [str(n) for n in range(1, 53)]
        assert _port_rows(page, ["1", "2", "3"]) == numbered
        # Not declared, the order is the job's: as the config first
        # mentions them.
        source = page.locator(_tid("migrate-device-source-model-select"))
        source.select_option(value="")
        as_named = _port_rows(page, ["1", "48", "49"])
        assert sorted(as_named, key=int) == numbered and as_named != numbered
        # A device with fewer ports: its own in its order, and the names
        # it does not have after them, in the order they had.
        source.select_option(value="fam:2930F:2930F-24G-4SFP")
        expect(page.locator(_tid("migrate-device-source-note-ports"))).to_contain_text("28 ports")
        rows = _port_rows(page, ["1", "2", "3"])
        assert rows[:28] == numbered[:28]
        assert rows[28:] == [name for name in as_named if int(name) > 28]

    def test_after_apply_the_order_is_the_plans(
        self, aoss_2930f: MigratePage, page: Page,
    ) -> None:
        """The plan's rows are in the plan's order -- the source
        device's -- with whatever the operator did to them."""
        _pick_target(page, TARGET_2930M_48G, bay_a="JL083A")
        _apply(page)
        expect(_plan(page)).to_have_attribute("data-state", "ok")
        assert _port_rows(page, ["1", "2", "3"]) == [str(n) for n in range(1, 53)]
