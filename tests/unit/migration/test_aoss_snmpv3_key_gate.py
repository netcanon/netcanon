"""AOS-S must not install another agent's SNMPv3 USM key as a passphrase.

``snmpv3 user "<n>" auth <proto> "<value>"`` takes the operator's PASSPHRASE:
the switch derives the localised key from it when the user is created.  The
render wrote whatever it was handed into that slot, so a value that was ALREADY
a key — an NX-OS ``localizedkey`` digest, a Junos ``authentication-key``, a
VyOS ``encrypted-password``, an AOS-CX ``ciphertext`` blob, a FortiGate ``ENC``
value — was run through key derivation a second time.  The resulting user
commits cleanly and authenticates nobody.

This is the Arista shape (#465), not the NX-OS one: the passphrase slot is the
only slot, so there is nothing to re-label and passphrase sources were already
correct.  The gate only refuses what was never usable.

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
        hostname="sw1",
        source_vendor=source_vendor,
        snmp=CanonicalSNMP(
            community="public",
            v3_users=[CanonicalSNMPv3User(
                name="monitor", group="ROGroup", auth_protocol="sha",
                auth_passphrase=auth, priv_protocol="aes128",
                priv_passphrase=priv,
            )],
        ),
    )
    return get_codec("aruba_aoss").render(intent)


def _config_lines(out: str) -> list[str]:
    """Non-comment lines.  The refusal comment names the user, so a bare
    substring check would match the comment itself."""
    return [ln for ln in out.splitlines() if not ln.lstrip().startswith(";")]


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_nxos", "juniper_junos", "vyos", "aruba_aoscx", "fortigate_cli", ""],
)
def test_a_key_bound_to_the_source_agent_is_never_emitted(source_vendor) -> None:
    """Localised digests, device ciphertext, ENC blobs, and an unknown source
    (which must fail closed) are all keys, not passphrases."""
    out = _render(source_vendor)
    assert _KEY not in out, f"{source_vendor!r} USM auth key re-emitted by AOS-S"
    assert _PRIV not in out, f"{source_vendor!r} USM privacy key re-emitted by AOS-S"
    assert "review:" in out and "monitor" in out
    assert not any("snmpv3 user" in ln for ln in _config_lines(out)), (
        f"{source_vendor!r} produced a configured v3 user, not just a comment"
    )


@pytest.mark.parametrize(
    "source_vendor",
    ["cisco_nxos", "juniper_junos", "vyos", "aruba_aoscx", "fortigate_cli", ""],
)
def test_a_refused_user_takes_its_group_binding_with_it(source_vendor) -> None:
    """A ``snmpv3 group ... user ...`` binding for a user that was never
    created is a dangling reference the switch rejects."""
    out = _render(source_vendor)
    assert not any("snmpv3 group" in ln for ln in _config_lines(out))
    assert get_codec("aruba_aoss").parse(out).snmp.v3_users == []


@pytest.mark.parametrize(
    "source_vendor",
    ["arista_eos", "cisco_iosxe_cli", "mikrotik_routeros"],
)
def test_a_passphrase_still_migrates_untouched(source_vendor) -> None:
    """The recovery path costs nothing here — AOS-S's passphrase slot is the
    same slot, so a portable source must be unaffected by the gate."""
    out = _render(source_vendor, auth=_PASS, priv=_PASS)
    assert f'auth sha "{_PASS}"' in out
    assert f'priv aes "{_PASS}"' in out
    assert 'snmpv3 group "ROGroup" user "monitor"' in out
    assert "review:" not in out


def test_a_native_aoss_key_still_round_trips() -> None:
    """Same-vendor: the value is going home, so AOS-S can have it back."""
    codec = get_codec("aruba_aoss")
    out = _render("aruba_aoss")
    assert f'auth sha "{_KEY}"' in out
    user = codec.parse(out).snmp.v3_users[0]
    assert (user.name, user.auth_passphrase, user.priv_passphrase) == (
        "monitor", _KEY, _PRIV,
    )


def test_a_refused_user_leaves_the_rest_of_the_snmp_block_intact() -> None:
    out = _render("cisco_nxos")
    assert 'snmp-server community "public"' in out


def test_the_review_comment_names_the_kind_not_the_key() -> None:
    out = _render("aruba_aoscx")
    assert "ciphertext USM key" in out
    assert _KEY not in out


def test_a_user_with_no_auth_is_not_gated() -> None:
    """noAuthNoPriv carries no key, so there is nothing to refuse."""
    import netcanon.migration.codecs as _c  # noqa: F401

    intent = CanonicalIntent(
        hostname="sw1",
        source_vendor="cisco_nxos",
        snmp=CanonicalSNMP(v3_users=[CanonicalSNMPv3User(
            name="reader", group="ROGroup",
        )]),
    )
    out = get_codec("aruba_aoss").render(intent)
    assert 'snmpv3 user "reader"' in out
    assert "review:" not in out
