"""Shared, vendor-neutral helpers for the CLI / text codecs.

These small pure functions were independently duplicated across several
codecs (the "duplicate rather than lift" convention noted in the older
per-codec docstrings).  Because they are vendor-neutral — IEEE MAC
canonicalisation, RFC 4291 link-local detection, and dotted-mask ⇄ CIDR
conversion — a single shared copy removes the drift risk without coupling
the codecs to one another's grammar.

Import as ``from .._helpers import <name>`` from inside a codec package
(e.g. ``codecs/cisco_iosxe_cli/parse.py``).

The functions that can fail take a keyword-only ``vendor`` argument so the
raised :class:`ParseError` / :class:`RenderError` still names the codec
whose input was malformed (preserving the diagnostics that the previous
per-codec copies emitted).
"""

from __future__ import annotations

import ipaddress
import re

from .base import ParseError, RenderError


def _normalise_mac_to_colon_hex(mac: str) -> str:
    """Normalise a vendor MAC representation to canonical colon-hex.

    Accepts the common operator-paste forms — dotted-triplet
    (``0001.c73a.0000``, Cisco / NX-OS native), colon-hex
    (``00:01:c7:3a:00:00``, canonical / Unix), or dash-hex
    (``00-01-C7-3A-00-00``, Windows / IEEE) — and returns the lower-case
    ``aa:bb:cc:dd:ee:ff`` form.  Returns the empty string for input it
    cannot classify (12 hex digits expected) so the caller skips the
    field rather than poisoning it with malformed data.
    """
    if not mac:
        return ""
    hex_only = re.sub(r"[^0-9a-f]", "", mac.strip().lower())
    if len(hex_only) != 12:
        return ""
    return ":".join(hex_only[i:i + 2] for i in range(0, 12, 2))


def _is_link_local_v6(addr: str) -> bool:
    """Return True iff *addr* is in the IPv6 link-local prefix fe80::/10.

    The prefix (RFC 4291 §2.4) is vendor-neutral: the first byte is 0xfe
    and the second nibble is 8/9/a/b (binary ``1111111010`` — ten leading
    ones).  This lets a codec recover link-local scope on a raw
    ``fe80::`` line even when the operator omits the vendor
    ``link-local`` keyword.  Only the leading characters are inspected,
    so malformed / over-``::`` inputs return False rather than raising —
    downstream canonical-build validation rejects a truly bad address.
    """
    if not addr:
        return False
    lo = addr.lower()
    return len(lo) >= 3 and lo[:2] == "fe" and lo[2] in ("8", "9", "a", "b")


def _mask_to_prefix(mask_str: str, *, vendor: str) -> int:
    """Convert a dotted-decimal IPv4 subnet mask to a CIDR prefix length.

    Raises :class:`ParseError` (prefixed with *vendor*) for an address
    that is not a valid dotted quad or whose set bits are not
    left-contiguous (e.g. ``255.0.255.0``).  The mask is zero-padded to
    the full 32 bits before the contiguity check so a mask whose leading
    octet is zero (e.g. the non-contiguous ``0.255.0.0``) is correctly
    rejected rather than silently mis-counted.
    """
    try:
        addr = ipaddress.IPv4Address(mask_str)
    except ipaddress.AddressValueError as e:
        raise ParseError(
            f"{vendor}: invalid subnet mask {mask_str!r}",
            snippet=mask_str,
        ) from e
    bits = bin(int(addr))[2:].zfill(32)
    if "01" in bits:
        raise ParseError(
            f"{vendor}: non-contiguous subnet mask {mask_str!r}",
            snippet=mask_str,
        )
    return bits.count("1")


def _prefix_to_mask(prefix: int, *, vendor: str) -> str:
    """Convert a CIDR prefix length to a dotted-decimal IPv4 subnet mask.

    Inverse of :func:`_mask_to_prefix`.  Used by render() for the Cisco
    ``ip address X Y`` / ``ipv4 address X Y`` forms that require a dotted
    mask (every other shipped codec uses CIDR natively, so the canonical
    tree holds prefix lengths and we expand on render).  Raises
    :class:`RenderError` (prefixed with *vendor*) when *prefix* is
    outside 0..32.
    """
    if not (0 <= prefix <= 32):
        raise RenderError(
            f"{vendor}: prefix length {prefix} out of range",
            yang_path="/interfaces/interface/ipv4/address/prefix-length",
        )
    mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0
    return str(ipaddress.IPv4Address(mask_int))


def _parse_vlan_list(text: str) -> list[int]:
    """Parse a VLAN id-list like ``1,10,2000`` or ``10-20`` into a flat
    list of ints.  Ranges are expanded inclusively.

    Shared by the codecs whose id-lists use the Cisco-style comma/hyphen
    grammar (``cisco_nxos``, ``cisco_iosxe_cli``, ``aruba_aoscx`` each
    previously carried a byte-identical private copy).  The valid VLAN
    space is clamped BEFORE the range is materialised so an out-of-bounds
    span (e.g. ``1-9999999999``) cannot OOM the process; the valid
    sub-range is preserved (lossless vs the downstream 1..4094 filter).
    Non-numeric tokens are skipped.  The inverse is
    :func:`_coalesce_vlan_ids`.
    """
    result: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                lo_i, hi_i = int(lo.strip()), int(hi.strip())
            except ValueError:
                continue
            lo_i, hi_i = max(1, lo_i), min(4094, hi_i)
            if lo_i <= hi_i:
                result.extend(range(lo_i, hi_i + 1))
        elif part.isdigit():
            result.append(int(part))
    return result


def _run_token(lo: int, hi: int) -> str:
    """Format a single consecutive run for :func:`_coalesce_vlan_ids`.

    A two-wide run (``10,11``) stays comma-separated rather than
    ``10-11`` — both re-parse identically, but the comma form matches the
    show-output convention for adjacent pairs.
    """
    if hi == lo:
        return str(lo)
    if hi == lo + 1:
        return f"{lo},{hi}"
    return f"{lo}-{hi}"


def _coalesce_vlan_ids(ids: list[int]) -> str:
    """Coalesce a sorted, de-duplicated VLAN-id list into comma/hyphen form.

    ``[1, 10, 11, 12, 20]`` → ``"1,10-12,20"``.  Consecutive runs of three
    or more collapse to ``lo-hi``; the inverse of :func:`_parse_vlan_list`
    so a ``vlan trunk allowed`` / id-list round-trips.  Shared by the
    codecs that previously carried a byte-identical private copy
    (``cisco_nxos``, ``aruba_aoscx``).  The caller is responsible for
    sorting and de-duplicating *ids* first.
    """
    if not ids:
        return ""
    parts: list[str] = []
    run_start = prev = ids[0]
    for vid in ids[1:]:
        if vid == prev + 1:
            prev = vid
            continue
        parts.append(_run_token(run_start, prev))
        run_start = prev = vid
    parts.append(_run_token(run_start, prev))
    return ",".join(parts)
