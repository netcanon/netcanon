"""A value of the canonical tree is written on one line.

Every renderer writes a config a line at a time and puts a value into
its line as it stands, so a value that holds a line break is written as
lines of its own, and the device reads the text after the break as a
command.  An interface description that held ``username x privilege 15
nopassword`` after a break was that account, with no password, on
IOS-XE, EOS, NX-OS, AOS-CX and OS10, in a job that said ``completed``;
every renderer wrote the extra line.  The parsers that read XML (OPNsense,
IOS-XE over NETCONF) keep a line break that an element's text holds, and
FortiOS prints a value of several lines inside its quotes, so the tree
can hold one.

No target is given a value of more than one line, whatever the field:

* :func:`one_line_each` writes each run of line breaks in a value as
  one space, in place, and returns where it did -- the pipeline calls it
  after the transforms (an operator's map is a value too) and before
  validation, and says each place in the job's warnings;
* :func:`first_line_break` is the check :meth:`CodecBase.render` makes
  before any renderer runs: a tree that still holds a line break is
  refused, so a caller that renders without the pipeline cannot write
  one either.

A line break is any character :meth:`str.splitlines` ends a line at
(:data:`LINE_BREAKS`), not only ``\\n``: a device, or a reader of the
output, may end a line at any of them.

What this costs a target that could hold the break -- an XML target, or
FortiOS inside its quotes -- is the layout of the text, and the warning
says so.  It is the same rule for every target because the alternative
is a list of which field of which target may hold a break, and a value
in the wrong place on that list is an account.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from .limits import ticked

#: The characters :meth:`str.splitlines` ends a line at.  A test holds
#: this to what ``splitlines`` does over every code point.
LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"

#: A run of them; the same characters, as a test holds.
_A_RUN = re.compile(r"[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]+")

#: The field that names a record in a place, first present first:
#: ``interfaces[Gi1].description``, ``vlans[10].name``,
#: ``static_routes[0.0.0.0/0].description``.
_NAMED_BY = ("name", "id", "destination", "network", "host", "prefix")


def _label(record: Any, index: int) -> str:
    for key in _NAMED_BY:
        value = getattr(record, key, None)
        if isinstance(value, bool) or value is None or value == "":
            continue
        if isinstance(value, (str, int)):
            text = str(value)
            if not _A_RUN.search(text):
                return text
    return str(index)


#: The types a value of the tree has that hold no text.
_NO_TEXT = frozenset({int, float, bool, type(None)})


class _Walk:
    """One walk of a tree.  ``mend`` writes each run as a space;
    ``named`` puts each record's name in the place, else ``[]``.

    It reads every field a record holds, whatever the schema says the
    field is (a parser that appends to a list is not validated), and a
    list of values with no text in them, or of text with no line break
    in it, is read at once rather than value by value: a trunk's list
    of every VLAN is 4,094 of them."""

    def __init__(self, *, mend: bool, named: bool, first: bool) -> None:
        self.mend = mend
        self.named = named
        self.first = first
        self.found: list[str] = []

    def done(self) -> bool:
        return self.first and bool(self.found)

    def _one(self, value: str, where: str) -> str | None:
        if _A_RUN.search(value) is None:
            return None
        self.found.append(where)
        return _A_RUN.sub(" ", value) if self.mend else None

    def model(self, record: BaseModel, where: str) -> None:
        held = dict(record.__dict__)
        held.update(record.__pydantic_extra__ or {})
        for name, value in held.items():
            if type(value) in _NO_TEXT or not value:
                continue
            here = f"{where}.{name}" if where else name
            if isinstance(value, str):
                mended = self._one(value, here)
                if mended is not None:
                    setattr(record, name, mended)
            else:
                self.value(value, here)
            if self.done():
                return

    def value(self, value: Any, where: str) -> None:
        if isinstance(value, BaseModel):
            self.model(value, where)
        elif isinstance(value, list):
            self.items(value, where)
        elif isinstance(value, dict):
            self.mapping(value, where)
        elif isinstance(value, (tuple, set, frozenset)):
            for item in ticked(list(value)):
                if isinstance(item, str):
                    self._one(item, f"{where}[]")
                else:
                    self.value(item, f"{where}[]")
            # Not mended: no field of the tree is one, and what a
            # tuple or a set holds is not written back in place.

    def items(self, values: list[Any], where: str) -> None:
        kinds = set(map(type, values))
        if kinds <= _NO_TEXT:
            return
        if kinds == {str} and not _A_RUN.search("".join(values)):
            return
        for index, item in enumerate(ticked(values)):
            if isinstance(item, str):
                mended = self._one(item, where)
                if mended is not None:
                    values[index] = mended
            elif isinstance(item, BaseModel):
                label = _label(item, index) if self.named else ""
                self.model(item, f"{where}[{label}]")
            elif type(item) not in _NO_TEXT:
                self.value(item, f"{where}[]")
            if self.done():
                return

    def mapping(self, values: dict[Any, Any], where: str) -> None:
        renamed: dict[Any, Any] = {}
        for key in ticked(list(values)):
            item = values[key]
            label = key if self.named and isinstance(key, str) else ""
            if isinstance(key, str):
                mended = self._one(key, f"{where} (a key)")
                if mended is not None:
                    renamed[key] = mended
                    label = mended if self.named else ""
            if isinstance(item, str):
                mended = self._one(item, f"{where}[{label}]")
                if mended is not None:
                    values[key] = mended
            elif type(item) not in _NO_TEXT:
                self.value(item, f"{where}[{label}]")
            if self.done():
                return
        if renamed:
            rebuilt = {renamed.get(k, k): v for k, v in values.items()}
            values.clear()
            values.update(rebuilt)


def one_line_each(tree: Any) -> list[str]:
    """Write each run of line breaks in every text value of *tree* as
    one space, in place.

    Returns:
        Where a value held one, a place each value, the records named
        (``interfaces[Gi1].description``).  Empty when no value did,
        and then *tree* is as it was.
    """
    walk = _Walk(mend=True, named=True, first=False)
    walk.value(tree, "")
    return walk.found


def first_line_break(tree: Any) -> str | None:
    """The first place in *tree* whose value holds a line break, by
    field and not by record (``interfaces[].description``: what it
    returns is said in an error, and an error is logged, so it names
    nothing of the config), or ``None``."""
    walk = _Walk(mend=False, named=False, first=True)
    walk.value(tree, "")
    return walk.found[0] if walk.found else None


def said(where: str) -> str:
    """The job's warning for a value :func:`one_line_each` wrote on one
    line."""
    return (
        f"{where} held a line break: it is written on one line, each "
        "break as a space, because no target is given a value of more "
        "than one line"
    )
