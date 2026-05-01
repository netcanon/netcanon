# Local users + hash formats: Arista EOS versus Aruba AOS-S

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
<name>` on a single user record.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has a **fixed two-role local-user model**: `manager`
(full admin) and `operator` (read-mostly):

```
password manager user-name "admin" sha1 a1b2c3...
password operator user-name "noc" plaintext "S0meP4ss"
password manager user-name "ops-team" bcrypt $2y$10$...
```

Hash forms accepted:

- `plaintext "<pass>"`
- `sha1 <hex>` (AOS-S-specific salt mechanics)
- `bcrypt $2y$...` (newer firmware)

There is **no numeric privilege level** — the role is named
(manager / operator).  No SHA-512 / SHA-256 / MD5 forms.

## Cross-vendor mapping

The canonical surface is `CanonicalLocalUser(name, privilege_level,
hashed_password, role)`.

Arista -> Aruba round-trip:

- Role mapping policy: Arista `role="network-admin"` (or any
  `privilege >= 15`) -> Aruba `role="manager"`; everything else
  -> Aruba `role="operator"`.  Numeric privilege is dropped on
  the Aruba target (no canonical home for granular Cisco
  1..15 privileges).

Hash compatibility (the hard limit):

- Arista `secret 5 $1$...` (MD5) — Arista-only on the canonical
  layer; Aruba does not accept MD5 for the `password` directive.
- Arista `secret sha512 $6$...` (SHA-512 crypt) — Arista-only;
  Aruba does not accept SHA-512.  This is the most common Arista
  default in modern EOS, so it bites every migration.
- Arista `secret 7 $...` (Cisco-7 reversible) — Cisco/Arista-
  only; Aruba does not accept type-7.
- Aruba's SHA-1 / bcrypt hash types are Aruba-only on the wire.

Cross-vendor migration of user accounts therefore **requires
re-setting passwords on the target device**.  Both codecs pass
hashes through verbatim; the loss surfaces in the validation
report.

The Arista kitchen-sink exercises:

```
username admin privilege 15 role network-admin nopassword
username operator privilege 15 role network-admin secret sha512 $6$fakeSalt$fakeHashSha512...
username readonly privilege 1 role network-operator secret 5 $1$fakeSalt$fakeMd5Hash...
```

— `admin` (nopassword) and `readonly` (privilege=1, MD5) emit
without secret on Aruba (or with `plaintext ""` placeholder which
is rejected); `operator` (privilege=15, SHA-512) requires
re-keying.

Disposition: **lossy** (hash-format incompatibility on every
modern Arista hash; Cisco-style `privilege` semantic collapses to
Aruba's two-role enum; SHA-512 the dominant case requires
re-keying).
