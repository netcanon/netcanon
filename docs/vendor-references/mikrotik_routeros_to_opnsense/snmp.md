# SNMP: MikroTik RouterOS versus OPNsense

## MikroTik RouterOS

Source: [SNMP — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP)

Retrieved: 2026-04-30

```
/snmp
set enabled=yes contact="noc@example.net" location="Synthetic Lab Rack 7" \
    trap-target=10.0.0.250

/snmp community
set [ find default=yes ] name=public
add name=write-rw security=none read-access=yes write-access=yes
add name=monitor-v3 authentication-protocol=SHA1 \
    authentication-password="fake-auth-passphrase-1" \
    encryption-protocol=AES \
    encryption-password="fake-priv-passphrase-1"
```

RouterOS overloads the ``/snmp community`` section to carry BOTH
v1/v2c communities and v3 USM users — disambiguated by the presence
of crypto knobs (``authentication-protocol=`` indicates a v3 user).
``security=none|authorized|private`` encodes the v3 securityLevel.
Auth protocols are MD5 / SHA1 only (no SHA-2 family).  Encryption
options are DES and AES (= AES-128); RouterOS does not implement
AES-192 / AES-256 / 3DES.  Trap targets are SINGLE-target
(``trap-target=``).

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
``<rocommunity>`` (read-only community), ``<syslocation>``,
``<syscontact>``, multiple ``<traphost>`` elements.  Trap hosts
support multiple destinations (unlike RouterOS).

**SNMPv3 USM is NOT modelled in ``config.xml``.**  OPNsense's bsnmpd
/ net-snmp plugin reads SNMPv3 user definitions from
``/usr/local/etc/snmpd.conf`` (``createUser`` lines) which is
outside the scope of ``config.xml`` and outside the canonical scope
of the OPNsense codec.  The codec lists ``/snmp/v3-user`` as
unsupported and ``unsupported_rename_categories`` includes
``"snmpv3"`` so the rename UI banners the gap before operators
commit overrides that won't render.

## Cross-vendor mapping

Canonical surface:

```
CanonicalSNMP(community, location, contact, trap_hosts[], v3_users[])
CanonicalSNMPv3User(name, group, auth_protocol, auth_passphrase,
                    priv_protocol, priv_passphrase, engine_id)
```

### v1/v2c (community / location / contact)

RouterOS ``/snmp set contact=`` / ``location=`` and ``/snmp community
set [ find default=yes ] name=`` map to OPNsense ``<syscontact>`` /
``<syslocation>`` / ``<rocommunity>``.  Round-trips cleanly.  Multiple
RouterOS communities collapse to the single primary community on
canonical (CanonicalSNMP carries one ``community`` scalar).

### Trap hosts

RouterOS ``trap-target=`` is single-valued; OPNsense supports
multiple ``<traphost>`` elements.  RouterOS source -> OPNsense target
emits one ``<traphost>`` and OPNsense accepts it without complaint.
The reverse direction (multiple OPNsense trap hosts -> RouterOS) is
the lossy direction.

### v3 USM users

RouterOS source carries v3 users (auth-protocol=SHA1 / MD5,
encryption-protocol=AES / DES).  OPNsense target has NO place to
write them in ``config.xml`` — render drops the v3_users list with
a banner; operator MUST recreate v3 users by editing
``/usr/local/etc/snmpd.conf`` directly on the OPNsense target.
This is documented on the OPNsense codec's ``/snmp/v3-user``
unsupported entry and surfaced via the ``snmpv3`` entry in
``unsupported_rename_categories``.

### Disposition

| Field | Disposition |
|---|---|
| `snmp.community` | good |
| `snmp.location` | good |
| `snmp.contact` | good |
| `snmp.trap_hosts` | good (RouterOS single -> OPNsense first) |
| `snmp.v3_users` | unsupported (OPNsense does not store v3 USM in config.xml) |
