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
from collections.abc import Callable, Hashable, Iterable, Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from .._tier3_detection import left_out_rows
from ..canonical.transforms import is_every_vlan
from ..canonical.transforms import trunk_untagged_vlan as trunk_untagged_vlan
from ..limits import charge, ticked
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
#:
#: A place that makes a list from this counts the ids it is about to
#: make first (``charge("vlan_ids", ...)``): eight bytes an id is
#: still four million ids from a kilobyte of ``2-4000`` tokens.
VLAN_IDS: tuple[int, ...] = tuple(range(4095))

#: Every VLAN id, 1-4094, as one tuple of those ints: what a trunk
#: that carries every VLAN has for a list, before anyone has asked
#: for a list of it.  ``add`` and ``remove`` on the first allowed
#: line of such a trunk start from a copy, which is counted.
EVERY_VLAN_ID: tuple[int, ...] = VLAN_IDS[1:]

#: What a refusal says was counted, for the ids no character of the
#: config stands for (a refusal quotes eighty characters, so the
#: words come first and the name after).
_NO_LIST_IS_EVERY_VLAN = "a trunk with no allowed list, which is every VLAN"
_STANZA_MET_AGAIN = "the allowed list of a stanza that is met again"


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
#:   VLAN and no tagged VLAN until an allowed line names one.  (The
#:   allowed line of OS10 names tagged VLANs only; its parser then
#:   adds the access VLAN to the list, by
#:   :data:`NATIVE_VLAN_AND_THE_LIST`.)
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


#: How a platform's text states the VLAN a trunk carries untagged
#: (:data:`NATIVE_VLAN_AND_THE_LIST`).
LIST_DECIDES = "list decides"
BESIDE_THE_LIST = "beside the list"

#: Where a platform's TEXT states the VLAN a trunk carries untagged,
#: by codec.  The ONE place this is written.
#:
#: In the tree a trunk's allowed list is what the port carries, its
#: native VLAN among them, and the native VLAN says which of them
#: goes untagged.  A native VLAN the list does not hold is stated
#: and not carried (:func:`trunk_untagged_vlan`: read a trunk
#: through it, never from ``trunk_native_vlan`` alone).  A platform's
#: text says that in one of two ways:
#:
#: * :data:`LIST_DECIDES` -- IOS-XE, EOS, NX-OS, AOS-CX, Junos.  The
#:   native VLAN is a line of its own, and the allowed line (``vlan
#:   members`` on Junos) can name it or leave it out: both are text
#:   these platforms print.  The parser puts the list the text
#:   states and the renderer writes the list as it stands, so a
#:   native line beside a list that leaves the VLAN out comes back
#:   as it went.  (Junos here is the ELS grammar, which is what its
#:   codec writes: ``interface-mode trunk`` and ``native-vlan-id`` on
#:   the physical interface.  The older grammar -- ``port-mode
#:   trunk`` and ``native-vlan-id`` under the unit -- states the
#:   native VLAN beside its members, and a native VLAN that is ALSO
#:   on the members is sent tagged there; its parser reads the two
#:   grammars as one today, which the known limitations say.)
#: * :data:`BESIDE_THE_LIST` -- OS10.  The untagged VLAN is the
#:   trunk's ``switchport access vlan`` line, and the allowed line
#:   names tagged VLANs: one VLAN is not on both.  The parser adds
#:   the access VLAN to the list it puts (:func:`trunk_list_read`)
#:   and the renderer takes the native VLAN out of the list it
#:   writes (:func:`trunk_list_written`).  Both ask this table, by
#:   the codec's name.
#:
#: The value says how the text is WRITTEN, which is all a codec
#: needs of it.  What a device then does with a native VLAN its
#: list leaves out is the vendor's to say, and not every vendor
#: says it: the sentences, their sources and what is not
#: established are in
#: ``docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md``.
#: A trunk that carries an untagged VLAN is written with that VLAN
#: in its list for every :data:`LIST_DECIDES` target.  The vendor
#: says the list has to hold it on AOS-CX, on IOS-XE and NX-OS for
#: the default native VLAN 1, and -- as a requirement to receive --
#: in the Junos grammar written here; for another native VLAN on
#: IOS-XE and NX-OS that is an inference from the vendor's rule, and
#: for EOS it is not established.  It is NOT a rule for platforms
#: in general: where the untagged VLAN is stated beside the list,
#: naming it in the list as well can mean something else.
#:
#: Every codec of :data:`TRUNK_THAT_STATES_NO_LIST` is here and no
#: other is;
#: ``tests/unit/migration/test_the_list_holds_the_native_vlan.py``
#: fails for a codec that is in one table and not the other.  (AOS-S
#: is in neither, for the one reason: it is told VLAN by VLAN.  Its
#: port records are made by ``project_vlan_to_switchport``, which
#: puts the VLAN a port is untagged in into the port's list.)
NATIVE_VLAN_AND_THE_LIST: dict[str, str] = {
    "arista_eos": LIST_DECIDES,
    "aruba_aoscx": LIST_DECIDES,
    "cisco_iosxe_cli": LIST_DECIDES,
    "cisco_nxos": LIST_DECIDES,
    "dell_os10": BESIDE_THE_LIST,
    "juniper_junos": LIST_DECIDES,
}


#: What a trunk that states no native VLAN has for one, where that
#: is not an id (:data:`TRUNK_THAT_STATES_NO_NATIVE`).
NATIVE_NONE = "none"
NATIVE_OF_THE_SWITCH = "the switch's default VLAN"

