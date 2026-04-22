"""
Render the Aruba Central 5MemberStack AOS-S template into a concrete,
parseable config for real-capture validation.

Source template (downloaded as a build step; not vendored directly):
    https://raw.githubusercontent.com/aruba/central-sample-bulk-configurations/
    master/ArubaOS-Switch%20Templates/5MemberStack%20-%20Template/
    5memberStack%20-%20Template.txt

The template uses two kinds of substitution directive:

  %variable%           - replace with value from SUBSTITUTIONS dict
  %if X%               - emit body if SUBSTITUTIONS[X] is non-empty
  %if X = Y%           - emit body if SUBSTITUTIONS[X] == Y (literal)
  %else%               - inverse branch
  %endif%              - close conditional
  %_sys_*%             - Aruba Central system-injected content; we skip

Why render into a fixture instead of using the template directly?
  Real-capture validation's whole premise is that we exercise grammar
  the codec author didn't anticipate.  A raw template with %variable%
  tokens crashes our parser AND isn't representative of a deployed
  switch.  Rendering it with defensible values turns it into the kind
  of config a real stack would actually carry, using Aruba's own
  chosen idioms.

Provenance chain for the resulting fixture:
    Aruba's template (BSD-licensed)
        -> this script (in-tree, inspectable)
        -> tests/fixtures/real/aruba_aoss/aruba_central_5memberstack_rendered.cfg

DO-BETTER NOTE: swap this for a real sanitised AOS-S capture if/when
one becomes available (see tests/fixtures/real/aruba_aoss/README.md).
A rendered template is still, fundamentally, using grammar I've seen —
a real capture would exercise stuff the Aruba template author also
didn't anticipate, which is strictly more valuable.

Usage:
    python scripts/render_aruba_central_template.py  \\
        --template path/to/5memberStack.txt          \\
        --output tests/fixtures/real/aruba_aoss/aruba_central_5memberstack_rendered.cfg
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Substitution values
# ---------------------------------------------------------------------------

# Defensible "representative small office" values.  Goal: exercise as many
# grammar corners as possible (not minimize).  IPs are RFC1918, names are
# non-identifying.
SUBSTITUTIONS: dict[str, str] = {
    # System
    "hostname": "sw-demo-01",
    "_motd": "Authorized use only.",
    "syslog.server": "192.168.10.4",
    "dfgw": "192.168.10.1",
    "dns": "192.168.10.4",

    # Static routes — test the 3 slots
    "static.route.1": "172.16.0.0/12 192.168.10.1",
    "static.route.2": "10.0.0.0/8 192.168.10.1",
    # leave static.route.3 blank to also exercise the false branch

    # STP
    "stp.config.name": "demo-stp",
    "stp.prio": "4",

    # VLAN 1 (primary/management)
    "vlan.1.dhcp": "0",          # "0" = static IP on vlan 1
    "vlan.1.ip": "192.168.10.2/24",
    "vlan.1.untagged": "1/1-1/24",
    "_prim.vlan": "10",
    "_mgmt.vlan": "10",

    # Secondary VLAN (users)
    "vlan.2nd": "20",
    "vlan.2nd.name": "USERS",
    "vlan.2nd.ip": "192.168.20.1/24",
    "vlan.2nd.untagged": "1/1-1/12",
    "vlan.2nd.tagged": "1/25-1/26",

    # Tertiary VLAN (voice)
    "vlan.3rd": "30",
    "vlan.3rd.name": "VOICE",
    "vlan.3rd.ip": "192.168.30.1/24",
    "vlan.3rd.untagged": "1/13-1/24",

    # Trunks (LAG)
    "_trunk.1": "1/25-1/26",
    "_trunk.2": "",               # leave blank — exercise false branch

    # Aruba AP profile tagged VLANs
    "ap.prof.tagged.vlans": "20,30",

    # Stack members — only member 1 populated with 48 ports.
    # Template inconsistency: uses both `member.1.ports` (no underscore)
    # and `_member.N.ports` (with underscore) — populate both forms.
    "member.1.ports": "48",
    "_member.1.ports": "48",
    "_member.2.ports": "",         # leave false to exercise else
    "_member.3.ports": "",
    "_member.4.ports": "",
    "_member.5.ports": "",

    # FlexNetwork SKU check (J### module identifiers)
    "flex.a.member.1": "JL078A",
    "flex.a.member.2": "",
    "flex.a.member.3": "",
    "flex.a.member.4": "",
    "flex.a.member.5": "",

    # Port names — populate a few to exercise the path, leave most blank
    "interface.1_1.name": "Desk-A",
    "interface.1_2.name": "Desk-B",
    "interface.1_25.name": "UPLINK",
    "interface.1_26.name": "UPLINK",
    # All others: empty (default)

    # PoE — explicit disable on a few to exercise the branch
    "interface.1_3.poe": "0",
    "interface.1_4.poe": "0",

    # Port states — disable a few to exercise the branch
    "interface.1_47.state": "disable",
    "interface.1_48.state": "disable",
}


# Default: unset/empty/falsy.  Any %variable% not in SUBSTITUTIONS falls
# back to empty string; any %if variable% where variable is empty takes
# the false branch.
def lookup(var: str) -> str:
    return SUBSTITUTIONS.get(var, "")


# ---------------------------------------------------------------------------
# Parser for the template syntax
# ---------------------------------------------------------------------------

# Matches `%if VAR%` or `%if VAR = VALUE%`
_IF_RE = re.compile(r"^\s*%if\s+([^%=]+?)(?:\s*=\s*([^%]+?))?\s*%\s*$")
_ELSE_RE = re.compile(r"^\s*%else%\s*$")
_ENDIF_RE = re.compile(r"^\s*%endif%\s*$")

# Matches inline `%variable%` references.  Limited to var-name chars so
# it doesn't greedily swallow `%if X%`-style directives when they share
# a line (which the template does not do, but defensive is cheap).
_VAR_RE = re.compile(r"%([a-zA-Z0-9_.]+)%")

# Aruba Central system-injected markers we skip entirely.  These would
# be replaced by Central at provisioning time with group-level config;
# for a standalone rendered fixture we emit nothing in their place.
_SYS_MARKER_RE = re.compile(r"^\s*%_sys_[a-zA-Z0-9_]+%\s*$")


def evaluate_condition(var: str, expected: str | None) -> bool:
    """Decide whether an %if ...% block's body should be emitted."""
    value = lookup(var.strip())
    if expected is None:
        # `%if X%` — truthy iff non-empty.
        return bool(value)
    # `%if X = Y%` — literal equality, whitespace-trimmed.
    return value.strip() == expected.strip()


