# SNMP: OPNsense versus Junos

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
- `<rocommunity>` carries the read-only community string;
  `<rwcommunity>` exists but is rarely used.
- `<syslocation>` / `<syscontact>` mirror standard MIB scalars.
- `<traphost>` is repeated for multiple trap receivers.
- **v3 USM is NOT in `config.xml`** — the OPNsense bsnmpd /
  net-snmp plugin stores v3 user definitions in
  `/usr/local/etc/snmpd.conf` (`createUser` lines).  The OPNsense
  codec capability matrix lists `/snmp/v3-user` as `unsupported`.

## Junos

Source: [Junos SNMP overview](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/concept/snmp-overview.html)
Source: [Junos SNMPv3 configuration topic-map](https://www.juniper.net/documentation/us/en/software/junos/network-mgmt/topics/topic-map/snmpv3-configuration.html)
Retrieved: 2026-05-01

```
set snmp community public authorization read-only
set snmp location "Lab Rack 7"
set snmp contact "noc@example.net"
set snmp trap-group monitoring targets 10.0.0.250

set snmp v3 usm local-engine user monitor authentication-md5 authentication-key "$9$..."
set snmp v3 vacm security-to-group security-model usm security-name monitor group netadmin
```

Junos SNMP notes:

- v1/v2c communities under `set snmp community NAME authorization
  read-only|read-write`.
- Trap targets grouped — `set snmp trap-group <name> targets <ip>`
  flattens to canonical `trap_hosts: list[str]`.
- v3 USM splits across THREE hierarchies (usm local-engine + vacm
  security-to-group + vacm access).
- v3 keys stored as `$9$...` reversibly-encrypted blobs.

## Cross-vendor mapping

OPNsense -> Junos:

- `snmp.community`: **good** — OPNsense `<rocommunity>` ↔ Junos `set
  snmp community NAME authorization read-only`.
- `snmp.location`: **good** — OPNsense `<syslocation>` ↔ Junos
  `location`.
- `snmp.contact`: **good** — OPNsense `<syscontact>` ↔ Junos
  `contact`.
- `snmp.trap_hosts`: **good** — OPNsense `<traphost>` list ↔ Junos
  `set snmp trap-group monitoring targets <ip>`.  Junos requires
  a trap-group name; codec render synthesises a default name.
- `snmp.v3_users`: **not_applicable** — OPNsense source never
  populates v3 USM users (they live in plugin's `snmpd.conf`,
  outside the canonical wire format).  Junos target supports v3
  USM but receives nothing to render.

Disposition: v1/v2c surface **good**; v3 USM **not_applicable** on
this direction (the loss is on the SOURCE side, not the target —
no v3 USM ever reaches canonical from OPNsense).
