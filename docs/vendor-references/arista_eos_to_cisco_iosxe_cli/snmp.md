# SNMP: Arista EOS versus Cisco IOS-XE

## Arista EOS

Source: [EOS 4.36.0F — SNMP](https://www.arista.com/en/um-eos/eos-snmp)
Retrieved: 2026-04-30

v1 / v2c surface (verbatim from the EOS manual):

```
snmp-server community <string_text> [view <view_name>] [ro|rw]
snmp-server location <node_locate>
snmp-server contact <contact_string>
snmp-server host <host_id> [informs|traps] [udp-port <dest_port>] version [1|2c|3] [community_string]
```

v3 USM:

```
snmp-server group <group_name> version [v1|v2c|v3 noauth|auth|priv] [read <view_name>] [write <view_name>]
snmp-server user <user_name> <group_name> [remote <addr>] version v3 [auth <method> <password>] [priv <encryption> <password>]
```

Concrete EOS example:

```
snmp-server group tech-group v3 priv read all-items
snmp-server user tech-user-1 tech-group v3 auth sha SecretAuth priv aes 128 SecretPriv
```

## Cisco IOS-XE

Source: [SNMP Configuration Guide, Cisco IOS XE Release 3SE — SNMP Version 3](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-3se/3850/snmp-xe-3se-3850-book/nm-snmp-snmpv3.html)
Source: [SNMP Configuration Guide, Cisco IOS XE Release 3SE — AES and 3-DES Encryption Support for SNMP Version 3](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-3se/3850/snmp-xe-3se-3850-book/nm-snmp-encrypt-snmp-support.html)
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

The `snmp-server user` line is NOT echoed in `show running-config` for
security reasons (Cisco strips it); it is recovered via
`show snmp user`.  Migration parsers must accept either source.

## Cross-vendor mapping

The canonical surface is `CanonicalSNMP` (with `community`,
`location`, `contact`, `trap_hosts`, `v3_users`).  Both codecs declare
the standard paths in their capability matrices:

```
/snmp/community
/snmp/location
/snmp/contact
/snmp/trap-host
/snmp/v3-user
```

Round-trip is good for v1 / v2c: byte-identical grammar between
vendors.  v3 USM lands cross-vendor for the fields modelled on
`CanonicalSNMPv3User` (name, group, auth_protocol, auth_passphrase,
priv_protocol, priv_passphrase, engine_id) BUT the opaque hashed
passphrases are NOT cross-compatible: USM keys are salted with
vendor-specific engineID-derived constants, so an Arista-derived
passphrase will fail on Cisco after migration.

The schema docstring (`CanonicalSNMPv3User` in
`netconfig/migration/canonical/intent.py`) documents this directly:
"Same-vendor round-trip is lossless; cross-vendor migration typically
requires re-keying on the target device (hashes are salted with
vendor-specific constants)."

Disposition for community / location / contact / trap-host: **good**.
Disposition for v3 user keys: **lossy** (operator re-keys on target).
