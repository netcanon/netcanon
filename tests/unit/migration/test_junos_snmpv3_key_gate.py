"""Junos must not write a foreign USM key into ``authentication-key``.

``set snmp v3 usm local-engine user <n> authentication-<proto>
authentication-key "<v>"`` is the ALREADY-PROCESSED form: Junos expects the
value it stores for a key of its own.  The render wrote every source's value
there, so an NX-OS ``localizedkey`` digest, a VyOS ``encrypted-password``, an
AOS-CX ``ciphertext`` blob or a FortiGate ``ENC`` value was installed as if
Junos had produced it, and a genuine PASSPHRASE (Arista, IOS-XE, AOS-S and
RouterOS parse only that form) was stored as if it were already a key.

Junos has the portable form the other half needs: ``authentication-password``
takes the operator's passphrase and Junos derives and stores the key itself.
So a passphrase now renders through that leaf — and the parser reads it back —
while a key bound to the source device is refused outright, taking its VACM
binding with it (a security-name with no usable key authenticates nobody).

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
        hostname="fw1",
        source_vendor=source_vendor,
        snmp=CanonicalSNMP(
            community="public",
            v3_users=[CanonicalSNMPv3User(
                name="monitor", group="view-all", auth_protocol="sha",
                auth_passphrase=auth, priv_protocol="aes128",
                priv_passphrase=priv,
            )],
        ),
    )
    return get_codec("juniper_junos").render(intent)


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_nxos", "vyos", "aruba_aoscx", "fortigate_cli", ""],
)
def test_a_key_bound_to_the_source_agent_is_never_emitted(source_vendor) -> None:
    out = _render(source_vendor)
    assert _KEY not in out, f"{source_vendor!r} USM auth key re-emitted by Junos"
    assert _PRIV not in out, f"{source_vendor!r} USM privacy key re-emitted by Junos"
    assert "review:" in out and "monitor" in out
    assert "usm local-engine user monitor" not in out


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_nxos", "vyos", "aruba_aoscx", "fortigate_cli", ""],
)
def test_a_refused_user_takes_its_vacm_binding_with_it(source_vendor) -> None:
    """A ``security-to-group`` binding for a user with no usable key leaves a
    half-configured account behind; the whole entry goes."""
    out = _render(source_vendor)
    assert "security-name monitor" not in out
    assert get_codec("juniper_junos").parse(out).snmp.v3_users == []


@pytest.mark.parametrize(
    "source_vendor",
    ["arista_eos", "cisco_iosxe_cli", "aruba_aoss", "mikrotik_routeros"],
)
def test_a_passphrase_migrates_through_the_password_leaf(source_vendor) -> None:
    """The recovery path: Junos derives the key itself from
    ``authentication-password``, so a passphrase source is carried rather
    than refused — but it must NOT go through ``authentication-key``."""
    out = _render(source_vendor, auth=_PASS, priv=_PASS)
    assert f'authentication-password "{_PASS}"' in out
    assert f'privacy-password "{_PASS}"' in out
    assert "authentication-key" not in out
    assert "privacy-key" not in out
    assert "review:" not in out
    assert "security-name monitor group view-all" in out


@pytest.mark.parametrize(
    "source_vendor",
    ["arista_eos", "cisco_iosxe_cli", "aruba_aoss", "mikrotik_routeros"],
)
def test_the_recovered_passphrase_parses_back(source_vendor) -> None:
    """A leaf the render emits but the parser ignores is a silent loss —
    ``authentication-password`` has to round-trip."""
    codec = get_codec("juniper_junos")
    user = codec.parse(_render(source_vendor, auth=_PASS, priv=_PASS)).snmp.v3_users[0]
    assert (user.name, user.group) == ("monitor", "view-all")
    assert (user.auth_protocol, user.auth_passphrase) == ("sha", _PASS)
    assert (user.priv_protocol, user.priv_passphrase) == ("aes128", _PASS)


def test_a_native_junos_key_still_round_trips_through_the_key_leaf() -> None:
    """Same-vendor: the value is Junos's own, so it goes back verbatim."""
    codec = get_codec("juniper_junos")
    out = _render("juniper_junos")
    assert f'authentication-key "{_KEY}"' in out
    assert "authentication-password" not in out
    user = codec.parse(out).snmp.v3_users[0]
    assert (user.name, user.auth_passphrase, user.priv_passphrase) == (
        "monitor", _KEY, _PRIV,
    )


def test_a_refused_user_leaves_the_rest_of_the_snmp_block_intact() -> None:
    out = _render("cisco_nxos")
    assert "set snmp community public authorization read-only" in out


def test_the_review_comment_names_the_kind_not_the_key() -> None:
    out = _render("aruba_aoscx")
    assert "ciphertext USM key" in out
    assert _KEY not in out


def test_a_user_with_no_auth_is_not_gated() -> None:
    """noAuthNoPriv carries no key: the VACM binding alone is a faithful
    rendering and must survive."""
    import netcanon.migration.codecs as _c  # noqa: F401

    intent = CanonicalIntent(
        hostname="fw1",
        source_vendor="cisco_nxos",
        snmp=CanonicalSNMP(v3_users=[CanonicalSNMPv3User(
            name="reader", group="view-all",
        )]),
    )
    out = get_codec("juniper_junos").render(intent)
    assert "security-name reader group view-all" in out
    assert "review:" not in out
