# RADIUS: Juniper Junos versus Aruba AOS-S

How RADIUS server entries and shared secrets are declared on each
platform.

Sources:
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-radius-cli`, `aruba-radius`.

## Junos form

```
set system radius-server 10.0.0.200 secret "$9$fakeRadiusSecret$1"
set system radius-server 10.0.0.201 port 1812 secret "$9$fakeRadiusSecret$2"
set system radius-server 10.0.0.201 accounting-port 1813
```

The `secret` is typically stored as a `$9$...`-encrypted blob
(Junos's reversible Type-9 encryption).  Default ports identical
to Aruba (1812 / 1813).

## Aruba AOS-S form

```
radius-server host 10.0.20.10 key "fakeRadiusSecret-A"
radius-server host 10.0.20.11 key "fakeRadiusSecret-B"
radius-server key "fakeGlobalKey"
```

Default ports 1812 (auth) / 1813 (acct); per-server overrides via
`auth-port` / `acct-port`.

## Cross-vendor mapping

The canonical surface is `CanonicalRADIUSServer(host, key, auth_port,
acct_port)`.

Specifics:

* `host` round-trips losslessly.
* `key`: opaque shared-secret string from the source.  Junos's
  `$9$...` reversible blob lands verbatim on the canonical field
  but Aruba cannot decode `$9$` — operator must re-set the shared
  secret on the target.  Cross-decrypt is NOT possible.
* `auth_port` / `acct_port`: integers round-trip cleanly (Junos
  `port` / `accounting-port` -> canonical -> Aruba `auth-port` /
  `acct-port`).

Junos's RADIUS server attributes (`retry`, `timeout`,
`source-address`) are not modelled canonically and drop on round-
trip.

Disposition: **lossy** (shared-secret cross-decrypt impossible;
host + ports preserve cleanly).
