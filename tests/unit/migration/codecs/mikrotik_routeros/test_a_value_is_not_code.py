"""A value of the tree is text on RouterOS, never script.

A RouterOS device reads an imported config as script (MikroTik,
"Scripting": https://help.mikrotik.com/docs/spaces/ROS/pages/47579229/Scripting).
Outside a string, white space parts two words, ``;`` ends the command,
``$`` substitutes a variable, ``[ ]``, ``( )`` and ``{ }`` open a
command, an expression and a scope, ``#`` opens a comment and a
backslash is refused.  Inside one, ``$name``, ``$[...]`` and ``$(...)``
are substituted -- by a variable, by what a command returns, by what an
expression returns.

The renderer wrote a bond's members, a route's gateway, the SNMP
community and trap targets, a RADIUS server's address and secret, a
DHCP network's options, a user's name and the DNS and NTP servers as
they stood, and quoted the others only for white space, a quote or a
backslash; and it escaped no ``$`` inside any string.  An interface
description holding ``$[/system reset-configuration]`` -- from any
source vendor, where it is a description -- was that command on the
router that imported the output.  A port named ``my port`` broke its
own bond and route; a passphrase holding ``$1`` came out as another
passphrase.

Tested here:

(a) a reader of the output written for this test, from the MikroTik
    page and not from the renderer: what in a line RouterOS reads as
    script, a ``$`` a string does not escape, a word that is not a
    ``key=value``;
(b) a tree built from the schema, a value holding every character of
    the script in every place that holds text, through each branch of
    the renderer: the reader finds nothing, and the values reach the
    output in every key a hand-typed list names;
(c) each value the parser reads comes back as it was;
(d) a description from another vendor, through the pipeline;
(e) every committed input onto RouterOS;
(f) each check, handed the defect it is for, fails.
"""

from __future__ import annotations

import re
import types
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints
from unittest import mock

import pytest
from pydantic import BaseModel

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalStaticRoute,
)
from netcanon.migration.codecs.mikrotik_routeros import parse as ros_parse
from netcanon.migration.codecs.mikrotik_routeros import render as ros_render
from netcanon.migration.codecs.registry import get_codec
from netcanon.migration.fixture_dirs import DIR_TO_CODEC_NAME
from netcanon.services.migration_pipeline import run_plan

_FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"

#: Every character of the script, a quote, a backslash and white space.
_HOSTILE = 'x y;$[/system reset-configuration]$(1)$v#"\\{z}'


# ---------------------------------------------------------------------------
# (a) The reader
# ---------------------------------------------------------------------------

#: Outside a string, the characters RouterOS reads as script.
_SCRIPT_OUTSIDE = frozenset(';$#[](){}\\')
#: The escapes the renderer writes in a string: a backslash, a quote, a
#: ``$``.  Any other is a backslash of the value that was not doubled.
_ESCAPES = frozenset('\\"$')
_KEY = re.compile(r"[a-z][a-z0-9-]*")
_PATH_WORD = re.compile(r"/?[a-z0-9-]+")


def _words(line: str) -> tuple[list[str], list[str]]:
    """The words of *line*, a string in one standing as ``"S"``, and
    what the line holds that RouterOS reads as script."""
    found: list[str] = []
    words: list[str] = []
    word = ""
    at = 0
    while at < len(line):
        char = line[at]
        if char == '"':
            at += 1
            while at < len(line) and line[at] != '"':
                if line[at] == "\\":
                    escaped = line[at + 1:at + 2]
                    if escaped not in _ESCAPES:
                        found.append(f"the escape \\{escaped} at {at}")
                    at += 2
                    continue
                if line[at] == "$":
                    found.append(f"a $ the string does not escape, at {at}")
                at += 1
            if at >= len(line):
                found.append("a string with no end")
            word += '"S"'
            at += 1
            continue
        if char in " \t":
            if word:
                words.append(word)
                word = ""
        else:
            word += char
        at += 1
    if word:
        words.append(word)
    return words, found


