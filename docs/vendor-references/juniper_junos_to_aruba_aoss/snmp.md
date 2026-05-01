# SNMP (v1 / v2c / v3 USM): Juniper Junos versus Aruba AOS-S

How communities, trap hosts, and v3 USM users are declared on each
platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-snmp-overview`, `junos-snmpv3-cg`,
`aruba-snmp`.

## Junos form

v1 / v2c:

```
set snmp community public authorization read-only
set snmp community private authorization read-write
set snmp location "Synthetic Lab Rack 7"
set snmp contact "noc@example.net"
set snmp trap-group monitoring targets 10.0.0.250
set snmp trap-group monitoring targets 10.0.0.251
```

v3 USM:

```
set snmp v3 usm local-engine user monitor authentication-md5 authentication-key "$9$fakeMd5AuthKey"
set snmp v3 usm local-engine user monitor privacy-des privacy-key "$9$fakeDesPrivKey"
set snmp v3 vacm security-to-group security-model usm security-name monitor group netadmin
```

Auth-protocol tokens: `authentication-md5`, `authentication-sha`
(SHA-1), `authentication-sha224`, `authentication-sha256`.
Priv-protocol tokens: `privacy-des`, `privacy-aes128`, `privacy-aes192`,
`privacy-aes256`, `privacy-3des`.

## Aruba AOS-S form

v1 / v2c:

```
snmp-server community "public" Operator
snmp-server community "private" Manager unrestricted
snmp-server location "Synthetic-Lab Rack 7"
snmp-server contact "noc@example.invalid"
snmp-server host 10.0.10.200
snmp-server host 10.0.10.201
```

v3 USM:

```
snmpv3 user "monitor-usr" auth sha "AUTHP4SS" priv aes "PR1VP4SS"
snmpv3 group "auth-priv-grp" user "monitor-usr" sec-model ver3
```

Auth-protocol tokens: `sha` (SHA-1), `md5`.  Priv-protocol tokens:
`aes` (= AES-128 default), `des`.

## Cross-vendor mapping

The canonical surface is `CanonicalSNMP(community, location, contact,
trap_hosts, v3_users)`.

Junos -> Aruba round-trip details:

* `community`: Junos `read-only` -> Aruba `Operator`; Junos
  `read-write` -> Aruba `Manager`.  The canonical model carries
  only the bare community string (single field).
* `location` / `contact`: opaque free-text round-trips.
* `trap_hosts`: Junos's `trap-group <name> targets <addr>` lines
  collect into a single `CanonicalSNMP.trap_hosts` list; Aruba
  render emits flat `snmp-server host <addr>` lines (the
  trap-group name and per-group categories drop).
* `v3_users`: Junos's `authentication-sha` / `authentication-md5`
  -> Aruba `sha` / `md5`; Junos `privacy-aes128` -> Aruba `aes`;
  Junos `privacy-des` -> Aruba `des`.  Junos-only protocol variants
  (`authentication-sha224` / `sha256`, `privacy-aes192` / `aes256`,
  `privacy-3des`) have no Aruba analogue and collapse to the
  closest match (`sha` / `aes`) with a comment, OR drop on render
  if no match.  Opaque hashed passphrases are NOT cross-compatible.

Lossy notes specific to this direction:

* Junos's `set snmp v3 vacm access` plumbing (richer than canonical)
  drops on round-trip.
* Junos's per-trap-group categories (`set snmp trap-group X
  categories ...`) drop on canonical (single host list).
* Junos's `engine-id` overrides under `local-engine` are not
  modelled canonically (rare in production).

Disposition for `community` / `location` / `contact` /
`trap_hosts`: **good**.

Disposition for `v3_users`: **lossy** (Junos-only auth/priv variants
collapse + operator re-key required for passphrases).
