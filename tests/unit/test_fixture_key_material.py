"""A user-contributed capture must carry no key material.

The ``user_contrib_*`` files under ``tests/fixtures/real/`` are configs taken
from real devices (see ``tests/fixtures/real/NOTICE.md``), so whatever key
material the device held, the capture held too.  Sanitising one by hand is
easy to get almost right, and a block that was missed fails nothing, because
nothing looks.

This module looks.  It covers the two shapes key material takes in these
captures; a third-party capture keeps whatever its upstream published, so it
is out of scope here and its licence row in ``NOTICE.md`` says where it came
from.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REAL = Path(__file__).resolve().parents[1] / "fixtures" / "real"
_PLACEHOLDER = "REMOVED_FIXTURE_SANITISATION"
_KEY_BLOCK = re.compile(r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----(.*?)-----END \1-----", re.S)
_ENC = re.compile(r"^\s*set \S+ ENC (\S+)", re.M)
_CONTRIB = sorted(_REAL.glob("*/user_contrib_*"))


def test_the_corpus_has_user_contributed_captures() -> None:
    """The glob finds the user-contributed captures.

    Every other test here iterates over that glob.  If the files were renamed
    or moved, the glob would match nothing and those tests would pass while
    checking nothing, so this one fails first.
    """
    assert _CONTRIB, f"no user_contrib_* capture under {_REAL}"


@pytest.mark.parametrize("path", _CONTRIB, ids=lambda p: p.name)
def test_every_private_key_block_is_the_placeholder(path: Path) -> None:
    """Every PEM or OpenSSH private-key block holds only the placeholder.

    A capture may keep the ``-----BEGIN ... PRIVATE KEY-----`` frame, because
    the codecs parse a quoted multi-line value and the frame is the grammar a
    fixture exists to exercise.  The body is the device's key, so it must be
    gone.  An encrypted key counts too: the passphrase that opens it is held
    on the same device, so it is never more than one leak away.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    kept = [
        kind for kind, body in _KEY_BLOCK.findall(text) if body.strip().strip('"').strip() not in ("", _PLACEHOLDER)
    ]
    assert not kept, f"{path.name}: {len(kept)} private-key block(s) still hold key material: {sorted(set(kept))}"


@pytest.mark.parametrize("path", _CONTRIB, ids=lambda p: p.name)
def test_every_fortios_enc_value_is_a_synthetic_marker(path: Path) -> None:
    """Every FortiOS ``ENC`` value is one of the corpus's synthetic markers.

    FortiOS writes a stored secret as ``ENC <base64>``.  For most fields that
    is the secret encrypted with a key every FortiOS image shares (unless the
    device turns on private-data encryption), so it can be reversed; for an
    admin password it is a salted hash, which can be cracked offline.  Either
    way it stands in for a password, so in a user-contributed capture it must
    be a synthetic ``fakeEncodedSecret...`` marker.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    real = [v for v in _ENC.findall(text) if not v.startswith("fakeEncodedSecret")]
    assert not real, f"{path.name}: {len(real)} ENC value(s) are not synthetic markers"
