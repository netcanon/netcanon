"""A value is written as ONE value of the place it goes, or not at all.

A renderer puts a value of the tree into its line as it stands.  Most
CLIs read a line a word at a time, so a value that holds white space is
two words there, and the second is read as whatever that place of the
grammar takes next: a keyword, an argument, or nothing (the line is
refused).  The second reading is the dangerous one.  On NX-OS
``snmp-server community public rw`` is a READ-WRITE community
``public``; on EOS the second word of a community is read as an ACL
name; a password ``secret scrypt`` sets the password ``secret``.  The
values come from another vendor's config, which may quote a value with
white space (FortiOS, RouterOS, Junos, VyOS, AOS-S) or hold one as
element text (OPNsense, IOS-XE over NETCONF), and from text nobody
vouches for.

Which places of which grammar read one word, and which read the rest of
the line or a quoted string, is a fact about the vendor, and none of the
word-at-a-time CLIs documents a quoted form for a credential (the
vendor references are in
``docs/reviews/2026-10-20-values-with-white-space/``).  So a SECRET
-- a password, an SNMP community, an SNMPv3 passphrase, an FHRP
authentication key -- or the name of an account that holds white space
is not written there, and is never altered to fit (a secret with a space
replaced is another secret).  The renderer leaves the record out with
the granularity the credential rules set (a local user whole, an SNMPv3
user with every line composing it, a community with every trap host
that would carry it, an FHRP authentication line alone), and writes a
review line that names the place and never the secret.

A grammar that quotes with no escape (AOS-S: HPE documents escapes for
``banner motd`` only) has the same hole one character over: a ``"`` in
a value ends the quoted string, and the rest of the value is CLI words.
:func:`breaks_its_quotes` asks that question.

RADIUS keys are not here yet: their lines are being rewritten for the
stored forms of a key, and are taken up after that change.

What is not a secret follows the same rule, by what it is
(:func:`one_value_tree`, which a renderer calls on the tree before it
writes a line):

* a NAME that labels -- the host name, a VLAN's name, a VRF's name, a
  route's name -- is written as :func:`one_word` makes it (``_`` for
  each run of white space, ``'`` for a ``"``), at every place it goes
  at once: a VRF is renamed together with every interface, route and
  EVPN prefix in it, and a name that would then be another VRF's is
  told apart.  The output says so;
* an ADDRESS -- a server, a domain, a gateway -- is never altered (an
  address with a space replaced is another address): it is left out
  and said, and a static route whose next hop is left out goes WHOLE,
  since a route that keeps its destination without its gateway is
  another route;
* a TEXT -- a description, an SNMP location or contact -- is written
  as it stands where the vendor documents that its place reads to the
  end of the line; where no page says so, it is written with a review
  line beside it; and where the target quotes with no escape, a ``"``
  in it is written as ``'`` and said.

A review line names the place and never quotes the value: a value
holds what its source config held, a comment's terminator included.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


def splits(value: str | None) -> bool:
    """Whether *value* would not stand as one word of a word-at-a-time
    CLI: it holds white space, which ends a word, or a ``"``, which
    NX-OS reads as the start of a quoted string and IOS-XE forbids in
    a user name ("Spaces and quotation marks are not allowed").

    Any character :meth:`str.isspace` takes counts, not only the space
    and the tab: what a device's reader takes for a separator is not
    documented character by character, and a value that is refused for
    a no-break space is the safe side.
    """
    return bool(value) and (
        '"' in value or any(ch.isspace() for ch in value)
    )


def breaks_its_quotes(value: str | None) -> bool:
    """Whether *value* cannot stand between double quotes on a grammar
    that documents no escape: it holds a ``"`` (which ends the string)
    or white space other than the space (which a reader may take for
    the end of the line or of a word)."""
    if not value:
        return False
    return '"' in value or any(ch.isspace() and ch != " " for ch in value)


def left_out(what: str, target_label: str) -> str:
    """The text of the review line for a record left out by this rule.

    *what* names the record (``username alice``, ``an SNMP community``)
    and must not hold a secret: the line is written into the output,
    and the value is the thing that could not be written.
    """
    return (
        f"{what} -- review: a value of it holds white space or a quote, "
        f"which {target_label} does not read as one value; it is left "
        f"out, re-create it on the device"
    )


def one_word(value: str) -> str:
    """A name that labels, as one word: each run of white space is
    ``_`` and each ``"`` is ``'``.  A name that is nothing else is
    ``_``, never empty (an empty VRF name is the global table)."""
    return "_".join(value.replace('"', "'").split()) or "_"


#: The fields :func:`one_value_tree` knows, by kind.
NAMES = (
    "hostname", "vlans[].name", "routing_instances[].name",
    "static_routes[].description",
)
ADDRESSES = (
    "domain", "ntp_servers", "syslog_servers", "dns_servers",
    "static_routes[].gateway", "dhcp_servers[].domain_name",
    "dhcp_servers[].gateway", "dhcp_servers[].dns_servers",
)
TEXTS = (
    "interfaces[].description", "vlans[].description",
    "routing_instances[].description", "snmp.location", "snmp.contact",
)
_LISTS = ("ntp_servers", "syslog_servers", "dns_servers")
_WHAT_A_LIST_HOLDS = {
    "ntp_servers": "an NTP server", "syslog_servers": "a syslog server",
    "dns_servers": "a DNS server",
}


def _who(group: str, record: Any) -> str:
    """How a record is named in a review line: by a value of it that is
    one word, or by what it is."""
    if group == "vlans":
        return f"VLAN {record.id}"
    attr, named, unnamed = {
        "interfaces": ("name", "interface {}", "an interface"),
        "routing_instances": ("name", "VRF {}", "a VRF"),
        "static_routes": ("destination", "the route to {}", "a static route"),
        "dhcp_servers": ("interface", "the DHCP pool on {}", "a DHCP pool"),
    }[group]
    value = getattr(record, attr)
    return named.format(value) if value and not splits(value) else unnamed


def _places(tree: Any, field: str) -> list[tuple[Any, str, str]]:
    """``(record, attribute, how the place is named)`` for each value of
    a field that holds one string a record."""
    if field in ("hostname", "domain"):
        noun = "host" if field == "hostname" else "domain"
        return [(tree, field, f"the {noun} name")]
    if field.startswith("snmp."):
        attr = field[len("snmp."):]
        return [(tree.snmp, attr, f"the SNMP {attr}")] if tree.snmp else []
    group, attr = field.split("[].")
    noun = attr.replace("_", " ")
    return [
        (record, attr, f"the {noun} of {_who(group, record)}")
        for record in getattr(tree, group)
    ]


def _values(tree: Any, field: str) -> list[str]:
    if field in _LISTS:
        return list(getattr(tree, field))
    if field == "dhcp_servers[].dns_servers":
        return [s for pool in tree.dhcp_servers for s in pool.dns_servers]
    if field == "routing_instances[].name":
        return [r.name for r in tree.routing_instances] + [
            r.vrf for r in (
                *tree.interfaces, *tree.static_routes, *tree.evpn_type5_routes)
        ]
    return [getattr(rec, attr) or "" for rec, attr, _ in _places(tree, field)]


def _white(value: str | None) -> bool:
    return bool(value) and any(ch.isspace() for ch in value)


def one_value_tree(
    tree: Any,
    target_label: str,
    *,
    names: Iterable[str] = (),
    addresses: Iterable[str] = (),
    unread_text: Iterable[str] = (),
    no_escape: Iterable[str] = (),
    test: Callable[[str | None], bool] = splits,
) -> tuple[Any, list[str]]:
    """The tree a renderer writes, with each value one value of its place.

    Args:
        tree: The :class:`CanonicalIntent` to render.  It is not changed.
        target_label: The platform's name, for the review lines.
        names: Fields of :data:`NAMES` the target writes as one word: a
            value *test* refuses is written as :func:`one_word` makes
            it, at every place it goes.
        addresses: Fields of :data:`ADDRESSES` the target writes as one
            word: a value *test* refuses is left out (a static route
            whose gateway it is, whole).
        unread_text: Fields of :data:`TEXTS` the target writes where no
            page says the place reads to the end of the line: a value
            with white space is written as it stands and said, and a
            ``"`` in it is written ``'``.
        no_escape: Fields the target writes between quotes it has no
            escape for: a ``"`` in the value is written ``'``.
        test: Whether a value does not stand as one value of the place:
            :func:`splits` for a bare word, :func:`breaks_its_quotes`
            for a place the target quotes.

    Returns:
        The tree to write (the same object when nothing is changed, a
        copy otherwise) and the text of each review line, without the
        target's comment marker, in the order the fields are given.
    """
    names, addresses = tuple(names), tuple(addresses)
    unread_text, no_escape = tuple(unread_text), tuple(no_escape)
    if not (
        any(test(v) for f in (*names, *addresses) for v in _values(tree, f))
        or any(
            _white(v) or '"' in v
            for f in unread_text for v in _values(tree, f))
        or any('"' in v for f in no_escape for v in _values(tree, f))
    ):
        return tree, []
    work = tree.model_copy(deep=True)
    said: list[str] = []
    one = f"which {target_label} does not read as one word"
    for field in names:
        if field == "routing_instances[].name":
            said += _rename_vrfs(work, test, one)
            continue
        for record, attr, place in _places(work, field):
            if test(getattr(record, attr)):
                setattr(record, attr, one_word(getattr(record, attr)))
                said.append(
                    f"{place} -- review: it holds white space or a quote, "
                    f"{one}; each run of white space is written _ and each "
                    f"double quote '")
    for field in addresses:
        said += _leave_out(work, field, test, target_label)
    for field in unread_text:
        for record, attr, place in _places(work, field):
            value = getattr(record, attr) or ""
            if '"' in value:
                setattr(record, attr, value.replace('"', "'"))
                said.append(
                    f"{place} -- review: it holds a double quote, which "
                    f"{target_label} is not documented to read in this "
                    f"place; each is written '")
            if _white(value):
                said.append(
                    f"{place} -- review: it holds white space, and no "
                    f"{target_label} page found says this place reads to "
                    f"the end of the line; it is written as it stands, "
                    f"check it on the device")
    for field in no_escape:
        for record, attr, place in _places(work, field):
            value = getattr(record, attr) or ""
            if '"' in value:
                setattr(record, attr, value.replace('"', "'"))
                said.append(
                    f"{place} -- review: it holds a double quote, which "
                    f"{target_label} cannot write between its quotes; "
                    f"each is written '")
    return work, said


def _rename_vrfs(
    work: Any, test: Callable[[str | None], bool], one: str,
) -> list[str]:
    """Rename each VRF *test* refuses, with every reference to it, to a
    name no other VRF has."""
    referrers = (*work.interfaces, *work.static_routes, *work.evpn_type5_routes)
    names = [r.name for r in work.routing_instances] + [
        r.vrf for r in referrers if r.vrf
    ]
    taken = {n for n in names if not test(n)}
    renamed: dict[str, str] = {}
    for old in names:
        if old in renamed or not test(old):
            continue
        new = base = one_word(old)
        count = 2
        while new in taken:
            new = f"{base}_{count}"
            count += 1
        taken.add(new)
        renamed[old] = new
    for record in work.routing_instances:
        record.name = renamed.get(record.name, record.name)
    for record in referrers:
        record.vrf = renamed.get(record.vrf, record.vrf)
    return [
        f"the name of a VRF -- review: it holds white space or a quote, "
        f"{one}; each run of white space is written _ and each double "
        f"quote ', at every place the VRF is named"
        + ("" if new == one_word(old) else
           ", with a number after it, since another VRF has that name")
        for old, new in renamed.items()
    ]


def _leave_out(
    work: Any, field: str, test: Callable[[str | None], bool], target_label: str,
) -> list[str]:
    """Leave out each value of an address field *test* refuses."""
    tail = (
        f"an address that holds white space or a quote, which "
        f"{target_label} does not read as one value; it is left out, "
        f"re-create it on the device")
    if field in _LISTS:
        kept = [v for v in getattr(work, field) if not test(v)]
        gone = len(getattr(work, field)) - len(kept)
        setattr(work, field, kept)
        return [f"{_WHAT_A_LIST_HOLDS[field]} -- review: {tail}"] * gone
    if field == "dhcp_servers[].dns_servers":
        said: list[str] = []
        for pool in work.dhcp_servers:
            kept = [v for v in pool.dns_servers if not test(v)]
            said += [
                f"a DNS server of {_who('dhcp_servers', pool)} -- review: "
                f"{tail}"
            ] * (len(pool.dns_servers) - len(kept))
            pool.dns_servers = kept
        return said
    if field == "static_routes[].gateway":
        whole = tail.replace("it is left out", "the route is left out whole")
        said = [
            f"{_who('static_routes', route)} -- review: its gateway is {whole}"
            for route in work.static_routes if test(route.gateway)
        ]
        work.static_routes = [
            r for r in work.static_routes if not test(r.gateway)
        ]
        return said
    said = []
    for record, attr, place in _places(work, field):
        if test(getattr(record, attr)):
            setattr(record, attr, "")
            said.append(f"{place} -- review: {tail}")
    return said
