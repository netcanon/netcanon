# RADIUS / AAA: OPNsense versus MikroTik RouterOS

## OPNsense

Source: [OPNsense Users manual — Authentication servers](https://docs.opnsense.org/manual/users.html)

Retrieved: 2026-04-30

```xml
<system>
  <authserver>
    <refid>radius-primary</refid>
    <type>radius</type>
    <name>radius-primary</name>
    <host>10.0.0.50</host>
    <radius_secret>fakeRadiusSharedSecret01</radius_secret>
    <radius_auth_port>1812</radius_auth_port>
    <radius_acct_port>1813</radius_acct_port>
    <radius_timeout>5</radius_timeout>
    <radius_protocol>PAP</radius_protocol>
  </authserver>
</system>
```

OPNsense stores RADIUS configuration alongside other authentication
back-ends inside ``<system>/<authserver>``.  Each ``<authserver>``
carries ``<type>radius</type>``.

## MikroTik RouterOS

Source: [RADIUS Client — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS)

Retrieved: 2026-04-30

```
/radius
add address=10.0.0.50 secret=fakeRadiusSharedSecret01 service=login \
    authentication-port=1812 accounting-port=1813
```

RouterOS ``/radius`` carries flat per-server records.

## Cross-vendor mapping

Canonical surface:

```
CanonicalRADIUSServer(host, key, auth_port, acct_port)
```

### host / key / auth_port / acct_port

Round-trip cleanly:

- OPNsense ``<host>10.0.0.50</host>`` ↔ RouterOS ``address=10.0.0.50``
- OPNsense ``<radius_secret>...</radius_secret>`` ↔ RouterOS
  ``secret=...``
- OPNsense ``<radius_auth_port>1812</radius_auth_port>`` ↔ RouterOS
  ``authentication-port=1812``
- OPNsense ``<radius_acct_port>1813</radius_acct_port>`` ↔ RouterOS
  ``accounting-port=1813``

### service binding

RouterOS's ``service=login,ppp,wireless,hotspot,dhcp,ipsec`` is a
RouterOS-internal flag set indicating which subsystems consult this
server.  OPNsense source has no equivalent — RADIUS servers are
referenced via ``<refid>`` from individual subsystems.  Cross-pair
render to RouterOS defaults to ``service=login`` with a banner;
operator must adjust manually if other services need RADIUS.

### radius_protocol / radius_timeout

OPNsense's ``<radius_protocol>`` (PAP / CHAP / MSCHAPv1 / MSCHAPv2)
and ``<radius_timeout>`` are not modelled canonically.  RouterOS
uses PAP by default; cross-pair drops the protocol setting on
render.

### Disposition

| Field | Disposition |
|---|---|
| `radius_servers[].host` | good |
| `radius_servers[].key` | good (verbatim shared-secret pass-through) |
| `radius_servers[].auth_port` | good |
| `radius_servers[].acct_port` | good |
