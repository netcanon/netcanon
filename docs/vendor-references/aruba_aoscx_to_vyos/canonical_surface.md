# AOS-CX → VyOS: measured canonical surface

Cached measurement backing
`tests/fixtures/cross_vendor_expectations/aruba_aoscx__vyos.yaml`.

**Source of every number here:** a full `tools/run_full_mesh.py` pass over the
committed corpus, reconciled with `tools/run_phase4_reconciliation.py`. Per-key
dispositions were resolved through the audit's own `actual_disposition()` rather
than inferred from the drift shape, so this file and the ratchet agree by
construction. Every loss recorded was additionally re-derived by hand —
`aruba_aoscx.parse()` → `vyos.render()` → `vyos.parse()` on each of the 7
fixtures — so no claim below rests on the drift shape alone.

- Fixture cells: **7** (6 real AOS-CX captures + the AOS-CX kitchen sink)
- Render errors: **0** · re-parse errors: **0**
- Retrieved: 2026-08-25

> **No device-vendor documentation was consulted for this file.** Everything
> below is derived from in-repo artefacts: the two codecs' `CapabilityMatrix`
> declarations, the measured mesh run, hand round-trips of the committed
> fixtures, and read-only inspection of the vyos codec's render/parse sources.
> Where a disposition rests on a declaration rather than an observed round-trip,
> the YAML says so explicitly.

## Device-class framing — there is no switch in VyOS

`aruba_aoscx` in this corpus is a **campus / DC access-aggregation switch**:
`1/1/N` port names, a VLAN database with SVIs, `lag N` link aggregations,
VARP-style active-gateway addressing, and a chassis-wide anycast gateway MAC.
`vyos` is a **Linux software router / firewall appliance**.

That asymmetry is the whole story of this pair. VyOS has no VLAN database, no
`switchport` mode, no VARP, and no LACP bundle it can name from an AOS-CX LAG.
It does have interfaces, addresses, VRFs, static routes, SNMP and login users.

So the pair splits cleanly:

| plane | outcome |
|---|---|
| routed edge — interface identity, addressing, MTU, admin state, description, VRF binding, static routes | **migrates intact** |
| management plane — hostname, SNMP scalars and v3 users, user identity + stored secret | **migrates intact** |
| switching plane — VLAN database, port membership, LAGs, anycast/VARP gateway | **does not migrate at all** |

## The structural finding — and it is NOT the interface list

Anyone arriving here from `aruba_aoscx_to_arista_eos/canonical_surface.md`
should read this before assuming the same shape. There, the dominant loss was
the interface inventory shrinking 9 → 5, which dragged every `interfaces[].*`
sub-field into `lossy`.

**Here the interface inventory is fully preserved.**

| measurement | value |
|---|---|
| source interface records, all 7 cells | **157** |
| records after parse → render → re-parse | **157** |
| cells where the interface name set differs | **0** |

`1/1/1`, `mgmt`, `loopback 0`, `lag 1` and `vlan 101` all come back with their
names byte-identical. The render re-orders interfaces into VyOS commit order
(loopback, then ethernet, then bonding), and the audit's own per-sub-field
comparison records **zero** name drift on 7 of 7 cells.

