"""A config the server refused as too large, as the pages paint it.

A refusal is a result: the operator has to be able to READ what was
large, how large, and the limit, on the page they are looking at.

* **Migrate.**  The job's sentence is drawn in the red banner, whole.
  It is not offered "Did you mean another vendor?": that is for a
  config that could not be read, and this one was read.
* **Migrate, on a server set as the public demo is.**  The sentence
  says whose limit it is and what a Netcanon of one's own allows; it
  names no setting, because a visitor cannot change one.
* **Sanitize.**  The server answers 413 with the same sentence.  Other
  failures on that page are a toast, which is gone in four seconds:
  this one is put on the page and stays.
* **Sanitize asks in turn.**  One submit is two requests, the audit
  and the output.  Each is a whole parse and render of the same
  config, so the page sends the second when the first has answered
  and never both at once -- read here from the order of the requests
  the page makes.
* **Busy.**  A server set as the demo is works on one config at a
  time.  A request that waited its whole time behind another is
  refused in words that say so, on both pages: where a refusal for
  size goes, and never as "the wrong vendor?".
* **Every place taken.**  The same server counts a request when its
  headers arrive, and answers one more than may work and wait with
  503, before its body.  The migrate page shows that answer's
  sentence as it shows every answer that is not a job: in a toast.

What is asserted is what is painted -- the text in the element's box,
the colour of its ground from a screenshot -- and never a class name.
"""
from __future__ import annotations

import re
import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Locator, Page, expect

from netcanon.migration import limits as L
from tests.e2e.conftest import _find_free_port
from tests.e2e.drawn import RGB, alike, contrast, ink, png_pixels
from tests.e2e.helpers import MigratePage

pytestmark = pytest.mark.e2e

#: One AOS-S stanza of 40 port ranges: 520 bytes that name 40,040 ports.
AOSS_RANGES = 'hostname "T"\nvlan 10\n   name "V10"\n   tagged ' + ",".join(
    f"{n * 2000 + 1}-{n * 2000 + 1001}" for n in range(40)
) + "\n   exit\n"
#: A config any server takes.
AOSS_SMALL = 'hostname "T"\nvlan 10\n   name "V10"\n   tagged 1-4\n   exit\n'
#: Three such ranges: 3,003 ports, more than a demo instance takes.
AOSS_THREE = 'hostname "T"\nvlan 10\n   name "V10"\n   tagged 1-1001,2001-3001,4001-5001\n   exit\n'
#: 2,501 interface stanzas of one line each.  Detection reads this as
#: IOS-XE; it is sent as Arista EOS, whose parser reads the stanzas too.
STANZAS = "hostname T\n!\n" + "".join(f"interface Gi{n}\n" for n in range(2_501)) + "end\n"

STANDARD_SENTENCE = (
    "refused: reading the config as aruba_aoss would make 9,009 or more different ports named by port "
    "ranges; the limit is 8,192 (counted over 9 ranges; the last one read: 16001-17001).  This server runs "
    "with the 'standard' config size limit.  To allow more, set NETCANON_CONFIG_LIMITS=large (or unlimited) "
    "in its environment and restart it; in the desktop application, choose Preferences... -> Config size limit."
)


@pytest.fixture(scope="module")
def small_server_url(_e2e_definitions_dir: Path, _e2e_configs_dir: Path) -> Iterator[str]:
    """A second server, set as the public demo's instances are."""
    import uvicorn

    from netcanon.config import Settings
    from netcanon.main import create_app

    port = _find_free_port()
    app = create_app(Settings(
        definitions_dir=_e2e_definitions_dir, configs_dir=_e2e_configs_dir, config_limits="small",
    ))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            break
        except Exception:
            time.sleep(0.1)
    else:
        server.should_exit = True
        raise RuntimeError("the second e2e server did not answer within 10 seconds")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@contextmanager
def _a_request_at_work() -> Iterator[None]:
    """The place of a server set as the demo is, taken until the block
    ends.  (The servers of these tests run in this process, and the
    limit is the process's.)"""
    held, let_go = threading.Event(), threading.Event()

    def work() -> None:
        with L.server_scope(L.SMALL):
            held.set()
            let_go.wait(60)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    assert held.wait(10)
    try:
        yield
    finally:
        let_go.set()
        thread.join(10)


