# RADIUS / AAA: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS

Source: [RADIUS Client — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/13402205/RADIUS)
Retrieved: 2026-04-30

```
/radius
add address=10.0.0.10 secret=fake-radius-shared-secret-1 \
    service=login authentication-port=1812 accounting-port=1813
add address=10.0.0.11 secret=fake-radius-shared-secret-2 \
    service=login,dhcp authentication-port=1645 accounting-port=1646
```

RouterOS uses `/radius add address=X secret=Y service=<list>`.
Service binding (`service=login,ppp,hotspot,wireless,dhcp,ipsec`)
controls which RouterOS subsystems may consult this RADIUS row.

AAA policy lives elsewhere — RouterOS does not have Cisco-style
method lists; each service that accepts RADIUS authentication has
its own enable flag (e.g. `/user aaa set use-radius=yes`).

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for
2930F / 2930M / 3810 / 5400R — RADIUS chapter](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
radius-server host 10.0.0.10 key "fakeRadiusSecret-A"
radius-server host 10.0.0.11 key "fakeRadiusSecret-B"
aaa authentication ssh login radius local
```

Aruba uses a flat `radius-server host <addr> key "<secret>"` form,
one line per server.  Optional auth-port / acct-port modifiers
default to 1812 / 1813.  Authentication method-list selection lives
on `aaa authentication` directives keyed by login type.

## Cross-vendor mapping

The canonical surface is

```
CanonicalRADIUSServer(host, key, auth_port, acct_port)
```

Host / key / auth_port / acct_port round-trip cleanly.

### Lossy bits

- **Service binding** — RouterOS source carries `service=login,ppp,
  hotspot,wireless,dhcp,ipsec`.  Aruba target only models login
  authentication; RouterOS-only services (`ppp` / `wireless` /
  `hotspot` / `dhcp` / `ipsec`) drop with a banner.  Aruba target
  render emits an `aaa authentication ssh login radius local`
  default.
- **Method-list policy** — RouterOS's per-service enable-flag
  model versus Aruba's method-list model is not modelled
  canonically.  Cross-vendor render emits sensible defaults; the
  operator may need to fine-tune.
- **Shared secret encoding** — Both codecs pass through verbatim.
  The receiving Aruba side accepts the secret as a quoted string;
  RouterOS-side bare or quoted forms both lift cleanly.

### Disposition

| Field | Disposition |
|---|---|
| `radius_servers[].host` | good |
| `radius_servers[].key` | good (verbatim pass-through) |
| `radius_servers[].auth_port` | good |
| `radius_servers[].acct_port` | good |
| Service binding | lossy (RouterOS-rich; Aruba defaults) |
| Method-list policy | unsupported (canonical schema gap) |