def substitute_inline(line: str) -> str:
    """Replace every `%variable%` on this line with its lookup value."""
    return _VAR_RE.sub(lambda m: lookup(m.group(1)), line)


# AOS-S keywords that ONLY make sense at column 0 (top-level stanzas,
# global-scope directives).  The Aruba Central template uses nested
# `%if%` blocks that propagate their indentation into the rendered
# output, which produces e.g. "   vlan 20" instead of "vlan 20".  Real
# AOS-S config pushed by Central strips that indentation before commit.
# We do the same as a post-pass.
_TOPLEVEL_KEYWORDS = re.compile(
    r"^\s+("
    r"hostname|vlan|interface|trunk|snmp-server|snmpv3|banner|no|"
    r"spanning-tree|ip|password|timesync|ntp|sntp|logging|"
    r"include-credentials|device-profile|mac-delimiter|module|"
    r"stacking|aaa|qos|lldp|dhcp|management-vlan|primary-vlan|"
    r"tftp|autorun|cwmp"
    r")\s"
)


def _dedent_top_level_stanzas(rendered: str) -> str:
    """Strip leading whitespace from any line that starts with a
    recognised AOS-S top-level keyword.  Preserves indentation inside
    multi-line stanza bodies (those lines don't start with a top-level
    keyword)."""
    out: list[str] = []
    for line in rendered.splitlines():
        if _TOPLEVEL_KEYWORDS.match(line):
            out.append(line.lstrip())
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def render(template_text: str) -> str:
    """Walk the template, emitting a concrete AOS-S config.

    Uses a stack of booleans — one per active %if% — where each bool
    tracks whether we're currently emitting.  A block's emission state
    is the AND of every enclosing block's state.
    """
    out_lines: list[str] = []
    # Stack entries: {"emit": bool, "took_branch": bool}
    # `emit` = are we currently emitting THIS branch?
    # `took_branch` = has EITHER branch in this conditional been active?
    #    (used to ensure %else% inverts correctly when the if-branch was
    #    already false)
    stack: list[dict[str, bool]] = []

    def currently_emitting() -> bool:
        return all(frame["emit"] for frame in stack)

    for raw_line in template_text.splitlines():
        # `%endif%`
        if _ENDIF_RE.match(raw_line):
            if not stack:
                raise ValueError(
                    f"unbalanced %endif%: {raw_line!r}"
                )
            stack.pop()
            continue

        # `%else%`
        if _ELSE_RE.match(raw_line):
            if not stack:
                raise ValueError(
                    f"unbalanced %else%: {raw_line!r}"
                )
            frame = stack[-1]
            # Only invert if the current branch WAS emitting — otherwise
            # the else path is still gated by an outer false block.
            # Simpler model: the else branch emits iff the if branch
            # did NOT emit (at this level).
            frame["emit"] = not frame["took_branch"]
            # Don't set took_branch here; it stays what it was.
            continue

        # `%if X%` or `%if X = Y%`
        m_if = _IF_RE.match(raw_line)
        if m_if:
            # Always push a frame, but only evaluate the condition if
            # our enclosing block is emitting (otherwise this whole
            # conditional is dead code).
            parent_emitting = currently_emitting()
            cond = evaluate_condition(m_if.group(1), m_if.group(2))
            take = parent_emitting and cond
            stack.append({"emit": take, "took_branch": take})
            continue

        # Non-directive line — skip if we're in a non-emitting branch.
        if not currently_emitting():
            continue

        # Aruba Central system-injected markers — skip silently.
        if _SYS_MARKER_RE.match(raw_line):
            continue

        # Substitute inline %vars%.
        out_line = substitute_inline(raw_line)

        # If substitution turned the whole line into whitespace, drop it.
        # (Happens for lines like `     %interface.1_5.name%` where the
        # variable is empty.)
        if not out_line.strip():
            continue

        out_lines.append(out_line)

    if stack:
        # The upstream Aruba template has a known off-by-one: 1462 %if%
        # vs. 1461 %endif% (checked against the master branch at time
        # of writing).  Rather than crash on a third-party bug, emit a
        # warning and auto-close — still lets us render a useful
        # fixture.  The only risk is that the tail of the file falls
        # into a branch that was meant to be conditional; in practice
        # that's fine since we're picking defensible substitutions.
        print(
            f"warning: template ended with {len(stack)} unclosed %if% block(s); "
            f"auto-closing for best-effort render.",
            file=sys.stderr,
        )

    # Ensure exactly one trailing newline.
    rendered = "\n".join(out_lines) + "\n"

    # Dedent top-level stanzas that got indented by enclosing %if% blocks.
    rendered = _dedent_top_level_stanzas(rendered)

    return rendered


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template", type=Path, required=True,
        help="path to 5memberStack - Template.txt downloaded from the "
             "aruba/central-sample-bulk-configurations repo",
    )
    parser.add_argument(
        "--output", type=Path, required=True,
        help="destination path for the rendered AOS-S config",
    )
    parser.add_argument(
        "--banner", action="store_true", default=True,
        help="prepend an AOS-S-style banner to the rendered file "
             "(makes provenance obvious to anyone who opens it)",
    )
    args = parser.parse_args(argv)

    template_text = args.template.read_text(encoding="utf-8", errors="replace")
    rendered = render(template_text)

    if args.banner:
        banner = (
            "; Rendered from aruba/central-sample-bulk-configurations\n"
            "; 5MemberStack template by scripts/render_aruba_central_template.py\n"
            "; Values are defensible defaults, not a real deployment.\n"
            "; J9729A Configuration Editor; Created via template render\n"
            "\n"
        )
        rendered = banner + rendered

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {args.output} ({len(rendered.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
