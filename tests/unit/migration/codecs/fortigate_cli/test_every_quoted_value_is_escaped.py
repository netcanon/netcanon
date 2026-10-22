"""Every value the FortiOS renderer writes between quotes is escaped.

FortiOS quotes a name or a value with ``"`` and escapes inside the quotes
with ``\\``: the replacement messages of the committed FG-100E capture
print ``<html lang=\\"en\\">`` inside ``set buffer "..."``.  A value
written between quotes as it stands ends the quoted string at its first
``"``, and what follows is read as CLI words.  In a list that is another
entry: a LAG member ``port"1`` wrote ``set member "port"1" ...``.  The
renderer escaped a description, a host name and a user's name, and wrote
an interface's own name, a LAG's members, a VLAN's parent, a route's
device, a DHCP pool's interface and domain, a RADIUS server, the domain
and an NTP server as they stood.  And the parser read an ``edit`` name
with its outer quotes stripped and its escapes left in, so even an
escaped name came back as another name.

The output is read here by a reader of this module's own, a character at
a time, not by the codec's tokenizer; the parser is held to the same
values; and the renderer's source is read for any value between quotes
that is not escaped.  Each check is handed the defect it is for.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalDHCPPool,
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLAG,
    CanonicalRADIUSServer,
    CanonicalStaticRoute,
    CanonicalVlan,
)
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec
from netcanon.migration.codecs.fortigate_cli import parse as parse_module
from netcanon.migration.codecs.fortigate_cli import render as render_module

_QUOTE = 'port"1'
_BACKSLASH = "port\\2"
_LAG = 'agg"1'
_SVI = 'vl"20'


def _tree() -> CanonicalIntent:
    """A value holding a ``"`` or a ``\\`` in every place the renderer
    quotes.  Addresses hold a backslash only: one holding a ``"`` is
    left out before it is written (``_one_value``)."""
    return CanonicalIntent(
        hostname="fw1",
        domain="example\\lan",
        ntp_servers=["ntp\\1.example.net"],
        interfaces=[
            CanonicalInterface(
                name=_QUOTE,
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="192.0.2.1", prefix_length=24),
                ],
            ),
            CanonicalInterface(name=_BACKSLASH),
            CanonicalInterface(
                name=_LAG, interface_type="ianaift:ieee8023adLag",
            ),
            CanonicalInterface(
                name=_SVI,
                interface_type="ianaift:l3ipvlan",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="198.51.100.1", prefix_length=24),
                ],
            ),
        ],
        lags=[CanonicalLAG(name=_LAG, members=[_QUOTE, _BACKSLASH])],
        vlans=[CanonicalVlan(id=20, name=_SVI), CanonicalVlan(id=30)],
        static_routes=[
            CanonicalStaticRoute(
                destination="203.0.113.0/24",
                gateway="192.0.2.254",
                interface=_QUOTE,
            ),
        ],
        dhcp_servers=[
            CanonicalDHCPPool(
                interface=_QUOTE,
                network="192.0.2.0/24",
                start_ip="192.0.2.100",
                end_ip="192.0.2.200",
                domain_name="pool\\lan",
            ),
        ],
        radius_servers=[CanonicalRADIUSServer(host="radius\\1")],
    )


def _words(line: str) -> list[str]:
    """A FortiOS CLI line, a word at a time.

    Outside quotes a word ends at white space; a ``"`` opens a quoted
    string, in which ``\\`` takes the next character as it stands and a
    ``"`` ends the string.  Raises ``ValueError`` for a line whose quotes
    are not closed.
    """
    words: list[str] = []
    word: list[str] = []
    in_word = quoted = escaped = False
    for ch in line:
        if quoted:
            if escaped:
                word.append(ch)
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
            else:
                word.append(ch)
        elif ch == '"':
            quoted = in_word = True
        elif ch.isspace():
            if in_word:
                words.append("".join(word))
                word, in_word = [], False
        else:
            word.append(ch)
            in_word = True
    if quoted or escaped:
        raise ValueError(f"a quote is not closed: {line!r}")
    if in_word:
        words.append("".join(word))
    return words


#: Each line the output must hold, as words.
_LINES = [
    ["set", "domain", "example\\lan"],
    ["set", "server", "ntp\\1.example.net"],
    ["edit", _QUOTE],
    ["edit", _LAG],
    ["set", "member", _QUOTE, _BACKSLASH],
    ["edit", _SVI],
    ["edit", "vlan30"],
    ["set", "interface", _LAG],
    ["set", "interface", _QUOTE],
    ["set", "device", _QUOTE],
    ["set", "domain", "pool\\lan"],
    ["set", "server", "radius\\1"],
]


def _misread_lines(output: str) -> list[str]:
    """What is wrong with *output*, read by :func:`_words`."""
    problems: list[str] = []
    read: list[list[str]] = []
    for line in output.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            read.append(_words(line))
        except ValueError as exc:
            problems.append(str(exc))
    for want in _LINES:
        if want not in read:
            problems.append(f"no line reads as {want!r}")
    return problems


def _misparsed(output: str) -> list[str]:
    """What the FortiOS parser reads otherwise than the tree holds."""
    back = FortiGateCLICodec().parse(output)
    names = {i.name for i in back.interfaces}
    lags = {lag.name: lag.members for lag in back.lags}
    problems = [
        f"no interface {name!r}" for name in (_QUOTE, _LAG, _SVI)
        if name not in names
    ]
    if lags.get(_LAG) != [_QUOTE, _BACKSLASH]:
        problems.append(f"LAG members {lags!r}")
    if [r.interface for r in back.static_routes] != [_QUOTE]:
        problems.append("the route's device")
    if [(p.interface, p.domain_name) for p in back.dhcp_servers] != [
        (_QUOTE, "pool\\lan"),
    ]:
        problems.append("the DHCP pool's interface or domain")
    if [r.host for r in back.radius_servers] != ["radius\\1"]:
        problems.append("the RADIUS server")
    if back.domain != "example\\lan":
        problems.append("the domain")
    if back.ntp_servers != ["ntp\\1.example.net"]:
        problems.append("the NTP server")
    return problems


def _between_quotes(source: str) -> list[tuple[str, bool]]:
    """Each value of an f-string in *source* that is written between
    two ``"``: where it is, and whether it goes through ``_esc``."""
    found: list[tuple[str, bool]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.JoinedStr):
            continue
        parts = node.values
        for i, part in enumerate(parts):
            if not isinstance(part, ast.FormattedValue):
                continue
            before = parts[i - 1] if i else None
            after = parts[i + 1] if i + 1 < len(parts) else None
            opens = (
                isinstance(before, ast.Constant)
                and str(before.value).endswith('"')
            )
            closes = (
                isinstance(after, ast.Constant)
                and str(after.value).startswith('"')
            )
            if not (opens and closes):
                continue
            value = part.value
            escaped = (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "_esc"
            )
            found.append(
                (f"line {node.lineno}: {ast.unparse(value)}", escaped),
            )
    return found


