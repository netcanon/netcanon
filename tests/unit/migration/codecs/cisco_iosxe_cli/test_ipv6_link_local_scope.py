"""Wave 10 γ-3 — pin the IPv6 link-local scope classifier in
``cisco_iosxe_cli`` parse.

Before this fix the parser only treated an IPv6 address as
``link-local`` when the operator typed the trailing ``link-local``
keyword.  Carrier-router fixtures that write a fe80::/10 address
verbatim (e.g. ``ipv6 address FE80::A8:2DA:1689/126`` on a
Loopback) without the keyword landed in canonical with
``scope="global"`` — which then drifted against ``juniper_junos``'s
prefix-inference path that correctly returns ``link-local``.

Per RFC 4291 §2.4 the fe80::/10 prefix (covering fe80:: through
febf::) is RESERVED for link-local addressing by IANA, regardless
of vendor keyword decoration.  The fix infers scope from the
prefix when the keyword is absent.

See:
* netconfig/migration/codecs/cisco_iosxe_cli/parse.py:_is_link_local_v6
* netconfig/migration/codecs/juniper_junos/parse.py (working reference)
"""

from __future__ import annotations

import pytest

from netconfig.migration.codecs.cisco_iosxe_cli.parse import (
    _is_link_local_v6,
    parse_intent,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _is_link_local_v6 — prefix-shape recognition
# ---------------------------------------------------------------------------


def test_is_link_local_v6_recognises_canonical_fe80_lowercase() -> None:
    """The ``fe80::/10`` prefix (lower-case, the most common form)
    classifies as link-local."""
    assert _is_link_local_v6("fe80::1") is True
    assert _is_link_local_v6("fe80::a:2") is True
    assert _is_link_local_v6("fe80:0:0:0:0:0:0:1") is True


def test_is_link_local_v6_recognises_uppercase_fe80() -> None:
    """Cisco shows IPv6 addresses upper-case in some output (e.g.
    NTC carrier captures); recognition is case-insensitive."""
    assert _is_link_local_v6("FE80::1") is True
    assert _is_link_local_v6("FE80:A8::2DA:1689") is True


def test_is_link_local_v6_recognises_full_fe80_through_febf_range() -> None:
    """fe80::/10 covers the second-nibble values 8, 9, a, b
    (binary 1111111010 means the first 10 bits are 1111111010 →
    leading byte 0xfe and second nibble 8/9/a/b).  Each must
    classify as link-local."""
    assert _is_link_local_v6("fe80::1") is True
    assert _is_link_local_v6("fe90::1") is True
    assert _is_link_local_v6("fea0::1") is True
    assert _is_link_local_v6("feb0::1") is True
    assert _is_link_local_v6("febf:ffff::") is True


def test_is_link_local_v6_rejects_non_link_local_prefixes() -> None:
    """fc00::/7 (ULA), 2000::/3 (global unicast), ff00::/8 (multicast)
    must NOT classify as link-local."""
    assert _is_link_local_v6("2001:db8::1") is False
    assert _is_link_local_v6("fc00::1") is False  # ULA
    assert _is_link_local_v6("fd12:3456::1") is False  # ULA
    assert _is_link_local_v6("fec0::1") is False  # site-local (deprecated)
    assert _is_link_local_v6("ff02::1") is False  # link-local multicast
    assert _is_link_local_v6("::1") is False  # loopback


def test_is_link_local_v6_handles_empty_and_short_inputs() -> None:
    """Empty or too-short inputs return False rather than crashing."""
    assert _is_link_local_v6("") is False
    assert _is_link_local_v6("fe") is False
    assert _is_link_local_v6("f") is False


def test_is_link_local_v6_tolerates_malformed_double_colons() -> None:
    """The malformed ``FE80:A8::2DA::1689`` shape (two ``::`` is
    invalid IPv6 syntax per RFC 4291 §2.2) appears in some real
    fixtures.  The scope classifier inspects only the leading bytes
    so it returns True without crashing — downstream ipaddress
    validation handles correctness."""
    assert _is_link_local_v6("FE80:A8::2DA::1689") is True


# ---------------------------------------------------------------------------
# parse_intent — full-pipeline behaviour
# ---------------------------------------------------------------------------


def test_parse_classifies_fe80_with_keyword_as_link_local() -> None:
    """Existing behaviour: explicit ``link-local`` keyword still wins."""
    cfg = (
        "interface GigabitEthernet0/0\n"
        " ipv6 address fe80::1 link-local\n"
    )
    intent = parse_intent(cfg)
    iface = intent.interfaces[0]
    assert len(iface.ipv6_addresses) == 1
    assert iface.ipv6_addresses[0].scope == "link-local"


def test_parse_classifies_bare_fe80_without_keyword_as_link_local() -> None:
    """The bug fix: a fe80::/10 address WITHOUT the ``link-local``
    keyword (typical on carrier fixtures) infers scope from the
    prefix.  Pre-fix this misclassified as ``global``."""
    cfg = (
        "interface Loopback99\n"
        " ipv6 address FE80::A8:2DA:1689/126\n"
    )
    intent = parse_intent(cfg)
    iface = intent.interfaces[0]
    assert len(iface.ipv6_addresses) == 1
    addr = iface.ipv6_addresses[0]
    assert addr.scope == "link-local", (
        f"FE80:: address must classify as link-local; got {addr.scope!r}"
    )
    assert addr.prefix_length == 126


def test_parse_classifies_global_address_without_keyword_as_global() -> None:
    """Regression guard: non-fe80 addresses without a keyword stay
    ``global``."""
    cfg = (
        "interface GigabitEthernet0/1\n"
        " ipv6 address 2001:db8::1/64\n"
    )
    intent = parse_intent(cfg)
    iface = intent.interfaces[0]
    assert len(iface.ipv6_addresses) == 1
    assert iface.ipv6_addresses[0].scope == "global"


def test_parse_classifies_ula_without_keyword_as_global() -> None:
    """Regression guard: fd00::/8 ULA addresses are NOT link-local;
    they must remain ``global`` (canonical doesn't carry a
    unique-local scope discriminator)."""
    cfg = (
        "interface GigabitEthernet0/2\n"
        " ipv6 address fd12:3456::1/64\n"
    )
    intent = parse_intent(cfg)
    iface = intent.interfaces[0]
    assert iface.ipv6_addresses[0].scope == "global"


def test_parse_does_not_crash_on_malformed_double_colon_v6() -> None:
    """Some real NTC carrier fixtures contain ``FE80:A8::2DA::1689``
    (two ``::`` — invalid per RFC 4291 §2.2).  The parser must not
    crash on the malformed shape, and the prefix-based scope
    classifier should still return link-local since the leading
    bytes match fe80::/10."""
    cfg = (
        "interface Loopback42\n"
        " ipv6 address FE80:A8::2DA::1689/126\n"
    )
    # Should not raise.
    intent = parse_intent(cfg)
    iface = intent.interfaces[0]
    # The address may or may not be stored depending on validation,
    # but if it IS stored, scope must be link-local.
    for addr in iface.ipv6_addresses:
        assert addr.scope == "link-local"


def test_parse_mixed_global_and_link_local_keeps_separate_scopes() -> None:
    """A single interface with both a global and a link-local
    address classifies each one independently from its prefix."""
    cfg = (
        "interface GigabitEthernet0/3\n"
        " ipv6 address 2001:db8::a/64\n"
        " ipv6 address fe80::a link-local\n"
    )
    intent = parse_intent(cfg)
    iface = intent.interfaces[0]
    assert len(iface.ipv6_addresses) == 2
    scopes = sorted(a.scope for a in iface.ipv6_addresses)
    assert scopes == ["global", "link-local"]
