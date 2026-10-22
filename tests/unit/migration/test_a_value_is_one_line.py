"""A value of the tree is written on one line, whatever the field and
whatever the target.

Every renderer puts a value into its line as it stands, so a value that
held a line break was written as lines of its own, and the text after
the break was a command: an interface description that held ``username
intruder privilege 15 nopassword`` after a break was that account on
every line-based target, in a job that said ``completed``.  The parsers
that read XML (OPNsense, IOS-XE over NETCONF) keep a break that an
element's text holds, and FortiOS prints a value of several lines
between its quotes, so the tree can hold one.

``netcanon.migration._one_line``: the pipeline writes each run of breaks
as a space, after the transforms, and says where in the job's warnings;
``CodecBase.render`` refuses a tree that still holds one.  Tested here:

(a) the characters are those ``str.splitlines`` ends a line at, over
    every code point;
(b) a tree built from the schema, a value with a break in every place
    that holds text: each is found and mended, read back from the tree's
    JSON, and each is found on its own by the render's check;
(c) every public codec's render refuses such a tree, naming the field
    and nothing of the value;
(d) the sources that put a break into the tree, onto every public codec:
    no line of the output is the value's second line, and the job says
    where it wrote one line;
(e) the sanitiser renders such a config;
(f) each check, handed the defect it is for, fails.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints
from unittest import mock

import pytest
from pydantic import BaseModel, create_model

from netcanon.migration import _one_line
from netcanon.migration._one_line import (
    LINE_BREAKS,
    first_line_break,
    one_line_each,
    said,
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

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"

#: The value's second line: an account with no password, in the grammar
#: of most line-based targets.
_COMMAND = "username intruder privilege 15 nopassword"
_NL = chr(10)


def _injected(text: str) -> list[str]:
    """The lines of *text* that BEGIN with the command: written as a line
    of its own, not inside the line of the value that held it."""
    return [
        line for line in text.splitlines()
        if line.strip().strip('"').startswith(_COMMAND)
    ]


# ---------------------------------------------------------------------------
# (a) The characters
# ---------------------------------------------------------------------------


class TestTheCharacters:
    def test_they_are_what_splitlines_ends_a_line_at(self) -> None:
        ends = {
            chr(point) for point in range(sys.maxunicode + 1)
            if not 0xD800 <= point <= 0xDFFF
            and len(("a" + chr(point) + "b").splitlines()) == 2
        }
        assert set(LINE_BREAKS) == ends

    def test_the_pattern_finds_each_and_nothing_else(self) -> None:
        for point in range(sys.maxunicode + 1):
            if 0xD800 <= point <= 0xDFFF:
                continue
            found = _one_line._A_RUN.search("a" + chr(point) + "b") is not None
            assert found == (chr(point) in LINE_BREAKS), hex(point)

    def test_a_run_is_one_space(self) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="x", description="a" + LINE_BREAKS + "b" + _NL + _NL + "c"),
        ])
        assert one_line_each(tree) == ["interfaces[x].description"]
        assert tree.interfaces[0].description == "a b c"


# ---------------------------------------------------------------------------
# (b) A break in every place that holds text
# ---------------------------------------------------------------------------

#: A field of a shape that holds nothing to write.
_NOTHING = object()


class _Slots:
    """The text values of one built tree, in the order they are built.
    *broken* is the one slot whose value holds a break, ``None`` for
    every slot, ``-1`` for none."""

    def __init__(self, broken: int | None) -> None:
        self.broken = broken
        self.paths: list[str] = []

    def text(self, path: str) -> str:
        number = len(self.paths)
        self.paths.append(path)
        if self.broken is None or self.broken == number:
            return f"v{number}{_NL}{_COMMAND}"
        return f"v{number}"


def _unwrapped(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, types.UnionType):
        kinds = [arg for arg in get_args(annotation) if arg is not type(None)]
        return kinds[0] if len(kinds) == 1 else annotation
    return annotation


def _built(annotation: Any, path: str, slots: _Slots) -> Any:
    """A value of *annotation* with text in every place that holds it:
    one element in a list, one entry in a dict, a key of text included.
    A shape this does not know is refused, not skipped: left out, a
    field the walk does not reach would pass every test below."""
    kind = _unwrapped(annotation)
    origin = get_origin(kind)
    if kind is str:
        return slots.text(path)
    if isinstance(kind, type) and issubclass(kind, BaseModel):
        return _record(kind, path, slots)
    if origin is list:
        (item,) = get_args(kind)
        one = _built(item, path, slots)
        return _NOTHING if one is _NOTHING else [one]
    if origin is dict:
        key, item = get_args(kind)
        if _unwrapped(key) is not str:
            raise AssertionError(f"{path}: a dict whose keys are not text")
        return {_built(key, path, slots): _built(item, path, slots)}
    if kind in (int, bool, float):
        return _NOTHING
    raise AssertionError(f"{path}: a shape this builder does not fill ({kind!r})")


def _record(model: type[BaseModel], path: str, slots: _Slots) -> BaseModel:
    declared = get_type_hints(model)
    values: dict[str, Any] = {}
    for name in model.model_fields:
        here = f"{path}.{name}" if path else name
        value = _built(declared[name], here, slots)
        if value is not _NOTHING:
            values[name] = value
    # Built without validation: a made-up value is not an address.
    return model.model_construct(**values)


def _tree(broken: int | None) -> tuple[CanonicalIntent, list[str]]:
    slots = _Slots(broken)
    tree = _record(CanonicalIntent, "", slots)
    assert isinstance(tree, CanonicalIntent)
    return tree, slots.paths


def _field(place: str) -> str:
    """``interfaces[Gi1].vrrp_groups[].description`` ->
    ``interfaces.vrrp_groups.description``: the place by its fields."""
    return re.sub(r"\[[^\]]*\]| \(a key\)", "", place)


def _texts(node: Any) -> list[str]:
    """Every string a JSON document holds, keys included: what the tree
    holds, read without the walk."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [text for item in node for text in _texts(item)]
    if isinstance(node, dict):
        return [text for key, item in node.items() for text in [key, *_texts(item)]]
    return []


