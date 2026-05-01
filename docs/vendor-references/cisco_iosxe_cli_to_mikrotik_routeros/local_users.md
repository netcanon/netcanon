# Local users + hash formats: Cisco IOS-XE versus MikroTik RouterOS

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide.

```
username admin privilege 15 secret 9 $9$abcdef$ghijklmnop...
username readonly privilege 1 secret 5 $1$mERr$xyz...
username audit privilege 5 secret 8 $8$ABC...$DEF...
```

Cisco models `username <name> privilege <0-15> secret <type> <hash>`
where `<type>` indicates the hash family:

- type 5 — MD5-crypt (`$1$...`) — broadly portable Linux crypt(3)
- type 7 — Cisco-proprietary obfuscation; reversible — never use
- type 8 — PBKDF2-SHA256 — Cisco-only
- type 9 — scrypt — Cisco-only

`privilege` is a numeric scope (0 = none, 15 = enable / admin).

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)

Retrieved: 2026-04-30

```
/user add name=admin group=full password=S3cretPass!
/user add name=readonly group=read password=R3adOnlyPass!
/user add name=audit group=audit-custom password=Audit!
```

RouterOS uses `/user add name=X password=Y group=Z`.  Predefined
groups are `full` / `write` / `read`; operators can create custom
groups via `/user group add name=<name> policy=<policy-list>`
with policies drawn from the RouterOS RBAC primitives (`local`,
`telnet`, `ssh`, `ftp`, `read`, `write`, `policy`, `test`,
`winbox`, `password`, `web`, `sniff`, `sensitive`, `api`, `rest-
api`, `romon`).

`/export` of the user table by default OMITS the password (treated
as sensitive) — operators must explicitly run `/export show-
sensitive` to include the password line, and even then the
password renders as the operator-supplied plaintext or, on hashed-
storage configurations, as a hash blob without a vendor-stable
format identifier.

## Cross-vendor mapping

The canonical surface is

```
CanonicalLocalUser(name, privilege_level: int, hashed_password: str,
                   role: str)
```

### Privilege / role mismatch

Cisco's numeric `privilege 1-15` versus RouterOS's named groups
(`full` / `write` / `read` / custom) requires operator-curated
mapping:

- privilege 15 -> `full` (admin)
- privilege 1  -> `read` (read-only by convention)
- privilege 5-14 -> custom group; canonical preserves the
  numeric privilege but RouterOS render emits a default group
  with a banner

### Password hash incompatibility

Cisco's type-9 scrypt and type-8 PBKDF2-SHA256 are Cisco-only
hash families; RouterOS does not consume them.  RouterOS hashes
its own password store using a vendor-private format (not the
standard Linux crypt(3) family) and the export does not surface
the hash directly — making cross-vendor migration of the secret
impossible without a re-key step.

The codec passes the hash through verbatim into a `comment=`
field on the rendered RouterOS user line so the operator has
the source-side hash visible during re-key, but neither vendor
will authenticate against the other's hash blob.

### Disposition

| Field | Disposition |
|---|---|
| `local_users[].name` | good |
| `local_users[].privilege_level` | lossy (numeric -> named-group mapping) |
| `local_users[].role` | lossy (Cisco has no first-class role; RouterOS has no privilege number) |
| `local_users[].hashed_password` | lossy (cross-vendor hash format incompatibility; re-key required) |
