# Local users: MikroTik RouterOS versus Arista EOS

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)
Retrieved: 2026-05-01

```
/user
add group=full name=admin
add group=write name=operator
add group=read name=auditor

/user group
add name=audit policy=read,winbox,api
```

Critically, RouterOS does **NOT** surface password material in
`/export verbose` output.  The `add` lines have no password
attribute at all — the password is stored internally in a
vendor-private format and the export omits it.  This is by
design: `/export` is intended to be safely shareable / version-
controllable.

RouterOS's role model is **named groups**:

- `full` — full access (admin)
- `write` — read/write but no policy/user management
- `read` — read-only
- custom — operator-defined groups with explicit policy lists

## Arista EOS

Source: [Arista EOS — User Security](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

```
username admin privilege 15 role network-admin secret sha512 $6$fakeSalt$fakeHashSha512AbcDefGhiJklMnoPqrStuVwxYz0123456789AbcDefGhiJklMnoPqrStuVwxYz01234
username operator privilege 7 role network-admin nopassword
username readonly privilege 1 role network-operator nopassword
```

Arista's local-user model is **two-axis**: a numeric privilege
level (0..15) plus a named role.  Password material is stored
under `secret <type> <hash>` form (`secret sha512 $6$...` is the
modern default).

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.local_users:
list[CanonicalLocalUser]` with fields `name` / `privilege_level`
/ `hashed_password` / `role`.

RouterOS -> Arista round-trip:

**Role / privilege mapping** — operator-curated:

| RouterOS group | Arista privilege | Arista role |
|---|---|---|
| `full` | 15 | network-admin |
| `write` | 7 | network-admin |
| `read` | 1 | network-operator |
| custom | 1 (default) | network-operator (default) |

The codec emits a banner when a custom RouterOS group is
encountered; operator must override the privilege/role mapping
manually.

**Password material** — the structural blocker:

RouterOS does not surface hashed passwords in `/export`, so the
canonical `hashed_password` arrives empty after RouterOS parse.
Arista render emits:

```
username admin privilege 15 role network-admin nopassword
username operator privilege 7 role network-admin nopassword
username auditor privilege 1 role network-operator nopassword
```

— with the explicit `nopassword` marker.  This is the safest
default behaviour: users CAN log in only via RADIUS / TACACS+ or
once the operator has set a password manually.

Operator MUST set passwords manually on the Arista target after
migration:

```
username admin secret <new-password>
```

Arista hashes the supplied plaintext on entry and stores the
result.

This is a documented RouterOS limitation, not a codec gap.  The
alternative (storing plaintext passwords in `/export`) would be
worse for security.

The MikroTik synthetic kitchen-sink carries three users
(admin/full + operator/write + auditor/read).  All three lift
to canonical with empty `hashed_password`; all three render to
Arista as `username X privilege Y role Z nopassword`.

Disposition: **lossy** — the username + group → privilege/role
mapping survives, but password material drops.  Operator MUST
re-set passwords on the Arista target.