#: The native VLAN of a trunk whose config states NONE, by codec: the
#: platform's own default.  The ONE place this is written.
#:
#: In a tree a parser made, ``trunk_native_vlan is None`` says that
#: the port carries no VLAN untagged, as far as its platform's text
#: AND its platform's default go.  What a platform does with a
#: statement that is not there is a fact about the SOURCE, and only
#: its parser knows it.  So the parser of a platform whose trunk has
#: a default native VLAN puts that VLAN (:class:`TrunksByName`, which
#: asks :func:`unstated_native_vlan`), as it puts the list of a trunk
#: that states none (:data:`TRUNK_THAT_STATES_NO_LIST`) -- and, like
#: the list, only for a port that SAYS it is a trunk.  And the
#: ``switchport`` renderers write no native line for the VLAN that is
#: their platform's default (:func:`switchport_trunk_native_value`):
#: no real capture of the three prints one.  The other way, a trunk
#: that carries NO VLAN untagged and whose list holds the default is
#: owed a form that says so on a target that has a default
#: (:func:`wants_no_untagged_vlan`): written no native line, it would
#: carry the default VLAN untagged there.
#:
#: * IOS-XE, EOS, AOS-CX: VLAN 1, in each vendor's own sentence.
#: * NX-OS: VLAN 1, in two sentences of one Cisco page: such a
#:   trunk "uses the default VLAN", and "The default VLAN is
#:   VLAN1."
#: * Junos: :data:`NATIVE_NONE`.  Untagged packets are dropped on a
#:   trunk that states no ``native-vlan-id``.
#: * OS10: :data:`NATIVE_OF_THE_SWITCH`.  Dell's sentence says the
#:   native VLAN of a port is the default VLAN of the switch.  Which
#:   id that is is a setting of the switch, which a trunk's stanza
#:   does not state, so it is NOT filled in: an OS10 trunk that
#:   states no access VLAN is left with no native VLAN -- the reading
#:   that carries fewer.  (No committed capture has such a trunk.)
#:   As a TARGET the default has no id either, so no "does the list
#:   hold it" can be asked: a trunk with no native VLAN is written
#:   ``no switchport access vlan`` under a review line, by its
#:   renderer, and not through :func:`wants_no_untagged_vlan` --
#:   unless another record of the interface states its untagged VLAN
#:   (a native VLAN, or an access VLAN), which the line would take
#:   back.
#:
#: The vendors' sentences, with their sources, are in
#: ``docs/vendor-references/cisco_iosxe_cli_to_juniper_junos/vlans.md``
#: (the table "And when the config states no untagged VLAN at all").
#:
#: Every codec of :data:`TRUNK_THAT_STATES_NO_LIST` is here and no
#: other is;
#: ``tests/unit/migration/test_the_list_holds_the_native_vlan.py``
#: fails for a codec that is in one of the three trunk tables and not
#: in all of them.  (AOS-S is in none, for the one reason: it is told
#: VLAN by VLAN.  HPE's sentences say a port is in the default VLAN
#: until it is removed from it, and not whether tagged or untagged,
#: so nothing is filled in for it either.  As a target it is asked
#: VLAN by VLAN too: its renderer takes a name the output tags
#: somewhere, lists untagged nowhere and names on no line of VLAN 1
#: out of VLAN 1 with ``no untagged``, and writes a trunk that
#: carries VLAN 1 tagged in a ``vlan 1`` stanza where the tree has no
#: VLAN 1 record.)
TRUNK_THAT_STATES_NO_NATIVE: dict[str, int | str] = {
    "arista_eos": 1,
    "aruba_aoscx": 1,
    "cisco_iosxe_cli": 1,
    "cisco_nxos": 1,
    "dell_os10": NATIVE_OF_THE_SWITCH,
    "juniper_junos": NATIVE_NONE,
}


def trunk_list_read(
    codec: str, stated: list[int], untagged: int | None,
) -> list[int]:
    """The allowed list a parser of *codec* puts for a trunk whose
    allowed line names *stated* and whose text states *untagged* as
    the VLAN it carries untagged.

    Where the list decides (:data:`LIST_DECIDES`) the text says what
    the tree says: *stated*, whether or not it names the native VLAN.
    Where the untagged VLAN is stated beside the list
    (:data:`BESIDE_THE_LIST`) the trunk carries it whatever the
    allowed line names, so it is added to the list -- unless there
    is none, or the line names it already.  It goes before the first
    id greater than it, so that a list in rising order stays in
    rising order, and ``2-4094`` beside VLAN 1 is the list of every
    VLAN in the order :func:`...canonical.transforms.is_every_vlan`
    knows at sight.

    *stated* itself where nothing is added; a new list otherwise.

    Args:
        codec: A codec of :data:`NATIVE_VLAN_AND_THE_LIST`.
        stated: The ids the allowed line names (the platform's list
            for a trunk with no line, where it has none).
        untagged: The VLAN the text states untagged, or ``None``.

    Raises:
        KeyError: *codec* is not in the table.
    """
    if (
        NATIVE_VLAN_AND_THE_LIST[codec] == LIST_DECIDES
        or untagged is None or untagged in stated
    ):
        return stated
    at = next(
        (n for n, vid in enumerate(stated) if vid > untagged), len(stated),
    )
    return [*stated[:at], untagged, *stated[at:]]


def trunk_list_written(
    codec: str, allowed: Sequence[int], native: int | None,
) -> Sequence[int]:
    """The VLANs a renderer of *codec* names on a trunk's allowed
    line, for a trunk whose list is *allowed* and whose native VLAN
    is *native*.

    Where the list decides (:data:`LIST_DECIDES`): the list as it
    stands.  Where the untagged VLAN is stated beside the list
    (:data:`BESIDE_THE_LIST`): the list WITHOUT the native VLAN, so
    that no VLAN is on that line and on the line of the untagged
    VLAN.  A native VLAN the list does not hold is not carried, and
    there is nothing to take out.

    *allowed* itself where nothing is taken out; a new list
    otherwise.

    Args:
        codec: A codec of :data:`NATIVE_VLAN_AND_THE_LIST`.
        allowed: The trunk's ``trunk_allowed_vlans``.
        native: Its ``trunk_native_vlan``.

    Raises:
        KeyError: *codec* is not in the table.
    """
    if (
        NATIVE_VLAN_AND_THE_LIST[codec] == LIST_DECIDES
        or native is None or native not in allowed
    ):
        return allowed
    return [vid for vid in allowed if vid != native]


