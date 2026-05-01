# RADIUS: OPNsense versus Aruba AOS-S

## OPNsense

Source: [OPNsense Users manual — Authentication
servers](https://docs.opnsense.org/manual/users.html)
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
    </authserver>
  </system>
</opnsense>
```

- Each `<authserver>` block is one server.
- `<host>` / `<radius_secret>` / `<radius_auth_port>` /
  `<radius_acct_port>` are the cross-vendor-stable fields.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Access Security Guide — RADIUS](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
radius-server host 10.0.20.10 key "fakeRadiusSecret-A"
radius-server host 10.0.20.10 auth-port 1812 acct-port 1813
```

- Flat `radius-server host <ip>` form with shared key inline or via
  separate `radius-server key "<secret>"` global default.
- Default ports 1812 / 1813.

## Cross-vendor mapping

Canonical fields (`CanonicalRADIUSServer`):

```
host, key, auth_port, acct_port
```

OPNsense -> Aruba:

- `radius_servers`: **good** — `host` / `key` / `auth_port` /
  `acct_port` round-trip cleanly.  OPNsense `<radius_secret>` lands
  verbatim in Aruba's `key "<secret>"`; default ports preserved.
  Aruba's flat `radius-server host` form is functionally equivalent
  to OPNsense's per-server `<authserver>` block.
