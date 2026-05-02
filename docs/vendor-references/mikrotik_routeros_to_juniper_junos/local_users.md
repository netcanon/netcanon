# Local users (auth, hash format, role): MikroTik RouterOS versus Juniper Junos

How local user accounts are declared on each platform.

Sources:
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html (retrieved 2026-05-01)
- Juniper: https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903 (retrieved 2026-05-01)

Citation ids: `mikrotik-user`, `junos-password-cli`,
`junos-kb-password-format`.

## RouterOS form

```
/user
add group=full name=admin
add group=write name=operator
add group=read name=auditor
```

RouterOS uses named groups: `full` (read+write+policy), `write`
(read+write minus security-sensitive), `read` (read-only), plus
operator-defined groups via `/user group add name=<X> policy=<list>`.
Password handling on RouterOS is opaque — passwords are NOT shown in
`/export` regardless of hash format.  RouterOS hashes passwords
internally with a vendor-private scheme that is not cross-portable.
SSH public-key auth is configured via `/user ssh-keys import` and
is not surfaced in the canonical model today.

## Junos form

```
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication encrypted-password \
    "$6$fakeAdmin$fakeAdminHash01234567890123"
set system login user operator class operator
set system login user operator authentication encrypted-password \
    "$6$fakeOp$fakeOpHash9876543210"
set system login user readonly class read-only
set system login user readonly authentication ssh-rsa "ssh-rsa AAAAB3..."
```

Junos defaults to SHA-512 (`$6$`) for `encrypted-password` since
17.2 (per KB31903); accepts `$1$` (MD5 legacy) and `$5$` (SHA-256)
on older releases.  Built-in classes are `super-user`, `operator`,
`read-only`, `unauthorized`, plus operator-defined classes via
`set system login class <name>`.

## Cross-vendor mapping

* `local_users[].name`: opaque identity string, direct mapping.
* `local_users[].privilege_level` / `role`: RouterOS named groups ->
  Junos named classes via codec policy: `full` -> `super-user`,
  `write` -> `operator`, `read` -> `read-only`.  RouterOS custom
  groups have no clean Junos analogue — fall back to `read-only`
  with banner.
* `local_users[].hashed_password`: RouterOS does not surface the
  password hash in /export at all (vendor-private internal format).
  Canonical `hashed_password` is typically empty after RouterOS
  parse — Junos render emits no `authentication encrypted-password`
  line, leaving the user account WITHOUT a password.  Operator MUST
  re-set passwords on the target after migration before the user
  can log in.
* SSH public-key auth: RouterOS `/user ssh-keys` is outside the
  canonical surface; Junos's `ssh-rsa` / `ssh-ed25519` records on
  the `authentication` sub-tree have no canonical RouterOS source.

Disposition: **lossy** — name and role round-trip (with role-mapping
policy); RouterOS source NEVER carries a hash, so cross-vendor
migration of user accounts always lands without a password and
requires operator intervention before the user can log in.
