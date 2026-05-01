# Local users + hash formats: MikroTik RouterOS versus Cisco IOS-XE

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)

Retrieved: 2026-04-30

```
/user
add name=admin group=full password=S3cretPass!
add name=readonly group=read password=R3adOnlyPass!
add name=monitor group=read address=10.0.0.0/24
```

Predefined groups (cannot be deleted): `full`, `write`, `read`.
Custom groups via `/user group add name=<name> policy=<list>`.

`/export` of the user table redacts the password by default; `/export
show-sensitive` includes it.  RouterOS stores its passwords in a
private, vendor-specific format that is not exposed in the
running-config (no Linux-crypt-style hash blob in `/export`).

## Cisco IOS-XE

Source: Cisco IOS XE Security Configuration Guide.

```
username admin privilege 15 secret 9 $9$abcdef$ghijklmnop...
username readonly privilege 1 secret 5 $1$mERr$xyz...
username monitor privilege 1 secret 8 $8$ABC...$DEF...
```

Cisco's secret types:

- type 5 — MD5-crypt (`$1$...`)
- type 7 — Cisco-proprietary obfuscation (reversible; deprecated)
- type 8 — PBKDF2-SHA256
- type 9 — scrypt

## Cross-vendor mapping

The canonical surface is

```
CanonicalLocalUser(name, privilege_level, hashed_password, role)
```

### MikroTik -> Cisco direction

Each field's mapping:

- **name** — direct string copy.
- **group** -> **role + privilege_level**: RouterOS's
  `full`/`write`/`read` groups map to Cisco privilege:
    - `full` -> privilege 15
    - `write` -> privilege 7 (operator-curated; no canonical
      mapping table)
    - `read` -> privilege 1
  Custom RouterOS groups have no Cisco numeric equivalent;
  canonical preserves the group name in `role`, render emits a
  banner for review.
- **password / hashed_password**: this is the structural blocker.
  RouterOS does not expose a hashed-password blob in `/export`,
  so the canonical model receives an empty string.  Cisco
  render therefore emits `username X privilege Y` with NO
  `secret` clause — the operator must set the password on the
  target device by hand.

### Disposition

| Field | Disposition (MikroTik -> Cisco) |
|---|---|
| `local_users[].name` | good |
| `local_users[].privilege_level` | lossy (group -> privilege mapping is operator-curated for non-default groups) |
| `local_users[].role` | lossy (custom groups carry, no numeric privilege mapping) |
| `local_users[].hashed_password` | lossy (RouterOS does not export hashes; Cisco render omits the secret clause) |