def _sanitise_requests(page: Page) -> list[str]:
    """What the page asks the sanitiser, and what it is answered, in
    the order they happen: a list the page's requests are added to
    as it makes them."""
    events: list[str] = []

    def asked(request) -> None:
        if request.method == "POST" and request.url.endswith("/api/v1/sanitize"):
            events.append("asked")

    def answered(response) -> None:
        if response.request.method == "POST" and response.url.endswith("/api/v1/sanitize"):
            kind = response.headers.get("content-type", "").split(";")[0]
            events.append(f"answered {response.status} {kind}")

    page.on("request", asked)
    page.on("response", answered)
    return events


def _words(text: str) -> str:
    """*text* as a page draws it: a run of white space is one space."""
    return " ".join(text.split())


def _translate(page: Page, url: str, source: str, target: str, text: str) -> MigratePage:
    page.goto(f"{url}/migrate")
    mig = MigratePage(page)
    page.wait_for_function(
        """() => {
            const sel = document.querySelector('[data-testid="migrate-source-select"]');
            return sel && sel.options.length > 0;
        }"""
    )
    mig.pick_source(source)
    mig.pick_target(target)
    mig.fill_raw(text)
    mig.submit_btn.click()
    mig.result.wait_for(state="visible", timeout=15_000)
    return mig


def _ground(locator: Locator) -> RGB:
    """The colour painted behind *locator*'s text: the commonest pixel
    of a screenshot of the element.  (The element is in the page's
    own flow, below the fold, so the element screenshot is the right
    one here; ``drawn.shot`` is for what sits in a fixed box.)"""
    _width, _height, pixels = png_pixels(locator.screenshot())
    return Counter(pixels).most_common(1)[0][0]


def _token_beside(locator: Locator, token: str) -> RGB:
    """What ``background: var(<token>)`` paints on the ground
    *locator* is drawn on: a probe is put in front of it, in the same
    parent, read, and removed.  (The badge tints are translucent, so a
    token is a colour only on a ground.)"""
    locator.evaluate(
        """(el, token) => {
            const probe = document.createElement('div');
            probe.id = 'limits-token-probe';
            probe.style.cssText = 'width:40px;height:16px;background:var(' + token + ')';
            el.parentElement.insertBefore(probe, el);
        }""",
        token,
    )
    try:
        return _ground(locator.page.locator("#limits-token-probe"))
    finally:
        locator.page.evaluate("document.getElementById('limits-token-probe').remove()")


def _is_drawn_whole(page: Page, selector: str) -> None:
    """The element's text is inside its box and its box inside the
    window: nothing of it is cut off or pushed off the side."""
    box = page.evaluate(
        """(selector) => {
            const el = document.querySelector(selector);
            el.scrollIntoView({block: 'nearest', behavior: 'instant'});
            const r = el.getBoundingClientRect();
            return {
                left: r.left, right: r.right, top: r.top, bottom: r.bottom,
                clipped: el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1,
                width: window.innerWidth, height: window.innerHeight,
                shown: getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).opacity !== '0',
            };
        }""",
        selector,
    )
    assert box["shown"] and not box["clipped"], box
    # (A pixel of slack: a box scrolled into view can end on a fraction.)
    assert box["left"] >= -1 and box["right"] <= box["width"] + 1, box
    assert box["top"] >= -1 and box["bottom"] <= box["height"] + 1, box