def _unescaped(source: str) -> list[str]:
    """Each value between quotes in *source* that skips ``_esc``."""
    return [where for where, escaped in _between_quotes(source) if not escaped]


_RENDER_SOURCE = Path(render_module.__file__).read_text(encoding="utf-8")


class TestEveryQuotedValueIsEscaped:
    def test_the_output_reads_as_the_tree(self) -> None:
        output = FortiGateCLICodec().render(_tree())
        assert _misread_lines(output) == []

    def test_the_parser_reads_each_value_back(self) -> None:
        output = FortiGateCLICodec().render(_tree())
        assert _misparsed(output) == []

    def test_no_value_between_quotes_skips_the_escape(self) -> None:
        assert _unescaped(_RENDER_SOURCE) == []

    def test_the_source_check_reads_the_renderer(self) -> None:
        # A walk that finds no place between quotes passes every source:
        # it has to find the places this module's tree goes through.
        places = " ".join(where for where, _ in _between_quotes(_RENDER_SOURCE))
        for expr in (
            "iface.name", "m)", "parent)", "route.interface",
            "pool.interface", "pool.domain_name", "server.host",
            "tree.domain", "child['name']",
        ):
            assert expr in places, expr

    def test_an_edit_id_is_read_as_a_value_is(self) -> None:
        assert parse_module._edit_id('"a\\"b"') == 'a"b'
        assert parse_module._edit_id('"a\\\\b"') == "a\\b"
        assert parse_module._edit_id('"port 1"') == "port 1"
        assert parse_module._edit_id("7") == "7"
        # Not one token: the reading this change found, unaltered.
        assert parse_module._edit_id('"unbalanced') == "unbalanced"


class TestEachCheckSeesItsDefect:
    @pytest.fixture
    def unescaped_render(self, monkeypatch: pytest.MonkeyPatch) -> str:
        monkeypatch.setattr(render_module, "_esc", lambda value: value)
        return FortiGateCLICodec().render(_tree())

    def test_the_reader_sees_a_value_written_as_it_stands(
        self, unescaped_render: str,
    ) -> None:
        assert _misread_lines(unescaped_render)

    def test_the_parser_check_sees_a_value_written_as_it_stands(
        self, unescaped_render: str,
    ) -> None:
        assert _misparsed(unescaped_render)

    def test_the_parser_check_sees_an_escape_left_in(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        output = FortiGateCLICodec().render(_tree())
        monkeypatch.setattr(
            parse_module, "_edit_id",
            lambda text: text.strip().strip('"').strip("'"),
        )
        assert _misparsed(output)

    def test_the_source_check_sees_a_value_written_as_it_stands(self) -> None:
        source = "x = f'    edit \"{name}\"'\ny = f'set a \"{_esc(v)}\"'\n"
        assert _unescaped(source) == ["line 1: name"]
