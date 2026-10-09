"""Static guards on the device-picker partial of the migrate page.

``netcanon/templates/_partials/device-models.js`` is spliced into the
page by a Jinja ``{% include %}`` and writes strings to the page that
come from model-family and profile YAML -- which an operator can author
-- and from lines of the pasted config itself.  Two things about its
text are therefore load-bearing, and neither is visible to the browser
tests until it has already gone wrong:

* it must build the page with ``textContent`` and DOM calls, never by
  assigning markup, so no such string can be read as HTML;
* it must contain no Jinja delimiter, or the template engine will try
  to evaluate a piece of JavaScript and the page will not render.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PARTIAL = (
    Path(__file__).resolve().parents[2]
    / "netcanon" / "templates" / "_partials" / "device-models.js"
)


@pytest.fixture(scope="module")
def source() -> str:
    return PARTIAL.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "sink", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"],
)
def test_it_never_writes_markup(source: str, sink: str) -> None:
    assert sink not in source, (
        f"device-models.js uses {sink}: every string it shows comes from "
        f"YAML an operator can author or from the pasted config, and must "
        f"be written with textContent"
    )


@pytest.mark.parametrize("delimiter", ["{{", "{%", "{#"])
def test_it_holds_no_jinja_delimiter(source: str, delimiter: str) -> None:
    assert delimiter not in source, (
        f"device-models.js contains {delimiter!r}; it is included into "
        f"migrate.html by Jinja, which would try to evaluate it"
    )


def test_the_page_includes_it() -> None:
    page = (PARTIAL.parents[1] / "migrate.html").read_text(encoding="utf-8")
    assert '{% include "_partials/device-models.js" %}' in page
