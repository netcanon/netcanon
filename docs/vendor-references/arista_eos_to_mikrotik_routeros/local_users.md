# Local users: Arista EOS versus MikroTik RouterOS

<!-- an-account-with-no-password -->
> **Update 2026-11-04 — an account with no password is no longer written.**  Up to this change the RouterOS render wrote an account whose source holds no password (an empty secret, or a tag with nothing after it) as `/user add group=<group> name=<name>` with no `password=`, which RouterOS gives an empty password.  It now writes one review comment IN PLACE of the account, under `/user`, `# user "<name>" -- review: no password for this account was read from the source, and an account written for RouterOS without one could log in with none; it is left out: add it on the device with a password, or as an account for remote (RADIUS or TACACS+) login`, and the job carries one warning naming each such account.  Measured on this pair: **3** such accounts across 2 cells (2 on one real capture, 1 on the synthetic kitchen sink).  All 3 used to arrive, and none does now: `local_users` in/out over the 8 cells that populate users goes from **15 / 3** to **15 / 0**.  The other 12 accounts are review lines for a secret RouterOS cannot take, as before.  Any statement below that such an account is written, arrives without a password, or renders `nopassword` describes the render before this change.  Current dispositions are in `tests/fixtures/cross_vendor_expectations/arista_eos__mikrotik_routeros.yaml`.

## Arista EOS

Source: [Arista EOS — User Security](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

```
username admin privilege 15 role network-admin nopassword
username operator privilege 15 role network-admin secret sha512 $6$fakeSalt$fakeHashSha512AbcDefGhiJklMnoPqrStuVwxYz0123456789AbcDefGhiJklMnoPqrStuVwxYz01234
username readonly privilege 1 role network-operator secret 5 $1$fakeSalt$fakeMd5Hash01234
username legacy privilege 7 secret 7 045B0F4D40
```

Arista's local-user model is **two-axis**: a numeric privilege
level (0..15) plus a named role (`network-admin`,
`network-operator`, custom roles).  The conventional admin form
is `privilege 15 role network-admin`.

Password material is stored under the `secret <type> <hash>`
form:

* `secret sha512 $6$...` — Linux-crypt SHA-512 (modern default,
  RFC-compatible)
* `secret 5 $1$...` — Linux-crypt MD5 (legacy)
* `secret 7 ...` — Cisco type-7 reversible obfuscation (legacy)
* `secret 9 $9$...` — scrypt-based (newer EOS releases)
* `nopassword` — explicit no-password account (typically RADIUS-
  authenticated)

The `arista_eos` codec capability matrix lists
`/aaa/authentication/users/user/config/username`, `password`,
and `role` under **supported**.

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)
Retrieved: 2026-05-01

```
/user
add group=full name=admin
add group=write name=operator
add group=read name=auditor
```

Critically, RouterOS does **NOT** surface password material in
`/export verbose` output.  The `add` lines have no password
attribute at all — the password is stored internally in a
vendor-private format and the export omits it.  This is by
design: `/export` is intended to be safely shareable / version-
controllable.

RouterOS's role model is **named groups** (`full` / `write` /
`read` / custom).  Custom groups are defined separately:

```
/user group
add name=audit policy=read,winbox,api
```

Predefined groups:
- `full` — full access (admin)
- `write` — read/write but no policy/user management
- `read` — read-only

## Cross-vendor mapping

The canonical surface is `CanonicalIntent.local_users:
list[CanonicalLocalUser]` with fields `name` / `privilege_level`
/ `hashed_password` / `role`.

Arista -> RouterOS round-trip:

**Role / privilege mapping** — operator-curated:

* Arista `privilege 15 role network-admin` -> RouterOS
  `group=full`
* Arista `privilege 1 role network-operator` -> RouterOS
  `group=read`
* Arista `privilege 7 ...` -> RouterOS `group=write`
  (intermediate privilege levels lack a clean group analogue)
* Custom Arista roles -> RouterOS default `read` with a banner

**Password material** — the structural blocker:

The codec passes the Arista-side hash through the canonical
`hashed_password` field, but RouterOS does not have a wire
syntax for setting a password to a hash.  The codec emits
`/user add group=<grp> name=<name>` with NO password attribute
on the wire and stamps the source hash onto a `comment="orig-
hash:<hash>"` annotation so the operator has it during re-key.

The Arista-side hash formats are NOT cross-compatible with
RouterOS:

* `secret sha512 $6$...` — Linux-crypt SHA-512 — RouterOS does
  NOT store crypt() hashes; the operator must re-set the
  password on the RouterOS target via `/user set <name>
  password=<plaintext>` (which RouterOS internally hashes with
  its own algorithm).
* `secret 5 $1$...` — Linux-crypt MD5 — same story; not
  cross-compatible.
* `secret 7 ...` — Cisco type-7 reversible obfuscation —
  decrypts to plaintext on Arista; the codec could in principle
  decrypt and re-emit as a RouterOS plaintext password, BUT
  shipping plaintext through canonical violates the "never
  plaintext" invariant on `CanonicalLocalUser.hashed_password`.
  Operator must manually decrypt + re-set.
* `nopassword` — Arista's explicit no-password marker — RouterOS
  has no equivalent; the codec emits `/user add ...` with no
  password and a banner.

**Net result:** operator MUST set passwords manually on the
RouterOS target after migration.  The cross-vendor migration
preserves the username + group mapping but not the secret.

The Arista synthetic kitchen-sink (`ks-leaf-01`) carries three
test users (admin/operator/readonly).  All three lift to
canonical with their hashes preserved; all three render to
RouterOS without password material.

Disposition: **lossy** — see the YAML for the per-field break-
down.
