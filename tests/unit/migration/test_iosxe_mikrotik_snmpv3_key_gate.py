"""IOS-XE CLI and RouterOS must not install another agent's USM key as a passphrase.

Both grammars have one slot for the SNMPv3 auth/privacy secret and both expect
the operator's PASSPHRASE there — ``snmp-server user <n> <grp> v3 auth <proto>
<value>`` on IOS-XE, ``authentication-password="<value>"`` on RouterOS.  The
device derives the localised USM key from it.  Each render wrote whatever it
was handed into that slot, so a value that was ALREADY a key (an NX-OS
``localizedkey`` digest, a Junos ``authentication-key``, a VyOS
``encrypted-password``, an AOS-CX ``ciphertext`` blob, a FortiGate ``ENC``
value) was run through key derivation a second time, producing a user that
commits cleanly and authenticates nobody.

This is the Arista shape (#465): the passphrase slot is the only slot, so there
is nothing to re-label and passphrase sources were already correct.  These are
the last two targets in the series.

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

#: (target codec, comment char, the token that proves a user was configured)
_TARGETS = {
    "cisco_iosxe_cli": ("!", "snmp-server user monitor"),
    "mikrotik_routeros": ("#", "add name=monitor"),
    "fortigate_cli": ("#", 'edit "monitor"'),
}

_UNPORTABLE = ["cisco_nxos", "juniper_junos", "vyos", "aruba_aoscx", ""]
#: Sources whose grammar carries a passphrase.  ``cisco_iosxe`` is the stamp
#: the IOS-XE CLI parser actually writes (parse.py sets the family name, not
#: the codec name), so it stands in for an IOS-XE CLI source here.
_PORTABLE = ["arista_eos", "aruba_aoss", "cisco_iosxe", "mikrotik_routeros"]

#: The parser stamps a FAMILY name that differs from the codec/target name.
#: Both must count as same-vendor, or a device's own key is refused on a
#: re-render of its own config.
_FAMILY_STAMPS = [
    ("fortigate", "fortigate_cli"),
    ("cisco_iosxe", "cisco_iosxe_cli"),
]


def _render(target: str, source_vendor: str, auth=_KEY, priv=_PRIV) -> str:
    import netcanon.migration.codecs as _c  # noqa: F401  (registry population)

    intent = CanonicalIntent(
        hostname="dev1",
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
    return get_codec(target).render(intent)


def _config_lines(out: str, comment: str) -> list[str]:
    """Non-comment lines.  A refusal comment names the user, so a bare
    substring check would match the comment itself."""
    return [ln for ln in out.splitlines() if not ln.lstrip().startswith(comment)]


@pytest.mark.parametrize("target", sorted(_TARGETS))
@pytest.mark.parametrize("source_vendor", _UNPORTABLE)
def test_a_key_bound_to_the_source_agent_is_never_emitted(
    target: str, source_vendor: str,
) -> None:
    """Localised digests, device ciphertext, ENC blobs, and an unknown source
    (which must fail closed) are all keys, not passphrases."""
    comment, configured = _TARGETS[target]
    out = _render(target, source_vendor)
    assert _KEY not in out, f"{source_vendor!r} auth key re-emitted by {target}"
    assert _PRIV not in out, f"{source_vendor!r} priv key re-emitted by {target}"
    assert "review:" in out and "monitor" in out
    assert not any(configured in ln for ln in _config_lines(out, comment)), (
        f"{target} configured a v3 user from {source_vendor!r}, not just a comment"
    )


@pytest.mark.parametrize("target", sorted(_TARGETS))
@pytest.mark.parametrize("source_vendor", _UNPORTABLE)
def test_a_refused_user_does_not_survive_a_reparse(
    target: str, source_vendor: str,
) -> None:
    """The refusal comment must be inert: re-parsing the rendered config
    yields no v3 user, rather than a record built from the comment text."""
    out = _render(target, source_vendor)
    reparsed = get_codec(target).parse(out)
    users = reparsed.snmp.v3_users if reparsed.snmp else []
    assert users == [], f"{target} re-parsed a refused user from {source_vendor!r}"


@pytest.mark.parametrize("target", sorted(_TARGETS))
@pytest.mark.parametrize("source_vendor", _PORTABLE)
def test_a_passphrase_still_migrates_untouched(
    target: str, source_vendor: str,
) -> None:
    """The recovery path costs nothing here — the passphrase slot is the same
    slot, so a portable source must be unaffected by the gate."""
    comment, configured = _TARGETS[target]
    out = _render(target, source_vendor, auth=_PASS, priv=_PASS)
    assert _PASS in out
    assert any(configured in ln for ln in _config_lines(out, comment))
    assert "review:" not in out


#: A value shaped the way THAT platform natively stores one.  FortiOS keeps
#: the ``ENC`` marker inside the value, so a bare hex string is not a native
#: FortiGate key and asserting it round-trips unchanged would be testing a
#: shape the device never produces.
_NATIVE_KEY = {
    "cisco_iosxe_cli": _KEY,
    "mikrotik_routeros": _KEY,
    "fortigate_cli": f"ENC {_KEY}",
}


@pytest.mark.parametrize("target", sorted(_TARGETS))
def test_a_native_key_still_round_trips(target: str) -> None:
    """Same-vendor: the value is going home, so the target can have it back."""
    codec = get_codec(target)
    native = _NATIVE_KEY[target]
    out = _render(target, target, auth=native, priv=native)
    assert native in out
    user = codec.parse(out).snmp.v3_users[0]
    assert (user.name, user.auth_passphrase) == ("monitor", native)


@pytest.mark.parametrize("target", sorted(_TARGETS))
def test_a_same_vendor_user_whose_export_omitted_the_key_survives(
    target: str,
) -> None:
    """A device's own ``/export`` often omits secrets.

    Re-rendering that config to the SAME platform must keep the user: there is
    no foreign key to refuse, and dropping it loses a record the operator still
    has on the box.  Regression guard — two committed RouterOS captures carry
    ``public`` with an md5 protocol and no key, and gating them by value-first
    (``if not value: return False`` ahead of the same-vendor check) broke
    ``test_real_capture_round_trips_stable``.
    """
    comment, configured = _TARGETS[target]
    out = _render(target, target, auth="", priv="")
    assert any(configured in ln for ln in _config_lines(out, comment)), (
        f"{target} refused its own keyless v3 user on a same-vendor re-render"
    )
    assert "review:" not in out


@pytest.mark.parametrize("stamp,target", _FAMILY_STAMPS)
def test_the_parsers_family_stamp_counts_as_same_vendor(
    stamp: str, target: str,
) -> None:
    """Regression guard for a trap the gate could introduce.

    ``fortigate_cli/parse.py`` stamps ``source_vendor="fortigate"`` and
    ``cisco_iosxe_cli/parse.py`` stamps ``"cisco_iosxe"`` — the FAMILY name,
    not the codec name.  If the gate compares only the codec name, re-rendering
    a device's OWN config refuses its OWN key.  FortiGate showed this: its
    values classify ``encrypted``, which no target accepts from a foreign
    source, so the family stamp is the only thing marking them as native.
    """
    from netcanon.migration._usm_keys import usm_is_migratable

    value = "ENC abc123==" if stamp.startswith("fortigate") else "Passphrase0"
    assert usm_is_migratable(value, stamp, target), (
        f"a {stamp!r}-stamped config re-rendered to {target!r} had its own key "
        f"refused — the parser's family stamp must count as same-vendor"
    )
    out = _render(target, stamp)
    assert _KEY in out, f"{target} refused its own key under the {stamp!r} stamp"


@pytest.mark.parametrize("target", sorted(_TARGETS))
def test_a_refused_user_leaves_the_rest_of_the_snmp_block_intact(
    target: str,
) -> None:
    out = _render(target, "cisco_nxos")
    assert "public" in out, f"{target} dropped the v2c community with the user"


@pytest.mark.parametrize("target", sorted(_TARGETS))
def test_the_review_comment_names_the_kind_not_the_key(target: str) -> None:
    out = _render(target, "aruba_aoscx")
    assert "ciphertext USM key" in out
    assert _KEY not in out
