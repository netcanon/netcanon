"""
Guards for the product scope line: which platforms Netcanon is *for*.

The scope rule itself lives in ``AGENTS.md`` § Hard Rules ("Never author or
change a codec's ``device_classes[0]`` without applying the scope test").  This
module is its teeth.  Background and the measurements behind the rule are in
``docs/reviews/2026-08-10-firewall-scope-exit/``.

The short version: a codec's FIRST declared device class is its **primary
device class**, and that single field is the project's authoritative scope
declaration for the platform.  A ``firewall``-primary codec ships, is
certified, holds fixtures, is auto-detected and is fully audited — but
Netcanon translates its L2/L3 layer only, and it does not get to be the face
of the product.

Covers:
    * The firewall-primary roster is pinned (changing it is a product call).
    * Every codec declares at least one device class.
    * ``vendors/<vendor>.yaml`` and the codec's ``CapabilityMatrix`` agree.
    * The landing page's capability-matrix evidence is not drawn from a
      firewall-primary codec.
    * Firewall-primary demo scenarios do not grow (downward-only ratchet).

See also: ``tests/unit/migration/test_device_class.py`` (the runtime
compatibility guard), ``tests/unit/migration/test_vendors.py`` (vendor YAML
schema), ``docs/CAPABILITIES.md`` § Platform fit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from netcanon.migration.codecs.registry import get_codec, list_codecs
from netcanon.migration.vendors import load_vendors
from netcanon.models.migration import DeviceClass
from netcanon.tools.demo import SCENARIOS

REPO_ROOT = Path(__file__).resolve().parents[3]

# The scope line.  Membership here is a PRODUCT decision, not a refactor --
# see the two-clause test in AGENTS.md § Hard Rules before changing it.
_FIREWALL_PRIMARY = {"fortigate_cli", "opnsense"}

# Firewall-primary scenarios in `netcanon/tools/demo.py`.  The rule's target is
# AT MOST ONE of the four; HEAD carries two (`fortigate__mikrotik`,
# `opnsense__junos`).  Closing that gap means re-authoring a demo scenario,
# which drags the landing-page hero pane + og.png + the paired walkthrough with
# it (AGENTS.md doc-sync, "a demo-scenario change alters the rendered OUTPUT"),
# so it is deliberately a separate wave.  This is a RATCHET: it may only ever
# be lowered.  Raising it re-opens the dilution this rule exists to close.
_MAX_FIREWALL_PRIMARY_SCENARIOS = 2
_TARGET_FIREWALL_PRIMARY_SCENARIOS = 1


def _primary_class(codec_name: str) -> DeviceClass | None:
    classes = get_codec(codec_name).capabilities.device_classes
    return classes[0] if classes else None


def _is_firewall_primary(codec_name: str) -> bool:
    return _primary_class(codec_name) is DeviceClass.firewall


class TestScopeLine:
    """``device_classes[0]`` is the scope declaration."""

    def test_firewall_primary_roster_is_pinned(self):
        """Changing this set is a product decision, not a refactor.

        If you are here because you added a codec: apply the two-clause scope
        test in AGENTS.md § Hard Rules and record the reasoning in the PR body.
        If you are here because you *re-ordered* an existing codec's
        ``device_classes``, stop -- that silently moves the platform between
        scope tiers and changes what the landing page promises.
        """
        live = {name for name in list_codecs() if _is_firewall_primary(name)}
        assert live == _FIREWALL_PRIMARY, (
            f"firewall-primary roster changed: {live} != {_FIREWALL_PRIMARY}. "
            "device_classes[0] is the project's scope declaration -- see "
            "AGENTS.md Hard Rules."
        )

    @pytest.mark.parametrize("codec_name", sorted(list_codecs()))
    def test_every_codec_declares_a_primary_device_class(self, codec_name):
        """An empty ``device_classes`` would make the scope test undecidable."""
        assert _primary_class(codec_name) is not None, (
            f"{codec_name} declares no device_classes, so it has no primary "
            "device class and its scope tier cannot be resolved."
        )


class TestVendorYamlAgreement:
    """The two places device classes are written must not drift apart."""

    def test_vendor_yaml_agrees_with_codec_device_classes(self):
        """``vendors/<id>.yaml`` and the codec's ``CapabilityMatrix`` must match.

        Order matters as well as membership: the FIRST entry is the scope
        declaration, so a re-order is a scope change even when the set is
        identical.

        This guard was written after finding `juniper_junos` drifted -- the
        YAML named the SRX series and declared `firewall`, the codec did not.
        The codec was the wrong side (it parses a vSRX fixture), so the codec
        gained the class rather than the YAML losing it.
        """
        vendors = load_vendors()
        drift = []
        for name in sorted(list_codecs()):
            caps = get_codec(name).capabilities
            vendor = vendors.get(caps.vendor_id)
            if vendor is None:  # pragma: no cover - schema guard covers this
                continue
            codec_classes = list(caps.device_classes or [])
            yaml_classes = list(vendor.device_classes or [])
            if codec_classes != yaml_classes:
                drift.append(
                    f"{name}: codec={[c.value for c in codec_classes]} "
                    f"vendors/{caps.vendor_id}.yaml={[c.value for c in yaml_classes]}"
                )
        assert not drift, "device_classes drift between codec and vendor YAML:\n  " + "\n  ".join(drift)


class TestFirewallPrimaryIsNotTheFaceOfTheProduct:
    """The operational half of the rule -- what firewall-primary codecs may not be."""

    def test_landing_page_matrix_excerpt_is_not_firewall_primary(self):
        """site/index.html proves "every field has a declared fate" with one
        codec panel.  Drawing that proof from a platform we translate only at
        L2/L3 is the dilution the scope rule exists to prevent.
        """
        page = (REPO_ROOT / "site" / "index.html").read_text(encoding="utf-8")
        section = page.split('id="matrix"', 1)[1].split("</section>", 1)[0]
        named = re.findall(r"<code>([a-z0-9_]+)</code> panel", section)
        assert named, "could not find the codec panel named in the #matrix section"
        offenders = [c for c in named if c in _FIREWALL_PRIMARY]
        assert not offenders, (
            f"the landing page's capability-matrix excerpt is drawn from "
            f"firewall-primary codec(s) {offenders}; use a switch/router codec."
        )

    def test_firewall_primary_demo_scenarios_do_not_grow(self):
        """Downward-only ratchet -- see ``_MAX_FIREWALL_PRIMARY_SCENARIOS``."""
        firewall_scenarios = sorted(
            key
            for key, scenario in SCENARIOS.items()
            if _is_firewall_primary(scenario.source_codec) or _is_firewall_primary(scenario.target_codec)
        )
        assert len(firewall_scenarios) <= _MAX_FIREWALL_PRIMARY_SCENARIOS, (
            f"{len(firewall_scenarios)} of {len(SCENARIOS)} demo scenarios are "
            f"firewall-primary ({firewall_scenarios}); the ratchet allows at most "
            f"{_MAX_FIREWALL_PRIMARY_SCENARIOS} and the target is "
            f"{_TARGET_FIREWALL_PRIMARY_SCENARIOS}.  This ratchet only lowers."
        )
