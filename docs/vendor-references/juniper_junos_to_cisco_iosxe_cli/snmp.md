# SNMP: Juniper Junos versus Cisco IOS-XE

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html (retrieved 2026-04-30)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html (retrieved 2026-04-30)
- Cisco: https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/snmp/configuration/xe-17/snmp-xe-17-book.html (retrieved 2026-04-30)

Citation ids: `junos-snmp-overview`, `junos-snmpv3-cg`, `cisco-snmp-cg`.

## Junos form

```
set snmp community public authorization read-only
set snmp community private authorization read-write
set snmp location "Rack 4 DC1"
set snmp contact "noc@example.com"
set snmp trap-group ops-traps targets 10.0.0.99
set snmp trap-group ops-traps version v2

set snmp v3 usm local-engine user noc authentication-sha authentication-key "$9$..."
set snmp v3 usm local-engine user noc privacy-aes128 privacy-key "$9$..."
set snmp v3 vacm security-to-group security-model usm security-name noc group OPS-GROUP
set snmp v3 vacm access group OPS-GROUP default-context-prefix security-model usm security-level privacy read-view OPS-VIEW write-view OPS-VIEW
set snmp view OPS-VIEW oid .1 include
```

## Cisco IOS-XE form

```
snmp-server community public RO
snmp-server community private RW
snmp-server location "Rack 4 DC1"
snmp-server contact "noc@example.com"
snmp-server host 10.0.0.99 version 2c public

snmp-server group OPS-GROUP v3 priv read OPS-VIEW write OPS-VIEW
snmp-server user noc OPS-GROUP v3 auth sha NocAuthPass priv aes 128 NocPrivPass
```

## Mapping notes

- **v1 / v2c.** Round-trips losslessly on `community`,
  `location`, `contact`, and trap target list.  Junos's
  per-community `authorization read-only|read-write` maps to
  Cisco's `community ... RO|RW` keyword.
- **Trap target structure.** Junos's `snmp trap-group <name>
  targets <addr>` collects multiple targets under a named policy;
  Cisco's `snmp-server host <addr>` is per-target.  Canonical
  `trap_hosts: list[str]` flattens both.  Per-target version
  (`v1` / `v2` / `v3`) is preserved opportunistically; canonical
  doesn't model it explicitly.
- **v3 USM round-trip.** Both vendors store auth-protocol,
  priv-protocol, opaque hash blobs, and a group binding.
  Canonical `CanonicalSNMPv3User` carries the surface losslessly.
- **Hash bytes don't cross-decrypt.** Junos's `$9$...`
  reversible-encrypted blob and Cisco's engineID-derived
  encrypted blob are distinct; operator must re-key v3 users on
  the target after migration.  Documented in
  `CanonicalSNMPv3User` docstring.
- **VACM richness.** Junos's three-hierarchy
  user/security-to-group/access split is wider than Cisco's
  single-line `snmp-server group / user`.  Canonical doesn't
  model views or per-context access; cross-vendor round-trip
  emits a default group only.

Disposition: **good** on v1/v2c surface; **lossy** on v3 USM
passphrase preservation.
