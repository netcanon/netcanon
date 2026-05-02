# VLAN configuration: FortiGate FortiOS versus Juniper Junos

## FortiGate FortiOS

Source: [Fortinet — FortiOS Cookbook — VLAN child interfaces and VLAN tagging](https://docs.fortinet.com/document/fortigate/7.4.0/cookbook/).
Source: FortiOS CLI Reference — `config system interface` (`type vlan`).
Retrieved: 2026-05-01.

FortiGate has **no first-class VLAN object**.  VLAN membership is
encoded by creating a child interface of type `vlan` whose parent is
the trunked physical / aggregate port:

```
config system interface
    edit "agg1.100"
        set type vlan
        set vlanid 100
        set interface "agg1"
        set ip 10.100.0.1 255.255.255.0
    next
    edit "VL_200"
        set type vlan
        set vlanid 200
        set interface "agg1"
        set ip 10.200.0.1 255.255.255.0
    next
end
```

Notable consequences:

- The **child-interface name** doubles as the VLAN's identifier in
  FortiOS — the operator picks `<parent>.<vlanid>` (dotted form) or
  any operator-friendly name (`VL_<id>`, `DATA_<role>`).
- There is **no per-VLAN `description` field** distinct from the
  child-interface's `set alias`.
- There is **no port-list-per-VLAN structure** — VLAN membership is
  encoded entirely on the parent (the child interface declares
  `set interface "<parent>"`).  Multi-port VLANs require multiple
  child interfaces (one per parent), not a single VLAN object with
  a tagged-ports list.
- L3 SVI: the VLAN child interface itself carries the IP address.
- `set type vlan` may be omitted in some parser shapes when the
  dotted-name + `set vlanid` is unambiguous.

## Juniper Junos

Source: [Junos `vlans` statement reference (QFX bridging)](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/ref/statement/vlans-bridging-qfx-series.html).
Source: [Junos Bridging and VLANs Overview](https://www.juniper.net/documentation/us/en/software/junos/multicast-l2/topics/topic-map/bridging-and-vlans-overview.html).
Retrieved: 2026-05-01.

Junos models VLANs as **first-class objects** under `set vlans
<name> ...`, with port membership declared on each interface's
`family ethernet-switching vlan members <name>`:

```
set vlans USERS vlan-id 10
set vlans USERS description "User access VLAN"
set vlans VOICE vlan-id 20
set vlans TENANT_A_DATA vlan-id 100
set vlans TENANT_A_DATA l3-interface irb.100
#
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members USERS
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members VOICE
set interfaces ge-0/0/1 unit 0 family ethernet-switching native-vlan-id 1
#
set interfaces irb unit 100 family inet address 172.16.100.1/24
```

Notable Junos specifics:

- **VLAN names** allow letters, digits, hyphens, periods only (up to
  255 chars).  No underscores.
- **L3 SVI** uses the `irb` (Integrated Routing and Bridging)
  interface with per-unit binding; the VLAN object references the
  IRB unit via `l3-interface irb.<N>`.
- **Port membership** lives on the interface's
  `family ethernet-switching` block — VLAN-centric port lists must
  be transposed.
- **VXLAN VNI** can be attached to the VLAN: `set vlans <name>
  vxlan vni <N>`.

## Cross-vendor mapping (FortiGate -> Junos)

Canonical surface (from `CanonicalVlan`):

```
class CanonicalVlan(BaseModel):
    id: int = Field(ge=1, le=4094)
    name: str = ""
    description: str = ""
    tagged_ports: list[str]
    untagged_ports: list[str]
    ipv4_addresses: list[CanonicalIPv4Address]
```

- **id** — `good`.  FortiOS `set vlanid N` parses to
  `CanonicalVlan.id`; Junos render emits `set vlans <name> vlan-id N`.
- **name** — `lossy`.  FortiOS edit-ID becomes the canonical name.
  Junos VLAN names cannot contain underscores or slashes — names with
  underscores (`VL_200`) need sanitisation on Junos render
  (typically `_` -> `-`).
- **description** — `lossy`.  FortiGate has no per-VLAN description
  (only child-interface alias); canonical empty after FortiGate
  parse.  Junos render therefore emits no `description`.
- **tagged_ports / untagged_ports** — `lossy` (model gap).  FortiGate
  has no port-list-per-VLAN structure; canonical lists are empty
  after FortiGate parse.  Operators must reconstruct
  `family ethernet-switching vlan members` per-interface manually
  on Junos.
- **ipv4_addresses** — `good`.  VLAN child interface's `set ip`
  becomes canonical `ipv4_addresses`; Junos emits `irb unit N` SVI.

## Cross-vendor mapping (Junos -> FortiGate)

Reverse direction (see also `../juniper_junos_to_fortigate_cli/vlans.md`):

- **name** — `lossy`.  Junos hyphen/period-only names preserve, but
  FortiOS edit-ID conventions favour underscores.
- **tagged_ports / untagged_ports** — `lossy` (model gap).  Junos
  populates the canonical port-list per VLAN; FortiGate render
  cannot consume directly without synthesising multiple VLAN-child
  interfaces (one per VLAN per parent), which v1 codec does not do.
  Operators reconstruct manually post-migration.
- **ipv4_addresses** — `good` (Junos IRB unit -> FortiGate VLAN-
  child SVI form).
