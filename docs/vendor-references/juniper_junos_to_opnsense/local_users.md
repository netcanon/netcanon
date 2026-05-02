# Local users: Junos versus OPNsense

## Junos

Source: [Junos password (Login) CLI reference](https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html)
Source: [Juniper KB31903 — password format SHA512 default in 17.2+](https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903)
Retrieved: 2026-05-01

```
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$fakeAdmin$fakeAdminHash01234567890123"
set system login user operator uid 2001
set system login user operator class operator
set system login user operator authentication encrypted-password "$6$fakeOp$fakeOpHash9876543210"
set system login user readonly uid 2002
set system login user readonly class read-only
set system login user readonly authentication ssh-rsa "ssh-rsa AAAAB3..."
```

Junos local-users notes:

- Each user binds a `class` (named role): `super-user`, `operator`,
  `read-only`, `unauthorized`, plus operator-defined custom classes.
- Authentication can be:
  - `encrypted-password "<hash>"` — SHA-512 (`$6$`) default since
    Junos 17.2; SHA-256 (`$5$`) and MD5 (`$1$`) accepted on legacy.
  - `ssh-rsa "ssh-rsa AAAAB3..."` — public-key auth only.
  - `no-password` — class-only access (rare).
- UID is required only when the operator wants a specific numeric ID.

## OPNsense

Source: [OPNsense Users manual](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-04-30

```xml
<system>
  <group>
    <name>admins</name>
    <description>System Administrators</description>
    <scope>system</scope>
    <gid>1999</gid>
    <member>0</member>
    <member>2000</member>
    <priv>page-all</priv>
  </group>
  <user>
    <name>netops</name>
    <descr>Network Operations</descr>
    <scope>user</scope>
    <groupname>admins</groupname>
    <password>$2b$10$fakeAJhashNetopsAccountPlaceholder</password>
    <uid>2000</uid>
  </user>
</system>
```

OPNsense local-users notes:

- Password hashes are bcrypt only (`$2b$<cost>$<salt><hash>`).
  OPNsense's PAM stack rejects non-bcrypt hashes on apply.
- Privilege model is group-based: `<groupname>admins</groupname>`
  grants administrative access via `<priv>page-all</priv>`;
  `<groupname>users</groupname>` grants read-only.
- The `<scope>` element distinguishes `system` (built-in, e.g. root)
  from `user` (operator-created).
- SSH public keys live separately under `<authorizedkeys>` (base64-
  encoded openssh authorized_keys file content).

## Cross-vendor mapping

Junos -> OPNsense:

- `local_users[].name`: **good** — opaque identity string round-trips.
- `local_users[].privilege_level`: **lossy** — Junos `class` (named
  role) versus OPNsense binary admin / non-admin via group membership.
  Mapping rule: `super-user` → `admins` group (privilege_level=15);
  `operator` / `read-only` → `users` group (privilege_level=1).
  Junos custom classes lose their named identity on the cross-pair.
- `local_users[].hashed_password`: **lossy** — Junos `$6$` SHA-512
  (or `$5$` / `$1$` legacy forms) is NOT bcrypt; OPNsense's PAM stack
  will reject the hash on apply.  Junos `ssh-rsa` public-key auth
  lands in `<password>` verbatim, but OPNsense expects a bcrypt hash
  there and the SSH key in `<authorizedkeys>` (separate field).
  Operators MUST reset passwords / re-add SSH keys on the OPNsense
  target after migration.  Both codecs pass hashes through verbatim;
  loss surfaces in the validation report.
- `local_users[].role`: **lossy** — Junos's named `class` is more
  expressive than OPNsense's group-binary; cross-pair flattens to
  group name.

Disposition: **lossy** — hash-format incompatibility plus
privilege-model collapse plus separate SSH-key field documented; both
codecs round-trip the canonical fields but the target hash will not
authenticate without operator intervention.
