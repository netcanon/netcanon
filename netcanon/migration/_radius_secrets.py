"""Cross-codec RADIUS shared-secret portability policy.

Third sibling of :mod:`netcanon.migration._user_secrets` (local-user
password hashes) and :mod:`netcanon.migration._usm_keys` (SNMPv3 USM keys).
A RADIUS shared secret is a fourth thing again: it is a **symmetric secret
agreed between this device and the RADIUS server**, so unlike a password
hash it is not one-way, and unlike a USM key it is not derived from an
engine ID.  What it shares with both is that a vendor may store it in a
form only that vendor's device can read back.

Two shapes reach the canonical tree:

============  ==========================================================
kind          where it comes from
============  ==========================================================
``plaintext`` The secret as the operator typed it.  ``aruba_aoss``
              (``radius-server host <ip> key "<secret>"``) and
              ``opnsense`` (``<radius_secret>``) store it this way, and
              the canonical value carries no envelope.  Portable: every
              target's RADIUS grammar accepts a literal secret.
``encrypted`` FortiGate's ``set secret ENC <blob>``, carried canonically
              behind the ``fortios:`` envelope the FortiGate parser
              applies.  The blob is encrypted under the FortiGate's own
              device key.  **Not portable to anything.**
============  ==========================================================

Why this module exists (defect D3, 2026-09-23)
----------------------------------------------
Every render path emitted ``server.key`` verbatim into the target's key
slot.  Five of the six -- ``arista_eos``, ``cisco_iosxe_cli``,
``aruba_aoss``, ``mikrotik_routeros``, ``opnsense`` -- wrote a FortiGate
``fortios:ENC <blob>`` string into a field their vendor reads as the
literal shared secret.  That is the failure the Hard Rules already name
twice: a credential meaningful only on its source device re-emitted
somewhere it authenticates nobody, and an envelope that, once anything
strips it, BECOMES the password.

It ran in the other direction too.  The FortiGate renderer split the
canonical value on ``":"`` and stamped ``ENC`` on whatever came back,
so a *plaintext* secret from Aruba or OPNsense was written as
``set secret ENC <plaintext>`` -- claiming a provenance it never had and
handing FortiOS a value it will try to decrypt.

Both directions are fixed by the same rule the sibling modules use:
**gate on provenance, and refuse rather than invent a form the target
does not accept.**

Contract
--------
* Same-vendor re-render always passes -- the value is going back to the
  kind of device that produced it.  ``fortigate_cli`` -> ``fortigate_cli``
  keeps its ``ENC`` blob, and that path is the reference implementation.
* Cross-vendor, only ``plaintext`` survives.
* Refusing a secret does NOT drop the server record.  A
  ``radius-server host <ip>`` line with no key is a real, inspectable,
  half-configured server the operator must finish; a vanished server is
  a silent hole in their AAA config.  This differs deliberately from the
  SNMPv3 rule (#465), where a v3 user without a usable key is not a
  meaningful record at all.  Renderers emit a review comment instead.
"""

from __future__ import annotations

import re

# The envelope the FortiGate parser stamps on a `set secret ENC <blob>`
# value.  Kept as a constant because both the classifier and the
# FortiGate renderer's round-trip branch key off it.
FORTIOS_ENVELOPE = "fortios:"

#: Codec names that mean the same physical platform, mirroring
#: ``_usm_keys._VENDOR_ALIASES``.  A tree parsed by ``fortigate_cli`` may
#: be stamped with either the family name or the codec name depending on
#: which surface set ``source_vendor``.
_VENDOR_ALIASES: dict[str, frozenset[str]] = {
    "fortigate_cli": frozenset({"fortigate", "fortigate_cli"}),
    "cisco_iosxe_cli": frozenset({"cisco_iosxe", "cisco_iosxe_cli"}),
}

#: What each render target can actually consume cross-vendor.  Every
#: target takes a literal secret; none can use another device's
#: encrypted blob.  Listed per-target rather than assumed so that adding
#: a codec is a deliberate edit here, not a silent inherit -- the trap
#: that let four user-password render paths skip their gate until #461.
_TARGET_ACCEPTS: dict[str, frozenset[str]] = {
    "arista_eos": frozenset({"plaintext"}),
    "aruba_aoss": frozenset({"plaintext"}),
    "cisco_iosxe_cli": frozenset({"plaintext"}),
    "fortigate_cli": frozenset({"plaintext"}),
    "mikrotik_routeros": frozenset({"plaintext"}),
    "opnsense": frozenset({"plaintext"}),
}


#: Every envelope any parser in the tree applies to a RADIUS secret, and
#: the kind it denotes.  This set is CLOSED: a value carrying an
#: envelope-shaped prefix that is not listed here cannot be classified,
#: and :func:`classify_radius_secret` returns ``"unknown"`` for it rather
#: than assuming the benign answer.
#:
#: Guarded by ``test_radius_secret_envelope_registry_is_complete``, which
#: fails if a parser starts applying an envelope nobody registered.
_KNOWN_ENVELOPES: dict[str, str] = {
    FORTIOS_ENVELOPE: "encrypted",
}

