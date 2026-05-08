"""Cross-codec naming-value sanitisation utilities.

Some target vendors' CLI parsers reject whitespace in hostname /
domain / VRF-name tokens — Arista EOS and Cisco IOS-XE both treat
``hostname Quinta Router`` as ``hostname Quinta`` (truncate at first
space) or refuse the line entirely depending on parser version.

To produce a wire form that round-trips through the target's own
parser, the renderer should replace whitespace runs with a safe
separator before emit.  Source state (which may have spaces in
hostnames) is preserved on the canonical model and only modified
at the wire boundary.

Background
----------
Flagged by the mikrotik_routeros source agent (Phase 4b cross-vendor
cleanup): a synthetic mikrotik intent with ``hostname = "Quinta
Router"`` round-tripped through Arista as ``""`` (Arista parser
regex ``\\s*$`` rejects) and through Cisco IOS-XE CLI as
``"Quinta"`` (parser ``\\S+`` captures only the first token).  The
underlying issue is render-side: both codecs were emitting
``hostname Quinta Router`` unquoted, and their own parsers refused
the round-trip.

Per-vendor sanitisation policy may differ for other naming-value
slots (Junos / Aruba / FortiGate may have looser or stricter
rules).  This helper currently targets the two codecs whose
parsers actively reject whitespace; expand the call sites only
after auditing each new codec's parser grammar.

See also:
- netcanon/migration/codecs/arista_eos/render.py — VLAN-name
  sanitisation already uses the same regex inline; the hostname
  emit now routes through this helper.
- netcanon/migration/codecs/cisco_iosxe_cli/render.py — hostname
  emit uses this helper.
- netcanon/migration/_user_secrets.py — sibling shared utility for
  cross-codec hash-portability policy (separate concern).
"""

from __future__ import annotations

import re

_WHITESPACE_RUN = re.compile(r"\s+")


def sanitise_hostname(name: str, separator: str = "_") -> str:
    """Replace whitespace runs in *name* with *separator*.

    Returns the input unchanged when there's no whitespace.  Strips
    leading/trailing whitespace before substitution.  The default
    separator (``_``) matches what Arista's AVD style guide
    recommends for VLAN names with multi-word descriptions; Cisco
    accepts the same form natively.

    Args:
        name: The candidate hostname / naming token.  Empty or
            whitespace-only inputs return ``""``.
        separator: Replacement for whitespace runs.  Defaults to
            ``_`` (the AVD-recommended VLAN-name separator,
            accepted by both Arista and Cisco hostname parsers).

    Returns:
        The sanitised name.  Single-token names emit unchanged.
    """
    if not name:
        return name
    stripped = name.strip()
    if not stripped:
        return ""
    return _WHITESPACE_RUN.sub(separator, stripped)
