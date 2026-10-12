"""The words of a Junos ``set`` line.

They were split by ``shlex.split``, which costs the square of the
longest word in the line: it adds a character at a time to a string
it keeps on itself.  ``_split_words`` reads the same words in time
that fits the line.

"The same" is the claim, and ``shlex`` is there to hold it to: every
short line there is over the characters that matter, and longer
lines at random, are split both ways and compared -- the words, or
the refusal.
"""

from __future__ import annotations

import itertools
import random
import shlex

import pytest

from netcanon.migration.codecs.juniper_junos.parse import _split_words, _tokenise_set

pytestmark = pytest.mark.unit


def _as_shlex(line: str) -> list[str] | str:
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return "refused"


def _as_ours(line: str) -> list[str] | str:
    try:
        return _split_words(line)
    except ValueError:
        return "refused"


#: White space, both quotes, the backslash, and something to quote.
_THAT_MATTER = " \t\"'\\a#"


def test_every_short_line_is_split_as_shlex_does() -> None:
    lines = 0
    for length in range(6):
        for chars in itertools.product(_THAT_MATTER, repeat=length):
            line = "".join(chars)
            assert _as_ours(line) == _as_shlex(line), repr(line)
            lines += 1
    # Lines that are refused and lines that are not were both there.
    assert lines > 19_000
    assert _as_ours('a "b') == "refused" and _as_ours("a\\") == "refused"


def test_longer_lines_are_split_as_shlex_does() -> None:
    """With the other characters a line can hold: the ends of lines,
    white space that is not a blank or a tab, and what the
    hierarchical form writes."""
    letters = " \t\r\n\"'\\ab#{};[]/*:" + chr(0x0C) + chr(0xA0) + chr(0xE9)
    pick = random.Random(20261011)
    for _ in range(6_000):
        line = "".join(pick.choice(letters) for _ in range(pick.randint(6, 40)))
        assert _as_ours(line) == _as_shlex(line), repr(line)


@pytest.mark.parametrize(
    ("line", "words"),
    [
        ("interfaces ge-0/0/1 unit 0 family inet address 10.0.0.1/24", None),
        ('interfaces ge-0/0/1 description "WAN uplink"', ["interfaces", "ge-0/0/1", "description", "WAN uplink"]),
        ('system login message "say \\"hello\\"\\n# {here};"', None),
        ("system login user bob authentication encrypted-password /* SECRET-DATA */", None),
        ('policy-options policy-statement "direct routes" then accept', None),
        ("interfaces  ge-0/0/1\tmtu   9000 ", ["interfaces", "ge-0/0/1", "mtu", "9000"]),
        ('snmp location ""', ["snmp", "location", ""]),
        ("system host-name r\\ 1", ["system", "host-name", "r 1"]),
        ("snmp contact 'a \"b\" c'", ["snmp", "contact", 'a "b" c']),
        ('a"b c"d', ["ab cd"]),
        ("", []),
        ("   ", []),
    ],
)
def test_the_lines_a_config_has(line: str, words: list[str] | None) -> None:
    assert _split_words(line) == shlex.split(line, posix=True)
    if words is not None:
        assert _split_words(line) == words


@pytest.mark.parametrize("line", ['description "never closed', "description 'never closed", "description ends\\"])
def test_a_line_that_is_refused_is_cut_at_its_spaces(line: str) -> None:
    """As before: a quote that never closes is a word like another."""
    with pytest.raises(ValueError):
        _split_words(line)
    with pytest.raises(ValueError):
        shlex.split(line, posix=True)
    assert _tokenise_set(line) == line.split()
