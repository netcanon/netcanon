"""
FortiGate CLI parser — recursive block model + per-stanza dispatch.

Extracted from ``codec.py`` during the parse/render split.  Everything
that consumes FortiOS text and produces a ``CanonicalIntent`` lives
here; ``render.py`` holds the reverse path.  ``codec.py`` is now a
thin class that delegates ``parse()`` and ``render()`` to module-level
functions here and in the sibling render module.

Public surface (consumed by codec.py's ``parse()`` method):

* :func:`parse_intent` — one-shot parse entry: raw text in, fully-
  populated :class:`CanonicalIntent` out.
* :func:`without_quoted_values` — the text with the lines of every
  quoted value of several lines emptied, each line keeping its number;
  what the Tier-3 detection and the release are read from.
* ``UNENDED_VALUE_MESSAGE`` — the refusal for a quoted value no later
  line ends.

A statement is read whole, up to the line whose quote no backslash
escapes (:func:`_statements`), so no line of a quoted value -- a
certificate, a key, a replacement message's HTML -- is a statement of
its own.

A static route printed with no ``set dst`` is a default route (the
default FortiOS's ``show`` leaves out), and a route the tree cannot
hold -- disabled, of a VRF other than 0, a blackhole, to an address
object, with a gateway learned from DHCP or PPP, or with neither a
gateway nor a device -- is left out and said (:class:`_RoutesNotHeld`).

An interface in a VRF other than 0 (``set vrf <id>``) keeps its
record, and its addresses, its DHCP client, its VRRP groups, the
DHCP pools on it and the routes out it are left out and said
(:func:`_out_of_their_vrf`): the parser reads no VRF, and in the
global table of the output they would route traffic the source
keeps apart.

Wave B: also handles **VRRP groups** nested as ``config vrrp /
edit N / set vrip X / set priority / set preempt / set adv-interval
/ set status / set authentication / next / end`` inside the
per-interface ``config system interface / edit <name>`` body.
Each ``edit <vrid>`` materialises a :class:`CanonicalVRRPGroup`
attached to the parent :class:`CanonicalInterface`.

Internal block model (still importable as ``_parse_blocks`` /
``_prefix_to_mask`` / ``_mask_to_prefix`` for tests that pin the
parser's structural contract):

* :class:`_ConfigBlock` + :class:`_EditBlock` — two-tier container
  model reflecting FortiOS's ``config / edit / set / next / end``
  5-keyword grammar.
* :func:`_parse_blocks` — recursive tokeniser producing a list of
  top-level ``_ConfigBlock`` instances.
* ``_apply_<path>`` functions — one per supported ``config <path>``
  stanza; each mutates the passed-in ``CanonicalIntent`` in-place.

IP mask utilities (shared with the render module):

* :func:`_prefix_to_mask`, :func:`_mask_to_prefix`, :func:`_split_cidr`.

The constants ``_FORTIGATE_LACP_TO_CANONICAL`` + the canonical-to-
FortiGate inverse live here (parse consumes the forward map; render
imports the inverse).  Keeping them together next to the parse
logic avoids the circular-import hazard of splitting them across
both modules.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import shlex
from collections.abc import Collection, Iterator
from typing import ClassVar

from ..._bonds import ACTIVE_BACKUP
from ..._radius_secrets import FORTIOS_ENVELOPE
from ..._tier3_detection import left_out_rows
from ...canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalIPv6Address,
    CanonicalLAG,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalStaticRoute,
    CanonicalVlan,
    CanonicalVRRPGroup,
)
from ...limits import ticked
from .._helpers import _mask_to_prefix, a_few_named, a_tag
from .._helpers import _prefix_to_mask as _shared_prefix_to_mask
from .._input_shape import detect_input_shape
from .._scanner import Body, without_text_bodies
from ..base import ParseError
from .dhcp_pools import pools_of
from .port_names import classify_port_name
from .vlan_heuristics import infer_iface_type as _infer_iface_type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IP helpers (shared with render.py)
# ---------------------------------------------------------------------------


def _prefix_to_mask(prefix: int) -> str:
    """Convert CIDR prefix length to dotted-decimal mask.

    Thin fortigate-vendor binding over
    :func:`netcanon.migration.codecs._helpers._prefix_to_mask` so the
    dotted-mask range-check + math have a single home (run3
    ``duplicated-prefix-to-mask-fortigate``).  Kept as a no-arg shim so
    the render-side call sites + ``_split_cidr`` API stay stable; raises
    the same :class:`RenderError` on an out-of-range prefix.
    """
    return _shared_prefix_to_mask(prefix, vendor="fortigate_cli")


def _split_cidr(destination: str) -> tuple[str, int]:
    """Accept ``A.B.C.D/N`` OR ``A.B.C.D`` (implicit /32)."""
    if "/" in destination:
        ip, prefix = destination.split("/", 1)
        return ip, int(prefix)
    return destination, 32


def _is_unset_address(ip: str) -> bool:
    """Is this FortiOS's "no address configured" sentinel rather than an address?

    An unconfigured FortiOS interface carries ``set ip 0.0.0.0 0.0.0.0``.  No
    interface can legitimately hold ``0.0.0.0``, so the value is unambiguous
    whatever mask accompanies it, and treating it as real produced
    ``ip address 0.0.0.0/0`` in every target render — rejected by EOS / NX-OS
    / IOS-XE, meaningless on IOS-XR and Junos.

    Deliberately narrow: only the all-zeros host. ``0.0.0.0/0`` as a static
    route DESTINATION is a real default route and is parsed elsewhere
    (:func:`_split_cidr`); this helper must never be applied there.
    """
    return ip.strip() == "0.0.0.0"


# ---------------------------------------------------------------------------
# LACP-mode mapping (parse uses forward; render imports the inverse)
# ---------------------------------------------------------------------------


_FORTIGATE_LACP_TO_CANONICAL = {
    "active": "active",
    "passive": "passive",
    "static": "static",
}
_CANONICAL_MODE_TO_FORTIGATE_LACP = {
    "active": "active",
    "passive": "passive",
    "static": "static",
}
# A bond whose peer needs no aggregate (``active-backup``,
# netcanon.migration._bonds) is no aggregate here: it is a redundant
# interface, in which "traffic only goes over one interface at any
# time" (Fortinet, FortiOS Administration Guide, "Aggregation and
# redundancy").  ``set type redundant`` is read as that LAG and the
# renderer writes it back.


# ---------------------------------------------------------------------------
# Block model
# ---------------------------------------------------------------------------


class _ConfigBlock:
    """One ``config <path> ... end`` block, possibly with ``edit``s.

    May also contain nested ``config`` sub-blocks directly (e.g.
    ``config ntpserver`` inside ``config system ntp``).  Most FortiOS
    sub-tables nest inside an ``edit`` entry, but a few live at the
    config level.
    """

    def __init__(self, config_path: str) -> None:
        self.config_path: str = config_path
        self.settings: dict[str, list[str]] = {}
        self.edits: list[_EditBlock] = []
        # Nested config-subtables at the config level.
        self.sub_blocks: list[_ConfigBlock] = []


class _EditBlock:
    """One ``edit <id> ... next`` entry inside a ``config`` block."""

    def __init__(self, edit_id: str) -> None:
        self.edit_id: str = edit_id
        self.settings: dict[str, list[str]] = {}
        # Nested config-subtables (e.g. per-policy sub-tables).
        self.sub_blocks: list[_ConfigBlock] = []


#: ``(\S.*)`` (greedy-to-EOL, anchored on a non-space) NOT ``(.+?)\s*$``:
#: a lazy body whose class overlaps the trailing ``\s*$`` backtracks O(n^2)
#: on ``config <x><run of spaces><non-space>`` (the #337 ReDoS shape).  The
#: consumers ``.strip()`` the capture, so dropping the trailing trim from the
#: pattern is behaviour-identical.
_CONFIG_HEADER_RE = re.compile(r"^config\s+(\S.*)$", re.IGNORECASE)
_EDIT_HEADER_RE = re.compile(r"^edit\s+(\S.*)$", re.IGNORECASE)
#: ``re.DOTALL``: a statement whose quoted value runs over several lines
#: (:func:`_statements`) is one ``set``, its line breaks inside the value.
_SET_RE = re.compile(r"^set\s+(\S+)\s*(.*)$", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"^\s*#")
#: A double quote, or an escape: a backslash and the character after it,
#: which is never a quote that opens or ends a value (``\"``, ``\\``).
_QUOTE_OR_ESCAPE = re.compile(r'\\.|"')

#: Said of a quoted value that no later line ends.  It quotes nothing of
#: the text: a parse failure is logged.
UNENDED_VALUE_MESSAGE = (
    "fortigate_cli: line {line} opens a quoted value that no later line "
    "ends, so where the value ends, and where the configuration goes on, "
    "cannot be told.  Paste the configuration whole, as the FortiGate "
    "prints it (a backup file, or the output of `show`)."
)


def _quotes(line: str) -> int:
    """How many double quotes of *line* open or end a quoted value.

    A line with no backslash holds no escape, and its quotes are
    counted as they stand: the pattern is for the other lines, and
    every line of a config is asked, twice.
    """
    if "\\" not in line:
        return line.count('"')
    return sum(1 for m in _QUOTE_OR_ESCAPE.finditer(line) if m.group() == '"')


def _leaves_a_value_open(line: str) -> bool:
    """Does *line* open a quoted value that runs on over later lines?

    FortiOS prints a value of several lines -- a replacement message's
    HTML, a certificate, a key, as the captures show -- as it is,
    between its quotes, a quote or a backslash in it escaped with a
    backslash.  A ``#`` line is a comment, whatever it holds.
    """
    return _quotes(line) % 2 == 1 and not _COMMENT_RE.match(line)


def _opens_a_quoted_value(text: str, number: int) -> Body | None:
    """``opens`` for :func:`without_text_bodies`: a quoted value that
    runs on is text, and ends with the line that ends its quote."""
    if not _leaves_a_value_open(text):
        return None
    return Body(ends=lambda line, number: _quotes(line) % 2 == 1)


def without_quoted_values(raw: str) -> str:
    """*raw* with every line of a quoted value that runs over several
    lines made empty, each line keeping its number: what the readers of
    the text other than :func:`_parse_blocks` read.

    A line of a replacement message or a certificate is text, never a
    stanza: read as one, ``config firewall policy`` in an HTML page was
    a row of firewall policies the config did not have.

    Raises:
        ParseError: A quoted value is still open at the end of the text
            (:data:`UNENDED_VALUE_MESSAGE`).
    """
    return without_text_bodies(
        raw, _opens_a_quoted_value, UNENDED_VALUE_MESSAGE,
        codec="fortigate_cli", command="show",
    )


def _statements(raw: str) -> Iterator[str]:
    """Each statement of *raw*: a line, or a line whose quoted value runs
    on, with the lines up to the one that ends the value, joined by line
    feeds.

    Read a line at a time, a line of a value is a statement of its own:
    a replacement message that held ``config system admin`` and ``edit``
    was an administrator, and a line of one that read ``end`` closed the
    block it was in.  Where a value ends is decided as in
    :func:`without_quoted_values`, which refuses a value no line ends --
    and is read first.
    """
    # One iterator, which both loops take lines from.
    lines = iter(raw.splitlines())
    for line in ticked(lines):
        if not _leaves_a_value_open(line):
            yield line
            continue
        pieces = [line]
        for more in ticked(lines):
            pieces.append(more)
            if _quotes(more) % 2 == 1:
                break
        yield "\n".join(pieces)


#: FortiOS release from the ``#config-version`` header, e.g.
#: ``#config-version=FG100E-7.2.13-FW-build1762-...`` → ``7.2.13``.  The
#: model token has no fixed length (FGT70G / FGVM64 / FG100E) but is always
#: alphanumeric, so ``[A-Za-z0-9]+`` matches it exactly up to the hyphen
#: delimiter — deliberately NOT ``\S+?`` (whose overlap with the ``-``
#: delimiter is a polynomial-ReDoS backtracking hazard on hostile input).
_VERSION_RE = re.compile(
    r"#config-version=[A-Za-z0-9]+-(\d+\.\d+\.\d+)", re.MULTILINE
)


def _extract_version(raw: str) -> str:
    """Return the FortiOS release from the ``#config-version`` header.

    Stored as :attr:`CanonicalIntent.source_version` (metadata only); the
    render path does not echo it, so it is informational.  Returns ``""``
    when the header is absent.
    """
    m = _VERSION_RE.search(raw)
    return m.group(1) if m else ""


def _tokenize_set(value: str) -> list[str]:
    """Split a ``set`` value into tokens, honouring quoted strings."""
    value = value.strip()
    if not value:
        return []
    try:
        return shlex.split(value, posix=True)
    except ValueError:
        # Unbalanced quote — fall back to whitespace split.
        return value.split()


def _edit_id(text: str) -> str:
    """The id of an ``edit`` line.

    FortiOS quotes a name as it quotes a ``set`` value, with ``\\`` the
    escape inside the quotes (``edit "a\\"b"`` is ``a"b``), so an id
    that is one token is read as :func:`_tokenize_set` reads a value.
    Anything else -- an unbalanced quote, words with no quotes round
    them -- keeps the old reading: the text, its outer quotes stripped.
    A name in quotes with no escape in it, and an id with no quote and
    no white space, are read without shlex, which makes the same of
    them: every ``edit`` line of a config is read here.
    """
    if "\\" not in text and "'" not in text:
        if len(text) > 1 and text[0] == '"' == text[-1] and text.count('"') == 2:
            return text[1:-1]
        if '"' not in text and not any(c in " \t\r\n" for c in text):
            return text
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = []
    if len(tokens) == 1:
        return tokens[0]
    return text.strip().strip('"').strip("'")


def _parse_blocks(raw: str) -> list[_ConfigBlock]:
    """Parse a FortiOS CLI text into a list of top-level ``config`` blocks.

    Nested ``config`` blocks inside an ``edit`` attach to the
    enclosing :class:`_EditBlock.sub_blocks`; otherwise they become
    new top-level entries.
    """
    blocks: list[_ConfigBlock] = []

    # Stack of "open containers" — either ``_ConfigBlock`` or
    # ``_EditBlock``.  Top of stack is the one receiving new tokens.
    stack: list[_ConfigBlock | _EditBlock] = []

    for raw_line in _statements(raw):
        line = raw_line.strip()
        if not line or _COMMENT_RE.match(line):
            continue

        # Stanza terminators.
        if line == "end":
            # Pop everything up to and including the innermost
            # ``_ConfigBlock``.  Spurious extra ``end`` tokens are
            # tolerated silently — real FortiOS exports are
            # well-formed, but misbehaved-input resilience is cheap.
            while stack:
                top = stack.pop()
                if isinstance(top, _ConfigBlock):
                    if not stack:
                        blocks.append(top)
                    else:
                        parent = stack[-1]
                        # Nested config attaches to whichever enclosing
                        # container has a ``sub_blocks`` list — both
                        # _EditBlock and _ConfigBlock do.
                        parent.sub_blocks.append(top)
                    break
            continue
        if line == "next":
            # Pop the innermost ``_EditBlock``, re-attach to its
            # enclosing ``_ConfigBlock``.
            while stack:
                top = stack.pop()
                if isinstance(top, _EditBlock):
                    if stack and isinstance(stack[-1], _ConfigBlock):
                        stack[-1].edits.append(top)
                    break
            continue

        cm = _CONFIG_HEADER_RE.match(line)
        if cm:
            path = cm.group(1).strip().strip('"').strip("'")
            stack.append(_ConfigBlock(config_path=path))
            continue

        em = _EDIT_HEADER_RE.match(line)
        if em:
            edit_id = _edit_id(em.group(1))
            stack.append(_EditBlock(edit_id=edit_id))
            continue

        sm = _SET_RE.match(line)
        if sm and stack:
            key = sm.group(1).strip()
            tokens = _tokenize_set(sm.group(2))
            stack[-1].settings[key] = tokens

    # Any unclosed containers at EOF — best-effort rescue.
    while stack:
        top = stack.pop()
        if isinstance(top, _ConfigBlock) and not stack:
            blocks.append(top)

    return blocks


# ---------------------------------------------------------------------------
# Per-stanza dispatchers — one ``_apply_<path>`` per supported
# ``config <path>`` at the top level.
# ---------------------------------------------------------------------------


def _apply_system_global(block: _ConfigBlock, intent: CanonicalIntent) -> None:
    hostname = block.settings.get("hostname")
    if hostname:
        intent.hostname = hostname[0]


#: The resolver slots of ``config system dns`` by the address family
#: each takes, in the order the tree keeps them: ``primary`` and
#: ``secondary`` take an IPv4 address, ``ip6-primary`` and
#: ``ip6-secondary`` an IPv6 one (Fortinet's CLI reference, 7.6.6).
#: ``alt-primary`` and ``alt-secondary`` are not read: the reference
#: says neither is "used as a failover DNS server".
RESOLVER_SLOTS: dict[int, tuple[str, str]] = {
    4: ("primary", "secondary"),
    6: ("ip6-primary", "ip6-secondary"),
}


def names_a_resolver(value: str) -> bool:
    """Whether a resolver slot holding *value* names a resolver: any
    value but the unspecified address, which is the slot's default
    (``0.0.0.0``, ``::``) and how a printout of the whole configuration
    says that it holds none.  A value that is no address is kept as it
    stands, for the target's renderer to write or to leave out."""
    try:
        return not ipaddress.ip_address(value).is_unspecified
    except ValueError:
        return True


