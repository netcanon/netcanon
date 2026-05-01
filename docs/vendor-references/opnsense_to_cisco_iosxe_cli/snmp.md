# SNMP: OPNsense versus Cisco IOS-XE

## OPNsense

Source: [OPNsense Net-SNMP plugin reference (development docs)](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-04-30

OPNsense's SNMP service is a separately-installable plugin
(``os-net-snmp``).  Configuration in ``config.xml`` ``<snmpd>``:

```xml
<opnsense>
  <snmpd>
    <rocommunity>public</rocommunity>
    <syslocation>Datacenter A</syslocation>
    <syscontact>noc@example.com</syscontact>
    <traphost>10.0.0.250</traphost>
  </snmpd>
</opnsense>
```

The OPNsense codec parses these into ``CanonicalSNMP`` (per
``parse.py``).  SNMPv3 USM users are NOT in ``config.xml`` — they
live in the daemon's ``snmpd.conf`` ``createUser`` lines (per the
codec's ``/snmp/v3-user`` unsupported entry).

## Cisco IOS-XE

```
snmp-server community public RO
snmp-server location Datacenter A
snmp-server contact noc@example.com
snmp-server host 10.0.0.250 version 2c public
snmp-server user admin AUTH_GROUP v3 auth sha SECRETPASS priv aes 128 PRIVPASS
```

## Cross-vendor mapping

Canonical fields (see ``CanonicalSNMP``):

```
community, location, contact, trap_hosts, v3_users
```

OPNsense -> Cisco:

- ``community``: **good** — direct mapping.  OPNsense's separate
  ``<rocommunity>`` / ``<rwcommunity>`` collapses to the canonical
  single-community model.
- ``location``: **good** — OPNsense ``<syslocation>`` ↔ Cisco
  ``snmp-server location``.
- ``contact``: **good** — OPNsense ``<syscontact>`` ↔ Cisco
  ``snmp-server contact``.
- ``trap_hosts``: **good** — both vendors model a list.
- ``v3_users``: **not_applicable** — OPNsense never populates this
  list (no SNMPv3 in ``config.xml``).  No data to migrate.

Disposition: v1/v2c surface is **good**; v3 surface is
**not_applicable** from an OPNsense source (the data isn't in
config.xml so nothing to translate).
