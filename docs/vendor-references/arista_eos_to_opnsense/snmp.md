# SNMP: Arista EOS versus OPNsense

## Arista EOS

Source: [Arista EOS User Manual — SNMP](https://www.arista.com/en/um-eos/eos-snmp)
Retrieved: 2026-05-01

```
snmp-server community public ro
snmp-server location "Synthetic Lab Rack 7"
snmp-server contact "noc@example.net"
snmp-server host 10.0.0.250
snmp-server user monitor netadmin v3 auth sha $9$fake$authHash$1 priv aes256 $9$fake$privHash$1
snmp-server user readonly readonly v3 auth sha256 $9$fake$authHash$2 priv aes $9$fake$privHash$2
```

Arista SNMP notes:

- v1/v2c: `snmp-server community <name> {ro|rw}`.  Canonical
  preserves the first community as `CanonicalSNMP.community`.
- `snmp-server location` / `contact` carry quoted free-text;
  canonical strips quotes.
- `snmp-server host <addr>` declares trap-receivers.
- v3 USM users: `snmp-server user <name> <group> v3 auth
  {md5|sha|sha256|...} <hash> priv {des|aes|aes256|...} <hash>`.
  The arista_eos codec capability matrix declares
  `/snmp/v3-user` supported with full auth + priv key
  pass-through.

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
    <traphost>10.0.0.250</traphost>
  </snmpd>
</opnsense>
```

Notes:

- `<rocommunity>` carries the read-only community.
  `<rwcommunity>` is supported but rare in production.
- Multiple `<traphost>` elements are accepted; canonical list
  order preserved.
- SNMPv3 USM is conspicuously absent from `config.xml`.  The
  OPNsense codec capability matrix lists `/snmp/v3-user` as
  unsupported with rationale: "OPNsense's SNMPv3 user store lives
  in the bsnmpd / net-snmp plugin's own configuration format
  (`/usr/local/etc/snmpd.conf` createUser lines), not in the
  config.xml this codec reads."

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields covered (`CanonicalSNMP`):

```
community: str
location: str
contact: str
trap_hosts: list[str]
v3_users: list[CanonicalSNMPv3User]
```

- `snmp.community`: **good** — Arista `snmp-server community X
  ro` ↔ OPNsense `<rocommunity>X</rocommunity>`.  The `rw`
  keyword is a degraded read-only on this cross-pair (OPNsense
  rwcommunity is rare; codec normalises to ro).
- `snmp.location` / `snmp.contact`: **good** — direct mapping to
  `<syslocation>` / `<syscontact>`.
- `snmp.trap_hosts`: **good** — Arista `snmp-server host <addr>`
  ↔ OPNsense `<traphost>`.
- `snmp.v3_users`: **unsupported** — Arista carries v3 USM users
  but OPNsense's v3 store lives in snmpd.conf, outside the
  canonical surface.  Arista-source v3 users drop on the
  cross-pair; the rename-pane shows the `snmpv3`
  unsupported-category banner declared on the OPNsense codec's
  `unsupported_rename_categories` frozenset.
