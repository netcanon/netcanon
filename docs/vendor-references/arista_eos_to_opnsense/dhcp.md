# DHCP: Arista EOS server / relay versus OPNsense `<dhcpd>` server

## Arista EOS

Source: [Arista EOS User Manual — DHCP and DHCP Relay](https://www.arista.com/en/um-eos/eos-dhcp-and-dhcp-relay)
Retrieved: 2026-05-01

Arista EOS supports both DHCP server pools and DHCP relay.  Pool
form:

```
ip dhcp pool USERS
   network 10.10.10.0 255.255.255.0
   range 10.10.10.100 10.10.10.200
   default-router 10.10.10.1
   domain-name example.net
   dns-server 10.10.10.1
   lease 0 12 0
!
ip dhcp pool VOICE
   network 10.10.20.0 /24
   range 10.10.20.50 10.10.20.150
```

Arista DHCP-pool notes:

- Named pool form (`ip dhcp pool <name>`); the canonical
  `CanonicalDHCPPool.interface` field carries the operator-chosen
  name.
- `network` accepts dotted-mask or CIDR forms.
- `range` is the allocatable window (start + end IP).
- `lease <days> <hours> <minutes>` is the wire-format triple;
  canonical converts to seconds.
- DHCP-relay form (`ip dhcp relay information option` plus
  per-VLAN `ip helper-address <addr>`) is independent of the pool
  surface; canonical has no helper-address field today.

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

- `dhcp_servers`: **lossy** — Arista's named-pool form
  (`USERS` / `VOICE`) maps to OPNsense's interface-keyed
  `<dhcpd>/<lan>` style.  The `interface` field on canonical
  carries the pool name on Arista but the zone label on
  OPNsense, so cross-pair render needs operator-driven mapping.
  Pool network / mask is INFERRED from the zone interface on
  OPNsense; Arista's explicit `network` line drops on render.
  Lease-time conversion (Arista d/h/m triple ↔ OPNsense
  seconds) is mechanical.  OPNsense codec does not currently
  advertise `/dhcp/pool` in its capability matrix; cross-pair
  render is partial pending wire-up.
