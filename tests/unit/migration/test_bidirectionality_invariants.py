"""
Bidirectionality invariants — meta-tests covering structural gaps
that produced the user-reported "Aruba paste rendered to NETCONF
XML instead of Cisco CLI" bug.

The bug surfaced because three independent assumptions broke down
together:

  1. Two codecs shared ``vendor_display_name="Cisco IOS-XE"``
     (one NETCONF, one CLI parser).
  2. The CLI codec was ``parse_only`` — operators picking "Cisco
     IOS-XE" as a target got the NETCONF stub by default.
  3. The cross-mesh smoke tests didn't exercise the (Aruba,
     cisco_iosxe) pair at all because ``_TARGET_CAPABLE`` was
     hand-curated and missing 4 of the 8 bidirectional codecs.

Cross-mesh smoke tests check "doesn't crash + rename map applied".
They don't check "operator picking vendor X gets format Y" — that's
the gap this file fills.

Each test below catches the specific structural assumption that
broke.  Failure here means a NEW codec landed without a matching
operator-facing render, OR an existing codec was demoted /
removed without updating the corresponding fixture / dropdown.

See also:
    * ``tests/unit/migration/test_cross_mesh_overrides.py`` — per-
      category smoke tests; complementary, broader, less strict.
    * ``netconfig/templates/migrate.html`` — target dropdown that
      surfaces ``input_format`` so the operator can disambiguate
      same-vendor codec siblings.
"""
from __future__ import annotations

import pytest

# Side-effect imports to register every codec.
from netconfig.migration.codecs import (  # noqa: F401
    arista_eos,
    aruba_aoss,
    cisco_iosxe,
    cisco_iosxe_cli,
    fortigate_cli,
    juniper_junos,
    mikrotik_routeros,
    opnsense,
)
from netconfig.migration.codecs.registry import get_codec, list_codecs

pytestmark = pytest.mark.unit


def _all_codecs() -> list:
    """Materialised list of every registered codec class.  Built
    fresh per call so mid-test registry changes are reflected."""
    return [type(get_codec(name)) for name in list_codecs()]


class TestEveryVendorHasCliRenderPath:
    """For every vendor whose primary operator interface is a CLI
    (Cisco / Arista / Aruba / FortiGate / Junos / MikroTik), there
    MUST exist a registered codec that renders that vendor's CLI
    format.  An XML-only render path (Cisco's NETCONF codec) does
    NOT satisfy this — operators pasting into a console expect CLI
    text, and a parse_only CLI codec means cross-vendor migrations
    INTO that vendor produce something un-paste-able.

    This is the meta-invariant that would have caught the
    user-reported aruba_aoss → cisco_iosxe bug on the SAME commit
    that left cisco_iosxe_cli as parse_only.  Failure mode:
      * Add a new vendor's CLI parser as parse_only without a
        sibling CLI renderer → fails (this test).
      * Demote an existing CLI renderer to parse_only → fails.
      * Add a new vendor whose only render is XML / JSON / etc. →
        fails (push them to add a CLI render or add the vendor to
        the explicit exemption list below).

    Exemption: OPNsense is config.xml-native — operators upload XML,
    not CLI — so the OPNsense XML codec IS its operator-facing
    render.  Same logic applies if a future vendor lands a JSON-
    native or NETCONF-native operator interface.
    """

    @pytest.mark.parametrize("vendor_id,expected_format_prefix", [
        ("arista_eos",        "cli-"),
        ("aruba_aoss",        "cli-"),
        ("cisco_iosxe",       "cli-"),
        ("fortigate",         "cli-"),
        ("juniper_junos",     "cli-"),
        ("mikrotik_routeros", "cli-"),
        # opnsense intentionally omitted — its operator-facing
        # format IS xml.  Same exception class would apply to a
        # future PAN-OS XML or RouterOS REST codec.
    ])
    def test_vendor_has_renderable_cli_codec(
        self, vendor_id: str, expected_format_prefix: str,
    ):
        """At least one registered codec for ``vendor_id`` must be
        renderable AND emit the operator-facing format."""
        matching = [
            c for c in _all_codecs()
            if c.capabilities.fget(c).vendor_id == vendor_id
            and getattr(c, "direction", "bidirectional") != "parse_only"
            and getattr(c, "input_format", "").startswith(
                expected_format_prefix,
            )
        ]
        assert matching, (
            f"Vendor {vendor_id!r} has no codec with direction != "
            f"parse_only AND input_format starting with "
            f"{expected_format_prefix!r}.  Operators selecting this "
            f"vendor as a TARGET in the migrate dropdown will get "
            f"either an unrelated wire format (NETCONF XML, REST "
            f"JSON) or a render error.  Either: ship a CLI render "
            f"path on the existing parse_only codec (that's what "
            f"promoting cisco_iosxe_cli to bidirectional did), or "
            f"add the vendor to the exemption list in this test "
            f"if its operator-facing format is genuinely non-CLI."
        )


