# RADIUS: Aruba AOS-S versus OPNsense

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Access Security Guide — RADIUS](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
radius-server host 10.0.20.10 key "fakeRadiusSecret-A"
radius-server host 10.0.20.11 key "fakeRadiusSecret-B"
radius-server host 10.0.20.10 auth-port 1812 acct-port 1813
```

- Flat `radius-server host <ip>` form with the shared key inline or
  via a separate `radius-server key "<secret>"` global default.
- Default ports 1812 (auth) / 1813 (acct).  Override with
  `auth-port` / `acct-port` keywords.
- The canonical `CanonicalRADIUSServer` carries `host`, `key`,
  `auth_port`, `acct_port` — round-trips cleanly.

## OPNsense

Source: [OPNsense Users manual — Authentication
servers](https://docs.opnsense.org/manual/users.html)
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
- Protocol (PAP / CHAP / MS-CHAP) and timeout/retry fields are
  OPNsense-specific and not modelled on canonical.

## Cross-vendor mapping

Canonical fields (`CanonicalRADIUSServer`):

```
host: str
key: str
auth_port: int = 1812
acct_port: int = 1813
```

Aruba -> OPNsense:

- `radius_servers`: **good** — host / key / port pair round-trip
  cleanly via the canonical `host`, `key`, `auth_port`, `acct_port`
  tuple.  Aruba's quoted shared secret lands verbatim in
  `<radius_secret>`; default ports preserved.  Aruba's optional
  per-server `radius-server retransmit` / `timeout` directives do
  not map to canonical (no canonical retry / timeout fields) and
  drop on render.
