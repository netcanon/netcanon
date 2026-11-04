# Local users + hash formats: Aruba AOS-S versus Arista EOS

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

## Arista EOS

Source: [Arista EOS — User Security](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

Arista EOS uses a **named-RBAC role + hashed-secret** model:

```
username admin privilege 15 role network-admin nopassword
username operator privilege 15 role network-admin secret sha512 $6$fakeSalt$fakeHashSha512AbcDef...
username readonly privilege 1 role network-operator secret 5 $1$fakeSalt$fakeMd5Hash...
```

Hash type codes accepted by `secret`:

- `secret 0 <plain>` — plaintext (rejected on `service password-
  encryption` enabled devices).
- `secret 5 <hash>` — MD5 (`$1$...`).
- `secret sha512 <hash>` — SHA-512 crypt (`$6$...`).
- `secret 7 <hash>` — Cisco-7 reversible (rare on EOS).

Arista carries **both** `privilege <N>` (numeric, 1-15) AND `role
<name>` on a single user record — `role` is the source of truth
for Arista's RBAC; `privilege` is a Cisco-compat shim.

## Cross-vendor mapping

The canonical surface is `CanonicalLocalUser(name, privilege_level,
hashed_password, role)`.  Each codec populates the primitive it
owns; cross-vendor translation requires policy:

- Aruba -> Arista: synthesise `privilege_level=15 / role=
  "network-admin"` for AOS-S `role="manager"`; `privilege_level=1
  / role="network-operator"` for AOS-S `role="operator"`.  The
  Arista renderer emits the dual-attribute form
  (`privilege ... role ... secret ...`).

Hash compatibility (the hard limit):

- AOS-S `sha1 <hex>` — Aruba-only.  Arista's `secret` keyword
  accepts `5` (MD5), `7` (Cisco-7), and `sha512`; **no SHA-1
  variant is accepted**.  Cross-vendor migration of a SHA-1-
  hashed user account requires re-setting the password.
- AOS-S `bcrypt $2y$...` — Aruba-only.  Arista does not accept
  bcrypt for `secret`.
- AOS-S `plaintext "<pass>"` — Arista accepts plaintext via
  `secret 0 <pass>` but modern EOS rejects it on devices with
  password-encryption enabled.

Cross-vendor migration of user accounts therefore **requires
re-setting passwords on the target device**.  Both codecs pass
hashes through verbatim; the loss surfaces in the validation
report.

The Aruba synthetic kitchen-sink exercises all three forms
(`sha1` manager, `plaintext` manager-redacted, `sha1` operator)
which all land as opaque `hashed_password` on the canonical record
but **none round-trip clean** to Arista's `secret 5` / `secret
sha512` formats.

Disposition: **lossy** (hash-format incompatibility: SHA-1 /
bcrypt are Aruba-only; Arista's MD5 / SHA-512 are Arista-only;
only the legacy plaintext form survives literally and is
rejected on production devices).
