"""Guard: a codec's module-header ``Certainty:`` line must match its
declared ``certainty`` ClassVar.

Project review 2026-06-06, finding R-05 / DE-01: the 2026-05-21 audit
promoted Aruba + MikroTik to ``certified`` in code, but the docs-audit
only fixed MikroTik's header — Aruba's ``__init__.py`` header still
claimed ``best_effort`` while ``codec.py`` declared ``certified``.  This
test mechanically enforces header↔code agreement for every codec that
declares a ``Certainty:`` line, so the contradiction can't recur.

Every real codec declares a ``Certainty:`` line; only the internal ``mock``
test codec omits one and is skipped.  A real codec with no header now FAILS
(HEAD-review T10) so a codec can't dodge the guard by deleting its header line
instead of updating it — the guard checks consistency where the claim is made
AND that every real codec makes the claim.
"""

from __future__ import annotations

import importlib
import re

import pytest

from netcanon.migration.codecs.registry import get_codec, list_codecs

pytestmark = pytest.mark.unit

# Matches both `Certainty: certified` and the RST-backticked
# `Certainty: ``certified``` header forms.
_CERTAINTY_RE = re.compile(r"Certainty:\s*`*([a-z_]+)`*", re.IGNORECASE)


@pytest.mark.parametrize("name", sorted(list_codecs()))
def test_header_certainty_matches_classvar(name):
    codec = get_codec(name)
    # The codec class lives in `<pkg>.codec`; its package __init__ holds
    # the module header we're checking.
    pkg_name = type(codec).__module__.rsplit(".", 1)[0]
    doc = importlib.import_module(pkg_name).__doc__ or ""

    m = _CERTAINTY_RE.search(doc)
    if m is None:
        # Only the internal `mock` test codec omits a Certainty header; every
        # real codec declares one (verified at HEAD).  Fail — not skip — for a
        # real codec so a codec can't dodge this header↔code guard by DELETING
        # its header line instead of updating it when demoted (T10).
        if name == "mock":
            pytest.skip(f"{name}: internal test codec declares no 'Certainty:' line")
        pytest.fail(
            f"{name}: package header ({pkg_name}) declares no 'Certainty:' line "
            "— every real codec must declare one (a demoted codec must UPDATE "
            "its header, not delete the line)."
        )

    header_value = m.group(1)
    assert header_value == codec.certainty, (
        f"{name}: module header says Certainty={header_value!r} but the codec "
        f"declares certainty={codec.certainty!r} — update the {pkg_name} "
        "header to match the code (finding R-05 / DE-01)."
    )
