"""What one request may make, and for how long.

A config is whatever was pasted, and a few bytes of it can stand for a
great deal: a range is thousands of entries, ``all`` is 4,094 -- and so
is a trunk that states no allowed list, on the platforms where such a
trunk carries every VLAN -- and two honest counts multiply.  The length
of the text therefore bounds neither
the memory a request takes nor its time.  This module COUNTS what a
request makes, at the places where a few bytes become many entries, and
refuses -- in words an operator can act on -- past a limit.  It also
carries the request's deadline, which the same places look at, and so
does every parser's loop over the lines of a config.

Four things:

* :class:`Limits` -- the numbers.  Four named sets ship
  (:data:`PROFILES`): ``small`` (the public demo), ``standard`` (the
  default everywhere else), ``large`` and ``unlimited``.
* a *scope* -- which :class:`Limits` apply to the work in progress, and
  the deadline all of that work shares.  An entry point opens one
  (:func:`limits_scope`); the request path does it in
  ``api.routes._migration_helpers.run_translation``.  Work that opens
  none runs under :data:`STANDARD`: a caller nobody thought about is
  still bounded.
* a *meter* -- the running counts of ONE stage (one ``parse``, one
  ``render``).  ``CodecBase`` opens it around every codec's ``parse``
  and ``render``, so no codec and no pipeline signature carries it: a
  place that expands a token calls :func:`charge` BEFORE it makes the
  entries, and a loop over lines goes through :func:`ticked`.
* a *turn* -- every limit above is for ONE request, and requests at
  once add up.  Limits can say how many requests a server works on
  at once (``at_once``: one under ``small``, no limit otherwise).
  A request to a server opens its scope with :func:`server_scope`,
  which waits for a turn before a line is read -- inside the
  request's own deadline, which runs from when the scope was opened
  -- and gives the turn back on every way out.  A request that is
  still waiting when its deadline passes is refused like any other,
  in words that say the server was busy and to send it again.  The
  application holds the turn a little longer than the work: until
  the request's answer has gone out (:class:`Answer`), because an
  answer is memory too.  Work that opens no server scope (the
  command line, a library caller, a test) never waits:
  :func:`limits_scope` takes no turn.
* a *place* -- a request holds memory before it can ask for a
  turn: its body.  So where limits say how many work at once, the
  application COUNTS a request that would read config text when
  its headers arrive, before its body is read
  (:meth:`Answer.arrived`): as many places as may work and wait,
  and one more request is refused at once, unread.  A place is
  held until the request's answer has gone out; the request's one
  deadline is then counted from its ARRIVAL, and at it an answer
  that has still not gone out is abandoned.

Counts belong to one stage, because they are a property of the CONFIG:
the same text is refused or accepted whichever endpoint it is posted to
and however many times that endpoint parses it.  The deadline belongs
to the scope, because it is a property of the REQUEST.

What is counted (:data:`KINDS`) is entries and characters, never bytes
of memory: an operator can check "1,000 trunk ports x 1,000 VLANs"
against a device, and cannot check a megabyte.  The kinds are kept
apart because one of each is not one price: a VLAN id on a port is
eight bytes, an interface about five thousand.

The deadline stops a PARSER.  A renderer, a transform between the
stages, and one long call into C (a pattern at work, a sort) are not
looked at; a request whose time ran out there is refused only if
another stage starts afterwards.  ``SECURITY.md`` says so in full.
"""

from __future__ import annotations

import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from itertools import chain
from typing import Any, TypeVar

_T = TypeVar("_T")

#: kind -> (what a refusal calls it, what the counted pieces are called).
KINDS: dict[str, tuple[str, str]] = {
    "vlan_ids": ("VLAN ids that the config's lists and ranges name", "lists and ranges"),
    "memberships": ("port memberships (one port in one VLAN or one LAG)", "lists and ranges"),
    "ports": ("different ports named by port ranges", "ranges"),
    "interfaces": ("interfaces", ""),
    "copies": ("entries copied from an interface-range onto its members", "interface-ranges"),
    "words": ("words of set commands written out from block-form text", "statements"),
    "text": ("characters of rendered config", "pieces"),
    "seconds": ("seconds of work", ""),
}

#: What a refusal for want of a turn is filed under
#: (``LimitExceeded.kind``, ``Refusal.limit``).  Not one of
#: :data:`KINDS`: those are what a stage COUNTS, and this is not a
#: count of anything a config holds.
AT_ONCE = "at_once"
_AT_ONCE_WHAT = "requests that read config text, at work at once"

#: The most requests that may WAIT for a turn.  One more is turned
#: away at once, in words, and not left to wait.  A request that waits
#: is not free: it holds a thread of the pool the server runs its
#: handlers on (a pool that is all waiters serves no page), and it
#: holds its body -- measured, four to five megabytes for a body of
#: two, on an instance of 256 MiB that one request alone can take
#: past 220 MB.  So this is also how many PLACES there are beyond
#: the ones at work (:meth:`Answer.arrived`): a request is counted
#: when its headers arrive, and one that finds every place taken
#: is refused before its body is read.
#: Two is what a page of the application has in flight behind a
#: translation: reading the vendor and the device out of a paste.
MOST_WAITING = 2

#: What the count of a finished tree calls each kind (:func:`census`).
_HELD = {
    "vlan_ids": "VLAN ids in the allowed lists of ports",
    "memberships": "port memberships (one port in one VLAN or one LAG)",
    "ports": "ports that a VLAN's or a LAG's port list names and no interface stanza declares",
    "interfaces": "interfaces",
}


