# Local users: Arista EOS versus OPNsense

## Arista EOS

Source: [Arista EOS User Manual — User Security](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

```
username admin privilege 15 role network-admin nopassword
username operator privilege 15 role network-admin secret sha512 $6$fakeSalt$fakeHashSha512AbcDef...
username readonly privilege 1 role network-operator secret 5 $1$fakeSalt$fakeMd5Hash01234
```

Arista user-account notes:

- `username <name> privilege <0-15> role <name> secret
  <type> <hash>` is the canonical wire form.
- Hash types accepted by `secret <type>`:
  - `5` — MD5-crypt (`$1$` prefix), oldest, deprecated but
    accepted.
  - `sha512` — SHA-512-crypt (`$6$` prefix), the recommended
    default on recent EOS.
  - `0` — plaintext (typed once, never persisted in
    show-running output).
- The role token (`network-admin`, `network-operator`, custom
  roles) is informational; canonical
  `CanonicalLocalUser.role` carries it verbatim.
- Privilege 15 = full admin; 1 = read-only by convention.

The arista_eos codec passes whatever opaque hash / blob the source
carried directly through to the canonical
`CanonicalLocalUser.hashed_password`.

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
  </system>
</opnsense>
```

OPNsense user model:

- Hashes are bcrypt (`$2a$` / `$2b$` / `$2y$` prefixes).
  OPNsense rejects non-bcrypt forms (SHA-512-crypt, MD5-crypt,
  plaintext) on apply via the FreeBSD `crypt(3)` backend's
  allowed-prefix list.
- Role is conveyed via `<groupname>` membership.  The privilege
  surface is binary: `admins` group = full admin; any other
  group = operator-class.

## Cross-vendor mapping (Arista -> OPNsense)

Canonical fields (`CanonicalLocalUser`):

```
name: str
privilege_level: int
hashed_password: str
role: str
```

- `local_users[].name`: **good**.
- `local_users[].privilege_level`: **lossy** — Arista's 0-15
  range collapses to OPNsense's binary admin / non-admin via
  group membership: privilege ≥ 15 →
  `<groupname>admins</groupname>`, otherwise
  `<groupname>users</groupname>` (or similar).  Mid-range
  privileges (5-14) do not survive.
- `local_users[].hashed_password`: **lossy** — Arista's `$1$`
  (MD5-crypt) and `$6$` (SHA-512-crypt) hashes are NOT bcrypt
  and OPNsense will reject them on apply.  Operators must reset
  passwords on the OPNsense target.  Both codecs pass hashes
  verbatim per canonical doctrine; loss surfaces in the
  validation report.
- `local_users[].role`: **lossy** — Arista's `network-admin` /
  `network-operator` / custom-role names collapse to OPNsense's
  binary group membership; the role text drops.
