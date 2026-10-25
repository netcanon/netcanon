"""No value of the tree is written with a control character, whatever the
field and whatever the target.

A parser that reads its config as text keeps a control character that a
value holds -- an escape, a backspace, a C1 control -- and every
renderer put the value into its line as it stands.  An IOS-XE
description holding ``ESC [1A ESC [2K`` (up a line, erase it) was
written into every line-based target's output, and an operator reading
that output on a terminal did not see the line above it.  RouterOS
writes such a byte as an escape (``\\1B``), which its parser now reads.

``netcanon.migration._one_line``: the pipeline writes each run of them
as a space, after the transforms, and says where in the job's warnings;
``CodecBase.render`` refuses a tree that still holds one.  The tree is
built as the one-line rule's test builds it
(``test_a_value_is_one_line.py``).  Tested here:

(a) the characters are those Unicode calls control characters, but a
    tab and the line breaks, over every code point;
(b) a tree built from the schema, a control character in every place
    that holds text: each is found and mended, and each is found on its
    own by the render's check;
(c) every public codec's render refuses such a tree, naming the field
    and nothing of the value;
(d) the sources that put one into the tree, onto every public codec: no
    control character in the output, and the job says where;
(e) a secret that held one: never written without it, and where it is
    written it is with a space -- another secret, on the targets pinned
    here (a stated limitation);
(f) the sanitiser renders such a config;
(g) each check, handed the defect it is for, fails.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from netcanon.migration import _one_line
from netcanon.migration._one_line import (
    CONTROL_CHARACTERS,
    LINE_BREAKS,
    first_control_character,
    said_of_a_control_character,
    text_only_each,
)
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
)
from netcanon.migration.codecs.base import RenderError
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan
from netcanon.tools.sanitize import sanitize_text
from tests.unit.migration.test_a_value_is_one_line import (
    _PLACES,
    _field,
    _held,
    _record,
)
from tests.unit.migration.test_a_value_is_one_line import (
    _Slots as _BrokenSlots,
)

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"

_ESC = chr(0x1B)
#: Up a line, and erase it: what a terminal does with the value.
_ERASE = f"{_ESC}[1A{_ESC}[2K"
_TARGETS = sorted(list_public_codecs())


def _controls(text: str) -> list[str]:
    """The control characters *text* holds, by code point: read with
    ``unicodedata``, not with the module's own list."""
    return sorted({
        f"U+{ord(char):04X}" for char in text
        if unicodedata.category(char) == "Cc"
        and char not in "\t\n\r"
    })


# ---------------------------------------------------------------------------
# (a) The characters
# ---------------------------------------------------------------------------


def _every_point() -> list[str]:
    return [
        chr(point) for point in range(sys.maxunicode + 1)
        if not 0xD800 <= point <= 0xDFFF
    ]


class TestTheCharacters:
    def test_they_are_the_control_characters_but_a_tab_and_the_breaks(self) -> None:
        controls = {char for char in _every_point() if unicodedata.category(char) == "Cc"}
        assert set(CONTROL_CHARACTERS) == controls - {"\t"} - set(LINE_BREAKS)
        assert len(CONTROL_CHARACTERS) == len(set(CONTROL_CHARACTERS))

    def test_the_pattern_finds_each_and_nothing_else(self) -> None:
        for char in _every_point():
            found = _one_line._A_CONTROL_RUN.search("a" + char + "b") is not None
            assert found == (char in CONTROL_CHARACTERS), hex(ord(char))

    def test_a_run_is_one_space(self) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="x", description="up" + _ERASE + "link\tA" + chr(0x9B) + "B"),
        ])
        assert text_only_each(tree) == ["interfaces[x].description"]
        assert tree.interfaces[0].description == "up [1A [2Klink\tA B"

    def test_a_tab_is_left_as_it_is(self) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="x", description="a\tb"),
        ])
        assert text_only_each(tree) == []
        assert tree.interfaces[0].description == "a\tb"


# ---------------------------------------------------------------------------
# (b) A control character in every place that holds text
# ---------------------------------------------------------------------------


class _Slots(_BrokenSlots):
    """The one-line test's slots, holding a control character where
    they held a break."""

    def text(self, path: str) -> str:
        number = len(self.paths)
        self.paths.append(path)
        if self.broken is None or self.broken == number:
            return f"v{number}{_ERASE}"
        return f"v{number}"


def _tree(broken: int | None) -> tuple[CanonicalIntent, list[str]]:
    slots = _Slots(broken)
    tree = _record(CanonicalIntent, "", slots)
    assert isinstance(tree, CanonicalIntent)
    return tree, slots.paths


