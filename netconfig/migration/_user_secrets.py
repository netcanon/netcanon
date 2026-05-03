"""Cross-codec user-secret migration policy.

Recognises hash-algorithm formats that cannot be re-used on
a target vendor and exposes helpers each codec calls before
emitting password material.  Centralises the policy that was
previously duplicated in aruba_aoss/render.py.

Canonical ``CanonicalLocalUser.hashed_password`` carries vendor-tagged
hashes from many sources.  The shapes observed in real captures and
the synthetic round-trip fixtures are:

* ``"plaintext"`` (no separator)                       -> ("plaintext", "plaintext")
* ``"alg:hash"``  (single colon, e.g. ``sha1:abc``)    -> ("alg", "hash")
* ``"vendor:alg:hash"`` (e.g. ``arista:sha512:$6$..``) -> ("alg", "hash")
* ``"<digit> <payload>"`` (e.g. ``9 $9$..``, ``5 $1$..``)  -> ("<digit>", "payload")

Each target vendor codec calls :func:`is_migratable` before emitting
a ``password`` line.  When the hash cannot be consumed, the codec
should emit a ``format_review_comment`` line in the appropriate
comment syntax for that vendor and skip the password command — never
fall back to plaintext (would leak the hash literal as the password).

See also:
- netconfig/migration/codecs/aruba_aoss/render.py — original implementation
- tests/fixtures/real/user_smoke_findings.md issue #1 — bug report
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Algorithm vocabulary
# ---------------------------------------------------------------------------

#: Algorithms that NO target codec can re-use across vendors.  Each of
#: these is a one-way hash whose binary format is not portable between
#: vendor families.  When the source hash matches one of these, the
#: target codec must emit a comment-form review line and skip the
#: password command.
_UNIVERSALLY_UNMIGRATABLE: frozenset[str] = frozenset({
    "5",         # Cisco IOS type-5 (md5crypt with leading "5 ")
    "7",         # Cisco IOS type-7 reversible XOR
    "8",         # Cisco IOS-XE type-8 (PBKDF2-SHA256)
    "9",         # Cisco IOS-XE type-9 (scrypt)
    "sha512",    # Arista / generic crypt $6$ — not all targets accept
    "bcrypt",    # OPNsense / pfSense / generic $2y$
    "fortios",   # FortiGate ENC-encrypted blob
    "md5crypt",  # Synonym for some sources tagged as "md5crypt:..."
})

#: Per-target accepted algorithms.  ``"plaintext"`` is implicitly
#: accepted by every target (we just emit the literal password).
#:
#: Notes on individual targets:
#:
#: * ``aruba_aoss`` accepts ``plaintext`` plus the two hex hash forms
#:   AOS-S's ``password manager`` command can ingest verbatim.
#: * ``fortigate_cli`` only accepts its own ``ENC <blob>`` format
#:   (tagged ``fortios:`` here); foreign hashes cannot be consumed.
#: * ``juniper_junos`` accepts crypt-format $1$ (md5) and $6$
#:   (sha512) — they're recognised by the Junos commit-time hasher.
#:   Pure ``sha512`` from Arista IS migratable to Junos.
#: * ``opnsense`` is FreeBSD/PHP-style and accepts bcrypt ($2y$).
#: * ``mikrotik_routeros`` does NOT accept foreign hashes — RouterOS
#:   re-hashes the supplied password itself.  Plaintext only.
_TARGET_ACCEPTS: dict[str, frozenset[str]] = {
    "aruba_aoss":        frozenset({"plaintext", "sha1", "sha256"}),
    "fortigate_cli":     frozenset({"plaintext", "fortios"}),
    "juniper_junos":     frozenset({"plaintext", "junos_type1", "sha512"}),
    "opnsense":          frozenset({"plaintext", "bcrypt"}),
    "mikrotik_routeros": frozenset({"plaintext"}),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_hash(hashed: str) -> tuple[str, str]:
    """Classify a canonical ``hashed_password`` into (algorithm, payload).

    Mirrors the three input shapes Aruba's ``_split_aos_hash`` handles:

    * ``vendor:alg:payload`` — two-colon vendor-tagged form.  Returns
      ``(alg, payload)`` with the vendor tag dropped.
    * ``alg:payload`` — single-colon tagged form.  Returns ``(alg, payload)``.
    * ``<digit> <payload>`` — bare-digit Cisco form (``5 $1$..``,
      ``9 $9$..``).  Returns ``("<digit>", "<payload>")``.
    * Anything else (no separator, unknown shape) is treated as a
      literal plaintext password and returns ``("plaintext", hashed)``.
      The empty string returns ``("plaintext", "")``.

    Algorithm tokens are normalised to lower-case.  The payload is
    returned verbatim.
    """
    if not hashed:
        return "plaintext", ""

    # Vendor-tagged form: ``arista:sha512:<hash>`` / ``cisco:type9:<hash>``.
    # Two segments before the payload.
    if ":" in hashed:
        first, _, rest = hashed.partition(":")
        if rest and ":" in rest:
            alg, _, payload = rest.partition(":")
            return alg.lower(), payload
        # Single-colon form: ``alg:<value>``.
        return first.lower(), rest

    # Bare leading-digit Cisco form: ``5 $1$...`` / ``9 $9$...``.
    head, sep, tail = hashed.partition(" ")
    if sep and head in {"5", "7", "8", "9"}:
        return head, tail

    # No algorithm tag — treat as literal plaintext password.
    return "plaintext", hashed


def is_migratable(hashed: str, target_vendor: str) -> bool:
    """Return True if ``hashed`` can be re-emitted on ``target_vendor``.

    Plaintext is always migratable.  Otherwise the algorithm token
    extracted by :func:`classify_hash` must appear in the target's
    accepted set.  Unknown vendors are conservatively treated as
    accepting only plaintext.
    """
    algorithm, _payload = classify_hash(hashed)
    if algorithm == "plaintext":
        return True
    accepted = _TARGET_ACCEPTS.get(target_vendor, frozenset({"plaintext"}))
    return algorithm in accepted


_COMMENT_PREFIXES: dict[str, tuple[str, str]] = {
    "hash":      ("# ", ""),
    "semicolon": ("; ", ""),
    "slash":     ("/* ", " */"),
    "xml":       ("<!-- ", " -->"),
}


def format_review_comment(
    user_name: str,
    algorithm: str,
    comment_syntax: str = "hash",
) -> str:
    """Build a one-line review comment naming an unmigratable hash.

    The body follows the wording Aruba already uses so cross-vendor
    diffs read consistently::

        password manager user-name "<name>" -- review: <alg> hash from
        source vendor cannot be re-used on this target; reset this
        user password manually

    ``comment_syntax`` selects the comment delimiter:

    ===========  ==========================================
    Value        Vendors
    ===========  ==========================================
    ``hash``     Cisco IOS / IOS-XE, MikroTik, fortigate
    ``semicolon`` Aruba AOS-S, Junos
    ``slash``    C-style block (rarely used)
    ``xml``      OPNsense XML config
    ===========  ==========================================

    The wording uses "this target" rather than naming a specific
    vendor — codecs that prefer vendor-specific phrasing (Aruba does)
    can keep building their comment line themselves.
    """
    prefix, suffix = _COMMENT_PREFIXES.get(comment_syntax, ("# ", ""))
    body = (
        f'password manager user-name "{user_name}" -- review: '
        f"{algorithm} hash from source vendor cannot be re-used on "
        f"this target; reset this user password manually"
    )
    return f"{prefix}{body}{suffix}"