@dataclass(frozen=True)
class Limits:
    """The most one stage may make of each kind, the seconds one
    scope may take, and how many requests a server works on at once.
    ``None`` is no limit.

    Raises:
        ValueError: ``at_once`` is set and is less than one, or is
            set with no ``seconds``: a request waits for its turn
            inside its deadline, and with none it could wait for
            ever.
    """

    name: str
    vlan_ids: int | None
    memberships: int | None
    ports: int | None
    interfaces: int | None
    copies: int | None
    words: int | None
    text: int | None
    seconds: float | None
    #: How many requests that read config text a server works on at
    #: once; the others wait their turn (:func:`server_scope`).
    at_once: int | None = None

    def __post_init__(self) -> None:
        if self.at_once is None:
            return
        if self.at_once < 1:
            raise ValueError("at_once is how many requests work at once: 1 or more, or None")
        if self.seconds is None:
            raise ValueError(
                "limits that set at_once need seconds: a request waits for its "
                "turn inside its deadline"
            )


#: The public demo: a container of 256 MiB and half a CPU for each
#: visitor, behind a proxy that waits 30 seconds and takes a body of
#: two megabytes.  The numbers are what was measured in such a
#: container (``docs/demo-plan/07-budget.md`` has the measurements):
#: with them, the text that reaches every limit at once is one request
#: the instance survives.  ``vlan_ids``: 256 ports that each allow
#: every VLAN.  ``at_once``: ONE request at a time.  Every number
#: here is for one request; two of the largest at once were measured
#: to end the instance, and in turn they fit.
SMALL = Limits(
    "small", 1_048_576, 50_000, 2_048, 2_500, 10_000, 250_000, 8_000_000, 20.0,
    at_once=1,
)
#: The default.  ``vlan_ids``: 4,096 ports that each allow every VLAN.
#: ``memberships``: three times the largest device a vendor verifies.
#: ``at_once``: no limit, here and in the two sets below.  This is
#: what the desktop application runs, where there is one user and
#: nobody to wait behind; and on a server it is the operator who
#: knows the machine and how many use it, and who sets the profile.
#: A default that made one user's request wait for another's would
#: slow every server down to protect a size none of these sets
#: was measured against.
STANDARD = Limits(
    "standard", 16_777_216, 1_000_000, 8_192, 50_000, 100_000, 4_000_000, 64_000_000, 120.0,
)
#: Four times ``standard`` (five times its seconds).
LARGE = Limits(
    "large", 67_108_864, 4_000_000, 32_768, 200_000, 400_000, 16_000_000, 256_000_000, 600.0,
)
#: No limit and no deadline.
UNLIMITED = Limits("unlimited", None, None, None, None, None, None, None, None)

PROFILES: dict[str, Limits] = {p.name: p for p in (SMALL, STANDARD, LARGE, UNLIMITED)}

_NEXT = {"standard": "large", "large": "unlimited"}


def describe(limits: Limits) -> str:
    """*limits* in one line, for the line a server logs at start."""
    if limits.name == "unlimited":
        return "unlimited (no config size limit and no time limit)"
    parts = [f"{kind} {_number(getattr(limits, kind))}" for kind in KINDS]
    parts.append(f"{AT_ONCE} {_number(limits.at_once)}")
    return f"{limits.name} ({', '.join(parts)})"


def _number(value: float | None) -> str:
    """A limit as a document prints it: ``1,000,000``, ``120``, ``none``."""
    if value is None:
        return "none"
    return f"{int(value):,}" if value == int(value) else f"{value:g}"


def how_to_raise(limits: Limits, kind: str = "", surface: str = "server") -> str:
    """The words that end a refusal: which limits were in force, and
    what allows more.

    Args:
        limits: The limits that refused.
        kind: The kind that was over, a key of :data:`KINDS`, or
            :data:`AT_ONCE`.
        surface: ``server`` (the web application and the desktop
            application, which embeds it) or ``cli``.

    Under ``small`` a server never names a setting: those limits are
    the public demo's, and a visitor there cannot change one.  It
    says what a Netcanon of one's own allows.  The command line has
    no server and its user did choose: there it names the option.
    """
    said: list[str] = []
    if limits.name == "small":
        allowed = getattr(STANDARD, kind, None) if kind else None
        if kind == AT_ONCE:
            own = " does not make one request wait for another"
        elif allowed is not None:
            own = f" allows {_number(allowed)}" + (" seconds" if kind == "seconds" else "")
        else:
            own = " allows more"
        if surface == "cli":
            said.append(
                "This run used the 'small' config size limit, the one the "
                f"public demo uses.  The default, 'standard',{own}: pass "
                "--limits standard."
            )
        else:
            said.append(
                "This server runs with the 'small' config size limit, the one the "
                f"public demo uses.  A Netcanon you run yourself{own} by default."
            )
    elif limits.name in _NEXT:
        more = _NEXT[limits.name]
        either = "" if more == "unlimited" else " (or unlimited)"
        if surface == "cli":
            said.append(
                f"This run used the '{limits.name}' config size limit.  To allow "
                f"more, pass --limits {more}{either}."
            )
        else:
            said.append(
                f"This server runs with the '{limits.name}' config size limit.  "
                f"To allow more, set NETCANON_CONFIG_LIMITS={more}{either} in "
                "its environment and restart it; in the desktop application, "
                "choose Preferences... -> Config size limit."
            )
    else:
        said.append("These limits were set by the caller.")
    if kind == "words":
        said.append(
            "The same config as set commands (`show configuration | display "
            "set`) is not counted in words."
        )
    return "  ".join(said)


