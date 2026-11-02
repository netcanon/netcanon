"""The PII guard must catch a leak without itself being one.

The guard that ``.github/workflows/pii-guard.yml`` and
``scripts/git-hooks/pre-push`` used to run spelled the maintainer's personal
email local part as a character-class regex, so that it would not match its own
text.  That kept the grep quiet and published the identifier to every reader of
the file.  The scanner that replaced it (``.github/scripts/pii_guard.py``)
matches personal identifiers by sha256 digest instead, listed in
``.github/pii-guard.hashes``.

Two properties keep that true, and this module holds both:

1. **The scanner is not vacuous.**  ``--self-test`` proves each layer (shape,
   digest, character-class spelling, private token) fires on a synthetic canary
   and that clean text passes.  A guard that silently matches nothing would
   pass every PR while protecting nothing.

2. **The hashes file holds digests only.**  Every entry must be a 64-hex
   sha256, so a plaintext identifier can never be "listed" by pasting it in,
   and the canary's digest must stay listed so (1) can run.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _ROOT / ".github" / "scripts" / "pii_guard.py"
_HASHES = _ROOT / ".github" / "pii-guard.hashes"


def test_self_test_proves_every_layer_fires() -> None:
    """``pii_guard.py --self-test`` exits 0: each layer fires on its canary and clean text passes.

    Guards against a scanner edit that breaks a layer (a regex typo, a lost
    squash pass) and so passes every tree without checking it.
    """
    result = subprocess.run(
        [sys.executable, "-I", str(_GUARD), "--self-test"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hashes_file_lists_digests_only_and_keeps_the_canary() -> None:
    """Every entry in ``.github/pii-guard.hashes`` is a sha256 digest, and the canary is listed.

    Guards against the original leak in a new shape: an identifier pasted into
    the list in plaintext is published the moment the file is.  The canary
    must stay listed or the self-test above cannot prove the digest layer.
    """
    entries = []
    for line in _HASHES.read_text(encoding="utf-8").splitlines():
        field = line.split("#", 1)[0].split()
        if field:
            entries.append(field[0])
    assert entries, "the hashes file lists nothing"
    bad = [e[:12] for e in entries if not re.fullmatch(r"[0-9a-f]{64}", e)]
    assert not bad, f"non-digest entries: {bad}"
    canary = "piiguard" + "canary" + "7f3a"
    canary_digest = hashlib.sha256(b"pii-guard/v1:" + canary.encode()).hexdigest()
    assert canary_digest in entries