def _script_in(line: str) -> list[str]:
    """What *line* holds that RouterOS reads as script, where the
    renderer meant text.

    A comment line is text to its end (a value in it is one line by the
    rule every renderer is held to).  A path line is words of a path.
    A command is ``add`` or ``set``, the renderer's own ``[ find ...
    ]`` where it writes one, and then ``key=value`` words, each value a
    string or a word with nothing of the script in it.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return []
    words, found = _words(stripped)
    if stripped.startswith("/"):
        return found + [
            f"{word!r} in a path" for word in words if not _PATH_WORD.fullmatch(word)
        ]
    if words[0] not in ("add", "set"):
        found.append(f"{words[0]!r} where a command goes")
    rest = words[1:]
    if rest[:1] == ["["]:
        close = rest.index("]") if "]" in rest else len(rest)
        predicate, rest = rest[1:close], rest[close + 1:]
        if predicate[:1] != ["find"] or len(predicate) != 2:
            found.append(f"a predicate {predicate!r}")
        rest = predicate[1:] + rest
    for word in rest:
        key, eq, value = word.partition("=")
        if not eq or not _KEY.fullmatch(key) or not value:
            found.append(f"{word!r} where a key=value goes")
            continue
        if value != '"S"':
            found += [
                f"{char!r} outside a string, in {word!r}"
                for char in value if char in _SCRIPT_OUTSIDE or char == '"'
            ]
    return found


def _script_in_text(text: str) -> list[str]:
    return [
        f"line {number}: {finding}: {line}"
        for number, line in enumerate(text.splitlines(), start=1)
        for finding in _script_in(line)
    ]


class TestTheReader:
    @pytest.mark.parametrize("line", [
        "/interface ethernet",
        "/ip dhcp-server network",
        "set [ find default-name=ether1 ] name=WAN disabled=no",
        'set [ find name="my port" ] comment="a \\"b\\" \\$c \\\\d" disabled=no',
        "add address=10.0.0.1/24 interface=ether1",
        "add dst-address=0.0.0.0/0 gateway=192.0.2.1%ether2",
        "set [ find default=yes ] name=public",
        "# review: a comment; $[x] {y}",
        "add slaves=ether1,ether2 mode=802.3ad name=bond1",
    ])
    def test_it_passes_what_the_renderer_means(self, line: str) -> None:
        assert _script_in(line) == []

    @pytest.mark.parametrize(("line", "what"), [
        ("add slaves=my port,ether2 name=bond1", "'port,ether2' where"),
        ("add secret=a;b", "';' outside a string"),
        ("set name=$x", "'$' outside a string"),
        ("add domain=a[b]", "'[' outside a string"),
        ("add domain=a(b)", "'(' outside a string"),
        ("add domain=a{b}", "'{' outside a string"),
        ("add domain=a#b", "'#' outside a string"),
        ('add comment="$[/system reset-configuration]"', "a $ the string does not escape"),
        ('add comment="a\\zb"', "the escape \\z"),
        ('add comment="open', "a string with no end"),
        ("set [ find default-name=ether1 ; ] name=x", "a predicate"),
        ("delete name=x", "'delete' where a command goes"),
    ])
    def test_it_finds_each_kind_of_script(self, line: str, what: str) -> None:
        assert any(what in finding for finding in _script_in(line)), _script_in(line)


# ---------------------------------------------------------------------------
# (b) Every place that holds text, through each branch
# ---------------------------------------------------------------------------

_NOTHING = object()


def _unwrapped(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, types.UnionType):
        kinds = [arg for arg in get_args(annotation) if arg is not type(None)]
        return kinds[0] if len(kinds) == 1 else annotation
    return annotation


def _built(annotation: Any, path: str, texts: list[str]) -> Any:
    """A value of *annotation* with a hostile text in every place that
    holds text.  A shape this does not know is refused, not skipped."""
    kind = _unwrapped(annotation)
    origin = get_origin(kind)
    if kind is str:
        texts.append(path)
        return f"v{len(texts)} {_HOSTILE}"
    if isinstance(kind, type) and issubclass(kind, BaseModel):
        return _record(kind, path, texts)
    if origin is list:
        (item,) = get_args(kind)
        one = _built(item, path, texts)
        return _NOTHING if one is _NOTHING else [one]
    if origin is dict:
        key, item = get_args(kind)
        return {_built(key, path, texts): _built(item, path, texts)}
    if kind in (int, bool, float):
        return _NOTHING
    raise AssertionError(f"{path}: a shape this builder does not fill ({kind!r})")


def _record(model: type[BaseModel], path: str, texts: list[str]) -> BaseModel:
    declared = get_type_hints(model)
    values: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        here = f"{path}.{name}" if path else name
        value = _built(declared[name], here, texts)
        if value is _NOTHING and field.is_required():
            value = {int: 10, bool: True, float: 1.0}[_unwrapped(declared[name])]
        if value is not _NOTHING:
            values[name] = value
    # Built without validation: a made-up value is not an address.
    return model.model_construct(**values)


#: The branches of the renderer, by the interface's type, typed here
#: rather than read from it.
_KINDS = (
    "ianaift:ethernetCsmacd",
    "ianaift:bridge",
    "ianaift:softwareLoopback",
    "ianaift:tunnel",
    "ianaift:l3ipvlan",
    "ianaift:ieee8023adLag",
)


def _hostile_tree(kind: str) -> CanonicalIntent:
    tree = _record(CanonicalIntent, "", [])
    assert isinstance(tree, CanonicalIntent)
    for iface in tree.interfaces:
        iface.interface_type = kind
        for group in iface.vrrp_groups:
            group.mode = "vrrp"
            group.authentication = f"plain:{_HOSTILE}"
    # A source whose SNMPv3 grammar is RouterOS's own, so that a v3
    # user is written rather than refused for its key.
    tree.source_vendor = "mikrotik_routeros"
    return tree


#: The keys a value of the tree is written under, typed by hand: the
#: test reaches each, or it would pass by writing nothing.
_KEYS_WITH_A_VALUE = {
    "name", "default-name", "comment", "slaves", "interface", "address",
    "dst-address", "gateway", "contact", "location", "trap-target",
    "secret", "ranges", "dns-server", "domain", "password", "servers",
    "authentication-password", "encryption-password",
}


def _keys_holding_a_value(text: str) -> set[str]:
    """The keys whose string in *text* holds one of the built values
    (``"v<n> x y;..."``), escaped."""
    escaped = ros_render._escape(_HOSTILE)
    keys: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for match in re.finditer(r'(?<![\w-])([a-z][a-z0-9-]*)="((?:\\.|[^"\\])*)"', line):
            if escaped in match.group(2):
                keys.add(match.group(1))
    return keys


class TestEveryPlace:
    @pytest.mark.parametrize("kind", _KINDS)
    def test_no_value_is_script(self, kind: str) -> None:
        text = ros_render.render_intent(_hostile_tree(kind))
        assert _script_in_text(text) == []

    def test_the_values_reach_every_key(self) -> None:
        reached: set[str] = set()
        for kind in _KINDS:
            reached |= _keys_holding_a_value(ros_render.render_intent(_hostile_tree(kind)))
        assert reached >= _KEYS_WITH_A_VALUE, _KEYS_WITH_A_VALUE - reached

    def test_a_bare_value_is_written_as_it_stands(self) -> None:
        """The common case does not move: a name, an address, a list."""
        for value in ("ether1", "sfp-sfpplus1", "ge-0/0/1", "10.0.0.0/24",
                      "fe80::1", "192.0.2.1%ether2", "ether1,ether2", "a_b.c"):
            assert ros_render._quote_if_needed(value) == value
        for value in ("", "my port", "a;b", "$x", "a#b", "a[b]", "é", "a=b", "a!"):
            assert ros_render._quote_if_needed(value).startswith('"'), value


# ---------------------------------------------------------------------------
# (c) What the parser reads comes back
# ---------------------------------------------------------------------------


def _round_trip_tree() -> CanonicalIntent:
    return CanonicalIntent(
        hostname=_HOSTILE,
        interfaces=[
            CanonicalInterface(
                name="ether1", default_name="ether1",
                interface_type="ianaift:ethernetCsmacd", description=_HOSTILE,
            ),
            CanonicalInterface(
                name="my port", interface_type="ianaift:ethernetCsmacd",
                description="b $[/user add name=x group=full]",
                ipv4_addresses=[CanonicalIPv4Address(ip="192.0.2.1", prefix_length=24)],
            ),
            CanonicalInterface(name="bond 1", interface_type="ianaift:ieee8023adLag"),
        ],
        lags=[CanonicalLAG(name="bond 1", members=["ether1", "my port"], mode="active")],
        static_routes=[
            CanonicalStaticRoute(
                destination="10.9.0.0/16", gateway="192.0.2.254",
                interface="my port", description=_HOSTILE,
            ),
            CanonicalStaticRoute(destination="10.8.0.0/16", interface="my port"),
        ],
        snmp=CanonicalSNMP(
            community="pub lic;$x", contact=_HOSTILE, location=_HOSTILE,
        ),
        radius_servers=[CanonicalRADIUSServer(host="192.0.2.10", key="s e;c$[r]et")],
        dhcp_servers=[CanonicalDHCPPool(
            network="10.1.0.0/24", start_ip="10.1.0.10", end_ip="10.1.0.99",
            gateway="10.1.0.1", domain_name="corp;$[x].example",
        )],
    )


class TestTheValueComesBack:
    def test_through_the_parser(self) -> None:
        codec = get_codec("mikrotik_routeros")
        tree = _round_trip_tree()
        text = codec.render(tree)
        assert _script_in_text(text) == []
        back = codec.parse(text)
        by_name = {i.name: i for i in back.interfaces}
        assert back.hostname == _HOSTILE
        assert by_name["ether1"].description == _HOSTILE
        assert by_name["my port"].description == "b $[/user add name=x group=full]"
        assert [(lag.name, lag.members) for lag in back.lags] == [
            ("bond 1", ["ether1", "my port"]),
        ]
        assert [
            (r.destination, r.gateway, r.interface, r.description)
            for r in back.static_routes
        ] == [
            ("10.9.0.0/16", "192.0.2.254", "my port", _HOSTILE),
            # A gateway that is an interface alone is read into
            # ``gateway``, as the parser always has: it does not tell a
            # name from an address there.
            ("10.8.0.0/16", "my port", "", ""),
        ]
        assert back.snmp is not None
        assert (back.snmp.community, back.snmp.contact, back.snmp.location) == (
            "pub lic;$x", _HOSTILE, _HOSTILE,
        )
        assert [s.key for s in back.radius_servers] == ["s e;c$[r]et"]
        assert [p.domain_name for p in back.dhcp_servers] == ["corp;$[x].example"]

    @pytest.mark.parametrize("name", ['a "b"', "a\\b", "a $b", "a;b"])
    def test_a_find_by_a_quoted_name(self, name: str) -> None:
        codec = get_codec("mikrotik_routeros")
        tree = CanonicalIntent(interfaces=[CanonicalInterface(
            name=name, interface_type="ianaift:ethernetCsmacd", description="d",
        )])
        text = codec.render(tree)
        assert f"set [ find name={ros_render._quote_if_needed(name)} ]" in text
        assert [(i.name, i.description) for i in codec.parse(text).interfaces] == [(name, "d")]

    def test_a_find_by_a_quoted_default_name(self) -> None:
        tree = get_codec("mikrotik_routeros").parse(
            '/interface ethernet\nset [ find default-name="ether 1" ] name=WAN\n'
        )
        assert [(i.name, i.default_name) for i in tree.interfaces] == [("WAN", "ether 1")]


# ---------------------------------------------------------------------------
# (d) From another vendor, through the pipeline
# ---------------------------------------------------------------------------

_IOSXE = """\
hostname r1
!
interface GigabitEthernet1
 description $[/system reset-configuration]
 ip address 192.0.2.1 255.255.255.0
