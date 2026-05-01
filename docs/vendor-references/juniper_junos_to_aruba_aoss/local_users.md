# Local users + hash formats: Juniper Junos versus Aruba AOS-S

How local user accounts and password hashes are declared on each
platform.

Sources:
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html (retrieved 2026-05-01)
- Juniper: https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903 (retrieved 2026-05-01)
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm (retrieved 2026-05-01)

Citation ids: `junos-password-cli`, `junos-kb-password-format`,
`aruba-user-security`.

## Junos form

```
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$fakeAdmin$..."
set system login user operator class operator
set system login user operator authentication encrypted-password "$6$fakeOp$..."
set system login user readonly class read-only
set system login user readonly authentication ssh-rsa "ssh-rsa AAAAB3Nz..."
```

Class tokens: `super-user`, `operator`, `read-only`, `unauthorized`,
plus operator-defined classes via `set system login class`.

Hash formats accepted on `encrypted-password`:

- `$1$` — MD5 crypt (legacy).
- `$5$` — SHA-256 crypt.
- `$6$` — SHA-512 crypt (default since Junos 17.2 per KB31903).
- Older firmware accepts `$sha1$` / scrypt forms with version
  caveats.

SSH public-key authentication via `authentication ssh-rsa`,
`ssh-dsa`, `ssh-ed25519`.

## Aruba AOS-S form

Two-role local-user model with quoted user-name:

```
password manager user-name "admin" sha1 a1b2c3...
password manager user-name "siteops" plaintext "fakeRedactedPlaintext"
password operator user-name "monitor" sha1 0bce0bce...
password manager user-name "ops-team" bcrypt $2y$10$...
```

Hash forms: `plaintext "<pass>"`, `sha1 <hex>`, `bcrypt $2y$...`.
Roles: `manager` (admin) and `operator` (read-mostly) only.

## Cross-vendor mapping

The canonical surface is `CanonicalLocalUser(name, privilege_level,
hashed_password, role)`.

Junos -> Aruba role mapping (codec policy):

* Junos `class super-user` -> Aruba `role="manager"`.
* Junos `class operator` -> Aruba `role="operator"`.
* Junos `class read-only` -> Aruba `role="operator"` (closest
  approximation; Aruba has no first-class read-only role distinct
  from operator).
* Junos operator-defined classes (`set system login class <X>
  permissions ...`) -> Aruba `role="operator"` with a comment
  indicating the original class name.  Aruba RBAC cannot replicate
  per-class permission sets.

Hash compatibility (the hard limit):

- Junos `$1$` MD5 — Aruba does not accept `$1$` on the `password
  manager`/`password operator` form.
- Junos `$5$` SHA-256 — Aruba-incompatible.
- Junos `$6$` SHA-512 (the modern default) — Aruba-incompatible.
- Junos SSH-RSA / SSH-DSA / SSH-ED25519 keys — Aruba AOS-S accepts
  SSH public keys via `aaa authentication local-user / ssh-publickey`
  (a separate plumbing path); the canonical
  `CanonicalLocalUser.hashed_password` field is hash-shaped, so SSH
  keys parse-and-ignore on Junos source today (lossy by deferral).

Cross-vendor migration of user accounts therefore requires
re-setting passwords on the target device.  Both codecs pass hashes
through verbatim; the loss surfaces in the validation report.

Disposition: **lossy** (hash incompatibility + Junos-only class
diversity collapses to Aruba's two-role model).