class LimitExceeded(Exception):
    """A request asked for more than its limits allow, or ran past its
    deadline.  A result, not a fault: every entry point turns it into
    an answer that says what was too large, how large, and the limit.

    Attributes:
        kind: A key of :data:`KINDS`, or :data:`AT_ONCE` for a
            request that did not get a turn.
        asked: How many had been asked for when counting stopped (for
            ``seconds``: how long the request had run; for
            ``at_once``: how many requests were at work or waiting,
            this one among them).
        cap: The limit.
        exact: ``asked`` is the whole number -- it was counted on
            something already made.  ``False`` for a count made before
            the entries were: "at least this many".
        stage: ``parse`` or ``render`` (``""`` outside both);
            ``body`` for a request whose time ran out while its
            body was still arriving, which only a server says and
            no job carries.
        codec: The codec whose stage it was.
        lists: How many lists, ranges or statements had been counted.
        where: The last thing counted, as the config wrote it; at most
            80 characters.  For the client: never logged.
        what: The kind in words.
        profile: Name of the :class:`Limits` in force.
        hint: What allows more (:func:`how_to_raise`).
        starting: For ``seconds``: the time was already spent when
            the stage began.
        waited: For ``at_once``: the seconds the request waited for
            a turn; ``None`` when it was not let wait, because
            enough were waiting already.
        out_of: For ``at_once``: the seconds a request may take,
            when this one GOT its turn after ``waited`` of them
            and what was left was not enough; ``None`` for a
            request that never got a turn.
    """

    def __init__(
        self, kind: str, asked: float, cap: float, *, exact: bool = False,
        stage: str = "", codec: str = "", lists: int = 0, where: str = "",
        what: str = "", profile: str = "", hint: str = "", starting: bool = False,
        waited: float | None = None, out_of: float | None = None,
    ) -> None:
        self.kind, self.asked, self.cap, self.exact = kind, asked, cap, exact
        self.stage, self.codec, self.lists = stage, codec, lists
        self.where, self.profile, self.hint = where[:80], profile, hint
        self.what = what or (
            _AT_ONCE_WHAT if kind == AT_ONCE else KINDS.get(kind, (kind, ""))[0]
        )
        self.starting, self.waited, self.out_of = starting, waited, out_of
        super().__init__(self._words())

    def _words(self) -> str:
        doing = {
            "parse": f"reading the config as {self.codec}",
            "render": f"writing the config for {self.codec}",
        }.get(self.stage, "")
        when = ""
        if self.stage == "body":
            when = " while its body was still arriving"
        elif doing:
            when = f" before {doing} began" if self.starting else f" while {doing}"
        if self.kind == AT_ONCE:
            # Not "too large": nothing is wrong with the config.  It says
            # what to do, which is to send the same thing again.
            most = int(self.cap)
            takes = "one config" if most == 1 else f"{most:,} configs"
            if self.out_of is not None:
                # It got its turn, and late.  A tenth of a second is
                # the least it is said to have waited.
                waited = max(round(self.waited or 0.0, 1), 0.1)
                return (
                    f"the server works on {takes} at a time, and this request "
                    f"waited {waited:g} seconds for its turn; what was left of "
                    f"the {self.out_of:g} seconds it may take was not enough, "
                    f"and it was stopped{when}.  Send it again.  {self.hint}"
                )
            if self.waited is None:
                why = f"{int(self.asked) - most - 1:,} more were already waiting their turn"
            else:
                other = "another" if most == 1 else "others"
                why = (
                    f"was busy with {other} for the {self.waited:g} seconds "
                    "this request may take"
                )
            return (
                f"the server works on {takes} at a time, and {why}; this "
                "request was not started and its config was not read.  Send it "
                f"again.  {self.hint}"
            )
        if self.kind == "seconds":
            return (
                f"the request passed the {self.cap:g} seconds it may take"
                f"{when}, and was stopped.  {self.hint}"
            )
        doing = doing or "this request"
        made = (
            f"makes {int(self.asked):,}" if self.exact
            else f"would make {int(self.asked):,} or more"
        )
        text = f"{doing} {made} {self.what}; the limit is {int(self.cap):,}"
        units = KINDS.get(self.kind, ("", ""))[1]
        if self.kind == "interfaces":
            text += f" (the last one read: {self.where})" if self.where else ""
        elif self.lists > 1 and units:
            text += f" (counted over {self.lists:,} {units}"
            text += f"; the last one read: {self.where})" if self.where else ")"
        elif self.where:
            text += f" (at: {self.where})"
        return f"{text}.  {self.hint}"

    def as_dict(self) -> dict[str, Any]:
        """The refusal as data, for ``MigrationJob.refusal``."""
        return {
            "limit": self.kind,
            "what": self.what,
            "asked": self.asked,
            "exact": self.exact,
            "cap": self.cap,
            "stage": self.stage,
            "codec": self.codec,
            "profile": self.profile,
            "how_to_raise": self.hint,
        }


class _Scope:
    """Which limits apply, and the deadline the work under it shares."""

    __slots__ = ("beside", "deadline", "limits", "surface", "waited")

    def __init__(self, limits: Limits, surface: str) -> None:
        self.limits, self.surface = limits, surface
        self.deadline = (
            None if limits.seconds is None else time.monotonic() + limits.seconds
        )
        #: The seconds the request stood in the line for its turn,
        #: and how many were at work or waiting when it joined (it
        #: among them).  Zero for work that did not wait.
        self.waited, self.beside = 0.0, 0

    def check_clock(self) -> None:
        """Refuse if the deadline has passed.  For a loop over lines
        that runs outside any stage (reading the device out of a
        config, before the parse)."""
        if self.deadline is not None:
            over = time.monotonic() - self.deadline
            if over > 0:
                raise _out_of_time(
                    self.limits, self.surface, over, self.waited, self.beside,
                )