def unstated_trunk_list(codec: str, where: str = "") -> list[int]:
    """The allowed list of a trunk of *codec* that states none.

    Every id where the platform's trunk carries every VLAN by default,
    no id where it carries none (:data:`TRUNK_THAT_STATES_NO_LIST`).
    A new list each call; its entries are the shared ints of
    :data:`VLAN_IDS`.

    Every id is 4,094 entries that no character of the config stands
    for: a stanza of two lines makes them, and a config can hold as
    many such stanzas as it likes.  They are counted like the word
    ``all``, BEFORE the list is made, so that a config of many
    default trunks is refused at the limit on VLAN ids and not when
    its lists are already held.

    Args:
        codec: A codec of the table.
        where: The trunk, as the config names it, for a refusal
            to say which was the last one counted.

    Raises:
        KeyError: *codec* is not in the table.
        LimitExceeded: With this list the config names more VLAN
            ids than the limits allow.
    """
    if TRUNK_THAT_STATES_NO_LIST[codec] == TRUNK_ALL:
        charge(
            "vlan_ids", 4094,
            f"{_NO_LIST_IS_EVERY_VLAN}: {where}" if where else _NO_LIST_IS_EVERY_VLAN,
        )
        return vlan_id_run(1, 4094)
    return []


def unstated_native_vlan(codec: str, allowed: Sequence[int]) -> int | None:
    """The native VLAN a parser of *codec* puts for a TRUNK that
    states none and whose allowed list is *allowed*: the platform's
    default native VLAN (:data:`TRUNK_THAT_STATES_NO_NATIVE`) where
    it has one AND the list holds it, and ``None`` otherwise.

    Asked when the list has been resolved -- a trunk with no allowed
    line has the platform's list (:func:`unstated_trunk_list`) -- and
    before the port is put on the VLANs' member lists, so that the
    default VLAN has a record and the port is its untagged member.

    ``None`` where the list leaves the default out: nothing is
    filled in.  In the tree a native VLAN outside its list is
    *stated and not carried* (:func:`trunk_untagged_vlan`), and that
    is for a line the config HAS: the targets that state the
    untagged VLAN apart write a review line for it, and a trunk that
    stated nothing is owed none.  (What a switch does with a native
    VLAN its list leaves out is each vendor's to say, and for EOS it
    is not established: the vendor-reference page has the
    sentences.)

    ``None`` as well where the platform has no default (Junos), or
    has one that its text does not give the id of (OS10).

    The caller asks for a port that says it is a trunk, and for no
    other (:meth:`TrunksByName.settle`); and not for one whose text
    says its native VLAN is sent TAGGED
    (:meth:`TrunksByName.native_is_tagged`).

    Args:
        codec: A codec of the table.
        allowed: The port's ``trunk_allowed_vlans``, resolved.

    Raises:
        KeyError: *codec* is not in the table.
    """
    default = TRUNK_THAT_STATES_NO_NATIVE[codec]
    if isinstance(default, int) and default in allowed:
        return default
    return None


def switchport_trunk_native_value(
    codec: str, allowed: Sequence[int], native: int | None,
) -> int | None:
    """What follows ``switchport trunk native vlan`` on *codec*
    (IOS-XE, EOS, NX-OS), or ``None`` for no line.

    No line for a port with no native VLAN.  And no line for the VLAN
    that is the platform's own for a trunk with no line
    (:data:`TRUNK_THAT_STATES_NO_NATIVE`) where the port's list holds
    it: it is the default, no real capture of the three prints a
    line for it, and a trunk that stated none comes back as it went.
    By the vendors' sentences the port is the same with the line and
    without.

    A native VLAN the list does NOT hold is written whatever its id.
    It is stated and not carried (:func:`trunk_untagged_vlan`), and
    that is a statement of the config, which a default is not.

    Asked for a port that is written as a TRUNK.  The default is a
    trunk's, and a parser puts it back only for a port that says it
    is one (:meth:`TrunksByName.settle`): the IOS-XE renderer, which
    also writes the trunk lines of a port in another mode, writes
    the native line of such a port as it stands.

    (AOS-CX does not ask: its captures print ``vlan trunk native 1``
    on every trunk, and its renderer writes the line.)

    Args:
        codec: A codec of the table.
        allowed: The port's ``trunk_allowed_vlans``.
        native: Its ``trunk_native_vlan``.

    Raises:
        KeyError: *codec* is not in the table.
    """
    if (
        native == TRUNK_THAT_STATES_NO_NATIVE[codec]
        and trunk_untagged_vlan(allowed, native) is not None
    ):
        return None
    return native


