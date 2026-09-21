"""Cross-codec user-secret migration policy.

Recognises hash-algorithm formats that cannot be re-used on
a target vendor and exposes helpers each codec calls before
emitting password material.  Centralises the policy that was
previously duplicated in aruba_aoss/render.py.

Canonical ``CanonicalLocalUser.hashed_password`` carries vendor-tagged
hashes from many sources.  The shapes observed in real captures and
the synthetic round-trip fixtures are:

* ``"alg:hash"``  (single colon, e.g. ``sha1:abc``)    -> ("alg", "hash")
* ``"vendor:alg:hash"`` (e.g. ``arista:sha512:$6$..``) -> ("alg", "hash")
* ``"<digit> <payload>"`` (e.g. ``9 $9$..``, ``5 $1$..``)  -> ("<digit>", "payload")
* bare crypt(3) / vendor ciphertext (e.g. ``$6$..``, ``AQB..``)
  -> ("<algorithm>", "<whole string>") via :data:`_STRUCTURED_PREFIXES`
* structured but unmodelled (any other ``$id$`` shape)  -> (:data:`_UNKNOWN`, ...)
* anything else (no separator, no structure)            -> ("plaintext", ...)

⚠️ The last line is a FAIL-OPEN default and is deliberately narrow.  It
used to catch everything unrecognised, including bare crypt strings —
so ``$6$..`` classified as plaintext, ``is_migratable`` returned True,
and the Arista render emitted it under ``secret 0``, EOS's cleartext
marker: the digest became the password, on 14 of 14 VyOS records.  Only
genuinely unstructured values reach it now.  Guarded by
``tests/unit/migration/test_secret_fail_open.py``.

Each target vendor codec calls :func:`is_migratable` before emitting
a ``password`` line.  When the hash cannot be consumed, the codec
should emit a ``format_review_comment`` line in the appropriate
comment syntax for that vendor and skip the password command — never
fall back to plaintext (would leak the hash literal as the password).

See also:
- netcanon/migration/codecs/aruba_aoss/render.py — original implementation
- tests/fixtures/real/user_smoke_findings.md issue #1 — bug report

Public surface:

* :func:`classify_hash` — split a vendor-tagged
  ``CanonicalLocalUser.hashed_password`` value into
  ``(algorithm, payload)`` per the four shapes documented above.
* :func:`is_migratable` — predicate: can *this* algorithm be re-emitted
  on *that* target vendor?  Codecs call this before deciding whether to
  emit a ``password`` line or a review-comment line.
* :func:`format_review_comment` — vendor-correct comment-syntax
  formatter for the review line emitted when a hash can't be migrated.

Configuration surface:

* ``_UNIVERSALLY_UNMIGRATABLE`` — descriptive only.  NOT consulted by
  :func:`is_migratable`, which decides purely from ``_TARGET_ACCEPTS``.
  Its contents in fact contradict that table (it lists ``sha512`` and
  ``bcrypt``, which ``arista_eos``/``juniper_junos``/``opnsense`` do
  accept), so wiring it in would break working migrations.  Retained
  because a unit test asserts its membership; relabelled so the next
  reader is not misled into treating it as policy.
* ``_TARGET_ACCEPTS`` — per-target accepted-algorithm sets; the
  positive list backing :func:`is_migratable`.
* ``_COMMENT_PREFIXES`` — per-target ``(open, close)`` comment-syntax
  tuples used by :func:`format_review_comment`.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Algorithm vocabulary
# ---------------------------------------------------------------------------

#: ⚠️ DESCRIPTIVE ONLY — nothing in production reads this.
#: :func:`is_migratable` decides from :data:`_TARGET_ACCEPTS` alone, and
#: this set contradicts it (``sha512`` and ``bcrypt`` below ARE accepted
#: by ``arista_eos`` / ``juniper_junos`` / ``opnsense``), so wiring it in
#: would break working migrations rather than harden them.  Kept because
#: ``test_universally_unmigratable_membership`` asserts its contents.
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
#: * ``arista_eos`` accepts ``plaintext`` plus the algorithms whose
#:   payloads EOS's ``secret`` command can consume natively:
#:   ``"5"`` (Cisco bare-digit md5crypt), ``"md5crypt"`` (synonym
#:   tagged form), and ``"sha512"`` (Arista vendor-tagged or generic
#:   ``$6$``).  These keys mirror :data:`_ARISTA_SECRET_TYPE` in
#:   ``codecs/arista_eos/render.py`` exactly — the shared helper
#:   gates migratability while the codec-local table dispatches
#:   ``algorithm -> "secret <N>"`` tag for the emit form.
#: * ``cisco_iosxe_cli`` accepts the Cisco-native bare-digit forms
#:   plus the ``md5crypt`` alias.
#: * ``fortigate_cli`` only accepts its own ``ENC <blob>`` format
#:   (tagged ``fortios:`` here); foreign hashes cannot be consumed.
#: * ``juniper_junos`` accepts crypt-format $1$ (md5) and $6$
#:   (sha512) — they're recognised by the Junos commit-time hasher.
#:   Pure ``sha512`` from Arista IS migratable to Junos.
#: * ``opnsense`` verifies local passwords with PHP ``password_verify()``,
#:   which consumes any crypt(3) hash.  It accepts bcrypt ($2y$) and SHA-512
#:   crypt ($6$); the latter is evidenced by real OPNsense HA configs in the
#:   corpus.  MD5 crypt is not accepted: no OPNsense capture carries it.
#: * ``mikrotik_routeros`` does NOT accept foreign hashes — RouterOS
#:   re-hashes the supplied password itself.  Plaintext only.
#: * ``cisco_nxos`` writes every crypt(3) form under ``password 5``:
#:   ``$5$`` (its default) and the legacy ``$1$``.
#: * ``cisco_iosxr`` takes ``secret 5`` ($1$), ``8`` ($8$), ``9`` ($9$),
#:   ``10`` ($6$) and ``password 7``; a bare ``$6$`` re-tags as type 10.
#: * ``vyos`` stores a Linux crypt(3) string in ``encrypted-password``
#:   ($1$ / $5$ / $6$); plaintext goes to ``plaintext-password``.
#: * ``aruba_aoscx`` only takes its own ``AQB`` ciphertext (device-keyed)
#:   or ``password plaintext``.
#:
#: Each of those four codecs keeps a codec-local emit table whose keys
#: mirror its entry here exactly; a guard test asserts the two agree, so an
#: accepted token can never reach a render with no emit form.
#: Structured-secret prefixes -> algorithm token.  These are secrets that
#: carry NO algorithm tag of their own: a bare crypt(3) string (the form
#: VyOS stores natively) or a vendor ciphertext blob.  Before this table
#: existed they matched none of the tagged shapes above and fell through to
#: the plaintext default, so a digest could be re-emitted as the password
#: itself under a target's cleartext marker.
#:
#: Longest-prefix-first ordering matters: ``$2y$`` must be tested before a
#: hypothetical ``$2`` entry.  crypt(3) ids follow crypt(5).
#:
#: ⚠️ ``$5$`` maps to ``sha256crypt``, deliberately NOT to ``sha256``.
#: ``sha256`` is the token ``aruba_aoss`` accepts, and it means a raw hex
#: digest its ``password manager`` command ingests verbatim — not a crypt
#: string.  Reusing that token would hand AOS-S a value it cannot consume
#: while passing the migratability gate: a new fail-open wearing the shape
#: of a fix.  Guarded by
#: ``tests/unit/migration/test_secret_fail_open.py``.
_STRUCTURED_PREFIXES: tuple[tuple[str, str], ...] = (
    ("$1$",  "md5crypt"),      # crypt(3) MD5
    ("$2a$", "bcrypt"),
    ("$2b$", "bcrypt"),
    ("$2x$", "bcrypt"),
    ("$2y$", "bcrypt"),        # OPNsense / FreeBSD / PHP
    ("$5$",  "sha256crypt"),   # NOT "sha256" — see the warning above
    ("$6$",  "sha512"),        # VyOS native; EOS + Junos can consume it
    ("$7$",  "scrypt"),
    ("$9$",  "junos_type9"),  # Juniper reversible; native ON Junos only
    ("$y$",  "yescrypt"),
    ("AQB",  "aoscx_encrypted"),  # ArubaOS-CX user-password ciphertext
)

#: Sentinel for a structured secret whose format is not in the table above.
#: It is deliberately absent from every entry of :data:`_TARGET_ACCEPTS`, so
#: :func:`is_migratable` refuses it — the *next* unseen secret format fails
#: closed rather than open.  :func:`is_migratable` also refuses it
#: explicitly, so adding it to an accept set cannot silently reopen the
#: hole.
_UNKNOWN = "unknown"

#: Tags that are a vendor ENVELOPE rather than an algorithm.  The Junos parser
#: stores every account secret as ``junos:<value>`` whatever the value is —
#: ``$1$`` MD5 crypt, ``$6$`` SHA-512 crypt, or a sanitisation placeholder —
#: so the tag says where the secret came from, not how to consume it.
_ENVELOPE_TAGS: frozenset[str] = frozenset({"junos"})

#: Tags that DO name a crypt(3) algorithm, but can be wrong.  The OPNsense
#: parser tags every password ``bcrypt:`` unconditionally, and real HA
#: fixtures carry a ``$6$`` SHA-512 crypt body behind that tag.
_CRYPT_FAMILY_TAGS: frozenset[str] = frozenset({
    "md5crypt", "bcrypt", "sha256crypt", "sha512", "scrypt", "yescrypt",
})

#: crypt(3) ids whose presence in the payload overrides an envelope or a
#: contradicting crypt-family tag.  ``$9$`` is deliberately absent: it is
#: Juniper's reversible form AND Cisco's type-9 scrypt, so the id alone
#: cannot decide.  ``AQB`` is vendor ciphertext, not crypt(3).
_CRYPT_ID_PREFIXES: tuple[tuple[str, str], ...] = tuple(
    (prefix, algorithm) for prefix, algorithm in _STRUCTURED_PREFIXES
    if prefix.startswith("$") and prefix != "$9$"
)


def _trust_payload_id(tag: str, payload: str) -> str:
    """Resolve the algorithm of a tagged secret.

    A tag is kept unless it is an envelope (:data:`_ENVELOPE_TAGS`) or a
    crypt-family name (:data:`_CRYPT_FAMILY_TAGS`), in which case the
    payload's own crypt(3) id wins.  Before this, ``junos:$6$...`` classified
    as the algorithm ``junos`` and ``bcrypt:$6$...`` as ``bcrypt``: every
    target refused the first, and the second was handed to OPNsense and every
    other bcrypt consumer as if it were bcrypt.  Both failed CLOSED, so this
    recovers credentials rather than closing a leak.  A payload with no
    recognisable id keeps its tag, so a sanitisation placeholder behind
    ``junos:`` is still refused everywhere but Junos.
    """
    if tag not in _ENVELOPE_TAGS and tag not in _CRYPT_FAMILY_TAGS:
        return tag
    for prefix, algorithm in _CRYPT_ID_PREFIXES:
        if payload.startswith(prefix):
            return algorithm
    if tag in _ENVELOPE_TAGS and payload.startswith("$9$"):
        return "junos_type9"
    return tag


_TARGET_ACCEPTS: dict[str, frozenset[str]] = {
    "aruba_aoss":        frozenset({"plaintext", "sha1", "sha256"}),
    "arista_eos":        frozenset({"plaintext", "5", "md5crypt", "sha512"}),
    "cisco_iosxe_cli":   frozenset({"plaintext", "5", "7", "8", "9", "md5crypt"}),
    "fortigate_cli":     frozenset({"plaintext", "fortios"}),
    "juniper_junos":     frozenset({"plaintext", "junos_type1", "junos_type9", "sha512"}),
    "opnsense":          frozenset({"plaintext", "bcrypt", "sha512"}),
    "mikrotik_routeros": frozenset({"plaintext"}),
    "cisco_nxos":        frozenset({"plaintext", "5", "md5crypt", "sha256crypt"}),
    # Dell OS10 stores `username ... password <crypt>` with NO type digit.
    # The switch writes SHA-512 ($6$) itself, and the User Guide documents
    # MD-5 / SHA-256 / SHA-512 as accepted for backward compatibility with
    # releases up to 10.3.1E — hence the three crypt(3) families.  There is
    # no codec-local emit table to mirror (no type digit to dispatch on).
    "dell_os10":         frozenset({
        "plaintext", "md5crypt", "sha256crypt", "sha512",
    }),
    "cisco_iosxr":       frozenset({
        "plaintext", "5", "md5crypt", "7", "8", "9", "10", "sha512",
    }),
    "vyos":              frozenset({
        "plaintext", "5", "md5crypt", "sha256crypt", "10", "sha512",
    }),
    "aruba_aoscx":       frozenset({"plaintext", "aoscx_encrypted"}),
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
            return _trust_payload_id(alg.lower(), payload), payload
        # Single-colon form: ``alg:<value>``.  The tag may be an envelope
        # (``junos:``) or a wrong algorithm name (OPNsense's unconditional
        # ``bcrypt:``) — see :func:`_trust_payload_id`.
        return _trust_payload_id(first.lower(), rest), rest

    # Bare leading-digit Cisco form: ``5 $1$...`` / ``9 $9$...``.
    # ``10`` is IOS-XR's sha512crypt wrapper.  It is recognised here (rather
    # than left to fall through) because the whole string — type number and
    # all — was previously treated as a plaintext password, which made the
    # literal ``10`` the credential on the target.  No accept set contains
    # "10": the payload is a portable ``$6$`` and COULD be re-tagged for a
    # target that takes sha512, but that is a migration improvement rather
    # than a security fix, so this change refuses and leaves the operator a
    # review comment instead of guessing.
    head, sep, tail = hashed.partition(" ")
    if sep and head in {"5", "7", "8", "9", "10"}:
        # Type 5 is NOT always md5crypt.  IOS / IOS-XE / IOS-XR / EOS put a
        # ``$1$`` behind it, but NX-OS writes EVERY crypt(3) variant under
        # ``password 5`` — and its default is ``$5$`` (sha256crypt; 10 of 10
        # corpus records).  Tagging that "5" told EOS and IOS-XE it was
        # md5crypt, so ``secret 5 $5$...`` passed the gate and produced an
        # account nobody could log in to.  Route by the payload's own id.
        if head == "5" and tail.startswith("$5$"):
            return "sha256crypt", tail
        if head == "5" and tail.startswith("$6$"):
            return "sha512", tail
        return head, tail

    # Structured secret carrying no algorithm tag of its own: a bare crypt
    # string or a vendor ciphertext blob.
    for prefix, algorithm in _STRUCTURED_PREFIXES:
        if hashed.startswith(prefix):
            return algorithm, hashed

    # Unrecognised but structurally a secret: anything in ``$id$`` shape we
    # do not model.  Fail CLOSED — see :data:`_UNKNOWN`.
    if hashed.startswith("$"):
        return _UNKNOWN, hashed

    # Genuinely untagged and unstructured — a password a human typed.
    # The corpus has one: a 5-character alphanumeric secret on an AOS-CX
    # ``admin`` account.  Refusing everything unrecognised would catch that
    # too, which is why the rule keys on structured-secret SHAPE rather than
    # on "did I recognise it".
    return "plaintext", hashed


def is_migratable(hashed: str, target_vendor: str) -> bool:
    """Return True if ``hashed`` can be re-emitted on ``target_vendor``.

    Plaintext is always migratable.  Otherwise the algorithm token
    extracted by :func:`classify_hash` must appear in the target's
    accepted set.  Unknown vendors are conservatively treated as
    accepting only plaintext.

    A secret whose format is structured but unmodelled (:data:`_UNKNOWN`)
    is refused outright, ahead of the accept-set lookup.  The lookup
    alone would already refuse it — no target lists the sentinel — but
    stating the rule here means a later edit that adds the sentinel to an
    accept set cannot silently reopen the fail-open this guards.  The
    caller is expected to emit a review comment and skip the password
    line; never to fall back to plaintext, which is what made a digest
    the credential in the first place.
    """
    algorithm, _payload = classify_hash(hashed)
    if algorithm == _UNKNOWN:
        return False
    if algorithm == "plaintext":
        return True
    accepted = _TARGET_ACCEPTS.get(target_vendor, frozenset({"plaintext"}))
    return algorithm in accepted


_COMMENT_PREFIXES: dict[str, tuple[str, str]] = {
    "hash":        ("# ", ""),
    "semicolon":   ("; ", ""),
    "slash":       ("/* ", " */"),
    "xml":         ("<!-- ", " -->"),
    "exclamation": ("! ", ""),
}


def format_review_comment(
    user_name: str,
    algorithm: str,
    comment_syntax: str = "hash",
    target_label: str = "this target",
) -> str:
    """Build a one-line review comment naming an unmigratable hash.

    The body follows the wording Aruba already uses so cross-vendor
    diffs read consistently::

        password manager user-name "<name>" -- review: <alg> hash from
        source vendor cannot be re-used on <target_label>; reset this
        user password manually

    ``comment_syntax`` selects the comment delimiter:

    ============  ==========================================
    Value         Vendors
    ============  ==========================================
    ``hash``      MikroTik, fortigate, Junos
    ``semicolon`` Aruba AOS-S
    ``slash``     C-style block (rarely used)
    ``xml``       OPNsense XML config
    ``exclamation`` Cisco IOS / IOS-XE, Arista EOS
    ============  ==========================================

    ``target_label`` lets each codec inject a vendor-specific label
    ("Cisco IOS-XE", "Junos", "Arista EOS", "FortiOS", "RouterOS")
    so operator-readable comments name the actual target rather
    than the generic "this target" default.  Aruba builds its own
    comment line locally with "AOS-S" wording — this parameter
    matches that pattern for codecs that consume the helper.

    XML safety: the XML 1.0 spec forbids the literal ``--`` substring
    inside a comment body (``<!-- ... -->``); the parser treats it as
    premature termination of the comment.  When ``comment_syntax`` is
    ``"xml"`` the body separator collapses from ``--`` to a single
    ``-`` so the output is embeddable directly into XML without
    post-processing.  All other comment syntaxes keep the ``--``
    separator byte-for-byte (Aruba / FortiGate / Junos rely on it).
    """
    prefix, suffix = _COMMENT_PREFIXES.get(comment_syntax, ("# ", ""))
    # XML 1.0 disallows ``--`` inside comment bodies — collapse to a
    # single hyphen for the xml variant only.  Other syntaxes keep the
    # original ``-- review:`` separator byte-identical (existing Aruba
    # / FortiGate / Junos output stays unchanged).
    separator = "-" if comment_syntax == "xml" else "--"
    body = (
        f'password manager user-name "{user_name}" {separator} review: '
        f"{algorithm} hash from source vendor cannot be re-used on "
        f"{target_label}; reset this user password manually"
    )
    return f"{prefix}{body}{suffix}"
