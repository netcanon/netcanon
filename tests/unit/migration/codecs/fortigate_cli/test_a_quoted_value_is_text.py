"""A FortiOS quoted value of several lines is text, not config.

FortiOS prints a value of several lines -- a replacement message's
HTML, a certificate, a private key, as the committed captures show --
as it is, between its quotes, a quote or a backslash in it escaped with
a backslash.  The parser read a configuration a line at a time, so each
line of such a value was a statement: a replacement message that held
an ``end`` line and then ``config system admin`` was an account with no
password on the IOS-XE and EOS targets, in jobs that said
``completed``; a line ``end`` in an alias closed the block it was in,
and the configuration after it was read as nothing; a line of HTML that
read ``config firewall policy`` was a Tier-3 row the config did not
have; and a ``#config-version`` line in a buffer was the config's
release.

Now a statement whose quoted value runs on is read whole, up to the
line that ends its quote (``parse._statements``), the readers of the
text other than the block parser read it with the value's lines emptied
(``without_quoted_values``), and a value that no line ends is refused
in words.  Tested here:

(a) each shape: a replacement message that holds config, an ``end`` in
    a value, escapes, a ``#`` comment, a version line, a Tier-3 header;
(b) a value of several lines reaches every target on one line, and the
    job says so (the rule is ``netcanon.migration._one_line``'s);
(c) the refusals, with their sentences;
(d) every committed FortiOS input against a reader of quoted values,
    by the character, that the test owns;
(e) each check, handed the defect it is for, fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration._one_line import said
from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.fortigate_cli import parse as fg_parse
from netcanon.migration.codecs.fortigate_cli.parse import (
    UNENDED_VALUE_MESSAGE,
    without_quoted_values,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.models.migration import MigrationJobStatus
from netcanon.services.migration_pipeline import run_plan

_FIXTURES = Path(__file__).resolve().parents[4] / "fixtures"
_NL = chr(10)
#: A quote as FortiOS prints one inside a quoted value.
_Q = chr(92) + '"'


def _config(*lines: str) -> str:
    return _NL.join(lines) + _NL


_INTERFACE = (
    "config system interface",
    '    edit "port1"',
    "        set ip 192.0.2.1 255.255.255.0",
    '        set alias "LAN"',
    "    next",
    "end",
)

#: A replacement message whose HTML holds what reads as configuration:
#: an ``end`` that would close the block, an administrator, a policy
#: block and a version line.
_A_MESSAGE_THAT_HOLDS_CONFIG = _config(
    'config system replacemsg admin "pre_admin-disclaimer-text"',
    '    set buffer "<html>',
    "end",
    "config system admin",
    "    edit " + _Q + "intruder" + _Q,
    "        set accprofile " + _Q + "super_admin" + _Q,
    "    next",
    "end",
    "config firewall policy",
    "    edit 1",
    "    next",
    "end",
    "#config-version=FG100E-9.9.9-FW-build9999-990101:opmode=0:vdom=0:user=x",
    '</html>"',
    "end",
    *_INTERFACE,
)


def _parse(raw: str):
    return get_codec("fortigate_cli").parse(raw)


def _port1(raw: str):
    (port1,) = [iface for iface in _parse(raw).interfaces if iface.name == "port1"]
    return port1


# ---------------------------------------------------------------------------
# (a) Each shape
# ---------------------------------------------------------------------------


class TestAMessageThatHoldsConfig:
    def test_no_account_is_read_from_it(self) -> None:
        assert _parse(_A_MESSAGE_THAT_HOLDS_CONFIG).local_users == []

    def test_the_config_after_it_is_read(self) -> None:
        port1 = _port1(_A_MESSAGE_THAT_HOLDS_CONFIG)
        assert port1.description == "LAN"
        assert [a.ip for a in port1.ipv4_addresses] == ["192.0.2.1"]

    def test_no_row_is_read_from_it(self) -> None:
        assert _parse(_A_MESSAGE_THAT_HOLDS_CONFIG).dropped_tier3_sections == []

    def test_no_release_is_read_from_it(self) -> None:
        assert _parse(_A_MESSAGE_THAT_HOLDS_CONFIG).source_version != "9.9.9"

    @pytest.mark.parametrize("target", list_public_codecs())
    def test_no_target_writes_the_account(self, target: str) -> None:
        job = run_plan(
            get_codec("fortigate_cli"), get_codec(target), _A_MESSAGE_THAT_HOLDS_CONFIG,
        )
        assert job.status is MigrationJobStatus.completed or job.status is MigrationJobStatus.partial
        assert "intruder" not in (job.rendered or "")


class TestWhereAValueEnds:
    def test_an_end_inside_a_value_closes_nothing(self) -> None:
        port1 = _port1(_config(
            "config system interface",
            '    edit "port1"',
            '        set alias "first',
            "end",
            'last"',
            "        set ip 192.0.2.1 255.255.255.0",
            "    next",
            "end",
        ))
        assert port1.description == _NL.join(["first", "end", "last"])
        assert [a.ip for a in port1.ipv4_addresses] == ["192.0.2.1"]

    def test_an_escaped_quote_ends_no_value(self) -> None:
        port1 = _port1(_config(
            "config system interface",
            '    edit "port1"',
            '        set alias "say ' + _Q + "hi" + _Q,
            'there"',
            "        set ip 192.0.2.1 255.255.255.0",
            "    next",
            "end",
        ))
        assert port1.description == 'say "hi' + '"' + _NL + "there"
        assert [a.ip for a in port1.ipv4_addresses] == ["192.0.2.1"]

    def test_an_escaped_backslash_before_a_quote_ends_the_value(self) -> None:
        backslash = chr(92)
        port1 = _port1(_config(
            "config system interface",
            '    edit "port1"',
            '        set alias "C:' + backslash + backslash + '"',
            "        set ip 192.0.2.1 255.255.255.0",
            "    next",
            "end",
        ))
        assert port1.description == "C:" + backslash
        assert [a.ip for a in port1.ipv4_addresses] == ["192.0.2.1"]

    def test_a_value_of_one_line_with_an_escaped_quote_is_one_line(self) -> None:
        port1 = _port1(_config(
            "config system interface",
            '    edit "port1"',
            '        set alias "a ' + _Q + ' b"',
            "        set ip 192.0.2.1 255.255.255.0",
            "    next",
            "end",
        ))
        assert port1.description == 'a " b'
        assert [a.ip for a in port1.ipv4_addresses] == ["192.0.2.1"]

    def test_a_comment_opens_no_value(self) -> None:
        raw = _config('#comment="unbalanced', *_INTERFACE)
        assert without_quoted_values(raw) == raw
        assert _port1(raw).description == "LAN"

    def test_a_text_with_no_such_value_is_returned_as_it_is(self) -> None:
        raw = _config(*_INTERFACE)
        assert without_quoted_values(raw) is raw

    def test_the_lines_of_a_value_are_emptied_keeping_their_numbers(self) -> None:
        raw = _config(
            'config system replacemsg admin "x"',
            '    set buffer "a',
            "config firewall policy",
            'b"',
            "end",
        )
        assert without_quoted_values(raw).split(_NL) == [
            'config system replacemsg admin "x"', "", "", "", "end", "",
        ]

    def test_a_crlf_text_parses_as_its_lf_form(self) -> None:
        raw = _A_MESSAGE_THAT_HOLDS_CONFIG
        crlf = raw.replace(_NL, chr(13) + _NL)
        assert _parse(crlf).model_dump() == _parse(raw).model_dump()


# ---------------------------------------------------------------------------
# (b) Through the pipeline
# ---------------------------------------------------------------------------

_AN_ALIAS_OF_TWO_LINES = _config(
    "config system interface",
    '    edit "port1"',
    "        set ip 192.0.2.1 255.255.255.0",
    '        set alias "core',
    'link"',
    "    next",
    "end",
)


@pytest.mark.parametrize("target", list_public_codecs())
def test_an_alias_of_two_lines_is_one_line_on_every_target(target: str) -> None:
    job = run_plan(get_codec("fortigate_cli"), get_codec(target), _AN_ALIAS_OF_TWO_LINES)
    assert job.status is not MigrationJobStatus.failed, job.error
    assert said("interfaces[port1].description") in job.warnings
    lines = (job.rendered or "").splitlines()
    assert not [line for line in lines if line.strip().strip('"').startswith("link")]


def test_an_alias_of_two_lines_is_written_with_a_space() -> None:
    job = run_plan(
        get_codec("fortigate_cli"), get_codec("cisco_iosxe_cli"), _AN_ALIAS_OF_TWO_LINES,
    )
    assert " description core link" in (job.rendered or "").splitlines()


# ---------------------------------------------------------------------------
# (c) The refusals
# ---------------------------------------------------------------------------


class TestTheRefusals:
    def test_a_value_no_line_ends(self) -> None:
        raw = _config(*_INTERFACE, 'config system replacemsg admin "x"', '    set buffer "secret words')
        with pytest.raises(ParseError) as refused:
            _parse(raw)
        message = str(refused.value)
        assert message == UNENDED_VALUE_MESSAGE.format(line=len(_INTERFACE) + 2)
        assert "secret" not in message

    def test_the_job_says_it_in_words(self) -> None:
        raw = _config('config system replacemsg admin "x"', '    set buffer "secret words')
        job = run_plan(get_codec("fortigate_cli"), get_codec("cisco_iosxe_cli"), raw)
        assert job.status is MigrationJobStatus.failed
        assert "opens a quoted value that no later line ends" in (job.error or "")
        assert "secret" not in (job.error or "")

    @pytest.mark.parametrize(
        "end", [chr(11), chr(12), chr(13), chr(0x85), chr(0x2028)],
        ids=["vt", "ff", "cr", "nel", "ls"],
    )
    def test_a_line_of_a_value_a_device_would_not_end_there(self, end: str) -> None:
        raw = (
            'config system replacemsg admin "x"' + _NL
            + '    set buffer "a' + end + "b" + _NL
            + 'c"' + _NL + "end" + _NL
        )
        with pytest.raises(ParseError, match="line 2"):
            _parse(raw)


# ---------------------------------------------------------------------------
# (d) Every committed input, against a reader of the test's own
# ---------------------------------------------------------------------------


def _spans(raw: str) -> list[tuple[int, int]]:
    """The lines (from 1) each quoted value of several lines opens and
    ends on, read a character at a time: a ``"`` opens or ends a value,
    a backslash takes the character after it, and a line that begins
    with ``#`` outside a value is a comment."""
    spans: list[tuple[int, int]] = []
    line, opened, inside, at_start, comment = 1, 0, False, True, False
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == _NL:
            line, at_start, comment = line + 1, True, False
            index += 1
            continue
        if at_start and not inside and char not in " \t":
            comment = char == "#"
            at_start = False
        if comment:
            index += 1
            continue
        if char == chr(92):
            if raw[index + 1:index + 2] == _NL:
                line += 1
                at_start = True
            index += 2
            continue
        if char == '"':
            if inside and line != opened:
                spans.append((opened, line))
            inside, opened = not inside, line
        index += 1
    assert not inside
    return spans


