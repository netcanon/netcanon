# Local users: Aruba AOS-S versus OPNsense

## Aruba AOS-S

Source: [Aruba AOS-S 16.10 Access Security Guide — Local
manager / operator](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

```
password manager user-name "admin" sha1 "fa1cefa1cefa1cefa1cefa1cefa1cefa1cefa1ce"
password manager user-name "siteops" plaintext "fakeRedactedPlaintext"
password operator user-name "monitor" sha1 "0bce0bce0bce0bce0bce0bce0bce0bce0bce0bce"
```

Aruba AOS-S role model:

- Two roles only: `manager` (full admin) and `operator` (read-only
  / limited).  No numeric privilege levels.
- Hash formats accepted by the password directive:
  - `sha1 "<40-hex>"` — the standard form.
  - `bcrypt "$2y$..."` — newer firmware.
  - `plaintext "<plaintext>"` — typically redacted in saved configs
    but accepted on the wire (codec preserves verbatim).
- The aruba_aoss codec passes whatever opaque hash / blob the source
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

- Hashes are bcrypt (`$2a$` / `$2b$` / `$2y$` prefixes).  OPNsense
  rejects non-bcrypt forms (SHA-1, MD5-crypt, plaintext) on apply
  via the FreeBSD `crypt(3)` backend's allowed-prefix list.
- Role is conveyed via `<groupname>` membership.  The privilege
  surface is binary (admins → full admin via `page-all` privilege;
  any other group → operator-class).  The opnsense codec maps
  `groupname=admins` → privilege 15 on parse; render writes
  `<groupname>admins</groupname>` for privilege ≥ 15 and
  `<groupname>users</groupname>` (or similar) for any lower
  privilege.

## Cross-vendor mapping

Canonical fields (`CanonicalLocalUser`):

```
name: str
privilege_level: int       # 1-15 nominally; vendor-specific
hashed_password: str       # opaque, never plaintext
role: str
```

Aruba -> OPNsense:

- `local_users[].name`: **good**.
- `local_users[].privilege_level`: **lossy** — Aruba's manager →
  privilege 15, operator → privilege 1 (an in-codec convention).
  OPNsense maps privilege ≥ 15 → `<groupname>admins</groupname>`
  and otherwise → `<groupname>users</groupname>`.  Information is
  preserved across the round-trip but the intermediate-privilege
  granularity that Cisco-style sources carry has no Aruba
  equivalent in the first place.
- `local_users[].hashed_password`: **lossy** — Aruba SHA-1 hex,
  bcrypt, or plaintext are NOT all cross-compatible with OPNsense's
  bcrypt-only acceptance.  Bcrypt-shape hashes from a recent Aruba
  firmware MIGHT round-trip if the prefix matches; plaintext (which
  Aruba accepts on the wire) and SHA-1 hex will be rejected on apply.
  Operators typically reset passwords on the OPNsense target.  Both
  codecs pass hashes verbatim per canonical doctrine; loss surfaces
  in the validation report.
- `local_users[].role`: **lossy** — Aruba `manager` / `operator` ↔
  OPNsense `<groupname>admins</groupname>` / `users`.  Direct enum
  collapse; cross-pair render emits the OPNsense form based on
  privilege.
