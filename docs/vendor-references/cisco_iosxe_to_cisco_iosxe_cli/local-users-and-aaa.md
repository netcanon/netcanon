# Local users + AAA — NETCONF source rendered to IOS-XE CLI

For full bidirectional content (CLI form, openconfig-system AAA
form, hash-format families) see the sibling file
`../cisco_iosxe_cli_to_cisco_iosxe/local-users-and-aaa.md`.

## Direction-specific disposition

The OpenConfig NETCONF codec does not parse AAA XML at all.  Its
parse path walks `<interfaces>` only.

| Canonical field | NETCONF -> CLI |
|---|---|
| `local_users[].name` | not_applicable — parser never populates |
| `local_users[].privilege_level` | not_applicable |
| `local_users[].hashed_password` | not_applicable |
| `local_users[].role` | not_applicable |
| `radius_servers` | not_applicable |

Once wired, the same-vendor `good` story is particularly clean here:

* `hashed_password` round-trips verbatim because both sides consume
  the same Cisco hash family (`$1$` MD5-crypt, `$8$` PBKDF2-SHA256,
  `$9$` scrypt).  Unlike cross-vendor pairs where Cisco type-9
  scrypt is incompatible with Arista or Juniper hash formats, here
  the hash bytes are byte-identical on parse and render.
* `radius_servers[].key` (the encrypted shared-secret ciphertext,
  e.g. `key 7 ENC...`) round-trips verbatim same-vendor-same-engine
  — the type-7 password obfuscation key is a constant (the same
  XOR pad on every IOS-XE device), and even Cisco's "type 6" AES-
  encrypted form survives because the master-key is derived from
  the device's own engineID which doesn't change cross-format on
  the same device.
* `privilege_level` <-> `role` mapping is platform-specific
  (privilege 15 -> admin role, etc.) but stable same-vendor.

This will be one of the highest-confidence wire-up wins for this
codec pair — same-vendor hash/secret continuity is what cross-vendor
audits flag as fundamentally broken, and here it's free.
