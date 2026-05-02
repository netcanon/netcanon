# SNMP handling — Cisco NETCONF source to OPNsense target

Source: [openconfig-system YANG schema docs (SNMP)](https://openconfig.net/projects/models/schemadocs/yangdoc/openconfig-system.html)
Retrieved: 2026-05-01

Source: [Cisco-IOS-XE-snmp.yang vendor model (YangModels GitHub)](https://github.com/YangModels/yang/blob/main/vendor/cisco/xe/1651/Cisco-IOS-XE-snmp.yang)
Retrieved: 2026-05-01

Source: [OPNsense Net-SNMP plugin reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-05-01

## Source side: parse-side gap

The cisco_iosxe codec's `parse()` does not walk `<snmp>` (whether
that's the openconfig-system v1/v2c-style community list or the
Cisco-IOS-XE-snmp.yang native v3 USM tree).  `intent.snmp` is `None`
after parse — there is nothing in the canonical tree for the
OPNsense render to consume.

The codec's `CapabilityMatrix._CAPS` does declare the v1/v2c paths
under `supported`:

* `/snmp/community`
* `/snmp/location`
* `/snmp/contact`
* `/snmp/trap-host`

These declarations are aspirational (so cross-codec mesh
translations don't classify them as `unsupported`) — the parser
just doesn't read XML for them yet.

The codec's matrix EXPLICITLY declares `/snmp/v3-user` as
`unsupported` with rationale: "The NETCONF/OpenConfig codec is a
stub (Phase 0.5 experimental) — SNMPv3 USM wire-up requires the
Cisco-IOS-XE-snmp native YANG module, not covered today."  Even if
v1/v2c eventually wires up, v3 stays explicitly unsupported on this
codec until native-YANG bridging lands.

## Target side: OPNsense SNMP scope

OPNsense's SNMP plugin (Net-SNMP / bsnmpd) carries v1/v2c surface
in `<snmpd>`:

```xml
<snmpd>
  <syslocation>Rack 4 Row B</syslocation>
  <syscontact>noc@example.com</syscontact>
  <rocommunity>public</rocommunity>
  <traphost>198.51.100.50</traphost>
</snmpd>
```

The OPNsense codec maps this to canonical:

- `/snmp/community` <-> `<rocommunity>`
- `/snmp/location` <-> `<syslocation>`
- `/snmp/contact` <-> `<syscontact>`
- `/snmp/trap-host` <-> `<traphost>`

OPNsense's SNMPv3 USM users live in the Net-SNMP plugin's own
configuration format (`/usr/local/etc/snmpd.conf` `createUser`
lines), NOT in `config.xml`.  The OPNsense codec's matrix declares
`/snmp/v3-user` as `unsupported` — Tier-3 carry-through is not
wired; operators re-declare v3 users on the target after migration.

## Cross-pair disposition

| Canonical field | Disposition | Reason |
|---|---|---|
| `snmp` | not_applicable | source parser doesn't read `<snmp>`; canonical is `None` |
| `snmp.community` | not_applicable | same as parent |
| `snmp.location` | not_applicable | same as parent |
| `snmp.contact` | not_applicable | same as parent |
| `snmp.trap_hosts` | not_applicable | same as parent |
| `snmp.v3_users` | not_applicable | doubly so: source parser doesn't read AND source matrix declares `/snmp/v3-user` unsupported AND OPNsense target also declares `/snmp/v3-user` unsupported |

If parser-side v1/v2c wire-up lands on the cisco_iosxe codec, the
v1/v2c sub-fields would flip to `good` (OPNsense target wires the
full v1/v2c surface).  v3 USM stays `unsupported` from both ends
regardless.
