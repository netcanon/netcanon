# Local users: OPNsense versus Aruba AOS-S

## OPNsense

Source: [OPNsense Users manual](https://docs.opnsense.org/manual/users.html)
Retrieved: 2026-04-30

```xml
<opnsense>
  <system>
    <user>
      <name>root</name>
      <descr>System Administrator</descr>
      <scope>system</scope>
      <groupname>admins</groupname>
      <password>$2b$10$fakeAJhashRootAccountPlaceholder...</password>
      <uid>0</uid>
    </user>
    <user>
      <name>readonly</name>
      <scope>user</scope>
      <groupname>users</groupname>
      <password>$2b$10$fakeAJhashReadonly...</password>
      <uid>2001</uid>
    </user>
  </system>
</opnsense>
```

OPNsense user model:

- Bcrypt hashes only (`$2a$` / `$2b$` / `$2y$` prefixes).
- Role via `<groupname>` membership.  The opnsense codec maps
  `groupname=admins` → `CanonicalLocalUser.privilege_level = 15` on
  parse; any other group → privilege 1.

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Access Security Guide](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
password manager user-name "admin" sha1 "fa1cefa1cefa1cefa1cefa1cefa1cefa1cefa1ce"
password manager user-name "siteops" plaintext "fakeRedactedPlaintext"
password operator user-name "monitor" sha1 "0bce0bce0bce0bce0bce0bce0bce0bce0bce0bce"
```

Aruba user model:

- Two roles: `manager` (full admin) and `operator` (read-only).
- Hash formats: `sha1 "<40-hex>"`, `bcrypt "$2y$..."`,
  `plaintext "<plaintext>"`.

## Cross-vendor mapping

Canonical fields (`CanonicalLocalUser`):

```
name, privilege_level, hashed_password, role
```

OPNsense -> Aruba:

- `local_users[].name`: **good**.
- `local_users[].privilege_level`: **lossy** — OPNsense privilege
  ≥ 15 → Aruba `manager`, anything lower → Aruba `operator`.
  OPNsense's binary admin / non-admin model is structurally similar
  to Aruba's two-role surface, so loss is minimal in practice;
  intermediate Cisco-style privilege levels never surfaced from
  OPNsense in the first place.
- `local_users[].hashed_password`: **lossy** — OPNsense bcrypt
  (`$2y$` / `$2b$`) MAY be accepted by recent Aruba firmware (16.11+
  with bcrypt support); older AOS-S firmware accepts only SHA-1
  hex.  Cross-pair render passes the bcrypt blob verbatim and
  operators verify on apply.  If the target Aruba doesn't accept
  bcrypt, password reset is required.
- `local_users[].role`: **lossy** — Aruba two-role keyword
  collapse, identical to the privilege mapping above.
