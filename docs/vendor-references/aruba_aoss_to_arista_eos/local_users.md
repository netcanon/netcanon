# Local users + hash formats: Aruba AOS-S versus Arista EOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has a **fixed two-role local-user model**: `manager` (full
admin) and `operator` (read-mostly).  Verbatim manual shape:

```
password manager user-name "admin" sha1 a1b2c3...
password operator user-name "noc" plaintext "S0meP4ss"
password operator user-name "tech" sha1 deadbeef...
password manager user-name "ops-team" bcrypt $2y$10$...
```

Hash forms accepted (the codec's parse module stores any of these
opaque):

- `plaintext "<pass>"` — literal plaintext (codec preserves
  verbatim per the canonical schema doctrine; operator must
  re-hash on import).
- `sha1 <hex>` — SHA-1 hash with AOS-S-specific salt mechanics.
- `bcrypt $2y$...` — newer firmware (16.11+) introduces bcrypt.

There is **no numeric privilege level** — the role is named
(manager / operator).

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
