"""
What it costs to read text nobody vouches for.

A config is whatever was pasted.  ``/detect``, ``/plan`` and every
other route that takes one hand it to code written for real configs,
and some of that code took time that grew with the SQUARE of a run in
the text:

* a line-anchored pattern that began with ``\\s`` under
  ``re.MULTILINE`` -- from every line start it walked to the end of the
  run of blank lines it was in;
* a lazy value in front of trailing white space (``(\\S.*?)\\s*$``) --
  re-read to the end of the line for every character it took;
* a search that failed and started again inside the run it had just
  crossed (``(\\d+)$`` on digits and then a letter, ``([\\w-]+)=`` on a
  long word);
* code that was no pattern at all: a line continuation joined by
  ``buffer += ...``, copied whole for every line it grew by;
* and a handler that runs once per line and looked through everything
  the earlier lines had made (``next(r for r in intent.routes if
  ...)``, ``any(...)``, ``name in a_list``, a dict rebuilt from a
  list): the square of the NUMBER of stanzas, on text with nothing
  odd in any one line of it.

This has been fixed before, a pattern at a time, where a scanner named
the pattern (``test_redos_hardening.py`` pins those) or a reader
named the loop (``test_parse_quadratic_scan_perf.py``).  A list of what
was wrong cannot show that nothing is left, so nothing here is a list
of patterns.  It is a SEARCH, in two halves, and a list beside them:

* every regex the product holds -- each literal in the source, each
  compiled pattern or pattern-shaped string a module or class keeps,
  each pattern in a shipped device definition -- is handed texts built
  from its own structure: what the pattern needs before one of its
  repeats, then a run of what that repeat accepts, then something the
  rest of it refuses.  Time is read at growing sizes.
* every public codec's ``probe`` and ``parse`` are timed on a real
  capture with a run put into it: of whole filler lines, of lines that
  go on (a continuation, an open quote, an open brace), and of white
  space inside each of the capture's own lines.

The last shape is the one the two halves do not build: nothing about
one line of it is slow.  The search for it is a tool,
``tools/stanza_cost_search.py``, which writes every line and block of
every capture many times over and takes minutes; what it found is
pinned here, a text for each handler that was fixed
(``TestParseFitsTheNumberOfItsStanzas``).  That part IS a list, and
says so: run the tool when a parser's handler changes.

A search is not a proof.  What is not reached: a pattern put together
inside a function from parts that are not literals and not kept, on a
path the capture and its runs do not drive; a handler no capture has a
line for; work that needs two kinds of stanza to grow together; code
that is slow on a shape nobody thought to build.  The calls the first
half cannot read -- a pattern that is not a literal, flags that are
not written out -- are listed by name, so a new one is at least
looked at.

Nor is any of this about what a config expands TO.  ``1-4094`` is a
few bytes that parse to thousands of entries; reading it costs the
size of what was asked for, which no search for work that grows
faster than the text will report.

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
from re import _constants as sre
from re import _parser as sre_parser

import pytest
import yaml

import netcanon
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.services.migration_detect import DEFAULT_PROBE_BYTES, detect_codec

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "netcanon"

# ---------------------------------------------------------------------------
# Reading the clock on a machine that is doing other things
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Texts built for one pattern
# ---------------------------------------------------------------------------

#: Repeated from the first character, whatever the pattern is.  White
#: space in every form a line can end or be indented with, and the
#: short units a config is made of.
UNITS = (
    "\n", " \n", "   \n", "\r\n", "\t\n", " ", "\t", "a", "0", "a ", "a\n", " a", "0 ", "0.", "a.", "a/",
    "a=", "a:", "a-", "!\n", "#\n", ";\n", '"', "{\n", "a,", "a b\n", "  a\n", "a  \n", "/", ".", "-",
    ":", "=", ",", "1/", "x1 ", "set \n", "no \n",
)

_REPEATS = {sre.MAX_REPEAT, sre.MIN_REPEAT, getattr(sre, "POSSESSIVE_REPEAT", sre.MAX_REPEAT)}
_GROUPS = {sre.SUBPATTERN, getattr(sre, "ATOMIC_GROUP", sre.SUBPATTERN)}
_NO_WIDTH = {sre.AT, sre.ASSERT, sre.ASSERT_NOT, sre.GROUPREF, sre.GROUPREF_EXISTS}
_OF_A_CLASS = {
    sre.CATEGORY_DIGIT: "1", sre.CATEGORY_SPACE: " \t\n", sre.CATEGORY_WORD: "a1_",
    sre.CATEGORY_NOT_SPACE: "x1/-", sre.CATEGORY_NOT_DIGIT: "x ", sre.CATEGORY_NOT_WORD: "- ",
}
_IS_OF_A_CLASS: dict[object, Callable[[str], bool]] = {
    sre.CATEGORY_DIGIT: str.isdigit,
    sre.CATEGORY_SPACE: str.isspace,
    sre.CATEGORY_WORD: lambda ch: ch.isalnum() or ch == "_",
    sre.CATEGORY_NOT_SPACE: lambda ch: not ch.isspace(),
    sre.CATEGORY_NOT_DIGIT: lambda ch: not ch.isdigit(),
    sre.CATEGORY_NOT_WORD: lambda ch: not (ch.isalnum() or ch == "_"),
}
_TRIED = 'xa1 -/.:="\t_,\n'


def _accepted(op: object, av: object) -> str:
    """A few characters the one-character node ``(op, av)`` accepts."""
    if op is sre.LITERAL:
        return chr(av)  # type: ignore[arg-type]
    if op is sre.NOT_LITERAL:
        return "".join(ch for ch in _TRIED if ch != chr(av))[:3]  # type: ignore[arg-type]
    if op is sre.ANY:
        return "x 1"
    if op is sre.CATEGORY:
        return _OF_A_CLASS.get(av, "")
    if op is not sre.IN:
        return ""
    members = [(kind, value) for kind, value in av if kind is not sre.NEGATE]  # type: ignore[union-attr]

    def has(ch: str) -> bool:
        for kind, value in members:
            if kind is sre.LITERAL and chr(value) == ch:
                return True
            if kind is sre.RANGE and value[0] <= ord(ch) <= value[1]:
                return True
            if kind is sre.CATEGORY and _IS_OF_A_CLASS.get(value, lambda _ch: False)(ch):
                return True
        return False

    if len(members) < len(av):  # type: ignore[arg-type]
        return "".join(ch for ch in _TRIED if not has(ch))[:4]
    out = ""
    for kind, value in members:
        if kind is sre.LITERAL:
            out += chr(value)
        elif kind is sre.RANGE:
            out += chr(value[0])
        elif kind is sre.CATEGORY:
            out += _OF_A_CLASS.get(value, "")
    return "".join(dict.fromkeys(out))[:4]


def _inside(op: object, av: object) -> object:
    return av[3] if op is sre.SUBPATTERN else av  # type: ignore[index]


def _sample(nodes: object) -> str:
    """One string the sequence accepts: the first alternative of each
    choice, the fewest turns of each repeat."""
    out = ""
    for op, av in nodes:  # type: ignore[union-attr]
        if op in _REPEATS:
            low, _high, body = av
            out += _sample(body) * max(low, 1)
        elif op in _GROUPS:
            out += _sample(_inside(op, av))
        elif op is sre.BRANCH:
            out += _sample(av[1][0])
        elif op not in _NO_WIDTH:
            out += _accepted(op, av)[:1]
    return out


def _flat(nodes: object, cap: int = 8) -> list[list[tuple[object, object]]]:
    """Groups opened up: one flat sequence per combination of
    alternatives, the first *cap* of them."""
    flats: list[list[tuple[object, object]]] = [[]]
    for op, av in nodes:  # type: ignore[union-attr]
        if op in _GROUPS:
            parts = _flat(_inside(op, av), cap)
        elif op is sre.BRANCH:
            parts = [flat for alternative in av[1] for flat in _flat(alternative, cap)]
        else:
            parts = [[(op, av)]]
        flats = [head + tail for head in flats for tail in parts][:cap]
    return flats


_Nodes = list[tuple[object, object]]


def _repeat_sites(flat: _Nodes, before: str, following: _Nodes, depth: int = 0) -> Iterator[tuple[str, _Nodes, _Nodes]]:
    """Every repeat with no upper bound in *flat*, at any depth: the
    text the pattern needs before it, its body, and what comes after.

    At any depth, because the run that costs its square can be inside
    a repeat of its own: in ``^ntp\\n((?:[ \\t]+.*\\n)+)`` it is the
    indent of one body line, not the lines.
    """
    for at, (op, av) in enumerate(flat):
        if op not in _REPEATS:
            continue
        needed = before + _sample(flat[:at])
        after = [*flat[at + 1:], *following]
        body = list(av[2])  # type: ignore[index]
        if av[1] is sre.MAXREPEAT:  # type: ignore[index]
            yield needed, body, after
        if depth < 3:
            for inner in _flat(body, 4):
                yield from _repeat_sites(inner, needed, after, depth + 1)


def _shapes(pattern: str, flags: int) -> Iterator[tuple[str, str, str]]:
    """``(before, unit, after)``: the text is ``before + unit * n +
    after``.

    First the plain units, from the first character.  Then, for each
    repeat of the pattern that has no upper bound: what the pattern
    needs up to it, a unit that the repeat or a later part accepts, and
    an end the rest may refuse.  ``^ip\\s+route\\s+(\\S.*?)\\s*$`` is
    never reached by a run of spaces from the first character; it is
    reached by ``ip route x`` and then the run.
    """
    seen: set[tuple[str, str, str]] = set()
    for unit in UNITS:
        seen.add(("", unit, ""))
        yield "", unit, ""
    try:
        parsed = sre_parser.parse(pattern, flags)
    except Exception:  # the pattern does not compile; nothing to time
        return
    for flat in _flat(list(parsed)):
        for before, body, following in _repeat_sites(flat, "", []):
            once = _sample(body)
            units = list(_accepted(*body[0])) if len(body) == 1 else []
            units.append(once)
            for later_op, later_av in following:
                if later_op in _REPEATS:
                    later = list(later_av[2])  # type: ignore[index]
                    units += list(_accepted(*later[0])[:2]) if len(later) == 1 else [_sample(later)]
                elif later_op in (sre.LITERAL, sre.IN):
                    units += list(_accepted(later_op, later_av)[:2])
            for unit in list(dict.fromkeys(unit for unit in units if unit))[:8]:
                for lead in dict.fromkeys(("", once)):
                    for after in ("", "\x01", "\n"):
                        shape = (before + lead, unit, after)
                        if shape not in seen:
                            seen.add(shape)
                            yield shape


#: How many units the first look at a text has.
_FIRST_LOOK = 1500
#: A pattern faster than this on the first look is not measured
#: further.  Work that is quadratic in 1,500 units is a million steps,
#: which takes milliseconds; this is well under that.
_WORTH_MEASURING = 0.0002
#: Growth is judged at a size that takes at least this long, or at the
#: largest size tried: a ratio of two timings near zero means nothing.
_ENOUGH_TO_JUDGE = 0.015
_LARGEST = _FIRST_LOOK * 64


def _slow_on(pattern: re.Pattern[str]) -> tuple[str, str, str] | None:
    """The shape *pattern* is super-linear on, or ``None``.

    For each shape: a first look; if that takes any time at all, the
    text is grown until a reading is long enough to judge, and the time
    for four times as much is compared with it -- twice, at two sizes,
    each the best of several readings.  One stalled reading cannot make
    a linear pattern look steep, nor a steep one linear.
    """

    def scan(text: str) -> None:
        for _ in pattern.finditer(text):
            pass

    for before, unit, after in _shapes(pattern.pattern, pattern.flags):

        def text(units: int, before: str = before, unit: str = unit, after: str = after) -> str:
            return before + unit * units + after

        if _best(scan, text(_FIRST_LOOK), 1) < _WORTH_MEASURING:
            continue
        size = _FIRST_LOOK * 4
        while size < _LARGEST and _best(scan, text(size), 1) < _ENOUGH_TO_JUDGE:
            size *= 4
        smaller, here = _best(scan, text(size // 4)), _best(scan, text(size))
        if here < _TOO_STEEP * smaller:
            continue
        larger = _best(scan, text(size * 4), 2)
        if larger > _TOO_STEEP * here and larger > 0.05:
            return before, unit, after
    return None


# ---------------------------------------------------------------------------
# Every regex the product holds
# ---------------------------------------------------------------------------

_RE_CALLS = {
    "compile": 1, "search": 2, "match": 2, "fullmatch": 2, "findall": 2, "finditer": 2,
    "split": 3, "sub": 4, "subn": 4,
}


def _names_of_re(tree: ast.AST) -> tuple[set[str], dict[str, str]]:
    """The names a module gives ``re`` itself (``import re``, ``import
    re as _re``, at the top or inside a function), and the names it
    gives ``re``'s functions (``from re import search as find``)."""
    modules: set[str] = set()
    functions: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.asname or "re" for alias in node.names if alias.name == "re")
        elif isinstance(node, ast.ImportFrom) and node.module == "re" and not node.level:
            functions.update(
                (alias.asname or alias.name, alias.name) for alias in node.names if alias.name in _RE_CALLS
            )
    return modules, functions


