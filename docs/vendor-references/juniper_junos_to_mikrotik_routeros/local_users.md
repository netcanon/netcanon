# Local users (auth, hash format, role): Juniper Junos versus MikroTik RouterOS

How local user accounts are declared on each platform.

Sources:
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html (retrieved 2026-05-01)
- Juniper: https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903 (retrieved 2026-05-01)
- MikroTik: https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User (retrieved 2026-05-01)

Citation ids: `junos-password-cli`, `junos-kb-password-format`,
`mikrotik-user`.

## Junos form

```
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication encrypted-password \
    "$6$fakeAdmin$fakeAdminHash01234567890123"
set system login user operator uid 2001
set system login user operator class operator
set system login user operator authentication encrypted-password \
    "$6$fakeOp$fakeOpHash9876543210"
set system login user readonly uid 2002
set system login user readonly class read-only
set system login user readonly authentication ssh-rsa "ssh-rsa AAAAB3..."
```

Junos defaults to SHA-512 (`$6$`) for `encrypted-password` since
17.2 (per KB31903); accepts `$1$` (MD5 legacy) and `$5$` (SHA-256)
on older releases.  Built-in classes are `super-user`, `operator`,
`read-only`, `unauthorized`, plus operator-defined classes via
`set system login class <name>`.  SSH public-key authentication
(`ssh-rsa "..."`, `ssh-ed25519 "..."`) is parallel to encrypted-
password and lives on the same `authentication` sub-tree.

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
Password handling on RouterOS is opaque: passwords are NOT shown in
`/export` regardless of hash format.  The `/export` output omits the
password attribute entirely; an unprotected backup uses the
`/export hide-sensitive` flag's inverse.  RouterOS hashes passwords
internally with a vendor-private scheme that is not cross-portable.
SSH public-key auth is configured via `/user ssh-keys import` and
is not surfaced in the canonical model today.

## Cross-vendor mapping

* `local_users[].name`: opaque identity string, direct mapping.
* `local_users[].privilege_level` / `role`: Junos's named classes
  (`super-user` / `operator` / `read-only`) map to RouterOS named
  groups (`full` / `write` / `read`) via codec policy:
  `super-user` -> `full`, `operator` -> `write`, `read-only` -> `read`.
  Custom Junos classes have no clean RouterOS analogue — fall back
  to `read` with a banner.
* `local_users[].hashed_password`: Junos `$6$...` (SHA-512) or
  `$5$...` (SHA-256) or `$1$...` (MD5) blobs are NOT cross-compatible
  with RouterOS's vendor-private internal hash format.  RouterOS
  /export does not surface the hash at all, so the cross-vendor
  render typically passes the Junos blob through into a RouterOS
  `comment=` so the operator has it during re-key.  Operator MUST
  re-set passwords on the target after migration.
* SSH public-key auth: Junos's `ssh-rsa` / `ssh-ed25519` records have
  no canonical model today and drop to raw_sections on parse.
  RouterOS's `/user ssh-keys` is also outside the canonical surface.

Disposition: **lossy** — name and role round-trip (with role-mapping
policy); hash formats incompatible (cross-vendor migration of user
accounts always requires re-keying on the target); SSH key
authentication outside canonical scope.
