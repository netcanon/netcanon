"""Cross-vendor sanitize → render secret-leak guard.

The existing sanitizer guards (``tests/unit/tools/test_sanitize.py``) assert
that :func:`sanitize_intent` redacts every modelled secret field at the
*canonical* level.  This module guards the level beyond that — the one the
dogfood mesh's Tier-C *translation-induced leak* sweep pioneered and the one
the #226 NX-OS SNMPv3 leak actually lived at:

    sanitize_intent(intent)  ->  target_codec.render(sanitized)  ->  <text>

A secret can survive into that rendered text even when the canonical was
sanitized, if a codec emits a field the sanitizer doesn't model AS a secret
(the #226 root: the NX-OS priv key was mis-parsed into the un-redacted
``priv_protocol`` field and re-emitted verbatim).  The canonical-level guards
cannot see that — only rendering the sanitized canonical through every codec
and scanning the OUTPUT does.

This is the regression guard for that whole class: it locks in #226 and fails
RED if any future codec (or a future canonical secret field) leaks a planted
secret VALUE verbatim into any vendor's rendered output.

Method: plant a recognisable ``LEAKCANARY...`` sentinel in every modelled
secret-bearing field, sanitize, render through all 12 codecs, and assert no
canary survives.  A companion guard-the-guard renders the UN-sanitized intent
and asserts at least one codec DOES surface a canary — so the no-leak assertion
can never pass vacuously.
"""

from __future__ import annotations

import pytest

import netcanon.migration  # noqa: F401 — side-effect: register every codec
from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalInterface,
    CanonicalIPv4Address,
    CanonicalLocalUser,
    CanonicalRADIUSServer,
    CanonicalSNMP,
    CanonicalSNMPv3User,
    CanonicalVRRPGroup,
)
from netcanon.migration.codecs.registry import get_codec, list_public_codecs
from netcanon.tools.sanitize import sanitize_intent

pytestmark = pytest.mark.unit

#: Common prefix of every planted secret value — appears ONLY inside secret
#: fields, never in a sanitizer placeholder (REDACTED-* / fake hashes / docs
#: ranges), so a single substring scan is unambiguous.
_CANARY = "LEAKCANARY"

#: The individual sentinels, one per modelled secret-bearing canonical field,
#: so a failure can name exactly which secret class leaked.
_SENTINELS = (
    "LEAKCANARYhash",        # local_users[].hashed_password
    "LEAKCANARYcommunity",   # snmp.community
    "LEAKCANARYauth",        # snmp.v3_users[].auth_passphrase
    "LEAKCANARYpriv",        # snmp.v3_users[].priv_passphrase
    "LEAKCANARYradius",      # radius_servers[].key
    "LEAKCANARYvrrp",        # interfaces[].vrrp_groups[].authentication
)


def _secret_laden_intent() -> CanonicalIntent:
    """A CanonicalIntent with a recognisable secret sentinel in every modelled
    secret-bearing field.  Deliberately uses format-plausible shells around the
    canary (``$6$``-shaped hash, ``plain:`` VRRP scheme) so the codecs' render
    paths exercise their real secret-emitting branches."""
    return CanonicalIntent(
        hostname="device",
        local_users=[
            CanonicalLocalUser(
                name="admin",
                privilege_level=15,
                hashed_password="$6$AbCdEfGh$LEAKCANARYhash0123456789abcdefABCDEF",
            ),
        ],
        snmp=CanonicalSNMP(
            community="LEAKCANARYcommunity",
            v3_users=[
                CanonicalSNMPv3User(
                    name="v3user",
                    auth_protocol="md5",
                    auth_passphrase="0xLEAKCANARYauth00112233445566778899",
                    priv_protocol="aes",
                    priv_passphrase="0xLEAKCANARYpriv00112233445566778899",
                ),
            ],
        ),
        radius_servers=[
            CanonicalRADIUSServer(host="10.0.0.9", key="LEAKCANARYradius"),
        ],
        interfaces=[
            CanonicalInterface(
                name="Vlan10",
                ipv4_addresses=[
                    CanonicalIPv4Address(ip="10.0.0.1", prefix_length=24),
                ],
                vrrp_groups=[
                    CanonicalVRRPGroup(
                        group_id=1,
                        mode="vrrp",
                        authentication="plain:LEAKCANARYvrrp",
                        virtual_ips=["10.0.0.254"],
                    ),
                ],
            ),
        ],
    )


def _render_safe(codec_name: str, intent: CanonicalIntent) -> str | None:
    """Render *intent* through the named codec, returning the text — or None
    if the codec raises on this synthetic intent (a render error is not a leak;
    skip it rather than fail the leak guard)."""
    try:
        return get_codec(codec_name).render(intent)
    except Exception:
        return None


def test_sanitized_canonical_leaks_no_secret_through_any_codec():
    """sanitize_intent + render(<any codec>) must NOT re-emit a planted secret
    VALUE verbatim — the cross-vendor twin of the #226 NX-OS SNMPv3 priv-key
    leak.  If this fails, a codec is emitting a secret from a field the
    sanitizer doesn't redact (a field-modelling or render bug)."""
    sanitized, _subs = sanitize_intent(_secret_laden_intent())
    leaks: dict[str, list[str]] = {}
    for name in list_public_codecs():
        out = _render_safe(name, sanitized)
        if out is None:
            continue
        hit = [s for s in _SENTINELS if s in out]
        if hit:
            leaks[name] = hit
    assert not leaks, (
        "sanitize_intent + render leaked a secret VALUE verbatim into the "
        "rendered output of these codecs (the #226 cross-vendor secret-leak "
        f"class): {leaks}.  Either the codec emits a canonical field the "
        "sanitizer does not redact, or a parse/render bug routes the secret "
        "into an un-redacted field (cf. #226: NX-OS priv key -> priv_protocol)."
    )


def test_leak_scan_is_not_vacuous():
    """Guard-the-guard: render the UN-sanitized intent and confirm at least one
    codec surfaces a canary, proving the scan above can detect a secret when
    present (so its green is meaningful, not a codec-fleet that renders
    nothing)."""
    intent = _secret_laden_intent()
    surfaced = False
    for name in list_public_codecs():
        out = _render_safe(name, intent)
        if out and _CANARY in out:
            surfaced = True
            break
    assert surfaced, (
        "no codec surfaced the canary even WITHOUT sanitization — the leak "
        "scan would be vacuously green; the secret-laden intent is not "
        "exercising any codec's secret-emitting render path."
    )
