# SNMP: Cisco IOS-XE versus Juniper Junos

How v1 / v2c communities and v3 USM users are declared.

Sources:
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-17/snmp-xe-17-book.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html (retrieved 2026-04-30)

Citation ids: `cisco-snmp-cg`, `junos-snmp-overview`, `junos-snmpv3-cg`.

## Cisco IOS-XE form

v1 / v2c:

```
snmp-server community public RO
snmp-server community private RW
snmp-server location "Rack 4 DC1"
snmp-server contact "noc@example.com"
snmp-server host 10.0.0.99 version 2c public
```

v3 USM:

```
snmp-server group OPS-GROUP v3 priv read OPS-VIEW write OPS-VIEW
snmp-server user noc OPS-GROUP v3 auth sha NocAuthPass priv aes 128 NocPrivPass
```

Hash storage in `running-config` after first save:

```
snmp-server user noc OPS-GROUP v3 encrypted auth sha <hash> priv aes 128 <hash>
```

## Junos form

v1 / v2c:

```
set snmp community public authorization read-only
set snmp community private authorization read-write
set snmp location "Rack 4 DC1"
set snmp contact "noc@example.com"
set snmp trap-group ops-traps targets 10.0.0.99
set snmp trap-group ops-traps version v2
```

v3 USM (three independent hierarchies — user, security-to-group,
group access):

```
set snmp v3 usm local-engine user noc authentication-sha authentication-key "$9$..."
set snmp v3 usm local-engine user noc privacy-aes128 privacy-key "$9$..."
set snmp v3 vacm security-to-group security-model usm security-name noc group OPS-GROUP
set snmp v3 vacm access group OPS-GROUP default-context-prefix security-model usm security-level privacy read-view OPS-VIEW write-view OPS-VIEW
set snmp view OPS-VIEW oid .1 include
```

Junos auth-protocol values: `authentication-md5`, `authentication-sha`
(SHA-1), `authentication-sha224`, `authentication-sha256`.  Privacy
values: `privacy-des`, `privacy-3des`, `privacy-aes128`,
`privacy-aes192`, `privacy-aes256`.

## Mapping notes

- **v1 / v2c surface.** `community`, `location`, `contact`, and
  trap hosts (`trap_hosts`) round-trip cleanly between vendors;
  the canonical `CanonicalSNMP` carries the cross-vendor surface.
- **v3 USM round-trip.** Both vendors store
  `auth-protocol`, `priv-protocol`, opaque hash blobs, and a
  group binding.  Canonical `CanonicalSNMPv3User` carries this
  surface losslessly at the schema level.
- **Hash incompatibility.** Cisco encrypts the auth/priv passphrase
  with a vendor-specific engineID-derived key; Junos uses its own
  `$9$...` reversible-encrypted blob for the same purpose.  Bytes
  do NOT cross-decrypt.  Canonical preserves the opaque blob;
  cross-vendor migration requires re-keying every v3 user on the
  target device.  Documented in the `CanonicalSNMPv3User`
  docstring.
- **VACM access plumbing.** Junos's three-hierarchy
  user/security-to-group/access split is richer than Cisco's
  single-line `snmp-server group / user`.  Canonical doesn't model
  views or per-context-prefix access; cross-vendor round-trip
  emits a default group only.
- **Trap group versus per-host.** Cisco's `snmp-server host
  <addr>` is per-trap-target; Junos's `snmp trap-group <name>
  targets <addr>` groups multiple targets under one named policy.
  The canonical `trap_hosts: list[str]` flattens both into a host
  list.

Disposition: **good** on v1/v2c surface; **lossy** on v3 USM
passphrase preservation (re-key required on cross-vendor migration).
