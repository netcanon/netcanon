# RADIUS: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — User Security / RADIUS](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

Arista uses Cisco-style flat or named-server forms:

```
radius-server host 10.0.20.10 key "fakeRadiusSecret-A"
radius-server host 10.0.20.11 auth-port 1812 acct-port 1813 key "fakeRadiusSecret-B"
radius-server key "globalDefaultSecret"
```

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses a flat per-host declaration with a separate global
key directive:

```
radius-server host 10.0.20.10 key "fakeRadiusSecret-A"
radius-server host 10.0.20.11 key "fakeRadiusSecret-B"
radius-server host 10.0.20.12 auth-port 1812 acct-port 1813
radius-server key "globalDefaultSecret"
```

Both vendors share Cisco-derived `radius-server host` grammar
with `auth-port` / `acct-port` per-host overrides and an
optional global key fallback.

## Cross-vendor mapping

The canonical surface is `CanonicalRADIUSServer(host, key,
auth_port, acct_port)`.

Arista -> Aruba round-trip:

* `host`: opaque IP / FQDN string round-trips cleanly.
* `key`: a key written as typed round-trips verbatim.  RADIUS
  shared secrets are NOT engineID-salted (unlike SNMPv3 USM
  passphrases), so cross-vendor migration of such a key IS
  possible without re-keying.  EOS prints a key in its own form,
  `key 7 <blob>`: that is held behind `eos:`, not decoded, and the
  server is written with no key, beside a review line.
* `auth_port` / `acct_port`: defaults to 1812 / 1813 on both
  vendors; per-host overrides round-trip as explicit keywords.

The Arista kitchen-sink does not carry RADIUS servers; coverage
of this path lives in real-capture fixtures
(`tests/fixtures/real/arista/...`) and the Aruba kitchen-sink's
two `radius-server host ... key "..."` lines.

Disposition: **lossy** (host / port tuple and a key written as
typed round-trip; a `key 7` is refused).