#: An envelope-shaped prefix: a lowercase identifier then a colon.  Used
#: ONLY to notice that a value *claims* structure we do not recognise.
_ENVELOPE_SHAPE = re.compile(r"^[a-z][a-z0-9_]*:")


def classify_radius_secret(value: str, source_vendor: str = "") -> str:
    """Return the kind of RADIUS secret *value* carries.

    One of ``""`` (empty), ``"plaintext"``, ``"encrypted"``, or
    ``"unknown"``.

    Classification is by ENVELOPE and PROVENANCE, never by guessing at
    the body's shape -- a sanitised fixture makes a base64 blob look like
    a word and a short secret look like a digest.

    The awkward case is a colon.  When provenance is KNOWN, the full
    set of envelopes any parser applies is known too, so a value
    carrying none of them is literal: ``my:secret`` is a perfectly
    legal shared secret and must not be refused.  Refusing every value
    containing a colon would be the false-positive blast #460 warns
    about when closing a default in the wrong order.

    But a value that carries an unregistered envelope-shaped prefix AND
    comes from a source we cannot vouch for is exactly the case the Hard
    Rules refuse to guess at: "never let an unrecognised secret classify
    as plaintext".  That returns ``"unknown"``, and
    :func:`radius_secret_is_migratable` refuses it.
    """
    if not value:
        return ""
    for envelope, kind in _KNOWN_ENVELOPES.items():
        if value.startswith(envelope):
            return kind
    if source_vendor:
        # Provenance vouches for the shape.  We know which parser
        # produced this value, we know the full set of envelopes any
        # parser applies (:data:`_KNOWN_ENVELOPES`, guarded by
        # ``test_radius_secret_envelope_registry_is_complete``), and
        # this value carries none of them -- so a colon here is CONTENT.
        # ``my:secret`` is a legal shared secret and refusing it would
        # be the false-positive blast #460 warns about.  Applies equally
        # to an envelope-applying source: FortiOS ``set secret <plain>``
        # is legal and reaches us envelope-free.
        return "plaintext"
    if _ENVELOPE_SHAPE.match(value):
        # Claims a structure no parser in this tree produces.  Either a
        # codec grew an envelope without registering it here, or this is
        # a value we have no story for.  Do not guess.
        return "unknown"
    return "plaintext"


def _same_vendor(source_vendor: str, target_vendor: str) -> bool:
    """True when *source_vendor* names the same platform as *target_vendor*."""
    if not source_vendor:
        return False
    if source_vendor == target_vendor:
        return True
    return source_vendor in _VENDOR_ALIASES.get(target_vendor, frozenset())


def radius_secret_is_migratable(
    value: str,
    source_vendor: str,
    target_vendor: str,
) -> bool:
    """True when *target_vendor* can actually use this shared secret.

    A same-vendor re-render always can.  Cross-vendor, only a plaintext
    secret survives -- an encrypted blob belongs to one device's key and
    would authenticate nobody anywhere else.

    An unknown *target_vendor* returns ``False``: a codec that has not
    been considered here must refuse rather than inherit permission.
    That is the fail-closed default the Hard Rules require, and it is
    why :data:`_TARGET_ACCEPTS` enumerates targets explicitly.
    """
    if _same_vendor(source_vendor, target_vendor):
        return True
    kind = classify_radius_secret(value, source_vendor)
    if not kind:
        return False
    return kind in _TARGET_ACCEPTS.get(target_vendor, frozenset())


def unwrap_native_secret(value: str) -> str:
    """Strip the ``fortios:`` envelope for a FortiGate-side re-render.

    ONLY for the same-vendor path: the envelope is an internal marker,
    and the value behind it is the ``ENC <blob>`` text FortiOS wrote.
    Callers must have cleared :func:`radius_secret_is_migratable` first
    -- unwrapping is what turns a foreign blob into a bare string that
    the next parser reads as the literal secret.
    """
    if value.startswith(FORTIOS_ENVELOPE):
        return value[len(FORTIOS_ENVELOPE):]
    return value


def format_review_comment(
    host: str,
    comment_syntax: str = "hash",
    target_label: str = "this target",
) -> str:
    """Build a one-line review comment naming a refused shared secret.

    Mirrors :func:`netcanon.migration._user_secrets.format_review_comment`
    so cross-vendor diffs read consistently.  The server record is still
    rendered; this line says why it has no key.
    """
    body = (
        f"radius-server host {host} -- review: the source device stored "
        f"this shared secret encrypted under its own device key, so it "
        f"cannot be re-used on {target_label}; re-enter the secret "
        f"manually"
    )
    delimiters = {
        "hash": ("# ", ""),
        "semicolon": ("; ", ""),
        "slash": ("/* ", " */"),
        "xml": ("<!-- ", " -->"),
        "exclamation": ("! ", ""),
        # Undelimited — for callers that supply their own wrapper, e.g.
        # an ``ET.Comment`` node, which adds ``<!-- -->`` itself.  Using
        # ``xml`` there would nest the markers and corrupt the document.
        "plain": ("", ""),
    }
    prefix, suffix = delimiters.get(comment_syntax, ("# ", ""))
    return f"{prefix}{body}{suffix}"
