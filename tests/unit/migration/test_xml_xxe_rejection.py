"""XXE / entity-bomb rejection for operator-uploaded XML configs.

Netcanon parses XML config families (OPNsense ``config.xml`` + Cisco
IOS-XE NETCONF) and routes them through defusedxml's hardened
``fromstring``.  The dependency is pinned in ``pyproject.toml`` with a
rationale comment, but no test previously fed a malicious payload to
confirm the guard actually fires end-to-end through a codec's parse
path.  These tests feed a recursive entity bomb ("billion laughs") and
an external-entity (XXE) payload and assert they are rejected as a
``ParseError`` rather than expanded (run3 ``no-xxe-payload-test``).
"""

from __future__ import annotations

import pytest

from netcanon.migration.codecs.base import ParseError
from netcanon.migration.codecs.opnsense.codec import OPNsenseCodec

pytestmark = pytest.mark.unit


# Recursive entity expansion: a naive parser would balloon memory
# expanding &lol3; into thousands of "lol" copies.  defusedxml refuses
# any DOCTYPE-defined entity.
_BILLION_LAUGHS = (
    '<?xml version="1.0"?>\n'
    "<!DOCTYPE opnsense [\n"
    '  <!ENTITY lol "lol">\n'
    '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
    '  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
    "]>\n"
    "<opnsense><system><hostname>&lol3;</hostname></system></opnsense>"
)

# External-entity (XXE): a naive parser would read a local file off
# disk and inline it.  defusedxml refuses external references.
_XXE_FILE_READ = (
    '<?xml version="1.0"?>\n'
    "<!DOCTYPE opnsense [\n"
    '  <!ENTITY xxe SYSTEM "file:///etc/passwd">\n'
    "]>\n"
    "<opnsense><system><hostname>&xxe;</hostname></system></opnsense>"
)


class TestOpnsenseXxeRejection:
    @pytest.mark.parametrize(
        "payload,label",
        [
            (_BILLION_LAUGHS, "billion-laughs"),
            (_XXE_FILE_READ, "external-entity"),
        ],
    )
    def test_malicious_doctype_is_rejected(self, payload: str, label: str) -> None:
        with pytest.raises(ParseError):
            OPNsenseCodec().parse(payload)

    def test_benign_config_still_parses(self) -> None:
        """The rejection is targeted at DOCTYPE / entities — a plain
        ``config.xml`` with no DOCTYPE parses without raising."""
        benign = (
            '<?xml version="1.0"?>\n'
            "<opnsense><system><hostname>fw1</hostname></system></opnsense>"
        )
        intent = OPNsenseCodec().parse(benign)
        assert intent.hostname == "fw1"


def test_shared_safe_fromstring_rejects_entity_bomb() -> None:
    """Library-level guard: the hardened parser the XML codecs share
    (``defusedxml.ElementTree.fromstring``) refuses the entity bomb
    regardless of per-codec wrapping — proves the dependency is doing
    its job, not silently no-op'd by an import swap."""
    from defusedxml.common import DefusedXmlException
    from defusedxml.ElementTree import fromstring as safe_fromstring

    with pytest.raises(DefusedXmlException):
        safe_fromstring(_BILLION_LAUGHS)