class TestTheMigratePage:
    def test_the_red_banner_shows_the_sentence_whole(self, page: Page, base_url: str) -> None:
        mig = _translate(page, base_url, "aruba_aoss", "cisco_iosxe_cli", AOSS_RANGES)
        expect(mig.status_summary).to_contain_text("status: failed")
        expect(mig.banner).to_be_visible()
        assert _words(mig.banner.inner_text()) == _words("Error: " + STANDARD_SENTENCE)
        _is_drawn_whole(page, '[data-testid="migrate-compatibility-banner"]')
        # Red, as painted: the banner's ground is the failed tint on the page's own ground.
        ground = _ground(mig.banner)
        assert alike(ground, _token_beside(mig.banner, "--badge-failed-bg"), within=3)
        # Nothing was translated: there is no output to copy.
        assert mig.output.inner_text().strip() == ""

    def test_a_refusal_is_not_offered_another_vendor(
        self, page: Page, small_server_url: str,
    ) -> None:
        """"Did you mean ...?" follows a job whose error begins
        ``parse failed``.  The text here is one detection gives to
        another codec than the one it was sent as, so a parse failure
        WOULD be followed by the offer -- and a refusal is not."""
        top = httpx.post(
            f"{small_server_url}/api/v1/migration/detect", json={"raw_text": STANZAS, "min_confidence": 40},
        ).json()[0]["codec"]
        assert top != "arista_eos", "detection has to disagree with the source for this to mean anything"
        with page.expect_response("**/api/v1/migration/plan") as planned:
            mig = _translate(page, small_server_url, "arista_eos", "juniper_junos", STANZAS)
        job = planned.value.json()
        assert job["status"] == "failed" and job["refusal"]["limit"] == "interfaces"
        expect(mig.banner).to_contain_text("refused: reading the config as arista_eos would make 2,501 or more")
        # The offer is fetched after the job is drawn: give it the time it would take.
        page.wait_for_timeout(1_500)
        expect(page.locator('[data-testid="migrate-parse-failure-detect-suggest"]')).to_have_count(0)
        assert "Did you mean" not in mig.banner.inner_text()

    def test_a_parse_failure_still_gets_the_offer(
        self, page: Page, base_url: str,
    ) -> None:
        """The other half: the same page, a text the picked codec
        cannot read.  Without this the test above would pass on a page
        that had lost the offer altogether."""
        xml = '<?xml version="1.0"?>\n<opnsense>\n  <system><hostname>fw</hostname></system>\n</opnsense>\n'
        mig = _translate(page, base_url, "cisco_iosxe_cli", "juniper_junos", xml)
        expect(mig.banner).to_contain_text("parse failed")
        expect(page.locator('[data-testid="migrate-parse-failure-detect-suggest"]')).to_be_visible(timeout=5_000)
        assert "Did you mean" in mig.banner.inner_text()

    def test_a_demo_server_names_no_setting(
        self, page: Page, small_server_url: str,
    ) -> None:
        mig = _translate(page, small_server_url, "aruba_aoss", "cisco_iosxe_cli", AOSS_THREE)
        said = _words(mig.banner.inner_text())
        assert said == (
            "Error: refused: reading the config as aruba_aoss would make 3,003 or more different ports named "
            "by port ranges; the limit is 2,048 (counted over 3 ranges; the last one read: 4001-5001). This "
            "server runs with the 'small' config size limit, the one the public demo uses. A Netcanon you run "
            "yourself allows 8,192 by default."
        )
        for word in ("NETCANON_", "environment", "Preferences", "restart"):
            assert word not in said
        _is_drawn_whole(page, '[data-testid="migrate-compatibility-banner"]')

    def test_busy_is_a_refusal_and_not_a_wrong_vendor(
        self, page: Page, small_server_url: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The server is at work on another config for longer than a
        request may wait (a second stands in for the twenty).  The
        job comes back refused, and the banner says the server was
        busy and to send it again -- whichever of the page's requests
        got to the line first."""
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=1.0))
        with _a_request_at_work():
            mig = _translate(page, small_server_url, "aruba_aoss", "cisco_iosxe_cli", AOSS_SMALL)
            expect(mig.status_summary).to_contain_text("status: failed")
            said = _words(mig.banner.inner_text())
            page.wait_for_timeout(1_500)
            expect(page.locator('[data-testid="migrate-parse-failure-detect-suggest"]')).to_have_count(0)
        assert said.startswith("Error: refused: the server works on one config at a time, and "), said
        assert "this request was not started and its config was not read. Send it again." in said
        assert "Did you mean" not in said and "parse failed" not in said
        _is_drawn_whole(page, '[data-testid="migrate-compatibility-banner"]')
        assert mig.output.inner_text().strip() == ""

    def test_with_every_place_taken_the_sentence_is_shown(self, page: Page, small_server_url: str) -> None:
        """Three requests hold the three places.  The page's own is
        answered 503, which is not a job: the sentence is in the
        toast the page shows for a request that was not taken, and
        nothing is offered as another vendor."""
        held = [L.Answer() for _ in range(3)]
        for answer in held:
            answer.arrived("small")
        try:
            page.goto(f"{small_server_url}/migrate")
            mig = MigratePage(page)
            page.wait_for_function(
                """() => {
                    const sel = document.querySelector('[data-testid="migrate-source-select"]');
                    return sel && sel.options.length > 0;
                }"""
            )
            mig.pick_source("aruba_aoss")
            mig.pick_target("cisco_iosxe_cli")
            mig.fill_raw(AOSS_SMALL)
            mig.submit_btn.click()
            toast = page.locator('[data-testid="toast"]')
            expect(toast).to_be_visible(timeout=10_000)
            said = _words(toast.inner_text())
        finally:
            for answer in held:
                answer.sent()
        assert said.startswith(
            "Request rejected: Refused: the server works on one config at a time, and 2 more were already "
            "waiting their turn; this request was not started and its config was not read. Send it again."
        ), said
        assert "Did you mean" not in said and "parse failed" not in said
        expect(page.locator('[data-testid="migrate-parse-failure-detect-suggest"]')).to_have_count(0)

    def test_standard_translates_the_same_config(self, page: Page, base_url: str) -> None:
        mig = _translate(page, base_url, "aruba_aoss", "aruba_aoss", AOSS_THREE)
        expect(mig.status_summary).not_to_contain_text("status: failed")
        assert "tagged 1-1001,2001-3001,4001-5001" in mig.output.inner_text()
        assert "refused" not in mig.banner.inner_text()


class TestTheSanitizePage:
    def _submit(self, page: Page, url: str, text: str) -> None:
        page.goto(f"{url}/sanitize")
        page.wait_for_function(
            """() => {
                const sel = document.querySelector('[data-testid="sanitize-source-select"]');
                return sel && sel.options.length > 0;
            }"""
        )
        page.locator('[data-testid="sanitize-source-select"]').select_option(value="aruba_aoss")
        page.locator('[data-testid="sanitize-raw-input"]').fill(text)
        page.locator('[data-testid="sanitize-submit-btn"]').click()

    def test_the_sentence_is_put_on_the_page_and_stays(self, page: Page, base_url: str) -> None:
        """A toast is gone in four seconds, and this is four hundred
        characters that say what to do.  It is read here after five."""
        self._submit(page, base_url, AOSS_RANGES)
        refusal = page.locator('[data-testid="sanitize-refusal"]')
        expect(refusal).to_be_visible(timeout=10_000)
        sentence = _words("Refused: " + STANDARD_SENTENCE.removeprefix("refused: "))
        assert len(sentence) > 350
        assert _words(refusal.inner_text()) == sentence
        page.wait_for_timeout(5_000)
        expect(refusal).to_be_visible()
        assert _words(refusal.inner_text()) == sentence
        _is_drawn_whole(page, '[data-testid="sanitize-refusal"]')
        ground = _ground(refusal)
        assert alike(ground, _token_beside(refusal, "--badge-failed-bg"), within=3)
        assert contrast(ink(refusal), ground) >= 4.5
        # It is not also a toast, and nothing was sanitised.
        expect(page.locator('[data-testid="toast"]')).to_be_hidden()
        expect(page.locator('[data-testid="sanitize-result"]')).to_be_hidden()

    def test_the_next_submit_takes_it_away(self, page: Page, base_url: str) -> None:
        self._submit(page, base_url, AOSS_RANGES)
        refusal = page.locator('[data-testid="sanitize-refusal"]')
        expect(refusal).to_be_visible(timeout=10_000)
        page.locator('[data-testid="sanitize-raw-input"]').fill(AOSS_THREE)
        page.locator('[data-testid="sanitize-submit-btn"]').click()
        expect(page.locator('[data-testid="sanitize-result"]')).to_be_visible(timeout=10_000)
        expect(refusal).to_be_hidden()
        assert refusal.inner_text() == ""

    def test_under_the_demo_limits_it_names_no_setting(self, page: Page, small_server_url: str) -> None:
        self._submit(page, small_server_url, AOSS_THREE)
        refusal = page.locator('[data-testid="sanitize-refusal"]')
        expect(refusal).to_be_visible(timeout=10_000)
        said = refusal.inner_text()
        assert "the one the public demo uses" in said and "A Netcanon you run yourself allows 8,192" in said
        assert "NETCANON_" not in said and "environment" not in said

    def test_the_audit_and_the_output_are_asked_for_in_turn(self, page: Page, base_url: str) -> None:
        """One submit, two requests: the audit, and when it has been
        answered the output.  Sent together, both would be asked
        before either was answered -- and on a server with little
        memory the config would be held twice over."""
        events = _sanitise_requests(page)
        self._submit(page, base_url, AOSS_THREE)
        expect(page.locator('[data-testid="sanitize-result"]')).to_be_visible(timeout=10_000)
        assert events == ["asked", "answered 200 application/json", "asked", "answered 200 text/plain"]
        # Both are painted: the audit, and the sanitized text.
        assert re.fullmatch(r"[1-9]\d* redactions?", page.locator('[data-testid="sanitize-audit-count"]').inner_text())
        assert page.locator('[data-testid="sanitize-audit-row"]').count() >= 1
        expect(page.locator('[data-testid="sanitize-output-section"]')).to_be_visible()
        assert "tagged 1-1001,2001-3001,4001-5001" in page.locator('[data-testid="sanitize-output"]').inner_text()
        expect(page.locator('[data-testid="sanitize-refusal"]')).to_be_hidden()

    def test_a_preview_asks_once(self, page: Page, base_url: str) -> None:
        events = _sanitise_requests(page)
        page.goto(f"{base_url}/sanitize")
        page.locator('[data-testid="sanitize-dry-run-checkbox"]').check()
        page.wait_for_function(
            """() => document.querySelector('[data-testid="sanitize-source-select"]').options.length > 1"""
        )
        page.locator('[data-testid="sanitize-source-select"]').select_option(value="aruba_aoss")
        page.locator('[data-testid="sanitize-raw-input"]').fill(AOSS_THREE)
        page.locator('[data-testid="sanitize-submit-btn"]').click()
        expect(page.locator('[data-testid="sanitize-result"]')).to_be_visible(timeout=10_000)
        assert events == ["asked", "answered 200 application/json"]
        expect(page.locator('[data-testid="sanitize-output-section"]')).to_be_hidden()

    def test_busy_is_put_on_the_page_and_the_output_is_not_asked_for(
        self, page: Page, small_server_url: str, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The server is at work on another config for longer than a
        request may wait (a second stands in for the twenty): 503, and
        a sentence to read and act on.  It goes where a refusal for
        size goes and stays there; the second request is not made."""
        monkeypatch.setitem(L.PROFILES, "small", replace(L.SMALL, seconds=1.0))
        events = _sanitise_requests(page)
        refusal = page.locator('[data-testid="sanitize-refusal"]')
        with _a_request_at_work():
            self._submit(page, small_server_url, AOSS_SMALL)
            expect(refusal).to_be_visible(timeout=10_000)
            # Not also a toast -- looked at now, while one would still be up.
            assert not page.locator('[data-testid="toast"]').is_visible()
            page.wait_for_timeout(1_500)
            assert not page.locator('[data-testid="toast"]').is_visible()
        assert events == ["asked", "answered 503 application/json"]
        assert _words(refusal.inner_text()) == _words(
            "Refused: the server works on one config at a time, and was busy with another for the 1 seconds this "
            "request may take; this request was not started and its config was not read.  Send it again.  This "
            "server runs with the 'small' config size limit, the one the public demo uses.  A Netcanon you run "
            "yourself does not make one request wait for another by default."
        )
        _is_drawn_whole(page, '[data-testid="sanitize-refusal"]')
        expect(page.locator('[data-testid="toast"]')).to_be_hidden()
        expect(page.locator('[data-testid="sanitize-result"]')).to_be_hidden()
        # Sent again, with the server free, it is sanitised.
        page.locator('[data-testid="sanitize-submit-btn"]').click()
        expect(page.locator('[data-testid="sanitize-result"]')).to_be_visible(timeout=10_000)
        expect(refusal).to_be_hidden()
        assert events[2:] == ["asked", "answered 200 application/json", "asked", "answered 200 text/plain"]
