"""Arista EOS must not install another agent's SNMPv3 USM key as a passphrase.

``snmp-server user <n> <group> v3 auth <proto> <value>`` takes the operator's
PASSPHRASE: EOS derives the localised key from it at commit and thereafter
displays the derived form (``auth sha <key> localized <engineID>``, which this
codec's parser deliberately does not match).  The render wrote whatever it was
handed into that slot, so a value that was ALREADY a key — an NX-OS
``localizedkey`` digest, a Junos ``authentication-key``, a VyOS
``encrypted-password``, an AOS-CX ``ciphertext`` blob or a FortiGate ``ENC``
value — was fed back through EOS's key derivation as if it were a passphrase.
The resulting user commits cleanly and authenticates nobody.

Unlike VyOS (#463) there IS a portable shape here, and unlike NX-OS (#464)
nothing has to change to emit it: a passphrase source was already correct.  So
this gate only refuses what was never usable.

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
                name="monitor", group="v3group", auth_protocol="sha",
                auth_passphrase=auth, priv_protocol="aes128",
                priv_passphrase=priv,
            )],
        ),
    )
    return get_codec("arista_eos").render(intent)


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_nxos", "juniper_junos", "vyos", "aruba_aoscx", "fortigate_cli", ""],
)
def test_a_key_bound_to_the_source_agent_is_never_emitted(source_vendor) -> None:
    """Localised digests, device ciphertext, ENC blobs, and an unknown source
    (which must fail closed) are all keys, not passphrases."""
    out = _render(source_vendor)
    assert _KEY not in out, f"{source_vendor!r} USM auth key re-emitted by EOS"
    assert _PRIV not in out, f"{source_vendor!r} USM privacy key re-emitted by EOS"
    assert "review:" in out and "monitor" in out
    assert "snmp-server user monitor" not in out


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_iosxe_cli", "aruba_aoss", "mikrotik_routeros"],
)
def test_a_passphrase_still_migrates_untouched(source_vendor) -> None:
    """The recovery path costs nothing here — EOS's passphrase slot is the
    same slot, so a portable source must be unaffected by the gate."""
    out = _render(source_vendor, auth=_PASS, priv=_PASS)
    assert f"auth sha {_PASS}" in out
    assert f"priv aes {_PASS}" in out
    assert "review:" not in out


def test_a_native_eos_key_still_round_trips() -> None:
    """Same-vendor: the key is going home, so EOS can have it back."""
    codec = get_codec("arista_eos")
    out = _render("arista_eos")
    assert f"auth sha {_KEY}" in out
    user = codec.parse(out).snmp.v3_users[0]
    assert (user.name, user.auth_passphrase, user.priv_passphrase) == (
        "monitor", _KEY, _PRIV,
    )


def test_a_refused_user_leaves_the_rest_of_the_snmp_block_intact() -> None:
    out = _render("cisco_nxos")
    assert "snmp-server community public ro" in out
    assert get_codec("arista_eos").parse(out).snmp.v3_users == []


def test_the_review_comment_names_the_kind_not_the_key() -> None:
    out = _render("aruba_aoscx")
    assert "ciphertext USM key" in out
    assert _KEY not in out


def test_a_user_with_no_auth_is_not_gated() -> None:
    """noAuthNoPriv carries no key, so there is nothing to refuse — the
    ``v3`` line is still a faithful rendering of the source."""
    import netcanon.migration.codecs as _c  # noqa: F401

    intent = CanonicalIntent(
        hostname="leaf1",
        source_vendor="cisco_nxos",
        snmp=CanonicalSNMP(v3_users=[CanonicalSNMPv3User(
            name="reader", group="v3group",
        )]),
    )
    out = get_codec("arista_eos").render(intent)
    assert "snmp-server user reader v3group v3" in out
    assert "review:" not in out
