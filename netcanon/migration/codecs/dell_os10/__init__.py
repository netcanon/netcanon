"""
Dell SmartFabric OS10 codec — ``show running-configuration`` translator
for the Dell EMC PowerSwitch S-series and Z-series.

Distinct vendor identity (``vendor_id=dell_os10``) from Dell's older
Force10 NOS (OS9 / FTOS): a different CLI grammar, different port naming
(``ethernet1/1/1`` vs ``TenGigabitEthernet 0/1``), and a VLAN model that
is port-centric rather than VLAN-centric.  OS9 is parked — see
``docs/vendor-research/dell_os10/40-os9-appendix.md``.

Module layout (mirrors ``cisco_nxos`` post-split):
    * codec.py      — ``DellOS10Codec`` class (metadata, delegation,
                      probe, port-name bridges).
    * parse.py      — line-scan over OS10 text.  Entry: :func:`parse_intent`.
    * render.py     — canonical tree → OS10 text.  Entry: :func:`render_intent`.
    * port_names.py — cross-vendor port-name bridge.

⚠️ This codec is **not registered** yet — ``codec.py`` carries no
``@register`` decorator, and ``dell_os10`` is absent from the explicit
import lists in ``tools/run_full_mesh.py`` and the two mesh tests.
Registering a 13th codec grows the cross-vendor mesh from 132 to 156
ordered pairs and breaks ``test_cross_mesh_ci_guard``'s exact
``cells_total`` assertion, so it is inseparable from the Phase-4 baseline
re-cut.  ``tests/unit/migration/test_dell_os10.py`` imports the class
directly.

Direction: ``bidirectional`` (Phase 2 — parse + render).
Certainty: ``best_effort`` — the parse path is validated against 14 real
    OS10 captures held out-of-tree at ``local/dell-os10/configs/``, but
    the render path is exercised against SYNTHETIC samples only and there
    is no committed round-trip fixture and no mesh coverage.
    ``certified`` requires committed real captures, as for every other
    codec.
"""

from __future__ import annotations

from .codec import DellOS10Codec

__all__ = ["DellOS10Codec"]