class _Meter:
    """The running counts of one stage."""

    __slots__ = (
        "_n", "beside", "codec", "counts", "deadline", "limits", "lists", "names",
        "stage", "surface", "waited",
    )

    def __init__(
        self, limits: Limits, surface: str, deadline: float | None,
        stage: str, codec: str, waited: float = 0.0, beside: int = 0,
    ) -> None:
        self.limits, self.surface, self.deadline = limits, surface, deadline
        self.stage, self.codec = stage, codec
        self.waited, self.beside = waited, beside
        self.counts: dict[str, int] = {}
        self.lists: dict[str, int] = {}
        self.names: dict[str, set[str]] = {}
        self._n = 0

    def _refuse(
        self, kind: str, asked: float, cap: float, where: str, exact: bool,
        what: str = "", starting: bool = False,
    ) -> None:
        raise LimitExceeded(
            kind, asked, cap, exact=exact, stage=self.stage, codec=self.codec,
            lists=self.lists.get(kind, 0), where=where, what=what,
            profile=self.limits.name,
            hint=how_to_raise(self.limits, kind, self.surface),
            starting=starting,
        )

    def check_clock(self, starting: bool = False) -> None:
        """Refuse if the deadline has passed."""
        if self.deadline is not None:
            over = time.monotonic() - self.deadline
            if over > 0:
                raise _out_of_time(
                    self.limits, self.surface, over, self.waited, self.beside,
                    self.stage, self.codec, starting,
                )

    def charge(self, kind: str, n: int, where: str = "", what: str = "") -> None:
        """Count *n* more of *kind*, before they are made."""
        total = self.counts.get(kind, 0) + n
        self.lists[kind] = self.lists.get(kind, 0) + 1
        cap = getattr(self.limits, kind)
        if cap is not None and total > cap:
            self._refuse(kind, total, cap, where, False, what)
        self.counts[kind] = total
        self.check_clock()

    def distinct(self, kind: str, names: Iterable[str], where: str = "", what: str = "") -> None:
        """Count the DIFFERENT names among those made so far: the
        ports ``1-48`` tagged in 400 VLANs are 48 ports."""
        seen = self.names.setdefault(kind, set())
        seen.update(names)
        self.lists[kind] = self.lists.get(kind, 0) + 1
        cap = getattr(self.limits, kind)
        if cap is not None and len(seen) > cap:
            self._refuse(kind, len(seen), cap, where, False, what)
        if len(seen) > self.counts.get(kind, 0):
            self.counts[kind] = len(seen)

    def settle(self, kind: str, n: int, where: str = "", what: str = "") -> None:
        """*n* of *kind* are in something already made: the count is
        at least that, and it is exact."""
        cap = getattr(self.limits, kind)
        if cap is not None and n > cap:
            self.lists[kind] = 0
            self._refuse(kind, n, cap, where, True, what)
        if n > self.counts.get(kind, 0):
            self.counts[kind] = n


_SCOPE: ContextVar[_Scope | None] = ContextVar("netcanon_limits_scope", default=None)
_METER: ContextVar[_Meter | None] = ContextVar("netcanon_limits_meter", default=None)


def resolve(limits: Limits | str | None) -> Limits:
    """A :class:`Limits` from itself, a profile name, or ``None``
    (:data:`STANDARD`).  An unknown name is ``standard``: a typing
    mistake must not be read as "no limit"."""
    if isinstance(limits, Limits):
        return limits
    return PROFILES.get((limits or "standard").strip().lower(), STANDARD)


@contextmanager
def limits_scope(
    limits: Limits | str | None = None, *, surface: str = "server",
) -> Iterator[None]:
    """Run the enclosed work under *limits*, with one deadline for all
    of it, counted from now.  Entry points open this; nothing below
    them has to.

    It takes no turn and never waits, whatever ``at_once`` says: this
    is the scope of the command line, of a tool, of a test.  A
    handler of the server opens :func:`server_scope`.

    Args:
        limits: A :class:`Limits`, the name of one of :data:`PROFILES`,
            or ``None`` for :data:`STANDARD`.
        surface: Who reads a refusal -- ``server`` or ``cli`` -- so
            that it names the setting that reader has.
    """
    token = _SCOPE.set(_Scope(resolve(limits), surface))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def _busy(limits: Limits, asked: int, waited: float | None) -> LimitExceeded:
    return LimitExceeded(
        AT_ONCE, asked, limits.at_once or 1, exact=True, profile=limits.name,
        hint=how_to_raise(limits, AT_ONCE, "server"), waited=waited,
    )


