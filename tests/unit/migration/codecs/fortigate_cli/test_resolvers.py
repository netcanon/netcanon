"""The resolvers of ``config system dns``: each address family in slots
of its own, and what no slot takes left out and said.

Fortinet's CLI reference (7.6.6, ``config system dns``) gives FortiOS
two IPv4 slots, ``primary`` and ``secondary``, and two IPv6 slots,
``ip6-primary`` and ``ip6-secondary``; each defaults to the unspecified
address, which a printout of the whole configuration shows.  The
renderer wrote the first two resolvers of the tree into ``primary`` and
``secondary`` whatever their family, so an IPv6 resolver went into a
slot that takes an IPv4 address, and a third resolver was left out with
nothing said.  The parser read ``primary`` and ``secondary`` only, and
read a slot printed as ``0.0.0.0`` as a resolver.

What each output should hold is written out by hand below, and read
from the text by a reader this module owns.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.fortigate_cli import FortiGateCLICodec

pytestmark = pytest.mark.unit


def _dns_block(text: str) -> tuple[dict[str, str], int]:
    """The ``set`` lines of the ``config system dns`` block of *text*,
    slot to value, and how many review lines the block holds."""
    slots: dict[str, str] = {}
    reviews = 0
    inside = False
    for line in text.splitlines():
        if line == "config system dns":
            inside = True
            continue
        if not inside:
            continue
        if line == "end":
            break
        words = line.split()
        if words[:2] == ["#", "review:"]:
            reviews += 1
        elif words and words[0] == "set" and len(words) == 3:
            assert words[1] not in slots, line
            slots[words[1]] = words[2]
    return slots, reviews


def _check(text: str, slots: dict[str, str], reviews: int, absent: tuple[str, ...]) -> None:
    """*text* holds exactly *slots* among the resolver slots, *reviews*
    review lines in its DNS block, and none of the values *absent*."""
    written, said = _dns_block(text)
    resolvers = {
        slot: value for slot, value in written.items()
        if slot in ("primary", "secondary", "ip6-primary", "ip6-secondary")
    }
    assert resolvers == slots
    assert said == reviews
    for value in absent:
        assert value not in text, value


#: Resolvers of a tree, the slots each lands in, how many review lines
#: are written, and the values the output must not hold -- by hand.
CASES = [
    pytest.param(
        ["192.0.2.53", "192.0.2.54"],
        {"primary": "192.0.2.53", "secondary": "192.0.2.54"}, 0, (),
        id="two-ipv4",
    ),
    pytest.param(
        ["2001:db8::53", "2001:db8::54"],
        {"ip6-primary": "2001:db8::53", "ip6-secondary": "2001:db8::54"}, 0, (),
        id="two-ipv6",
    ),
    pytest.param(
        ["192.0.2.53", "2001:db8::53", "192.0.2.54"],
        {
            "primary": "192.0.2.53", "secondary": "192.0.2.54",
            "ip6-primary": "2001:db8::53",
        },
        1, (),
        id="an-ipv6-between-two-ipv4",
    ),
    pytest.param(
        [
            "192.0.2.1", "192.0.2.2", "192.0.2.3",
            "2001:db8::1", "2001:db8::2", "2001:db8::3",
        ],
        {
            "primary": "192.0.2.1", "secondary": "192.0.2.2",
            "ip6-primary": "2001:db8::1", "ip6-secondary": "2001:db8::2",
        },
        2, ("192.0.2.3", "2001:db8::3"),
        id="three-of-each",
    ),
    pytest.param(
        ["ns.example.net", "0.0.0.0", "::", "192.0.2.53"],
        {"primary": "192.0.2.53"}, 1, ("ns.example.net",),
        id="no-address-and-none",
    ),
]


@pytest.mark.parametrize(("servers", "slots", "reviews", "absent"), CASES)
def test_each_resolver_goes_in_a_slot_of_its_family(
    servers: list[str], slots: dict[str, str], reviews: int, absent: tuple[str, ...],
) -> None:
    out = FortiGateCLICodec().render(CanonicalIntent(dns_servers=servers))
    _check(out, slots, reviews, absent)


@pytest.mark.parametrize(("servers", "slots", "reviews", "absent"), CASES)
def test_what_is_written_is_read_back(
    servers: list[str], slots: dict[str, str], reviews: int, absent: tuple[str, ...],
) -> None:
    codec = FortiGateCLICodec()
    back = codec.parse(codec.render(CanonicalIntent(dns_servers=servers)))
    order = ("primary", "secondary", "ip6-primary", "ip6-secondary")
    assert back.dns_servers == [slots[slot] for slot in order if slot in slots]


def test_the_check_fails_for_an_ipv6_resolver_in_an_ipv4_slot() -> None:
    """The output the renderer wrote before: the second resolver of the
    tree in ``secondary`` whatever its family, the third left out."""
    before = (
        "config system dns\n"
        "    set primary 192.0.2.53\n"
        "    set secondary 2001:db8::53\n"
        "end\n"
    )
    with pytest.raises(AssertionError):
        _check(before, {
            "primary": "192.0.2.53", "secondary": "192.0.2.54",
            "ip6-primary": "2001:db8::53",
        }, 1, ())


def test_the_check_fails_for_a_resolver_left_out_unsaid() -> None:
    unsaid = (
        "config system dns\n"
        "    set primary 192.0.2.1\n"
        "    set secondary 192.0.2.2\n"
        "end\n"
    )
    with pytest.raises(AssertionError):
        _check(unsaid, {"primary": "192.0.2.1", "secondary": "192.0.2.2"}, 1, ())


def test_the_check_fails_for_a_value_named_in_the_output() -> None:
    named = (
        "config system dns\n"
        "    # review: ns.example.net is left out\n"
        "    set primary 192.0.2.53\n"
        "end\n"
    )
    with pytest.raises(AssertionError):
        _check(named, {"primary": "192.0.2.53"}, 1, ("ns.example.net",))


def test_the_four_slots_are_read_in_the_order_of_the_tree() -> None:
    """Printed in another order, the slots are read IPv4 first, each
    family's primary before its secondary."""
    text = (
        "config system dns\n"
        "    set ip6-secondary 2001:db8::54\n"
        "    set secondary 192.0.2.54\n"
        "    set ip6-primary 2001:db8::53\n"
        "    set primary 192.0.2.53\n"
        "end\n"
    )
    assert FortiGateCLICodec().parse(text).dns_servers == [
        "192.0.2.53", "192.0.2.54", "2001:db8::53", "2001:db8::54",
    ]


