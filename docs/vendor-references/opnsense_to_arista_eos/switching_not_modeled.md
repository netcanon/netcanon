# Switching state structurally absent on OPNsense source

OPNsense is a FreeBSD-based router/firewall with no switching
fabric.  Arista EOS is a DC-class L2/L3 switch.  On the
`opnsense -> arista_eos` direction the asymmetry inverts versus
the forward direction: switching state is **not_applicable**
(empty on parse), not unsupported (would be lost on render).

## What OPNsense lacks

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-04-30

OPNsense `config.xml` carries only L3 attributes per interface:

- IP addressing (v4 / v6 / DHCP / SLAAC / track6 / 6rd / 6to4).
- MTU.
- Enable / disable.
- Description.
- Block-private / bogon / RFC1918 (firewall-policy attributes).

There is NO:

- `switchport mode access` / `switchport mode trunk`
- `switchport access vlan` / `switchport trunk allowed vlan` /
  `switchport trunk native vlan`
- `switchport voice vlan`
- spanning-tree state (admin-edge, BPDU guard, MSTP instance
  membership)
- LLDP-MED voice-VLAN signalling

## What Arista accepts

Source: [Arista EOS VLAN Configuration](https://www.arista.com/en/um-eos/eos-vlan-configuration)
Retrieved: 2026-05-01

Arista EOS accepts `switchport mode {access|trunk}` plus per-port
VLAN-membership directives on physical interfaces and LAG-level
interfaces.  Spanning-tree (`mstp` / `rstp` / `pvst`) is global +
per-port; LLDP-MED voice-VLAN is per-port.

## Cross-vendor disposition

Canonical fields affected:

- `interfaces[].switchport_mode`
- `interfaces[].access_vlan`
- `interfaces[].trunk_allowed_vlans`
- `interfaces[].trunk_native_vlan`
- `interfaces[].voice_vlan`
- `vlans[].tagged_ports`
- `vlans[].untagged_ports`

All marked **not_applicable** on this direction — OPNsense parse
never populates the fields, so the Arista target render emits no
`switchport` / `tagged` / `untagged` lines because the canonical
lists are empty.  Operators reconstruct the trunk topology
manually after migration.
