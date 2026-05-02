# DHCP: OPNsense `<dhcpd>` server versus Arista EOS `ip dhcp pool`

## OPNsense

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)
Retrieved: 2026-04-30

OPNsense uses the ISC dhcpd backend (or Kea on newer releases)
with INTERFACE-KEYED pool blocks:

```xml
<opnsense>
  <dhcpd>
    <lan>
      <enable>1</enable>
      <range>
        <from>10.0.10.100</from>
        <to>10.0.10.200</to>
      </range>
      <gateway>10.0.10.1</gateway>
      <domain>example.net</domain>
      <dnsserver>10.0.10.1</dnsserver>
      <defaultleasetime>7200</defaultleasetime>
      <maxleasetime>86400</maxleasetime>
    </lan>
  </dhcpd>
</opnsense>
```

- The XML tag IS the zone interface (`<lan>`, `<opt1>`, …); no
  separate `<name>` element.
- Network / mask is INFERRED from the zone interface's
  `<ipaddr>` + `<subnet>`; not stored on the pool record.
- Lease time is in seconds.

## Arista EOS

Source: [Arista EOS User Manual — DHCP and DHCP Relay](https://www.arista.com/en/um-eos/eos-dhcp-and-dhcp-relay)
Retrieved: 2026-05-01

```
ip dhcp pool USERS
   network 10.10.10.0 255.255.255.0
   range 10.10.10.100 10.10.10.200
   default-router 10.10.10.1
   domain-name example.net
   dns-server 10.10.10.1
   lease 0 12 0
```

- Named-pool form (`ip dhcp pool <name>`).
- `network` accepts dotted-mask or CIDR forms.
- `range` is the allocatable window.
- `lease <days> <hours> <minutes>` triple; canonical converts
  to seconds.

## Cross-vendor mapping (OPNsense -> Arista EOS)

Canonical fields covered (`CanonicalDHCPPool`).

- `dhcp_servers`: **lossy** — OPNsense source populates
  `CanonicalIntent.dhcp_servers` with one record per zone
  interface carrying a `<dhcpd>` block (interface, range,
  gateway, dns_servers, lease_time, domain_name).  Arista
  target accepts `ip dhcp pool` blocks via the standard
  Cisco-style grammar but the network / mask must be SYNTHESISED
  from the canonical `network` field (which OPNsense parse
  populates by computing it from the zone interface's IP +
  subnet).  Lease-time conversion (seconds ↔ d/h/m) is
  mechanical.  OPNsense codec does not currently advertise
  `/dhcp/pool` on its capability matrix; cross-pair render is
  partial pending wire-up.
