# Switching state (switchport / spanning-tree / VTP / SVI): OPNsense versus Cisco IOS-XE

## OPNsense

OPNsense is a FreeBSD-based router/firewall.  It does NOT model:

- ``switchport`` (access / trunk modes) — interfaces are L3 or
  bridge-members
- per-port allowed-VLAN lists — every ``<vlans>/<vlan>`` rides its
  parent NIC
- voice VLAN (LLDP-MED auto-config)
- spanning-tree (only available on the bridge ``<bridges>`` block,
  not on a switching fabric — and not in the canonical schema)
- VTP / DTP / GVRP

The OPNsense parser therefore NEVER POPULATES the canonical
``CanonicalInterface.switchport_mode`` /
``CanonicalInterface.access_vlan`` /
``CanonicalInterface.trunk_allowed_vlans`` /
``CanonicalInterface.trunk_native_vlan`` /
``CanonicalInterface.voice_vlan`` /
``CanonicalVlan.tagged_ports`` /
``CanonicalVlan.untagged_ports`` fields.

## Cisco IOS-XE

Cisco IOS-XE on a Catalyst-class platform models all of the above
extensively (see the reverse-direction
``cisco_iosxe_cli_to_opnsense/switchport_unsupported.md`` for full
syntax).

## Cross-vendor mapping

Canonical fields impacted:

- ``CanonicalInterface.switchport_mode``: **not_applicable** from
  OPNsense source — the parser never populates it.  Cisco render
  emits routed-port stanzas (no ``switchport`` lines).
- ``CanonicalInterface.access_vlan``: **not_applicable**.
- ``CanonicalInterface.trunk_allowed_vlans``: **not_applicable**.
- ``CanonicalInterface.trunk_native_vlan``: **not_applicable**.
- ``CanonicalInterface.voice_vlan``: **not_applicable**.
- ``CanonicalVlan.tagged_ports``: **not_applicable**.
- ``CanonicalVlan.untagged_ports``: **not_applicable**.

This is a SOURCE-SIDE NOT_APPLICABLE — the field exists on the
canonical schema, the Cisco target codec CAN render it, but the
OPNsense source never has the data so the cross-pair never has
anything to lose.  Disposition is "the field doesn't apply on
this source vendor", consistent with how other vendors' YAMLs
mark Junos ``apply_groups`` / ``group_content`` not_applicable for
non-Junos sources.

If an operator's OPNsense device is ALSO acting as a small-network
switch via FreeBSD bridges (``<bridges>``), the bridge state is in
``raw_sections`` at best — the canonical surface will not carry it.

Disposition: **not_applicable** for the entire switching-state
surface from an OPNsense source.
