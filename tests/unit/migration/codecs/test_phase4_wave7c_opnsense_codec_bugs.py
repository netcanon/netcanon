"""
Wave 7c Agent G regression tests — opnsense source CODEC_BUG cells.

Reproduction tests for the 1 CODEC_BUG cell the post-batch-1 matrix
flagged with ``source_codec=opnsense`` (target ``aruba_aoss``).  Root
cause:

1. Aruba AOS-S render emits ``radius-server host <ip> key "<secret>"``
   only — it never projects ``auth_port`` / ``acct_port`` when the
   canonical record carries non-default ports.  The parser regex
   ``_RADIUS_HOST_RE`` symmetrically refused to accept anything past
   the optional ``key "..."`` clause.  Result: an OPNsense source with
   ``<radius_auth_port>11812</radius_auth_port>`` /
   ``<radius_acct_port>11813</radius_acct_port>`` round-tripped to the
   AOS-S defaults 1812 / 1813.

   Fix: emit a companion ``radius-server host <ip> auth-port <N>
   acct-port <N>`` line whenever a port differs from the AOS-S
   default; symmetrically, accept either inline-port or separate-line
   port grammar in the parser and merge port values onto the matching
   host record.  See ``docs/vendor-references/opnsense_to_aruba_aoss/
   radius.md`` for the grammar reference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netcanon.migration.canonical.intent import (
    CanonicalIntent,
    CanonicalRADIUSServer,
)
from netcanon.migration.codecs.aruba_aoss.parse import (
    parse_intent as aruba_parse,
)
from netcanon.migration.codecs.aruba_aoss.render import (
    render_intent as aruba_render,
)
from netcanon.migration.codecs.opnsense.parse import (
    parse_intent as opnsense_parse,
)

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# opnsense -> aruba_aoss: RADIUS port wire-through
# ---------------------------------------------------------------------------


def test_opnsense_to_aruba_preserves_radius_custom_ports() -> None:
    """The kitchen_sink synthetic OPNsense fixture carries two RADIUS
    servers; the second uses non-default ports (11812 / 11813).  After
    parsing OPNsense XML, rendering AOS-S, and reparsing, both servers
    must keep their port numbers."""
    src_xml = _load("tests/fixtures/synthetic/opnsense/kitchen_sink.xml")
    intent_src = opnsense_parse(src_xml)
    assert len(intent_src.radius_servers) == 2
    assert intent_src.radius_servers[0].auth_port == 1812
    assert intent_src.radius_servers[0].acct_port == 1813
    assert intent_src.radius_servers[1].auth_port == 11812
    assert intent_src.radius_servers[1].acct_port == 11813

    rendered = aruba_render(intent_src)
    intent_rt = aruba_parse(rendered)

    assert len(intent_rt.radius_servers) == 2, (
        f"expected 2 RADIUS servers after round-trip, got "
        f"{len(intent_rt.radius_servers)}: {intent_rt.radius_servers!r}"
    )
    by_host = {s.host: s for s in intent_rt.radius_servers}
    s1 = by_host["10.0.0.50"]
    assert s1.auth_port == 1812
    assert s1.acct_port == 1813
    assert s1.key == "fakeRadiusSharedSecret01"
    s2 = by_host["10.0.0.51"]
    assert s2.auth_port == 11812, (
        f"second RADIUS server must keep custom auth-port 11812; got "
        f"{s2.auth_port}"
    )
    assert s2.acct_port == 11813, (
        f"second RADIUS server must keep custom acct-port 11813; got "
        f"{s2.acct_port}"
    )
    assert s2.key == "fakeRadiusSharedSecret02"


# ---------------------------------------------------------------------------
# Pinned unit tests for the underlying render / parse paths
# ---------------------------------------------------------------------------


def test_aruba_render_emits_auth_acct_port_when_non_default() -> None:
    """Render a CanonicalIntent carrying a single RADIUS server with
    custom ports.  The output must contain a line wiring auth-port and
    acct-port for that host."""
    intent = CanonicalIntent(
        hostname="sw1",
        radius_servers=[
            CanonicalRADIUSServer(
                host="10.0.0.51",
                key="fakeRadiusSharedSecret02",
                auth_port=11812,
                acct_port=11813,
            ),
        ],
    )
    rendered = aruba_render(intent)
    # Inline key line present.
    assert 'radius-server host 10.0.0.51 key "fakeRadiusSharedSecret02"' in rendered
    # Separate port line present.
    assert "radius-server host 10.0.0.51 auth-port 11812 acct-port 11813" in rendered


def test_aruba_render_omits_port_line_when_defaults() -> None:
    """When auth_port / acct_port match AOS-S defaults (1812 / 1813)
    the render must NOT emit a separate port line — keep the wire
    minimal so existing real-capture round-trips don't pick up
    spurious ``auth-port 1812`` lines."""
    intent = CanonicalIntent(
        hostname="sw1",
        radius_servers=[
            CanonicalRADIUSServer(
                host="10.0.0.50",
                key="fakeRadiusSharedSecret01",
            ),
        ],
    )
    rendered = aruba_render(intent)
    assert 'radius-server host 10.0.0.50 key "fakeRadiusSharedSecret01"' in rendered
    assert "auth-port" not in rendered
    assert "acct-port" not in rendered


def test_aruba_parse_radius_port_separate_line_form() -> None:
    """Symmetric parse: ingest the form aruba_aoss.render emits."""
    cfg = (
        'hostname "sw1"\n'
        'radius-server host 10.0.0.51 key "fakeRadiusSharedSecret02"\n'
        "radius-server host 10.0.0.51 auth-port 11812 acct-port 11813\n"
    )
    intent = aruba_parse(cfg)
    assert len(intent.radius_servers) == 1
    s = intent.radius_servers[0]
    assert s.host == "10.0.0.51"
    assert s.key == "fakeRadiusSharedSecret02"
    assert s.auth_port == 11812
    assert s.acct_port == 11813


def test_aruba_parse_radius_port_inline_form() -> None:
    """Aruba AOS-S also accepts the ports inline with key on a single
    line — the parser should ingest that form too for resilience to
    operator hand-crafted configs."""
    cfg = (
        'hostname "sw1"\n'
        'radius-server host 10.0.0.51 auth-port 11812 acct-port 11813 '
        'key "fakeRadiusSharedSecret02"\n'
    )
    intent = aruba_parse(cfg)
    assert len(intent.radius_servers) == 1
    s = intent.radius_servers[0]
    assert s.host == "10.0.0.51"
    assert s.key == "fakeRadiusSharedSecret02"
    assert s.auth_port == 11812
    assert s.acct_port == 11813
