# DHCP server pools — Cisco NETCONF source to OPNsense target

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-05-01

## Source side: parse-side gap

OpenConfig has no widely-deployed DHCP server model at the device
level.  Cisco IOS XE devices carry DHCP server pools under the
`Cisco-IOS-XE-dhcp.yang` native module, not under any OpenConfig
augment.  The cisco_iosxe codec's `parse()` doesn't walk DHCP XML
in any form — `intent.dhcp_servers` is empty after parse.

## Target side: OPNsense DHCP model

OPNsense uses ISC DHCPd (legacy) or Kea DHCP (modern).  The
`<dhcpd>` block in `config.xml` is INTERFACE-KEYED rather than
named-pool-keyed:

```xml
<dhcpd>
  <lan>
    <enable/>
    <range>
      <from>10.0.0.100</from>
      <to>10.0.0.200</to>
    </range>
    <gateway>10.0.0.1</gateway>
    <dnsserver>10.0.0.1</dnsserver>
    <defaultleasetime>86400</defaultleasetime>
  </lan>
</dhcpd>
```

The pool's network/mask is INFERRED from the parent zone interface
(`<lan>`'s `<ipaddr>` + `<subnet>`).  No explicit `<network>` or
`<netmask>` element.

The OPNsense codec parses `<dhcpd>` into the canonical
`dhcp_servers` list on its own parse path, but the cisco_iosxe
codec doesn't produce `dhcp_servers` records on this cross-pair
since the parser doesn't read DHCP XML.

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `dhcp_servers` | not_applicable | source parser doesn't read DHCP XML (no OpenConfig DHCP server model widely deployed); canonical list is empty |

If parser-side wire-up lands (would require Cisco native YANG
bridging like `Cisco-IOS-XE-dhcp.yang`), the cross-pair would flip
to `lossy`: pool network would need to be reverse-mapped to an
OPNsense zone, and Cisco's d/h/m lease-time triple would convert to
OPNsense seconds.  Excluded-address ranges (Cisco
`ip dhcp excluded-address`) aren't in the canonical schema and
would still drop.
