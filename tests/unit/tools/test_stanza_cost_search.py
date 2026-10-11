"""The stanza-count search: how it cuts a capture, and that it can find what it is for.

``tools/stanza_cost_search.py`` looks for parse work that grows faster
than the NUMBER of a config's stanzas, by writing each line and block
of every capture many times over.  It takes minutes and is run by hand;
what it found is pinned in ``tests/unit/test_untrusted_text_cost.py``.
A search that cannot find anything passes on every tree, so this pins
the two things it stands on: the units it cuts, and that a reader which
looks through what it has made is reported while one that finds by key
is not.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import list_public_codecs

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[3] / "tools" / "stanza_cost_search.py"
_spec = importlib.util.spec_from_file_location("stanza_cost_search", _PATH)
assert _spec is not None and _spec.loader is not None
tool = importlib.util.module_from_spec(_spec)
sys.modules["stanza_cost_search"] = tool
_spec.loader.exec_module(tool)

SAMPLE = """hostname sw
!
interface Ethernet1
   description uplink
   switchport access vlan 10
!
interface Ethernet2
   description uplink
   switchport access vlan 20
!
ip route 10.1.0.0/16 192.0.2.1
ip route 10.2.0.0/16 192.0.2.1
"""


class TestTheUnitsOfACapture:
    def test_each_line_and_each_block_once_per_shape(self) -> None:
        lines, spans = tool.units(SAMPLE)
        cut = ["\n".join(lines[first:end]) for first, end in spans]
        assert cut == [
            "hostname sw",
            "!",
            "interface Ethernet1",
            # A block takes the line that closes it.
            "interface Ethernet1\n   description uplink\n   switchport access vlan 10\n!",
            "   description uplink",
            "   switchport access vlan 10",
            # ``Ethernet2`` and the second route differ from the first
            # only in their numbers: the same units.
            "ip route 10.1.0.0/16 192.0.2.1",
        ]

    def test_a_block_too_long_to_be_a_stanza_is_not_a_unit(self) -> None:
        text = "router bgp 1\n" + "".join(f"   neighbor 192.0.2.{n} remote-as 2\n" for n in range(80))
        _lines, spans = tool.units(text)
        assert all(end - first == 1 for first, end in spans)

    def test_an_xml_block_takes_its_closing_tag(self) -> None:
        lines, spans = tool.units("<a>\n  <b>\n    <c>1</c>\n  </b>\n</a>\n")
        assert "  <b>\n    <c>1</c>\n  </b>" in ["\n".join(lines[first:end]) for first, end in spans]


class TestAUnitWrittenAgain:
    LINES, SPANS = tool.units(SAMPLE)
    BLOCK = (2, 6)

    def test_identically(self) -> None:
        text = tool.written_again(self.LINES, self.BLOCK, 3, "A")
        assert text.count("interface Ethernet1\n") == 3 and text.count("switchport access vlan 10") == 3
        assert text.startswith("hostname sw\n!\ninterface Ethernet1") and "interface Ethernet2" in text

    def test_with_a_counter_in_its_first_line(self) -> None:
        text = tool.written_again(self.LINES, self.BLOCK, 3, "B")
        assert [f"interface Ethernet{n}\n" in text for n in (1, 2, 3)] == [True, True, True]
        assert text.count("switchport access vlan 10") == 3

    def test_with_a_counter_in_every_line_that_has_a_number(self) -> None:
        text = tool.written_again(self.LINES, self.BLOCK, 3, "C")
        # The counter under the first line starts again after 250, so
        # that a value with a range (a VLAN id) stays inside it.
        assert [f"switchport access vlan {n + 1}" in text for n in (1, 2, 3)] == [True, True, True]
        assert text.count("description uplink") == 4

    def test_a_line_with_no_number_gets_one_after_its_last_word(self) -> None:
        lines = ["set system login user ops class operator"]
        assert tool.written_again(lines, (0, 1), 2, "B").split("\n") == [
            "set system login user ops class operator1", "set system login user ops class operator2",
        ]


def _routes(count: int) -> str:
    return "\n".join(f"route {n}" for n in range(count)) + "\n"


class TestTheSearchFindsWhatItIsFor:
    """On readers made for it, at sizes that take a moment and not
    minutes.  The text is one line; the search writes it again.

    The floor is set low for them: a reader that really looks through
    its list is quick at these sizes, and quicker on a faster machine.
    """

    TEXTS = [("sample", "route 0\n")]
    FLOOR = 0.005

    @staticmethod
    def _reads_its_list_for_every_line(text: str) -> None:
        made: list[str] = []
        for line in text.split("\n"):
            if not any(earlier == line for earlier in made):
                made.append(line)

    @staticmethod
    def _finds_by_key(text: str) -> None:
        made: dict[str, str] = {}
        for line in text.split("\n"):
            made.setdefault(line, line)

    def test_a_reader_that_looks_through_what_it_made_is_reported(self) -> None:
        # Asked up to three times: one stalled reading of the smaller
        # text hides a steep one, which is the safe way round for the
        # search and the wrong way round for this test.
        for _attempt in range(3):
            found = list(tool.search(self._reads_its_list_for_every_line, self.TEXTS, small=400, floor=self.FLOOR))
            if found:
                break
        (finding,) = found
        assert (finding.variant, finding.first_line, finding.lines) == ("B", 1, 1)
        low, high, top = finding.seconds
        assert top is not None and top > high > low

    def test_the_same_lines_written_identically_are_not(self) -> None:
        """Every line finds itself first in the list: variant A is
        quick for this reader, and only the counter makes it slow."""
        found = list(tool.search(self._reads_its_list_for_every_line, self.TEXTS, small=400, floor=self.FLOOR))
        assert "A" not in {finding.variant for finding in found}

    def test_a_reader_that_finds_by_key_is_not(self) -> None:
        assert list(tool.search(self._finds_by_key, self.TEXTS, small=400, floor=self.FLOOR)) == []

    def test_a_step_that_does_not_go_on_is_not_reported(self) -> None:
        """Work that is the square of the count up to a limit and then
        no more -- a list that stops growing, a range that is clamped --
        is steep once and then level.  It is not what this looks for."""

        def square_of_the_first_lines(text: str) -> None:
            self._reads_its_list_for_every_line("\n".join(text.split("\n")[:1600]))

        assert list(tool.search(square_of_the_first_lines, self.TEXTS, small=400, floor=self.FLOOR)) == []

    def test_one_stalled_reading_is_not_a_finding(self) -> None:
        """The machine stalls.  A unit is read a second time before it
        is reported, and the quicker reading is the one judged.  Here
        the first reading of the larger text is made slow and no
        longer text is read after it (``longest=0``), so that the
        second reading is all that stands between a stall and a
        finding."""
        import time

        seen: set[int] = set()

        def stalls_once(text: str) -> None:
            if len(text) > 8_000 and len(text) not in seen:
                seen.add(len(text))
                time.sleep(0.25)

        assert list(tool.search(stalls_once, self.TEXTS, small=400, floor=0.02, longest=0.0)) == []
        seen.clear()

        def always_slow(text: str) -> None:
            if len(text) > 8_000:
                time.sleep(0.25)

        assert len(list(tool.search(always_slow, self.TEXTS, small=400, floor=0.02, longest=0.0))) == 2

    def test_a_reader_that_raises_is_timed_all_the_same(self) -> None:
        def refuses(text: str) -> None:
            self._reads_its_list_for_every_line(text)
            raise ValueError("no")

        for _attempt in range(3):
            if list(tool.search(refuses, self.TEXTS, small=400, floor=self.FLOOR)):
                return
        raise AssertionError("a slow reader that raises was not reported")


class TestTheCapturesItReads:
    def test_every_public_codec_has_one(self) -> None:
        """A codec with no capture is a codec the search passes without
        having read a line for it."""
        found = tool.captures()
        assert set(list_public_codecs()) <= set(found)
        assert all(texts == sorted(texts, key=lambda item: len(item[1])) for texts in found.values())
