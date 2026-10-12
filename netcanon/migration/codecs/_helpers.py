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
from bisect import bisect_left
from collections.abc import Callable, Hashable, Iterable
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ..limits import charge
from .base import ParseError, RenderError

if TYPE_CHECKING:
    from ..canonical.intent import CanonicalIntent

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
#:
#: A place that makes a list from this counts the ids it is about to
#: make first (``charge("vlan_ids", ...)``): eight bytes an id is
#: still four million ids from a kilobyte of ``2-4000`` tokens.
VLAN_IDS: tuple[int, ...] = tuple(range(4095))


def vlan_id_run(low: int, high: int) -> list[int]:
    """The VLAN ids *low* to *high*, both included, as a new list
    whose entries are the shared ints of :data:`VLAN_IDS`.

    Equal to ``list(range(low, high + 1))`` for ``1 <= low`` and
    ``high <= 4094``, which the caller has to have seen to: a slice
    does not refuse a bound, it stops at the end of the tuple.  The
    caller counts them, too, before it asks: it knows what the config
    wrote, which a refusal quotes.
    """
    return list(VLAN_IDS[low:high + 1])


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
                # Counted before it is made: a range is a few bytes.
                charge("vlan_ids", hi_i - lo_i + 1, part)
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
    existing: list[int],
    remainder: str,
    *,
    parse_ids: Callable[[str], list[int]] = _parse_vlan_list,
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
    """
    tokens = remainder.split(None, 1)
    keyword = tokens[0].lower() if tokens else ""
    if keyword not in _TRUNK_ALLOWED_KEYWORDS:
        # Bare ``<id-list>`` — preserve the exact prior parse behaviour.
        return parse_ids(remainder)
    if keyword == "none":
        return []
    if keyword == "all":
        charge("vlan_ids", 4094, "all")
        return vlan_id_run(1, 4094)
    rest = tokens[1] if len(tokens) > 1 else ""
    ids = parse_ids(rest)
    if keyword == "except":
        blocked = set(ids)
        charge(
            "vlan_ids", 4094 - len(blocked.intersection(VLAN_IDS[1:])), remainder,
        )
        return [vid for vid in VLAN_IDS[1:] if vid not in blocked]
    base = list(existing)
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


def joined_ids_length(ids: list[int]) -> int:
    """How long ``",".join(str(vid) for vid in ids)`` is, without
    writing it: a digit count and the commas.

    Exact for ids from 0 to 9999, which is every VLAN id; an id with
    more digits is counted as four, so the answer is never more than
    the text.  One sort of the list in C and three lookups: nothing
    is made for an id.
    """
    count = len(ids)
    if not count:
        return 0
    ordered = sorted(ids)
    shorter = (
        bisect_left(ordered, 10) + bisect_left(ordered, 100)
        + bisect_left(ordered, 1000)
    )
    return 4 * count - shorter + count - 1


def charge_id_lines(
    interfaces: Iterable[Any], lead: str, *, trunks_only: bool,
) -> None:
    """Count the lines that write a port's allowed-VLAN list id by id,
    BEFORE a renderer writes any of them.

    IOS-XE and EOS take the list as ``lead`` and every id, so a tree
    whose lists hold four million ids is nineteen megabytes of those
    lines.  The lists' lengths say so before the first character: a
    renderer calls this once, ahead of its output.  What is charged is
    the length of those lines and nothing else, so it is never more
    than the output is.

    Args:
        interfaces: The interfaces the renderer is about to write.
        lead: The line up to the first id, as the renderer writes it.
        trunks_only: The renderer writes the line for a port in trunk
            mode only (EOS); otherwise for any port with a list.

    Raises:
        LimitExceeded: Those lines alone are longer than the output
            may be (:mod:`netcanon.migration.limits`).
    """
    total = ports = 0
    for iface in interfaces:
        ids = iface.trunk_allowed_vlans
        if ids and (not trunks_only or iface.switchport_mode == "trunk"):
            total += len(lead) + joined_ids_length(ids) + 1
            ports += 1
    if ports:
        charge(
            "text", total,
            f"the allowed-VLAN lists of {ports:,} ports, written id by id",
        )


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