def _held(tree: BaseModel) -> list[str]:
    return _texts(json.loads(tree.model_dump_json(warnings=False)))


_PLACES = _tree(-1)[1]


class TestEveryPlace:
    def test_the_tree_holds_text_in_many_places(self) -> None:
        """Else the tests below compare nothing."""
        assert len(_PLACES) > 50
        assert "interfaces.description" in _PLACES
        assert "raw_sections" in _PLACES

    def test_a_tree_with_no_break_is_left_as_it_was(self) -> None:
        tree, _ = _tree(-1)
        before = tree.model_dump_json(warnings=False)
        assert first_line_break(tree) is None
        assert one_line_each(tree) == []
        assert tree.model_dump_json(warnings=False) == before

    def test_every_place_is_found_and_mended(self) -> None:
        tree, paths = _tree(None)
        places = one_line_each(tree)
        assert sorted(_field(place) for place in places) == sorted(paths)
        held = _held(tree)
        assert [text for text in held if text.splitlines() != [text] and text] == []
        mended = {text for text in held if _COMMAND in text}
        assert mended == {f"v{n} {_COMMAND}" for n in range(len(paths))}
        assert first_line_break(tree) is None

    def test_the_render_check_finds_each_place_on_its_own(self) -> None:
        missed = []
        for number, path in enumerate(_PLACES):
            tree, _ = _tree(number)
            where = first_line_break(tree)
            if where is None or _field(where) != path:
                missed.append((path, where))
        assert missed == []

    def test_a_place_names_no_value(self) -> None:
        """The render's check is said in an error, and an error is
        logged: its place names fields only."""
        tree, _ = _tree(None)
        where = first_line_break(tree)
        assert where is not None and "v0" not in where and _COMMAND not in where

    def test_a_record_whose_name_holds_the_break_is_named_by_its_index(self) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="a" + _NL + "b", description="c" + _NL + "d"),
        ])
        assert one_line_each(tree) == ["interfaces[0].name", "interfaces[0].description"]

    def test_a_value_a_parser_put_where_the_schema_says_numbers_go(self) -> None:
        """A list is not validated when a parser appends to it."""
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="x", trunk_allowed_vlans=[10, 20]),
        ])
        tree.interfaces[0].trunk_allowed_vlans.append("30" + _NL + _COMMAND)  # type: ignore[arg-type]
        assert first_line_break(tree) == "interfaces[].trunk_allowed_vlans"
        assert one_line_each(tree) == ["interfaces[x].trunk_allowed_vlans"]
        assert tree.interfaces[0].trunk_allowed_vlans[-1] == "30 " + _COMMAND

    def test_a_key_that_holds_a_break_is_mended_with_its_value(self) -> None:
        tree = CanonicalIntent(hostname="r1")
        tree.raw_sections = {"a" + _NL + "b": "c", "d": "e"}
        assert one_line_each(tree) == ["raw_sections (a key)"]
        assert tree.raw_sections == {"a b": "c", "d": "e"}


# ---------------------------------------------------------------------------
# (c) Every render refuses a tree that holds one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("codec_name", list_public_codecs())
class TestTheRenderRefuses:
    def test_a_description_that_holds_a_break(self, codec_name: str) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="port1", description="uplink" + _NL + _COMMAND),
        ])
        with pytest.raises(RenderError) as refused:
            get_codec(codec_name).render(tree)
        message = str(refused.value)
        assert "(interfaces[].description) holds a line break" in message
        assert _COMMAND not in message and "uplink" not in message

    def test_a_break_in_any_place(self, codec_name: str) -> None:
        tree, _ = _tree(None)
        with pytest.raises(RenderError, match="holds a line break"):
            get_codec(codec_name).render(tree)

    def test_once_mended_it_renders_and_writes_no_such_line(self, codec_name: str) -> None:
        tree = CanonicalIntent(hostname="r1", interfaces=[
            CanonicalInterface(name="port1", description="uplink" + _NL + _COMMAND),
        ])
        one_line_each(tree)
        assert _injected(get_codec(codec_name).render(tree)) == []


