# RADIUS: Arista EOS versus OPNsense

## Arista EOS

Source: [Arista EOS User Manual — User Security (RADIUS)](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

```
radius-server host 10.0.20.10 key fakeRadiusSecret-A
radius-server host 10.0.20.10 auth-port 1812 acct-port 1813
radius-server host 10.0.20.11 key fakeRadiusSecret-B
```

- Flat `radius-server host <ip>` form with the shared key inline
  (`key <secret>`) or via separate `radius-server key <secret>`
  global default.
- Default ports 1812 (auth) / 1813 (acct).  Override with
  `auth-port` / `acct-port` keywords.
- Optional `timeout <sec>` and `retransmit <N>` per-server
  modifiers; canonical lacks fields for these.

## OPNsense

Source: [OPNsense Users manual — Authentication servers](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-04-30

OPNsense models RADIUS as an `<authserver>` block in `<system>`:

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

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields (`CanonicalRADIUSServer`):

```
host: str
key: str
auth_port: int = 1812
acct_port: int = 1813
```

- `radius_servers`: **good** — Arista `radius-server host <ip>
  key <secret>` ↔ OPNsense `<authserver>` with
  `<host>` / `<radius_secret>` / `<radius_auth_port>` /
  `<radius_acct_port>`.  Round-trips host / port pair / secret
  cleanly with default ports 1812 / 1813.  Arista's optional
  `timeout` / `retransmit` per-server directives have no
  canonical model and drop on render.
