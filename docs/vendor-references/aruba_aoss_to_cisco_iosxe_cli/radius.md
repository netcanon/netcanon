# RADIUS: Aruba AOS-S versus Cisco IOS-XE

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses flat `radius-server host` lines:

```
radius-server host 10.0.0.10
radius-server host 10.0.0.10 key "SharedSecret"
radius-server key "SharedSecret"
```

The codec accepts:

* Inline per-host key: `radius-server host <ip> key "<secret>"`.
* Global default key: `radius-server key "<secret>"` (back-filled
  onto hosts that lack inline keys).
* Default ports (1812 auth, 1813 acct) — AOS-S does not advertise
  `auth-port` / `acct-port` keywords on the host line.

## Cisco IOS-XE

Source: Cisco IOS XE Security Command Reference — `radius server`
command family.

Modern form:

```
radius server CORP-RADIUS
 address ipv4 10.0.0.10 auth-port 1812 acct-port 1813
 key 0 SharedSecret
```

Legacy / flat form:

```
radius-server host 10.0.0.10 auth-port 1812 acct-port 1813 key SharedSecret
```

## Cross-vendor mapping

The canonical model is `CanonicalRADIUSServer(host, key,
auth_port, acct_port)`.

Aruba -> Cisco round-trip:

* `host`: round-trips cleanly.
* `key`: opaque string round-trips; both vendors accept the
  literal secret.  Operator best practice rotates secrets on
  cutover regardless of vendor.
* `auth_port` / `acct_port`: defaults to 1812 / 1813 on parse
  (Aruba doesn't carry the keyword).  Cisco render emits
  explicit `auth-port 1812 acct-port 1813`.

Disposition: **good**.
