"""AOS-CX must not label a foreign USM key — or a passphrase — as its own ciphertext.

``snmpv3 user <n> auth <proto> auth-pass ciphertext <blob>`` asserts the value
is encrypted under THIS device's key.  The render appended ``ciphertext`` to
every v3 user whatever the source, so:

* a key belonging to another agent (an NX-OS ``localizedkey`` digest, a Junos
  ``authentication-key``, a VyOS ``encrypted-password``, a FortiGate ``ENC``
  value) was installed as if this switch had encrypted it — it authenticates
  nobody;
* a genuine PASSPHRASE (Arista, IOS-XE CLI, AOS-S and RouterOS all parse only
  that form) was stored as if it were already a device-encrypted blob — the
  case that should have worked, and did not.

This is the NX-OS defect (#464) in a different grammar, and AOS-CX has the same
kind of portable form: ``auth-pass plaintext <passphrase>``, which the switch
encrypts itself.  The parser already accepts both keywords, so the recovered
form round-trips without a parser change.

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

_KEY = "AQBapY" + "Qr" * 12
_PRIV = "AQBbpZ" + "Rs" * 12
_PASS = "Passphrase0"


def _render(source_vendor: str, auth=_KEY, priv=_PRIV) -> str:
    import netcanon.migration.codecs as _c  # noqa: F401  (registry population)

    intent = CanonicalIntent(
        hostname="leaf1",
        source_vendor=source_vendor,
        snmp=CanonicalSNMP(
            community="public",
            v3_users=[CanonicalSNMPv3User(
                name="monitor", group="ops", auth_protocol="sha",
                auth_passphrase=auth, priv_protocol="aes128",
                priv_passphrase=priv,
            )],
        ),
    )
    return get_codec("aruba_aoscx").render(intent)


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_nxos", "juniper_junos", "vyos", "fortigate_cli", ""],
)
def test_a_key_bound_to_the_source_agent_is_never_emitted(source_vendor) -> None:
    """Another agent's key, and an unknown source (which must fail closed),
    can never be re-encrypted by this switch."""
    out = _render(source_vendor)
    assert _KEY not in out, f"{source_vendor!r} USM auth key re-emitted by AOS-CX"
    assert _PRIV not in out, f"{source_vendor!r} USM privacy key re-emitted by AOS-CX"
    assert "review:" in out and "monitor" in out
    # The refusal comment is itself ``! snmpv3 user monitor -- review: ...``,
    # so a bare substring check matches the comment.  What must not exist is a
    # CONFIGURED user: assert over the non-comment lines only.
    config = [ln for ln in out.splitlines() if not ln.lstrip().startswith("!")]
    assert not any("snmpv3 user monitor" in ln for ln in config), (
        f"{source_vendor!r} produced a configured v3 user, not just a comment"
    )


@pytest.mark.parametrize(
    "source_vendor",
    ["arista_eos", "cisco_iosxe_cli", "aruba_aoss", "mikrotik_routeros"],
)
def test_a_passphrase_migrates_through_the_plaintext_keyword(source_vendor) -> None:
    """The recovery path: AOS-CX encrypts a passphrase itself, but only if the
    line says ``plaintext`` — under ``ciphertext`` it is stored as a blob."""
    out = _render(source_vendor, auth=_PASS, priv=_PASS)
    assert f"auth-pass plaintext {_PASS}" in out
    assert f"priv-pass plaintext {_PASS}" in out
    assert "ciphertext" not in out
    assert "review:" not in out


@pytest.mark.parametrize(
    "source_vendor",
    ["arista_eos", "cisco_iosxe_cli", "aruba_aoss", "mikrotik_routeros"],
)
def test_the_recovered_passphrase_parses_back(source_vendor) -> None:
    """The parser already accepts both keywords, so the portable form must
    survive a round-trip rather than becoming a silent loss."""
    codec = get_codec("aruba_aoscx")
    user = codec.parse(_render(source_vendor, auth=_PASS, priv=_PASS)).snmp.v3_users[0]
    assert (user.name, user.auth_protocol, user.auth_passphrase) == (
        "monitor", "sha", _PASS,
    )
    assert user.priv_passphrase == _PASS


def test_a_native_aoscx_key_still_round_trips_as_ciphertext() -> None:
    """Same-vendor: the blob is going home, so the claim is true."""
    codec = get_codec("aruba_aoscx")
    out = _render("aruba_aoscx")
    assert f"auth-pass ciphertext {_KEY}" in out
    user = codec.parse(out).snmp.v3_users[0]
    assert (user.name, user.auth_passphrase, user.priv_passphrase) == (
        "monitor", _KEY, _PRIV,
    )


def test_a_refused_user_leaves_the_rest_of_the_snmp_block_intact() -> None:
    out = _render("cisco_nxos")
    assert "snmp-server community public" in out
    assert get_codec("aruba_aoscx").parse(out).snmp.v3_users == []


def test_the_review_comment_names_the_kind_not_the_key() -> None:
    out = _render("juniper_junos")
    assert "localised USM key" in out
    assert _KEY not in out
