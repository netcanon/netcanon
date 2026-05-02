# Local users: OPNsense versus Arista EOS

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
      <password>$2b$10$fakeAJhashRootAccountPlaceholderObviouslySyntheticAaaaa</password>
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

OPNsense user-account notes:

- Hashes are bcrypt (`$2a$` / `$2b$` / `$2y$` prefixes).
  OPNsense rejects non-bcrypt forms via the FreeBSD `crypt(3)`
  backend.
- Privilege is binary: `<groupname>admins</groupname>` =
  full admin (mapped to canonical privilege 15);
  `<groupname>users</groupname>` (or other) = operator-class.
- The opnsense codec round-trips users via `<system><user>`
  blocks (parse + render); capability matrix lists
  `/aaa/authentication/users/user/config/{username,password,role}`
  supported.

## Arista EOS

Source: [Arista EOS User Manual — User Security](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

```
username admin privilege 15 role network-admin nopassword
username operator privilege 15 role network-admin secret sha512 $6$fakeSalt$fakeHashSha512AbcDef...
username readonly privilege 1 role network-operator secret 5 $1$fakeSalt$fakeMd5Hash01234
```

Arista user-account notes:

- `username <name> privilege <0-15> role <name> secret <type>
  <hash>`.
- Hash types accepted: `5` (`$1$` MD5-crypt), `sha512` (`$6$`
  SHA-512-crypt), `0` (plaintext, never persisted in show).
- Bcrypt (`$2a$` / `$2b$` / `$2y$`) is NOT a supported `secret`
  type on Arista EOS — the CLI parser rejects it.
- Privilege 15 = full admin; 1 = read-only by convention.

## Cross-vendor mapping (OPNsense -> Arista EOS)

Canonical fields (`CanonicalLocalUser`).

- `local_users[].name`: **good**.
- `local_users[].privilege_level`: **lossy** — OPNsense's
  binary group → privilege 15 / 1 collapse maps directly to
  Arista's privilege 15 / 1 endpoints.  Mid-range privileges
  that downstream Arista re-import might want to populate (5,
  10, etc.) are unrecoverable.
- `local_users[].hashed_password`: **lossy** — OPNsense bcrypt
  hashes are NOT accepted by Arista's `secret` parser; the
  cross-pair fails on apply and operators reset the password.
  Both codecs pass hashes verbatim per canonical doctrine; loss
  surfaces in the validation report.
- `local_users[].role`: **lossy** — OPNsense `<groupname>`
  (admins / users) collapses to Arista's `network-admin` /
  `network-operator` mapping (codec convention).  The richer
  Arista role-naming surface (custom roles) is unreachable from
  an OPNsense source.
