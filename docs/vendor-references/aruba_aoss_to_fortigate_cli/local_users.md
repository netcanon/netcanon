# Local users + admin profiles: Aruba AOS-S versus FortiGate FortiOS

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
