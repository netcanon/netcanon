"""Registry-wide invariant for the same-vendor version-echo (review #63).

The shared ``same_vendor_version`` helper (``codecs/_helpers.py``) decides
whether a render echoes the device's own OS release.  It must compare against
each codec's ``capabilities.vendor_id`` — NOT its registry key — because some
codecs stamp a different vendor_id than their registry name (``cisco_iosxe_cli``
→ ``cisco_iosxe``, ``fortigate_cli`` → ``fortigate``).  A codec wiring the wrong
literal would silently stop echoing; the parametrised test below pins the
behaviour end-to-end so a future copy can't drift.
"""

from __future__ import annotations

import pytest

from netcanon.migration.canonical.intent import CanonicalIntent
from netcanon.migration.codecs._helpers import same_vendor_version
from netcanon.migration.codecs.aruba_aoscx import ArubaAOSCXCodec
from netcanon.migration.codecs.cisco_iosxr import CiscoIOSXRCodec
from netcanon.migration.codecs.cisco_nxos import CiscoNXOSCodec
from netcanon.migration.codecs.mikrotik_routeros import MikroTikRouterOSCodec
from netcanon.migration.codecs.vyos import VyOSCodec

pytestmark = pytest.mark.unit

#: Codecs whose render echoes the device's own OS release on a same-vendor pass
#: (#297 banner echo + #61 MikroTik export header).
_ECHOING_CODECS = [
    ArubaAOSCXCodec,
    CiscoIOSXRCodec,
    CiscoNXOSCodec,
    MikroTikRouterOSCodec,
    VyOSCodec,
]


class TestSameVendorVersionHelper:
    def test_same_vendor_with_version_returns_it(self):
        t = CanonicalIntent(source_vendor="cisco_nxos", source_version="9.9.9")
        assert same_vendor_version(t, vendor_id="cisco_nxos", default="D") == "9.9.9"

    def test_cross_vendor_returns_default(self):
        t = CanonicalIntent(source_vendor="cisco_nxos", source_version="9.9.9")
        assert same_vendor_version(t, vendor_id="vyos", default="D") == "D"

    def test_same_vendor_without_version_returns_default(self):
        t = CanonicalIntent(source_vendor="cisco_nxos", source_version="")
        assert same_vendor_version(t, vendor_id="cisco_nxos", default="D") == "D"


@pytest.mark.parametrize(
    "codec_cls", _ECHOING_CODECS, ids=lambda c: c().capabilities.vendor_id
)
def test_same_vendor_render_echoes_source_version(codec_cls):
    """A same-vendor tree's ``source_version`` must appear in the render — proof
    the codec compares against ``capabilities.vendor_id``, not a stale literal
    that could silently diverge (review #63)."""
    codec = codec_cls()
    vid = codec.capabilities.vendor_id
    tree = CanonicalIntent(
        hostname="echo-probe",
        source_vendor=vid,
        source_version="9.9.9-echo",
    )
    out = codec.render(tree)
    assert "9.9.9-echo" in out, (
        f"{vid}: same-vendor render did not echo source_version — its render "
        "vendor_id literal likely diverged from capabilities.vendor_id"
    )
