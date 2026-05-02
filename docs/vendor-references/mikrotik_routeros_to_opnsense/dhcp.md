# DHCP server: MikroTik RouterOS versus OPNsense

## MikroTik RouterOS

Source: [DHCP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/24805500/DHCP)

Retrieved: 2026-04-30

RouterOS splits DHCP server configuration into THREE sections:

```
/ip pool
add name=lan_pool ranges=10.0.0.100-10.0.0.200
add name=users_pool ranges=10.100.0.100-10.100.0.200

/ip dhcp-server
add address-pool=lan_pool authoritative=yes disabled=no \
    interface=bridge1 lease-time=1h name=lan-dhcp
add address-pool=users_pool authoritative=yes disabled=no \
    interface=vlan100 lease-time=8h name=users-dhcp

/ip dhcp-server network
add address=10.0.0.0/24 gateway=10.0.0.1 \
    dns-server=10.0.0.1,1.1.1.1 domain=lab.example.net
add address=10.100.0.0/24 gateway=10.100.0.1 \
    dns-server=10.100.0.1 domain=users.example.net

/ip dhcp-server lease
add address=10.0.0.50 mac-address=AA:BB:CC:DD:EE:FF \
    server=lan-dhcp comment="Reserved printer"
```

The MikroTik codec joins the three sections on parse to produce a
single CanonicalDHCPPool per (interface, network) pair:

- ``/ip pool`` defines the lease range as ``ranges=START-END``.
- ``/ip dhcp-server`` binds a pool to an interface and sets
  authoritative / lease-time flags.
- ``/ip dhcp-server network`` carries network-level options (gateway,
  DNS servers, domain name).
- ``/ip dhcp-server lease`` carries static reservations — these have
  no canonical field and drop to ``raw_sections``.

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
``<defaultleasetime>`` is in SECONDS.  Static reservations live under
``<dhcpd>/<staticmap>`` (separate from the pool body).  The
underlying ISC ``dhcpd`` daemon (or the newer ``kea`` engine in
recent OPNsense releases) reads a synthesised ``dhcpd.conf`` from
``config.xml`` at boot.

## Cross-vendor mapping

Canonical surface:

```
CanonicalDHCPPool(interface, network, start_ip, end_ip, gateway,
                  dns_servers[], lease_time, domain_name)
```

The OPNsense codec does not currently advertise ``/dhcp/pool`` in
its capability matrix supported[]; render is partial pending
wire-up.  RouterOS source canonical DHCP pools therefore drop on
render.

### Specific lossy points

- **Network inference** — RouterOS stores ``address=10.0.0.0/24``
  on the ``/ip dhcp-server network`` line; OPNsense infers the
  network from the zone interface.  The cross-vendor render must
  reconcile these by ensuring the pool's interface matches the
  inferred zone — operator-curated.
- **Lease time units** — RouterOS uses suffixed text
  (``lease-time=1h`` / ``lease-time=8h`` / ``lease-time=86400s``)
  which the codec parses into seconds for canonical.  OPNsense's
  ``<defaultleasetime>`` is bare seconds.  Round-trip preserves
  the integer.
- **DNS server list shape** — RouterOS ``dns-server=10.0.0.1,1.1.1.1``
  (comma-separated) ↔ OPNsense ``<dnsserver>1.1.1.1,9.9.9.9
  </dnsserver>`` (also comma-separated).  Same list semantics.
- **Static reservations** — RouterOS ``/ip dhcp-server lease`` and
  OPNsense ``<staticmap>`` have no canonical field; both drop to
  ``raw_sections``.
- **DHCP option codes** — RouterOS option-set (option 43, 82, etc.)
  is not modelled canonically.

### Disposition

| Field | Disposition |
|---|---|
| `dhcp_servers[].interface` | lossy (OPNsense render wire-up pending) |
| `dhcp_servers[].network` | lossy (OPNsense infers from zone interface; render wire-up pending) |
| `dhcp_servers[].start_ip` | lossy (OPNsense render wire-up pending) |
| `dhcp_servers[].end_ip` | lossy (OPNsense render wire-up pending) |
| `dhcp_servers[].gateway` | lossy (OPNsense render wire-up pending) |
| `dhcp_servers[].dns_servers` | lossy (OPNsense render wire-up pending) |
| `dhcp_servers[].lease_time` | lossy (OPNsense render wire-up pending) |
| `dhcp_servers[].domain_name` | lossy (OPNsense render wire-up pending) |
