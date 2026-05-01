# Local users + admin profiles: FortiGate FortiOS versus Cisco IOS-XE

Reverse-direction sibling of
[`../cisco_iosxe_cli_to_fortigate_cli/local_users.md`](../cisco_iosxe_cli_to_fortigate_cli/local_users.md).
Source URLs unchanged.

## FortiGate FortiOS CLI

Source: [Fortinet FortiGate / FortiOS Administration Guide — System administrators](https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide/) — `config system admin`.
Retrieved: 2026-04-30

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

## Cisco IOS-XE

Source: Cisco IOS XE Security Command Reference — `username` command.

```
username admin privilege 15 secret 9 $9$ABCDEFGH$abcdef0123...
username noc privilege 5 secret 5 $1$abc$xyzdef...
```

## Cross-vendor mapping (FortiGate -> Cisco)

Canonical surface (same as forward direction):

```
class CanonicalLocalUser(BaseModel):
    name: str
    privilege_level: int = 1
    hashed_password: str = ""
    role: str = ""
```

- **name** — `good`.  Direct preservation.
- **privilege_level** — `lossy`.  FortiGate parse maps
  `super_admin` accprofile to `15` and other profiles to `1`
  (see `parse._apply_system_admin`).  Cross-vendor render to
  Cisco emits `privilege 15` for admins and `privilege 1` for
  others, dropping the granular per-profile detail (Cisco's
  privilege levels 2-14 are uncommon but the canonical model
  has no way to express FortiOS's `prof_admin` / `prof_voip` /
  custom-named profiles).
- **hashed_password** — `lossy`.  Hash formats are NOT cross-
  compatible.  FortiOS `ENC <base64>` is FortiOS-proprietary and
  Cisco does not accept it; Cisco's `$9$` / `$8$` / `$1$` are not
  accepted by FortiOS.  Both codecs preserve the opaque hash
  verbatim under canonical `hashed_password`; cross-vendor
  migration of admin accounts requires re-setting passwords on
  the target device.
- **role** — `lossy`.  FortiGate's accprofile string lands on
  canonical `role`; Cisco render does not emit it (Cisco uses
  `privilege` numeric levels, not named roles).

Disposition: **lossy**.  Reason: hash formats are not cross-
compatible (FortiOS `ENC <base64>` versus Cisco `$9$` / `$8$` /
`$1$`); RBAC representation collapses FortiOS's named accprofiles
to Cisco's numeric privilege levels.
