# Local users + hash formats: MikroTik RouterOS versus Aruba AOS-S

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)
Retrieved: 2026-04-30

```
/user add group=full name=admin
/user add group=write name=operator
/user add group=read name=auditor
```

RouterOS uses `/user add name=X group=Z password=Y` with predefined
groups `full` / `write` / `read` (operators can create custom
groups via `/user group add` with policy lists drawn from RouterOS
RBAC primitives).

RouterOS `/export` by default **omits the password** (treated as
sensitive).  Operators must run `/export show-sensitive` to include
the password line, and even then RouterOS does not surface a
vendor-stable hash format identifier.  This is the structural
**password-export gap** that makes RouterOS the source side of
every cross-vendor local-user migration lossy on the password
material.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for
2930F / 2930M / 3810 / 5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
password manager user-name "admin" sha1 "<40-hex>"
password manager user-name "siteops" plaintext "<plaintext>"
password operator user-name "monitor" sha1 "<40-hex>"
```

Aruba uses a **two-role** model: `manager` (privileged) and
`operator` (read-only).  Both roles accept SHA-1 hex / bcrypt /
plaintext-redacted hash forms.  Aruba does NOT accept the
RouterOS vendor-private password format.

## Cross-vendor mapping

The canonical surface is

```
CanonicalLocalUser(name, privilege_level: int, hashed_password: str,
                   role: str)
```

### Role / group mapping

RouterOS named groups -> Aruba two-role:

- RouterOS `full` -> Aruba `manager` (privilege 15)
- RouterOS `write` -> Aruba `manager` (privilege 15) — the closest
  Aruba role; canonical preserves the distinction via `role="write"`
  but the rendered Aruba line is `password manager user-name ...`
- RouterOS `read` -> Aruba `operator` (privilege 1)
- Custom RouterOS groups -> Aruba `operator` with banner (no
  intermediate role on Aruba)

### Password material — the structural blocker

RouterOS does not surface hashed passwords in `/export`, so the
canonical `hashed_password` arrives **empty** after parsing a
RouterOS source.  Aruba target render emits:

```
password manager user-name "admin" sha1 ""
```

which Aruba accepts syntactically but treats as a no-password
account (login disabled until the operator manually sets a password).
This is the dominant lossy path for cross-vendor user migration in
this direction — the operator MUST run `password manager user-name
"<name>" plaintext "<new-password>"` on each migrated user post-
migration.

The codec emits a banner explaining the empty-hash render so the
operator sees the gap during the migration validation review.

### Disposition

| Field | Disposition |
|---|---|
| `local_users[].name` | good |
| `local_users[].privilege_level` | lossy (custom RouterOS groups have no Aruba numeric equivalent) |
| `local_users[].role` | lossy (RouterOS `write` collapses to Aruba `manager`) |
| `local_users[].hashed_password` | lossy (RouterOS does not surface hashes; render emits empty SHA-1) |
