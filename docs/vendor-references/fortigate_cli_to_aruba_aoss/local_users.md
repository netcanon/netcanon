# Local users + admin profiles: FortiGate FortiOS versus Aruba AOS-S

This is the reverse-direction sibling of
[`../aruba_aoss_to_fortigate_cli/local_users.md`](../aruba_aoss_to_fortigate_cli/local_users.md).

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — Administrators](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/).
Retrieved: 2026-04-30

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
    edit "auditor"
        set accprofile "super_admin_readonly"
        set password ENC fakeAuditorHashGGGGGGGGGGGGGG==
    next
end
```

Built-in accprofiles: `super_admin` (full read/write),
`super_admin_readonly` (full read-only), `prof_admin` (operator-
class).  Custom profiles via `config system accprofile`.

- **`set password ENC <opaque-base64>`** — internal-key encryption.
- **`set trusthost1` ... `set trusthost10`** — IP-based access
  controls; not modelled in canonical.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

Two-role model (`manager` / `operator`):

```
password manager user-name "admin" sha1 "fa1cefa1cefa1cefa1cefa1cefa1cefa1cefa1ce"
password manager user-name "auditor" sha1 "0bce0bce0bce0bce0bce0bce0bce0bce0bce0bce"
password operator user-name "netops" sha1 "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
```

See [`../aruba_aoss_to_fortigate_cli/local_users.md`](../aruba_aoss_to_fortigate_cli/local_users.md)
for full Aruba specifics.

## Cross-vendor mapping (FortiGate -> Aruba)

Canonical surface:

```
class CanonicalLocalUser(BaseModel):
    name: str
    privilege_level: int = 1
    hashed_password: str = ""
    role: str = ""
```

- **name** — `good`.  Direct preservation.
- **role / privilege_level** — `lossy`.  FortiGate accprofile
  strings collapse to Aruba's two-role model:
    - `super_admin` -> `manager` (all-access).
    - `super_admin_readonly` -> `operator` (read-only collapses
      to read-mostly; semantic shift).
    - `prof_admin` -> `operator`.
    - Custom accprofiles -> `operator` (granularity lost).
- **hashed_password** — `lossy`.  FortiOS `ENC <opaque-base64>`
  is FortiGate-only; Aruba accepts plaintext / sha1-hex / bcrypt
  but not the FortiOS form.  Cross-vendor migration of admin
  accounts requires re-setting passwords on the target device.
- **trusthost rules (`set trusthost1` ...)** — `unsupported`.
  Not modelled in canonical; drop entirely on parse.  Aruba target
  has no equivalent IP-based access-restriction primitive in the
  user record (operators may emulate via management-VLAN ACLs).

Disposition: **lossy**.  Reason: hash-format incompatibility (re-
keying required) + RBAC collapse from named-accprofile-string to
two-role model.