def wants_no_untagged_vlan(
    codec: str, allowed: Sequence[int], native: int | None,
) -> bool:
    """Whether a TRUNK whose list is *allowed* and whose native VLAN
    is *native* is to be written *codec*'s form for "this trunk
    carries no VLAN untagged".

    So it is where the tree gives the port no native VLAN -- in a
    tree a parser made that is a port that carries no VLAN untagged
    -- and its list holds the platform's default native VLAN
    (:data:`TRUNK_THAT_STATES_NO_NATIVE`, where that is an id).
    Written no native line, such a trunk has the default as its
    native VLAN on the target, and carries it untagged: a VLAN the
    source carried tagged.

    Nothing is wanted where the list leaves the default out: the
    default native VLAN is then off the list, which is how a native
    VLAN that is not carried is written.  Nor where the tree states
    a native VLAN: a line for it is written, and the default is not
    in force.  Nor on a platform whose default is no id (Junos has
    none; OS10's is a setting of the switch, so its renderer writes
    ``no switchport access vlan`` for a trunk with no native VLAN
    whatever its list holds, unless another record of the interface
    states its untagged VLAN -- a native VLAN, or an access VLAN).
    AOS-S is in no table: its renderer asks VLAN by VLAN which names
    no line takes out of VLAN 1.

    Asked for a port written as a trunk, of an interface that has no
    native VLAN in any record (:func:`native_vlan_stated`).

    Args:
        codec: A codec of :data:`TRUNK_THAT_STATES_NO_NATIVE`.
        allowed: The port's ``trunk_allowed_vlans``.
        native: Its ``trunk_native_vlan``.

    Raises:
        KeyError: *codec* is not in the table.
    """
    default = TRUNK_THAT_STATES_NO_NATIVE[codec]
    return native is None and isinstance(default, int) and default in allowed


def native_vlan_stated(interfaces: Iterable[CanonicalInterface]) -> frozenset[str]:
    """The names of *interfaces* that have a native VLAN in some record.

    A config can hold the stanza of one interface more than once, and
    a parser that makes a record a stanza gives the native VLAN to the
    record whose stanza states it, and to no other
    (:meth:`TrunksByName.native_line`).  The other records of that
    interface have none, which says nothing of what the interface
    carries untagged: none of them is written the form for "no VLAN
    untagged" (:func:`wants_no_untagged_vlan`).
    """
    return frozenset(iface.name for iface in interfaces if iface.trunk_native_vlan is not None)


#: The modes a ``switchport`` renderer writes a mode line for.  A
#: port the tree has in another (``dynamic``, ``private-vlan``) is
#: written none, and is left in its target's own default mode.
_MODES_WRITTEN = frozenset({"access", "trunk"})


def every_native_vlan_tagged(
    codec: str, interfaces: Iterable[CanonicalInterface],
) -> bool:
    """Whether an output of *codec* whose ports are *interfaces* is
    to state that the native VLAN of EVERY trunk is sent tagged
    (``vlan dot1q tag native``, a line for the whole switch): the form
    for "this trunk carries no VLAN untagged" that Cisco documents for
    the Catalyst 9300 and the Nexus 9000 alike.  (Cisco's sentences,
    for it and for a Catalyst port's default mode, are on the vendor
    reference's VLAN page.)

    It is a statement about every trunk of the switch.  It is decided
    over the ports in trunk mode, the ports that hold trunk lines in
    no mode, and the ports in a mode that negotiates (``dynamic``) or
    another mode the renderer writes no line for; it is written where:

    * at least one trunk wants it (:func:`wants_no_untagged_vlan`);
    * no port in trunk mode carries a VLAN untagged
      (:func:`trunk_untagged_vlan`).  A trunk whose native VLAN its
      list leaves out carries none, and is no obstacle.  A LAG is a
      port like the others, and so is a member that repeats its
      LAG's lines; a member that states only its membership has no
      mode of its own, and is the LAG's;
    * no port is in a mode the renderer writes no line for, or holds
      trunk lines in no mode at all.  Such a port is left in its
      target's default mode -- on a Catalyst a port that can become
      a trunk -- and its tree says nothing of what it would carry
      untagged then: a native VLAN is filled in only for a port
      that says it is a trunk.

    A port in access mode is not looked at.  Nor is a port in no mode
    with no trunk line (a member that states only its LAG among
    them): it is not counted.  On a Catalyst such a port is in
    dynamic auto by default, and should it become a trunk the line
    tags its native VLAN as well.

    Where this is ``False`` and a trunk wants the form, the renderer
    writes a review line on that port instead.

    Args:
        codec: The renderer's codec (:data:`TRUNK_THAT_STATES_NO_NATIVE`).
        interfaces: Every port the output writes.

    Raises:
        KeyError: *codec* is not in the table.
    """
    interfaces = list(interfaces)
    stated = native_vlan_stated(interfaces)
    wanted = False
    for iface in interfaces:
        mode = iface.switchport_mode
        if mode == "trunk":
            allowed, native = iface.trunk_allowed_vlans, iface.trunk_native_vlan
            if trunk_untagged_vlan(allowed, native) is not None:
                return False
            wanted = wanted or (iface.name not in stated and wants_no_untagged_vlan(codec, allowed, native))
        elif mode is None:
            if iface.trunk_allowed_vlans or iface.trunk_native_vlan is not None:
                return False
        elif mode not in _MODES_WRITTEN:
            return False
    return wanted


#: ``vlan dot1q tag native``, a line of its own at the left margin,
#: with ``exclude control`` after it or without: the native VLAN of
#: every trunk of the config is sent tagged.  (``exclude control``
#: is on a Cisco page for the Nexus 7000: "Excludes untagged control
#: traffic on the native VLAN in a trunk."  The line with it is read
#: as the line for every trunk, the native VLAN's data traffic
#: tagged: that is netcanon's reading, not a Cisco sentence.  What it
#: does to control traffic is not modelled.)
_TAGS_EVERY_NATIVE_RE = re.compile(
    r"^vlan[ \t]+dot1q[ \t]+tag[ \t]+native(?:[ \t]+exclude[ \t]+control)?[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE,
)
#: ``switchport trunk native vlan tag``, under an interface: the
#: native VLAN of that trunk is sent tagged.
_TAGS_ITS_NATIVE_RE = re.compile(
    r"^\s*switchport\s+trunk\s+native\s+vlan\s+tag\s*$", re.IGNORECASE,
)
#: ``no switchport trunk native vlan tag``, under an interface: that
#: trunk's native VLAN is NOT sent tagged, the line for every trunk
#: notwithstanding.
_UNTAGS_ITS_NATIVE_RE = re.compile(
    r"^\s*no\s+switchport\s+trunk\s+native\s+vlan\s+tag\s*$", re.IGNORECASE,
)


