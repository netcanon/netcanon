# DHCP: Arista EOS `dhcp server` versus OPNsense `<dhcpd>` server

## Arista EOS

Sources: [Arista EOS User Manual — DHCP Server](https://www.arista.com/en/um-eos/eos-dhcp-overview),
and the `dhcp-servers` template of Arista's config generator, AVD
(`eos_cli_config_gen`), which prints a server as the switch does.
Retrieved: 2026-11-09

```
dhcp server vrf TENANT_A
   dns domain name ipv4 example.net
   !
   subnet 10.10.10.0/24
      !
      range 10.10.10.100 10.10.10.200
      dns server 10.10.10.1
      lease time 0 days 12 hours 0 minutes
      default-gateway 10.10.10.1
!
interface Vlan10
   vrf TENANT_A
   ip address 10.10.10.1/24
   dhcp server ipv4
```

Arista DHCP-server notes:

- One server a VRF: `dhcp server` (the default VRF) or `dhcp server
  vrf <name>`, in column 0.  Its own settings are one level in
  (`disabled`, `lease time ipv4 ...`, `dns domain name ipv4 ...`,
  `dns server ipv4 ...`, TFTP, vendor options), and `subnet <prefix>`
  with the subnet's settings a level deeper: `range <start> <end>`
  (several), `dns server`, `lease time D days H hours M minutes`,
  `default-gateway`, `reservations`, `name`.  The manual's subnet
  example writes `lease time ipv4 ...`; both forms are read.
- "dhcp Server settings can also be configured per subnet and
  overrides the dhcp Server global mode configurations": a subnet has
  the server's DNS servers and lease where it states none.  The
  domain is the server's.  Up to two DNS servers a subnet.
- An interface takes part with `dhcp server ipv4` under it.  Which
  subnet it serves is not stated; netcanon takes a subnet to be
  served on the interface with that line, in the server's VRF, that
  holds an address of it (an inference), and a subnet no such
  interface holds an address of to be served to relayed clients only.
- EOS disables a subnet whose range is outside it ("The range must be
  within the subnet mask, otherwise the subnet becomes disabled"),
  subnets that overlap, and, as `show dhcp server` shows, a subnet
  with ranges that overlap or an address reserved twice.  netcanon
  leaves such a subnet out, and the subnets of a `disabled` server,
  and says so in a row.
- No default lease is stated: a subnet whose server states none
  either is given one day, and a row says so.
- `ip dhcp pool` is no form of the server that Arista documents; it is
  not read as a pool, and a row says so.
- DHCP relay (`ip helper-address`) is independent of the server; the
  tree has no helper-address field.

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

- The XML tag IS the zone interface (`<lan>`, `<opt1>`, …).
- Network / mask is INFERRED from the zone interface's `<ipaddr>`
  + `<subnet>`; not stored on the pool record.
- Lease time is in seconds (no day/hour/minute units).

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields covered (`CanonicalDHCPPool`):

```
interface: str
network: str
start_ip: str
end_ip: str
gateway: str
dns_servers: list[str]
lease_time: int
domain_name: str
```

- `dhcp_servers`: **lossy** — an EOS subnet served on an interface is
  a pool on that interface, and OPNsense writes it under the zone of
  the port the interface becomes.  A subnet served to relayed clients
  only names no interface, and OPNsense writes it under `<lan>`, a
  zone the output has only if an interface is called that (see
  `docs/CAPABILITIES.md`, OPNsense, `/dhcp-servers/pool`).  The tree
  holds one run of addresses a pool: an EOS subnet with several
  ranges keeps the largest, and a row says so.  A subnet's
  reservations, TFTP settings and the server's vendor options are
  rows too.  Lease-time conversion (EOS days / hours / minutes ↔
  OPNsense seconds) is mechanical.
