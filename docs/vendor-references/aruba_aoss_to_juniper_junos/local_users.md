# Local users + hash formats: Aruba AOS-S versus Juniper Junos

How local user accounts and password hashes are declared on each
platform.

Sources:
- Aruba: https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm (retrieved 2026-05-01)
- Juniper: https://www.juniper.net/documentation//us/en/software/junos/cli-reference/topics/ref/statement/password-edit-system-login.html (retrieved 2026-05-01)
- Juniper: https://kb.juniper.net/InfoCenter/index?page=content&id=KB31903 (retrieved 2026-05-01)

Citation ids: `aruba-user-security`, `junos-password-cli`,
`junos-kb-password-format`.

## Aruba AOS-S form

AOS-S has a fixed two-role local-user model: `manager` (full admin)
and `operator` (read-mostly):

```
password manager user-name "admin" sha1 a1b2c3...
password manager user-name "siteops" plaintext "fakeRedactedPlaintext"
password operator user-name "monitor" sha1 0bce0bce...
password manager user-name "ops-team" bcrypt $2y$10$...
```

Hash forms accepted:

- `plaintext "<pass>"` — literal plaintext (codec preserves verbatim;
  operator must re-hash on import).
- `sha1 <hex>` — SHA-1 hash with AOS-S-specific salt mechanics.
- `bcrypt $2y$...` — newer firmware (16.11+) introduces bcrypt.

There is **no numeric privilege level** — the role is named.

## Junos form

Junos uses `system login user <name>` with class-based RBAC and
crypt-style hashed-password or SSH public-key authentication:

```
set system login user admin uid 2000
set system login user admin class super-user
set system login user admin authentication encrypted-password "$6$fakeAdmin$fakeAdminHash..."
set system login user operator class operator
set system login user operator authentication encrypted-password "$6$fakeOp$fakeOpHash..."
set system login user readonly class read-only
set system login user readonly authentication ssh-rsa "ssh-rsa AAAAB3Nz..."
```

Class tokens: `super-user`, `operator`, `read-only`, `unauthorized`,
plus operator-defined classes via `set system login class`.  Hash
formats: `$1$` (MD5, legacy), `$5$` (SHA-256), `$6$` (SHA-512;
default since 17.2 per KB31903), and SHA-1 / scrypt variants.
SSH-RSA / SSH-DSA / SSH-ED25519 public keys live under
`authentication ssh-<algo> "<key>"`.

## Cross-vendor mapping

The canonical surface is `CanonicalLocalUser(name, privilege_level,
hashed_password, role)`.  Each codec populates the primitive it owns;
cross-vendor translation requires policy.

Aruba -> Junos role mapping (codec policy):

* Aruba `role="manager"` -> Junos `class super-user`.
* Aruba `role="operator"` -> Junos `class operator`.

Hash compatibility (the hard limit):

- AOS-S SHA-1 (`<hex>`) — Aruba-only.  Junos rejects on
  `authentication encrypted-password`.
- AOS-S `bcrypt $2y$...` — Aruba-only.  Junos does not accept bcrypt
  on `encrypted-password`.
- AOS-S `plaintext "<pass>"` — Junos's `set system login user X
  authentication plain-text-password` accepts plaintext interactively
  but the configuration form requires `encrypted-password` with a
  pre-hashed crypt() value, so a literal plaintext string cannot
  cross.
- Junos `$1$` / `$5$` / `$6$` crypt hashes — Junos-side only; Aruba
  source never produces these.

Cross-vendor migration of user accounts therefore requires re-setting
passwords on the target device.  Both codecs pass hashes through
verbatim; the loss surfaces in the validation report.

The numeric `privilege_level` field on canonical is Cisco-shaped;
both Aruba and Junos use named roles / classes, so the field is
typically empty on parse for these codecs.

Disposition: **lossy** (hash-format incompatibility + role token
mapping).
