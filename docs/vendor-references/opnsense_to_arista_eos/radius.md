# RADIUS: OPNsense versus Arista EOS

## OPNsense

Source: [OPNsense Users manual — Authentication servers](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-04-30

```xml
<opnsense>
  <system>
    <authserver>
      <type>radius</type>
      <name>RADIUS-1</name>
      <host>10.0.20.10</host>
      <radius_secret>fakeRadiusSecret-A</radius_secret>
      <radius_auth_port>1812</radius_auth_port>
      <radius_acct_port>1813</radius_acct_port>
      <radius_protocol>PAP</radius_protocol>
      <radius_timeout>5</radius_timeout>
    </authserver>
  </system>
</opnsense>
```

- Each `<authserver>` block is one server.
- `<host>` / `<radius_secret>` / `<radius_auth_port>` /
  `<radius_acct_port>` are the cross-vendor-stable fields.
- Protocol (PAP / CHAP / MS-CHAP) and timeout / retry fields are
  OPNsense-specific.

## Arista EOS

Source: [Arista EOS User Manual — User Security (RADIUS)](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

```
radius-server host 10.0.20.10 key fakeRadiusSecret-A
radius-server host 10.0.20.10 auth-port 1812 acct-port 1813
```

- Flat `radius-server host <ip>` form.
- Default ports 1812 / 1813.

## Cross-vendor mapping (OPNsense -> Arista EOS)

- `radius_servers`: **good** — OPNsense `<authserver>` ↔ Arista
  `radius-server host`.  Round-trips host / port pair / shared
  key cleanly.  OPNsense's per-server protocol / timeout /
  retransmit fields drop on render (no canonical model).
