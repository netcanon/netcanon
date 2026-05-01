# SNMP: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: Cisco IOS XE Network Management Configuration Guide — SNMP.

```
snmp-server community READONLY ro
snmp-server location "Building 1, Floor 2"
snmp-server contact noc@example.com
snmp-server host 10.0.0.250 version 2c READONLY
snmp-server user admin AUTH_GROUP v3 auth sha SECRETPASS priv aes 128 PRIVPASS
```

Cisco supports v1 / v2c (community-string) and v3 (USM) on the same
device.  v3 user grammar lives on a single ``snmp-server user`` line
with auth + priv tokens.  The Cisco codec parses both surfaces (per
its capability matrix entries for ``/snmp/community`` and
``/snmp/v3-user``).

## OPNsense

Source: [OPNsense Net-SNMP plugin reference (development docs)](https://docs.opnsense.org/development/api/plugins/netsnmp.html)
Retrieved: 2026-04-30

OPNsense's SNMP service is a separately-installable plugin
(``os-net-snmp``).  Its configuration lives partly in
``config.xml`` ``<snmpd>``:

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

For SNMPv3, OPNsense's docs describe a UserController API endpoint
("UserController — Manages SNMPv3 users with commands for adding,
deleting, and configuring individual users") but the actual v3 user
records live in the ``net-snmp`` daemon's own ``createUser`` lines
in ``/usr/local/etc/snmpd.conf``, NOT in ``config.xml``.  See the
OPNsense codec's capability matrix entry for ``/snmp/v3-user``:
"OPNsense's SNMPv3 user store lives in the bsnmpd / net-snmp
plugin's own configuration format... not in the config.xml this
codec reads."

## Cross-vendor mapping

Canonical fields (see ``CanonicalSNMP``):

```
community: str
location: str
contact: str
trap_hosts: list[str]
v3_users: list[CanonicalSNMPv3User]
```

Cisco -> OPNsense:

- ``community``: **good** — direct mapping to ``<rocommunity>``.
  Cisco's ``ro`` / ``rw`` distinction is lost (OPNsense splits into
  ``<rocommunity>`` + ``<rwcommunity>`` but the canonical model is
  community-string-only with no R/W flag).
- ``location``: **good** — Cisco ``snmp-server location`` ↔ OPNsense
  ``<syslocation>``.
- ``contact``: **good** — Cisco ``snmp-server contact`` ↔ OPNsense
  ``<syscontact>``.
- ``trap_hosts``: **good** — Cisco ``snmp-server host`` ↔ OPNsense
  ``<traphost>``.
- ``v3_users``: **unsupported** — OPNsense's ``config.xml`` does not
  carry SNMPv3 user records; the data lives in the daemon's
  ``snmpd.conf``.  The codec advertises ``/snmp/v3-user`` as
  unsupported on OPNsense.  Cross-pair drops v3 users entirely; the
  cross-mesh pane-compat banner surfaces this via the
  ``unsupported_rename_categories: {"snmpv3"}`` declaration on the
  OPNsense codec.

Disposition: v1/v2c surface **good**; v3 USM surface **unsupported**.
Operators must reconfigure SNMPv3 directly via the OPNsense
plugin's GUI or the ``snmpd.conf`` file after migration.
