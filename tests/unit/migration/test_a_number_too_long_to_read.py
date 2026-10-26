"""A run of more digits than a number is read from is refused, in words.

Python converts a string of digits to an ``int`` only up to a limit
(``sys.get_int_max_str_digits()``, 4,300 digits by default) and raises
``ValueError`` past it.  A config that held a run of 4,400 digits failed
the parse of seven of the public codecs, each time as ``unexpected error
in stage parsing`` with the interpreter's advice to raise the limit; an
entry of a port map whose target held one failed seven of the targets
at render the same way.  ``CodecBase.parse`` now refuses such a text
with a ``ParseError`` that names the line, and ``CodecBase.render`` a
tree that holds such a run, naming the field
(:mod:`netcanon.migration._long_numbers`).

What is read here: every line of a committed capture of each public
codec that holds a run of digits, with its first run made too long,
each parsed; a port named by an operator's map onto every target; and
each check taken out, to show the texts reach the failure it is for.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from netcanon.migration import _long_numbers
from netcanon.migration.codecs import base
from netcanon.migration.codecs.base import ParseError, RenderError
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.models.migration import MigrationJob
from netcanon.services.migration_pipeline import run_plan_with_checked_names

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
REAL = FIXTURES / "real"

LIMIT = sys.int_info.default_max_str_digits
#: A run of digits longer than any number Python reads by default.
LONG = "1" * (LIMIT + 100)

_NOT_CONFIG = {".md", ".json", ".yaml", ".yml", ".py", ".pyc"}

#: A codec whose committed inputs are not under ``real/``.
_OTHER_INPUTS = {"cisco_iosxe": [FIXTURES / "iosxe" / "get_config_simple.xml"]}


@pytest.fixture(autouse=True)
def _the_default_limit() -> Iterator[None]:
    """Each test under Python's default limit, whatever the run set."""
    before = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(LIMIT)
    yield
    sys.set_int_max_str_digits(before)


def _smallest_capture(codec: str) -> str:
    """The smallest committed capture of *codec* (over 200 bytes)."""
    found = [
        path
        for folder, name in DIR_TO_CODEC_NAME.items()
        if name == codec
        for path in (REAL / folder).glob("*")
        if path.is_file() and path.suffix.lower() not in _NOT_CONFIG and path.stat().st_size > 200
    ] + _OTHER_INPUTS.get(codec, [])
    assert found, f"no committed capture of {codec}"
    return min(found, key=lambda p: (p.stat().st_size, p.name)).read_text(encoding="utf-8")


def _with_one_line_long(text: str) -> Iterator[tuple[int, str]]:
    """(line number, *text* with that line's first run of digits made
    too long), for each line that holds a run -- lines counted as
    :meth:`str.splitlines` counts them, from 1."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        start = next((i for i, ch in enumerate(line) if ch.isdecimal()), None)
        if start is None:
            continue
        end = start
        while end < len(line) and line[end].isdecimal():
            end += 1
        changed = line[:start] + LONG + line[end:]
        yield index + 1, "".join(lines[:index]) + changed + "".join(lines[index + 1:])


_CODECS = list_public_codecs()


class TestTheText:
    @pytest.mark.parametrize("codec", _CODECS)
    def test_every_line_that_holds_a_number(self, codec: str) -> None:
        """Wherever the run is, the parse is refused with the line, and
        with nothing of the text."""
        parser = get_codec(codec)
        tried = 0
        for line, text in _with_one_line_long(_smallest_capture(codec)):
            tried += 1
            with pytest.raises(ParseError) as caught:
                parser.parse(text)
            message = str(caught.value)
            assert message == _long_numbers.parse_refused(codec, line)
            assert "1" * 20 not in message
        assert tried > 3

    def test_the_check_sees_the_old_reading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without the check the same texts reach the limit inside the
        parsers: the interpreter's ``ValueError``, not a ``ParseError``."""
        monkeypatch.setattr(base, "first_long_run_line", lambda raw: None)
        failed: set[str] = set()
        for codec in _CODECS:
            parser = get_codec(codec)
            for _, text in _with_one_line_long(_smallest_capture(codec)):
                try:
                    parser.parse(text)
                except ParseError:
                    continue
                except ValueError as exc:
                    assert "integer string conversion" in str(exc)
                    failed.add(codec)
                    break
        assert len(failed) >= 4, failed

    def test_no_committed_input_is_refused(self) -> None:
        held = [
            str(path.relative_to(FIXTURES))
            for path in sorted(FIXTURES.rglob("*"))
            if path.is_file() and path.suffix.lower() not in _NOT_CONFIG
            and _long_numbers.first_long_run_line(
                path.read_text(encoding="utf-8", errors="replace"),
            ) is not None
        ]
        assert held == []

    def test_a_run_as_long_as_the_limit_is_read(self) -> None:
        text = (
            "hostname r1\ninterface GigabitEthernet1/0/1\n"
            f" description {'1' * LIMIT}\n!\nend\n"
        )
        [port] = [i for i in get_codec("cisco_iosxe_cli").parse(text).interfaces
                  if i.name == "GigabitEthernet1/0/1"]
        assert port.description == "1" * LIMIT

    def test_the_job_says_it_in_words(self) -> None:
        text = (
            "hostname r1\nvlan 10\n!\n"
            f"interface GigabitEthernet1/0/{LONG}\n switchport access vlan 10\n!\nend\n"
        )
        job = run_plan_with_checked_names(
            get_codec("cisco_iosxe_cli"), get_codec("juniper_junos"), text, port_rename_map={},
        )
        assert job.status.value == "failed"
        assert job.error == "parse failed: " + _long_numbers.parse_refused("cisco_iosxe_cli", 4)