# ---------------------------------------------------------------------------
# (d) The sources that can put one into the tree, onto every target
# ---------------------------------------------------------------------------


def _with_a_break(source: str) -> str:
    """The source's synthetic config with a break in one interface's
    description, in the source's own form of it."""
    if source == "opnsense":
        raw = (_FIXTURES / "opnsense" / "kitchen_sink.xml").read_text(encoding="utf-8")
        old = "<descr>WAN uplink to upstream carrier</descr>"
        new = "<descr>WAN uplink&#10;" + _COMMAND + "</descr>"
    elif source == "cisco_iosxe":
        raw = (_FIXTURES / "cisco_iosxe" / "kitchen_sink.xml").read_text(encoding="utf-8")
        old = "<description>WAN uplink to upstream carrier</description>"
        new = "<description>WAN uplink&#10;" + _COMMAND + "</description>"
    else:
        raw = (_FIXTURES / "fortigate_cli" / "kitchen_sink.conf").read_text(encoding="utf-8")
        old = 'set alias "WAN-uplink"'
        new = 'set alias "WAN-uplink' + _NL + _COMMAND + '"'
    assert raw.count(old) == 1, source
    return raw.replace(old, new)


#: Each source, and the interface whose description holds the break.
_SOURCES = {
    "opnsense": "em0",
    "cisco_iosxe": "GigabitEthernet0/0/0",
    "fortigate_cli": "port1",
}


@pytest.mark.parametrize("target", list_public_codecs())
@pytest.mark.parametrize("source", sorted(_SOURCES))
def test_the_value_is_one_line_in_every_output(source: str, target: str) -> None:
    job = run_plan(get_codec(source), get_codec(target), _with_a_break(source))
    assert job.status is not MigrationJobStatus.failed, job.error
    assert _injected(job.rendered or "") == []
    assert said(f"interfaces[{_SOURCES[source]}].description") in job.warnings


def test_the_parse_holds_the_break_and_the_warning_says_why() -> None:
    """What the source parser gave is a value of two lines: the rule is
    the pipeline's, not the parser's."""
    tree = get_codec("opnsense").parse(_with_a_break("opnsense"))
    (wan,) = [iface for iface in tree.interfaces if iface.name == "em0"]
    assert wan.description == "WAN uplink" + _NL + _COMMAND
    assert "no target is given a value of more than one line" in said("x")


# ---------------------------------------------------------------------------
# (e) The sanitiser
# ---------------------------------------------------------------------------


def test_the_sanitiser_renders_a_config_that_holds_a_break() -> None:
    result = sanitize_text(_with_a_break("opnsense"), "opnsense")
    assert _injected(result.sanitized_text) == []


# ---------------------------------------------------------------------------
# (f) Each check, handed its defect
# ---------------------------------------------------------------------------

#: Where a break written as it stands puts the command on a line of its
#: own.  FortiOS writes an interface's description as an alias, cut to
#: its 25 characters and between quotes.
_THE_DEFECT_SHOWS_ON = set(list_public_codecs()) - {"fortigate_cli"}


def _without_the_rule() -> Any:
    return mock.patch.multiple(
        "netcanon.services.migration_pipeline", one_line_each=lambda tree: [],
    )


class TestTheChecksCanFail:
    def test_the_reader_of_the_output_sees_a_line_of_its_own(self) -> None:
        assert _injected(f"interface x{_NL} description up{_NL}{_COMMAND}{_NL}") == [_COMMAND]
        assert _injected(f" description up {_COMMAND}{_NL}") == []

    def test_with_no_rule_the_command_is_a_line_of_the_output(self) -> None:
        shows = set()
        with _without_the_rule(), mock.patch(
            "netcanon.migration.codecs.base.first_line_break", lambda tree: None,
        ):
            for target in list_public_codecs():
                job = run_plan(
                    get_codec("cisco_iosxe"), get_codec(target), _with_a_break("cisco_iosxe"),
                )
                if _injected(job.rendered or ""):
                    shows.add(target)
        assert shows == _THE_DEFECT_SHOWS_ON

    def test_with_no_mend_the_render_refuses_the_tree(self) -> None:
        with _without_the_rule():
            job = run_plan(
                get_codec("opnsense"), get_codec("cisco_iosxe_cli"), _with_a_break("opnsense"),
            )
        assert job.status is MigrationJobStatus.failed
        assert "holds a line break" in (job.error or "")
        assert _COMMAND not in (job.error or "")

    @pytest.mark.parametrize(
        "shape", [dict[int, str], tuple[str, ...], set[str], Any, str | int],
        ids=["int-keys", "tuple", "set", "any", "union"],
    )
    def test_the_builder_refuses_a_shape_it_does_not_fill(self, shape: Any) -> None:
        odd = create_model("Odd", holds=(shape, None))
        with pytest.raises(AssertionError):
            _record(odd, "", _Slots(None))
