# SNMP: Aruba AOS-S versus OPNsense

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Management and Configuration Guide —
SNMP](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
snmp-server community "public" Operator
snmp-server location "Synthetic-Lab Rack 7"
snmp-server contact "netops@example.invalid"
snmp-server host 10.0.10.200
snmp-server host 10.0.10.201

snmpv3 user "monitor-usr" auth sha "$1$fakeAJ$auth1abcdef0123456789" priv aes "$1$fakeAJ$priv1abcdef0123456789"
snmpv3 group "auth-priv-grp" user "monitor-usr" sec-model ver3
```

- v1/v2c: communities tagged `Operator` (read-only) or `Manager`
  (read-write).  The canonical SNMP model carries only the FIRST
  community as a single string.
- SNMPv3 USM users live in `snmpv3 user <name> auth <hash-alg>
  "<auth-hash>" priv <cipher> "<priv-hash>"` plus a separate
  `snmpv3 group <group> user <name> sec-model ver3` line.
- `snmp-server host <addr>` declares trap-receivers.

## OPNsense

Source: [OPNsense Net-SNMP plugin reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-04-30

OPNsense's snmpd configuration lives in `<snmpd>`:

```xml
<opnsense>
  <snmpd>
    <syslocation>Synthetic-Lab Rack 7</syslocation>
    <syscontact>netops@example.invalid</syscontact>
    <rocommunity>public</rocommunity>
    <traphost>10.0.10.200</traphost>
  </snmpd>
</opnsense>
```

Notes:

- `<rocommunity>` carries the read-only community.  Read-write
  (`<rwcommunity>`) is supported but the OPNsense documentation
  warns against it; rare in production.
- Only ONE trap-host element is supported in the base shape; some
  plugin versions extend this.
- SNMPv3 USM is conspicuously absent from `config.xml`.  The
  OPNsense codec capability matrix lists `/snmp/v3-user` as
  unsupported with rationale: "OPNsense's SNMPv3 user store lives in
  the bsnmpd / net-snmp plugin's own configuration format
  (`/usr/local/etc/snmpd.conf` createUser lines), not in the
  config.xml this codec reads."

## Cross-vendor mapping

Canonical fields covered (`CanonicalSNMP`):

```
community: str
location: str
contact: str
trap_hosts: list[str]
v3_users: list[CanonicalSNMPv3User]
```

Aruba -> OPNsense:

- `snmp.community`: **good** — Aruba `snmp-server community "X"
  Operator` ↔ OPNsense `<rocommunity>X</rocommunity>`.  The
  Operator/Manager keyword is normalised to RO on canonical (only
  the first community survives).
- `snmp.location` / `snmp.contact`: **good** — direct mapping to
  `<syslocation>` / `<syscontact>`.
- `snmp.trap_hosts`: **good** — Aruba `snmp-server host <addr>` ↔
  OPNsense `<traphost>`.  If multiple Aruba trap-hosts are
  configured, the OPNsense render emits multiple `<traphost>`
  elements (the schema accepts repetition).
- `snmp.v3_users`: **unsupported** — OPNsense's v3 store lives in
  snmpd.conf, outside the canonical surface.  Aruba-source v3 users
  drop on the cross-pair; the rename-pane shows the `snmpv3`
  unsupported-category banner declared on the OPNsense codec's
  `unsupported_rename_categories` frozenset.
