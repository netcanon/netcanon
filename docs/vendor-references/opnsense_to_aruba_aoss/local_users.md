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
password operator user-name "monitor" sha1 "0bce0bce0bce0bce0bce0bce0bce0bce0bce0bce"
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

Aruba user model:

- Two roles: `manager` (full admin) and `operator` (read-only).
- Hash formats: `sha1 "<40-hex>"`, `sha256 "<64-hex>"`,
  `plaintext "<plaintext>"`; no bcrypt form.

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
  (`$2y$` / `$2b$`) is not a form AOS-S takes (`plaintext`, `sha1`,
  `sha256`; HPE Access Security Guide, AOS-S 16.x), so each such
  account is a `review:` comment naming it, in place of the account,
  and its password is set again on the switch.
- `local_users[].role`: **lossy** — Aruba two-role keyword
  collapse, identical to the privilege mapping above.
