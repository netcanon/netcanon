# SNMP: OPNsense versus Aruba AOS-S

## OPNsense

Source: [OPNsense Net-SNMP plugin reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-04-30

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

OPNsense SNMP notes:

- v1/v2c only via the base `<snmpd>` block.  `<rocommunity>` is the
  read-only community; `<rwcommunity>` is documented but the
  OPNsense docs warn against its use.
- SNMPv3 USM is conspicuously absent from `config.xml`.  The
  OPNsense codec capability matrix lists `/snmp/v3-user` as
  unsupported with rationale: "OPNsense's SNMPv3 user store lives in
  the bsnmpd / net-snmp plugin's own configuration format
  (`/usr/local/etc/snmpd.conf` createUser lines), not in the
  config.xml this codec reads."
- The opnsense codec also declares `unsupported_rename_categories =
  frozenset({"snmpv3"})` so the rename pane suppresses v3-user
  rename collection on this codec.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Management and Configuration Guide —
SNMP](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
snmp-server community "public" Operator
snmp-server location "Synthetic-Lab Rack 7"
snmp-server contact "netops@example.invalid"
snmp-server host 10.0.10.200

snmpv3 user "monitor-usr" auth sha "..." priv aes "..."
snmpv3 group "auth-priv-grp" user "monitor-usr" sec-model ver3
```

Aruba SNMP notes:

- v1/v2c communities tagged `Operator` (read-only) or `Manager`
  (read-write).
- v3 USM users in `snmpv3 user` plus `snmpv3 group` lines.

## Cross-vendor mapping

Canonical fields (`CanonicalSNMP`):

```
community, location, contact,
trap_hosts: list[str],
v3_users: list[CanonicalSNMPv3User]
```

OPNsense -> Aruba:

- `snmp.community`: **good** — `<rocommunity>` ↔ Aruba
  `snmp-server community "X" Operator`.  Read-only is the assumed
  default (OPNsense's `<rwcommunity>` is rare; canonical doesn't
  carry an RO/RW discriminator).
- `snmp.location` / `snmp.contact`: **good** — direct mapping to
  `snmp-server location` / `snmp-server contact` quoted strings.
- `snmp.trap_hosts`: **good** — `<traphost>` ↔ `snmp-server host
  <addr>`.
- `snmp.v3_users`: **not_applicable** — OPNsense source never
  populates the canonical list (parse path declares the path
  unsupported; the rename pane shows the unsupported-category
  banner).  Aruba target would happily render `snmpv3 user` lines
  if the list were populated, but on this direction there is
  nothing to render.
