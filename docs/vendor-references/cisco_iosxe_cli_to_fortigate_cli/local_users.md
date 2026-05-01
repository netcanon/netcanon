# Local users + admin profiles: Cisco IOS-XE versus FortiGate FortiOS

## Cisco IOS-XE

Source: Cisco IOS XE Security Command Reference — `username` command.

Cisco IOS-XE uses numeric privilege levels (1 = exec, 15 = admin):

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

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — System administrators](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system admin`.
Source: FortiOS CLI Reference — `config system admin`.
Retrieved: 2026-04-30

FortiOS uses **named admin profiles** (`accprofile`) rather than
numeric privilege levels.  The built-in profile `super_admin`
grants full control; operator-curated profiles (`prof_admin`,
custom names) carry per-feature scopes.

```
config system admin
    edit "admin"
        set accprofile "super_admin"
        set vdom "root"
        set password ENC <opaque-base64>
    next
    edit "noc"
        set accprofile "prof_admin"
        set vdom "root"
        set password ENC <opaque-base64>
    next
end
```

Notable FortiOS specifics:

- **`ENC` prefix on hashes.**  FortiOS encrypts the password with
  an internal device key; the resulting opaque blob is prefixed
  `ENC` in show output.  The hash format is FortiOS-proprietary
  (not crypt(3) and not Cisco type-9 scrypt).
- **`set vdom`**.  FortiGate's multi-tenancy model gives each admin
  a primary VDOM (Virtual Domain).  Single-VDOM deployments use
  `vdom = "root"`.
- **`config system accprofile`** elsewhere in the config defines
  which capabilities each profile grants.  Out of canonical scope.
- **`set trusthost<N>`**.  Per-admin source-IP allowlist (multiple
  hosts allowed via `trusthost1`, `trusthost2`, ...).  Not modelled
  canonically.

## Cross-vendor mapping (Cisco -> FortiGate)

Canonical surface:

```
class CanonicalLocalUser(BaseModel):
    name: str
    privilege_level: int = 1
    hashed_password: str = ""       # opaque hash, never plaintext
    role: str = ""                  # "manager" / "operator" / "admin" etc.
```

- **name** — `good`.  Direct preservation as the FortiGate edit ID.
- **privilege_level** — `lossy`.  FortiOS has no numeric privilege
  field; the FortiGate codec maps `super_admin` accprofile to
  `privilege_level = 15` and everything else to `1`.  The reverse
  mapping (Cisco -> FortiGate) synthesises `accprofile = super_admin`
  for `privilege_level >= 15` and `accprofile = prof_admin` (or the
  operator-curated default) for lower levels.
- **hashed_password** — `lossy`.  Hash formats are NOT cross-
  compatible:
    - Cisco type-9 scrypt (`$9$...`) is Cisco-only.
    - Cisco type-8 PBKDF2-SHA256 (`$8$...`) is Cisco-only.
    - Cisco type-5 MD5 (`$1$...`) is **not** accepted by FortiOS.
    - FortiOS `ENC <base64>` is FortiOS-only.
  Cross-vendor migration of admin accounts therefore requires
  re-setting passwords on the target device.  Both codecs pass
  hashes through verbatim with vendor tags (`fortios:` prefix on
  the FortiGate side, raw hash on Cisco) so the loss surfaces in
  the validation report rather than silently dropping accounts.
- **role** — `lossy`.  FortiGate's accprofile string lands in
  the canonical `role` field on FortiGate-side parse; cross-vendor
  migration on Cisco -> FortiGate requires synthesising a
  reasonable accprofile name.  The codec defaults to `super_admin`
  for high privilege and `prof_admin` otherwise.

Disposition: **lossy**.  Reason: hash formats are not cross-
compatible (`$9$` / `$8$` / `$1$` versus FortiOS `ENC <base64>`);
RBAC representation requires synthesised accprofile names.
