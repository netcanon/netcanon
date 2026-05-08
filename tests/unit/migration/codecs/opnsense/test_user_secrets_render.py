"""Unit tests for the OPNsense renderer's user-secret emission policy.

OPNsense's ``<password>`` element only consumes bcrypt (``$2y$...``)
hashes — FreeBSD-side ``password_verify()`` rejects everything else.
Foreign hashes (Cisco type-5/8/9, Arista sha512, FortiGate ENC) cannot
be re-used on the target; emitting them as-is leaks the source hash
literal as the password element value (CRITICAL security bug — see
``tests/fixtures/real/user_smoke_findings.md`` issue #1).

Render must consult :func:`netcanon.migration._user_secrets.is_migratable`
and either:

* emit ``<password>$2y$10$...</password>`` for migratable bcrypt or
  plaintext payloads (the helper's ``_TARGET_ACCEPTS["opnsense"]``
  set), OR
* emit a sibling ``<!-- ... -->`` review comment INSIDE the
  ``<user>`` element naming the source algorithm and skip the
  ``<password>`` child entirely for unmigratable formats.

See also:
- ``netcanon/migration/_user_secrets.py`` — shared policy module
- ``netcanon/migration/codecs/opnsense/render.py`` — implementation
- ``tests/unit/migration/codecs/aruba_aoss/test_loopback_oobm_render.py``
  — sister tests for the Aruba comment-form path
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalLocalUser,
)
from netcanon.migration.codecs.opnsense.render import render_intent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Unmigratable hash forms — must NOT leak into <password>
# ---------------------------------------------------------------------------


def test_unmigratable_cisco_type_9_emits_xml_review_comment() -> None:
    """A Cisco IOS-XE type-9 hash (``9 $9$...``) is not bcrypt and cannot
    be re-used by OPNsense.  Render must surface a comment-form review
    line and MUST NOT leak the source hash literal as a password value."""
    intent = CanonicalIntent(
        local_users=[CanonicalLocalUser(
            name="netadmin",
            privilege_level=15,
            hashed_password="9 $9$cisco$scrypt$hash",
        )],
    )
    out = render_intent(intent)
    # Comment marker present, naming the user.
    assert "password manager" in out
    assert 'user-name "netadmin"' in out
    # Carries the source algorithm name so the operator knows what
    # they are resetting from.
    assert "9 hash" in out
    # The original hash literal MUST NOT leak into rendered output.
    assert "$9$" not in out
    assert "scrypt$hash" not in out


def test_unmigratable_hash_does_not_emit_password_element() -> None:
    """When the hash is unmigratable, the ``<password>`` element must
    not be emitted at all — neither populated with the bad hash nor
    self-closing-empty.  Operator sees ONLY the review comment."""
    intent = CanonicalIntent(
        local_users=[CanonicalLocalUser(
            name="netadmin",
            privilege_level=15,
            hashed_password="9 $9$cisco$scrypt$hash",
        )],
    )
    out = render_intent(intent)
    # The bad pattern from the bug report must be absent.
    assert "<password>9" not in out
    assert "<password>$9$" not in out
    # No password element at all (filled or empty).
    assert "<password>" not in out
    assert "<password/>" not in out


def test_arista_sha512_unmigratable_to_opnsense() -> None:
    """Arista's ``arista:sha512:$6$...`` is not in OPNsense's accepted
    set ({plaintext, bcrypt}).  Must surface the comment-form review."""
    intent = CanonicalIntent(
        local_users=[CanonicalLocalUser(
            name="aaa",
            privilege_level=15,
            hashed_password=(
                "arista:sha512:$6$1b/rOJXKhrCHmRXC$fakeAristaHashPayload"
            ),
        )],
    )
    out = render_intent(intent)
    assert "<!--" in out
    assert "password manager" in out
    assert "sha512 hash" in out
    # Source hash must not leak.
    assert "$6$" not in out
    assert "fakeAristaHashPayload" not in out
    # No <password> element emitted.
    assert "<password>" not in out


# ---------------------------------------------------------------------------
# Migratable hash forms — must emit <password> with the raw payload
# ---------------------------------------------------------------------------


def test_bcrypt_native_hash_emits_password_element() -> None:
    """Native bcrypt is OPNsense's own format and must round-trip
    intact: ``<password>$2y$10$...</password>`` with the ``bcrypt:``
    tag stripped from the canonical form."""
    intent = CanonicalIntent(
        local_users=[CanonicalLocalUser(
            name="root",
            privilege_level=15,
            hashed_password=(
                "bcrypt:$2y$10$abc.def.ghi.jklmnopqrs.tuvwxyz0123456789AB"
            ),
        )],
    )
    out = render_intent(intent)
    # Raw $2y$10$... must appear inside <password>...</password>.
    assert (
        "<password>$2y$10$abc.def.ghi.jklmnopqrs.tuvwxyz0123456789AB"
        "</password>"
    ) in out
    # No bcrypt: prefix should leak.
    assert "bcrypt:" not in out
    # No comment-form review line for the migratable case.
    assert "review:" not in out
