# SNMP: OPNsense versus MikroTik RouterOS

## OPNsense

Source: [OPNsense Net-SNMP plugin development reference](https://docs.opnsense.org/development/api/plugins/netsnmp.html)

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

OPNsense ``config.xml`` carries v1/v2c surface inside ``<snmpd>``:
``<rocommunity>``, ``<syslocation>``, ``<syscontact>``, multiple
``<traphost>`` elements.  Trap hosts support multiple destinations.

**SNMPv3 USM is NOT modelled in ``config.xml``.**  OPNsense's bsnmpd
/ net-snmp plugin reads SNMPv3 user definitions from
``/usr/local/etc/snmpd.conf`` (``createUser`` lines) which is
outside the scope of ``config.xml`` and outside the canonical scope
of the OPNsense codec.  ``CanonicalSNMP.v3_users`` is always empty
from an OPNsense source.

## MikroTik RouterOS

Source: [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)

Retrieved: 2026-04-30

```
/snmp
set enabled=yes contact="noc@example.net" \
    location="Synthetic Lab Rack 7" trap-target=10.0.0.250

/snmp community
set [ find default=yes ] name=kitchensink-ro
```

RouterOS overloads ``/snmp community`` for v1/v2c + v3.  Trap
targets are SINGLE-target (``trap-target=``); RouterOS does NOT
support multiple trap destinations.  Auth protocols (when v3 USM is
populated) are MD5 / SHA1 only; encryption is DES / AES (= AES-128).

## Cross-vendor mapping

Canonical surface:

```
CanonicalSNMP(community, location, contact, trap_hosts[], v3_users[])
CanonicalSNMPv3User(name, group, auth_protocol, auth_passphrase,
                    priv_protocol, priv_passphrase, engine_id)
```

### v1/v2c (community / location / contact)

OPNsense ``<rocommunity>`` / ``<syslocation>`` / ``<syscontact>`` ↔
RouterOS ``/snmp set contact=`` / ``location=`` / ``/snmp community
set [ find default=yes ] name=``.  Round-trips cleanly.

### Trap hosts

OPNsense supports multiple ``<traphost>`` elements; RouterOS supports
only ONE ``trap-target=``.  Multi-target OPNsense source -> RouterOS
target drops to the first trap host with a banner; the rest land in
``raw_sections`` for operator review.  This is the lossy direction
of the trap-host asymmetry (the inverse direction is good).

### v3 USM users

OPNsense has NO place in ``config.xml`` to declare v3 users — they
live in the Net-SNMP plugin's ``snmpd.conf``.  ``v3_users`` is
always empty from an OPNsense source; the cross-pair has nothing to
migrate.  RouterOS target codec CAN render v3 users when the
canonical list is populated; just not from this source.

### Disposition

| Field | Disposition |
|---|---|
| `snmp.community` | good |
| `snmp.location` | good |
| `snmp.contact` | good |
| `snmp.trap_hosts` | lossy (RouterOS single-target — multi-host OPNsense source drops extras) |
| `snmp.v3_users` | not_applicable (OPNsense never populates v3 from config.xml) |
