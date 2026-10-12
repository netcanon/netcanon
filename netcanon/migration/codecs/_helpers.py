"""Shared, vendor-neutral helpers for the CLI / text codecs.

These small pure functions were independently duplicated across several
codecs (the "duplicate rather than lift" convention noted in the older
per-codec docstrings).  Because they are vendor-neutral — IEEE MAC
canonicalisation, RFC 4291 link-local detection, and dotted-mask ⇄ CIDR
conversion — a single shared copy removes the drift risk without coupling
the codecs to one another's grammar.

Import as ``from .._helpers import <name>`` from inside a codec package
(e.g. ``codecs/cisco_iosxe_cli/parse.py``).

The functions that can fail take a keyword-only ``vendor`` argument so the
raised :class:`ParseError` / :class:`RenderError` still names the codec
whose input was malformed (preserving the diagnostics that the previous
per-codec copies emitted).
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Hashable, Sequence
from typing import TYPE_CHECKING, Generic, TypeVar

from ..canonical.transforms import is_every_vlan
from .base import ParseError, RenderError

if TYPE_CHECKING:
    from ..canonical.intent import CanonicalIntent, CanonicalInterface

_K = TypeVar("_K", bound=Hashable)
_T = TypeVar("_T")


class GrowingIndex(Generic[_K, _T]):
    """Find a record, by key, in a list that grows while a config is
    parsed -- without reading the list again for every line.

    A parser's handler runs once per line.  One that looks through
    everything the earlier lines made (``next(r for r in intent.routes
    if r.name == name)``, ``any(...)``) costs the square of the lines,
    and a config is whatever was pasted: sixteen thousand stanzas of
    one kind held a worker for minutes.  This reads each record once,
    whoever appended it: before every answer it takes in the records
    the list has gained since the last.

    ``get`` returns the FIRST record with a key, as the scan it
    replaces did -- or the LAST, with ``last=True``, for the place
    that used to build ``{record.name: record for record in ...}``
    for every line.

    Two things have to hold while it is in use, and both do for the
    lists a parser fills as it reads: a record's key does not change
    once the record is in the list, and records are not taken out of
    the middle.  A list that was REPLACED, or that became shorter, is
    read again from the start.

    Args:
        records: Returns the list.  Called before every answer, so
            that a list the tree was given anew is the one read.
        key: A record's key.
        last: Of several records with one key, answer with the last
            in the list and not the first.
    """

    def __init__(
        self, records: Callable[[], list[_T]], key: Callable[[_T], _K], *, last: bool = False,
    ) -> None:
        self._records = records
        self._key = key
        self._last = last
        self._first: dict[_K, _T] = {}
        self._list: list[_T] | None = None
        self._read = 0

    def _catch_up(self) -> None:
        records = self._records()
        if records is not self._list or len(records) < self._read:
            self._list, self._first, self._read = records, {}, 0
        first, key = self._first, self._key
        while self._read < len(records):
            record = records[self._read]
            if self._last:
                first[key(record)] = record
            else:
                first.setdefault(key(record), record)
            self._read += 1

    def get(self, key: _K) -> _T | None:
        """The first record in the list whose key is *key*, or ``None``."""
        self._catch_up()
        return self._first.get(key)

    def __contains__(self, key: object) -> bool:
        self._catch_up()
        return key in self._first


class Uniques:
    """Append a value to a list unless the list has it -- what ``if x
    not in lst: lst.append(x)`` does -- without reading the list for
    every value.

    The addresses of one interface, the members of one LAG and the
    route targets of one VRF are each a list of ONE record, and a line
    that adds to one first looks for its value there.  Many lines for
    one record cost their square, on a config with nothing odd in any
    line of it: an index of the records (:class:`GrowingIndex`) does
    not help, because there is only the one.

    One is made per parse, or per pass, and asked about any number of
    lists.  For each list it keeps what the list holds, by key, and
    before every answer takes in what the list has gained since the
    last, whoever appended it.  So an answer is the scan's answer for
    a list that only grows; one that became shorter is read again
    from the start, and a list a record was given anew is another
    list.  What must not happen between two questions about one list
    is an entry being replaced in place, or one taken out and another
    put in.

    *key* is for values that cannot be hashed (a pydantic record).  It
    has to be equal for two values that are equal, and the same
    function every time one list is asked about; values under one key
    are still compared with ``==``, so a key that is too coarse costs
    time and never an answer.
    """

    def __init__(self) -> None:
        # id(list) -> [the list, its values by key, how many of its
        # entries have been read].  The list is held, so its id cannot
        # be given to another list.
        self._lists: dict[int, list] = {}

    def _entry(self, items: list, key: Callable | None) -> list:
        """What is kept for *items*, with the entries the list has
        gained since the last question taken in."""
        entry = self._lists.get(id(items))
        if entry is None or len(items) < entry[2]:
            entry = self._lists[id(items)] = [items, {}, 0]
        values = entry[1]
        for at in range(entry[2], len(items)):
            item = items[at]
            values.setdefault(item if key is None else key(item), []).append(item)
        entry[2] = len(items)
        return entry

    def add(self, items: list, value: object, key: Callable | None = None) -> bool:
        """Append *value* to *items* unless it is there.

        Args:
            items: The list.  It is held from the first question on.
            value: What to append.
            key: A key for a value that cannot be hashed.

        Returns:
            True if *value* was appended.
        """
        entry = self._entry(items, key)
        same = entry[1].setdefault(value if key is None else key(value), [])
        if value in same:
            return False
        same.append(value)
        items.append(value)
        entry[2] += 1
        return True


def address_key(address: object) -> tuple:
    """A key for :class:`Uniques` over IPv4 address records: fields
    that two equal addresses share.  (Comparing the records themselves,
    one against every other, is what made 8,000 secondary addresses on
    one SVI take 28 seconds: a record is compared field by field.)"""
    return (
        address.ip, address.prefix_length, address.is_secondary,  # type: ignore[attr-defined]
        address.virtual_gateway_address, address.virtual_gateway_mac,  # type: ignore[attr-defined]
    )


#: Every VLAN id, once: the int at index N is N (0 is there only to
#: make that so).  A list of ids that is a slice of this holds these
#: objects and makes none of its own, so an id in a list costs the
#: eight bytes of its place there.  Counted from a range it cost a new
#: int as well, 38 bytes in all, and a config can state ``1-4094`` on
#: every port it has.  Use :func:`vlan_id_run` to expand a range.
VLAN_IDS: tuple[int, ...] = tuple(range(4095))


def vlan_id_run(low: int, high: int) -> list[int]:
    """The VLAN ids *low* to *high*, both included, as a new list
    whose entries are the shared ints of :data:`VLAN_IDS`.

    Equal to ``list(range(low, high + 1))`` for ``1 <= low`` and
    ``high <= 4094``, which the caller has to have seen to: a slice
    does not refuse a bound, it stops at the end of the tuple.
    """
    return list(VLAN_IDS[low:high + 1])


#: What a trunk's allowed list says (:func:`trunk_list_says`).  On a
#: trunk the list means what it says: an empty list is NO VLAN, a list
#: of every id (1-4094) is EVERY VLAN, and any other list is the list.
#: There is no value for "not stated".
TRUNK_NONE = "none"
TRUNK_ALL = "all"
TRUNK_SOME = "some"

#: What a trunk carries when its config states NO allowed list, by
#: codec: the platform's own default.  The ONE place this is written.
#: A parser fills an unstated list from it, for a port that says it
#: is a trunk (:class:`TrunksByName`, which asks
#: :func:`unstated_trunk_list`), and the ``switchport`` renderers
#: write no allowed line for the list that is their platform's
#: default, which is what the device prints
#: (:func:`switchport_trunk_allowed_value`).
#:
#: * IOS-XE, EOS, NX-OS: every VLAN.  A trunk with no ``switchport
#:   trunk allowed vlan`` line carries all of them.  (NX-OS keeps a
#:   block of ids for itself, 3968-4047 unless it is moved; the list
#:   is the 4,094 ids all the same, because only that list makes a
#:   renderer write its form for every VLAN.)
#: * AOS-CX: every VLAN.  Defining a native VLAN makes the switch
#:   run ``vlan trunk allowed all`` itself.
#: * OS10: none.  A trunk carries untagged traffic on its access
#:   VLAN and no tagged VLAN until an allowed line names one.
#: * Junos: none.  A trunk is a member of the VLANs its ``vlan
#:   members`` name.
#:
#: The vendors' own sentences, with their sources, are in
#: ``docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md``.
#:
#: A codec whose parser can make a trunk is here, or it is named with
#: its reason among the codecs that have no allowed list, in
#: ``tests/unit/migration/test_a_trunk_says_none_nothing_or_all.py``; the
#: test fails for a public codec that is in neither.  (AOS-S is one of
#: those: a port is a trunk there only by being tagged in a VLAN.)
TRUNK_THAT_STATES_NO_LIST: dict[str, str] = {
    "arista_eos": TRUNK_ALL,
    "aruba_aoscx": TRUNK_ALL,
    "cisco_iosxe_cli": TRUNK_ALL,
    "cisco_nxos": TRUNK_ALL,
    "dell_os10": TRUNK_NONE,
    "juniper_junos": TRUNK_NONE,
}


def unstated_trunk_list(codec: str) -> list[int]:
    """The allowed list of a trunk of *codec* that states none.

    Every id where the platform's trunk carries every VLAN by default,
    no id where it carries none (:data:`TRUNK_THAT_STATES_NO_LIST`).
    A new list each call; its entries are the shared ints of
    :data:`VLAN_IDS`.

    Raises:
        KeyError: *codec* is not in the table.
    """
    if TRUNK_THAT_STATES_NO_LIST[codec] == TRUNK_ALL:
        return vlan_id_run(1, 4094)
    return []


def trunk_list_says(allowed: Sequence[int]) -> str:
    """What a trunk's allowed list says: :data:`TRUNK_NONE` for an
    empty list, :data:`TRUNK_ALL` for a list of every id, 1-4094
    (:func:`...canonical.transforms.is_every_vlan`), and
    :data:`TRUNK_SOME` for any other."""
    if not allowed:
        return TRUNK_NONE
    if is_every_vlan(allowed):
        return TRUNK_ALL
    return TRUNK_SOME


def switchport_trunk_allowed_value(
    codec: str, allowed: Sequence[int], *, coalesce: bool,
) -> str | None:
    """What follows ``switchport trunk allowed vlan`` for a TRUNK on
    *codec* (IOS-XE, EOS, NX-OS, OS10), or ``None`` for no line.

    No line for the list that is the platform's own for a trunk with
    no line (:data:`TRUNK_THAT_STATES_NO_LIST`): the device prints
    none, and a default trunk comes back as it went.  So every VLAN is
    no line on IOS-XE, EOS and NX-OS -- never the 4,094 ids, which is
    one line of some 19,000 characters, and never ``1-4094``, which
    names ids NX-OS keeps for itself -- and no VLAN is no line on
    OS10.

    ``none`` for no VLAN where the platform's trunk carries every
    VLAN by default.  The list otherwise: as ranges with *coalesce*,
    as the ids in their order without.  (OS10 has no word for every
    VLAN; that list is written there as the range, and its renderer
    says so beside it.)

    Raises:
        KeyError: *codec* is not in the table.
    """
    says = trunk_list_says(allowed)
    if says == TRUNK_THAT_STATES_NO_LIST[codec]:
        return None
    if says == TRUNK_NONE:
        return "none"
    if coalesce:
        return _coalesce_vlan_ids(sorted(set(allowed)))
    return ",".join(str(vid) for vid in allowed)


def same_vendor_version(
    tree: CanonicalIntent, *, vendor_id: str, default: str
) -> str:
    """The version token to stamp on render: the device's OWN ``source_version``
    when the tree was parsed by THIS codec (``source_vendor == vendor_id``) and
    carries a version, else the synthetic *default*.

    Compare against the codec's ``capabilities.vendor_id`` — NOT its registry
    key.  Some codecs stamp a different vendor_id than their registry name
    (``cisco_iosxe_cli`` → ``cisco_iosxe``, ``fortigate_cli`` → ``fortigate``),
    so a registry-key literal would silently never fire for those.  Keeps a
    same-vendor re-render (sanitize / X→X) echoing the device's real release
    instead of relabelling it with a constant.  ``source_version`` is
    metadata-excluded from every comparator, so this is round-trip-invisible.
    """
    if tree.source_vendor == vendor_id and tree.source_version:
        return tree.source_version
    return default


def _normalise_mac_to_colon_hex(mac: str) -> str:
    """Normalise a vendor MAC representation to canonical colon-hex.

    Accepts the common operator-paste forms — dotted-triplet
    (``0001.c73a.0000``, Cisco / NX-OS native), colon-hex
    (``00:01:c7:3a:00:00``, canonical / Unix), or dash-hex
    (``00-01-C7-3A-00-00``, Windows / IEEE) — and returns the lower-case
    ``aa:bb:cc:dd:ee:ff`` form.  Returns the empty string for input it
    cannot classify (12 hex digits expected) so the caller skips the
    field rather than poisoning it with malformed data.
    """
    if not mac:
        return ""
    hex_only = re.sub(r"[^0-9a-f]", "", mac.strip().lower())
    if len(hex_only) != 12:
        return ""
    return ":".join(hex_only[i:i + 2] for i in range(0, 12, 2))


def _is_link_local_v6(addr: str) -> bool:
    """Return True iff *addr* is in the IPv6 link-local prefix fe80::/10.

    The prefix (RFC 4291 §2.4) is vendor-neutral: the first byte is 0xfe
    and the second nibble is 8/9/a/b (binary ``1111111010`` — ten leading
    ones).  This lets a codec recover link-local scope on a raw
    ``fe80::`` line even when the operator omits the vendor
    ``link-local`` keyword.  Only the leading characters are inspected,
    so malformed / over-``::`` inputs return False rather than raising —
    downstream canonical-build validation rejects a truly bad address.
    """
    if not addr:
        return False
    lo = addr.lower()
    return len(lo) >= 3 and lo[:2] == "fe" and lo[2] in ("8", "9", "a", "b")


def _mask_to_prefix(mask_str: str, *, vendor: str) -> int:
    """Convert a dotted-decimal IPv4 subnet mask to a CIDR prefix length.

    Raises :class:`ParseError` (prefixed with *vendor*) for an address
    that is not a valid dotted quad or whose set bits are not
    left-contiguous (e.g. ``255.0.255.0``).  The mask is zero-padded to
    the full 32 bits before the contiguity check so a mask whose leading
    octet is zero (e.g. the non-contiguous ``0.255.0.0``) is correctly
    rejected rather than silently mis-counted.
    """
    try:
        addr = ipaddress.IPv4Address(mask_str)
    except ipaddress.AddressValueError as e:
        raise ParseError(
            f"{vendor}: invalid subnet mask {mask_str!r}",
            snippet=mask_str,
        ) from e
    bits = bin(int(addr))[2:].zfill(32)
    if "01" in bits:
        raise ParseError(
            f"{vendor}: non-contiguous subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    return bits.count("1")


def _prefix_to_mask(prefix: int, *, vendor: str) -> str:
    """Convert a CIDR prefix length to a dotted-decimal IPv4 subnet mask.

    Inverse of :func:`_mask_to_prefix`.  Used by render() for the Cisco
    ``ip address X Y`` / ``ipv4 address X Y`` forms that require a dotted
    mask (every other shipped codec uses CIDR natively, so the canonical
    tree holds prefix lengths and we expand on render).  Raises
    :class:`RenderError` (prefixed with *vendor*) when *prefix* is
    outside 0..32.
    """
    if not (0 <= prefix <= 32):
        raise RenderError(
            f"{vendor}: prefix length {prefix} out of range",
            yang_path="/interfaces/interface/ipv4/address/prefix-length",
        )
    mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0
    return str(ipaddress.IPv4Address(mask_int))


def _parse_vlan_list(text: str) -> list[int]:
    """Parse a VLAN id-list like ``1,10,2000`` or ``10-20`` into a flat
    list of ints.  Ranges are expanded inclusively.

    Shared by the codecs whose id-lists use the Cisco-style comma/hyphen
    grammar (``cisco_nxos``, ``cisco_iosxe_cli``, ``aruba_aoscx`` each
    previously carried a byte-identical private copy).  The valid VLAN
    space is clamped BEFORE the range is materialised so an out-of-bounds
    span (e.g. ``1-9999999999``) cannot OOM the process; the valid
    sub-range is preserved (lossless vs the downstream 1..4094 filter).
    Non-numeric tokens are skipped.  The inverse is
    :func:`_coalesce_vlan_ids`.
    """
    result: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                lo_i, hi_i = int(lo.strip()), int(hi.strip())
            except ValueError:
                continue
            lo_i, hi_i = max(1, lo_i), min(4094, hi_i)
            if lo_i <= hi_i:
                result.extend(VLAN_IDS[lo_i:hi_i + 1])
        elif part.isdigit():
            result.append(int(part))
    return result


#: Leading keywords in the Cisco / Arista / NX-OS ``switchport trunk
#: allowed vlan`` grammar that make the line RELATIVE to the running list
#: rather than a fresh assignment.  ``show running-config`` emits a long
#: allowed-list as an initial set line followed by ``... add`` continuation
#: lines, so a parser that overwrites per line (instead of applying the
#: keyword) silently keeps only the last line.
_TRUNK_ALLOWED_KEYWORDS = frozenset(
    {"add", "remove", "except", "none", "all"}
)


def merge_trunk_allowed(
    existing: list[int] | None,
    remainder: str,
    *,
    parse_ids: Callable[[str], list[int]] = _parse_vlan_list,
    unstated: Sequence[int] = (),
) -> list[int]:
    """Apply one ``switchport trunk allowed vlan`` *remainder* to *existing*.

    The Cisco / Arista / NX-OS grammar renders a long allowed-list across
    multiple lines using relative keywords::

        switchport trunk allowed vlan 10,20      # set      -> [10, 20]
        switchport trunk allowed vlan add 30,40  # union    -> [10, 20, 30, 40]
        switchport trunk allowed vlan remove 20  # subtract -> [10, 30, 40]

    A bare list (no keyword) SETS the membership; ``none`` clears it;
    ``all`` is the full 1-4094 space; ``except L`` is everything but *L*.
    The keyword must be stripped before the id list is parsed — otherwise
    it glues onto the first token (``"add 30"``), which is non-numeric and
    is silently dropped, so ``allowed vlan add 30,40`` collapsed to
    ``[40]`` and (because each line overwrote the previous) any earlier set
    line vanished entirely (blind-audit ``65f9c01`` T0-1).

    *parse_ids* parses a comma/hyphen id-list into ``list[int]``; it
    defaults to the shared :func:`_parse_vlan_list` but a codec injects its
    own near-twin (``arista_eos._expand_vlan_list``) so this keyword logic
    can be shared without converging the codec's deliberately-divergent
    id-list parser.  Because the bare-list path delegates straight to
    *parse_ids*, the common single-line form round-trips exactly as before;
    only the keyword forms — which no prior code handled — change
    behaviour.  ``add``/``remove`` preserve *existing* order and append /
    drop in place.

    *existing* is ``None`` while the interface has stated no allowed
    line yet (:class:`TrunksByName` keeps what it has stated, across
    its stanzas).  ``add`` and ``remove`` then start from *unstated*, the
    platform's list for a trunk that states none
    (:func:`unstated_trunk_list`), because that is the list the device
    edits: on a platform whose trunk carries every VLAN, ``remove 10``
    on a port with no earlier line is every VLAN but 10 (it was read
    as no VLAN), and ``add 30`` is still every VLAN (it was read as
    VLAN 30 alone).

    Args:
        existing: The list the interface has stated so far, or
            ``None`` if it has stated none.
        remainder: What follows ``switchport trunk allowed vlan``.
        parse_ids: Reads a comma/hyphen id list.
        unstated: The list ``add`` and ``remove`` start from when
            *existing* is ``None``.  Empty by default, which is the
            list of a platform whose trunk carries no VLAN until one
            is named.

    Returns:
        The interface's list after this line.  Always a list: a line
        was stated.
    """
    tokens = remainder.split(None, 1)
    keyword = tokens[0].lower() if tokens else ""
    if keyword not in _TRUNK_ALLOWED_KEYWORDS:
        # Bare ``<id-list>`` — preserve the exact prior parse behaviour.
        return parse_ids(remainder)
    if keyword == "none":
        return []
    if keyword == "all":
        return vlan_id_run(1, 4094)
    rest = tokens[1] if len(tokens) > 1 else ""
    ids = parse_ids(rest)
    if keyword == "except":
        blocked = set(ids)
        return [vid for vid in VLAN_IDS[1:] if vid not in blocked]
    base = list(unstated) if existing is None else list(existing)
    if keyword == "add":
        # (#11) ``vid not in base`` is an O(len(base)) list scan per id;
        # a config with K× ``allowed vlan add 1-4094`` lines drove the
        # accumulating 4094-element list to ~8.4M comparisons per line
        # (K=200 → ~7 s parse; near-cap bodies → hours, on the default
        # local bind).  A set membership check is O(1) and behaviour-
        # identical (order preserved; the comprehension doesn't observe
        # its own additions either way, so duplicate ids resolve the same).
        seen = set(base)
        return base + [vid for vid in ids if vid not in seen]
    # keyword == "remove"
    drop = set(ids)
    return [vid for vid in base if vid not in drop]


class TrunksByName:
    """What the interfaces of ONE config state about their trunks, kept
    by the interface's NAME as the config writes it.

    A config can hold the stanza of one interface more than once -- a
    pasted change, a template that sets the mode in one place and the
    list in another -- and the device applies every line under the
    name, in the order it meets them, to ONE interface.  Whether an
    interface states an allowed list, and whether it says it is a
    trunk, are facts about the interface and not about a stanza.  Two
    parsers keep one record a name; four make a record a stanza.
    Resolved a stanza, a trunk of VLAN 10 whose stanza was met again
    with only its mode line came out with a second record of the
    platform's list -- every VLAN, or from OS10 none -- and ``allowed
    vlan add 30`` in a second stanza was added to that list and not
    to the interface's own.

    The parser says what it meets (:meth:`allowed_line` or
    :meth:`allowed_is`, :meth:`mode_line` or :meth:`says_trunk`), says
    when it has made a record (:meth:`made`), and asks for the lists
    when the config has been read (:meth:`settle`).  Each of those
    takes a KEY that says which interface is meant.  For a parser
    that reads stanzas the key is :meth:`key` of the stanza's header
    line, and not the name it gives the record: two of these parsers
    read ``interface port-channel 1`` and ``interface port-channel 2``
    as one name, ``port-channel``, and those are two interfaces.  (A
    parser that keeps one record a name has nothing better than that
    name.)  Each record is then given its interface's list:

    * An interface that states an allowed line has what its lines
      come to, each applied in the order it is met, whichever stanza
      it is in.  A record whose stanza states one has that list as it
      stood when the record was made (its stanza had ended).  A TRUNK
      whose own stanza states none has it too -- as it stood then,
      or, where the interface had stated none yet, as the interface
      is left with it.
    * A trunk whose interface states none, in any stanza, has the
      platform's list (:data:`TRUNK_THAT_STATES_NO_LIST`) -- where
      the interface SAYS it is a trunk.  Two parsers take a port for
      a trunk from a trunk line alone (NX-OS and EOS: ``switchport
      trunk native vlan N`` and no ``switchport mode trunk``, on
      platforms whose port is an access port until it is told
      otherwise and keeps such a line without acting on it).  A trunk
      the parser inferred is given nothing from the platform's list:
      the empty list where it states none, and an ``add`` or a
      ``remove`` on its first allowed line starts from nothing.  That
      is fewer VLANs than a trunk would carry, and never more.
    * A port that is not a trunk has the list its own stanza states
      (IOS-XE keeps one on such a port), and none otherwise.

    Args:
        codec: A codec of :data:`TRUNK_THAT_STATES_NO_LIST`.
        parse_ids: Reads a comma/hyphen id list, for
            :func:`merge_trunk_allowed`.

    Raises:
        KeyError: *codec* is not in the table.
    """

    def __init__(
        self,
        codec: str,
        *,
        parse_ids: Callable[[str], list[int]] = _parse_vlan_list,
    ) -> None:
        self._codec = codec
        self._parse_ids = parse_ids
        # What ``add`` and ``remove`` start from on an interface's
        # first allowed line: the platform's list.
        self._platform: tuple[int, ...] = (
            VLAN_IDS[1:] if TRUNK_THAT_STATES_NO_LIST[codec] == TRUNK_ALL
            else ()
        )
        self._allowed: dict[str, list[int]] = {}
        # The same lines applied to an empty list, kept only for an
        # interface whose every allowed line so far is an ``add`` or
        # a ``remove``: the one case in which the platform's list is
        # part of what the lines come to.
        self._from_nothing: dict[str, list[int]] = {}
        self._said_trunk: set[str] = set()
        # The interfaces that have stated an allowed line since a
        # record of them was last made: in the stanza being read.
        self._in_this_stanza: set[str] = set()
        # Each record made: its interface's key, whether its own
        # stanza stated an allowed line, and the interface's two
        # lists as they stood then (``None`` twice: none stated yet).
        self._made: list[tuple[
            CanonicalInterface, str, bool, list[int] | None, list[int] | None,
        ]] = []

    @staticmethod
    def key(header: str) -> str:
        """The key of the interface a stanza's *header* line names:
        the line with its white space taken out, in lower case.

        ``interface Vlan 10``, ``interface vlan10`` and the same line
        met again are one interface; ``interface port-channel 1`` and
        ``interface port-channel 2`` are two.
        """
        return "".join(header.split()).lower()

    def says_trunk(self, key: str) -> None:
        """Interface *key* states that it is a trunk (``switchport
        mode trunk``; on AOS-CX a ``vlan trunk`` line, which is how a
        trunk is stated there)."""
        self._said_trunk.add(key)

    def mode_line(self, key: str, mode: str) -> None:
        """Interface *key* states ``switchport mode <mode>``, in lower
        case: :meth:`says_trunk` where the mode is ``trunk``, and
        nothing for any other."""
        if mode == "trunk":
            self._said_trunk.add(key)

    def allowed_is(self, key: str, allowed: list[int]) -> list[int]:
        """Interface *key* states its list outright, as *allowed*
        (which is kept, not copied).  Returns it."""
        self._allowed[key] = allowed
        self._from_nothing.pop(key, None)
        self._in_this_stanza.add(key)
        return allowed

    def allowed_line(self, key: str, remainder: str) -> list[int]:
        """Apply one ``switchport trunk allowed vlan <remainder>`` line
        of interface *key* (:func:`merge_trunk_allowed`) to the list
        the interface has stated so far, in this stanza or an earlier
        one.

        Returns:
            The interface's list after the line.  It is not changed
            afterwards: the next line makes a new one.
        """
        before = self._allowed.get(key)
        after = self._allowed[key] = merge_trunk_allowed(
            before, remainder,
            parse_ids=self._parse_ids, unstated=self._platform,
        )
        self._in_this_stanza.add(key)
        if self._platform:
            word = remainder.split(None, 1)[0].lower() if remainder.strip() else ""
            if word in ("add", "remove") and (
                before is None or key in self._from_nothing
            ):
                self._from_nothing[key] = merge_trunk_allowed(
                    self._from_nothing.get(key), remainder,
                    parse_ids=self._parse_ids,
                )
            else:
                self._from_nothing.pop(key, None)
        return after

    def made(self, key: str, iface: CanonicalInterface) -> CanonicalInterface:
        """A record of interface *key* has been made: every line of
        its stanza has been handed over.  Returns *iface*.

        A parser that keeps one record a name calls this for each
        when the config has been read.
        """
        allowed = self._allowed.get(key)
        self._made.append((
            iface, key, key in self._in_this_stanza,
            allowed, self._from_nothing.get(key, allowed),
        ))
        self._in_this_stanza.discard(key)
        return iface

    def settle(self) -> None:
        """Give each record handed to :meth:`made` the allowed list of
        its interface (the class docstring says which).  Called once,
        when every stanza has been read: a later stanza can state the
        list of an interface, or say that it is a trunk, after a
        record of it was made.

        No two records are given the same list object.
        """
        handed: set[int] = set()
        for iface, key, in_its_stanza, allowed, from_nothing in self._made:
            if iface.switchport_mode != "trunk":
                # No trunk: the list its own stanza states, if any.
                if not in_its_stanza or allowed is None:
                    continue
            else:
                if allowed is None:
                    # Nothing stated when the record was made: what
                    # the interface states by the end, if anything.
                    allowed = self._allowed.get(key)
                    from_nothing = self._from_nothing.get(key, allowed)
                if key not in self._said_trunk:
                    # A trunk the parser inferred: nothing of the
                    # platform's list.
                    allowed = [] if from_nothing is None else from_nothing
                elif allowed is None:
                    allowed = unstated_trunk_list(self._codec)
            if id(allowed) in handed:
                allowed = list(allowed)
            handed.add(id(allowed))
            iface.trunk_allowed_vlans = allowed


def _run_token(lo: int, hi: int) -> str:
    """Format a single consecutive run for :func:`_coalesce_vlan_ids`.

    A two-wide run (``10,11``) stays comma-separated rather than
    ``10-11`` — both re-parse identically, but the comma form matches the
    show-output convention for adjacent pairs.
    """
    if hi == lo:
        return str(lo)
    if hi == lo + 1:
        return f"{lo},{hi}"
    return f"{lo}-{hi}"


def _coalesce_vlan_ids(ids: list[int]) -> str:
    """Coalesce a sorted, de-duplicated VLAN-id list into comma/hyphen form.

    ``[1, 10, 11, 12, 20]`` → ``"1,10-12,20"``.  Consecutive runs of three
    or more collapse to ``lo-hi``; the inverse of :func:`_parse_vlan_list`
    so a ``vlan trunk allowed`` / id-list round-trips.  Shared by the
    codecs that previously carried a byte-identical private copy
    (``cisco_nxos``, ``aruba_aoscx``).  The caller is responsible for
    sorting and de-duplicating *ids* first.
    """
    if not ids:
        return ""
    parts: list[str] = []
    run_start = prev = ids[0]
    for vid in ids[1:]:
        if vid == prev + 1:
            prev = vid
            continue
        parts.append(_run_token(run_start, prev))
        run_start = prev = vid
    parts.append(_run_token(run_start, prev))
    return ",".join(parts)
