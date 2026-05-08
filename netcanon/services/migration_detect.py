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

from ..migration.codecs.registry import get_codec, list_codecs

#: Bytes of input passed to each codec's probe.  Longer gives better
#: signal for ambiguous formats but most real signatures fit in the
#: first 200-300 bytes.  Keep generous.
DEFAULT_PROBE_BYTES = 500


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
    for name in list_codecs():
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

    Useful for callers that want to auto-pre-select a codec without
    rendering the full ranking (e.g. the /migrate UI does this when
    the user picks a stored config).

    Args:
        raw: Raw config text.
        min_confidence: Minimum confidence required — below this the
            function returns ``None`` rather than risk a wrong pick.
            Default 50 (rules out weak-shape-only matches).
    """
    ranked = detect_codec(raw, min_confidence=min_confidence)
    return ranked[0] if ranked else None
