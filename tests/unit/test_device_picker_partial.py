"""Static guards on the partials that draw the device pickers and the
rename table of the migrate page.

``device-models.js`` and ``rename-table.js`` (under
``netcanon/templates/_partials/``) are spliced into the page by a Jinja
``{% include %}`` and write strings to the page that come from
model-family and profile YAML -- which an operator can author -- from
the server's warnings, and from interface names in the pasted config
itself.  Two things about their text are therefore load-bearing, and
neither is visible to the browser tests until it has already gone
wrong:

* each must build the page with ``textContent``, attributes and DOM
  calls, never by assigning or parsing markup, so no such string can be
  read as HTML;
* neither may contain a Jinja delimiter, or the template engine will
  try to evaluate a piece of JavaScript and the page will not render.

This is a search of the text for the ways markup gets written, by
name.  It cannot see a sink reached through a name it does not list,
so the browser tier holds the same thing from the other side: a model
family whose every string is markup is drawn, and no element comes of
it (``tests/e2e/test_migrate_device_models_drawn.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PARTIALS_DIR = Path(__file__).resolve().parents[2] / "netcanon" / "templates" / "_partials"

#: The partials that draw operator-authorable strings with DOM calls only.
PARTIALS = ("device-models.js", "rename-table.js")

#: Every way of turning a string into markup, by the name it is called
#: by.  ``"HTML"`` catches ``innerHTML`` however the property name is
#: put together (``el['inner' + 'HTML']``): the letters have to be
#: somewhere.
SINKS = (
    "HTML",
    "document.write",
    "createContextualFragment",
    "DOMParser",
    "parseFromString",
    "srcdoc",
    "eval(",
    "new Function",
)


@pytest.fixture(scope="module", params=PARTIALS)
def partial(request: pytest.FixtureRequest) -> tuple[str, str]:
    name = request.param
    return name, (PARTIALS_DIR / name).read_text(encoding="utf-8")


def _code(source: str) -> str:
    """*source* without its comments: a comment may name a sink, to
    say that it is not used."""
    out: list[str] = []
    at = 0
    while at < len(source):
        if source.startswith("/*", at):
            end = source.find("*/", at + 2)
            at = len(source) if end < 0 else end + 2
        elif source.startswith("//", at) and (at == 0 or source[at - 1] != ":"):
            end = source.find("\n", at)
            at = len(source) if end < 0 else end
        else:
            out.append(source[at])
            at += 1
    return "".join(out)


@pytest.mark.parametrize("sink", SINKS)
def test_it_never_writes_markup(partial: tuple[str, str], sink: str) -> None:
    name, source = partial
    assert sink not in _code(source), (
        f"{name} uses {sink}: every string it shows comes from YAML an "
        f"operator can author, from the server, or from the pasted config, "
        f"and must be written with textContent or as an attribute value"
    )


def test_the_search_reads_code_and_not_comments() -> None:
    """The check that the check can fail, and for the right reason."""
    assert "HTML" in _code("el['inner' + 'HTML'] = text;  // not markup")
    assert "HTML" not in _code("el.textContent = text;  // never innerHTML\n/* nor outerHTML */")
    assert "HTML" in _code("var url = 'http://x';\nel.innerHTML = url;")


@pytest.mark.parametrize("delimiter", ["{{", "{%", "{#"])
def test_it_holds_no_jinja_delimiter(partial: tuple[str, str], delimiter: str) -> None:
    name, source = partial
    assert delimiter not in source, (
        f"{name} contains {delimiter!r}; it is included into migrate.html "
        f"by Jinja, which would try to evaluate it"
    )


@pytest.mark.parametrize("name", PARTIALS)
def test_the_page_includes_it(name: str) -> None:
    page = (PARTIALS_DIR.parent / "migrate.html").read_text(encoding="utf-8")
    assert '{% include "_partials/' + name + '" %}' in page
