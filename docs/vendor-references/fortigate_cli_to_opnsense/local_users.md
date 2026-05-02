# Local users: FortiGate FortiOS versus OPNsense

Both vendors carry their own opaque vendor-private hash format, and
neither hash format is portable to the other end.  Cross-vendor
migration of admin accounts requires re-setting passwords on the
target.

## FortiGate FortiOS

Source: [FortiGate / FortiOS 7.4 Administration Guide — `config system
admin`](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/)
Retrieved: 2026-05-01

```
config system admin
    edit "admin"
        set accprofile "super_admin"
        set vdom "root"
        set password ENC fakeEncodedSuperAdminHash==
    next
    edit "auditor"
        set accprofile "prof_admin"
        set vdom "root"
        set password ENC fakeEncodedAuditorHash==
        set trusthost1 10.0.10.0 255.255.255.0
    next
end
```

Notes:

- `set accprofile` enumerates the named profile (`super_admin` /
  `prof_admin` / custom-named profiles) — FortiGate's role model is
  named profiles, not numeric privilege levels.
- `set password ENC <opaque-base64>` is FortiGate's proprietary
  encrypted form.  The codec carries it through verbatim with a
  `fortios:` tag in canonical for intra-vendor round-trip.
- `set trusthost1...trusthost10` enumerate IP-restricted access
  controls (FortiGate-specific; not in canonical).
- Privilege mapping: super_admin -> canonical privilege 15; other
  profiles -> canonical privilege 1 with the profile name preserved
  in `role`.

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

Notes:

- `<password>` is a bcrypt hash.  FreeBSD `crypt(3)` accepts
  `$2a$` / `$2b$` / `$2y$` prefixes interchangeably.
- `<groupname>admins</groupname>` ↔ admin role; any other group
  membership ↔ non-admin.  Canonical privilege >= 15 maps to
  `admins`, otherwise `users`.
- `<scope>user</scope>` (versus `<scope>system</scope>` for built-in
  accounts) — not currently a canonical field.
- `<uid>` is a UNIX user-ID, allocated by OPNsense; not portable.

## Cross-vendor mapping

Canonical fields covered (`CanonicalLocalUser`):

```
username, password_hash, hash_format, privilege, role
```

FortiGate -> OPNsense:

- `username`: **good** — verbatim string transfer.
- `password_hash`: **lossy** — FortiGate `ENC <opaque-base64>` is
  FortiOS-internal-key-encrypted; OPNsense bcrypt is
  FreeBSD-`crypt(3)`-compatible.  Hashes are NOT cross-compatible.
  Both codecs preserve hashes verbatim with vendor tags
  (`fortios:` on FortiGate, `bcrypt:` on OPNsense) so the loss
  surfaces in the validation report.  Operators must reset
  passwords on the OPNsense target.
- `hash_format`: **lossy** — same root cause; vendor-private form
  on either side.
- `privilege`: **lossy** — FortiGate's named accprofile collapses
  to OPNsense's binary admin / non-admin via group membership:
  super_admin (canonical privilege 15) -> `<groupname>admins</groupname>`,
  other profiles -> `<groupname>users</groupname>`.  Granular
  per-profile detail is lost.
- `role`: **lossy** — FortiGate accprofile name (`prof_admin` /
  custom) preserves through canonical for intra-FortiGate round-trip
  but OPNsense render does not consume it (collapsed to group
  membership).
- FortiGate `set trusthost1...trusthost10`: not modelled on
  canonical; drops on parse.