!
end
"""


def test_a_description_from_another_vendor_is_text() -> None:
    job = run_plan(get_codec("cisco_iosxe_cli"), get_codec("mikrotik_routeros"), _IOSXE)
    assert job.rendered
    assert 'comment="\\$[/system reset-configuration]"' in job.rendered
    assert _script_in_text(job.rendered) == []
    back = get_codec("mikrotik_routeros").parse(job.rendered)
    assert "$[/system reset-configuration]" in [i.description for i in back.interfaces]


# ---------------------------------------------------------------------------
# (e) Every committed input
# ---------------------------------------------------------------------------

_NOT_A_CAPTURE = {".md", ".py", ".pyc", ".json", ".yaml", ".yml"}


def _inputs() -> list[tuple[str, str]]:
    found = []
    for directory, codec_name in DIR_TO_CODEC_NAME.items():
        for tier in ("real", "synthetic"):
            root = _FIXTURES / tier / directory
            if root.is_dir():
                found += [
                    (path.relative_to(_FIXTURES).as_posix(), codec_name)
                    for path in sorted(root.iterdir())
                    if path.is_file() and path.suffix.lower() not in _NOT_A_CAPTURE
                ]
    return found


_INPUTS = _inputs()


def test_there_are_inputs() -> None:
    assert len(_INPUTS) > 50


@pytest.mark.parametrize(("path", "source"), _INPUTS, ids=[p for p, _ in _INPUTS])
def test_every_committed_input(path: str, source: str) -> None:
    raw = (_FIXTURES / path).read_text(encoding="utf-8", errors="replace")
    job = run_plan(get_codec(source), get_codec("mikrotik_routeros"), raw)
    assert _script_in_text(job.rendered or "") == []


# ---------------------------------------------------------------------------
# (f) The checks fail on the defect
# ---------------------------------------------------------------------------


def _old_quote(value: str) -> str:
    """The rule this change replaced: white space, a quote, a backslash."""
    if not value:
        return '""'
    if any(c in value for c in ' \t\n"\\'):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _old_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class TestTheChecksCanFail:
    def test_with_no_escape_of_a_dollar_a_description_is_script(self) -> None:
        with mock.patch.object(ros_render, "_escape", _old_escape):
            job = run_plan(
                get_codec("cisco_iosxe_cli"), get_codec("mikrotik_routeros"), _IOSXE,
            )
        assert any("does not escape" in f for f in _script_in_text(job.rendered or ""))

    @pytest.mark.parametrize("kind", _KINDS)
    def test_with_the_old_rule_every_branch_is_script(self, kind: str) -> None:
        with mock.patch.object(ros_render, "_quote_if_needed", _old_quote), \
                mock.patch.object(ros_render, "_escape", _old_escape):
            text = ros_render.render_intent(_hostile_tree(kind))
        assert _script_in_text(text)

    def test_a_value_written_bare_is_found_by_its_key(self) -> None:
        """The keys the renderer wrote as they stood, from any value:
        written so again, each is found, by name."""
        with mock.patch.object(ros_render, "_quote_if_needed", lambda value: value):
            text = ros_render.render_intent(_hostile_tree("ianaift:ethernetCsmacd"))
        for key in ("slaves", "gateway", "secret", "domain", "servers", "dns-server",
                    "trap-target", "dst-address", "ranges", "address"):
            lines = [line for line in text.splitlines() if f" {key}=v" in line]
            assert lines, key
            assert all(_script_in(line) for line in lines), key

    @pytest.mark.parametrize(("pattern", "text"), [
        (
            "_FIND_NAME_RE",
            '/interface ethernet\nset [ find name="a \\"b\\"" ] comment=d\n',
        ),
        (
            "_FIND_DEFAULT_NAME_RE",
            '/interface ethernet\nset [ find default-name="ether 1" ] name=WAN\n',
        ),
    ])
    def test_with_the_old_find_patterns_the_interface_is_lost(
        self, pattern: str, text: str,
    ) -> None:
        """Read by the patterns this change replaced -- a string with
        no escape in it, a word with no quote -- such a line was no
        interface at all."""
        old = {
            "_FIND_NAME_RE": re.compile(r'\[\s*find\s+name=(?:"([^"]*)"|(\S+?))\s*\]'),
            "_FIND_DEFAULT_NAME_RE": re.compile(
                r'\[\s*find\s+default-name=(?:"(\x00)"|(\S+))\s*\]'
            ),
        }[pattern]
        codec = get_codec("mikrotik_routeros")
        assert codec.parse(text).interfaces
        with mock.patch.object(ros_parse, pattern, old):
            assert codec.parse(text).interfaces == []