def _out_of_time(
    limits: Limits, surface: str, over: float, waited: float, beside: int,
    stage: str = "", codec: str = "", starting: bool = False,
) -> LimitExceeded:
    """The refusal of work whose time is spent.

    A request that stood in the line for its turn is told THAT: the
    server was busy, how long this request waited, and to send it
    again.  It is filed as :data:`AT_ONCE`, the kind a client sends
    again, and not as ``seconds``: "the request passed the N seconds
    it may take ... a server of your own allows more" would send its
    reader looking for something slow in a config that has nothing
    wrong with it.  Work that did not wait is refused for its time,
    as ever.
    """
    cap = limits.seconds or 0
    if waited > 0 and limits.at_once is not None:
        return LimitExceeded(
            AT_ONCE, beside, limits.at_once, exact=True, stage=stage, codec=codec,
            profile=limits.name, hint=how_to_raise(limits, AT_ONCE, surface),
            starting=starting, waited=waited, out_of=cap,
        )
    return LimitExceeded(
        "seconds", round(cap + over, 3), cap, exact=True, stage=stage, codec=codec,
        profile=limits.name, hint=how_to_raise(limits, "seconds", surface),
        starting=starting,
    )


def body_late(limits: Limits | str | None, spent: float) -> LimitExceeded:
    """The refusal of a request whose body had not arrived when its
    time was up: *spent* seconds after its headers did.  For the
    application, which is what waits for a body."""
    resolved = resolve(limits)
    cap = resolved.seconds or 0
    return LimitExceeded(
        "seconds", round(max(spent, cap), 3), cap, exact=True, stage="body",
        profile=resolved.name, hint=how_to_raise(resolved, "seconds", "server"),
    )


