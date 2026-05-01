# DHCP relay versus DHCP server pools: Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x DHCP Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_dhcp/configuration/xe-17/dhcp-xe-17-book.html)
Retrieved: 2026-04-30

Cisco devices act as DHCP server, DHCP relay, or both.  Server
pools live under the `ip dhcp pool` stanza:

```
ip dhcp pool USERS
 network 192.168.10.0 255.255.255.0
 default-router 192.168.10.1
 dns-server 8.8.8.8
 lease 0 12 0
```

DHCP relay on an interface uses `ip helper-address`:

```
interface Vlan10
 ip helper-address 10.0.0.10
```

The `cisco_iosxe_cli` codec parses `ip dhcp pool` stanzas (per its
`/dhcp/pool` capability path) into `CanonicalDHCPPool` records.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IP Routing Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S devices act primarily as **DHCP relay** — the platform is
not designed to be an enterprise DHCP server.  The DHCP-relay
syntax uses `dhcp-relay`:

```
dhcp-relay
ip helper-address 10.0.0.10
```

`ip helper-address` is configured per-VLAN inside the VLAN stanza
on AOS-S (not per-physical-interface as on Cisco).

The `aruba_aoss` codec does NOT advertise `/dhcp/pool` in its
supported set — DHCP-server pool config has no parse path on the
AOS-S side.  Server pools, where deployed (newer AOS-S firmware
adds basic DHCP-server support), are emitted into a relay-comment
block by the renderer for operator review.

## Cross-vendor mapping

* Cisco -> Aruba: `CanonicalDHCPPool` records (which the Cisco
  parser populates) are dropped on the Aruba render.  Codec emits
  a relay-comment block describing what was lost.
* Aruba -> Cisco: AOS-S source carries no DHCP server pools (the
  codec does not parse them).  The
  `CanonicalIntent.dhcp_servers` field is always empty on this
  direction; nothing is lost.

`ip helper-address` directives on Cisco interfaces are not modelled
in the canonical tree (no `CanonicalInterface.helper_addresses`
field).  These drop on parse and are not preserved across
migration.

Disposition: **lossy** Cisco -> Aruba (server pools drop;
relay-helper directives drop both ways).  **Not applicable**
Aruba -> Cisco (source has no server pools to lose).
