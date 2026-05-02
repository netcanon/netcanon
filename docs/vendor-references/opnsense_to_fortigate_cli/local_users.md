# Local users: OPNsense versus FortiGate FortiOS

Reverse direction.  Forward direction in
`../fortigate_cli_to_opnsense/local_users.md`.

Both vendors carry their own opaque vendor-private hash format, and
neither hash format is portable to the other end.  Cross-vendor
migration of admin accounts requires re-setting passwords on the
target.

## OPNsense

Source: [OPNsense Users
manual](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-05-01

```xml
<opnsense>
  <system>
    <user>
      <name>admin</name>
      <descr>Administrator</descr>
      <scope>user</scope>
      <password>$2y$10$fakeBcryptAdminHash..............</password>
      <groupname>admins</groupname>
      <uid>0</uid>
    </user>
    <user>
      <name>auditor</name>
      <descr>Auditor</descr>
      <scope>user</scope>
      <password>$2y$10$fakeBcryptAuditorHash...........</password>
      <groupname>users</groupname>
      <uid>1001</uid>
    </user>
  </system>
</opnsense>
```

OPNsense notes:

- `<password>` is bcrypt — FreeBSD `crypt(3)` accepts `$2a$` / `$2b$`
  / `$2y$` prefixes interchangeably.
- `<groupname>admins</groupname>` ↔ admin role; any other group ↔
  non-admin.  Canonical privilege >= 15 maps to `admins`,
  otherwise `users`.
- `<scope>user</scope>` discriminates user-created accounts from
  built-ins (`<scope>system</scope>`).

## FortiGate FortiOS

See `../fortigate_cli_to_opnsense/local_users.md` for the
FortiGate-side shape.  Key points:

- Admin accounts under `config system admin` edit-table.
- `set password ENC <opaque-base64>` is FortiOS proprietary
  encrypted form.
- `set accprofile` enumerates named profiles (`super_admin` /
  `prof_admin` / custom-named).
- Privilege mapping: super_admin -> 15; other profiles -> 1 with
  the profile name preserved in canonical `role`.

## Cross-vendor mapping (OPNsense -> FortiGate)

- `username`: **good** — verbatim string transfer.
- `password_hash`: **lossy** — OPNsense bcrypt is FreeBSD-`crypt(3)`-
  compatible; FortiOS uses `ENC <opaque-base64>` with internal-key
  encryption.  Hashes are NOT cross-compatible.  Both codecs
  preserve hashes verbatim with vendor tags (`bcrypt:` on OPNsense,
  `fortios:` on FortiGate) so the loss surfaces in the validation
  report.  Operators must reset passwords on the FortiGate target.
- `hash_format`: **lossy** — same root cause; vendor-private form on
  either side.
- `privilege`: **lossy** — OPNsense's binary admin / non-admin (via
  `<groupname>`) collapses to FortiGate's named accprofile:
  privilege 15 -> `super_admin`, otherwise -> `prof_admin`.  Lossy
  in the sense that nuance from canonical privilege levels is
  flattened to a binary on the OPNsense source side already, before
  reaching the FortiGate target.
- `role`: **not_applicable** — OPNsense source does not populate
  the canonical `role` field (no concept of named accprofiles), so
  FortiGate render synthesises `super_admin` / `prof_admin` from
  privilege.
- OPNsense `<scope>` / `<uid>` / `<descr>` fields drop on canonical
  (no schema fields).