def tags_every_native_vlan(raw: str) -> bool:
    """Whether the text of a config in the ``switchport`` grammar
    holds ``vlan dot1q tag native`` as a line of its own (or
    ``vlan dot1q tag native exclude control``).

    The words are looked for, and which platform has the line is not
    decided here.  A parser that finds them gives no trunk of the
    config a native VLAN (:meth:`TrunksByName.native_is_tagged`): a
    VLAN put as the port's native VLAN is one the tree reads as
    untagged, and the text says it is sent tagged -- except on a
    port whose own text says it is not (:func:`untags_its_native_vlan`).
    """
    return _TAGS_EVERY_NATIVE_RE.search(raw) is not None


def tags_its_native_vlan(line: str) -> bool:
    """Whether *line*, a line under an interface, is ``switchport
    trunk native vlan tag`` (:func:`tags_every_native_vlan` says
    what is made of it)."""
    return _TAGS_ITS_NATIVE_RE.match(line) is not None


def untags_its_native_vlan(line: str) -> bool:
    """Whether *line*, a line under an interface, is ``no switchport
    trunk native vlan tag``: the port's native VLAN is not sent
    tagged, whatever the line for every trunk says.  (Cisco documents
    it for the Catalyst 9500 High Performance models, as the way one
    trunk leaves ``vlan dot1q tag native``.)"""
    return _UNTAGS_ITS_NATIVE_RE.match(line) is not None


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
    says so beside it.  Its renderer hands over the list WITHOUT the
    native VLAN, :func:`trunk_list_written`: an OS10 allowed line
    names tagged VLANs.)

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
    Non-numeric tokens are skipped, and so is a token ``int`` cannot
    read (a superscript digit, more digits than it converts): a pasted
    config is not to end a job with an unexpected error.  The inverse
    is :func:`_coalesce_vlan_ids`.
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
        elif part.isdecimal():
            # ``isdecimal``, not ``isdigit``: a superscript two is a
            # digit that ``int`` refuses.  So is a run of more digits
            # than ``int`` converts, which ``isdecimal`` lets through.
            try:
                result.append(int(part))
            except ValueError:
                continue
    return result