class TestNoOrphanedParseOnlyCliCodec:
    """A ``parse_only`` codec with a ``cli-*`` input_format is an
    operator-confusion risk: it parses CLI text but can't render
    it back, so cross-vendor migrations TO that vendor's CLI fall
    through to whatever other codec shares the vendor_id (often
    a NETCONF / REST renderer with a wildly different output
    shape).  This test enforces the "if you parse CLI, you also
    render CLI" invariant.

    Acceptable: parse_only XML / NETCONF / proprietary fact-only
    codecs.  Those don't pretend to be the operator-paste path.
    """

    def test_no_parse_only_cli_codecs(self):
        offenders = []
        for cls in _all_codecs():
            direction = getattr(cls, "direction", "bidirectional")
            input_format = getattr(cls, "input_format", "")
            if direction == "parse_only" and input_format.startswith("cli-"):
                offenders.append(
                    f"{cls.__name__} (vendor_id="
                    f"{cls.capabilities.fget(cls).vendor_id!r}, "
                    f"input_format={input_format!r})"
                )
        assert not offenders, (
            f"Found parse_only codec(s) with cli-* input_format: "
            f"{offenders}.  Ship a render path or change the "
            f"input_format if the codec genuinely doesn't represent "
            f"a CLI grammar."
        )


class TestVendorDisplayNameCollisionsAreDisambiguated:
    """When two codecs share a vendor_display_name (e.g. cisco_iosxe
    NETCONF + cisco_iosxe_cli CLI both display as 'Cisco IOS-XE'),
    the operator-facing target dropdown MUST be able to tell them
    apart.  Disambiguation = ``input_format`` differs between the
    siblings, so the dropdown's
    ``"<vendor_display> — <input_format> (<device_classes>)"``
    label uniquely identifies each codec.

    Failure mode this catches: two same-vendor sibling codecs
    accidentally declaring identical input_format (which would
    produce duplicate dropdown entries indistinguishable to the
    operator).
    """

    def test_same_vendor_codecs_have_distinct_input_formats(self):
        from collections import defaultdict
        by_vendor: dict[str, list] = defaultdict(list)
        for cls in _all_codecs():
            caps = cls.capabilities.fget(cls)
            by_vendor[caps.vendor_id].append(cls)

        ambiguous = []
        for vendor_id, codecs in by_vendor.items():
            if len(codecs) <= 1:
                continue
            formats = [getattr(c, "input_format", "") for c in codecs]
            if len(set(formats)) != len(formats):
                ambiguous.append((vendor_id, formats))
        assert not ambiguous, (
            f"Vendors with multiple codecs sharing identical "
            f"input_format: {ambiguous}.  The migrate dropdown "
            f"shows ``<vendor> — <input_format>`` and would render "
            f"duplicate entries the operator can't distinguish.  "
            f"Either give one of the siblings a distinct format "
            f"slug or merge them into a single codec."
        )


class TestEveryBidirectionalTargetHasFixtureCoverage:
    """Lighter-touch coverage guard: every codec that COULD be
    selected as a migrate-modal target (direction != parse_only)
    appears in at least ONE cross-mesh smoke test fixture.  This
    is the meta-test that would have flagged the missing
    cisco_iosxe entry in ``_TARGET_CAPABLE`` BEFORE the user-
    reported bug shipped.

    Failure mode this catches: hand-curated fixture lists that
    silently shrink coverage as the codec count grows.  Extending
    the list to include a new codec makes this test pass; refusing
    to add the codec means owning a documented exemption (rare).
    """

    def test_every_bidir_codec_has_smoke_coverage(self):
        # Lazy import — keeps test discovery cheap and avoids a
        # cyclic import if the cross-mesh module ever imports this
        # one transitively.
        from tests.unit.migration import test_cross_mesh_overrides as cm

        bidir_codec_names = {
            cls.capabilities.fget(cls).adapter
            for cls in _all_codecs()
            if getattr(cls, "direction", "bidirectional") != "parse_only"
        }
        # The ``mock`` codec is an experimental reference adapter,
        # not a real vendor — exempt it from the coverage check.
        bidir_codec_names.discard("mock")

        # Every bidirectional codec should appear in EITHER the
        # source-capable axis OR the target-capable axis of the
        # cross-mesh smoke tests.  Missing on BOTH = silent
        # coverage gap.
        covered = set(cm._SOURCE_CAPABLE) | set(cm._TARGET_CAPABLE)
        uncovered = bidir_codec_names - covered
        assert not uncovered, (
            f"Bidirectional codecs missing from the cross-mesh "
            f"smoke matrix: {sorted(uncovered)}.  Add them to "
            f"_SOURCE_CAPABLE / _TARGET_CAPABLE in "
            f"test_cross_mesh_overrides.py (with a representative "
            f"_SRC_CONFIGS entry for the source axis) so cross-"
            f"vendor migrations through these codecs are exercised "
            f"by the smoke tier.  This is the guard that would have "
            f"caught the cisco_iosxe coverage gap before the "
            f"aruba_aoss → cisco_iosxe NETCONF-XML bug shipped."
        )
