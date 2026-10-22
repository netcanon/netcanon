# RADIUS: Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: Cisco IOS XE Security Command Reference — `radius server`
command family.

Modern IOS-XE form (preferred):

```
radius server CORP-RADIUS
 address ipv4 10.0.0.10 auth-port 1812 acct-port 1813
 key 0 SharedSecret
```

Legacy form (still accepted):

```
radius-server host 10.0.0.10 auth-port 1812 acct-port 1813 key SharedSecret
```

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S uses a flat `radius-server host` line.  Verbatim manual
shapes:

```
radius-server host 10.0.0.10
radius-server host 10.0.0.10 key "SharedSecret"
radius-server key "SharedSecret"
```

The codec's `_RADIUS_HOST_RE` parser accepts the host line
(optional inline `key "<secret>"`) AND a separate
`radius-server key "<secret>"` line that applies as the global
default key.  When the host line lacks an inline key, the parser
back-fills from the global default.

## Cross-vendor mapping

Both codecs round-trip the canonical
`CanonicalRADIUSServer(host, key, auth_port, acct_port)` tuple
for a key written as typed.

* `host`: IPv4 address (string).
* `key`: a key written as typed (`key <secret>`, `key 0 <secret>`)
  is carried as the literal secret.  A key IOS-XE stored in its own
  form -- `key 7 <blob>` (Cisco's reversible cipher) or `key 6
  <blob>` (AES under the router's master key) -- is a form only
  IOS-XE reads: the parser holds it behind `iosxe:`, it is not
  decoded, and the AOS-S render writes the server with no key,
  beside a review line that names the form.  The secret has to be
  re-entered.
* `auth_port` / `acct_port`: integers; both vendors default to
  1812 / 1813.

Cisco's modern `radius server <name>` form (with named server +
nested address sub-command) condenses to the same canonical record
as the flat `radius-server host` form.  Aruba renders only the
flat form.

Disposition: **lossy** (a `key 7` / `key 6` is refused; the
kitchen sink's `key 7` shows it).