class TestEveryPlace:
    def test_the_places_are_the_one_line_tests(self) -> None:
        assert _tree(-1)[1] == _PLACES

    def test_a_tree_with_none_is_left_as_it_was(self) -> None:
        tree, _ = _tree(-1)
        before = tree.model_dump_json(warnings=False)
        assert first_control_character(tree) is None
        assert text_only_each(tree) == []
        assert tree.model_dump_json(warnings=False) == before

    def test_every_place_is_found_and_mended(self) -> None:
        tree, paths = _tree(None)
        places = text_only_each(tree)
        assert sorted(_field(place) for place in places) == sorted(paths)
        held = _held(tree)
        assert [text for text in held if _controls(text)] == []
        mended = {text for text in held if "[2K" in text}
        assert mended == {f"v{n} [1A [2K" for n in range(len(paths))}
        assert first_control_character(tree) is None

    def test_the_render_check_finds_each_place_on_its_own(self) -> None:
        missed = []
        for number, path in enumerate(_PLACES):
            tree, _ = _tree(number)
            where = first_control_character(tree)
            if where is None or _field(where) != path:
                missed.append((path, where))
        assert missed == []

    def test_a_place_names_no_value(self) -> None:
        tree, _ = _tree(None)
        where = first_control_character(tree)
        assert where is not None and "v0" not in where and _ESC not in where

    def test_a_record_whose_name_holds_one_is_named_by_its_index(self) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="a" + _ESC + "b", description="c" + _ESC + "d"),
        ])
        assert text_only_each(tree) == ["interfaces[0].name", "interfaces[0].description"]

    def test_a_key_that_holds_one_is_mended_with_its_value(self) -> None:
        tree = CanonicalIntent(hostname="r1")
        tree.raw_sections = {"a" + _ESC + "b": "c", "d": "e"}
        assert text_only_each(tree) == ["raw_sections (a key)"]
        assert tree.raw_sections == {"a b": "c", "d": "e"}


# ---------------------------------------------------------------------------
# (c) Every render refuses a tree that holds one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("codec_name", _TARGETS)
class TestTheRenderRefuses:
    def test_a_description_that_holds_one(self, codec_name: str) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="port1", description="uplink" + _ERASE),
        ])
        with pytest.raises(RenderError) as refused:
            get_codec(codec_name).render(tree)
        message = str(refused.value)
        assert "(interfaces[].description) holds a control character" in message
        assert _ESC not in message and "uplink" not in message

    def test_one_in_any_place(self, codec_name: str) -> None:
        tree, _ = _tree(None)
        with pytest.raises(RenderError, match="holds a control character"):
            get_codec(codec_name).render(tree)

    def test_once_mended_it_renders_with_none(self, codec_name: str) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="port1", description="uplink" + _ERASE),
        ])
        text_only_each(tree)
        assert _controls(get_codec(codec_name).render(tree)) == []


# ---------------------------------------------------------------------------
# (d) The sources that can put one into the tree, onto every target
# ---------------------------------------------------------------------------


def _ios() -> str:
    raw = (_FIXTURES / "cisco_iosxe_cli" / "kitchen_sink.txt").read_text(encoding="utf-8")
    old = " description Uplink to core (LACP)"
    assert raw.count(old) == 1
    return raw.replace(old, " description Up" + _ERASE + "link")


def _routeros() -> str:
    """RouterOS writes the byte as an escape, which its parser reads."""
    return (
        "# by RouterOS 7.14\n"
        "/interface ethernet\n"
        'set [ find default-name=ether2 ] comment="Up\\1B[1A\\1B[2Klink"\n'
        "/ip address\n"
        "add address=192.0.2.1/24 interface=ether2 network=192.0.2.0\n"
    )


def _fortigate() -> str:
    raw = (_FIXTURES / "fortigate_cli" / "kitchen_sink.conf").read_text(encoding="utf-8")
    old = 'set alias "WAN-uplink"'
    assert raw.count(old) == 1
    return raw.replace(old, 'set alias "WAN' + _ESC + '[2K-uplink"')


def _opnsense() -> str:
    """XML 1.0 holds no C0 control but a tab and the breaks, not even as a
    reference; it holds the C1 controls, CSI among them."""
    raw = (_FIXTURES / "opnsense" / "kitchen_sink.xml").read_text(encoding="utf-8")
    old = "<descr>WAN uplink to upstream carrier</descr>"
    assert raw.count(old) == 1
    return raw.replace(old, "<descr>WAN uplink&#155;2K to upstream carrier</descr>")


#: Each source, its config, and the interface whose description holds
#: the control character.
_SOURCES = {
    "cisco_iosxe_cli": (_ios, "Port-channel1"),
    "mikrotik_routeros": (_routeros, "ether2"),
    "fortigate_cli": (_fortigate, "port1"),
    "opnsense": (_opnsense, "em0"),
}


