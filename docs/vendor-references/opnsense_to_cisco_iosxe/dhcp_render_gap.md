# DHCP server pools — OPNsense source to Cisco NETCONF target

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-05-01

Source: [openconfig-system YANG schema docs](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

## OPNsense source shape

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
`<netmask>` element on the pool record.

The OPNsense codec parses `<dhcpd>` into the canonical
`dhcp_servers` list (interface-keyed entries with start_ip / end_ip
/ gateway / dns_servers / lease_time / domain_name).

## Cisco target render shape

The `cisco_iosxe._render_canonical()` method does NOT emit any DHCP
elements regardless of what the canonical tree carries.  The render
is `<interfaces>`-only.

OpenConfig has no widely-deployed DHCP server model in the
publically-shipped IOS XE 17.x YANG datastore; the data would have
to be emitted via the `Cisco-IOS-XE-dhcp.yang` native module, which
is out of scope for this Phase 0.5 stub codec.

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `dhcp_servers` | unsupported | OPNsense source populates `dhcp_servers` records; target render emits no DHCP element |

`unsupported` rather than `not_applicable` because the OPNsense
source DOES carry the data into the canonical tree.  The render-
side gap is the dominant failure mode.

If render-side wire-up lands, the disposition would flip to `lossy`
— pool network would need to be reverse-mapped from the OPNsense
zone-side inference, lease-time units would convert (OPNsense
seconds <-> Cisco d/h/m triple), and `ip dhcp excluded-address`
ranges aren't in the canonical schema and would still drop.
