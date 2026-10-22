"""An escape in a RouterOS string is read as MikroTik's table says.

MikroTik, "Scripting"
(https://help.mikrotik.com/docs/spaces/ROS/pages/47579229/Scripting),
lists the escapes a string can hold: ``\\"``, ``\\\\``, ``\\n``,
``\\r``, ``\\t``, ``\\$``, ``\\?``, ``\\_`` (a space), ``\\a`` (bell),
``\\b`` (backspace), ``\\f`` (form feed), ``\\v`` (vertical tab) and
``\\xx``, "a print character from hex value.  Hex numbers should use
capital letters."  An export writes a byte outside printable ASCII so
(``\\C3\\A9``).  The parser read a backslash and the character after
it as that character, whatever it was: a description ``Caf\\C3\\A9``
reached every target as ``CafC3A9``, ``\\_`` as ``_`` and ``\\n`` as
``n``.

RouterOS keeps a string as bytes, and the text does not say which
encoding they are in (UTF-8 and Windows-1251 are both met).  A run of
bytes is read as UTF-8 where it is UTF-8 and kept as written where it
is not; a control character a terminal acts on rather than shows is
kept as written as well, since the tree is written into other vendors'
configs and read on a terminal.  A line break is read as one, and the
pipeline writes it as a space and says so, as it does any value's
(:mod:`netcanon.migration._one_line`).

Tested here:

(a) each row of the page's table, typed here by hand, through the
    parser;
(b) the page's own example;
(c) runs of bytes: UTF-8, not UTF-8, control characters, a lower-case
    hex digit;
(d) an export through the pipeline onto every public codec, its output
    read as text;
(e) RouterOS to RouterOS: what is read is written and read back the
    same;
(f) each check, handed the old reading, fails.
"""

from __future__ import annotations

from unittest import mock

import pytest

from netcanon.migration.codecs.mikrotik_routeros import parse as ros_parse
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_pipeline import run_plan


def _export(comment: str) -> str:
    """A RouterOS export whose ``ether2`` has the string *comment*
    (its escapes as an export writes them) and an address."""
    return (
        "# by RouterOS 7.14\n"
        "/interface ethernet\n"
        f'set [ find default-name=ether2 ] comment="{comment}"\n'
        "/ip address\n"
        "add address=192.0.2.1/24 interface=ether2 network=192.0.2.0\n"
    )


def _described(comment: str) -> str | None:
    tree = get_codec("mikrotik_routeros").parse(_export(comment))
    (port,) = [i for i in tree.interfaces if i.name == "ether2"]
    return port.description


