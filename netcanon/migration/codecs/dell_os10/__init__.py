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

Registered (Phase 4) as the 13th codec.  Registration grew the
cross-vendor mesh from 132 to 156 ordered pairs, which is why it landed
together with the 24 new pair-expectation YAMLs, their
``docs/vendor-references/`` companions and a re-cut
``tests/fixtures/real/_phase4_runs/latest.json`` baseline — the coverage
ratchet in ``test_cross_mesh_ci_guard`` holds
``cells_without_expectation_yaml`` at 0, so the wiring could not be split
from the authoring.

Direction: ``bidirectional`` (Phase 2 — parse + render).
Certainty: ``best_effort`` — the parse path is validated against 14 real
    OS10 captures held out-of-tree at ``local/dell-os10/configs/``, and
    Phase 4 added a committed synthetic kitchen-sink fixture plus full
    cross-vendor mesh coverage.  It stays ``best_effort`` rather than
    ``certified`` because no REAL capture is committed: every other
    codec's ``certified`` rests on an in-tree real corpus, and these
    captures carry live password hashes.
"""

from __future__ import annotations

from .codec import DellOS10Codec

__all__ = ["DellOS10Codec"]
