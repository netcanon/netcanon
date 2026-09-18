"""Cross-codec SNMPv3 USM key portability policy.

Sibling of :mod:`netcanon.migration._user_secrets`, for the other credential
surface.  A USM key is not a password: the agent derives it from a passphrase
and **localises it against its own engine ID**, so a localised key is
meaningful only on the device that produced it.  A *passphrase* ports fine —
every target whose CLI takes one re-derives the key on commit.

``CanonicalSNMPv3User.auth_passphrase`` / ``priv_passphrase`` carry both
shapes in one string field, so the kind has to be inferred.  It is inferred
from the SOURCE CODEC'S GRAMMAR, never from the value's shape: a sanitised
fixture makes a localised digest look like a word, and "it looks like a
passphrase" is the fail-open that #460 closed on the other credential surface.

============  =========================================================
kind          where it comes from
============  =========================================================
``plaintext`` A passphrase the operator typed.  ``arista_eos``,
              ``cisco_iosxe_cli``, ``aruba_aoss`` and
              ``mikrotik_routeros`` parse only this form — EOS's
              pre-hashed ``localized <engineID>`` form is
              parse-and-ignore per its own parser comment, and RouterOS
              uses ``authentication-password=``.
``localised`` A key the SOURCE agent already processed for itself and
              cannot hand on: NX-OS ``localizedkey`` and VyOS
              ``encrypted-password`` are localised against that agent's
              engine ID, and Junos ``authentication-key`` is the value
              Junos stored for a key of its own.
``ciphertext`` A blob encrypted under the source device's key: AOS-CX
              ``auth-pass ciphertext``.
``encrypted`` FortiGate's ``ENC `` blob — the one kind that marks
              itself, because FortiOS keeps the marker in the value.
============  =========================================================

Three grammars mark the kind ON THE LINE, and those markers are now CAPTURED
per value rather than inferred per codec: NX-OS ``localizedkey`` /
``localizedV2key``, AOS-CX ``ciphertext`` vs ``plaintext``, and Junos
``authentication-key`` vs ``authentication-password``.  Each parser records
what it read into ``CanonicalSNMPv3User.auth_kind`` / ``priv_kind``, and
:func:`classify_usm_key` prefers that over
:data:`_SOURCE_DEFAULT_KIND`.  The table above therefore describes the
DEFAULT for a line that carried no marker.

⚠️ This is still kind-from-grammar, at finer resolution -- it is NOT a licence
to read the value.  Three committed NX-OS captures carry ``localizedkey`` over
a value sanitisation turned word-like: the marker survived, the shape did not.

Recording the marker fixed two failures at once.  Cross-vendor, a genuine
passphrase from any of the three was refused rather than migrated.  And
SAME-VENDOR, NX-OS re-emitted a passphrase line WITH ``localizedkey``
appended, telling the Nexus a passphrase was already localised against its own
engine ID -- corruption on the one path that is supposed to be lossless, and
invisible to the round-trip guard because parse -> render -> parse stayed
stable while the rendered TEXT was wrong.
"""

from __future__ import annotations

PLAINTEXT = "plaintext"
LOCALISED = "localised"
CIPHERTEXT = "ciphertext"
ENCRYPTED = "encrypted"

#: What a value from this source IS, per that codec's parse grammar.
_SOURCE_DEFAULT_KIND: dict[str, str] = {
    "arista_eos": PLAINTEXT,
    "cisco_iosxe_cli": PLAINTEXT,
    "cisco_iosxe": PLAINTEXT,
    "aruba_aoss": PLAINTEXT,
    "mikrotik_routeros": PLAINTEXT,
    "cisco_nxos": LOCALISED,
    "juniper_junos": LOCALISED,
    "vyos": LOCALISED,
    "aruba_aoscx": CIPHERTEXT,
    "fortigate_cli": ENCRYPTED,
    "fortigate": ENCRYPTED,
}

#: Kinds each target can consume from a FOREIGN source.  A same-vendor
#: re-render always re-emits its own value verbatim and does not consult this.
#:
#: Every entry is ``{PLAINTEXT}`` or empty, and that is the point: no target
#: can use another agent's localised key.  ``vyos`` is empty because its
#: saved-config grammar has no passphrase form — its matrix says "plaintext
#: keys are never accepted" (#463).  ``opnsense`` and ``cisco_iosxr`` render no
#: USM users at all and are absent.
_TARGET_USM_ACCEPTS: dict[str, frozenset[str]] = {
    "arista_eos": frozenset({PLAINTEXT}),
    "aruba_aoss": frozenset({PLAINTEXT}),
    "aruba_aoscx": frozenset({PLAINTEXT}),
    "cisco_iosxe_cli": frozenset({PLAINTEXT}),
    "cisco_nxos": frozenset({PLAINTEXT}),
    "fortigate_cli": frozenset({PLAINTEXT}),
    "juniper_junos": frozenset({PLAINTEXT}),
    "mikrotik_routeros": frozenset({PLAINTEXT}),
    "vyos": frozenset(),
}


