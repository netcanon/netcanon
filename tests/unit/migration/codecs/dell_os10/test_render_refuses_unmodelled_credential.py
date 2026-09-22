"""A local user whose password hash the codec cannot model is REFUSED,
not re-emitted — and the refusal is visible in the output.

This is the ``classify_hash`` fail-closed contract (#460 → #472) seen
from the OS10 side: the renderer must never emit a credential it cannot
prove is safe to reuse on the target device.  When it cannot, it drops
the ``username`` line and leaves a review comment naming the user, so
the loss is loud rather than silent.

⭐ Why this module exists at all: the behaviour was confirmed against a
REAL third-party capture, not a hand-built sample.  Microsoft publish an
OS10 reference config whose credentials are scrubbed to the literal
token ``$CREDENTIAL_PLACEHOLDER$``
(``Azure_Local_Physical_Network_Config_Tool``,
``tests/test_cases/std_dell_os10_fc/``).  That token is not a
recognisable hash in any vendor's scheme, so the gate fires on it — the
codec parses two users and renders none.  A round-trip check over that
file therefore reports the user list going 2 → 0, which reads like a
parser bug and is in fact the security gate doing its job.

That distinction is the whole point of pinning it here: the next person
to run a real-capture round-trip sweep will see the same 2 → 0 and needs
to find this file rather than "fix" the refusal.

⚠️ Consequence for round-trip testing: a fixture carrying an unmodelled
credential can never be round-trip stable on ``local_users``.  That is
by design and is why ``_KNOWN_ROUNDTRIP_GAPS`` exists in
``test_real_captures.py``.

See also:
- netcanon/migration/_user_secrets.py — the shared hash-classification gate
- docs/vendors/dell_os10.md — "SNMPv3 keys" + "Lossy paths"
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs.dell_os10 import DellOS10Codec

pytestmark = pytest.mark.unit


#: The scrub token Microsoft ship in their published OS10 reference
#: configs.  Deliberately NOT a real hash — that is the point.
_PLACEHOLDER = "$CREDENTIAL_PLACEHOLDER$"


def _intent_with_unmodelled_hash() -> CanonicalIntent:
    return CanonicalIntent(
        hostname="tor-1a",
        local_users=[
            {
                "name": "admin",
                "privilege_level": 15,
                "hashed_password": _PLACEHOLDER,
                "role": "sysadmin",
            },
        ],
    )


def test_unmodelled_hash_is_not_emitted_as_a_username_line() -> None:
    """The credential must not reach the wire in any form."""
    out = DellOS10Codec().render(_intent_with_unmodelled_hash())
    assert "username admin password" not in out
    assert _PLACEHOLDER not in out, (
        "the unmodelled credential leaked into rendered output"
    )


def test_refusal_is_announced_in_the_output() -> None:
    """A dropped user is reported, never silent.

    Asserting on stable fragments rather than the full sentence so
    wording can be improved without a false failure.
    """
    out = DellOS10Codec().render(_intent_with_unmodelled_hash())
    assert "admin" in out
    assert "review:" in out
    assert "cannot be re-used" in out


def test_refused_user_disappears_on_reparse_by_design() -> None:
    """Pins the 2 → 0 round-trip asymmetry as INTENDED.

    parse(render(intent)) yields no users because the only rendered
    trace is a comment.  This is the fail-closed contract, not a parser
    defect — see the module docstring.
    """
    codec = DellOS10Codec()
    intent = _intent_with_unmodelled_hash()
    assert len(intent.local_users) == 1

    reparsed = codec.parse(codec.render(intent))
    assert reparsed.local_users == []


def test_a_modellable_password_still_round_trips() -> None:
    """Regression guard: the gate refuses the UNKNOWN, not everything.

    A standard crypt-style ``$6$`` hash is a form OS10 itself emits, so
    it must survive render → parse intact.  Without this, a renderer
    that dropped every user would pass the three tests above.
    """
    codec = DellOS10Codec()
    sha512 = "$6$abcdefgh$0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOP"
    intent = CanonicalIntent(
        hostname="tor-1a",
        local_users=[
            {
                "name": "operator",
                "privilege_level": 15,
                "hashed_password": sha512,
                "role": "sysadmin",
            },
        ],
    )
    reparsed = codec.parse(codec.render(intent))
    assert [u.name for u in reparsed.local_users] == ["operator"]
    assert reparsed.local_users[0].hashed_password == sha512
