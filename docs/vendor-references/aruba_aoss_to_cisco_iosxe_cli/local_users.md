# Local users + hash formats: Aruba AOS-S versus Cisco IOS-XE

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

## Cisco IOS-XE

Source: Cisco IOS XE Security Command Reference — `username` command.

Cisco IOS uses `privilege <N>` for RBAC (1 = exec, 15 = admin):

```
username admin privilege 15 secret 9 $9$ABCDEFGH$abcdef0123...
username noc privilege 5 secret 5 $1$abc$xyzdef...
```

Hash type codes:

- `secret 5` — MD5 hash (`$1$...`).
- `secret 8` — PBKDF2-SHA256 (`$8$...`).
- `secret 9` — scrypt (`$9$...`, modern Cisco default).

## Cross-vendor mapping

The canonical surface is `CanonicalLocalUser(name, privilege_level,
hashed_password, role)`.  Each codec populates the primitive it
owns; cross-vendor translation requires policy:

- Aruba -> Cisco: synthesise `privilege_level=15` for
  `role="manager"`, else `privilege_level=1` for
  `role="operator"`.

Hash compatibility (the hard limit):

- AOS-S SHA-1 (`<hex>`) — Aruba-only.  Cisco accepts no SHA-1
  form for `secret`.
- AOS-S bcrypt (`$2y$...`) — Aruba-only.  Cisco does not accept
  bcrypt for `secret`.
- AOS-S `plaintext "<pass>"` — Cisco accepts plaintext via
  `secret 0 <pass>` but modern Cisco refuses plaintext at write
  time; the literal string lands but a `secret 0` line will fail
  validation on `service password-encryption` enabled devices.

Cross-vendor migration of user accounts therefore requires
re-setting passwords on the target device.  Both codecs pass
hashes through verbatim; the loss surfaces in the validation
report.

Disposition: **lossy** (hash-format incompatibility + role
expansion from two-role to numeric privilege).