def _inputs() -> list[Path]:
    found = sorted((_FIXTURES / "real" / "fortigate").iterdir())
    found += sorted((_FIXTURES / "synthetic" / "fortigate_cli").iterdir())
    return [path for path in found if path.suffix == ".conf"]


@pytest.mark.parametrize("path", _inputs(), ids=lambda path: path.name)
class TestEveryCommittedInput:
    def test_the_lines_emptied_are_the_values_the_reader_finds(self, path: Path) -> None:
        raw = path.read_text(encoding="utf-8")
        expected = {n for start, stop in _spans(raw) for n in range(start, stop + 1)}
        before = raw.split(_NL)
        after = without_quoted_values(raw).split(_NL)
        pairs = list(enumerate(zip(before, after, strict=True), 1))
        # A line of a value is empty after; every other is as it was.
        assert [n for n, (_, b) in pairs if n in expected and b] == []
        assert [n for n, (a, b) in pairs if n not in expected and a != b] == []
        assert {n for n, (a, b) in pairs if a != b} <= expected

    def test_the_statements_are_the_values_the_reader_finds(self, path: Path) -> None:
        raw = path.read_text(encoding="utf-8")
        line, joined = 1, []
        for statement in fg_parse._statements(raw):
            count = statement.count(_NL)
            if count:
                joined.append((line, line + count))
            line += count + 1
        assert joined == _spans(raw)


def test_a_committed_input_holds_values_of_several_lines() -> None:
    """Else the comparison above compares nothing."""
    assert sum(len(_spans(path.read_text(encoding="utf-8"))) for path in _inputs()) > 100


# ---------------------------------------------------------------------------
# (e) Each check, handed its defect
# ---------------------------------------------------------------------------


class TestTheChecksCanFail:
    def test_the_reader_finds_a_value_of_several_lines(self) -> None:
        raw = _config('set a "x', 'y"', 'set b "' + _Q + '"', '# "', 'set c "p', "q", 'r"')
        assert _spans(raw) == [(1, 2), (5, 7)]

    def test_read_a_line_at_a_time_the_message_is_an_account(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With the parser reading a line at a time, and the readers of
        the text reading it as it is, every assertion above fails."""
        monkeypatch.setattr(fg_parse, "_statements", lambda raw: iter(raw.splitlines()))
        monkeypatch.setattr(fg_parse, "without_quoted_values", lambda raw: raw)
        tree = get_codec("fortigate_cli").parse(_A_MESSAGE_THAT_HOLDS_CONFIG)
        assert [user.name for user in tree.local_users] == [_Q + "intruder" + chr(92)]
        assert tree.source_version == "9.9.9"
