# SNMP: Aruba AOS-S versus Arista EOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Management and Configuration Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/MCG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

v1/v2c surface — quoted community + AOS-S-named access keyword:

```
snmp-server community "public" Operator
snmp-server community "private" Manager unrestricted
snmp-server location "Building 7 Floor 3"
snmp-server contact "noc@example.com"
snmp-server host 10.0.0.5 community "public"
```

Access keywords: `Operator` (read-only by default) and `Manager`
(read-write).  These are AOS-S RBAC roles, not RO/RW.

v3 USM (the codec's `_SNMPV3_USER_RE` and `_SNMPV3_GROUP_BIND_RE`
match this shape):

```
snmpv3 user "monitor-usr" auth sha "AUTHP4SS" priv aes "PR1VP4SS"
snmpv3 group "auth-priv-grp" user "monitor-usr" sec-model ver3
```

Aruba accepts `md5` / `sha` for auth, and `des` / `aes` for priv.

## Arista EOS

Source: [Arista EOS — SNMP](https://www.arista.com/en/um-eos/eos-snmp)
Retrieved: 2026-05-01

v1/v2c surface (Cisco-style grammar):

```
snmp-server community public ro
snmp-server community private rw
snmp-server location "Synthetic Lab Rack 7"
snmp-server contact "noc@example.net"
snmp-server host 10.0.0.250
```

v3 USM:

```
snmp-server user monitor netadmin v3 auth sha $9$fake$authHash$1 priv aes256 $9$fake$privHash$1
snmp-server user readonly readonly v3 auth sha256 $9$fake$authHash$2 priv aes $9$fake$privHash$2
```

Arista accepts the full SHA family (`sha`, `sha224`, `sha256`,
`sha384`, `sha512`) and `aes` / `aes192` / `aes256` for priv.

## Cross-vendor mapping

The canonical surface is `CanonicalSNMP` with `community`,
`location`, `contact`, `trap_hosts`, and `v3_users`.

Aruba -> Arista round-trip details:

* `community`: Aruba `Operator` -> Arista `ro`; Aruba `Manager`
  -> Arista `rw` (the access semantic is not modelled in canonical
  v1; cross-vendor render emits a default mapping).
* `location` / `contact`: opaque free-text round-trips cleanly
  (both vendors quote-tolerate).
* `trap_hosts`: Aruba's `snmp-server host <addr> community "X"`
  emits as Arista's `snmp-server host <addr>`.
* `v3_users`: structured fields (name + group + auth_protocol +
  priv_protocol) round-trip; opaque hashed passphrases are NOT
  cross-compatible because USM keys are salted with vendor-
  specific engineID-derived constants.  Documented in
  `CanonicalSNMPv3User` docstring.

The Aruba synthetic kitchen-sink carries `snmp-server community
"public" Operator` plus two v3 users (`monitor-usr`, `audit-usr`)
which exercise the auth-md5/sha + priv-des/aes matrix.  The
Arista kitchen-sink (`ks-leaf-01`) carries v3 users with
`sha`/`sha256` auth and `aes`/`aes256` priv — both protocol
enums round-trip cleanly through the canonical layer.

Disposition for `community` / `location` / `contact` /
`trap_hosts`: **good**.

Disposition for `v3_users`: **lossy** (operator must re-key on
the target device because the engineID-derived passphrase salt
differs).
