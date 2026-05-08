# What the cisco_iosxe NETCONF render actually emits

Source: `netcanon.migration.codecs.cisco_iosxe.codec.CiscoIOSXECodec._render_canonical`
(authoritative in-tree source for "what the render walks")
Retrieved: 2026-05-01

Source: [openconfig-interfaces YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-interfaces.html)
Retrieved: 2026-05-01

Source: [Programmability Configuration Guide, Cisco IOS XE 17.15.x — NETCONF Protocol](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/prog/configuration/1715/b_1715_programmability_cg/m_1715_prog_yang_netconf.html)
Retrieved: 2026-05-01

## The render's actual code path

The cisco_iosxe codec's `_render_canonical(intent)` method does this:

1. Create the root `<interfaces xmlns="...openconfig-interfaces">`
   element.
2. For each `intent.interfaces[]` record: create `<interface>` with
   `<name>`, `<config><name>`, `<config><description>` (if non-empty),
   `<config><enabled>` (true/false), `<config><type>` (if non-empty),
   `<subinterfaces>/<subinterface index=0>/<ipv4>` (if any
   ipv4_addresses) and `<ipv6>` (if any ipv6_addresses).
3. Pretty-print and return.

That's the entire render surface.  `intent.hostname`, `intent.snmp`,
`intent.vlans`, `intent.routing_instances`, `intent.static_routes`,
`intent.local_users`, `intent.radius_servers`, `intent.lags`,
`intent.vxlan_vnis`, `intent.evpn_type5_routes`, `intent.dhcp_servers`,
`intent.ntp_servers`, `intent.syslog_servers`, `intent.dns_servers`,
`intent.timezone`, `intent.domain`, `intent.apply_groups`,
`intent.group_content` are NEVER written to the output XML by this
codec, regardless of how rich the canonical tree is.

## What the output XML looks like

After `cisco_iosxe.render(canonical_tree)` of a Junos source with
hostname / DNS / NTP / VLANs / VXLAN / VRF / SNMP / local users
populated, the resulting XML carries:

```xml
<interfaces xmlns="http://openconfig.net/yang/interfaces">
  <interface>
    <name>ge-0/0/0</name>
    <config>
      <name>ge-0/0/0</name>
      <description>WAN uplink</description>
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
  <!-- ... more <interface> records -->
</interfaces>
```

There is no top-level `<system>`, `<vlans>`, `<network-instances>`,
`<snmp>`, `<aaa>`.  A downstream OpenConfig consumer would see
interface-only data — VLAN id 100 from the Junos source is gone, the
hostname is gone, the SNMPv3 USM users are gone.

## Wire-up gaps explicitly declared

The codec's CapabilityMatrix declares many paths under `supported`:

* `/system/hostname`, `/system/dns-server`, `/system/ntp-server`
* `/vlans/vlan/id`, `/vlans/vlan/name`
* `/routing/static-route`
* `/snmp/community`, `/snmp/location`, `/snmp/contact`,
  `/snmp/trap-host`

These declarations are aspirational — they exist so cross-codec mesh
translations don't classify these paths as `unsupported` on the
target side.  But the render does not actually emit any XML for
them.  The disposition for these on this direction is `unsupported`
with reason citing "render-side wire-up gap; matrix declares
supported aspirationally".

## Disposition implication

Every canonical field NOT walked by the render shows up as
`unsupported` on this direction's expectation YAML.  This is
materially honest about the codec's current state.  The Junos
source IS wired for these fields (hostname / DNS / NTP / VLANs /
VXLAN / VRF / SNMP all populate the canonical tree); the gap is
purely on the Cisco render path.

When render-side wire-up lands on the cisco_iosxe codec, the YAML
would need substantial revision to flip `unsupported` to `good` /
`lossy` for the canonical-modelled fields.
