"""
What it costs to read text nobody vouches for.

A config is whatever was pasted.  ``/detect``, ``/plan`` and every
other route that takes one hand it to patterns written for real
configs, and a pattern can take time that grows with the SQUARE of a
run in the text: under ``re.MULTILINE``, ``^\\s+X`` walks from every
line start to the end of the run of blank lines it is in, fails, and
walks back.  Sixty-four kilobytes of blank lines once held ``/detect``
for about a minute.

A list of the patterns that were wrong cannot show that none is left,
so nothing here is a list of patterns.  Three experiments:

* every regex the product holds — each literal in the source, each
  compiled pattern a module or class keeps, each pattern in a shipped
  device definition — is timed on repeated input at growing sizes;
* every public codec's ``probe`` and ``parse`` are timed on a real
  capture with a run of filler lines inserted, at two sizes;
* codec detection as a whole is timed on a probe window of filler.

What the first cannot see is a pattern assembled inside a function
from parts that are not literals; only the second reaches those, and
only where a codec's ``probe`` or ``parse`` runs them.

Each check is also handed something that is slow, and has to say so.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import yaml

import netcanon
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_detect import DEFAULT_PROBE_BYTES, detect_codec

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "netcanon"

# ---------------------------------------------------------------------------
# Repeated input
# ---------------------------------------------------------------------------

#: What is repeated.  White space in every form a line can end or be
#: indented with, and the short units a config is made of: a word, a
#: number, a separator after one.
UNITS = (
    "\n", " \n", "   \n", "\r\n", "\t\n", " ", "\t", "a", "0", "a ", "a\n", " a", "0 ", "0.", "a.", "a/",
    "a=", "a:", "a-", "!\n", "#\n", ";\n", '"', "{\n", "a,", "a b\n", "  a\n", "a  \n", "/", ".", "-",
    ":", "=", ",", "1/", "x1 ", "set \n", "no \n",
)

#: How many repeats the first look at a pattern uses.
_FIRST_LOOK = 1500
#: A pattern faster than this on the first look is not measured
#: further.  Work that is quadratic in 1,500 units is a million steps,
#: which takes milliseconds; this is well under that.
_WORTH_MEASURING = 0.0002
#: Growth is judged at a size that takes at least this long, or at the
#: largest size tried: a ratio of two timings near zero means nothing.
_ENOUGH_TO_JUDGE = 0.015
_LARGEST = _FIRST_LOOK * 64
#: Four times the input: linear work takes four times as long,
#: quadratic work sixteen.  Halfway, on a log scale.
_TOO_STEEP = 8.0


def _best(read: Callable[[str], object], text: str, tries: int = 3) -> float:
    """The quickest of *tries* readings.  A loaded machine only ever
    adds time, so the least of several is the one to believe."""
    best = float("inf")
    for _ in range(tries):
        started = time.perf_counter()
        read(text)
        best = min(best, time.perf_counter() - started)
        if best > 1.0:
            break
    return best


def _scan(pattern: re.Pattern[str]) -> Callable[[str], None]:
    def scan(text: str) -> None:
        for _ in pattern.finditer(text):
            pass

    return scan


def _slow_on(pattern: re.Pattern[str]) -> str | None:
    """The unit *pattern* is super-linear on, or ``None``.

    For each unit: a first look; if that takes any time at all, the
    input is grown until a reading is long enough to judge, and the
    time for four times as much is compared with it -- twice, at two
    sizes, each the best of several readings.  One stalled reading
    cannot make a linear pattern look steep, nor a steep one linear.
    """
    scan = _scan(pattern)
    for unit in UNITS:
        if _best(scan, unit * _FIRST_LOOK, 1) < _WORTH_MEASURING:
            continue
        size = _FIRST_LOOK * 4
        while size < _LARGEST and _best(scan, unit * size, 1) < _ENOUGH_TO_JUDGE:
            size *= 4
        smaller, here = _best(scan, unit * (size // 4)), _best(scan, unit * size)
        if here < _TOO_STEEP * smaller:
            continue
        larger = _best(scan, unit * (size * 4), 2)
        if larger > _TOO_STEEP * here and larger > 0.05:
            return unit
    return None


# ---------------------------------------------------------------------------
# Every regex the product holds
# ---------------------------------------------------------------------------

_RE_CALLS = {
    "compile": 1, "search": 2, "match": 2, "fullmatch": 2, "findall": 2, "finditer": 2,
    "split": 3, "sub": 4, "subn": 4,
}


def _flags(call: ast.Call) -> int | None:
    exprs = [kw.value for kw in call.keywords if kw.arg == "flags"]
    position = _RE_CALLS[call.func.attr]  # type: ignore[attr-defined]
    if len(call.args) > position:
        exprs.append(call.args[position])
    flags = 0
    for expr in exprs:
        try:
            flags |= int(eval(compile(ast.Expression(expr), "<flags>", "eval"), {"re": re}))
        except Exception:
            return None
    return flags


def _literals(root: Path) -> Iterator[tuple[str, str, int]]:
    """``(where, pattern, flags)`` for every ``re.<call>("literal", ...)``."""
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _RE_CALLS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "re"
                and node.args
            ):
                continue
            first = node.args[0]
            flags = _flags(node)
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and flags is not None:
                yield f"{path.relative_to(root.parent).as_posix()}:{node.lineno}", first.value, flags


def _kept(root_package: str) -> Iterator[tuple[str, str, int]]:
    """Compiled patterns a module or a class keeps, however they were built."""

    def patterns(value: object, depth: int = 0) -> Iterator[re.Pattern[str]]:
        if isinstance(value, re.Pattern):
            if isinstance(value.pattern, str):
                yield value
            return
        elif depth < 2 and isinstance(value, (tuple, list, set, frozenset)):
            for item in value:
                yield from patterns(item, depth + 1)
        elif depth < 2 and isinstance(value, dict):
            for item in value.values():
                yield from patterns(item, depth + 1)

    package = importlib.import_module(root_package)
    names = [root_package] + [
        info.name for info in pkgutil.walk_packages(package.__path__, root_package + ".")
    ]
    for name in names:
        try:
            module = importlib.import_module(name)
        except Exception:  # an optional dependency that is not installed
            continue
        # ``re.UNICODE`` is set on every compiled str pattern; without
        # it a kept pattern and the literal it was compiled from are
        # one entry, not two.
        for attr, value in vars(module).items():
            for pattern in patterns(value):
                yield f"{name}.{attr}", pattern.pattern, pattern.flags & ~re.UNICODE
            if isinstance(value, type) and value.__module__ == name:
                for inner, held in vars(value).items():
                    for pattern in patterns(held):
                        yield f"{name}.{attr}.{inner}", pattern.pattern, pattern.flags & ~re.UNICODE


def _in_definitions(root: Path) -> Iterator[tuple[str, str, int]]:
    """Patterns in the shipped device definitions.  The collectors
    apply them to what a device printed, with ``re.MULTILINE``."""

    def walk(node: object, trail: tuple[str, ...]) -> Iterator[tuple[str, str]]:
        if isinstance(node, dict):
            for key, value in node.items():
                yield from walk(value, (*trail, str(key)))
        elif isinstance(node, list):
            for value in node:
                yield from walk(value, trail)
        elif isinstance(node, str) and any(
            word in part.lower() for part in trail for word in ("pattern", "regex", "prompt", "expect")
        ):
            yield "/".join(trail), node

    for path in sorted(root.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for trail, pattern in walk(data, ()):
            yield f"{path.relative_to(REPO_ROOT).as_posix()} [{trail}]", pattern, re.MULTILINE


#: Patterns that ARE super-linear and are left so, each with why that
#: is safe.  Keyed by the pattern, not by where it is.  An entry that
#: is no longer slow fails the test below, so this cannot go stale.
KNOWN_SLOW: dict[str, str] = {
    r"^(?P<prefix>.*?)(?P<start>\d+)-(?P<prefix2>.*?)(?P<end>\d+)$": (
        "target_profiles._RANGE_RE: matched against one `range:` shorthand of a profile file the "
        "server loads at start.  Never against request text."
    ),
}


def _every_regex() -> dict[tuple[str, int], str]:
    """``(pattern, flags)`` to one place it was found."""
    found: dict[tuple[str, int], str] = {}
    for source in (_literals(PACKAGE), _kept("netcanon"), _in_definitions(PACKAGE / "definitions")):
        for where, pattern, flags in source:
            found.setdefault((pattern, flags), where)
    return found


class TestEveryRegexTheProductHolds:
    def test_none_is_super_linear_on_repeated_input(self) -> None:
        found = _every_regex()
        # The three sources have to have been read at all.
        assert len(found) > 300
        assert any(where.startswith("netcanon/definitions/") for where in found.values())
        assert any("mlag" in pattern and flags & re.MULTILINE for pattern, flags in found)

        slow: list[str] = []
        excused: set[str] = set()
        for (pattern, flags), where in found.items():
            try:
                compiled = re.compile(pattern, flags)
            except re.error:
                continue
            unit = _slow_on(compiled)
            if unit is None and pattern in KNOWN_SLOW:
                # Said to be slow: look again before calling that stale.
                unit = _slow_on(compiled) or _slow_on(compiled)
            if unit is None:
                continue
            if pattern in KNOWN_SLOW:
                excused.add(pattern)
                continue
            slow.append(f"{where}: {pattern!r} on {unit!r} repeated")
        assert slow == [], (
            "these patterns take time that grows faster than their input.  If the text is a whole "
            "config, write [^\\S\\n] where a line-anchored pattern has \\s (\\s crosses newlines); "
            "see the Hard Rule on text nobody vouches for: " + "; ".join(slow)
        )
        assert excused == set(KNOWN_SLOW), "a pattern excused as slow no longer is: drop it from KNOWN_SLOW"

    @pytest.mark.parametrize(
        ("pattern", "flags"),
        [
            (r"^\s+mlag\s+\d+\s*$", re.MULTILINE),
            (r"^\s*logging\s+(\S.*)$", re.MULTILINE | re.IGNORECASE),
            (r"([\w\-]+)=(\S+)", 0),
            (r"\s+mac-address\s+\S+", 0),
        ],
        ids=["an indented keyword", "an optional indent", "a key that restarts inside a word", "a scrub"],
    )
    def test_the_check_can_fail(self, pattern: str, flags: int) -> None:
        """Each is a pattern this codebase had."""
        assert _slow_on(re.compile(pattern, flags)) is not None

    @pytest.mark.parametrize(
        ("pattern", "flags"),
        [
            (r"^[^\S\n]+mlag\s+\d+\s*$", re.MULTILINE),
            (r"(?<![\w\-])([\w\-]+)=(\S+)", 0),
            (r"^interface\s+(\S+)", re.MULTILINE),
        ],
    )
    def test_and_it_passes_what_is_linear(self, pattern: str, flags: int) -> None:
        assert _slow_on(re.compile(pattern, flags)) is None

    def test_the_scan_reads_a_literal_split_over_lines_and_a_pattern_built_at_import(self) -> None:
        literal = {pattern for _where, pattern, _flags in _literals(PACKAGE)}
        assert any("vn-segment" in pattern and "vrf" in pattern for pattern in literal)
        kept = {where: pattern for where, pattern, _flags in _kept("netcanon")}
        built = kept["netcanon.migration.codecs.arista_eos.parse._USERNAME_RE"]
        assert built not in literal and "username" in built


# ---------------------------------------------------------------------------
# Every public codec, on a real capture with a run inserted
# ---------------------------------------------------------------------------

FILLERS = {"blank lines": "\n", "lines of spaces": "   \n", "blank CRLF lines": "\r\n", "lines of a tab": "\t\n"}


def _captures() -> dict[str, str]:
    """Codec name to the smallest committed capture detection gives it."""
    best: dict[str, str] = {}
    for path in sorted((REPO_ROOT / "tests" / "fixtures").rglob("*")):
        if not path.is_file() or path.suffix.lower() in {".md", ".json", ".yaml", ".yml", ".py", ".pyc"}:
            continue
        if not 200 < path.stat().st_size < 60_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits = detect_codec(text)
        if hits and (hits[0].codec not in best or len(text) < len(best[hits[0].codec])):
            best[hits[0].codec] = text
    return best


CAPTURES = _captures()


def _with_a_run(text: str, run: str) -> str:
    lines = text.split("\n")
    middle = len(lines) // 2
    return "\n".join(lines[:middle]) + "\n" + run + "\n".join(lines[middle:])


def _grows_faster_than_its_input(read: Callable[[str], object], make: Callable[[int], str], small: int) -> str:
    """Empty when reading ``make(4 * small)`` costs about four times
    ``make(small)``; otherwise what was measured.

    Quadratic work costs sixteen times.  Each reading is the quicker
    of two, and the floor is there because a ratio of two timings
    near zero means nothing.
    """

    def quietly(text: str) -> None:
        try:
            read(text)
        except Exception:  # a codec may refuse the text; how long it took is the point
            pass

    low = _best(quietly, make(small), 2)
    high = _best(quietly, make(4 * small), 2)
    if high > _TOO_STEEP * low and high > 0.5:
        return f"{small} lines: {low:.3f}s; {4 * small} lines: {high:.3f}s"
    return ""


class TestEveryPublicCodec:
    def test_each_has_a_capture_to_be_tried_on(self) -> None:
        """A codec with no small capture that detection gives to it is
        a codec these tests would pass without having run."""
        assert set(CAPTURES) == set(list_public_codecs())

    @pytest.mark.parametrize("filler", sorted(FILLERS))
    @pytest.mark.parametrize("name", list_public_codecs())
    def test_parse_fits_the_length_of_the_text(self, name: str, filler: str) -> None:
        codec, capture = get_codec(name), CAPTURES[name]
        slow = _grows_faster_than_its_input(
            codec.parse, lambda lines: _with_a_run(capture, FILLERS[filler] * lines), 8_000,
        )
        assert not slow, f"{name}.parse on a capture with a run of {filler}: {slow}"

    @pytest.mark.parametrize("filler", sorted(FILLERS))
    @pytest.mark.parametrize("name", list_public_codecs())
    def test_probe_fits_the_length_of_the_window(self, name: str, filler: str) -> None:
        """On the window alone, and on a capture's first line followed
        by the run: a probe that returns early on a header it knows has
        to be reached both ways."""
        probe = type(get_codec(name)).probe
        first_line = CAPTURES[name].split("\n", 1)[0] + "\n"
        per_line = len(FILLERS[filler])
        most = DEFAULT_PROBE_BYTES // per_line // 4
        for lead in ("", first_line):
            slow = _grows_faster_than_its_input(
                lambda text: probe(text[:DEFAULT_PROBE_BYTES]),
                lambda lines, lead=lead: lead + FILLERS[filler] * lines,
                most,
            )
            assert not slow, f"{name}.probe on a window of {filler}: {slow}"

    @pytest.mark.parametrize("filler", sorted(FILLERS))
    def test_detection_of_a_window_of_filler_is_quick(self, filler: str) -> None:
        """Every codec's probe, on a probe window with nothing in it.
        About a minute before the patterns were fixed."""
        text = FILLERS[filler] * (DEFAULT_PROBE_BYTES // len(FILLERS[filler]))
        started = time.perf_counter()
        detect_codec(text)
        assert time.perf_counter() - started < 5.0

    def test_the_check_can_fail(self) -> None:
        """A reader with the defect, and the same reader without it."""
        indented = re.compile(r"^\s+shutdown\s*$", re.MULTILINE)
        fixed = re.compile(r"^[^\S\n]+shutdown\s*$", re.MULTILINE)
        capture = CAPTURES["cisco_iosxe_cli"]

        def make(lines: int) -> str:
            return _with_a_run(capture, "   \n" * lines)

        assert _grows_faster_than_its_input(lambda text: indented.findall(text), make, 4_000)
        assert not _grows_faster_than_its_input(lambda text: fixed.findall(text), make, 4_000)

    def test_netcanon_is_the_package_under_test(self) -> None:
        assert Path(netcanon.__file__).resolve().parent == PACKAGE
