"""A foreign SNMPv3 USM key must never be re-emitted as a VyOS USM key.

VyOS stores the v3 auth / privacy keys as an ``encrypted-password`` blob
localised against its OWN agent engine ID.  The vyos capability matrix says so
at ``/snmp/v3-user/auth-passphrase``: the blob "round-trips verbatim
same-vendor but cross-vendor migration requires re-keying", and "plaintext keys
are never accepted".

The render wrote ANY source's key into that leaf.  Measured on the committed
corpus before the fix, 30 USM records from 8 source vendors landed there:

==================  =======  =========================================
source              records  what the key actually is
==================  =======  =========================================
cisco_nxos               12  ``localizedkey`` digest (engine-salted)
juniper_junos             4  Junos USM key
mikrotik_routeros         4  2 keys + 2 EMPTY (malformed leaf)
arista_eos                2  plaintext passphrase
aruba_aoscx               2  plaintext passphrase
aruba_aoss                2  31-char AOS-S key
cisco_iosxe_cli           2  plaintext passphrase
fortigate_cli             2  ``ENC`` ciphertext blob
==================  =======  =========================================

None of them authenticates on VyOS.  Unlike a local-user password there is no
recovery path — the target has no plaintext USM form — so the user is refused
and named in a review comment.

⚠️ No key material appears in this file; every value is a synthetic shape.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netcanon.migration.codecs.vyos.render import render_intent

pytestmark = pytest.mark.unit

_KEY = "a" * 40          # synthetic opaque key shape
_PRIV = "b" * 40


def _intent(source_vendor: str, **user_kw) -> CanonicalIntent:
    kw = {
        "name": "monitor", "group": "operators", "auth_protocol": "sha",
        "auth_passphrase": _KEY, "priv_protocol": "aes", "priv_passphrase": _PRIV,
    }
    kw.update(user_kw)
    return CanonicalIntent(
        hostname="edge1",
        source_vendor=source_vendor,
        snmp=CanonicalSNMP(community="public", v3_users=[CanonicalSNMPv3User(**kw)]),
    )


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_nxos", "juniper_junos", "arista_eos", "aruba_aoss", "fortigate_cli",
     "cisco_iosxe_cli", "aruba_aoscx", "mikrotik_routeros", ""],
)
def test_a_foreign_usm_key_is_never_emitted(source_vendor) -> None:
    """The key body must not appear anywhere — not in a leaf, not in a comment."""
    out = render_intent(_intent(source_vendor))
    assert _KEY not in out, f"{source_vendor} USM auth key re-emitted by the vyos render"
    assert _PRIV not in out, f"{source_vendor} USM privacy key re-emitted by the vyos render"


@pytest.mark.parametrize("source_vendor", ["cisco_nxos", "arista_eos"])
def test_a_refused_user_is_dropped_with_a_review_comment(source_vendor) -> None:
    """VyOS USM has no form for a user without auth, so the whole entry goes."""
    out = render_intent(_intent(source_vendor))
    assert "review:" in out and "monitor" in out
    assert "user monitor {" not in out
    assert "encrypted-password" not in out


def test_the_refusal_comment_survives_a_re_parse() -> None:
    """A comment must not corrupt the config: it re-parses, and the rest stays."""
    from netcanon.migration.codecs.vyos.parse import parse_intent

    out = render_intent(_intent("cisco_nxos"))
    back = parse_intent(out)
    assert back.hostname == "edge1"
    assert back.snmp is not None and back.snmp.community == "public"
    assert back.snmp.v3_users == []


def test_a_vyos_native_key_still_round_trips() -> None:
    """The same-vendor path is why the gate keys on provenance, not on shape."""
    from netcanon.migration.codecs.vyos.parse import parse_intent

    out = render_intent(_intent("vyos"))
    assert f"encrypted-password {_KEY}" in out
    assert f"encrypted-password {_PRIV}" in out
    assert "review:" not in out
    user = parse_intent(out).snmp.v3_users[0]
    assert (user.name, user.auth_passphrase, user.priv_passphrase) == ("monitor", _KEY, _PRIV)


def test_a_same_vendor_user_with_no_auth_key_is_refused() -> None:
    """An empty key used to render ``encrypted-password`` with no value."""
    out = render_intent(_intent("vyos", auth_passphrase=""))
    assert "encrypted-password" not in out
    assert "review:" in out


def test_an_empty_privacy_key_omits_the_block_instead_of_emitting_it_empty() -> None:
    """Auth is intact, so the user survives; only the privacy block goes."""
    out = render_intent(_intent("vyos", priv_passphrase=""))
    assert f"encrypted-password {_KEY}" in out
    assert "privacy {" not in out
    assert "user monitor {" in out


def test_no_v3_block_is_emitted_when_every_user_is_refused() -> None:
    """An empty ``v3 { }`` node is not a thing to leave behind."""
    out = render_intent(_intent("cisco_nxos"))
    assert "v3 {" not in out
    assert "community public {" in out
