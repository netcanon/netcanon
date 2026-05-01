# SNMP: Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

v1/v2c surface — quoted community + AOS-S-named access keyword:

```
snmp-server community "public" Operator
snmp-server community "private" Manager unrestricted
snmp-server location "Building 7 Floor 3"
snmp-server contact "noc@example.com"
snmp-server host 10.0.0.5 community "public"
```

Access keywords: `Operator` (read-only by default) and `Manager`
(read-write).  These are AOS-S RBAC roles, not RO/RW.

v3 USM (the codec's `_SNMPV3_USER_RE` and `_SNMPV3_GROUP_BIND_RE`
match this shape):

```
snmpv3 user "opsuser" auth sha "AUTHP4SS" priv aes "PR1VP4SS"
snmpv3 group "READONLY" user "opsuser" sec-model ver3
```

## Cisco IOS-XE

Source: [SNMP Configuration Guide, Cisco IOS XE Release 3SE](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-3se/3850/snmp-xe-3se-3850-book/nm-snmp-snmpv3.html)
Retrieved: 2026-04-30

v1/v2c surface:

```
snmp-server community public RO
snmp-server community private RW
snmp-server location "Building 7 Floor 3"
snmp-server contact "noc@example.com"
snmp-server host 10.0.0.5 version 2c public
```

v3 USM:

```
snmp-server group READONLY v3 priv read all-items
snmp-server user opsuser READONLY v3 auth sha AUTHP4SS priv aes 128 PR1VP4SS
```

## Cross-vendor mapping

The canonical surface is `CanonicalSNMP` with `community`,
`location`, `contact`, `trap_hosts`, and `v3_users`.

Aruba -> Cisco round-trip details:

* `community`: Aruba `Operator` -> Cisco `RO`; Aruba `Manager`
  -> Cisco `RW` (the access semantic is not modelled in canonical
  v1, so cross-vendor render emits a default mapping).
* `location` / `contact`: opaque free-text round-trips cleanly.
* `trap_hosts`: Aruba's `snmp-server host <addr> community "X"`
  emits as Cisco's `snmp-server host <addr> version 2c X`.
* `v3_users`: structured fields (name + group + auth_protocol +
  priv_protocol) round-trip; opaque hashed passphrases are NOT
  cross-compatible because USM keys are salted with vendor-
  specific engineID-derived constants.  Documented in
  `CanonicalSNMPv3User` docstring.

Disposition for `community` / `location` / `contact` /
`trap_hosts`: **good**.

Disposition for `v3_users`: **lossy** (operator must re-key on the
target device).
