#!/usr/bin/env python
"""
Search for parse work that grows faster than the NUMBER of a config's stanzas.

A config is whatever was pasted, and a real one is long.  A parser's
handler runs once per line; one that looks through everything the
earlier lines made (``next(r for r in intent.routes if ...)``,
``any(...)``, ``name in a_list``, a dict rebuilt from a list) costs
the square of the lines.  Nothing about one such line is slow, so no
pattern-level check sees it: it shows only when a stanza is written
many times.

What this does
--------------
For every public codec and every committed capture detection gives it,
it takes each **unit** of the capture -- a line, or a line and the
more-indented lines under it -- and rebuilds the capture with that
unit written N times in place:

* ``A`` -- identically (a block header that is repeated);
* ``B`` -- with a counter in the unit's first line (many records of
  one kind);
* ``C`` -- with a counter in the first line and in every line under
  it that holds a number.

It parses the result at N = ``--small`` and at four times that.  A
unit whose time grows by more than ``--steep`` and passes ``--floor``
seconds is read again (the quicker of two readings); if it still
does, it is read at sixteen times ``--small``, and reported if the
growth went on.  (A reading of six seconds or more is not followed
by a longer one: the unit is reported on the two.)

What this is not
----------------
A proof.  It reaches the stanzas the captures hold, in the three
variants above, at the sizes given.  A handler no capture has a line
for is not reached; nor is a cost that needs two KINDS of stanza to
grow together (a lookup among networks for every pool), nor one whose
constant is too small to pass the floor at these sizes.  The fixed
cases found with it are pinned in
``tests/unit/test_untrusted_text_cost.py``; run this when a parser's
handler changes, or a codec is added.

It also does not look at what a config expands TO.  A port or VLAN
range (``1-4094``) is a few bytes that parse to thousands of entries;
that cost is the size of what was asked for, and is not reported here
unless it also grows faster than the number of lines.

Operator usage
--------------

    python tools/stanza_cost_search.py
    python tools/stanza_cost_search.py --codec arista_eos --small 800

Prints one line per codec and one per flagged unit; exits 1 if any
unit was flagged.  It takes minutes: it parses every unit of every
capture several times.
"""

from __future__ import annotations

import argparse
import multiprocessing
import re
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Lines that close a block at the indentation of its first line.
_CLOSERS = ("}", "next", "end", "!", "exit", "</", "exit-address-family", "exit-vrf", "quit")
_NOT_A_CAPTURE = {".md", ".json", ".yaml", ".yml", ".py", ".pyc"}
_LAST_NUMBER = re.compile(r"\d+(?!.*\d)")
_LAST_WORD = re.compile(r"([\w.\-]+)([^\w]*)$")
#: A block longer than this is a section of a config, not a stanza.
_LONGEST_BLOCK = 60


@dataclass(frozen=True)
class Finding:
    codec: str
    capture: str
    first_line: int
    lines: int
    variant: str
    unit: str
    seconds: tuple[float, float, float | None]

    def __str__(self) -> str:
        low, high, top = self.seconds
        third = "" if top is None else f", {top:.2f}s"
        return (
            f"{self.codec} | {self.capture} line {self.first_line} (+{self.lines - 1}) | {self.variant} | "
            f"{self.unit[:70]} | {low:.3f}s, {high:.3f}s{third}"
        )


def captures() -> dict[str, list[tuple[str, str]]]:
    """Codec name to ``(path, text)`` for every committed capture
    detection gives that codec, smallest first."""
    from netcanon.services.migration_detect import detect_codec

    found: dict[str, list[tuple[str, str]]] = {}
    for path in sorted((REPO_ROOT / "tests" / "fixtures").rglob("*")):
        if not path.is_file() or path.suffix.lower() in _NOT_A_CAPTURE:
            continue
        if not 200 < path.stat().st_size < 60_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits = detect_codec(text)
        if hits:
            found.setdefault(hits[0].codec, []).append((path.relative_to(REPO_ROOT).as_posix(), text))
    for texts in found.values():
        texts.sort(key=lambda item: len(item[1]))
    return found


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def units(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """The lines of *text*, and the ``(first, end)`` span of every unit:
    each line that says something, and each such line with the
    more-indented lines under it (and the line that closes them).  One
    span per shape -- two lines that differ only in their numbers are
    one unit."""
    lines = text.split("\n")
    seen: set[tuple[str, str]] = set()
    spans: list[tuple[int, int]] = []
    for first, line in enumerate(lines):
        if not line.strip():
            continue
        shape = re.sub(r"\d+", "0", line)
        if ("line", shape) not in seen:
            seen.add(("line", shape))
            spans.append((first, first + 1))
        depth = _indent(line)
        end = first + 1
        while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) > depth):
            end += 1
        while end > first + 1 and not lines[end - 1].strip():
            end -= 1
        if end == first + 1:
            # Nothing under it but blank lines: a line, not a block.
            continue
        if end < len(lines) and _indent(lines[end]) == depth and lines[end].strip().startswith(_CLOSERS):
            end += 1
        if end - first <= _LONGEST_BLOCK:
            shape = re.sub(r"\d+", "0", "\n".join(lines[first:end]))
            if ("block", shape) not in seen:
                seen.add(("block", shape))
                spans.append((first, end))
    return lines, spans


