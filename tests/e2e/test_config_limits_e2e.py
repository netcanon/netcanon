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

What is asserted is what is painted -- the text in the element's box,
the colour of its ground from a screenshot -- and never a class name.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.conftest import _find_free_port
from tests.e2e.drawn import RGB, alike, contrast, ink, png_pixels
from tests.e2e.helpers import MigratePage

pytestmark = pytest.mark.e2e

#: One AOS-S stanza of 40 port ranges: 520 bytes that name 40,040 ports.
AOSS_RANGES = 'hostname "T"\nvlan 10\n   name "V10"\n   tagged ' + ",".join(
    f"{n * 2000 + 1}-{n * 2000 + 1001}" for n in range(40)
) + "\n   exit\n"
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