The structural loss on this pair lands on a different list: **`vlans`**. All
**30** VLAN records across the 7 cells become **0**. That single loss is claimed
once, at `vlans[].id`; the five sibling `vlans[].*` keys are recorded `good`
precisely because they carry no independent signal — see
[Where the VLAN data actually goes](#where-the-vlan-data-actually-goes).

## Per-field measurement (7 cells)

| field | preserved | drifted | trivially empty |
|---|---|---|---|
| hostname | 7 | 0 | 0 |
| interfaces[].name / description / enabled / mtu | 7 | 0 | 0 |
| interfaces[].ipv6_addresses | 2 | 0 | 5 |
| interfaces[].ipv4_addresses | 2 | 5 | 0 |
| interfaces[].interface_type | 0 | 7 | 0 |
| interfaces[].lag_member_of | 0 | 7 | 0 |
| vlans[].* | 0 | 7 | 0 |
| static_routes | 2 | 0 | 5 |
| snmp.* (all five keys) | 4 | 0 | 3 |
| lags | 0 | 7 | 0 |
| local_users[].name / hashed_password | 6 | 0 | 1 |
| local_users[].role | 0 | 6 | 1 |
| vxlan_vnis[].vni | 3 | 0 | 4 |
| vxlan_vnis[].vlan_id | 2 | 1 | 4 |
| routing_instances[].name | 3 | 0 | 4 |
| anycast_gateway_mac | 0 | 5 | 2 |

Fields trivially empty on all 7 cells: `domain`, `dns_servers`, `ntp_servers`,
`timezone`, `syslog_servers`, `interfaces[].vrrp_groups`, `dhcp_servers`,
`radius_servers`, `vxlan_vnis[].mcast_group`, `evpn_type5_routes`,
`routing_instances[].description`, `raw_sections`, `apply_groups`,
`group_content`.

### Per-record detail behind the interface drift

Measured across all 157 records, not sampled from one cell:

| sub-field | records affected | of populated | shape |
|---|---|---|---|
| `interface_type` | 157 | 157 | value → empty string |
| `lag_member_of` | 44 | 44 | value → null |
| `ipv4_addresses` | 15 | 41 | `virtual_gateway_address` → empty; ip + prefix intact |
| `switchport_mode` | 64 | 64 | value → null |
| `trunk_native_vlan` | 34 | 34 | value → null |
| `access_vlan` | 30 | 30 | value → null |
| `trunk_allowed_vlans` | 23 | 23 | list → empty |
| `description` | 0 | 66 | — |
| `enabled` | 0 | 157 | — (19 shut ports, all still shut) |
| `mtu` | 0 | 50 | — |
| `ipv6_addresses` | 0 | 2 | — |

`interface_type` breaks down uniformly by type: **95** `ianaift:ethernetCsmacd`,
**34** `ianaift:ieee8023adLag`, **18** `ianaift:l3ipvlan` and **10**
`ianaift:softwareLoopback` — every one drops. Unlike the EOS pairs, not even the
loopbacks survive. The vyos matrix states why: the codec re-derives the IANA
type from the *name shape* (`ethN` → ethernetCsmacd, `lo`/`dumN` →
softwareLoopback, `bondN` → ieee8023adLag). No AOS-CX name matches any of those
shapes, so nothing is recovered. Both matrices already declare
`/interfaces/interface/config/type` lossy.

The four campus-L2 sub-fields (`switchport_mode`, `access_vlan`,
`trunk_allowed_vlans`, `trunk_native_vlan`) are **one mechanism with the VLAN
drop**, not four extra findings — vyos declares all four unsupported at the
exact path. They are listed here for completeness; none of them is a key in the
expectation YAML, and none is cited as evidence for any other key.

## Source-side gaps vs target-side drops

`aruba_aoscx` declares these **unsupported at the exact path**, so as a *source*
it never emits them and there is nothing for VyOS to lose:

`/system/domain` · `/system/dns-server` · `/system/ntp-server` ·
`/routing-instances/instance/description` · `/snmp/trap-host`

The first three are recorded `not_applicable`, and the operational note matters:
**vyos declares all three SUPPORTED** (`/system/domain`, `/system/dns-server`,
`/system/ntp-server`). Re-authoring domain, resolvers and NTP on the VyOS side
will stick — the migration simply never carried them off the AOS-CX box.
`/routing-instances/instance/description` is the same shape, and is recorded
`not_applicable` for the same reason.

`/snmp/trap-host` is the odd one out and the YAML says so on the key: AOS-CX
declares it unsupported so no cell populates it, *and* vyos declares no path for
it either way, so `snmp.trap_hosts` is an unexercised cell rather than a
demonstrated success. It is recorded `good` — zero drift on 4 populated cells —
with that caveat stated in the note rather than implied.

These are **symmetric** gaps — both matrices declare them unsupported — and are
recorded `unsupported` rather than `not_applicable`:

`/system/timezone` · `/system/syslog-server` · `/dhcp-servers/pool` ·
`/radius-servers/server/host` · `/radius-servers/server/key` ·
`/interfaces/interface/vrrp-groups/group/*`

None is populated on any committed cell, so each is a declared gap rather than
an observed one; the YAML says so per key.

## The five findings worth carrying forward

### 1. The VLAN database is a total concept drop

**30** VLAN records across all 7 cells become **0**. This is not a thin dot1q
registry — the records carry real campus data: names (`PROD-WEB`, `PROD-DB`,
`CORE-ROUTING`, `NMN`, `HMN`, `CMN`, `USERS`, `VOICE`), descriptions
(`Server VLAN`, `Black hole VLAN 2701`, `Out-of-band management`), SVI
addressing, and untagged/tagged port membership lists.

`vyos` declares `/vlans/vlan/id` **unsupported** and states the cause plainly:
VyOS has no top-level VLAN database; 802.1Q VLANs are modelled as `vif <vid>`
sub-interfaces rendered as `ethN.<vid>` interface records. AOS-CX VLAN records
are not `ethN.<vid>` sub-interfaces, so nothing converts.

Recorded `unsupported`, not `lossy`: a vanished record is not lossy (#436), and
`lossy` — which warns but stays compatible — would badly understate losing every
VLAN on a campus switch.

#### Where the VLAN data actually goes

The addressing is **not** lost, and this is the one thing to get right before
reading the five `good` sibling keys as optimism:

| measurement | value |
|---|---|
| VLAN records, all 7 cells | 30 |
| of those, carrying an SVI IPv4 address | 18 |
| of those 18, having a matching `vlan <N>` **interface** record | 18 |
| whose address survives on the target interface record | **18** |

The AOS-CX parser mounts an SVI's L3 on *both* the VLAN record and an interface
record named `vlan <N>`. The interface record round-trips (it is part of the
157/157), so every SVI address lands on the target as
`interfaces ethernet vlan <N> { address <ip>/<plen> }`. What is gone is the
VLAN *object* — its id, name, description and port membership — plus the 12
pure-L2 VLANs that have no SVI at all (ids `1`, `10`, `11`, `30`, `2701`,
`2707`).

That is why `vlans[].name`, `vlans[].ipv4_addresses`, `vlans[].untagged_ports`,
`vlans[].tagged_ports` and `vlans[].description` are recorded **`good`**: the
list-level disappearance is one loss, it is claimed once at `vlans[].id`, and a
second claim on a sibling key would double-count the same drop while being
impossible to evidence independently. Correlated drift is not independent
evidence.

Rebuild the VLANs on the target as `vif` sub-interfaces and a bridge; the SVI
addresses are already there.

### 2. LAGs are dropped by a name-shape mismatch, and the matrix does not warn

**34** LAG records across all 7 cells become **0**, and the rendered VyOS config
contains **no `bonding` block on any cell**. All **44** interface records with a
`lag_member_of` value come back null, while the member ports themselves survive
— the dangerous shape, because the ports come up standalone rather than bundled.

This one is worth stating mechanically, because a bare `lags` drift on a VyOS
target is usually a naming artifact rather than a loss. It is not, here. In
`netcanon/migration/codecs/vyos/render.py`, `_vyos_type_and_name()` maps a
canonical interface name to its VyOS block type: `lo` → `loopback`,
`^dum\d+$` → `dummy`, `^bond\d+$` → `bonding`, and **anything else** →
`ethernet <name>`. `_bond_extra()` — which emits the `mode 802.3ad` line and the
`member { interface … }` list — is called **only** when the block type is
`bonding`. AOS-CX LAGs are named `lag 1`, `lag 256`; none matches `^bond\d+$`.
Each therefore renders as `ethernet lag 1 { }`, carrying its description and
addressing but neither its mode nor its members, and re-parses as a plain
interface.

Both `lags` and `interfaces[].lag_member_of` are recorded `unsupported` (#436).
**They are one mechanism, not two independent findings.** Neither is cited as
evidence for the other; each is recorded where it is measured.

Standing observation, left for a codec change rather than fixed here: the vyos
matrix declares `/lags/lag/name` and `/lags/lag/members` **supported** and
`/lags/lag/mode` merely lossy, while dropping 34 of 34 LAGs on this pair. The
declaration is honest for a same-vendor round-trip, where LAGs are already named
`bondN` — it is silently wrong for any source whose LAG names have another
shape. That is a matrix under-declaration, not a pair-specific fact.

### 3. The anycast / VARP gateway surface vanishes in two places at once

`anycast_gateway_mac` is populated on **5 of 7** cells and returns empty on all
5. `vyos` declares `/anycast-gateway-mac` unsupported: VyOS has no VARP /
distributed-anycast-gateway grammar. Recorded `unsupported` — the scalar
vanishes, it does not degrade.

The same absence shows up a second time, per-address:
`interfaces[].ipv4_addresses` drifts on **15 of 41** populated records, and on
every one of those 15 the `ip` and `prefix_length` are **identical** — what
empties is `virtual_gateway_address` (e.g. an SVI keeping `10.12.101.2/24` while
its shared gateway `10.12.101.1` disappears). Zero records lose an address.
`vyos` declares `/interfaces/interface/ipv4/address/virtual-gateway-address`
unsupported for exactly this reason.

`interfaces[].ipv4_addresses` is recorded **`lossy`**, not `unsupported`,
deliberately: no address record vanishes and the target models interface
addressing perfectly well. Calling the key `unsupported` would tell a migration
report that VyOS cannot hold interface IPv4 addressing, which is flatly false
and would be the most damaging possible error on this pair.

`lossy` is not "harmless" here, though: on the 15 affected SVIs the *hosts'*
default gateway is what disappeared. Re-create first-hop redundancy on the VyOS
side (VRRP is also unsupported by this codec — see the matrix) before cutover.

This and `anycast_gateway_mac` are **one mechanism**, measured in two places.
Neither corroborates the other.

### 4. Every migrated user arrives as an administrator

7 user records across 6 cells. Names: **7 of 7 preserved**. Stored secret:
**7 of 7 byte-identical**. Role: **7 of 7 drifted**.

| source | target |
|---|---|
| `administrators` (6 records) | `admin` |
| `operators` (1 record, `netops` on `kitchen_sink.cfg`) | `admin` |

The mechanism is not a mapping table, it is a constant. `_render_login()` in
`netcanon/migration/codecs/vyos/render.py` emits `user <name> { authentication {
encrypted-password <hash> } }` and **no role or level at all** — VyOS's
`system login user` grammar has none in the common case. On re-parse,
`netcanon/migration/codecs/vyos/parse.py` assigns every login user
`role="admin"` and `privilege_level=15` unconditionally.

The consequence is a **fail-open**: the one non-admin account in the corpus,
`netops`, goes in with role `operators` / privilege level 1 and comes back with
role `admin` / privilege level 15. Measured on exactly 1 record on 1 cell — the
other 6 were already administrators, so only their role *string* changes.

`local_users[].role` is recorded `lossy`, not `unsupported`: the record survives
with its name and its secret, and only the value collapses.

Worth flagging as a second standing observation: **neither** matrix declares
`/local-users/user/role` as anything but supported, while it drifts on 7 of 7
records. The adjacent `/local-users/user/privilege-level` *is* declared lossy on
both sides, with vyos's reason spelling out the same collapse. The role path is
under-declared; that belongs to a codec change, not to this file.

Before cutover, diff the source account list against the render and re-apply
least privilege by hand. A read-only operator silently promoted to admin is a
worse migration outcome than an account that fails to arrive.

### 5. The VNI→VLAN binding is re-synthesised, not carried

4 VNI records across 3 cells. `vni` is preserved on **4 of 4**. `vlan_id` drifts
on **2 of 4** (both on `kitchen_sink.cfg`): `10 → 1822` and `20 → 1832`.

`netcanon/migration/codecs/vyos/parse.py` computes `vlan_id=((vni - 1) % 4094) +
1`, because the VyOS `vxlan vxlanN` netdev carries a VNI but no VLAN — the L2
binding lives on a separate bridge, and the canonical field is required. The
render confirms it: `vxlan vxlan0 { vni 10010; source-address 10.255.0.1; port
4789 }` with no VLAN anywhere.

The two records that *did* survive (VNI 11 → VLAN 11, on the two `arch3` cells)
survived by **coincidence**: for any VNI ≤ 4094 the derivation is the identity.
Read that as "preserved where the numbers happened to agree", not as
"preserved". `vyos` already declares `/vxlan-vnis/vlan-id` lossy.

Recorded `lossy`: the VNI record survives, the binding value is replaced. It is
a silent replacement rather than an obvious gap, which is what makes it worth
checking by hand on every VNI above 4094.

## The VyOS quote rewrite — checked, and not exercised here

`_q()` in the vyos render replaces embedded `"` with `'` before quoting a value,
because VyOS rejects embedded double-quotes in value strings even when escaped.
A description can therefore come back with altered punctuation while its text
survives.

**That hazard does not fire on this pair.** Measured: **66** populated interface
descriptions across the 7 cells, **0** drifted, and **0** of them contain a
double-quote character. `interfaces[].description` is `good` on the measurement,
not on the absence of a check — but a future AOS-CX fixture with a quoted
description would exercise this, and the loss would be punctuation, not content.

## Preservation is not target-syntax validity

One caveat an operator should not discover at cutover. The render emits every
canonical interface name verbatim under an `ethernet` node, producing blocks
such as `ethernet 1/1/1 { … }`, `ethernet lag 1 { … }` and
`ethernet vlan 101 { … }`. Those names carry spaces and slashes; VyOS ethernet
interfaces are `eth0`, `eth1`, and so on.

netcanon's fidelity harness scores **canonical preservation**, not whether the
target device would accept the rendered config. The 157/157 interface figure
above is a preservation figure. Every `good` in the expectation YAML means "the
canonical value survived the round-trip", and on this pair a name-translation
step is required before the output is loadable. That is a property of the whole
pair, stated once here rather than repeated on 21 keys.

## Credential material

No secret value is reproduced in this file or in the expectation YAML — only
shape. The AOS-CX source form is `user <name> group <role> password ciphertext
<blob>`; the stored secret is a vendor ciphertext blob, base64-alphabet, with no
UNIX crypt scheme marker (`$1$` / `$5$` / `$6$` / `$2y$`) at all. Observed blob
lengths across the corpus range from 5 to 184 characters.

The VyOS render places that blob verbatim into `system login user <name>
authentication encrypted-password`, and it re-parses byte-identical — which is
why `local_users[].hashed_password` is `good`. **Preserved is not usable.** That
slot holds a UNIX crypt string on VyOS, and an AOS-CX ciphertext blob is not
one. Treat every migrated account as having no working credential and set
passwords on the target before cutover.

The SNMP v3 USM material behaves the same way: the auth and privacy passphrases
round-trip verbatim on the 2 cells that carry a v3 user (the committed values
are sanitised placeholders). Both matrices nonetheless declare
`/snmp/v3-user/auth-passphrase`, `/priv-passphrase`, `/auth-protocol`,
`/priv-protocol` and `/engine-id` lossy, and vyos's stated reasons include a
genuine cryptographic downgrade — `auth type` renders only `md5`/`sha`, so a
SHA-256/384/512 source collapses to SHA-1, and AES-192/256 collapses to bare
`aes`. No committed cell exercises a strong algorithm, so that caveat is
declared, not observed. Re-key SNMPv3 on the target regardless.
