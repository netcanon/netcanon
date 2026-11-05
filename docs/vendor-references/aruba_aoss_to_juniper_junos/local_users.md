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
