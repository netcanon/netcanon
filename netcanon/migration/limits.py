"""What one request may make, and for how long.

A config is whatever was pasted, and a few bytes of it can stand for a
great deal: a range is thousands of entries, ``all`` is 4,094, and two
honest counts multiply.  The length of the text therefore bounds neither
the memory a request takes nor its time.  This module COUNTS what a
request makes, at the places where a few bytes become many entries, and
refuses -- in words an operator can act on -- past a limit.  It also
carries the request's deadline, which the same places look at, and so
does every parser's loop over the lines of a config.

Three things:

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

import time
from collections.abc import Iterable, Iterator
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

#: What the count of a finished tree calls each kind (:func:`census`).
_HELD = {
    "vlan_ids": "VLAN ids in the allowed lists of ports",
    "memberships": "port memberships (one port in one VLAN or one LAG)",
    "ports": "ports that a VLAN's or a LAG's port list names and no interface stanza declares",
    "interfaces": "interfaces",
}


@dataclass(frozen=True)
class Limits:
    """The most one stage may make of each kind, and the seconds one
    scope may take.  ``None`` is no limit."""

    name: str
    vlan_ids: int | None
    memberships: int | None
    ports: int | None
    interfaces: int | None
    copies: int | None
    words: int | None
    text: int | None
    seconds: float | None


#: The public demo: a container of 256 MiB and half a CPU for each
#: visitor, behind a proxy that waits 30 seconds and takes a body of
#: two megabytes.  The numbers are what was measured in such a
#: container (``docs/demo-plan/07-budget.md`` has the measurements):
#: with them, the text that reaches every limit at once is one request
#: the instance survives.  ``vlan_ids``: 256 ports that each allow
#: every VLAN.
SMALL = Limits(
    "small", 1_048_576, 50_000, 2_048, 2_500, 10_000, 250_000, 8_000_000, 20.0,
)
#: The default.  ``vlan_ids``: 4,096 ports that each allow every VLAN.
#: ``memberships``: three times the largest device a vendor verifies.
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
        kind: The kind that was over, a key of :data:`KINDS`.
        surface: ``server`` (the web application and the desktop
            application, which embeds it) or ``cli``.

    Under ``small`` this never names a setting: those limits are the
    public demo's, and a visitor there cannot change one.  It says
    what a Netcanon of one's own allows.
    """
    said: list[str] = []
    if limits.name == "small":
        allowed = getattr(STANDARD, kind, None) if kind else None
        own = (
            f" allows {_number(allowed)}" + (" seconds" if kind == "seconds" else "")
            if allowed is not None else " allows more"
        )
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
        kind: A key of :data:`KINDS`.
        asked: How many had been asked for when counting stopped (for
            ``seconds``: how long the request had run).
        cap: The limit.
        exact: ``asked`` is the whole number -- it was counted on
            something already made.  ``False`` for a count made before
            the entries were: "at least this many".
        stage: ``parse`` or ``render`` (``""`` outside both).
        codec: The codec whose stage it was.
        lists: How many lists, ranges or statements had been counted.
        where: The last thing counted, as the config wrote it; at most
            80 characters.  For the client: never logged.
        what: The kind in words.
        profile: Name of the :class:`Limits` in force.
        hint: What allows more (:func:`how_to_raise`).
        starting: For ``seconds``: the time was already spent when
            the stage began.
    """

    def __init__(
        self, kind: str, asked: float, cap: float, *, exact: bool = False,
        stage: str = "", codec: str = "", lists: int = 0, where: str = "",
        what: str = "", profile: str = "", hint: str = "", starting: bool = False,
    ) -> None:
        self.kind, self.asked, self.cap, self.exact = kind, asked, cap, exact
        self.stage, self.codec, self.lists = stage, codec, lists
        self.where, self.profile, self.hint = where[:80], profile, hint
        self.what = what or KINDS.get(kind, (kind, ""))[0]
        self.starting = starting
        super().__init__(self._words())

    def _words(self) -> str:
        doing = {
            "parse": f"reading the config as {self.codec}",
            "render": f"writing the config for {self.codec}",
        }.get(self.stage, "")
        if self.kind == "seconds":
            when = ""
            if doing:
                when = f" before {doing} began" if self.starting else f" while {doing}"
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

    __slots__ = ("deadline", "limits", "surface")

    def __init__(self, limits: Limits, surface: str) -> None:
        self.limits, self.surface = limits, surface
        self.deadline = (
            None if limits.seconds is None else time.monotonic() + limits.seconds
        )

    def check_clock(self) -> None:
        """Refuse if the deadline has passed.  For a loop over lines
        that runs outside any stage (reading the device out of a
        config, before the parse)."""
        if self.deadline is not None:
            over = time.monotonic() - self.deadline
            if over > 0:
                cap = self.limits.seconds or 0
                raise LimitExceeded(
                    "seconds", round(cap + over, 3), cap, exact=True,
                    profile=self.limits.name,
                    hint=how_to_raise(self.limits, "seconds", self.surface),
                )


class _Meter:
    """The running counts of one stage."""

    __slots__ = (
        "_n", "codec", "counts", "deadline", "limits", "lists", "names", "stage",
        "surface",
    )

    def __init__(
        self, limits: Limits, surface: str, deadline: float | None,
        stage: str, codec: str,
    ) -> None:
        self.limits, self.surface, self.deadline = limits, surface, deadline
        self.stage, self.codec = stage, codec
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
                cap = self.limits.seconds or 0
                self._refuse("seconds", round(cap + over, 3), cap, "", True, starting=starting)

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
    if scope is None:
        limits, surface = STANDARD, "server"
        deadline = None if limits.seconds is None else time.monotonic() + limits.seconds
    else:
        limits, surface, deadline = scope.limits, scope.surface, scope.deadline
    meter = _Meter(limits, surface, deadline, stage, codec)
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