def _apply_system_dns(block: _ConfigBlock, intent: CanonicalIntent) -> None:
    for slots in RESOLVER_SLOTS.values():
        for slot in slots:
            value = block.settings.get(slot)
            if value and names_a_resolver(value[0]):
                intent.dns_servers.append(value[0])
    # ``set domain "<fqdn>"`` is the FortiOS-native domain-name form
    # inside ``config system dns`` (mirrors render emit at
    # ``fortigate_cli/render.py`` ~line 450).  Without this read the
    # renderer-emitted line was silently dropped on parse, breaking
    # round-trip ``parse(render(tree))`` for ``CanonicalIntent.domain``
    # (Phase 4b finding flagged by 3 agents — arista_eos, opnsense,
    # cisco_iosxe_cli source-side).  A DHCP pool's ``set domain``
    # (read in ``dhcp_pools.py``) targets a different field
    # (``CanonicalDHCPPool.domain_name``, the per-pool search domain)
    # and remains unchanged.
    domain = block.settings.get("domain")
    if domain:
        intent.domain = domain[0]


def _apply_system_ntp(block: _ConfigBlock, intent: CanonicalIntent) -> None:
    for sub in block.sub_blocks:
        if sub.config_path != "ntpserver":
            continue
        for edit in sub.edits:
            server = edit.settings.get("server")
            if server:
                intent.ntp_servers.append(server[0])


