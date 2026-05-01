# RADIUS: Aruba AOS-S versus Juniper Junos

How RADIUS server entries and shared secrets are declared on each
platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation/us/en/software/junos/cli-reference/topics/ref/statement/radius-server-edit-system.html (retrieved 2026-05-01)

Citation ids: `aruba-radius`, `junos-radius-cli`.

## Aruba AOS-S form

```
radius-server host 10.0.20.10 key "fakeRadiusSecret-A"
radius-server host 10.0.20.11 key "fakeRadiusSecret-B"

# Or with a separate global key:
radius-server host 10.0.20.12
radius-server key "fakeGlobalKey"
```

Default ports are 1812 (auth) / 1813 (acct); per-server overrides
via `auth-port` / `acct-port`.

## Junos form

```
set system radius-server 10.0.0.200 secret "$9$fakeRadiusSecret$1"
set system radius-server 10.0.0.201 port 1812 secret "$9$fakeRadiusSecret$2"
set system radius-server 10.0.0.201 accounting-port 1813
```

The `secret` is typically stored as a `$9$...`-encrypted blob.
Default ports identical to Aruba (1812 / 1813).

## Cross-vendor mapping

The canonical surface is `CanonicalRADIUSServer(host, key, auth_port,
acct_port)`.

Specifics:

* `host` round-trips losslessly.
* `key`: opaque shared-secret string from the source; cross-decrypt
  is NOT possible.  Junos's `$9$...` reversible-encrypted form and
  Aruba's quoted plaintext / encrypted blob land verbatim on the
  canonical field but the target device cannot decode them as-is.
  Operator must re-set the shared secret on the target.
* `auth_port` / `acct_port`: integers round-trip cleanly.

Aruba's "global key" form (separate `radius-server key`) is
post-merged onto every `host`-only entry by the codec parse path
so the canonical record carries a single explicit `key`.

Disposition: **lossy** (shared-secret cross-decrypt impossible; host
+ ports preserve cleanly).
