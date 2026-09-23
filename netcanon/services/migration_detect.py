"""
Auto-detect which codec can parse a given blob of raw config text.

R5 deliverable: walk every registered codec, call its
:meth:`CodecBase.probe` classmethod with the first ~500 bytes of
*raw*, collect confidence scores, and return a ranked list.

Design principles:
    * **Pure function, no I/O.**  The service lives under
      ``netcanon/services/`` alongside the other pure engines (diff,
      migration_pipeline, migration_validate).
    * **Each codec is the source of truth** for its own format
      signature.  The service does not hard-code per-vendor regexes;
      that logic lives on the codec.
    * **Truncate the prefix** so detection stays O(codecs × constant).
      Real-world configs can be 50K+ lines; reading them fully per
      detection would be wasteful.
    * **Stable order** for ties (highest score first, then codec name
      alphabetically) so the UI doesn't see arbitrary re-shuffling.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..migration.codecs.registry import get_codec, list_public_codecs

#: Bytes of input passed to each codec's probe.
#:
#: This was 500 until #483, on the reasoning that "most real signatures fit in
#: the first 200-300 bytes".  Measured against the committed corpus, that was
#: false often enough to matter: real captures open with collection headers,
#: jinja2 template preambles, login banners, MOTDs and QoS blocks that push
#: the vendor marker past the window.  A codec that never sees its own marker
#: returns no candidate, and the operator gets silence or — worse — a
#: different vendor's weaker marker winning by default.
#:
#: Measured 2026-09-23 over 90 committed fixtures (correct / wrong / silent)
#: and the 40-capture Dell OS10 corpus:
#:
#:     window   committed        dell
#:        500   73 / 0 / 17    19 / 10 / 11
#:       1000   83 / 1 /  6    26 /  6 /  8
#:       1100   85 / 0 /  5    26 /  6 /  8
#:       1500   86 / 1 /  3    28 /  4 /  8
#:       2000   86 / 1 /  3    26 /  6 /  8
#:       4000   87 / 1 /  2    26 /  6 /  8
#:       8000   89 / 0 /  1    27 /  6 /  7
#:      16384   89 / 0 /  1    29 /  4 /  7
#:      65536   90 / 0 /  0    29 /  4 /  7
#:  whole file  90 / 0 /  0    29 /  4 /  7
#:
#: ⚠️ **Widening is NOT monotonic — do not interpolate a value, measure it.**
#: Two committed fixtures are mis-attributed in the middle of the range and
#: correct at both ends: `aruba_aoscx/canu_csm17_spine001_ipv6_vrf.cfg` is
#: claimed by `cisco_iosxe_cli` at 2000 and 4000 but is silent at 500-1000 and
#: correct from 8000, and `cisco_iosxr/xrdtools_sr_xrd1.cfg` is claimed at 1000
#: but correct from 1500.  A larger window admits more of the *wrong* codec's
#: markers as readily as the right one's; only past every marker does the
#: ranking settle.
#:
#: 65536 is where the committed corpus reaches 90/0/0, and it is identical to
#: probing the whole file for every fixture we hold — the cap exists to bound
#: the cost of a pathological paste, not to trade away accuracy.  Cost at this
#: width is ~2.8 ms per file across the corpus.
DEFAULT_PROBE_BYTES = 65536


class DetectCandidate(BaseModel):
    """One row in the auto-detection ranking.

    Attributes:
        codec: The codec's registry name (e.g. ``"opnsense"``).
        confidence: 0-100 score from :meth:`CodecBase.probe`.  Higher
            is better.  See :meth:`CodecBase.probe` for the scoring
            convention.
        reason: Short human-readable explanation of the match.  Shown
            in the UI's auto-detection banner.
    """

    codec: str
    confidence: int = Field(ge=0, le=100)
    reason: str


def detect_codec(
    raw: str,
    *,
    probe_bytes: int = DEFAULT_PROBE_BYTES,
    min_confidence: int = 1,
) -> list[DetectCandidate]:
    """Return a ranked list of codecs that can plausibly parse *raw*.

    Args:
        raw: The raw config text.  Usually from a paste or from a
            ``FileConfigStore.get_content()`` call.
        probe_bytes: How many leading bytes to hand to each codec.
            Kept configurable for tests; production callers should
            leave this at the default.
        min_confidence: Drop candidates below this score.  Default 1
            (keep everything that scored).  Set to 50+ for strict
            matches only.

    Returns:
        List of :class:`DetectCandidate`, sorted by descending
        confidence (ties broken by codec name).  Empty list means
        no codec recognised the input.
    """
    prefix = raw[:probe_bytes] if len(raw) > probe_bytes else raw
    candidates: list[DetectCandidate] = []
    for name in list_public_codecs():
        try:
            codec_cls = type(get_codec(name))
            result = codec_cls.probe(prefix)
        except Exception:  # pragma: no cover — probe MUST NOT raise
            # A malformed codec shouldn't take down detection for the
            # others.  Treat it as "no opinion".
            continue
        if result is None:
            continue
        confidence, reason = result
        if confidence < min_confidence:
            continue
        candidates.append(DetectCandidate(
            codec=name,
            confidence=confidence,
            reason=reason,
        ))
    # Stable sort: descending confidence, then ascending name.
    candidates.sort(key=lambda c: (-c.confidence, c.codec))
    return candidates


def best_codec(
    raw: str,
    *,
    min_confidence: int = 50,
) -> DetectCandidate | None:
    """Convenience: return the top-ranked candidate, or ``None``.

    Intended for callers that want to auto-pre-select a codec without
    rendering the full ranking.

    .. warning::
       **This function has no production caller.**  The example that
       used to sit here -- "the /migrate UI does this when the user
       picks a stored config" -- was false: the UI posts to
       ``/api/v1/migration/detect`` with a hard-coded
       ``min_confidence: 40`` (``migrate.html``), so this 50 floor is
       never applied anywhere a user can reach.  Do not reason about
       operator-facing behaviour from this default.

    Args:
        raw: Raw config text.
        min_confidence: Minimum confidence required — below this the
            function returns ``None`` rather than risk a wrong pick.
            Default 50 (rules out weak-shape-only matches).
    """
    ranked = detect_codec(raw, min_confidence=min_confidence)
    return ranked[0] if ranked else None
