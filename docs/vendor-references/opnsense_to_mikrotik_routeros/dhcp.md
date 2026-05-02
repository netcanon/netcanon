# DHCP server: OPNsense versus MikroTik RouterOS

## OPNsense

Source: [OPNsense ISC DHCPv4 manual](https://docs.opnsense.org/manual/isc.html)

Retrieved: 2026-04-30

OPNsense uses an INTERFACE-KEYED layout — pools live under
``<dhcpd>/<zone-name>``:

```xml
<dhcpd>
  <wan/>
  <lan>
    <enable/>
    <range>
      <from>192.168.10.100</from>
      <to>192.168.10.199</to>
    </range>
    <gateway>192.168.10.1</gateway>
    <dnsserver>1.1.1.1,9.9.9.9</dnsserver>
    <domain>lan.example.net</domain>
    <defaultleasetime>7200</defaultleasetime>
    <maxleasetime>86400</maxleasetime>
  </lan>
</dhcpd>
```

The pool network / mask is INFERRED from the zone interface (the
``<lan>`` zone's IP / subnet defines the pool's network).
``<defaultleasetime>`` is in SECONDS.

## MikroTik RouterOS

Source: [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)

Retrieved: 2026-04-30

RouterOS splits DHCP server into THREE sections:

```
/ip pool
add name=lan_pool ranges=192.168.10.100-192.168.10.199

/ip dhcp-server
add address-pool=lan_pool authoritative=yes disabled=no \
    interface=ether2 lease-time=2h name=lan-dhcp

/ip dhcp-server network
add address=192.168.10.0/24 gateway=192.168.10.1 \
    dns-server=1.1.1.1,9.9.9.9 domain=lan.example.net
```

The MikroTik codec joins the three sections on parse to produce a
single CanonicalDHCPPool per (interface, network) pair; renders
all three on emission.

## Cross-vendor mapping

Canonical surface:

```
CanonicalDHCPPool(interface, network, start_ip, end_ip, gateway,
                  dns_servers[], lease_time, domain_name)
```

The OPNsense codec parses ``<dhcpd>`` into the canonical list (per
the kitchen-sink fixture's documented coverage).  RouterOS target
codec advertises ``/dhcp/pool`` in its capability matrix, so the
RouterOS render path emits the three-section form.

### Specific lossy points

- **Network inference** — OPNsense infers from zone interface;
  RouterOS stores ``address=`` directly.  Cross-pair renders the
  RouterOS network from the canonical ``CanonicalDHCPPool.network``
  (which the OPNsense parser populates from the zone interface's
  IP + subnet).
- **Lease time units** — OPNsense seconds (``<defaultleasetime>7200``)
  ↔ RouterOS suffixed text (``lease-time=2h``).  Both round-trip
  via integer seconds on canonical.
- **Static reservations** — OPNsense ``<staticmap>`` and RouterOS
  ``/ip dhcp-server lease`` have no canonical field; both drop to
  ``raw_sections``.
- **DHCP option codes** — option 43 / option 82 / etc. are not
  modelled canonically; drop on either direction.
- **DNS server list shape** — both sides comma-separated; round-trip
  cleanly.
- **Multiple zones** — OPNsense supports multiple zone-keyed pools
  (``<lan>``, ``<opt1>``, …); RouterOS supports multiple
  ``/ip dhcp-server`` entries.  Round-trip preserves multiplicity.

### Disposition

| Field | Disposition |
|---|---|
| `dhcp_servers[].interface` | lossy (zone tag → RouterOS interface name; rename-mesh canonicalises) |
| `dhcp_servers[].network` | good |
| `dhcp_servers[].start_ip` | good |
| `dhcp_servers[].end_ip` | good |
| `dhcp_servers[].gateway` | good |
| `dhcp_servers[].dns_servers` | good |
| `dhcp_servers[].lease_time` | good |
| `dhcp_servers[].domain_name` | good |
