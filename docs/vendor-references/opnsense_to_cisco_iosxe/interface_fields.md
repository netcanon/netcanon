# Interface canonical-core fields — OPNsense source to Cisco NETCONF target

Source: [OPNsense Interfaces manual](https://docs.opnsense.org/manual/interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [openconfig-if-ip YANG schema docs (IPv4 / IPv6 augment)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-if-ip.html)
Retrieved: 2026-05-01

Source: `netcanon.migration.codecs.cisco_iosxe.codec._render_canonical`
(in-tree code documenting what the renderer emits)
Retrieved: 2026-05-01

## What the OPNsense source populates

The OPNsense codec parses `<interfaces>` zone elements (`<wan>`,
`<lan>`, `<optN>`) into a list of `CanonicalInterface` records.
Per the codec's `parse.py`:

| Canonical field | Populated? | Source XML element |
|---|---|---|
| `name` | yes | `<wan>` / `<lan>` / `<optN>` zone label (operator-facing) |
| `description` | yes | `<descr>` |
| `enabled` | yes | `<enable/>` empty element (present = enabled) |
| `interface_type` | NO | OPNsense doesn't surface a type field |
| `mtu` | yes | `<mtu>` integer (when set) |
| `ipv4_addresses` | yes | `<ipaddr>` + `<subnet>` (CIDR prefix) |
| `ipv6_addresses` | yes | `<ipaddrv6>` + `<subnetv6>` (CIDR prefix) |
| `switchport_mode` | NO | OPNsense has no switching fabric |
| `access_vlan` | NO | same |
| `trunk_allowed_vlans` | NO | same |
| `trunk_native_vlan` | NO | same |
| `voice_vlan` | NO | same |
| `lag_member_of` | yes | derived from `<laggs>/<lagg>/<members>` back-link |
| `dhcp_client` | NO | parser doesn't currently wire `<ipaddr>dhcp</ipaddr>` |
| `vrf` | NO | OPNsense has no VRF concept |

## What the cisco_iosxe target renderer emits

The `cisco_iosxe._render_canonical(intent)` walks
`intent.interfaces` and for each interface emits:

```xml
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>GigabitEthernet0/0/0</name>
    <config>
      <name>GigabitEthernet0/0/0</name>
      <description>Internal</description>
      <enabled>true</enabled>
      <type>iana-if-type:ethernetCsmacd</type>
    </config>
    <subinterfaces>
      <subinterface>
        <index>0</index>
        <ipv4 xmlns="http://openconfig.net/yang/interfaces/ip">
          <addresses>
            <address>
              <ip>10.0.0.1</ip>
              <config>
                <ip>10.0.0.1</ip>
                <prefix-length>24</prefix-length>
              </config>
            </address>
          </addresses>
        </ipv4>
      </subinterface>
    </subinterfaces>
  </interface>
</interfaces>
```

Render limits:

- The `<config><type>` slot accepts whatever the canonical
  `interface_type` carries — but OPNsense source never populates
  it, so the slot is empty on this pair.
- The renderer does NOT emit `<config><mtu>` even when
  `intent.interfaces[i].mtu` is set.  This is a render-side wire-up
  gap (the codec lists `/interfaces/interface/config/mtu` under
  `lossy`, not `supported`).
- The renderer does NOT emit `<config><switched-vlan>` augment for
  switchport state.  Empty by default; OPNsense source has nothing
  to feed here either.
- The renderer does NOT emit `openconfig-if-aggregate:aggregate-id`
  for LAG members.  `lag_member_of` from OPNsense source is dropped
  on render.

## Per-field disposition (opnsense -> cisco_iosxe NETCONF)

| Field | Disposition | Reason |
|---|---|---|
| `interfaces[].name` | lossy | round-trips through rename mesh; OPNsense zone label / BSD device name doesn't match Cisco speed-encoded shape |
| `interfaces[].description` | good | free-text |
| `interfaces[].enabled` | good | `<enable/>` -> YANG bool |
| `interfaces[].interface_type` | not_applicable | OPNsense source doesn't populate |
| `interfaces[].mtu` | lossy | OPNsense source populates; cisco_iosxe render doesn't emit `<config><mtu>` (matrix declares lossy) |
| `interfaces[].ipv4_addresses` | good | mechanical conversion to OpenConfig `openconfig-if-ip:ipv4` |
| `interfaces[].ipv6_addresses` | lossy | scope discriminator: source preserves; OpenConfig render doesn't emit address-type enum |
| `interfaces[].switchport_mode` | not_applicable | OPNsense source doesn't populate |
| `interfaces[].access_vlan` | not_applicable | same as switchport_mode |
| `interfaces[].trunk_allowed_vlans` | not_applicable | same |
| `interfaces[].trunk_native_vlan` | not_applicable | same |
| `interfaces[].voice_vlan` | not_applicable | same |
| `interfaces[].lag_member_of` | unsupported | OPNsense source DOES populate via `<laggs>` back-link; cisco_iosxe render doesn't emit `openconfig-if-aggregate:aggregate-id` |
| `interfaces[].dhcp_client` | not_applicable | OPNsense source doesn't populate (codec wire-up gap) |
| `interfaces[].vrf` | not_applicable | OPNsense source doesn't populate |
