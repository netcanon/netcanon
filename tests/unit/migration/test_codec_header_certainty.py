"""Guard: a codec's module-header ``Certainty:`` line must match its
declared ``certainty`` ClassVar.

Project review 2026-06-06, finding R-05 / DE-01: the 2026-05-21 audit
promoted Aruba + MikroTik to ``certified`` in code, but the docs-audit
only fixed MikroTik's header — Aruba's ``__init__.py`` header still
claimed ``best_effort`` while ``codec.py`` declared ``certified``.  This
test mechanically enforces header↔code agreement for every codec that
declares a ``Certainty:`` line, so the contradiction can't recur.

Codecs whose header omits a ``Certainty:`` line are skipped (header
uniformity across all codecs is a separate, lower-priority item) — the
guard checks consistency *where the claim is made*, not presence.
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
        pytest.skip(f"{name}: package header declares no 'Certainty:' line")

    header_value = m.group(1)
    assert header_value == codec.certainty, (
        f"{name}: module header says Certainty={header_value!r} but the codec "
        f"declares certainty={codec.certainty!r} — update the {pkg_name} "
        "header to match the code (finding R-05 / DE-01)."
    )
