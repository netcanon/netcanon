# Local users + admin profiles: Aruba AOS-S versus FortiGate FortiOS

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has a **fixed two-role local-user model**: `manager` (full
admin) and `operator` (read-mostly):

```
password manager user-name "admin" sha1 "fa1cefa1cefa1cefa1cefa1cefa1cefa1cefa1ce"
password manager user-name "siteops" plaintext "fakeRedactedPlaintext"
password operator user-name "monitor" sha1 "0bce0bce0bce0bce0bce0bce0bce0bce0bce0bce"
```

Hash forms accepted:

- `plaintext "<pass>"` — literal plaintext (codec stores as-is per
  the canonical schema doctrine that codecs preserve whatever
  opaque blob the source emitted).
- `sha1 <hex>` — SHA-1-based hash.  AOS-S-specific salting; not
  cross-compatible with the Linux crypt() family or FortiOS
  internal-key encryption.
- `bcrypt $2y$...` — newer firmware (16.11+) introduces bcrypt
  support.  Stored verbatim.

There is **no numeric privilege level** — the role is named.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Administrators](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

FortiGate uses **named accprofile strings** for RBAC.  Built-in
profiles include `super_admin` (full read/write),
`super_admin_readonly` (full read-only), `prof_admin` (operator-
class), plus operator-curated custom profiles via `config system
accprofile`:

```
config system admin
    edit "admin"
        set accprofile "super_admin"
        set password ENC fakeAdminHashEEEEEEEEEEEEEE==
        set trusthost1 10.0.0.0 255.255.0.0
    next
    edit "netops"
        set accprofile "prof_admin"
        set password ENC fakeNetopsHashFFFFFFFFFFFFFF==
        set trusthost1 10.50.0.0 255.255.255.0
    next
end
```

Hash form: **`ENC <opaque-base64>`** — FortiOS encrypts secrets
with an internal device-keyed cipher.  The format is FortiGate-only
and is NOT cross-compatible with Aruba SHA-1 / bcrypt.

Trusthost / IP-based access controls (`set trusthost1` ..
`set trusthost10`) are FortiGate-specific and not modelled in
canonical.

## Cross-vendor mapping (Aruba -> FortiGate)

Canonical surface:

```
class CanonicalLocalUser(BaseModel):
    name: str
    privilege_level: int = 1
    hashed_password: str = ""
    role: str = ""
```

The model carries both `privilege_level` (Cisco's primitive) and
`role` (Aruba's primitive).  Aruba's two-role model maps to
FortiGate's accprofile strings:

- Aruba `manager` -> FortiGate `super_admin` (privilege 15
  shorthand).
- Aruba `operator` -> FortiGate `prof_admin` (privilege 1
  shorthand for operator-class).

Hash compatibility is the hard limit:

- AOS-S SHA-1 (`<hex>`) — Aruba-only; FortiOS rejects.
- AOS-S bcrypt (`$2y$...`) — Aruba-only; FortiOS rejects.
- FortiOS `ENC <base64>` — FortiGate-only; not Aruba-accepted.

Cross-vendor migration of admin accounts therefore requires
re-setting passwords on the target device.  Both codecs pass
hashes through verbatim; the loss surfaces in the validation
report.

Trusthost rules (`set trusthost1` ...) drop entirely on Aruba
source -> FortiGate target (Aruba carries no equivalent intent).

Disposition: **lossy**.  Reason: hash-format incompatibility +
RBAC model translation (named two-role -> named-accprofile-string)
require operator review and password-reset on cross-vendor
migration.
