# Local users + hash formats: Cisco IOS-XE versus Aruba AOS-S

## Cisco IOS-XE

Source: Cisco IOS XE Security Command Reference — `username` command.

Cisco IOS uses `privilege <N>` for RBAC (1 = exec, 15 = admin):

```
username admin privilege 15 secret 9 $9$ABCDEFGH$abcdef0123...
username noc privilege 5 secret 5 $1$abc$xyzdef...
username readonly privilege 1 password 7 0822455D0A16
```

Hash type codes:

- `secret 0` — plaintext (forbidden in modern configs)
- `secret 5` — MD5 hash, `$1$<salt>$<hash>` form
- `secret 7` — type-7 reversible (vigenere); not used for `secret`
- `secret 8` — PBKDF2-SHA256, `$8$...`
- `secret 9` — scrypt, `$9$...` (modern Cisco default)
- `password 7` — type-7 reversible (legacy plaintext recovery)

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has a fixed two-role local-user model: `manager` (full admin)
and `operator` (read-mostly).  Verbatim manual shape:

```
password manager user-name "admin" sha1 a1b2c3...
password operator user-name "noc" plaintext "S0meP4ss"
password operator user-name "tech" sha1 deadbeef...
```

Hash forms accepted:

- `plaintext "<pass>"` — literal plaintext (codec stores as-is per
  the canonical schema doctrine that codecs preserve whatever
  opaque blob the source emitted; operator must re-hash on import).
- `sha1 <hex>` — SHA-1-based hash.  AOS-S-specific salting; not
  cross-compatible with the Linux crypt() family.
- `bcrypt $2y$...` — newer firmware introduces bcrypt support
  (manual: "Aruba ArubaOS-Switch 16.11 release notes").  Stored
  verbatim; not cross-compatible with Cisco type-9 scrypt.

There is **no** numeric privilege level — the role is named.

## Cross-vendor mapping

The canonical surface is `CanonicalLocalUser`:

```
class CanonicalLocalUser(BaseModel):
    name: str
    privilege_level: int = 1   # vendor-specific; 15 = admin on Cisco
    hashed_password: str = ""  # opaque hash, never plaintext
    role: str = ""             # "manager" / "operator" / "admin" etc.
```

The model carries both `privilege_level` (Cisco's primitive) and
`role` (Aruba's primitive); each codec populates the one it owns and
defaults the other.  Cross-vendor translation requires policy:

- Cisco -> Aruba: synthesise `role="manager"` if
  `privilege_level >= 15`, else `role="operator"`.  Aruba has only
  the two named roles, so all intermediate Cisco privilege levels
  collapse to operator.
- Aruba -> Cisco: synthesise `privilege_level=15` for
  `role="manager"`, else `privilege_level=1` for `role="operator"`.

Hash compatibility is the hard limit:

- Cisco type-9 scrypt (`$9$...`) — Cisco-only.
- Cisco type-8 PBKDF2 (`$8$...`) — Cisco-only.
- Cisco / shared MD5 type-5 (`$1$...`) — Linux-crypt format; AOS-S
  does NOT advertise the type-5 form (manual lists only
  `plaintext` / `sha1` / `bcrypt`).  Carrying a Cisco `$1$` hash to
  Aruba via the codec produces a string AOS-S won't authenticate
  against without re-hashing.
- AOS-S SHA-1 (`<hex>`) — Aruba-only; Cisco accepts no SHA-1 form
  for `secret`.
- AOS-S bcrypt (`$2y$...`) — Aruba-only.

Cross-vendor migration of user accounts therefore requires
re-setting passwords on the target device.  Both codecs pass
hashes through verbatim; the loss surfaces in the validation
report.

Disposition: **lossy** (hash-format incompatibility + RBAC
collapse from numeric privilege to two-role model).
