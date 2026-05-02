# RADIUS: Junos versus OPNsense

## Junos

Source: [Junos radius-server statement reference](https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html)
Retrieved: 2026-05-01

```
set system radius-server 10.0.0.200 secret "$9$fakeRadiusSecret$1"
set system radius-server 10.0.0.200 port 1812
set system radius-server 10.0.0.200 accounting-port 1813
set system radius-server 10.0.0.201 port 1812 secret "$9$fakeRadiusSecret$2"
```

Junos RADIUS notes:

- Server-keyed by IP address: `set system radius-server <addr>`.
- Shared secret stored as `$9$...` Junos-encrypted blob (reversible
  encryption with vendor-specific salt).
- Auth port (`port`) and accounting port (`accounting-port`)
  default to RFC standards (1812 / 1813) when omitted.
- Multiple servers are independent stanzas — Junos consults them in
  configuration order.

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
- Each authserver carries a `<refid>` for cross-references and a
  `<name>` for operator display.

## Cross-vendor mapping

Junos -> OPNsense:

- `radius_servers[].host`: **good** — Junos IP-keyed server ↔
  OPNsense `<host>`.  Round-trip preserves the address.
- `radius_servers[].auth_port`: **good** — both default to 1812;
  explicit overrides round-trip.
- `radius_servers[].acct_port`: **good** — both default to 1813.
- `radius_servers[].key`: **lossy** — Junos's `$9$...` reversibly-
  encrypted secret will land verbatim in OPNsense `<radius_secret>`,
  but the decryption is JUNOS-SPECIFIC.  OPNsense will treat the
  `$9$...` blob as a literal string when authenticating, which fails
  against the RADIUS server.  Operator MUST reset the shared secret
  on the OPNsense target after migration.

Disposition: **good** for host / port pair; **lossy** scope due to
shared-secret encryption format mismatch.  Documented as a caveat
on the validation report.