#: Kinds this policy models.  A *kind* arriving from anywhere else is not
#: trusted: it fails closed to ``localised`` exactly as an unknown SOURCE
#: does, so a codec that later records a kind this module does not know
#: cannot smuggle a device-bound key past the gate.
_KNOWN_KINDS: frozenset[str] = frozenset(
    {PLAINTEXT, LOCALISED, CIPHERTEXT, ENCRYPTED},
)


def classify_usm_key(value: str, source_vendor: str, kind: str = "") -> str:
    """Return the kind of a canonical USM key.

    *kind* is the per-value provenance recorded by the parser
    (:attr:`CanonicalSNMPv3User.auth_kind` / ``priv_kind``) for the three
    grammars that mark the kind ON THE LINE.  It wins over the per-codec
    default, because it is the more precise reading of the SAME evidence --
    the source grammar -- not a different kind of evidence.  ``""`` means the
    source line carried no marker, and the codec default applies.

    An unknown source vendor classifies ``localised`` — the unportable kind —
    so a codec added later fails closed until it declares itself in
    :data:`_SOURCE_DEFAULT_KIND`.  An unrecognised *kind* fails closed the
    same way.

    The ``ENC `` test stays ahead of *kind*: FortiOS keeps that marker inside
    the value, and ``encrypted`` is unportable, so honouring it first can only
    ever refuse more.
    """
    if not value:
        return PLAINTEXT
    if value.upper().startswith("ENC "):
        return ENCRYPTED
    if kind:
        return kind if kind in _KNOWN_KINDS else LOCALISED
    return _SOURCE_DEFAULT_KIND.get(source_vendor, LOCALISED)


#: Parsers that stamp a FAMILY name rather than the codec name.  A
#: ``fortigate_cli`` capture is stamped ``fortigate``; an IOS-XE CLI capture is
#: stamped ``cisco_iosxe``.  Both must count as same-vendor against the codec
#: that produced them, or re-rendering a device's OWN config refuses its OWN
#: key.  FortiGate showed this: its values classify ``encrypted``, which no
#: target accepts from a foreign source, so the family stamp is the only thing
#: marking them as native.
_VENDOR_ALIASES: dict[str, frozenset[str]] = {
    "fortigate_cli": frozenset({"fortigate", "fortigate_cli"}),
    "cisco_iosxe_cli": frozenset({"cisco_iosxe", "cisco_iosxe_cli"}),
}


def _same_vendor(source_vendor: str, target_vendor: str) -> bool:
    """True when *source_vendor* names the same platform as *target_vendor*,
    allowing for the family-name stamps in :data:`_VENDOR_ALIASES`."""
    if not source_vendor:
        return False
    if source_vendor == target_vendor:
        return True
    return source_vendor in _VENDOR_ALIASES.get(target_vendor, frozenset())


def usm_is_migratable(
    value: str,
    source_vendor: str,
    target_vendor: str,
    kind: str = "",
) -> bool:
    """True if *target_vendor* can actually use this key.

    A same-vendor re-render always can: the key is going back to the kind of
    device that made it.  Cross-vendor, only a passphrase survives — a
    localised key belongs to one engine ID and a ciphertext blob to one device
    key.
    """
    # Same-vendor FIRST: a device re-rendering its own config keeps its own
    # users, including one whose `/export` omitted the secret.  The
    # empty-value rule below is about cross-vendor portability ("nothing to
    # migrate"), and must not refuse a record the operator still has on the
    # box -- two committed RouterOS captures carry exactly that shape.
    if _same_vendor(source_vendor, target_vendor):
        return True
    if not value:
        return False
    return classify_usm_key(value, source_vendor, kind) in _TARGET_USM_ACCEPTS.get(
        target_vendor, frozenset(),
    )


def user_usm_is_migratable(user, source_vendor: str, target_vendor: str) -> bool:
    """True when EVERY key this user actually carries can reach the target.

    ``auth_passphrase`` and ``priv_passphrase`` are separate leaves with
    separate provenance, and they CAN disagree: Junos writes them on two
    independent ``set`` lines, and AOS-CX marks each token on its own.  The
    render paths used to collapse them to ``auth_passphrase or
    priv_passphrase`` and judge the user on that one value, which would leak a
    device-bound PRIVACY key whenever the auth key happened to be portable.

    A user carrying no key at all is decided by vendor alone -- same-vendor
    keeps the record (a ``/export`` that omitted the secret is still that
    device's own user), cross-vendor has nothing to migrate.
    """
    populated = [
        (value, kind)
        for value, kind in (
            (user.auth_passphrase, user.auth_kind),
            (user.priv_passphrase, user.priv_kind),
        )
        if value
    ]
    if not populated:
        return _same_vendor(source_vendor, target_vendor)
    return all(
        usm_is_migratable(value, source_vendor, target_vendor, kind)
        for value, kind in populated
    )


def user_usm_kind(user, source_vendor: str) -> str:
    """The kind to NAME when refusing *user* -- its least portable key.

    Reporting the auth key's kind while refusing on the privacy key's would
    put a misleading word in the operator's review comment.
    """
    for value, kind in (
        (user.auth_passphrase, user.auth_kind),
        (user.priv_passphrase, user.priv_kind),
    ):
        if value:
            resolved = classify_usm_key(value, source_vendor, kind)
            if resolved != PLAINTEXT:
                return resolved
    return PLAINTEXT
