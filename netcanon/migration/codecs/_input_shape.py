"""
Shape detection for codec input — tolerates leading framing junk.

Every CLI-flavoured codec (cisco_iosxe_cli, fortigate_cli,
juniper_junos, mikrotik_routeros, arista_eos, aruba_aoss) needs to
reject XML / JSON inputs early — operators who pick the wrong codec
in the migrate UI should hit a clean ``ParseError`` instead of a
silent "completed with zero supported paths" near-empty render.

Pre-Phase-3 Round 4.2 each codec did the inline check::

    stripped = raw.lstrip()
    if stripped.startswith("<") or stripped.startswith("{"):
        raise ParseError(...)

That ``stripped[0]`` check is **too strict for real captures**.  The
backup collector (and many manual ``cat`` / ``show`` paste flows)
prefix the actual config with framing lines:

* OPNsense / FreeBSD shell capture::

      cat /conf/config.xml
      <?xml version="1.0"?>
      <opnsense>...

* Cisco-IOS session-transcript paste::

      router# show running-config
      Building configuration...
      !
      ! Last configuration change ...

* Operator MOTD / banner preceded by the actual config body.

The first non-empty line in all of those isn't ``<``; the actual
shape signal is on line 2-5.  This helper scans the first
``max_lines`` non-empty lines and reports the first XML / JSON shape
it sees — which covers the real captures without slowing down the
common clean-paste case.

Design:

* **Module-private** name (leading underscore) — no caller outside
  the codec parsers should plug in.
* **Bounded scan** (``max_lines=5`` default) — keeps the helper O(1)
  for arbitrarily large inputs.
* **No JSON-vs-Junos-curly-brace ambiguity** — we deliberately
  match a bare leading ``{`` for JSON; Junos ``set`` configs never
  start with a bare brace at column 0 (Junos ``{`` blocks are
  always preceded by a keyword like ``system { ... }``), so the
  curly-brace match is safe in practice.

The regex marker for XML is purposely tight: either ``<?xml`` (the
XML declaration) or ``<`` followed by an XML-NAME-start character
(letter), then an XML-name body character (letter / digit / hyphen
/ underscore), then a separator (whitespace / ``>`` / ``/``).  That
won't false-positive on a CLI line containing ``<`` mid-text
(e.g. an ``! Comment: <upstream router>`` description) — the regex
anchors at start-of-stripped-line, so descriptions and comments
don't trip it.
"""

from __future__ import annotations

import re

__all__ = ["detect_input_shape"]


# Anchored at start of stripped line.  Two forms:
#   <?xml ...       — XML declaration (most explicit)
#   <name ...       — root element opener (letter-starting tag)
# The second alternative requires a separator (whitespace / ``>`` /
# ``/``) after the name to avoid matching CLI lines that happen to
# contain ``<word`` mid-token (rare but possible in descriptions).
_XML_MARKER = re.compile(
    r"^<(?:\?xml\b|[A-Za-z][A-Za-z0-9_\-]*[\s>/])"
)

# JSON object opener — bare ``{`` at start of stripped line.  Real
# JSON output (e.g. REST API responses pasted into the wrong codec)
# always starts a top-level object this way.  See module docstring
# for the Junos-curly-brace non-conflict.
_JSON_MARKER = re.compile(r"^\{")


def detect_input_shape(raw: str, *, max_lines: int = 5) -> str | None:
    """Sniff the first few non-empty lines for XML / JSON shape.

    Args:
        raw: The raw input as the codec sees it (operator paste or
            stored file content).
        max_lines: How many non-empty leading lines to scan before
            giving up.  Default 5 — covers shell-echo + banner +
            blank line + actual config opener.  Bounded to keep the
            helper cheap even on 100K-line pastes.

    Returns:
        ``"xml"`` if any of the first *max_lines* non-empty lines
        looks like an XML declaration or root element opener;
        ``"json"`` if any starts with ``{``; ``None`` otherwise.

    Examples:
        >>> detect_input_shape("<?xml version='1.0'?>\\n<opnsense>")
        'xml'
        >>> detect_input_shape("cat /conf/config.xml\\n<?xml version='1.0'?>")
        'xml'
        >>> detect_input_shape("router# show run\\nBuilding config...\\n!\\nhostname r1")
        >>> detect_input_shape("{\\n  \\"key\\": 1\\n}")
        'json'
        >>> detect_input_shape("! IOS comment\\nhostname router")
        >>> detect_input_shape("interface Vlan10\\n description <upstream link>")
    """
    seen = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        seen += 1
        if seen > max_lines:
            break
        if _XML_MARKER.match(line):
            return "xml"
        if _JSON_MARKER.match(line):
            return "json"
    return None