@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_the_parse_holds_it(source: str) -> None:
    """What the source parser gave holds the character: the rule is the
    pipeline's, not the parser's."""
    text, name = _SOURCES[source]
    tree = get_codec(source).parse(text())
    (port,) = [iface for iface in tree.interfaces if iface.name == name]
    assert _controls(port.description or "") != []


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_no_output_holds_one(source: str, target: str) -> None:
    text, name = _SOURCES[source]
    job = run_plan(get_codec(source), get_codec(target), text())
    assert job.status is not MigrationJobStatus.failed, job.error
    assert _controls(job.rendered or "") == []
    assert said_of_a_control_character(f"interfaces[{name}].description") in job.warnings


# ---------------------------------------------------------------------------
# (e) A secret that held one
# ---------------------------------------------------------------------------

#: The targets that write a community holding white space in quotes, and
#: so write one that held a control character with a space in its place:
#: another secret, said in the job's warnings and not left out.  A stated
#: limitation (CHANGELOG, SECURITY.md); the change that leaves such a
#: secret out empties this pin.
_ANOTHER_SECRET_ON = {
    "aruba_aoss", "fortigate_cli", "juniper_junos", "mikrotik_routeros", "opnsense",
}


def _a_community_with_one() -> str:
    raw = (_FIXTURES / "cisco_iosxe_cli" / "kitchen_sink.txt").read_text(encoding="utf-8")
    old = "snmp-server community publicRO RO"
    assert raw.count(old) == 1
    return raw.replace(old, "snmp-server community ab" + _ESC + "cd RO")


def test_a_secret_is_never_written_without_it() -> None:
    """A space, not nothing: taken out, the character would leave
    ``abcd``, a secret nobody set, written with no review line."""
    another = set()
    for target in _TARGETS:
        job = run_plan(get_codec("cisco_iosxe_cli"), get_codec(target), _a_community_with_one())
        out = job.rendered or ""
        assert "abcd" not in out, target
        assert said_of_a_control_character("snmp.community") in job.warnings, target
        if "ab cd" in out:
            another.add(target)
    assert another == _ANOTHER_SECRET_ON


# ---------------------------------------------------------------------------
# (f) The sanitiser
# ---------------------------------------------------------------------------


def test_the_sanitiser_renders_a_config_that_holds_one() -> None:
    result = sanitize_text(_ios(), "cisco_iosxe_cli")
    assert _controls(result.sanitized_text) == []


# ---------------------------------------------------------------------------
# (g) Each check, handed its defect
# ---------------------------------------------------------------------------

#: Where a control character written as it stands reaches the output.
#: The two XML renderers fail the job instead: XML 1.0 cannot hold it.
_THE_DEFECT_SHOWS_ON = set(_TARGETS) - {"cisco_iosxe", "opnsense"}


def _without_the_rule() -> Any:
    return mock.patch.multiple(
        "netcanon.services.migration_pipeline", text_only_each=lambda tree: [],
    )


class TestTheChecksCanFail:
    def test_the_reader_of_the_output_sees_one(self) -> None:
        assert _controls(f" description Up{_ERASE}link\n") == ["U+001B"]
        assert _controls(f"a{chr(0x9B)}b\tc\r\n") == ["U+009B"]

    def test_with_no_rule_it_is_in_the_output(self) -> None:
        shows = set()
        with _without_the_rule(), mock.patch(
            "netcanon.migration.codecs.base.first_control_character", lambda tree: None,
        ):
            for target in _TARGETS:
                job = run_plan(get_codec("cisco_iosxe_cli"), get_codec(target), _ios())
                if _controls(job.rendered or ""):
                    shows.add(target)
        assert shows == _THE_DEFECT_SHOWS_ON

    def test_with_no_mend_the_render_refuses_the_tree(self) -> None:
        with _without_the_rule():
            job = run_plan(get_codec("cisco_iosxe_cli"), get_codec("arista_eos"), _ios())
        assert job.status is MigrationJobStatus.failed
        assert "holds a control character" in (job.error or "")
        assert _ESC not in (job.error or "") and "link" not in (job.error or "")

    def test_with_the_old_routeros_reading_no_byte_is_read(self) -> None:
        """Up to 0.7.7 the parser took ``\\1B`` for ``1B``: nothing for
        the rule to find, so (d) proves the RouterOS row only with the
        new reading."""
        from netcanon.migration.codecs.mikrotik_routeros import parse as ros_parse
        from tests.unit.migration.codecs.mikrotik_routeros.test_an_escape_is_read import (
            _old_unescape,
        )

        with mock.patch.object(ros_parse, "_unescape", _old_unescape):
            tree = get_codec("mikrotik_routeros").parse(_routeros())
        (port,) = [iface for iface in tree.interfaces if iface.name == "ether2"]
        assert _controls(port.description or "") == []
