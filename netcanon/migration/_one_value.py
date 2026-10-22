"""A value is written as ONE value of the place it goes, or not at all.

A renderer puts a value of the tree into its line as it stands.  Most
CLIs read a line a word at a time, so a value that holds white space is
two words there, and the second is read as whatever that place of the
grammar takes next: a keyword, an argument, or nothing (the line is
refused).  The second reading is the dangerous one.  On NX-OS
``snmp-server community public rw`` is a READ-WRITE community
``public``; on EOS the second word of a community is read as an ACL
name; a password ``secret scrypt`` sets the password ``secret``.  The
values come from another vendor's config, which may quote a value with
white space (FortiOS, RouterOS, Junos, VyOS, AOS-S) or hold one as
element text (OPNsense, IOS-XE over NETCONF), and from text nobody
vouches for.

Which places of which grammar read one word, and which read the rest of
the line or a quoted string, is a fact about the vendor, and none of the
word-at-a-time CLIs documents a quoted form for a credential (the
vendor references are in
``docs/reviews/2026-10-20-values-with-white-space/``).  So a SECRET
-- a password, an SNMP community, an SNMPv3 passphrase, an FHRP
authentication key -- or the name of an account that holds white space
is not written there, and is never altered to fit (a secret with a space
replaced is another secret).  The renderer leaves the record out with
the granularity the credential rules set (a local user whole, an SNMPv3
user with every line composing it, a community with every trap host
that would carry it, an FHRP authentication line alone), and writes a
review line that names the place and never the secret.

A grammar that quotes with no escape (AOS-S: HPE documents escapes for
``banner motd`` only) has the same hole one character over: a ``"`` in
a value ends the quoted string, and the rest of the value is CLI words.
:func:`breaks_its_quotes` asks that question.

RADIUS keys are not here yet: their lines are being rewritten for the
stored forms of a key, and are taken up after that change.
"""

from __future__ import annotations


def splits(value: str | None) -> bool:
    """Whether *value* would not stand as one word of a word-at-a-time
    CLI: it holds white space, which ends a word, or a ``"``, which
    NX-OS reads as the start of a quoted string and IOS-XE forbids in
    a user name ("Spaces and quotation marks are not allowed").

    Any character :meth:`str.isspace` takes counts, not only the space
    and the tab: what a device's reader takes for a separator is not
    documented character by character, and a value that is refused for
    a no-break space is the safe side.
    """
    return bool(value) and (
        '"' in value or any(ch.isspace() for ch in value)
    )


def breaks_its_quotes(value: str | None) -> bool:
    """Whether *value* cannot stand between double quotes on a grammar
    that documents no escape: it holds a ``"`` (which ends the string)
    or white space other than the space (which a reader may take for
    the end of the line or of a word)."""
    if not value:
        return False
    return '"' in value or any(ch.isspace() and ch != " " for ch in value)


def left_out(what: str, target_label: str) -> str:
    """The text of the review line for a record left out by this rule.

    *what* names the record (``username alice``, ``an SNMP community``)
    and must not hold a secret: the line is written into the output,
    and the value is the thing that could not be written.
    """
    return (
        f"{what} -- review: a value of it holds white space or a quote, "
        f"which {target_label} does not read as one value; it is left "
        f"out, re-create it on the device"
    )