def _old_unescape(value: str) -> str:
    """The reading up to 0.7.7: a backslash takes the next character."""
    out: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            out.append(value[i + 1])
            i += 2
        else:
            out.append(value[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# (a) The table
# ---------------------------------------------------------------------------

#: Each row of the page's table, as an export writes it, and what the
#: tree holds for it -- typed here, not taken from the parser.  The bell
#: and the backspace are kept as written (a terminal acts on them); the
#: page gives ``\f`` as "form feed (0xFF)", and it is read as the form
#: feed.
_THE_TABLE = [
    ('\\"', '"'),
    ("\\\\", "\\"),
    ("\\n", "\n"),
    ("\\r", "\r"),
    ("\\t", "\t"),
    ("\\$", "$"),
    ("\\?", "?"),
    ("\\_", " "),
    ("\\a", "\\a"),
    ("\\b", "\\b"),
    ("\\f", "\x0c"),
    ("\\v", "\x0b"),
    ("\\41", "A"),
]


@pytest.mark.parametrize(("written", "meant"), _THE_TABLE, ids=[w for w, _ in _THE_TABLE])
def test_each_row_of_the_table(written: str, meant: str) -> None:
    assert _described(f"x{written}y") == f"x{meant}y"


# ---------------------------------------------------------------------------
# (b) The page's example
# ---------------------------------------------------------------------------


def test_the_pages_own_example() -> None:
    written = "\\48\\45\\4C\\4C\\4F\\r\\nThis\\r\\nis\\r\\na\\r\\ntest"
    assert _described(written) == "HELLO\r\nThis\r\nis\r\na\r\ntest"


# ---------------------------------------------------------------------------
# (c) Runs of bytes
# ---------------------------------------------------------------------------

_RUNS = [
    # UTF-8, as an export writes it.
    ("Caf\\C3\\A9", "Café"),
    ("\\D0\\9F\\D1\\80\\D0\\B8", "При"),
    # The same word in Windows-1251: not UTF-8, so kept as written.
    ("\\CF\\F0\\E8", "\\CF\\F0\\E8"),
    # Control characters a terminal acts on: escape, delete, NUL, and
    # U+009B (a C1 control, two bytes in UTF-8).
    ("\\1B[2J", "\\1B[2J"),
    ("\\7F", "\\7F"),
    ("\\00", "\\00"),
    ("\\C2\\9B", "\\C2\\9B"),
    # One run of several kinds: each character on its own.
    ("\\C3\\A9\\07\\41", "é\\07A"),
    # White space by its byte.
    ("\\0A", "\n"),
    ("\\09", "\t"),
    # Lower case is no hex digit (the page): ``\c`` is ``c``, ``\a`` the
    # bell.
    ("\\c3\\a9", "c3\\a9"),
    # A backslash of the value, then digits.
    ("\\\\41", "\\41"),
]


@pytest.mark.parametrize(("written", "meant"), _RUNS, ids=[w for w, _ in _RUNS])
def test_a_run_of_bytes(written: str, meant: str) -> None:
    assert _described(written) == meant


def test_a_lone_backslash_at_the_end_is_kept() -> None:
    assert ros_parse._unescape("end\\") == "end\\"


# ---------------------------------------------------------------------------
# (d) Onto every public codec
# ---------------------------------------------------------------------------

#: A description in two scripts, with a space escaped and a line break
#: in front of a line that would be an account if it were a line.
_COMMENT = "Caf\\C3\\A9 \\D0\\9F\\D1\\80\\D0\\B8\\_lan\\nusername x privilege 15 nopassword"
_TARGETS = sorted(list_public_codecs())


@pytest.mark.parametrize("target", _TARGETS)
def test_onto_every_codec(target: str) -> None:
    job = run_plan(get_codec("mikrotik_routeros"), get_codec(target), _export(_COMMENT))
    out = job.rendered or ""
    assert "Café При lan" in out
    assert "C3A9" not in out and "\\C3" not in out
    assert not [ln for ln in out.splitlines() if ln.strip().startswith("username x")]
    assert any(
        w.startswith("interfaces[ether2].description held a line break") for w in job.warnings
    )


def test_every_target_is_tried() -> None:
    assert len(_TARGETS) > 10


# ---------------------------------------------------------------------------
# (e) RouterOS to RouterOS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written", ["Caf\\C3\\A9\\_x", "\\CF\\F0\\E8", "a\\ab\\1B[2J", "tab\\there"],
)
def test_read_written_and_read_back(written: str) -> None:
    codec = get_codec("mikrotik_routeros")
    meant = _described(written)
    job = run_plan(codec, codec, _export(written))
    back = codec.parse(job.rendered)
    (port,) = [i for i in back.interfaces if i.name == "ether2"]
    assert port.description == meant


# ---------------------------------------------------------------------------
# (f) The checks, handed the old reading
# ---------------------------------------------------------------------------


class TestTheOldReading:
    """With the reading up to 0.7.7 each check above fails."""

    @pytest.fixture(autouse=True)
    def _old(self):
        with mock.patch.object(ros_parse, "_unescape", _old_unescape):
            yield

    @pytest.mark.parametrize("written", ["\\n", "\\_", "\\41", "\\a"])
    def test_the_table(self, written: str) -> None:
        meant = dict(_THE_TABLE)[written]
        assert _described(f"x{written}y") != f"x{meant}y"

    def test_the_example(self) -> None:
        assert _described("\\48\\45\\4C\\4C\\4F") != "HELLO"

    def test_a_run(self) -> None:
        assert _described("Caf\\C3\\A9") == "CafC3A9"

    def test_onto_a_codec(self) -> None:
        job = run_plan(
            get_codec("mikrotik_routeros"), get_codec("cisco_iosxe_cli"), _export(_COMMENT),
        )
        assert "Café" not in (job.rendered or "")
        assert "CafC3A9" in (job.rendered or "")
