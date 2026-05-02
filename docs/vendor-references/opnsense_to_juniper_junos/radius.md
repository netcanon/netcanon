# RADIUS: OPNsense versus Junos

## OPNsense

Source: [OPNsense Users manual (Authentication servers)](https://docs.opnsense.org/manual/users.html)
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

OPNsense RADIUS notes:

- `<authserver>` block under `<system>`; `<type>radius</type>`
  discriminates from LDAP / other auth backends.
- `<radius_secret>` is plaintext in `config.xml` (file is treated
  as confidential at the OS level, not field-encrypted).
- Each authserver carries a `<refid>` and a `<name>`.

## Junos

Source: [Junos radius-server statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html)
Retrieved: 2026-05-01

```
set system radius-server 10.0.0.200 secret "$9$fakeRadiusSecret$1"
set system radius-server 10.0.0.200 port 1812
set system radius-server 10.0.0.200 accounting-port 1813
```

Junos RADIUS notes:

- Server-keyed by IP address: `set system radius-server <addr>`.
- Shared secret stored as `$9$...` Junos-encrypted blob.
- Auth port (`port`) and accounting port (`accounting-port`)
  default to 1812 / 1813.

## Cross-vendor mapping

OPNsense -> Junos:

- `radius_servers[].host`: **good** — OPNsense `<host>` ↔ Junos
  IP-keyed server.  Round-trip preserves the address.
- `radius_servers[].auth_port`: **good** — both default to 1812;
  explicit overrides round-trip.
- `radius_servers[].acct_port`: **good** — both default to 1813.
- `radius_servers[].key`: **lossy** — OPNsense's plaintext
  `<radius_secret>` lands verbatim in Junos's `secret` field.
  Junos accepts plaintext secrets on input and encrypts them at
  config-commit time (the `$9$...` form appears on subsequent
  reads).  Functionally the cross-pair WORKS as long as the source
  was plaintext — operator may want to re-encrypt for hygiene
  but authentication will succeed.

Disposition: **good** for host / port pair; **lossy** scope due
to OPNsense's plaintext secret crossing to Junos's
expected-encrypted format (auto-encryption on commit closes the
gap functionally but the hash differs from the source).
