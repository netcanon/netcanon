# DHCP relay (no server pools): Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 IP Routing Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/IPv4/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S devices act primarily as **DHCP relay**:

```
dhcp-relay
ip helper-address 10.0.0.10
```

`ip helper-address` is configured per-VLAN inside the VLAN stanza
on AOS-S:

```
vlan 10
   name "USERS"
   untagged 1-24
   ip address 192.168.10.1/24
   ip helper-address 10.0.0.10
   exit
```

The `aruba_aoss` codec does NOT advertise `/dhcp/pool` in its
supported set — DHCP-server pool config has no parse path on the
AOS-S side, so the canonical `dhcp_servers` list is always empty
on Aruba parse.

(Newer firmware adds basic DHCP-server support; the codec does
not yet wire it up.  Lossy-by-deferral on this direction.)

## Cisco IOS-XE

Source: [Cisco IOS XE 17.x DHCP Configuration Guide](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/ipaddr_dhcp/configuration/xe-17/dhcp-xe-17-book.html)
Retrieved: 2026-04-30

Cisco supports both DHCP server pools (`ip dhcp pool <name>`) and
DHCP relay (`ip helper-address` per L3 interface).

## Cross-vendor mapping

* Aruba -> Cisco: `CanonicalIntent.dhcp_servers` is always empty
  on the source side, so this direction loses nothing on parse.
  The canonical model is unaffected.
* `ip helper-address` directives on the Aruba VLAN stanza are not
  parsed into the canonical model (no
  `CanonicalVlan.helper_addresses` field).  These drop on parse
  and are not preserved across migration.

Disposition: **not_applicable** for `dhcp_servers` (always empty
on Aruba source).  **Lossy** for the helper-address directive
(not modelled).
