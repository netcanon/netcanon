# SNMP: Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: [SNMP Configuration Guide, Cisco IOS XE Release 3SE](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-3se/3850/snmp-xe-3se-3850-book/nm-snmp-snmpv3.html)
Retrieved: 2026-04-30

v1 / v2c surface:

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

`snmp-server user` lines are NOT echoed in `show running-config` for
security reasons (recovered via `show snmp user`).  The migration
parser must accept either source.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

v1 / v2c surface — note the quoted community + access-keyword
differences:

```
snmp-server community "public" Operator
snmp-server community "private" Manager unrestricted
snmp-server location "Building 7 Floor 3"
snmp-server contact "noc@example.com"
snmp-server host 10.0.0.5 community "public"
```

AOS-S access keywords are `Operator` / `Manager` (the AOS-S RBAC
roles) rather than `RO` / `RW`.  The default mapping is
`Operator -> read-only`, `Manager -> read-write`.

v3 USM (the codec's `_SNMPV3_USER_RE` matches this exact shape):

```
snmpv3 user "opsuser" auth sha "AUTHP4SS" priv aes "PR1VP4SS"
snmpv3 group "READONLY" user "opsuser" sec-model ver3
```

The grammar uses `snmpv3` keyword (not `snmp-server`) and quotes the
user + passphrase tokens.  The group binding is on a separate line
which the parser merges with the user record.

## Cross-vendor mapping

The canonical surface is `CanonicalSNMP` with `community`,
`location`, `contact`, `trap_hosts`, and `v3_users`.  Both codecs
declare the standard paths in their capability matrices:

```
/snmp/community
/snmp/location
/snmp/contact
/snmp/trap-host
/snmp/v3-user
```

Round-trip details:

* `community`: stored as the bare community string (without the
  RO/RW or Operator/Manager keyword).  The access-mode mapping is
  not modelled in v1 of `CanonicalSNMP` so cross-vendor round-trip
  defaults Cisco RO -> Aruba Operator and Cisco RW -> Aruba
  Manager.  Operator overrides the access semantic at deploy time.
* `location` / `contact`: opaque free-text; round-trips cleanly.
* `trap_hosts`: list of host addresses.  Per-host `version 2c
  <community>` (Cisco) versus `community "<name>"` (Aruba)
  positional differences are not modelled.
* `v3_users`: name + group + auth_protocol + auth_passphrase +
  priv_protocol + priv_passphrase round-trip the structured
  fields.  The opaque hashed passphrases are NOT cross-compatible
  — USM keys are salted with vendor-specific engineID-derived
  constants.  Documented in `CanonicalSNMPv3User` docstring.

Disposition for `community` / `location` / `contact` / `trap_hosts`:
**good**.

Disposition for `v3_users`: **lossy** (operator must re-key on the
target device).