def _find_trim() -> Callable[[int], int] | None:
    """The C library's ``malloc_trim``, where there is one (glibc on
    Linux); ``None`` everywhere else."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes

        trim = ctypes.CDLL(None).malloc_trim
        trim.argtypes, trim.restype = [ctypes.c_size_t], ctypes.c_int
    except (ImportError, OSError, AttributeError):
        return None
    return trim


#: Hands memory that was used and freed back to the system; ``None``
#: where the C library has no such call.
_trim: Callable[[int], int] | None = _find_trim()


def _hand_freed_memory_back() -> None:
    """Give back to the system what earlier requests used and freed.

    Freed memory is not memory the system has back.  The C library
    keeps what a thread freed for that thread to use again, and a
    server runs its requests on whichever thread is idle, so
    requests in turn on different threads leave the process
    holding what each of them used.  Measured in a 256 MiB
    container, three of the largest requests at once, eight times
    over: 256 MB without this, 229 MB with it.  A request that has
    just taken its turn calls this before it reads a line -- it is
    the one that needs the room, and nothing else is at work to be
    slowed.  A few milliseconds, and only under limits that say how
    many requests work at once: where memory is not that tight,
    nothing is trimmed.
    """
    if _trim is not None:
        _trim(0)


class _Held:
    """A turn that is held, and how.

    ``at_work`` while the block that took it is running; ``lent`` once
    the block has ended and the request's answer is on its way out;
    ``back`` when it has been given back.  ``deadline`` is the
    request's: past it, a turn that is only lent can be had back by
    whoever is waiting.  ``waited`` is how long the request stood
    in the line for it, and ``beside`` how many were at work or
    waiting when it joined, itself among them (zero and zero for a
    turn that was free).
    """

    __slots__ = ("beside", "deadline", "state", "waited")

    def __init__(self, deadline: float, waited: float = 0.0, beside: int = 0) -> None:
        self.deadline, self.state = deadline, "at_work"
        self.waited, self.beside = waited, beside


class Answer:
    """What a server keeps for ONE request from its arrival until its
    answer has gone out: the request's place and its deadline, when
    it was counted at its arrival, and its turn, when it has one.

    The work of a request ends when its handler returns, and its
    memory does not: the answer is still to be made into bytes and
    sent, and a job's answer can be tens of megabytes.  So a turn
    that was given back when the work ended let the next request
    start beside all of that -- measured, with the work in turn and
    the answers not, three requests at once still ended a 256 MiB
    instance.  A handler therefore opens its
    scope with the request's ``Answer`` (:func:`server_scope`), the
    turn stays with it when the block ends, and whoever sends the
    answer calls :meth:`sent` when it has gone out (the application
    does, in its outermost middleware, on every way out).

    A client that does not read its answer cannot keep the turn for
    ever: past the request's deadline a turn that is only lent is
    taken back for whoever is waiting (:class:`_Turns`).

    A request holds memory before it has a turn, too: its body.  So
    the application counts a request that would read config text
    when its headers arrive (:meth:`arrived`), before a byte of its
    body is read, and one that finds every place taken is refused
    then.  The place is given back with the answer -- when it has
    gone out, or never will -- on every way out.

    Attributes:
        deadline: When the request's time is up (a
            ``time.monotonic()`` time), counted from its ARRIVAL:
            the body has that long to come in, the request to get
            its turn and be worked on, and the answer to go out.
            ``None`` for a request that was not counted -- under
            limits that do not say how many work at once, or one
            that reads no config text.
    """

    __slots__ = ("_gone", "_held", "_in_line", "_place", "deadline")

    def __init__(self) -> None:
        self._held: _Held | None = None
        self._gone = False
        self._place = False
        self._in_line = False
        self.deadline: float | None = None

    def arrived(self, limits: Limits | str | None = None) -> None:
        """The request's headers are in, and it is one that would
        read config text: count it, BEFORE its body is read.

        Under limits that say how many requests work at once there
        are that many places and :data:`MOST_WAITING` more.  The
        request takes one, and its deadline is set, counted from
        now.  Under any other limits nothing is counted and
        nothing is set.

        Raises:
            LimitExceeded: With ``kind`` :data:`AT_ONCE`: every
                place is taken.  The request is to be answered
                with that at once, and its body left unread.
        """
        resolved = resolve(limits)
        if resolved.at_once is None or resolved.seconds is None:
            return
        _TURNS.admit(resolved, self)
        self.deadline = time.monotonic() + resolved.seconds

    def left(self) -> float | None:
        """The seconds until the request's deadline (negative past
        it); ``None`` for a request that has none."""
        return None if self.deadline is None else self.deadline - time.monotonic()

    def sent(self) -> None:
        """The answer has gone out, or never will (the client left, the
        handler raised, the answer was abandoned at the request's
        deadline): give the turn back, and the place.  Safe to call
        from any thread, more than once, and for a request that
        took neither.

        A request whose block is still running -- its client left and
        nothing waits for the answer any more -- keeps its turn and
        its place until the block ends: the work is still using the
        memory.
        """
        _TURNS.answer_sent(self)


class _Turns:
    """Whose turn it is, on a server that works on a set number of
    requests at once.

    One for the process, because what the limit protects is the
    process's memory, which every server in it shares.

    A turn is taken by a worker thread -- the server runs a handler
    on one, and the sanitiser hands its work to one -- and the wait
    for it is a ``threading.Condition``, which the event loop is
    never inside: ``/health`` and the pages are not behind it.  When
    the thread's block ends the turn is given back, or -- for a
    request with an :class:`Answer` -- lent to the answer until that
    has gone out.  Nothing here knows of a connection: a client that
    goes away while its handler waits or works changes nothing, since
    the thread runs on to the end of its block either way, and the
    answer is then "sent" as soon as there is nobody to send it to.

    Turns are taken in order of arrival.  A request that arrives
    while others wait goes to the back even if a place is free at
    that instant, so a waiter is never passed by a newcomer.

    It also counts PLACES (:meth:`admit`): the requests that have
    arrived and whose answer has not gone out, whatever they are
    doing -- sending a body, waiting, at work, being answered.

    Three things bound it.  Nothing waits longer than its own
    deadline.  At most :data:`MOST_WAITING` wait at all.  And a turn
    that is lent to an answer nobody reads is taken back at its
    holder's deadline.  That is also what happens to a waiting thread
    when the server is told to stop: it ends when its turn comes or
    its deadline passes, whichever is first, as a thread that is
    working does -- a server that waits for its requests before it
    exits waits no longer for one of these.
    """

    __slots__ = ("_changed", "_lent", "_line", "places", "working")

    def __init__(self) -> None:
        self._changed = threading.Condition(threading.Lock())
        self._line: deque[object] = deque()
        self._lent: list[_Held] = []
        #: Turns that are out: at work, or lent to an answer.
        self.working = 0
        #: Places that are taken: requests counted at their arrival
        #: whose answer has not gone out.
        self.places = 0

    @property
    def waiting(self) -> int:
        return len(self._line)

    def _give_back(self, held: _Held) -> None:
        """With the lock held."""
        if held.state == "back":
            return
        if held.state == "lent":
            self._lent.remove(held)
        held.state = "back"
        self.working -= 1
        self._changed.notify_all()

    def admit(self, limits: Limits, answer: Answer) -> None:
        """Give the request of *answer* a place under *limits*, or
        refuse it: there are as many places as may work at once and
        :data:`MOST_WAITING` more.

        Raises:
            LimitExceeded: Every place is taken.
        """
        most = (limits.at_once or 1) + MOST_WAITING
        with self._changed:
            if answer._place:
                return
            if self.places >= most:
                raise _busy(limits, self.places + 1, None)
            self.places += 1
            answer._place = True

    def _settle(self, answer: Answer | None) -> None:
        """With the lock held: give back the place of *answer*'s
        request, if its answer has gone and none of its work is
        still going on -- in the line, or at work with its turn."""
        if answer is None or not answer._place or not answer._gone or answer._in_line:
            return
        held = answer._held
        if held is not None and held.state == "at_work":
            return
        answer._place = False
        self.places -= 1

    def _take_back_what_is_overdue(self, now: float) -> float | None:
        """With the lock held: take back every lent turn whose holder's
        deadline has passed; the earliest deadline of those still
        lent."""
        for held in [held for held in self._lent if held.deadline <= now]:
            self._give_back(held)
        return min((held.deadline for held in self._lent), default=None)

    def take(self, limits: Limits, deadline: float, answer: Answer | None = None) -> _Held | None:
        """Take a turn under *limits*, waiting for one until
        *deadline* (a ``time.monotonic()`` time).

        Returns:
            The turn; ``None`` when the request of *answer* is at work
            under its turn already (a block inside its block, on a
            thread the context did not follow): there is nothing more
            to take, and nothing for this caller to give back.

        Raises:
            LimitExceeded: The deadline passed in the line, or the
                line was full.  No turn is held.
        """
        most = limits.at_once or 1
        with self._changed:
            mine = answer._held if answer is not None else None
            if mine is not None and mine.state == "at_work":
                return None
            if mine is not None and mine.state == "lent":
                # The same request, at work again: it never gave its turn up.
                self._lent.remove(mine)
                mine.state = "at_work"
                return mine
            self._take_back_what_is_overdue(time.monotonic())
            waited, beside = 0.0, 0
            if self.working >= most or self._line:
                if len(self._line) >= MOST_WAITING:
                    raise _busy(limits, self.working + len(self._line) + 1, None)
                me = object()
                self._line.append(me)
                beside, began = self.working + len(self._line), time.monotonic()
                if answer is not None:
                    answer._in_line = True
                refused = True
                try:
                    while True:
                        now = time.monotonic()
                        soonest = self._take_back_what_is_overdue(now)
                        if self.working < most and self._line[0] is me:
                            break
                        if deadline <= now:
                            raise _busy(limits, self.working + len(self._line), limits.seconds)
                        # Until the turn comes, the time is up, or a lent
                        # turn falls due -- whichever is first.
                        self._changed.wait(min(deadline, soonest or deadline) - now)
                    refused = False
                finally:
                    self._line.remove(me)
                    if answer is not None:
                        answer._in_line = False
                        if refused:
                            # Its client may have left while it stood here.
                            self._settle(answer)
                    # Whoever is first in the line now may have a place.
                    self._changed.notify_all()
                # Never zero for a request that stood in the line: a
                # refusal for time that follows says it was busy.
                waited = max(time.monotonic() - began, 1e-9)
            held = _Held(deadline, waited, beside)
            self.working += 1
            if answer is not None:
                answer._held = held
            return held

    def done(self, held: _Held, answer: Answer | None) -> None:
        """The block that took *held* has ended: lend the turn to
        *answer* until that has gone out, or give it back."""
        with self._changed:
            if answer is None or answer._gone or answer._held is not held or held.state != "at_work":
                self._give_back(held)
                self._settle(answer)
                return
            held.state = "lent"
            self._lent.append(held)
            # Whoever waits now waits no longer than this turn's deadline.
            self._changed.notify_all()

    def answer_sent(self, answer: Answer) -> None:
        with self._changed:
            answer._gone = True
            held = answer._held
            if held is not None and held.state == "lent":
                self._give_back(held)
            self._settle(answer)


_TURNS = _Turns()
_TURN: ContextVar[_Held | None] = ContextVar("netcanon_limits_turn", default=None)


def in_flight() -> tuple[int, int]:
    """How many requests hold a turn in this process -- at work, or
    with their answer still going out -- and how many wait for one.
    Requests under limits with no ``at_once`` are in neither number:
    they take no turn."""
    return _TURNS.working, _TURNS.waiting


def places() -> int:
    """How many places are taken in this process: the requests that
    were counted at their arrival (:meth:`Answer.arrived`) and
    whose answer has not gone out."""
    return _TURNS.places


@contextmanager
def server_scope(
    limits: Limits | str | None = None, *, answer: Answer | None = None,
) -> Iterator[None]:
    """The scope of ONE REQUEST to a server: :func:`limits_scope`, and
    the request's turn.  Every handler that hands config text to a
    parser opens this, and nothing else does.

    Under limits that set ``at_once`` the request first waits for a
    turn (:class:`_Turns`).  Its deadline is set BEFORE the wait and
    the wait ends at it: a request has one deadline, and the time it
    stood in the line is time it has spent.  The deadline is counted
    from when the scope was opened -- or, for a request the
    application counted at its arrival (*answer* has a deadline),
    from then: the time its body took to come in is time it has
    spent too.  With its turn it first hands back to the system the
    memory that earlier requests used and freed
    (:func:`_hand_freed_memory_back`).

    A request that waited and then runs out of time is refused as
    BUSY (:func:`_out_of_time`): in words that say how long it
    waited and to send it again, and filed as :data:`AT_ONCE`.

    The turn is given back on every way out of the block -- a return,
    a refusal, any exception.  With *answer*, it is not given back
    there but lent to the answer, and comes back when the answer has
    gone out (:class:`Answer`): the memory of a request outlasts its
    work by the making and the sending of what it answers.

    A server scope opened inside one that holds a turn takes no
    second turn and does not wait for the first: it is the same
    request.  (The context carries the turn, as it carries the
    scope.)  So is a second scope opened for the same *answer*.

    Args:
        limits: A :class:`Limits`, the name of one of :data:`PROFILES`,
            or ``None`` for :data:`STANDARD`.
        answer: The request's :class:`Answer`, from whoever will send
            it.  ``None`` -- a caller with nobody to tell it that the
            answer went out -- gives the turn back when the block
            ends.

    Raises:
        LimitExceeded: With ``kind`` :data:`AT_ONCE`: the deadline
            passed while the request waited, or enough were waiting
            already.  Raised before the block is entered; no turn is
            held.
    """
    resolved = resolve(limits)
    scope = _Scope(resolved, "server")
    if answer is not None and answer.deadline is not None and scope.deadline is not None:
        # One deadline a request, and this one's began at its arrival.
        scope.deadline = min(scope.deadline, answer.deadline)
    outer = _TURN.get()
    held: _Held | None = None
    if (
        resolved.at_once is not None and scope.deadline is not None
        and not (outer is not None and outer.state == "at_work")
    ):
        held = _TURNS.take(resolved, scope.deadline, answer)
    turn_of = held if held is not None else outer
    if turn_of is not None and turn_of.state == "at_work":
        scope.waited, scope.beside = turn_of.waited, turn_of.beside
    try:
        if held is not None:
            _hand_freed_memory_back()
        token = _SCOPE.set(scope)
        turn = _TURN.set(held) if held is not None else None
        try:
            yield
        finally:
            if turn is not None:
                _TURN.reset(turn)
            _SCOPE.reset(token)
    finally:
        if held is not None:
            _TURNS.done(held, answer)


@contextmanager
def metered(stage: str, codec: str = "") -> Iterator[_Meter]:
    """One stage's meter.  ``CodecBase`` wraps every ``parse`` and
    ``render`` in it.  A stage inside a stage (a codec that parses in
    order to render) counts on the outer meter.

    Raises:
        LimitExceeded: The scope's time was spent before the stage
            began: a request that is out of time does not start
            another parse or another render.
    """
    outer = _METER.get()
    if outer is not None:
        outer.check_clock(starting=True)
        yield outer
        return
    scope = _SCOPE.get()
    waited, beside = 0.0, 0
    if scope is None:
        limits, surface = STANDARD, "server"
        deadline = None if limits.seconds is None else time.monotonic() + limits.seconds
    else:
        limits, surface, deadline = scope.limits, scope.surface, scope.deadline
        waited, beside = scope.waited, scope.beside
    meter = _Meter(limits, surface, deadline, stage, codec, waited, beside)
    token = _METER.set(meter)
    try:
        meter.check_clock(starting=True)
        yield meter
    finally:
        _METER.reset(token)


def charge(kind: str, n: int, where: str = "", what: str = "") -> None:
    """Count *n* more of *kind* BEFORE making them.

    Outside any stage (a transform called by itself) there is no
    running count to add to, so *n* alone is held to the limit.

    Args:
        kind: A key of :data:`KINDS`.
        n: How many are about to be made.
        where: What stands for them, as the config wrote it (a range,
            a name).  A refusal quotes its first 80 characters.
        what: The kind in words, where :data:`KINDS` is not exact
            enough for this place.

    Raises:
        LimitExceeded: That passes the limit in force, or the
            deadline has passed.
    """
    meter = _METER.get()
    if meter is not None:
        meter.charge(kind, n, where, what)
        return
    scope = _SCOPE.get()
    limits = scope.limits if scope is not None else STANDARD
    cap = getattr(limits, kind)
    if cap is not None and n > cap:
        raise LimitExceeded(
            kind, n, cap, where=where, what=what, profile=limits.name,
            hint=how_to_raise(limits, kind, scope.surface if scope is not None else "server"),
        )


def distinct(kind: str, names: list[str], where: str = "", what: str = "") -> None:
    """Count the different names of *kind* made so far in this stage.
    Outside a stage, the names given are held to the limit by
    themselves.

    Raises:
        LimitExceeded: There are more different names than the limit.
    """
    meter = _METER.get()
    if meter is not None:
        meter.distinct(kind, names, where, what)
    else:
        charge(kind, len(set(names)), where, what)


def tick() -> None:
    """One step of a loop over untrusted text: every 256th looks at
    the deadline.  For a ``while`` loop; a ``for`` loop uses
    :func:`ticked`.  Outside a stage it does nothing."""
    meter = _METER.get()
    if meter is None:
        return
    meter._n += 1
    if not meter._n & 0xFF:
        meter.check_clock()


def _ticking(items: Iterable[_T], clock: _Meter | _Scope) -> Iterator[_T]:
    for n, item in enumerate(items, 1):
        if not n & 0xFF:
            clock.check_clock()
        yield item


def _in_runs(items: list[_T], clock: _Meter | _Scope) -> Iterator[list[_T]]:
    """*items* a run of 256 at a time, with a look at the clock before
    every run but the first."""
    start = 0
    while start < len(items):
        if start:
            clock.check_clock()
        yield items[start:start + 256]
        start += 256


def ticked(items: Iterable[_T]) -> Iterable[_T]:
    """*items*, with the deadline looked at at every 256th.  Wrap the
    iterable of every loop over the lines of a config: ``for line in
    ticked(raw.splitlines()):``.  With no deadline in force it is
    *items* itself, and costs nothing.

    Inside a stage the deadline is the stage's; outside one, the
    scope's, if a scope is open.

    A list -- what ``splitlines()`` gives -- is handed over a run of
    256 at a time, which costs a slice a run and a third of what a
    generator costs a line.  So a loop must not rewrite the lines
    AHEAD of itself in the list it is walking: it would be walking a
    copy of the run it is in.  One that does walks by index, and calls
    :func:`tick`."""
    clock: _Meter | _Scope | None = _METER.get() or _SCOPE.get()
    if clock is None or clock.deadline is None:
        return items
    if type(items) is list:
        return chain.from_iterable(_in_runs(items, clock))
    return _ticking(items, clock)


def census(tree: Any) -> None:
    """Count what a finished parse holds, whoever made it.

    The places that expand a token count BEFORE they make, so that a
    refusal comes before the memory is spent; this is the count that
    needs no list of such places.  It reads lengths only -- except
    for the ports no stanza declares, which it looks for only when
    there are enough memberships for there to be too many of them.

    Raises:
        LimitExceeded: The tree holds more of a kind than the limit.
    """
    meter = _METER.get()
    interfaces = getattr(tree, "interfaces", None)
    vlans = getattr(tree, "vlans", None)
    if meter is None or interfaces is None or vlans is None:
        return
    meter.settle("interfaces", len(interfaces), what=_HELD["interfaces"])
    meter.settle(
        "vlan_ids", sum(len(i.trunk_allowed_vlans) for i in interfaces),
        what=_HELD["vlan_ids"],
    )
    lags = getattr(tree, "lags", None) or []
    pairs = (
        sum(len(v.tagged_ports) + len(v.untagged_ports) for v in vlans)
        + sum(len(lag.members) for lag in lags)
    )
    meter.settle("memberships", pairs, what=_HELD["memberships"])
    cap = meter.limits.ports
    if cap is not None and pairs > cap:
        named: set[str] = set()
        for v in vlans:
            named.update(v.tagged_ports)
            named.update(v.untagged_ports)
        for lag in lags:
            named.update(lag.members)
        named.difference_update(i.name for i in interfaces)
        meter.settle("ports", len(named), what=_HELD["ports"])
