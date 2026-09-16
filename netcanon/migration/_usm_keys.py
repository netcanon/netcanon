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

⚠️ Three grammars distinguish the kind ON THE LINE and the kind is still
inferred per-CODEC rather than per-line: NX-OS ``localizedkey`` /
``localizedV2key``, AOS-CX ``ciphertext`` vs ``plaintext``, and Junos
``authentication-key`` vs ``authentication-password``.  All three therefore
fall back to the UNSAFE kind here (``localised`` / ``ciphertext``), which
fails closed: a config from one of them that really did carry a passphrase is
refused rather than mis-emitted.  ⚠️ Emitting the right marker is a separate
question from classifying one: since #466 the AOS-CX RENDER chooses
``plaintext`` vs ``ciphertext`` correctly, but its PARSE still discards the
keyword, so an AOS-CX source still classifies ``ciphertext``.  Junos is the one
whose parser now READS its passphrase leaf — it has to, because the render emits that leaf to carry a
portable key in (#465), and a leaf the render writes but the parser ignores is
a silent loss — but reading it does not yet make the VALUE classify as
``plaintext`` when Junos is the source.  Capturing these markers as per-value
provenance is follow-up work.
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


def classify_usm_key(value: str, source_vendor: str) -> str:
    """Return the kind of a canonical USM key.

    An unknown source vendor classifies ``localised`` — the unportable kind —
    so a codec added later fails closed until it declares itself in
    :data:`_SOURCE_DEFAULT_KIND`.
    """
    if not value:
        return PLAINTEXT
    if value.upper().startswith("ENC "):
        return ENCRYPTED
    return _SOURCE_DEFAULT_KIND.get(source_vendor, LOCALISED)


def usm_is_migratable(value: str, source_vendor: str, target_vendor: str) -> bool:
    """True if *target_vendor* can actually use this key.

    A same-vendor re-render always can: the key is going back to the kind of
    device that made it.  Cross-vendor, only a passphrase survives — a
    localised key belongs to one engine ID and a ciphertext blob to one device
    key.
    """
    if not value:
        return False
    if source_vendor and source_vendor == target_vendor:
        return True
    return classify_usm_key(value, source_vendor) in _TARGET_USM_ACCEPTS.get(
        target_vendor, frozenset(),
    )
