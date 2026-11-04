# Local users + hash formats: Arista EOS versus Aruba AOS-S

## Arista EOS

Source: [Arista EOS — User Security](https://www.arista.com/en/um-eos/eos-user-security)
Retrieved: 2026-05-01

Arista EOS uses a **named-RBAC role + hashed-secret** model:

```
username admin privilege 15 role network-admin nopassword
username operator privilege 15 role network-admin secret sha512 $6$fakeSalt$fakeHashSha512AbcDef...
username readonly privilege 1 role network-operator secret 5 $1$fakeSalt$fakeMd5Hash...
```

Hash type codes accepted by `secret`:

- `secret 0 <plain>` — plaintext (rejected on `service password-
  encryption` enabled devices).
- `secret 5 <hash>` — MD5 (`$1$...`).
- `secret sha512 <hash>` — SHA-512 crypt (`$6$...`).
- `secret 7 <hash>` — Cisco-7 reversible (rare on EOS).

Arista carries **both** `privilege <N>` (numeric, 1-15) AND `role
<name>` on a single user record.

## Aruba AOS-S

Source: [Aruba ArubaOS-Switch 16.10 Access Security Guide for 2930F/2930M/3810/5400R](https://www.arubanetworks.com/techdocs/AOS-S/16.10/ASG/2930F-3810-5400/index.htm)
Retrieved: 2026-04-30

AOS-S has a **fixed two-role local-user model**: `manager`
(full admin) and `operator` (read-mostly):

```
password manager user-name "admin" sha1 a1b2c3...
password operator user-name "noc" plaintext "S0meP4ss"
```

AOS-S holds **one** manager and **one** operator account: the
user-name names the account, and a second `password manager` line
re-points the same one (HPE Access Security Guide, AOS-S 16.x).  An
operator password with no manager password gives manager access.
Netcanon writes the first user of each role that AOS-S can take, an
operator only beside a manager, and every other user as a `; ...
-- review:` comment, with a job warning where the reason is AOS-S's
own; further named accounts on a switch are `aaa authentication
local-user` (CLI only; not written).
See [`../../vendors/aruba_aoss.md`](../../vendors/aruba_aoss.md#local-users-one-manager-and-one-operator).

Hash forms accepted:

- `plaintext "<pass>"`
- `sha1 <hex>` (AOS-S-specific salt mechanics)
- `sha256 <hex>`

There is **no numeric privilege level** — the role is named
(manager / operator).  No bcrypt form, and no crypt(3) form (`$1$`,
`$5$`, `$6$`).

## Cross-vendor mapping

The canonical surface is `CanonicalLocalUser(name, privilege_level,
hashed_password, role)`.

Arista -> Aruba round-trip:

- Role mapping policy: Arista `role="network-admin"` (or any
  `privilege >= 15`) -> Aruba `role="manager"`; everything else
  -> Aruba `role="operator"`.  Numeric privilege is dropped on
  the Aruba target (no canonical home for granular Cisco
  1..15 privileges).

Hash compatibility (the hard limit):

- Arista `secret 5 $1$...` (MD5) — Arista-only on the canonical
  layer; Aruba does not accept MD5 for the `password` directive.
- Arista `secret sha512 $6$...` (SHA-512 crypt) — Arista-only;
  Aruba does not accept SHA-512.  This is the most common Arista
  default in modern EOS, so it bites every migration.
- Arista `secret 7 $...` (Cisco-7 reversible) — Cisco/Arista-
  only; Aruba does not accept type-7.
- AOS-S's `sha1` / `sha256` digests are AOS-S-only on the wire.

Cross-vendor migration of user accounts therefore **requires
re-setting passwords on the target device**.  An account whose
secret the target cannot take is a `review:` comment naming it, in
place of the account, in either direction; no secret is quoted.

The Arista kitchen-sink exercises:

```
username admin privilege 15 role network-admin nopassword
username operator privilege 15 role network-admin secret sha512 $6$fakeSalt$fakeHashSha512...
username readonly privilege 1 role network-operator secret 5 $1$fakeSalt$fakeMd5Hash...
```

— none of the three is written on AOS-S: `admin` has no password (a
review comment, with a job warning), and `operator` (SHA-512) and
`readonly` (MD5) hold secrets AOS-S cannot take (a review comment
each).  On the switch, set the manager first, then at most one
operator.

Disposition: **lossy** (hash-format incompatibility on every
modern Arista hash; Cisco-style `privilege` semantic collapses to
Aruba's two-role enum; SHA-512 the dominant case requires
re-keying).