class TestTheLine:
    """Which line is named, and under which limit."""

    @pytest.mark.parametrize(
        ("text", "line"),
        [
            pytest.param(LONG, 1, id="the first line"),
            pytest.param(f"a\nb\n{LONG}\n", 3, id="after line feeds"),
            pytest.param(f"a\r\nb\r\n x {LONG}", 3, id="after CR LF"),
            pytest.param(f"a\u2028b\x0c{LONG}", 3, id="after other line breaks"),
            pytest.param(f"{'1' * LIMIT} x\n{LONG}", 2, id="a run of the limit is read"),
            pytest.param("\u0661" * (LIMIT + 1), 1, id="digits of another script"),
        ],
    )
    def test_the_line_of_the_first_run(self, text: str, line: int) -> None:
        assert _long_numbers.first_long_run_line(text) == line
        # The line as the parsers count lines.
        runs = re.findall(r"\d+", text.splitlines()[line - 1])
        assert max(map(len, runs)) > LIMIT

    def test_a_run_is_not_joined_across_white_space(self) -> None:
        half = "1" * (LIMIT // 2 + 1)
        assert _long_numbers.first_long_run_line(f"{half} {half}\n{half}\n{half}") is None

    def test_the_limit_is_read_when_the_check_is_made(self) -> None:
        sys.set_int_max_str_digits(1000)
        assert _long_numbers.first_long_run_line("1" * 1000) is None
        assert _long_numbers.first_long_run_line("x\n" + "1" * 1001) == 2
        assert "more than 1,000 digits" in _long_numbers.parse_refused("vyos", 2)

    def test_no_limit_refuses_nothing(self) -> None:
        sys.set_int_max_str_digits(0)
        assert _long_numbers.first_long_run_line(LONG * 3) is None
        assert _long_numbers.first_long_run(get_codec("vyos").parse(
            f"set interfaces ethernet eth0 description {LONG}\n",
        )) is None


_HOST = (
    "hostname r1\nvlan 10\n!\ninterface GigabitEthernet1/0/1\n switchport mode access\n"
    " switchport access vlan 10\n!\ninterface GigabitEthernet1/0/2\n switchport mode access\n"
    " switchport access vlan 10\n!\nend\n"
)


def _named_long(target: str) -> MigrationJob:
    return run_plan_with_checked_names(
        get_codec("cisco_iosxe_cli"), get_codec(target), _HOST,
        port_rename_map={"GigabitEthernet1/0/1": "Ethernet" + LONG},
    )


class TestTheTree:
    @pytest.mark.parametrize("target", _CODECS)
    def test_a_port_an_entry_names_with_one(self, target: str) -> None:
        job = _named_long(target)
        assert job.status.value == "failed"
        assert job.error == "render failed: " + _long_numbers.render_refused(
            target, "interfaces[].name",
        )
        assert job.rendered is None

    @pytest.mark.parametrize("target", _CODECS)
    def test_render_is_refused_whoever_calls_it(self, target: str) -> None:
        """Any field, and a caller that is not the pipeline: the rule
        is the render's."""
        tree = get_codec("cisco_iosxe_cli").parse(_HOST)
        tree.interfaces[0].description = LONG
        with pytest.raises(RenderError) as caught:
            get_codec(target).render(tree)
        assert str(caught.value) == _long_numbers.render_refused(
            target, "interfaces[].description",
        )

    def test_the_check_sees_the_old_reading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without the render's check the name reaches the renderers:
        onto VyOS the job failed as a fault, in the interpreter's words."""
        monkeypatch.setattr(base, "first_long_run", lambda tree: None)
        job = _named_long("vyos")
        assert job.status.value == "failed"
        assert job.error.startswith("unexpected error in stage rendering: Exceeds the limit")


class TestTheDocuments:
    @pytest.mark.parametrize("doc", ["docs/CAPABILITIES.md", "docs/TROUBLESHOOTING.md"])
    def test_they_give_the_limit_python_gives(self, doc: str) -> None:
        """The operator's pages give the default limit as a number: it
        is Python's, and this holds them to it."""
        text = (REPO_ROOT / doc).read_text(encoding="utf-8")
        assert set(re.findall(r"([\d,]+)\s+digits", text)) == {f"{LIMIT:,}"}
