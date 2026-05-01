# Local users + hash formats: Aruba AOS-S versus MikroTik RouterOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for
2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
password manager user-name "admin" sha1 "fa1cefa1cefa1cefa1cefa1cefa1cefa1cefa1ce"
password manager user-name "siteops" plaintext "fakeRedactedPlaintext"
password operator user-name "monitor" sha1 "0bce0bce0bce0bce0bce0bce0bce0bce0bce0bce"
```

Aruba uses a **two-role** model: `manager` (privileged / write) and
`operator` (read-only).  Both roles accept SHA-1, bcrypt, or
plaintext-redacted hash forms:

- `sha1 "<40-hex>"` — SHA-1 hex digest of the password
- `bcrypt "$2y$..."` — bcrypt cost+salt+hash blob
- `plaintext "..."` — plaintext password (typically redacted on
  export)

Aruba accepts these formats only.  Cisco type-9 scrypt
(`$9$...`), Cisco type-8 PBKDF2 (`$8$...`), Linux MD5-crypt
(`$1$...`) are NOT accepted.

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)
Retrieved: 2026-04-30

```
/user add name=admin group=full
/user add name=operator group=write
/user add name=auditor group=read
```

RouterOS uses `/user add name=X group=Z password=Y` with predefined
groups `full` / `write` / `read` (operators can create custom
groups via `/user group add` with policy lists drawn from the
RouterOS RBAC primitives `local`, `telnet`, `ssh`, `read`, `write`,
`policy`, `winbox`, `password`, `web`, `api`, `rest-api`, `romon`).

RouterOS `/export` by default **omits the password** (treated as
sensitive).  Operators must run `/export show-sensitive` to include
the password line, and even then RouterOS does not surface a
vendor-stable hash format identifier — the password renders as the
operator-supplied plaintext or as a vendor-private blob.  This is
the "RouterOS does not surface hashed passwords in /export"
limitation that makes RouterOS the source-side of every cross-vendor
local-user migration lossy on the password material.

## Cross-vendor mapping

The canonical surface is

```
CanonicalLocalUser(name, privilege_level: int, hashed_password: str,
                   role: str)
```

### Role / privilege mapping

Aruba's two-role model (manager / operator) maps to RouterOS's
named groups (full / write / read):

- Aruba `manager` -> RouterOS `full`
- Aruba `operator` -> RouterOS `read`

The intermediate RouterOS `write` group has no Aruba equivalent
(Aruba is strictly two-role); inverse direction renders RouterOS
`write` -> Aruba `manager` with a banner.

The numeric `privilege_level` field on canonical is set to 15
(manager) or 1 (operator) by the aruba_aoss codec on parse so the
cross-vendor surface to Cisco-style targets remains stable; on the
RouterOS render path the privilege number is ignored in favour of
the role-derived group name.

### Password hash incompatibility

Aruba's SHA-1 hex / bcrypt / plaintext forms are NOT consumed by
RouterOS, and RouterOS's vendor-private password format is NOT
consumed by Aruba.  Cross-vendor migration of user accounts
**always requires re-setting passwords** on the target device.

The codec passes the source-side hash through verbatim into a
`comment=` field on the rendered RouterOS user line so the operator
has the source-side hash visible during re-key, but neither vendor
will authenticate against the other's hash blob.

In the inverse direction (RouterOS source -> Aruba target), the
canonical `hashed_password` arrives empty because RouterOS does
not surface the hash in `/export`.  Aruba render emits the
`password manager user-name "<name>" sha1 ""` form which Aruba
will accept syntactically but treats as a no-password account
(login disabled until the operator sets a password).

### Disposition

| Field | Disposition |
|---|---|
| `local_users[].name` | good |
| `local_users[].privilege_level` | lossy (numeric -> named-group) |
| `local_users[].role` | lossy (manager/operator <-> full/read; intermediate group on RouterOS has no Aruba equivalent) |
| `local_users[].hashed_password` | lossy (cross-vendor hash format incompatibility; re-key required) |
