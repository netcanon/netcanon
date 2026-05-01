# SNMP (v1 / v2c / v3 USM): Aruba AOS-S versus Juniper Junos

How communities, trap hosts, and v3 USM users are declared on each
platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html (retrieved 2026-05-01)

Citation ids: `aruba-snmp`, `junos-snmp-overview`, `junos-snmpv3-cg`.

## Aruba AOS-S form

v1 / v2c — quoted community + AOS-S-named access keyword:

```
snmp-server community "public" Operator
snmp-server community "private" Manager unrestricted
snmp-server location "Synthetic-Lab Rack 7"
snmp-server contact "noc@example.invalid"
snmp-server host 10.0.10.200
snmp-server host 10.0.10.201
```

`Operator` is read-only by default; `Manager` is read-write.  These
are AOS-S role tokens (not RO/RW abbreviations).

v3 USM (the codec's `_SNMPV3_USER_RE` and `_SNMPV3_GROUP_BIND_RE`
match this shape):

```
snmpv3 user "monitor-usr" auth sha "AUTHP4SS" priv aes "PR1VP4SS"
snmpv3 group "auth-priv-grp" user "monitor-usr" sec-model ver3
```

Auth-protocol tokens: `sha` (= SHA-1), `md5`.  Priv-protocol tokens:
`aes` (= AES-128 default), `des`.

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

Trap hosts are grouped under a named `trap-group` rather than
flat `snmp-server host` directives.

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

## Cross-vendor mapping

The canonical surface is `CanonicalSNMP(community, location, contact,
trap_hosts, v3_users)`.

Aruba -> Junos round-trip details:

* `community`: Aruba `Operator` -> Junos `read-only`; Aruba `Manager`
  -> Junos `read-write`.  The canonical model carries only the bare
  community string (single `community` field), so the access-keyword
  difference is policy on render.
* `location` / `contact`: opaque free-text round-trips cleanly.
* `trap_hosts`: Aruba's flat `snmp-server host X` lines collect into
  a single `CanonicalSNMP.trap_hosts` list; Junos render emits
  `set snmp trap-group <name> targets <addr>` lines under a
  synthesised group name.
* `v3_users`: structured fields (name + group + auth_protocol +
  priv_protocol) round-trip via `CanonicalSNMPv3User`.  Aruba `sha`
  maps to Junos `authentication-sha` (SHA-1 default); Aruba `aes`
  maps to Junos `privacy-aes128`.  Opaque hashed passphrases are
  NOT cross-compatible because USM keys are salted with vendor-
  specific engineID-derived constants — operator must re-key v3
  users on the target after migration.  Documented in the
  `CanonicalSNMPv3User` docstring.

Disposition for `community` / `location` / `contact` /
`trap_hosts`: **good**.

Disposition for `v3_users`: **lossy** (operator re-key required).