def _re_calls(root: Path) -> Iterator[tuple[Path, str, ast.Call, str, set[str]]]:
    """Every call of one of ``re``'s functions under *root*, with the
    function's own name and the names the module gives ``re`` --
    whatever the module calls it, and whether or not the pattern is
    passed by position."""
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules, functions = _names_of_re(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _RE_CALLS
                and isinstance(func.value, ast.Name)
                and func.value.id in modules
            ):
                yield path, source, node, func.attr, modules
            elif isinstance(func, ast.Name) and func.id in functions:
                yield path, source, node, functions[func.id], modules


def _pattern_of(call: ast.Call) -> ast.expr | None:
    """The pattern argument, by position or by name."""
    if call.args and not isinstance(call.args[0], ast.Starred):
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "pattern":
            return keyword.value
    return None


def _flags(call: ast.Call, function: str, modules: set[str]) -> int | None:
    """The flags of a call, or ``None`` if the source does not say:
    ``re.MULTILINE | re.DOTALL`` is read, under any name the module
    has for ``re``; a variable is not."""
    exprs = [kw.value for kw in call.keywords if kw.arg == "flags"]
    position = _RE_CALLS[function]
    if len(call.args) > position:
        exprs.append(call.args[position])
    names = dict.fromkeys(modules | {"re"}, re)
    flags = 0
    for expr in exprs:
        try:
            flags |= int(eval(compile(ast.Expression(expr), "<flags>", "eval"), names))
        except Exception:
            return None
    return flags


