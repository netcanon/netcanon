# SNMP: OPNsense versus FortiGate FortiOS

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/snmp.md`.

## OPNsense

Source: [OPNsense Net-SNMP plugin
reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-05-01

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

OPNsense notes:

- v1/v2c surface: `<rocommunity>` (read-only) — read-write
  `<rwcommunity>` is rare in production.
- `<traphost>` carries trap receivers; some plugin versions support
  multiple elements.
- SNMPv3 USM is **NOT** in `config.xml`.  OPNsense's v3 user store
  lives in the bsnmpd / net-snmp plugin's own
  `/usr/local/etc/snmpd.conf` createUser lines, outside the
  canonical surface.  The OPNsense codec capability matrix lists
  `/snmp/v3-user` as `unsupported` with this rationale.
- Therefore, OPNsense source NEVER populates `CanonicalSNMP.v3_users` —
  the cross-pair v3 disposition is `not_applicable` (source absent),
  not `unsupported` (which would mean target absent).

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/snmp.md` for the FortiGate-side
shape.  Key points:

- v1/v2c via `config system snmp community` edit-table; multiple
  communities supported but canonical takes only the first.
- v3 USM via `config system snmp user` edit-table with auth/priv
  protocols and `ENC <opaque-base64>` passphrases.
- FortiGate `<hosts>` sub-table per community carries trap receivers.

## Cross-vendor mapping (OPNsense -> FortiGate)

- `snmp.community`: **good** — OPNsense `<rocommunity>` ↔ FortiGate
  `set name "..."` (community edit).  OPNsense's optional
  `<rwcommunity>` collapses to read-only on canonical.
- `snmp.location`: **good** — `<syslocation>` ↔ FortiGate
  `set description "..."` (sysinfo).  Note FortiOS labels the field
  `description` while OPNsense uses `syslocation`.
- `snmp.contact`: **good** — `<syscontact>` ↔ FortiGate
  `set contact-info "..."`.
- `snmp.trap_hosts`: **good** — OPNsense `<traphost>` elements ↔
  FortiGate per-community `<hosts>` edit-table.
- `snmp.v3_users`: **not_applicable** — OPNsense source never
  populates `v3_users` (capability matrix declares `/snmp/v3-user`
  unsupported because OPNsense's v3 store lives outside config.xml).
  FortiGate target accepts v3 users but nothing to render.  The
  rename pane shows the OPNsense-side `snmpv3` unsupported-category
  banner declared on the OPNsense codec's
  `unsupported_rename_categories` frozenset — useful to surface the
  gap in the inverse direction (when FortiGate is target).
- Note the asymmetry from the forward direction: forward FortiGate ->
  OPNsense, v3_users is **unsupported** (target absent / can't render);
  reverse OPNsense -> FortiGate, v3_users is **not_applicable**
  (source absent / nothing to lose).
