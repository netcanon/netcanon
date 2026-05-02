# SNMP: Junos versus OPNsense

## Junos

Source: [Junos SNMP overview](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html)
Source: [Junos SNMPv3 configuration topic-map](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html)
Retrieved: 2026-05-01

```
set snmp community public authorization read-only
set snmp community private authorization read-write
set snmp location "Synthetic Lab Rack 7"
set snmp contact "noc@example.net"
set snmp trap-group monitoring targets 10.0.0.250
set snmp trap-group monitoring targets 10.0.0.251

set snmp v3 usm local-engine user monitor authentication-md5 authentication-key "$9$fakeMd5AuthKey$1"
set snmp v3 usm local-engine user monitor privacy-des privacy-key "$9$fakeDesPrivKey$1"
set snmp v3 vacm security-to-group security-model usm security-name monitor group netadmin
```

Junos SNMP notes:

- v1/v2c communities under `set snmp community NAME authorization
  read-only|read-write`.
- Trap targets are grouped — `set snmp trap-group <name> targets <ip>`
  flattens to canonical `CanonicalSNMP.trap_hosts: list[str]`.
- v3 USM splits across THREE hierarchies — `usm local-engine user`
  for auth/priv keys, `vacm security-to-group` for group binding,
  `vacm access` for view permissions.
- v3 keys are stored as `$9$...` reversibly-encrypted blobs (Junos
  ENCRYPT private-key format).

## OPNsense

Source: [OPNsense Net-SNMP plugin reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-04-30

```xml
<snmpd>
  <rocommunity>kitchensink-ro</rocommunity>
  <syslocation>Synthetic Lab Rack 7</syslocation>
  <syscontact>noc@example.net</syscontact>
  <traphost>10.0.0.250</traphost>
  <traphost>10.0.0.251</traphost>
</snmpd>
```

OPNsense SNMP notes:

- v1/v2c surface lives in `<snmpd>` block in `config.xml`.
- `<rocommunity>` carries the read-only community string; `<rwcommunity>`
  exists but is rarely used.
- `<syslocation>` / `<syscontact>` mirror standard MIB scalars.
- `<traphost>` is repeated for multiple trap receivers.
- **v3 USM is NOT in `config.xml`** — the OPNsense bsnmpd / net-snmp
  plugin stores v3 user definitions in
  `/usr/local/etc/snmpd.conf` (`createUser` lines).  The OPNsense
  codec capability matrix lists `/snmp/v3-user` as `unsupported`
  with rationale "OPNsense's SNMPv3 user store lives in the bsnmpd
  / net-snmp plugin's own configuration format".

## Cross-vendor mapping

Junos -> OPNsense:

- `snmp.community`: **good** — Junos `set snmp community NAME` ↔
  OPNsense `<rocommunity>`.  Junos's `read-only` / `read-write`
  authorization keyword maps to OPNsense's `<rocommunity>` /
  `<rwcommunity>` (canonical takes the first community; multi-
  community Junos sources collapse on render).
- `snmp.location`: **good** — Junos `location` ↔ OPNsense
  `<syslocation>`.
- `snmp.contact`: **good** — Junos `contact` ↔ OPNsense `<syscontact>`.
- `snmp.trap_hosts`: **good** — Junos `trap-group <name> targets <ip>`
  flattens to canonical `trap_hosts: list[str]` and renders to
  multiple OPNsense `<traphost>` elements.  Trap-group names drop
  (OPNsense has no group concept).
- `snmp.v3_users`: **unsupported** — Junos populates
  `CanonicalSNMP.v3_users` from its USM grammar.  OPNsense's
  capability matrix lists `/snmp/v3-user` as unsupported because
  v3 user records live in `snmpd.conf` (not `config.xml`).
  Cross-pair drops the v3 USM users; rename-pane shows the
  `snmpv3` unsupported-category banner.

Disposition: v1/v2c surface **good**; v3 USM **unsupported** on
cross-pair (target codec wire-format limitation).
