# Switching state not modelled on OPNsense source (OPNsense -> RouterOS)

OPNsense is a FreeBSD-based router/firewall.  It does NOT model
switching state in ``config.xml``:

- No per-port ``switchport mode`` toggle (access / trunk).
- No per-port allowed-VLAN list.
- No voice-VLAN concept.
- No spanning-tree / BPDU-guard / loop-protect.
- VLANs are tagged sub-interfaces on a single parent NIC, not a
  port-membership concept.

The OPNsense codec NEVER populates the canonical fields:

- ``CanonicalInterface.switchport_mode``
- ``CanonicalInterface.access_vlan``
- ``CanonicalInterface.trunk_allowed_vlans``
- ``CanonicalInterface.trunk_native_vlan``
- ``CanonicalInterface.voice_vlan``
- ``CanonicalVlan.tagged_ports``
- ``CanonicalVlan.untagged_ports``

These fields all stay at their default empty / null values after an
OPNsense parse.

## Cross-pair implication: not_applicable

On the OPNsense -> RouterOS direction, these switching-state fields
are **not_applicable** rather than **lossy** or **unsupported**:

- The source side never carries the data.
- The RouterOS target side CAN render Plane-2 (bridge VLAN
  filtering) port-membership rows when the canonical lists are
  populated — just not from this source.

The cross-pair render emits no bridge VLAN filtering config from
this source.  RouterOS Plane-1 (router-on-a-stick ``/interface
vlan``) is still emitted from the canonical VLAN id + name fields,
which OPNsense source DOES populate.

## Inverse direction is different

On the inverse RouterOS -> OPNsense direction, the same fields are
**unsupported** (not not_applicable): RouterOS source CAN populate
them (from Plane-2 parse), but OPNsense target has nowhere to write
them.  The asymmetry is by design.
