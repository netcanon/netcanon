"""Dell OS10 must not claim a foreign SNMPv3 USM key is its own localised digest.

``snmp-server user <n> <group> 3 auth <proto> <key> [localized]`` — the
trailing keyword tells the switch the value is ALREADY localised against
its OWN engine ID.  Dell states such keys are generated from that engine
ID and cannot be copied between switches (10.5.2 User Guide L8942).  So
the keyword is a CLAIM about the value, and emitting it on the wrong value
breaks authentication in both directions:

* a foreign localised digest (NX-OS ``localizedkey``, Junos
  ``authentication-key``, VyOS ``encrypted-password``), an AOS-CX
  ``ciphertext`` blob or a FortiGate ``ENC`` value installed behind
  ``localized`` is treated as if OS10 had derived it — it authenticates
  nobody;
* a genuine PASSPHRASE emitted WITH the keyword is stored as a digest
  instead of being localised on commit — the #471 same-vendor corruption,
  invisible to a round-trip guard because parse→render→parse stays stable
  while the rendered TEXT is wrong.

⚠️ **OS10 is not NX-OS.**  Its per-codec default kind is ``plaintext``,
not ``localised`` — an UNMARKED OS10 line is a passphrase.  A gate copied
from the NX-OS one would therefore label native unmarked values as
pre-localised and reintroduce exactly the corruption above.
:func:`test_a_native_unmarked_value_stays_a_passphrase` pins that
asymmetry.

The codec is not registered yet (see ``codec.py``), so it is instantiated
directly rather than through ``get_codec``.

⚠️ No key material appears in this file; every value is a synthetic shape.
"""
from __future__ import annotations

import pytest

from netcanon.migration._usm_keys import LOCALISED
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netcanon.migration.codecs.dell_os10 import DellOS10Codec

pytestmark = pytest.mark.unit

_KEY = "0x" + "ab" * 16
_PRIV = "0x" + "cd" * 16
_PASS = "Passphrase0"


def _render(source_vendor: str, auth=_KEY, priv=_PRIV, **kinds) -> str:
    intent = CanonicalIntent(
        hostname="leaf1",
        source_vendor=source_vendor,
        snmp=CanonicalSNMP(
            community="public",
            v3_users=[CanonicalSNMPv3User(
                name="monitor", group="netadmin", auth_protocol="sha",
                auth_passphrase=auth, priv_protocol="aes128",
                priv_passphrase=priv, **kinds,
            )],
        ),
    )
    return DellOS10Codec().render(intent)


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_nxos", "juniper_junos", "vyos", "aruba_aoscx", "fortigate_cli", ""],
)
def test_an_unportable_usm_key_is_never_emitted(source_vendor) -> None:
    """Localised digests, device ciphertext, ENC blobs, and an unknown
    source (which must fail closed) all belong to another agent."""
    out = _render(source_vendor)
    assert _KEY not in out, f"{source_vendor!r} USM auth key re-emitted by OS10"
    assert _PRIV not in out, f"{source_vendor!r} USM privacy key re-emitted"
    assert "review:" in out and "monitor" in out
    assert "snmp-server user monitor" not in out


@pytest.mark.parametrize(
    "source_vendor",
    ["arista_eos", "cisco_iosxe_cli", "aruba_aoss", "mikrotik_routeros"],
)
def test_a_passphrase_migrates_and_is_not_labelled_pre_localised(
    source_vendor,
) -> None:
    """The recovery path: OS10 localises a passphrase itself on commit,
    but only if the line does NOT carry ``localized``."""
    out = _render(source_vendor, auth=_PASS, priv=_PASS)
    assert f"auth sha {_PASS}" in out
    assert "localized" not in out
    assert "review:" not in out


def test_a_native_unmarked_value_stays_a_passphrase() -> None:
    """The OS10-specific asymmetry.

    ``_SOURCE_DEFAULT_KIND["dell_os10"]`` is ``plaintext``, so a
    same-vendor value carrying NO recorded kind is a passphrase and must
    render without the keyword.  NX-OS defaults the other way; copying its
    gate here would label every unmarked native value pre-localised.
    """
    out = _render("dell_os10", auth=_PASS, priv=_PASS)
    assert f"auth sha {_PASS}" in out
    assert "localized" not in out


def test_a_native_localised_key_round_trips_with_the_keyword() -> None:
    """Same-vendor and explicitly marked: the digest is going home, so the
    claim is true and the marker must survive.  Recovering a key without
    re-marking it makes the switch derive a key from a key."""
    codec = DellOS10Codec()
    out = _render("dell_os10", auth_kind=LOCALISED, priv_kind=LOCALISED)
    assert f"auth sha {_KEY}" in out
    assert "localized" in out
    user = codec.parse(out).snmp.v3_users[0]
    assert (user.name, user.auth_passphrase, user.priv_passphrase) == (
        "monitor", _KEY, _PRIV,
    )
    assert user.auth_kind == LOCALISED


def test_a_refused_user_leaves_the_rest_of_the_snmp_block_intact() -> None:
    out = _render("juniper_junos")
    assert "snmp-server community public" in out
    assert DellOS10Codec().parse(out).snmp.v3_users == []


def test_the_review_comment_names_the_kind_not_the_key() -> None:
    out = _render("aruba_aoscx")
    assert "ciphertext USM key" in out
    assert _KEY not in out


def test_a_user_with_no_auth_is_not_gated() -> None:
    """noAuthNoPriv carries no key, so there is nothing to refuse — the
    line is still a faithful rendering of the source."""
    intent = CanonicalIntent(
        hostname="leaf1",
        source_vendor="cisco_nxos",
        snmp=CanonicalSNMP(v3_users=[CanonicalSNMPv3User(
            name="reader", group="netadmin",
        )]),
    )
    out = DellOS10Codec().render(intent)
    assert "snmp-server user reader netadmin 3" in out
    assert "review:" not in out
