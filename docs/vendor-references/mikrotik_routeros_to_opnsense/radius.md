# RADIUS / AAA: MikroTik RouterOS versus OPNsense

## MikroTik RouterOS

Source: [RADIUS Client — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS)

Retrieved: 2026-04-30

```
/radius
add address=10.0.0.10 secret=fake-radius-shared-secret-1 service=login \
    authentication-port=1812 accounting-port=1813
add address=10.0.0.11 secret=fake-radius-shared-secret-2 service=login,dhcp \
    authentication-port=1645 accounting-port=1646
```

RouterOS ``/radius`` carries flat per-server records with
``address=`` (host), ``secret=`` (shared key), ``authentication-port=``
and ``accounting-port=`` defaults.  The ``service=`` parameter binds
the server to one or more service categories: ``login``, ``ppp``,
``hotspot``, ``wireless``, ``dhcp``, ``ipsec`` — each is a
RouterOS-internal flag indicating which subsystems consult this
RADIUS server.

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
back-ends (LDAP, local DB) inside ``<system>/<authserver>``.  Each
``<authserver>`` carries a discriminator ``<type>radius</type>``.
The shared secret lives in ``<radius_secret>``; ``<radius_auth_port>``
and ``<radius_acct_port>`` default to 1812 / 1813.  ``<radius_protocol>``
defaults to ``PAP`` (other options: ``CHAP``, ``MSCHAPv1``,
``MSCHAPv2``).

OPNsense uses RADIUS for GUI / SSH login authentication primarily;
the firewall plumbing references the authserver by ``<refid>``.

## Cross-vendor mapping

Canonical surface:

```
CanonicalRADIUSServer(host, key, auth_port, acct_port)
```

### host / key / auth_port / acct_port

Round-trip cleanly:

- RouterOS ``address=10.0.0.10`` ↔ OPNsense ``<host>10.0.0.10</host>``
- RouterOS ``secret=...`` ↔ OPNsense ``<radius_secret>...
  </radius_secret>``
- RouterOS ``authentication-port=1812`` ↔ OPNsense
  ``<radius_auth_port>1812</radius_auth_port>``
- RouterOS ``accounting-port=1813`` ↔ OPNsense
  ``<radius_acct_port>1813</radius_acct_port>``

Both vendors pass the shared secret through verbatim — neither encodes
or obfuscates on the wire.

### service / method-list

RouterOS ``service=login,ppp,wireless,hotspot,dhcp,ipsec`` is a
RouterOS-internal binding that has no canonical model.  OPNsense
references RADIUS servers via ``<refid>`` from individual subsystems
(GUI auth, SSH auth, captive portal, etc.) and there is no flat
"this server is used for X" list.  Cross-vendor render emits the
``<authserver>`` block but the operator must wire it into the
target subsystems manually post-migration.

### radius_protocol / radius_timeout

OPNsense's ``<radius_protocol>`` (PAP/CHAP/MSCHAP) and ``<radius_timeout>``
have no RouterOS source counterpart (RouterOS uses PAP by default and
exposes timeout via separate ``timeout=`` attribute, not in the
canonical model); render emits OPNsense defaults.

### Disposition

| Field | Disposition |
|---|---|
| `radius_servers[].host` | good |
| `radius_servers[].key` | good (verbatim shared-secret pass-through) |
| `radius_servers[].auth_port` | good |
| `radius_servers[].acct_port` | good |
