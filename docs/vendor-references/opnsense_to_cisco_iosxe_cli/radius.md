# RADIUS server configuration: OPNsense versus Cisco IOS-XE

## OPNsense

Source: [OPNsense Users (Authentication Servers section)](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-04-30

OPNsense RADIUS via ``<authserver>`` in ``<system>``:

```xml
<opnsense>
  <system>
    <authserver>
      <type>radius</type>
      <name>CORP-RADIUS</name>
      <host>10.0.0.10</host>
      <radius_secret>SHARED_SECRET</radius_secret>
      <radius_auth_port>1812</radius_auth_port>
      <radius_acct_port>1813</radius_acct_port>
      <radius_protocol>MSCHAPv2</radius_protocol>
      <radius_timeout>5</radius_timeout>
    </authserver>
    <authserver>
      <type>ldap</type>
      <name>CORP-LDAP</name>
      <!-- ... ignored by RADIUS parser ... -->
    </authserver>
  </system>
</opnsense>
```

The OPNsense codec parses ``<authserver>`` records WHOSE
``<type>`` IS ``radius`` into ``CanonicalRADIUSServer`` records;
``ldap`` and ``local`` types are skipped (per ``parse.py``).

## Cisco IOS-XE

Modern named-server form:

```
radius server CORP-RADIUS
 address ipv4 10.0.0.10 auth-port 1812 acct-port 1813
 key 7 0822455D0A16
!
```

## Cross-vendor mapping

Canonical fields (see ``CanonicalRADIUSServer``):

```
host, key, auth_port, acct_port
```

OPNsense -> Cisco:

- ``host``: **good** — direct mapping.
- ``key``: **good** — OPNsense ``<radius_secret>`` is plaintext
  (typically); Cisco render emits it as ``key 0 <secret>`` (type-0,
  unencrypted at-rest unless ``service password-encryption`` is on).
  The cross-pair preserves the secret losslessly.
- ``auth_port`` / ``acct_port``: **good** — both vendors model both
  ports.

OPNsense's RADIUS protocol selection (``<radius_protocol>MSCHAPv2``)
and timeout (``<radius_timeout>``) are not modelled in the canonical
schema; Cisco's defaults apply post-migration.

Disposition: **good** for the cross-vendor-stable host / key / port
surface.
