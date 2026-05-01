# Local users + hash formats: Aruba AOS-S versus Cisco IOS-XE

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

There is **no numeric privilege level** — the role is named.

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