def _numbered(line: str, number: int, cycle: int | None = None) -> str:
    """*line* with *number* in place of its last number, or after its
    last word if it has none."""
    value = number if cycle is None else number % cycle + 1
    if _LAST_NUMBER.search(line):
        return _LAST_NUMBER.sub(str(value), line, count=1)
    word = _LAST_WORD.search(line)
    if word and word.group(1) not in ("next", "end", "exit"):
        return line[: word.start(1)] + word.group(1) + str(value) + word.group(2)
    return line


def written_again(lines: list[str], span: tuple[int, int], count: int, variant: str) -> str:
    """The text with the unit at *span* written *count* times in place."""
    first, end = span
    unit = lines[first:end]
    if variant == "A":
        body = unit * count
    else:
        body = []
        closes_in_xml = len(unit) > 1 and unit[-1].strip().startswith("</")
        for number in range(1, count + 1):
            body.append(_numbered(unit[0], number))
            for position, line in enumerate(unit[1:], start=1):
                if closes_in_xml and position == len(unit) - 1:
                    body.append(_numbered(line, number))
                elif variant == "C" and re.search(r"\d", line):
                    body.append(_numbered(line, number, 250))
                else:
                    body.append(line)
    return "\n".join([*lines[:first], *body, *lines[end:]])


def _seconds(read: Callable[[str], object], text: str) -> float:
    started = time.perf_counter()
    try:
        read(text)
    except Exception:  # a codec may refuse the text; how long it took is the point
        pass
    return time.perf_counter() - started


def search(
    read: Callable[[str], object],
    texts: list[tuple[str, str]],
    *,
    codec: str = "",
    small: int = 500,
    floor: float = 0.08,
    steep: float = 6.5,
    longest: float = 6.0,
) -> Iterator[Finding]:
    """Every unit of *texts* whose reading grows faster than its count.

    Args:
        read: What is timed -- a codec's ``parse``.
        texts: ``(name, text)`` captures.
        codec: Named in the findings.
        small: The smaller count; the larger is four times it.
        floor: A reading under this many seconds is not judged.
        steep: The growth, for four times the count, that is too much.
            Linear work is 4; quadratic work is 16.
        longest: A reading of this many seconds is not followed by one
            of four times the count: the unit is reported on the two.
    """
    seen: set[str] = set()
    for name, text in texts:
        lines, spans = units(text)
        for span in spans:
            shape = re.sub(r"\d+", "0", "\n".join(lines[span[0]:span[1]]))
            if shape in seen:
                continue
            seen.add(shape)
            for variant in ("A", "B", "C") if span[1] - span[0] > 1 else ("A", "B"):
                low_text = written_again(lines, span, small, variant)
                high_text = written_again(lines, span, 4 * small, variant)
                low, high = _seconds(read, low_text), _seconds(read, high_text)
                if not (high > floor and high > steep * low):
                    continue
                # One slow reading is the machine; read both again.
                low, high = min(low, _seconds(read, low_text)), min(high, _seconds(read, high_text))
                if not (high > floor and high > steep * low):
                    continue
                # And the growth has to go on.  Small texts are noisy: a
                # step that looked steep and then levels off is not
                # work that grows with the square of the count.
                top = None
                if high < longest:
                    top = _seconds(read, written_again(lines, span, 16 * small, variant))
                    if top <= steep * high:
                        continue
                yield Finding(
                    codec=codec, capture=Path(name).name, first_line=span[0] + 1, lines=span[1] - span[0],
                    variant=variant, unit=" / ".join(line.strip() for line in lines[span[0]:span[1]]),
                    seconds=(low, high, top),
                )


def _one_codec(job: tuple[str, int, float, float]) -> tuple[str, int, list[Finding]]:
    name, small, floor, steep = job
    from netcanon.migration.codecs.registry import get_codec

    texts = captures().get(name, [])
    found = list(search(get_codec(name).parse, texts, codec=name, small=small, floor=floor, steep=steep))
    return name, len(texts), found


def main(argv: list[str] | None = None) -> int:
    from netcanon.migration.codecs.registry import list_public_codecs

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    parser.add_argument("--codec", action="append", help="a codec to search (default: every public codec)")
    parser.add_argument("--small", type=int, default=500, help="the smaller count (default 500)")
    parser.add_argument("--floor", type=float, default=0.08, help="seconds a reading must take to be judged")
    parser.add_argument("--steep", type=float, default=6.5, help="growth for four times the count that is too much")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    names = args.codec or list_public_codecs()
    jobs = [(name, args.small, args.floor, args.steep) for name in names]
    flagged: list[Finding] = []
    with multiprocessing.Pool(min(args.workers, len(jobs))) as pool:
        for name, count, found in pool.imap_unordered(_one_codec, jobs):
            print(f"{name}: {count} capture(s), {len(found)} unit(s) flagged", flush=True)
            flagged += found
    for finding in flagged:
        print(finding)
    print(f"flagged: {len(flagged)}")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
