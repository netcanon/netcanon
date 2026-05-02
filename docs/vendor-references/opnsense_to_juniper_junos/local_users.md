# Local users: OPNsense versus Junos

## OPNsense

Source: [OPNsense Users manual](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-04-30

```xml
<system>
  <group>
    <name>admins</name>
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

- Password hashes are bcrypt (`$2b$<cost>$<salt><hash>`).
- Privilege model is group-based: `<groupname>admins</groupname>`
  grants administrative access; `<groupname>users</groupname>`
  grants read-only.
- The opnsense codec maps `<groupname>admins</groupname>` →
  `CanonicalLocalUser.privilege_level=15`; other groups → 1.
- SSH public keys live separately under `<authorizedkeys>`
  (base64-encoded openssh authorized_keys file content); not
  currently wired into canonical.

## Junos

Source: [Junos password (Login) CLI reference](https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html)
Source: [Juniper KB31903 — password format SHA512 default in 17.2+](https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903)
Retrieved: 2026-05-01

```
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$..."
```

Junos local-users notes:

- Each user binds a `class` (named role): `super-user`, `operator`,
  `read-only`, plus operator-defined custom classes.
- `encrypted-password "<hash>"` defaults to SHA-512 (`$6$`) since
  Junos 17.2; SHA-256 (`$5$`) and MD5 (`$1$`) accepted on legacy.

## Cross-vendor mapping

OPNsense -> Junos:

- `local_users[].name`: **good** — opaque identity round-trips.
- `local_users[].privilege_level`: **lossy** — OPNsense's group-
  binary (`admins` ↔ 15, others ↔ 1) maps to Junos's named class.
  Default mapping: privilege >= 15 → `super-user`; else
  `operator` (or `read-only` if a richer mapping is wired).
  OPNsense custom groups lose their identity.
- `local_users[].hashed_password`: **lossy** — OPNsense bcrypt
  (`$2b$...`) is NOT a Junos `encrypted-password` accepted format
  (Junos accepts `$1$` MD5, `$5$` SHA-256, `$6$` SHA-512).  Junos
  may parse the bcrypt hash on commit (Linux/PAM crypt() supports
  bcrypt on most modern Junos OS releases) but the safer
  expectation is rejection or non-authentication; operator
  re-keys on the Junos target.  Both codecs pass hashes through
  verbatim; loss surfaces in the validation report.
- `local_users[].role`: **lossy** — same as `privilege_level`
  collapse; OPNsense's group name does not map cleanly to a
  Junos class.

Disposition: **lossy** — bcrypt versus `$6$` SHA-512 hash-format
incompatibility plus group-binary versus named-class privilege
collapse.
