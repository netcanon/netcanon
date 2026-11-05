# Local users + hash formats: Aruba AOS-S versus MikroTik RouterOS

<!-- an-account-with-no-password -->
> **Update 2026-11-04 — what each direction writes for an account it cannot carry.**  AOS-S to RouterOS: an AOS-S SHA-1 secret is one RouterOS cannot take, and since 2026-10-20 a refused secret drops the whole account: the render writes `# user "<name>" -- review: sha1 hash from source vendor cannot be re-used on RouterOS; reset this user password manually` IN PLACE of it, and no `comment=` carries the source hash.  Measured: `local_users` in/out over the 3 cells that populate users is **4 / 1** (3 refused SHA-1 secrets; the account that arrives holds a plaintext password in the source).  RouterOS to AOS-S (the inverse): a RouterOS export holds no passwords, and since #605 the AOS-S render writes no `password manager user-name "<name>" sha1 ""` line for such an account but a review comment in its place, `; password manager user-name "<name>" -- review: no password for this account was read from the source; set it on the switch with password manager user-name "<name>", which asks for the password` for a manager and `; password operator user-name "<name>" -- review: no password for this account was read from the source; set the manager password on the switch first (an operator password alone gives manager access on AOS-S), then this one with password operator user-name "<name>"` for an operator, with one job warning naming each.  Measured on `mikrotik_routeros__aruba_aoss`: 3 such accounts on 1 cell (the synthetic kitchen sink), `local_users` in/out **3 / 0**.  Any statement below that the source hash is carried in a `comment=` field, or that the AOS-S render writes an empty `sha1 ""` line, describes an earlier render.  Current dispositions are in `tests/fixtures/cross_vendor_expectations/aruba_aoss__mikrotik_routeros.yaml` and `tests/fixtures/cross_vendor_expectations/mikrotik_routeros__aruba_aoss.yaml`.

## Aruba AOS-S

AOS-S has two kinds of local account (HPE Access Security Guide,
AOS-S 16.x).

**The manager account and the operator account**, one of each.  A
line sets the account of its role and names it; a second line of a
role re-points the same account, so the switch keeps the last:

```
password manager user-name "admin" sha1 "<40 hex digits>"
password operator user-name "noc" sha1 "<40 hex digits>"
```

`user-name` may be left out (the names are then `manager` and
`operator`), and a terminal can wrap the quoted hash onto the next
line.  Without `include-credentials` the switch prints neither name
nor hash: a bare `password manager` or `password operator` says only
that the role has a password.  The forms the switch takes are
`plaintext`, `sha1` and `sha256`; there is no bcrypt form, and a
`plaintext` password is never printed, the switch storing a hash.

**Local users** beside them, up to 100, each in an authorization group
and set from the CLI:

```
aaa authentication local-user "admin2" group "Level-15" password sha1 "<40 hex digits>"
aaa authentication local-user "admin2" group "Level-15"
```

(the second as the switch prints it without `include-credentials`).
The switch's own groups `Level-0` to `Level-15` stand for a level's
rights: `Level-15` has the manager's, `Level-1` the operator's.  What
any other group allows is in its `aaa authorization group` rules.

What the parser reads (since 2026-11-04): the last line of each role,
as the switch does, and an earlier one in a row of
`dropped_tier3_sections`; a bare marker as an account of the role's
default name that holds no secret, which every target writes as a
review comment in place of an account; and each local user, at the
privilege level of its `Level-N` group, or at 1 in any other group
(said in a row), with no `role`.  The manager is privilege 15, the
operator 1, and the two come first in the tree.  What the sections
below say of a bcrypt AOS-S form, or of a hash carried verbatim onto
another vendor, describes an earlier reading: a hash the target cannot
take is a review comment in place of the account, and the current
dispositions are in the pair's expectation YAML under
`tests/fixtures/cross_vendor_expectations/`.

## MikroTik RouterOS

Source: [User — RouterOS](https://help.mikrotik.com/docs/spaces/ROS/pages/8978504/User)
Retrieved: 2026-04-30

```
/user add name=admin group=full
/user add name=operator group=write
/user add name=auditor group=read
```

RouterOS uses `/user add name=X group=Z password=Y` with predefined
groups `full` / `write` / `read` (operators can create custom
groups via `/user group add` with policy lists drawn from the
RouterOS RBAC primitives `local`, `telnet`, `ssh`, `read`, `write`,
`policy`, `winbox`, `password`, `web`, `api`, `rest-api`, `romon`).

RouterOS `/export` by default **omits the password** (treated as
sensitive).  Operators must run `/export show-sensitive` to include
the password line, and even then RouterOS does not surface a
vendor-stable hash format identifier — the password renders as the
operator-supplied plaintext or as a vendor-private blob.  This is
the "RouterOS does not surface hashed passwords in /export"
limitation that makes RouterOS the source-side of every cross-vendor
local-user migration lossy on the password material.

## Cross-vendor mapping

The canonical surface is

```
CanonicalLocalUser(name, privilege_level: int, hashed_password: str,
                   role: str)
```

### Role / privilege mapping

Aruba's two-role model (manager / operator) maps to RouterOS's
named groups (full / write / read):

- Aruba `manager` -> RouterOS `full`
- Aruba `operator` -> RouterOS `read`

The intermediate RouterOS `write` group has no Aruba equivalent
(Aruba is strictly two-role); inverse direction renders RouterOS
`write` -> Aruba `manager` with a banner.

The numeric `privilege_level` field on canonical is set to 15
(manager) or 1 (operator) by the aruba_aoss codec on parse so the
cross-vendor surface to Cisco-style targets remains stable; on the
RouterOS render path the privilege number is ignored in favour of
the role-derived group name.

### Password hash incompatibility

Aruba's SHA-1 hex / bcrypt / plaintext forms are NOT consumed by
RouterOS, and RouterOS's vendor-private password format is NOT
consumed by Aruba.  Cross-vendor migration of user accounts
**always requires re-setting passwords** on the target device.

The codec passes the source-side hash through verbatim into a
`comment=` field on the rendered RouterOS user line so the operator
has the source-side hash visible during re-key, but neither vendor
will authenticate against the other's hash blob.

In the inverse direction (RouterOS source -> Aruba target), the
canonical `hashed_password` arrives empty because RouterOS does
not surface the hash in `/export`.  Aruba render emits the
`password manager user-name "<name>" sha1 ""` form which Aruba
will accept syntactically but treats as a no-password account
(login disabled until the operator sets a password).

### Disposition

| Field | Disposition |
|---|---|
| `local_users[].name` | good |
| `local_users[].privilege_level` | lossy (numeric -> named-group) |
| `local_users[].role` | lossy (manager/operator <-> full/read; intermediate group on RouterOS has no Aruba equivalent) |
| `local_users[].hashed_password` | lossy (cross-vendor hash format incompatibility; re-key required) |
