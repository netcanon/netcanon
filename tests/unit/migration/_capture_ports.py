"""What hardware ports a committed real capture shows — shared by the
provenance guards.

Two test modules prove model data against real device output:
``test_target_profile_evidence.py`` (flat target profiles) and
``test_device_models_shipped.py`` (compiled device-model inventories).
Both need the same reading of a capture, and a reading that differed
between them would let one registry pass on a name the other rejects.

Not a test module (no ``test_`` prefix): pytest does not collect it.
"""

from __future__ import annotations

from pathlib import Path

from netcanon.migration.codecs.registry import get_codec
from netcanon.services.migration_detect import detect_codec

#: Canonical interface types that are not hardware ports.  A capture's
#: SVIs, LAGs, loopbacks, bridges and tunnels are real names in the
#: config, but model data that lists one as a port is wrong.
NOT_A_PORT = frozenset({
    "ianaift:l3ipvlan",
    "ianaift:l2vlan",
    "ianaift:ieee8023adLag",
    "ianaift:softwareLoopback",
    "ianaift:bridge",
    "ianaift:tunnel",
})


def vendor_of(codec_name: str) -> str:
    """The vendor id a codec is filed under."""
    # ``_CAPS`` is the class-level capability matrix; there is no public
    # accessor for a codec's vendor id (``api/routes/ui.py`` reads it the
    # same way).
    return get_codec(codec_name)._CAPS.vendor_id


def ports_in_capture(path: Path, vendor: str) -> tuple[set[str], str]:
    """Hardware port names a real capture mentions, and its lower-cased text.

    A running-config names a port in an ``interface`` stanza only when
    the port carries non-default config; an unconfigured access port
    appears solely in a VLAN's membership list (``untagged 1-47``), and
    a LAG member solely under the LAG.  All three are evidence that the
    device has a port of that name.  A LAG's OWN name, an SVI, a
    loopback or a bridge is not — and LAG names also arrive through
    VLAN membership, so they are subtracted after the union.

    Asserts that some codec recognises the capture and that it is a
    capture of *vendor*: model data must not be proven against another
    vendor's file.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    candidates = detect_codec(raw)
    assert candidates, f"{path.name}: no codec recognises this capture"
    capture_vendor = vendor_of(candidates[0].codec)
    assert capture_vendor == vendor, (
        f"{path.name} is a {capture_vendor} capture; the model data citing "
        f"it is filed under {vendor}"
    )
    intent = get_codec(candidates[0].codec).parse(raw)
    names = {iface.name for iface in intent.interfaces}
    for vlan in intent.vlans:
        names.update(vlan.tagged_ports or [])
        names.update(vlan.untagged_ports or [])
    for lag in intent.lags or []:
        names.update(lag.members or [])
    names -= {
        iface.name for iface in intent.interfaces
        if iface.interface_type in NOT_A_PORT
    }
    # A LAG's name arrives in either case (AOS-S prints ``trk1`` where
    # it is defined and ``Trk1`` in a VLAN list), as it does for
    # ``collect_hardware_port_names``.
    lag_names = {lag.name.lower() for lag in intent.lags or [] if lag.name}
    names = {name for name in names if name.lower() not in lag_names}
    return names, raw.lower()
