# Local users + hash formats: Cisco IOS-XE versus Arista EOS

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
- `secret 9` — scrypt, `$9$...`  (modern Cisco default)
- `password 7` — type-7 reversible (legacy plaintext recovery)

## Arista EOS

Source: [EOS 4.36.0F — User Security](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-04-30

Arista uses `role <name>` (named RBAC roles, not numeric privilege
levels):

```
username admin role network-admin secret sha512 $6$saltsalt$hashash...
username noc role network-operator secret 5 $1$abc$xyzdef...
username monitor role monitor nopassword
```

Hash type codes (verbatim from the EOS manual):

- Type 0 — plaintext (default if `encrypt-type` omitted)
- Type 5 — MD5-encrypted hash, `$1$<salt>$<hash>` form
- Type 7 — proprietary encrypted string
- `sha512` — SHA-512-encrypted strings, `$6$<salt>$<hash>` form

EOS supports `nopassword` to create a username with no password.

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
`role` (Arista's primitive); each codec populates the one it owns and
defaults the other.  Cross-vendor translation requires policy:

- Cisco -> Arista: synthesise a `role` from `privilege_level` (15 =
  network-admin, 1 = network-operator, intermediate maps to operator).
  Arista's role names are not standardised across organisations, so
  this is best-effort.

- Arista -> Cisco: synthesise a `privilege_level` from `role`
  (network-admin = 15, others = 1 unless explicitly mapped).

Hash compatibility is the hard limit:

- MD5 type-5 (`$1$...`) — cross-compatible (both vendors accept the
  same format).
- Cisco type-9 scrypt (`$9$...`) — Cisco-only.  Arista cannot import.
- Arista sha512 (`$6$...`) — Arista-only.  Cisco accepts type-8 PBKDF2
  but NOT raw sha512 crypt.

Cross-vendor migration of user accounts therefore requires re-setting
passwords on the target device.  Both codecs pass through opaque
hashes verbatim per the schema doctrine ("codecs preserve whatever
opaque hash / encrypted blob the source emitted") so the loss surfaces
in the validation report rather than silently dropping accounts.

Disposition: **lossy**.  Reason: hash formats are not cross-compatible
between Cisco scrypt/PBKDF2 and Arista sha512-crypt.  RBAC
representation also requires operator-curated mapping
(`privilege_level` <-> `role`).