def sole_vlan_id(text: str) -> int | None:
    """The id an id-list names when it names exactly ONE (``10``,
    ``10-10``), and ``None`` when it names none or several.

    What ``_parse_vlan_list(text)`` gives as a list of one, found
    without making the list and without counting it.  For a pass
    that only has to know whether a ``vlan <list>`` line opens a
    stanza of one VLAN, on a line that another pass expands: a line
    expanded twice is counted twice, and the number a refusal prints
    is then twice what the config names.
    """
    found: int | None = None
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                lo_i, hi_i = int(lo.strip()), int(hi.strip())
            except ValueError:
                continue
            lo_i, hi_i = max(1, lo_i), min(4094, hi_i)
            if lo_i > hi_i:
                continue
            if lo_i != hi_i or found is not None:
                return None
            found = lo_i
        elif part.isdecimal():
            try:
                vid = int(part)
            except ValueError:
                continue
            if found is not None:
                return None
            found = vid
    return found


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

    Raises:
        LimitExceeded: The ids this line makes -- a range, ``all``,
            ``except``, or the copy of *unstated* that a first
            ``add`` or ``remove`` starts from -- pass the limit on
            VLAN ids.  Counted before they are made.
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
    if existing is None:
        if unstated:
            # The platform's own list, which no character of this
            # line stands for: counted before it is copied.
            charge(
                "vlan_ids", len(unstated),
                f"{keyword} on a trunk with no earlier list, which starts "
                "from every VLAN",
            )
        base = list(unstated)
    else:
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
    line, and not the name it gives the record: the NX-OS parser
    reads ``interface port-channel 1`` and ``interface port-channel 2``
    as one name, ``port-channel`` (the IOS-XE parser did, before
    :func:`spaced_port_name`), and those are two interfaces.  (A
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

    And the record of a TRUNK is given its interface's NATIVE VLAN
    where the interface states none (:meth:`native_line`), in any
    stanza: the platform's default, where the record's list holds it
    (:func:`unstated_native_vlan`) -- where the interface SAYS it is
    a trunk, as for the platform's list.  The default is a trunk's.
    A port in another mode that keeps trunk lines (IOS-XE), and a
    port the parser took for a trunk from a trunk line alone (NX-OS,
    EOS), are given nothing from it: a native VLAN put there would
    be written as the untagged VLAN of a port whose text does not
    say it is a trunk.  It is given AFTER the list, since a trunk
    with no allowed line holds the default by the platform's list
    and not by a line.  And where the text says the native VLAN is
    sent tagged (:meth:`native_is_tagged`), a trunk is given NO native
    VLAN: not the default, and not one its interface states.  Such a
    trunk carries no VLAN untagged, which is what ``None`` says, and
    the tree has no field for the id of a native VLAN sent tagged.

    What this makes from few bytes is counted before it is made, as
    VLAN ids (:func:`...limits.charge`).  The platform's list is
    4,094 ids for a trunk whose stanza is two lines
    (:func:`unstated_trunk_list`), and for the first ``add`` or
    ``remove`` of an interface (:func:`merge_trunk_allowed`).  And a
    stanza that is met again is a record of its own with a list of
    its own: the interface's list copied for it (:meth:`settle`), or
    made anew by an ``add`` or a ``remove`` while the list it
    started from stays with the record of the earlier stanza
    (:meth:`allowed_line`).  A list a line states outright is
    counted where its ranges are read, and once: the ids of a line
    are read one time, whatever is made of them.

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
            EVERY_VLAN_ID if TRUNK_THAT_STATES_NO_LIST[codec] == TRUNK_ALL
            else ()
        )
        self._allowed: dict[str, list[int]] = {}
        # The same lines applied to an empty list, kept only for an
        # interface whose every allowed line so far is an ``add`` or
        # a ``remove``: the one case in which the platform's list is
        # part of what the lines come to.
        self._from_nothing: dict[str, list[int]] = {}
        self._said_trunk: set[str] = set()
        # The interfaces that state a native VLAN; and whether the
        # text says the native VLAN is sent tagged, by interface
        # (``None``: the line for every trunk of the config).
        self._native_stated: set[str] = set()
        self._native_tagged: dict[str | None, bool] = {}
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

    def native_line(self, key: str) -> None:
        """Interface *key* states its native VLAN, in this stanza or
        another (``switchport trunk native vlan N``; on AOS-CX
        ``vlan trunk native N``, with ``tag`` after it or without).

        For a parser that makes a record a stanza: the record of
        another stanza of the interface does not hold the native
        VLAN, and is owed no default.  A parser that keeps one
        record a name has it on the record."""
        self._native_stated.add(key)

    def native_is_tagged(self, key: str | None = None, tagged: bool = True) -> None:
        """The text says the native VLAN is sent TAGGED: on interface
        *key* (``switchport trunk native vlan tag``; on AOS-CX ``vlan
        trunk native N tag``), or, with no key, on every trunk of the
        config (``vlan dot1q tag native``).  With *tagged* false the
        interface's own text says it is NOT (``no switchport trunk
        native vlan tag``), and the line for every trunk does not
        overrule it.  What an interface says last stands.

        A trunk whose native VLAN is sent tagged is given no native
        VLAN (:meth:`settle`)."""
        self._native_tagged[key] = tagged

    def _sent_tagged(self, key: str) -> bool:
        """Whether the native VLAN of interface *key* is sent tagged:
        its own word, or else the line for every trunk."""
        return self._native_tagged.get(key, self._native_tagged.get(None, False))

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

        Raises:
            LimitExceeded: What the line makes passes the limit on
                VLAN ids.
        """
        before = self._allowed.get(key)
        word = remainder.split(None, 1)[0].lower() if remainder.strip() else ""
        relative = word in ("add", "remove")
        # ``add`` and ``remove`` copy the list they start from.
        # Within a stanza the list a line started from is let go
        # when the line has been applied.  A list stated in an
        # EARLIER stanza is not: it stays with the record made of
        # that stanza, and this line makes another beside it -- so
        # a stanza of two lines, met again and again, is its
        # interface's whole list each time.  Counted first.
        again = relative and key not in self._in_this_stanza
        said = f"{_STANZA_MET_AGAIN}: {remainder.strip()}"
        if again and before:
            charge("vlan_ids", len(before), said)
        # The ids of the line are read ONCE, for both lists below.
        # Read twice a range is counted twice, and the number a
        # refusal prints is then more than the config names.
        read: dict[str, list[int]] = {}

        def ids_of(text: str) -> list[int]:
            if text not in read:
                read[text] = self._parse_ids(text)
            return read[text]

        after = self._allowed[key] = merge_trunk_allowed(
            before, remainder, parse_ids=ids_of, unstated=self._platform,
        )
        self._in_this_stanza.add(key)
        if self._platform:
            if relative and (before is None or key in self._from_nothing):
                started = self._from_nothing.get(key)
                if again and started:
                    charge("vlan_ids", len(started), said)
                self._from_nothing[key] = merge_trunk_allowed(
                    started, remainder, parse_ids=ids_of,
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
        its interface, and then -- a trunk whose interface says it is
        one -- its native VLAN where the interface states none (the
        class docstring says which).  Called once,
        when every stanza has been read: a later stanza can state the
        list of an interface, or its native VLAN, or say that it is a
        trunk, after a record of it was made.

        No two records are given the same list object.  A list made
        here -- the platform's, for a trunk that states none, or a
        copy for the record of a stanza that is met again -- is
        counted before it is made.

        Raises:
            LimitExceeded: The lists pass the limit on VLAN ids.
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
                    allowed = unstated_trunk_list(self._codec, iface.name)
            if id(allowed) in handed:
                if allowed:
                    charge(
                        "vlan_ids", len(allowed),
                        f"{_STANZA_MET_AGAIN}: {iface.name}",
                    )
                allowed = list(allowed)
            handed.add(id(allowed))
            iface.trunk_allowed_vlans = allowed
            if iface.switchport_mode == "trunk" and self._sent_tagged(key):
                # Its native VLAN is sent tagged: it carries no VLAN
                # untagged, whatever id its text states.
                iface.trunk_native_vlan = None
            # The default native VLAN is a trunk's: for a record
            # that is a trunk, of an interface that says it is one
            # (the test made above for the platform's list).
            elif (
                iface.switchport_mode == "trunk"
                and key in self._said_trunk
                and iface.trunk_native_vlan is None
                and key not in self._native_stated
            ):
                iface.trunk_native_vlan = unstated_native_vlan(
                    self._codec, allowed,
                )


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
    interfaces: Iterable[Any], lead: str, *, codec: str, trunks_only: bool,
) -> None:
    """Count the lines that carry a port's allowed-VLAN list, BEFORE a
    renderer writes any of them.

    IOS-XE and EOS take the list as ``lead`` and every id, so a tree
    whose lists hold four million ids is nineteen megabytes of those
    lines.  The lists' lengths say so before the first character: a
    renderer calls this once, ahead of its output.  What is charged is
    the length of those lines and nothing else, so it is never more
    than the output is.

    A list means what it says, and the count follows what is then
    written (:func:`switchport_trunk_allowed_value`).  On a TRUNK the
    list that is the platform's own for a trunk with no line -- every
    VLAN, for both of these -- is no line, and nothing is counted
    for that port; no VLAN is the line that says ``none``; any other
    list is its ids.  On a port that is not a trunk a list is
    written by IOS-XE alone, and every id is the word ``all`` there.

    Args:
        interfaces: The interfaces the renderer is about to write.
        lead: The line up to the first id, as the renderer writes it.
        codec: The renderer's codec, a key of
            :data:`TRUNK_THAT_STATES_NO_LIST`.
        trunks_only: The renderer writes the line for a port in trunk
            mode only (EOS); otherwise for any port with a list.

    Raises:
        LimitExceeded: Those lines alone are longer than the output
            may be (:mod:`netcanon.migration.limits`).
        KeyError: *codec* is not in the table.
    """
    unwritten = TRUNK_THAT_STATES_NO_LIST[codec]
    total = ports = 0
    for iface in interfaces:
        ids = iface.trunk_allowed_vlans
        if iface.switchport_mode == "trunk":
            says = trunk_list_says(ids)
            if says == unwritten:
                continue
            value = len("none") if says == TRUNK_NONE else joined_ids_length(ids)
        elif trunks_only or not ids:
            continue
        else:
            value = len("all") if is_every_vlan(ids) else joined_ids_length(ids)
        total += len(lead) + value + 1
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


# ---------------------------------------------------------------------------
# Cisco header lines: a type and its number as two words, and keywords
# ---------------------------------------------------------------------------

#: A word that follows ``interface`` on a Cisco-shaped header line
#: and is no interface type.
#:
#: * ``interface preconfigure TenGigE0/0/0/12`` (IOS XR) holds
#:   configuration for an interface the system does not have until
#:   its line card is put in.
#: * ``interface range ...`` configures several interfaces at once.
#:   IOS does not print it in ``show running-config``; a text written
#:   by hand, or one from another system, can hold it.  Its body is
#:   in no output, and its row says so.
#: * ``interface breakout 1/1/49 map 100g-1x`` splits a port into
#:   lanes.  It is OS10's grammar, in a text these parsers can be
#:   handed, and it states nothing on any interface.
#:
#: None of the three is a name, and none is joined to what follows
#: it (:func:`spaced_port_name`).
NOT_AN_INTERFACE_TYPE = frozenset({"breakout", "preconfigure", "range"})

#: The one of them whose stanza the device holds and does not run.
_HELD_KEYWORD = "preconfigure"

#: The first word after ``interface`` on a header line.
_HEADER_WORD_RE = re.compile(r"^interface\s+(\S+)", re.IGNORECASE)


def spaced_port_name(first: str, second: str | None) -> str:
    """The interface name that two words of a Cisco line spell.

    IOS and IOS XR read ``interface ethernet 1/11`` and ``ip route
    0.0.0.0 0.0.0.0 loopback 66`` as ``Ethernet1/11`` and
    ``Loopback66``: a type and its number may be written apart.
    ``show running-config`` prints them together, so the spaced form
    is in pasted and documentation-shaped text.  Read a word at a
    time, the name was the TYPE: two stanzas made one interface
    called ``ethernet``, and in a route the interface's number was
    taken for the distance.

    The two words are one name when *first* is a type on its own (it
    ends in a letter, as a type does and a whole name does not) and
    *second* begins with a digit.  What follows a whole name is a
    keyword (``point-to-point``, ``l2transport``), which is left
    where it is.  The letters stay as the config has them.

    Args:
        first: The word in the place of a name.
        second: The word after it, or ``None`` at the end of a line.

    Returns:
        ``first + second`` when the two are one name, else *first*.
        A word of :data:`NOT_AN_INTERFACE_TYPE` is returned alone.
    """
    if (
        second
        and first[-1:].isalpha()
        and second[0].isdigit()
        and first.lower() not in NOT_AN_INTERFACE_TYPE
    ):
        return first + second
    return first


def without_keyword_stanzas(raw: str) -> tuple[str, list[str]]:
    """*raw* without the ``interface`` stanzas a keyword opens, and
    the header line of each.

    A header whose first word is one of :data:`NOT_AN_INTERFACE_TYPE`
    names no interface a record can be made for.  Read as a name, the
    keyword became an interface of the tree and was written into every
    target's output.  The whole stanza is taken out before any reader
    sees it -- its body with it, so that a ``bundle id`` or an
    ``encapsulation dot1q`` inside binds nothing -- and its header is
    returned for ``dropped_tier3_sections``
    (:func:`keyword_stanza_rows`): the stanza is not translated, and
    the list says which.  A stanza ends where the interface readers
    end one, at the next line that is not indented: a line that
    begins with a space or a tab is of the body, and so is an empty
    line.  The keyword is read in any letter case, as ``interface``
    is.

    Returns:
        ``(text, headers)``: *raw* itself when it has no such stanza;
        the header lines as written, white space apart, in the order
        met and once each.
    """
    lines = raw.splitlines(keepends=True)
    kept: list[str] | None = None
    headers: dict[str, None] = {}
    inside = False
    for at, line in enumerate(ticked(lines)):
        if inside and line[:1].isspace():
            continue
        inside = False
        word = _HEADER_WORD_RE.match(line)
        if word and word.group(1).lower() in NOT_AN_INTERFACE_TYPE:
            if kept is None:
                kept = lines[:at]
            headers[" ".join(line.split())] = None
            inside = True
            continue
        if kept is not None:
            kept.append(line)
    if kept is None:
        return raw, []
    return "".join(kept), list(headers)


def keyword_stanza_rows(headers: Iterable[str]) -> list[str]:
    """The rows of ``dropped_tier3_sections`` for the stanzas
    :func:`without_keyword_stanzas` took out.

    The keywords are two different things to say.  ``interface
    preconfigure <name>`` is a statement the device HOLDS AND DOES
    NOT RUN, configuration for an interface it does not have: its row
    is a left-out row (``_tier3_detection.left_out_rows``), which
    shows the stanza's path and nothing of its body, is one of a
    bounded number, and is not taken for a sign that the text was a
    config -- a text that is nothing but such stanzas translated
    nothing, and its job is not ``completed``.  ``interface range
    ...`` and ``interface breakout ...`` are in force where they
    were typed and are not translated: the row of each is its header
    line, a section like any other the output does not have.

    Args:
        headers: The header lines, as :func:`without_keyword_stanzas`
            returns them.

    Returns:
        The left-out rows, then the header lines that are sections.
    """
    held: list[tuple[str, list[str]]] = []
    sections: list[str] = []
    for header in headers:
        words = header.split()
        if words[1].lower() == _HELD_KEYWORD:
            held.append((_HELD_KEYWORD, [words[0].lower(), *words[2:]]))
        else:
            sections.append(header)
    return [*left_out_rows(held, rest=_HELD_KEYWORD), *sections]


#: The tags of a routed sub-interface, as its tag statement states them
#: when the statement is read whole: the outer 802.1Q tag, and the inner
#: one or ``None``.
Tags = tuple[int, int | None]


def a_tag(word: str) -> int | None:
    """*word* as one 802.1Q VLAN id (1 to 4094, in ASCII digits), else
    ``None``.

    A word that is not one id -- ``any``, a range, a list, a keyword --
    is not read as the id it begins with.
    """
    if not (word.isascii() and word.isdigit()) or len(word) > 4:
        return None
    vid = int(word)
    return vid if 1 <= vid <= 4094 else None


def second_dot1q_tags(statement: str) -> Tags | None:
    """The tags of a Cisco ``encapsulation dot1q`` statement, read whole.

    ``encapsulation dot1Q <outer>`` and ``encapsulation dot1Q <outer>
    second-dot1q <inner>`` (IOS-XE 17, "IEEE 802.1Q-in-Q VLAN Tag
    Termination"; IOS XR, "Configuring 802.1Q VLAN Interfaces").  Every
    other form is ``None``: ``second-dot1q any``, a range or a list of
    inner tags (an "ambiguous" sub-interface, in Cisco's word), and
    ``native`` -- each a statement the tree has no form for.  Read for
    its first value, an ambiguous sub-interface was a sub-interface of
    the outer tag alone on every target, in jobs that said
    ``completed``.

    Args:
        statement: The line, white space at its ends apart.
    """
    words = statement.split()
    if [w.lower() for w in words[:2]] != ["encapsulation", "dot1q"]:
        return None
    if len(words) == 3:
        outer = a_tag(words[2])
        return None if outer is None else (outer, None)
    if len(words) == 5 and words[3].lower() == "second-dot1q":
        outer, inner = a_tag(words[2]), a_tag(words[4])
        if outer is not None and inner is not None:
            return (outer, inner)
    return None


def unread_tags_row(where: str, statement: str) -> str:
    """The row of ``dropped_tier3_sections`` for a sub-interface left
    out because its tag statement is not read whole.

    The sub-interface is in force on the source and is not in the
    output, so the row is a section's: where it is, and the statement.
    A tag statement holds VLAN ids and keywords, nothing secret.
    """
    return (
        f"{' '.join(where.split())}: {' '.join(statement.split())} -- not "
        f"one 802.1Q tag and at most one inner tag, so the sub-interface "
        f"is not translated"
    )


def without_unread_tags(
    raw: str,
    is_tag_statement: Callable[[str], bool],
    tags_of: Callable[[str], Tags | None],
) -> tuple[str, list[str]]:
    """*raw* without each ``interface`` stanza whose tag statement is
    not read whole, and a row for each.

    A tag statement is read whole or not at all.  The readers took the
    first id of one (``encapsulation dot1Q 2234 second-dot1q 15`` was
    VLAN 2234, and so were the five other units of a committed capture
    on that outer tag), and an inner tag that is a range, a list or
    ``any`` has no form in the tree.  So a stanza whose own tag
    statement *tags_of* cannot read is taken out before any reader sees
    it -- its addresses and its VRF with it, since a sub-interface
    written with fewer tags than it matches is another sub-interface --
    and :func:`unread_tags_row` says which.

    A stanza ends where :func:`without_keyword_stanzas` ends one.  Its
    own lines are at the indent of its first body line; a line indented
    deeper is a submode's (an IOS-XE ``service instance`` has an
    ``encapsulation`` of its own) and is not the stanza's statement.

    Args:
        raw: The config text.
        is_tag_statement: Whether a line, white space at its ends apart,
            is a tag statement of the platform.
        tags_of: Its tags, read whole, or ``None``.

    Returns:
        ``(text, rows)``: *raw* itself when no stanza is taken out.
    """
    kept: list[str] = []
    rows: list[str] = []
    stanza: list[str] = []
    depth: int | None = None
    unread = ""

    def close() -> None:
        if unread:
            rows.append(unread_tags_row(stanza[0], unread))
        else:
            kept.extend(stanza)

    for line in ticked(raw.splitlines(keepends=True)):
        if stanza and line[:1].isspace():
            stanza.append(line)
            statement = line.strip()
            if unread or not statement:
                continue
            width = len(line) - len(line.lstrip())
            if depth is None:
                depth = width
            if (
                width == depth
                and is_tag_statement(statement)
                and tags_of(statement) is None
            ):
                unread = statement
            continue
        if stanza:
            close()
            stanza, depth, unread = [], None, ""
        if _HEADER_WORD_RE.match(line):
            stanza = [line]
        else:
            kept.append(line)
    if stanza:
        close()
    if not rows:
        return raw, []
    return "".join(kept), rows
