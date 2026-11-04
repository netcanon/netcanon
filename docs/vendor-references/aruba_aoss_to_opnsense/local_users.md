# Local users: Aruba AOS-S versus OPNsense

## Aruba AOS-S

AOS-S has two kinds of local account (HPE Access Security Guide,
AOS-S 16.x).

**The manager account and the operator account**, one of each.  A
line sets the account of its role and names it; a second line of a
role re-points the same account, so the switch keeps the last:

```
password manager user-name "admin" sha1 "<40 hex digits>"
password operator user-name "noc" sha1 "<40 hex digits>"
```

`user-name` may be left out (the names are then `manager` and
`operator`), and a terminal can wrap the quoted hash onto the next
line.  Without `include-credentials` the switch prints neither name
nor hash: a bare `password manager` or `password operator` says only
that the role has a password.  The forms the switch takes are
`plaintext`, `sha1` and `sha256`; there is no bcrypt form, and a
`plaintext` password is never printed, the switch storing a hash.

**Local users** beside them, up to 100, each in an authorization group
and set from the CLI:

```
aaa authentication local-user "admin2" group "Level-15" password sha1 "<40 hex digits>"
aaa authentication local-user "admin2" group "Level-15"
```

(the second as the switch prints it without `include-credentials`).
The switch's own groups `Level-0` to `Level-15` stand for a level's
rights: `Level-15` has the manager's, `Level-1` the operator's.  What
any other group allows is in its `aaa authorization group` rules.

What the parser reads (since 2026-11-04): the last line of each role,
as the switch does, and an earlier one in a row of
`dropped_tier3_sections`; a bare marker as an account of the role's
default name that holds no secret, which every target writes as a
review comment in place of an account; and each local user, at the
privilege level of its `Level-N` group, or at 1 in any other group
(said in a row), with no `role`.  The manager is privilege 15, the
operator 1, and the two come first in the tree.  What the sections
below say of a bcrypt AOS-S form, or of a hash carried verbatim onto
another vendor, describes an earlier reading: a hash the target cannot
take is a review comment in place of the account, and the current
dispositions are in the pair's expectation YAML under
`tests/fixtures/cross_vendor_expectations/`.

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
  bcrypt, or plaintext are NOT all cross-compatible with what OPNsense
  accepts (bcrypt, and SHA-512 crypt since #462).  Bcrypt-shape hashes from a recent Aruba
  firmware MIGHT round-trip if the prefix matches; plaintext (which
  Aruba accepts on the wire) and SHA-1 hex will be rejected on apply.
  Operators typically reset passwords on the OPNsense target.  Both
  codecs pass hashes verbatim per canonical doctrine; loss surfaces
  in the validation report.
- `local_users[].role`: **lossy** — Aruba `manager` / `operator` ↔
  OPNsense `<groupname>admins</groupname>` / `users`.  Direct enum
  collapse; cross-pair render emits the OPNsense form based on
  privilege.
