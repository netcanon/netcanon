"""NX-OS must not claim a foreign SNMPv3 USM key is its own localised digest.

``snmp-server user <n> auth <proto> <key> localizedkey`` tells the Nexus the
value is ALREADY localised against its own engine ID.  The render appended that
keyword to every v3 user, whatever the source, so:

* a foreign localised digest (Junos ``authentication-key``, VyOS
  ``encrypted-password``), an AOS-CX ``ciphertext`` blob or a FortiGate ``ENC``
  value was installed as if the Nexus had derived it — it authenticates nobody;
* a genuine PASSPHRASE (Arista, IOS-XE, AOS-S, RouterOS all parse only that
  form) was stored as a digest instead of being localised on commit — the one
  case that should have worked, and did not.

So the gate is not symmetric with the VyOS one (#463): NX-OS *does* have a
portable form, and a passphrase now renders WITHOUT the keyword.

⚠️ No key material appears in this file; every value is a synthetic shape.
"""
from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalSNMP,
    CanonicalSNMPv3User,
)
from netcanon.migration.codecs.registry import get_codec

pytestmark = pytest.mark.unit

_KEY = "0x" + "ab" * 16
_PRIV = "0x" + "cd" * 16
_PASS = "Passphrase0"


def _render(source_vendor: str, auth=_KEY, priv=_PRIV) -> str:
    import netcanon.migration.codecs as _c  # noqa: F401  (registry population)

    intent = CanonicalIntent(
        hostname="leaf1",
        source_vendor=source_vendor,
        snmp=CanonicalSNMP(
            community="public",
            v3_users=[CanonicalSNMPv3User(
                name="monitor", group="network-operator", auth_protocol="md5",
                auth_passphrase=auth, priv_protocol="aes128", priv_passphrase=priv,
            )],
        ),
    )
    return get_codec("cisco_nxos").render(intent)


@pytest.mark.parametrize(
    "source_vendor",
    ["juniper_junos", "vyos", "aruba_aoscx", "fortigate_cli", ""],
)
def test_an_unportable_usm_key_is_never_emitted(source_vendor) -> None:
    """Localised digests, device ciphertext, ENC blobs, and an unknown source
    (which must fail closed) all belong to another agent."""
    out = _render(source_vendor)
    assert _KEY not in out, f"{source_vendor!r} USM auth key re-emitted by NX-OS"
    assert _PRIV not in out, f"{source_vendor!r} USM privacy key re-emitted by NX-OS"
    assert "review:" in out and "monitor" in out
    assert "snmp-server user monitor" not in out


@pytest.mark.parametrize(
    "source_vendor",
    ["arista_eos", "cisco_iosxe_cli", "aruba_aoss", "mikrotik_routeros"],
)
def test_a_passphrase_migrates_and_is_not_labelled_pre_localised(source_vendor) -> None:
    """The recovery path: NX-OS localises a passphrase itself on commit, but
    only if the line does NOT carry ``localizedkey``."""
    out = _render(source_vendor, auth=_PASS, priv=_PASS)
    assert f"auth md5 {_PASS}" in out
    assert "localizedkey" not in out
    assert "review:" not in out


def test_a_native_nxos_key_still_round_trips_with_the_keyword() -> None:
    """Same-vendor: the digest is going home, so the claim is true."""
    codec = get_codec("cisco_nxos")
    out = _render("cisco_nxos")
    assert f"auth md5 {_KEY}" in out
    assert "localizedkey" in out
    user = codec.parse(out).snmp.v3_users[0]
    assert (user.name, user.auth_passphrase, user.priv_passphrase) == (
        "monitor", _KEY, _PRIV,
    )


def test_a_refused_user_leaves_the_rest_of_the_snmp_block_intact() -> None:
    out = _render("juniper_junos")
    assert "snmp-server community public" in out
    assert get_codec("cisco_nxos").parse(out).snmp.v3_users == []


def test_the_review_comment_names_the_kind_not_the_key() -> None:
    out = _render("aruba_aoscx")
    assert "ciphertext USM key" in out
    assert _KEY not in out
