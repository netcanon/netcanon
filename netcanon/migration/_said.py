"""A review line the renderer writes for a loss is a warning of the job.

A renderer writes a ``review:`` comment where it leaves a record out,
or writes it otherwise than the tree holds it, for a reason of the
target's own: a VRRP group of a protocol the target does not run, a
trunk of every VLAN on a platform with no word for that, a VLAN
interface with no port to ride on, an SNMP trap host given a community
the source did not state.  The validation report is made from the tree
before the renderer decides, so it lists none of these, and a job
whose only loss was such a line said ``completed`` (AGENTS.md: "a
warning is not a status").

Each such line is made through :func:`review` (or :func:`review_line`),
which returns the line's words and, where a job is rendering
(:func:`said_while_rendering`, which the pipeline opens around
:meth:`~netcanon.migration.codecs.base.CodecBase.render`), adds a
warning of the job that restates them: ``Review: <where> -- <why>.``.
The line and its warning come from one call, so neither is a copy of
the other.  Outside a job (the sanitiser, a bare render) nothing is
collected and the line is the same text.

The lines of a value a target does not read as one value are made
here too, by :mod:`netcanon.migration._one_value` (:func:`review_line`).
Two kinds of review line are not:

* a DOUBT -- a line that writes the value and asks for a check on the
  device, because no vendor page found says what the device does with
  it ("not established", "check it on the device", "Dell's pages
  disagree"), or says what the device's own form refuses when the
  record is edited there (an OPNsense VLAN device name).  The output
  holds what the source held; the job is not held for it;
* a line a target says another way: in
  :meth:`~netcanon.migration.codecs.base.CodecBase.render_warnings`
  (a credential it cannot carry, an account, a DHCP pool, a bond, the
  AOS-S management plane and VLAN interfaces, the RouterOS ``lo``),
  where the warning is made by the code that decides, or by the check
  of the names two source names share.

``tests/unit/migration/test_a_review_line_holds_the_job.py`` holds every
review line of an output to one of the three, and every call of
:func:`review` or :func:`review_line` in the product to an input that
reaches it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

#: The warnings of the render at work, where a job is rendering
#: (:func:`said_while_rendering`); ``None`` elsewhere.
_SAID: ContextVar[list[str] | None] = ContextVar("review_lines_said", default=None)


@contextmanager
def said_while_rendering() -> Iterator[list[str]]:
    """A warning for each review line made through :func:`review` while
    the block runs.

    Read from the lines the renderer makes, as it makes them, so that a
    line and its warning are one.

    Yields:
        The list the warnings are added to, in the order the lines are
        made; each is ``Review: <where> -- <why>.`` (``Review: <why>.``
        where the line names its own place), and never a secret.
    """
    said: list[str] = []
    token = _SAID.set(said)
    try:
        yield said
    finally:
        _SAID.reset(token)


def review(why: str, where: str = "") -> str:
    """The words of a review line for a loss, said as a warning of the
    job that is rendering.

    Args:
        why: What the line says after ``review:``: what was left out or
            written otherwise, and why.  It must not hold a secret.
        where: What the line is in, where its words do not name it (the
            interface whose stanza holds it, say); the warning names it.

    Returns:
        *why*, for the renderer to write after its ``review:`` marker.
    """
    said = _SAID.get()
    if said is not None:
        said.append(f"Review: {where} -- {why}." if where else f"Review: {why}.")
    return why


def review_line(place: str, why: str) -> str:
    """``<place> -- review: <why>``, said as :func:`review` says it, with
    *place* for *where*."""
    return f"{place} -- review: {review(why, place)}"
