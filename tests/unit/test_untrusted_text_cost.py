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

Two more lists stand beside it.  One is of records that are given many
lines -- the addresses of one interface, the members of one LAG --
where the handler looked through the record's own list before it added
to it (``TestParseFitsTheLinesOfOneRecord``): the tool writes a line
many times with a counter in its last number, which for most of these
lines makes many records and not many lines for one.  The other is of
work done after the parse, by the port-name translator, a renderer or
the plan (``TestATranslationFitsWhatItIsGiven``, and for a renderer
timed by itself ``TestARenderFitsTheTrunksItIsGiven``): the tool times
``parse``.  The first of the two has a search of its own that needs no
clock: ``TestNoListIsLookedThroughThenAddedTo`` reads the source
for a list that one function both looks through and adds to.

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
faster than the text will report.  That is counted and limited
(``netcanon.migration.limits``, ``tests/unit/migration/test_limits.py``).
Every test here reads its texts with those limits off
(``no_config_limits``): the texts are larger than any device, a limit
would refuse some of them, and a refused text is read quickly whatever
the code behind it costs.  A reading that is refused all the same is
an error here, never a time.

Each check is also handed something that is slow, and has to say so.
"""

from __future__ import annotations

import ast
import functools
import importlib
import pkgutil
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from re import _constants as sre
from re import _parser as sre_parser
from typing import Any

import pytest
import yaml

import netcanon
from netcanon.definitions import LIBRARY_DIR
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.migration.device_models import Deployment, MemberSpec, compile_deployment, load_model_families_dir
from netcanon.migration.limits import LimitExceeded
from netcanon.services.migration_detect import DEFAULT_PROBE_BYTES, detect_codec
from netcanon.services.migration_pipeline import run_plan_with_models, run_plan_with_overrides

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("no_config_limits")]

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "netcanon"

# ---------------------------------------------------------------------------
# Reading the clock on a machine that is doing other things
# ---------------------------------------------------------------------------

#: Four times the input: linear work takes four times as long,
#: quadratic work sixteen.  Halfway, on a log scale.
_TOO_STEEP = 8.0

#: A ratio of two timings near zero means nothing: the larger text has
#: to take this long before its ratio is believed.
_FLOOR = 0.5

#: Past this the larger text is not read at a third size before it is
#: called slow: a reader that costs the square of its input would take
#: sixteen times as long again.
_PLAINLY_SLOW = 2.0


def _cpu_clock() -> Callable[[], float]:
    """Seconds of CPU the calling thread has had.

    The readings below are compared with each other, and a ratio of two
    wall-clock times is only as good as the machine is quiet: time
    another process had the CPU is in one reading and not in the next,
    and a reading of a few milliseconds fits inside one turn at the CPU
    where a reading of a few hundred does not.  The thread's own CPU
    time leaves all of that out.  On Windows the thread clock moves in
    steps of 15.6 ms whatever resolution it reports, too coarse to read
    a millisecond, so the thread's cycle count is read there instead:
    ticks of the processor's time-stamp counter, at the rate the
    registry states for it.
    """
    if sys.platform != "win32":
        return time.thread_time
    import ctypes
    import winreg

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentThread.restype = ctypes.c_void_p
    kernel32.QueryThreadCycleTime.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong)]

    def cycles() -> int:
        count = ctypes.c_ulonglong()
        kernel32.QueryThreadCycleTime(kernel32.GetCurrentThread(), ctypes.byref(count))
        return count.value

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            rate = winreg.QueryValueEx(key, "~MHz")[0] * 1e6
    except OSError:
        return time.perf_counter
    return lambda: cycles() / rate


_now = _cpu_clock()


def _best(read: Callable[[str], object], text: str, tries: int = 3) -> float:
    """The quickest of *tries* readings.  A loaded machine only ever
    adds time, so the least of several is the one to believe."""
    best = float("inf")
    for _ in range(tries):
        started = _now()
        read(text)
        best = min(best, _now() - started)
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


def _not_literal(root: Path) -> Counter[tuple[str, str]]:
    """``(file, what was written)`` for every ``re`` call the scan
    cannot time: its pattern is not a string literal, or its flags are
    not ones that can be read from the source (a pattern means
    different things under different flags).  Counted: a second call
    spelt like a listed one in the same file is a new call."""
    found: Counter[tuple[str, str]] = Counter()
    for path, source, node, function, modules in _re_calls(root):
        pattern = _pattern_of(node)
        if not _is_literal(pattern):
            written = " ".join((ast.get_source_segment(source, pattern) or "").split()) if pattern else ""
            found[(_where(path), written[:60] or "<no pattern argument>")] += 1
        elif _flags(node, function, modules) is None:
            found[(_where(path), "flags of " + repr(pattern.value)[:50])] += 1  # type: ignore[union-attr]
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
        assert _not_literal(PACKAGE) == Counter(dict.fromkeys(NOT_LITERAL, 1))

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
        assert set(_not_literal(tmp_path)) == {
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


def _grows_faster_than_its_input(
    read: Callable[[str], object],
    make: Callable[[int], str],
    small: int,
    *,
    largest: int | None = None,
    floor: float = _FLOOR,
) -> str:
    """Empty when reading ``make(4 * small)`` costs about four times
    ``make(small)``; otherwise what was measured.

    Quadratic work costs sixteen times.  One reading of each; only if
    that looks steep are both read again, the quicker of three -- so a
    text that is read in time costs one reading, and one stalled
    reading fails nothing.  *floor* is there because a ratio of two
    timings near zero means nothing.

    A step that still looks steep is then asked a second question: is
    the NEXT step steep too?  A reader that costs the square of its
    input is; one whose smaller reading happened to be quick is not.
    On a shared CI runner a parse that is linear here over a 64-fold
    range (3.3, 4.3 and 4.2 times for each four times the text) was
    read once as 8.7 times -- 0.099 s and 0.857 s -- and two readings
    cannot tell that from a defect.  The third size is not read where
    it would decide nothing: past *largest* units (a probe reads a
    window and no further), or once the second size is plainly slow.
    """

    def quietly(text: str) -> None:
        try:
            read(text)
        except LimitExceeded:
            # Refused for its size: nothing was read, and the time to
            # say no is not what this measures.
            raise
        except Exception:  # a codec may refuse the text; how long it took is the point
            pass

    low_text, high_text = make(small), make(4 * small)
    low, high = _best(quietly, low_text, 1), _best(quietly, high_text, 1)
    if not (high > _TOO_STEEP * low and high > floor):
        return ""
    low, high = min(low, _best(quietly, low_text, 2)), min(high, _best(quietly, high_text, 2))
    if not (high > _TOO_STEEP * low and high > floor):
        return ""
    measured = f"{small} units: {low:.3f}s; {4 * small} units: {high:.3f}s"
    if largest is not None and 16 * small > largest:
        return measured
    if high > _PLAINLY_SLOW and small >= 4:
        # Too slow to read sixteen times as much of.  Ask the question one
        # step DOWN instead: a reader that costs the square of its input is
        # steep there too, and a quarter of the smaller text costs little.
        # If that step is not steep, the third size is read after all.
        lower = _best(quietly, make(small // 4))
        if low > _TOO_STEEP * lower:
            return f"{small // 4} units: {lower:.3f}s; {measured}"
    higher = _best(quietly, make(16 * small), 1)
    if higher > _TOO_STEEP * high:
        return f"{measured}; {16 * small} units: {higher:.3f}s"
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
        # A floor of its own: with the fourth shape put back, the larger
        # text reads in under a second here -- on a faster machine, under
        # the floor the other texts use, and so in time.  The mended
        # parse reads it in a seventh of a second.
        slow = _grows_faster_than_its_input(
            codec.parse, lambda lines: _with_a_run(capture, GOES_ON[shape] * lines), 16_000, floor=0.2,
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
                largest=4 * most,  # the window: a third size would be the second again
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

        # Up to three times, and with a floor of its own: on a machine twice
        # as fast the larger reading is under the floor the real texts use.
        assert any(
            _grows_faster_than_its_input(indented.findall, lines_of_spaces, 4_000, largest=16_000, floor=0.05)
            for _attempt in range(3)
        )
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

        assert any(
            _grows_faster_than_its_input(joined_by_adding, continued, 16_000, largest=64_000, floor=0.05)
            for _attempt in range(3)
        )

    def test_netcanon_is_the_package_under_test(self) -> None:
        assert Path(netcanon.__file__).resolve().parent == PACKAGE


# ---------------------------------------------------------------------------
# One kind of stanza, written many times
# ---------------------------------------------------------------------------


def _config(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _routes(count: int) -> str:
    return _config(*(f"route {number}" for number in range(count)))


def _takes(seconds: float) -> None:
    """Take *seconds*, whatever the machine: the controls of the
    timing check plant their cost with this.  Not ``time.sleep``,
    whose shortest sleep is a scheduler tick -- fifteen milliseconds
    on Windows -- so that a planted cost of four came out as fifteen
    and the ratio the control is about was gone."""
    until = _now() + seconds
    while _now() < until:
        pass


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


def _junos_v3_users(count: int) -> str:
    """A user's key, and then its group: each line found its user by
    reading every user so far."""
    return _config("set system host-name r1", *(
        line for number in range(count) for line in (
            f"set snmp v3 usm local-engine user u{number} authentication-sha authentication-key fakeauthkey{number}",
            f"set snmp v3 vacm security-to-group security-model usm security-name u{number} group readonly",
        )
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


def _aoss_trunk_lines_of_one_lag(count: int) -> str:
    """One LAG, a ``trunk`` line for each of its ports.  A second
    line for a LAG joins the first record, and a handler that goes
    through the members it already has, once per line, costs the
    square of the lines -- ten seconds for 16,000 of them, where
    the text above (a LAG per line) was read in a fifth of one."""
    return _config(
        *_AOSS_TOP,
        *(line for number in range(1, count + 1) for line in (f"interface {number}", '   name "p"', "   exit")),
        *(f"trunk {number} trk1 lacp" for number in range(1, count + 1)),
    )


#: Ports named by each line of the text below.
_PORTS_A_TRUNK_LINE = 64


def _aoss_trunk_lines_of_many_ports(count: int) -> str:
    """One LAG again, each ``trunk`` line a range of ports it does
    not have yet.  The text above is a port a line, and it shows
    what a handler does in Python once for each member.  It does
    not show a membership test against the LAG's own list: that
    is done in C at a tenth of the cost a step, and at a port a
    line the lines cost as much to read as the looking does until
    there are twenty thousand of them -- that break was caught in
    two runs of three.  Here the ports are many and the lines
    few, so the looking is all there is to measure."""
    return _config(
        *_AOSS_TOP,
        *(
            f"trunk {first}-{first + _PORTS_A_TRUNK_LINE - 1} trk1 lacp"
            for first in range(1, count * _PORTS_A_TRUNK_LINE + 1, _PORTS_A_TRUNK_LINE)
        ),
    )


def _eos_bgp_vlans(count: int) -> str:
    """``vlan N`` under ``router bgp``, looked up among the VLANs
    and the MAC-VRFs made so far."""
    return _config(
        "hostname sw", "!", *(line for _ in range(count) for line in ("vlan 2", "!")),
        "router bgp 65001", *("   vlan 3" for _ in range(count)), "!",
    )


def _eos_bgp_vrfs_then_vlans(count: int) -> str:
    return _config(
        "hostname sw", "!", "router bgp 65001", *(f"   vrf T{n}" for n in range(count)),
        *(f"   vlan {n % 4000 + 2}" for n in range(count)), "!",
    )


def _eos_vxlan_stanzas_with_a_port(count: int) -> str:
    """A UDP port that is not the default is written onto every
    VNI made so far."""
    stanza = (
        "interface Vxlan1", "   vxlan source-interface Loopback1", "   vxlan udp-port 4790",
        "   vxlan vlan 110 vni 10110", "   vxlan vlan 111 vni 10111", "!",
    )
    return _config("hostname sw", "!", *(stanza * count))


def _junos_vnis(count: int) -> str:
    return _config(
        "set system host-name r1", "set vlans v10 vlan-id 10",
        *(f"set vlans v10 vxlan vni {10000 + n}" for n in range(count)),
    )


def _junos_deactivated(count: int) -> str:
    """An interface a line, and each deactivated.  A ``set`` line is
    asked whether it is under a deactivated path: asked of each
    path in turn, that is every line against every path."""
    return _config(
        "set system host-name r1",
        *(f"set interfaces ge-0/0/{n} description d{n}" for n in range(count)),
        *(f"deactivate interfaces ge-0/0/{n}" for n in range(count)),
    )


def _junos_open_comments(count: int) -> str:
    """A ``/*`` in every line and no ``*/`` in the text.  Comments
    were cut out of hierarchical text by a pattern, and the pattern
    was run over every Junos text before its form was known: from
    each ``/*`` it read to the end of the text for the ``*/``.
    Set-form like this -- a description, a wildcard -- cost the
    square of its lines: 8,000 of them, a third of a megabyte, took
    seven seconds."""
    return _config("set system host-name r1", *(
        f"set interfaces ge-0/0/{n} description a/* b" for n in range(count)
    ))


#: Characters of the one word, for each unit of the two texts below.
_WORD_A_UNIT = 100


def _junos_long_word(count: int) -> str:
    """One ``set`` line with one long word in it.  The words of a
    line were split by ``shlex``, which builds a word by adding a
    character at a time to a string it keeps: the word was copied
    for each character of it."""
    return _config("set system host-name r1", "set interfaces ge-0/0/1 description " + "a" * (_WORD_A_UNIT * count))


def _junos_long_string(count: int) -> str:
    """The same in quotes, with a backslash now and then."""
    return _config(
        "set system host-name r1",
        'set interfaces ge-0/0/1 description "' + ("a" * (_WORD_A_UNIT - 2) + '\\"') * count + '"',
    )


#: Tags ahead of the statement, for each unit of the text below.
_TAGS_A_UNIT = 10


def _junos_tags(count: int) -> str:
    """One statement with many tags ahead of it.  The tags were
    taken off the front of the statement's words one at a time, and
    each one moved every word after it."""
    return _config(
        "system {", "    host-name r1;", "}", "interfaces {",
        "    " + "protect: " * (_TAGS_A_UNIT * count) + "ge-0/0/1 {", "        mtu 9000;", "    }", "}",
    )


def _junos_path_lengths(words: int, every_length: bool) -> str:
    """``deactivate`` lines, and as many ``set`` lines of *words*
    words that run beside them to the end and are under none.  With
    *every_length* there is a path of each length from one word to
    *words*; without, the same number of paths, all of half that
    length -- the same text to read, near enough."""
    if every_length:
        paths = ("deactivate " + "x " * (length - 1) + "z" for length in range(1, words + 1))
    else:
        paths = ("deactivate " + "x " * (words // 2) + f"z{n}" for n in range(words))
    return _config("set system host-name r1", *paths, *("set " + "x " * words for _ in range(words)))


def _iosxe_class_maps(count: int) -> str:
    """Every line a Tier-3 section of its own.  The detector that
    every CLI parse runs kept its labels in a list and looked
    through it for each match: 40,000 of these lines, 1.1 MB, took
    nine seconds."""
    return _config("hostname r1", *(f"class-map match-any CM{n}" for n in range(count)))


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
    "juniper_junos: SNMPv3 users and their groups": ("juniper_junos", 4000, _junos_v3_users),
    "aruba_aoss: VLAN stanzas that claim the same ports": ("aruba_aoss", 2500, _aoss_vlans),
    "aruba_aoss: RADIUS hosts and a global key": ("aruba_aoss", 3000, _aoss_radius),
    "aruba_aoss: RADIUS hosts and a key that is empty": ("aruba_aoss", 3000, _aoss_radius_no_key),
    "aruba_aoss: SNMPv3 users and their groups": ("aruba_aoss", 3000, _aoss_v3_users),
    "aruba_aoss: trunks over many interfaces": ("aruba_aoss", 2500, _aoss_trunks),
    "aruba_aoss: trunk lines of one LAG": ("aruba_aoss", 2500, _aoss_trunk_lines_of_one_lag),
    "aruba_aoss: trunk lines of one LAG, many ports a line": (
        "aruba_aoss", 160, _aoss_trunk_lines_of_many_ports,
    ),
    "arista_eos: a VLAN under router bgp, again and again": ("arista_eos", 4000, _eos_bgp_vlans),
    "arista_eos: VRFs and then VLANs under router bgp": ("arista_eos", 4000, _eos_bgp_vrfs_then_vlans),
    "arista_eos: Vxlan stanzas that set a UDP port": ("arista_eos", 1500, _eos_vxlan_stanzas_with_a_port),
    "juniper_junos: the VNIs of one VLAN": ("juniper_junos", 4000, _junos_vnis),
    "juniper_junos: deactivated paths": ("juniper_junos", 4000, _junos_deactivated),
    "juniper_junos: comments that are never closed": ("juniper_junos", 2000, _junos_open_comments),
    "juniper_junos: tags ahead of one statement": ("juniper_junos", 4000, _junos_tags),
    "juniper_junos: one long word in a line": ("juniper_junos", 1000, _junos_long_word),
    "juniper_junos: one long quoted string in a line": ("juniper_junos", 1000, _junos_long_string),
    "cisco_iosxe_cli: Tier-3 sections, each of its own": ("cisco_iosxe_cli", 10000, _iosxe_class_maps),
    "opnsense: laggs over many interfaces": ("opnsense", 3000, _opnsense_laggs),
    "mikrotik_routeros: pools over many networks": ("mikrotik_routeros", 1500, _routeros_pools),
}


#: Reading paths of every length may cost this many times what
#: reading paths of one length costs.  Asked once for each length, the
#: parser took two and a half to three times as long on the text the
#: test uses; walking each line once, it takes the same.
_FOR_THE_LENGTHS = 1.7


def _costs_more_with_every_length(read: Callable[[str], object], words: int) -> str:
    """Empty when *read* takes about as long over ``deactivate``
    paths of every length as over paths of one length; otherwise what
    was measured.  The quicker of two readings of each."""
    every = _best(read, _junos_path_lengths(words, True), 2)
    one = _best(read, _junos_path_lengths(words, False), 2)
    if every <= _FOR_THE_LENGTHS * one:
        return ""
    return f"paths of every length up to {words} words: {every:.3f}s; of one length: {one:.3f}s"


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
            "juniper_junos: SNMPv3 users and their groups": lambda t: len(t.snmp.v3_users),
            "aruba_aoss: VLAN stanzas that claim the same ports": lambda t: len(t.vlans),
            "aruba_aoss: RADIUS hosts and a global key": lambda t: len(t.radius_servers),
            "aruba_aoss: RADIUS hosts and a key that is empty": lambda t: len(t.radius_servers),
            "aruba_aoss: SNMPv3 users and their groups": lambda t: len(t.snmp.v3_users),
            "aruba_aoss: trunks over many interfaces": lambda t: len(t.lags),
            "aruba_aoss: trunk lines of one LAG": lambda t: len(t.lags[0].members),
            "aruba_aoss: trunk lines of one LAG, many ports a line": (
                lambda t: len(t.lags[0].members) // _PORTS_A_TRUNK_LINE
            ),
            "arista_eos: a VLAN under router bgp, again and again": lambda t: len(t.vlans),
            "arista_eos: VRFs and then VLANs under router bgp": lambda t: len(t.routing_instances),
            "arista_eos: Vxlan stanzas that set a UDP port": lambda t: len(t.vxlan_vnis),
            "juniper_junos: the VNIs of one VLAN": lambda t: len(t.vxlan_vnis),
            "juniper_junos: deactivated paths": lambda t: len(t.dropped_tier3_sections),
            "juniper_junos: comments that are never closed": lambda t: len(t.interfaces),
            # One port, whatever the count: it is behind every tag.
            # (``mtu 9000`` on the port: 8986 in the tree, the payload.)
            "juniper_junos: tags ahead of one statement": lambda t: 40 * [i.mtu for i in t.interfaces].count(8986),
            # One word, whatever the count: as long as the text says.
            "juniper_junos: one long word in a line": lambda t: len(t.interfaces[0].description) // _WORD_A_UNIT,
            "juniper_junos: one long quoted string in a line": (
                lambda t: len(t.interfaces[0].description) // (_WORD_A_UNIT - 1)
            ),
            "cisco_iosxe_cli: Tier-3 sections, each of its own": lambda t: len(t.dropped_tier3_sections),
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
            _takes(lines * lines * 2e-9)

        # Asked up to three times: the first pair of readings decides
        # that a text is read in time, so one stalled reading of the
        # smaller text would pass a slow reader.  That is the safe way
        # round for the check, and the wrong way round for this test.
        said = ""
        for _attempt in range(3):
            said = said or _grows_faster_than_its_input(
                costs_the_square_of_its_lines, _routes, 1500, floor=0.02,
            )
        # All three sizes were read: it is steep at each step.
        assert said.count("units") == 3, said

    def test_and_passes_a_reader_whose_cost_is_its_length(self) -> None:
        """As long at the middle size as the reader above, and four
        times the smaller, not sixteen."""

        def costs_its_lines(text: str) -> None:
            _takes(text.count("\n") * 1.2e-5)

        assert not _grows_faster_than_its_input(costs_its_lines, _routes, 1500, floor=0.02)

    def test_and_passes_a_reader_that_was_only_steep_once(self) -> None:
        """What a CI runner did to a linear parse: the smaller text
        read quickly, the next one eight and a half times slower, and
        nothing of the kind after that.  Two readings cannot tell this
        from a defect; the third size can."""

        def costs_its_lines_after_a_quick_start(text: str) -> None:
            lines = text.count("\n")
            _takes(lines * 1.2e-5 if lines > 1500 else lines * 5e-6)

        assert not _grows_faster_than_its_input(
            costs_its_lines_after_a_quick_start, _routes, 1500, floor=0.02,
        )

    def test_path_lengths_are_not_paid_for(self) -> None:
        """Not a kind of stanza written many times, and not a cost the
        check above can read: a ``set`` line asked once for each LENGTH
        of deactivated path costs the square of its words, but the
        paths of every length are themselves half the square of the
        longest in text, so the whole grows as the text to the power
        of one and a half -- eight times for four times the text,
        which is exactly where that check draws its line.

        So the same words are read twice: with a path of every
        length, and with as many paths of one length.  They cost
        about the same to read, or the lengths are being paid for."""
        parse = get_codec("juniper_junos").parse
        assert parse(_junos_path_lengths(40, True)).hostname == "r1"
        said = _costs_more_with_every_length(parse, 800)
        assert not said, said

    def test_and_that_check_can_fail(self) -> None:
        """A reader that asks once for each length, as the parser did."""

        def asks_once_for_each_length(text: str) -> None:
            lines = [line.split() for line in text.splitlines()]
            paths = {tuple(words[1:]) for words in lines if words[0] == "deactivate"}
            lengths = sorted({len(path) for path in paths})
            for words in lines:
                if words[0] == "set":
                    assert not [length for length in lengths if tuple(words[1:1 + length]) in paths]

        assert _costs_more_with_every_length(asks_once_for_each_length, 300)

    def test_a_third_size_is_not_read_past_the_largest_that_means_anything(self) -> None:
        """A probe reads a window.  Past it nothing grows, so a third
        size would clear a reader that is quadratic within the window:
        with *largest* given, two steep readings are the verdict."""

        def squares_within_a_window(text: str) -> None:
            lines = min(text.count("\n"), 6000)
            _takes(lines * lines * 2e-9)

        assert not _grows_faster_than_its_input(squares_within_a_window, _routes, 1500, floor=0.02)
        # Asked up to three times, as the control above is: one stalled
        # reading of the smaller text passes a slow reader.
        assert any(
            _grows_faster_than_its_input(squares_within_a_window, _routes, 1500, floor=0.02, largest=6000)
            for _attempt in range(3)
        )


# ---------------------------------------------------------------------------
# Trunks that state no allowed list
# ---------------------------------------------------------------------------


def _eos_trunks_with_no_list(count: int) -> str:
    return _config("hostname sw", "!", "vlan 10-13", "!", *(
        line for number in range(1, count + 1)
        for line in (f"interface Ethernet{number}", "   switchport mode trunk", "!")
    ))


def _cx_trunks_with_no_list(count: int) -> str:
    return _config("hostname sw", "vlan 1,10-13", *(
        line for number in range(1, count + 1)
        for line in (f"interface 1/1/{number}", "    no shutdown", "    no routing", "    vlan trunk native 1")
    ))


def _iosxe_trunks_with_no_list(count: int) -> str:
    return _config("hostname sw", "!", "vlan 10-13", "!", *(
        line for number in range(1, count + 1)
        for line in (f"interface GigabitEthernet1/0/{number}", " switchport mode trunk", "!")
    ))


def _nxos_trunks_with_no_list(count: int) -> str:
    return _config("hostname sw", "", "vlan 10-13", "", *(
        line for number in range(1, count + 1)
        for line in (f"interface Ethernet1/{number}", "  switchport mode trunk", "")
    ))


#: The four parsers that make every VLAN id of a trunk with no allowed
#: line: the smaller count, and the text.
TRUNKS_WITH_NO_LIST: dict[str, tuple[int, Callable[[int], str]]] = {
    "arista_eos": (400, _eos_trunks_with_no_list),
    "aruba_aoscx": (400, _cx_trunks_with_no_list),
    "cisco_iosxe_cli": (400, _iosxe_trunks_with_no_list),
    "cisco_nxos": (400, _nxos_trunks_with_no_list),
}


class TestATrunkWithNoListIsEveryVlan:
    """On four platforms a trunk that states no allowed list carries
    every VLAN, and the tree says so with the 4,094 ids: thousands of
    entries for a line that is not in the text.

    What that costs is the size of what the text means, which the
    head of this module says no search here will report, and which is
    counted in bytes where the ids are made
    (``test_projection_makes_what_is_kept.py``).  What is asked here
    is the other thing: that reading N such trunks costs N times one,
    and not the square.
    """

    @pytest.mark.parametrize("name", sorted(TRUNKS_WITH_NO_LIST))
    def test_parse_fits_the_number_of_trunks(self, name: str) -> None:
        small, make = TRUNKS_WITH_NO_LIST[name]
        slow = _grows_faster_than_its_input(get_codec(name).parse, make, small)
        assert not slow, f"{name}: {slow}"

    def test_each_text_is_trunks_of_every_id(self) -> None:
        """A text read as ports with no list, or as no ports, would
        be read quickly whatever the parser did."""
        for name, (_small, make) in TRUNKS_WITH_NO_LIST.items():
            tree = get_codec(name).parse(make(40))
            every = [port for port in tree.interfaces if len(port.trunk_allowed_vlans) == 4094]
            assert len(every) == 40 and all(port.switchport_mode == "trunk" for port in every), name

    def test_they_are_the_codecs_of_every_vlan(self) -> None:
        from netcanon.migration.codecs._helpers import TRUNK_ALL, TRUNK_THAT_STATES_NO_LIST

        assert set(TRUNKS_WITH_NO_LIST) == {
            name for name, default in TRUNK_THAT_STATES_NO_LIST.items() if default == TRUNK_ALL
        }


# ---------------------------------------------------------------------------
# Many lines for one record
# ---------------------------------------------------------------------------


def _host(number: int) -> str:
    return f"10.{number // 65536 % 256}.{number // 256 % 256}.{number % 256}"


def _v6(number: int) -> str:
    return f"2001:db8:{number // 65536:x}:{number % 65536:x}::1"


def _named(records: Any, name: object, by: str = "name") -> Any:
    return next(record for record in records if getattr(record, by) == name)


def _junos(*lines: str) -> str:
    return _config("set system host-name r1", *lines)


def _junos_unit_addresses(count: int) -> str:
    return _junos(*(f"set interfaces ge-0/0/0 unit 0 family inet address {_host(n)}/24" for n in range(count)))


def _junos_unit_v6_addresses(count: int) -> str:
    return _junos(*(f"set interfaces ge-0/0/0 unit 0 family inet6 address {_v6(n)}/64" for n in range(count)))


def _junos_irb_addresses(count: int) -> str:
    return _junos(*(f"set interfaces irb unit 100 family inet address {_host(n)}/24" for n in range(count)))


def _junos_irb_addresses_of_a_vlan(count: int) -> str:
    """The unit is a VLAN's ``l3-interface``, so its addresses are
    folded onto the VLAN: a set of the VLAN's addresses was built
    again for each one."""
    return _junos(
        "set vlans V100 vlan-id 100", "set vlans V100 l3-interface irb.100",
        *(f"set interfaces irb unit 100 family inet address {_host(n)}/24" for n in range(count)),
    )


def _junos_irb_v6_addresses(count: int) -> str:
    return _junos(*(f"set interfaces irb unit 100 family inet6 address {_v6(n)}/64" for n in range(count)))


def _junos_lag_members(count: int) -> str:
    return _junos(*(f"set interfaces ge-0/0/{n} ether-options 802.3ad ae0" for n in range(count)))


def _junos_range_members(count: int) -> str:
    return _junos(*(f"set interfaces interface-range R member ge-0/0/{n}" for n in range(count)))


def _junos_range_addresses(count: int) -> str:
    """One member, so that the addresses of the range are the only
    thing there is many of."""
    return _junos(
        "set interfaces interface-range R member ge-0/0/0",
        *(f"set interfaces interface-range R unit 0 family inet address {_host(n)}/24" for n in range(count)),
    )


def _junos_pool_name_servers(count: int) -> str:
    pool = "set access address-assignment pool P family inet"
    return _junos(f"{pool} network 10.0.0.0/8", *(
        f"{pool} dhcp-attributes name-server {_host(n)}" for n in range(count)
    ))


def _junos_old_pool_name_servers(count: int) -> str:
    return _junos(*(f"set system services dhcp pool 10.0.0.0/8 name-server {_host(n)}" for n in range(count)))


def _junos_route_targets(count: int) -> str:
    return _junos("set routing-instances V instance-type vrf", *(
        f"set routing-instances V vrf-target import target:65000:{n}" for n in range(count)
    ))


def _junos_route_targets_both_ways(count: int) -> str:
    return _junos("set routing-instances V instance-type vrf", *(
        f"set routing-instances V vrf-target target:65000:{n}" for n in range(count)
    ))


_JUNOS_VRRP = "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/8 vrrp-group 1"


def _junos_vrrp_addresses(count: int) -> str:
    return _junos(*(f"{_JUNOS_VRRP} virtual-address {_host(n)}" for n in range(count)))


def _junos_vrrp_tracked(count: int) -> str:
    return _junos(*(f"{_JUNOS_VRRP} track interface ge-0/0/{n}" for n in range(count)))


def _junos_v3_users(count: int) -> str:
    return _junos(*(
        f"set snmp v3 usm local-engine user u{n} authentication-sha authentication-password fakepass{n}"
        for n in range(count)
    ))


def _eos_vrf_route_targets(count: int) -> str:
    return _config("hostname sw", "!", "vrf instance V", *(
        f"   route-target import 65000:{n}" for n in range(count)
    ), "!")


def _eos_bgp_route_targets(count: int) -> str:
    return _config("hostname sw", "!", "router bgp 65001", "   vrf V", "      rd 65001:1", *(
        f"      route-target import evpn 65000:{n}" for n in range(count)
    ), "!")


def _eos_vrrp_tracked(count: int) -> str:
    return _config("hostname sw", "!", "interface Ethernet1", "   no switchport", "   ip address 10.0.0.1/8", *(
        f"   vrrp 1 track Ethernet{n}" for n in range(count)
    ), "!")


def _cx_lag_members(count: int) -> str:
    return _config("hostname sw", "interface lag 1", "    no shutdown", *(
        line for n in range(count) for line in (f"interface 1/1/{n + 1}", "    lag 1")
    ))


def _iosxe_lag_members(count: int) -> str:
    return _config("hostname sw", "!", *(
        line for n in range(count)
        for line in (f"interface GigabitEthernet1/0/{n + 1}", " channel-group 1 mode active", "!")
    ))


def _iosxr_lag_members(count: int) -> str:
    return _config("hostname r1", "!", *(
        line for n in range(count)
        for line in (f"interface GigabitEthernet0/0/0/{n}", " bundle id 1 mode active", "!")
    ))


def _nxos_lag_members(count: int) -> str:
    return _config("hostname sw", "feature lacp", *(
        line for n in range(count) for line in (f"interface Ethernet1/{n + 1}", "  channel-group 1 mode active")
    ))


def _os10_lag_members(count: int) -> str:
    return _config("! Version 10.5.4.0", "hostname sw", "!", *(
        line for n in range(count)
        for line in (f"interface ethernet1/1/{n + 1}", " channel-group 1 mode active", "!")
    ))


def _secondary(count: int, line: str) -> Iterator[str]:
    """An address line a number: the first primary, the rest secondary."""
    return (line.format(_host(n)) + (" secondary" if n else "") for n in range(count))


def _cx_svi_addresses(count: int) -> str:
    """The VLAN is declared, so the SVI's addresses are merged onto a
    record that is there: each was compared, field by field, with
    every address the record had."""
    return _config(
        "hostname sw", "vlan 10", "    name users", "interface vlan 10",
        *_secondary(count, "    ip address {}/24"),
    )


def _iosxe_svi_addresses(count: int) -> str:
    return _config(
        "hostname sw", "!", "vlan 10", " name users", "!", "interface Vlan10",
        *_secondary(count, " ip address {} 255.255.255.0"), "!",
    )


def _nxos_svi_addresses(count: int) -> str:
    return _config(
        "hostname sw", "feature interface-vlan", "vlan 10", "  name users", "interface Vlan10",
        *_secondary(count, "  ip address {}/24"),
    )


def _os10_svi_addresses(count: int) -> str:
    """OS10 has no ``vlan N`` stanza: the first SVI makes the record
    and a second stanza of the same SVI is merged onto it."""
    return _config(
        "! Version 10.5.4.0", "hostname sw", "!", "interface vlan10", " ip address 172.16.0.1/24", "!",
        "interface vlan10", *(f" ip address {_host(n)}/24 secondary" for n in range(count)), "!",
    )


def _netconf_svi_addresses(count: int) -> str:
    """As OS10: a second ``Vlan10`` element, merged onto the record
    the first one made."""

    def interface(addresses: list[str]) -> str:
        return (
            "<interface><name>Vlan10</name><config><name>Vlan10</name><enabled>true</enabled></config>"
            '<subinterfaces><subinterface><index>0</index><ipv4 xmlns="http://openconfig.net/yang/interfaces/ip">'
            "<addresses>" + "".join(
                f"<address><ip>{address}</ip><config><ip>{address}</ip>"
                "<prefix-length>24</prefix-length></config></address>"
                for address in addresses
            ) + "</addresses></ipv4></subinterface></subinterfaces></interface>"
        )

    return _config(
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rpc-reply xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" message-id="101">', "<data>",
        '<interfaces xmlns="http://openconfig.net/yang/interfaces">',
        interface(["172.16.0.1"]), interface([_host(n) for n in range(count)]),
        "</interfaces>", "</data>", "</rpc-reply>",
    )


def _vyos_bond_members(count: int) -> str:
    return _config("set system host-name r1", "set interfaces bonding bond0 mode 802.3ad", *(
        f"set interfaces bonding bond0 member interface eth{n}" for n in range(count)
    ))


def _vyos_ntp_servers(count: int) -> str:
    return _config("set system host-name r1", *(f"set service ntp server {_host(n)}" for n in range(count)))


def _vyos_vxlan_remotes(count: int) -> str:
    return _config("set system host-name r1", "set interfaces vxlan vxlan10 vni 10010", *(
        f"set interfaces vxlan vxlan10 remote {_host(n)}" for n in range(count)
    ))


#: Ports named by each ``untagged`` line of the text below.
_PORTS_AN_UNTAGGED_LINE = 1000


def _aoss_ports_taken_back(count: int) -> str:
    """One VLAN: the same thousand ports stated on every ``untagged``
    line, then as many ``no untagged`` lines.  The list was added to
    without a look and written again whole for each line that took a
    port out: 320 of each, thirteen kilobytes, took four seconds."""
    return _config(
        *_AOSS_TOP, "vlan 10", *(f"   untagged 1-{_PORTS_AN_UNTAGGED_LINE}" for _ in range(count)),
        *(f"   no untagged {5000 + n}" for n in range(count)), "   exit",
    )


def _aoss_single_ports_taken_back(count: int) -> str:
    return _config(
        *_AOSS_TOP, "vlan 10", *(f"   untagged {n + 1}" for n in range(count)),
        *(f"   no untagged {900000 + n}" for n in range(count)), "   exit",
    )


#: Ports each VLAN of the text below is tagged on.
_PORTS_A_TAGGED_VLAN = 48


def _aoss_vlans_tagged_on_a_switch(count: int) -> str:
    """A real shape: 48 ports tagged in every VLAN.  Giving each port
    its list of VLANs looked through that list for each VLAN."""
    return _config(
        *_AOSS_TOP,
        *(line for port in range(1, _PORTS_A_TAGGED_VLAN + 1)
          for line in (f"interface {port}", '   name "p"', "   exit")),
        *(line for number in range(count)
          for line in (f"vlan {number % 4093 + 2}", f"   tagged 1-{_PORTS_A_TAGGED_VLAN}", "   exit")),
    )


_ROUTEROS_TOP = "# 2026-01-01 00:00:00 by RouterOS 7.14"


def _routeros_ntp_servers(count: int) -> str:
    return _config(_ROUTEROS_TOP, "/system ntp client servers", *(f"add address={_host(n)}" for n in range(count)))


def _routeros_ntp_set_lines(count: int) -> str:
    return _config(_ROUTEROS_TOP, "/system ntp client", *(
        f"set enabled=yes servers={_host(n)},pool.ntp.org" for n in range(count)
    ))


#: A list of ONE record that every line adds to, where the line used to
#: look through the list first (``if x not in lst: lst.append(x)``):
#: codec, the smaller count, the text, and what the parsed tree has to
#: hold ``count`` of.  The addresses of one interface, the members of
#: one LAG, the route targets of one VRF.  No index of the records
#: helps -- there is one record -- and nothing about any line is odd.
#: Read before the mend at four times the count here: from a second
#: (1,600 secondary addresses on one SVI, 60 KB) to eight (32,000
#: route targets of one Junos VRF, 1.7 MB).
ONE_RECORD: dict[str, tuple[str, int, Callable[[int], str], Callable[[Any], int]]] = {
    "juniper_junos: the addresses of one unit": (
        "juniper_junos", 4000, _junos_unit_addresses, lambda t: len(_named(t.interfaces, "ge-0/0/0").ipv4_addresses),
    ),
    "juniper_junos: the IPv6 addresses of one unit": (
        "juniper_junos", 4000, _junos_unit_v6_addresses,
        lambda t: len(_named(t.interfaces, "ge-0/0/0").ipv6_addresses),
    ),
    "juniper_junos: the addresses of an IRB unit": (
        "juniper_junos", 4000, _junos_irb_addresses, lambda t: len(_named(t.interfaces, "irb.100").ipv4_addresses),
    ),
    "juniper_junos: the addresses of an IRB unit, folded onto its VLAN": (
        "juniper_junos", 2000, _junos_irb_addresses_of_a_vlan, lambda t: len(_named(t.vlans, 100, "id").ipv4_addresses),
    ),
    "juniper_junos: the IPv6 addresses of an IRB unit": (
        "juniper_junos", 4000, _junos_irb_v6_addresses, lambda t: len(_named(t.interfaces, "irb.100").ipv6_addresses),
    ),
    "juniper_junos: the members of one LAG": (
        "juniper_junos", 8000, _junos_lag_members, lambda t: len(_named(t.lags, "ae0").members),
    ),
    "juniper_junos: the members of one interface-range": (
        "juniper_junos", 8000, _junos_range_members, lambda t: len(t.interfaces),
    ),
    "juniper_junos: the addresses of one interface-range": (
        "juniper_junos", 4000, _junos_range_addresses, lambda t: len(_named(t.interfaces, "ge-0/0/0").ipv4_addresses),
    ),
    "juniper_junos: the name servers of one pool": (
        "juniper_junos", 8000, _junos_pool_name_servers, lambda t: len(t.dhcp_servers[0].dns_servers),
    ),
    "juniper_junos: the name servers of one pool, old grammar": (
        "juniper_junos", 8000, _junos_old_pool_name_servers, lambda t: len(t.dhcp_servers[0].dns_servers),
    ),
    "juniper_junos: the route targets of one VRF": (
        "juniper_junos", 8000, _junos_route_targets, lambda t: len(_named(t.routing_instances, "V").rt_imports),
    ),
    "juniper_junos: the route targets of one VRF, both ways": (
        "juniper_junos", 8000, _junos_route_targets_both_ways,
        lambda t: len(_named(t.routing_instances, "V").rt_exports),
    ),
    "juniper_junos: the virtual addresses of one VRRP group": (
        "juniper_junos", 8000, _junos_vrrp_addresses,
        lambda t: len(_named(t.interfaces, "ge-0/0/0").vrrp_groups[0].virtual_ips),
    ),
    "juniper_junos: the tracked interfaces of one VRRP group": (
        "juniper_junos", 8000, _junos_vrrp_tracked,
        lambda t: len(_named(t.interfaces, "ge-0/0/0").vrrp_groups[0].track_interfaces),
    ),
    "juniper_junos: SNMPv3 users": ("juniper_junos", 4000, _junos_v3_users, lambda t: len(t.snmp.v3_users)),
    "arista_eos: the route targets of one VRF": (
        "arista_eos", 8000, _eos_vrf_route_targets, lambda t: len(_named(t.routing_instances, "V").rt_imports),
    ),
    "arista_eos: the route targets of one VRF under router bgp": (
        "arista_eos", 8000, _eos_bgp_route_targets, lambda t: len(_named(t.routing_instances, "V").rt_imports),
    ),
    "arista_eos: the tracked interfaces of one VRRP group": (
        "arista_eos", 8000, _eos_vrrp_tracked,
        lambda t: len(_named(t.interfaces, "Ethernet1").vrrp_groups[0].track_interfaces),
    ),
    "aruba_aoscx: the members of one LAG": (
        "aruba_aoscx", 8000, _cx_lag_members, lambda t: len(_named(t.lags, "lag 1").members),
    ),
    "cisco_iosxe_cli: the members of one LAG": (
        "cisco_iosxe_cli", 8000, _iosxe_lag_members, lambda t: len(_named(t.lags, "Port-channel1").members),
    ),
    "cisco_iosxr: the members of one LAG": (
        "cisco_iosxr", 8000, _iosxr_lag_members, lambda t: len(_named(t.lags, "Bundle-Ether1").members),
    ),
    "cisco_nxos: the members of one LAG": (
        "cisco_nxos", 8000, _nxos_lag_members, lambda t: len(_named(t.lags, "port-channel1").members),
    ),
    "dell_os10: the members of one LAG": (
        "dell_os10", 8000, _os10_lag_members, lambda t: len(_named(t.lags, "port-channel1").members),
    ),
    "aruba_aoscx: the addresses of one SVI": (
        "aruba_aoscx", 400, _cx_svi_addresses, lambda t: len(_named(t.vlans, 10, "id").ipv4_addresses),
    ),
    "cisco_iosxe_cli: the addresses of one SVI": (
        "cisco_iosxe_cli", 400, _iosxe_svi_addresses, lambda t: len(_named(t.vlans, 10, "id").ipv4_addresses),
    ),
    "cisco_iosxe: the addresses of one SVI": (
        "cisco_iosxe", 400, _netconf_svi_addresses, lambda t: len(_named(t.vlans, 10, "id").ipv4_addresses),
    ),
    "cisco_nxos: the addresses of one SVI": (
        "cisco_nxos", 400, _nxos_svi_addresses, lambda t: len(_named(t.vlans, 10, "id").ipv4_addresses),
    ),
    "dell_os10: the addresses of one SVI": (
        "dell_os10", 400, _os10_svi_addresses, lambda t: len(_named(t.vlans, 10, "id").ipv4_addresses),
    ),
    "vyos: the members of one bond": (
        "vyos", 8000, _vyos_bond_members, lambda t: len(_named(t.lags, "bond0").members),
    ),
    "vyos: NTP servers": ("vyos", 8000, _vyos_ntp_servers, lambda t: len(t.ntp_servers)),
    "vyos: the remotes of one VXLAN": (
        "vyos", 8000, _vyos_vxlan_remotes, lambda t: len(t.vxlan_vnis[0].flood_list),
    ),
    "aruba_aoss: ports stated again and again, then taken back": (
        "aruba_aoss", 80, _aoss_ports_taken_back,
        lambda t: len(_named(t.vlans, 10, "id").untagged_ports) * 40 // _PORTS_AN_UNTAGGED_LINE,
    ),
    "aruba_aoss: ports of one VLAN, then others taken back": (
        "aruba_aoss", 2000, _aoss_single_ports_taken_back, lambda t: len(_named(t.vlans, 10, "id").untagged_ports),
    ),
    "aruba_aoss: a switch of ports tagged in every VLAN": (
        "aruba_aoss", 1000, _aoss_vlans_tagged_on_a_switch,
        lambda t: len(_named(t.interfaces, "1").trunk_allowed_vlans),
    ),
    "mikrotik_routeros: NTP servers": ("mikrotik_routeros", 2000, _routeros_ntp_servers, lambda t: len(t.ntp_servers)),
    "mikrotik_routeros: NTP servers on set lines": (
        "mikrotik_routeros", 2000, _routeros_ntp_set_lines, lambda t: len(t.ntp_servers),
    ),
}


#: Texts whose list stops growing: a port is in at most 4,094 VLANs,
#: so past that many stanzas the text grows and the list does not, and
#: a third size would clear a reader that costs the square of the
#: list.  Two steep readings are the verdict for these.
NO_LARGER_THAN: dict[str, int] = {
    "aruba_aoss: a switch of ports tagged in every VLAN": 4000,
}


class TestParseFitsTheLinesOfOneRecord:
    """One record, and a line for each thing it holds.  A handler that
    looks through the record's list before it adds to it costs the
    square of the lines -- and so does one that compares a new address
    with every address the record has, or writes the list again for
    each line that takes something out.

    A list like the one above it: a text for each place that was
    found doing it, and not a search.  What keeps the next one out
    is ``TestNoListIsLookedThroughThenAddedTo``, which reads the
    source for the idiom and needs no clock.
    """

    @pytest.mark.parametrize("title", sorted(ONE_RECORD))
    def test_one_record_given_many_lines(self, title: str) -> None:
        name, small, make, _made = ONE_RECORD[title]
        slow = _grows_faster_than_its_input(
            get_codec(name).parse, make, small, largest=NO_LARGER_THAN.get(title),
        )
        assert not slow, f"{title}: {slow}"

    def test_each_text_makes_what_it_says(self) -> None:
        assert set(NO_LARGER_THAN) <= set(ONE_RECORD)
        for title, (name, _small, make, made) in ONE_RECORD.items():
            assert made(get_codec(name).parse(make(40))) >= 40, title


# ---------------------------------------------------------------------------
# Work that is done after the parse
# ---------------------------------------------------------------------------


def _translated(source: str, target: str, port_rename_map: dict[str, str | None] | None = None) -> Callable[[str], Any]:
    def read(text: str) -> Any:
        return run_plan_with_overrides(get_codec(source), get_codec(target), text, port_rename_map=port_rename_map)

    return read


@functools.cache
def _declared_devices() -> tuple[Any, Any]:
    """A standalone 48-port AOS-S switch, and a stack to move it to."""
    registry = load_model_families_dir(LIBRARY_DIR / "model_families")

    def device(mode: str, **member: Any) -> Any:
        return compile_deployment(
            Deployment(vendor="aruba_aoss", mode=mode, members=[MemberSpec(**member)]), registry,
        )

    return device("standalone", model="JL260A"), device("stacked", model="JL322A", modules={"A": "JL083A"})


def _translated_between_devices(text: str) -> Any:
    source, target = _declared_devices()
    return run_plan_with_models(get_codec("aruba_aoss"), get_codec("aruba_aoss"), text, source, target)


_AOSS_2930F = ("; JL260A Configuration Editor; Created on release #WC.16.07.0002", 'hostname "sw"')
_AOSS_VLAN_1 = ("vlan 1", '   name "DEFAULT_VLAN"', "   untagged 1-52")


def _aoss_ports_that_share_a_name(count: int) -> str:
    """Port ``1/k`` and module port ``1/Ak`` are one name on Junos:
    ``count`` pairs, and a warning for each.  The warning looked
    through every name the run had translated to find its two."""
    return _config(*_AOSS_TOP, *(
        line for k in range(1, count + 1) for name in (f"1/{k}", f"1/A{k}")
        for line in (f"interface {name}", '   name "p"', "   exit")
    ))


def _aoss_names_under_a_port(count: int) -> str:
    """Names the declared switch does not have, each of which reads
    as a sub-interface of its port 1."""
    return _config(
        *_AOSS_2930F, *_AOSS_VLAN_1, *(f"   tagged 1.{k}" for k in range(1, count + 1)), "   exit",
    )


def _aoss_lags_and_interfaces(count: int) -> str:
    """A LAG of one port each, and a stanza for each port: for every
    LAG, every interface was asked whether it belonged to it."""
    return _config(
        *_AOSS_2930F,
        *(line for k in range(1, count + 1) for line in (f"interface {k}", '   name "p"', "   exit")),
        *(f"trunk {k} trk{k} lacp" for k in range(1, count + 1)),
        *_AOSS_VLAN_1, "   exit",
    )


def _nxos_route_targets(count: int) -> str:
    """One VRF, as many imports as exports and none of them the
    same: the renderer looked each up in the other list."""
    return _config(
        "hostname sw", "vrf context V", "  rd 65000:1", "  address-family ipv4 unicast",
        *(f"    route-target import 65000:{n}" for n in range(count)),
        *(f"    route-target export 65001:{n}" for n in range(count)),
    )


def _iosxe_vlans_and_lags(count: int) -> str:
    """As many VLANs as port-channels as member ports.  To find the
    parent of each VLAN the OPNsense renderer walked every interface
    for every LAG, and again for every member: three kinds that grow
    together, and 400 of each took twelve seconds."""
    return _config(
        "hostname sw", "!",
        *(line for v in range(count) for line in (f"vlan {v % 4000 + 2}", f" name v{v}", "!")),
        *(line for k in range(1, count + 1) for line in (f"interface Port-channel{k}", " switchport mode trunk", "!")),
        *(line for k in range(1, count + 1)
          for line in (f"interface GigabitEthernet1/0/{k}", f" channel-group {k} mode active", "!")),
    )


def _vyos_v3_users(count: int) -> str:
    """A same-vendor render carries every user, and compared each,
    field by field, with all that it carried."""
    return _config("set system host-name r1", *(
        line for n in range(count) for line in (
            f"set service snmp v3 user u{n} auth type sha",
            f"set service snmp v3 user u{n} auth plaintext-password fakepass{n}",
        )
    ))


#: Work after the parse that cost the square of what it was given, or
#: worse -- in the port-name translator, in a renderer, in what a plan
#: says of itself: how the text is read, the smaller count, the text,
#: and what the job has to hold ``count`` of.
TRANSLATIONS: dict[str, tuple[Callable[[str], Any], int, Callable[[int], str], Callable[[Any], int]]] = {
    "aruba_aoss to juniper_junos: ports that share a name": (
        _translated("aruba_aoss", "juniper_junos", {}), 2000, _aoss_ports_that_share_a_name,
        lambda job: sum("multiple source ports map to" in warning for warning in job.warnings),
    ),
    "aruba_aoss, devices declared: names that are no port's": (
        _translated_between_devices, 16000, _aoss_names_under_a_port,
        lambda job: len(job.port_mapping_plan.off_inventory) + len(job.port_mapping_plan.sub_interfaces),
    ),
    "aruba_aoss, devices declared: LAGs over many interfaces": (
        _translated_between_devices, 1000, _aoss_lags_and_interfaces, lambda job: job.rendered.count(" lacp"),
    ),
    "cisco_nxos to cisco_nxos: the route targets of one VRF": (
        _translated("cisco_nxos", "cisco_nxos"), 2000, _nxos_route_targets,
        lambda job: job.rendered.count("route-target import"),
    ),
    "cisco_iosxe_cli to opnsense: VLANs, LAGs and their members": (
        _translated("cisco_iosxe_cli", "opnsense"), 100, _iosxe_vlans_and_lags,
        lambda job: job.rendered.count("<vlan>"),
    ),
    "vyos to vyos: SNMPv3 users": (
        _translated("vyos", "vyos"), 500, _vyos_v3_users, lambda job: job.rendered.count("plaintext-password"),
    ),
}


class TestATranslationFitsWhatItIsGiven:
    """The parse is not all a request does with a config.  A list,
    as the two above it are: one text for each place found."""

    @pytest.mark.parametrize("title", sorted(TRANSLATIONS))
    def test_one_kind_written_many_times(self, title: str) -> None:
        read, small, make, _made = TRANSLATIONS[title]
        # Read once before any reading is timed.  The first job of a
        # process loads the device models, and that went into the
        # smaller reading only: the step up then looked gentle, and
        # a reader that costs the square was read in time whenever
        # its test was the first in its worker.
        read(make(3))
        slow = _grows_faster_than_its_input(read, make, small)
        assert not slow, f"{title}: {slow}"

    def test_each_job_holds_what_its_text_says(self) -> None:
        for title, (read, _small, make, made) in TRANSLATIONS.items():
            job = read(make(40))
            assert job.rendered and made(job) >= 40, title


# ---------------------------------------------------------------------------
# A renderer that gives every VLAN one port to ride on
# ---------------------------------------------------------------------------


def _iosxe_trunks_and_vlan_interfaces(count: int) -> str:
    """As many trunks that state no allowed list as VLAN interfaces.
    On IOS-XE such a trunk is a trunk of every VLAN, and its list is
    the 4,094 ids."""
    return _config(
        "hostname sw", "!",
        *(line for k in range(count)
          for line in (f"interface GigabitEthernet{k // 48 + 1}/0/{k % 48 + 1}", " switchport mode trunk", "!")),
        *(line for v in range(count)
          for line in (f"interface Vlan{v % 4000 + 2}", f" ip address 10.{v // 250}.{v % 250}.1 255.255.255.0", "!")),
    )


def _trunks_and_vlan_interfaces(count: int) -> Any:
    """The tree a renderer is handed for that text."""
    return get_codec("cisco_iosxe_cli").parse(_iosxe_trunks_and_vlan_interfaces(count))


#: The targets that have no trunk of their own and hang each VLAN on
#: ONE parent port, which they find by looking through the ports of
#: the tree: what their output has one of for every VLAN.
ONE_PARENT_A_VLAN: dict[str, str] = {
    "fortigate_cli": "set vlanid ",
    "mikrotik_routeros": " vlan-id=",
    "opnsense": "<tag>",
}


class TestARenderFitsTheTrunksItIsGiven:
    """Three renderers choose a parent port for each VLAN, and each
    asks a port whether its trunk is a trunk of every VLAN -- which
    reads a list of 4,094 ids.  Asked once a port, that costs the
    ports.  Asked of every port again for every VLAN interface, it
    costs their product: the FortiOS renderer did, and a thousand
    trunks that state no list beside a thousand VLAN interfaces took
    half a minute to write.

    The RENDER is what is timed here, on a tree parsed beforehand.  A
    tree of N trunks of every VLAN and N VLANs holds N times N
    memberships, and reading it, translating its port names and
    checking it cost that product whatever the renderer does: timed
    as a whole plan, a renderer that is right and one that is not
    both grow with the square, and only a clock tells them apart.
    """

    @pytest.mark.parametrize("target", sorted(ONE_PARENT_A_VLAN))
    def test_render_fits_trunks_and_svis(self, target: str) -> None:
        render = get_codec(target).render
        # Rendered once before any reading is timed, for what the
        # first render of a process loads.
        render(_trunks_and_vlan_interfaces(3))
        slow = _grows_faster_than_its_input(render, _trunks_and_vlan_interfaces, 100)
        assert not slow, f"{target}: {slow}"

    def test_each_tree_is_what_it_says(self) -> None:
        """Trunks read as ports with no list, or VLAN interfaces that
        no renderer writes a VLAN for, would be rendered quickly
        whatever the renderer did."""
        tree = _trunks_and_vlan_interfaces(40)
        every = [port for port in tree.interfaces if len(port.trunk_allowed_vlans) == 4094]
        assert len(every) == 40 and all(port.switchport_mode == "trunk" for port in every)
        for target, one_a_vlan in ONE_PARENT_A_VLAN.items():
            assert get_codec(target).render(tree).count(one_a_vlan) >= 40, target

    def test_they_are_the_codecs_that_ask(self) -> None:
        """The targets here are the codecs that ask what a trunk's
        list says -- themselves, or through the shared rule that finds
        the port that carries a VLAN (``vlan_carriers``) -- and are not
        in the table of platforms that have such a list: they ask in
        order to choose a port.  One that starts to ask is added here
        with it."""
        from netcanon.migration.codecs._helpers import TRUNK_THAT_STATES_NO_LIST

        asks = {
            name for name in list_public_codecs()
            if name not in TRUNK_THAT_STATES_NO_LIST and any(
                re.search(
                    r"\b(?:is_every_vlan|trunk_list_says|vlan_carriers)\(", path.read_text(encoding="utf-8"),
                )
                for path in (PACKAGE / "migration" / "codecs" / name).glob("*.py")
            )
        }
        assert asks == set(ONE_PARENT_A_VLAN)

    def test_the_check_can_fail(self) -> None:
        """A renderer that asks every trunk again for every VLAN
        interface, whatever the machine."""

        def asks_each_port_for_each_vlan(tree: Any) -> None:
            trunks = sum(1 for port in tree.interfaces if port.switchport_mode == "trunk")
            _takes(trunks * (len(tree.interfaces) - trunks) * 2e-6)

        # Asked up to three times: one stalled reading of the smaller
        # tree passes a slow reader.
        said = ""
        for _attempt in range(3):
            said = said or _grows_faster_than_its_input(
                asks_each_port_for_each_vlan, _trunks_and_vlan_interfaces, 50, floor=0.02,
            )
        assert said.count("units") == 3, said


# ---------------------------------------------------------------------------
# A list that is looked through before it is added to
# ---------------------------------------------------------------------------

_GROWS_A_LIST = {"append", "extend", "insert"}


def _leaves(node: ast.AST) -> bool:
    """Whether a ``return`` or a ``break`` ends *node*'s loop: one in
    a function defined inside the loop does not."""
    pending = list(ast.iter_child_nodes(node))
    while pending:
        inner = pending.pop()
        if isinstance(inner, (ast.Return, ast.Break)):
            return True
        if not isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            pending.extend(ast.iter_child_nodes(inner))
    return False


def _looks_then_adds(source: str) -> Iterator[tuple[str, str, str]]:
    """``(function, expression, how)`` for every list a function both
    adds to and looks through: ``x in lst`` or ``x not in lst``, or a
    ``for`` over it that returns or breaks (a search written out).

    The list is whatever expression ``.append``, ``.extend`` or
    ``.insert`` is called on, compared as text; a function is read
    with the functions defined inside it, since those share its
    lists.  A set is not seen (it is added to with ``.add``), and that
    is the point: looked for in a set, kept in a list.
    """
    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        grown = {
            ast.unparse(node.func.value)
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in _GROWS_A_LIST
        }
        if not grown:
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Compare):
                for op, right in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.In, ast.NotIn)) and ast.unparse(right) in grown:
                        yield function.name, ast.unparse(right), "looked for in it"
            elif isinstance(node, ast.For) and ast.unparse(node.iter) in grown and _leaves(node):
                yield function.name, ast.unparse(node.iter), "searched in a loop"


#: The places where a list is looked through and added to in one
#: function, and why each may stay: file, function, the list.  A new
#: one fails the test until it is mended -- ``Uniques`` or a set kept
#: beside the list -- or is listed here with the bound that makes it
#: harmless.
LOOKED_THROUGH: dict[tuple[str, str, str], str] = {
    ("migration/codecs/_helpers.py", "add", "same"): (
        "Uniques itself: the values that share ONE key, which is one value unless the key is coarse"
    ),
    ("migration/codecs/arista_eos/parse.py", "_vrrp_group_for", "iface.vrrp_groups"): (
        "the VRRP groups of one interface, found by number: at most the 4,096 group ids the model allows"
    ),
    ("migration/codecs/juniper_junos/parse.py", "_blockform_convert", "words"): (
        "the words of one statement, looked through once when the statement ends"
    ),
    ("migration/deployment_detect.py", "propose_deployment", "proposal.unknown_parts"): (
        "the part numbers of one deployment, refused above 64 members before this is reached"
    ),
}


class TestNoListIsLookedThroughThenAddedTo:
    """``if x not in lst: lst.append(x)`` reads the list for every
    value it is given.  Where the list belongs to one record and a
    config can give that record a line for each value, the cost is the
    square of the lines; the texts above are what that looked like.

    This reads the source instead of a clock, so it finds the idiom
    where no text reaches it -- and it is narrower than it sounds.  It
    does not see a set or a dict rebuilt from the list for every value,
    a helper called per line that copies the list, a scan of ANOTHER
    list, or a list that reaches the function under two names.
    """

    def _found(self) -> dict[tuple[str, str, str], str]:
        found: dict[tuple[str, str, str], str] = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            for function, expression, how in _looks_then_adds(path.read_text(encoding="utf-8")):
                found[path.relative_to(PACKAGE).as_posix(), function, expression] = how
        return found

    def test_every_place_is_mended_or_listed(self) -> None:
        found = self._found()
        unlisted = {place: how for place, how in found.items() if place not in LOOKED_THROUGH}
        assert not unlisted, f"a list is added to and {unlisted}: look in a set, or use Uniques"
        gone = sorted(set(LOOKED_THROUGH) - set(found))
        assert not gone, f"no longer in the source, so no longer to be listed: {gone}"

    def test_the_reasons_given_are_true(self) -> None:
        """A bound that is stated is a bound that is read."""
        from netcanon.migration.canonical.intent import CanonicalVRRPGroup
        from netcanon.migration.deployment_detect import MAX_DEPLOYMENT_MEMBERS

        group_id = CanonicalVRRPGroup.model_fields["group_id"]
        bounds = {type(bound).__name__: bound for bound in group_id.metadata}
        assert (bounds["Ge"].ge, bounds["Le"].le) == (0, 4095)
        assert MAX_DEPLOYMENT_MEMBERS == 64

    def test_the_walk_sees_the_idiom(self) -> None:
        seen = list(_looks_then_adds(
            "def handler(entry, value, ports):\n"
            "    if value not in entry['ipv4']:\n"
            "        entry['ipv4'].append(value)\n"
            "    if value in ports:\n"
            "        return\n"
            "    ports.extend([value])\n"
            "def find(tree, name):\n"
            "    for user in tree.users:\n"
            "        if user.name == name:\n"
            "            return user\n"
            "    tree.users.append(name)\n"
            "def outer(names, name):\n"
            "    def inner():\n"
            "        return name in names\n"
            "    names.insert(0, name)\n"
        ))
        assert sorted(seen) == [
            ("find", "tree.users", "searched in a loop"),
            ("handler", "entry['ipv4']", "looked for in it"),
            ("handler", "ports", "looked for in it"),
            ("outer", "names", "looked for in it"),
        ]

    def test_and_passes_what_is_not_the_idiom(self) -> None:
        """A set kept beside the list; a pass over the list that
        leaves by no ``return``; a ``return`` inside a function made
        in the loop; a list that is only read."""
        assert not list(_looks_then_adds(
            "def handler(entry, value, seen, others):\n"
            "    if value not in seen:\n"
            "        seen.add(value)\n"
            "        entry.append(value)\n"
            "    for item in entry:\n"
            "        def later():\n"
            "            return item\n"
            "        print(later)\n"
            "    return value in others\n"
        ))
