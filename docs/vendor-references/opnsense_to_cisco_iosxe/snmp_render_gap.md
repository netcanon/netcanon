# SNMP handling — OPNsense source to Cisco NETCONF target

Source: [OPNsense Net-SNMP plugin reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-05-01

Source: [openconfig-system YANG schema docs (SNMP)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

## OPNsense source shape

OPNsense's SNMP plugin (Net-SNMP / bsnmpd) carries the v1/v2c
surface in `<snmpd>`:

```xml
<snmpd>
  <syslocation>Rack 4 Row B</syslocation>
  <syscontact>noc@example.com</syscontact>
  <rocommunity>public</rocommunity>
  <traphost>198.51.100.50</traphost>
</snmpd>
```

The OPNsense codec maps this to canonical:

- `<rocommunity>` -> `intent.snmp.community`
- `<syslocation>` -> `intent.snmp.location`
- `<syscontact>` -> `intent.snmp.contact`
- `<traphost>` -> `intent.snmp.trap_hosts[]`

OPNsense's SNMPv3 USM users live in the Net-SNMP plugin's own
configuration format (`/usr/local/etc/snmpd.conf` `createUser`
lines), NOT in `config.xml`.  The OPNsense codec's matrix declares
`/snmp/v3-user` as `unsupported`.  `intent.snmp.v3_users` is
therefore always empty from this source.

## Cisco target render shape

The `cisco_iosxe._render_canonical()` method does NOT emit any
`<snmp>` element regardless of what the canonical tree carries in
`intent.snmp`.  The render is `<interfaces>`-only.  Even though the
matrix declares `/snmp/community`, `/snmp/location`, `/snmp/contact`,
`/snmp/trap-host` under `supported`, the rendering path doesn't act
on them.

The codec's matrix also EXPLICITLY declares `/snmp/v3-user` as
`unsupported` ("The NETCONF/OpenConfig codec is a stub (Phase 0.5
experimental) — SNMPv3 USM wire-up requires the
Cisco-IOS-XE-snmp native YANG module, not covered today.").

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `snmp` | unsupported | OPNsense source populates v1/v2c surface; target render emits no `<snmp>` element |
| `snmp.community` | unsupported | same as parent |
| `snmp.location` | unsupported | same |
| `snmp.contact` | unsupported | same |
| `snmp.trap_hosts` | unsupported | same |
| `snmp.v3_users` | not_applicable | OPNsense source never populates (data lives in plugin's snmpd.conf, not config.xml); target also unsupported by matrix declaration |

The v1/v2c sub-fields are `unsupported` rather than
`not_applicable` because the OPNsense source DOES populate the
canonical structure — the loss is solely on the target render side.
When target render-side wire-up lands, those would flip to `good`.

`v3_users` stays not_applicable from the OPNsense source side
regardless (the data is structurally absent from `config.xml`),
and `unsupported` from the cisco_iosxe matrix side regardless
(declared explicitly so).  Whichever way you read it, no v3 data
crosses this pair.
