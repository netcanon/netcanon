# RADIUS / AAA: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for
2930F / 2930M / 3810 / 5400R — RADIUS chapter](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
radius-server host 10.0.20.10 key "fakeRadiusSecret-A"
radius-server host 10.0.20.11 key "fakeRadiusSecret-B"
aaa authentication login privilege-mode
aaa authentication ssh login radius local
```

Aruba uses a flat `radius-server host <addr> key "<secret>"` form,
one line per server.  Optional auth-port / acct-port modifiers
default to 1812 / 1813.  Authentication method-list selection lives
on `aaa authentication` directives keyed by login type
(`telnet`, `ssh`, `web`, `console`).

## MikroTik RouterOS

Source: [RADIUS Client — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS)
Retrieved: 2026-04-30

```
/radius
add address=10.0.20.10 secret=fake-radius-shared-secret-1 \
    service=login authentication-port=1812 accounting-port=1813
add address=10.0.20.11 secret=fake-radius-shared-secret-2 \
    service=login,dhcp authentication-port=1645 accounting-port=1646
```

RouterOS uses `/radius add address=X secret=Y service=<list>` with
service binding (`service=login`, `service=ppp`, `service=hotspot`,
`service=wireless`, `service=dhcp`, `service=ipsec`).  A single
RADIUS row is bound to one or more services (comma-separated).

AAA method-list policy lives elsewhere — RouterOS does not have
Cisco-style method lists; instead, each service that accepts RADIUS
authentication has its own enable flag (e.g. `/user aaa set
use-radius=yes`).

## Cross-vendor mapping

The canonical surface is

```
CanonicalRADIUSServer(host, key, auth_port, acct_port)
```

Host / key / auth_port / acct_port round-trip cleanly in both
directions.  The canonical schema does not model service binding
or method lists; those carry vendor-specific semantics that lossy
on cross-vendor render.

### Lossy bits

- **Service binding** — RouterOS source carries `service=login,ppp,
  hotspot,wireless,dhcp,ipsec`.  Aruba target only models
  authentication for login (`telnet` / `ssh` / `web` / `console`)
  and accounting; RouterOS-only services like `ppp` / `wireless` /
  `hotspot` drop on cross-vendor render.  Aruba source -> RouterOS
  target defaults `service=login` on render.
- **Method lists** — Aruba `aaa authentication ssh login radius
  local` (try RADIUS first, fall back to local) is not modelled
  canonically.  RouterOS render emits its default fallback
  behaviour (RADIUS first, local fallback always allowed unless
  `/user aaa set accept-aaa-from-radius-only=yes`).
- **Shared secret encoding** — Both codecs pass through verbatim.
  Aruba accepts the secret in quoted-string form; RouterOS accepts
  bare or quoted.  Cross-vendor render preserves the byte content
  so receiving-side RADIUS daemons accept the secret unchanged.

### Disposition

| Field | Disposition |
|---|---|
| `radius_servers[].host` | good |
| `radius_servers[].key` | good (verbatim pass-through) |
| `radius_servers[].auth_port` | good |
| `radius_servers[].acct_port` | good |
| Service binding | lossy (RouterOS-rich; Aruba defaults to login) |
| Method-list policy | unsupported (canonical schema gap) |
