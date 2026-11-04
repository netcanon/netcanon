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
password operator user-name "monitor" sha1 "<40-hex>"
```

AOS-S holds **one** manager and **one** operator account: the
user-name names the account, and a second `password manager` line
re-points the same one (HPE Access Security Guide, AOS-S 16.x).  An
operator password with no manager password gives manager access.
Netcanon writes the first user of each role that AOS-S can take, an
operator only beside a manager, and every other user as a `; ...
-- review:` comment, with a job warning where the reason is AOS-S's
own; further named accounts on a switch are `aaa authentication
local-user` (CLI only; not written).
See [`../../vendors/aruba_aoss.md`](../../vendors/aruba_aoss.md#local-users-one-manager-and-one-operator).

Aruba uses a **two-role** model: `manager` (privileged) and
`operator` (read-only).  Both roles take the `plaintext`, `sha1`
and `sha256` forms.  Aruba does NOT accept the RouterOS
vendor-private password format.

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
RouterOS source.  AOS-S has no account without a password, so the
render writes no live line for such a user.  Each is a comment:

```
; password manager user-name "admin" -- review: no password for this account was read from the source; set it on the switch with password manager user-name "admin", which asks for the password
```

and the job carries a warning for it.  This is the dominant lossy
path for user migration in this direction.  On the switch, set the
manager password first and then at most one operator: AOS-S holds one
account of each role, and a second `password manager` line replaces
the first.

### Disposition

| Field | Disposition |
|---|---|
| `local_users[].name` | good |
| `local_users[].privilege_level` | lossy (custom RouterOS groups have no Aruba numeric equivalent) |
| `local_users[].role` | lossy (RouterOS `write` collapses to Aruba `manager`) |
| `local_users[].hashed_password` | lossy (RouterOS does not surface hashes; each account is a review comment) |