def _apply_system_interface(  # noqa: C901
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    # Name -> interface index for O(1) LAG member reverse-linking.  Holds
    # exactly the interfaces appended so far (the current ``iface`` is added
    # at the end of each iteration), mirroring the previously-appended set the
    # old ``for prev in intent.interfaces`` scan saw — but O(1) instead of the
    # O(members x interfaces) quadratic that pinned a worker on adversarial
    # thousand-aggregate inputs (2026-07-06 review MEDIUM #30).
    iface_by_name: dict[str, CanonicalInterface] = {}
    for edit in ticked(block.edits):
        name = edit.edit_id
        iface = CanonicalInterface(name=name, enabled=True)

        alias = edit.settings.get("alias")
        if alias:
            iface.description = alias[0]

        status = edit.settings.get("status")
        if status:
            # FortiOS uses "up" / "down" for interface admin status.
            iface.enabled = status[0].lower() == "up"

        mtu_tokens = edit.settings.get("mtu")
        if mtu_tokens:
            try:
                iface.mtu = int(mtu_tokens[0])
            except ValueError:
                pass
        # FortiOS uses `set mtu-override enable` + `set mtu N` — we
        # capture mtu regardless; the override flag is not canonically
        # modelled.

        ip_tokens = edit.settings.get("ip")
        if ip_tokens and len(ip_tokens) >= 2:
            ip, mask = ip_tokens[0], ip_tokens[1]
            # ``set ip 0.0.0.0 0.0.0.0`` is FortiOS's "no address
            # configured" encoding — the default an unconfigured interface
            # carries — NOT an address.  Taking it literally produced
            # ``ip address 0.0.0.0/0`` on 18 interfaces of one capture,
            # which EOS / NX-OS / IOS-XE reject outright and which is
            # meaningless on IOS-XR and Junos.  No interface can legitimately
            # hold 0.0.0.0, so the sentinel is unambiguous and is skipped
            # whatever mask accompanies it.
            if not _is_unset_address(ip):
                iface.ipv4_addresses.append(CanonicalIPv4Address(
                    ip=ip,
                    prefix_length=_mask_to_prefix(
                        mask, vendor="fortigate_cli",
                    ),
                ))

        # ``set mode {static | dhcp | pppoe}``: with ``dhcp`` the
        # interface takes its IPv4 address from a DHCP server -- the line
        # the renderer writes for ``dhcp_client``, read back.  ``static``
        # is the default; ``pppoe`` is not modelled.
        mode_tokens = edit.settings.get("mode")
        if mode_tokens and mode_tokens[0].lower().strip('"') == "dhcp":
            iface.dhcp_client = True

        # Additional interface IPs live in a nested ``config secondaryip``
        # sub-table (``set secondary-IP enable`` gates it).  Without this
        # every secondary subnet vanishes on parse — a whole-subnet
        # reachability loss (promotion #3).  Harvest each ``set ip <ip>
        # <mask>`` onto a secondary CanonicalIPv4Address.
        for sub in edit.sub_blocks:
            if sub.config_path != "secondaryip":
                continue
            for sec in sub.edits:
                sec_tokens = sec.settings.get("ip")
                if (
                    sec_tokens
                    and len(sec_tokens) >= 2
                    and not _is_unset_address(sec_tokens[0])
                ):
                    iface.ipv4_addresses.append(CanonicalIPv4Address(
                        ip=sec_tokens[0],
                        prefix_length=_mask_to_prefix(
                            sec_tokens[1], vendor="fortigate_cli",
                        ),
                        is_secondary=True,
                    ))

        # IPv6 dynamic-address mode: ``set ip6-mode {static|dhcp|
        # delegated|pppoe}`` on FortiOS.  The ``dhcp`` value populates
        # the canonical ``dhcp_client_v6`` field.  Other modes
        # (``delegated`` is RFC 3633 prefix delegation, ``pppoe`` is
        # the LAC client) don't have a clean cross-vendor mapping and
        # are intentionally not surfaced here.  ``static`` is the
        # FortiOS default and means "no DHCPv6"; we don't populate
        # the field.
        # FortiOS 6.x puts ``set ip6-mode`` directly on the interface edit;
        # 7.x nests it under a ``config ipv6`` sub-block (same as
        # ``ip6-address`` below).  Read the direct form first, then the nested
        # block — without the nested fallback a 7.x DHCPv6 client was silently
        # dropped even though ``dhcp-client-v6`` is declared supported
        # (HEAD-review L1-7, the un-hardened sibling of the #345 ip6-address
        # nested harvest).
        ip6_mode_tokens = edit.settings.get("ip6-mode")
        if not (ip6_mode_tokens and ip6_mode_tokens[0]):
            for sub in edit.sub_blocks:
                if sub.config_path == "ipv6":
                    ip6_mode_tokens = sub.settings.get("ip6-mode")
                    break
        if ip6_mode_tokens and ip6_mode_tokens[0]:
            mode_value = ip6_mode_tokens[0].lower().strip('"')
            if mode_value == "dhcp":
                iface.dhcp_client_v6 = "dhcp6"

        # GAP-EVPN-3: ``set ip6-address <addr>/<prefix>`` (CIDR form,
        # FortiOS native).  ``set ip6-address ::/0`` is "no IPv6
        # address" — drop the all-zero placeholder rather than emit
        # a canonical record for it.
        #
        # FortiOS 6.x puts ``set ip6-address`` directly on the interface
        # edit; FortiOS 7.x nests it under a ``config ipv6`` sub-block
        # (``edit port1 / config ipv6 / set ip6-address .../64 / end``).
        # Read the direct form first, then the nested block if the direct
        # form was absent — a real config carries the address in exactly
        # one place, so this never double-appends (promotion #2: the path
        # is declared supported, so a dropped nested address was a
        # fail-open silent loss).  Nested ``ip6-mode`` gets the identical
        # direct-then-nested treatment above (HEAD-review L1-7).
        ip6_tokens = edit.settings.get("ip6-address")
        if not (ip6_tokens and ip6_tokens[0]):
            for sub in edit.sub_blocks:
                if sub.config_path == "ipv6":
                    ip6_tokens = sub.settings.get("ip6-address")
                    break
        if ip6_tokens and ip6_tokens[0]:
            v6_token = ip6_tokens[0]
            if "/" in v6_token:
                ip_part, prefix_str = v6_token.split("/", 1)
                # Filter the FortiOS placeholder ``::/0`` (semantic
                # "no v6 address" — every interface in the corpus
                # carries this default and treating it as a real
                # address would flood the canonical tree).
                if ip_part not in ("::", "0::"):
                    try:
                        iface.ipv6_addresses.append(CanonicalIPv6Address(
                            ip=ip_part,
                            prefix_length=int(prefix_str),
                            scope="global",
                        ))
                    except ValueError:
                        pass

        iface_type = edit.settings.get("type")
        vlanid = edit.settings.get("vlanid")
        parent_iface = edit.settings.get("interface")
        member_tokens = edit.settings.get("member")
        type_value = iface_type[0].lower() if iface_type else ""

        # Real FortiOS configs often omit `set type vlan`, leaving
        # vlanid + interface (parent) as the only VLAN signals.  Treat
        # either form as a VLAN subinterface.  Surfaced by
        # KevinGuenay/fortinet-resources FGT-70G-BRANCH.conf: VL_100
        # has no `set type` line but carries vlanid=100 /
        # interface=LAG_INTERNAL and is unambiguously a VLAN iface.
        looks_like_vlan = (
            type_value == "vlan"
            or (vlanid is not None and parent_iface is not None)
        )
        if looks_like_vlan and vlanid:
            iface.interface_type = "ianaift:l3ipvlan"
            # The interface the VLAN rides on, as the config states it:
            # without it the renderer chose one, and every VLAN of the
            # committed captures came back on another port -- a loopback
            # among them.
            if parent_iface and parent_iface[0]:
                iface.vlan_parent = parent_iface[0]
            try:
                vid = int(vlanid[0])
                # Use the iface name as the canonical VLAN name so the
                # render path can map the iface back to its VLAN id
                # via `_vlan_id_for`.  The alias (set via `set alias`)
                # is the one label FortiOS has for the VLAN and for its
                # interface: the description of both, as RouterOS's
                # `comment=` is.
                intent.vlans.append(CanonicalVlan(
                    id=vid, name=name, description=iface.description,
                ))
            except ValueError:
                pass
        elif type_value in ("aggregate", "redundant"):
            # LAG / 802.3ad bundle, or a redundant interface (one
            # member at a time: an active-backup bond).  Members
            # arrive as a space-separated token list on the `set
            # member` line.
            iface.interface_type = "ianaift:ieee8023adLag"
            members: list[str] = []
            if member_tokens:
                for tok in member_tokens:
                    members.extend(m for m in tok.split() if m)
            if type_value == "redundant":
                mode = ACTIVE_BACKUP
            else:
                lacp_mode = edit.settings.get("lacp-mode")
                mode = _FORTIGATE_LACP_TO_CANONICAL.get(
                    lacp_mode[0].lower() if lacp_mode else "active", "active"
                )
            intent.lags.append(CanonicalLAG(
                name=name,
                members=members,
                mode=mode,
            ))
            # Reverse-link on members we already know about.  Members
            # defined later in the same block will be wired up on the
            # second-pass below.  O(1) name lookup — see iface_by_name.
            for m in members:
                prev = iface_by_name.get(m)
                if prev is not None and prev.lag_member_of is None:
                    prev.lag_member_of = name
        elif type_value in _TYPE_IT_STATES:
            # A port, a loopback or a tunnel is what its ``set type``
            # says, whatever its name: FortiOS names a loopback or a
            # tunnel freely (Fortinet's own loopback is
            # ``Lo-BGP-RID``).  Read by the name's shape, a loopback
            # called ``port1.5`` was a port, and went as a unit of
            # ``port1``.
            iface.interface_type = _TYPE_IT_STATES[type_value]
        else:
            iface.interface_type = _infer_iface_type(name)

        # ── VRRP groups (Wave B) ──────────────────────────────────────
        # FortiOS nests VRRP groups inside a per-interface ``config vrrp``
        # sub-block, with one ``edit <vrid> ... next`` entry per group.
        # The block model parses this as ``_EditBlock.sub_blocks`` on the
        # interface's edit entry (path == ``vrrp``).  Mirrors the nested-
        # subtable handling already in use for DHCP ``config ip-range``
        # in ``dhcp_pools.py``.
        #
        # Mandatory key: ``set vrip <X>`` (the virtual IP).  Without it
        # the edit is malformed and we silently skip — real exports
        # always emit ``vrip`` because FortiOS rejects ``config vrrp``
        # edits that omit it.
        #
        # Optional v3 / opaque keys:
        #   * ``set vrip6 <X>``        -> appended to ``virtual_ipv6s``
        #   * ``set priority N``       -> ``priority`` (default 100)
        #   * ``set preempt enable``   -> ``preempt=True``
        #   * ``set adv-interval S``   -> ``advertisement_interval``
        #   * ``set authentication T`` -> ``authentication="plain:T"``
        #   * ``set vrdst <iface>``    -> appended to ``track_interfaces``
        #     (FortiOS "destination" tracking — semantically close to
        #     interface-state tracking on other vendors)
        #
        # FortiOS-specific knobs without canonical equivalent (vrgrp,
        # start-time, vrdst-priority, version, vrrp-virtual-mac) are
        # silently ignored — captured under the matrix's lossy notes.
        for sub in edit.sub_blocks:
            if sub.config_path != "vrrp":
                continue
            for vrrp_edit in sub.edits:
                try:
                    gid = int(vrrp_edit.edit_id)
                except ValueError:
                    continue
                if not (1 <= gid <= 255):
                    continue
                vrip_tokens = vrrp_edit.settings.get("vrip")
                if not vrip_tokens:
                    continue
                priority = 100
                priority_tokens = vrrp_edit.settings.get("priority")
                if priority_tokens:
                    try:
                        priority = int(priority_tokens[0])
                    except ValueError:
                        pass
                # FortiOS permits VRRP priority 1-255 (255 = the
                # address-owner master).  ``CanonicalVRRPGroup.priority`` now
                # spans the full 0-255 FHRP union, so a legitimate ``set
                # priority 255`` is preserved verbatim and round-trips.  The
                # [1, 255] clamp only guards against a malformed out-of-range
                # value (FortiOS never writes one) rather than raising.
                priority = max(1, min(priority, 255))
                preempt_tokens = vrrp_edit.settings.get("preempt")
                # FortiOS default for preempt is ``enable`` when the knob
                # is absent — matches the canonical default (``True``).
                preempt = (
                    preempt_tokens[0].lower() == "enable"
                    if preempt_tokens else True
                )
                adv_interval = 1
                adv_tokens = vrrp_edit.settings.get("adv-interval")
                if adv_tokens:
                    try:
                        adv_interval = int(adv_tokens[0])
                    except ValueError:
                        pass
                group = CanonicalVRRPGroup(
                    group_id=gid,
                    mode="vrrp",
                    virtual_ips=[vrip_tokens[0]],
                    priority=priority,
                    preempt=preempt,
                    advertisement_interval=adv_interval,
                )
                vrip6_tokens = vrrp_edit.settings.get("vrip6")
                if vrip6_tokens:
                    group.virtual_ipv6s.append(vrip6_tokens[0])
                auth_tokens = vrrp_edit.settings.get("authentication")
                if auth_tokens:
                    group.authentication = f"plain:{auth_tokens[0]}"
                vrdst_tokens = vrrp_edit.settings.get("vrdst")
                if vrdst_tokens:
                    # FortiOS allows a single vrdst per edit; preserve
                    # verbatim as one entry on ``track_interfaces``.
                    group.track_interfaces.append(vrdst_tokens[0])
                iface.vrrp_groups.append(group)

        intent.interfaces.append(iface)
        iface_by_name[name] = iface
    # A member defined AFTER its aggregate's edit is linked by
    # ``_link_lag_members``, once, when every block has been read.


def _link_lag_members(intent: CanonicalIntent) -> None:
    """Stamp ``lag_member_of`` on every member an aggregate names that
    the edit of the aggregate could not: one defined after it, or in
    another ``config system interface`` block.

    Run once, after every block.  It used to run at the end of each
    ``config system interface`` block, over every LAG and every
    interface the config had so far: a config with that block written
    N times read its own interfaces N times over.  Once at the end
    gives each interface the same answer -- the first LAG, in the
    order the config defines them, that names it, unless an edit
    already linked it -- because nothing reads the link in between.
    """
    lag_members: dict[str, str] = {}
    for lag in intent.lags:
        for m in lag.members:
            lag_members.setdefault(m, lag.name)
    have: set[str] = set()
    for iface in intent.interfaces:
        have.add(iface.name)
        if iface.lag_member_of is None and iface.name in lag_members:
            iface.lag_member_of = lag_members[iface.name]
    # A member that ``set member`` names and no ``edit`` of its own
    # configures -- a pasted fragment; FortiOS prints every port -- is
    # given the record an edit with nothing in it would make, so that
    # a target that writes a member from its record writes it.
    for m, lag_name in lag_members.items():
        if m not in have:
            intent.interfaces.append(
                CanonicalInterface(name=m, lag_member_of=lag_name),
            )


#: What an interface is typed, by the ``set type`` of its own edit,
#: where that type is one the tree has (a VLAN interface, an aggregate
#: and a redundant interface are read above).  Any other type --
#: ``switch``, ``vap-switch``, ``vdom-link`` and the like -- is typed
#: by the name's shape, as before.
_TYPE_IT_STATES = {
    "physical": "ianaift:ethernetCsmacd",
    "loopback": "ianaift:softwareLoopback",
    "tunnel": "ianaift:tunnel",
}

#: What a parent read as a port is typed, by the type its own edit
#: states.
_PORT_BY_STATED_TYPE = {
    "physical": "ianaift:ethernetCsmacd",
    "aggregate": "ianaift:ieee8023adLag",
    "redundant": "ianaift:ieee8023adLag",
}

#: What a parent read as a port is typed, by its name's kind, where
#: its edit states no type.
_PORT_BY_KIND = {
    "physical": "ianaift:ethernetCsmacd",
    "lag": "ianaift:ieee8023adLag",
}


def _a_vlan_on_a_port_is_a_sub_interface(
    blocks: list[_ConfigBlock], intent: CanonicalIntent,
) -> None:
    """A VLAN interface whose ``set interface`` is a port or an
    aggregate is a routed sub-interface of it.

    ``edit "VL_100"`` / ``set vlanid 100`` / ``set interface
    "LAG_INTERNAL"`` tags the frames of one interface on
    ``LAG_INTERNAL``, and only there: FortiOS takes the same VLAN id
    on another interface as another interface.  So its tag is its
    own (``dot1q_vlan``), it is typed as its parent is, and it makes
    no VLAN record -- the form a sub-interface has in the tree, from
    every parser that reads one.  Read as a VLAN interface, it was an
    SVI and a VLAN no port carried on every target that has the two:
    ``interface Vlan100`` on IOS-XE, ``irb.100`` on Junos, and nothing
    on the aggregate.

    The parent is a port where its own edit says ``set type
    physical``, and an aggregate where it says ``set type
    aggregate`` or ``set type redundant`` without ``set fortilink
    enable``.  A FortiLink
    aggregate carries the VLANs of the FortiSwitches it manages, and
    a hardware or software switch (``set type hard-switch``,
    ``switch``) carries VLANs as a bridge does: a VLAN interface on
    one stays a VLAN interface with its VLAN, and so does one on
    anything else.  One on a VLAN interface (``set vlanid``, whatever
    its name looks like) is a second tag, which
    :func:`_tags_with_no_form` leaves out.  Where the parent's edit states no type, or the
    config has no edit for it, its name decides
    (:func:`.port_names.classify_port_name`: ``port4``, ``wan1``, but
    not ``internal`` or ``lan``, which are switches, nor
    ``fortilink``, the FortiLink interface's own name, which the
    classifier reads as a port).  Decided after every block: an
    aggregate may be defined after the VLAN interfaces on it.
    """
    stated: dict[str, tuple[str, bool]] = {}
    for block in blocks:
        if block.config_path != "system interface":
            continue
        for edit in ticked(block.edits):
            kind = edit.settings.get("type")
            fortilink = edit.settings.get("fortilink")
            stated.setdefault(edit.edit_id, (
                "vlan" if "vlanid" in edit.settings
                else kind[0].lower() if kind else "",
                bool(fortilink) and fortilink[0].lower() == "enable",
            ))
    made: dict[str, list[CanonicalVlan]] = {}
    for vlan in intent.vlans:
        made.setdefault(vlan.name, []).append(vlan)
    taken_out: set[int] = set()
    for iface in ticked(intent.interfaces):
        parent = iface.vlan_parent
        if (
            iface.interface_type != "ianaift:l3ipvlan"
            or not parent or parent == iface.name
            or not made.get(iface.name)
        ):
            continue
        kind, fortilink = stated.get(parent, ("", False))
        if fortilink or (not kind and parent.lower() == "fortilink"):
            continue
        port_type = (
            _PORT_BY_STATED_TYPE.get(kind) if kind
            else _PORT_BY_KIND.get(classify_port_name(parent).kind)
        )
        if port_type is None:
            continue
        # The VLAN record its edit made, the one named after it.
        vlan = made[iface.name].pop(0)
        iface.interface_type = port_type
        iface.dot1q_vlan = vlan.id
        taken_out.add(id(vlan))
    if taken_out:
        intent.vlans = [vlan for vlan in intent.vlans if id(vlan) not in taken_out]


def _tags_with_no_form(blocks: list[_ConfigBlock], intent: CanonicalIntent) -> list[str]:
    """Leave out each VLAN interface whose tag the tree has no form
    for, and say which.

    The tree's tags are 802.1Q tags.  ``set vlan-protocol 8021ad``
    makes the VLAN interface's tag an 802.1ad service tag (FortiOS
    prints ``set vlan-protocol 8021q`` for one that is not), and a
    VLAN interface whose ``set interface`` is another VLAN interface
    is a second tag: "QinQ (802.1ad) allows multiple VLAN tags to be
    inserted into a single frame", the outer one a provider tag
    (Fortinet, FortiOS Administration Guide, "QinQ").  The guide
    shows the outer VLAN interface with ``set vlan-protocol 8021ad``
    and says nothing of one with ``8021q``: whether FortiOS sends two
    802.1Q tags there is not established.  Read as one tag, either
    was another interface on every target, in jobs that said
    ``completed``.  A ``set vlanid`` that is no VLAN id (0, 4095)
    made no VLAN, and its interface was one of no tag.  So each is
    left out -- with its VLAN record and
    its addresses, and a VLAN interface on one of them with it -- and
    a row for each reason names a few and counts the rest.  A route
    or a DHCP server that names it keeps the name, as one that names
    any interface the tree does not have does.

    Returns:
        The rows of ``dropped_tier3_sections``.
    """
    service: set[str] = set()
    tagged: set[str] = set()
    no_id: set[str] = set()
    for block in blocks:
        if block.config_path != "system interface":
            continue
        for edit in ticked(block.edits):
            if "vlanid" not in edit.settings:
                continue
            tagged.add(edit.edit_id)
            vlanid = edit.settings["vlanid"]
            if a_tag(vlanid[0] if vlanid else "") is None:
                no_id.add(edit.edit_id)
            protocol = edit.settings.get("vlan-protocol")
            if protocol and protocol[0].lower() == "8021ad":
                service.add(edit.edit_id)
    left_out: dict[str, list[str]] = {reason: [] for reason in _NO_FORM}
    for iface in ticked(intent.interfaces):
        if iface.name not in tagged or (
            iface.interface_type != "ianaift:l3ipvlan" and iface.dot1q_vlan is None
        ):
            continue
        if iface.name in no_id:
            left_out["id"].append(iface.name)
        elif iface.name in service:
            left_out["service"].append(iface.name)
        elif iface.vlan_parent in tagged and iface.vlan_parent != iface.name:
            left_out["stack"].append(iface.name)
    gone = {name for names in left_out.values() for name in names}
    if gone:
        intent.interfaces = [i for i in intent.interfaces if i.name not in gone]
        intent.vlans = [vlan for vlan in intent.vlans if vlan.name not in gone]
    return [
        f"config system interface edit {a_few_named(names)}: "
        f"{_NO_FORM[reason]}, so the interface is not translated"
        for reason, names in left_out.items() if names
    ]


#: Why a VLAN interface is left out (:func:`_tags_with_no_form`).
_NO_FORM = {
    "id": "set vlanid -- a number that is no VLAN id, 1 to 4094",
    "service": (
        "set vlan-protocol 8021ad -- an 802.1ad service tag, not an "
        "802.1Q tag"
    ),
    "stack": (
        "set interface <a VLAN interface> -- a second tag; FortiOS "
        "documents Q-in-Q with an 802.1ad outer tag, and two 802.1Q "
        "tags are not established"
    ),
}


def _apply_snmp_sysinfo(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system snmp sysinfo`` — contact + location + desc."""
    contact = block.settings.get("contact-info")
    location = block.settings.get("location")
    if contact or location:
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        if contact:
            intent.snmp.contact = contact[0]
        if location:
            intent.snmp.location = location[0]


def _apply_snmp_community(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system snmp community`` — community strings +
    trap host sub-tables."""
    for edit in ticked(block.edits):
        name = edit.settings.get("name")
        if not name:
            continue
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        if not intent.snmp.community:
            intent.snmp.community = name[0]
        # Nested hosts sub-block records trap targets.
        for sub in edit.sub_blocks:
            if sub.config_path != "hosts":
                continue
            for host_edit in sub.edits:
                ip_tokens = host_edit.settings.get("ip")
                if not ip_tokens:
                    continue
                # FortiOS writes `set ip "1.2.3.4 255.255.255.255"`
                # as a single quoted string — shlex keeps it together.
                # Split on whitespace to pull out just the IP.
                first_token = ip_tokens[0].split()[0]
                intent.snmp.trap_hosts.append(first_token)


def _apply_snmp_user(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system snmp user`` — SNMPv3 USM users.

    FortiOS grammar (7.0+ stable; 7.2+ keeps same knobs with added
    SHA-256/384/512 support):

    .. code-block:: text

        config system snmp user
            edit "netadmin"
                set security-level auth-priv
                set auth-proto sha256
                set auth-pwd ENC encrypted-hash-blob==
                set priv-proto aes256
                set priv-pwd ENC encrypted-hash-blob==
            next
        end

    FortiOS doesn't carry an explicit "group" surface — each user is
    self-grouped by its security-level.  ``group`` lands empty on
    canonical; renderers that require one (Cisco, Junos, Aruba)
    synthesise a default.

    The ``ENC`` prefix on password fields is FortiOS's encrypted-
    blob marker.  We carry it verbatim: shlex keeps ``ENC <hash>``
    together as one quoted string when the operator exported with
    quotes, or as two tokens otherwise.  Either shape round-trips
    because the renderer re-quotes on output.
    """
    for edit in ticked(block.edits):
        name_tokens = [edit.edit_id] if edit.edit_id else (
            edit.settings.get("name") or []
        )
        if not name_tokens:
            continue
        if intent.snmp is None:
            intent.snmp = CanonicalSNMP()
        name = name_tokens[0]
        from ...canonical.intent import CanonicalSNMPv3User
        # FortiOS auth-proto → canonical.
        _FG_AUTH_MAP = {
            "md5": "md5",
            "sha": "sha",
            "sha1": "sha",
            "sha224": "sha224",
            "sha256": "sha256",
            "sha384": "sha384",
            "sha512": "sha512",
        }
        # FortiOS priv-proto → canonical.  ``aes`` on older FOS =
        # AES-128; newer ``aes256`` / ``aes256cisco`` are distinct.
        _FG_PRIV_MAP = {
            "des": "des",
            "aes": "aes128",
            "aes128": "aes128",
            "aes192": "aes192",
            "aes256": "aes256",
            # ``aes256cisco`` is an interop mode — treat as aes256
            # on the canonical (lossy) and let operators re-key on
            # non-FortiGate targets.
            "aes256cisco": "aes256",
        }
        auth_proto_tokens = edit.settings.get("auth-proto") or [""]
        priv_proto_tokens = edit.settings.get("priv-proto") or [""]
        auth_proto = _FG_AUTH_MAP.get(
            auth_proto_tokens[0].lower(), "",
        )
        priv_proto = _FG_PRIV_MAP.get(
            priv_proto_tokens[0].lower(), "",
        )
        # FortiOS exports ``set auth-pwd ENC <hash>`` as two tokens
        # when unquoted, or a single quoted string when the operator
        # exported with `show full-configuration`.  Join with space
        # so the canonical passphrase carries the ``ENC`` marker
        # + hash verbatim, matching the local-user pattern above.
        auth_pwd_tokens = edit.settings.get("auth-pwd") or []
        priv_pwd_tokens = edit.settings.get("priv-pwd") or []
        auth_passphrase = " ".join(auth_pwd_tokens) if auth_pwd_tokens else ""
        priv_passphrase = " ".join(priv_pwd_tokens) if priv_pwd_tokens else ""
        intent.snmp.v3_users.append(CanonicalSNMPv3User(
            name=name,
            auth_protocol=auth_proto,
            auth_passphrase=auth_passphrase,
            priv_protocol=priv_proto,
            priv_passphrase=priv_passphrase,
        ))


#: What FortiOS takes for a route's destination when no ``set dst``
#: line is printed: ``show`` leaves out a setting at its default, and
#: the default ``dst`` is ``0.0.0.0 0.0.0.0`` (``config router
#: static``) and ``::/0`` (``config router static6``) -- Fortinet,
#: FortiOS 7.4 CLI reference,
#: https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference/522620/config-router-static
#: and .../525620/config-router-static6.  A route printed with no
#: ``set dst`` is a default route.
_DEFAULT_DESTINATION: dict[str, str] = {
    "router static": "0.0.0.0/0",
    "router static6": "::/0",
}

#: The ``gateway`` FortiOS prints for a route with none: the default,
#: which ``show full-configuration`` prints (same references).
_NO_GATEWAY = frozenset({"0.0.0.0", "::"})

#: The rows of :class:`_RoutesNotHeld`, a kind each, as each ends.
_ROUTES_NOT_HELD: dict[str, str] = {
    "vrf": (
        "route(s) of a VRF other than 0 (set vrf <id> on the route, or "
        "on the interface its set device names): no VRF of a FortiOS "
        "config is read; not translated"
    ),
    "blackhole": (
        "blackhole route(s) (set blackhole enable): the tree has no form "
        "for a route that discards; not translated"
    ),
    "object": (
        "route(s) to an address object or an Internet service (set "
        "dstaddr, set internet-service): the tree holds a destination as "
        "a prefix; not translated"
    ),
    "dynamic": (
        "route(s) whose gateway is learned from DHCP or PPP (set "
        "dynamic-gateway enable): the tree has no form for one; not "
        "translated"
    ),
    "nowhere": (
        "route(s) with neither a gateway nor a device (an SD-WAN route, "
        "set sdwan-zone): the tree has no form for one; not translated"
    ),
    "unread": "route(s) whose destination is not read; not translated",
}


class _RoutesNotHeld:
    """The routes of one ``config router static`` or ``static6`` block
    the parser reads and does not translate, and the rows that say so.

    * ``set status disable`` -- the FortiGate holds the route and does
      not install it: left out, a row of :func:`left_out_rows` each.
    * ``set vrf <id>`` other than 0 -- a VRF's route.  The parser reads
      no VRF of a FortiOS config, and in the global table of the output
      such a route would carry traffic the source keeps apart.  So is a
      route whose ``set device`` is an interface in such a VRF (see
      :func:`_in_a_vrf`).
    * ``set blackhole enable`` -- the tree has no form for a route that
      discards; without its flag it is a route to nowhere.
    * ``set dstaddr`` / ``set internet-service`` -- the destination is
      an object, and a canonical route's destination is a prefix.
    * ``set dynamic-gateway enable`` -- the next hop is whatever DHCP or
      PPP gives the interface; without it the route is an interface
      route.
    * neither a gateway nor a device (an SD-WAN route) -- a route to
      nowhere on every target.
    * a ``set dst`` the parser cannot read as a prefix.

    Each kind but the first is one row that counts its routes.
    """

    def __init__(self, head: str) -> None:
        self.head = head
        self.disabled: list[tuple[str, list[str]]] = []
        self.counts: dict[str, int] = dict.fromkeys(_ROUTES_NOT_HELD, 0)

    def rows(self) -> list[str]:
        """The rows, in a bounded number: the disabled routes through
        :func:`left_out_rows`, the others one row a kind."""
        rows = left_out_rows(self.disabled, rest="disabled-route")
        rows.extend(
            f"{self.head}: {count} {_ROUTES_NOT_HELD[kind]}"
            for kind, count in self.counts.items() if count
        )
        return rows


def _first(edit: _EditBlock, key: str) -> str:
    """The first word of the edit's ``set <key>``, or ``""``."""
    tokens = edit.settings.get(key) or [""]
    return tokens[0]


def _route_destination(tokens: list[str] | None, head: str) -> str | None:
    """The prefix a route's ``set dst`` names; FortiOS's default where
    there is no such line; ``None`` where the words are not a prefix.

    ``config router static`` prints an address and a mask; a prefix
    written ``<address>/<length>`` is read as written, as it is in
    ``config router static6``.
    """
    if not tokens:
        return _DEFAULT_DESTINATION[head]
    if len(tokens) == 1 and "/" in tokens[0]:
        return tokens[0]
    if head == "router static" and len(tokens) == 2 and "/" not in tokens[0]:
        return f"{tokens[0]}/{_mask_to_prefix(tokens[1], vendor='fortigate_cli')}"
    return None


def _read_routes(
    block: _ConfigBlock,
    intent: CanonicalIntent,
    in_a_vrf: Collection[str] = frozenset(),
) -> None:
    """Read the routes of a ``config router static`` or ``static6``
    block, and say each the tree cannot hold (:class:`_RoutesNotHeld`).

    ``set comment "<text>"`` is the route's description; ``set
    distance <n>`` (administrative distance, FortiOS's default 10) is
    its metric, so that a floating static round-trips.

    Args:
        block: The ``config router static`` or ``static6`` block.
        intent: The tree the routes are added to.
        in_a_vrf: The interfaces in a VRF other than 0
            (:func:`_in_a_vrf`): a route out one is that VRF's.
    """
    not_held = _RoutesNotHeld(block.config_path)
    for edit in ticked(block.edits):
        if _first(edit, "status").lower() == "disable":
            not_held.disabled.append((
                "disabled-route",
                ["config", *block.config_path.split(), "edit", edit.edit_id],
            ))
            continue
        vrf = _first(edit, "vrf")
        if (vrf and vrf != "0") or _first(edit, "device") in in_a_vrf:
            not_held.counts["vrf"] += 1
            continue
        if _first(edit, "blackhole").lower() == "enable":
            not_held.counts["blackhole"] += 1
            continue
        if (
            _first(edit, "dstaddr")
            or _first(edit, "internet-service") not in ("", "0")
            or _first(edit, "internet-service-custom")
        ):
            not_held.counts["object"] += 1
            continue
        destination = _route_destination(edit.settings.get("dst"), block.config_path)
        if destination is None:
            not_held.counts["unread"] += 1
            continue
        if _first(edit, "dynamic-gateway").lower() == "enable":
            not_held.counts["dynamic"] += 1
            continue
        gateway = _first(edit, "gateway")
        if gateway in _NO_GATEWAY:
            gateway = ""
        device = _first(edit, "device")
        if not gateway and not device:
            not_held.counts["nowhere"] += 1
            continue
        distance = _first(edit, "distance")
        intent.static_routes.append(CanonicalStaticRoute(
            destination=destination,
            gateway=gateway,
            interface=device,
            metric=int(distance) if distance.isdigit() else 0,
            description=_first(edit, "comment"),
        ))
    intent.dropped_tier3_sections.extend(not_held.rows())


def _in_a_vrf(blocks: list[_ConfigBlock]) -> set[str]:
    """The interfaces whose ``set vrf`` names a VRF other than 0.

    "VRFs are always enabled and, by default, all routing is done in
    VRF 0"; an interface is put in another with ``set vrf <id>``, and
    "all routes relating to that interface are isolated to that VRF
    specific routing table" (Fortinet, FortiOS 7.0.1 Administration
    Guide, "Implementing VRF").  A static route is put in a VRF by
    the interface its ``set device`` names (Fortinet KB, "Configure
    static routes and black hole routes to different VRFs": the VRF
    is configured on the interface, and the route points at it).
    Read from every block before any route: a block may come before
    the interfaces it names.
    """
    names: set[str] = set()
    for block in blocks:
        if block.config_path != "system interface":
            continue
        for edit in ticked(block.edits):
            vrf = _first(edit, "vrf")
            if edit.edit_id and vrf and vrf != "0":
                names.add(edit.edit_id)
    return names


def _out_of_their_vrf(intent: CanonicalIntent, in_a_vrf: Collection[str]) -> list[str]:
    """Leave out what each interface in a VRF other than 0 routes,
    keep the interface, and say which.

    The parser reads no VRF of a FortiOS config, and the output puts
    nothing in one: an interface of :func:`_in_a_vrf` written with its
    addresses is an interface of the global table, connected to every
    other, where the source keeps it apart ("Interfaces in one VRF
    cannot reach interfaces in a different VRF", the guide above).
    Up to 0.7.7 it was, in jobs that said ``completed``.  So its
    IPv4 and IPv6 addresses, its DHCP client and its VRRP groups are
    left out, and the record is kept with what is not routing (its
    description, state, MTU, type, tag and LAG).  FortiOS supports VRF
    for IPv6 from 7.0.1 (Fortinet KB, "VRF Support for IPv6": before
    it the IPv6 table showed no connected network of an interface in a
    VRF); what a release before 7.0.1 does with such an interface's
    IPv6 addresses is not established, and they are left out with the
    rest on every release, the reading that carries less.  The DHCP pools
    on such an interface are left out by
    :func:`.dhcp_pools.pools_of`, and the routes out it by
    :func:`_read_routes`.

    Returns:
        The row of ``dropped_tier3_sections``: one, naming a few of
        the interfaces and counting the rest; none where no
        interface of the tree is in a VRF.
    """
    names: list[str] = []
    for iface in ticked(intent.interfaces):
        if iface.name not in in_a_vrf:
            continue
        names.append(iface.name)
        iface.ipv4_addresses = []
        iface.ipv6_addresses = []
        iface.dhcp_client = False
        iface.dhcp_client_v6 = ""
        iface.vrrp_groups = []
    if not names:
        return []
    return [
        f"config system interface edit {a_few_named(names)}: set vrf <id> "
        "-- an interface in a VRF other than 0, and no VRF of a FortiOS "
        "config is read; its addresses, DHCP client and VRRP groups are "
        "not translated"
    ]


def _apply_system_admin(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config system admin`` into CanonicalLocalUser records.

    Each ``edit "NAME"`` is an administrator account.  Relevant fields:
        set password ENC <hash>      - current encrypted password
        set old-password ENC <hash>  - previous password (seen in some
                                       exports; we use as fallback if
                                       `password` isn't present)
        set accprofile "<profile>"   - admin profile; super_admin = 15
        set trusthost<N> <net> <mask>- IP allowlist (not modelled)

    FortiOS encrypts passwords with an internal-key scheme; the ``ENC``
    prefix denotes this.  We preserve the ENC-prefixed hash verbatim
    under canonical ``hashed_password`` so a lossless round-trip back
    to a FortiGate target reconstructs the original command.
    """
    for edit in ticked(block.edits):
        name = edit.edit_id
        pw_tokens = edit.settings.get("password") or edit.settings.get("old-password")
        hashed = ""
        if pw_tokens:
            # FortiOS form: `set password ENC <base64>` -> tokens
            # split by whitespace inside the shlex-aware settings dict
            # end up as ["ENC", "<base64>"]; join them back with a
            # "fortios:" prefix so target renderers can route.
            joined = " ".join(pw_tokens)
            hashed = f"fortios:{joined}"
        accprofile_tokens = edit.settings.get("accprofile")
        # The profile as it is written: it is written back as
        # ``set accprofile`` to a FortiGate, so its case is kept.
        accprofile = accprofile_tokens[0] if accprofile_tokens else ""
        # super_admin is FortiOS's built-in full-access profile.
        # prof_admin / custom profiles are usually scoped.
        is_admin = accprofile.lower() == "super_admin"
        intent.local_users.append(CanonicalLocalUser(
            name=name,
            privilege_level=15 if is_admin else 1,
            hashed_password=hashed,
            # The profile the admin names, or none: a name made up
            # here was written back as `set accprofile` of a profile
            # FortiOS does not have (netcanon/migration/_roles.py).
            role=accprofile,
        ))


def _apply_user_radius(
    block: _ConfigBlock, intent: CanonicalIntent,
) -> None:
    """Parse ``config user radius`` into CanonicalRADIUSServer records.

    FortiOS shape:
        edit "MyRadius"
            set server "10.0.0.4"
            set secret ENC <encoded>
            set auth-type auto
            set radius-port 1812
            set acct-interim-interval 600
        next

    The ``ENC`` prefix is preserved on the canonical key so a lossless
    round-trip back to FortiGate reconstructs the original command, and
    the whole ``ENC <blob>`` is carried behind ``FORTIOS_ENVELOPE``: it
    is encrypted under this FortiGate's own key.  ``set secret <secret>``
    without ``ENC`` is the secret as typed (FortiOS takes it so, and
    prints it encrypted), and carries no envelope.  Until 2026-10 every
    secret was put behind the envelope, and the RADIUS policy refused a
    typed secret on every other target.
    """
    for edit in ticked(block.edits):
        server_tokens = edit.settings.get("server")
        if not server_tokens:
            continue
        host = server_tokens[0]
        secret_tokens = edit.settings.get("secret")
        key = ""
        if secret_tokens and secret_tokens[0] == "ENC":
            key = f"{FORTIOS_ENVELOPE}{' '.join(secret_tokens)}"
        elif secret_tokens:
            key = " ".join(secret_tokens)
        auth_port = 1812
        acct_port = 1813
        port_tokens = edit.settings.get("radius-port")
        if port_tokens:
            try:
                raw_port = int(port_tokens[0])
            except ValueError:
                raw_port = 1812
            # FortiOS uses `set radius-port 0` to mean "use the default
            # port 1812" — real FG100E captures written by FortiGate's
            # own config export contain this idiom.  Canonicalise to the
            # effective value (1812) so round-trip stays stable:
            # renderer omits when auth_port == 1812 (matching FortiOS's
            # own default-omission pattern), re-parse sees no
            # radius-port, defaults to 1812.  Storing 0 would drift.
            if raw_port != 0:
                auth_port = raw_port
        intent.radius_servers.append(CanonicalRADIUSServer(
            host=host,
            key=key,
            auth_port=auth_port,
            acct_port=acct_port,
        ))


# ---------------------------------------------------------------------------
# Public parse entry point
# ---------------------------------------------------------------------------


#: Dispatch table from ``config <path>`` (as captured after the
#: ``config`` keyword) to the per-stanza applier.  Paths absent from
#: this table are silently ignored — FortiOS exports carry many
#: Tier-3 sections (firewall policies, SD-WAN rules, UTM profiles)
#: that we deliberately don't model.
_DISPATCH: ClassVar[dict[str, object]] = {
    "system global": _apply_system_global,
    "system dns": _apply_system_dns,
    "system ntp": _apply_system_ntp,
    "system interface": _apply_system_interface,
    "system snmp sysinfo": _apply_snmp_sysinfo,
    "system snmp community": _apply_snmp_community,
    "system snmp user": _apply_snmp_user,
    "system admin": _apply_system_admin,
    "user radius": _apply_user_radius,
}


def parse_intent(raw: str) -> CanonicalIntent:
    """Parse a FortiOS CLI export into :class:`CanonicalIntent`.

    Unrecognised ``config`` paths fall through as silent drops; if you
    need tolerant-mode guarantees for a new path, add it to the
    ``_DISPATCH`` table with an ``_apply_<path>`` function.  The
    ``config router static`` and ``static6`` blocks are read by
    :func:`_read_routes`, which is given the interfaces in a VRF.

    Raises:
        ParseError: On empty input or input that looks like a different
            format (XML / JSON).
    """
    if not raw.strip():
        raise ParseError(
            "fortigate_cli: empty input", snippet="",
        )
    # Shape sanity — Round-4.2 shared helper tolerates leading
    # shell-echo / banner framing on real captures.
    shape = detect_input_shape(raw)
    if shape is not None:
        raise ParseError(
            f"fortigate_cli: input looks like {shape.upper()}, "
            f"not FortiOS CLI.",
            snippet=raw.lstrip()[:120],
        )

    intent = CanonicalIntent(
        source_vendor="fortigate",
        source_format="cli-fortigate",
    )
    # Refuses a quoted value no line ends, before any statement is read.
    intent.source_version = _extract_version(without_quoted_values(raw))

    blocks = _parse_blocks(raw)
    # Track which top-level paths we saw vs which we dispatched — the
    # gap is the set of silently-ignored stanzas (Tier 3 / out of
    # scope).  DEBUG surface lets ops see what was dropped without
    # requiring a separate grep pass.
    ignored_paths: list[str] = []
    in_a_vrf = _in_a_vrf(blocks)
    for block in ticked(blocks):
        if block.config_path in ("router static", "router static6"):
            _read_routes(block, intent, in_a_vrf)
            continue
        applier = _DISPATCH.get(block.config_path)
        if applier is not None:
            applier(block, intent)
        else:
            ignored_paths.append(block.config_path)
    _link_lag_members(intent)
    _a_vlan_on_a_port_is_a_sub_interface(blocks, intent)
    # Read after every block: a pool of ``dns-service local`` or
    # ``default`` gives its clients an interface's address or the
    # FortiGate's own DNS servers, which may be stated after it.
    pools, pool_rows, pools_left_out = pools_of(blocks, intent.interfaces, in_a_vrf)
    intent.dhcp_servers.extend(pools)
    intent.dropped_tier3_sections.extend([
        *pool_rows, *left_out_rows(pools_left_out, rest="disabled"),
    ])
    intent.dropped_tier3_sections.extend(_tags_with_no_form(blocks, intent))
    intent.dropped_tier3_sections.extend(_out_of_their_vrf(intent, in_a_vrf))

    logger.debug(
        "fortigate_cli parsed: hostname=%r ifaces=%d vlans=%d "
        "routes=%d lags=%d users=%d snmp=%s dhcp=%d radius=%d "
        "blocks=%d ignored=%d (input=%d chars)",
        intent.hostname,
        len(intent.interfaces),
        len(intent.vlans),
        len(intent.static_routes),
        len(intent.lags),
        len(intent.local_users),
        "yes" if intent.snmp else "no",
        len(intent.dhcp_servers),
        len(intent.radius_servers),
        len(blocks),
        len(ignored_paths),
        len(raw),
    )
    # Only emit the ignored-paths detail when there's actual gap to
    # report — avoids noise on clean round-trip cases.
    if ignored_paths:
        logger.debug(
            "fortigate_cli: %d unhandled config path(s) dropped: %s",
            len(ignored_paths),
            ", ".join(sorted(set(ignored_paths))[:15]),
        )

    return intent