def test_a_slot_that_holds_its_default_holds_no_resolver() -> None:
    """A printout of the whole configuration shows every slot, and an
    empty one as the unspecified address."""
    text = (
        "config system dns\n"
        "    set primary 192.0.2.53\n"
        "    set secondary 0.0.0.0\n"
        "    set ip6-primary ::\n"
        "    set ip6-secondary ::\n"
        "end\n"
    )
    assert FortiGateCLICodec().parse(text).dns_servers == ["192.0.2.53"]


def test_the_alternate_servers_are_not_resolvers() -> None:
    """Fortinet's reference says ``alt-primary`` is "not used as a
    failover DNS server"; neither it nor ``alt-secondary`` is read."""
    text = (
        "config system dns\n"
        "    set primary 192.0.2.53\n"
        "    set alt-primary 192.0.2.98\n"
        "    set alt-secondary 192.0.2.99\n"
        "end\n"
    )
    assert FortiGateCLICodec().parse(text).dns_servers == ["192.0.2.53"]


def test_a_value_that_is_no_address_is_kept_for_the_target() -> None:
    """The parser does not judge a value that is no address: it keeps it,
    and each target's renderer writes it or leaves it out and says so
    (FortiOS itself leaves it out, above)."""
    text = (
        "config system dns\n"
        "    set primary ns.example.net\n"
        "end\n"
    )
    assert FortiGateCLICodec().parse(text).dns_servers == ["ns.example.net"]