def _where(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path.name


def _is_literal(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _literals(root: Path) -> Iterator[tuple[str, str, int]]:
    """``(where, pattern, flags)`` for every call of an ``re`` function
    with a literal pattern and flags that can be read."""
    for path, _source, node, function, modules in _re_calls(root):
        pattern, flags = _pattern_of(node), _flags(node, function, modules)
        if _is_literal(pattern) and flags is not None:
            yield f"{_where(path)}:{node.lineno}", pattern.value, flags  # type: ignore[union-attr]


def _not_literal(root: Path) -> set[tuple[str, str]]:
    """``(file, what was written)`` for every ``re`` call the scan
    cannot time: its pattern is not a string literal, or its flags are
    not ones that can be read from the source (a pattern means
    different things under different flags)."""
    found = set()
    for path, source, node, function, modules in _re_calls(root):
        pattern = _pattern_of(node)
        if not _is_literal(pattern):
            written = " ".join((ast.get_source_segment(source, pattern) or "").split()) if pattern else ""
            found.add((_where(path), written[:60] or "<no pattern argument>"))
        elif _flags(node, function, modules) is None:
            found.add((_where(path), "flags of " + repr(pattern.value)[:50]))  # type: ignore[union-attr]
    return found


#: A string a module keeps in a tuple, list, set or dict is taken for a
#: pattern if it reads like one.  ``_JUNOS_SETFORM_VETO`` is such a
#: tuple: its strings are handed to ``re.search`` one by one.
_READS_LIKE_A_PATTERN = re.compile(r"\\[sSdDwWb]|\(\?|\[\^|^\^|[^\\]\$$|[*+?]\)")


def _kept(root_package: str) -> Iterator[tuple[str, str, int]]:
    """Compiled patterns a module or a class keeps, however they were
    built, and strings it keeps in a collection that read like one."""

    def patterns(value: object, depth: int = 0) -> Iterator[tuple[str, int]]:
        if isinstance(value, re.Pattern):
            if isinstance(value.pattern, str):
                # ``re.UNICODE`` is set on every compiled str pattern;
                # without it a kept pattern and the literal it was
                # compiled from are one entry, not two.
                yield value.pattern, value.flags & ~re.UNICODE
        elif isinstance(value, str):
            if depth and _READS_LIKE_A_PATTERN.search(value):
                # How it will be applied is not known here: as the
                # worst case, to a whole text.
                yield value, re.MULTILINE
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
        for attr, value in vars(module).items():
            for pattern, flags in patterns(value):
                yield f"{name}.{attr}", pattern, flags
            if isinstance(value, type) and value.__module__ == name:
                for inner, held in vars(value).items():
                    for pattern, flags in patterns(held):
                        yield f"{name}.{attr}.{inner}", pattern, flags


def _in_definitions(root: Path) -> Iterator[tuple[str, str, int]]:
    """Patterns in the shipped device definitions.  The collectors
    apply the probe patterns to what a device printed, with
    ``re.MULTILINE``; the prompt patterns are shipped beside them."""

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

#: ``re`` calls whose pattern is not a string literal, so that the scan
#: of the source cannot read it -- each with what does cover it.  A new
#: one fails the test until it is listed here with its answer.
_KEPT_FROM_LITERALS = "compiled at import from a tuple of literals and kept: `_kept` reads them"
NOT_LITERAL: dict[tuple[str, str], str] = {
    ("netcanon/collectors/probe.py", "pattern"): (
        "a probe pattern of a device definition: `_in_definitions` reads those"
    ),
    (
        "netcanon/migration/codecs/arista_eos/parse.py",
        r'rf"^username{_WS}+(?P<name>\S+)" rf"(?:{_WS}+privilege{_WS}+',
    ): "compiled at import and kept as `_USERNAME_RE`: `_kept` reads it",
    ("netcanon/migration/codecs/arista_eos/port_names.py", "p"): _KEPT_FROM_LITERALS,
    ("netcanon/migration/codecs/aruba_aoscx/port_names.py", "p"): _KEPT_FROM_LITERALS,
    ("netcanon/migration/codecs/cisco_iosxe_cli/port_names.py", "p"): _KEPT_FROM_LITERALS,
    (
        "netcanon/migration/codecs/cisco_iosxe_cli/render.py",
        r'rf"^(?:{_CISCO_PORT_PREFIX_ALTS})[\s\d/.:]*$"',
    ): "compiled at import and kept: `_kept` reads it",
    ("netcanon/migration/codecs/cisco_iosxr/port_names.py", "p"): _KEPT_FROM_LITERALS,
    ("netcanon/migration/codecs/cisco_nxos/port_names.py", "p"): _KEPT_FROM_LITERALS,
    ("netcanon/migration/codecs/dell_os10/port_names.py", "p"): _KEPT_FROM_LITERALS,
    ("netcanon/migration/codecs/opnsense/port_names.py", r'rf"^{prefix}(\d+)$"'): (
        "one of a fixed tuple of interface-family prefixes, then digits, anchored at both ends and "
        "matched against one port name: nothing in it can be split two ways"
    ),
    ("netcanon/migration/codecs/vyos/codec.py", "pat"): (
        "a string of `_JUNOS_SETFORM_VETO`: `_kept` reads the strings a class keeps in a tuple"
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
    def test_none_is_super_linear_on_a_text_built_for_it(self) -> None:
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
            shape = _slow_on(compiled)
            if shape is None and pattern in KNOWN_SLOW:
                # Said to be slow: look again before calling that stale.
                shape = _slow_on(compiled) or _slow_on(compiled)
            if shape is None:
                continue
            if pattern in KNOWN_SLOW:
                excused.add(pattern)
                continue
            before, unit, after = shape
            slow.append(f"{where}: {pattern!r} on {before!r} + {unit!r} repeated + {after!r}")
        assert slow == [], (
            "these patterns take time that grows faster than their input (see the Hard Rule on text "
            "nobody vouches for, and this module's docstring for the four shapes): " + "; ".join(slow)
        )
        assert excused == set(KNOWN_SLOW), "a pattern excused as slow no longer is: drop it from KNOWN_SLOW"

    @pytest.mark.parametrize(
        ("pattern", "flags"),
        [
            (r"^\s+mlag\s+\d+\s*$", re.MULTILINE),
            (r"([\w\-]+)=(\S+)", 0),
            (r"^ip\s+route\s+(?P<rest>\S.*?)\s*$", re.IGNORECASE),
            (r"^RP/\S+:\S+#\s*$", re.MULTILINE),
            (r"^ntp[ \t]*\r?\n((?:[ \t]+.*\r?\n)+)", re.MULTILINE),
        ],
        ids=[
            "an indented keyword", "a key that restarts inside a word", "a lazy value before trailing space",
            "two runs either side of a separator", "an indent and the rest of its line, inside a repeat",
        ],
    )
    def test_the_check_can_fail(self, pattern: str, flags: int) -> None:
        """Each is a pattern this codebase had."""
        assert _slow_on(re.compile(pattern, flags)) is not None

    @pytest.mark.parametrize(
        ("pattern", "flags"),
        [
            (r"^[^\S\n]+mlag\s+\d+\s*$", re.MULTILINE),
            (r"(?<![\w\-])([\w\-]+)=(\S+)", 0),
            (r"^ip\s+route\s+(?P<rest>\S(?:.*\S)?)\s*$", re.IGNORECASE),
            (r"^RP/[^\s:]+:\S+#\s*$", re.MULTILINE),
            (r"(?<!\d)(\d+)$", 0),
            (r"^\s+mlag\s+\d+\s*$", 0),
            (r"^ntp[ \t]*\r?\n((?:[ \t].*\r?\n)+)", re.MULTILINE),
        ],
        ids=[
            "an indent", "a key", "a value", "a separator", "a trailing number", "an indent on one line only",
            "a body line",
        ],
    )
    def test_and_it_passes_each_of_them_mended(self, pattern: str, flags: int) -> None:
        assert _slow_on(re.compile(pattern, flags)) is None

    def test_a_text_is_built_from_the_pattern_it_is_for(self) -> None:
        """A run of spaces from the first character never gets past
        the ``i`` of ``ip``."""
        shapes = set(_shapes(r"^ip\s+route\s+(?P<rest>\S.*?)\s*$", re.IGNORECASE))
        assert ("ip route x", " ", "\x01") in shapes
        assert ("", "   \n", "") in shapes

    def test_the_scan_reads_each_kind_of_place_a_pattern_is_kept(self) -> None:
        literal = {pattern for _where, pattern, _flags in _literals(PACKAGE)}
        # A literal written over several lines.
        assert any("vn-segment" in pattern and "vrf" in pattern for pattern in literal)
        kept: dict[str, set[str]] = {}
        for where, pattern, _flags in _kept("netcanon"):
            kept.setdefault(where, set()).add(pattern)
        # A pattern built at import from parts.
        (built,) = kept["netcanon.migration.codecs.arista_eos.parse._USERNAME_RE"]
        assert built not in literal and "username" in built
        # Strings a class keeps in a tuple and compiles one at a time.
        veto = kept["netcanon.migration.codecs.vyos.codec.VyOSCodec._JUNOS_SETFORM_VETO"]
        assert any(pattern.startswith("^set ") for pattern in veto)

    def test_every_call_the_scan_cannot_read_is_accounted_for(self) -> None:
        """A pattern that is not a literal is read some other way, or
        is argued here.  There is no default."""
        assert _not_literal(PACKAGE) == set(NOT_LITERAL)

    def test_the_scan_reads_re_however_a_module_names_it(self, tmp_path: Path) -> None:
        """A scan that knew only ``re.<function>("literal", flags)``
        passed over a slow pattern behind ``import re as _re``, behind
        ``from re import search``, in a call that names its arguments,
        and beside flags held in a variable.  One module with each."""
        (tmp_path / "forms.py").write_text(
            "import re\n"
            "import re as _rx\n"
            "from re import search as find, compile\n"
            "FLAGS = re.MULTILINE\n"
            "def f(text):\n"
            "    import re as inner\n"
            "    _rx.search(r'aliased\\s+x$', text)\n"
            "    find(r'imported\\s+x$', text)\n"
            "    compile(r'compiled\\s+x$', re.MULTILINE)\n"
            "    re.search(pattern=r'named\\s+x$', string=text, flags=_rx.IGNORECASE)\n"
            "    inner.sub(r'local\\s+x$', '', text)\n"
            "    re.search(r'variable flags\\s+x$', text, FLAGS)\n"
            "    re.search(text, text)\n"
            "    re.compile(*[text])\n"
            "    text.search('not re at all')\n",
            encoding="utf-8",
        )
        read = {pattern.split("\\")[0]: flags for _where_found, pattern, flags in _literals(tmp_path)}
        assert read == {
            "aliased": 0, "imported": 0, "compiled": re.MULTILINE, "named": re.IGNORECASE, "local": 0,
        }
        assert _not_literal(tmp_path) == {
            ("forms.py", "flags of 'variable flags\\\\s+x$'"),
            ("forms.py", "text"),
            ("forms.py", "<no pattern argument>"),
        }


# ---------------------------------------------------------------------------
# Every public codec, on a real capture with a run put into it
# ---------------------------------------------------------------------------

#: Whole lines with nothing on them.
FILLERS = {"blank lines": "\n", "lines of spaces": "   \n", "blank CRLF lines": "\r\n", "lines of a tab": "\t\n"}

#: Lines that say the next one belongs with them.  Code that gathers
#: such lines into one must not copy what it has gathered for each.
GOES_ON = {"continued lines": "add x=y \\\n", "an open quote": 'set a "b\n', "an open brace": "a {\n"}


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


def _with_a_run_in_every_line(text: str, spaces: int, where: str) -> str:
    """Every line of *text* that says anything, with a run of spaces
    in it: after its first word, or before a last word added to it."""
    run, out = " " * spaces, []
    for line in text.split("\n"):
        words = line.split(None, 1)
        if not words:
            out.append(line)
        elif where == "after the first word":
            indent = line[: len(line) - len(line.lstrip())]
            out.append(indent + words[0] + run + (words[1] if len(words) > 1 else "x"))
        else:
            out.append(line.rstrip() + run + "x")
    return "\n".join(out)


def _grows_faster_than_its_input(read: Callable[[str], object], make: Callable[[int], str], small: int) -> str:
    """Empty when reading ``make(4 * small)`` costs about four times
    ``make(small)``; otherwise what was measured.

    Quadratic work costs sixteen times.  One reading of each; only if
    that looks steep are both read again, the quicker of three -- so a
    text that is read in time costs one reading, and one stalled
    reading fails nothing.  The floor is there because a ratio of two
    timings near zero means nothing.
    """

    def quietly(text: str) -> None:
        try:
            read(text)
        except Exception:  # a codec may refuse the text; how long it took is the point
            pass

    low_text, high_text = make(small), make(4 * small)
    low, high = _best(quietly, low_text, 1), _best(quietly, high_text, 1)
    if high > _TOO_STEEP * low and high > 0.5:
        low, high = min(low, _best(quietly, low_text, 2)), min(high, _best(quietly, high_text, 2))
        if high > _TOO_STEEP * low and high > 0.5:
            return f"{small} units: {low:.3f}s; {4 * small} units: {high:.3f}s"
    return ""


class TestEveryPublicCodec:
    def test_each_has_a_capture_to_be_tried_on(self) -> None:
        """A codec with no small capture that detection gives to it is
        a codec these tests would pass without having run."""
        assert set(CAPTURES) == set(list_public_codecs())

    @pytest.mark.parametrize("filler", sorted(FILLERS))
    @pytest.mark.parametrize("name", list_public_codecs())
    def test_parse_fits_a_run_of_empty_lines(self, name: str, filler: str) -> None:
        codec, capture = get_codec(name), CAPTURES[name]
        slow = _grows_faster_than_its_input(
            codec.parse, lambda lines: _with_a_run(capture, FILLERS[filler] * lines), 8_000,
        )
        assert not slow, f"{name}.parse on a capture with a run of {filler}: {slow}"

    @pytest.mark.parametrize("shape", sorted(GOES_ON))
    @pytest.mark.parametrize("name", list_public_codecs())
    def test_parse_fits_a_run_of_lines_that_go_on(self, name: str, shape: str) -> None:
        """Larger than the others: joining a continued line by adding
        to one string is quick until the string is long."""
        codec, capture = get_codec(name), CAPTURES[name]
        slow = _grows_faster_than_its_input(
            codec.parse, lambda lines: _with_a_run(capture, GOES_ON[shape] * lines), 16_000,
        )
        assert not slow, f"{name}.parse on a capture with a run of {shape}: {slow}"

    @pytest.mark.parametrize("where", ["after the first word", "before a last word"])
    @pytest.mark.parametrize("name", list_public_codecs())
    def test_parse_fits_a_run_inside_each_of_its_lines(self, name: str, where: str) -> None:
        codec, capture = get_codec(name), CAPTURES[name]
        slow = _grows_faster_than_its_input(
            codec.parse, lambda spaces: _with_a_run_in_every_line(capture, spaces, where), 2_000,
        )
        assert not slow, f"{name}.parse on a capture with a run of spaces {where} of every line: {slow}"

    @pytest.mark.parametrize("filler", sorted(FILLERS))
    @pytest.mark.parametrize("name", list_public_codecs())
    def test_probe_fits_the_length_of_the_window(self, name: str, filler: str) -> None:
        """On the window alone, and on a capture's first line followed
        by the run: a probe that returns early on a header it knows has
        to be reached both ways."""
        probe = type(get_codec(name)).probe
        first_line = CAPTURES[name].split("\n", 1)[0] + "\n"
        most = DEFAULT_PROBE_BYTES // len(FILLERS[filler]) // 4
        for lead in ("", first_line):
            slow = _grows_faster_than_its_input(
                lambda text: probe(text[:DEFAULT_PROBE_BYTES]),
                lambda lines, lead=lead: lead + FILLERS[filler] * lines,
                most,
            )
            assert not slow, f"{name}.probe on a window of {filler}: {slow}"

    @pytest.mark.parametrize("window", [*sorted(FILLERS), "a comment mark and spaces"])
    def test_detection_of_a_window_with_nothing_in_it_is_quick(self, window: str) -> None:
        """Every codec's probe, on a probe window with nothing in it.
        About a minute for the lines of spaces before the patterns
        were mended."""
        unit = FILLERS.get(window, " ")
        text = ("#" if window not in FILLERS else "") + unit * (DEFAULT_PROBE_BYTES // len(unit))
        started = time.perf_counter()
        detect_codec(text)
        assert time.perf_counter() - started < 5.0

    def test_the_check_can_fail(self) -> None:
        """A reader with each defect, and the same reader without it."""
        capture = CAPTURES["cisco_iosxe_cli"]
        indented = re.compile(r"^\s+shutdown\s*$", re.MULTILINE)
        mended = re.compile(r"^[^\S\n]+shutdown\s*$", re.MULTILINE)

        def lines_of_spaces(lines: int) -> str:
            return _with_a_run(capture, "   \n" * lines)

        assert _grows_faster_than_its_input(indented.findall, lines_of_spaces, 4_000)
        assert not _grows_faster_than_its_input(mended.findall, lines_of_spaces, 4_000)

        def joined_by_adding(text: str) -> str:
            buffer = ""
            for line in text.splitlines():
                buffer = (buffer + " " + line.strip()).rstrip()
                if buffer.endswith("\\"):
                    buffer = buffer[:-1].rstrip()
                else:
                    buffer = ""
            return buffer

        def continued(lines: int) -> str:
            return _with_a_run(capture, GOES_ON["continued lines"] * lines)

        assert _grows_faster_than_its_input(joined_by_adding, continued, 16_000)

    def test_netcanon_is_the_package_under_test(self) -> None:
        assert Path(netcanon.__file__).resolve().parent == PACKAGE


# ---------------------------------------------------------------------------
# One kind of stanza, written many times
# ---------------------------------------------------------------------------


def _config(*lines: str) -> str:
    return "\n".join(lines) + "\n"


_AOSS_TOP = ("; J9729A Configuration Editor; Created on release #WB.16.08.0001", 'hostname "sw"')


def _eos_vxlan_stanzas(count: int) -> str:
    stanza = (
        "interface Vxlan1", "   vxlan source-interface Loopback1", "   vxlan udp-port 4789",
        "   vxlan vlan 110 vni 10110", "   vxlan vlan 111 vni 10111", "!",
    )
    return _config("hostname sw", "!", *(stanza * count))


def _eos_trunks(count: int) -> str:
    return _config("hostname sw", "!", *(
        line for number in range(1, count + 1) for line in (
            f"interface Port-Channel{number}", "   switchport mode trunk",
            "   switchport trunk allowed vlan 10-13", "   switchport trunk native vlan 10", "!",
        )
    ))


def _eos_bgp_vrfs(count: int) -> str:
    return _config("hostname sw", "!", "router bgp 65001", *(
        line for number in range(1, count + 1) for line in (f"   vrf T{number}", f"      rd 65001:{number}")
    ), "!")


def _eos_vxlan_vrfs(count: int) -> str:
    return _config(
        "hostname sw", "!", "interface Vxlan1", "   vxlan source-interface Loopback1",
        *(f"   vxlan vrf T{number} vni {50000 + number}" for number in range(1, count + 1)), "!",
    )


def _cx_trunks(count: int) -> str:
    return _config("hostname sw", "vlan 1,10-13", *(
        line for number in range(1, count + 1) for line in (
            f"interface 1/1/{number}", "    no shutdown", "    no routing", "    vlan trunk native 10",
            "    vlan trunk allowed 10-13",
        )
    ))


def _fortigate_interface_blocks(count: int) -> str:
    block = (
        "config system interface", '    edit "port1"', '        set vdom "root"', "    next",
        '    edit "agg1"', '        set vdom "root"', "        set type aggregate",
        '        set member "port1" "port2"', "    next", "end",
    )
    return _config(*(block * count))


def _net(number: int) -> str:
    return f"10.{number // 256 % 256}.{number % 256}"


def _junos_routes(count: int) -> str:
    return _config("set system host-name r1", *(
        f"set routing-options static route {_net(number)}.0/24 next-hop 192.0.2.1" for number in range(count)
    ))


def _junos_vrf_routes(count: int) -> str:
    return _config("set system host-name r1", *(
        f"set routing-instances RED routing-options static route {_net(number)}.0/24 next-hop 192.0.2.1"
        for number in range(count)
    ))


def _junos_instances(count: int) -> str:
    return _config("set system host-name r1", *(
        f"set routing-instances VRF{number} instance-type vrf" for number in range(count)
    ))


def _junos_users(count: int) -> str:
    return _config("set system host-name r1", *(
        f"set system login user u{number} class operator" for number in range(count)
    ))


def _junos_applied_groups(count: int) -> str:
    return _config("set system host-name r1", *(f"set apply-groups g{number}" for number in range(count)))


def _aoss_vlans(count: int) -> str:
    return _config(*_AOSS_TOP, *(
        line for number in range(count) for line in (f"vlan {number % 4000 + 2}", "   untagged 1-48", "   exit")
    ))


def _aoss_radius(count: int) -> str:
    """A host and then a global key, again and again; the key is the
    empty one on every other line, which gives nothing to anyone."""
    return _config(*_AOSS_TOP, *(
        line for number in range(count) for line in (
            f"radius-server host 10.{number // 65536 % 256}.{number // 256 % 256}.{number % 256}",
            'radius-server key ""' if number % 2 else 'radius-server key "fake-shared-secret"',
        )
    ))


def _aoss_radius_no_key(count: int) -> str:
    return _config(*_AOSS_TOP, *(
        line for number in range(count) for line in (
            f"radius-server host 10.{number // 65536 % 256}.{number // 256 % 256}.{number % 256}",
            'radius-server key ""',
        )
    ))


def _aoss_v3_users(count: int) -> str:
    return _config(*_AOSS_TOP, *(
        line for number in range(count) for line in (
            f'snmpv3 user "u{number}" auth sha "fakeauthpass"',
            f'snmpv3 group "operatorauth" user "u{number}" sec-model ver3',
        )
    ))


def _aoss_trunks(count: int) -> str:
    return _config(
        *_AOSS_TOP,
        *(line for number in range(1, count + 1) for line in (f"interface {number}", '   name "p"', "   exit")),
        *(f"trunk {number} trk{number} lacp" for number in range(1, count + 1)),
    )


def _opnsense_laggs(count: int) -> str:
    return _config(
        '<?xml version="1.0"?>', "<opnsense>",
        "<system><hostname>fw</hostname><domain>example.test</domain></system>", "<interfaces>",
        *(f"<opt{number}><if>igb{number}</if><enable>1</enable></opt{number}>" for number in range(count)),
        "</interfaces>", "<laggs>",
        *(
            f"<lagg><laggif>lagg{number}</laggif><members>igb{number}</members><proto>lacp</proto></lagg>"
            for number in range(count)
        ),
        "</laggs>", "</opnsense>",
    )


def _routeros_pools(count: int) -> str:
    return _config(
        "# 2026-01-01 00:00:00 by RouterOS 7.14", "/ip dhcp-server network",
        *(f"add address={_net(number)}.0/24 gateway={_net(number)}.1" for number in range(count)),
        "/ip pool",
        *(f"add name=p{number} ranges={_net(number)}.10-{_net(number)}.20" for number in range(count)),
    )


#: What was slow, by the handler that was fixed: codec, the smaller
#: count, the text.  Each was read in time that grew with the square of
#: the count -- measured before the fix at four times the count here:
#: from under a second (trunks that share their VLANs) to half a minute
#: (RouterOS pools), on half a megabyte to two megabytes of text.
STANZAS: dict[str, tuple[str, int, Callable[[int], str]]] = {
    "arista_eos: the Vxlan stanza again and again": ("arista_eos", 1500, _eos_vxlan_stanzas),
    "arista_eos: trunks that share their VLANs": ("arista_eos", 3000, _eos_trunks),
    "arista_eos: a VRF under router bgp": ("arista_eos", 4000, _eos_bgp_vrfs),
    "arista_eos: a VRF's VNI": ("arista_eos", 4000, _eos_vxlan_vrfs),
    "aruba_aoscx: trunks that share their VLANs": ("aruba_aoscx", 3000, _cx_trunks),
    "fortigate_cli: the interface block again and again": ("fortigate_cli", 2500, _fortigate_interface_blocks),
    "juniper_junos: static routes": ("juniper_junos", 4000, _junos_routes),
    "juniper_junos: a VRF's static routes": ("juniper_junos", 4000, _junos_vrf_routes),
    "juniper_junos: routing instances": ("juniper_junos", 4000, _junos_instances),
    "juniper_junos: users": ("juniper_junos", 4000, _junos_users),
    "juniper_junos: applied groups": ("juniper_junos", 8000, _junos_applied_groups),
    "aruba_aoss: VLAN stanzas that claim the same ports": ("aruba_aoss", 2500, _aoss_vlans),
    "aruba_aoss: RADIUS hosts and a global key": ("aruba_aoss", 3000, _aoss_radius),
    "aruba_aoss: RADIUS hosts and a key that is empty": ("aruba_aoss", 3000, _aoss_radius_no_key),
    "aruba_aoss: SNMPv3 users and their groups": ("aruba_aoss", 3000, _aoss_v3_users),
    "aruba_aoss: trunks over many interfaces": ("aruba_aoss", 2500, _aoss_trunks),
    "opnsense: laggs over many interfaces": ("opnsense", 3000, _opnsense_laggs),
    "mikrotik_routeros: pools over many networks": ("mikrotik_routeros", 1500, _routeros_pools),
}


class TestParseFitsTheNumberOfItsStanzas:
    """A handler runs once per line.  One that reads through what the
    earlier lines made costs the square of the lines, and no line of
    such a config is odd in itself.

    This is a list -- one text for each handler that was found doing
    it -- and not a search: the search is ``tools/stanza_cost_search.py``,
    which takes minutes.  Each text is one kind of stanza written N
    times and then 4N.
    """

    @pytest.mark.parametrize("title", sorted(STANZAS))
    def test_one_kind_of_stanza_written_many_times(self, title: str) -> None:
        name, small, make = STANZAS[title]
        tree = get_codec(name).parse(make(3))
        assert tree is not None
        slow = _grows_faster_than_its_input(get_codec(name).parse, make, small)
        assert not slow, f"{title}: {slow}"

    def test_each_text_is_read_and_makes_what_it_says(self) -> None:
        """A text the codec refused, or read as nothing, would be read
        quickly whatever the handler did."""
        made = {
            "arista_eos: the Vxlan stanza again and again": lambda t: len(t.vxlan_vnis),
            "arista_eos: trunks that share their VLANs": lambda t: len(t.interfaces),
            "arista_eos: a VRF under router bgp": lambda t: len(t.routing_instances),
            "arista_eos: a VRF's VNI": lambda t: len(t.routing_instances),
            "aruba_aoscx: trunks that share their VLANs": lambda t: len(t.interfaces),
            "fortigate_cli: the interface block again and again": lambda t: len(t.lags),
            "juniper_junos: static routes": lambda t: len(t.static_routes),
            "juniper_junos: a VRF's static routes": lambda t: len(t.static_routes),
            "juniper_junos: routing instances": lambda t: len(t.routing_instances),
            "juniper_junos: users": lambda t: len(t.local_users),
            "juniper_junos: applied groups": lambda t: 40,
            "aruba_aoss: VLAN stanzas that claim the same ports": lambda t: len(t.vlans),
            "aruba_aoss: RADIUS hosts and a global key": lambda t: len(t.radius_servers),
            "aruba_aoss: RADIUS hosts and a key that is empty": lambda t: len(t.radius_servers),
            "aruba_aoss: SNMPv3 users and their groups": lambda t: len(t.snmp.v3_users),
            "aruba_aoss: trunks over many interfaces": lambda t: len(t.lags),
            "opnsense: laggs over many interfaces": lambda t: len(t.lags),
            "mikrotik_routeros: pools over many networks": lambda t: len(t.dhcp_servers),
        }
        assert set(made) == set(STANZAS)
        for title, (name, _small, make) in STANZAS.items():
            assert made[title](get_codec(name).parse(make(40))) >= 40, title

    def test_the_check_can_fail(self) -> None:
        """A reader whose cost is the square of its lines, whatever
        the machine.  (One that really looks through a list it is
        making, for every line, is quick enough on a fast machine at
        this size to pass under the check's floor: the control then
        said the check could not fail.  The search tool's own tests
        read such a reader, with a floor set for it.)"""

        def costs_the_square_of_its_lines(text: str) -> None:
            lines = text.count("\n")
            time.sleep(lines * lines * 2.5e-8)

        # Asked up to three times: the first pair of readings decides
        # that a text is read in time, so one stalled reading of the
        # smaller text would pass a slow reader.  That is the safe way
        # round for the check, and the wrong way round for this test.
        assert any(
            _grows_faster_than_its_input(
                costs_the_square_of_its_lines, lambda count: _config(*(f"route {n}" for n in range(count))), 1500,
            )
            for _attempt in range(3)
        )

    def test_and_passes_a_reader_whose_cost_is_its_length(self) -> None:
        """As long at the larger size as the reader above, and four
        times the smaller, not sixteen."""

        def costs_its_lines(text: str) -> None:
            time.sleep(text.count("\n") * 1.5e-4)

        assert not _grows_faster_than_its_input(
            costs_its_lines, lambda count: _config(*(f"route {n}" for n in range(count))), 1500,
        )
