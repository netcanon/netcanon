"""A value written into a comment stays in the comment.

A renderer says what it left out in a comment, and puts the name it
left out into that comment as the tree holds it.  A comment ends at its
terminator, and what follows the terminator is configuration: a source
account named ``x*/system{...}/*`` closed a VyOS ``/* */`` review
comment and left ``system{...}`` on the line as nodes, and one named
``x--><user>...</user><!--`` closed an OPNsense ``<!-- -->`` review
comment and wrote an account the source never had, holding whatever
elements the name spelled out.  A name that only held ``--``, which
XML allows nowhere in a comment, failed the OPNsense render with an
error that said nothing of the name.

So a comment a renderer builds from a value of the tree is built here,
and what would end it is broken where it stands (:func:`comment_text`).
A line comment (``!``, ``#``, ``;``) ends at the end of its line; a
value that holds a line break is another defect, and another rule's.

Guarded by ``tests/unit/migration/test_a_value_stays_in_its_comment.py``.
"""

from __future__ import annotations

import re

#: Each comment syntax a renderer writes: what opens it and what closes
#: it.  ``plain`` is the text alone, for a caller that puts it somewhere
#: of its own (the text of an XML element, which ElementTree escapes).
DELIMITERS: dict[str, tuple[str, str]] = {
    "hash": ("# ", ""),
    "semicolon": ("; ", ""),
    "exclamation": ("! ", ""),
    "slash": ("/* ", " */"),
    "xml": ("<!-- ", " -->"),
    "plain": ("", ""),
}

#: A hyphen that another follows: XML 1.0 (section 2.5) allows no
#: ``--`` inside a comment.
_HYPHEN_BEFORE_HYPHEN_RE = re.compile(r"-(?=-)")


def comment_text(text: str, syntax: str) -> str:
    """*text* as it can stand inside a comment of *syntax*.

    Nothing in the result ends the comment:

    * ``slash`` -- ``*/`` ends a ``/* */`` comment, and is written
      ``* /``.
    * ``xml`` -- XML 1.0 allows no ``--`` in a comment and no ``-`` at
      its end (``--->`` is not a close), so a hyphen that another
      follows is written with a space after it, and a final one is
      followed by a space.  The result is also safe as the text of an
      ``ET.Comment``, which ElementTree writes as it stands.

    Every other syntax ends at the end of its line, and *text* is
    returned as it is.

    Args:
        text: What the comment says, values of the tree included.
        syntax: A key of :data:`DELIMITERS`.

    Returns:
        *text*, with what would end the comment broken where it stands.
    """
    if syntax == "slash":
        return text.replace("*/", "* /")
    if syntax == "xml":
        text = _HYPHEN_BEFORE_HYPHEN_RE.sub("- ", text)
        return text + " " if text.endswith("-") else text
    return text


def comment(text: str, syntax: str) -> str:
    """*text* as one comment of *syntax*, its delimiters included.

    An unknown *syntax* is written as a ``#`` comment, as the review
    helpers always have.

    Args:
        text: What the comment says, values of the tree included.
        syntax: A key of :data:`DELIMITERS`.

    Returns:
        The comment, which nothing in *text* can end early.
    """
    prefix, suffix = DELIMITERS.get(syntax, DELIMITERS["hash"])
    return f"{prefix}{comment_text(text, syntax)}{suffix}"
