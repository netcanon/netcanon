# RADIUS server configuration: Cisco IOS-XE versus OPNsense

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide — RADIUS.

Modern IOS-XE form (named-server style):

```
radius server CORP-RADIUS
 address ipv4 10.0.0.10 auth-port 1812 acct-port 1813
 key 7 0822455D0A16
!
aaa group server radius CORP-AAA
 server name CORP-RADIUS
!
aaa authentication login default group CORP-AAA local
```

Legacy style (still accepted on IOS-XE):

```
radius-server host 10.0.0.10 auth-port 1812 acct-port 1813 key SHARED_SECRET
```

The shared secret can be plaintext (deprecated), type 7 (Cisco's
weak reversible cipher), or unencrypted but stored encrypted via
``service password-encryption``.

## OPNsense

Source: [OPNsense Users (Authentication Servers section)](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-04-30

OPNsense models RADIUS via ``<authserver>`` records inside
``<system>``:

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
  </system>
</opnsense>
```

The OPNsense codec parses ``<authserver>`` records whose
``<type>`` is ``radius`` into ``CanonicalRADIUSServer`` records (per
its ``parse.py``); LDAP and local types are skipped.

## Cross-vendor mapping

Canonical fields (see ``CanonicalRADIUSServer``):

```
host: str
key: str
auth_port: int = 1812
acct_port: int = 1813
```

Cisco -> OPNsense:

- ``host``: **good** — direct mapping to ``<host>``.
- ``key``: **lossy** — Cisco's type-7 obfuscated keys
  (``key 7 0822455D0A16``) need decryption before the plaintext
  secret can land in OPNsense's ``<radius_secret>``.  Neither codec
  decrypts type-7 in v1; the obfuscated form lands unchanged in the
  OPNsense XML and authentication fails until the operator resets
  the secret.  A caveat in the validation report.
- ``auth_port`` / ``acct_port``: **good** — OPNsense models both
  explicitly.

Cisco's ``aaa group server`` / ``aaa authentication login`` AAA-policy
plumbing has no canonical surface; OPNsense's choice of EAP protocol
(``MSCHAPv2`` / ``PAP``) defaults to whatever the operator selects
in the GUI.

Disposition: **good** for the cross-vendor-stable surface
(host / port pair); **lossy** when the source carries type-7
obfuscated keys.
