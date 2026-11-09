# DHCP: OPNsense `<dhcpd>` server versus Arista EOS `dhcp server`

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

Sources: [Arista EOS User Manual — DHCP Server](https://www.arista.com/en/um-eos/eos-dhcp-overview),
and the `dhcp-servers` template of Arista's config generator, AVD
(`eos_cli_config_gen`).
Retrieved: 2026-11-09

```
dhcp server
   !
   subnet 10.10.10.0/24
      !
      range 10.10.10.100 10.10.10.200
      dns server 10.10.10.1
      lease time 0 days 2 hours 0 minutes
      default-gateway 10.10.10.1
!
interface Ethernet2
   no switchport
   ip address 10.10.10.1/24
   dhcp server ipv4
```

- One server a VRF (`dhcp server [vrf <name>]`), a `subnet <prefix>`
  for each pool, and `dhcp server ipv4` under each interface that
  serves one.  A domain is a setting of the whole server.
- Up to two DNS servers a subnet; a lease is days, hours and
  minutes, of at most 2000 days (AVD's schema).
- See [`../arista_eos_to_opnsense/dhcp.md`](../arista_eos_to_opnsense/dhcp.md)
  for the grammar in full.

## Cross-vendor mapping (OPNsense -> Arista EOS)

Canonical fields covered (`CanonicalDHCPPool`).

- `dhcp_servers`: **supported** — an OPNsense pool is on the device
  its zone is assigned to, with the subnet of the zone's address as
  its network.  The EOS output writes it as a `subnet` of the server
  of that interface's VRF, with `dhcp server ipv4` under the
  interface, and reads the pool's interface back from it.  What EOS
  cannot be given as the tree has it is a `! review:` line in the
  server and a warning of the job: a domain that not every subnet of
  the server has, DNS servers past two, a lease that does not end or
  is longer than 2000 days, a range outside the network, an interface
  that holds no address of the pool's network.  Lease-time conversion
  (seconds ↔ days / hours / minutes) is mechanical, a minute at the
  finest.
