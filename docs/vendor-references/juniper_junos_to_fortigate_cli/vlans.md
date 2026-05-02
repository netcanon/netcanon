# VLAN configuration: Juniper Junos versus FortiGate FortiOS

## Juniper Junos

Source: [Junos `vlans` statement reference (QFX bridging)](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html).
Source: [Junos Bridging and VLANs Overview](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html).
Retrieved: 2026-05-01.

Junos models VLANs as first-class objects under `set vlans <name>`,
with port membership declared on each interface's
`family ethernet-switching vlan members <name>`:

```
set vlans USERS vlan-id 10
set vlans USERS description "User access VLAN"
set vlans VOICE vlan-id 20
set vlans TENANT_A_DATA vlan-id 100
set vlans TENANT_A_DATA l3-interface irb.100
set vlans TENANT_A_DATA vxlan vni 10100
#
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members USERS
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VOICE
set interfaces ge-0/0/1 unit 0 family ethernet-switching native-vlan-id 1
#
set interfaces irb unit 100 family inet address 172.16.100.1/24
```

Notable Junos specifics:

- **VLAN names** allow letters / digits / hyphens / periods only
  (max 255 chars).  No underscores.
- **L3 SVI** uses the `irb` interface; the VLAN object references
  the IRB unit via `l3-interface irb.<N>`.
- **VXLAN VNI** can be attached: `set vlans <name> vxlan vni <N>`.
- **Description** is first-class on the VLAN object.

## FortiGate FortiOS

Source: [Fortinet — FortiOS Cookbook — VLAN child interfaces](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Retrieved: 2026-05-01.

FortiGate has no first-class VLAN object.  VLAN membership is encoded
by creating a child interface of type `vlan`:

```
config system interface
    edit "agg1.100"
        set type vlan
        set vlanid 100
        set interface "agg1"
        set ip 10.100.0.1 255.255.255.0
    next
end
```

- **Child-interface name** doubles as the VLAN identifier.
- **No port-list-per-VLAN** structure — VLAN membership is encoded
  on the parent.  Multi-port VLANs require multiple child interfaces
  (one per parent).
- **No first-class description** distinct from the child-interface
  alias.
- **L3 SVI** lives directly on the VLAN-child interface.

## Cross-vendor mapping (Junos -> FortiGate)

Canonical surface (`CanonicalVlan`).

- **id** — `good`.  Junos `vlan-id N` -> FortiGate `set vlanid N`.
- **name** — `lossy`.  Junos hyphen / period-only names preserve as
  FortiGate edit IDs but FortiGate convention favours underscores.
  Junos `vlan vxlan vni` mappings have no FortiGate analogue.
- **description** — `lossy`.  Junos VLAN description drops on
  FortiGate render with a banner.
- **tagged_ports / untagged_ports** — `lossy` (model gap).  Junos
  populates the canonical port-list-per-VLAN (transposed by the
  Junos parser from per-interface `family ethernet-switching vlan
  members`); FortiGate render cannot consume directly without
  synthesising multiple VLAN-child interfaces (one per VLAN per
  parent), which v1 codec does not do.  Operators reconstruct
  manually post-migration.
- **ipv4_addresses** — `good`.  Junos IRB unit -> FortiGate
  VLAN-child SVI form (`edit "<name>" / set vlanid N / set ip
  A.B.C.D MASK`).

## Cross-vendor mapping (FortiGate -> Junos)

Reverse direction (see also `../fortigate_cli_to_juniper_junos/vlans.md`):

- **tagged_ports / untagged_ports** — `lossy` for the opposite reason
  (FortiGate parse populates an empty list because there is no
  per-VLAN port-list structure on FortiOS; operators reconstruct
  Junos `family ethernet-switching vlan members` manually).
